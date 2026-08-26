---
name: docx
description: "Dipakai kapan pun task melibatkan file Word (.docx/.dotx): membuat dokumen baru (laporan, surat, memo, 
kontrak), mengedit dokumen yang sudah ada, mengisi template, menambah/mengganti gambar, atau membaca isi file .docx. 
JANGAN dipakai untuk PDF, spreadsheet, atau slide presentasi — itu skill terpisah."
---

# DOCX — pembuatan, edit, dan analisis

## Pilih pendekatan sesuai task

| Task | Pustaka / cara |
|---|---|
| **Buat** dokumen baru | Python `python-docx` (utama) |
| **Edit** dokumen yang sudah ada, ganti sedikit teks | `python-docx` dibuka lalu disimpan lagi — HATI-HATI, lihat 
"Gotcha edit" |
| **Edit presisi tanpa merusak formatting kompleks** | unzip `.docx` → edit XML `word/document.xml` langsung → zip 
lagi |
| **Baca isi cepat** | `pandoc -t markdown file.docx` atau `python-docx` untuk baca paragraf/tabel terstruktur |
| **Convert dari .doc lama** | `soffice --headless --convert-to docx file.doc` dulu, baru diproses |

## JANGAN pakai ini

- **Jangan** pakai `docx2txt` untuk ekstraksi kalau butuh struktur (heading, tabel) — hilang semua. Pakai `python-docx` 
atau `pandoc`.
- **Jangan** pakai library `python-docx-template`/Jinja kalau template-nya tidak disiapkan user sendiri — kompleksitas 
ekstra yang jarang perlu.
- **Jangan** menulis dokumen panjang sebagai satu string lalu `document.add_paragraph(long_string)` yang berisi `\n` — 
python-docx tidak mengubah `\n` jadi paragraf baru, hasilnya satu paragraf raksasa. Setiap paragraf = satu pemanggilan 
`add_paragraph()`.

## Gotcha `python-docx` saat membuat dokumen

- **Ukuran halaman default adalah Letter di sebagian install, A4 di lainnya** — jangan andalkan default. Set eksplisit:
  ```python
  from docx.shared import Inches
  section = document.sections[0]
  section.page_width = Inches(8.27)   # A4
  section.page_height = Inches(11.69)
  # atau Letter: Inches(8.5) x Inches(11)
  ```
- **Bullet/numbered list**: jangan sisipkan karakter `•` manual. Pakai style bawaan:
  ```python
  document.add_paragraph("Item pertama", style="List Bullet")
  document.add_paragraph("Item bernomor", style="List Number")
  ```
- **Heading untuk Table of Contents**: TOC otomatis di Word hanya membaca style `Heading 1`/`Heading 2` dst. Style 
heading custom (font besar tapi bukan style "Heading N") tidak akan muncul di TOC.
- **python-docx tidak bisa generate field TOC yang auto-update.** Cara paling andal: sisipkan field code TOC lewat XML 
mentah, lalu beri instruksi ke user untuk klik "Update Field" saat pertama buka — atau lebih aman, render manual daftar 
heading sebagai teks statis kalau dokumennya tidak akan diedit lagi.
- **Lebar kolom tabel**: set lebar di level cell, bukan cuma `table.columns[i].width` — Word sering mengabaikan lebar 
kolom kalau cell-nya tidak diberi lebar juga.
  ```python
  from docx.shared import Cm
  for row in table.rows:
      row.cells[0].width = Cm(4)
      row.cells[1].width = Cm(10)
  ```
- **Shading tabel (warna latar cell)**: `python-docx` tidak punya API bawaan — perlu manipulasi XML langsung lewat 
`oxml`. Jangan pakai warna solid gelap tanpa mengecek kontras teksnya.
- **Gambar**: `document.add_picture(path, width=Inches(6))` — SELALU beri `width` eksplisit, kalau tidak gambar 
dimasukkan di resolusi native (sering terlalu besar, merusak layout).
- **Page break**: `document.add_page_break()` sebagai elemen sendiri, atau `run.add_break(WD_BREAK.PAGE)` di tengah run 
— jangan pakai banyak paragraf kosong untuk "mendorong" halaman.
- **Header/Footer**: `section.header.paragraphs[0].text = "..."` — ingat tiap section punya header/footer sendiri; 
kalau dokumen multi-section, atur `section.header.is_linked_to_previous = False` dulu sebelum override.

## Gotcha edit dokumen existing

- **Run splitting**: Word sering memecah satu frasa yang terlihat utuh jadi beberapa `<w:r>` (run) berbeda karena 
riwayat edit/spell-check. Kalau `find & replace` teks via `python-docx` gagal menemukan teks yang jelas-jelas ada, 
kemungkinan besar teks itu terpecah lintas run — perlu digabung dulu (iterasi semua run di paragraf, gabung teksnya, 
replace, lalu tulis ulang run pertama dan kosongkan run sisanya) atau turun ke edit XML mentah.
- **Overwrite `paragraph.text = "..."` menghapus semua formatting** run di paragraf itu (bold/italic/warna hilang, jadi 
satu run polos). Kalau formatting harus dipertahankan, edit `run.text` pada run yang tepat, jangan `paragraph.text`.
- **File `.docx` dari sumber luar/tidak dipercaya**: unzip dan cek dulu apakah ada symlink aneh di dalamnya sebelum 
diproses lebih lanjut — hindari path traversal.

## Wajib: verifikasi visual sebelum dianggap selesai

Jangan pernah menganggap dokumen "jadi" hanya karena skrip berhasil jalan tanpa error. Render ke gambar dan benar-benar 
dilihat:

```bash
soffice --headless --convert-to pdf output.docx
pdftoppm -jpeg -r 100 output.pdf page
# lalu lihat page-1.jpg, page-2.jpg, dst — cek layout, tabel tidak terpotong,
# teks tidak overflow keluar margin, gambar tidak pecah/blur
```

## Tema & layout untuk dokumen "profesional"

- **Font**: satu font untuk body (Calibri/Arial/Times New Roman), maksimal satu font aksen untuk heading. Jangan campur 
lebih dari 2 font dalam satu dokumen.
- **Margin konsisten**: 1 inch (2.54 cm) semua sisi kecuali diminta lain.
- **Hierarki heading jelas**: `Heading 1` untuk judul bagian besar, `Heading 2` untuk sub-bagian — jangan lompat level 
(Heading 1 langsung ke Heading 3).
- **Spasi**: `space_after` konsisten antar paragraf (mis. 6-8pt), jangan pakai paragraf kosong sebagai jarak.
- **Tabel**: header row diberi bold + shading tipis (bukan warna solid gelap), border tipis konsisten, jangan tabel 
tanpa border sama sekali untuk data numerik.
- **Warna korporat**: kalau user tidak spesifikasi, pakai palet netral (navy/abu gelap untuk heading, hitam untuk body) 
— hindari warna terang mencolok di dokumen formal.

## Dependensi

`pip install python-docx` · `pandoc` (baca cepat) · `soffice`/LibreOffice (convert & verifikasi) · `poppler-utils` 
(`pdftoppm`, untuk render halaman jadi gambar).
