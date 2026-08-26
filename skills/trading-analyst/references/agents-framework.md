# Kerangka Multi-Agen (adaptasi dari TradingAgents)

TradingAgents asli menjalankan tiap peran ini sebagai agen LLM terpisah dalam graph LangGraph. Di sini, kamu (Garwa) memerankan setiap peran **secara berurutan dalam satu respons/percakapan** — beri header yang jelas untuk tiap bagian supaya user bisa mengikuti alur penalarannya, seperti membaca notulen rapat tim trading.

## 1. Tim Analis

Empat analis bekerja paralel (secara konseptual), masing-masing hanya fokus ke domainnya — jangan campur aduk.

**Analis Fundamental**
- Tugas: evaluasi kesehatan keuangan & valuasi. Cari red flags (utang naik cepat, margin turun, arus kas negatif berulang).
- Output: ringkasan rasio kunci (P/E, P/B, ROE, D/E, margin, pertumbuhan pendapatan) + interpretasi apakah valuasi mahal/wajar/murah relatif terhadap sektor & histori.
- **Untuk saham Indonesia (IDX):** analisis fundamental **harus** berbasis laporan keuangan resmi emiten, bukan sekadar angka valuasi dari agregator. Ambil laporan keuangan dari idx.co.id (file `.xlsx` / `.pdf`, atau XBRL), lalu **baca isi file mentahnya** untuk mengekstrak neraca, laba rugi, dan arus kas — lihat `idx-coid-navigation.md` §2.6–2.7 untuk alur unduh + cara membaca laporan keuangan. Jangan mengarang angka laporan keuangan — kalau file tidak bisa dibaca bersih, laporkan keterbatasan dan fallback ke RTI/Stockbit.

**Analis Teknikal**
- Tugas: baca pola harga & indikator (lihat `technical-indicators.md`).
- Output: level support/resistance, tren (naik/turun/sideways), sinyal dari RSI/MACD/Bollinger Bands, volume yang mengonfirmasi/tidak mengonfirmasi tren.

**Analis Berita**
- Tugas: pantau berita korporat & makro yang relevan dengan aset.
- Output: 3-5 berita paling material (bukan daftar lengkap semua berita), dengan penjelasan singkat dampak potensialnya ke harga.

**Analis Sentimen**
- Tugas: agregasi sentimen dari forum/sosial media jadi satu pembacaan mood pasar jangka pendek.
- Output: sentimen dominan (bullish/bearish/campur), disertai catatan kalau ada tanda manipulasi/pom-pom.
- **Penting**: jangan mengarang postingan sosial media. Jika tidak menemukan data sentimen nyata via `web_search`, katakan terus terang datanya terbatas — jangan fabrikasi kutipan forum.

## 2. Tim Peneliti — Debat Bull vs Bear

Setelah laporan 4 analis di atas selesai, buat **debat terstruktur** dua sisi:

- **Peneliti Bullish**: susun argumen terkuat untuk kenaikan harga, menarik dari temuan analis yang mendukung (fundamental kuat, momentum teknikal positif, sentimen positif, katalis berita positif).
- **Peneliti Bearish**: susun argumen terkuat untuk penurunan harga dari temuan yang sama.

Format sebagai 2-3 putaran singkat saling counter (bukan cuma dua paragraf statis) — bullish menyampaikan poin, bearish membalas poin spesifik itu, lalu sebaliknya. Ini meniru *structured debate* di TradingAgents yang tujuannya menghindari bias konfirmasi satu arah.

## 3. Trader

Sintesis semua di atas jadi **satu proposal aksi konkret**, bukan opini umum. Wajib mencakup:
- Aksi: BUY / SELL / HOLD
- Level entry yang diusulkan (atau range)
- Stop-loss (level & alasan, mis. di bawah support terdekat)
- Take-profit (level & alasan)
- Ukuran posisi relatif (mis. "kecil/eksploratif" vs "penuh sesuai rencana") — jangan sarankan persentase modal pasti karena Garwa tidak tahu profil risiko/modal user secara detail kecuali diberi tahu.

## 4. Tim Manajemen Risiko — Debat Tiga Sisi

Tiga persona meninjau proposal Trader dari sudut pandang berbeda:
- **Agresif**: dorong ambil risiko lebih besar jika sinyal kuat, argumen soal potensi upside yang terlewat.
- **Konservatif**: soroti risiko yang mungkin diremehkan, argumen untuk posisi lebih kecil/menunggu konfirmasi tambahan.
- **Netral**: menengahi, cari titik keseimbangan berdasar horizon waktu & volatilitas aset.

Ringkas tiap pandangan 1-2 kalimat — ini bukan debat panjang seperti bull/bear, lebih ke tiga sudut pandang cepat sebelum keputusan akhir.

## 5. Manajer Portofolio — Keputusan Akhir

Timbang seluruh laporan + hasil debat, keluarkan keputusan akhir dengan format di `report-template.md`. Manajer Portofolio **boleh menolak atau memodifikasi** proposal Trader kalau tim risiko memberi alasan kuat — jangan otomatis meng-copy proposal Trader mentah-mentah.

## Reflection / decision log (opsional, kalau relevan)

TradingAgents asli menyimpan log keputusan lintas sesi untuk belajar dari hasil sebelumnya. Di konteks percakapan Garwa, versi sederhananya: jika user sebelumnya di percakapan yang sama sudah minta analisis ticker yang sama dan ada perkembangan baru, secara eksplisit bandingkan dengan analisis sebelumnya ("dibanding analisis sebelumnya, RSI sudah keluar dari zona oversold, jadi...") daripada mengulang dari nol tanpa konteks.
