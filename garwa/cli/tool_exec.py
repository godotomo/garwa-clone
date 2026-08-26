"""cli/tool_exec.py
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
from .. import tool_runtime
from . import _state as state
from .colors import C
from .colors import c
from .mojibake import _format_mojibake_error
from .mojibake import scan_tool_arguments_for_mojibake
from .text_utils import confirm



def execute_tool(name: str, arguments: dict, auto_approve: bool) -> str:

    resolved_name = tool_runtime.REGISTRY.resolve(name)
    if resolved_name not in TOOLS:
        return f"[ERROR] Tool '{name}' tidak dikenal. Tool yang tersedia: {', '.join(TOOLS.keys())}"

    name = resolved_name
    spec = TOOLS[name]

    # Hitung tool call yang benar-benar dieksekusi (bukan yang gagal parse)
    # untuk ditampilkan di status bar (tools:N).
    state.TOOL_CALL_TOTAL += 1

    if isinstance(arguments, dict) and "_raw" in arguments:
        print(c(f"  → memanggil tool: {name}({json.dumps(arguments, ensure_ascii=False)})", C.CYAN))
        raw_preview = arguments.get("_raw")
        raw_preview = "" if raw_preview is None else str(raw_preview)
        if len(raw_preview) > 400:
            raw_preview = raw_preview[:400] + "...(dipotong)"
        error_msg = (
            f"[ERROR] Argumen untuk tool '{name}' bukan JSON yang valid. "
            "Ini BUKAN cuma salah format (key tanpa kutip, escape salah, "
            "dst -- semua sudah dicoba diperbaiki otomatis dan tetap "
            "gagal); kemungkinan besar generation Anda TERPOTONG di "
            "tengah menulis argumen (mis. kehabisan batas token output "
            "sebelum selesai menulis sebuah string panjang). Argumen "
            f"mentah yang diterima: {raw_preview!r}\n"
            "Kirim ulang PANGGILAN TOOL INI dari awal dengan argumen JSON "
            "yang LENGKAP dan valid. Kalau argumen yang panjang (mis. "
            "'new_str'/'content') adalah penyebabnya, pertimbangkan "
            "memecahnya jadi beberapa panggilan edit yang lebih kecil "
            "supaya tidak terpotong lagi."
        )
        print(c(f"  {error_msg}", C.RED))
        return error_msg

    mojibake_report = scan_tool_arguments_for_mojibake(arguments)
    if mojibake_report:
        error_msg = _format_mojibake_error(name, mojibake_report)
        print(c(f"  {error_msg}", C.RED))
        return error_msg

    print(c(f"  → memanggil tool: {name}({json.dumps(arguments, ensure_ascii=False)})", C.CYAN))

    destructive = spec["destructive"]
    if callable(destructive):
        destructive = destructive(arguments)

    needs_confirm = destructive == "force" or (destructive and not auto_approve)
    if needs_confirm:
        if not confirm(f"Izinkan eksekusi tool '{name}' di atas?"):
            return "[DITOLAK] User menolak eksekusi tool ini."

    return tool_runtime.run_tool_with_runtime(
        name=name,
        arguments=arguments,
        handler=spec["handler"],
        index=state._tool_call_index.get(),
        hooks=tool_runtime.DEFAULT_HOOKS,
    )
