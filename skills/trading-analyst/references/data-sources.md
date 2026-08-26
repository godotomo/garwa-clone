# Pengambilan Data — Panduan Detail

Referensi ini menjelaskan **cara persis** mengambil setiap jenis data yang dipakai TradingAgents (harga/OHLCV, fundamental, berita, sentimen, indikator, makro), diadaptasi untuk lingkungan Garwa yang hanya punya `web_search` dan `webfetch` sebagai jalur jaringan ke situs finansial (`bash` tidak bisa mengakses domain finansial).

## Prinsip umum

1. **Selalu `web_search` dulu, baru `webfetch`.** `webfetch` hanya bisa membuka URL yang sudah muncul di percakapan (dari user atau dari hasil `web_search` sebelumnya) — tidak bisa menebak/menyusun URL API secara langsung.
2. **Silangkan (cross-check) angka kritis** — terutama harga dan rasio valuasi — dengan minimal 2 sumber independen jika akan dipakai sebagai dasar keputusan beli/jual. Satu sumber cukup untuk konteks umum (mis. ringkasan berita).
3. **Catat timestamp.** Harga dari hasil pencarian web punya delay (biasanya 15 menit sampai beberapa jam). Selalu nyatakan "data per [waktu]" di laporan, dan untuk kripto/forex yang bergerak cepat, ingatkan user untuk mengecek harga live di exchange/broker sebelum eksekusi.
4. **Ikuti aturan hak cipta**: parafrasekan isi berita, jangan kutip lebih dari kebutuhan. Angka/data (harga, rasio, volume) bukan masalah hak cipta, tapi narasi analisis dari sumber pihak ketiga harus ditulis ulang dengan kata sendiri.
5. **Vendor fallback (seperti router data di TradingAgents asli):** jika sumber utama gagal (blocked, paywall, data kosong), pindah ke sumber berikutnya di daftar — jangan mengarang angka.

---

## A. Saham AS / Global

**Harga & OHLCV**
- Query: `"[TICKER] stock price"` atau `"[TICKER] historical prices yahoo finance"` → `webfetch` halaman Yahoo Finance (`finance.yahoo.com/quote/[TICKER]` dan tab `/history`).
- Alternatif/cross-check: `stooq.com`, `marketwatch.com/investing/stock/[ticker]`, `google.com/finance`.
- Untuk data historis dalam jumlah besar (mis. 1 tahun harian untuk hitung indikator), cari `"[TICKER] historical data csv download"` — beberapa penyedia (Stooq) menyediakan tautan unduhan CSV yang bisa langsung di-`webfetch`.

**Fundamental (laporan keuangan & rasio)**
- Query: `"[TICKER] balance sheet income statement"`, `"[TICKER] financial ratios PE PB ROE"`.
- Sumber: `stockanalysis.com/stocks/[TICKER]`, tab *Statistics*/*Financials* di Yahoo Finance, `sec.gov` (EDGAR, untuk laporan 10-K/10-Q resmi emiten AS).
- Ambil minimal: pendapatan (revenue), laba bersih, EPS, P/E, P/B, debt-to-equity, free cash flow, margin.

**Berita**
- Query: `"[TICKER] news [bulan tahun]"` atau `"[nama perusahaan] latest news"`.
- Sumber: Reuters, Bloomberg, halaman *Newsroom*/*Investor Relations* resmi perusahaan, `finance.yahoo.com/quote/[TICKER]/news`.
- Fokus pada: rilis laba (earnings), panduan manajemen (guidance), merger/akuisisi, perubahan regulasi.

**Sentimen sosial**
- Query: `"[TICKER] stocktwits sentiment"`, `"[TICKER] reddit wallstreetbets"`.
- Sumber: `stocktwits.com/symbol/[TICKER]`, subreddit terkait (r/stocks, r/wallstreetbets, r/investing) via pencarian.
- Perlakukan sentimen sosial sebagai indikator *mood jangka pendek*, bukan sinyal fundamental — selalu beri bobot lebih kecil dibanding data fundamental/teknikal.

---

## B. Saham Indonesia (IDX) — lihat juga `indonesia-market.md` dan `idx-coid-navigation.md`

**Harga & OHLCV**
- Ticker Yahoo Finance untuk saham IDX memakai akhiran `.JK`, contoh: `BBCA.JK`, `TLKM.JK`, `BBRI.JK`, `ASII.JK`.
- Query: `"[KODE].JK stock price yahoo finance"` atau `"harga saham [KODE] hari ini"`.
- Sumber resmi paling andal: **idx.co.id** (menu *Data Pasar* → *Ringkasan Perdagangan* / *Statistik*), `rti.co.id` (RTI Business), `stockbit.com/symbol/[KODE]`, `investing.com` versi Indonesia.
- Yahoo Finance kadang delay/kurang akurat untuk saham IDX kapitalisasi kecil — jika hasilnya meragukan, prioritaskan idx.co.id atau RTI.

**Fundamental & laporan keuangan**
- Sumber resmi: **idx.co.id** → *Perusahaan Tercatat* → cari kode emiten → *Laporan Keuangan* (laporan triwulanan/tahunan resmi, wajib dilaporkan ke OJK/BEI).
- Sumber ringkasan/rasio siap pakai: `rti.co.id`, `stockbit.com` (tab *Fundamental*), `stockanalysis.com` (sebagian emiten besar IDX juga tercakup).
- Query contoh: `"laporan keuangan [KODE] idx.co.id"`, `"[nama emiten] laba bersih kuartal [Q] [tahun]"`.
- Perhatikan mata uang laporan (banyak emiten melapor dalam Rupiah, tapi sebagian dalam USD) — selalu cek satuan sebelum membandingkan rasio.

**Berita**
- Sumber utama: **Kontan.co.id**, **Bisnis.com**, **CNBC Indonesia**, **Investor Daily**, **Katadata**, `kompas.com/ekonomi`, `idnfinancials.com` (versi bahasa Inggris untuk investor asing).
- Query: `"[KODE] berita saham"`, `"[nama emiten] RUPS"`, `"[nama emiten] right issue"`, `"[nama emiten] dividen"`.
- Perhatikan aksi korporasi khas IDX: **cum-date/ex-date dividen**, **right issue**, **stock split**, **suspensi/UMA (Unusual Market Activity)** — semuanya diumumkan resmi di idx.co.id dan sering jadi katalis harga jangka pendek.

**Sentimen**
- **Stockbit** adalah padanan terdekat dengan StockTwits untuk pasar Indonesia — forum diskusi per-saham aktif. Query: `"stockbit [KODE] diskusi"`.
- X/Twitter: cari cashtag `$[KODE]` atau nama emiten + "saham".
- Perlakukan sentimen forum retail Indonesia dengan hati-hati — volume diskusi bisa dimanipulasi (pom-pom saham gorengan), jangan jadikan satu-satunya dasar keputusan.

**Data makro Indonesia**
- **Bank Indonesia** (`bi.go.id`): BI-Rate/BI Rate acuan, kurs referensi JISDOR (USD/IDR resmi).
  - **Statistik moneter lengkap**: `https://www.bi.go.id/id/statistik/Default.aspx` — pusat data statistik BI (suku bunga, inflasi, uang beredar/M2, cadangan devisa, neraca pembayaran, kredit perbankan, dsb.). Ambil dengan `webfetch`; banyak tabel tersedia sebagai file unduhan (Excel/PDF) yang bisa dibaca di `bash` (lihat `idx-coid-navigation.md` §2.7 untuk teknik ekstraksi xlsx/pdf/zip yang sama).
  - Untuk data yang lebih terstruktur, BI juga menyediakan **API/Statistik Terkini** (`bi.go.id` → Statistik → Statistik Terkini) — jika endpoint muncul di hasil `web_search`, boleh langsung di-`webfetch`; jangan menyusun URL dari ingatan.
- **BPS** (`bps.go.id`): inflasi (IHK), pertumbuhan PDB.
- **OJK** (`ojk.go.id`): regulasi sektor keuangan, status pengawasan emiten.

---

## C. Forex

**Harga**
- Pair ditulis format Yahoo Finance: `USDIDR=X`, `EURUSD=X`, `USDJPY=X`.
- Query: `"[PAIR] exchange rate live"` atau `"[PAIR]=X yahoo finance"`.
- Sumber: Yahoo Finance, `investing.com/currencies/[pair]`, `xe.com`, `dailyfx.com`.
- Untuk kurs resmi USD/IDR: **JISDOR Bank Indonesia** (`bi.go.id`) adalah rujukan resmi pemerintah, meski market rate riil di money changer/bank bisa sedikit berbeda.

**Fundamental (makro, bukan laporan keuangan perusahaan)**
- Kalender ekonomi: `investing.com/economic-calendar`, `forexfactory.com/calendar` — cari rilis suku bunga, inflasi (CPI), NFP (non-farm payroll AS), PDB.
- Pernyataan bank sentral: Federal Reserve (`federalreserve.gov`), ECB (`ecb.europa.eu`), Bank Indonesia (`bi.go.id`).
- Query: `"[negara] interest rate decision [bulan tahun]"`, `"Fed FOMC statement latest"`.

**Berita**
- Reuters (kategori *Markets/Currencies*), Bloomberg, DailyFX, Investing.com.

**Sentimen/positioning**
- **COT Report (Commitment of Traders)** dari CFTC (`cftc.gov`) — data posisi net-long/net-short trader institusional, dirilis mingguan, berguna untuk melihat positioning besar di pasar futures forex.
- Sentimen ritel: `dailyfx.com/sentiment` (IG Client Sentiment).

---

## D. Kripto

**Harga & data pasar**
- Query: `"[nama koin] price coingecko"` atau `"[SYMBOL]-USD yahoo finance"`.
- Sumber: **CoinGecko** (`coingecko.com/en/coins/[nama-koin]`) — mencakup market cap, volume 24 jam, supply; **CoinMarketCap** (`coinmarketcap.com`); Yahoo Finance format `BTC-USD`, `ETH-USD`; Binance (`binance.com`, halaman market pair — data harga real-time exchange terbesar by volume).
- CoinGecko juga punya API publik dengan endpoint sederhana (mis. `/api/v3/simple/price`) — jika endpoint tersebut muncul di hasil `web_search`, boleh langsung di-`webfetch` untuk data JSON yang bersih; jangan menyusun sendiri URL API dari ingatan.

**Fundamental/tokenomics (padanan "laporan keuangan" untuk kripto)**
- Query: `"[nama koin] tokenomics supply"`, `"[nama koin] whitepaper"`.
- Sumber: halaman CoinGecko/CoinMarketCap (tab *Tokenomics*), `messari.io` (profil aset lebih mendalam), situs resmi proyek/whitepaper.
- Perhatikan: total supply vs circulating supply, jadwal unlock/vesting token (katalis penting untuk tekanan jual), mekanisme konsensus.

**Berita**
- Sumber: `cryptopanic.com` (agregator berita kripto), `coindesk.com`, `theblock.co`.
- Query: `"[nama koin] news [bulan tahun]"`.

**Sentimen**
- **Crypto Fear & Greed Index** (`alternative.me/crypto/fear-and-greed-index`) — indikator sentimen pasar kripto agregat 0-100, update harian.
- Reddit (r/CryptoCurrency, subreddit koin spesifik), X/Twitter cashtag `$BTC` dsb.
- On-chain sentiment ringkas (opsional, untuk analisis lebih dalam): `glassnode.com`, `cryptoquant.com` (banyak metrik gratis terbatas, sebagian butuh langganan — gunakan ringkasan publik yang muncul di artikel berita jika data mentah tidak bisa diakses).

---

## Ringkasan urutan fallback per kategori data

| Kategori | Prioritas 1 | Prioritas 2 | Prioritas 3 |
|---|---|---|---|
| Harga saham AS | Yahoo Finance | Stooq | MarketWatch |
| Harga saham IDX | idx.co.id | RTI Business | Yahoo Finance `.JK` |
| Fundamental IDX | idx.co.id (laporan resmi) | RTI/Stockbit | stockanalysis.com |
| Harga forex | Yahoo Finance `=X` | Investing.com | XE.com |
| Harga kripto | CoinGecko | Yahoo Finance | CoinMarketCap |
| Berita umum | Reuters/Bloomberg | Media lokal (Kontan/CNBC ID) | Agregator (Google News) |
| Sentimen | StockTwits/Stockbit | Reddit/X | Fear & Greed Index (khusus kripto) |
| Data makro Indonesia | bi.go.id (statistik) | BPS (bps.go.id) | OJK/Kontan |
