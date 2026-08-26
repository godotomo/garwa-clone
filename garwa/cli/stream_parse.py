"""cli/stream_parse.py
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
from ._state import TOOL_CLOSE, TOOL_OPEN
from .llm_errors import LlamaServerStreamError



def _extract_stream_content(obj: dict) -> str:
    """Ambil content dari chunk OpenAI-compatible server model.

    Raise LlamaServerStreamError kalau chunk berisi field 'error' eksplisit,
    supaya caller bisa menampilkannya alih-alih diam-diam melewatinya.
    """
    if isinstance(obj.get("error"), (dict, str)):
        err = obj["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else err
        raise LlamaServerStreamError(str(msg))

    choices = obj.get("choices") or []
    if not choices:
        return ""
    choice = choices[0] or {}
    delta = choice.get("delta") or {}
    content = delta.get("content")
    if content is None:

        message = choice.get("message") or {}
        content = message.get("content")
    return content if isinstance(content, str) else ""


def _extract_stream_reasoning(obj: dict) -> str:
    """Ambil delta.reasoning_content ("chain of thought") dari chunk SSE,
    kalau backend mengirimkannya sebagai field terpisah dari 'content'
    (mis. server model dengan model reasoning seperti Garwa/DeepSeek-R1).

    Field ini TIDAK termasuk jawaban akhir -- tidak pernah ditambahkan ke
    full_parts/assistant_text, hanya dipakai untuk preview live sementara
    supaya user tahu model sedang berpikir, bukan macet.
    """
    choices = obj.get("choices") or []
    if not choices:
        return ""
    choice = choices[0] or {}
    delta = choice.get("delta") or {}
    reasoning = delta.get("reasoning_content")
    if reasoning is None:
        message = choice.get("message") or {}
        reasoning = message.get("reasoning_content")
    return reasoning if isinstance(reasoning, str) else ""


def _extract_stream_finish_reason(obj: dict):
    """Ambil choices[0].finish_reason dari chunk SSE, kalau ada.

    Chunk yang HANYA berisi field "usage" (trailer akhir stream, dipakai
    sebagian backend seperti contoh nyata: {"choices": [], "usage": {...}})
    punya "choices" kosong -- return None untuk kasus itu, BUKAN string
    kosong, supaya caller bisa membedakan "belum ada info" dari "finish_reason
    memang eksplisit None/'stop'".
    """
    choices = obj.get("choices") or []
    if not choices:
        return None
    choice = choices[0] or {}
    fr = choice.get("finish_reason")
    return fr if isinstance(fr, str) else None


def _extract_stream_usage(obj: dict):
    """Ambil field 'usage' dari chunk SSE kalau ada dan berbentuk dict.

    Beberapa backend OpenAI-compatible mengirim usage TERPISAH di chunk
    trailer (choices kosong) setelah chunk konten terakhir -- lihat contoh
    di TruncatedGenerationError. Dipakai murni untuk pesan diagnostik
    (jumlah completion_tokens/reasoning_tokens), tidak memengaruhi parsing
    konten sama sekali.
    """
    usage = obj.get("usage")
    return usage if isinstance(usage, dict) else None


def _stream_visible_text(state: dict, text: str) -> str:
    """Return only user-visible text while hiding tool_call blocks.

    Handles <tool_call> / </tool_call> markers split across arbitrary SSE
    chunks. `state` is mutated in-place and contains:
      - in_tool: currently inside a tool_call block
      - pending: suffix held back so a marker split across chunks is safe
      - ws_hold: run of trailing whitespace/newline yang DITAHAN (belum
        dicetak) sampai jelas apakah setelahnya ada teks lagi (baru
        dicetak) atau langsung <tool_call> (dibuang) -- lihat komentar di
        bawah kenapa ini perlu.

    CATATAN soal ws_hold: model sering menulis newline ganda (baris kosong)
    tepat sebelum blok <tool_call>, mis. "...selanjutnya.\\n\\n<tool_call>".
    Tanpa penahanan ini, newline ganda tsb ikut ter-print sebagai baris
    kosong SEBELUM baris "→ memanggil tool: ..." dicetak (lihat
    execute_tool()), membuat jarak antara teks penjelasan model dan
    pemanggilan tool terasa terlalu jauh. Whitespace di akhir SETIAP
    potongan teks ditahan satu langkah; begitu jelas potongan berikutnya
    adalah <tool_call>, whitespace yang ditahan itu DIBUANG (bukan
    dicetak) -- kalau ternyata bukan <tool_call> (ada teks lain
    menyusul), whitespace itu digabung kembali di depan teks berikutnya
    sehingga urutan/isi keseluruhan tetap sama persis seperti sebelumnya.
    """
    if not text:
        return ""

    state["pending"] += text
    out = []

    while state["pending"]:
        pending = state["pending"]

        if state["in_tool"]:
            close_at = pending.find(TOOL_CLOSE)
            if close_at >= 0:

                state["pending"] = pending[close_at + len(TOOL_CLOSE):]
                state["in_tool"] = False
                continue

            keep = len(TOOL_CLOSE) - 1
            if len(pending) > keep:
                state["pending"] = pending[-keep:]
            break

        open_at = pending.find(TOOL_OPEN)
        if open_at >= 0:
            if open_at:

                combined = state.get("ws_hold", "") + pending[:open_at]
                state["ws_hold"] = ""
                stripped = combined.rstrip("\n\r\t ")
                if stripped:
                    out.append(stripped)
            else:

                state["ws_hold"] = ""
            state["pending"] = pending[open_at + len(TOOL_OPEN):]
            state["in_tool"] = True
            continue

        keep = len(TOOL_OPEN) - 1
        if len(pending) > keep:
            chunk = pending[:-keep]
            state["pending"] = pending[-keep:]
            combined = state.get("ws_hold", "") + chunk
            stripped = combined.rstrip("\n\r\t ")
            state["ws_hold"] = combined[len(stripped):]
            if stripped:
                out.append(stripped)
        break

    return "".join(out)


def _flush_visible_text(state: dict) -> str:
    """Flush remaining non-tool text at end of stream."""
    if state["in_tool"]:

        state["pending"] = ""
        state["ws_hold"] = ""
        return ""

    text = state.get("ws_hold", "") + state["pending"]
    state["pending"] = ""
    state["ws_hold"] = ""
    return text


def _print_stream_text(text: str, state: dict) -> None:
    if not text:
        return
    state["renderer"].feed(text)
    state["started"] = state["renderer"].prefix_written
