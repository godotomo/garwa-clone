"""tool_runtime/executor.py
Dipecah otomatis dari tool_runtime.py (lihat _shared.py untuk konstanta bersama).
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from . import _shared as shared
from .copy_utils import copy_in
from .errors import ToolRuntimeError
from .hooks import DEFAULT_HOOKS
from .errors import tool_error
from .hooks import ToolCallEnded
from .hooks import ToolCallHooks
from .hooks import ToolCallStarted



def run_tool_with_runtime(
    name: str,
    arguments: Dict[str, Any],
    handler: Callable[..., Any],
    index: int = 0,
    hooks: Optional[ToolCallHooks] = None,
) -> str:
    """Eksekusi tool dengan validasi nilai + hooks + klasifikasi error.

    Ini adalah jalur eksekusi baru yang menggantikan blok try/except generik
    di execute_tool() cli.py. Mengembalikan string hasil (sama seperti
    execute_tool lama) sehingga pipeline pemanggil tidak berubah.

    Args:
        name: nama tool.
        arguments: dict argumen (sudah lolos guard _raw/mojibake di cli.py).
        handler: spec["handler"] dari TOOLS.
        index: nomor urut tool call dalam giliran (untuk hooks).
        hooks: instance ToolCallHooks; default DEFAULT_HOOKS.
    """
    hooks = hooks or DEFAULT_HOOKS
    start = time.monotonic()

    try:
        safe_args = copy_in(arguments, f"arguments untuk tool '{name}'")
    except ToolRuntimeError as e:
        duration_ms = (time.monotonic() - start) * 1000.0
        hooks.fire_end(ToolCallEnded(
            index, name, arguments, duration_ms, "failure", e.format_for_model()
        ))
        return e.format_for_model()

    hooks.fire_start(ToolCallStarted(index, name, safe_args))

    try:
        result = handler(**safe_args)
        duration_ms = (time.monotonic() - start) * 1000.0
        hooks.fire_end(ToolCallEnded(index, name, safe_args, duration_ms, "success"))
        return str(result)
    except TypeError as e:
        err = tool_error(
            shared.KIND_INVALID_TOOL_INPUT,
            f"Argumen tidak sesuai untuk tool '{name}': {e}",
            [
                "Periksa nama dan tipe argumen yang dikirim vs skema tool.",
                "Pastikan semua argumen wajib terisi dan tidak ada argumen tak dikenal.",
            ],
        )
        duration_ms = (time.monotonic() - start) * 1000.0
        hooks.fire_end(ToolCallEnded(index, name, safe_args, duration_ms, "failure", err.format_for_model()))
        return err.format_for_model()
    except ToolRuntimeError as e:
        duration_ms = (time.monotonic() - start) * 1000.0
        hooks.fire_end(ToolCallEnded(index, name, safe_args, duration_ms, "failure", e.format_for_model()))
        return e.format_for_model()
    except Exception as e:  # noqa: BLE001 - error tool apa pun jadi pesan model-safe
        err = tool_error(
            shared.KIND_INVALID_TOOL_OUTPUT,
            f"Eksekusi tool '{name}' gagal: {e}",
            [
                "Periksa apakah input yang diberikan valid untuk tool ini.",
                "Coba dengan argumen yang lebih sederhana atau periksa kondisi lingkungan.",
            ],
        )
        duration_ms = (time.monotonic() - start) * 1000.0
        hooks.fire_end(ToolCallEnded(index, name, safe_args, duration_ms, "failure", err.format_for_model()))
        return err.format_for_model()
