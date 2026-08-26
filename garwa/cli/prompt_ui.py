"""cli/prompt_ui.py
Prompt input dengan status bar terminal.

Dua jalur, dipilih otomatis saat import:

1. prompt_toolkit tersedia (opsional, lihat requirements.txt):
   Pakai PromptSession dengan `bottom_toolbar` sehingga info status
   (model / ctx / ses / auto) dirender sebagai baris yang MENEMPEL di
   dasar terminal, tepat di bawah tempat mengetik. Paste multi-baris
   ditangani native oleh prompt_toolkit (bracketed paste).

2. prompt_toolkit TIDAK tersedia:
   Fallback aman ke `read_user_input()` (perilaku lama berbasis input()/
   readline). Status bar dicetak sebagai baris redup di atas prompt.

Prioritas keamanan: kalau prompt_toolkit gagal di-import ATAU gagal saat
runtime (mis. terminal non-interaktif), CLI tidak pernah crash -- selalu
jatuh ke jalur fallback yang sudah terbukti.
"""
import sys

# Import opsional prompt_toolkit. Kegagalan apa pun membuat _HAS_PT = False
# dan semua fungsi di bawah otomatis memakai fallback. Ini menjamin CLI
# tetap berjalan walau prompt_toolkit tidak terpasang atau rusak.
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.styles import Style

    _HAS_PT = True
except Exception:  # pragma: no cover - bergantung environment
    _HAS_PT = False

# Perilaku lama (fallback). Di-import di sini, bukan di main, supaya
# main.py cukup memanggil satu fungsi prompt_with_status().
from .paste_input import read_user_input
from .colors import C, c, c_prompt

# Satu PromptSession dipakai ulang antar iterasi supaya history per-sesi
# (panah atas/bawah) tetap bekerja, persis seperti readline.
_session = None

# Style prompt_toolkit untuk toolbar. Warna redup agar tidak menyaingi
# prompt utama.
_TOOLBAR_STYLE = Style.from_dict(
    {
        "bottom-toolbar": "bg:#262626 fg:#8a8a8a",
        "bottom-toolbar.model": "fg:#5fafd7",
        "bottom-toolbar.ctx": "fg:#8787af",
        "bottom-toolbar.ses": "fg:#87875f",
        "bottom-toolbar.tools": "fg:#5faf87",
        "bottom-toolbar.tok": "fg:#d7af87",
        "bottom-toolbar.sandbox": "fg:#d7af5f",
        "bottom-toolbar.sandbox.on": "fg:#5faf87",
        "bottom-toolbar.sandbox.off": "fg:#d75f5f",
        # auto:ON -> hijau (mode approve aktif, tool berjalan terkendali);
        # auto:OFF -> kuning (mode nonaktif, perlu perhatian).
        "bottom-toolbar.auto": "fg:#5faf87",
        "bottom-toolbar.auto.off": "fg:#d7af5f",
        "bottom-toolbar.wd": "fg:#5fafd7",
        "bottom-toolbar.dur": "fg:#af87d7",
        "bottom-toolbar.err": "fg:#d75f5f",
    }
)


def _format_toolbar(status_info: str):
    """Render string status_info jadi HTML berwarna untuk bottom_toolbar.

    Format status_info: `[model] ctx:N ses:ABCDEF12 tools:N sandbox:ON auto:OFF wd:dir dur:1m err:0`.
    Setiap token diberi class warna terpisah supaya mudah dibedakan di toolbar.
    """
    if not status_info:
        return ""
    tokens = status_info.split(" ")
    parts = []
    for tok in tokens:
        if not tok:
            continue
        if tok.startswith("["):
            cls = "model"
        elif tok.startswith("ctx:"):
            cls = "ctx"
        elif tok.startswith("ses:"):
            cls = "ses"
        elif tok.startswith("tools:"):
            cls = "tools"
        elif tok.startswith("tok:"):
            cls = "tok"
        elif tok.startswith("sandbox:"):
            # sandbox:ON -> hijau (terkunci di workdir); sandbox:OFF -> merah
            # (akses terbuka ke seluruh sistem, perlu perhatian).
            cls = "sandbox.off" if tok.endswith("OFF") else "sandbox.on"
        elif tok.startswith("auto:"):
            # auto:ON -> hijau (aktif); auto:OFF -> kuning (nonaktif).
            cls = "auto.off" if tok.endswith("OFF") else "auto"
        elif tok.startswith("wd:"):
            cls = "wd"
        elif tok.startswith("dur:"):
            cls = "dur"
        elif tok.startswith("err:"):
            # err:N -> merah (ada giliran gagal), perhatian.
            cls = "err"
        else:
            cls = ""
        if cls:
            parts.append(f'<bottom-toolbar.{cls}>{tok}</bottom-toolbar.{cls}>')
        else:
            parts.append(f"<bottom-toolbar>{tok}</bottom-toolbar>")
    return "  " + " ".join(parts)


def prompt_with_status(prompt: str, status_info: str) -> str:
    """Terima input user, tampilkan status_info sebagai status bar.

    Mengembalikan string yang diketik user (bisa multi-baris untuk paste).

    - Kalau prompt_toolkit tersedia & stdout TTY: status_info dirender
      sebagai bottom toolbar menempel di dasar terminal.
    - Kalau tidak: status_info dicetak sebagai baris redup di atas prompt,
      lalu input()/readline dipakai seperti biasa.
    """
    if _HAS_PT and sys.stdout.isatty():
        try:
            return _prompt_pt(prompt, status_info)
        except Exception:
            # prompt_toolkit error tak terduga -- jangan crash CLI, jatuh
            # ke fallback yang sudah terbukti.
            pass
    return _prompt_fallback(prompt, status_info)


def _prompt_pt(prompt: str, status_info: str) -> str:
    global _session
    if _session is None:
        _session = PromptSession()
    toolbar = HTML(_format_toolbar(status_info)) if status_info else ""
    return _session.prompt(
        message=HTML(f"<b>{prompt}</b>"),
        bottom_toolbar=toolbar,
        style=_TOOLBAR_STYLE,
        # prompt_toolkit menangani paste multi-baris native; nonaktifkan
        # multiline editing manual supaya Enter tetap submit satu baris
        # seperti readline biasa.
        multiline=False,
    )


def _prompt_fallback(prompt: str, status_info: str) -> str:
    # Cetak baris status redup di atas prompt (perilaku status bar lama).
    if sys.stdout.isatty() and status_info:
        print(c(f"  {status_info}", C.DIM))
    return read_user_input(c_prompt(prompt, C.GREEN))
