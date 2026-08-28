"""cli/progress.py
Utilitas tampilan progres di console untuk proses yang berjalan lama
(mis. summarization riwayat percakapan).

Dua gaya yang didukung:
- Spinner: animasi karakter berputar (mis. "⠋⠙⠹...") + teks status.
- Progress bar: bilah isian yang bergerak dari 0% -> 100% + teks status.

Keduanya "aman untuk non-TTY": kalau stdout bukan terminal (mis. output
dialihkan ke file/pipe, atau mode --auto/--overnight), semua output
progres dinonaktifkan otomatis supaya tidak mengotori log. Warna dipakai
hanya kalau terminal mendukungnya (via colors.c()).

Spinner dan progress bar dirancang agar bisa dipakai BERSAMAAN tanpa
saling menimpa: Spinner dapat menampilkan bilah progress inline sehingga
satu baris berisi spinner + bilah + persen + status.

Semua output progress dijaga agar TIDAK PERNAH melebihi lebar terminal,
sehingga tidak terjadi line-wrap yang menyebabkan baris tercetak
berulang di baris baru (terutama di Python 3.11+).
"""
import re
import shutil
import sys
import threading

from .colors import C
from .colors import c

# Karakter spinner (Braille) yang umum didukung terminal modern.
_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_SPINNER_INTERVAL = 0.1  # detik per frame

# Lebar bilah progress bar (jumlah kolom karakter).
_BAR_WIDTH = 30

# Regex untuk menghapus ANSI escape sequences dari string.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Hapus semua ANSI escape sequences, menyisakan teks polos."""
    return _ANSI_RE.sub("", text)


def _term_width() -> int:
    """Lebar terminal saat ini (fallback 80 jika tidak bisa dideteksi)."""
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return 80


def _enabled() -> bool:
    """Progress hanya aktif kalau stdout terminal dan bukan mode non-interaktif."""
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def _render_bar(fraction: float, width: int = _BAR_WIDTH) -> str:
    """Bangun teks bilah progress: [█████░░░░░] 50%."""
    fraction = max(0.0, min(1.0, fraction))
    filled = int(round(fraction * width))
    bar = "█" * filled + "░" * (width - filled)
    pct = f"{fraction * 100:.0f}%"
    return c(f"[{bar}]", C.BOLD_CYAN) + c(f" {pct}", C.BOLD_WHITE)


class Spinner:
    """Animasi spinner berjalan di thread latar.

    Bisa menampilkan progress bar inline lewat ``set_progress()`` sehingga
    satu baris berisi spinner + bilah + persen + status sekaligus.

    Contoh pemakaian:
        with Spinner("Meringkas riwayat...") as sp:
            sp.set_status("Mengirim ke model (percobaan 1/3)...")
            sp.set_progress(0.33)
            ...  # kerja lama
        # keluar dari `with` -> spinner dihentikan & baris dibersihkan
    """

    def __init__(self, message: str = ""):
        self._message = message
        self._status = ""
        self._fraction: float | None = None
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._active = _enabled()

    def set_status(self, text: str) -> None:
        """Perbarui teks status yang ditampilkan di samping spinner."""
        with self._lock:
            self._status = text

    def set_progress(self, fraction: float) -> None:
        """Aktifkan bilah progress inline; `fraction` adalah 0.0..1.0."""
        with self._lock:
            self._fraction = max(0.0, min(1.0, fraction))

    def _spin(self) -> None:
        idx = 0
        try:
            while not self._stop.is_set():
                with self._lock:
                    status = self._status
                    fraction = self._fraction
                frame = _SPINNER_FRAMES[idx % len(_SPINNER_FRAMES)]
                parts = [c(f"{frame} {self._message}", C.BOLD_CYAN)]
                if fraction is not None:
                    parts.append(_render_bar(fraction))
                if status:
                    parts.append(c(status, C.DIM))
                line = " ".join(parts)
                # Potong agar tidak melebihi lebar terminal (mencegah
                # line-wrap yang menyebabkan baris tercetak ke baris baru).
                term_w = _term_width()
                visual_len = len(_strip_ansi(line))
                if visual_len > term_w:
                    # Potong dari teks polos, lalu rekonstruksi ulang
                    # dengan ANSI code yang sudah di-strip.
                    line = _strip_ansi(line)[:term_w]
                # Tulis baris + bersihkan sisa karakter dari output
                # sebelumnya dengan spasi hingga selebar terminal.
                sys.stdout.write("\r" + line + " " * max(0, term_w - visual_len))
                sys.stdout.flush()
                idx += 1
                self._stop.wait(_SPINNER_INTERVAL)
        finally:
            # Bersihkan seluruh baris spinner saat dihentikan.
            term_w = _term_width()
            sys.stdout.write("\r" + " " * term_w + "\r")
            sys.stdout.flush()

    def __enter__(self) -> "Spinner":
        if self._active:
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._active and self._thread is not None:
            self._stop.set()
            self._thread.join(timeout=1.0)


def progress_bar(
    fraction: float,
    message: str = "",
    width: int = _BAR_WIDTH,
) -> None:
    """Tampilkan progress bar satu baris (di-rewrite via carriage return).

    `fraction` adalah nilai 0.0..1.0. Terakhir kali dipanggil dengan
    fraction >= 1.0, baris dibiarkan tampil (bukan dibersihkan) supaya
    hasil akhir terlihat, lalu pindah baris.
    """
    if not _enabled():
        return
    line = _render_bar(fraction, width)
    if message:
        line += c(f" {message}", C.DIM)
    # Potong agar tidak melebihi lebar terminal.
    term_w = _term_width()
    visual_len = len(_strip_ansi(line))
    if visual_len > term_w:
        line = _strip_ansi(line)[:term_w]
    sys.stdout.write("\r" + line + " " * max(0, term_w - visual_len))
    sys.stdout.flush()
    if fraction >= 1.0:
        sys.stdout.write("\n")
        sys.stdout.flush()


def summarize_progress(
    message: str,
    total: float = 1.0,
    done: float = 0.0,
) -> None:
    """Progress bar khusus untuk proses summarization.

    `done`/`total` bisa berupa angka token/baris agar bilah bergerak
    realistis. Nilai default 0..1 cukup untuk sekadar memberi animasi.
    """
    progress_bar(done / total if total else 0.0, message=message)
