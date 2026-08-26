# Spesifik Pasar Saham Indonesia (IDX)

> **Navigasi lengkap & cara ambil data dari website resmi idx.co.id:** lihat `idx-coid-navigation.md` (peta URL, struktur path file laporan keuangan, periode TW1/TW2/TW3/audit, aksi korporasi, data pasar).

Catatan teknis yang sering salah kalau menganalisis saham Indonesia seolah-olah seperti saham AS.

## Jam perdagangan (WIB)
- Sesi I: 09:00 – 11:30 (Senin-Kamis), 09:00 – 11:30 (Jumat sedikit beda jam istirahat)
- Sesi II: 13:30 – 15:49 (Senin-Kamis), 14:00 – 15:49 (Jumat)
- Pre-closing & closing auction singkat di akhir sesi II.
- Selalu cek apakah "harga terkini" yang didapat dari pencarian web itu harga saat bursa buka (live) atau harga closing hari sebelumnya — nyatakan status ini di laporan.

## Format ticker
- Kode saham IDX: 4 huruf, mis. `BBCA`, `TLKM`, `ASII`, `BBRI`.
- Di Yahoo Finance & platform internasional, tambahkan `.JK`, mis. `BBCA.JK`.
- Jangan tertukar dengan ticker bursa lain yang mirip (mis. kode 3-4 huruf yang sama juga dipakai di bursa AS/Malaysia).

## Satuan perdagangan
- 1 lot = 100 lembar saham (sejak 2014). Harga yang di-quote adalah harga per lembar — kalikan 100 untuk nilai per lot.
- Fraksi harga (tick size) berjenjang tergantung rentang harga saham (aturan `Auto Rejection` & fraksi harga BEI berubah dari waktu ke waktu — jika relevan untuk order presisi, cek aturan terbaru di idx.co.id, jangan pakai angka dari ingatan lama).

## Auto Rejection (ARA/ARB)
- BEI menerapkan batas auto-reject atas (ARA) dan bawah (ARB) — persentase kenaikan/penurunan maksimum dalam sehari, besarannya berjenjang sesuai rentang harga dan bisa berubah kebijakan (pernah disesuaikan BEI di periode volatilitas tinggi). Jika user bertanya soal potensi pergerakan harga ekstrem harian, sebutkan konsep ARA/ARB tapi verifikasi persentase persis yang berlaku via `web_search` alih-alih mengasumsikan angka tetap.

## Aksi korporasi yang sering jadi katalis
- **Cum-date/Ex-date dividen**: harga biasanya turun sekitar nilai dividen per lembar pada ex-date.
- **Right issue (HMETD)**: dilusi kepemilikan, sering menekan harga jangka pendek meski tujuan jangka panjang bisa positif (mis. untuk ekspansi/bayar utang).
- **Stock split/reverse split**: tidak mengubah nilai fundamental, tapi memengaruhi likuiditas & psikologi harga.
- **Suspensi & UMA (Unusual Market Activity)**: BEI menghentikan sementara perdagangan saham yang bergerak tidak wajar — cek pengumuman resmi idx.co.id sebelum menyimpulkan alasan pergerakan ekstrem.
- Semua pengumuman resmi ada di idx.co.id menu *Berita* / *Keterbukaan Informasi*.

## Indeks acuan
- **IHSG (Indeks Harga Saham Gabungan)** — indeks utama, padanan S&P 500. Ticker Yahoo Finance: `^JKSE`.
- Indeks sektoral & IDX30/LQ45 (kumpulan saham likuid) juga sering dipakai sebagai pembanding relatif (benchmark alpha) — sebutkan performa relatif terhadap IHSG atau sektor, bukan cuma harga absolut.

## Sumber data yang lebih andal daripada default internasional
Yahoo Finance & agregator global kadang punya data lebih lambat/kurang lengkap untuk saham IDX kapitalisasi kecil-menengah. Prioritaskan:
1. **idx.co.id** — data resmi bursa, laporan keuangan wajib, pengumuman korporasi.
2. **RTI Business** (rti.co.id) — ringkasan data pasar & fundamental yang banyak dipakai analis retail Indonesia.
3. **Stockbit** — data pasar + forum diskusi (sentimen) dalam satu platform, populer di kalangan trader ritel Indonesia.

## Bahasa & satuan laporan keuangan
- Mayoritas emiten IDX melapor dalam **Rupiah (IDR)**, biasanya dalam satuan jutaan atau miliar rupiah — selalu cek satuan di header tabel laporan keuangan sebelum membandingkan angka antar-emiten.
- Sebagian emiten besar (terutama yang berbasis komoditas/ekspor) melapor dalam USD — jangan asumsikan semua dalam Rupiah.

## Pajak & biaya transaksi (konteks, bukan nasihat pajak)
- Ada bea materai, fee broker (beli & jual beda persentase), dan PPh final 0,1% dari nilai transaksi jual — relevan untuk menghitung estimasi biaya total sebuah trade, tapi selalu arahkan user ke broker/konsultan pajak untuk angka final karena ini bisa berubah kebijakan.
