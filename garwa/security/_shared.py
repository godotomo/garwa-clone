"""
security/_shared.py
Konstanta bersama yang dipakai di beberapa modul scanner (hasil pecahan
security.py). Bukan state mutable-dari-luar (tidak ada yang mereassign
atribut modul ini dari luar paket) -- cukup diimpor sebagai `shared.NAMA`
supaya satu definisi dipakai bersama tanpa duplikasi nilai.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from pathlib import Path
from urllib.parse import urlparse
from ipaddress import ip_address
from shutil import which
import hashlib
import json
import os
import re
import signal
import subprocess
import tempfile
import time
from typing import Any, Callable, Optional


DEFAULT_TIMEOUT = 300
MAX_TIMEOUT = 1800
MAX_FINDINGS = 500
MAX_EVIDENCE_CHARS = 100_000
MAX_STDOUT_CHARS = 2_000_000
MAX_STDERR_CHARS = 20_000
MAX_COMMAND_ARGS = 64
MAX_PATH_TEXT = 2048
_SEV = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "error": "HIGH",
    "medium": "MEDIUM",
    "warning": "MEDIUM",
    "low": "LOW",
    "info": "INFO",
    "informational": "INFO",
    "unknown": "UNKNOWN",
}
_SEV_RANK = {"UNKNOWN": 0, "INFO": 1, "LOW": 2, "MEDIUM": 3, "HIGH": 4, "CRITICAL": 5}
_CONF_RANK = {"UNKNOWN": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
_SECRET_PATTERNS = [
    (re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s\"'`]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)(['\"]?)[^\s,;'\"`]+"), r"\1\2[REDACTED]"),
    (re.compile(r"(?i)((?:password|passwd|secret|token|access[_-]?key)\s*[=:]\s*)(['\"]?)[^\s,'\"]+"),
     r"\1\2[REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AKIA****************"),
    (re.compile(r"-----BEGIN [^-]+ PRIVATE KEY-----.*?-----END [^-]+ PRIVATE KEY-----", re.S),
     "[PRIVATE KEY REDACTED]"),
]
