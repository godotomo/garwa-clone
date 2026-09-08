"""tools/cron_runner.py
Runner jadwal cron untuk Garwa. Membaca tabel `scheduled_tasks` (yang dikelola
tool `schedule_task`/`list_schedules`/`remove_schedule`) dan mengeksekusi aksi
yang sudah waktunya berjalan.

TIDAK ada dependency eksternal: pencocokan ekspresi cron 5-field diimplementasi
sendiri di `_cron_expr` (dipakai juga untuk validasi saat insert).

Keandalan (robustness):
  - Anti-double-run: sebelum eksekusi, task di-"claim" atomik lewat
    `UPDATE ... SET running=1, claimed_at=? WHERE id=? AND running=0`.
    Runner lain (crontab + --forever sekaligus) tidak akan mengeksekusi task
    yang sedang berjalan / baru saja di-claim.
  - Timeout seragam untuk SEMUA aksi (bash, send_email, send_telegram) via
    thread + `join(timeout)`.
  - Audit trail: hasil eksekusi dicatat ke tabel `schedule_runs`.
  - Loop `--forever` disinkronkan ke awal menit (tidak drift).

Cara pakai (dipanggil tiap menit oleh system cron / Termux crond):
    python -m garwa.tools.cron_runner [--once]

Tanpa --once, loop selamanya mengecek tiap 60 detik. Dengan --once, cek sekali
lalu keluar (cocok untuk crontab: `* * * * * python -m garwa.tools.cron_runner --once`).
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

# Impor relatif bekerja baik saat dijalankan sebagai `python -m garwa.tools.cron_runner`
# maupun diimpor langsung.
try:
    from . import _state as state
    from .. import db as dbmod
    from . import comm_tools
    from ._cron_expr import _cron_matches
except ImportError:  # pragma: no cover - fallback saat dijalankan sebagai skrip
    from garwa.tools import _state as state
    from garwa import db as dbmod
    from garwa.tools import comm_tools
    from garwa.tools._cron_expr import _cron_matches

# Batas waktu (detik) per aksi. Bash boleh lebih lama (proses shell), tapi
# tetap dibatasi; email/telegram diturunkan ke nilai aman.
ACTION_TIMEOUTS = {
    "bash": 120,
    "send_email": 60,
    "send_telegram": 60,
}

# Umur claim (detik) sebelum dianggap "kadaluarsa" dan boleh di-claim ulang.
# Ini mencegah task macet selamanya bila runner mati di tengah eksekusi.
CLAIM_STALE_SECONDS = 300

# Retry untuk aksi transien (email/telegram). Bash TIDAK di-retry (bisa
# non-idempotent). Jumlah percobaan maksimum & backoff dasar (dengan jitter).
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0  # detik; dikali attempt + jitter acak

# Batas maksimum menit yang di-catch-up bila runner sempat mati. Mencegah
# banjir eksekusi saat gap besar (mis. runner mati berjam-jam).
MAX_CATCHUP_MINUTES = 60


def _execute_task(task) -> str:
    """Jalankan satu task dan kembalikan string hasil singkat."""
    action = task["action"]
    try:
        payload = json.loads(task["payload"] or "{}")
    except (TypeError, ValueError):
        payload = {}

    if action == "send_email":
        return comm_tools.tool_send_email(
            to=payload.get("to"),
            subject=payload.get("subject", ""),
            body=payload.get("body", ""),
            html=bool(payload.get("html", False)),
        )
    if action == "send_telegram":
        return comm_tools.tool_send_telegram(
            text=payload.get("text", ""),
            chat_id=payload.get("chat_id"),
        )
    if action == "bash":
        cmd = payload.get("command", "")
        if not cmd:
            return "[cron] bash tanpa command."
        # Keamanan: tolak command yang cocok pola berbahaya (sama dengan guard
        # tool bash normal). Karena cron berjalan tanpa konfirmasi user, command
        # berbahaya TIDAK boleh dieksekusi -- ditolak langsung.
        if state._DANGEROUS_BASH_RE.search(cmd):
            return "[cron] bash DITOLAK: command cocok pola berbahaya dan cron tidak punya konfirmasi user."
        try:
            proc = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=120
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            return f"[cron bash] exit={proc.returncode}: {out[:500]}"
        except Exception as e:
            return f"[cron bash] error: {e}"
    return f"[cron] aksi tak dikenal: {action}"


def _run_once_with_timeout(task, timeout: float) -> str:
    """Eksekusi task sekali dalam thread daemon dengan timeout. Return string."""
    box = {}

    def _run():
        try:
            box["result"] = _execute_task(task)
        except Exception as e:  # noqa: BLE001 - jangan biarkan thread mati
            box["result"] = f"[cron] error eksekusi: {e}"

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return f"[cron] timeout setelah {timeout}s untuk aksi `{task['action']}`."
    return box.get("result", "[cron] tanpa hasil.")


def _is_transient_failure(action: str, result: str) -> bool:
    """True bila hasil menandakan kegagalan yang layak di-retry (transien)."""
    if action not in ("send_email", "send_telegram"):
        return False
    return result.startswith("[ERROR") or result.startswith("[cron] error")


def _execute_task_with_timeout(task) -> str:
    """Eksekusi task dengan timeout seragam + retry backoff untuk aksi transien.

    Aksi `send_email`/`send_telegram` yang gagal (transien, mis. gangguan
    jaringan) diulang hingga MAX_RETRIES kali dengan backoff eksponensial +
    jitter. `bash` TIDAK di-retry karena bisa non-idempotent.
    """
    action = task["action"]
    timeout = ACTION_TIMEOUTS.get(action, 60)
    retries = MAX_RETRIES if action in ("send_email", "send_telegram") else 1
    last = _run_once_with_timeout(task, timeout)
    for attempt in range(1, retries):
        if not _is_transient_failure(action, last):
            break
        delay = RETRY_BACKOFF_BASE * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
        time.sleep(delay)
        last = _run_once_with_timeout(task, timeout)
    return last


def _schedule_runs_sql() -> str:
    return """
CREATE TABLE IF NOT EXISTS schedule_runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER NOT NULL,
    name       TEXT NOT NULL,
    action     TEXT NOT NULL,
    started_at REAL NOT NULL,
    finished_at REAL,
    status     TEXT NOT NULL,   -- 'ok' | 'error' | 'timeout'
    result     TEXT
);
CREATE INDEX IF NOT EXISTS idx_schedule_runs_task ON schedule_runs(task_id);
"""


def _ensure_runs_table(db_path: str) -> None:
    with dbmod.connect(db_path) as conn:
        conn.executescript(_schedule_runs_sql())


def _log_run(conn, task_id: int, name: str, action: str,
             started_at: float, status: str, result: str) -> None:
    """Catat hasil eksekusi ke tabel schedule_runs (best-effort).

    Memakai koneksi `conn` yang sama dengan transaksi eksekusi supaya tidak
    terjadi deadlock/lock saat koneksi utama masih memegang transaksi tulis.
    """
    try:
        conn.execute(
            "INSERT INTO schedule_runs (task_id, name, action, started_at, finished_at, status, result) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task_id, name, action, started_at, time.time(), status, result),
        )
    except Exception:  # noqa: BLE001 - logging tidak boleh menggagalkan runner
        pass


def _run_single(conn, r) -> str:
    """Claim + eksekusi satu task (sudah dipastikan due). Return string hasil."""
    # Anti-double-run: claim atomik. Task yang sedang running (running=1) atau
    # baru di-claim (claimed_at segar) di-skip oleh runner lain.
    # Task yang running dengan claim segar di-skip (anti-double-run); task yang
    # claim-nya sudah basi (runner mati di tengah eksekusi) boleh di-claim ulang.
    stale_cutoff = time.time() - CLAIM_STALE_SECONDS
    claimed = conn.execute(
        "UPDATE scheduled_tasks SET running=1, claimed_at=? "
        "WHERE id=? AND (running=0 OR claimed_at < ?)",
        (time.time(), r["id"], stale_cutoff),
    )
    if claimed.rowcount == 0:
        return None  # sedang diproses runner lain / baru di-claim -> skip

    started = time.time()
    res = _execute_task_with_timeout(r)
    status = "ok"
    if res.startswith("[cron] timeout"):
        status = "timeout"
    elif res.startswith("[ERROR") or res.startswith("[cron] error"):
        status = "error"
    # Lepas claim & update last_run. claimed_at di-reset ke NULL supaya task
    # berulang bisa di-claim lagi di siklus berikutnya.
    conn.execute(
        "UPDATE scheduled_tasks SET running=0, claimed_at=NULL, last_run=? WHERE id=?",
        (time.time(), r["id"]),
    )
    _log_run(conn, r["id"], r["name"], r["action"], started, status, res)
    return res


def _missed_slots(schedule_expr: str, last_run: float, now_local: datetime) -> list:
    """Hitung slot menit yang terlewat (due tapi belum dijalankan) sejak `last_run`.

    Iterasi menit demi menit dari `last_run` (dibulatkan ke menit berikutnya)
    sampai `now_local`, lalu cek `_cron_matches`. Return list datetime yang due
    dan belum dijalankan. Dibatasi MAX_CATCHUP_MINUTES menit agar tidak banjir.

    Return [] bila `last_run` null (task belum pernah jalan -> tidak ada yang
    di-catch-up; hanya slot sekarang yang ditangani run_due biasa).
    """
    if not last_run:
        return []
    # Mulai dari menit setelah last_run (menit last_run sudah dijalankan).
    start_dt = datetime.fromtimestamp(last_run, tz=now_local.tzinfo)
    start = start_dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    now_floor = now_local.replace(second=0, microsecond=0)
    if start >= now_floor:
        return []
    slots = []
    cur = start
    steps = 0
    # EXCLUSIVE terhadap now_floor: menit sekarang ditangani run_due secara
    # terpisah, jadi tidak boleh di-catch-up di sini (mencegah duplikasi).
    while cur < now_floor and steps < MAX_CATCHUP_MINUTES:
        try:
            if _cron_matches(schedule_expr, cur):
                slots.append(cur)
        except Exception:
            pass
        cur += timedelta(minutes=1)
        steps += 1
    return slots


def run_due(now: datetime = None) -> list:
    """Eksekusi semua task enabled yang due saat ini. Return list hasil.

    Termasuk catch-up: bila task punya `last_run` lama (runner sempat mati),
    slot menit yang terlewat (due tapi belum dijalankan) ikut dieksekusi,
    dibatasi MAX_CATCHUP_MINUTES menit.
    """
    now = now or datetime.now(timezone.utc)
    now_local = now.astimezone()  # cron dievaluasi di zona lokal mesin
    db_path = getattr(state, "DB_PATH", None) or dbmod.DEFAULT_DB_PATH
    comm_tools._ensure_cron_table(db_path)
    _ensure_runs_table(db_path)
    results = []
    with dbmod.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, name, schedule_expr, action, payload, enabled, last_run "
            "FROM scheduled_tasks WHERE enabled = 1"
        ).fetchall()
        for r in rows:
            # Kumpulkan slot yang perlu dijalankan: slot sekarang (bila due) +
            # slot terlewat (catch-up).
            slots = []
            try:
                if _cron_matches(r["schedule_expr"], now_local):
                    slots.append(now_local)
            except Exception:
                pass
            try:
                slots.extend(_missed_slots(r["schedule_expr"], r["last_run"], now_local))
            except Exception:
                pass
            # Jalankan tiap slot (claim atomik di _run_single mencegah double-run
            # antar-runner; last_run di-update setelah tiap eksekusi).
            for _ in slots:
                res = _run_single(conn, r)
                if res is not None:
                    results.append((r["name"], res))
    return results


def _seconds_until_next_minute() -> float:
    """Detik tersisa sampai awal menit berikutnya (untuk loop --forever)."""
    now = time.time()
    return 60.0 - (now % 60.0)


def main(argv: list = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    once = "--once" in argv
    while True:
        try:
            results = run_due()
            for name, res in results:
                print(f"[{name}] {res}", flush=True)
        except Exception as e:  # noqa: BLE001 - runner tidak boleh mati
            print(f"[cron_runner] error: {e}", flush=True)
        if once:
            break
        # Sinkron ke awal menit supaya tidak drift & tidak melewatkan jendela.
        time.sleep(_seconds_until_next_minute())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
