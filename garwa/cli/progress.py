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
  interaktif (TTY). Di luar TTY (pipe/redirect), cukup cetak satu blok
  status sekali tanpa `\r`.
- Tidak menyalakan thread latar apa pun; setiap pembaruan dirender
  langsung (sinkron).
- Kapasitas lebar maximum = lebar terminal (fallback 80) agar tidak
  membentang melewati tepi layar.

Deteksi lebar terminal memakai `shutil.get_terminal_size` (menghormati env
`COLUMNS`) dengan fallback ke `os.get_terminal_size`. Di Termux
`os.get_terminal_size()` sering gagal (`Permission denied`) sehingga dulu
lebar selalu jatuh ke 80 padahal layar hanya 48 kolom -- akibatnya bar
terpotong/wrap dan hanya terlihat sebagian. `shutil` membaca `COLUMNS`
sehingga lebar yang dipakai sesuai layar nyata.

Tata letak (layout) sekarang DUA baris:

    [████████████████░░░░░░░░]  50%
    mengirim ke model ... (percobaan 1/3)

Baris pertama = bar + persentase (tetap). Baris kedua = pesan status
(tulisan). Pesan dipindah ke bawah supaya bar bisa memakai lebar penuh
tanpa terpotong oleh teks panjang. Di TTY kedua baris ditimpa ulang
(live update) memakai ANSI cursor-up; di non-TTY cukup dicetak sekali.
"""

import os
import shutil
import sys

FALLBACK_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# ANSI: pindah kursor naik n baris (1-based). Dipakai untuk menimpa blok
# multi-baris di TTY.
_CURSOR_UP = "\x1b[{}A"


def _term_width() -> int:
    """Lebar kolom terminal.

    Prioritas: `shutil.get_terminal_size` (menghormati env `COLUMNS`, dan
    bekerja di Termux) -> `os.get_terminal_size` -> fallback 80.
    """
    try:
        width = shutil.get_terminal_size().columns
        if width > 0:
            return width
    except Exception:
        pass
    try:
        width = os.get_terminal_size().columns
        if width > 0:
            return width
    except Exception:
        pass
    return 80


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
        with ProgressBar("Meringkas riwayat...") as pb:
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
        # Baris terakhir yang dirender (list[str]); None = belum pernah render.
        self._last_lines = None
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

    def update(self, fraction: float, message: str | None = None) -> None:
        """Perbarui fraksi DAN pesan sekaligus, lalu render SEKALI.

        Pengganti memanggil set_progress() lalu set_status() berurutan --
        dua pemanggilan itu masing-masing merender sehingga menghasilkan
        render ganda (flicker di TTY / dua blok di non-TTY).
        """
        self._fraction = max(0.0, min(1.0, float(fraction)))
        if message is not None:
            self._message = message
        self._render()

    # -- Rendering --------------------------------------------------------

    def _build_lines(self) -> list:
        """Susun baris yang akan dirender.

        Baris 1: ``[bar] pct%`` (bar + persentase, memakai lebar penuh).
        Baris 2: pesan status (kalau ada).
        """
        term_w = self._width
        # Sisakan 1 kolom (term_w - 1): menulis TEPAT selebar terminal memicu
        # auto-wrap di banyak terminal (termasuk Termux), yang membuat baris
        # berikutnya tercetak di baris baru dan bar tampak terpotong.
        usable = max(1, term_w - 1)
        pct = int(self._fraction * 100)
        pct_str = f"{pct:>3}%"
        # Kolom tetap baris 1: "[", "]", spasi, persentase.
        fixed = len("[") + len("]") + 1 + len(pct_str)
        bar_w = max(1, usable - fixed)
        bar = _render_bar(self._fraction, bar_w)
        line1 = f"[{bar}] {pct_str}"[:usable]
        lines = [line1]
        if self._message:
            msg = self._message
            if len(msg) > usable:
                msg = msg[: max(0, usable - 1)] + "…"
            lines.append(msg)
        return lines

    def _clear(self) -> None:
        """Hapus blok progress saat ini (TTY) atau abaikan (non-TTY)."""
        if not _is_tty(self._stream) or self._last_lines is None:
            return
        n = len(self._last_lines)
        # Pad maksimum term_w - 1 kolom: menulis TEPAT selebar terminal memicu
        # auto-wrap (kursor pindah ke baris berikutnya) sehingga perhitungan
        # cursor-up jadi salah.
        pad_w = max(1, self._width - 1)
        buf = []
        if n > 1:
            # Kursor ada di baris terakhir blok -> naik ke baris pertama.
            buf.append(_CURSOR_UP.format(n - 1))
        buf.append("\r")
        for i in range(n):
            buf.append(" " * pad_w)
            if i < n - 1:
                buf.append("\n")
        if n > 1:
            # Kembali ke baris pertama blok agar output berikutnya menimpa
            # dari posisi awal (bukan menyisakan baris kosong).
            buf.append(_CURSOR_UP.format(n - 1))
        buf.append("\r")
        self._stream.write("".join(buf))
        self._stream.flush()
        self._last_lines = None

    def _render(self) -> None:
        if self._finished:
            return
        term_w = self._width
        lines = self._build_lines()

        if _is_tty(self._stream):
            self._draw_tty(lines, term_w)
        else:
            # non-TTY (pipe/redirect): cetak SATU blok status saja (yang
            # pertama) supaya tidak menumpuk jadi banyak baris berantakan.
            # Update berikutnya diabaikan -- tidak ada cara menimpa baris di
            # stream non-terminal.
            if self._last_lines is None:
                self._stream.write("\n".join(lines) + "\n")
                self._stream.flush()
                self._last_lines = lines

    def _draw_tty(self, lines: list, term_w: int) -> None:
        """Timpa blok progress di TTY (multi-baris) memakai ANSI cursor-up."""
        prev_n = len(self._last_lines) if self._last_lines is not None else 0
        new_n = len(lines)
        # Pad maksimum term_w - 1 kolom: menulis TEPAT selebar terminal memicu
        # auto-wrap (kursor pindah ke baris berikutnya) sehingga perhitungan
        # cursor-up jadi salah.
        pad_w = max(1, term_w - 1)
        buf = []
        if prev_n > 1:
            # Kursor ada di baris terakhir blok lama -> naik ke baris pertama.
            buf.append(_CURSOR_UP.format(prev_n - 1))
        buf.append("\r")
        for i, ln in enumerate(lines):
            # Pad ke lebar terminal supaya sisa karakter baris lama tertimpa.
            buf.append(ln + " " * max(0, pad_w - len(ln)))
            if i < new_n - 1:
                buf.append("\n")
        # Kalau blok lama lebih banyak baris (mis. pesan hilang), bersihkan
        # baris sisa lalu kembali ke baris pertama blok baru.
        if prev_n > new_n:
            for _ in range(prev_n - new_n):
                buf.append("\n" + " " * pad_w)
            buf.append(_CURSOR_UP.format(prev_n - new_n))
        self._stream.write("".join(buf))
        self._stream.flush()
        self._last_lines = lines
