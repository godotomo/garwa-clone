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
- Tidak menyalakan spinner berputar. Satu-satunya thread latar adalah
  creep dari `start_creep()` (lihat "Kemajuan otomatis" di bawah), dan
  creep itu MONOTONIK: fraksi hanya pernah naik, tidak pernah menggambar
  ulang frame di posisi yang sama seperti spinner.
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

Kemajuan otomatis (creep) -- kenapa perlu
-----------------------------------------
Bug yang dilaporkan user: "progress bar tidak terlihat ada kemajuan,
hanya 25% saja". Penyebabnya: satu permintaan HTTP (`requests.post`) untuk
meringkas riwayat TIDAK memberi sinyal kemajuan apa pun sampai responsnya
tuntas. Caller (context_manager) hanya bisa memperbarui bar di ANTAR
percobaan, jadi pada percobaan pertama bar berhenti di 1/4 = 25% lalu
hilang -- secara teknis benar, tapi bagi user tampak macet.

Karena server tidak melaporkan byte/token yang sudah diterima, kemajuan
nyata tidak bisa dihitung. Solusinya: `start_creep()` menaikkan fraksi
mengikuti WAKTU selama menunggu respons, dengan kurva hiperbolik

    ratio(t) = t / (t + half_life)

dengan `t` = detik sejak creep dimulai. Sifat yang penting:
- `ratio(half_life) == 0.5` (mudah diuji dan didokumentasikan).
- Asimtotnya plafon global `CREEP_CEILING` (0.95), jadi bar TIDAK PERNAH
  mengaku selesai sebelum pekerjaannya benar-benar selesai (100% hanya
  dari `finish()`).
- Dipilih hiperbolik, bukan eksponensial, supaya bar tidak "membeku" di
  ujung: selalu ada kenaikan kecil walau permintaan berjalan lama.

`start_creep()` TANPA argumen `span` merayap dari fraksi sekarang menuju
plafon 0.95 itu -- artinya SATU permintaan HTTP yang berjalan lama
(mis. 3 menit) tetap bergerak naik, tidak berhenti di ujung irisan
percobaan. Pemanggil yang ingin rentang terbatas cukup memberi `span`
eksplisit.

Catatan sejarah desain: sebelumnya tiap percobaan diberi IRISAN bar sendiri
`[attempt/total, (attempt+1)/total * 0.95]`. Itu SALAH: untuk operasi dengan
4 percobaan, irisan pertama berhenti di 23,75% sehingga permintaan pertama
yang lama membuat bar mandek di ~24% -- gejala "mentok di 25%" muncul lagi.
Karena itu sekarang hanya ada SATU plafon global untuk keseluruhan operasi,
dan percobaan yang di-retry cukup MELANJUTKAN pendakian dari posisi
terakhir (tidak pernah turun).

Thread creep hanya dinyalakan di TTY (di pipe/redirect pembaruan memang
tidak mungkin terlihat, lihat `_render`), berjalan sebagai daemon, dan
selalu dihentikan sebelum blok progress dibersihkan.

Karakter bar: blok Unicode `█`/`░` secara default. Bila terminal tidak
punya glyph blok (atau terlihat double-width), set env
`GARWA_PROGRESS_ASCII=1` untuk memakai `#`/`-` yang jauh lebih aman.
"""

import os
import shutil
import sys
import threading
import time

FALLBACK_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# Plafon creep: fraksi tertinggi yang boleh dicapai kemajuan OTOMATIS.
# 100% hanya boleh datang dari `finish()`, yang dipanggil setelah pekerjaan
# benar-benar selesai. Tanpa plafon, bar akan "mengaku selesai" lalu diam di
# 100% selama sisa tunggu -- menyesatkan.
CREEP_CEILING = 0.95

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


def _bar_chars() -> tuple:
    """Karakter (isi, kosong) untuk bar.

    Default blok Unicode. Bila env `GARWA_PROGRESS_ASCII` di-set ke nilai
    truthy, pakai `#`/`-` -- pilihan aman untuk terminal tanpa glyph blok.
    """
    val = os.environ.get("GARWA_PROGRESS_ASCII", "").strip().lower()
    if val in ("1", "true", "yes", "on"):
        return "#", "-"
    return "█", "░"


def _render_bar(fraction: float, width: int) -> str:
    """Buat string progress bar sepanjang ``width`` kolom."""
    fraction = max(0.0, min(1.0, fraction))
    filled = int(round(fraction * width))
    full, empty = _bar_chars()
    return full * filled + empty * (width - filled)


class ProgressBar:
    """
    Progress bar sinkron tanpa animasi berputar.

    Contoh:
        with ProgressBar("Meringkas riwayat...") as pb:
            for i, item in enumerate(items):
                ...
                pb.set_progress(i / len(items))

    Progress bar otomatis berhenti (menghapus barisnya) saat keluar dari
    block ``with``. Untuk pekerjaan tunggal yang lamanya tidak diketahui
    (satu permintaan HTTP), pakai `start_creep()` + `finish()` supaya bar
    tetap bergerak dari 0% ke 100%.
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
        # RLock: render bisa dipanggil dari thread creep DAN thread utama.
        # RLock (bukan Lock) karena set_progress()/set_creep() memanggil
        # _render() saat lock sudah dipegang.
        self._lock = threading.RLock()
        # State creep (kemajuan otomatis berbasis waktu).
        self._creep_stop = None
        self._creep_thread = None
        self._creep_base = 0.0
        self._creep_span = 0.0
        self._creep_t0 = 0.0
        self._creep_half_life = 6.0
        self._creep_interval = 0.1

    def __enter__(self):
        self._started = True
        return self

    def __exit__(self, exc_type, exc, tb):
        # Creep dihentikan LEBIH DULU: kalau thread masih hidup saat blok
        # dibersihkan, ia bisa menggambar ulang bar sesudah _clear() dan
        # meninggalkan baris sampah.
        self.stop_creep()
        self._finished = True
        self._clear()
        return False

    # -- API yang dipakai caller (context_manager, dll) --------------------

    @property
    def fraction(self) -> float:
        """Fraksi kemajuan terakhir (0.0 - 1.0), tanpa efek samping render.

        Dibaca dari tes dan dari caller yang ingin tahu posisi bar tanpa
        memicu penulisan frame baru.
        """
        with self._lock:
            return self._fraction

    def set_progress(self, fraction: float) -> None:
        """Perbarui fraksi kemajuan (0.0 - 1.0) lalu render."""
        with self._lock:
            self._fraction = max(0.0, min(1.0, float(fraction)))
            self._render()

    def set_status(self, message: str) -> None:
        """Perbarui pesan status lalu render."""
        with self._lock:
            self._message = message
            self._render()

    def update(self, fraction: float, message: str | None = None) -> None:
        """Perbarui fraksi DAN pesan sekaligus, lalu render SEKALI.

        Pengganti memanggil set_progress() lalu set_status() berurutan --
        dua pemanggilan itu masing-masing merender sehingga menghasilkan
        render ganda (flicker di TTY / dua blok di non-TTY).
        """
        with self._lock:
            self._fraction = max(0.0, min(1.0, float(fraction)))
            if message is not None:
                self._message = message
            self._render()

    # -- Kemajuan otomatis berbasis waktu (creep) -------------------------

    def start_creep(self, base: float | None = None, span: float | None = None,
                    message: str | None = None, half_life: float | None = None,
                    interval: float | None = None) -> None:
        """Majukan bar otomatis mengikuti WAKTU selama menunggu respons.

        Dipakai untuk pekerjaan tunggal yang durasinya tidak diketahui (mis.
        satu POST yang meringkas riwayat): tanpa ini bar hanya berubah di
        ANTAR percobaan sehingga tampak macet.

        Bar naik dari ``base`` (default: fraksi sekarang) mengikuti
        ``ratio(t) = t / (t + half_life)``, dengan ``t`` = detik sejak creep
        dimulai. Pada ``t == half_life`` kemajuan tepat separuh rentang.

        Bila ``span`` TIDAK diberikan (kasus umum di context_manager), creep
        mendaki dari fraksi sekarang menuju plafon ``CREEP_CEILING`` (0.95).
        Ini penting: permintaan pertama bisa berjalan menit-an, dan dengan
        rentang tetap bar akan berhenti di ujungnya lalu tampak macet lagi.
        ``span`` eksplisit tetap dihormati (berguna untuk berbagi rentang
        antar tahap), dan dipotong supaya tidak melewati plafon.

        Aman dipanggil berulang: creep yang sedang jalan dihentikan dulu.
        Karena ``base`` default = fraksi sekarang dan bar tidak pernah turun,
        percobaan yang di-retry otomatis MELANJUTKAN dari posisi terakhir.
        Di non-TTY creep tidak dinyalakan (pembaruan memang tidak akan
        terlihat), tapi blok status pertama TETAP dicetak sekali.
        """
        self.stop_creep()

        tty = _is_tty(self._stream)
        with self._lock:
            if self._finished:
                return
            start = self._fraction if base is None else float(base)
            start = max(0.0, min(1.0, start))
            if span is None:
                want = max(0.0, CREEP_CEILING - start)
            else:
                want = max(0.0, float(span))
            # Jangan sampai melewati plafon walau caller memberi span berlebih.
            self._creep_span = min(want, max(0.0, CREEP_CEILING - start))
            self._creep_base = start
            self._creep_half_life = (float(half_life) if half_life else 6.0)
            self._creep_interval = (float(interval) if interval else 0.1)
            self._creep_t0 = time.monotonic()
            if message is not None:
                self._message = message
            # Fraksi tidak diturunkan: bar selalu monoton naik.
            if start > self._fraction:
                self._fraction = start
            self._render()

        if not tty or self._creep_span <= 0.0:
            return

        stop = threading.Event()
        thread = threading.Thread(
            target=self._creep_loop, args=(stop,),
            name="garwa-progress-creep", daemon=True,
        )
        with self._lock:
            self._creep_stop = stop
            self._creep_thread = thread
        thread.start()

    def stop_creep(self) -> None:
        """Hentikan creep otomatis (idempoten, aman dipanggil dari mana pun)."""
        with self._lock:
            stop = self._creep_stop
            thread = self._creep_thread
            self._creep_stop = None
            self._creep_thread = None
        if stop is not None:
            stop.set()
        # Join DI LUAR lock: kalau thread sedang menunggu lock untuk render,
        # join sambil memegang lock akan membuat deadlock.
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def _creep_loop(self, stop: threading.Event) -> None:
        """Thread creep: naikkan fraksi tiap ``interval`` detik sampai dihentikan."""
        while not stop.wait(self._creep_interval):
            if stop.is_set():
                return
            # _creep_advance() sendiri yang memeriksa `_finished` + memegang lock.
            self._creep_advance()

    def _creep_advance(self) -> bool:
        """Hitung satu langkah creep berbasis waktu. Return True bila bar naik.

        Dipisah dari loop thread supaya bisa diuji tanpa tidur: tes cukup
        memundurkan `_creep_t0` lalu memanggil method ini.
        """
        with self._lock:
            if self._finished or self._creep_span <= 0.0:
                return False
            elapsed = time.monotonic() - self._creep_t0
            if elapsed <= 0:
                return False
            ratio = elapsed / (elapsed + self._creep_half_life)
            target = self._creep_base + self._creep_span * ratio
            if target <= self._fraction:
                # Sudah dilewati pembaruan manual dari caller -> jangan turun.
                return False
            self._fraction = min(1.0, target)
            self._render()
            return True

    def finish(self, message: str | None = None, leave: bool = True) -> None:
        """Tandai pekerjaan SELESAI: hentikan creep, tampilkan 100%.

        Blok live dibersihkan lalu satu baris final ``[####] 100%  pesan``
        dicetak PERMANEN (bisa dimatikan dengan ``leave=False``). Tanpa ini
        user tidak pernah melihat 100%: blok live selalu dihapus saat keluar
        dari ``with``.

        Setelah `finish()`, `__exit__` tidak menghapus baris final itu karena
        ``_last_lines`` sudah di-None-kan di sini.
        """
        if self._finished:
            return
        self.stop_creep()
        with self._lock:
            if message is not None:
                self._message = message
            self._fraction = 1.0
            live_wiped = self._clear()
            if not leave:
                return
            final = "  ".join(self._build_lines())
            # Keluarkan satu baris final tanpa ANSI cursor-up: baris ini
            # sengaja ditinggal supaya user melihat bar mencapai 100%.
            if live_wiped:
                self._stream.write(" " * max(1, self._width - 1) + "\r")
            self._stream.write(final + "\n")
            self._stream.flush()
            self._last_lines = None

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

    def _clear(self) -> bool:
        """Hapus blok progress saat ini (TTY) atau abaikan (non-TTY).

        Return True bila memang ada blok yang dibersihkan dari layar.
        """
        with self._lock:
            if not _is_tty(self._stream) or self._last_lines is None:
                return False
            n = len(self._last_lines)
            # Pad maksimum term_w - 1 kolom: menulis TEPAT selebar terminal
            # memicu auto-wrap (kursor pindah ke baris berikutnya) sehingga
            # perhitungan cursor-up jadi salah.
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
            return True

    def _render(self) -> None:
        with self._lock:
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
                # stream non-terminal. Baris 100% final tetap dicetak oleh
                # finish() supaya user tahu pekerjaannya tuntas.
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
