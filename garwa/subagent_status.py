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


def _running_records() -> list:
    """Semua record sub-agent yang masih berstatus RUNNING (tahan error)."""
    try:
        return [
            r for r in registry.list_records()
            if r["status"] == registry.STATUS_RUNNING
        ]
    except Exception:
        return []


def _running_count() -> int:
    return len(_running_records())


def notify_start(rec_id: str, role: str, task: str) -> None:
    """Cetak baris 'mulai' untuk satu sub-agent yang baru berjalan."""
    n = _running_count()
    _emit(
        f"[sub-agent] ▶ mulai   {role}  {rec_id}  [{n} berjalan]"
        f"  — {_short(task, _MAX_TASK)}"
    )
    # Watchdog: sub-agent TUNGGAL pun bisa menggantung (server LLM macet,
    # retry ber-backoff panjang). Tanpa ini tidak ada satu pun baris status
    # setelah "mulai" sampai sub-agent selesai -- pengguna mengira proses mati.
    _ensure_keepalive()


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
    # Bila ini sub-agent TERAKHIR yang berjalan (dan tidak ada batch aktif),
    # hentikan watchdog supaya tidak mencetak baris kosong setelah selesai.
    if not _any_running():
        _request_keepalive_stop()


# ---------------------------------------------------------------------------
# Keepalive + watchdog stall
# ---------------------------------------------------------------------------
# Masalah nyata: `spawn_agents_parallel` dijalankan SINKRON di loop utama, jadi
# selama batch berjalan terminal tidak menampilkan apa pun setelah header.
# Kalau server mengembalikan 429 concurrent_limit, backoff 30-120 detik membuat
# batch "menggantung" tanpa jejak selama beberapa menit dan pengguna mengira
# proses mati. Keepalive di bawah mencetak progres berkala ke stderr
# (mis. "2/4 selesai, 2 berjalan, 1m05s") sampai batch selesai.
#
# Sejak perbaikan watchdog, thread yang sama juga memantau sub-agent TUNGGAL
# yang tampak MACET (tidak ada kabar sama sekali selama > GARWA_SUBAGENT_STALL
# detik). Sebelumnya satu sub-agent yang menggantung tidak menghasilkan satu
# baris pun setelah "mulai", sehingga pengguna tidak bisa membedakan
# "sedang bekerja" dari "sudah mati".
#
# Interval diatur env GARWA_SUBAGENT_KEEPALIVE (detik, default 15; 0 = mati).
# Ambang stall: env GARWA_SUBAGENT_STALL (detik, default 60; 0 = watchdog mati).
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
# Event stop MILIK GENERASI WATCHDOG YANG SEDANG JALAN (bukan global abadi).
# Setiap kali watchdog baru di-spawn, event ini DIGANTI dengan yang baru.
# Alasan: `notify_done` sub-agent #1 men-set event lama. Kalau event itu dipakai
# bersama, `_ensure_keepalive` berikutnya melihat thread lama masih "alive"
# (sedang unwind) sambil stop-nya sudah ter-set -> early-return, dan sub-agent
# #2 berjalan TANPA watchdog sama sekali selama seluruh durasinya sehingga user
# tidak melihat kabar "masih berjalan"/"MACET" (bug nyata, direproduksi).
_keepalive_stop = threading.Event()
_keepalive_thread = None
# True HANYA selama loop benar-benar berjalan (di-set False di `finally` loop).
# `is_alive()` saja tidak cukup: thread yang sudah keluar dari loop masih
# dilaporkan hidup sesaat, dan pada jendela itu `_ensure_keepalive` bisa
# salah menyimpulkan "watchdog sudah ada".
_keepalive_alive = False
# Nomor generasi watchdog. Naik tiap kali generasi baru dibuat. Dipakai oleh
# loop lama untuk memastikan ia hanya menurunkan `_keepalive_alive` bila dirinya
# MASIH generasi terkini -- kalau sudah ada generasi baru, penurunannya akan
# mematikan flag milik generasi baru secara keliru (bug: watchdog kedua).
_keepalive_gen = 0


def _mark_keepalive_exit(gen: int) -> None:
    """Tandai bahwa loop generasi `gen` sudah berhenti.

    Hanya efek bila `gen` masih generasi terkini; generasi usang yang terlambat
    bangun tidak boleh mengubah status watchdog yang sekarang.
    """
    global _keepalive_alive
    with _BATCH_LOCK:
        if _keepalive_gen == gen:
            _keepalive_alive = False


def _keepalive_interval() -> float:
    try:
        return float(os.environ.get("GARWA_SUBAGENT_KEEPALIVE", "15"))
    except (TypeError, ValueError):
        return 15.0


def _stall_after() -> float:
    """Ambang detik tanpa kabar sebelum status sub-agent disebut 'macet'.

    0 (atau nilai invalid) = watchdog stall dimatikan.
    """
    try:
        v = float(os.environ.get("GARWA_SUBAGENT_STALL", "60"))
    except (TypeError, ValueError):
        return 60.0
    return v if v > 0 else 0.0


def _keepalive_loop(stop: threading.Event, gen: int) -> None:
    """Thread daemon: status berkala selagi ada sub-agent/batch berjalan.

    Dua mode:
      - batch paralel aktif -> cetak progres batch (done/total, ok/err);
      - sub-agent tunggal yang masih RUNNING -> cetak baris 'masih berjalan',
        dan tandai 'MACET' bila tidak ada kabar lebih dari ambang stall.
    Thread berhenti sendiri saat tidak ada batch aktif DAN tidak ada lagi
    record RUNNING (supaya /agents tak terus mencetak baris setelah selesai).
    """
    try:
        _keepalive_loop_body(stop)
    finally:
        _mark_keepalive_exit(gen)


def _keepalive_loop_body(stop: threading.Event) -> None:
    while True:
        iv = _keepalive_interval()
        if iv <= 0:
            return
        if stop.wait(iv):
            return
        with _BATCH_LOCK:
            batch_active = _BATCH["active"]
            total = _BATCH["total"]
            done = _BATCH["done"]
            ok = _BATCH["ok"]
            err = _BATCH["err"]
            started = _BATCH["started"]
        if batch_active:
            running = max(total - done, 0)
            dur = _fmt_duration(time.time() - started) if started else "-"
            _emit(
                f"[sub-agent] … progres {done}/{total} selesai "
                f"(✓{ok} ✗{err}), {running} berjalan, {dur} berlalu"
            )
            continue
        # Mode sub-agent tunggal (role apapun, termasuk agen reviewer).
        running_recs = _running_records()
        if not running_recs:
            return  # tidak ada pekerjaan lagi -> hentikan thread
        now = time.time()
        stall_after = _stall_after()
        for r in running_recs:
            started = r.get("started_at")
            dur = _fmt_duration(now - started) if started else "-"
            extra = ""
            if stall_after > 0 and started and (now - started) >= stall_after:
                extra = (f"  ⚠ TERLIHAT MACET (> {_fmt_duration(stall_after)}); "
                         "mungkin server model menggantung")
            _emit(
                f"[sub-agent] … masih berjalan {r.get('role', '?')}  {r.get('id')}"
                f"  {dur}  {r.get('session_id') or '-'}{extra}"
                f"  — {_short(r.get('task'), _MAX_TASK)}"
            )


def _any_running() -> bool:
    """True bila masih ada sub-agent RUNNING atau batch paralel aktif."""
    try:
        if _BATCH["active"]:
            return True
    except Exception:
        pass
    return bool(_running_records())


def _ensure_keepalive() -> None:
    """Nyalakan thread keepalive/watchdog (satu thread saja, dipakai ulang).

    Aman dipanggil berulang & dari banyak thread: kalau watchdog generasi
    sekarang benar-benar masih berjalan, tidak ada thread baru yang dibuat.
    Sebaliknya, bila thread lama sudah selesai (atau sudah diminta berhenti),
    event stop DIGANTI dengan event baru supaya request stop milik generasi
    lama tidak ikut mematikan watchdog generasi baru (lihat `_keepalive_stop`).
    """
    global _keepalive_thread, _keepalive_stop, _keepalive_alive, _keepalive_gen
    if _keepalive_interval() <= 0:
        return
    with _BATCH_LOCK:
        if _keepalive_alive:
            return  # watchdog generasi sekarang masih hidup -> pakai itu
        _keepalive_gen += 1
        gen = _keepalive_gen
        _keepalive_stop = threading.Event()
        _keepalive_alive = True
        t = threading.Thread(target=_keepalive_loop, args=(_keepalive_stop, gen),
                             daemon=True, name="subagent-keepalive")
        _keepalive_thread = t
    t.start()


def _request_keepalive_stop() -> None:
    """Minta watchdog berhenti (dipakai saat tidak ada lagi pekerjaan).

    Ditulis terpusat supaya semua pemanggil memakai event generasi yang SAMA
    dengan yang sedang dibaca loop (hindari men-set event usang).

    `_keepalive_alive = False` di-set di sini juga -- bukan hanya di dalam loop.
    Tanpa itu ada jendela balapan: event sudah di-set tapi thread lama belum
    sempat bangun dari `stop.wait(iv)`, sehingga `_ensure_keepalive` berikutnya
    (sub-agent baru) masih melihat `_keepalive_alive = True`, tidak membuat
    generasi baru, lalu watchdog lama keluar -> sub-agent baru TANPA watchdog.
    Dengan menurunkannya di sini, setiap start berikutnya dijamin membuat
    generasi watchdog sendiri.
    """
    global _keepalive_alive
    with _BATCH_LOCK:
        # Re-cek di dalam lock: ada jendela balapan antara pemanggil yang
        # mengecek `_any_running()` dan baris ini. Bila di jendela itu sub-agent
        # BARU sudah mulai (dan `_ensure_keepalive` sudah membuat generasi
        # watchdog baru), men-set event/flag di sini akan mematikan watchdog
        # generasi baru tersebut -> sub-agent itu kembali tanpa watchdog.
        # Jadi bila ternyata masih ada pekerjaan, jangan menyentuh apa pun.
        if _any_running():
            return
        _keepalive_alive = False
        _keepalive_stop.set()


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
    with _BATCH_LOCK:
        active = _BATCH["active"]
        total = _BATCH["total"]
        done = _BATCH["done"]
        ok = _BATCH["ok"]
        err = _BATCH["err"]
        started = _BATCH["started"]
        _BATCH["active"] = False
    # Hentikan watchdog HANYA bila sudah tidak ada sub-agent RUNNING lain
    # (mis. sub-agent tunggal yang jalan bersamaan dengan batch): kalau masih
    # ada, thread-nya dibiarkan hidup supaya status 'masih berjalan' tetap
    # tercetak untuk sub-agent tersebut.
    if not _running_records():
        _request_keepalive_stop()
    if not active:
        return
    dur = _fmt_duration(time.time() - started) if started else "-"
    line = (f"[sub-agent] batch selesai: {done}/{total} task "
            f"(✓{ok} ✗{err}) dalam {dur}")
    if note:
        line += f"  — {_short(note, _MAX_ERR)}"
    _emit(line)
