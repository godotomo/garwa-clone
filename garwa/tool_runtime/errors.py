"""tool_runtime/errors.py
Dipecah otomatis dari tool_runtime.py (lihat _shared.py untuk konstanta bersama).
"""
from __future__ import annotations

from typing import List, Optional
from . import _shared as shared



class ToolRuntimeError(Exception):
    """Error tool terstruktur ala opencode ToolRuntimeError.

    Attributes:
        kind: salah satu dari VALID_KINDS -- kategori akar masalah.
        suggestions: daftar saran perbaikan konkret untuk model.
    """

    def __init__(
        self,
        kind: str,
        message: str,
        suggestions: Optional[List[str]] = None,
    ) -> None:
        if kind not in shared.VALID_KINDS:
            raise ValueError(f"kind tidak dikenal: {kind!r}")
        super().__init__(message)
        self.kind = kind
        self.suggestions = list(suggestions or [])

    def format_for_model(self) -> str:
        """Format pesan yang kaya sinyal untuk dikembalikan ke model."""
        parts = [f"[ERROR] {self.kind}: {self.args[0]}"]
        if self.suggestions:
            parts.append("Saran:")
            for i, s in enumerate(self.suggestions, 1):
                parts.append(f"  {i}. {s}")
        return "\n".join(parts)


def tool_error(kind: str, message: str, suggestions: Optional[List[str]] = None) -> ToolRuntimeError:
    """Konstruktor ringkas ala opencode toolError()."""
    return ToolRuntimeError(kind, message, suggestions)


def is_blocked_member(name: str) -> bool:
    """True kalau nama properti termasuk yang diblokir (prototype pollution)."""
    return name in shared.BLOCKED_MEMBER_NAMES


class InvalidDataValueError(ToolRuntimeError):
    """Error khusus untuk nilai yang melanggar kontrak data plain."""

    def __init__(self, message: str) -> None:
        super().__init__(shared.KIND_INVALID_DATA_VALUE, message)
