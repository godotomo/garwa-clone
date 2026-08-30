"""Reproduksi nyata IndexError pada pemrosesan respon SSE sangat panjang
berisi kode markdown.

Instruksi aktif meminta: buat tes nyata (bukan tebakan) dengan membuat
respon SSE sangat panjang berisi kode markdown untuk mereproduksi error
IndexError yang muncul sebagai:
  [ERROR] Giliran ini berhenti karena error tak terduga: IndexError: list index out of range

Alur yang direproduksi = jalur stream_call.py:
  _call_llama_server_stream -> tiap chunk -> _extract_stream_content
  -> _stream_visible_text -> _print_stream_text -> renderer.feed
  -> _detect_repetition -> dst.
"""
import json

import pytest

from garwa.cli import _state as state
from garwa.cli.markdown_render import MarkdownTerminalRenderer
from garwa.cli.stream_parse import _extract_stream_content
from garwa.cli.stream_parse import _flush_visible_text
from garwa.cli.stream_parse import _print_stream_text
from garwa.cli.stream_parse import _stream_visible_text
from garwa.cli.text_utils import _detect_repetition


def _make_sse_chunk(content: str) -> dict:
    """Buat satu chunk SSE OpenAI-compatible berisi delta.content."""
    return {
        "choices": [{"delta": {"content": content}, "finish_reason": None}],
    }


def _make_sse_trailer() -> dict:
    """Chunk trailer yang hanya berisi usage (choices kosong) -- bentuk nyata
    dipakai sebagian backend."""
    return {"choices": [], "usage": {"completion_tokens": 100, "prompt_tokens": 10}}


def _long_markdown_code_response() -> str:
    """Respon SSE sangat panjang berisi banyak blok kode markdown + tabel +
    heading, mirip output coding agent yang menjawab dengan banyak file."""
    blocks = []
    for i in range(120):
        blocks.append(
            f"### File {i}\n\n"
            f"Berikut implementasi modul ke-{i}.\n\n"
            "```python\n"
            f"def func_{i}(x):\n"
            f"    \"\"\"Dokumen fungsi {i}.\"\"\"\n"
            f"    return x + {i}\n"
            "\n"
            f"class Klass{i}:\n"
            f"    def __init__(self):\n"
            f"        self.value = {i}\n"
            "```\n\n"
            "| kolom_a | kolom_b |\n"
            "|---------|---------|\n"
            f"| {i}      | {i * 2}    |\n\n"
        )
    return "".join(blocks)


def _feed_entire_response(text: str):
    """Feed seluruh respon lewat renderer (jalur _render_markdown_once)."""
    renderer = MarkdownTerminalRenderer()
    renderer.feed(text)
    renderer.finish()


def _feed_chunk_by_chunk(text: str, chunk_size: int = 64):
    """Feed respon chunk-by-chunk (jalur streaming nyata di stream_call.py),
    melewati _stream_visible_text -> _print_stream_text -> renderer.feed."""
    visible_state = {
        "in_tool": False,
        "pending": "",
        "ws_hold": "",
        "started": False,
        "renderer": MarkdownTerminalRenderer(),
    }
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        delta = _extract_stream_content(_make_sse_chunk(chunk))
        visible = _stream_visible_text(visible_state, delta)
        _print_stream_text(visible, visible_state)
    tail = _flush_visible_text(visible_state)
    _print_stream_text(tail, visible_state)
    visible_state["renderer"].finish()


def test_sse_long_markdown_no_indexerror_renderer_once():
    """Feed seluruh respon markdown panjang sekaligus ke renderer -- TIDAK
    boleh IndexError."""
    text = _long_markdown_code_response()
    _feed_entire_response(text)


def test_sse_long_markdown_no_indexerror_chunk_by_chunk():
    """Feed respon markdown panjang chunk-by-chunk (jalur streaming) -- TIDAK
    boleh IndexError."""
    text = _long_markdown_code_response()
    _feed_chunk_by_chunk(text)


def test_sse_long_markdown_with_trailer_no_indexerror():
    """Jalur streaming penuh termasuk chunk trailer usage (choices kosong) --
    TIDAK boleh IndexError."""
    text = _long_markdown_code_response()
    visible_state = {
        "in_tool": False,
        "pending": "",
        "ws_hold": "",
        "started": False,
        "renderer": MarkdownTerminalRenderer(),
    }
    for i in range(0, len(text), 128):
        chunk = text[i:i + 128]
        delta = _extract_stream_content(_make_sse_chunk(chunk))
        visible = _stream_visible_text(visible_state, delta)
        _print_stream_text(visible, visible_state)
    # trailer: choices kosong + usage
    assert _extract_stream_content(_make_sse_trailer()) == ""
    tail = _flush_visible_text(visible_state)
    _print_stream_text(tail, visible_state)
    visible_state["renderer"].finish()


def test_sse_chunk_split_inside_code_fence():
    """Memotong respon tepat di tengah fence markdown (```) -- TIDAK boleh
    IndexError."""
    text = "```python\nprint('halo')\n```\n```\nprint('x')\n```\n"
    _feed_chunk_by_chunk(text, chunk_size=3)


def test_sse_chunk_split_inside_table():
    """Memotong respon tepat di tengah baris tabel markdown -- TIDAK boleh
    IndexError."""
    text = "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n"
    _feed_chunk_by_chunk(text, chunk_size=5)


def test_sse_chunk_split_inside_heading_and_latex():
    """Memotong respon di tengah heading dan formula latex -- TIDAK boleh
    IndexError."""
    text = "## Judul\n\n$f(x) = \\frac{a}{b}$\n\n### Sub\n\n$x^2$\n"
    _feed_chunk_by_chunk(text, chunk_size=7)


def test_detect_repetition_on_long_markdown_no_indexerror():
    """Jalankan deteksi repetisi pada respon markdown panjang (dipanggil
    setiap REPEAT_CHECK_EVERY char di stream_call.py) -- TIDAK boleh
    IndexError."""
    text = _long_markdown_code_response()
    # deteksi repetisi dipanggil per potongan akumulasi
    for i in range(0, len(text), 512):
        _detect_repetition(text[:i + 512])


def test_extract_tool_call_with_long_markdown_surrounding():
    """extract_tool_call dipanggil pada teks yang dikelilingi markdown panjang
    berisi kode -- TIDAK boleh IndexError."""
    from garwa.cli.json_repair import extract_tool_call
    text = _long_markdown_code_response()
    # tanpa tool_call -> harus None, None
    name, args = extract_tool_call(text)
    assert name is None and args is None


def test_convert_alt_tool_call_syntax_with_long_markdown():
    """_convert_alt_tool_call_syntax dipanggil pada respon markdown panjang
    (no-op jika tidak ada <|tool_call|>) -- TIDAK boleh IndexError."""
    from garwa.cli.tool_schema.alt_syntax import _convert_alt_tool_call_syntax
    text = _long_markdown_code_response()
    out = _convert_alt_tool_call_syntax(text)
    assert out == text


def test_native_tool_calls_accumulate_with_long_markdown():
    """Akumulasi native tool calls di tengah markdown panjang -- TIDAK boleh
    IndexError."""
    from garwa.cli.tool_schema import _accumulate_stream_tool_calls
    native_state = {}
    text = _long_markdown_code_response()
    # chunk dengan tool call di tengah markdown
    tc_chunk = {
        "choices": [{
            "delta": {
                "tool_calls": [{
                    "index": 0,
                    "function": {"name": "read_file", "arguments": '{"path": "x.py"}'},
                }],
            },
            "finish_reason": None,
        }],
    }
    for i in range(0, len(text), 256):
        _accumulate_stream_tool_calls(_make_sse_chunk(text[i:i + 256]), native_state)
    _accumulate_stream_tool_calls(tc_chunk, native_state)
