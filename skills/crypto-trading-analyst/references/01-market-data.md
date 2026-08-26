# Data Pasar (Market Data) — Top 30+ Koin

**Sumber utama: CoinGecko API.** Riset (Agustus 2026) menunjukkan CoinGecko adalah pilihan gratis terbaik: banyak endpoint bisa diakses tanpa API key (rate limit lebih ketat), atau pakai Demo API key gratis (daftar di coingecko.com, tanpa kartu kredit) untuk ~30 request/menit dan ~10.000 kredit/bulan dengan header `x-cg-demo-api-key`. Base URL:
- Demo/free: `https://api.coingecko.com/api/v3/`
- Pro (kalau user punya key berbayar): `https://pro-api.coingecko.com/api/v3/`

Alternatif kalau CoinGecko diblokir/limit habis: CoinMarketCap API (butuh key gratis, model kredit per-request lebih mahal), CoinPaprika (gratis, ada endpoint "people"/tim proyek), CryptoCompare.

## Endpoint inti

### 1. Top 30+ koin sekaligus (untuk ranking CMC-style)
```
GET https://api.coingecko.com/api/v3/coins/markets
  ?vs_currency=usd
  &order=market_cap_desc
  &per_page=30
  &page=1
  &price_change_percentage=1h,24h,7d
  &sparkline=false
```
Mengembalikan array per koin: `id, symbol, name, current_price, market_cap, market_cap_rank, total_volume, high_24h, low_24h, price_change_percentage_24h, circulating_supply, total_supply, max_supply, ath, ath_change_percentage, atl`.

Contoh curl:
```bash
curl -s "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=30&page=1&price_change_percentage=1h,24h,7d"
```

### 2. Detail satu koin
```
GET https://api.coingecko.com/api/v3/coins/{id}
  ?localization=false&tickers=true&market_data=true&community_data=true&developer_data=false
```
`{id}` pakai slug CoinGecko (mis. `bitcoin`, `ethereum`, bukan simbol ticker). Kalau belum tahu id-nya, pakai endpoint search:
```
GET https://api.coingecko.com/api/v3/search?query=namakoin
```

### 3. Harga cepat (ringan, buat cek harga cepat beberapa koin)
```
GET https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana&vs_currencies=usd&include_market_cap=true&include_24hr_vol=true&include_24hr_change=true
```

### 4. Histori harga / chart (OHLC untuk analisis teknikal ringan)
```
GET https://api.coingecko.com/api/v3/coins/{id}/market_chart?vs_currency=usd&days=30
GET https://api.coingecko.com/api/v3/coins/{id}/ohlc?vs_currency=usd&days=14
```
`days` demo plan biasanya dibatasi granularitas historis ~1 tahun harian.

### 5. Data global market
```
GET https://api.coingecko.com/api/v3/global
```
Berguna untuk total market cap kripto, dominasi BTC/ETH, dan total volume — konteks makro sebelum bahas koin spesifik.

### 6. Koin dari alamat kontrak (kalau user kasih contract address, bukan nama)
```
GET https://api.coingecko.com/api/v3/coins/{platform_id}/contract/{contract_address}
```
`{platform_id}` contoh: `ethereum`, `binance-smart-chain`, `polygon-pos`, `solana`, `arbitrum-one`, `base`.

### 7. Data DEX on-chain granular (GeckoTerminal, bagian dari CoinGecko, keyless)
```
GET https://api.coingecko.com/api/v3/onchain/networks/{network}/pools/{pool_address}
GET https://api.coingecko.com/api/v3/onchain/networks/{network}/trending_pools
```
Berguna untuk token baru yang belum listing resmi di CoinGecko utama (lihat juga DexScreener di `02-whale-onchain.md`, sering lebih cepat untuk pair DEX baru).

## Cara menyajikan ke user
- Selalu sertakan: harga, market cap, rank, volume 24h, perubahan 24h & 7d, dan **timestamp saat data diambil**.
- Untuk perbandingan >1 koin, gunakan tabel markdown atau `comparison_card_display_v0`.
- Untuk top 30, kalau relevan tampilkan sebagai tabel ringkas (rank, nama, harga, %24h, market cap, volume) — jangan dump JSON mentah ke user.
- Kalau angka volume/market cap tidak masuk akal dibanding rank (mis. token baru rank rendah tapi volume tinggi), catat sebagai potensi red flag dan cross-check di `05-security-rugpull.md`.
