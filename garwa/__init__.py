"""
garwa package
Coding-agent CLI (mirip coding-agent CLI pada umumnya) yang bicara ke
llama-server lewat API ala OpenAI.

Struktur paket (hasil refactor dari 9 file tunggal menjadi package per
tanggung jawab -- lihat README_REFACTOR.md di root repo untuk detail):

    config.py            konfigurasi dari environment variable
    db.py                lapisan persistensi SQLite
    token_utils.py        estimasi jumlah token
    context_manager.py     manajemen context window (summarize + tail)
    repo_map.py             peta struktur repo (ala Aider repo-map)
    security/               orkestrasi security scanner lokal
    tool_runtime/            infrastruktur runtime tool (registry, hooks, dsb)
    tools/                   definisi & implementasi tool (schema + handler)
    cli/                     antarmuka command-line interaktif (entry point)

Jalankan lewat:  python -m garwa
"""

__version__ = "0.2.0"
