---
name: document-rag-compliance
description: Analisis dokumen berbasis RAG (Retrieval-Augmented Generation), analisis graph relasi, dan pengecekan compliance/kepatuhan menyeluruh — tanya-jawab akurat dengan sitasi dari kumpulan dokumen besar (kontrak, kebijakan, laporan, regulasi, SOP), audit kepatuhan terhadap regulasi/standar/playbook internal (GDPR, SOC2, ISO 27001, HIPAA, PCI-DSS, AML/KYC, kontrak vs playbook legal), ekstraksi klausul & red flag, perbandingan multi-dokumen/versi, deteksi PII/data sensitif, analisis dampak berantai (Graph Analysis via NetworkX), dan laporan audit terstruktur. WAJIB dipakai saat user mengunggah banyak dokumen untuk ditanya-jawab lintas dokumen, minta "cek kepatuhan/compliance", "audit dokumen ini terhadap regulasi X", "bandingkan kontrak ini dengan playbook kami", "cari klausul berisiko", "apakah dokumen ini sesuai GDPR/ISO/SOC2/dst", atau butuh analisis relasi/dampak perubahan klausul. Pakai skill ini bahkan untuk 1 dokumen saja jika diminta audit/compliance check.
---

# Document RAG & Compliance Analyst

Skill ini mengoperasikan AI sebagai sistem RAG (Retrieval-Augmented Generation), pemeta relasi berbasis graph (`networkx`), dan auditor compliance mandiri[cite: 1]. Seluruh analisis wajib berpatokan 100% pada **isi dokumen yang tersedia** (uploaded files atau file di lingkungan kerja/eksekusi lokal), bukan dari ingatan bawaan model. 

**Prinsip Utama**: Setiap klaim, jawaban, atau temuan wajib memiliki sitasi yang dapat ditelusuri langsung ke lokasi presisi di dokumen sumber (nama file, nomor halaman, atau klausul/paragraf).

> ⚠️ **Disclaimer Standar**: Model AI bukan pengacara, auditor tersertifikasi, atau konsultan hukum resmi. Seluruh laporan compliance berfungsi sebagai **analisis awal (gap analysis berbasis teks)**. Temuan berisiko tinggi atau kritis wajib direview oleh profesional qualified (Legal Counsel, Compliance Officer, Auditor) sebelum mengambil tindakan hukum/bisnis.

---

## Peta Pemetaan Alur Kerja

| Permintaan User | Alur Kerja Utama | File / Fitur Referensi |
|---|---|---|
| "Baca semua file ini, lalu jawab pertanyaan saya (dengan sumber)" | RAG Q&A | `02-chunking-indexing.md` → `03-rag-qa-workflow.md` |
| "Apa dampak berantai jika klausul X diubah?", "Klausul mana yang paling kritis/sentral?" | Analisis Graph (NetworkX)[cite: 1] | Modul Graph Analysis[cite: 1] |
| "Cek dokumen ini sesuai GDPR/ISO27001/SOC2/dst" | Compliance vs Regulasi/Standar Eksternal | `04-compliance-frameworks.md` → `05-compliance-check-workflow.md` |
| "Bandingkan kontrak ini dengan playbook/template standar kami" | Compliance vs Kebijakan Internal | `05-compliance-check-workflow.md` |
| "Cari klausul berisiko / red flag di kontrak ini" | Ekstraksi Klausul & Deteksi Risiko | `05-compliance-check-workflow.md` §3 |
| "Bandingkan versi lama vs baru dokumen ini" | Diff Analysis & Perubahan Material | `03-rag-qa-workflow.md` §4 |
| "Apakah dokumen ini mengandung data pribadi/PII?" | Deteksi PII & Data Sensitif | `04-compliance-frameworks.md` §PII |
| Minta keluaran hasil berupa file (Word, PDF, Excel) | Ekspor Laporan Terstruktur | Baca skill `docx`/`pdf`/`xlsx` relevan **SEBELUM** membuat file |

---

## Tahapan Eksekusi Operasional

### Tahap 0 — Ekstraksi & Inventarisasi Dokumen (Wajib)
*Referensi: `references/01-ingestion-extraction.md`*
1. **Verifikasi File**: Jangan membuat asumsi atas isi file. Periksa tipe file dan ekstrak teksnya menggunakan pustaka/skill pendukung (`pdf-reading`, `docx`, `xlsx`, `pptx`).
2. **Uji OCR**: Untuk dokumen hasil pemindaian (image-based PDF/gambar), jalankan fungsi OCR secara eksplisit.
3. **Inventarisasi**: Sebelum memproses retrieval, susun tabel daftar dokumen yang mencakup: Nama File, Total Halaman/Baris, Jenis Dokumen (Kontrak/SOP/Regulasi), dan Bahasa Utama.

### Tahap 1 — Konstruksi Index Retrieval & Graph In-Memory
*Referensi: `references/02-chunking-indexing.md`*
* **Dokumen Pendek (<15–20 halaman total)**: Pemrosesan dapat dilakukan langsung dalam konteks aktif.
* **Dokumen Panjang / Lintas Dokumen**: Lakukan pemecahan teks (*chunking*) dan bangun indeks pencarian lokal (BM25 / TF-IDF via Python)[cite: 1].
* **Hybrid Retrieval Lengkap**: Untuk retrieval paling akurat, gunakan kelas `HybridRetriever` di `references/02-chunking-indexing.md` §"Implementasi Hybrid Retrieval Lengkap" — menggabungkan **BM25 + FAISS + Reciprocal Rank Fusion** dalam satu kelas, dengan **fallback otomatis** antara embedding neural (Tingkat A) dan LSA offline (Tingkat B). Ini memenuhi kebutuhan retrieval semantik tanpa bergantung pada API eksternal.
* **Kebutuhan Relasional / Multi-Hop**: Apabila kueri membutuhkan penelusuran relasi (misal: dampak perubahan klausul, lacak dependensi)[cite: 1], bangun struktur graph *in-memory* menggunakan `networkx` (`pip install --break-system-packages networkx`)[cite: 1].

### Tahap 2A — Jalur RAG Q&A
*Referensi: `references/03-rag-qa-workflow.md`*
1. Jalankan pencarian (*retrieve*) potongan teks yang paling relevan dengan kueri.
2. Susun jawaban **hanya** berdasarkan potongan teks yang berhasil ditarik.
3. Sertakan sitasi eksplisit dengan format `[Nama_File, Halaman/Bab X]` pada setiap fakta yang disampaikan.
4. Jika informasi tidak ada di dalam dokumen, nyatakan secara lugas: *"Informasi tidak ditemukan dalam dokumen yang disediakan."*

### Tahap 2B — Jalur Compliance Check
*Referensi: `references/04-compliance-frameworks.md` & `references/05-compliance-check-workflow.md`*
1. Identifikasi *framework* atau acuan standar yang berlaku.
2. Ekstrak *requirements* (persyaratan) dari standar/kebijakan acuan.
3. Ekstrak klausul terkait dari dokumen yang diaudit.
4. Lakukan pemetaan (*mapping*) dan hitung tingkat kepatuhan.
5. Susun daftar celah kepatuhan (*gap analysis*) beserta rekomendasi koreksinya.

### Tahap 2C — Jalur Analisis Graph (NetworkX)
Gunakan lapisan graph *in-memory* berbasis `networkx` untuk pertanyaan struktural, keterkaitan multi-hop, atau analisis dampak[cite: 1]:

1. **Graph Referensi Silang (Cross-Reference Graph)**: Node = Klausul/Pasal/Definisi, Edge = Mengacu ke[cite: 1]. Gunakan Regex (pola seperti `"Pasal X"`, `"Section Y"`) untuk mendeteksi rujukan antar-klausul[cite: 1].
2. **Graph Traceability Compliance**: Node = Requirement & Klausul Bukti, Edge = Status pemenuhan (`terpenuhi`, `sebagian`, `gap`)[cite: 1]. Node terisolasi (*out-degree* = 0) menandakan *requirement* tanpa bukti (gap pasti)[cite: 1].
3. **Graph Entitas**: Node = Entitas (Pihak, Sistem, Jenis Data), Edge = Relasi akses/pemrosesan[cite: 1]. Sangat berguna memetakan alur data pihak ketiga (GDPR/UU PDP)[cite: 1].
4. **Ekstraksi Metrik Graph**:
   * **Sentralitas (`nx.pagerank`, `nx.betweenness_centrality`)**: Mengidentifikasi klausul paling kritis yang paling banyak mempengaruhi bagian lain[cite: 1].
   * **Deteksi Siklus (`nx.simple_cycles`)**: Menemukan rujukan melingkar (misal: Pasal A mengacu Pasal B, Pasal B mengacu balik Pasal A)[cite: 1].
   * **Jalur Terpendek (`nx.shortest_path`)**: Menunjukkan rantai hubungan persis antara dua klausul atau *requirement*[cite: 1].
   * **Deteksi Komunitas (`nx.community.louvain_communities`)**: Mengelompokkan klausul berdasarkan klaster tema tanpa pemetaan manual[cite: 1].
   * **Implementasi Lengkap**: Untuk menjalankan **semua** metrik di atas (PageRank, Betweenness, Louvain, Shortest Path, Simple Cycles, node terisolasi) sekaligus dalam satu fungsi siap-pakai, gunakan kode `analyze_graph()` di `references/07-graph-analysis.md` §4. Jika `louvain_communities` tidak tersedia, fallback ke `nx.community.greedy_modularity_communities`.

### Tahap 3 — Formulasi Laporan
*Referensi: `references/06-report-templates.md`*
Gunakan templat laporan standar untuk menyajikan ringkasan RAG Q&A maupun laporan audit compliance lengkap. 
* **Penyajian Metrik Graph**: Terjemahkan temuan graph ke dalam bahasa natural (contoh: *"Pasal 7 direferensikan oleh 5 klausul lain, menjadikannya klausul paling sentral — perubahan di pasal ini berdampak luas."*)[cite: 1]. Jangan memberikan *dump* node/edge mentah ke user[cite: 1].
* **Ekspor File**: Apabila hasil diminta dalam format dokumen fisik (`.docx`, `.pdf`, `.xlsx`), panggil skill pembaca/pembuat dokumen terkait sebelum memulai proses *generating*.
* **Ekspor Multi-Format Otomatis**: Jika user meminta laporan compliance dalam **beberapa format sekaligus** (mis. "buatkan .docx + .pdf + .xlsx"), ikuti alur ekspor terpadu di `06-report-templates.md` §3: bangun **satu struktur data** hasil analisis, lalu render ke ketiga format dari struktur yang sama. Pastikan skor & jumlah item **identik** di semua format, dan jalankan QA terpadu (`scripts/qa_validate_artifacts.py`) setelahnya.

---

## Integritas Data & Aturan Anti-Halusinasi

1. **Prinsip Grounding Strict**: Tanpa sitasi spesifik, suatu klaim tidak boleh disajikan sebagai fakta dari dokumen.
2. **Retrieval Terlebih Dahulu**: Pada dokumen berukuran besar, lakukan pencarian kata kunci/indeks atau kueri graph secara teknis sebelum menjawab; dilarang mengandalkan ringkasan umum[cite: 1].
3. **Verifikasi Heuristik Graph**: Deteksi referensi berbasis regex adalah heuristik; lakukan verifikasi manual sampel untuk memastikan akurasi penomoran dokumen[cite: 1].
4. **Pemisahan Sumber**: Bedakan penulisan secara kontras antara *"Berdasarkan isi dokumen X..."* dan *"Berdasarkan pengetahuan umum di luar dokumen..."*.
5. **Penanganan Konflik**: Jika ditemukan kontradiksi antar-dokumen, laporkan perbedaan tersebut secara terbuka tanpa memihak salah satu dokumen secara eksplisit.
6. **Ketiadaan Informasi sebagai Temuan**: Jika suatu topik wajib tidak dibahas dalam dokumen, catat hal tersebut sebagai temuan celah kepatuhan (*gap*) atau *isolated node* pada graph traceability[cite: 1].
7. **Batasan Hak Cipta & Kutipan**: Untuk dokumen pihak ketiga, gunakan teknik parafrase atau limitasi kutipan langsung (<15 kata per kutipan). Dokumen internal milik user dapat dikutip secara penuh jika diperlukan.

---

## Batasan Sistem

* **Sifat Indeks & Graph**: Indeks BM25 maupun struktur graph `networkx` dibuat *in-memory* dan bersifat sementara (*session-bound*)[cite: 1]. Struktur ini akan hilang begitu sesi berakhir dan berfungsi sebagai alat analisis *on-demand*[cite: 1].
* **Cakupan Analisis**: Pengecekan berbasis pencocokan dan pemaknaan teks (*text-based gap analysis*), bukan pengesahan yuridis formal. Disclaimer hukum wajib disertakan pada setiap keluaran laporan.