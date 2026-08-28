"""cli/scanners/gitleaks.py
Dipecah lebih lanjut dari cli/scanners.py.
"""
from __future__ import annotations

from pathlib import Path
from shutil import which
from .. import _shared as shared
from ..findings import Finding
from ..findings import _finding_id
from ..findings import _safe_rel
from ..process_utils import _run_json_command
from .common import _base_result
from .common import _scanner_version
from .common import _unavailable



def scan_gitleaks(workdir: Path, timeout: int = shared.DEFAULT_TIMEOUT) -> dict:
    exe = which("gitleaks")
    if not exe:
        return _unavailable("gitleaks", "gitleaks")

    cmd = [exe, "detect", "--source", str(workdir), "--report-format", "json",
           "--report-path", "-", "--no-banner"]
    try:
        rc, data, stderr, elapsed, timed_out = _run_json_command(cmd, workdir, timeout)
    except OSError as e:
        return _base_result("gitleaks", "error", reason=str(e))
    if timed_out:
        return _base_result("gitleaks", "timeout", reason="scanner timeout",
                            elapsed_seconds=round(elapsed, 3))

    raw = data if isinstance(data, list) else []
    findings = []
    for item in raw:
        path = _safe_rel(workdir, item.get("File"))
        rule = item.get("RuleID") or "secret"
        line = item.get("StartLine")
        findings.append(Finding(
            id=_finding_id("secret", rule, path, line, rule),
            source="secret", scanner="gitleaks",
            severity="CRITICAL", confidence="HIGH",
            title=f"Potential secret: {rule}",
            message="Potential credential/secret detected; value redacted.",
            file=path, line=line, rule_id=rule,
            evidence="[REDACTED]",
            remediation="Revoke/rotate the credential and remove it from source/history.",
        ).to_dict())
    status = "completed" if rc in (0, 1) else "error"
    return _base_result("gitleaks", status, findings=findings,
                        elapsed_seconds=round(elapsed, 3),
                        scanner_exit_code=rc, stderr=stderr,
                        coverage="secrets", version=_scanner_version("gitleaks"))
