# Berita Kripto, Berita Makro Global & Analisis Sentimen

## 1. Crypto Fear & Greed Index — Alternative.me (Keyless / Tanpa API Key)
Endpoint API:
```http
GET [https://api.alternative.me/fng/?limit=1](https://api.alternative.me/fng/?limit=1)               # Nilai hari ini
GET [https://api.alternative.me/fng/?limit=30&format=json](https://api.alternative.me/fng/?limit=30&format=json)    # 30 hari terakhir (untuk tren)

```

Respons Utama: `value` (0–100), `value_classification` ("Extreme Fear" s/d "Extreme Greed"), `timestamp`. Index ini mengombinasikan data volatilitas, momentum/volume, media sosial, dominasi BTC, dan tren pencarian web sebagai indikator sentimen pasar kripto secara keseluruhan.

Panduan Interpretasi:

* **0–24 (Extreme Fear)**: Secara historis sering menjadi zona akumulasi, tetapi dapat mengindikasikan tren penurunan (*downtrend*) yang kuat. Jangan menginterpretasikan secara otomatis sebagai sinyal beli.
* **75–100 (Extreme Greed)**: Pasar rentan mengalami koreksi akibat euforia berlebihan, meskipun *bull market* yang kuat dapat bertahan di zona ini dalam rentang waktu yang lama.
* **Analisis Tren**: Bandingkan nilai hari ini dengan nilai 7 atau 30 hari sebelumnya untuk mengidentifikasi arah perubahan sentimen secara tepat.

## 2. CryptoPanic API — Agregator Berita & Sentimen Komunitas (API Key Gratis)

Portal Pendaftaran: `cryptopanic.com/developers`

Endpoint API (v2):

```http
GET [https://cryptopanic.com/api/v2/posts/?auth_token=](https://cryptopanic.com/api/v2/posts/?auth_token=){TOKEN}&currencies=BTC,ETH&filter=hot

```

Parameter Penting:

* `filter`: `rising` | `hot` | `bullish` | `bearish` | `important` | `saved` | `lol` (Filter berdasarkan agregasi *voting* komunitas).
* `currencies`: `BTC,ETH,SOL` (Filter berita per aset menggunakan ticker, dipisahkan koma).
* `kind`: `news` | `media` (Jenis konten sumber).

Setiap entri memuat data `votes` (bullish, bearish, important, toxic, dll.) dari pengguna sebagai indikator sentimen agregat *crowd-sourced* yang valid untuk dikombinasikan dengan Fear & Greed Index.

*Alternatif Pengambilan Data*: Jika tidak tersedia API key, gunakan fitur pencarian web (`web_search` / `webfetch`) untuk mengambil berita terkini dari media utama (CoinDesk, Cointelegraph, The Block, Decrypt) dengan menerapkan prinsip sitasi yang benar (paragraf ringkasan, hindari penggandaan teks secara utuh).

## 3. Pemantauan Berita Makro Global & Faktor Pasar

Untuk data makroekonomi yang tidak menyediakan API terbuka, manfaatkan pencarian web (`web_search`) dengan fokus pada indikator kunci berikut:

* **Kebijakan Moneter & The Fed**: Keputusan suku bunga FOMC, pernyataan resmi Ketua The Fed, data inflasi (CPI/PCE AS), dan grafik *dot plot*. Kata kunci pencarian: `"FOMC meeting" [bulan tahun]`, `"Fed interest rate decision"`, `"CPI report" [bulan]`.
* **Regulasi & Kerangka Hukum**: Kebijakan lembaga pengawas seperti SEC/CFTC (AS), MiCA (Uni Eropa), Bappebti/OJK (Indonesia), regulasi tingkat negara, serta status hukum *exchange* utama.
* **Indikator Pasar Tradisional**: Indeks DXY (Dolar AS), *yield* obligasi pemerintah AS 10-tahun, harga emas, serta dinamika *risk-on/risk-off* pada indeks saham utama (S&P 500, Nasdaq).
* **Arus Dana Institusional**: *Net inflow/outflow* bulanan dan harian pada ETF Bitcoin & Ethereum spot. Kata kunci pencarian: `"bitcoin ETF flows today"`, `"ethereum ETF net inflow"`.
* **Sentimen Sosial & Media**: Pemantauan topik hangat pada platform komunitas kripto utama melalui pencarian web berbasis tren.

## 4. Protokol Sintesis Sentimen

Gunakan format berikut dalam menyusun ringkasan analisis sentimen:

1. **Skor Kuantitatif**: Nilai Fear & Greed Index hari ini beserta analisis tren perbandingannya.
2. **Katalis Berita Utama**: Maksimal 3–5 poin berita terpenting (dilengkapi tanggal dan sumber data) yang mencakup berita koin spesifik dan isu makro ekonomi terkini.
3. **Kesimpulan Arah Sentimen**: Tentukan kategori (*Bullish / Bearish / Netral-Campuran*) beserta argumentasi logis yang menghubungkan data kuantitatif dan katalog berita. Jelaskan secara eksplisit jika terdapat korelasi atau kontradiksi antar-data (contoh: sentimen komunitas *bullish*, tetapi proyeksi kebijakan makro cenderung *hawkish*).
4. **Disclaimer Risiko**: Pahami bahwa sentimen pasar merupakan gambaran kondisi *real-time* dan bukan indikator kepastian arah harga di masa depan.