"""tools/security_tool.py
Dipecah otomatis dari tools.py (lihat tools/_state.py untuk state bersama).
"""
import os
import sys
import glob
import shlex
import signal
import subprocess
import difflib
import json
import ast
import base64
import re
import tempfile
import threading
import xml.etree.ElementTree as ET
from urllib.parse import quote
from datetime import datetime, timezone, timedelta

# termios/tty dipakai untuk menyimpan & mengembalikan mode terminal di
# sekitar pemanggilan tool_bash -- jaring pengaman kalau command yang
# dijalankan mengubah mode terminal (mis. stty -echo / raw, program
# interaktif) dan tidak mengembalikannya. Hanya tersedia di POSIX.
try:
    import termios
    _HAS_TERMIOS = True
except ImportError:
    _HAS_TERMIOS = False

import requests

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False

from .. import db as dbmod

try:
    from .. import repo_map as repo_map_mod
except ImportError:
    # repo_map hanya dipakai oleh tool repo_map/outline_file (opsional).
    # Jangan sampai seluruh tools.py (dan cli.py yang meng-import-nya
    # di top-level) gagal start hanya karena modul opsional ini belum ada.
    repo_map_mod = None

try:
    from .. import security as security_mod
except ImportError:
    security_mod = None

try:
    from .. import config as config_mod
except ImportError:
    config_mod = None
from . import _state as state



def tool_security_scan(
    scan_type: str = "all",
    timeout: int = 300,
    dast_target: str = None,
    allow_nonlocal_dast: bool = False,
) -> str:
    """Audit the current working directory with the optional security scanners.

    This is intentionally opt-in: the model should call it only when the user
    asks for a security/dependency/supply-chain audit or for production-readiness
    verification. Missing scanners remain INCOMPLETE; they are never reported
    as clean.
    """
    if security_mod is None:
        return "[ERROR] Modul security.py tidak tersedia pada instalasi CLI."

    try:
        timeout = max(5, min(int(timeout), 1800))
    except (TypeError, ValueError):
        timeout = 300

    mode = str(scan_type or "all").strip().lower()
    allowed = {"all", "sast", "dependencies", "python", "deep",
               "secrets", "iac", "dast", "compliance"}
    if mode not in allowed:
        return f"[ERROR] scan_type tidak valid: {mode}"

    try:
        result = security_mod.security_scan(
            os.path.realpath(state.WORKDIR),
            scan_type=mode,
            timeout=timeout,
            dast_target=dast_target,
            allow_nonlocal_dast=bool(allow_nonlocal_dast),
        )
    except Exception as e:
        return f"[ERROR] Security scan gagal: {type(e).__name__}: {e}"

    # Security.py already bounds scanner output and redacts secrets. Keep a
    # second hard context limit here so a future scanner adapter cannot flood
    # the model context.
    try:
        raw = json.dumps(result, ensure_ascii=False)
        if len(raw) > 120_000:
            result = dict(result)
            result["findings"] = (result.get("findings") or [])[:200]
            result["truncated"] = True
            result["note"] = "Security evidence truncated before entering model context."
    except Exception:
        pass

    return json.dumps(result, ensure_ascii=False, indent=2)
