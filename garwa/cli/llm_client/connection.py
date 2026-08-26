"""cli/llm_client/connection.py
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



def _auth_headers(api_key: str = "") -> dict:
    """Header Authorization Bearer kalau api_key diisi, dict kosong kalau tidak.

    Dipanggil di kedua path (stream & non-stream) supaya konsisten -- kalau
    server model dijalankan dengan --api-key (lihat notebook
    llama_server_cloudflare_tunnel_v2.ipynb) tapi CLI ini tidak mengirim
    header ini, semua request akan gagal dengan 401 Unauthorized.
    """
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _fetch_server_n_ctx(base: str, api_key: str = "",
                        timeout: float = state.LLAMA_SERVER_CHECK_TIMEOUT):
    """Ambil ukuran context window (n_ctx) yang SUNGGUHAN sedang aktif di
    server model, lewat endpoint bawaan '/props'.

    Context window sungguhan ditentukan di sisi server (mis. hasil fallback
    ladder --ctx-size di notebook Kaggle), bukan dari flag statis
    `--context-window`. Query langsung ke server menghilangkan kelas bug
    di mana context_manager menganggap prompt "aman" padahal server
    menolaknya (400 exceed_context_size_error).

    '/props' adalah endpoint standar server model (llama.cpp) yang membalas
    metadata server berjalan. Field n_ctx bisa muncul di dua lokasi
    tergantung versi llama.cpp:
      - top-level: {"n_ctx": 65536, ...}
      - bersarang: {"default_generation_settings": {"n_ctx": 65536, ...}}
    Keduanya dicoba, top-level diprioritaskan kalau ada.

    Return: int n_ctx kalau berhasil, None kalau endpoint tidak ada/gagal
    diparse (server versi lama, atau proxy yang tidak meneruskan '/props')
    -- caller harus fallback ke nilai --context-window statis dalam kasus
    ini, bukan dianggap error fatal.
    """
    props_url = base.rstrip("/") + "/props"
    try:
        resp = requests.get(props_url, headers=_auth_headers(api_key), timeout=timeout)
    except requests.exceptions.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    n_ctx = data.get("n_ctx")
    if n_ctx is None:
        default_gen = data.get("default_generation_settings")
        if isinstance(default_gen, dict):
            n_ctx = default_gen.get("n_ctx")

    try:
        return int(n_ctx) if n_ctx is not None else None
    except (TypeError, ValueError):
        return None


def check_llama_server_connection(url: str, api_key: str = "",
                                   timeout: float = state.LLAMA_SERVER_CHECK_TIMEOUT):
    """Cek apakah server model di `url` bisa dijangkau, sekalian ambil nama
    model yang sedang di-load lewat endpoint '/v1/models' DAN context
    window sungguhan yang aktif lewat endpoint '/props'.

    PENTING: yang jadi patokan "server hidup" bukan status code HTTP-nya
    (build server model yang aneh/proxy di depannya bisa saja balas non-200
    -- itu tetap berarti proses server ADA & merespons di alamat itu),
    melainkan apakah koneksi TCP/HTTP-nya berhasil sama sekali. Hanya
    exception level-koneksi (ConnectionError, Timeout, dll -- server benar-
    benar tidak merespons) yang dianggap "tidak terjangkau". Body response
    baru diparse sebagai JSON kalau statusnya 200 -- kalau gagal/format
    tidak dikenali, model_id/n_ctx tetap None tapi koneksi tetap dianggap
    ok.

    Return: (ok: bool, detail: str | None, model_id: str | None, n_ctx: int | None).
    - `detail` diisi pesan error singkat kalau ok=False, None kalau ok=True.
    - `model_id` diisi nilai 'data[0].id' dari '/v1/models' kalau berhasil
      diparse, None kalau tidak tersedia/gagal diparse.
    - `n_ctx` diisi context window sungguhan dari '/props' kalau endpoint
      tersedia & berhasil diparse (lihat _fetch_server_n_ctx()), None kalau
      tidak -- caller sebaiknya fallback ke --context-window statis dalam
      kasus ini.
    """
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False, f"URL tidak valid: {url!r}", None, None
        base = f"{parsed.scheme}://{parsed.netloc}"
    except Exception as e:
        return False, f"URL tidak valid: {url!r} ({e})", None, None

    models_url = base.rstrip("/") + "/v1/models"
    try:
        resp = requests.get(models_url, headers=_auth_headers(api_key), timeout=timeout)
    except requests.exceptions.RequestException as e:
        return False, f"{type(e).__name__}: {e}", None, None

    model_id = None
    if resp.status_code == 200:
        try:
            data = resp.json().get("data") or []
            if data and isinstance(data, list):
                model_id = data[0].get("id")
        except Exception:

            pass

    n_ctx = _fetch_server_n_ctx(base, api_key, timeout)

    return True, None, model_id, n_ctx


def _apply_detected_n_ctx(args, n_ctx: int, source_label: str = "server"):
    """Override `args.context_window` (dipakai context_manager untuk
    trimming/summarization history) memakai n_ctx SUNGGUHAN yang baru saja
    dideteksi dari server lewat '/props', bukan flag statis --context-window
    yang gampang basi (lihat docstring _fetch_server_n_ctx()).

    Dipanggil dari DUA tempat terpisah (main() untuk mode interaktif/auto,
    run_overnight_mode() untuk mode overnight) yang masing-masing melakukan
    pengecekan koneksi sendiri -- helper ini memastikan logika override &
    pesan yang dicetak konsisten di keduanya, tidak terduplikasi/divergen.
    """
    if not n_ctx or n_ctx <= 0:
        return

    if source_label == "/props":
        state._LLAMA_CPP_SERVER_DETECTED[0] = True
    effective = max(n_ctx - state.CONTEXT_WINDOW_SAFETY_MARGIN, state.MIN_CONTEXT_WINDOW)
    old = args.context_window
    args.context_window = effective
    if old != effective:
        print(c(
            f"[OK] Context window terdeteksi otomatis dari {source_label}: "
            f"n_ctx={n_ctx} -> budget history dipakai {effective} token "
            f"(disisakan {state.CONTEXT_WINDOW_SAFETY_MARGIN} token untuk overhead "
            f"template/jawaban model; sebelumnya asumsi statis {old}).",
            C.GREEN,
        ))
