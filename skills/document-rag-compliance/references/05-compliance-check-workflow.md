# Alur Kerja Compliance Check (Gap Analysis)

## 1. Penetapan Parameter Perbandingan (Sisi Analisis)

Analisis kepatuhan (*compliance check*) wajib memetakan dua elemen acuan:

* **Acuan Persyaratan (Requirement Side)**: Ketentuan standar eksternal (GDPR, UU PDP, ISO 27001), regulasi industri, atau kebijakan/playbook internal pengguna (seperti *template* kontrak standar).


* **Acuan Implementasi (Implementation Side)**: Dokumen target yang diaudit (kontrak vendor, draft kebijakan privasi, dokumen SOP, atau matriks kontrol).



> **Instruksi Eksekusi**: Identifikasi secara tegas dokumen mana yang berfungsi sebagai *Requirement* dan dokumen mana yang menjadi target *Implementasi* sebelum memulai analisis.
> 
> 

---

## 2. Ekstraksi Persyaratan Menjadi Checklist Atomik

Ubah dokumen persyaratan menjadi daftar periksa (*checklist*) berbasis kriteria terukur (atomik) yang memiliki nilai evaluasi biner atau berderajat.

**Contoh Format Checklist Atomik**:

* [ ] **R1**: Tersedia mekanisme formal bagi subjek data untuk mengajukan hak akses data.
* [ ] **R2**: Terdapat klausul kewajiban notifikasi kebocoran data (*breach notification*) maksimal 72 jam kepada otoritas.
* [ ] **R3**: Mencantumkan dasar hukum pemrosesan data (*lawful basis*) untuk setiap kategori data yang dikelola.


Untuk playbook internal, ekstraksi checklist dilakukan dengan menarik poin-poin utama dari template standar menggunakan prosedur pencarian pada `02-chunking-indexing.md`.

---

## 3. Pemetaan & Pencarian Bukti (Evidence Mapping)

Jalankan pencarian kata kunci multi-istilah (*multi-query retrieval*) pada dokumen target untuk setiap butir *requirement*. Tetapkan status pemenuhan ke dalam salah satu kategori berikut:

| Status Evaluasi | Simbol | Kriteria Penilaian | Action Required |
| --- | --- | --- | --- |
| **Terpenuhi** | ✅ | Klausul relevan ditemukan dan memenuhi seluruh kriteria persyaratan.

 | Kutip teks klausul persis dan cantumkan sitasi lokasi (`nama_file`, `halaman/pasal`).

 |
| **Sebagian / Ambigu** | ⚠️ | Topik dibahas namun lingkupnya tidak lengkap, kabur, atau berpotensi multitafsir.

 | Jelaskan celah/kekurangan spesifik yang belum terpenuhi.

 |
| **Tidak Ditemukan (Gap)** | ❌ | Tidak ditemukan pembahasan terkait setelah melalui pencarian variasi kata kunci.

 | Tandai sebagai celah kepatuhan (*gap*).

 |
| **Tidak Berlaku (N/A)** | ➖ | Persyaratan tidak relevan dengan konteks dokumen atau cakupan operasional target.

 | Berikan alasan konteks mengapa butir tersebut dinilai *Not Applicable*.

 |

---

## 4. Deteksi Klausul Berisiko (Red Flag Analysis - Kontrak)

Selain memeriksa kriteria formal, lakukan pemindaian pola klausul berisiko tinggi (*red flag*) yang dapat merugikan posisi hukum/bisnis:

1. **Ketidakseimbangan Tanggung Jawab (Unbalanced Liability)**: Batas ganti rugi (*liability cap*) satu pihak sangat terbatas sementara pihak lainnya tidak terbatas.


2. **Perpanjangan Otomatis Ketat (Strict Auto-Renewal)**: Jendela waktu pemberitahuan pembatalan sangat sempit (misalnya wajib 90 hari sebelum terminasi).


3. **Perubahan Sepihak (Unilateral Amendment)**: Hak untuk mengubah isi kontrak/kebijakan secara sepihak tanpa persetujuan tertulis.


4. **Indemnifikasi Tanpa Batas**: Klausul ganti rugi yang terlalu luas atau menanggung akibat kelalaian pihak lawan.


5. **Yurisdiksi/Forum Merugikan**: Penetapan hukum yang berlaku (*governing law*) atau forum sengketa di lokasi yang secara logistik/finansial memberatkan.


6. **Definisi Ambigu**: Penggunaan istilah tanpa tolok ukur yang jelas (misalnya *"usaha terbaik"* tanpa kriteria keberhasilan).


7. **Kerahasiaan Tanpa Batas Waktu**: Kewajiban *confidentiality* tanpa batas durasi yang wajar.



> **Atribut Red Flag**: Setiap temuan wajib diberi tingkat keparahan (*Severity*: `Low`, `Medium`, `High`, `Critical`), kutipan klausul asli, serta rekomendasi perbaikan spesifik.
> 
> 

---

## 5. Perhitungan Skor Kepatuhan & Klasifikasi Kategori

Setelah seluruh indikator dinilai, hitung Persentase Kepatuhan Keseluruhan menggunakan formula berikut:

$$\text{Skor Kepatuhan (\%)} = \left( \frac{\text{Jumlah } \text{✅} + (0.5 \times \text{Jumlah } \text{⚠️})}{\text{Total Item Requirement} - \text{Jumlah } \text{➖}} \right) \times 100\%$$

Sajikan pula hasil evaluasi berdasarkan rincian per kategori (contoh: *Kategori Perlindungan Data: 8/10 Terpenuhi; Kategori Keamanan Teknis: 3/6 Terpenuhi*) untuk mempermudah pemetaan prioritas.

---

## 6. Prioritisasi Dampak Temuan

Urutkan seluruh temuan *gap* dan *red flag* berdasarkan skala dampak teknis/hukum, bukan sekadar kuantitas temuan:

1. **Critical / High**: Potensi sanksi regulasi skala besar, denda finansial, kebocoran data PII, atau kerugian hukum material.
2. **Medium**: Amboguitas operasional, risiko administrasi menengah, atau ketidaksesuaian prosedur non-vital.
3. **Low / Kosmetik**: Ketidaksesuaian minor, kesalahan format, atau redaksional sederhana.


Temuan berkategori Critical/High wajib ditampilkan secara terpisah di bagian atas ringkasan eksekutif.

---

## 7. Formulasi Usulan Rekomendasi

Untuk setiap *gap* atau *red flag*, berikan usulan rekomendasi perbaikan konkret. Jika memungkinkan, sertakan **draft klausul revisi** sebagai bahan pertimbangan awal.

> ⚠️ Setiap usulan klausul revisi wajib ditandai dengan catatan: *"Draft rekomendasi ini merupakan usulan teknis awal dan wajib direview oleh tim legal/compliance officer sebelum digunakan secara formal."*

---

## 8. Ekspor Hasil Evaluasi

Format seluruh hasil analisis ini menggunakan struktur laporan yang telah ditentukan pada referensi `06-report-templates.md` (bagian *Laporan Audit Compliance*).