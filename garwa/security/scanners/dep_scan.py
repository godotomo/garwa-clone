"""cli/scanners/dep_scan.py
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
from .common import _base_result
from .common import _scanner_version
from .common import _unavailable



def _parse_depscan_report(report_dir: Path, workdir: Path) -> list[dict]:
    findings = []
    for path in sorted(report_dir.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue

        candidates = []
        if isinstance(data, dict):
            candidates.extend(data.get("vulnerabilities") or [])
            candidates.extend(data.get("vulns") or [])
            for item in data.get("results", []) or []:
                if isinstance(item, dict):
                    candidates.extend(item.get("vulnerabilities") or [])
        elif isinstance(data, list):
            candidates.extend(data)

        for v in candidates:
            if not isinstance(v, dict):
                continue
            vid = v.get("id") or v.get("vulnerabilityId") or v.get("VulnerabilityID") or "DEPSCAN"
            aliases = v.get("aliases") or v.get("references") or []
            if isinstance(aliases, dict):
                aliases = list(aliases.keys())
            findings.append({
                "id": _finding_id("dependency", vid, None, None, v.get("title") or vid,
                                  v.get("package") or v.get("component")),
                "source": "dependency",
                "scanner": "dep-scan",
                "severity": _severity(v.get("severity") or v.get("cvss")),
                "confidence": "MEDIUM",
                "title": _redact(v.get("title") or v.get("summary") or vid, 500),
                "message": _redact(v.get("description") or v.get("summary") or vid, 1200),
                "rule_id": vid,
                "package": v.get("package") or v.get("component"),
                "version": v.get("version") or v.get("installedVersion"),
                "fixed_version": v.get("fixedVersion") or v.get("fixVersion"),
                "advisory": v.get("url") or v.get("reference"),
                "aliases": [str(x) for x in aliases if isinstance(x, (str, int))][:20],
                "owasp": ["A06:2021"],
                "remediation": _redact(v.get("recommendation") or "", 600),
            })
    return findings


def scan_dep_scan(workdir: Path, timeout: int = 600) -> dict:
    exe = which("depscan")
    if not exe:
        return _unavailable("dep-scan", "depscan")

    with tempfile.TemporaryDirectory(prefix="deepagents-depscan-") as tmp:
        report_dir = Path(tmp)
        cmd = [exe, "--no-banner", "--src", str(workdir),
               "--reports-dir", str(report_dir), "--profile", "appsec",
               "--no-suggest"]
        try:
            rc, stdout, stderr, elapsed, timed_out = _run_command(cmd, workdir, timeout)
        except OSError as e:
            return _base_result("dep-scan", "error", reason=str(e))
        if timed_out:
            return _base_result("dep-scan", "timeout", reason="scanner timeout",
                                elapsed_seconds=round(elapsed, 3))
        findings = _parse_depscan_report(report_dir, workdir)

        status = "completed" if rc in (0, 1) else "error"
        return _base_result("dep-scan", status, findings=findings,
                            elapsed_seconds=round(elapsed, 3),
                            scanner_exit_code=rc,
                            stderr=stderr,
                            stdout=_redact(stdout, 3000),
                            coverage="deep-dependencies",
                            version=_scanner_version("depscan"))
