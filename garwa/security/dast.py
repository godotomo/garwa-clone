"""security/dast.py
Dipecah otomatis dari security.py (lihat security/_shared.py untuk konstanta bersama).
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
from .findings import Finding
from .findings import _finding_id
from .findings import _redact
from .findings import _severity
from .process_utils import _run_command
from .scanners import _base_result
from .scanners import _scanner_version
from .scanners import _unavailable



def _is_private_or_loopback_host(host: str) -> bool:
    if not host:
        return False
    h = host.lower().rstrip(".")
    if h in {"localhost", "localhost.localdomain"}:
        return True
    try:
        ip = ip_address(h)
        return ip.is_loopback or ip.is_private or ip.is_link_local
    except ValueError:

        return False


def validate_dast_target(target: str, allow_nonlocal: bool = False) -> tuple[bool, str]:
    if not target or len(target) > 2048:
        return False, "DAST target wajib berupa URL yang eksplisit."
    try:
        u = urlparse(target)
    except ValueError:
        return False, "DAST target URL tidak valid."
    if u.scheme not in {"http", "https"} or not u.hostname:
        return False, "DAST hanya mendukung http/https URL."
    if u.username or u.password:
        return False, "Credential inline dalam URL DAST tidak diizinkan."
    if not allow_nonlocal and not _is_private_or_loopback_host(u.hostname):
        return False, "Target DAST non-local ditolak; gunakan explicit authorization."
    return True, ""


def scan_zap(workdir: Path, timeout: int = 600, target: Optional[str] = None,
             allow_nonlocal: bool = False) -> dict:
    exe = which("zap-baseline.py") or which("zap.sh")
    if not exe:
        return _unavailable("zap", "zap-baseline.py/zap.sh")
    if not target:
        return _base_result("zap", "not_applicable",
                            reason="DAST target tidak diberikan",
                            coverage="dast")
    ok, reason = validate_dast_target(target, allow_nonlocal)
    if not ok:
        return _base_result("zap", "blocked", reason=reason, coverage="dast")

    with tempfile.TemporaryDirectory(prefix="deepagents-zap-") as tmp:
        report = Path(tmp) / "zap.json"
        if Path(exe).name == "zap-baseline.py":
            cmd = [exe, "-t", target, "-J", str(report), "-I"]
        else:

            cmd = [exe, "-cmd", "-quickurl", target,
                   "-quickout", str(report), "-quickprogress"]
        try:
            rc, stdout, stderr, elapsed, timed_out = _run_command(cmd, workdir, timeout)
        except OSError as e:
            return _base_result("zap", "error", reason=str(e))
        if timed_out:
            return _base_result("zap", "timeout", reason="DAST timeout",
                                elapsed_seconds=round(elapsed, 3), coverage="dast")

        data = {}
        try:
            if report.exists():
                data = json.loads(report.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            data = {}

        findings = []

        alerts = data.get("site", []) if isinstance(data, dict) else []
        if isinstance(alerts, list):
            for site in alerts:
                for alert in site.get("alerts", []) or []:
                    risk = alert.get("riskdesc") or alert.get("risk") or "UNKNOWN"
                    sev = _severity(str(risk).split()[0])
                    findings.append(Finding(
                        id=_finding_id("dast", alert.get("pluginid"), alert.get("uri"),
                                       alert.get("instances", [{}])[0].get("uri") if alert.get("instances") else None,
                                       alert.get("name")),
                        source="dast", scanner="zap", severity=sev, confidence="MEDIUM",
                        title=_redact(alert.get("name") or "ZAP alert", 500),
                        message=_redact(alert.get("desc") or alert.get("name") or "", 1200),
                        file=_redact(alert.get("uri") or "", 1000),
                        rule_id=str(alert.get("pluginid") or "ZAP"),
                        evidence=_redact(alert.get("solution") or "", 700),
                        remediation=_redact(alert.get("solution") or "", 700),
                    ).to_dict())

        return _base_result("zap", "completed" if rc in (0, 1, 2) else "error",
                            findings=findings,
                            elapsed_seconds=round(elapsed, 3),
                            scanner_exit_code=rc,
                            stderr=stderr,
                            stdout=_redact(stdout, 3000),
                            target=target,
                            coverage="dast",
                            version=_scanner_version("zap.sh") or _scanner_version("zap-baseline.py"))
