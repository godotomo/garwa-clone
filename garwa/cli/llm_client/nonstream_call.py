"""cli/llm_client/nonstream_call.py
Dipecah lebih lanjut dari cli/llm_client.py.
"""
import argparse
import base64
import copy
import difflib
import json
import mimetypes
import os
import re
import select
import shlex
import shutil
import sys
import time
import unicodedata
from collections import OrderedDict
from datetime import datetime
from urllib.parse import unquote, urlparse

try:

    import readline  # noqa: F401
except ImportError:
    readline = None

import requests

from ...tools import TOOLS
from .. import _state as state
from ..colors import C
from ..colors import c
from ..llm_errors import LlamaServerStreamError
from ..llm_errors import RepetitionLoopError
from ..llm_errors import TruncatedGenerationError
from ..llm_errors import _parse_context_exceeded
from ..markdown_render import MarkdownTerminalRenderer
from ..markdown_render import ReasoningPreview
from ..stream_parse import _extract_stream_content
from ..stream_parse import _extract_stream_finish_reason
from ..stream_parse import _extract_stream_reasoning
from ..stream_parse import _extract_stream_usage
from ..stream_parse import _flush_visible_text
from ..stream_parse import _print_stream_text
from ..stream_parse import _stream_visible_text
from ..text_utils import _detect_repetition
from ..text_utils import _resp_text_utf8
from ..tool_schema import _accumulate_stream_tool_calls
from ..tool_schema import _native_tool_calls_to_blocks
from ..tool_schema import build_openai_tools_payload
from .connection import _auth_headers
from .debug_log import _debug_log
from .debug_log import _debug_payload_preview
from .openrouter_cache import _apply_openrouter_cache_control
from .openrouter_cache import _wants_openrouter_cache_control



def _call_llama_server_nonstream(url: str, model: str, messages: list,
                                 temperature: float = 0.2, api_key: str = "",
                                 debug: bool = False) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,

        "tools": build_openai_tools_payload(),

        "stop": [state.TOOL_CLOSE + "\n\n", "<|end_of_turn|>", state.ALT_TOOL_CLOSE],
    }

    if state._LLAMA_CPP_SERVER_DETECTED[0]:
        payload["cache_prompt"] = True

    if _wants_openrouter_cache_control(url, model):
        payload["messages"] = _apply_openrouter_cache_control(messages)
    if debug:
        _debug_log("REQUEST", f"POST {url} (stream=False, {len(messages)} pesan dalam messages)")
        _debug_log("PAYLOAD", _debug_payload_preview(payload))

    response = None
    try:
        response = requests.post(url, json=payload, headers=_auth_headers(api_key), timeout=300)
        if debug:
            _debug_log("HTTP-STATUS", f"{response.status_code} {response.reason}")
            raw_text = _resp_text_utf8(response)
            preview = raw_text if len(raw_text) <= 8000 else raw_text[:8000] + f"...(dipotong, total {len(raw_text)} char)"
            _debug_log("RESPONSE-RAW", preview)
        response.raise_for_status()
        try:
            data = response.json()
        except json.JSONDecodeError as e:

            body_preview = _resp_text_utf8(response)[:500] if response is not None else ""
            print(c(
                f"[ERROR] Respon dari server model bukan JSON valid: {e}\n{body_preview}",
                C.RED,
            ))
            raise LlamaServerStreamError(f"Respon non-stream bukan JSON valid: {e}") from e
        try:
            _choice0 = data["choices"][0]
            message = _choice0["message"]
            content = message.get("content") or ""

            _nonstream_finish_reason = _choice0.get("finish_reason")
            _nonstream_usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
        except (KeyError, IndexError, TypeError) as e:

            preview = json.dumps(data, ensure_ascii=False)[:500] if isinstance(data, (dict, list)) else str(data)[:500]
            print(c(
                f"[ERROR] Struktur respon server model tidak sesuai dugaan "
                f"(field 'choices[0].message.content' tidak ada): {e}\n{preview}",
                C.RED,
            ))
            raise LlamaServerStreamError(f"Struktur respon tidak sesuai dugaan: {e}") from e

        native_tool_calls = message.get("tool_calls")
        if native_tool_calls:
            content += _native_tool_calls_to_blocks(native_tool_calls)
    except requests.exceptions.ConnectionError:
        print(c(
            f"[ERROR] Tidak bisa konek ke server model di {url}. "
            f"Pastikan server model sudah jalan.",
            C.RED,
        ))
        raise
    except requests.exceptions.HTTPError as e:

        ctx_err = _parse_context_exceeded(response)
        if ctx_err is not None:
            detail = (
                f"prompt {ctx_err.n_prompt_tokens} token > context server "
                f"{ctx_err.n_ctx} token"
                if ctx_err.n_prompt_tokens is not None and ctx_err.n_ctx is not None
                else str(ctx_err)
            )
            print(c(f"[ERROR] Context window server terlampaui: {detail}", C.RED))
            raise ctx_err from e
        body = ""
        try:
            body = _resp_text_utf8(response)[:1000] if response is not None else ""
        except Exception:
            pass
        hint = ""
        if response is not None and response.status_code == 401:
            hint = c(
                "\n[hint] 401 Unauthorized -- server ini butuh API key. "
                "Isi LLAMA_API_KEY di config.py / environment variable, atau --api-key di CLI.",
                C.YELLOW,
            )
        print(c(f"[ERROR] HTTP error dari server model: {e}\n{body}", C.RED) + hint)
        raise
    except requests.exceptions.RequestException as e:

        print(c(f"[ERROR] Request ke server model gagal: {type(e).__name__}: {e}", C.RED))
        raise
    finally:
        if response is not None:
            response.close()

    if debug:
        _debug_log("FULL-CONTENT", content)

    if _nonstream_finish_reason in state.TRUNCATION_FINISH_REASONS and not content.strip():
        comp_tok = _nonstream_usage.get("completion_tokens") if _nonstream_usage else None
        reason_tok = None
        if _nonstream_usage:
            reason_tok = (
                _nonstream_usage.get("reasoning_tokens")
                or (_nonstream_usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
                or (_nonstream_usage.get("output_tokens_details") or {}).get("reasoning_tokens")
            )
        detail = f"finish_reason={_nonstream_finish_reason!r}"
        if comp_tok is not None:
            detail += f", completion_tokens={comp_tok}"
        if reason_tok is not None:
            detail += f", reasoning_tokens={reason_tok}"
        raise TruncatedGenerationError(
            f"Server menghentikan generation karena batas token habis "
            f"SEBELUM model menghasilkan konten/tool_call apa pun ({detail}).",
            finish_reason=_nonstream_finish_reason,
            completion_tokens=comp_tok,
            reasoning_tokens=reason_tok,
        )
    if state.TOOL_OPEN in content and state.TOOL_CLOSE not in content:
        content += "\n" + state.TOOL_CLOSE
    if _nonstream_usage is not None:
        state._accumulate_usage(_nonstream_usage)
    return content
