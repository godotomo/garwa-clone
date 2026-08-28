"""tools/web_search.py
Dipecah otomatis dari tools.py (lihat tools/_state.py untuk state bersama).
"""
import json
import base64
import re
import xml.etree.ElementTree as ET

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
from .datetime_utils import _now_wib



def _query_needs_current_date(query: str) -> bool:
    q = query.lower()
    relative_terms = (
        "hari ini", "today", "terbaru", "terkini", "saat ini", "sekarang",
        "kemarin", "yesterday", "minggu ini", "this week", "bulan ini",
        "this month", "tahun ini", "this year", "latest", "breaking",
        "versi terbaru", "rilis terbaru", "update terbaru",
    )
    return any(term in q for term in relative_terms)


def _prepare_news_query(query: str) -> tuple[str, str]:
    """Return (original_query, query_for_google_news).

    Untuk query relatif, tanggal aktual WIB ditambahkan otomatis. Ini membuat
    web_search tetap aman walaupun model lupa memanggil local_now terlebih dulu.
    local_now tetap diekspos sebagai tool agar model dapat memakai timestamp
    aktual untuk konteks lain.
    """
    original = str(query or "").strip()
    if not original:
        return original, original

    if not _query_needs_current_date(original):
        return original, original

    now = _now_wib()
    date_text = now.strftime("%Y-%m-%d")
    year = now.strftime("%Y")
    # Hindari menambahkan tahun dua kali bila query sudah eksplisit menyebutnya.
    prepared = original
    if not re.search(r"\b20\d{2}\b", prepared):
        prepared = f"{prepared} {year}"
    # Google News cukup baik dengan date keyword; tanggal ISO mempersempit
    # hasil untuk permintaan "hari ini" tanpa bergantung pada tanggal model.
    prepared = f"{prepared} {date_text}"
    return original, prepared


def _remote_get(url: str, **kwargs):
    kwargs.setdefault("timeout", state._REMOTE_TIMEOUT)
    headers = dict(kwargs.get("headers") or {})
    headers.setdefault("User-Agent", "Garwa/1.0")
    kwargs["headers"] = headers
    return requests.get(url, **kwargs)


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    import html as _html
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


def _decode_google_news_url(source_url: str) -> str:
    match = re.search(r"news\.google\.com/rss/articles/([^?/]+)", source_url)
    if not match:
        return source_url
    encoded_id = match.group(1)

    try:
        decoded_bytes = base64.urlsafe_b64decode(encoded_id + "===")
        decoded_str = decoded_bytes.decode("latin1")
        if decoded_str.startswith("\x08\x13\x22"):
            decoded_str = decoded_str[3:]
        if decoded_str.endswith("\xd2\x01\x00"):
            decoded_str = decoded_str[:-3]
        arr = bytearray(decoded_str, "latin1")
        if arr:
            length = arr[0]
            candidate = (
                decoded_str[2:length + 1]
                if length >= 0x80
                else decoded_str[1:length + 1]
            )
            if candidate.startswith(("http://", "https://")):
                return candidate
    except Exception:
        pass

    # Fallback copied from agent.py's Google News resolver.
    try:
        page = _remote_get(source_url, allow_redirects=True)
        page.raise_for_status()
        sig_m = re.search(r'data-n-a-sg="([^"]+)"', page.text)
        ts_m = re.search(r'data-n-a-ts="([^"]+)"', page.text)
        if not (sig_m and ts_m):
            return source_url

        signature, timestamp = sig_m.group(1), ts_m.group(1)
        inner_payload = json.dumps([
            "garturlreq",
            [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
              None, None, None, None, None, 0, 1],
             "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
            encoded_id, int(timestamp), signature,
        ])
        f_req = json.dumps([[["Fbv4je", inner_payload, None, "generic"]]])
        resp = requests.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            headers={
                "User-Agent": "Garwa/1.0",
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            },
            data={"f.req": f_req},
            timeout=state._REMOTE_TIMEOUT,
        )
        resp.raise_for_status()
        body = resp.text.split("\n\n", 1)[1]
        outer = json.loads(body)
        inner = json.loads(outer[0][2])
        candidate = inner[1]
        if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
            return candidate
    except Exception:
        pass

    return source_url


_NEWS_LOCALES = {
    "id": ("id", "ID", "ID:id"),
    "en": ("en", "US", "US:en"),
}


def _resolve_news_locale(lang: str) -> tuple[str, str, str]:
    """Peta bahasa -> (hl, gl, ceid) untuk Google News RSS.

    `lang` yang tidak dikenal dianggap "auto" (default lokal Indonesia).
    """
    key = (str(lang or "").strip().lower() or "auto")
    if key in _NEWS_LOCALES:
        return _NEWS_LOCALES[key]
    return (state.GOOGLE_NEWS_HL, state.GOOGLE_NEWS_GL, state.GOOGLE_NEWS_CEID)


def _search_google_news_rss(query: str, max_results: int, lang: str = "auto") -> list[dict]:
    hl, gl, ceid = _resolve_news_locale(lang)
    response = _remote_get(
        "https://news.google.com/rss/search",
        params={
            "q": query,
            "hl": hl,
            "gl": gl,
            "ceid": ceid,
        },
        allow_redirects=True,
    )
    response.raise_for_status()
    root = ET.fromstring(response.content[:1_000_000])

    results = []
    for item in root.findall(".//item")[:max_results]:
        title = (item.findtext("title") or "").strip()
        redirect_url = (item.findtext("link") or "").strip()
        published = (item.findtext("pubDate") or "").strip()
        source_el = item.find("source")
        source = (source_el.text or "").strip() if source_el is not None else ""
        snippet = _html_to_text(item.findtext("description") or "")[:state._WEB_MAX_SNIPPET]
        if title and redirect_url:
            results.append({
                "title": title,
                "url": _decode_google_news_url(redirect_url),
                "snippet": snippet,
                "source": source,
                "published": published,
            })
    return results


def tool_web_search(query: str, max_results: int = 5, lang: str = "auto") -> str:
    """Cari berita/informasi terkini melalui Google News RSS.

    Bukan general web search. Gunakan untuk berita, event, pengumuman,
    dan perkembangan terkini.

    Parameter `lang` (opsional):
      - "id"  -> hasil berbahasa Indonesia (lokal Indonesia).
      - "en"  -> hasil berbahasa Inggris (lokal AS).
      - "auto" (default) -> coba bahasa Indonesia dulu; jika tidak ada hasil,
        otomatis fallback ke bahasa Inggris. Berguna untuk query yang
        relevan lintas bahasa (mis. berita internasional).

    PENTING: Untuk query relatif seperti "hari ini", "terbaru", "saat ini",
    "kemarin", atau "minggu ini", tool mengambil tanggal aktual WIB dari
    clock mesin dan menambahkannya ke query secara otomatis. Model tetap
    dianjurkan memanggil `local_now` terlebih dahulu agar mengetahui tanggal
    aktual sebelum menyusun pencarian.
    """
    query = str(query or "").strip()
    max_results = max(1, min(int(max_results), 10))
    if not query:
        return "[ERROR] query wajib diisi."

    original_query, search_query = _prepare_news_query(query)
    lang = (str(lang or "").strip().lower() or "auto")

    def _run(locale: str):
        try:
            return _search_google_news_rss(search_query, max_results, locale)
        except ET.ParseError as e:
            return f"[ERROR: web_search RSS tidak valid -- {e}]"
        except requests.RequestException as e:
            return f"[ERROR: web_search gagal -- {e}]"
        except Exception as e:
            return f"[ERROR: web_search gagal -- {e}]"

    results = _run(lang)
    # Fallback otomatis: mode auto + hasil kosong -> coba bahasa Inggris.
    if lang == "auto" and isinstance(results, list) and not results:
        results = _run("en")

    if isinstance(results, str):
        return results
    if not results:
        return f"[web_search] Tidak ada hasil untuk query: {query!r}"

    lines = [f"[web_search] {len(results)} hasil Google News untuk {original_query!r}:"]
    for i, item in enumerate(results, 1):
        meta = " / ".join(x for x in (item["source"], item["published"]) if x)
        suffix = f" ({meta})" if meta else ""
        lines.append(
            f"{i}. {item['title']}{suffix}\n"
            f"   {item['url']}\n"
            f"   {item['snippet']}"
        )
    return "\n".join(lines)
