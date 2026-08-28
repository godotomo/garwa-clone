"""cli/scanners/semgrep.py
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



def scan_semgrep(workdir: Path, timeout: int = shared.DEFAULT_TIMEOUT) -> dict:
    exe = which("semgrep")
    if not exe:
        return _unavailable("semgrep", "semgrep")

    cmd = [exe, "--config", "auto", "--json", "--quiet", str(workdir)]
    try:
        rc, data, stderr, elapsed, timed_out = _run_json_command(cmd, workdir, timeout)
    except OSError as e:
        return _base_result("semgrep", "error", reason=str(e))

    if timed_out:
        return _base_result("semgrep", "timeout", reason="scanner timeout",
                            elapsed_seconds=round(elapsed, 3))
    if not isinstance(data, dict):
        return _base_result("semgrep", "error", reason="invalid JSON output",
                            stderr=stderr)

    findings = []
    for item in data.get("results", []) or []:
        extra = item.get("extra") or {}
        meta = extra.get("metadata") or {}
        path = _safe_rel(workdir, item.get("path"))
        start = item.get("start") or {}
        rule = item.get("check_id") or "semgrep"
        sev = _severity(extra.get("severity") or meta.get("severity"))
        cwe = meta.get("cwe") or []
        if isinstance(cwe, str):
            cwe = [cwe]
        owasp = meta.get("owasp") or []
        if isinstance(owasp, str):
            owasp = [owasp]
        findings.append(Finding(
            id=_finding_id("sast", rule, path, start.get("line"), rule),
            source="sast", scanner="semgrep",
            severity=sev,
            confidence="HIGH",
            title=extra.get("message") or rule,
            message=_redact(extra.get("message") or rule, 1200),
            file=path,
            line=start.get("line"),
            column=start.get("col"),
            rule_id=rule,
            cwe=list(map(str, cwe)),
            owasp=list(map(str, owasp)),
            evidence=_redact((extra.get("lines") or ""), 700),
            remediation=_redact(meta.get("fix") or meta.get("fix-regex") or "", 600),
        ).to_dict())

    status = "completed" if rc in (0, 1) else "error"
    return _base_result("semgrep", status, findings=findings,
                        elapsed_seconds=round(elapsed, 3),
                        scanner_exit_code=rc, stderr=stderr,
                        coverage="sast", version=_scanner_version("semgrep"))
