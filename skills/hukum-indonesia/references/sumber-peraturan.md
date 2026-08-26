# Sumber Resmi — Peraturan Perundang-undangan

Gunakan `web_search` untuk menemukan halaman spesifik (mis. "UU No 13 Tahun 2003 peraturan.go.id"), lalu `web_fetch` URL hasilnya untuk membaca detail (status, tanggal, lampiran PDF).

## Portal Nasional (prioritas utama)

- **peraturan.go.id** — Database resmi Ditjen Peraturan Perundang-undangan, Kementerian Hukum. Situs paling lengkap untuk UU, Perppu, PP, Perpres, Permen, Peraturan Badan/Lembaga, dan Perda pusat maupun daerah. Menampilkan status "Berlaku"/"Tidak Berlaku"/"Diubah", relasi antar-peraturan (mengubah/dicabut oleh/melaksanakan), dan link download PDF resmi. Juga memuat terjemahan resmi bahasa Inggris untuk sebagian peraturan (`peraturan.go.id/terjemahresmi`) dan ringkasan Putusan MK.
  - Pencarian global: `peraturan.go.id/cariglobal`
  - Daftar per jenis: `peraturan.go.id/all`
- **jdihn.go.id** — Jaringan Dokumentasi dan Informasi Hukum Nasional (JDIHN), portal gabungan yang mengagregasi dokumen hukum dari seluruh anggota JDIHN (kementerian, lembaga, pemda, pengadilan, perguruan tinggi). Berguna saat suatu peraturan/putusan tidak ditemukan di peraturan.go.id, karena mencakup dokumen sekunder seperti monografi hukum, artikel, dan naskah akademik juga. Dikoordinasikan oleh BPHN (Badan Pembinaan Hukum Nasional), Kementerian Hukum.
- **peraturan.bpk.go.id** dan **jdih.bpk.go.id** — Database Peraturan BPK, versi lain yang sering lebih cepat ter-update dan menyertakan salinan lengkap putusan MK (uji materi) dalam format PDF terpindai/teks. Berguna sebagai cross-check kedua jika peraturan.go.id tidak lengkap.

## JDIH Kementerian/Lembaga (untuk peraturan teknis internal instansi)

Hampir setiap kementerian dan lembaga negara punya portal JDIH sendiri dengan pola URL `jdih.[namainstansi].go.id`. Contoh yang sering dibutuhkan:
- `jdih.setneg.go.id` — Kementerian Sekretariat Negara
- `jdih.kemlu.go.id` — Kementerian Luar Negeri
- `jdih.kemenkeu.go.id` — Kementerian Keuangan
- `jdih.kemnaker.go.id` — Kementerian Ketenagakerjaan
- `jdih.kemendagri.go.id` — Kementerian Dalam Negeri
- `jdih.kemenkes.go.id` — Kementerian Kesehatan
- `jdih.polri.go.id` — Kepolisian RI

**Cara mencari yang benar**: jangan menebak-nebak URL dari ingatan — gunakan `web_search` dengan pola `"jdih [nama instansi]"` untuk memastikan domain yang benar dan masih aktif, karena beberapa instansi mengganti platform JDIH mereka dari waktu ke waktu.

## JDIH Pemerintah Daerah

Pola serupa: `jdih.[namadaerah]prov.go.id` (provinsi) atau `jdih.[namadaerah]kab.go.id` / `jdih.[namadaerah]kota.go.id` (kabupaten/kota). Gunakan ini untuk mencari Perda, Pergub/Perbup/Perwali, dan produk hukum daerah lain yang seringkali tidak lengkap terindeks di peraturan.go.id.

## Naskah Akademik & Proses Legislasi

- **dpr.go.id** — Dewan Perwakilan Rakyat: status RUU yang sedang dibahas, daftar Program Legislasi Nasional (Prolegnas), risalah rapat.
- **bphn.go.id** — Badan Pembinaan Hukum Nasional: naskah akademik, kajian hukum, publikasi pembangunan hukum nasional.
- **setkab.go.id** — Sekretariat Kabinet: siaran pers dan info kebijakan pemerintah terbaru yang sering mendahului terbitnya peraturan resmi.

## Sumber Sekunder (boleh untuk konteks, bukan sumber primer)

- **hukumonline.com** — Media hukum terbesar di Indonesia, punya pusat data peraturan (Pusat Data) dan analisis. Bagus untuk ringkasan/analisis tren, tapi selalu verifikasi bunyi pasal ke sumber primer di atas.
- Jurnal hukum kampus (mis. `journal.uii.ac.id`, jurnal fakultas hukum UI/UGM/Unpad) — untuk analisis akademik mendalam suatu isu, bukan untuk mengecek status peraturan.

## Tips Praktis

- Jika mencari peraturan dengan nomor/tahun spesifik, query yang efektif: `"[jenis peraturan] nomor [X] tahun [YYYY] peraturan.go.id"`.
- Selalu perhatikan bagian "status" pada peraturan.go.id: peraturan yang "Tidak Berlaku" biasanya masih muncul di hasil pencarian tapi tidak boleh dijadikan dasar hukum aktif — cek peraturan pengganti/perubahannya.
- Untuk UU besar yang sering direvisi (KUHP, Ketenagakerjaan, Perpajakan, Cipta Kerja), selalu cek apakah ada UU/Perppu "omnibus" terbaru yang mengubahnya sebelum mengutip pasal versi lama.
