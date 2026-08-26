"""
tool_runtime/_shared.py
Konstanta & singleton bersama (mis. REGISTRY) yang dipakai lintas modul
hasil pecahan tool_runtime.py. Diakses sebagai `shared.NAMA`.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple


KIND_UNKNOWN_TOOL = "UnknownTool"
KIND_INVALID_TOOL_INPUT = "InvalidToolInput"
KIND_INVALID_TOOL_OUTPUT = "InvalidToolOutput"
KIND_INVALID_DATA_VALUE = "InvalidDataValue"
KIND_TOOL_CALL_LIMIT_EXCEEDED = "ToolCallLimitExceeded"
VALID_KINDS = frozenset({
    KIND_UNKNOWN_TOOL,
    KIND_INVALID_TOOL_INPUT,
    KIND_INVALID_TOOL_OUTPUT,
    KIND_INVALID_DATA_VALUE,
    KIND_TOOL_CALL_LIMIT_EXCEEDED,
})
MAX_VALUE_DEPTH = 32
BLOCKED_MEMBER_NAMES = frozenset({"__proto__", "constructor", "prototype"})
_DATA_LEAF_TYPES = (str, bool, int, float, type(None))
DEFAULT_CATALOG_BUDGET = 2_000
DEFAULT_SEARCH_LIMIT = 10
_SIGNATURES: Dict[str, str] = {}
_TYPE_RE = re.compile(r"^\s*([a-zA-Z]+)\s*(?:\(([^)]*)\))?\s*[-:]\s*(.*)$", re.DOTALL)
_TYPE_MAP = {
    "string": "string",
    "integer": "integer",
    "int": "integer",
    "number": "number",
    "float": "number",
    "boolean": "boolean",
    "bool": "boolean",
    "array": "array",
    "list": "array",
    "object": "object",
    "dict": "object",
    "any": "string",
}
