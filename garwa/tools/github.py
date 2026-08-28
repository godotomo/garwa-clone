"""tools/github.py
Dipecah otomatis dari tools.py (lihat tools/_state.py untuk state bersama).
"""
import base64
import re
from urllib.parse import quote

import requests

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
from .web_search import _remote_get



def _github_headers() -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Garwa/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if state.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {state.GITHUB_TOKEN}"
    return headers


def _github_repo_valid(repo: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""))


def tool_github_search_repos(query: str, max_results: int = 5) -> str:
    """Cari repository publik GitHub berdasarkan query/qualifier GitHub."""
    query = str(query or "").strip()
    max_results = max(1, min(int(max_results), 10))
    if not query:
        return "[ERROR] query wajib diisi."
    try:
        resp = _remote_get(
            f"{state.GITHUB_API}/search/repositories",
            params={"q": query, "per_page": max_results},
            headers=_github_headers(),
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])[:max_results]
    except requests.RequestException as e:
        return f"[ERROR: github_search_repos gagal -- {e}]"
    except Exception as e:
        return f"[ERROR: github_search_repos gagal -- {e}]"

    if not items:
        return f"[github_search_repos] Tidak ada hasil untuk query: {query!r}"

    lines = [f"[github_search_repos] {len(items)} hasil untuk {query!r}:"]
    for i, item in enumerate(items, 1):
        desc = (item.get("description") or "").strip()
        if len(desc) > 300:
            desc = desc[:300] + "…"
        lines.append(
            f"{i}. {item.get('full_name', '-')}"
            f" ({item.get('language') or '-'}, ★{item.get('stargazers_count', 0)})\n"
            f"   {item.get('html_url', '')}\n   {desc}"
        )
    return "\n".join(lines)


def tool_github_search_code(query: str, max_results: int = 5) -> str:
    """Cari potongan kode publik GitHub. Endpoint ini membutuhkan token."""
    query = str(query or "").strip()
    max_results = max(1, min(int(max_results), 10))
    if not query:
        return "[ERROR] query wajib diisi."
    if not state.GITHUB_TOKEN:
        return (
            "[ERROR] github_search_code membutuhkan GITHUB_TOKEN. "
            "Set environment GITHUB_TOKEN atau isi config.py. "
            "github_search_repos/github_read_file publik dapat digunakan "
            "tanpa token."
        )
    try:
        resp = _remote_get(
            f"{state.GITHUB_API}/search/code",
            params={"q": query, "per_page": max_results},
            headers=_github_headers(),
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])[:max_results]
    except requests.RequestException as e:
        return f"[ERROR: github_search_code gagal -- {e}]"
    except Exception as e:
        return f"[ERROR: github_search_code gagal -- {e}]"

    if not items:
        return f"[github_search_code] Tidak ada hasil untuk query: {query!r}"

    lines = [f"[github_search_code] {len(items)} hasil untuk {query!r}:"]
    for i, item in enumerate(items, 1):
        repo = item.get("repository", {}).get("full_name", "-")
        lines.append(
            f"{i}. {repo}:{item.get('path', '-')}\n"
            f"   {item.get('html_url', '')}"
        )
    return "\n".join(lines)


def tool_github_read_file(repo: str, path: str, ref: str = None) -> str:
    """Baca satu file dari repo GitHub publik; hasil dibatasi agar context aman."""
    repo = str(repo or "").strip()
    path = str(path or "").strip().lstrip("/")
    if not _github_repo_valid(repo):
        return "[ERROR] repo harus berformat 'owner/name'."
    if not path:
        return "[ERROR] path wajib diisi."

    try:
        resp = _remote_get(
            f"{state.GITHUB_API}/repos/{repo}/contents/{quote(path, safe='/')}",
            params={"ref": ref} if ref else None,
            headers=_github_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        return f"[ERROR: github_read_file gagal mengambil {repo}:{path} -- {e}]"
    except Exception as e:
        return f"[ERROR: github_read_file gagal -- {e}]"

    if isinstance(data, list):
        return f"[ERROR] {path!r} adalah direktori, bukan file."
    if data.get("type") != "file":
        return f"[ERROR] {repo}:{path} bukan file biasa."

    content_b64 = data.get("content")
    if not content_b64:
        return f"[ERROR] GitHub tidak mengembalikan content untuk {repo}:{path}."

    try:
        content = base64.b64decode(
            content_b64.replace("\n", ""), validate=False
        ).decode("utf-8", errors="replace")
    except Exception as e:
        return f"[ERROR] Gagal decode {repo}:{path} -- {e}"

    truncated = len(content) > state._GITHUB_MAX_CONTENT
    if truncated:
        content = content[:state._GITHUB_MAX_CONTENT]
    suffix = "\n…[dipotong oleh github_read_file]" if truncated else ""
    return (
        f"[github_read_file] {repo}:{path}@{ref or 'default'}:\n"
        f"{content}{suffix}"
    )
