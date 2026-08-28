"""cli/paste_input.py
Dipecah otomatis dari cli.py (lihat cli/_state.py untuk state bersama).
"""
import os
import select
import sys

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from . import _state as state



def _describe_paste(text: str) -> str:
    """Baris ringkasan yang ditampilkan ke user, bukan isi paste-nya."""
    line_count = text.count("\n") + 1
    char_count = len(text)
    flat = text.replace("\n", " ").replace("\t", " ").strip()
    preview = flat[:state.PASTE_PREVIEW_CHARS]
    ellipsis = "…" if len(flat) > state.PASTE_PREVIEW_CHARS else ""
    return (
        f'[PASTE] "{preview}{ellipsis}" — {line_count} baris, {char_count} '
        f"karakter (dikirim sebagai attachment)"
    )


def _format_pasted_attachment(text: str) -> str:
    """Bungkus teks yang di-paste (multi-baris) sebagai blok 'attachment'
    eksplisit sebelum disimpan ke DB/dikirim ke model -- supaya model tahu
    ini konten tempelan besar (mis. log/kode/file), bukan instruksi ketik
    manual biasa, tanpa mengubah isi teks itu sendiri sedikit pun.
    """
    line_count = text.count("\n") + 1
    return (
        f'<pasted_attachment lines="{line_count}">\n'
        f"{text}\n"
        f"</pasted_attachment>"
    )


def _stdin_has_pending_data(timeout: float = 0.0) -> bool:
    """True kalau ada data yang SUDAH menunggu di buffer stdin tanpa perlu
    menunggu user mengetik lagi.

    Dipakai sebagai fallback deteksi paste multi-baris untuk
    terminal/readline yang TIDAK bracketed-paste-aware: pada kasus itu,
    paste multi-baris tiba sebagai banyak baris yang masing-masing memicu
    "submit" input() terpisah -- tapi semuanya sudah tertulis ke buffer
    stdin sekaligus (jauh lebih cepat dari kecepatan mengetik manusia
    baris-demi-baris), sehingga bisa dibedakan dari ketikan manual dengan
    mengecek apakah baris berikutnya sudah siap dibaca SEKARANG JUGA.

    Hanya berfungsi di platform POSIX (select() atas stdin bekerja untuk
    pipe/tty di Linux/macOS). Di Windows select() tidak mendukung file
    descriptor biasa/stdin dengan cara yang sama, jadi selalu kembalikan
    False di sana -- fallback ini nonaktif, tapi jalur bracketed-paste
    readline (lihat parse_and_bind di atas) tetap bisa bekerja kalau
    terminal Windows modern mengirimkannya.
    """
    if os.name != "posix":
        return False
    try:
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        return bool(ready)
    except Exception:
        return False


def read_user_input(prompt: str) -> str:
    """Pengganti input() biasa dengan deteksi paste multi-baris.

    Ada dua jalur paste yang ditangani:

    1. Terminal + readline bracketed-paste-aware (readline >= 8.1, umum
       di distro modern): seluruh isi paste -- termasuk newline di
       dalamnya -- sudah datang sebagai SATU nilai balik input(). Ini
       dideteksi cukup dengan mengecek '\\n' pada hasilnya.

    2. Terminal/readline yang TIDAK bracketed-paste-aware: paste
       multi-baris tiba sebagai banyak baris terpisah yang masing-masing
       memicu "submit" input(), tapi semuanya sudah menunggu di buffer
       stdin sekaligus. Begitu baris pertama diterima, cek apakah baris
       berikutnya SUDAH siap dibaca tanpa jeda (select timeout ~0) --
       kalau ya, terus baca baris demi baris selama masih ada data
       pending, lalu gabungkan semuanya jadi satu blok paste.

    Kalau tidak terdeteksi sebagai paste sama sekali, perilakunya persis
    seperti input() biasa (satu baris ketikan manual).
    """
    first = input(prompt)

    if "\n" in first:

        return first

    if not _stdin_has_pending_data(0.0):

        return first

    lines = [first]
    while _stdin_has_pending_data(0.02):
        try:
            line = input()
        except EOFError:
            break
        lines.append(line)
    return "\n".join(lines)
