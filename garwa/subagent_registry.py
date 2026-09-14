"""garwa/subagent_registry.py
Registry in-memory (thread-safe) untuk melacak sub-agent.

Tujuan: pengguna bisa melihat sub-agent apa saja yang SEDANG berjalan dan
statusnya (running / success / error / interrupted). Sub-agent Garwa berjalan
in-process di thread (lihat `garwa/tools/sub_agent.py`), jadi registry cukup
disimpan di memori proses -- tidak perlu tabel DB. Record tetap ada setelah
sub-agent selesai (selama proses CLI hidup) supaya pengguna bisa memeriksa
hasil/error-nya kapan saja lewat `/agents`.

Modul ini SENGAJA tidak meng-import apa pun dari `garwa.cli` atau
`garwa.tools` supaya bisa dipakai dari mana saja tanpa circular import.
"""
import threading
import time
import uuid

# Batas jumlah record yang disimpan. Record yang sudah SELESAI (punya
# finished_at) paling lama dibuang lebih dulu saat melebihi batas; record yang
# masih running tidak pernah dibuang.
MAX_RECORDS = 200

STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_ERROR = "error"
STATUS_INTERRUPTED = "interrupted"

_LOCK = threading.Lock()
_RECORDS: list = []  # list[dict], urut waktu mulai


def _new_id() -> str:
    return "sa_" + uuid.uuid4().hex[:8]


def register_start(role: str, task: str, parent_session: str = None) -> str:
    """Catat sub-agent yang MULAI berjalan. Mengembalikan id record.

    `session_id` sub-agent belum tentu ada saat ini (dibuat setelahnya), jadi
    diisi via `update()`/`set_session()`.
    """
    rec = {
        "id": _new_id(),
        "role": role or "general",
        "task": str(task or "").strip(),
        "session_id": None,
        "parent_session": parent_session,
        "status": STATUS_RUNNING,
        "started_at": time.time(),
        "finished_at": None,
        "error": None,
    }
    with _LOCK:
        _RECORDS.append(rec)
        _prune_locked()
    return rec["id"]


def update(rec_id: str, **fields) -> bool:
    """Perbarui field record (mis. session_id). True kalau record ditemukan."""
    with _LOCK:
        for r in _RECORDS:
            if r["id"] == rec_id:
                r.update(fields)
                return True
    return False


def set_session(rec_id: str, session_id: str) -> bool:
    """Isi session_id sub-agent (dipanggil setelah sub-session dibuat)."""
    return update(rec_id, session_id=session_id)


def mark_done(rec_id: str, status: str, error: str = None) -> bool:
    """Tandai sub-agent selesai dengan status akhir + pesan error (opsional)."""
    return update(rec_id, status=status, error=error, finished_at=time.time())


def list_records() -> list:
    """Salinan semua record (dict), urut waktu mulai (terlama dulu)."""
    with _LOCK:
        return [dict(r) for r in _RECORDS]


def get(rec_id: str):
    """Ambil satu record (dict) atau None."""
    with _LOCK:
        for r in _RECORDS:
            if r["id"] == rec_id:
                return dict(r)
    return None


def clear() -> None:
    """Hapus semua record (dipakai test / reset)."""
    with _LOCK:
        _RECORDS.clear()


def _prune_locked() -> None:
    """Buang record SELESAI paling lama saat melebihi MAX_RECORDS.

    Record yang masih running tidak pernah dibuang. Dipanggil dengan _LOCK
    sudah dipegang.
    """
    if len(_RECORDS) <= MAX_RECORDS:
        return
    excess = len(_RECORDS) - MAX_RECORDS
    # Kandidat: record selesai, urut dari yang paling lama selesai.
    done = [r for r in _RECORDS if r["finished_at"] is not None]
    done.sort(key=lambda r: r["finished_at"])
    to_drop = {id(r) for r in done[:excess]}
    if to_drop:
        _RECORDS[:] = [r for r in _RECORDS if id(r) not in to_drop]
