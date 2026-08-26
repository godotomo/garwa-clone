"""cli/llm_client/openrouter_cache.py
Dipecah lebih lanjut dari cli/llm_client.py.
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
from ..colors import C
from ..colors import c
from ..llm_errors import LlamaServerStreamError
from ..llm_errors import RepetitionLoopError
from ..llm_errors import TruncatedGenerationError
from ..llm_errors import _parse_context_exceeded
from ..markdown_render import MarkdownTerminalRenderer
from ..markdown_render import ReasoningPreview
from ..stream_parse import _extract_stream_content
from ..stream_parse import _extract_stream_finish_reason
from ..stream_parse import _extract_stream_reasoning
from ..stream_parse import _extract_stream_usage
from ..stream_parse import _flush_visible_text
from ..stream_parse import _print_stream_text
from ..stream_parse import _stream_visible_text
from ..text_utils import _detect_repetition
from ..text_utils import _resp_text_utf8
from ..tool_schema import _accumulate_stream_tool_calls
from ..tool_schema import _native_tool_calls_to_blocks
from ..tool_schema import build_openai_tools_payload



def _wants_openrouter_cache_control(url: str, model: str) -> bool:
    """True kalau request ini menuju OpenRouter DAN model yang dipakai
    termasuk provider yang mewajibkan breakpoint cache_control eksplisit
    (lihat komentar panjang di atas OPENROUTER_EXPLICIT_CACHE_PREFIXES).

    Dicek per-request (bukan sekali di startup seperti deteksi llama.cpp)
    karena `model` bisa berbeda-beda kalau CLI ini nanti mendukung ganti
    model di tengah sesi -- tidak ada state global yang perlu disinkronkan.
    """
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    if "openrouter.ai" not in host:
        return False
    model_lower = (model or "").lower()
    return any(model_lower.startswith(p) for p in state.OPENROUTER_EXPLICIT_CACHE_PREFIXES)


def _build_openrouter_cache_marker(ttl: str = None) -> dict:
    """Bangun dict marker "cache_control" ala Anthropic/OpenRouter.

    `ttl` opsional ("5m" atau "1h") -- kalau tidak diisi, field "ttl" tidak
    disertakan sama sekali dan provider memakai TTL default mereka (~5
    menit sesuai dokumentasi OpenRouter). Parameter ini sengaja ada supaya
    caller di masa depan bisa memilih TTL lebih panjang untuk sesi yang
    sering jeda lama, tanpa perlu mengubah signature fungsi lain.
    """
    marker = {"type": "ephemeral"}
    if ttl:
        marker["ttl"] = ttl
    return marker


def _apply_cache_marker_to_message(msg: dict, marker: dict) -> None:
    """Tempel `marker` sebagai breakpoint ke SATU pesan, IN PLACE.

    Caller WAJIB sudah memberi `msg` yang aman diubah (mis. hasil
    copy.deepcopy) -- fungsi ini sengaja memutasi supaya tidak perlu
    membangun dict/list baru berulang di pemanggil.

    Tiga kasus bentuk `content` yang ditangani:
    - String non-kosong: dibungkus jadi array-of-parts SATU blok dengan
      cache_control di blok itu. Sengaja satu blok saja supaya otomatis
      jadi "blok terakhir" pesan tsb -- aturan OpenRouter/Anthropic
      mewajibkan cache_control cuma di blok terakhir tiap pesan (menaruh
      di semua blok pesan multi-blok bisa melebihi batas 4 breakpoint per
      request dan merusak inferensi, lihat riset caching sebelumnya).
    - List (sudah array-of-parts, mis. pesan vision/multipart): marker
      ditempel ke BLOK TERAKHIR SAJA (bukan seluruh blok), dengan alasan
      sama seperti di atas. Kalau blok terakhir bukan dict (bentuk yang
      tidak terduga), dilewati -- lebih aman diam daripada crash/merusak
      struktur yang tidak dikenal.
    - String kosong / None / tipe lain yang tidak dikenal: dilewati begitu
      saja. Tidak ada yang berharga untuk di-cache, dan memaksa bentuk
      pada isi yang tidak terduga lebih berisiko daripada tidak berbuat
      apa-apa untuk pesan itu.
    """
    content = msg.get("content")
    if isinstance(content, str) and content:
        msg["content"] = [{"type": "text", "text": content, "cache_control": marker}]
    elif isinstance(content, list) and content:
        last_block = content[-1]
        if isinstance(last_block, dict):
            last_block["cache_control"] = marker


def _apply_openrouter_cache_control(messages: list, cache_ttl: str = None) -> list:
    """Terapkan strategi "system_and_3" (lihat komentar
    OPENROUTER_CACHE_TAIL_BREAKPOINTS di atas): breakpoint di system prompt
    (kalau ada) + di sampai 3 pesan NON-system terakhir, memakai penuh
    jatah OPENROUTER_MAX_CACHE_BREAKPOINTS (4) yang diizinkan provider
    Anthropic-compatible.

    Robust terhadap kasus tepi:
    - `messages` kosong -> dikembalikan apa adanya.
    - Kurang dari 3 pesan non-system -> breakpoint dipasang ke yang ada
      saja (tidak error, tidak memaksa index di luar jangkauan).
    - Tidak ada pesan role="system" sama sekali -> seluruh 4 breakpoint
      dipakai untuk pesan non-system terakhir.
    - Pesan dengan `content` None/kosong/tipe tak terduga -> dilewati oleh
      _apply_cache_marker_to_message(), tidak membuat fungsi ini gagal.

    TIDAK memutasi `messages` asli sama sekali -- deep-copy dulu (`copy.
    deepcopy`) sebelum memutasi apa pun, mengikuti pola Hermes Agent, jadi
    aman walau caller masih memegang referensi ke `messages` yang sama
    setelah pemanggilan ini (mis. untuk logging/debug).
    """
    if not messages:
        return messages

    out = copy.deepcopy(messages)
    marker = _build_openrouter_cache_marker(cache_ttl)
    breakpoints_used = 0

    if out[0].get("role") == "system":
        _apply_cache_marker_to_message(out[0], marker)
        breakpoints_used += 1

    remaining = state.OPENROUTER_MAX_CACHE_BREAKPOINTS - breakpoints_used
    if remaining > 0:
        non_system_idx = [i for i, m in enumerate(out) if m.get("role") != "system"]
        tail_count = min(remaining, state.OPENROUTER_CACHE_TAIL_BREAKPOINTS)
        for idx in non_system_idx[-tail_count:]:
            _apply_cache_marker_to_message(out[idx], marker)

    return out
