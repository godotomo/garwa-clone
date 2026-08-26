"""cli/json_repair.py
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



def _repair_unquoted_json_keys(raw_json: str) -> str:
    """Perbaiki key JSON yang TIDAK dikutip (mis. `{name: "bash", arguments:
    {...}}`) menjadi key yang dikutip (`{"name": "bash", "arguments": {...}}`).

    Kejadian nyata yang mendasari ini: model kecil (mis. Garwa 4B/12B) kadang
    menulis tool_call dengan key tanpa tanda kutip ganda, yang membuat
    json.loads() gagal dengan pesan "Expecting property name enclosed in
    double quotes" (JSONDecodeError di posisi key pertama). Ini beda dari
    kasus backslash escape yang sudah ditangani _repair_invalid_json_escapes()
    -- di sini masalahnya key-nya sendiri tidak dikutip.

    Pendekatan: regex yang mengutip key yang valid (identifier: huruf/angka/
    underscore, tidak diawali digit) yang muncul tepat setelah `{` atau `,`
    dan diikuti `:`. Hanya key yang BELUM dikutip yang diubah (yang sudah
    dikutip `"key":` tidak cocok pola karena regex menuntut identifier
    langsung setelah `{`/`,` tanpa tanda kutip).

    KETERBATASAN yang disengaja (jujur soal batasnya):
      - Regex ini TIDAK bisa membedakan `{`/`,` di dalam string value vs di
        luar struktur. Kalau sebuah string value kebetulan mengandung pola
        `, key:` (mis. teks bebas di dalam argumen), regex bisa salah
        mengutip. Untuk mengurangi risiko ini, fungsi ini HANYA dipanggil
        sebagai fallback SETELAH json.loads() gagal dengan pesan spesifik
        "Expecting property name enclosed in double quotes" (lihat
        extract_tool_call) -- jadi tidak pernah menyentuh JSON yang sudah
        valid. Risiko sisa tetap ada, tapi jauh lebih kecil daripada
        membiarkan seluruh giliran gagal.
      - Key yang mengandung karakter non-identifier (spasi, tanda hubung,
        dst.) TIDAK diperbaiki di sini -- itu di luar cakupan pola umum
        model kecil yang biasanya memakai key sederhana (name/arguments/
        path/command/dst).
    """
    return re.sub(
        r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)',
        r'\1"\2"\3',
        raw_json,
    )


def _repair_unquoted_json_values(raw_json: str) -> str:
    """Perbaiki VALUE string JSON yang TIDAK dikutip (mis. `{"name": bash,
    "arguments": {"command": ls}}`) menjadi value yang dikutip
    (`{"name": "bash", "arguments": {"command": "ls"}}`).

    Kejadian nyata yang mendasari ini: model kecil (mis. Garwa 4B/12B) kadang
    menulis tool_call dengan key DAN value sama-sama tanpa tanda kutip ganda
    (gaya `{name: bash, arguments: {command: ls}}`). _repair_unquoted_json_keys()
    hanya mengutip KEY, sehingga hasilnya `{"name": bash, ...}` -- json.loads()
    masih gagal dengan "Expecting property name enclosed in double quotes"
    (di posisi value pertama). Fungsi ini menutup celah itu dengan mengutip
    value identifier yang tidak dikutip.

    Pendekatan: regex yang mengutip identifier (huruf/angka/underscore, plus
    titik, garis miring, dan tanda hubung untuk path/command) yang muncul
    tepat setelah `:` dan diikuti `,` atau `}`. Value yang SUDAH dikutip
    (`"bash"`) tidak cocok karena regex menuntut identifier langsung setelah
    `:` tanpa tanda kutip. Literal JSON `true`/`false`/`null` dan angka
    sengaja TIDAK dikutip (harus tetap jadi boolean/null/number agar
    json.loads() menerimanya).

    KETERBATASAN yang disengaja (jujur soal batasnya):
      - Regex ini TIDAK bisa membedakan `:` di dalam string value vs di luar
        struktur. Kalau sebuah string value kebetulan mengandung pola
        `: word,` (mis. teks bebas di dalam argumen), regex bisa salah
        mengutip. Untuk mengurangi risiko ini, fungsi ini HANYA dipanggil
        sebagai fallback SETELAH json.loads() gagal (lihat extract_tool_call),
        jadi tidak pernah menyentuh JSON yang sudah valid.
      - Value yang mengandung spasi (mis. `command: ls -la`) TIDAK diperbaiki
        di sini -- itu di luar cakupan pola umum model kecil yang biasanya
        memakai value sederhana (bash/ls/pwd/dst).
    """
    def _quote(m):
        val = m.group(2).strip()
        if val in ("true", "false", "null") or re.fullmatch(r"-?\d+(\.\d+)?", val):
            return m.group(1) + val + m.group(3)
        return m.group(1) + '"' + val + '"' + m.group(3)

    return re.sub(
        r'(:\s*)([^"{}][^,{}]*?)(\s*[,}])',
        _quote,
        raw_json,
    )


def _repair_single_quoted_json(raw_json: str) -> str:
    """Perbaiki JSON yang memakai tanda kutip TUNGGAL untuk key dan/atau
    value string (mis. `{'name': 'bash', 'arguments': {'command': 'ls'}}`)
    menjadi tanda kutip ganda standar JSON.

    Kejadian nyata yang mendasari ini: sebagian model (terutama yang kecil
    atau yang dilatih dengan contoh Python dict) kadang menulis tool_call
    memakai sintaks dict Python -- tanda kutip tunggal untuk key dan value.
    json.loads() lalu gagal dengan pesan "Expecting property name enclosed
    in double quotes" di posisi key pertama (char 1 setelah `{`), yang TIDAK
    ditangani _repair_unquoted_json_keys() (regex-nya menuntut identifier
    langsung setelah `{`/`,` tanpa tanda kutip apa pun).

    Pendekatan: ganti SEMUA tanda kutip tunggal menjadi tanda kutip ganda.
    Ini aman untuk kasus tool-call karena:
      - JSON valid tidak pernah memakai tanda kutip tunggal, jadi fungsi ini
        hanya dipanggil sebagai fallback SETELAH json.loads() gagal (lihat
        extract_tool_call), tidak pernah menyentuh JSON yang sudah valid.
      - Di dalam JSON yang memakai tanda kutip tunggal, tanda kutip tunggal
        hanya muncul sebagai delimiter string (Python dict tidak punya
        escape `\'` yang umum dipakai di dalam string yang dikutip tunggal
        -- kalau ada, itu kasus langka dan akan tetap gagal, jatuh ke
        PARSE_ERROR seperti sebelumnya).
    """
    return raw_json.replace("'", '"')


def _repair_invalid_json_escapes(raw_json: str) -> str:
    """Perbaiki backslash tunggal yang json.loads() secara eksplisit
    tandai sebagai escape tidak valid, satu per satu berdasarkan posisi
    PERSIS dari JSONDecodeError -- bukan menebak lewat pola/regex (lihat
    komentar panjang di atas, termasuk keterbatasannya, untuk alasannya).
    Return teks apa adanya (tidak berubah) kalau errornya bukan soal
    escape, atau kalau posisi error ternyata tidak menunjuk ke backslash
    (defensif terhadap perubahan pesan error antar versi Python).
    """
    text = raw_json
    for _ in range(state._MAX_JSON_ESCAPE_REPAIR_ATTEMPTS):
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError as e:
            if "Invalid \\escape" not in e.msg:
                return text
            pos = e.pos
            if pos < 0 or pos >= len(text) or text[pos] != "\\":
                return text
            text = text[:pos] + "\\" + text[pos:]
    return text


def extract_tool_call(text: str):
    match = state.TOOL_CALL_RE.search(text)
    if not match:
        return None, None
    raw_json = match.group(1)

    if re.fullmatch(r"\s*\{\s*\.\.\.\s*\}\s*", raw_json):
        return None, None
    try:
        obj = json.loads(raw_json)
    except json.JSONDecodeError as e:

        candidates = [raw_json]
        repaired_esc = _repair_invalid_json_escapes(raw_json)
        repaired_uq = _repair_unquoted_json_keys(raw_json)
        repaired_sq = _repair_single_quoted_json(raw_json)
        repaired_uv = _repair_unquoted_json_values(raw_json)
        for cand in (repaired_esc, repaired_uq, repaired_sq, repaired_uv):
            if cand not in candidates:
                candidates.append(cand)

        combined1 = _repair_unquoted_json_keys(repaired_esc)
        combined2 = _repair_invalid_json_escapes(repaired_uq)
        for cand in (combined1, combined2):
            if cand not in candidates:
                candidates.append(cand)

        combined3 = _repair_single_quoted_json(repaired_uq)
        combined4 = _repair_unquoted_json_keys(repaired_sq)
        combined5 = _repair_single_quoted_json(repaired_esc)
        combined6 = _repair_invalid_json_escapes(repaired_sq)
        for cand in (combined3, combined4, combined5, combined6):
            if cand not in candidates:
                candidates.append(cand)

        combined7 = _repair_unquoted_json_values(repaired_uq)
        combined8 = _repair_unquoted_json_keys(repaired_uv)
        combined9 = _repair_unquoted_json_values(repaired_esc)
        combined10 = _repair_unquoted_json_values(repaired_sq)
        combined11 = _repair_single_quoted_json(repaired_uv)
        for cand in (combined7, combined8, combined9, combined10, combined11):
            if cand not in candidates:
                candidates.append(cand)

        obj = None
        for cand in candidates:
            try:
                obj = json.loads(cand)
                break
            except json.JSONDecodeError:
                continue
        if obj is None:
            return "PARSE_ERROR", f"{e} | raw_json={raw_json!r}"

    name = obj.get("name")
    arguments = obj.get("arguments", {})

    if isinstance(name, str) and name.lstrip().startswith("{"):
        try:
            inner = json.loads(name)
        except json.JSONDecodeError:
            inner = None
        if isinstance(inner, dict) and "name" in inner:
            name = inner.get("name")
            inner_arguments = inner.get("arguments", arguments)
            if isinstance(inner_arguments, dict):
                arguments = inner_arguments

    if not isinstance(arguments, dict):
        return "PARSE_ERROR", "arguments harus berupa objek JSON"
    return name, arguments
