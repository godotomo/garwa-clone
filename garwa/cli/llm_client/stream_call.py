"""cli/llm_client/stream_call.py
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



def _call_llama_server_stream(url: str, model: str, messages: list,
                              temperature: float = 0.2, api_key: str = "",
                              debug: bool = False) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,

        "stop": [state.TOOL_CLOSE + "\n\n", "<|end_of_turn|>", state.ALT_TOOL_CLOSE],

        "tools": build_openai_tools_payload(),
    }

    if state._LLAMA_CPP_SERVER_DETECTED[0]:
        payload["cache_prompt"] = True

    if _wants_openrouter_cache_control(url, model):
        payload["messages"] = _apply_openrouter_cache_control(messages)
    response = None
    full_parts = []

    reasoning_parts = []
    _reasoning_chars_since_check = 0

    content_parts = []
    _content_chars_since_check = 0

    native_tool_call_state = {}

    last_finish_reason = None
    last_usage = None
    visible_state = {
        "in_tool": False,
        "pending": "",
        "ws_hold": "",
        "started": False,
        "renderer": MarkdownTerminalRenderer(),
    }

    reasoning_preview = None if debug else ReasoningPreview()

    if debug:
        _debug_log("REQUEST", f"POST {url} (stream=True, {len(messages)} pesan dalam messages)")
        _debug_log("PAYLOAD", _debug_payload_preview(payload))

    try:
        response = requests.post(
            url,
            json=payload,
            headers=_auth_headers(api_key),
            timeout=300,
            stream=True,
        )
        if debug:
            _debug_log("HTTP-STATUS", f"{response.status_code} {response.reason}")
            _debug_log("HTTP-HEADERS", dict(response.headers).__repr__())
        response.raise_for_status()

        chunk_n = 0

        for raw_line in response.iter_lines(decode_unicode=False):
            if raw_line is None:
                continue
            if isinstance(raw_line, bytes):
                raw_line = raw_line.decode("utf-8", errors="replace")
            line = raw_line.strip()

            if debug and line:
                chunk_n += 1
                _debug_log(f"SSE-RAW #{chunk_n}", line)

            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                data = line[5:].strip()
            else:

                data = line

            if data == "[DONE]":
                if debug:
                    _debug_log("SSE", "[DONE] diterima, stream berakhir normal.")
                break

            try:
                obj = json.loads(data)
            except json.JSONDecodeError as e:

                if debug:
                    _debug_log("SSE-PARSE-ERROR", f"{e} | raw data mentah: {data!r}")
                continue

            delta = _extract_stream_content(obj)
            reasoning_delta = _extract_stream_reasoning(obj)

            _accumulate_stream_tool_calls(obj, native_tool_call_state)

            _fr = _extract_stream_finish_reason(obj)
            if _fr:
                last_finish_reason = _fr
            _usage = _extract_stream_usage(obj)
            if _usage is not None:
                last_usage = _usage
            if debug:
                _debug_log("SSE-DELTA", repr(delta))
                if reasoning_delta:
                    _debug_log("SSE-REASONING", repr(reasoning_delta))

            if reasoning_delta and reasoning_preview is not None:
                reasoning_preview.feed(reasoning_delta)

            if reasoning_delta:
                reasoning_parts.append(reasoning_delta)
                _reasoning_chars_since_check += len(reasoning_delta)
                if _reasoning_chars_since_check >= state.REPEAT_CHECK_EVERY:
                    _reasoning_chars_since_check = 0
                    _reasoning_so_far = "".join(reasoning_parts)
                    if _detect_repetition(_reasoning_so_far):
                        if reasoning_preview is not None:
                            reasoning_preview.close()
                        visible_state["renderer"].abort()
                        print(c(
                            "\n[LOOP] Model mengulang kalimat/baris yang sama "
                            "berulang-ulang di dalam reasoning (chain of "
                            "thought) -- degenerate loop sebelum jawaban "
                            "asli keluar. Menghentikan stream lebih awal "
                            "untuk menghemat token.",
                            C.RED,
                        ))
                        raise RepetitionLoopError(
                            "Model mengulang teks yang sama di dalam "
                            "reasoning_content (intra-response degenerate "
                            "loop di chain of thought)."
                        )

            if not delta:
                continue

            if reasoning_preview is not None:
                reasoning_preview.close()

            full_parts.append(delta)
            visible = _stream_visible_text(visible_state, delta)
            _print_stream_text(visible, visible_state)

            content_parts.append(delta)
            _content_chars_since_check += len(delta)
            if _content_chars_since_check >= state.REPEAT_CHECK_EVERY:
                _content_chars_since_check = 0
                _content_so_far = "".join(content_parts)
                if _detect_repetition(_content_so_far):
                    if reasoning_preview is not None:
                        reasoning_preview.close()
                    visible_state["renderer"].abort()
                    print(c(
                        "\n[LOOP] Model mengulang kalimat/baris yang sama "
                        "berulang-ulang di dalam jawaban aslinya "
                        "(degenerate loop pada content). Menghentikan "
                        "stream lebih awal untuk menghemat token.",
                        C.RED,
                    ))
                    raise RepetitionLoopError(
                        "Model mengulang teks yang sama di dalam content "
                        "(intra-response degenerate loop pada jawaban asli)."
                    )

        if reasoning_preview is not None:
            reasoning_preview.close()
        visible_tail = _flush_visible_text(visible_state)
        _print_stream_text(visible_tail, visible_state)
        visible_state["renderer"].finish()

    except LlamaServerStreamError as e:
        if reasoning_preview is not None:
            reasoning_preview.close()
        visible_state["renderer"].abort()
        print(c(f"\n[ERROR] server model melaporkan error di tengah stream: {e}", C.RED))
        raise
    except requests.exceptions.ConnectionError:
        if reasoning_preview is not None:
            reasoning_preview.close()
        visible_state["renderer"].abort()
        print(c(
            f"[ERROR] Tidak bisa konek ke server model di {url}. "
            f"Pastikan server model sudah jalan.",
            C.RED,
        ))
        raise
    except requests.exceptions.HTTPError as e:
        if reasoning_preview is not None:
            reasoning_preview.close()
        visible_state["renderer"].abort()

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

        if reasoning_preview is not None:
            reasoning_preview.close()
        visible_state["renderer"].abort()
        print(c(f"[ERROR] Streaming terputus/gagal: {type(e).__name__}: {e}", C.RED))
        raise
    except KeyboardInterrupt:

        if reasoning_preview is not None:
            reasoning_preview.close()
        visible_state["renderer"].abort()
        raise
    finally:
        if response is not None:
            response.close()

    content = "".join(full_parts)

    if native_tool_call_state:
        ordered = [native_tool_call_state[i] for i in sorted(native_tool_call_state.keys())]
        content += _native_tool_calls_to_blocks([{"function": e} for e in ordered])
    if debug:
        _debug_log("FULL-CONTENT", content)

    if last_finish_reason in state.TRUNCATION_FINISH_REASONS and not content.strip():
        comp_tok = last_usage.get("completion_tokens") if last_usage else None
        reason_tok = None
        if last_usage:
            reason_tok = (
                last_usage.get("reasoning_tokens")
                or (last_usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
                or (last_usage.get("output_tokens_details") or {}).get("reasoning_tokens")
            )
        detail = f"finish_reason={last_finish_reason!r}"
        if comp_tok is not None:
            detail += f", completion_tokens={comp_tok}"
        if reason_tok is not None:
            detail += f", reasoning_tokens={reason_tok}"
        raise TruncatedGenerationError(
            f"Server menghentikan generation karena batas token habis "
            f"SEBELUM model menghasilkan konten/tool_call apa pun ({detail}).",
            finish_reason=last_finish_reason,
            completion_tokens=comp_tok,
            reasoning_tokens=reason_tok,
        )
    if state.TOOL_OPEN in content and state.TOOL_CLOSE not in content:
        content += "\n" + state.TOOL_CLOSE
    return content
