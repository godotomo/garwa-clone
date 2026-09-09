---
name: browser-automation
description: Otomasi browser modern (Playwright, CDP, DrissionPage) untuk registrasi akun otomatis, pembuatan profil, pengisian formulir multi-langkah (multi-step form filling), verifikasi email/OTP, dan manajemen session cookies.
version: 1.0.0
category: web-automation
platforms: [linux, macos, windows, termux]
---

# browser-automation

Panduan komprehensif untuk automasi browser headless, Chrome DevTools Protocol (CDP), Playwright, dan DrissionPage guna menjalankan tugas kompleks seperti:
1. Registrasi akun mandiri di web.
2. Pengisian formulir multi-langkah (form filling).
3. Pembuatan profil pengguna secara dinamis dan otonom.
4. Integrasi penanganan OTP/magic link via email.
5. Preservasi state, token, dan cookies lintas sesi.

---

## 0. Batasan Lingkungan (PENTING)

### Termux (Android) — Browser SUNGGAHAN TERSEDIA (update 2026-09)
**Temuan terbaru:** Termux kini dapat menjalankan browser sungguhan (Firefox/Chromium) via `x11-repo` + `tur-repo`, dan ada tool `termux-browser-pilot` yang bisa menembus Cloudflare/Turnstile. Ini membuka automasi yang sebelumnya "tidak feasible".

**Setup browser di Termux:**
```bash
# 1. Tambah repo (sekali)
pkg install -y x11-repo tur-repo
# 2. Install Firefox (paling ringan ~67MB) + Xvfb + tools
pkg install -y firefox xorg-server-xvfb xdotool xclip openbox imagemagick python3 ca-certificates
# 3. Install termux-browser-pilot (dari source, karena tidak di PyPI)
git clone https://github.com/salviz/termux-browser-pilot.git
# 4. Buat wrapper manual (pip build isolation rusak di Termux py3.14)
cat > $PREFIX/bin/tbp <<'EOF'
#!/usr/bin/env bash
export PYTHONPATH="/path/ke/termux-browser-pilot${PYTHONPATH:+:$PYTHONPATH}"
exec python3 /path/ke/termux-browser-pilot/cli.py "$@"
EOF
chmod +x $PREFIX/bin/tbp
```

**Catatan penting:**
- **Firefox lebih ringan** (~67MB paket / ~276MB terinstall) vs Chromium (~128–144MB / ~570–640MB). Pilih Firefox untuk hemat.
- **Firefox mode diklaim "passes Cloudflare natively via TLS fingerprint"**; Chromium punya Turnstile handler. Terverifikasi berhasil di 9inference.cloud (Turnstile tidak memblokir registrasi).
- **pip di Termux Python 3.14 bisa error** `No module named 'pip._internal.operations.install.wheel'` — ini BUKAN pip rusak permanen. Akar masalahnya `libexpat` terlalu lama (2.7.x) yang tidak punya simbol `XML_SetHashSalt16Bytes` yang dibutuhkan `pyexpat`. Solusi: `pkg install -y libexpat` (upgrade ke 2.8.4) → pyexpat OK → pip install bekerja (TERUJI 2026-09). Untuk `termux-browser-pilot` tetap pakai wrapper manual (langkah 4) karena paketnya tidak di PyPI.
- Browser teks (`lynx`, `w3m`, `links`) TIDAK bisa menembus Turnstile (tanpa JS penuh).

**Perintah dasar `tbp`:**
```bash
tbp start                          # mulai daemon (otomatis start Xvfb + openbox + Firefox)
tbp goto URL [-cf]                 # navigasi, -cf = Cloudflare bypass
tbp text / tbp html                # baca konten halaman
tbp eval "document.title"          # jalankan JavaScript
tbp find "Teks"                    # cari elemen by text
tbp click "selector" / tbp type "sel" "nilai"
tbp iframe list                    # deteksi iframe (mis. Turnstile)
tbp cookies --save f.json          # simpan sesi login
tbp screenshot page.png            # screenshot
tbp stop                           # matikan daemon
```

**Verifikasi status:** `tbp status` (PID, browser, URL, uptime).

- Solusi:
  - **Desktop/Linux/macOS**: gunakan Playwright + Chromium (pilihan utama, lihat section 1.B).
  - **Termux**: gunakan `termux-browser-pilot` + Firefox/Xvfb (lihat di atas). Untuk scraping data ringan tetap bisa pakai HTTP client (`httpx`/`requests`) atau API JSON platform.

---

## 1. Arsitektur dan Mode Eksekusi

### A. Local CDP Connection (Chrome / Chromium Debug Mode)
Agen dapat mengontrol browser lokal operator tanpa terdeteksi sebagai bot dasar:
```bash
google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.config/garwa/browser-profile" &
```

### B. Headless Playwright / Python Scripting
```python
from playwright.sync_api import sync_playwright

def run_automation(target_url, profile_data):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        page.goto(target_url, wait_until="networkidle")
        browser.close()
```

---

## 2. Formulir dan Registrasi (Form Filling Pipeline)

1. **Selector Heuristics**:
   - Deteksi input otomatis melalui `name`, `id`, `type`, `placeholder`, `aria-label`, dan text label terdekat.
   - Fallback selector hierarkis: CSS ID > name attr > data-testid > XPath berbasis label text.

2. **Human-like Typing dan Interactions**:
   - Jangan mengisi `input.value` secara instan jika situs memakai anti-bot behavioral.
   - Gunakan `page.type(selector, text, delay=50)` untuk menstimulasi keyboard event asli.
   - Trigger event `change` dan `blur` setelah mengisi field input.

3. **Multi-Step Form / Wizard Workflow**:
   - Step 1: Input data dasar (Email, Password, Username).
   - Step 2: Cek tombol Submit / Next -> tunggu transisi DOM / navigasi URL.
   - Step 3: Input detail profil (Nama Lengkap, Bio, Kategori Keahlian, Alamat).
   - Step 4: Handle upload avatar / CV jika ada `<input type="file">`.

---

## 3. Integrasi Email Verification dan OTP

Saat formulir registrasi membutuhkan verifikasi email / magic link / OTP 6 digit:
1. Baca email masuk via IMAP Garwa (`garwa.tools.comm_tools.tool_read_inbox` /
   `tool_read_email`) untuk mendapatkan email terbaru. Skill `job-tracker` juga
   menyediakan wrapper `_garwa_bridge.list_unread()` / `_garwa_bridge.read_email()`.
2. Ekstrak OTP numerik atau URL verifikasi menggunakan regex:
   ```python
   import re
   otp_match = re.search(r'\b\d{6}\b', email_body)
   link_match = re.search(r'https?://[^\s<>"']+/(?:verify|activate|confirm)[^\s<>"']*', email_body)
   ```
3. Lanjutkan navigasi browser ke link verifikasi atau masukkan OTP ke input form.

---

## 4. Cloudflare Turnstile / Anti-Bot Bypass (via Termux Browser)

**Temuan kunci (terverifikasi di 9inference.cloud):** Turnstile memblokir curl/headless/datacenter IP, tapi **browser sungguhan di Termux berhasil melewatinya** — registrasi 3-langkah (Email → Kode → Password) berjalan normal.

**Workflow menembus Turnstile di Termux:**
1. **Mulai daemon** → `tbp start` (otomatis Xvfb + openbox + Firefox).
2. **Navigasi dengan flag Cloudflare** → `tbp goto "https://target" -cf`.
3. **Verifikasi halaman termuat penuh** (bukan challenge):
   ```bash
   tbp text   # harus berisi konten asli, bukan "Verify you are human"
   ```
4. **Deteksi widget Turnstile:**
   ```bash
   tbp iframe list   # cari iframe Turnstile
   tbp eval "typeof turnstile !== 'undefined' ? 'loaded' : 'not loaded'"
   tbp eval "document.querySelector('[name=cf-turnstile-response]') ? 'ada' : 'tidak'"
   ```
5. **Interaksi form** (isi email, klik submit) — widget Turnstile biasanya ter-render setelah interaksi/submit. Browser sungguhan menyelesaikannya otomatis.
6. **Verifikasi lanjut ke step berikutnya** → cek `tbp text` untuk konfirmasi (mis. "Kode verifikasi sudah dikirim").

**Penting:** Gunakan **email yang bisa Anda baca inbox-nya** (mis. akun IMAP yang Anda akses) saat registrasi, supaya OTP/kode verifikasi bisa dibaca. Jangan pakai email acak yang tak bisa diakses.

**Trik akun kedua (Gmail plus-addressing) — terverifikasi:** Untuk menguji IDOR lintas-akun atau membuat akun kedua ketika Anda hanya punya SATU email yang bisa diakses inbox-nya, daftar dengan **Gmail plus-addressing**: `nama@gmail.com` → `nama+tag@gmail.com`. Gmail menganggap `nama+tag@gmail.com` sebagai alamat berbeda (akun terpisah di situs target) tapi emailnya tetap masuk ke inbox `nama@gmail.com`. Kode verifikasi untuk `nama+tag@gmail.com` bisa dibaca dari inbox yang sama (sering di folder `[Gmail]/Spam`). Ini memungkinkan verifikasi IDOR lintas-akun tanpa butuh email kedua.

---

## 5. Referensi Lengkap

- Panduan implementasi kode siap pakai ada di `references/cdp-form-filler.md`.
- Panduan praktis `termux-browser-pilot` (setup, perintah, Turnstile bypass, troubleshooting) ada di `references/termux-browser-pilot.md`.

## Dukungan Termux (Android) — hasil uji nyata (2026-09)

Stack browser di Termux **terverifikasi terinstall**:

| Komponen | Status | Versi |
|---|---|---|
| `tbp` binary | ✅ | v0.1.0a1 (`which tbp` → `$PREFIX/bin/tbp`) |
| Firefox | ✅ | v155.0.1 (x11) |
| `xorg-server-xvfb` | ✅ | v21.1.16-3 |
| `xdotool` | ✅ | v3.20211022.1 |
| `openbox` | ✅ | v3.6.1-62 |

**Do & don't:**
- **Do** — gunakan `tbp` command (`navigate`, `click`, `screenshot`, `screenshot-element`, `annotate`, `text`, `iframe list`, `eval`) untuk automasi; semuanya tersedia via binary `tbp`.
- **Do** — `tbp screenshot-element SELECTOR` untuk screenshot area spesifik (mis. CAPTCHA) — berguna untuk solusi vision LLM.
- **Do** — prefer Firefox (lebih ringan & lolos Cloudflare via TLS fingerprint) daripada Chromium (~570–640MB).
- **Don't** — jangan `pip install termux-browser-pilot` (tidak di PyPI); pakai wrapper manual.
- **Don't** — browser teks (`lynx`/`w3m`/`links`) tidak bisa menembus Turnstile.
