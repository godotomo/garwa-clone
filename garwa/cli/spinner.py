"""cli/spinner.py
Spinner terminal ringan untuk indikasi tool yang sedang berjalan lama.

Menulis karakter spinner ke STDERR (bukan stdout) supaya tidak mengotori
hasil tool yang dicetak ke stdout, dan memakai carriage-return agar baris
spinner menimpa dirinya sendiri -- tidak menumpuk baris baru di terminal.

Spinner dijalankan di thread daemon. Aman untuk kasus tool yang memanggil
input()/konfirmasi dari stdin: spinner hanya menulis ke stderr, tidak
menyentuh stdin, jadi prompt konfirmasi tetap bisa dibaca user. Namun demi
kebersihan, caller sebaiknya hanya mengaktifkan spinner saat tahu tidak ada
prompt interaktif yang akan muncul (mis. mode auto-approve).

Semua output spinner dijaga agar tidak melebihi lebar terminal, sehingga
tidak terjadi line-wrap yang menyebabkan baris tercetak berulang di baris
baru (terutama di Python 3.11+).
"""
import itertools
import shutil
import sys
import threading
import time

# Karakter spinner klasik.
_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_FALLBACK_FRAMES = ("|", "/", "-", "\\")

# Interval antar frame (detik).
_FRAME_INTERVAL = 0.1


def _term_width() -> int:
    """Lebar terminal saat ini (fallback 80 jika tidak bisa dideteksi)."""
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return 80


class Spinner:
    """Context manager yang menampilkan spinner selama blok berjalan.

    Contoh:
        with Spinner("menjalankan tool"):
            result = run_tool(...)

    Spinner otomatis berhenti (dan menghapus barisnya) saat keluar dari
    blok `with`, termasuk jika terjadi exception.
    """

    def __init__(self, message: str = "", stderr: bool = True):
        self._message = message
        self._stream = sys.stderr if stderr else sys.stdout
        self._thread = None
        self._stop = threading.Event()
        self._frames = _FRAMES if self._stream.isatty() else _FALLBACK_FRAMES

    def _spin(self):
        for frame in itertools.cycle(self._frames):
            if self._stop.is_set():
                break
            line = f"{frame} {self._message}"
            term_w = _term_width()
            visual_len = len(line)
            if visual_len > term_w:
                line = line[:term_w]
            # Tulis baris + bersihkan sisa karakter dari output sebelumnya.
            self._stream.write("\r" + line + " " * max(0, term_w - visual_len))
            self._stream.flush()
            time.sleep(_FRAME_INTERVAL)

    def __enter__(self):
        # Hanya tampilkan spinner kalau stream-nya terminal interaktif.
        # Kalau stdout/stdin di-redirect (mis. test otomatis), lewati saja
        # supaya tidak menulis karakter kontrol ke output yang bukan tty.
        if self._stream.isatty():
            self._thread = threading.Thread(
                target=self._spin, daemon=True, name="garwa-spinner"
            )
            self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._thread is not None:
            self._stop.set()
            self._thread.join(timeout=_FRAME_INTERVAL * 2)
            # Hapus seluruh baris spinner (carriage-return + spasi selebar terminal).
            term_w = _term_width()
            self._stream.write("\r" + " " * term_w + "\r")
            self._stream.flush()
        return False  # jangan menelan exception
