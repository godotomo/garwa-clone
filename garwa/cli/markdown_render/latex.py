"""cli/markdown_render/latex.py
Dipecah lebih lanjut dari cli/markdown_render.py.
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
from ..text_utils import _terminal_width
from ..text_utils import _truncate_display



def _latex_to_unicode(text: str) -> str:
    """Konversi subset LaTeX umum ke Unicode terminal.

    Hanya dipanggil pada teks biasa. Inline-code dan fenced-code sudah
    diproteksi sebelum fungsi ini dipanggil.
    """
    if not text:
        return text

    def convert_math(match):
        expr = match.group(1)

        for command, value in sorted(state.LATEX_UNICODE.items(), key=lambda x: -len(x[0])):
            expr = expr.replace(command, value)

        supers = str.maketrans("0123456789+-=()nix", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱˣ")
        subs = str.maketrans("0123456789+-=()aehijklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ")

        def sup(m):
            val = m.group(2) or m.group(3)
            return val.translate(supers)

        def sub(m):
            val = m.group(2) or m.group(3)
            return val.translate(subs)

        expr = re.sub(r"\^(\{([^{}]+)\}|([A-Za-z0-9+\-=()]+))", sup, expr)
        expr = re.sub(r"_(\{([^{}]+)\}|([A-Za-z0-9+\-=()]+))", sub, expr)

        expr = expr.replace("{", "").replace("}", "")

        expr = re.sub(r"\\([A-Za-z]+)", r"\1", expr)
        return expr

    text = re.sub(r"\$([^$\n]+)\$", convert_math, text)
    text = re.sub(r"\\\(([^)\n]+)\\\)", convert_math, text)
    return text
