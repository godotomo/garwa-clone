"""jobbot - Freelance job scraper & reporter for Garwa.

Sistem scraping+lapor lowongan freelance platform luar (bayar USD)
terintegrasi ke Garwa. Target minimal $50/hari.

Komponen:
  - db.py        : schema SQLite (jobs, applications, progress)
  - models.py    : Job + operasi CRUD
  - scraper.py   : core multi-platform scraper
  - reporter.py  : Telegram channel reporter
  - email_report.py : laporan email via SMTP (kirim)
  - imap_inbox.py   : baca & balas email masuk via IMAP (Gmail pribadi)
  - auto_reply.py   : auto-reply email cerdas (deteksi intent + balas kontekstual)
  - google_auth.py  : autentikasi Google (Service Account + impersonation)
  - google_drive.py : integrasi Google Sheets/Drive/Docs
  - gmail.py        : kirim/balas email via Gmail API
  - telegram_bot.py : bot Telegram dua arah (terima file & perintah)
  - cron.py      : cron scheduler harian
  - cli.py       : entrypoint CLI
"""

__version__ = "0.1.0"
