"""cli/scanners/trivy.py
Dipecah lebih lanjut dari cli/scanners.py.
"""
from __future__ import annotations

from pathlib import Path
from shutil import which
from .. import _shared as shared
from ..findings import Finding
from ..findings import _finding_id
from ..findings import _redact
from ..findings import _safe_rel
from ..findings import _severity
from ..process_utils import _run_json_command
from .common import _base_result
from .common import _scanner_version
from .common import _unavailable



def scan_trivy(workdir: Path, timeout: int = shared.DEFAULT_TIMEOUT) -> dict:
    exe = which("trivy")
    if not exe:
        return _unavailable("trivy", "trivy")

    cmd = [exe, "fs", "--format", "json",
           "--scanners", "vuln,misconfig", "--quiet", str(workdir)]
    try:
        rc, data, stderr, elapsed, timed_out = _run_json_command(cmd, workdir, timeout)
    except OSError as e:
        return _base_result("trivy", "error", reason=str(e))
    if timed_out:
        return _base_result("trivy", "timeout", reason="scanner timeout",
                            elapsed_seconds=round(elapsed, 3))

    findings = []
    for result in (data.get("Results", []) if isinstance(data, dict) else []):
        target = _safe_rel(workdir, result.get("Target"))
        for v in result.get("Vulnerabilities", []) or []:
            vid = v.get("VulnerabilityID") or "TRIVY"
            findings.append(Finding(
                id=_finding_id("iac", vid, target, None, v.get("PkgName", vid)),
                source="iac", scanner="trivy",
                severity=_severity(v.get("Severity")), confidence="HIGH",
                title=_redact(v.get("Title") or vid, 500),
                message=_redact(v.get("Description") or vid, 1200),
                file=target, rule_id=vid,
                package=v.get("PkgName"), version=v.get("InstalledVersion"),
                fixed_version=v.get("FixedVersion"),
                advisory=v.get("PrimaryURL"),
                owasp=["A06:2021"],
                remediation=(f"Upgrade/fix to {v.get('FixedVersion')}"
                             if v.get("FixedVersion") else "Review Trivy remediation."),
            ).to_dict())
        for m in result.get("Misconfigurations", []) or []:
            mid = m.get("ID") or "TRIVY-MISCONFIG"
            cause = m.get("CauseMetadata") or {}
            findings.append(Finding(
                id=_finding_id("iac", mid, target, cause.get("StartLine"), mid),
                source="iac", scanner="trivy",
                severity=_severity(m.get("Severity")), confidence="HIGH",
                title=_redact(m.get("Title") or mid, 500),
                message=_redact(m.get("Message") or m.get("Description") or mid, 1200),
                file=target, line=cause.get("StartLine"), rule_id=mid,
                owasp=["A05:2021"],
                remediation=_redact(m.get("Resolution") or "", 600),
            ).to_dict())
    status = "completed" if rc in (0, 1) else "error"
    return _base_result("trivy", status, findings=findings,
                        elapsed_seconds=round(elapsed, 3),
                        scanner_exit_code=rc, stderr=stderr,
                        coverage="iac", version=_scanner_version("trivy"))
