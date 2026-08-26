"""cli/colors.py
Dipecah otomatis dari cli.py (lihat cli/_state.py untuk state bersama).
"""
import argparse
import base64
import copy
import difflib
import json
import mimetypes
import os
import re
import select
import shlex
import shutil
import sys
import time
import unicodedata
from collections import OrderedDict
from datetime import datetime
from urllib.parse import unquote, urlparse

try:

    import readline  # noqa: F401
except ImportError:
    readline = None

import requests

from ..tools import TOOLS



class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"

    # Variasi bold/bright
    BOLD_RED = "\033[1;31m"
    BOLD_GREEN = "\033[1;32m"
    BOLD_YELLOW = "\033[1;33m"
    BOLD_BLUE = "\033[1;34m"
    BOLD_MAGENTA = "\033[1;35m"
    BOLD_CYAN = "\033[1;36m"
    BOLD_WHITE = "\033[1;37m"

    CODE = "\033[1;38;5;39m"  # biru terang, bold


def c(text, color):
    if not sys.stdout.isatty():
        return text
    return f"{color}{text}{C.RESET}"


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
