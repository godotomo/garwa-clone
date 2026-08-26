---
name: xlsx
description: "Dipakai kapan pun task melibatkan spreadsheet (.xlsx/.xlsm/.csv): membuat workbook baru dengan 
formula/formatting, mengedit spreadsheet yang ada, membersihkan data tabular berantakan, atau membaca isi spreadsheet. 
JANGAN dipakai kalau deliverable akhirnya Word/PDF/slide meski datanya tabular."
---

# XLSX — pembuatan, edit, dan analisis

## Pilih pendekatan sesuai task

| Task | Pustaka / cara |
|---|---|
| **Buat/edit** dengan formula & formatting | `openpyxl` |
| **Baca/tulis data massal** (tanpa peduli formula/style) | `pandas` (`read_excel` / `to_excel`) |
| **Lihat isi cepat** | `openpyxl` iterasi cell, atau `pandas.read_excel` lalu `.head()` |
| **Bersihkan CSV/data berantakan** | `pandas` (baca dengan `header=None` dulu kalau header tidak di baris pertama, 
baru dirapikan) |

## JANGAN pakai ini

- **Jangan tulis hasil hitungan Python langsung sebagai angka statis** kalau sel itu seharusnya formula (mis. total 
kolom). Tulis `sheet["B10"] = "=SUM(B2:B9)"`, bukan `sheet["B10"] = 45000`. Kalau input berubah, angka statis jadi 
salah dan tidak ada yang sadar.
- **Jangan pakai `pandas.to_excel` untuk workbook yang butuh formula/formatting kompleks** — pandas hanya menulis 
nilai, tidak ada cara natural untuk menulis formula atau styling per-cell. Pakai `openpyxl` untuk kasus itu.
- **Jangan pakai fungsi Excel generasi baru tanpa dicek dulu apakah dibuka lewat Excel asli atau lewat 
LibreOffice/online viewer** — `XLOOKUP`, `FILTER`, `UNIQUE`, `SORT`, `SEQUENCE` adalah *dynamic array function* yang 
butuh metadata spill; kalau ditulis lewat `openpyxl` (bukan diketik langsung di Excel), metadata spill itu tidak ada, 
sehingga hanya sel kiri-atas yang dapat nilai saat file dibuka software lain. Untuk kompatibilitas maksimal, pakai 
`INDEX`/`MATCH` sebagai pengganti `XLOOKUP`.

## Gotcha `openpyxl`

- **Formula yang ditulis `openpyxl` TIDAK punya cached value** — sampai file dibuka & dihitung ulang oleh aplikasi 
spreadsheet asli, siapa pun yang membaca file itu secara programatik (`data_only=True`, `pandas.read_excel`, banyak 
previewer) akan melihat sel berisi `None`, bukan hasil hitungannya. Kalau file ini akan langsung dibaca lagi secara 
programatik (bukan dibuka manual di Excel), **wajib** dipaksa recalc dulu:
  ```bash
  soffice --headless --convert-to xlsx --outdir recalced/ output.xlsx
  # atau, kalau LibreOffice tersedia via UNO API, panggil recalculate() lewat macro
  ```
  Verifikasi hasilnya dengan membuka ulang pakai `load_workbook(path, data_only=True)` dan cek sel-sel kunci 
benar-benar berisi angka, bukan `None`.
- **Membaca formula DAN nilai butuh dua kali `load_workbook`** — sekali default (dapat string formula, bukan hasil), 
sekali dengan `data_only=True` (dapat cached value, formula-nya hilang dari view). Satu load tidak bisa dapat keduanya 
sekaligus.
- **`data_only=True` itu destructive kalau di-save ulang** — kalau workbook dibuka dengan `data_only=True` lalu 
disimpan lagi, semua formula permanen berubah jadi nilai statis. Jangan pernah save workbook yang dibuka dengan mode 
ini.
- **Merged cells**: hanya sel kiri-atas dari range yang bisa ditulis; sel lain di range itu adalah `MergedCell` yang 
read-only — tulis ke situ akan error.
- **File `.xlsm` kehilangan macro-nya** kecuali dibuka dengan `load_workbook(path, keep_vba=True)`.
- **Nama sheet yang mengandung spasi** harus dikutip di formula cross-sheet: `='Data Bulanan'!B5`, bukan `=Data 
Bulanan!B5` (yang terakhir invalid).

## Format angka & warna — konvensi umum spreadsheet finansial

Kalau user tidak minta gaya lain:

- **Warna teks**: biru untuk angka input manual/asumsi, hitam untuk formula, hijau untuk link ke sheet lain dalam file 
yang sama — ini konvensi umum di dunia finance supaya orang lain langsung tahu mana yang boleh diubah.
- **Format angka**: mata uang `#,##0` dengan satuan disebut di header kolom (`Pendapatan (juta Rp)`), bukan diulang di 
tiap sel. Negatif dalam kurung `(#,##0)`. Persentase disimpan sebagai pecahan (`0.15`, format `0.0%`) — bukan `15` 
(akan tampil `1500%`).
- **Header**: bold + freeze pane baris pertama (`sheet.freeze_panes = "A2"`) untuk tabel panjang.

## Wajib: verifikasi sebelum dianggap selesai

1. Kalau ada formula: recalc dulu (lihat gotcha di atas), lalu buka dengan `data_only=True` dan pastikan tidak ada sel 
`#REF!`, `#VALUE!`, `#NAME?`, atau `None` yang seharusnya berisi angka.
2. Cek 2-3 formula manual (hitung sendiri, bandingkan) sebelum menyimpulkan seluruh grid formula benar — file yang 
"tidak error" belum tentu angkanya benar (mis. range formula off-by-one).

## Dependensi

`pip install openpyxl pandas` · `soffice`/LibreOffice (untuk memaksa recalculation formula).
