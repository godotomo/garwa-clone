"""cli/llm_client/openrouter_cache.py
Dipecah lebih lanjut dari cli/llm_client.py.
"""
import copy
import os
from urllib.parse import urlparse

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from .. import _state as state



def _wants_openrouter_cache_control(url: str, model: str) -> bool:
    """True kalau request ini menuju OpenRouter.

    Sejak riset dokumentasi resmi OpenRouter (Prompt Caching), SEMUA provider
    OpenRouter mendukung prompt caching:
      - Implicit/otomatis (OpenAI, DeepSeek, Gemini 2.5, dll) -- cache dipicu
        otomatis oleh OpenRouter/provider tanpa perlu marker apapun.
      - Explicit cache breakpoints (Anthropic, Alibaba Qwen, DeepSeek, Z.AI,
        Gemini) -- butuh marker `cache_control` per-message untuk kontrol
        halus (system_and_3).

    Karena OpenRouter menggunakan provider sticky routing untuk memaksimalkan
    cache hit, menerapkan marker `cache_control` ke SEMUA model (bukan hanya
    prefix tertentu) tidak merusak apa-apa: untuk provider implicit marker
    diabaikan/dinormalisasi, untuk provider explicit marker dipakai. Jadi
    fungsi ini mengembalikan True untuk SEMUA model yang lewat OpenRouter.

    Dicek per-request (bukan sekali di startup seperti deteksi llama.cpp)
    karena `model` bisa berbeda-beda kalau CLI ini nanti mendukung ganti
    model di tengah sesi -- tidak ada state global yang perlu disinkronkan.
    """
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    return "openrouter.ai" in host


def _build_openrouter_session_id(session_id: str = None, max_len: int = 256) -> str:
    """Bangun `session_id` yang aman untuk sticky routing OpenRouter.

    OpenRouter memakai `session_id` (body) atau header `x-session-id` sebagai
    kunci sticky routing: request dalam sesi yang sama dijamin diarahkan ke
    provider yang sama sehingga prompt cache tetap hangat (lihat riset
    dokumentasi resmi -- sticky routing aktif sejak request pertama bila
    `session_id` diberikan, bukan menunggu cache hit).

    Sumber session id (prioritas):
      1. Argumen eksplisit `session_id` (dari caller).
      2. Env var `GARWA_SESSION_ID` (di-set CLI saat sesi dibuat/di-resume).
      3. Fallback: string kosong -> caller memutuskan tidak memakai session.

    Aturan OpenRouter: `session_id` maksimal 256 karakter. Kalau sumber lebih
    panjang dari `max_len`, di-truncate (pakai hash SHA-256 untuk menghindari
    dua session berbeda menghasilkan prefix identik yang menempel di provider
    yang sama).
    """
    raw = session_id or os.environ.get("GARWA_SESSION_ID") or ""
    raw = str(raw).strip()
    if not raw:
        return ""
    if len(raw) <= max_len:
        return raw
    # Terlalu panjang: pakai hash penuh agar unik, bukan sekadar potongan
    # prefix yang bisa bertabrakan antar session.
    import hashlib
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _apply_openrouter_session_id(payload: dict, session_id: str = None) -> dict:
    """Suntik `session_id` ke payload bila ada sumber session yang valid.

    `payload` dimutasi IN PLACE dan dikembalikan (tidak deep-copy -- ini
    payload yang baru dibangun caller, aman diubah). Hanya menambahkan field
    `session_id` bila hasil `_build_openrouter_session_id` tidak kosong, jadi
    kalau CLI berjalan tanpa sesi (mis. test/one-shot) tidak ada field
    tambahan yang mengganggu provider non-OpenRouter.
    """
    sid = _build_openrouter_session_id(session_id)
    if sid:
        payload["session_id"] = sid
    return payload


def _build_openrouter_cache_marker(ttl: str = None) -> dict:
    """Bangun dict marker "cache_control" ala Anthropic/OpenRouter.

    `ttl` opsional ("5m" atau "1h") -- kalau tidak diisi, field "ttl" tidak
    disertakan sama sekali dan provider memakai TTL default mereka (~5
    menit sesuai dokumentasi OpenRouter). Parameter ini sengaja ada supaya
    caller di masa depan bisa memilih TTL lebih panjang untuk sesi yang
    sering jeda lama, tanpa perlu mengubah signature fungsi lain.
    """
    marker = {"type": "ephemeral"}
    if ttl:
        marker["ttl"] = ttl
    return marker


def _apply_cache_marker_to_message(msg: dict, marker: dict) -> None:
    """Tempel `marker` sebagai breakpoint ke SATU pesan, IN PLACE.

    Caller WAJIB sudah memberi `msg` yang aman diubah (mis. hasil
    copy.deepcopy) -- fungsi ini sengaja memutasi supaya tidak perlu
    membangun dict/list baru berulang di pemanggil.

    Tiga kasus bentuk `content` yang ditangani:
    - String non-kosong: dibungkus jadi array-of-parts SATU blok dengan
      cache_control di blok itu. Sengaja satu blok saja supaya otomatis
      jadi "blok terakhir" pesan tsb -- aturan OpenRouter/Anthropic
      mewajibkan cache_control cuma di blok terakhir tiap pesan (menaruh
      di semua blok pesan multi-blok bisa melebihi batas 4 breakpoint per
      request dan merusak inferensi, lihat riset caching sebelumnya).
    - List (sudah array-of-parts, mis. pesan vision/multipart): marker
      ditempel ke BLOK TERAKHIR SAJA (bukan seluruh blok), dengan alasan
      sama seperti di atas. Kalau blok terakhir bukan dict (bentuk yang
      tidak terduga), dilewati -- lebih aman diam daripada crash/merusak
      struktur yang tidak dikenal.
    - String kosong / None / tipe lain yang tidak dikenal: dilewati begitu
      saja. Tidak ada yang berharga untuk di-cache, dan memaksa bentuk
      pada isi yang tidak terduga lebih berisiko daripada tidak berbuat
      apa-apa untuk pesan itu.
    """
    content = msg.get("content")
    if isinstance(content, str) and content:
        msg["content"] = [{"type": "text", "text": content, "cache_control": marker}]
    elif isinstance(content, list) and content:
        last_block = content[-1]
        if isinstance(last_block, dict):
            last_block["cache_control"] = marker


def _apply_openrouter_cache_control(messages: list, cache_ttl: str = None) -> list:
    """Terapkan strategi "system_and_3" (lihat komentar
    OPENROUTER_CACHE_TAIL_BREAKPOINTS di atas): breakpoint di system prompt
    (kalau ada) + di sampai 3 pesan NON-system terakhir, memakai penuh
    jatah OPENROUTER_MAX_CACHE_BREAKPOINTS (4) yang diizinkan provider
    Anthropic-compatible.

    Robust terhadap kasus tepi:
    - `messages` kosong -> dikembalikan apa adanya.
    - Kurang dari 3 pesan non-system -> breakpoint dipasang ke yang ada
      saja (tidak error, tidak memaksa index di luar jangkauan).
    - Tidak ada pesan role="system" sama sekali -> seluruh 4 breakpoint
      dipakai untuk pesan non-system terakhir.
    - Pesan dengan `content` None/kosong/tipe tak terduga -> dilewati oleh
      _apply_cache_marker_to_message(), tidak membuat fungsi ini gagal.

    TIDAK memutasi `messages` asli sama sekali -- deep-copy dulu (`copy.
    deepcopy`) sebelum memutasi apa pun, mengikuti pola Hermes Agent, jadi
    aman walau caller masih memegang referensi ke `messages` yang sama
    setelah pemanggilan ini (mis. untuk logging/debug).
    """
    if not messages:
        return messages

    out = copy.deepcopy(messages)
    marker = _build_openrouter_cache_marker(cache_ttl)
    breakpoints_used = 0

    if out[0].get("role") == "system":
        _apply_cache_marker_to_message(out[0], marker)
        breakpoints_used += 1

    remaining = state.OPENROUTER_MAX_CACHE_BREAKPOINTS - breakpoints_used
    if remaining > 0:
        non_system_idx = [i for i, m in enumerate(out) if m.get("role") != "system"]
        tail_count = min(remaining, state.OPENROUTER_CACHE_TAIL_BREAKPOINTS)
        for idx in non_system_idx[-tail_count:]:
            _apply_cache_marker_to_message(out[idx], marker)

    return out
