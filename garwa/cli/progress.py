"""
progress.py
Render progress bar ringan tanpa animasi spinner berputar.

Sebelumnya progress bar menggunakan karakter spinner berputar (mis.
"⠋⠙⠹...") yang ditulis ulang ke terminal lewat carriage-return (`\r`)
di thread latar. Di sebagian lingkungan (pipe, redirect, atau terminal
tertentu) karakter `\r` tidak diproses dengan benar sehingga setiap frame
menumpuk menjadi satu baris spam yang panjang -- inilah pemicu bug
rendering yang dilaporkan user.

Untuk menghilangkan pemicu itu, progress bar sekarang:
- Menulis ULANG baris lewat `\r` HANYA saat stream adalah terminal
  interaktif (TTY). Di luar TTY (pipe/redirect), cukup cetak satu baris
  status sekali tanpa `\r`.
- Tidak menyalakan thread latar apa pun; setiap pembaruan dirender
  langsung (sinkron).
- Kapasitas lebar maximum = lebar terminal (fallback 80) agar tidak
  membentang melewati tepi layar.
"""

import os
import sys
import time

FALLBACK_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _term_width() -> int:
    """Lebar kolom terminal (fallback 80)."""
    try:
        width = os.get_terminal_size().columns
    except OSError:
        width = 80
    return max(1, width)


def _is_tty(stream) -> bool:
    """Benar kalau stream bisa diakses sebagai terminal interaktif."""
    try:
        return stream.isatty()
    except Exception:
        return False


def _render_bar(fraction: float, width: int) -> str:
    """Buat string progress bar sepanjang ``width`` kolom."""
    fraction = max(0.0, min(1.0, fraction))
    filled = int(round(fraction * width))
    return "█" * filled + "░" * (width - filled)


class ProgressBar:
    """
    Progress bar sinkron tanpa animasi berputar.

    Contoh:
        with ProgressBar("Meringas riwayat...") as pb:
            for i, item in enumerate(items):
                ...
                pb.set_progress(i / len(items))

    Progress bar otomatis berhenti (menghapus barisnya) saat keluar dari
    block ``with``.
    """

    def __init__(self, message: str = "", total: float | None = None,
                 stream=None, width: int | None = None):
        self._message = message
        self._total = total
        # Default ke stderr agar tidak bercampur dengan output tool di stdout.
        self._stream = stream if stream is not None else sys.stderr
        self._width = width if width is not None else _term_width()
        self._fraction = 0.0
        self._last_rendered = None
        self._started = False
        self._finished = False

    def __enter__(self):
        self._started = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self._finished = True
        self._clear()
        return False

    # -- API yang dipakai caller (context_manager, dll) --------------------

    def set_progress(self, fraction: float) -> None:
        """Perbarui fraksi kemajuan (0.0 - 1.0) lalu render."""
        self._fraction = max(0.0, min(1.0, float(fraction)))
        self._render()

    def set_status(self, message: str) -> None:
        """Perbarui pesan status lalu render."""
        self._message = message
        self._render()

    # -- Rendering --------------------------------------------------------

    def _clear(self) -> None:
        """Hapus baris progress saat ini (TTY) atau abaikan (non-TTY)."""
        if _is_tty(self._stream) and self._last_rendered is not None:
            # `\r` ke awal baris, spasi menutupi isi lama, `\r` lagi agar
            # kursor kembali ke awal sebelum baris berikutnya dicetak.
            self._stream.write("\r" + " " * self._width + "\r")
            self._stream.flush()
            self._last_rendered = None

    def _render(self) -> None:
        if self._finished:
            return
        bar = _render_bar(self._fraction, self._width)
        pct = int(self._fraction * 100)
        line = f"[{bar}] {pct:>3}%  {self._message}"
        if _is_tty(self._stream):
            self._stream.write("\r" + line)
            self._stream.flush()
            self._last_rendered = line
        else:
            # non-TTY: cetak satu baris status untuk setiap pembaruan,
            # tanpa `\r` (spam-safe). Tiap status berbeda menjadi baris
            # baru yang normal -- tidak ada spam carriage-return.
            self._stream.write(line + "\n")
            self._stream.flush()
            self._last_rendered = line
