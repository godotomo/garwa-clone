"""todo_utils.py
Helper bersama untuk PLAN/TODO: penanda status, umur item, dan deteksi item BASI.

Latar belakang:
    Todo disimpan per WORKDIR (lihat `db.replace_todos`) dan `todo_write`
    bersifat FULL REPLACE. Artinya setiap kali model mengirim daftar todo,
    SEMUA baris ditulis ulang -- termasuk `updated_at`. Akibatnya `updated_at`
    tidak bisa dipakai untuk mengukur "sejak kapan item ini menggantung".
    Kolom `status_since` (lihat db.py) menutup celah itu: nilainya hanya
    berubah kalau status item benar-benar berubah.

    Dengan `status_since`, klien bisa mendeteksi todo BASI: item
    pending/in_progress yang statusnya sudah tidak berubah melewati ambang
    waktu. Todo basi hampir selalu berarti model lupa menutupnya (tidak
    memanggil todo_write untuk menandai done) atau pekerjaannya ditinggalkan,
    padahal todo ini akan dibaca model di sesi lain.

Modul ini murni fungsi format/perhitungan (tanpa I/O) supaya bisa dipakai
seragam oleh tool (`tools/session_tools.py`) dan sisi CLI
(`cli/main.py`, `cli/autopilot.py`, `cli/slash_commands.py`), serta mudah
diuji.
"""
import os
import time

#: Ambang (jam) sebuah todo pending/in_progress dianggap BASI. Bisa diatur
#: lewat env `GARWA_TODO_STALE_HOURS` (0 = matikan deteksi basi).
DEFAULT_STALE_HOURS = 6.0

#: Penanda visual item yang sudah basi, ditambahkan pada tampilan.
STALE_TAG = "[STALE]"

MARKS = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]", "cancelled": "[-]"}


def stale_threshold_seconds() -> float:
    """Ambang deteksi basi dalam detik (0 = nonaktif).

    Dibaca ulang setiap panggilan (bukan konstanta saat import) supaya test
    dan user bisa mengubah env var tanpa me-restart proses.
    """
    raw = os.environ.get("GARWA_TODO_STALE_HOURS")
    hours = DEFAULT_STALE_HOURS
    if raw is not None:
        try:
            hours = float(raw)
        except (TypeError, ValueError):
            hours = DEFAULT_STALE_HOURS
    if hours <= 0:
        return 0.0
    return hours * 3600.0


def mark_for(status: str) -> str:
    """Tanda visual untuk sebuah status ([ ], [~], [x], [-])."""
    return MARKS.get(status or "pending", "[ ]")


def format_age(seconds) -> str:
    """Format durasi menjadi teks ringkas: 45d, 3j 20m, 12m, <1m."""
    try:
        seconds = float(seconds or 0)
    except (TypeError, ValueError):
        return "-"
    if seconds < 60:
        return "<1m"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    minutes = minutes % 60
    if hours < 24:
        return f"{hours}j {minutes}m" if minutes else f"{hours}j"
    days = hours // 24
    hours = hours % 24
    return f"{days}h {hours}j" if hours else f"{days}h"


def age_seconds(row: dict, now: float = None) -> float:
    """Umur STATUS sebuah baris todo (detik).

    Prioritas `status_since` (penanda sesungguhnya), lalu fallback ke
    `updated_at`/`created_at` untuk DB lama yang belum punya kolom itu.
    """
    if not row:
        return 0.0
    since = row.get("status_since") or row.get("updated_at") or row.get("created_at") or 0
    if not since:
        return 0.0
    try:
        since = float(since)
    except (TypeError, ValueError):
        return 0.0
    now = time.time() if now is None else now
    return max(0.0, now - since)


def is_stale(row: dict, threshold_seconds: float = None, now: float = None) -> bool:
    """True kalau item masih aktif (pending/in_progress) DAN sudah menggantung
    melewati ambang. Item done/cancelled TIDAK pernah dianggap basi.
    """
    if not row:
        return False
    status = row.get("status") or "pending"
    if status not in ("pending", "in_progress"):
        return False
    thr = stale_threshold_seconds() if threshold_seconds is None else float(threshold_seconds or 0)
    if thr <= 0:
        return False
    return age_seconds(row, now=now) >= thr


def format_rows(rows, threshold_seconds: float = None, now: float = None,
                with_age: bool = True, indent: str = "") -> list:
    """Format baris todo menjadi list baris teks siap cetak.

    Contoh keluaran:
        [~] refactor parser  (2j 5m) [STALE]
        [x] tulis test
    """
    thr = stale_threshold_seconds() if threshold_seconds is None else float(threshold_seconds or 0)
    now = time.time() if now is None else now
    lines = []
    for r in rows or []:
        status = r.get("status") or "pending"
        content = (r.get("content") or "").strip().replace("\n", " ")
        suffix = ""
        if with_age and status in ("pending", "in_progress"):
            suffix = f"  ({format_age(age_seconds(r, now=now))})"
            if is_stale(r, threshold_seconds=thr, now=now):
                suffix += f" {STALE_TAG}"
        lines.append(f"{indent}{mark_for(status)} {content}{suffix}")
    return lines


def stale_summary(rows, threshold_seconds: float = None, now: float = None) -> str:
    """Satu baris ringkas ringkasan item basi ("" kalau tidak ada)."""
    thr = stale_threshold_seconds() if threshold_seconds is None else float(threshold_seconds or 0)
    if thr <= 0:
        return ""
    now = time.time() if now is None else now
    stale = [r for r in (rows or []) if is_stale(r, threshold_seconds=thr, now=now)]
    if not stale:
        return ""
    oldest = max(age_seconds(r, now=now) for r in stale)
    return (
        f"{len(stale)} item todo menggantung/basi (paling lama {format_age(oldest)}) "
        f"-- tandai done/hapus lewat todo_write bila sudah selesai atau tidak relevan"
    )


def find_stale(rows, threshold_seconds: float = None, now: float = None) -> list:
    """Filter baris todo yang basi (urut dari paling lama menggantung)."""
    now = time.time() if now is None else now
    stale = [r for r in (rows or []) if is_stale(r, threshold_seconds=threshold_seconds, now=now)]
    stale.sort(key=lambda r: age_seconds(r, now=now), reverse=True)
    return stale
