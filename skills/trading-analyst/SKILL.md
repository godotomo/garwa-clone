---
name: trading-analyst
description: "Framework analisis trading multi-agen untuk saham (termasuk Bursa Efek Indonesia/IDX), forex, dan kripto, diadaptasi dari arsitektur TradingAgents (TauricResearch), plus lapisan analisis kuantitatif ala hedge fund (VaR, CVaR/Expected Shortfall, simulasi Monte Carlo, Sharpe/Sortino/Calmar ratio, maximum drawdown, Kelly Criterion, optimasi portofolio Markowitz). Gunakan skill ini setiap kali user meminta analisis saham/emiten, sinyal beli-jual, riset kripto atau pair forex, rekomendasi trading, analisis teknikal (RSI/MACD/dsb), analisis fundamental emiten, analisis risiko kuantitatif/matematis, VaR/CVaR, simulasi Monte Carlo, position sizing, atau menyebut ticker/kode saham (mis. BBCA, TLKM, BTC-USD, USDIDR, AAPL) dengan maksud trading/investasi — bahkan jika user tidak secara eksplisit mengatakan 'analisis'. Selalu picu skill ini juga saat user bertanya soal data harga historis, laporan keuangan emiten, sentimen pasar, kalender ekonomi, atau manajemen risiko portofolio untuk keperluan trading."
---

# Trading Analysis (Multi-Agent, ala TradingAgents)

Skill ini mereplikasi *alur kerja* framework open-source [TradingAgents](https://github.com/TauricResearch/TradingAgents) — bukan menjalankan kodenya secara langsung, tapi meniru pipeline analitisnya secara manual menggunakan tool riset yang tersedia (`web_search`, `webfetch`, `bash` untuk komputasi). Cocok untuk saham AS/global, **saham Indonesia (IDX)**, forex, dan kripto.

## ⚠️ Wajib disampaikan di setiap laporan

Skill ini adalah alat riset, **bukan nasihat keuangan**. Sertakan disclaimer singkat di akhir setiap laporan (lihat `references/report-template.md`). Jangan pernah menyatakan rekomendasi sebagai kepastian — selalu sertakan tingkat keyakinan dan risiko.

## Alur kerja inti

TradingAgents membagi analisis menjadi tim-tim khusus yang saling berdebat sebelum keputusan akhir diambil. Ikuti urutan ini setiap kali diminta analisis:

```
1. TIM ANALIS (kumpulkan data mentah, per domain)
   ├── Analis Fundamental   → laporan keuangan, rasio valuasi
   ├── Analis Teknikal      → harga historis, indikator (RSI/MACD/BB)
   ├── Analis Berita        → berita makro & korporat
   └── Analis Sentimen      → media sosial, forum, sentimen pasar
        ↓
2. TIM RISET (perdebatan terstruktur)
   ├── Peneliti Bullish     → argumen terkuat untuk NAIK
   └── Peneliti Bearish     → argumen terkuat untuk TURUN
        ↓
3. TRADER
   → menyintesis semua laporan jadi satu proposal aksi konkret
     (entry, ukuran posisi, stop-loss, take-profit)
        ↓
4. TIM MANAJEMEN RISIKO (perdebatan terstruktur + data kuantitatif)
   ├── Risk-taker agresif
   ├── Risk-taker konservatif
   ├── Risk-taker netral
   └── Input kuantitatif: VaR, CVaR, Monte Carlo, Sharpe/Sortino, max drawdown
        ↓
5. MANAJER PORTOFOLIO
   → keputusan akhir: SETUJU / TOLAK / SESUAIKAN, plus laporan lengkap
```

Detail peran, prompt internal, dan format debat masing-masing tim ada di `references/agents-framework.md`. **Baca file itu sebelum menjalankan analisis penuh** — jangan improvisasi struktur pipeline.

Untuk Analis Berita (tahap 1), jangan lupa cek **faktor eksternal** (politik/geopolitik & cuaca/iklim) yang sering jadi katalis besar di luar fundamental/teknikal murni — khususnya untuk komoditas, forex, dan pasar berkembang seperti Indonesia. Panduan lengkapnya di `references/external-factors.md`.

Untuk analisis cepat/ringan (user hanya minta "cek RSI BBCA" atau "harga BTC sekarang"), tidak perlu menjalankan seluruh 5 tahap — cukup jawab langsung dengan data yang relevan, tapi tetap ikuti metode pengambilan data di bawah.

## Pengambilan data — poin paling kritis

**Batasan penting**: `bash` di sandbox ini **tidak** memiliki akses jaringan ke situs finansial (Yahoo Finance, IDX, Binance, dll — daftar domain yang diizinkan hanya mencakup PyPI/npm/GitHub). Artinya kamu **tidak bisa** `pip install yfinance` lalu memanggil API-nya langsung dan berharap dapat koneksi keluar.

Sebagai gantinya, semua pengambilan data **harus** lewat `web_search` + `webfetch` (tool pencarian web bawaan Garwa, yang punya akses jaringan sendiri di luar sandbox), lalu data numerik yang sudah didapat baru diproses secara lokal (mis. hitung RSI dengan pandas di `bash`).

Baca `references/data-sources.md` untuk panduan lengkap: query pencarian persis, situs mana untuk aset apa, urutan fallback antar-sumber, dan cara memverifikasi data. Ringkasan sangat singkat:

| Kelas Aset | Sumber Harga Utama | Sumber Fundamental | Sumber Berita | Sumber Sentimen |
|---|---|---|---|---|
| Saham AS/Global | Yahoo Finance, Stooq | Yahoo Finance Statistics, stockanalysis.com, SEC EDGAR | Reuters, Bloomberg, IR resmi | StockTwits, Reddit |
| **Saham Indonesia (IDX)** | Yahoo Finance (`.JK`), IDX resmi, RTI Business | Laporan Keuangan IDX (idx.co.id), RTI, Stockbit | Kontan, Bisnis.com, CNBC Indonesia, Investor Daily | Stockbit, X/Twitter cashtag |
| Forex | Yahoo Finance (`XXXYYY=X`), Investing.com | Kalender ekonomi (Investing.com, ForexFactory) | Reuters, DailyFX, Bank Indonesia/Fed/ECB | COT Report (CFTC), DailyFX sentiment |
| Kripto | CoinGecko, CoinMarketCap, Yahoo Finance (`XXX-USD`) | CoinGecko (tokenomics), Messari | CryptoPanic, CoinDesk, X | Fear & Greed Index, Reddit, X |

Untuk saham Indonesia secara khusus, baca `references/indonesia-market.md` — ada catatan soal jam bursa, suffix ticker, satuan (lot), auto-reject, dan sumber yang lebih andal daripada default Yahoo Finance. Untuk mengambil laporan keuangan & pengumuman langsung dari **website resmi idx.co.id** (termasuk struktur path file PDF/XLSX/XBRL per periode TW1/TW2/TW3/audit), baca `references/idx-coid-navigation.md`.

> **Membaca laporan keuangan (IDX):** laporan keuangan emiten di idx.co.id tersedia sebagai file mentah (`.xlsx` / `.pdf`, atau XBRL). Untuk analisa fundamental, agen harus membaca isi file tersebut dan mengekstrak neraca, laba rugi, dan arus kas. Jangan menebak isi file — jika file tidak bisa dibaca bersih, laporkan keterbatasan dan fallback ke RTI/Stockbit. Instruksi lengkap di `references/idx-coid-navigation.md` §2.7.

## Mencegah look-ahead bias (aturan tanggal)

TradingAgents secara eksplisit "mengunci" tanggal analisis dan memfilter data agar tidak memakai informasi dari masa depan relatif terhadap tanggal itu. Terapkan hal yang sama:

- Tetapkan **tanggal analisis** di awal (default: hari ini, atau tanggal yang diminta user).
- Saat mengutip laporan keuangan/berita, selalu cek tanggal publikasinya — abaikan yang terbit setelah tanggal analisis jika user meminta analisis historis/backtest.
- Cantumkan **waktu pengambilan data** (timestamp pencarian) di laporan akhir, karena harga real-time dari web search bisa delay beberapa menit — ingatkan user untuk cek harga live di broker/exchange sebelum eksekusi order sungguhan.

## Indikator teknikal

Jangan minta LLM "menghitung" RSI/MACD dari ingatan — itu tidak akurat. Alurnya:
1. Kumpulkan data historis OHLCV (harga open/high/low/close/volume) lewat `web_search` + `webfetch` (lihat `references/data-sources.md`).
2. Susun jadi tabel/CSV di dalam `bash`.
3. Jalankan `scripts/compute_indicators.py` (butuh `pandas`, `numpy` — install dengan `pip install pandas numpy --break-system-packages` bila belum ada) untuk menghitung SMA/EMA/RSI/MACD/Bollinger Bands/ATR secara presisi.
4. Baca `references/technical-indicators.md` untuk interpretasi tiap indikator (bukan cuma angka mentah).

## Analisis kuantitatif ala hedge fund (VaR, CVaR, Monte Carlo, dkk.)

Untuk analisis yang lebih dalam dari sekadar teknikal/fundamental — terutama saat user bertanya soal **risiko portofolio, ukuran posisi, atau "seberapa besar saya bisa rugi"** — tambahkan lapisan kuantitatif ke Tim Manajemen Risiko (tahap 4 di pipeline). Ini mencakup:

- **VaR & CVaR/Expected Shortfall** (metode historical, parametric, dan Monte Carlo)
- **Simulasi Monte Carlo** (proyeksi distribusi harga/return N hari ke depan, model Geometric Brownian Motion)
- **Rasio kinerja disesuaikan risiko**: Sharpe, Sortino, Calmar
- **Maximum drawdown** (besaran & durasi)
- **Kelly Criterion** untuk referensi position sizing
- **Korelasi & optimasi portofolio** (Markowitz mean-variance) untuk pertanyaan multi-aset
- **Skewness/kurtosis** (fat tails) dan **stress testing** skenario historis

Baca `references/quant-risk-analysis.md` untuk formula, interpretasi, dan keterbatasan tiap metode — **jangan hitung ini secara mental**, selalu jalankan `scripts/quant_risk.py` di atas data harga historis yang sudah dikumpulkan lewat `web_search`/`webfetch`.

## Format laporan akhir

Gunakan struktur di `references/report-template.md` — meniru laporan akhir Portfolio Manager di TradingAgents: ringkasan eksekutif, temuan tiap tim analis, ringkasan debat bull/bear, penilaian risiko, dan keputusan akhir dengan tingkat keyakinan. Sajikan sebagai jawaban percakapan biasa (bukan file) kecuali user secara eksplisit minta laporan disimpan sebagai dokumen — dalam hal itu, ikuti skill `docx` atau `xlsx` sesuai kebutuhan format.

## Referensi cepat

- `references/agents-framework.md` — peran tiap agen, format debat bull/bear dan risk tiers
- `references/data-sources.md` — **panduan detail pengambilan data** per kelas aset (baca ini untuk pertanyaan "cara ambil datanya")
- `references/indonesia-market.md` — spesifik pasar saham Indonesia/IDX
- `references/idx-coid-navigation.md` — **peta URL & cara ambil data resmi dari idx.co.id** (struktur path file laporan keuangan, periode TW1/TW2/TW3/audit, aksi korporasi, data pasar)
- `references/technical-indicators.md` — formula & interpretasi indikator teknikal
- `references/quant-risk-analysis.md` — **VaR, CVaR, Monte Carlo, Sharpe/Sortino/Calmar, Kelly Criterion, optimasi portofolio** ala hedge fund
- `references/report-template.md` — template laporan akhir
- `references/external-factors.md` — **faktor eksternal** (politik/geopolitik & cuaca/iklim) yang sering diabaikan tapi bisa jadi katalis besar, khususnya untuk komoditas, forex, dan pasar berkembang seperti Indonesia
- `scripts/compute_indicators.py` — skrip Python untuk menghitung indikator dari data OHLCV
- `scripts/quant_risk.py` — skrip Python untuk VaR/CVaR/Monte Carlo/rasio risiko (aset tunggal & portofolio multi-aset)
