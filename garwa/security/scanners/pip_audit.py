"""cli/scanners/pip_audit.py
Dipecah lebih lanjut dari cli/scanners.py.
"""
from __future__ import annotations

from pathlib import Path
from shutil import which
import os
from .. import _shared as shared
from ..findings import Finding
from ..findings import _finding_id
from ..findings import _redact
from ..findings import _severity
from ..process_utils import _run_json_command
from .common import _base_result
from .common import _scanner_version
from .common import _unavailable



def _python_dependency_files(workdir: Path) -> list[Path]:
    names = {
        "requirements.txt", "requirements-dev.txt", "requirements-test.txt",
        "pyproject.toml", "Pipfile.lock", "poetry.lock", "uv.lock",
        "requirements.lock",
    }
    found = []
    for root, dirs, files in os.walk(workdir):
        dirs[:] = [d for d in dirs if d not in {".git", ".deepagents", "node_modules", ".venv", "venv"}]
        for name in files:
            if name in names:
                found.append(Path(root) / name)
    return found[:100]


def scan_pip_audit(workdir: Path, timeout: int = shared.DEFAULT_TIMEOUT) -> dict:
    exe = which("pip-audit")
    if not exe:
        return _unavailable("pip-audit", "pip-audit")

    files = [f for f in _python_dependency_files(workdir)
             if f.name not in {"poetry.lock", "uv.lock", "Pipfile.lock"}]
    if not files:
        return _base_result("pip-audit", "not_applicable",
                            reason="no supported Python dependency file found (poetry.lock/uv.lock/Pipfile.lock are handled by OSV-Scanner/dep-scan)",
                            coverage="python-dependencies")

    findings = []
    runs = []
    for req in files:

        if req.name == "pyproject.toml":
            # pip-audit resolves pyproject.toml via its PyProjectSource (needs pip);
            # `--disable-pip` is only valid together with `--requirement`, so it
            # must NOT be passed here.
            cmd = [exe, "--format", "json", "--vulnerability-service", "osv", str(req.parent)]
        else:
            cmd = [exe, "--format", "json", "--vulnerability-service", "osv", "--requirement", str(req)]
        try:
            rc, data, stderr, elapsed, timed_out = _run_json_command(cmd, workdir, timeout)
        except OSError as e:
            runs.append({"file": str(req), "status": "error", "reason": str(e)})
            continue
        runs.append({"file": str(req.relative_to(workdir)), "exit_code": rc,
                     "elapsed_seconds": round(elapsed, 3), "timed_out": timed_out})
        if timed_out:
            continue
        if not isinstance(data, list):

            deps = data.get("dependencies", []) if isinstance(data, dict) else []
        else:
            deps = data
        for dep in deps or []:
            name = dep.get("name")
            version = dep.get("version")
            for vuln in dep.get("vulns", []) or []:
                vid = vuln.get("id") or "PIP-AUDIT"
                fixes = vuln.get("fix_versions") or []
                fixed = fixes[0] if fixes else None
                aliases = vuln.get("aliases") or []
                findings.append(Finding(
                    id=_finding_id("dependency", vid, str(req.relative_to(workdir)), None, name, name, vid),
                    source="dependency", scanner="pip-audit",
                    severity=_severity(vuln.get("severity")),
                    confidence="HIGH",
                    title=vuln.get("description") or vid,
                    message=_redact(vuln.get("description") or vid, 1200),
                    file=str(req.relative_to(workdir)),
                    rule_id=vid, package=name, version=version,
                    fixed_version=fixed, advisory=vuln.get("url"),
                    aliases=[str(x) for x in aliases],
                    owasp=["A06:2021"],
                    remediation=f"Upgrade {name} to {fixed}" if fixed else "Review pip-audit remediation.",
                ).to_dict())

    status = "completed" if runs else "error"
    return _base_result("pip-audit", status, findings=findings, runs=runs,
                        coverage="python-dependencies", version=_scanner_version("pip-audit"))
