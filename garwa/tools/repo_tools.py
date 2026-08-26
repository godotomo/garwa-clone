"""tools/repo_tools.py
Dipecah otomatis dari tools.py (lihat tools/_state.py untuk state bersama).
"""
import os
import sys
import glob
import shlex
import signal
import subprocess
import difflib
import json
import ast
import base64
import re
import tempfile
import threading
import xml.etree.ElementTree as ET
from urllib.parse import quote
from datetime import datetime, timezone, timedelta

# termios/tty dipakai untuk menyimpan & mengembalikan mode terminal di
# sekitar pemanggilan tool_bash -- jaring pengaman kalau command yang
# dijalankan mengubah mode terminal (mis. stty -echo / raw, program
# interaktif) dan tidak mengembalikannya. Hanya tersedia di POSIX.
try:
    import termios
    _HAS_TERMIOS = True
except ImportError:
    _HAS_TERMIOS = False

import requests

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False

from .. import db as dbmod

try:
    from .. import repo_map as repo_map_mod
except ImportError:
    # repo_map hanya dipakai oleh tool repo_map/outline_file (opsional).
    # Jangan sampai seluruh tools.py (dan cli.py yang meng-import-nya
    # di top-level) gagal start hanya karena modul opsional ini belum ada.
    repo_map_mod = None

try:
    from .. import security as security_mod
except ImportError:
    security_mod = None

try:
    from .. import config as config_mod
except ImportError:
    config_mod = None
from . import _state as state
from .filesystem import _coerce_optional_int
from .sandbox import SandboxViolation
from .sandbox import _resolve_readonly



def tool_repo_map(token_budget: int = 1024) -> str:
    if repo_map_mod is None:
        return "[ERROR] Modul repo_map.py tidak tersedia pada instalasi CLI."
    try:
        token_budget = _coerce_optional_int(token_budget, "token_budget")
    except ValueError as e:
        return f"[ERROR] {e}"
    try:
        personalize = set(state._RECENTLY_TOUCHED[:10])
        return repo_map_mod.generate(state.WORKDIR, token_budget=token_budget, personalize_files=personalize)
    except Exception as e:
        return f"[ERROR] Gagal membangun repo map: {e}"


def tool_outline_file(path: str) -> str:
    if repo_map_mod is None:
        return "[ERROR] Modul repo_map.py tidak tersedia pada instalasi CLI."
    try:
        p = _resolve_readonly(path)
    except SandboxViolation as e:
        return f"[ERROR] {e}"
    if not os.path.isfile(p):
        return f"[ERROR] File tidak ditemukan: {p}"
    # SEBELUMNYA: panggilan ini tidak dibungkus try/except sama sekali,
    # tidak konsisten dengan tool_repo_map di atas yang membungkus
    # pemanggilan repo_map_mod serupa. outline_for_file() menyentuh cache
    # SQLite (file_cache di db.py) lewat DB_PATH -- kalau SQLite melempar
    # OperationalError ("database is locked") atau exception lain,
    # sebelumnya itu akan merambat mentah ke pemanggil (dispatcher tool-call
    # di cli.py) alih-alih dikembalikan sebagai pesan "[ERROR] ..." yang
    # konsisten seperti handler lain.
    try:
        outline = repo_map_mod.outline_for_file(p, state.WORKDIR, state.DB_PATH)
    except Exception as e:
        return f"[ERROR] Gagal membuat outline untuk {p}: {type(e).__name__}: {e}"
    if not outline:
        return "[ERROR] Ekstensi file tidak dikenali untuk outline (bukan bahasa yang didukung)."
    return outline
