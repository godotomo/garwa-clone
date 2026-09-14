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


def notify_parallel_header(n: int, max_workers: int) -> None:
    """Cetak header saat menjalankan beberapa sub-agent paralel."""
    _emit(f"[sub-agent] menjalankan {n} task paralel (max_workers={max_workers})")
