---
name: captcha-solver
description: Strategi & integrasi penanganan CAPTCHA (reCAPTCHA v2/v3, hCaptcha, Cloudflare Turnstile, image/slider CAPTCHA) untuk automasi registrasi dan perayapan web.
version: 1.0.0
category: security-automation
platforms: [linux, macos, windows, termux]
---

# captcha-solver

Skill penanganan dan menyelesaikan Tantangan CAPTCHA dan Anti-Bot Guard (Cloudflare Turnstile, reCAPTCHA v2/v3, hCaptcha, Slider, Image Grid).

---

## 0. Batasan Lingkungan (PENTING)

### Termux (Android)
Skill ini memerlukan browser sungguhan (Chromium/Firefox) untuk CAPTCHA interaktif. **Di Termux kini bisa menjalankan browser sungguhan** — Firefox/Chromium via `x11-repo`+`tur-repo` dan tool `termux-browser-pilot` (lihat skill `browser-automation`). Terverifikasi berhasil menembus Cloudflare Turnstile (9inference.cloud). Namun browser di Termux memakai IP perangkat asli (bukan datacenter IP), jadi Turnstile/datacenter-IP-block biasanya lolos.

**Solusi CAPTCHA visual kompleks (OCR huruf terdistorsi, slider, puzzle 3D, image grid):** ambil **screenshot** area CAPTCHA lalu kirim ke **model vision LLM** (multimodal) untuk diselesaikan — ini jalur utama di Garwa karena model vision sudah tersedia, tanpa solver API berbayar atau eskalasi manual. Lihat `references/visual-vlm-solving.md` untuk alur lengkap (screenshot → crop → prompt → parse jawaban → inject/submit). Fallback bila model vision tidak tersedia: solver API (2Captcha/CapSolver) atau human task (tandai `human_captcha_required` dan eskalasi ke operator). Catatan etika: bypass CAPTCHA berbayar melanggar ToS sebagian besar platform; gunakan hanya untuk tujuan yang diizinkan operator.

---

## 1. Taksonomi CAPTCHA & Anti-Bot Protection

| Tipe CAPTCHA | Tingkat Kesulitan | Strategi Penanganan Utama |
|---|---|---|
| **Cloudflare Turnstile** | Low / Medium | Cloud Browser / Residential CDP / Auto-click iframe box |
| **reCAPTCHA v2 Checkbox** | Medium | DOM Token Injection via Solver API / Behavioral click |
| **reCAPTCHA v3 (Score)** | Invisible | Human-like browser interaction / Residential IP / Headless false flag removal |
| **hCaptcha** | Medium / High | Solver API Injection (h-captcha-response) / Audio fallback |
| **Slider / Puzzle** | Medium | Drag & Drop Distance Calculation via Canvas/DOM Analysis |

---

## 2. Strategi Penanganan (Handling Strategy)

1. **Passive Avoidance (Pencegahan Utama)**:
   - Gunakan plugin stealth (mis. playwright-stealth / DrissionPage).
   - Gunakan profil browser sungguhan via CDP (--remote-debugging-port=9222) dengan cookies aktif.
   - Hindari User-Agent Headless Chrome generik (HeadlessChrome/...).

2. **Managed / Soft CAPTCHA Auto-Interaction**:
   - Untuk Cloudflare Turnstile & reCAPTCHA Checkbox:
     Cari iframe iframe[src*=turnstile] atau iframe[title*=recaptcha], lalu simulasi click pada koordinat checkbox setelah delay 1.5 - 3.0 detik.

3. **Active Solving & Token Injection**:
   - Jika halaman memblokir dan mensyaratkan token solusi:
     - Dapatkan sitekey dari elemen DOM (data-sitekey).
     - Minta token balasan dari solver (API 2Captcha/CapSolver/AntiCaptcha atau lokal OCR model).
     - Inject token ke input tersembunyi (g-recaptcha-response atau h-captcha-response) dan panggil callback function JS jika disyaratkan:
       ```javascript
       document.getElementById('g-recaptcha-response').value = 'TOKEN_SOLUSI';
       // Panggil callback internal reCAPTCHA jika perlu
       ```

4. **Human Task Fallback**:
   - Jika CAPTCHA memerlukan interaksi visual kompleks (mis. OCR huruf terdistorsi parah atau puzzle 3D) dan solver API tidak dikonfigurasi, beri penanda human_captcha_required dan teruskan instruksi ke operator.

---

## 3. Referensi Lengkap

- Detail implementasi penanganan Turnstile, reCAPTCHA, dan hCaptcha ada di `references/captcha-handling.md`.
- **Solusi CAPTCHA visual kompleks via model vision LLM** (screenshot → crop → prompt → parse → inject) ada di `references/visual-vlm-solving.md`.

## Dukungan Termux (Android) — hasil uji nyata (2026-09)

Stack browser di Termux **terverifikasi terinstall** (lihat skill `browser-automation`): `tbp` v0.1.0a1, Firefox v155.0.1, `xorg-server-xvfb`, `xdotool`, `openbox`.

**Do & don't:**
- **Do** — gunakan `tbp` command (`screenshot`, `screenshot-element`, `annotate`, `click`, `iframe list`) untuk menangani CAPTCHA interaktif di Termux; browser sungguhan menembus Turnstile otomatis.
- **Do** — untuk CAPTCHA visual kompleks (OCR huruf, slider, image grid): `tbp screenshot-element SELECTOR` → kirim ke model vision LLM (lihat `references/visual-vlm-solving.md`).
- **Don't** — jangan andalkan browser teks (`lynx`/`w3m`/`links`) — tidak bisa menembus Turnstile (tanpa JS penuh).
- **Don't** — solver API berbayar (2Captcha/CapSolver) hanya fallback bila model vision tidak tersedia.