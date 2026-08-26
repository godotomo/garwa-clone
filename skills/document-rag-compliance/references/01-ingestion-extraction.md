# Ingestion & Ekstraksi Dokumen

## Langkah 1: Inventarisasi dulu
Sebelum ekstraksi, `view`/`ls` direktori tempat dokumen berada (biasanya working directory atau folder upload yang ditunjuk user). Untuk tiap file catat: nama, tipe, ukuran perkiraan (jumlah halaman/baris/slide), dan status (sudah ada di context vs perlu diekstrak).

**Cek dulu apakah file sudah ada di context** (teks/gambar sudah terlihat langsung di percakapan) — kalau ya, tidak perlu tool tambahan untuk file itu. Kalau hanya path yang tersedia (`uploaded_files` block), lanjut ke skill `file-reading` sebagai router.

## Langkah 2: Ekstraksi per tipe file — gunakan skill yang sudah tersedia, JANGAN reinvent

| Tipe file | Skill/tool wajib dibaca dulu | Catatan |
|---|---|---|
| `.pdf` (text-based) | skill `pdf` (SKILL.md) | Ekstrak per halaman, simpan nomor halaman untuk sitasi |
| `.pdf` (hasil scan/gambar) | skill `pdf` (SKILL.md) — bagian OCR | WAJIB OCR, jangan asumsikan halaman kosong = tidak ada isi |
| `.docx` / `.dotx` | skill `docx` (SKILL.md) | Simpan struktur heading untuk sitasi per bagian, termasuk komentar/tracked changes kalau relevan untuk compliance (mis. redline kontrak) |
| `.xlsx` / `.xlsm` / `.csv` | skill `xlsx` (SKILL.md) | Untuk data tabular (mis. daftar aset, log transaksi, register risiko) |
| `.pptx` | skill `pptx` (SKILL.md) | Simpan nomor slide untuk sitasi |
| Gambar (`.png/.jpg`) berisi teks | Lihat langsung (sudah bisa dibaca visual oleh model) atau OCR via bash kalau volume besar | Untuk dokumen scan banyak halaman berbentuk gambar |
| Arsip `.zip` berisi banyak dokumen | Ekstrak dulu via `bash`, lalu proses tiap file sesuai tipenya | Jangan proses zip sebagai teks mentah |

## Langkah 3: Normalisasi jadi satu struktur data seragam
Setelah ekstraksi, satukan semua dokumen ke satu struktur record per "unit sitasi" (halaman/paragraf/klausul/slide) supaya retrieval & sitasi konsisten lintas format file. Simpan sebagai file JSON/JSONL sementara di folder scratchpad lokal (mis. `./.scratch/`), contoh struktur per unit:

```json
{
  "doc_id": "kontrak_vendor_A.pdf",
  "unit_type": "page",
  "unit_ref": "hal. 4",
  "text": "isi teks unit ini...",
  "doc_type": "kontrak",
  "extra": {"section_heading": "Pasal 7 - Kerahasiaan"}
}
```

Field `unit_ref` inilah yang nanti dipakai untuk sitasi di jawaban — **selalu tulis dalam bentuk yang bisa langsung ditelusuri user** (nama file + halaman/pasal/slide), bukan sekadar nomor chunk internal.

## Red flag saat ekstraksi (jangan lewati diam-diam)
- Halaman/slide kosong padahal filenya besar → kemungkinan scan gagal terbaca / perlu OCR.
- Tabel kompleks di PDF/DOCX yang berantakan saat diekstrak jadi teks → verifikasi ulang dengan render visual (`view` untuk gambar/PDF) sebelum dipakai sebagai dasar klaim compliance.
- Dokumen multi-bahasa → catat bahasa per dokumen; kalau user minta compliance check lintas bahasa, terjemahkan istilah kunci dengan hati-hati dan catat istilah asli untuk verifikasi.
- File terenkripsi/password-protected → beri tahu user, jangan coba bypass.

## Setelah ekstraksi selesai
Tampilkan ringkasan inventaris singkat ke user sebelum lanjut ke retrieval/compliance check (kecuali user sudah eksplisit minta langsung ke hasil akhir), contoh:

> Ditemukan 4 dokumen: `kontrak_vendor_A.pdf` (12 halaman, kontrak), `kebijakan_privasi_internal.docx` (8 bagian, kebijakan), `daftar_vendor.xlsx` (240 baris data), `regulasi_gdpr_ringkasan.pdf` (scan, 6 halaman — sudah di-OCR).
