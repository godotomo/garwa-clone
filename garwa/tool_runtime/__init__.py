"""
tool_runtime package
Infrastruktur runtime tool (error terstruktur, validasi argumen,
hooks observasi, registry namespace, skema tipe, eksekutor) -- dipecah
dari tool_runtime.py jadi beberapa modul kecil. Diimpor sebagai
`tool_runtime` (lihat `garwa/tool_runtime/__init__.py`) supaya
`import tool_runtime` di cli.py tetap bekerja tanpa berubah.
"""
from . import _shared as shared

from .errors import ToolRuntimeError, tool_error, is_blocked_member, InvalidDataValueError
from .copy_utils import copy_in
from .hooks import ToolCallStarted, ToolCallEnded, ToolCallHooks, DEFAULT_HOOKS
from .registry import ToolRegistry, register_signature, REGISTRY
from .introspection import parse_argument_description, build_openai_tools_payload
from .executor import run_tool_with_runtime

# Konstanta yang aslinya tinggal di top-level tool_runtime.py --
# diekspos ulang di sini persis dengan nama yang sama supaya
# `tool_runtime.KIND_UNKNOWN_TOOL` dkk tetap bekerja seperti sebelum
# dipecah.
KIND_UNKNOWN_TOOL = shared.KIND_UNKNOWN_TOOL
KIND_INVALID_TOOL_INPUT = shared.KIND_INVALID_TOOL_INPUT
KIND_INVALID_TOOL_OUTPUT = shared.KIND_INVALID_TOOL_OUTPUT
KIND_INVALID_DATA_VALUE = shared.KIND_INVALID_DATA_VALUE
KIND_TOOL_CALL_LIMIT_EXCEEDED = shared.KIND_TOOL_CALL_LIMIT_EXCEEDED
VALID_KINDS = shared.VALID_KINDS
DEFAULT_CATALOG_BUDGET = shared.DEFAULT_CATALOG_BUDGET
DEFAULT_SEARCH_LIMIT = shared.DEFAULT_SEARCH_LIMIT
