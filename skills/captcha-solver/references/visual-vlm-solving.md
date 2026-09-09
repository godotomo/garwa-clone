# Visual CAPTCHA Solving via Vision LLM (screenshot → model multimodal)

Pendekatan utama di Garwa untuk CAPTCHA **visual kompleks** (OCR huruf terdistorsi, slider/puzzle, image grid, reCAPTCHA v2 image challenge, hCaptcha grid) yang tidak bisa ditangani auto-click / token injection biasa: **ambil screenshot area CAPTCHA, kirim ke model vision LLM, parse jawaban, lalu inject/submit.**

Kelebihan vs solver API berbayar & human task:
- **Tanpa biaya per-token eksternal** — memakai model vision yang sudah tersedia di Garwa.
- **Tanpa eskalasi manual** — selesai otomatis dalam satu pipeline.
- **Langsung di lingkungan lokal** (Termux/desktop) — tidak butuh layanan cloud pihak ketiga.

---

## 1. Prasyarat

- Browser sungguhan berjalan (untuk Termux: `termux-browser-pilot`; lihat skill `browser-automation`).
- Model **vision/multimodal** tersedia di konfigurasi LLM Garwa (mendukung input gambar).
- Untuk crop presisi, browser harus bisa ambil screenshot elemen (Playwright `element.screenshot()` / `tbp screenshot`).

---

## 2. Alur Umum (5 langkah)

```
[1] Screenshot CAPTCHA
        │
[2] Crop ke area CAPTCHA (opsional, hilangkan noise halaman)
        │
[3] Kirim gambar + prompt ke model vision
        │
[4] Parse jawaban (teks / koordinat klik / urutan sel)
        │
[5] Inject token / submit / klik koordinat
```

### Langkah 1 — Screenshot

Ambil screenshot **elemen CAPTCHA** (lebih presisi daripada seluruh halaman):

```python
# Playwright: screenshot elemen
captcha = page.locator('iframe[src*=challenges.cloudflare.com], [class*=captcha], [role=checkbox]')
captcha.screenshot(path='captcha.png')

# Seluruh viewport (fallback bila selector tidak ditemukan)
page.screenshot(path='captcha.png')
```

Di Termux via `tbp` (lihat skill browser-automation):
```bash
tbp screenshot captcha.png
```

### Langkah 2 — Crop (opsional)

Kalau screenshot berisi banyak noise halaman, crop ke area CAPTCHA dengan `Pillow`:

```python
from PIL import Image
img = Image.open('captcha.png')
# Koordinat bounding box area CAPTCHA (kiri, atas, kanan, bawah)
crop = img.crop((x1, y1, x2, y2))
crop.save('captcha_crop.png')
```

### Langkah 3 — Kirim ke model vision

Prompt harus **meminta format jawaban yang bisa di-parse**, bukan jawaban naratif. Sertakan petunjuk tipe CAPTCHA.

```text
Ini screenshot CAPTCHA. Jawab PERSIS dalam format yang diminta, tanpa teks lain.

- Kalau CAPTCHA teks/karakter (huruf terdistorsi): berikan hanya karakter yang terlihat, mis. "R7K2P".
- Kalau image grid (pilih gambar yang memenuhi syarat): berikan nomor/indeks sel yang benar, mis. "2,5,7".
- Kalau slider/puzzle: berikan jarak geser dalam piksel (perkiraan), mis. "145".
- Kalau reCAPTCHA/hCaptcha checkbox: jawab "CHECKBOX" saja.
```

### Langkah 4 — Parse jawaban

Normalisasi output model (hapus spasi, huruf kecil, ekstrak pola) sebelum dipakai:

```python
import re
ans = raw_answer.strip().lower()
if re.fullmatch(r'[a-z0-9]+', ans):        # CAPTCHA teks
    solution = ans
elif re.fullmatch(r'[\d, ]+', ans):        # image grid → list indeks
    solution = [int(x) for x in re.findall(r'\d+', ans)]
elif ans == 'checkbox':
    solution = 'CHECKBOX'
else:
    # jawaban tidak jelas → retry sekali atau fallback human task
    solution = None
```

### Langkah 5 — Inject / submit

Berdasarkan tipe jawaban:

```python
# Teks CAPTCHA → isi input lalu submit
if isinstance(solution, str) and solution != 'CHECKBOX':
    page.fill('input[name*=captcha], input[id*=captcha]', solution)
    page.click('button[type=submit]')
# Image grid → klik sel yang diminta
elif isinstance(solution, list):
    cells = page.locator('[class*=grid] [class*=cell], [class*=tile]')
    for idx in solution:
        cells.nth(idx).click()
# Checkbox → klik checkbox
else:
    page.click('iframe[src*=challenges.cloudflare.com] input[type=checkbox]')
```

---

## 3. Prompt per Tipe CAPTCHA (template siap pakai)

| Tipe | Prompt | Format jawaban |
|---|---|---|
| **Teks/karakter** | "Baca karakter pada CAPTCHA. Jawab hanya karakter, tanpa spasi." | `R7K2P` |
| **Image grid** | "Pilih sel yang berisi [objek]. Jawab nomor sel dipisah koma." | `2,5,7` |
| **Slider/puzzle** | "Perkirakan jarak geser slider ke posisi pas, dalam piksel." | `145` |
| **reCAPTCHA v2 checkbox** | "Apakah ini checkbox CAPTCHA? Jawab CHECKBOX jika ya." | `CHECKBOX` |
| **hCaptcha grid** | "Pilih gambar yang memenuhi syarat. Jawab indeks sel." | `0,3,6` |

---

## 4. Best Practices

- **Crop dulu** sebelum kirim ke model — gambar kecil & fokus jauh lebih akurat & hemat token vision.
- **Retry logic**: kalau jawaban tidak valid (parse gagal / submit ditolak), ambil screenshot baru (CAPTCHA biasanya refresh) dan coba lagi maksimal 2–3×.
- **Delay random** antar percobaan (1–3 detik) untuk menghindari pola bot.
- **Jangan kirim seluruh halaman** ke model vision — boros token dan menurunkan akurasi.
- **Etika**: hanya gunakan untuk tujuan yang diizinkan operator; bypass CAPTCHA berbayar melanggar ToS sebagian besar platform.

---

## 5. Fallback

Bila model vision tidak tersedia / gagal berulang:
1. **Solver API berbayar** — 2Captcha / CapSolver / AntiCaptcha (butuh API key & biaya per token).
2. **Human task** — tandai `human_captcha_required` dan eskalasi ke operator (jangan blokir pipeline selamanya).
