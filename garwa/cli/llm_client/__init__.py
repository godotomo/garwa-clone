"""cli/llm_client/__init__.py
Re-export API publik supaya `from .llm_client import X`
di file lain tetap bekerja tanpa perubahan setelah dipecah lebih lanjut.
"""
from .connection import _auth_headers, _fetch_server_n_ctx, check_llama_server_connection, _apply_detected_n_ctx
from .openrouter_cache import _wants_openrouter_cache_control, _build_openrouter_cache_marker, _apply_cache_marker_to_message, _apply_openrouter_cache_control
from .debug_log import _debug_log, _redact_vision_payload_for_debug, _debug_payload_preview
from .stream_call import _call_llama_server_stream
from .nonstream_call import _call_llama_server_nonstream
from .dispatch import _is_rate_limit_error, _is_server_error, call_llama_server
