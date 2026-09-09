---
name: job-tracker
description: Scraping & pelaporan lowongan freelance platform luar (bayar USD) yang terintegrasi ke Garwa. Gunakan skill ini setiap kali user ingin mencari lowongan freelance (Remote OK, Remotive, We Work Remotely, GitHub Jobs, Working Nomads, Jobicy, Arbeitnow, JobsCollider), melamar pekerjaan, membuat laporan harian lowongan, mengirim notifikasi ke Telegram channel, atau menyimpan laporan ke Google Sheets/Drive. Menyediakan CLI `jobbot` yang sudah terverifikasi berfungsi.
---

# Job Tracker

Skill ini membungkus sistem scraping lowongan freelance multi-platform yang **sudah terverifikasi berfungsi** (diuji dengan data asli dari Remote OK & Remotive). Target: minimal $10/hari dari pekerjaan freelance luar (developer, designer, writer, web3).

> **Arsitektur (Garwa = runner utama):** jobbot TIDAK menduplikasi fitur yang sudah ada di Garwa. Email/IMAP/Telegram/cron-scheduling/Google Workspace dipanggil lewat `_garwa_bridge.py` yang membungkus `garwa.tools.comm_tools` dan skill `google-workspace`. Modul dobel lama (`email_report`, `gmail`, `imap_inbox`, `telegram_bot`, `google_auth`, `google_drive`) sudah dihapus.

## Lokasi & Cara Menjalankan

Kode ada di `skills/job-tracker/scripts/jobbot/`. CLI dijalankan via path skill:

```bash
# Dari root repo garwa-coder-v2
python skills/job-tracker/scripts/jobbot/cli.py run
```

Atau set PYTHONPATH agar bisa `python -m jobbot.cli ...`:

```bash
PYTHONPATH=skills/job-tracker/scripts python -m jobbot.cli run
```

## Arsitektur

```
skills/job-tracker/scripts/jobbot/
  db.py            # schema SQLite skill (jobs, applications, progress) — TERPISAH dari DB runtime Garwa
  models.py        # Job + operasi CRUD (dedup via UNIQUE(platform, job_id))
  scraper.py       # core multi-platform scraper
  reporter.py      # Telegram channel reporter (via Garwa bridge)
  proposal_email.py# kirim proposal email (via Garwa bridge)
  auto_reply.py    # auto-reply email cerdas (deteksi intent + balas kontekstual)
  llm_filter.py    # filter relevansi job via LLM (retry + backoff)
  workflow.py      # contract lifecycle (create/deliver/revise/complete)
  executor.py      # mesin produksi deliverable nyata (4 role)
  autopilot.py     # pipeline autonomous end-to-end (tanpa interaksi)
  proposal.py      # generator proposal + role detection
  cron.py          # cron scheduler harian (scraping berkala)
  github_client.py # publish deliverable ke GitHub
  _garwa_bridge.py # jembatan ke fitur runtime Garwa (email/IMAP/Telegram/Google)
  cli.py           # entrypoint CLI
```

### Pemisahan DB (PENTING)

DB skill **TIDAK pernah tercampur** dengan DB runtime Garwa (`~/.garwa/garwa.db`).
DB jobbot disimpan di `skills/job-tracker/scripts/jobs.db` (resolve otomatis dari
lokasi file `db.py`). Jangan pernah mengarahkan `DB_PATH` ke DB runtime Garwa.

## Platform Terverifikasi (tanpa auth)

| Platform | Endpoint | Status |
|---|---|---|
| Remote OK | `https://remoteok.com/api` (JSON) | ✅ Terverifikasi |
| Remotive | `https://remotive.com/api/remote-jobs` (JSON) | ✅ Terverifikasi |
| We Work Remotely | `https://weworkremotely.com/feeds/jobs.rss` (RSS) | ⚠️ Perlu test |
| GitHub Jobs | `https://api.github.com/search/jobs` (butuh GITHUB_TOKEN) | ⚠️ Perlu token |
| Working Nomads | `https://www.workingnomads.com/api/exposed_jobs/` (JSON) | ✅ Terverifikasi |
| Jobicy | `https://jobicy.com/api/v2/remote-jobs` (JSON) | ✅ Terverifikasi |
| Arbeitnow | `https://www.arbeitnow.com/api/job-board-api` (JSON) | ✅ Terverifikasi |
| JobsCollider | `https://jobscollider.com/api/search-jobs` (JSON, salary tahunan, 16 kategori) | ✅ Terverifikasi |

> Upwork/Freelancer/Indeed memakai anti-bot (Cloudflare) — scraping HTML sering
> gagal/tidak stabil. Jangan andalkan sebagai sumber utama; gunakan Remote OK +
> Remotive sebagai baseline.

## ⚠️ Jebakan Parsing (PENTING)

1. **Remote OK** mengembalikan item pertama sebagai **metadata (bukan job)** — selalu skip `data[1:]` dan filter `item.get("id")` & `item.get("position")` yang kosong.
2. **GitHub Jobs** (`api.github.com/search/jobs`) memerlukan `GITHUB_TOKEN` — tanpa token akan 401/403.

## CLI (jobbot)

```bash
# Dari root repo
J="python skills/job-tracker/scripts/jobbot/cli.py"

# Scrapa + report sekali (semua platform)
$J run

# Scrapa platform tertentu
$J run --platforms "remote-ok,remotive" --limit 20

# Custom keyword
$J run --keywords "python developer,solidity developer"

# Tampilkan job di DB
$J list --limit 20

# Report manual ke Telegram
$J report

# Statistik progress
$J stats

# Export jobs ke CSV/Google Sheets
$J export --format sheet --title "Jobbot Jobs"

# Laporan harian lengkap ke Google Workspace (Sheet + Doc + Drive)
$J gdrive

# Produksi deliverable nyata (developer/designer/writer/web3)
$J execute --role web3 --title "NFT marketplace smart contract" --company "Client"
$J execute --role developer --title "Build a React dashboard" --company "Client"

# Pipeline autonomous end-to-end (sekali jalan, tanpa interaksi)
$J autopilot --max-deliverables 3

# Long-running loop (jalan terus, siklus tiap 1 jam)
$J autopilot --interval 3600

# Setup Google OAuth (skill google-workspace)
$J setup-oauth

# Bot Telegram dua arah (via Garwa gateway)
$J bot            # polling sekali
$J bot --forever  # long-running

# Kirim laporan email via SMTP (via Garwa bridge)
$J email --subject "Daily report"

# Cek / balas email masuk via IMAP (via Garwa bridge)
$J inbox --limit 20
$J reply --num 3 --body "Balasan..."
$J watch --smart --interval 60   # polling inbox + auto-reply cerdas

# Catat aplikasi lamaran
$J apply --platform upwork --job-id 123 --title "Project X"
```

## Konfigurasi (env var)

| Env var | Fungsi |
|---|---|
| `JOB_TELEGRAM_TOKEN` | Token bot Telegram (fallback `TELEGRAM_TOKEN`) |
| `JOB_TELEGRAM_CHANNEL_ID` | ID/username channel Telegram (mis. `@channel` atau `-100...`) |
| `JOB_EMAIL_USER` | Email pengirim SMTP (fallback `EMAIL_USER` / `GARWA_EMAIL_USER`) |
| `JOB_EMAIL_PASS` | App password email SMTP (fallback `EMAIL_PASS` / `GARWA_EMAIL_PASS`) |
| `JOB_EMAIL_RECIPIENT` | Email tujuan laporan (fallback `EMAIL_RECIPIENT`) |
| `JOB_GITHUB_TOKEN` | Token GitHub (untuk GitHub Jobs & publish deliverable) |

> Email/IMAP/Telegram/cron/Google kini memakai konfigurasi **Garwa** (lewat
> `_garwa_bridge.py`). `JOB_*` tetap didukung sebagai override khusus jobbot.

## Alur Kerja

1. **Setup Telegram** (user): buat bot via @BotFather, set `GARWA_TELEGRAM_TOKEN` & `GARWA_TELEGRAM_CHAT_ID` (atau `JOB_TELEGRAM_TOKEN`/`JOB_TELEGRAM_CHANNEL_ID`).
2. **Setup Google** (user): jalankan `$J setup-oauth` (skill google-workspace) setelah menempatkan OAuth client.
3. **Jalankan scraping**: `$J run` — hasil tersimpan ke `skills/job-tracker/scripts/jobs.db` dan dikirim ke Telegram.
4. **Jadwalkan harian**: `$J tick --interval 3600` (loop) atau via Garwa cron (`tool_schedule_task` menjadwalkan `$J run`).
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

Output disimpan ke `skills/job-tracker/scripts/deliverables/<slug>/` (terpisah dari repo runtime).

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

## Google Workspace

Integrasi Google (Sheets/Drive/Docs) dipanggil lewat skill `google-workspace`
(`skills/google-workspace/scripts/google_api.py`), dibungkus di `_garwa_bridge.py`.
Setup OAuth: `$J setup-oauth`. Token disimpan di `~/.garwa/google_token.json`.

## Bot Telegram Dua Arah

Subcommand `bot` mendelegasikan ke **Garwa gateway** (`garwa.telegram_gateway`),
yang sudah menangani pesan, media, perintah, dan agent turn. Tidak ada bot Telegram
duplikat di jobbot.

## Email via SMTP/IMAP

Kirim/baca/balas email memakai fitur **Garwa** (`garwa.tools.comm_tools`):
`tool_send_email`, `tool_read_inbox`, `tool_read_email`, `tool_reply_email`.
Jobbot hanya membungkusnya di `_garwa_bridge.py`. Konfigurasi via
`GARWA_EMAIL_USER`/`GARWA_EMAIL_PASS` (fallback `JOB_EMAIL_*`).

## Disclaimer

Scraping harus mematuhi ToS masing-masing platform. Gunakan untuk keperluan pribadi/edukasi. Rate-limit & politeness (delay antar request) sudah diterapkan.
