"""cli/tool_schema/__init__.py
Re-export API publik supaya `from .tool_schema import X`
di file lain tetap bekerja tanpa perubahan setelah dipecah lebih lanjut.
"""
from .alt_syntax import _convert_alt_tool_call_syntax
from .schema_text import build_tool_schema_text, build_openai_tools_payload, _init_tool_registry
from .native_calls import _native_tool_calls_to_blocks, _accumulate_stream_tool_calls

# `__all__` menandai ini sebagai re-export yang disengaja (pyflakes menghormati
# `__all__`, sedangkan `# noqa` TIDAK dihormati oleh pyflakes 4.0.0).
__all__ = [
    "_convert_alt_tool_call_syntax",
    "build_tool_schema_text",
    "build_openai_tools_payload",
    "_init_tool_registry",
    "_native_tool_calls_to_blocks",
    "_accumulate_stream_tool_calls",
]
