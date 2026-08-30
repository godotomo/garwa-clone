"""Konfigurasi remote research tools Garwa.

GitHub:
- github_search_repos: token opsional (tanpa token rate limit publik lebih ketat).
- github_read_file: token opsional untuk repository publik.
- github_search_code: token diperlukan.

Cara aman (direkomendasikan):
    export GITHUB_TOKEN="github_pat_..."
Lalu jalankan garwa.

Alternatif:
- Isi GITHUB_TOKEN di file ini.
- Jangan commit file ini ke repository jika berisi token.
"""

import os

# Path file konfigurasi pengguna (URL/API key/model yang dipersistenkan lintas
# sesi lewat command slash /api-url, /api-key, dan /api-model).
USER_CONFIG_PATH = os.path.expanduser("~/.config/garwa/config")


def load_user_config() -> dict:
    """Baca file konfigurasi pengguna (~/.config/garwa/config).

    Format: satu `key=value` per baris, baris '#' dan kosong diabaikan.
    Mengembalikan dict; file tidak ada / tidak bisa dibaca -> dict kosong.
    """
    cfg: dict = {}
    try:
        with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    except (FileNotFoundError, OSError):
        pass
    return cfg


# Kunci-kunci yang dipersistenkan ke file konfigurasi pengguna, urutan tulis.
_USER_CONFIG_KEYS = (
    "url",
    "api_key",
    "model",
    "github_token",
    "github_max",
    "news_lang",
    "firecrawl_token",
    "context_window",
    "reserve_for_response",
    "summarize_threshold_ratio",
    "keep_tail_messages",
)


def save_user_config(
    url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    github_token: str | None = None,
    github_max: int | None = None,
    news_lang: str | None = None,
    firecrawl_token: str | None = None,
    context_window: int | None = None,
    reserve_for_response: int | None = None,
    summarize_threshold_ratio: float | None = None,
    keep_tail_messages: int | None = None,
) -> None:
    """Tulis nilai konfigurasi ke file konfigurasi pengguna.

    Nilai yang None dibiarkan apa adanya (tidak dihapus dari file).
    Kegagalan I/O ditelan diam-diam supaya CLI tetap berjalan.
    """
    cfg = load_user_config()
    if url is not None:
        cfg["url"] = url
    if api_key is not None:
        cfg["api_key"] = api_key
    if model is not None:
        cfg["model"] = model
    if github_token is not None:
        cfg["github_token"] = github_token
    if github_max is not None:
        cfg["github_max"] = str(int(github_max))
    if news_lang is not None:
        cfg["news_lang"] = news_lang
    if firecrawl_token is not None:
        cfg["firecrawl_token"] = firecrawl_token
    if context_window is not None:
        cfg["context_window"] = str(int(context_window))
    if reserve_for_response is not None:
        cfg["reserve_for_response"] = str(int(reserve_for_response))
    if summarize_threshold_ratio is not None:
        cfg["summarize_threshold_ratio"] = str(float(summarize_threshold_ratio))
    if keep_tail_messages is not None:
        cfg["keep_tail_messages"] = str(int(keep_tail_messages))
    try:
        os.makedirs(os.path.dirname(USER_CONFIG_PATH), exist_ok=True)
        with open(USER_CONFIG_PATH, "w", encoding="utf-8") as f:
            for k in _USER_CONFIG_KEYS:
                if k in cfg:
                    f.write(f"{k}={cfg[k]}\n")
    except OSError:
        pass


def remove_user_config_key(key: str) -> bool:
    """Hapus satu kunci dari file konfigurasi pengguna.

    Mengembalikan True jika kunci ada dan berhasil dihapus, False jika kunci
    tidak ditemukan. Kegagalan I/O ditelan diam-diam (mengembalikan False).
    """
    cfg = load_user_config()
    if key not in cfg:
        return False
    cfg.pop(key, None)
    try:
        os.makedirs(os.path.dirname(USER_CONFIG_PATH), exist_ok=True)
        with open(USER_CONFIG_PATH, "w", encoding="utf-8") as f:
            for k in _USER_CONFIG_KEYS:
                if k in cfg:
                    f.write(f"{k}={cfg[k]}\n")
    except OSError:
        return False
    return True


# Peta bahasa berita (nilai /news-lang) -> (hl, gl, ceid) untuk Google News.
# Kunci "id"/"en" didukung; nilai lain jatuh ke default "id".
_NEWS_LANG_MAP = {
    "id": ("id", "ID", "ID:id"),
    "en": ("en", "US", "US:en"),
    "ms": ("ms", "MY", "MY:ms"),
    "ar": ("ar", "SA", "SA:ar"),
    "zh": ("zh-Hans", "CN", "CN:zh-Hans"),
    "ja": ("ja", "JP", "JP:ja"),
    "ko": ("ko", "KR", "KR:ko"),
    "de": ("de", "DE", "DE:de"),
    "fr": ("fr", "FR", "FR:fr"),
    "es": ("es", "ES", "ES:es"),
    "pt": ("pt-BR", "BR", "BR:pt-BR"),
    "hi": ("hi", "IN", "IN:hi"),
    "nl": ("nl", "NL", "NL:nl"),
    "it": ("it", "IT", "IT:it"),
    "ru": ("ru", "RU", "RU:ru"),
}


def news_lang_to_params(lang: str) -> tuple[str, str, str]:
    """Terjemahkan nilai bahasa berita (/news-lang) ke (hl, gl, ceid)."""
    return _NEWS_LANG_MAP.get((lang or "").strip().lower(), _NEWS_LANG_MAP["id"])


_USER_CFG = load_user_config()

_DEFAULT_URL = "https://coder.garwa.id/v1/chat/completions"
_DEFAULT_MODEL = "deepseek-v4-flash-0731"

# Default context-window & summarization tuning (bisa diubah user via
# slash-command /ctx, /reserve, /summarize-threshold, /keep-tail dan
# dipersistenkan ke ~/.config/garwa/config). Nilai awal menyamai konstanta
# module-level lama di context_manager.py / _state.py.
DEFAULT_CONTEXT_WINDOW = 131072
DEFAULT_RESERVE_FOR_RESPONSE = 2048
DEFAULT_SUMMARIZE_THRESHOLD_RATIO = 0.2
DEFAULT_KEEP_TAIL_MESSAGES = 8


def _reload_values() -> None:
    """Hitung ulang semua nilai module-level dari env + file config pengguna.

    Dipanggil saat import dan bisa dipanggil ulang (mis. oleh test) setelah
    env / file config berubah. Prioritas tiap nilai: env > config > default.
    """
    global _USER_CFG, GITHUB_TOKEN
    global GOOGLE_NEWS_HL, GOOGLE_NEWS_GL, GOOGLE_NEWS_CEID
    global GITHUB_MAX_CONTENT, LLAMA_URL, LLAMA_API_KEY, LLAMA_MODEL
    global FIRECRAWL_API_KEY, FIRECRAWL_API_URL
    global CONTEXT_WINDOW, RESERVE_FOR_RESPONSE
    global SUMMARIZE_THRESHOLD_RATIO, KEEP_TAIL_MESSAGES

    _USER_CFG = load_user_config()

    # Prioritas nilai: env (GITHUB_TOKEN) > file konfigurasi pengguna > default.
    GITHUB_TOKEN = (os.environ.get("GITHUB_TOKEN") or _USER_CFG.get("github_token") or "").strip()

    # Bahasa berita: komponen env (GOOGLE_NEWS_HL/GL/CEID) menang; kalau tidak ada,
    # turunkan dari nilai `news_lang` di config pengguna; terakhir default "id".
    _news_hl, _news_gl, _news_ceid = news_lang_to_params(_USER_CFG.get("news_lang", "id"))
    GOOGLE_NEWS_HL = os.environ.get("GOOGLE_NEWS_HL") or _news_hl
    GOOGLE_NEWS_GL = os.environ.get("GOOGLE_NEWS_GL") or _news_gl
    GOOGLE_NEWS_CEID = os.environ.get("GOOGLE_NEWS_CEID") or _news_ceid

    # Nilai non-numerik (mis. config pengguna diedit manual) tidak boleh
    # membuat import config crash; jatuh ke default 12000.
    _github_max_raw = os.environ.get("GITHUB_MAX_CONTENT") or _USER_CFG.get("github_max") or "12000"
    try:
        GITHUB_MAX_CONTENT = int(_github_max_raw)
    except (TypeError, ValueError):
        GITHUB_MAX_CONTENT = 12000
    if GITHUB_MAX_CONTENT <= 0:
        GITHUB_MAX_CONTENT = 12000

    # Prioritas nilai: env (LLAMA_URL / LLAMA_API_KEY) > file konfigurasi pengguna
    # (~/.config/garwa/config) > default bawaan.
    LLAMA_URL = (os.environ.get("LLAMA_URL") or _USER_CFG.get("url") or _DEFAULT_URL).strip()
    LLAMA_API_KEY = (os.environ.get("LLAMA_API_KEY") or _USER_CFG.get("api_key") or "").strip()
    # Model: prioritas env (LLAMA_MODEL) > config pengguna (disimpan via /api-model)
    # > default bawaan CLI.
    LLAMA_MODEL = (os.environ.get("LLAMA_MODEL") or _USER_CFG.get("model") or _DEFAULT_MODEL).strip()

    # Firecrawl: prioritas env > config pengguna > default API endpoint.
    FIRECRAWL_API_KEY = (
        os.environ.get("FIRECRAWL_API_KEY") or _USER_CFG.get("firecrawl_token") or ""
    ).strip()
    FIRECRAWL_API_URL = (
        os.environ.get("FIRECRAWL_API_URL") or "https://api.firecrawl.dev/v1"
    ).rstrip("/")

    # Context-window & summarization tuning. Nilai non-numerik / tidak valid
    # (mis. config pengguna diedit manual) tidak boleh membuat import crash;
    # jatuh ke default masing-masing. Prioritas: env > config > default.
    CONTEXT_WINDOW = _read_int_env_or_cfg(
        "GARWA_CONTEXT_WINDOW", _USER_CFG.get("context_window"), DEFAULT_CONTEXT_WINDOW
    )
    RESERVE_FOR_RESPONSE = _read_int_env_or_cfg(
        "GARWA_RESERVE_FOR_RESPONSE", _USER_CFG.get("reserve_for_response"),
        DEFAULT_RESERVE_FOR_RESPONSE,
    )
    SUMMARIZE_THRESHOLD_RATIO = _read_float_env_or_cfg(
        "GARWA_SUMMARIZE_THRESHOLD_RATIO", _USER_CFG.get("summarize_threshold_ratio"),
        DEFAULT_SUMMARIZE_THRESHOLD_RATIO,
    )
    KEEP_TAIL_MESSAGES = _read_int_env_or_cfg(
        "GARWA_KEEP_TAIL_MESSAGES", _USER_CFG.get("keep_tail_messages"),
        DEFAULT_KEEP_TAIL_MESSAGES,
    )


def _read_int_env_or_cfg(env_name: str, cfg_value, default: int) -> int:
    """Baca integer dari env > config > default; nilai invalid jatuh ke default."""
    raw = os.environ.get(env_name) or cfg_value
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return default
    return value


def _read_float_env_or_cfg(env_name: str, cfg_value, default: float) -> float:
    """Baca float dari env > config > default; nilai invalid jatuh ke default."""
    raw = os.environ.get(env_name) or cfg_value
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value <= 0 or value > 1:
        return default
    return value


_reload_values()