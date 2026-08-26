"""cli/skills/discovery.py
Dipecah lebih lanjut dari cli/skills.py.
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
from ..tool_schema import build_tool_schema_text
from .frontmatter import _discover_skill_supporting_files
from .frontmatter import _parse_skill_frontmatter



def discover_skills(skills_dir: str):
    """Scan <skills_dir>/*/SKILL.md, kembalikan list dict
    {name, description, path, supporting_files}.

    supporting_files adalah dict {"references": [...], "scripts": [...],
    "assets": [...]} berisi path absolut file-file pendukung yang ada di
    dalam folder skill tsb (bisa kosong {} kalau skill hanya punya
    SKILL.md tanpa subfolder tambahan).

    Diam-diam mengembalikan [] kalau folder skills tidak ada -- fitur ini
    opsional, CLI tetap jalan normal tanpa skills terpasang.
    """
    results = []
    if not os.path.isdir(skills_dir):
        return results
    for entry in sorted(os.listdir(skills_dir)):
        skill_dir = os.path.join(skills_dir, entry)
        skill_md = os.path.join(skill_dir, "SKILL.md")
        if not os.path.isfile(skill_md):
            continue
        fm = _parse_skill_frontmatter(skill_md)
        if not fm or not fm.get("name") or not fm.get("description"):
            continue
        results.append({
            "name": fm["name"],
            "description": fm["description"],

            "path": skill_md,
            "supporting_files": _discover_skill_supporting_files(skill_dir),
        })
    return results


def _shorten_skill_description(desc: str, limit: int = 140) -> str:
    """Ringkas deskripsi skill jadi satu baris pendek untuk system prompt.

    Deskripsi skill di SKILL.md bisa sangat panjang (paragraf multi-kalimat,
    mis. crypto-trading-analyst yang memuat daftar lengkap pemicu). Untuk
    system prompt, model hanya perlu tahu *apa* skill itu dan *kapan* harus
    membacanya -- detail lengkap tetap tersedia lewat tool read_file pada
    SKILL.md itu sendiri (progressive disclosure). Memotong deskripsi di
    sini menghemat ribuan token per request tanpa kehilangan kemampuan
    model menemukan skill yang relevan.
    """
    desc = " ".join(desc.split())
    if len(desc) <= limit:
        return desc
    cut = desc[:limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(".,;: ") + "…"


def _build_skills_section(skills_dir: str) -> str:
    skills = discover_skills(skills_dir)
    if not skills:
        return ""
    lines = [
        "",
        "SKILLS TERSEDIA (panduan best-practice untuk task tertentu):",
        "Sebelum membuat/mengedit file dengan tipe di bawah, WAJIB baca dulu "
        "SKILL.md yang relevan lewat tool read_file -- di dalamnya ada daftar "
        "pustaka yang harus/tidak boleh dipakai, jebakan umum, dan langkah "
        "verifikasi wajib. Jangan lewati langkah ini walau Anda merasa sudah "
        "tahu cara membuat file tipe tsb.",
        "",
    ]
    for sk in skills:
        lines.append(
            f"- {sk['name']}: {_shorten_skill_description(sk['description'])}  "
            f"(baca: {sk['path']})"
        )
    return "\n".join(lines) + "\n"
