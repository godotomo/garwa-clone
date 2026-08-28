"""
tools package
Definisi tool (schema + implementasi nyata) untuk Garwa -- dipecah dari
tools.py (file tunggal ~1700 baris) menjadi beberapa modul kecil per
kategori tool. Paket ini tetap diimpor sebagai `tools` (lihat
`garwa/tools/__init__.py`) sehingga `from tools import TOOLS` dan
`import tools as tools_module` di cli.py tetap bekerja tanpa berubah.

State bersama (WORKDIR, SESSION_ID, dkk) ada di `tools/_state.py` dan
diekspos sebagai `tools.state` (mis. `tools_module.state.WORKDIR = ...`).
"""
from . import _state as state

from .sandbox import _touch, SandboxViolation, _resolve, _resolve_readonly
from .datetime_utils import _now_wib, tool_local_now
from .web_search import _query_needs_current_date, _prepare_news_query, _remote_get, _html_to_text, _decode_google_news_url, _search_google_news_rss, tool_web_search
from .github import _github_headers, _github_repo_valid, tool_github_search_repos, tool_github_search_code, tool_github_read_file
from .firecrawl import tool_firecrawl_scrape, tool_firecrawl_search, tool_firecrawl_crawl
from .filesystem import tool_glob, _coerce_optional_int, tool_read_file, _atomic_write, tool_write_file, tool_edit_file, tool_list_dir, tool_grep
from .webfetch import _webfetch_accept_header, _webfetch_mime_from, _webfetch_is_textual_mime, _webfetch_html_to_text, _webfetch_html_to_markdown, tool_webfetch
from .security_tool import tool_security_scan
from .bash_tool import _cap_output, _bash_is_risky, _restore_terminal_mode, tool_bash
from .repo_tools import tool_repo_map, tool_outline_file
from .session_tools import _require_session, tool_todo_write, tool_todo_read, tool_remember, tool_recall


# ---------------------------------------------------------------------------
# Registry tool: nama -> {schema, handler, destructive}
# ---------------------------------------------------------------------------
#
# CATATAN MIGRASI SKEMA:
#   - `inputSchema` adalah format kanonik: JSON-Schema penuh (draft-07 subset)
#     berbentuk {"type":"object","properties":{...},"required":[...]} -- format
#     yang sama dipakai MCP dan OpenAI function-calling. Ini sumber kebenaran.
#   - `arguments` (string deskriptif legacy) TIDAK lagi disimpan di sini.
#     Konsumen lama yang membutuhkannya mendapat derivasi otomatis via
#     tool_runtime._schema_to_legacy().

TOOLS = {
    "bash": {
        "handler": tool_bash,
        # Dinamis: execute_tool() di cli.py memanggil _bash_is_risky(arguments)
        # dengan argumen tool ini untuk memutuskan perlu konfirmasi atau tidak,
        # alih-alih selalu True. Lihat catatan di _DANGEROUS_BASH_RE.
        "destructive": _bash_is_risky,
        "schema": {
            "name": "bash",
            "description": "Jalankan perintah shell di working directory. Gunakan untuk menjalankan program, install paket, git, dsb. Command yang cocok pola berbahaya (rm -rf, dd ke device, force-push, dll) tetap meminta konfirmasi user walau auto-approve aktif untuk tool lain.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "perintah shell yang akan dijalankan"},
                    "timeout": {"type": "integer", "default": 60, "description": "batas waktu detik"},
                },
                "required": ["command"],
            },
        },
    },
    "read_file": {
        "handler": tool_read_file,
        "destructive": False,
        "schema": {
            "name": "read_file",
            "description": "Baca isi file teks, dengan nomor baris.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "path file, relatif atau absolut"},
                    "start_line": {"type": "integer", "description": "baris awal"},
                    "end_line": {"type": "integer", "description": "baris akhir"},
                },
                "required": ["path"],
            },
        },
    },
    "write_file": {
        "handler": tool_write_file,
        "destructive": True,
        "schema": {
            "name": "write_file",
            "description": "Buat file baru atau timpa seluruh isi file yang sudah ada.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "path file tujuan"},
                    "content": {"type": "string", "description": "seluruh isi file"},
                },
                "required": ["path", "content"],
            },
        },
    },
    "edit_file": {
        "handler": tool_edit_file,
        "destructive": True,
        "schema": {
            "name": "edit_file",
            "description": "Cari string unik (old_str) di dalam file lalu ganti dengan new_str. old_str HARUS unik dan cocok persis (termasuk whitespace/indentasi). Gunakan ini untuk edit presisi, bukan write_file, agar tidak menghapus bagian lain file.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "path file"},
                    "old_str": {"type": "string", "description": "teks persis yang dicari, harus unik dalam file"},
                    "new_str": {"type": "string", "description": "teks pengganti"},
                },
                "required": ["path", "old_str", "new_str"],
            },
        },
    },
    "list_dir": {
        "handler": tool_list_dir,
        "destructive": False,
        "schema": {
            "name": "list_dir",
            "description": "Tampilkan daftar file dan folder di suatu direktori.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "default": ".", "description": "path direktori"},
                },
                "required": [],
            },
        },
    },
    "grep": {
        "handler": tool_grep,
        "destructive": False,
        "schema": {
            "name": "grep",
            "description": "Cari pola teks/regex di dalam file-file pada suatu direktori (rekursif).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "pola pencarian"},
                    "path": {"type": "string", "default": ".", "description": "direktori target"},
                    "glob": {"type": "string", "default": "*", "description": "filter nama file, mis. '*.py'"},
                },
                "required": ["pattern"],
            },
        },
    },
    "repo_map": {
        "handler": tool_repo_map,
        "destructive": False,
        "schema": {
            "name": "repo_map",
            "description": "Tampilkan peta struktur seluruh repo (file + simbol paling relevan, hasil ranking PageRank) supaya cepat memahami proyek tanpa membaca semua file satu-satu. File yang baru dibaca/diedit di sesi ini diberi bobot lebih.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "token_budget": {"type": "integer", "default": 1024, "description": "perkiraan batas token output"},
                },
                "required": [],
            },
        },
    },
    "outline_file": {
        "handler": tool_outline_file,
        "destructive": False,
        "schema": {
            "name": "outline_file",
            "description": "Tampilkan daftar simbol top-level (fungsi/class/dll beserta nomor baris) dari satu file, tanpa isi lengkapnya. Cocok untuk file besar sebelum memutuskan bagian mana yang perlu dibaca detail lewat read_file.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "path file"},
                },
                "required": ["path"],
            },
        },
    },
    "todo_write": {
        "handler": tool_todo_write,
        "destructive": False,
        "schema": {
            "name": "todo_write",
            "description": "Simpan/timpa plan (daftar todo) untuk sesi saat ini, mirip TodoWrite. Kirim seluruh daftar setiap kali (full replace), tiap item berupa objek {content, status}. status salah satu dari: pending, in_progress, done, cancelled.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "description": "list objek {content, status}",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string", "description": "isi item todo"},
                                "status": {
                                    "type": "string",
                                    "description": "status item",
                                    "enum": ["pending", "in_progress", "done", "cancelled"],
                                },
                            },
                            "required": ["content", "status"],
                        },
                    },
                },
                "required": ["todos"],
            },
        },
    },
    "todo_read": {
        "handler": tool_todo_read,
        "destructive": False,
        "schema": {
            "name": "todo_read",
            "description": "Baca plan/todo list sesi saat ini yang tersimpan.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    "remember": {
        "handler": tool_remember,
        "destructive": False,
        "schema": {
            "name": "remember",
            "description": "Simpan catatan proyek key-value yang persisten lintas sesi untuk workdir ini (mis. konvensi kode, keputusan arsitektur).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "nama singkat catatan"},
                    "value": {"type": "string", "description": "isi catatan"},
                },
                "required": ["key", "value"],
            },
        },
    },
    "recall": {
        "handler": tool_recall,
        "destructive": False,
        "schema": {
            "name": "recall",
            "description": "Baca catatan proyek yang tersimpan untuk workdir ini. Kosongkan 'key' untuk melihat semua catatan.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "nama catatan spesifik yang ingin dibaca"},
                },
                "required": [],
            },
        },
    },
    "security_scan": {
        "handler": tool_security_scan,
        "destructive": False,
        "schema": {
            "name": "security_scan",
            "description": (
                "Audit keamanan LOKAL untuk membuat kode lebih siap produksi. "
                "Gunakan HANYA jika user meminta security audit, dependency audit, "
                "secret scan, supply-chain audit, IaC audit, DAST, atau production-readiness "
                "security check. Mode all menjalankan SAST+dependency+secrets+IaC. "
                "python menambahkan pip-audit; deep menambahkan pip-audit+dep-scan. "
                "Scanner yang tidak terpasang dilaporkan INCOMPLETE, bukan dianggap aman. "
                "Hasil dinormalisasi dan secret diredaKsi sebelum masuk context model."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scan_type": {
                        "type": "string",
                        "default": "all",
                        "description": "mode audit keamanan",
                        "enum": ["all", "sast", "dependencies", "python", "deep", "secrets", "iac", "dast", "compliance"],
                    },
                    "timeout": {"type": "integer", "default": 300, "description": "timeout per scanner dalam detik"},
                    "dast_target": {"type": "string", "description": "URL target DAST yang eksplisit; wajib untuk mode dast"},
                    "allow_nonlocal_dast": {
                        "type": "boolean",
                        "default": False,
                        "description": "izinkan target DAST non-local hanya jika pengguna benar-benar memberi otorisasi",
                    },
                },
                "required": [],
            },
        },
    },
    "local_now": {
        "handler": tool_local_now,
        "destructive": False,
        "schema": {
            "name": "local_now",
            "description": (
                "Dapatkan tanggal dan jam saat ini dari clock mesin dalam WIB "
                "(UTC+7). WAJIB digunakan sebelum web_search untuk query "
                "relatif seperti hari ini, terbaru, saat ini, kemarin, atau "
                "minggu ini; juga gunakan untuk kebutuhan timestamp lainnya."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    "web_search": {
        "handler": tool_web_search,
        "destructive": False,
        "schema": {
            "name": "web_search",
            "description": (
                "Cari berita/informasi terkini melalui Google News RSS. Bukan general web search. "
                "Gunakan param 'lang' untuk mengontrol bahasa: 'id' (Indonesia), 'en' (Inggris), "
                "atau 'auto' (default) yang mencoba Indonesia lalu fallback ke Inggris."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "topik/kata kunci pencarian"},
                    "max_results": {
                        "type": "integer",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 10,
                        "description": "jumlah hasil maksimum",
                    },
                    "lang": {"type": "string", "default": "auto", "description": "bahasa hasil: 'id', 'en', atau 'auto'"},
                },
                "required": ["query"],
            },
        },
    },
    "github_search_repos": {
        "handler": tool_github_search_repos,
        "destructive": False,
        "schema": {
            "name": "github_search_repos",
            "description": "Cari repository publik GitHub berdasarkan nama, deskripsi, topic, language, stars, dan qualifier GitHub.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "query GitHub"},
                    "max_results": {
                        "type": "integer",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 10,
                        "description": "jumlah hasil maksimum",
                    },
                },
                "required": ["query"],
            },
        },
    },
    "github_search_code": {
        "handler": tool_github_search_code,
        "destructive": False,
        "schema": {
            "name": "github_search_code",
            "description": "Cari potongan kode di GitHub. Membutuhkan GITHUB_TOKEN.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "query code search, mis. 'def foo language:python repo:owner/name'"},
                    "max_results": {
                        "type": "integer",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 10,
                        "description": "jumlah hasil maksimum",
                    },
                },
                "required": ["query"],
            },
        },
    },
    "github_read_file": {
        "handler": tool_github_read_file,
        "destructive": False,
        "schema": {
            "name": "github_read_file",
            "description": "Baca isi satu file source code/dokumentasi dari repository GitHub publik.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "format owner/name"},
                    "path": {"type": "string", "description": "path file relatif terhadap root repo"},
                    "ref": {"type": "string", "description": "branch, tag, atau commit SHA"},
                },
                "required": ["repo", "path"],
            },
        },
    },
    "firecrawl_scrape": {
        "handler": tool_firecrawl_scrape,
        "destructive": False,
        "schema": {
            "name": "firecrawl_scrape",
            "description": "Ambil konten satu halaman web menjadi teks markdown via Firecrawl. Butuh FIRECRAWL_API_KEY (set via /firecrawl-key atau env FIRECRAWL_API_KEY).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL halaman web yang akan di-scrape"},
                    "formats": {"type": "string", "description": "format output, koma-terpisah. Opsi: markdown, html, rawHtml, links, screenshot. Default 'markdown'."},
                },
                "required": ["url"],
            },
        },
    },
    "firecrawl_search": {
        "handler": tool_firecrawl_search,
        "destructive": False,
        "schema": {
            "name": "firecrawl_search",
            "description": "Cari di web via Firecrawl dan tampilkan judul+URL hasil teratas. Butuh FIRECRAWL_API_KEY.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "kata kunci pencarian web"},
                    "limit": {"type": "integer", "description": "jumlah hasil maksimum (1-10), default 5"},
                },
                "required": ["query"],
            },
        },
    },
    "firecrawl_crawl": {
        "handler": tool_firecrawl_crawl,
        "destructive": False,
        "schema": {
            "name": "firecrawl_crawl",
            "description": "Crawl satu situs web via Firecrawl, polling status job sampai selesai. Butuh FIRECRAWL_API_KEY.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL root situs yang akan di-crawl"},
                    "limit": {"type": "integer", "description": "jumlah halaman maksimum (1-100), default 10"},
                    "max_depth": {"type": "integer", "description": "kedalaman crawl maksimum (1-10), default 3"},
                },
                "required": ["url"],
            },
        },
    },
    "glob": {
        "handler": tool_glob,
        "destructive": False,
        "schema": {
            "name": "glob",
            "description": "Cari file dengan glob pattern di dalam WORKDIR (atau subdirektori). Mengembalikan daftar path relatif terhadap WORKDIR, satu per baris. Gunakan path relatif untuk mempersempit pencarian dan limit untuk membatasi jumlah hasil.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "glob pattern untuk mencocokkan file, mis. '**/*.py'"},
                    "path": {"type": "string", "default": ".", "description": "direktori relatif untuk mencari"},
                    "limit": {"type": "integer", "description": "jumlah hasil maksimum"},
                },
                "required": ["pattern"],
            },
        },
    },
    "webfetch": {
        "handler": tool_webfetch,
        "destructive": False,
        "schema": {
            "name": "webfetch",
            "description": "Fetch konten dari URL HTTP/HTTPS dan kembalikan sebagai text, markdown, atau html. Markdown adalah default. Gunakan tool yang lebih spesifik bila tersedia. Tool ini read-only. Hasil teks besar dibatasi agar tidak membanjiri context window.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL HTTP/HTTPS untuk di-fetch"},
                    "format": {"type": "string", "default": "markdown", "description": "format hasil: text, markdown, atau html"},
                    "timeout": {"type": "integer", "default": 30, "maximum": 120, "description": "timeout dalam detik"},
                },
                "required": ["url"],
            },
        },
    },

}
