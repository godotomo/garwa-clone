# Framework & Standar Compliance Umum

Dokumen ini berfungsi sebagai **acuan pemetaan awal** (*baseline mapping*) untuk mengenali persyaratan inti dari berbagai kerangka kerja (*framework*) compliance eksternal maupun internal. Dokumen ini digunakan bersama dengan workflow analisis celah (*gap analysis*) pada `05-compliance-check-workflow.md`.

> ⚠️ **Prinsip Dasar**: Ringkasan ini merupakan panduan orientasi operasional. Untuk kebutuhan audit mendalam atau verifikasi pasal presisi, lakukan pembaruan data melalui pencarian daring (*web search*) guna mengantisipasi revisi regulasi terbaru, serta sertakan batasan bahwa hasil analisis berbasis teks ini memerlukan tinjauan ahli hukum/auditor tersertifikasi.

---

## 1. Privasi & Perlindungan Data Pribadi

### GDPR (Uni Eropa)

* **Dasar Hukum Pemrosesan**: Memerlukan *lawful basis* yang sah (persetujuan, pelaksanaan kontrak, kewajiban hukum, kepentingan vital, kepentingan umum, atau kepentingan sah).
* **Hak Subjek Data**: Hak akses, perbaikan, penghapusan (*right to erasure/be forgotten*), pembatasan pemrosesan, portabilitas data, dan keberatan.
* **Notifikasi Insiden**: Pelaporan kebocoran data pribadi (*data breach*) ke otoritas pelindung data maksimal **72 jam** sejak diketahui.
* **Transfer Data Lintas Batas**: Menggunakan *Standard Contractual Clauses* (SCC) atau *Adequacy Decision*.
* **Persyaratan Tata Kelola**: Penunjukan *Data Protection Officer* (DPO) dan pembuatan *Data Protection Impact Assessment* (DPIA) untuk pemrosesan berisiko tinggi.

### UU PDP (Indonesia)

* **Dasar Pemrosesan Data**: Persetujuan eksplisit, pemenuhan kewajiban kontrak, kewajiban hukum, pemenuhan kepentingan sah, dll.
* **Hak Pemilik Data Pribadi**: Hak pembaruan data, akses, penghentian pemrosesan, penghapusan, dan ganti rugi atas pelanggaran.
* **Kewajiban Pengendali**: Notifikasi insiden keamanan data kepada pengendali/subjek data dan lembaga pengawas; penunjukan Pejabat/Petugas Pelindungan Data Pribadi (DPO) untuk aktivitas berisiko tinggi atau pemrosesan data skala besar.
* **Transfer Data Lintas Negara**: Pemetaan tingkat perlindungan negara penerima, ketersediaan perjanjian antarnegara, atau persetujuan subjek data.

### CCPA / CPRA (California, AS)

* **Hak Konsumen**: Hak untuk mengetahui data yang dikumpulkan, menghapus data, menolak penjualan/penyebaran data (*opt-out of sale/sharing*), serta pembatasan penggunaan data sensitif.
* **Definisi Luas**: Cakupan definisi *"Sale"* dan *"Sharing"* data pribadi diperluas mencakup pertukaran data untuk periklanan perilaku lintas konteks.

### HIPAA (AS - Sektor Kesehatan)

* **Cakupan**: Perlindungan *Protected Health Information* (PHI) melalui *Privacy Rule* dan *Security Rule*.
* **Persyaratan Kontraktual**: Wajib memiliki *Business Associate Agreement* (BAA) dengan pihak ketiga yang mengelola atau mengakses PHI.

---

## 2. Keamanan Informasi & Infrastruktur IT

### ISO/IEC 27001

* **ISMS (Information Security Management System)**: Kerangka kerja sistem manajemen keamanan informasi berbasis risiko.
* **Komponen Kunci**: Penilaian risiko formal, kebijakan keamanan, audit internal, tinjauan manajemen, serta kontrol keamanan (kontrol akses, kriptografi, keamanan fisik, operasional, manajemen insiden, dan keberlangsungan bisnis).

### SOC 2 (Trust Services Criteria)

* **Kriteria Evaluasi**: *Security* (wajib), serta kriteria opsional: *Availability*, *Processing Integrity*, *Confidentiality*, dan *Privacy*.
* **Tipe Laporan**:
* **Type I**: Evaluasi kesesuaian desain kontrol pada satu titik waktu (*point-in-time*).
* **Type II**: Evaluasi efektivitas operasional kontrol dalam rentang periode tertentu (umumnya 3–12 bulan).



### PCI-DSS (Sektor Kartu Pembayaran)

* **Aplikasi**: Entitas yang memproses, menyimpan, atau mentransmisikan data pemegang kartu (*Cardholder Data*).
* **Kontrol Wajib**: Segmentasi jaringan, enkripsi data sensitif (*data at rest & in transit*), kontrol akses berbasis kebutuhan (*need-to-know*), pengujian keamanan berkala (*vulnerability scan & pentest*), serta pemantauan log aktivitas.

### NIST Cybersecurity Framework (CSF)

* **Kerangka Fungsi**: *Identify*, *Protect*, *Detect*, *Respond*, *Recover*.
* **Peran**: Digunakan sebagai acuan pembanding (*baseline benchmark*) untuk mengukur tingkat kematangan (*maturity level*) keamanan siber organisasi.

---

## 3. Keuangan & Anti-Pencucian Uang (AML)

### AML / KYC (Anti-Money Laundering / Know Your Customer)

* **Verifikasi & Due Diligence**: Implementasi *Customer Due Diligence* (CDD) dan *Enhanced Due Diligence* (EDD) untuk nasabah/transaksi berisiko tinggi.
* **Pemantauan & Pelaporan**: Pemantauan transaksi mencurigakan dan pelaporan *Suspicious Transaction Report* (STR) ke otoritas terkait (seperti PPATK di Indonesia).
* **Penyaringan Sanksi**: *Screening* wajib terhadap daftar sanksi nasional dan internasional (seperti OFAC, UN Sanctions).

### SOX (Sarbanes-Oxley Act)

* **Aplikasi**: Perusahaan publik dan entitas terdaftar.
* **Fokus**: Pengendalian internal atas pelaporan keuangan (*Internal Controls Over Financial Reporting* / ICFR), sertifikasi eksekutif, dan keandalan audit independen.

---

## 4. Penelaahan Kontrak & Legal (Contract Review Checklist)

Gunakan daftar periksa berikut saat menganalisis dokumen perjanjian atau membandingkan kontrak terhadap *playbook* internal:

| Parameter Klausul | Fokus Pemeriksaan / Risiko |
| --- | --- |
| **Definisi & Istilah** | Konsistensi penggunaan istilah terdefinisi di seluruh pasal. |
| **Ruang Lingkup (SOW)** | Kejelasan kewajiban, *deliverables*, dan batas tanggung jawab para pihak. |
| **Pembayaran & Kompensasi** | Kejelasan nilai, jadwal pembayaran, mata uang, denda keterlambatan, dan pajak. |
| **Tanggung Jawab & Batas Ganti Rugi** | Keseimbangan posisi ganti rugi (*indemnification*) dan batasan tanggung jawab (*limitation of liability/cap*). |
| **Kerahasiaan (NDA)** | Cakupan data rahasia, durasi kewajiban, dan pengecualian hukum. |
| **Kekayaan Intelektual (IP)** | Penegasan kepemilikan hak cipta/paten dan batasan lisensi penggunaan. |
| **Pengakhiran (Termination)** | Syarat pengakhiran sepihak (*termination for convenience*) vs akibat wanprestasi (*for cause*), serta periode pemberitahuan. |
| **Hukum & Penyelesaian Sengketa** | Yurisdiksi hukum yang berlaku (*governing law*) dan forum penyelesaian (Pengadilan/Arbitrase). |
| **Addendum Data (DPA)** | Keberadaan klausul pemrosesan data pribadi jika kontrak melibatkan transfer/akses data subjek. |

---

## 5. Prosedur Deteksi PII & Data Sensitif

Apabila terdapat permintaan untuk mengidentifikasi keberadaan Data Pribadi / PII (*Personally Identifiable Information*), jalankan pencarian berbasis pola/skrip (*regex*) di lingkungan eksekusi lokal:

1. **Identitas Resmi**: Ekstraksi pola nomor NIK, SSN, atau nomor paspor berdasarkan format standar.
2. **Kontak Person**: Identifikasi format alamat email dan nomor telepon.
3. **Data Keuangan**: Pemindaian nomor kartu pembayaran yang valid menurut *Luhn Algorithm* (13–19 digit).
4. **Data Sensitif Kontekstual**: Kombinasi nama lengkap yang berdampingan dengan catatan kesehatan, orientasi politik/agama, atau data anak (memerlukan analisis konteks kalimat).

> **Penanganan Hasil**: Catat lokasi presisi (nama file, nomor halaman, atau nomor baris) untuk setiap temuan PII guna dijadikan basis rekomendasi penyamaran (*masking/redaction*) pada laporan audit.

---

## 6. Prosedur Penggunaan Modul

1. **Penentuan Framework**: Identifikasi kerangka kerja yang relevan berdasarkan konteks industri, jenis dokumen, atau permintaan kueri.
2. **Penetapan Asumsi**: Jika kerangka kerja tidak disebutkan secara eksplisit namun jenis dokumen memiliki arah yang jelas (misalnya Kebijakan Privasi aplikasi global), gunakan standar yang paling relevan (seperti GDPR/UU PDP) dan sampaikan asumsi tersebut di awal analisis.
3. **Pencarian Eksplisit**: Eksekusi pencarian daring (*web search*) jika diperlukan verifikasi atas pasal atau ketentuan ambang batas (*threshold*) terbaru.
4. **Eksekusi Audit**: Gunakan hasil pemetaan kerangka kerja ini untuk menjalankan tahapan analisis celah pada `05-compliance-check-workflow.md`.