"""tools/firecrawl.py
Tool integrasi Firecrawl (https://firecrawl.dev) via REST API langsung.

Menyediakan tiga tool:
  - tool_firecrawl_scrape : ambil konten satu halaman web (markdown).
  - tool_firecrawl_search : cari di web lalu ambil konten halaman teratas.
  - tool_firecrawl_crawl   : crawl satu situs (dengan polling status).

API key dikelola via slash-command `/firecrawl-key` (disimpan ke
config pengguna) atau environment `FIRECRAWL_API_KEY`. Nilai default
endpoint: https://api.firecrawl.dev/v1 (bisa di-override lewat env
`FIRECRAWL_API_URL`).
"""
import time

import requests

from . import _state as state
from .web_search import _remote_get


def _firecrawl_headers() -> dict:
    headers = {
        "Accept": "application/json",
        "User-Agent": "Garwa/1.0",
        "Content-Type": "application/json",
    }
    if state.FIRECRAWL_API_KEY:
        headers["Authorization"] = f"Bearer {state.FIRECRAWL_API_KEY}"
    return headers


def _no_key_msg(tool: str) -> str:
    return (
        f"[ERROR: {tool} membutuhkan FIRECRAWL_API_KEY. "
        "Set environment FIRECRAWL_API_KEY atau jalankan slash-command "
        "`/firecrawl-key <token>` untuk menyimpannya ke config pengguna.]"
    )


def _post(url: str, payload: dict):
    """POST JSON ke Firecrawl dengan timeout default dari state."""
    return requests.post(
        url,
        json=payload,
        headers=_firecrawl_headers(),
        timeout=state._REMOTE_TIMEOUT,
    )


def _snip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def tool_firecrawl_scrape(url: str, formats: str = "markdown") -> str:
    """Ambil konten satu halaman web menjadi teks markdown via Firecrawl."""
    url = str(url or "").strip()
    if not url:
        return "[ERROR] url wajib diisi."
    if not state.FIRECRAWL_API_KEY:
        return _no_key_msg("firecrawl_scrape")

    allowed = {"markdown", "html", "rawHtml", "links", "screenshot"}
    fmt_list = [f.strip() for f in str(formats).split(",") if f.strip()]
    fmt_list = [f for f in fmt_list if f in allowed] or ["markdown"]

    try:
        resp = _post(
            f"{state.FIRECRAWL_API_URL}/scrape",
            {"url": url, "formats": fmt_list},
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        return f"[ERROR: firecrawl_scrape gagal -- {e}]"
    except Exception as e:
        return f"[ERROR: firecrawl_scrape gagal -- {e}]"

    if not data.get("success"):
        err = data.get("error") or "respons tanpa success=true"
        return f"[ERROR: firecrawl_scrape -- {err}]"

    md = data.get("data", {}).get("markdown") or ""
    if not md:
        return f"[firecrawl_scrape] Tidak ada konten markdown untuk {url!r}."
    return f"[firecrawl_scrape] {url}\n\n{_snip(md, state.OUTPUT_CAP_BYTES)}"


def tool_firecrawl_search(query: str, limit: int = 5) -> str:
    """Cari di web via Firecrawl dan tampilkan judul+URL hasil teratas."""
    query = str(query or "").strip()
    limit = max(1, min(int(limit), 10))
    if not query:
        return "[ERROR] query wajib diisi."
    if not state.FIRECRAWL_API_KEY:
        return _no_key_msg("firecrawl_search")

    try:
        resp = _post(
            f"{state.FIRECRAWL_API_URL}/search",
            {"query": query, "limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        return f"[ERROR: firecrawl_search gagal -- {e}]"
    except Exception as e:
        return f"[ERROR: firecrawl_search gagal -- {e}]"

    if not data.get("success"):
        err = data.get("error") or "respons tanpa success=true"
        return f"[ERROR: firecrawl_search -- {err}]"

    results = data.get("data") or []
    if not results:
        return f"[firecrawl_search] Tidak ada hasil untuk query: {query!r}"

    lines = [f"[firecrawl_search] {len(results)} hasil untuk {query!r}:"]
    for i, item in enumerate(results, 1):
        title = (item.get("title") or "-").strip()
        link = item.get("url") or item.get("href") or "-"
        desc = _snip(item.get("description") or item.get("markdown") or "", 300)
        lines.append(f"{i}. {title}\n   {link}\n   {desc}")
    return "\n".join(lines)


def tool_firecrawl_crawl(url: str, limit: int = 10, max_depth: int = 3) -> str:
    """Crawl satu situs via Firecrawl, polling status sampai selesai."""
    url = str(url or "").strip()
    limit = max(1, min(int(limit), 100))
    max_depth = max(1, min(int(max_depth), 10))
    if not url:
        return "[ERROR] url wajib diisi."
    if not state.FIRECRAWL_API_KEY:
        return _no_key_msg("firecrawl_crawl")

    try:
        resp = _post(
            f"{state.FIRECRAWL_API_URL}/crawl",
            {"url": url, "limit": limit, "maxDepth": max_depth},
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        return f"[ERROR: firecrawl_crawl gagal -- {e}]"
    except Exception as e:
        return f"[ERROR: firecrawl_crawl gagal -- {e}]"

    if not data.get("success"):
        err = data.get("error") or "respons tanpa success=true"
        return f"[ERROR: firecrawl_crawl -- {err}]"

    job_id = data.get("id")
    if not job_id:
        return "[ERROR: firecrawl_crawl -- tidak ada job id pada respons.]"

    # Polling status job. Batas waktu total ~120 detik agar tidak menggantung.
    deadline = time.time() + 120
    status = None
    while time.time() < deadline:
        try:
            poll = _remote_get(f"{state.FIRECRAWL_API_URL}/crawl/{job_id}")
            poll.raise_for_status()
            job = poll.json()
        except requests.RequestException as e:
            return f"[ERROR: firecrawl_crawl polling gagal -- {e}]"
        except Exception as e:
            return f"[ERROR: firecrawl_crawl polling gagal -- {e}]"

        status = job.get("status")
        if status in ("completed", "failed", "cancelled"):
            break
        time.sleep(5)

    if status != "completed":
        return (
            f"[firecrawl_crawl] Job {job_id} belum selesai (status={status!r}). "
            "Coba lagi nanti atau cek dashboard Firecrawl."
        )

    pages = job.get("data") or []
    if not pages:
        return f"[firecrawl_crawl] Job {job_id} selesai tanpa halaman terindeks."

    lines = [f"[firecrawl_crawl] {len(pages)} halaman dari {url!r} (job {job_id}):"]
    for i, page in enumerate(pages, 1):
        md = page.get("markdown") or page.get("content") or ""
        title = (page.get("metadata", {}) or {}).get("title") or "-"
        page_url = page.get("metadata", {}).get("sourceURL") or page.get("url") or "-"
        lines.append(f"{i}. {title}\n   {page_url}\n   {_snip(md, 300)}")
    return "\n".join(lines)
