"""security/findings.py
Dipecah otomatis dari security.py (lihat security/_shared.py untuk konstanta bersama).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from pathlib import Path
import hashlib
import re
from typing import Any, Optional
from . import _shared as shared



@dataclass
class Finding:
    id: str
    source: str
    severity: str = "UNKNOWN"
    confidence: str = "UNKNOWN"
    title: str = ""
    message: str = ""
    file: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None
    rule_id: Optional[str] = None
    cwe: list[str] = field(default_factory=list)
    owasp: list[str] = field(default_factory=list)
    package: Optional[str] = None
    version: Optional[str] = None
    fixed_version: Optional[str] = None
    advisory: Optional[str] = None
    evidence: Optional[str] = None
    remediation: Optional[str] = None
    scanner: Optional[str] = None
    aliases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v not in (None, [], "")}


def _severity(value: Any, default: str = "UNKNOWN") -> str:
    return shared._SEV.get(str(value or "").strip().lower(), default)


def _redact(text: Any, limit: int = 800) -> str:
    if text is None:
        return ""
    s = str(text)
    for pattern, repl in shared._SECRET_PATTERNS:
        s = pattern.sub(repl, s)

    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)
    return s[:limit]


def _safe_rel(workdir: Path, value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    raw = str(value)
    if len(raw) > shared.MAX_PATH_TEXT:
        return "[PATH_TRUNCATED]"
    try:
        root = workdir.resolve()
        p = Path(raw)

        candidate = p.resolve() if p.is_absolute() else (root / p).resolve()
        return candidate.relative_to(root).as_posix()
    except (OSError, ValueError):

        return Path(raw).name[:shared.MAX_PATH_TEXT] or None


def _finding_id(source: str, rule: Any, file: Any, line: Any, title: Any,
                package: Any = None, advisory: Any = None) -> str:
    raw = "\x1f".join(map(str, (source, rule, file, line, title, package, advisory)))
    return "SEC-" + hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:16].upper()
