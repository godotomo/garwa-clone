---
name: google-workspace
description: "Gmail, Calendar, Drive, Docs, Sheets via gws CLI or Python. Gunakan skill ini setiap kali user ingin mengakses/mengelola Google Workspace: membaca/mengirim/membalas email Gmail, melihat/membuat acara Calendar, mencari/mengunggah/mengunduh/berbagi file di Drive, membaca/menulis Google Sheets, membaca/membuat Google Docs, atau daftar kontak. Menyediakan CLI `google_api.py` dan setup OAuth non-interaktif."
version: 1.2.0
---

# Google Workspace (Garwa)

Gmail, Calendar, Drive, Contacts, Sheets, dan Docs — melalui OAuth yang dikelola Garwa dan CLI wrapper tipis. Ketika `gws` terpasang, skill memakainya sebagai backend eksekusi; jika tidak, jatuh ke implementasi Python bawaan.

## Referensi

- `references/gmail-search-syntax.md` — operator pencarian Gmail (is:unread, from:, newer_than:, dll.)
- `references/daily-brief.md` — prosedur brief harian/pagi: jadwal + konflik + persiapan rapat + email mendesak dari Gmail dan Calendar. Muat saat user minta morning brief, persiapan rapat, atau "apa yang ada di kalender saya dan email apa yang perlu perhatian."

## Scripts

- `scripts/setup.py` — setup OAuth2 (jalankan sekali untuk otorisasi)
- `scripts/google_api.py` — CLI wrapper kompatibilitas. Mengutamakan `gws` bila tersedia, sambil mempertahankan kontrak output JSON.
- `scripts/_garwa_home.py` — resolve `GARWA_HOME` (default `~/.garwa`).
- `scripts/gws_bridge.py` — bridge token OAuth Garwa ke CLI `gws`.

## First-Time Setup

Setup sepenuhnya non-interaktif — Anda yang mengemudikannya langkah demi langkah sehingga bekerja di CLI, Telegram, atau platform apa pun.

Definisikan shorthand dulu:

```bash
GSETUP="python ${GARWA_HOME:-$HOME/.garwa}/skills/google-workspace/scripts/setup.py"
```

> Catatan: path skill sebenarnya ada di repo Garwa, bukan di `$GARWA_HOME`. Gunakan path relatif ke skill:
> ```bash
> GSETUP="python skills/google-workspace/scripts/setup.py"
> ```
> `$GARWA_HOME` hanya lokasi penyimpanan token (`~/.garwa/google_token.json`), ditangani otomatis oleh script.

### Step 0: Cek apakah sudah setup

```bash
$GSETUP --check
```

Jika mencetak `AUTHENTICATED`, lewati ke Usage — setup sudah selesai.

### Step 1: Triage — tanya user apa yang mereka butuhkan

Sebelum memulai setup OAuth, tanya user DUA pertanyaan:

**Pertanyaan 1: "Layanan Google apa yang Anda butuhkan? Hanya email, atau juga Calendar/Drive/Sheets/Docs?"**

- **Hanya email** → Mereka tidak butuh skill ini sama sekali. Gunakan email SMTP/IMAP bawaan Garwa (App Password Gmail) — 2 menit, tanpa project Google Cloud.
- **Email + Calendar** → Lanjutkan dengan skill ini, pakai `--services email,calendar` saat auth.
- **Calendar/Drive/Sheets/Docs saja** → Lanjutkan dengan set `--services` yang lebih sempit seperti `calendar,drive,sheets,docs`.
- **Akses Workspace penuh** → Lanjutkan dengan set layanan `all` default.

**Pertanyaan 2: "Apakah akun Google Anda memakai Advanced Protection (hardware security key wajib untuk masuk)? Jika tidak yakin, kemungkinan besar tidak."**

- **Tidak / Tidak yakin** → Setup normal.
- **Ya** → Admin Workspace harus menambahkan OAuth client ID ke daftar app yang diizinkan sebelum Step 4 berhasil.

### Step 2: Buat kredensial OAuth (sekali, ~5 menit)

> Anda butuh OAuth client Google Cloud. Ini setup sekali:
>
> 1. Buat/pilih project: https://console.cloud.google.com/projectselector2/home/dashboard
> 2. Aktifkan API yang dibutuhkan dari API Library: https://console.cloud.google.com/apis/library
>    Aktifkan: Gmail API, Google Calendar API, Google Drive API, Google Sheets API, Google Docs API, People API
> 3. Buat OAuth client: https://console.cloud.google.com/apis/credentials
>    Credentials → Create Credentials → OAuth 2.0 Client ID
> 4. Application type: "Desktop app" → Create
> 5. Jika app masih dalam Testing, tambahkan akun Google user sebagai test user: https://console.cloud.google.com/auth/audience → Audience → Test users → Add users
> 6. Download file JSON dan beri tahu path-nya

Setelah mereka beri path:

```bash
$GSETUP --client-secret /path/to/client_secret.json
```

### Step 3: Dapatkan authorization URL

```bash
$GSETUP --auth-url --services email,calendar --format json
$GSETUP --auth-url --services calendar,drive,sheets,docs --format json
$GSETUP --auth-url --services all --format json
```

Ini mengembalikan JSON dengan field `auth_url`. Kirim URL itu ke user sebagai satu baris. Beri tahu bahwa browser kemungkinan gagal di `http://localhost:1` setelah persetujuan, dan ini normal. Minta user menyalin SELURUH URL hasil redirect dari address bar.

### Step 4: Tukar kode

```bash
$GSETUP --auth-code "URL_ATAU_KODE_YANG_USER_TEMPEL" --format json
```

Jika gagal karena kode kedaluwarsa, kembalikan `fresh_auth_url` baru dan minta user coba lagi dengan redirect browser terbaru.

### Step 5: Verifikasi

```bash
$GSETUP --check
```

Harus mencetak `AUTHENTICATED`. Setup selesai — token auto-refresh mulai sekarang.

### Catatan

- Token disimpan di `~/.garwa/google_token.json` dan auto-refresh.
- `GARWA_HOME` env bisa mengubah lokasi (default `~/.garwa`).
- Untuk revoke: `$GSETUP --revoke`

## Usage

Semua perintah lewat script API. Set `GAPI` sebagai shorthand:

```bash
GAPI="python skills/google-workspace/scripts/google_api.py"
```

### Gmail

```bash
# Cari (mengembalikan array JSON dengan id, from, subject, date, snippet)
$GAPI gmail search "is:unread" --max 10
$GAPI gmail search "from:boss@company.com newer_than:1d"
$GAPI gmail search "has:attachment filename:pdf newer_than:7d"

# Baca pesan penuh (mengembalikan JSON dengan body text)
$GAPI gmail get MESSAGE_ID

# Kirim
$GAPI gmail send --to user@example.com --subject "Hello" --body "Message text"
$GAPI gmail send --to user@example.com --subject "Hello" --body "<h1>Q4</h1><p>Details...</p>" --html

# Balas (otomatis threading dan set In-Reply-To)
$GAPI gmail reply MESSAGE_ID --body "Thanks, that works for me."

# Label
$GAPI gmail labels
$GAPI gmail modify MESSAGE_ID --add-labels LABEL_ID
$GAPI gmail modify MESSAGE_ID --remove-labels UNREAD
```

### Calendar

```bash
# List event (default 7 hari ke depan)
$GAPI calendar list
$GAPI calendar list --start 2026-03-01T00:00:00Z --end 2026-03-07T23:59:59Z

# Buat event (ISO 8601 dengan timezone wajib)
$GAPI calendar create --summary "Team Standup" --start 2026-03-01T10:00:00-06:00 --end 2026-03-01T10:30:00-06:00
$GAPI calendar create --summary "Review" --start 2026-03-01T14:00:00Z --end 2026-03-01T15:00:00Z --attendees "alice@co.com,bob@co.com"

# Detail satu event
$GAPI calendar get EVENT_ID

# Perbarui event (hanya field yang diisi yang diubah)
$GAPI calendar update EVENT_ID --summary "Judul Baru"
$GAPI calendar update EVENT_ID --start 2026-03-01T11:00:00-06:00 --end 2026-03-01T11:30:00-06:00
$GAPI calendar update EVENT_ID --location "Zoom" --description "Notulensi rapat"

# Hapus event
$GAPI calendar delete EVENT_ID

# Daftar semua kalender yang terhubung ke akun
$GAPI calendar list-calendars
```

### Drive

```bash
# Cari file
$GAPI drive search "quarterly report" --max 10
$GAPI drive search "mimeType='application/pdf'" --raw-query --max 5

# Metadata satu file
$GAPI drive get FILE_ID

# Upload file lokal (auto-detect MIME type)
$GAPI drive upload /path/to/report.pdf
$GAPI drive upload /path/to/image.png --name "Logo.png" --parent FOLDER_ID

# Download (file biner apa adanya; file native Google diekspor — Docs→pdf, Sheets→csv, Slides→pdf, Drawings→png)
$GAPI drive download FILE_ID
$GAPI drive download DOC_ID --output ~/doc.pdf

# Buat folder
$GAPI drive create-folder "Reports"
$GAPI drive create-folder "Q4" --parent FOLDER_ID

# Bagikan
$GAPI drive share FILE_ID --email alice@example.com --role reader
$GAPI drive share FILE_ID --type anyone --role reader        # anyone with link

# Hapus — default ke trash (reversible). Pakai --permanent untuk skip trash.
$GAPI drive delete FILE_ID
$GAPI drive delete FILE_ID --permanent
```

### Contacts

```bash
$GAPI contacts list --max 20
```

### Sheets

```bash
# Buat spreadsheet baru
$GAPI sheets create --title "Q4 Budget"
$GAPI sheets create --title "Inventory" --sheet-name "Stock"

# Baca
$GAPI sheets get SHEET_ID "Sheet1!A1:D10"

# Tulis
$GAPI sheets update SHEET_ID "Sheet1!A1:B2" --values '[["Name","Score"],["Alice","95"]]'

# Append baris
$GAPI sheets append SHEET_ID "Sheet1!A:C" --values '[["new","row","data"]]'
```

### Docs

```bash
# Baca
$GAPI docs get DOC_ID

# Buat Doc baru (opsional di-seed body text)
$GAPI docs create --title "Meeting Notes"
$GAPI docs create --title "Draft" --body "First paragraph..."

# Append teks ke akhir Doc yang ada
$GAPI docs append DOC_ID --text "Additional content to append"
```

## Output Format

Semua perintah mengembalikan JSON. Field kunci:

- **Gmail search**: `[{id, threadId, from, to, subject, date, snippet, labels}]`
- **Gmail get**: `{id, threadId, from, to, subject, date, labels, body}`
- **Gmail send/reply**: `{status: "sent", id, threadId}`
- **Calendar list**: `[{id, summary, start, end, location, description, status, htmlLink}]`
- **Calendar get**: `{id, summary, description, location, start, end, status, htmlLink, attendees, creator}`
- **Calendar create**: `{status: "created", id, summary, htmlLink}`
- **Calendar update**: `{status: "updated", id, summary, start, end, htmlLink}`
- **Calendar delete**: `{status: "deleted", eventId}`
- **Calendar list-calendars**: `[{id, summary, description, accessRole, primary, timeZone}]`
- **Drive search**: `[{id, name, mimeType, modifiedTime, webViewLink}]`
- **Drive get**: `{id, name, mimeType, modifiedTime, size, webViewLink, parents, owners}`
- **Drive upload**: `{status: "uploaded", id, name, mimeType, webViewLink}`
- **Drive download**: `{status: "downloaded", id, name, path, mimeType}`
- **Drive create-folder**: `{status: "created", id, name, webViewLink}`
- **Drive share**: `{status: "shared", permissionId, fileId, role, type}`
- **Drive delete**: `{status: "trashed" | "deleted", fileId, permanent}`
- **Contacts list**: `[{name, emails: [...], phones: [...]}]`
- **Sheets get**: `[[cell, cell, ...], ...]`
- **Sheets create**: `{status: "created", spreadsheetId, title, spreadsheetUrl}`
- **Docs create**: `{status: "created", documentId, title, url}`
- **Docs append**: `{status: "appended", documentId, inserted_at, characters}`

## Aturan

1. **Jangan pernah kirim email, buat/hapus event calendar, hapus file Drive, bagikan file, atau modifikasi Docs/Sheets tanpa konfirmasi user dulu.** Tunjukkan apa yang akan dilakukan (penerima, file ID, konten, peran share) dan minta persetujuan. Untuk `drive delete`, utamakan trash default (reversible) daripada `--permanent`.
2. **Cek auth sebelum penggunaan pertama** — jalankan `setup.py --check`. Jika gagal, pandu user lewat setup.
3. **Gunakan referensi syntax pencarian Gmail** untuk query kompleks — muat dengan `read_file` pada `references/gmail-search-syntax.md`.
4. **Waktu Calendar harus sertakan timezone** — selalu ISO 8601 dengan offset (mis. `2026-03-01T10:00:00-06:00`) atau UTC (`Z`).
5. **Hormati rate limit** — hindari panggilan API cepat beruntun. Batch baca bila memungkinkan.

## Troubleshooting

| Masalah | Solusi |
|---------|--------|
| `NOT_AUTHENTICATED` | Jalankan setup Steps 2-5 di atas |
| `REFRESH_FAILED` | Token dicabut/kedaluwarsa — ulangi Steps 3-5 |
| `HttpError 403: Insufficient Permission` | Scope API kurang — `$GSETUP --revoke` lalu ulangi Steps 3-5 |
| `AUTHENTICATED (partial)` atau "Token missing scopes" | Kemampuan tulis baru butuh re-otorisasi. `$GSETUP --revoke` lalu ulangi Steps 3-5 |
| `HttpError 403: Access Not Configured` | API belum diaktifkan — user perlu mengaktifkannya di Google Cloud Console |
| `ModuleNotFoundError` | Jalankan `$GSETUP --install-deps` |
| Advanced Protection memblokir auth | Admin Workspace harus allowlist OAuth client ID |

## Revoking Access

```bash
$GSETUP --revoke
```
