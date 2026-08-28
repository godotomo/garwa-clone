"""security/orchestrator.py
Dipecah otomatis dari security.py (lihat security/_shared.py untuk konstanta bersama).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional
from . import _shared as shared
from .scanners import scan_semgrep, scan_osv, scan_pip_audit, scan_dep_scan, scan_gitleaks, scan_trivy
from .dast import scan_zap
from .findings import _redact
from .process_utils import _bounded_timeout
from .scanners import _base_result



SCANNER_REGISTRY: dict[str, Callable[..., dict]] = {
    "sast": scan_semgrep,
    "dependencies": scan_osv,
    "python": scan_pip_audit,
    "deep": scan_dep_scan,
    "secrets": scan_gitleaks,
    "iac": scan_trivy,
    "dast": scan_zap,
}

MODE_SCANNERS = {
    "all": ["sast", "dependencies", "secrets", "iac"],
    "sast": ["sast"],
    "dependencies": ["dependencies"],
    "python": ["dependencies", "python"],
    "deep": ["dependencies", "python", "deep"],
    "secrets": ["secrets"],
    "iac": ["iac"],
    "dast": ["dast"],
    "compliance": ["dependencies", "deep"],
}


def _deduplicate_findings(findings: list[dict]) -> list[dict]:
    """Deduplicate by vulnerability/rule/package/location while preserving
    strongest severity and collecting scanner agreement."""
    groups: dict[tuple, dict] = {}
    for f in findings:
        key = (
            str(f.get("rule_id") or f.get("title") or "").lower(),
            str(f.get("package") or "").lower(),
            str(f.get("file") or "").lower(),
            str(f.get("line") or ""),
        )
        existing = groups.get(key)
        if not existing:
            copy = dict(f)
            copy["scanners"] = [f.get("scanner")] if f.get("scanner") else []
            groups[key] = copy
            continue
        if shared._SEV_RANK.get(f.get("severity", "UNKNOWN"), 0) > shared._SEV_RANK.get(existing.get("severity", "UNKNOWN"), 0):
            existing["severity"] = f.get("severity")
        if shared._CONF_RANK.get(f.get("confidence", "UNKNOWN"), 0) > shared._CONF_RANK.get(existing.get("confidence", "UNKNOWN"), 0):
            existing["confidence"] = f.get("confidence")
        if f.get("scanner") and f["scanner"] not in existing["scanners"]:
            existing["scanners"].append(f["scanner"])
        for field_name in ("aliases", "cwe", "owasp"):
            merged = list(dict.fromkeys((existing.get(field_name) or []) + (f.get(field_name) or [])))
            if merged:
                existing[field_name] = merged

    result = list(groups.values())
    for f in result:
        f["scanner_agreement"] = len([x for x in f.get("scanners", []) if x])
        f["scanners"] = sorted(set(f.get("scanners", [])))
    result.sort(key=lambda x: (
        -shared._SEV_RANK.get(x.get("severity", "UNKNOWN"), 0),
        -shared._CONF_RANK.get(x.get("confidence", "UNKNOWN"), 0),
        str(x.get("id", "")),
    ))
    return result


def _security_gate(findings: list[dict], scanner_results: list[dict],
                   required: list[str]) -> dict:
    statuses = {r.get("scanner"): r.get("status") for r in scanner_results}
    unavailable = [s for s in required if statuses.get(s) in {"unavailable", "timeout", "error", "blocked"}]
    critical = [f for f in findings if f.get("severity") == "CRITICAL"]
    confirmed_high = [
        f for f in findings
        if f.get("severity") == "HIGH"
        and f.get("confidence") == "HIGH"
    ]
    if unavailable:
        status = "INCOMPLETE"
    elif critical or confirmed_high:
        status = "BLOCK"
    elif findings:
        status = "WARN"
    else:
        status = "PASS"
    return {
        "status": status,
        "blocking_findings": len(critical) + len(confirmed_high),
        "critical": len(critical),
        "confirmed_high": len(confirmed_high),
        "missing_or_failed_scanners": unavailable,
        "policy": {
            "critical": "BLOCK",
            "high_high_confidence": "BLOCK",
            "lower_findings": "WARN",
            "missing_or_failed_required_scanner": "INCOMPLETE",
        },
    }


def security_scan(workdir: Path, scan_type: str = "all", timeout: int = shared.DEFAULT_TIMEOUT,
                  dast_target: Optional[str] = None,
                  allow_nonlocal_dast: bool = False,
                  max_findings: int = shared.MAX_FINDINGS) -> dict:
    """
    Main public API used by cli.py.

    scan_type:
      all | sast | dependencies | python | deep | secrets | iac | dast | compliance

    `deep` adds pip-audit + OWASP dep-scan.
    `compliance` currently uses dependency/supply-chain scanners; license policy
    enforcement remains a future ORT integration and is not falsely reported as
    completed here.
    """
    root = Path(workdir).resolve()
    if not root.is_dir():
        return {"status": "error", "error": "workdir bukan directory"}

    mode = str(scan_type or "all").strip().lower()
    if mode not in MODE_SCANNERS:
        return {"status": "error", "error": f"scan_type tidak dikenal: {mode}"}

    selected = MODE_SCANNERS[mode]
    results = []
    all_findings = []
    per_scanner_timeout = _bounded_timeout(timeout)

    for scanner_key in selected:
        fn = SCANNER_REGISTRY[scanner_key]
        try:
            if scanner_key == "dast":
                result = fn(root, timeout=max(per_scanner_timeout, 600),
                             target=dast_target, allow_nonlocal=allow_nonlocal_dast)
            elif scanner_key == "deep":
                result = fn(root, timeout=max(per_scanner_timeout, 600))
            else:
                result = fn(root, timeout=per_scanner_timeout)
        except Exception as exc:
            result = _base_result(
                scanner_key, "error",
                reason=f"uncaught scanner adapter error: {type(exc).__name__}: {_redact(exc, 500)}",
            )
        results.append(result)
        all_findings.extend(result.get("findings", []) or [])

    findings = _deduplicate_findings(all_findings)[:max(1, min(int(max_findings), shared.MAX_FINDINGS))]
    required_scanners = [
        r.get("scanner") for r in results
        if r.get("status") != "not_applicable" and r.get("scanner")
    ]
    gate = _security_gate(findings, results, required_scanners)

    coverage = {
        "requested": selected,
        "completed": [r["scanner"] for r in results if r.get("status") == "completed"],
        "unavailable": [r["scanner"] for r in results if r.get("status") == "unavailable"],
        "failed": [r["scanner"] for r in results if r.get("status") in {"error", "timeout", "blocked"}],
    }

    status = "completed" if gate["status"] != "INCOMPLETE" else "incomplete"
    return {
        "status": status,
        "scan_type": mode,
        "gate": gate,
        "coverage": coverage,
        "scanner_results": results,
        "findings": findings,
        "summary": {
            "total_findings": len(findings),
            "critical": sum(f.get("severity") == "CRITICAL" for f in findings),
            "high": sum(f.get("severity") == "HIGH" for f in findings),
            "medium": sum(f.get("severity") == "MEDIUM" for f in findings),
            "low": sum(f.get("severity") == "LOW" for f in findings),
            "info": sum(f.get("severity") == "INFO" for f in findings),
        },
        "evidence_limits": {
            "max_findings": max_findings,
            "max_evidence_chars": shared.MAX_EVIDENCE_CHARS,
            "secrets_redacted": True,
        },
    }
