"""cli/colors.py
Dipecah otomatis dari cli.py (lihat cli/_state.py untuk state bersama).
"""
import re
import sys

try:

    import readline  # noqa: F401
except ImportError:
    readline = None





class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"

    # Variasi bold/bright
    BOLD_RED = "\033[1;31m"
    BOLD_GREEN = "\033[1;32m"
    BOLD_YELLOW = "\033[1;33m"
    BOLD_BLUE = "\033[1;34m"
    BOLD_MAGENTA = "\033[1;35m"
    BOLD_CYAN = "\033[1;36m"
    BOLD_WHITE = "\033[1;37m"

    CODE = "\033[1;38;5;39m"  # biru terang, bold


def _stdout_is_tty() -> bool:
    """True bila stdout adalah terminal nyata.

    Satu-satunya tempat pengecekan TTY di modul ini, supaya perilaku "tanpa
    warna saat output dialihkan" (pipe, redirect, NDJSON, mode --json) hanya
    punya satu sumber kebenaran dan mudah diuji. Tahan error: objek stdout
    pengganti (mis. wrapper gateway/capture) bisa saja tidak punya isatty().
    """
    try:
        return bool(sys.stdout.isatty())
    except Exception:  # noqa: BLE001 - stdout pengganti tanpa isatty()
        return False


def c(text, color):
    if not _stdout_is_tty():
        return text
    return f"{color}{text}{C.RESET}"


# Header/metadata diff unified: baris ini TIDAK boleh dianggap sebagai
# penambahan/penghapusan walau diawali '+' atau '-' (mis. '+++ b/file.py',
# '--- a/file.py', '@@ -1,3 +1,5 @@', 'diff --git', 'index abc..def').
# Dicek LEBIH DULU sebelum aturan '+' / '-'.
_DIFF_HEADER_RE = re.compile(
    r"^(?:\+\+\+|---|@@|diff --git|index |new file|deleted file|old mode|"
    r"new mode|similarity index|dissimilarity index|rename |copy )"
)


def looks_like_diff(text: str) -> bool:
    """True bila `text` benar-benar memuat diff unified.

    Penjaga penting supaya output tool biasa TIDAK ikut diwarnai: hasil
    `read_file` atas file markdown, misalnya, berisi baris bullet "- foo" dan
    itu BUKAN baris yang dihapus. Tanpa penjagaan ini, tiap baris diawali '-'
    akan keliru diwarnai merah.

    Patokan: ada baris `@@ ... @@` (hunk), atau header `diff --git `, atau
    pasangan berurutan `--- ...` lalu `+++ ...`.
    """
    if not text:
        return False
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("@@") or line.startswith("diff --git "):
            return True
        if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            return True
    return False


def colorize_diff(text: str, dim_context: bool = True, require_diff: bool = True) -> str:
    """Warnai baris diff unified: '+' hijau, '-' merah, header cyan, konteks redup.

    Dipakai untuk hasil tool edit file (garwa/tools/filesystem.py menghasilkan
    diff lewat difflib.unified_diff) dan untuk `/git-diff`. Baris yang BUKAN
    bagian diff (mis. baris pembuka "[OK] File diedit: ...") ikut diredupkan
    bila `dim_context=True` supaya diff-nya yang menonjol.

    Bila `require_diff=True` (bawaan) dan teks ternyata BUKAN diff unified
    (lihat `looks_like_diff`), teks dikembalikan apa adanya setelah diredupkan
    seperti perilaku lama -- jadi output tool biasa tidak berubah tampilannya,
    hanya hasil diff yang mendapat warna. Set `require_diff=False` kalau
    pemanggil sudah yakin teksnya diff (mis. hasil `git diff`).

    Aman untuk non-TTY: kalau stdout bukan terminal (pipe, redirect, NDJSON,
    mode --json), teks dikembalikan APA ADANYA tanpa kode ANSI sehingga output
    yang diparse mesin tetap bersih.
    """
    if not text:
        return text
    if not _stdout_is_tty():
        return text
    if require_diff and not looks_like_diff(text):
        return c(text, C.DIM) if dim_context else text
    out = []
    for line in text.split("\n"):
        if not line:
            out.append(line)
            continue
        if _DIFF_HEADER_RE.match(line):
            out.append(f"{C.CYAN}{line}{C.RESET}")
        elif line.startswith("+"):
            out.append(f"{C.GREEN}{line}{C.RESET}")
        elif line.startswith("-"):
            out.append(f"{C.RED}{line}{C.RESET}")
        elif line.startswith("\\ "):  # "\ No newline at end of file"
            out.append(f"{C.YELLOW}{line}{C.RESET}")
        elif dim_context:
            out.append(f"{C.DIM}{line}{C.RESET}")
        else:
            out.append(line)
    return "\n".join(out)


def c_prompt(text, color):
    """Sama seperti c(), tapi khusus untuk string yang dipakai sebagai
    prompt input().

    GNU readline menghitung lebar prompt dari jumlah karakter yang
    dicetak untuk tahu di kolom berapa kursor berada. Kode escape ANSI
    (warna) ikut terhitung sebagai karakter "kelihatan" walau sebenarnya
    tidak menempati ruang di layar -- akibatnya, begitu history
    dipanggil lewat panah atas/bawah (atau kursor digeser kiri/kanan),
    readline salah menghitung posisi dan redraw baris jadi berantakan/
    muncul karakter sisa.

    Fix standar: bungkus bagian non-printing (kode ANSI) dengan
    \\001 ... \\002 supaya readline tahu untuk mengabaikannya saat
    menghitung lebar prompt.
    """
    if not sys.stdout.isatty() or readline is None:
        return text
    return f"\001{color}\002{text}\001{C.RESET}\002"
