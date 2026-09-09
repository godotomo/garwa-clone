---
name: pdf
description: "Dipakai kapan pun task melibatkan file PDF: membuat PDF baru (laporan, invoice, sertifikat), 
menggabung/memisah/rotate halaman, mengisi form PDF, ekstrak teks/tabel/gambar, OCR PDF hasil scan, atau 
watermark/enkripsi. JANGAN dipakai untuk .docx/.pptx/.xlsx mentah — convert dulu kalau perlu jadi PDF."
---

# PDF — pembuatan, edit, dan analisis

## Pilih pendekatan sesuai task

| Task | Pustaka / cara |
|---|---|
| **Buat PDF ber-layout kompleks** (laporan, tema, tabel, gambar) | Tulis HTML+CSS lalu convert dengan `weasyprint` — 
jauh lebih mudah dikontrol layout/temanya daripada canvas API |
| **Buat PDF sederhana** (teks + tabel dasar, tanpa perlu HTML) | `reportlab` (Platypus: `SimpleDocTemplate` + 
`Paragraph`/`Table`) |
| **Gabung/pisah/rotate/enkripsi** file existing | `pypdf` |
| **Ekstrak teks dengan layout terjaga** | `pdfplumber` |
| **Ekstrak tabel** | `pdfplumber` (`page.extract_tables()`) |
| **PDF hasil scan (gambar, bukan teks asli)** | `pytesseract` + `pdf2image` (OCR) |
| **Isi form PDF (AcroForm)** | `pypdf` (`writer.update_page_form_field_values`) — cek dulu field name-nya pakai 
`reader.get_fields()` |

## JANGAN pakai ini

- **Jangan pakai `reportlab` canvas API mentah untuk dokumen panjang/berlapis** (banyak section, tabel, gambar campur) 
— mengatur posisi `x, y` manual untuk tiap elemen sangat rapuh, sedikit perubahan konten menggeser semua yang di 
bawahnya secara manual. Untuk itu pakai `weasyprint` (HTML/CSS, mengalir otomatis) atau `reportlab.platypus` (flowables 
yang otomatis alur/page-break).
- **Jangan gunakan karakter Unicode subscript/superscript** (₀₁₂ , ⁰¹²) langsung sebagai teks di `reportlab` — font 
bawaannya sering tidak punya glyph itu, hasilnya kotak hitam solid. Pakai tag `<sub>`/`<super>` di `Paragraph` 
(reportlab), atau `<sub>`/`<sup>` HTML biasa kalau lewat `weasyprint`.
- **Jangan proses PDF hasil scan dengan `pypdf`/`pdfplumber` untuk ekstraksi teks** — PDF scan itu isinya gambar, bukan 
teks; kedua library itu akan mengembalikan string kosong. Harus lewat OCR dulu.
- **Jangan asumsikan tabel hasil `pdfplumber.extract_tables()` selalu rapi** — PDF dengan garis tabel tidak konsisten 
(atau tanpa garis sama sekali, hanya spasi) sering menghasilkan baris kosong/kolom salah. Selalu print hasilnya dan cek 
manual sebelum dipakai lebih lanjut, jangan langsung `pd.DataFrame(table)`.

## Gotcha `pypdf`

- **Metadata (`reader.metadata.title`, dll) bisa `None`** kalau file tidak pernah diisi metadata-nya — selalu cek 
`None` sebelum dipakai, jangan asumsikan selalu ada string.
- **Merge/gabung**: `writer.add_page(page)` per halaman dari tiap reader — halaman dengan ukuran berbeda-beda antar 
file sumber tetap dipertahankan ukurannya masing-masing (tidak otomatis diseragamkan); kalau user minta ukuran seragam, 
resize manual dulu (`page.scale_to()`).
- **Watermark**: `page.merge_page(watermark_page)` menimpa watermark DI ATAS konten asli. Kalau watermark harus di 
belakang konten (bukan menutupi), watermark harus di-merge duluan ke halaman kosong, baru konten asli di-merge di 
atasnya — urutan `merge_page` menentukan layer mana di atas.

## Gotcha `weasyprint` (rekomendasi utama untuk PDF berlayout/tema)

- **Font custom**: daftarkan lewat `@font-face` di CSS dengan path lokal ke file font, jangan andalkan nama font sistem 
— hasil di sandbox/server sering tidak punya font yang sama dengan mesin development.
- **Page break**: kontrol lewat CSS `page-break-before`/`break-before: page` pada elemen, bukan menyisipkan halaman 
kosong manual di HTML.
- **Ukuran halaman & margin**: didefinisikan lewat `@page { size: A4; margin: 2cm; }` di CSS — kalau tidak diset, 
default browser-engine-nya kadang berbeda dari yang diharapkan.
- **Gambar**: pakai path absolut atau `file://` URI yang valid — path relatif sering gagal resolve tergantung working 
directory saat script dijalankan.

## Wajib: verifikasi sebelum dianggap selesai

```bash
pdftoppm -jpeg -r 100 output.pdf page
# lihat page-1.jpg, page-2.jpg, dst — cek margin, tabel tidak terpotong,
# font ter-render (bukan kotak/tofu), page break masuk akal
```
Untuk operasi non-visual (merge/split/encrypt), cek `len(reader.pages)` hasil akhir sesuai ekspektasi, dan buka ulang 
file hasil dengan `pypdf.PdfReader` untuk pastikan file tidak korup (tidak raise exception saat dibaca).

## Tema & layout (untuk PDF hasil generate, bukan ekstraksi)

- **Konsisten dengan skill docx**: font, hierarki heading, margin, dan warna aksen sebaiknya mengikuti prinsip yang 
sama seperti di `skills/docx/SKILL.md` — dokumen PDF laporan sering punya "saudara" versi Word, jagalah konsistensi 
visual.
- **Nomor halaman & header/footer** lewat CSS `@page` counter (`content: counter(page)`) di jalur `weasyprint`, atau 
`canvas.drawString` di posisi tetap tiap page kalau pakai `reportlab`.
- **Tabel data panjang**: pastikan header tabel berulang di tiap halaman baru (CSS `thead { display: 
table-header-group; }` di `weasyprint`) — jangan biarkan tabel terpotong tanpa konteks kolom di halaman berikutnya.

## Dependensi

`pip install pypdf pdfplumber reportlab weasyprint pytesseract pdf2image pandas` · `poppler-utils` (`pdftoppm`, 
`pdftotext`) · Tesseract OCR (untuk `pytesseract`) · `qpdf` (opsional, operasi command-line cepat: 
merge/split/rotate/decrypt).

## Dukungan Termux (Android) — garwa ringan & robust

Skill pdf berjalan penuh di Termux. **Inti (buat/gabung/split/enkripsi/ekstrak teks&tabel) hanya butuh pustaka Python murni** (`reportlab`, `pypdf`, `pdfplumber`) — ringan, tanpa tool eksternal. Tool sistem (`poppler-utils`, `tesseract`, `qpdf`, `weasyprint`) hanya untuk kasus spesifik dan **opsional**.

```bash
# 0. PENTING — perbaiki pip dulu bila error "No module named 'pip._internal.operations.install.wheel'".
#    Itu BUKAN pip rusak permanen: akar masalahnya libexpat terlalu lama (2.7.x) yang tidak punya
#    simbol XML_SetHashSalt16Bytes yang dibutuhkan pyexpat Python 3.14. Upgrade libexpat:
pkg install -y libexpat        # upgrade ke 2.8.4 → pyexpat OK → pip install bekerja (TERUJI 2026-09)
# 1. Wajib — pustaka inti (pip; wheel murni, TERUJI berhasil diinstall)
pip3 install --break-system-packages reportlab pypdf pdfplumber
# 2. Opsional — render halaman jadi gambar & ekstrak teks: pakai python-pymupdf (PyMuPDF/fitz),
#    TERSEDIA sebagai paket Termux (lebih ringan & tanpa poppler):
pkg install -y python-pymupdf
# 3. Opsional — ekstrak teks via CLI & render: poppler TERSEDIA di repo Termux
pkg install -y poppler
# 4. Opsional — OCR PDF scan: tesseract TERSEDIA di repo Termux
pkg install -y tesseract && pip3 install --break-system-packages pytesseract pdf2image
# 5. Opsional — operasi CLI cepat merge/split: qpdf TERSEDIA di repo Termux
pkg install -y qpdf
# 6. Opsional — PDF berlayout kompleks via HTML/CSS: weasyprint butuh libs sistem pango/cairo.
#    pango & cairo tersedia di Termux; install lib lalu pip. (Belum teruji penuh di Termux — fallback
#    utama tetap reportlab.)
pkg install -y pango && pip3 install --break-system-packages weasyprint
```

**Fallback ringan (tanpa weasyprint/poppler/tesseract/qpdf):**
- **Buat PDF berlayout** tanpa `weasyprint`: pakai `reportlab.platypus` (`SimpleDocTemplate` + `Paragraph`/`Table`) — sudah cukup untuk laporan, tabel, gambar. Kurangi ketergantungan pada HTML/CSS.
- **Render halaman jadi gambar** tanpa `poppler-utils` (`pdftoppm`): gunakan `python-pymupdf` (paket Termux, `fitz`) atau `pdf2image` bila poppler ada. Paling ringan: verifikasi struktural dengan `pypdf.PdfReader` — cek `len(reader.pages)` + tidak raise exception (buka ulang hasil yang di-generate).
- **OCR** tanpa `tesseract`: untuk PDF scan, beri tahu user bahwa OCR butuh `tesseract` (paket Termux) — atau gunakan `easyocr` (murni Python, tapi lebih berat & butuh torch). Untuk teks digital (bukan scan), `pdfplumber`/`pypdf` sudah cukup.
- **Merge/split cepat** tanpa `qpdf`: `pypdf` (`PdfWriter.add_page`) sudah menangani merge/split/rotate/enkripsi — qpdf hanya alternatif CLI yang lebih cepat untuk file besar.

> **Catatan pip di Termux (TERUJI):** `reportlab`, `pypdf`, `pdfplumber` adalah wheel murni — `pip3 install --break-system-packages` langsung jalan SETELAH `libexpat` di-upgrade (lihat langkah 0). Kalau muncul error `install_wheel`, JANGAN asumsikan pip rusak — upgrade `libexpat` dulu. Gunakan `--break-system-packages` karena Termux memakai sistem Python.
