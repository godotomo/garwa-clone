---
name: job-tracker
description: Scraping & pelaporan lowongan freelance platform luar (bayar USD) yang terintegrasi ke Garwa. Gunakan skill ini setiap kali user ingin mencari lowongan freelance (Upwork, Freelancer, Fiverr, GitHub Jobs, Remote OK, We Work Remotely, Remotive, Working Nomads, Jobicy, Arbeitnow, JobsCollider), melamar pekerjaan, membuat laporan harian lowongan, mengirim notifikasi ke Telegram channel, atau menyimpan laporan ke Google Sheets/Drive. Menyediakan CLI `jobbot` yang sudah terverifikasi berfungsi.
---

# Job Tracker

Skill ini membungkus sistem scraping lowongan freelance multi-platform yang **sudah terverifikasi berfungsi** (diuji dengan data asli dari Remote OK & Remotive). Target: minimal $10/hari dari pekerjaan freelance luar (developer, designer, writer, web3).

## Arsitektur

```
jobbot/
  db.py            # schema SQLite (jobs, applications, progress)
  models.py        # Job + operasi CRUD (dedup via UNIQUE(platform, job_id))
  scraper.py       # core multi-platform scraper (11 platform)
  reporter.py      # Telegram channel reporter
  email_report.py  # laporan email via SMTP
  google_auth.py   # autentikasi Google (Service Account + impersonation)
  google_drive.py  # integrasi Google Sheets/Drive/Docs
  gmail.py         # kirim/balas email via Gmail API
  telegram_bot.py  # bot Telegram dua arah (terima file & perintah)
  workflow.py      # contract lifecycle (create/deliver/revise/complete)
  executor.py      # mesin produksi deliverable nyata (4 role)
  autopilot.py     # pipeline autonomous end-to-end (tanpa interaksi)
  proposal.py      # generator proposal + role detection
  cron.py          # cron scheduler harian
  cli.py           # entrypoint CLI
```

## Platform Terverifikasi (tanpa auth)

| Platform | Endpoint | Status |
|---|---|---|
| Remote OK | `https://remoteok.com/api` (JSON) | ✅ Terverifikasi |
| Remotive | `https://remotive.com/api/remote-jobs` (JSON) | ✅ Terverifikasi |
| We Work Remotely | `https://weworkremotely.com/feeds/jobs.rss` (RSS) | ⚠️ Perlu test |
| GitHub Jobs | `https://api.github.com/search/jobs` (butuh GITHUB_TOKEN) | ⚠️ Perlu token |
| Upwork | scraping halaman search | ⚠️ Anti-bot, flaky |
| Freelancer | scraping halaman search | ⚠️ Anti-bot, flaky |
| Indeed | scraping halaman search | ⚠️ Anti-bot, flaky |
| Working Nomads | `https://www.workingnomads.com/api/exposed_jobs/` (JSON) | ✅ Terverifikasi |
| Jobicy | `https://jobicy.com/api/v2/remote-jobs` (JSON) | ✅ Terverifikasi |
| Arbeitnow | `https://www.arbeitnow.com/api/job-board-api` (JSON) | ✅ Terverifikasi |
| JobsCollider | `https://jobscollider.com/api/search-jobs` (JSON, salary tahunan, 16 kategori) | ✅ Terverifikasi |

## ⚠️ Jebakan Parsing (PENTING)

1. **Remote OK** mengembalikan item pertama sebagai **metadata (bukan job)** — selalu skip `data[1:]` dan filter `item.get("id")` & `item.get("position")` yang kosong.
2. **Upwork/Freelancer/Indeed** memakai anti-bot (Cloudflare) — scraping HTML sering gagal/tidak stabil. Jangan andalkan sebagai sumber utama; gunakan Remote OK + Remotive sebagai baseline.
3. **GitHub Jobs** (`api.github.com/search/jobs`) memerlukan `GITHUB_TOKEN` — tanpa token akan 401/403.

## CLI (jobbot)

```bash
# Scrapa + report sekali (semua platform)
python -m jobbot.cli run

# Scrapa platform tertentu
python -m jobbot.cli run --platforms "remote-ok,remotive" --limit 20

# Custom keyword
python -m jobbot.cli run --keywords "python developer,solidity developer"

# Tampilkan job di DB
python -m jobbot.cli list --limit 20

# Report manual ke Telegram
python -m jobbot.cli report

# Statistik progress
python -m jobbot.cli stats

# Export jobs ke CSV/Google Sheets
python -m jobbot.cli export --format sheet --title "Jobbot Jobs"

# Laporan harian lengkap ke Google Workspace (Sheet + Doc + Drive)
python -m jobbot.cli gdrive

# Produksi deliverable nyata (developer/designer/writer/web3)
python -m jobbot.cli execute --role web3 --title "NFT marketplace smart contract" --company "Client"
python -m jobbot.cli execute --role developer --title "Build a React dashboard" --company "Client"
python -m jobbot.cli execute --role designer --title "Landing page design" --company "Client"
python -m jobbot.cli execute --role writer --title "Blog post about productivity" --company "Client"

# Pipeline autonomous end-to-end (sekali jalan, tanpa interaksi)
python -m jobbot.cli autopilot --max-deliverables 3

# Long-running loop (jalan terus, siklus tiap 1 jam)
python -m jobbot.cli autopilot --interval 3600

# Setup Google OAuth (sekali)
python -m jobbot.cli setup-oauth

# Bot Telegram dua arah (terima file & perintah)
python -m jobbot.cli bot            # polling sekali
python -m jobbot.cli bot --forever  # long-running (terus polling)

# Kirim laporan email via SMTP
python -m jobbot.cli email --subject "Daily report"

# Background ticker (interval detik)
python -m jobbot.cli tick --interval 3600
```

## Konfigurasi (env var)

| Env var | Fungsi |
|---|---|
| `JOB_TELEGRAM_TOKEN` | Token bot Telegram (dari @BotFather) |
| `JOB_TELEGRAM_CHANNEL_ID` | ID/username channel Telegram (mis. `@channel` atau `-100...`) |
| `JOB_TELEGRAM_ADMIN_ID` | Chat ID admin (opsional, batasi akses bot dua arah) |
| `JOB_GOOGLE_SERVICE_ACCOUNT` | Path file service_account.json (default `jobbot/service_account.json`) |
| `JOB_GOOGLE_SUBJECT` | Email Workspace user yang di-impersonate (wajib untuk Gmail/Drive atas nama user) |
| `JOB_EMAIL_USER` | Email pengirim (SMTP) |
| `JOB_EMAIL_PASS` | App password email (SMTP) |
| `JOB_EMAIL_RECIPIENT` | Email tujuan laporan |
| `JOB_EMAIL_SMTP` | Host SMTP (default `smtp.gmail.com`) |
| `JOB_GITHUB_TOKEN` | Token GitHub (untuk GitHub Jobs) |

## Alur Kerja

1. **Setup Telegram** (user): buat bot via @BotFather, tambahkan ke channel, set `JOB_TELEGRAM_TOKEN` & `JOB_TELEGRAM_CHANNEL_ID`.
2. **Setup Google** (user): jalankan `python -m jobbot.cli setup-oauth` setelah menempatkan `credentials.json` di `jobbot/`.
3. **Jalankan scraping**: `python -m jobbot.cli run` — hasil tersimpan ke `jobbot/jobs.db` dan dikirim ke Telegram.
4. **Jadwalkan harian**: tambahkan cron `0 9 * * * cd /path && python -m jobbot.cli run`.
5. **Laporan**: email via SMTP dan/atau Google Sheets/Drive untuk pengolahan data.

## Kemampuan Produksi Deliverable (executor.py)

Sistem **mengerjakan pekerjaan sendiri**, bukan sekadar melamar. Modul `executor.py`
menghasilkan deliverable nyata yang siap kirim untuk 4 role:

| Role | Output | Generator |
|---|---|---|
| developer | Next.js/React app, FastAPI backend | `build_web_app()`, `build_api()` |
| designer | Landing page HTML/CSS, brand kit (logo SVG + guide) | `build_landing_page()`, `build_brand_kit()` |
| writer | Artikel/blog (Markdown + HTML) | `write_article()` |
| web3 | Smart contract Solidity + Hardhat + test + deploy + audit checklist | `build_smart_contract()` |

Fungsi utama:
- `execute_job(job, role=None)` — auto-detect role, produksi deliverable, return dict.
- `execute_contract(conn, contract_id, role=None)` — produksi deliverable untuk
  kontrak di DB, catat deliverable, set status `delivered`.

Semua output **bukan placeholder** — kode nyata yang siap di-`npm install`/`pip install`/compile/deploy.

## Mode Autonomous (autopilot.py)

Sistem bisa bekerja **sepenuhnya tanpa interaksi manusia** (autonomous & long-running).
Tidak ada langkah yang butuh approve/konfirmasi — semua tulis file, update DB, dan
report dijalankan langsung. Hanya perintah berbahaya (rm -rf, dd, force-push) yang
ditunda, dan autopilot tidak memakainya.

Pipeline per siklus:
```
scrape -> rank high-value -> filter relevansi (4 role) -> generate proposal
-> buat kontrak -> produksi deliverable nyata -> report Telegram
-> (opsional) Google Workspace
```

Filter relevansi (`_is_relevant`) memastikan hanya job yang cocok dengan 4 role
(developer/designer/writer/web3) yang diproses — job non-teknis (VP, sales, HR,
finance) otomatis di-skip.

Cara menjalankan:
```bash
# Sekali jalan (foreground)
python -m jobbot.cli autopilot --max-deliverables 3

# Long-running (loop terus, siklus tiap 1 jam)
python -m jobbot.cli autopilot --interval 3600

# Dengan laporan Google Workspace
python -m jobbot.cli autopilot --max-deliverables 3 --report-google
```

## Google Workspace (Service Account + Gmail)

Sistem mendukung **Service Account** (autonomous, token tidak expire, tanpa browser)
untuk Drive/Sheets/Docs/Gmail. Lebih cocok untuk mode autonomous dibanding OAuth desktop.

### Setup Service Account
1. Google Cloud Console → enable **Drive API, Sheets API, Docs API, Gmail API**.
2. Buat **Service Account** → download JSON → simpan `jobbot/service_account.json`.
3. (Untuk Gmail & akses atas nama user Workspace) **Domain-Wide Delegation**:
   - Google Admin Console → Security → API Controls → Manage Domain Wide Delegation.
   - Client ID = `client_id` di JSON; scopes = `gmail.send, gmail.modify, drive, spreadsheets, documents`.
   - Set `JOB_GOOGLE_SUBJECT` = email Workspace user (mis. `bot@domain-anda.com`).

### Fungsi Gmail (gmail.py)
- `send_email(to, subject, body)` — kirim email baru.
- `reply_email(message_id, body)` — balas email tertentu.
- `list_unread()` — daftar email belum dibaca (untuk auto-reply).
- `mark_read(message_id)` — tandai sudah dibaca.

> Tanpa `JOB_GOOGLE_SUBJECT`, service account hanya bisa buat file di Drive-nya
> sendiri; Gmail akan gagal (`Precondition check failed`) karena service account
> tidak punya mailbox.

## Bot Telegram Dua Arah (telegram_bot.py)

Melengkapi `reporter.py` (satu arah). Bot ini bisa **menerima file & perintah** dari user:

- **Kirim file** (JSON/gambar/dokumen) → otomatis tersimpan ke `inbox/`.
- **Perintah singkat**: `/status`, `/autopilot`, `/report`, `/earnings`, `/files`, `/help`.

Menjalankan:
```bash
python -m jobbot.cli bot            # polling sekali (proses pesan yang tertunda)
python -m jobbot.cli bot --forever  # long-polling terus-menerus
```

Batasi akses dengan `JOB_TELEGRAM_ADMIN_ID` (chat ID user). File yang diterima
disimpan di direktori `inbox/` (root proyek).

## Email via SMTP (gratis, tanpa Workspace)

Untuk **mengirim** email (laporan, deliverable, proposal ke klien) tanpa perlu
Google Workspace, gunakan **SMTP Gmail + App Password**:

1. Aktifkan **2-Step Verification** di akun Gmail.
2. Buat **App Password** (Google Account → Security → App passwords).
3. Set env `JOB_EMAIL_USER`, `JOB_EMAIL_PASS`, `JOB_EMAIL_RECIPIENT`.

```bash
# Kirim laporan email manual
python -m jobbot.cli email --subject "Daily report"

# Autopilot + kirim laporan email
python -m jobbot.cli autopilot --max-deliverables 3 --report-email
```

Fungsi: `send_email` (gmail.py, butuh Workspace) vs `EmailReporter.send`
(email_report.py, SMTP — gratis). Untuk kirim saja, **pakai SMTP**.

> SMTP hanya bisa **mengirim**, tidak bisa membaca/membalas inbox. Untuk
> baca/balas inbox tetap butuh Workspace (Domain-Wide Delegation).

## Disclaimer

Scraping harus mematuhi ToS masing-masing platform. Gunakan untuk keperluan pribadi/edukasi. Rate-limit & politeness (delay antar request) sudah diterapkan.
