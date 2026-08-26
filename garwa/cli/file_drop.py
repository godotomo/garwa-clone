"""cli/file_drop.py
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
from .. import tools as tools_module
from . import _state as state
from .colors import C
from .colors import c
from .text_utils import confirm



def _uri_to_path(token: str) -> str:
    """Beberapa file manager (drop dari Nautilus/Finder/Explorer ke
    terminal yang mendukung URI drop) menyisipkan path sebagai
    'file:///a/b%20c.png', bukan path mentah. Konversi ke path filesystem
    biasa kalau polanya cocok; kalau bukan URI, kembalikan token apa
    adanya (tidak ada efek samping untuk teks biasa).
    """
    if token.startswith("file://"):
        return unquote(urlparse(token).path)
    return token


def _extract_dropped_paths(raw_text: str) -> list:
    """Kalau `raw_text` adalah MURNI satu atau lebih path file (hasil
    drag & drop), kembalikan list path absolut yang valid & ada di disk.
    Kembalikan [] kalau tidak cocok pola drop sama sekali -- termasuk
    kalau ada SATU SAJA token yang bukan path file valid, supaya kalimat
    biasa yang kebetulan mengandung '/' (mis. "jelaskan apa itu a/b test")
    tidak salah dianggap sebagai drop.

    shlex.split(posix=True) dipakai karena aturan quoting/escape-nya
    (kutip tunggal/ganda, backslash-escape spasi) sama persis dengan yang
    dipakai kebanyakan terminal saat membangun teks drop -- jadi satu
    parser ini menangani ketiga gaya penyisipan path yang umum ditemui.
    """
    stripped = raw_text.strip()
    if not stripped:
        return []
    try:
        tokens = shlex.split(stripped, posix=True)
    except ValueError:

        return []
    if not tokens:
        return []

    resolved = []
    for token in tokens:
        candidate = os.path.expanduser(_uri_to_path(token))
        if os.path.isfile(candidate):
            resolved.append(os.path.abspath(candidate))
        else:
            return []
    return resolved


def _human_size(num_bytes) -> str:
    if num_bytes is None:
        return "? B"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def _describe_dropped_file(path: str) -> dict:
    try:
        size = os.path.getsize(path)
    except OSError:
        size = None
    ext = os.path.splitext(path)[1].lower()
    mime, _ = mimetypes.guess_type(path)
    return {
        "path": path,
        "size": size,
        "kind": "gambar" if ext in state.IMAGE_EXTENSIONS else "dokumen",
        "mime": mime or "application/octet-stream",
    }


def _is_inside_workdir(path: str, workdir: str) -> bool:
    try:
        wd = os.path.realpath(workdir)
        target = os.path.realpath(path)
        return os.path.commonpath([wd, target]) == wd
    except ValueError:

        return False


def _format_file_attachment_tag(info: dict, status: str) -> str:
    return (
        f'<file_attachment path="{info["path"]}" kind="{info["kind"]}" '
        f'mime="{info["mime"]}" size_bytes="{info["size"]}" status="{status}"/>'
    )


def handle_dropped_files(paths: list, workdir: str) -> str:
    """Proses file(s) hasil drag & drop: klasifikasi workdir vs eksternal,
    minta approval untuk yang eksternal & belum pernah diputuskan, cetak
    ringkasan ke user, lalu kembalikan blok <file_attachment> (satu per
    file) yang akan dikirim ke model sebagai pesan user.
    """
    entries = []  # list of (info, status)
    external_pending = []

    for path in paths:
        info = _describe_dropped_file(path)
        if _is_inside_workdir(path, workdir):
            entries.append((info, "workdir"))
        elif path in state._APPROVED_EXTERNAL_PATHS:
            entries.append((info, "approved_external"))
        elif path in state._DENIED_EXTERNAL_PATHS:
            entries.append((info, "denied_by_user"))
        else:
            external_pending.append(info)

    if external_pending:
        print(c(
            f"[ATTACHMENT] {len(external_pending)} file di luar working "
            "directory terdeteksi:",
            C.YELLOW,
        ))
        for info in external_pending:
            print(c(
                f"  - {info['path']}  ({_human_size(info['size'])}, "
                f"{info['kind']}, {info['mime']})",
                C.DIM,
            ))
        allow = confirm(
            "Izinkan CLI & model membaca file di atas meski berada di luar "
            "working directory?"
        )
        for info in external_pending:
            if allow:
                state._APPROVED_EXTERNAL_PATHS.add(info["path"])

                tools_module.state.ALLOWED_EXTERNAL_PATHS.add(info["path"])
                entries.append((info, "approved_external"))
            else:
                state._DENIED_EXTERNAL_PATHS.add(info["path"])
                entries.append((info, "denied_by_user"))

    blocks = []
    for info, status in entries:
        mark, color = ("✓", C.GREEN) if status != "denied_by_user" else ("✗", C.RED)
        print(c(f"  [{mark}] {info['path']} ({_human_size(info['size'])}, {status})", color))
        if info["kind"] == "gambar" and status != "denied_by_user":
            ext = os.path.splitext(info["path"])[1].lower()
            if ext not in state.VISION_SUPPORTED_EXTENSIONS:
                print(c(
                    f'      (format "{ext or "?"}" kemungkinan tidak didukung decoder '
                    "vision server model -- model kemungkinan cuma menerima metadata, "
                    "bukan isi gambar. Konversi ke PNG/JPEG kalau perlu.)",
                    C.DIM,
                ))
            elif info["size"] and info["size"] > state.MAX_VISION_IMAGE_BYTES:
                print(c(
                    f"      (ukuran {_human_size(info['size'])} melebihi batas "
                    f"{_human_size(state.MAX_VISION_IMAGE_BYTES)} -- model cuma menerima "
                    "metadata, bukan isi gambar. Ubah dengan --max-image-mb.)",
                    C.DIM,
                ))
            else:
                print(c(
                    "      (gambar akan dikirim ke model sebagai vision input)",
                    C.DIM,
                ))
        blocks.append(_format_file_attachment_tag(info, status))
    return "\n".join(blocks)
