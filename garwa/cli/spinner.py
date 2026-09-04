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

# Registry spinner yang sedang aktif (thread-safe). Dipakai oleh
# text_utils.confirm() untuk menghentikan sementara spinner sebelum membaca
# input stdin, supaya prompt konfirmasi tidak tertutup karakter spinner.
# Ini pengaman ganda: agent_loop.py sudah mencegah spinner menyala untuk tool
# yang berpotensi prompt, tapi kalau ada jalur lain yang memunculkan prompt
# saat spinner aktif, hook ini tetap melindungi.
_ACTIVE_SPINNERS = set()
_ACTIVE_LOCK = threading.Lock()

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


def pause_all_spinners():
    """Hentikan sementara semua spinner yang sedang aktif (dipanggil sebelum
    membaca input stdin dari prompt konfirmasi). Spinner yang di-pause berhenti
    menulis karakter dan menghapus barisnya, lalu bisa dilanjutkan lagi dengan
    resume_all_spinners() setelah input selesai dibaca."""
    with _ACTIVE_LOCK:
        spinners = list(_ACTIVE_SPINNERS)
    for sp in spinners:
        sp.pause()


def resume_all_spinners():
    """Lanjutkan kembali semua spinner yang sedang aktif setelah input stdin
    selesai dibaca. No-op kalau tidak ada spinner yang di-pause."""
    with _ACTIVE_LOCK:
        spinners = list(_ACTIVE_SPINNERS)
    for sp in spinners:
        sp.resume()


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
        self._paused = threading.Event()
        self._frames = _FRAMES if self._stream.isatty() else _FALLBACK_FRAMES

    def _spin(self):
        for frame in itertools.cycle(self._frames):
            # Kalau sedang di-pause (menunggu input stdin), tunggu sampai
            # di-resume -- jangan menulis karakter yang bisa menimpa prompt.
            # Berhenti total kalau spinner di-stop saat menunggu.
            while self._paused.is_set():
                if self._stop.is_set():
                    return
                time.sleep(0.05)
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

    def pause(self):
        """Hentikan sementara penulisan karakter spinner dan hapus barisnya.
        Dipanggil dari thread lain (mis. confirm()) sebelum membaca stdin."""
        self._paused.set()
        # Hapus baris spinner supaya prompt konfirmasi tampil bersih.
        term_w = _term_width()
        self._stream.write("\r" + " " * term_w + "\r")
        self._stream.flush()

    def resume(self):
        """Lanjutkan kembali penulisan karakter spinner setelah input selesai."""
        self._paused.clear()

    def __enter__(self):
        # Spinner sengaja DINONAKTIFKAN (no-op). Sebelumnya spinner berjalan
        # di thread latar dan menulis ulang baris via carriage-return (`\r`).
        # Di sebagian lingkungan (pipe, redirect, atau terminal tertentu)
        # `\r` tidak diproses dengan benar sehingga setiap frame menumpuk
        # menjadi satu baris spam yang panjang. Untuk menghindari bug itu,
        # spinner tidak pernah dijalankan -- context manager ini hanya
        # mengembalikan self tanpa memulai thread apa pun.
        #
        # Tetap mendaftarkan ke registry agar hook pause/resume (confirm())
        # berfungsi normal; tidak masalah karena thread tidak berjalan.
        with _ACTIVE_LOCK:
            _ACTIVE_SPINNERS.add(self)
        return self

    def __exit__(self, exc_type, exc, tb):
        # Tidak ada thread yang dijalankan, jadi tidak ada yang perlu
        # dihentikan atau dibersihkan. Tetap discard dari registry untuk
        # keamanan kalau ada sisa dari versi lama.
        with _ACTIVE_LOCK:
            _ACTIVE_SPINNERS.discard(self)
        return False  # jangan menelan exception
