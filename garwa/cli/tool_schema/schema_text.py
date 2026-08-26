"""cli/tool_schema/schema_text.py
Dipecah lebih lanjut dari cli/tool_schema.py.
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
from ... import tool_runtime
from .. import _state as state
from ..json_repair import _repair_invalid_json_escapes
from ..json_repair import _repair_single_quoted_json
from ..json_repair import _repair_unquoted_json_keys
from ..json_repair import _repair_unquoted_json_values



def build_tool_schema_text(full: bool = False) -> str:
    """Bangun blok teks daftar tool untuk system prompt.

    Field "tools" ala OpenAI (lihat build_openai_tools_payload() di bawah)
    SELALU disertakan di tiap request terlepas dari flag apa pun -- skema
    argumen LENGKAP tiap tool (nama, tipe, deskripsi tiap argumen) jadi
    sudah tersedia buat model lewat jalur itu. Menulis ulang skema yang
    SAMA PERSIS sebagai teks di system prompt (perilaku lama fungsi ini)
    berarti mengirim informasi identik DUA KALI setiap giliran -- salah
    satu kontributor terbesar kenapa system prompt bisa membengkak sampai
    puluhan ribu token pada project dengan banyak tool (lihat riwayat
    debugging ContextExceededError: total system prompt sampai ~250rb
    karakter, sementara context_manager sama sekali tidak menghitung field
    "tools" -- lihat CONTEXT_MANAGER_TOOLS_BUDGET di context_manager.py).

    Default (full=False): HANYA nama + deskripsi singkat 1 baris + daftar
    NAMA argumen (tanpa penjelasan tiap argumen) per tool -- cukup untuk
    model tahu tool apa saja yang ada dan kapan memakainya; detail argumen
    persis (tipe, wajib/opsional, deskripsi) dirujuk ke field "tools" JSON
    yang menyertai request ini.

    full=True (fallback): perilaku LAMA, skema argumen lengkap ditulis
    sebagai teks juga -- pakai ini lewat flag CLI --full-tool-schema-text
    kalau server/model TIDAK benar-benar memproses field "tools" (mis.
    server tanpa --jinja, atau model yang tidak dilatih untuk native
    tool-calling) sehingga teks system prompt jadi SATU-SATUNYA sumber
    informasi argumen yang dipunyai model.
    """
    lines = []
    for i, (name, spec) in enumerate(TOOLS.items(), 1):
        s = spec["schema"]
        if full:
            args_desc = "\n".join(f"     - {k}: {v}" for k, v in s["arguments"].items())
            lines.append(f"{i}. {s['name']}\n   Deskripsi: {s['description']}\n   Argumen:\n{args_desc}")
        else:
            arg_names = ", ".join(s["arguments"].keys()) or "(tanpa argumen)"
            lines.append(
                f"{i}. {s['name']} -- {s['description']}\n"
                f"   Argumen: {arg_names} (skema tipe/deskripsi lengkap ada di "
                f"field \"tools\" pada request ini)"
            )
    return "\n\n".join(lines)


def build_openai_tools_payload() -> list:
    """Bangun field 'tools' ala OpenAI function-calling dari TOOLS/tools.py.

    Delegasikan ke tool_runtime.build_openai_tools_payload() yang
    mengekstrak tipe AKURAT per argumen (string/integer/boolean/array/
    object) dari deskripsi schema -- menggantikan perilaku lama yang
    memberi type "string" untuk semua argumen. tools.py tetap melakukan
    validasi/konversi akhir, jadi payload ini hanya panduan bentuk untuk
    model.
    """
    return tool_runtime.build_openai_tools_payload(TOOLS)


def _build_tool_signature(name: str, spec: dict) -> str:
    """Bangun signature ringkas untuk tool, mis. "read_file(path, start_line?, end_line?)".

    Argumen wajib ditulis tanpa tanda tanya, argumen opsional diberi tanda
    '?'. Ini meniru gaya signature opencode dan dipakai untuk katalog/
    pencarian tool.
    """
    s = spec.get("schema", {})
    args = s.get("arguments", {})
    parts = []
    for argname, argdesc in args.items():
        optional = "opsional" in argdesc or "optional" in argdesc
        parts.append(f"{argname}?" if optional else argname)
    return f"{name}({', '.join(parts)})"


def _init_tool_registry() -> None:
    """Isi tool_runtime.REGISTRY (namespace + deskripsi + signature) dari TOOLS.

    Dipanggil sekali saat startup CLI (di main()), setelah TOOLS selesai
    diimpor dan sebelum tool dipakai. Aman dipanggil berulang (idempoten
    terhadap isi, karena register_* menimpa key yang sama).
    """
    reg = tool_runtime.REGISTRY

    for namespace, mapping in state._NAMESPACE_MAP.items():
        reg.register_namespace(namespace, mapping)

    for name, spec in TOOLS.items():
        s = spec.get("schema", {})
        desc = s.get("description", "")
        reg.register_tool(name, desc)
        tool_runtime.register_signature(name, _build_tool_signature(name, spec))
