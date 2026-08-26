"""cli/overnight/tee_stdout.py
Dipecah lebih lanjut dari cli/overnight.py.
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
from ..agent_loop import run_agent_loop
from ..auto_mode import parse_tasks_file
from ..colors import C
from ..colors import c
from ..llm_client import _apply_detected_n_ctx
from ..llm_client import check_llama_server_connection
from ..skills import build_system_prompt



class _TeeStdout:
    """Duplikasi semua yang ditulis ke stdout juga ke file log.

    Kode ANSI (warna/cursor movement) dibuang sebelum ditulis ke file supaya
    file log overnight tetap bersih dan bisa dibaca ulang keesokan harinya.
    Terminal asli tetap menerima output apa adanya (termasuk warna).
    """

    _ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

    def __init__(self, real, log_file):
        self._real = real
        self._log = log_file

    def write(self, text):
        self._real.write(text)
        try:
            self._log.write(self._ANSI_RE.sub("", text))
        except Exception:
            pass
        return len(text)

    def flush(self):
        self._real.flush()
        try:
            self._log.flush()
        except Exception:
            pass

    def isatty(self):
        return self._real.isatty()

    def __getattr__(self, name):
        return getattr(self._real, name)
