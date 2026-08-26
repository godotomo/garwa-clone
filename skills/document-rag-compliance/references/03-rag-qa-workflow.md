# Alur RAG Q&A & Perbandingan/Diff Dokumen

## 1. Alur Jawab Pertanyaan dari Dokumen

1. **Pahami Pertanyaan**: Jika ambigu (misalnya "apa syarat pembayarannya" tetapi terdapat 4 kontrak vendor berbeda), minta klarifikasi singkat atau jawab untuk seluruh dokumen relevan dengan label yang terpisah secara jelas per dokumen.
2. **Retrieve**: Lakukan pencarian (rujuk `02-chunking-indexing.md`) menggunakan kueri asli ditambah 1–2 variasi istilah.


3. **Verifikasi Kontekstual**: Lakukan verifikasi internal (*human-in-the-loop validation* oleh sistem) terhadap potongan teks (*chunk*) yang ditarik: apakah *chunk* ini benar-benar menjawab kueri, atau sekadar mengandung kata kunci yang sama tanpa relevansi substantif?
4. **Susun Jawaban**:
* Tampilkan jawaban langsung di awal tanpa pengantar bertele-tele.
* Setiap klaim faktual wajib diikuti sitasi spesifik: `(sumber: nama_file, hal./bagian X)`.
* Apabila jawaban bersumber dari beberapa dokumen, pisahkan informasi secara jelas per dokumen sumber.
* Jika informasi tidak ditemukan, nyatakan secara eksplisit: *"Tidak ditemukan pembahasan soal [topik] di dokumen yang diberikan."* Dilarang menjawab menggunakan pengetahuan umum tanpa memberikan penanda eksplisit bahwa informasi tersebut bukan berasal dari dokumen.


5. **Aturan Kutipan**: Jalankan aturan hak cipta standar untuk dokumen pihak ketiga (utamakan parafrase, kutipan langsung <15 kata per sumber, dan maksimal 1 kutipan per sumber). Untuk dokumen internal/milik pengguna sendiri (kontrak atau kebijakan internal), pengutipan dapat dilakukan lebih leluasa, namun tetap prioritaskan parafrase demi keterbacaan kecuali untuk klausul kritis (seperti definisi kontraktual atau nilai ambang batas).

## 2. Pertanyaan Multi-Hop (Penaakulan Berantai)

Untuk pertanyaan yang membutuhkan gabungan informasi dari beberapa bagian/dokumen (contoh: *"Apakah total kompensasi di kontrak ini melebihi anggaran yang disetujui di lampiran?"*):

* Lakukan pencarian (*retrieve*) dari dokumen-dokumen terkait.
* Ekstrak dan sajikan seluruh data pendukung (misalnya angka/nilai) secara terpisah per sumber.
* Tampilkan perhitungan atau kesimpulan gabungan di akhir agar pengguna dapat memverifikasi setiap komponen secara independen.

## 3. Pertanyaan Agregat / Analisis Statistik

Untuk kueri kuantitatif pada banyak dokumen (contoh: *"Dari 50 kontrak vendor ini, berapa yang memiliki klausul auto-renewal?"*):

* **Dilarang** melakukan estimasi/sampling sebagian dokumen untuk digeneralisasi.
* Lakukan pemrosesan secara menyeluruh pada **semua** dokumen/chunk relevan melalui pemrosesan terprogram (eksekusi skrip/loop), hitung secara presisi, dan tampilkan daftar dokumen yang memenuhi maupun tidak memenuhi kriteria guna transparansi verifikasi.

## 4. Perbandingan Versi / Diff Dokumen

Untuk menganalisis perubahan antara versi dokumen (lama vs. baru):

1. Ekstrak teks dari kedua versi berdasarkan unit struktural yang setara (misalnya per pasal/paragraf).
2. Apabila berkas berformat `.docx` dan memiliki riwayat perubahan (*tracked changes/comments*), manfaatkan fitur tersebut melalui pemrosesan dokumen sebagai sumber *diff* utama.
3. Jika tidak tersedia riwayat perubahan, jalankan *text diffing* terstruktur (seperti pustaka `difflib` pada Python per paragraf) untuk mengidentifikasi penambahan, penghapusan, atau pergeseran teks.
4. Klasifikasikan setiap perubahan ke dalam kategori:
* **Material**: Perubahan yang mempengaruhi kewajiban, nilai numerik, tenggat waktu, atau hak dan kewajiban para pihak.
* **Kosmetik**: Perubahan tata bahasa, format, perapihan spasi, atau penomoran ulang.


5. Sajikan hasil analisis dalam bentuk tabel terstruktur:

| Pasal/Bagian | Versi Lama | Versi Baru | Sifat Perubahan (Material/Kosmetik) | Catatan Dampak |
| --- | --- | --- | --- | --- |


## 5. Lembar Verifikasi Kualitas Jawaban (Pre-Output Checklist)

* [ ] Setiap klaim faktual yang bersumber dari dokumen telah dilengkapi sitasi lokasi yang presisi.
* [ ] Tidak ada pencampuran tanpa penanda antara isi dokumen dan pengetahuan bawaan model AI.
* [ ] Kontradiksi antar-dokumen atau antar-bagian dilaporkan secara transparan dan tidak diputuskan sepihak.
* [ ] Pertanyaan kuantitatif/agregat dihitung secara terprogram (bukan estimasi visual), serta mencantumkan cakupan data yang dianalisis.
* [ ] Bahasa jawaban disesuaikan dengan bahasa yang digunakan dalam kueri pengguna.