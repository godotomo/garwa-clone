---
name: hukum-indonesia
description: Panduan riset dan penjawaban pertanyaan hukum Indonesia (peraturan perundang-undangan, putusan pengadilan, hukum bisnis/korporasi, ketenagakerjaan, pertanahan, pajak, HKI, perizinan, dsb). WAJIB dipakai setiap kali user bertanya tentang UU, Perppu, PP, Perpres, Permen, Perda, KUHP/KUHAP, kontrak/perjanjian, pendirian PT/CV/yayasan, izin usaha/OSS, sengketa/gugatan, putusan MA/MK/pengadilan, hak kekayaan intelektual, hukum ketenagakerjaan, hukum keluarga/waris Indonesia, atau topik legal Indonesia lainnya — bahkan jika user hanya menyebut nama peraturan atau kasus tanpa kata "hukum" secara eksplisit. Skill ini berisi daftar situs resmi (JDIHN, peraturan.go.id, direktori putusan MA, MK, dsb) yang harus diakses lewat web_search/web_fetch untuk memverifikasi status terkini suatu peraturan sebelum menjawab, karena hukum Indonesia sering berubah dan model tidak boleh mengandalkan ingatan/pelatihan semata untuk nomor pasal, status berlaku, atau isi peraturan terbaru.
---

# Hukum Indonesia — Skill Riset & Penjawaban

## Prinsip Kerja Utama

1. **Jangan mengandalkan ingatan untuk detail hukum yang bisa berubah.** Nomor pasal, status berlaku/dicabut, angka denda/sanksi, nama lembaga, dan peraturan pelaksana SANGAT sering berubah di Indonesia (revisi UU, putusan MK yang mengubah tafsir, PP turunan baru, dsb). Selalu `web_search` dan/atau `web_fetch` ke sumber resmi di bawah sebelum menyatakan sesuatu sebagai fakta hukum yang pasti — terutama untuk pertanyaan yang menyebut nomor/tahun peraturan tertentu, status "masih berlaku atau tidak", atau perkembangan terbaru.
2. **Utamakan sumber primer (situs .go.id) di atas sumber sekunder** (hukumonline, artikel blog, dsb). Sumber sekunder boleh dipakai untuk analisis populer/konteks, tapi kutipan bunyi pasal dan status hukum harus dicek ke sumber primer.
3. **Selalu cek hierarki dan status peraturan** — apakah sudah diubah (perubahan/amandemen), dicabut, atau sedang diuji materi (judicial review) di MK/MA. Peraturan yang tampak relevan bisa saja sudah tidak berlaku.
4. **Beri disclaimer yang wajar** — model bukan advokat/notaris berlisensi dan jawaban bukan nasihat hukum resmi (legal opinion). Untuk kasus konkret dengan konsekuensi hukum nyata (sengketa, kontrak bernilai besar, pidana), sarankan konsultasi ke advokat, notaris/PPAT, atau konsultan pajak sesuai kebutuhan — sampaikan ini secara natural, bukan sebagai disclaimer templat di setiap respons pendek.
5. **Bedakan pertanyaan edukatif/umum vs kasus konkret pengguna.** Pertanyaan umum ("apa itu somasi", "bagaimana hierarki UU") bisa dijawab langsung dengan riset ringan. Pertanyaan yang menyiratkan situasi pribadi user (sengketa, kontrak yang sedang dihadapi, potensi pidana) tetap dijawab secara informatif dan faktual, tapi framing-nya sebagai informasi umum, bukan nasihat hukum personal yang final.

## Alur Kerja (Workflow)

1. **Identifikasi bidang hukum** — pidana, perdata, tata negara/administrasi, bisnis/korporasi, ketenagakerjaan, perpajakan, pertanahan, keluarga/waris, HKI, dsb. Ini menentukan situs sektoral mana yang relevan (lihat `references/sumber-sektoral.md`).
2. **Cari peraturan induk & turunannya** di `peraturan.go.id` atau `jdihn.go.id` (lihat `references/sumber-peraturan.md`). Catat nomor, tahun, judul lengkap, dan **status** (berlaku/dicabut/diubah).
3. **Cek apakah ada putusan MK yang menguji peraturan tersebut** (uji materi/judicial review) — putusan MK bisa membatalkan pasal atau mengubah tafsirnya secara mengikat. Cek di `mkri.id` atau kategori "Putusan MK" di `peraturan.go.id`.
4. **Jika relevan, cari yurisprudensi/putusan pengadilan** di Direktori Putusan MA (lihat `references/putusan-pengadilan.md`) untuk melihat bagaimana ketentuan diterapkan dalam praktik.
5. **Untuk isu sektoral** (izin usaha, pajak, ketenagakerjaan, pertanahan, dsb), cek regulator terkait — jangan hanya mengandalkan UU induk, karena banyak ketentuan teknis ada di Peraturan Menteri/Badan yang berubah lebih sering. Lihat `references/sumber-sektoral.md`.
6. **Susun jawaban**: sebutkan dasar hukum (nama & nomor peraturan, pasal jika relevan), status terkini, dan — bila relevan — arahkan user ke sumber resminya. Gunakan paraphrase, bukan kutipan panjang verbatim (tetap tunduk pada aturan copyright: kutipan langsung dari pasal peraturan pemerintah umumnya boleh lebih longgar karena merupakan dokumen publik/karya pemerintah, tapi tetap hindari menyalin seluruh pasal panjang tanpa perlu — ringkas dan jelaskan dengan bahasa sendiri).

## Alur Kerja Khusus: Analisis Dokumen untuk Compliance

Saat user mengunggah dokumen (kontrak, perjanjian kerja, kebijakan privasi, SOP internal, dsb) dan meminta pengecekan kepatuhan hukum, alur di atas perlu disesuaikan:

1. **Baca dokumen secara utuh dulu** sebelum mencari peraturan — pahami jenis dokumen dan bidang hukum yang relevan (kontrak kerja → ketenagakerjaan; kebijakan privasi → UU PDP No. 27/2022; perjanjian jual-beli → KUHPerdata/hukum kontrak umum; SOP sektor keuangan → OJK/BI).
2. **Identifikasi klausul yang menyentuh ketentuan memaksa (dwingend recht)** — ketentuan yang tidak bisa disimpangi oleh kesepakatan para pihak (mis. upah minimum, hak cuti, masa kerja PKWT maksimal). Klausul yang melanggar ini **wajib** ditandai sebagai berisiko tinggi/tidak sah, beda dengan klausul yang sekadar kurang lazim tapi tetap sah.
3. **Verifikasi tiap ketentuan yang jadi acuan** ke sumber primer terkini (jangan menandai klausul "melanggar Pasal X" tanpa mengecek dulu apakah Pasal X itu masih berlaku dalam bentuk aslinya atau sudah diubah).
4. **Kelompokkan temuan dengan jelas**, misalnya: (a) wajib direvisi — melanggar ketentuan memaksa; (b) berisiko/ambigu secara hukum — bisa menimbulkan sengketa tapi belum tentu melanggar; (c) saran praktik terbaik — tidak wajib tapi meningkatkan kepastian hukum. Jangan menyamaratakan semua temuan sebagai "masalah" dengan bobot yang sama.
5. **Jangan menandatangani atau menyimpulkan dokumen "aman" secara mutlak** — tutup dengan rekomendasi review final oleh advokat/in-house counsel, khususnya untuk dokumen yang akan ditandatangani atau punya nilai/risiko besar.

## Hierarki Peraturan Perundang-undangan (Ps. 7 UU No. 12 Tahun 2011 jo. UU No. 13 Tahun 2022)

Dari tertinggi ke terendah:
1. Undang-Undang Dasar Negara Republik Indonesia Tahun 1945
2. Ketetapan Majelis Permusyawaratan Rakyat (TAP MPR)
3. Undang-Undang (UU) / Peraturan Pemerintah Pengganti Undang-Undang (Perppu)
4. Peraturan Pemerintah (PP)
5. Peraturan Presiden (Perpres)
6. Peraturan Daerah Provinsi (Perda Provinsi)
7. Peraturan Daerah Kabupaten/Kota (Perda Kabupaten/Kota)

Di luar hierarki formal ini, ada juga Peraturan Menteri, Peraturan Lembaga/Badan (misal Peraturan BI, Peraturan OJK, Peraturan MK, Peraturan MA), dan Peraturan Kepala Daerah (Pergub/Perbup/Perwali) yang mengikat sepanjang diperintahkan oleh peraturan yang lebih tinggi dan diakui keberadaannya berdasarkan asas *lex superior derogat legi inferiori*. Asas lain yang relevan: *lex specialis derogat legi generali* (aturan khusus mengesampingkan yang umum) dan *lex posterior derogat legi priori* (aturan baru mengesampingkan yang lama untuk hal yang sama).

**Catatan penting**: nama kementerian/lembaga di Indonesia cukup sering berubah karena perombakan kabinet (contoh: Kementerian Hukum dan HAM sempat dipecah menjadi Kementerian Hukum dan Kementerian HAM terpisah dalam kabinet 2024–2029, dengan domain yang bisa bergeser dari `kemenkumham.go.id` ke `kemenkum.go.id`). **Selalu verifikasi nama lembaga dan domain resmi terkini lewat web_search sebelum mengarahkan user**, jangan berasumsi dari ingatan pelatihan.

## Sumber Resmi — Ringkasan Cepat

Untuk daftar lengkap dan penjelasan tiap situs, baca file referensi yang sesuai. Berikut inti yang paling sering dipakai:

| Kebutuhan | Situs utama |
|---|---|
| Cari UU/PP/Perpres/Permen/Perda apa saja, cek status berlaku | `peraturan.go.id` (Ditjen Peraturan Perundang-undangan, Kemenkum) |
| Portal gabungan semua dokumen hukum nasional (termasuk K/L & daerah) | `jdihn.go.id` |
| Putusan Mahkamah Agung (kasasi, PK, semua tingkat pengadilan umum/agama/militer/TUN) | `putusan3.mahkamahagung.go.id` |
| Putusan & Peraturan Mahkamah Konstitusi (uji materi UU) | `mkri.id` |
| Peraturan + putusan terkonsolidasi versi BPK | `peraturan.bpk.go.id`, `jdih.bpk.go.id` |
| Legalitas badan hukum (PT, yayasan, perkumpulan), fidusia | `ahu.go.id` |
| Perizinan berusaha (OSS/NIB) | `oss.go.id` |
| Kekayaan Intelektual (paten, merek, hak cipta) | `dgip.go.id` |
| Peraturan sektor jasa keuangan | `ojk.go.id` |
| Peraturan Bank Indonesia (moneter, sistem pembayaran) | `bi.go.id` |
| Peraturan & regulasi perpajakan | `pajak.go.id` (DJP, Kemenkeu) |
| Pertanahan/agraria | `atrbpn.go.id` |
| Ketenagakerjaan | `kemnaker.go.id` |
| Penuntutan pidana (JPU) | `jdih.kejaksaan.go.id` |
| Korupsi | `kpk.go.id` |
| Penyidikan pidana umum | `jdih.polri.go.id` |
| Aset kripto/keuangan digital | `ojk.go.id` (bukan lagi Bappebti sejak Jan 2026 — cek `references/sumber-sektoral.md`) |
| HAM | `komnasham.go.id` |
| Pengawasan etik hakim | `komisiyudisial.go.id` |

Lihat `references/sumber-peraturan.md`, `references/putusan-pengadilan.md`, dan `references/sumber-sektoral.md` untuk daftar lengkap per kategori beserta cara pakainya.

## Format Sitasi Hukum Indonesia yang Benar

Saat menyebut dasar hukum dalam jawaban, gunakan format standar:
- **Undang-Undang**: "Undang-Undang Nomor [X] Tahun [YYYY] tentang [Judul]" — disingkat "UU No. X/YYYY".
- **Perppu**: "Peraturan Pemerintah Pengganti Undang-Undang Nomor [X] Tahun [YYYY] tentang [Judul]".
- **Pasal**: gunakan format "Pasal [X] ayat ([Y]) huruf [z]" sesuai struktur aslinya.
- Jika UU sudah diubah beberapa kali, sebutkan versi konsolidasi terakhir, contoh: "UU No. 13 Tahun 2003 tentang Ketenagakerjaan sebagaimana diubah dengan UU No. 6 Tahun 2023 tentang Penetapan Perppu No. 2 Tahun 2022 tentang Cipta Kerja menjadi Undang-Undang".
- Untuk putusan pengadilan: "Putusan [Nama Pengadilan] Nomor [nomor register] tanggal [tanggal]" — untuk MK gunakan format nomor perkara seperti "Putusan MK Nomor 91/PUU-XVIII/2020".

Lihat `references/panduan-riset-dan-sitasi.md` untuk contoh lebih lengkap dan template kalimat.

## Batasan & Disclaimer

- Ini bukan pengganti advokat, notaris/PPAT, atau konsultan pajak. Untuk keputusan dengan konsekuensi hukum nyata (menandatangani kontrak, menghadapi somasi/gugatan, kasus pidana, transaksi properti/aset besar), sarankan konsultasi profesional secara natural di akhir jawaban.
- Perda tingkat kabupaten/kota sangat banyak dan tidak semuanya terindeks lengkap secara nasional — jika tidak ditemukan di `peraturan.go.id`/`jdihn.go.id`, coba JDIH pemerintah daerah terkait (`jdih.[namadaerah]kab.go.id` atau `jdih.[namadaerah]kota.go.id`) via web_search.
- Untuk pertanyaan yang menyentuh isu politis/kontroversial dalam pembentukan hukum (mis. UU Cipta Kerja, revisi KUHP, RUU yang masih dibahas), sajikan secara berimbang: apa isi ketentuannya, status legislasinya saat ini, dan — bila relevan — ringkas pro-kontra tanpa memihak opini pribadi.
