# Whale Tracking & On-Chain Analysis (ala Arkham Intelligence)

**Konteks riset**: Arkham Intelligence, Nansen, dan Glassnode adalah standar industri untuk whale/on-chain intelligence, tapi API mereka berbayar/enterprise dan tidak menyediakan akses publik gratis yang terdokumentasi. Whale Alert punya API tapi butuh developer subscription berbayar (free trial 7 hari saja). Untuk itu, strategi gratis yang realistis adalah **kombinasi block explorer + DEX data**, yang bisa mereplikasi sebagian besar fungsi whale tracking secara manual:

| Fungsi Arkham/Nansen | Pengganti gratis |
|---|---|
| Lihat holding & label wallet | Etherscan/BscScan/dst "Top Holders" tab + Etherscan API `tokenholderlist` (Pro tier Etherscan) atau GoPlus token_security (`holder_count`, top 10 holder %) |
| Deteksi transfer besar real-time | Etherscan API `txlist`/`tokentx` untuk 1 alamat; DexScreener untuk aktivitas pool; Blockchair untuk BTC |
| Exchange inflow/outflow | Cek apakah alamat pengirim/penerima adalah alamat exchange yang dikenal (Etherscan biasanya memberi label "Binance 14" dsb pada address populer) |
| Smart money / dompet profitable | Tidak ada pengganti gratis persis — jelaskan keterbatasan ini ke user, sarankan Nansen/Arkham kalau mereka butuh fitur itu spesifik |

## 1. Etherscan-family API (Etherscan, BscScan, PolygonScan, dst — kini terpadu di Etherscan API V2 multichain)

Daftar API key gratis di etherscan.io (gratis, 1 key bisa dipakai lintas 50+ chain EVM lewat V2). Base URL V2:
```
https://api.etherscan.io/v2/api?chainid={CHAIN_ID}&module=...&action=...&apikey={KEY}
```
Chain ID umum: Ethereum=1, BSC=56, Polygon=137, Arbitrum=42161, Optimism=10, Base=8453, Avalanche=43114.

Endpoint whale-relevant:
- **Transaksi besar sebuah alamat**: `module=account&action=txlist&address={addr}&sort=desc`
- **Transfer token (ERC-20) sebuah alamat**: `module=account&action=tokentx&address={addr}&sort=desc`
- **Saldo native**: `module=account&action=balance&address={addr}`
- **Saldo token tertentu**: `module=account&action=tokenbalance&contractaddress={token}&address={addr}`
- **Info kontrak & source code (untuk audit)**: `module=contract&action=getsourcecode&address={token}`

Cara pakai untuk "whale analysis": ambil `tokentx` untuk sebuah token besar, filter transaksi dengan `value` besar (di atas ambang tertentu, mis. >0.1% supply beredar atau >$1 juta), lalu cek apakah `from`/`to` adalah alamat exchange terkenal (biasanya muncul label di halaman explorer/`getsourcecode` metadata) — ini mendekati fungsi "exchange flow" ala Nansen/CryptoQuant secara manual.

## 2. DexScreener API (keyless, real-time DEX data — cocok untuk token baru/meme coin)

Base URL: `https://api.dexscreener.com`

```
GET /latest/dex/tokens/{tokenAddress}      # semua pair DEX untuk 1 token (hingga 30 alamat sekaligus, pisah koma)
GET /latest/dex/pairs/{chainId}/{pairAddress}
GET /latest/dex/search?q={query}           # cari pair by nama/simbol/alamat
GET /token-profiles/latest/v1              # token profile terbaru yang didaftarkan
```
Response berisi: `priceUsd, liquidity.usd, volume.h24/h6/h1/m5, txns.h24.buys/sells, priceChange, fdv, marketCap, pairCreatedAt`.

Guna untuk whale/aktivitas mencurigakan:
- **Rasio buys vs sells** timpang ekstrem dalam window pendek (m5/h1) → indikasi wash trading atau dump whale.
- **Likuiditas (`liquidity.usd`) kecil dibanding `fdv`/`marketCap`** → risiko slippage tinggi & rawan manipulasi harga oleh whale kecil sekalipun.
- **`pairCreatedAt` sangat baru + volume tinggi tiba-tiba** → khas pola pump token baru, cross-check ke `05-security-rugpull.md`.

## 3. Blockchair (Bitcoin & multi-chain explorer, keyless untuk pemakaian ringan)
```
GET https://api.blockchair.com/bitcoin/dashboards/address/{address}
GET https://api.blockchair.com/bitcoin/transactions?q=value(gt.100000000000)   # contoh filter transaksi besar (satuan satoshi)
```
Berguna untuk whale watching Bitcoin tanpa perlu run node sendiri. Rate limit ketat di tier gratis — gunakan secukupnya, jangan polling cepat.

## 4. Whale Alert (opsional, kalau user sudah punya API key)
Kalau user menyebut sudah punya akun/API key Whale Alert, base URL `https://api.whale-alert.io/v1/transactions?api_key=...&min_value=500000` bisa dipakai untuk feed transaksi besar lintas chain secara real-time. Kalau user **tidak** punya key, jangan pura-pura punya akses — gunakan kombinasi Etherscan+DexScreener+Blockchair di atas dan sebutkan keterbatasannya secara transparan.

## Cara menyajikan hasil whale analysis
1. Sebutkan alamat/hash transaksi konkret + jumlah + nilai USD saat itu + waktu.
2. Klasifikasikan tiap transaksi besar: exchange→wallet (potensi akumulasi/withdraw untuk hold), wallet→exchange (potensi jual), wallet→wallet (reposisi/internal transfer, dampak lebih netral).
3. Kalau data whale real-time tidak tersedia (butuh tool berbayar), katakan itu jujur dan sajikan proksi terbaik (top holder concentration, distribusi supply, tren volume DEX) sebagai gantinya.
