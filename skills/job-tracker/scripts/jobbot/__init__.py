"""jobbot - Freelance job scraper & reporter for Garwa.

Sistem scraping+lapor lowongan freelance platform luar (bayar USD)
terintegrasi ke Garwa. Target minimal $50/hari.

Arsitektur (Garwa = runner utama):
  - db.py        : schema SQLite skill (jobs, applications, progress) — TERPISAH dari DB runtime Garwa
  - models.py    : Job + operasi CRUD
  - scraper.py   : core multi-platform scraper
  - reporter.py  : Telegram channel reporter (via Garwa bridge)
  - proposal_email.py : kirim proposal email (via Garwa bridge)
  - auto_reply.py : auto-reply email cerdas (deteksi intent + balas kontekstual)
  - llm_filter.py : filter relevansi job via LLM (retry + backoff)
  - workflow.py  : contract lifecycle (create/deliver/revise/complete)
  - executor.py  : mesin produksi deliverable nyata (4 role)
  - autopilot.py : pipeline autonomous end-to-end (tanpa interaksi)
  - proposal.py  : generator proposal + role detection
  - cron.py      : cron scheduler harian (scraping berkala)
  - github_client.py : publish deliverable ke GitHub
  - _garwa_bridge.py : jembatan ke fitur runtime Garwa (email/IMAP/Telegram/Google)
  - cli.py       : entrypoint CLI

Fitur yang sudah ada di Garwa (email, IMAP, Telegram, cron scheduling, Google
Workspace) TIDAK diduplikasi di sini — dipanggil lewat `_garwa_bridge.py` yang
membungkus `garwa.tools.comm_tools` dan skill `google-workspace`.
"""

__version__ = "0.1.0"
