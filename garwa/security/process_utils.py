"""security/process_utils.py
Dipecah otomatis dari security.py (lihat security/_shared.py untuk konstanta bersama).
"""
from __future__ import annotations

from pathlib import Path
import json
import os
import signal
import subprocess
import time
from typing import Optional
from . import _shared as shared
from .findings import _redact



def _bounded_timeout(timeout: int) -> int:
    try:
        return max(5, min(int(timeout), shared.MAX_TIMEOUT))
    except (TypeError, ValueError):
        return shared.DEFAULT_TIMEOUT


def _terminate_process_tree(proc: subprocess.Popen) -> None:
    """Best-effort process-group termination. Never raises to the caller."""
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGTERM)
            time.sleep(0.2)
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
    except (OSError, ProcessLookupError):
        pass


def _run_command(cmd: list[str], cwd: Path, timeout: int,
                 env: Optional[dict[str, str]] = None) -> tuple[int, str, str, float, bool]:
    if not cmd or len(cmd) > shared.MAX_COMMAND_ARGS:
        raise ValueError("invalid scanner command")
    if any(not isinstance(x, str) or len(x) > shared.MAX_PATH_TEXT for x in cmd):
        raise ValueError("scanner argument too long")
    if not cwd.is_dir():
        raise ValueError("project directory does not exist")

    start = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        stdin=subprocess.DEVNULL,
        shell=False,
        start_new_session=(os.name == "posix"),
        env=env,
    )
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=_bounded_timeout(timeout))
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_tree(proc)
        stdout, stderr = proc.communicate()
    elapsed = time.monotonic() - start

    stdout = stdout[-shared.MAX_STDOUT_CHARS:]
    stderr = _redact(stderr, shared.MAX_STDERR_CHARS)
    return proc.returncode, stdout, stderr, elapsed, timed_out


def _run_json_command(cmd: list[str], cwd: Path, timeout: int):
    rc, stdout, stderr, elapsed, timed_out = _run_command(cmd, cwd, timeout)
    if timed_out:
        return rc, None, stderr, elapsed, True
    if not stdout.strip():
        return rc, {}, stderr, elapsed, False
    try:
        return rc, json.loads(stdout), stderr, elapsed, False
    except json.JSONDecodeError:
        return rc, {"_raw": _redact(stdout, 20_000)}, stderr, elapsed, False
