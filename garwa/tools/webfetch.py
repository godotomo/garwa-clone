"""tools/webfetch.py
Dipecah otomatis dari tools.py (lihat tools/_state.py untuk state bersama).
"""
import os
import sys
import glob
import shlex
import signal
import subprocess
import difflib
import json
import ast
import base64
import re
import tempfile
import threading
import xml.etree.ElementTree as ET
from urllib.parse import quote
from datetime import datetime, timezone, timedelta

# termios/tty dipakai untuk menyimpan & mengembalikan mode terminal di
# sekitar pemanggilan tool_bash -- jaring pengaman kalau command yang
# dijalankan mengubah mode terminal (mis. stty -echo / raw, program
# interaktif) dan tidak mengembalikannya. Hanya tersedia di POSIX.
try:
    import termios
    _HAS_TERMIOS = True
except ImportError:
    _HAS_TERMIOS = False

import requests

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False

from .. import db as dbmod

try:
    from .. import repo_map as repo_map_mod
except ImportError:
    # repo_map hanya dipakai oleh tool repo_map/outline_file (opsional).
    # Jangan sampai seluruh tools.py (dan cli.py yang meng-import-nya
    # di top-level) gagal start hanya karena modul opsional ini belum ada.
    repo_map_mod = None

try:
    from .. import security as security_mod
except ImportError:
    security_mod = None

try:
    from .. import config as config_mod
except ImportError:
    config_mod = None
from . import _state as state
from .bash_tool import _cap_output



def _webfetch_accept_header(format: str) -> str:
    if format == "markdown":
        return "text/markdown;q=1.0, text/x-markdown;q=0.9, text/plain;q=0.8, text/html;q=0.7, */*;q=0.1"
    if format == "text":
        return "text/plain;q=1.0, text/markdown;q=0.9, text/html;q=0.8, */*;q=0.1"
    if format == "html":
        return "text/html;q=1.0, application/xhtml+xml;q=0.9, text/plain;q=0.8, text/markdown;q=0.7, */*;q=0.1"
    return "*/*"


def _webfetch_mime_from(content_type: str) -> str:
    return (content_type.split(";", 1)[0] or "").strip().lower()


def _webfetch_is_textual_mime(mime: str) -> bool:
    return (
        not mime
        or mime.startswith("text/")
        or mime == "application/json"
        or mime.endswith("+json")
        or mime == "application/xml"
        or mime.endswith("+xml")
        or mime == "application/javascript"
        or mime == "application/x-javascript"
    )


def _webfetch_html_to_text(html: str) -> str:
    """Ekstrak teks dari HTML, buang script/style/noscript/iframe/object/embed."""
    if not _HAS_BS4:
        # Fallback tanpa bs4: buang tag dengan regex sederhana.
        text = re.sub(r"<(script|style|noscript|iframe|object|embed)[^>]*>.*?</\1>",
                      " ", html, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe", "object", "embed"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def _webfetch_html_to_markdown(html: str) -> str:
    """Konversi HTML ke Markdown sederhana (port dari TurndownService opencode).

    Tanpa dependensi turndown, kita lakukan konversi dasar: heading, link,
    bold/italic, code, list, dan paragraf. Ini cukup untuk sebagian besar
    halaman dokumentasi/berita.
    """
    if not _HAS_BS4:
        return _webfetch_html_to_text(html)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "meta", "link"]):
        tag.decompose()

    lines = []

    def render(node):
        if isinstance(node, str):
            return node
        name = node.name
        if name is None:
            return node.get_text()
        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(name[1])
            return f"\n\n{'#' * level} {node.get_text(strip=True)}\n\n"
        if name == "a":
            href = node.get("href", "")
            text = node.get_text(strip=True)
            return f"[{text}]({href})" if href and text else text
        if name in ("strong", "b"):
            return f"**{node.get_text(strip=True)}**"
        if name in ("em", "i"):
            return f"*{node.get_text(strip=True)}*"
        if name == "code":
            return f"`{node.get_text()}`"
        if name == "pre":
            return f"\n\n```\n{node.get_text()}\n```\n\n"
        if name in ("ul", "ol"):
            items = []
            for li in node.find_all("li", recursive=False):
                items.append(f"- {li.get_text(strip=True)}")
            return "\n" + "\n".join(items) + "\n"
        if name in ("p", "div", "section", "article", "blockquote"):
            inner = "".join(render(c) for c in node.children)
            return f"\n\n{inner.strip()}\n\n"
        if name == "br":
            return "\n"
        if name == "hr":
            return "\n\n---\n\n"
        # Default: render children.
        return "".join(render(c) for c in node.children)

    for child in soup.children:
        lines.append(render(child))

    text = "".join(lines)
    # Rapikan whitespace berlebih.
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def tool_webfetch(url: str, format: str = "markdown", timeout: int = None) -> str:
    """Fetch konten dari URL HTTP/HTTPS dan kembalikan sebagai text/markdown/html.

    Port dari opencode `tool/webfetch.ts`. Default format adalah markdown.
    Tool ini read-only. Hasil teks besar dibatasi (cap) agar tidak membanjiri
    context window.
    """
    url = str(url or "").strip()
    if not url:
        return "[ERROR] url wajib diisi."

    # Validasi skema URL (hanya http/https).
    try:
        parsed = requests.utils.urlparse(url)
    except Exception:
        parsed = None
    if not parsed or parsed.scheme not in ("http", "https"):
        return "[ERROR] URL harus menggunakan http:// atau https://."

    fmt = str(format or "markdown").strip().lower()
    if fmt not in ("text", "markdown", "html"):
        fmt = "markdown"

    if timeout is None:
        timeout = state._WEBFETCH_DEFAULT_TIMEOUT
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        timeout = state._WEBFETCH_DEFAULT_TIMEOUT
    timeout = max(1, min(timeout, state._WEBFETCH_MAX_TIMEOUT))

    headers = {
        "User-Agent": state._WEBFETCH_BROWSER_UA,
        "Accept": _webfetch_accept_header(fmt),
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=timeout, stream=True)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        mime = _webfetch_mime_from(content_type)

        # Tolak image (kecuali svg) dan tipe non-tekstual.
        if mime.startswith("image/") and mime not in ("image/svg+xml", "image/vnd.fastbidsheet"):
            return f"[ERROR] Tipe konten gambar tidak didukung: {mime}"
        if not _webfetch_is_textual_mime(mime):
            return f"[ERROR] Tipe konten file tidak didukung: {mime}"

        # Baca body dengan batas byte.
        chunks = []
        total = 0
        for chunk in resp.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > state._WEBFETCH_MAX_BYTES:
                return f"[ERROR] Respons terlalu besar (melebihi {state._WEBFETCH_MAX_BYTES} byte)."
            chunks.append(chunk)
        body = b"".join(chunks)
    except requests.Timeout:
        return f"[ERROR] Request timed out setelah {timeout} detik."
    except requests.RequestException as e:
        return f"[ERROR: webfetch gagal -- {e}]"
    except Exception as e:
        return f"[ERROR: webfetch gagal -- {e}]"

    content = body.decode("utf-8", errors="replace")

    # Konversi sesuai format (hanya jika konten HTML).
    if "text/html" in content_type:
        if fmt == "markdown":
            content = _webfetch_html_to_markdown(content)
        elif fmt == "text":
            content = _webfetch_html_to_text(content)
        # fmt == "html": biarkan apa adanya.

    return _cap_output(
        f"[webfetch] {url} (content-type: {content_type or 'unknown'}, format: {fmt}):\n{content}"
    )
