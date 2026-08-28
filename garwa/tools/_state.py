"""
tools/_state.py
Konstanta & variabel state module-level milik paket `tools` (hasil pecahan tools.py).

PENTING: modul ini adalah SATU-SATUNYA sumber kebenaran untuk state
yang bisa di-mutate dari luar paket (mis. cli.py melakukan
`tools_module.state.WORKDIR = args.workdir`). Semua submodule tools/*
mengakses nilai ini lewat `state.NAMA` (bukan `from ._state import NAMA`)
supaya perubahan dari luar langsung terlihat di semua tempat -- persis
seperti perilaku variabel module-level di tools.py sebelum dipecah.
"""
import os
import re
import threading
from datetime import timezone, timedelta

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


WORKDIR = os.environ.get("GARWA_WORKDIR", os.getcwd())
SANDBOX_ENABLED = True
DB_PATH = os.environ.get("GARWA_DB_PATH", dbmod.DEFAULT_DB_PATH)
SESSION_ID = os.environ.get("GARWA_SESSION_ID")
_RECENTLY_TOUCHED = []
_MAX_RECENT = 20
_RECENTLY_TOUCHED_LOCK = threading.Lock()
SKILLS_DIR = None
ALLOWED_EXTERNAL_PATHS = set()
_WIB = timezone(timedelta(hours=7), name="WIB")
_HARI_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
GOOGLE_NEWS_HL = getattr(config_mod, "GOOGLE_NEWS_HL", "id")
GOOGLE_NEWS_GL = getattr(config_mod, "GOOGLE_NEWS_GL", "ID")
GOOGLE_NEWS_CEID = getattr(config_mod, "GOOGLE_NEWS_CEID", "ID:id")
GITHUB_TOKEN = getattr(config_mod, "GITHUB_TOKEN", None)
GITHUB_API = "https://api.github.com"
FIRECRAWL_API_KEY = getattr(config_mod, "FIRECRAWL_API_KEY", None)
FIRECRAWL_API_URL = getattr(config_mod, "FIRECRAWL_API_URL", "https://api.firecrawl.dev/v1")
_REMOTE_TIMEOUT = (10, 20)
_WEB_MAX_SNIPPET = 400
_GITHUB_MAX_CONTENT = getattr(config_mod, "GITHUB_MAX_CONTENT", 12000)
_WEBFETCH_MAX_BYTES = 5 * 1024 * 1024   # 5 MB, sama dengan opencode
_WEBFETCH_DEFAULT_TIMEOUT = 30
_WEBFETCH_MAX_TIMEOUT = 120
_WEBFETCH_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)
OUTPUT_CAP_BYTES = 50 * 1024   # 50 KB, sesuai permintaan
_OUTPUT_HEAD_KEEP = 15 * 1024  # simpan awal (perintah/log pembuka)
_OUTPUT_TAIL_KEEP = 30 * 1024  # simpan akhir -- error/exit summary/traceback
_DANGEROUS_BASH_PATTERNS = [
    # rm dengan flag rekursif+force. Gunakan lookahead supaya menangkap semua
    # bentuk: tergabung (-rf/-fr/-Rf), terpisah (-r -f), long-form
    # (--recursive --force), maupun campuran (-r --force). Kedua lookahead
    # hanya memindai token flag (diawali '-'), bukan argumen path.
    r"\brm\s+(?=(?:-\S+\s*)*-\S*[rR]\S*)(?=(?:-\S+\s*)*-\S*[fF]\S*)",
    r"\bdd\s+.*\bof=/dev/",                           # dd ke block device
    r"\bmkfs(\.\w+)?\b",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",      # fork bomb klasik
    r"\bchmod\s+(-\S+\s+)*-?[Rr]\S*\s+.*(/\s|/$|/\*|~\s|~$)",  # chmod -R / atau ~
    r"\bchown\s+(-\S+\s+)*-?[Rr]\S*\s+.*(/\s|/$|/\*)",
    r"(curl|wget)\s+.*\|\s*(sh|bash|zsh|sudo\s+sh)\b",  # pipe skrip remote ke shell
    r"\bsudo\b",
    r"\b(shutdown|reboot|poweroff|halt)\b",
    r"\bkill\s+-9\s+1\b",
    r"\bkillall\b",
    r">\s*/dev/sd[a-z]\d*\b",
    r"\bgit\s+push\s+.*(--force|-f)\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+(?:-\S+\s+)*(?:-[a-zA-Z]*[fF][a-zA-Z]*|--force)\b",
    r"\bfind\s+.*-delete\b",
    r"\bfind\s+.*-exec\s+rm\b",
    r"\btruncate\s+-s\s*0\b",
    r"\bshutil\.rmtree\b",
    r"\bos\.remove\b|\bos\.rmdir\b",
]
_DANGEROUS_BASH_RE = re.compile("|".join(_DANGEROUS_BASH_PATTERNS), re.IGNORECASE)
