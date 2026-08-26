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
"""
import itertools
import sys
import threading
import time

# Karakter spinner klasik.
_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_FALLBACK_FRAMES = ("|", "/", "-", "\\")

# Interval antar frame (detik).
_FRAME_INTERVAL = 0.1


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
            self._stream.write(f"\r{frame} {self._message}")
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
            # Hapus baris spinner (carriage-return + spasi penutup).
            self._stream.write("\r" + " " * (len(self._message) + 2) + "\r")
            self._stream.flush()
        return False  # jangan menelan exception
