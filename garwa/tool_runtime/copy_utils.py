"""tool_runtime/copy_utils.py
Dipecah otomatis dari tool_runtime.py (lihat _shared.py untuk konstanta bersama).
"""
from __future__ import annotations

from typing import Any, Dict
from . import _shared as shared
from .errors import InvalidDataValueError
from .errors import is_blocked_member



def copy_in(value: Any, label: str = "tool arguments") -> Any:
    """Validasi & salin nilai terhadap kontrak data plain.

    Meniru opencode copyIn(): memeriksa kedalaman, circularity, hanya objek
    plain, properti terblokir, dan leaf data-only. Mengembalikan salinan yang
    aman (bukan referensi asli) supaya handler tidak bisa memutasi argumen
    yang sudah divalidasi.

    Melempar InvalidDataValueError (subclass ToolRuntimeError) saat nilai
    melanggar kontrak.
    """
    return _copy_bounded(value, label, 0, set())


def _copy_bounded(value: Any, label: str, depth: int, seen: set) -> Any:
    if depth > shared.MAX_VALUE_DEPTH:
        raise InvalidDataValueError(
            f"{label} melebihi kedalaman nilai maksimum {shared.MAX_VALUE_DEPTH}."
        )

    if isinstance(value, shared._DATA_LEAF_TYPES):
        return value

    if not isinstance(value, (dict, list, tuple)):
        raise InvalidDataValueError(
            f"{label} harus berisi data saja; ditemukan tipe {type(value).__name__}."
        )

    if id(value) in seen:
        raise InvalidDataValueError(f"{label} mengandung referensi melingkar (circular).")

    seen.add(id(value))
    try:
        if isinstance(value, dict):
            result: Dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise InvalidDataValueError(
                        f"{label} memiliki key non-string: {key!r}."
                    )
                if is_blocked_member(key):
                    raise InvalidDataValueError(
                        f"{label} memiliki properti terblokir: {key!r}."
                    )
                result[key] = _copy_bounded(item, f"{label}.{key}", depth + 1, seen)
            return result
        if isinstance(value, list):
            return [
                _copy_bounded(item, f"{label}[{i}]", depth + 1, seen)
                for i, item in enumerate(value)
            ]

        return [
            _copy_bounded(item, f"{label}[{i}]", depth + 1, seen)
            for i, item in enumerate(value)
        ]
    finally:
        seen.remove(id(value))
