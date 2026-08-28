"""cli/scanners/common.py
Dipecah lebih lanjut dari cli/scanners.py.
"""
from __future__ import annotations

from pathlib import Path
from shutil import which
from typing import Optional
from ..findings import _redact
from ..process_utils import _run_command



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
