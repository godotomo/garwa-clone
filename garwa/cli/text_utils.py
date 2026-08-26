"""cli/text_utils.py
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
from . import _state as state
from .colors import C
from .colors import c_prompt



def _normalize_ws(text: str) -> str:
    """Normalisasi whitespace untuk perbandingan kemiripan: runtuhkan semua
    spasi/tab/newline beruntun jadi satu spasi, dan buang spasi di ujung.
    Ini membuat dua respon yang beda hanya di whitespace dianggap sama.
    """
    return " ".join(text.split())


def _similarity(a: str, b: str) -> float:
    """Skor kemiripan 0..1 antara dua string memakai difflib.SequenceMatcher
    setelah normalisasi whitespace. 1.0 = identik (setelah normalisasi).
    """
    return difflib.SequenceMatcher(None, _normalize_ws(a), _normalize_ws(b)).ratio()


def _detect_repetition(text: str) -> bool:
    """Deteksi pola repetisi/degenerasi di dalam satu respon.

    Mengembalikan True kalau teks yang sudah terkumpul menunjukkan tanda
    loop: baris yang sama muncul minimal REPEAT_MAX_OCCUR kali, ATAU segmen
    terakhir (unit) muncul berkali-kali di seluruh teks, ATAU ada substring
    berulang (n-gram) dengan panjang cukup di posisi mana pun. False positive
    diminimalkan dengan mensyaratkan unit yang cukup panjang
    (REPEAT_MIN_UNIT_LEN) dan kemunculan yang cukup banyak
    (REPEAT_MAX_OCCUR).
    """

    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if lines:
        line_counts = {}
        for ln in lines:

            if len(ln) < 3:
                continue
            line_counts[ln] = line_counts.get(ln, 0) + 1
            if line_counts[ln] >= state.REPEAT_MAX_OCCUR:
                return True

    if len(text) >= state.REPEAT_MIN_UNIT_LEN:
        unit = text[-state.REPEAT_MIN_UNIT_LEN:]
        if text.count(unit) >= state.REPEAT_MAX_OCCUR:
            return True

    if len(text) >= state.REPEAT_NGRAM_MIN_LEN * state.REPEAT_NGRAM_MAX_OCCUR:
        ngram = state.REPEAT_NGRAM_MIN_LEN

        for i in range(0, len(text) - ngram + 1, ngram):
            block = text[i:i + ngram]
            count = 1
            j = i + ngram
            while j + ngram <= len(text) and text[j:j + ngram] == block:
                count += 1
                j += ngram
            if count >= state.REPEAT_NGRAM_MAX_OCCUR:
                return True

    return False


def _terminal_width(text: str) -> int:
    """Lebar terminal sederhana, mengabaikan ANSI dan menangani CJK/combining."""
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    width = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def _truncate_display(text: str, limit: int) -> str:
    if _terminal_width(text) <= limit:
        return text
    out = []
    width = 0
    for ch in text:
        w = 0 if unicodedata.combining(ch) else (
            2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        )
        if width + w > max(1, limit - 1):
            break
        out.append(ch)
        width += w
    return "".join(out).rstrip() + "…"


def _resp_text_utf8(response) -> str:
    """Ambil body response sebagai teks, di-decode UTF-8 secara eksplisit.

    `response.text` (properti bawaan requests) memakai `response.encoding`,
    yang ditebak dari header HTTP -- untuk media type text/*+json/event-stream
    tanpa parameter charset eksplisit, requests bisa menebak ISO-8859-1,
    bukan UTF-8 (lihat catatan panjang di _call_llama_server_stream()).
    server model (endpoint OpenAI-compatible) selalu berbicara UTF-8, jadi di
    sini kita decode langsung dari `response.content` (bytes mentah) dengan
    encoding yang benar, supaya pesan error yang ditampilkan ke user/model
    tidak ikut mojibake gara-gara tebakan encoding yang salah.
    """
    if response is None:
        return ""
    try:
        return response.content.decode("utf-8", errors="replace")
    except Exception:
        return response.text


def confirm(prompt: str) -> bool:
    ans = input(c_prompt(f"  {prompt} [y/N] ", C.YELLOW)).strip().lower()
    return ans in ("y", "yes")
