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