"""tool_runtime/hooks.py
Dipecah otomatis dari tool_runtime.py (lihat _shared.py untuk konstanta bersama).
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple



class ToolCallStarted:
    """Rekaman tool call yang baru mulai dieksekusi (ala opencode)."""

    __slots__ = ("index", "name", "input")

    def __init__(self, index: int, name: str, input: Any) -> None:
        self.index = index
        self.name = name
        self.input = input


class ToolCallEnded:
    """Rekaman tool call yang selesai dieksekusi (ala opencode)."""

    __slots__ = ("index", "name", "input", "duration_ms", "outcome", "message")

    def __init__(
        self,
        index: int,
        name: str,
        input: Any,
        duration_ms: float,
        outcome: str,
        message: Optional[str] = None,
    ) -> None:
        self.index = index
        self.name = name
        self.input = input
        self.duration_ms = duration_ms
        self.outcome = outcome  # "success" | "failure"
        self.message = message  # model-safe failure message; None saat sukses


class ToolCallHooks:
    """Hook non-throwing yang dipicu di sekitar setiap tool call.

    Meniru opencode ToolCallHooks. Hook tidak boleh melempar -- kalau hook
    sendiri error, error itu ditelan (dicatat) supaya tidak mengganggu
    eksekusi tool utama.
    """

    def __init__(
        self,
        on_tool_call_start: Optional[Callable[[ToolCallStarted], None]] = None,
        on_tool_call_end: Optional[Callable[[ToolCallEnded], None]] = None,
    ) -> None:
        self.on_tool_call_start = on_tool_call_start
        self.on_tool_call_end = on_tool_call_end

    def fire_start(self, call: ToolCallStarted) -> None:
        if self.on_tool_call_start is None:
            return
        try:
            self.on_tool_call_start(call)
        except Exception as e:  # noqa: BLE001 - hook tidak boleh melempar
            print(f"[tool_runtime] hook on_tool_call_start error (ditelan): {e}")

    def fire_end(self, call: ToolCallEnded) -> None:
        if self.on_tool_call_end is None:
            return
        try:
            self.on_tool_call_end(call)
        except Exception as e:  # noqa: BLE001 - hook tidak boleh melempar
            print(f"[tool_runtime] hook on_tool_call_end error (ditelan): {e}")


DEFAULT_HOOKS = ToolCallHooks()
