"""garwa/subagent_status.py
Cetak status sub-agent yang berjalan ke stderr secara LIVE.

Sub-agent Garwa berjalan in-process (thread). Saat proses spawn sedang
berjalan, pengguna TIDAK bisa mengetik slash command (loop induk sedang
sibuk), jadi status dicetak OTOMATIS ke stderr setiap kali sub-agent MULAI
dan SELESAI. Tiap baris memuat: aksi, role, id record, jumlah yang masih
berjalan, durasi, session, dan ringkasan task/error.

Output ke stderr (bukan stdout) supaya:
- tidak mengotori hasil tool (stdout),
- tidak ikut tertangkap isolasi stdout sub-agent (isolasi hanya menangkap
  stdout, bukan stderr).

Nonaktifkan dengan env ``GARWA_SUBAGENT_STATUS=0``.
"""
import os
import sys
import threading
import time

from . import subagent_registry as registry

_LOCK = threading.Lock()
_MAX_TASK = 60
_MAX_ERR = 100


def _enabled() -> bool:
    v = os.environ.get("GARWA_SUBAGENT_STATUS", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _emit(line: str) -> None:
    if not _enabled():
        return
    # Lock supaya baris dari banyak thread tidak saling menyisip.
    with _LOCK:
        try:
            sys.stderr.write(line + "\n")
            sys.stderr.flush()
        except Exception:
            pass


def _short(text, limit: int) -> str:
    text = str(text or "").replace("\n", " ").strip()
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def _fmt_duration(seconds) -> str:
    if seconds is None or seconds < 0:
        return "-"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def _running_count() -> int:
    try:
        return sum(
            1 for r in registry.list_records()
            if r["status"] == registry.STATUS_RUNNING
        )
    except Exception:
        return 0


def notify_start(rec_id: str, role: str, task: str) -> None:
    """Cetak baris 'mulai' untuk satu sub-agent yang baru berjalan."""
    n = _running_count()
    _emit(
        f"[sub-agent] ▶ mulai   {role}  {rec_id}  [{n} berjalan]"
        f"  — {_short(task, _MAX_TASK)}"
    )


def notify_done(rec_id: str, status: str, error: str = None) -> None:
    """Cetak baris 'selesai' untuk sub-agent (sukses/gagal/dibatalkan)."""
    rec = registry.get(rec_id) or {}
    role = rec.get("role", "?")
    started = rec.get("started_at")
    finished = rec.get("finished_at") or time.time()
    dur = _fmt_duration(finished - started) if started else "-"
    sid = rec.get("session_id") or "-"
    mark = {
        registry.STATUS_SUCCESS: "✓ selesai",
        registry.STATUS_ERROR: "✗ gagal  ",
        registry.STATUS_INTERRUPTED: "⊘ batal  ",
    }.get(status, f"? {status}")
    # Hitung ulang setelah status diubah (yang ini sudah tidak running).
    n = _running_count()
    line = f"[sub-agent] {mark} {role}  {rec_id}  {dur}  [{n} berjalan]  {sid}"
    if error:
        line += f"  — {_short(error, _MAX_ERR)}"
    _emit(line)


# ---------------------------------------------------------------------------
# Keepalive batch paralel
# ---------------------------------------------------------------------------
# Masalah nyata: `spawn_agents_parallel` dijalankan SINKRON di loop utama, jadi
# selama batch berjalan terminal tidak menampilkan apa pun setelah header.
# Kalau server mengembalikan 429 concurrent_limit, backoff 30-120 detik membuat
# batch "menggantung" tanpa jejak selama beberapa menit dan pengguna mengira
# proses mati. Keepalive di bawah mencetak progres berkala ke stderr
# (mis. "2/4 selesai, 2 berjalan, 1m05s") sampai batch selesai.
#
# Interval diatur env GARWA_SUBAGENT_KEEPALIVE (detik, default 15; 0 = mati).
_BATCH_LOCK = threading.Lock()
_BATCH = {
    "active": False,
    "total": 0,
    "workers": 0,
    "started": None,
    "done": 0,
    "ok": 0,
    "err": 0,
}
_keepalive_stop = threading.Event()
_keepalive_thread = None


def _keepalive_interval() -> float:
    try:
        return float(os.environ.get("GARWA_SUBAGENT_KEEPALIVE", "15"))
    except (TypeError, ValueError):
        return 15.0


def _keepalive_loop() -> None:
    """Thread daemon: cetak progres batch berkala selagi batch masih aktif."""
    while True:
        iv = _keepalive_interval()
        if iv <= 0:
            return
        if _keepalive_stop.wait(iv):
            return
        with _BATCH_LOCK:
            if not _BATCH["active"]:
                return
            total = _BATCH["total"]
            done = _BATCH["done"]
            ok = _BATCH["ok"]
            err = _BATCH["err"]
            started = _BATCH["started"]
        running = max(total - done, 0)
        dur = _fmt_duration(time.time() - started) if started else "-"
        _emit(
            f"[sub-agent] … progres {done}/{total} selesai "
            f"(✓{ok} ✗{err}), {running} berjalan, {dur} berlalu"
        )


def _ensure_keepalive() -> None:
    """Nyalakan thread keepalive (satu thread saja, dipakai ulang)."""
    global _keepalive_thread
    if _keepalive_interval() <= 0:
        return
    with _BATCH_LOCK:
        if _keepalive_thread is not None and _keepalive_thread.is_alive():
            return
        _keepalive_stop.clear()
        t = threading.Thread(target=_keepalive_loop, daemon=True,
                             name="subagent-keepalive")
        _keepalive_thread = t
    t.start()


def notify_parallel_header(n: int, max_workers: int) -> None:
    """Cetak header saat menjalankan beberapa sub-agent paralel + mulai keepalive."""
    with _BATCH_LOCK:
        _BATCH.update(active=True, total=max(0, int(n or 0)),
                      workers=max(0, int(max_workers or 0)),
                      started=time.time(), done=0, ok=0, err=0)
    _emit(f"[sub-agent] menjalankan {n} task paralel (max_workers={max_workers})")
    _ensure_keepalive()


def notify_batch_progress(ok: bool) -> None:
    """Catat satu task batch selesai + cetak progres ke stderr.

    Dipanggil dari thread utama (saat `as_completed` mengembalikan future),
    jadi tidak perlu lock sendiri selain yang sudah ada di `_BATCH_LOCK`.
    """
    with _BATCH_LOCK:
        if not _BATCH["active"]:
            return
        _BATCH["done"] += 1
        if ok:
            _BATCH["ok"] += 1
        else:
            _BATCH["err"] += 1
        total = _BATCH["total"]
        done = _BATCH["done"]
        n_ok = _BATCH["ok"]
        n_err = _BATCH["err"]
        started = _BATCH["started"]
    dur = _fmt_duration(time.time() - started) if started else "-"
    _emit(
        f"[sub-agent] selesai {done}/{total} task (✓{n_ok} ✗{n_err}) "
        f"— {dur} berlalu, {max(total - done, 0)} masih berjalan"
    )


def notify_batch_done(note: str = "") -> None:
    """Akhiri batch: matikan keepalive lalu cetak ringkasan sekali.

    Aman dipanggil walau batch tidak pernah dimulai (mis. error sebelum
    header) -- dalam kasus itu tidak mencetak apa pun.
    """
    global _keepalive_thread
    with _BATCH_LOCK:
        active = _BATCH["active"]
        total = _BATCH["total"]
        done = _BATCH["done"]
        ok = _BATCH["ok"]
        err = _BATCH["err"]
        started = _BATCH["started"]
        _BATCH["active"] = False
        _keepalive_thread = None
    _keepalive_stop.set()
    if not active:
        return
    dur = _fmt_duration(time.time() - started) if started else "-"
    line = (f"[sub-agent] batch selesai: {done}/{total} task "
            f"(✓{ok} ✗{err}) dalam {dur}")
    if note:
        line += f"  — {_short(note, _MAX_ERR)}"
    _emit(line)
