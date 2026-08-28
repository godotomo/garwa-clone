"""cli/scanners/osv.py
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
from ..process_utils import _run_json_command
from .common import _base_result
from .common import _scanner_version
from .common import _unavailable



def _iter_osv_packages(data: dict):
    for result in data.get("results", []) or []:
        source = result.get("source") or result.get("packageSource") or {}
        source_path = source.get("path")
        for pkg in result.get("packages", []) or []:
            package = pkg.get("package") or pkg.get("Package") or {}
            yield source_path, package, pkg.get("vulnerabilities") or pkg.get("Vulnerabilities") or []


def scan_osv(workdir: Path, timeout: int = shared.DEFAULT_TIMEOUT) -> dict:
    exe = which("osv-scanner")
    if not exe:
        return _unavailable("osv-scanner", "osv-scanner")

    commands = [
        [exe, "scan", "--format", "json", "--recursive", str(workdir)],
        [exe, "--format", "json", "--recursive", str(workdir)],
        [exe, "--json", "--recursive", str(workdir)],
    ]

    last = None
    for cmd in commands:
        try:
            rc, data, stderr, elapsed, timed_out = _run_json_command(cmd, workdir, timeout)
        except OSError as e:
            last = _base_result("osv-scanner", "error", reason=str(e))
            continue
        if timed_out:
            return _base_result("osv-scanner", "timeout", reason="scanner timeout",
                                elapsed_seconds=round(elapsed, 3))
        if isinstance(data, dict) and ("results" in data or "vulnerabilities" in data):
            break
        last = _base_result("osv-scanner", "error",
                            reason="invalid/unsupported JSON output", stderr=stderr)
    else:
        return last or _base_result("osv-scanner", "error", reason="scanner failed")

    findings = []
    for source_path, package, vulns in _iter_osv_packages(data):
        pkg_name = package.get("name")
        pkg_ver = package.get("version")
        for vuln in vulns:
            vid = vuln.get("id") or "OSV"
            aliases = [str(x) for x in (vuln.get("aliases") or [])]
            sev = "UNKNOWN"
            severity = vuln.get("severity")
            if isinstance(severity, list) and severity:

                score = None
                for s in severity:
                    score = score or s.get("score")
                try:
                    score_f = float(score)
                    sev = "CRITICAL" if score_f >= 9 else "HIGH" if score_f >= 7 else "MEDIUM" if score_f >= 4 else "LOW"
                except (TypeError, ValueError):
                    pass
            fixed = None
            for affected in vuln.get("affected", []) or []:
                for rng in affected.get("ranges", []) or []:
                    for event in rng.get("events", []) or []:
                        if event.get("fixed"):
                            fixed = event["fixed"]
                            break
            path = _safe_rel(workdir, source_path)
            findings.append(Finding(
                id=_finding_id("dependency", vid, path, None, pkg_name, pkg_name, vid),
                source="dependency", scanner="osv-scanner",
                severity=sev, confidence="HIGH",
                title=vuln.get("summary") or vid,
                message=_redact(vuln.get("details") or vuln.get("summary") or vid, 1200),
                file=path, rule_id=vid, package=pkg_name, version=pkg_ver,
                fixed_version=fixed, advisory=f"https://osv.dev/vulnerability/{vid}",
                aliases=aliases,
                remediation=f"Upgrade {pkg_name} to {fixed}" if fixed else "Review OSV remediation guidance.",
                owasp=["A06:2021"],
            ).to_dict())

    status = "completed" if rc in (0, 1) else "error"
    return _base_result("osv-scanner", status, findings=findings,
                        elapsed_seconds=round(elapsed, 3),
                        scanner_exit_code=rc, stderr=stderr,
                        coverage="dependencies", version=_scanner_version("osv-scanner"))
