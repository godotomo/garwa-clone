"""
cli package
Antarmuka command-line interaktif Garwa -- dipecah dari cli.py (satu file
~4700 baris) menjadi beberapa modul/subpackage kecil per tanggung jawab.

State module-level (banyak konstanta + _tool_call_index) ada di
cli/_state.py dan diakses sebagai `state.NAMA` di semua submodule supaya
perilakunya identik dengan file tunggal sebelum dipecah.
"""

from . import _state as state

# Aktifkan bracketed-paste readline SEKALI saat paket ini diimpor --
# persis seperti perilaku cli.py asli.
if state.readline is not None:
    try:
        state.readline.parse_and_bind("set enable-bracketed-paste on")
    except Exception:
        pass

from .main import main  # noqa: E402  (re-export entry point)

__all__ = ["main"]
