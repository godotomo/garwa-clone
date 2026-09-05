# Jobbot — Freelance Job Scraper & Reporter

Sistem scraping + pelaporan lowongan freelance platform luar (bayar USD) terintegrasi ke Garwa. Target minimal **$10/hari** dari pekerjaan freelance (developer, designer, writer, web3).

## Fitur

- **Multi-platform scraper (10 platform)**: Remote OK, Remotive, Working Nomads, Jobicy, Arbeitnow, We Work Remotely, GitHub Jobs, Upwork, Freelancer, Indeed
- **5 platform keyless terverifikasi**: Remote OK, Remotive, Working Nomads, Jobicy, Arbeitnow (API publik tanpa auth)
- **Dedup otomatis**: `UNIQUE(platform, job_id)` mencegah duplikasi
- **Telegram reporter**: kirim lowongan baru ke channel Telegram
- **Email report**: laporan harian via SMTP (HTML table)
- **Google Sheets/Drive**: simpan laporan ke Google (OAuth)
- **Cron scheduler**: jadwalkan scraping harian
- **SQLite storage**: state & statistik persisten

## Quick Start

```bash
# 1. Inisialisasi DB
python -m jobbot.cli stats

# 2. Scrapa lowongan (5 platform keyless terverifikasi)
python -m jobbot.cli run --platforms "remote-ok,remotive,working-nomads,jobicy,arbeitnow" --limit 20

# 3. Lihat hasil
python -m jobbot.cli list
```

## Setup Telegram

```bash
export JOB_TELEGRAM_TOKEN="123456:ABC-DEF..."
export JOB_TELEGRAM_CHANNEL_ID="@mychannel"
python -m jobbot.cli run
```

## Setup Google (OAuth)

1. Google Cloud Console → enable Drive API + Sheets API + Docs API
2. Buat OAuth 2.0 Client ID (desktop app)
3. Download `credentials.json` → simpan di `jobbot/credentials.json`
4. Jalankan `python -m jobbot.cli setup-oauth`

Fungsi Google tersedia:
- `upload_file_to_drive(local_path, folder_id, filename)` — upload file report
- `append_google_sheet(sheet_id, range_name, rows)` — append baris job
- `create_google_sheet(title, headers, folder_id)` — buat sheet baru
- `create_google_doc(title, content, folder_id)` — buat dokumen laporan
- `create_drive_folder(name, parent_id)` — buat folder

## Setup Email (SMTP)

```bash
export JOB_EMAIL_USER="you@gmail.com"
export JOB_EMAIL_PASS="your-app-password"
export JOB_EMAIL_RECIPIENT="recipient@gmail.com"
```

## Cron Harian

```bash
# Tambah ke crontab (jalankan tiap jam 9 pagi)
0 9 * * * cd /data/data/com.termux/files/home/garwa-coder-v2 && python -m jobbot.cli run
```

## Struktur

```
jobbot/
  db.py            # schema SQLite
  models.py        # Job + CRUD
  scraper.py       # 10 platform scraper
  reporter.py      # Telegram
  email_report.py  # SMTP email
  google_drive.py  # Google Sheets/Drive
  cron.py          # scheduler
  cli.py           # CLI entrypoint
```

## Status Platform

| Platform | Endpoint | Terverifikasi |
|---|---|---|
| Remote OK | public JSON | ✅ |
| Remotive | public JSON | ✅ |
| Working Nomads | public JSON | ✅ |
| Jobicy | public JSON | ✅ |
| Arbeitnow | public JSON | ✅ |
| We Work Remotely | RSS | ⚠️ perlu test |
| GitHub Jobs | API (butuh token) | ⚠️ |
| Upwork/Freelancer/Indeed | scraping (anti-bot) | ⚠️ flaky |
