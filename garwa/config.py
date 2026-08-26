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

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()

GOOGLE_NEWS_HL = os.environ.get("GOOGLE_NEWS_HL", "id")
GOOGLE_NEWS_GL = os.environ.get("GOOGLE_NEWS_GL", "ID")
GOOGLE_NEWS_CEID = os.environ.get("GOOGLE_NEWS_CEID", "ID:id")

GITHUB_MAX_CONTENT = int(os.environ.get("GITHUB_MAX_CONTENT", "12000"))

LLAMA_URL = os.environ.get(
    "LLAMA_URL", "https://coder.garwa.id/v1/chat/completions"
).strip()

LLAMA_API_KEY = os.environ.get("LLAMA_API_KEY", "").strip()