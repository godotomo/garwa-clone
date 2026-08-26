"""cli/tool_schema/__init__.py
Re-export API publik supaya `from .tool_schema import X`
di file lain tetap bekerja tanpa perubahan setelah dipecah lebih lanjut.
"""
from .alt_syntax import _parse_alt_tool_call_args, _convert_alt_tool_call_syntax
from .schema_text import build_tool_schema_text, build_openai_tools_payload, _build_tool_signature, _init_tool_registry
from .native_calls import _native_tool_call_to_block, _native_tool_calls_to_blocks, _accumulate_stream_tool_calls
