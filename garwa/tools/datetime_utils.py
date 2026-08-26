"""tools/datetime_utils.py
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



def _now_wib() -> datetime:
    return datetime.now(state._WIB)


def tool_local_now() -> str:
    """Kembalikan tanggal dan jam saat ini dalam WIB (UTC+7).

    Tool ini dipakai sebelum pencarian berita relatif seperti "hari ini",
    "terbaru", "saat ini", "kemarin", atau "minggu ini", dan untuk kebutuhan
    lain yang membutuhkan tanggal/waktu aktual. Nilai berasal dari clock mesin
    yang menjalankan CLI, bukan dari pengetahuan model.
    """
    now = _now_wib()
    hari = state._HARI_ID[now.weekday()]
    return f"{hari}, {now.strftime('%Y-%m-%d %H:%M:%S')} WIB (UTC+7)"
