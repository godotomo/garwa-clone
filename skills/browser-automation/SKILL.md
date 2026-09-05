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
1. Hubungkan modul IMAP (`jobbot.imap_inbox`) untuk membaca email terbaru.
2. Ekstrak OTP numerik atau URL verifikasi menggunakan regex:
   ```python
   import re
   otp_match = re.search(r'\b\d{6}\b', email_body)
   link_match = re.search(r'https?://[^\s<>"']+/(?:verify|activate|confirm)[^\s<>"']*', email_body)
   ```
3. Lanjutkan navigasi browser ke link verifikasi atau masukkan OTP ke input form.

---

## 4. Referensi Lengkap

- Panduan implementasi kode siap pakai ada di `references/cdp-form-filler.md`.
