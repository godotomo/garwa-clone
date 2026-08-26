---
name: pptx
description: "Dipakai kapan pun task melibatkan slide/presentasi (.pptx/.potx): membuat deck baru, mengedit deck yang 
ada, mengisi template perusahaan, menambah chart/gambar, atau membaca isi slide. JANGAN dipakai untuk dokumen Word atau 
PDF."
---

# PPTX — pembuatan, edit, dan analisis

## Pilih pendekatan sesuai task

| Task | Pustaka / cara |
|---|---|
| **Buat** deck baru dari nol, desain custom | `pptxgenjs` (Node) — kontrol layout/warna paling fleksibel |
| **Buat** deck sederhana, stack Python saja | `python-pptx` |
| **Isi ulang template** perusahaan (.potx / .pptx existing) | `python-pptx` dibuka dari file template, isi placeholder 
yang ada — JANGAN bikin slide dari nol lalu styling manual |
| **Baca isi slide cepat** | `python-pptx` (iterasi `slide.shapes`, ambil `.text_frame.text`) |
| **Convert dari .ppt lama** | `soffice --headless --convert-to pptx file.ppt` dulu |

## JANGAN pakai ini

- **Jangan generate chart sebagai gambar statis (matplotlib lalu di-insert)** kalau PowerPoint punya native chart type 
yang sesuai (bar/line/pie/scatter) — chart gambar tidak bisa diedit datanya di PowerPoint dan terlihat kurang 
profesional. Pakai chart native (`pptxgenjs` `addChart()` atau `python-pptx` `chart_data` + `add_chart()`).
- **Jangan** taruh teks lewat text box mengambang di atas gambar/shape kalau ada placeholder layout yang seharusnya 
dipakai — merusak konsistensi kalau user ganti tema/master slide.
- **Jangan** pakai `python-pptx` untuk menduplikasi slide kompleks (dengan chart/SmartArt) — `python-pptx` tidak punya 
cara resmi men-duplicate slide berikut semua asset-nya; kalau butuh duplikasi begini, lebih aman edit XML langsung 
(`ppt/slides/slideN.xml` + registrasi relationship) daripada memaksakan API tingkat tinggi.

## Gotcha `pptxgenjs` (kalau pakai jalur Node — direkomendasikan untuk desain custom)

- **Set `pres.layout` SEBELUM `addSlide()`.** Default canvas 10" × 5.625" (16:9 "kecil"), bukan 13.3" — kalau lupa, 
elemen yang dikoordinatkan untuk layar lebar akan terpotong/salah posisi (dan tidak error, cuma diam-diam salah 
tempat).
- **Warna heks TANPA `#` dan tanpa alpha 8-digit** — `color: "1F4E79"`, bukan `"#1F4E79"` atau `"1F4E79FF"`. 
Transparansi pakai properti terpisah (`transparency` untuk fill, `opacity` untuk shadow), bukan digabung ke hex.
- **Jangan reuse satu object opsi (`shadow`, dll) untuk beberapa `addShape`/`addText`** — pptxgenjs memutasi object itu 
saat konversi ke satuan internal (EMU), jadi pemanggilan kedua dengan object yang sama bisa dapat nilai yang sudah 
"termutasi". Buat object baru tiap panggilan.
- **List/bullet**: `bullet: true` per item, bukan karakter `•` manual (akan jadi bullet dobel). Set `breakLine: true` 
di semua item kecuali item terakhir.
- **Satu `new pptxgen()` per file output** — jangan reuse instance untuk generate banyak deck.
- **Speaker notes**: `slide.addNotes("...")`, jangan ditaruh sebagai text box biasa di slide.

## Gotcha `python-pptx` (kalau pakai jalur Python)

- **`text_frame.text = "..."` menghapus formatting** — sama seperti python-docx, ini collapse jadi satu run polos. 
Kalau formatting penting, edit `run.text` pada run spesifik.
- **Menambah slide baru = `slide = prs.slides.add_slide(layout)`** — hanya bisa pakai layout yang sudah ada di master, 
tidak bisa "duplicate slide existing" secara native.
- **Placeholder index berbeda-beda tiap layout** — jangan asumsikan `placeholders[1]` selalu subtitle; cek 
`shape.placeholder_format.idx` dan `.type` dulu sebelum menulis ke situ, terutama saat mengisi template pihak lain.
- **Gambar SVG/EMF** (banyak dipakai di template korporat untuk ikon) tidak bisa langsung di-`add_picture()` — perlu 
dikonversi ke PNG dulu (mis. lewat `cairosvg` atau `soffice`).

## Wajib: cek visual sebelum dianggap selesai

```bash
soffice --headless --convert-to pdf deck.pptx
pdftoppm -jpeg -r 100 deck.pdf slide
# lihat tiap slide-N.jpg — cek teks tidak overflow keluar text box,
# elemen tidak saling tumpuk, chart terbaca, warna kontras cukup
```
Kalau deck > 6-8 slide, generate satu grid thumbnail (montage semua slide jadi satu gambar) supaya QA lebih cepat 
daripada buka satu-satu.

## Tema & layout — jangan bikin slide membosankan

- **Pilih 1 palet warna yang kontekstual ke topik**, bukan palet generik biru-korporat untuk semua topik. Satu warna 
dominan (60-70% bobot visual), 1-2 warna pendukung, 1 warna aksen tajam untuk highlight/CTA.
- **Kontras dark/light**: slide judul & penutup boleh background gelap untuk kesan "premium", slide isi background 
terang untuk keterbacaan — atau konsisten gelap semua kalau temanya memang premium/dark theme.
- **Satu motif visual yang diulang** tiap slide (bentuk frame gambar, style ikon) — jangan tiap slide punya gaya 
berbeda-beda.
- **Hindari** hanya bullet list putih polos di semua slide — variasikan: slide dengan big number/statistik, slide 
perbandingan 2 kolom, slide dengan gambar full-bleed + caption, slide chart.
- **Konsistensi tipografi**: satu font untuk heading, satu untuk body, ukuran heading tidak berubah-ubah antar slide 
sejenis.
- **Margin aman**: jangan taruh elemen penting terlalu dekat tepi slide (risiko terpotong saat proyeksi/print) — beri 
padding minimal 0.4"-0.5" dari tepi.

## Dependensi

`npm install pptxgenjs` (jalur Node, direkomendasikan untuk desain) · `pip install python-pptx` (jalur Python) · 
`soffice`/LibreOffice (convert & verifikasi) · `poppler-utils` (render ke gambar).
