"""cli/vision/image_encoding.py
Dipecah lebih lanjut dari cli/vision.py.
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

from ...tools import TOOLS
from .. import _state as state
from ..file_drop import _human_size
from .cache import _vision_cache_get
from .cache import _vision_cache_put



def _encode_image_for_vision(path: str, declared_mime: str):
    """Coba baca & base64-encode satu file gambar untuk dikirim sebagai
    content block bergaya OpenAI vision (`{"type": "image_url", ...}`) ke
    server model.

    Mengembalikan tuple (data_url, error_message): salah satu SELALU None.
    TIDAK PERNAH melempar exception -- setiap kegagalan (file hilang,
    permission, format tak didukung, kosong, kelebihan ukuran, dll) balik
    sebagai error_message berbentuk teks manusiawi, supaya caller bisa
    tetap mengirim sisa request tanpa gambar itu (fail-soft), bukan bikin
    seluruh giliran chat gagal gara-gara satu lampiran bermasalah.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in state.VISION_SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(state.VISION_SUPPORTED_EXTENSIONS))
        return None, (
            f'format "{ext or "(tanpa ekstensi)"}" tidak didukung decoder vision '
            f"server model (stb_image). Format yang didukung: {supported}. "
            "Konversi dulu ke PNG/JPEG kalau ingin model melihat isinya."
        )

    try:
        st = os.stat(path)
    except OSError as e:
        return None, f"file tidak bisa diakses ({e.strerror or e})"

    if not os.path.isfile(path):
        return None, "path bukan file biasa (mungkin sudah dihapus/dipindah)"

    if st.st_size == 0:
        return None, "file berukuran 0 byte (kosong)"

    if st.st_size > state.MAX_VISION_IMAGE_BYTES:
        return None, (
            f"ukuran {_human_size(st.st_size)} melebihi batas "
            f"{_human_size(state.MAX_VISION_IMAGE_BYTES)} (ubah dengan --max-image-mb)"
        )

    cache_key = (path, getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)), st.st_size)
    cached = _vision_cache_get(cache_key)
    if cached is not None:
        return cached, None

    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        return None, f"gagal membaca file ({e.strerror or e})"
    except MemoryError:
        return None, "file terlalu besar untuk dimuat ke memori"

    if not raw:
        return None, "file terbaca tapi isinya kosong"

    mime = declared_mime if declared_mime in state._VISION_MIME_MAP.values() else None
    if not mime:
        mime = state._VISION_MIME_MAP.get(ext, "application/octet-stream")

    try:
        b64 = base64.b64encode(raw).decode("ascii")
    except Exception as e:  # pragma: no cover - base64 encode praktis tidak pernah gagal
        return None, f"gagal encode base64 ({e})"

    data_url = f"data:{mime};base64,{b64}"
    _vision_cache_put(cache_key, data_url)
    return data_url, None
