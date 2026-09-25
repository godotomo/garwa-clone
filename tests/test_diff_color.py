"""tests/test_diff_color.py

Tes pewarnaan diff (garwa/cli/colors.py::colorize_diff dan helper
`looks_like_diff`). Kontrak yang diuji:

1. Baris '+' diwarnai hijau dan baris '-' merah; header unified
   ('@@', '+++', 'diff --git', ...) diwarnai cyan, bukan hijau/merah.
2. Aman non-TTY: tanpa ANSI sama sekali (output untuk pipe/redirect/NDJSON/
   --json tetap bersih).
3. `looks_like_diff` mencegah output tool BIASA ikut diwarnai -- hasil
   read_file atas markdown berisi bullet "- foo" TIDAK boleh jadi merah.
4. Perilaku lama dipertahankan: teks non-diff (dan non-TTY) tetap dikembalikan
   apa adanya/diredupkan seperti sebelum fitur ini.
"""

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from garwa.cli.colors import C  # noqa: E402
from garwa.cli.colors import colorize_diff  # noqa: E402
from garwa.cli.colors import looks_like_diff  # noqa: E402


_DIFF = (
    "diff --git a/f.py b/f.py\n"
    "index 123..456 100644\n"
    "--- a/f.py\n"
    "+++ b/f.py\n"
    "@@ -1,3 +1,4 @@\n"
    " baris konteks\n"
    "-baris dihapus\n"
    "+baris baru\n"
)


@pytest.fixture
def tty(monkeypatch):
    """Paksa modul colors menganggap stdout TTY => kode ANSI dihasilkan.

    Menambal seam `colors._stdout_is_tty` (bukan `sys.stdout`) karena pytest
    capture mengganti `sys.stdout` per-test, sehingga menambal `sys.stdout`
    tidak andal.
    """
    import garwa.cli.colors as colors

    monkeypatch.setattr(colors, "_stdout_is_tty", lambda: True)


@pytest.fixture
def notty(monkeypatch):
    """Paksa modul colors menganggap stdout BUKAN TTY => tanpa ANSI."""
    import garwa.cli.colors as colors

    monkeypatch.setattr(colors, "_stdout_is_tty", lambda: False)


# --- looks_like_diff ---------------------------------------------------------

def test_looks_like_diff_unified_diff():
    assert looks_like_diff(_DIFF) is True


def test_looks_like_diff_header_pair_only():
    # Tanpa '@@' tapi ada pasangan '--- ' lalu '+++ ' -> tetap dianggap diff.
    assert looks_like_diff("--- a/x\n+++ b/x\n+halo\n") is True


def test_looks_like_diff_false_for_markdown_bullets():
    md = "# Judul\n\n- item pertama\n- item kedua\n+ catatan aneh\n"
    assert looks_like_diff(md) is False


def test_looks_like_diff_false_for_empty():
    assert looks_like_diff("") is False
    assert looks_like_diff(None) is False


# --- non-TTY: bersih tanpa ANSI ---------------------------------------------

def test_colorize_diff_non_tty_no_ansi(notty):
    assert colorize_diff(_DIFF) == _DIFF
    assert "\x1b" not in colorize_diff(_DIFF)


def test_colorize_diff_non_tty_require_diff_false(notty):
    assert colorize_diff(_DIFF, require_diff=False) == _DIFF


# --- TTY: warna per jenis baris ---------------------------------------------

def test_colorize_diff_tty_colors_added_and_removed(tty):
    out = colorize_diff(_DIFF, require_diff=False)
    lines = out.split("\n")
    assert f"{C.GREEN}+baris baru{C.RESET}" in lines
    assert f"{C.RED}-baris dihapus{C.RESET}" in lines
    # Konteks (diawali spasi) diredupkan.
    assert f"{C.DIM} baris konteks{C.RESET}" in lines


def test_colorize_diff_tty_headers_cyan_not_green_red(tty):
    out = colorize_diff(_DIFF, require_diff=False)
    lines = out.split("\n")
    for hdr in ("+++ b/f.py", "--- a/f.py", "@@ -1,3 +1,4 @@", "diff --git a/f.py b/f.py"):
        assert f"{C.CYAN}{hdr}{C.RESET}" in lines, hdr
        assert f"{C.GREEN}{hdr}{C.RESET}" not in lines
        assert f"{C.RED}{hdr}{C.RESET}" not in lines


def test_colorize_diff_tty_prefix_text_kept(tty):
    # Hasil tool edit_file: baris pembuka "[OK] File diedit: ..." lalu diff.
    text = "[OK] File diedit: f.py\n" + _DIFF
    out = colorize_diff(text)
    assert f"{C.DIM}[OK] File diedit: f.py{C.RESET}" in out.split("\n")
    assert f"{C.GREEN}+baris baru{C.RESET}" in out.split("\n")


def test_colorize_diff_dim_context_false_keeps_plain_context(tty):
    out = colorize_diff(_DIFF, dim_context=False, require_diff=False)
    assert " baris konteks" in out.split("\n")
    assert f"{C.DIM} baris konteks{C.RESET}" not in out.split("\n")


# --- penjagaan require_diff: output tool biasa tidak berubah warna ----------

def test_require_diff_default_keeps_non_diff_dim(tty):
    md = "- item markdown\n- item lain\n"
    out = colorize_diff(md)
    # Tidak ada hijau/merah -> hanya diredupkan seperti perilaku lama.
    assert C.GREEN not in out and C.RED not in out
    assert out == f"{C.DIM}{md}{C.RESET}"


def test_require_diff_default_colors_real_diff(tty):
    out = colorize_diff(_DIFF)
    assert f"{C.GREEN}+baris baru{C.RESET}" in out.split("\n")


def test_colorize_diff_empty_string_passthrough(tty):
    assert colorize_diff("") == ""


def test_edit_file_diff_from_difflib_is_detected():
    """Diff yang benar-benar dihasilkan tool edit_file harus dikenali.

    Ini mengunci kontrak antara garwa/tools/filesystem.py (unified_diff dengan
    lineterm="") dan pewarnaan di agent_loop -- tanpa perlu TTY.
    """
    import difflib

    old = "a = 1\nb = 2\nc = 3\n"
    new = "a = 1\nb = 22\nc = 3\n"
    diff = "\n".join(
        difflib.unified_diff(
            old.splitlines(), new.splitlines(),
            fromfile="x.py", tofile="x.py", lineterm="", n=2,
        )
    )
    assert looks_like_diff(diff) is True
    assert "-b = 2" in diff
    assert "+b = 22" in diff
