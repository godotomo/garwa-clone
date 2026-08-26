"""cli/scanners/common.py
Dipecah lebih lanjut dari cli/scanners.py.
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
from .. import _shared as shared
from ..findings import Finding
from ..findings import _finding_id
from ..findings import _redact
from ..findings import _safe_rel
from ..findings import _severity
from ..process_utils import _run_command
from ..process_utils import _run_json_command



def _base_result(scanner: str, status: str, **extra) -> dict:
    result = {
        "scanner": scanner,
        "status": status,
        "findings": [],
        "coverage": "unknown",
    }
    result.update(extra)
    return result


def _unavailable(scanner: str, executable: str) -> dict:
    return _base_result(
        scanner, "unavailable",
        executable=executable,
        reason=f"{executable} executable not found",
    )


def _scanner_version(executable: str) -> Optional[str]:
    path = which(executable)
    if not path:
        return None
    try:
        rc, out, _, _, _ = _run_command([path, "--version"], Path.cwd(), 10)
        if rc == 0:
            return _redact(out, 300).strip()
    except Exception:
        pass
    return None
