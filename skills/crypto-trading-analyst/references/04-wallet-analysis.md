# Analisis Transaksi & Isi Wallet

## Langkah 0: identifikasi chain dari format address
- `0x` + 40 karakter hex → EVM chain (Ethereum, BSC, Polygon, Arbitrum, Base, Avalanche C-Chain, dst). Perlu tanya/tebak chain mana kalau tidak jelas dari konteks (default: coba Ethereum dulu, lalu BSC).
- String base58 ~32–44 karakter tanpa `0x` → kemungkinan Solana.
- Alamat dimulai `bc1`/`1`/`3` → Bitcoin.
- Alamat berformat lain (TRON `T...`, dst) → sesuaikan explorer.

## EVM chains (Ethereum, BSC, Polygon, Arbitrum, dll) — Etherscan API V2
Base: `https://api.etherscan.io/v2/api?chainid={ID}&apikey={KEY}` (key gratis dari etherscan.io, berlaku lintas chain).

| Tujuan | module/action |
|---|---|
| Saldo native (ETH/BNB/dst) | `module=account&action=balance&address={addr}` |
| Saldo token ERC-20 tertentu | `module=account&action=tokenbalance&contractaddress={token}&address={addr}` |
| Semua transaksi native masuk/keluar | `module=account&action=txlist&address={addr}&sort=desc` |
| Semua transfer token ERC-20 | `module=account&action=tokentx&address={addr}&sort=desc` |
| Transfer NFT (ERC-721/1155) | `module=account&action=tokennfttx` / `token1155tx` |
| Internal transactions (interaksi kontrak) | `module=account&action=txlistinternal&address={addr}` |

Cara baca hasil untuk profil wallet:
1. **Umur wallet** — timestamp transaksi pertama vs sekarang → wallet baru (<30 hari) lebih berisiko/spekulatif daripada wallet lama dengan histori panjang.
2. **Diversifikasi holding** — banyak token kecil tak dikenal vs sedikit token besar mapan → indikasi profil risiko (degen vs conservative).
3. **Pola transaksi** — interaksi rutin dengan kontrak DeFi (staking, LP) vs cuma transfer in/out exchange → membedakan "trader aktif" vs "holder pasif".
4. **Cross-check label** — banyak explorer menampilkan nama publik untuk address terkenal (exchange, treasury proyek, dst) di halaman web mereka; kalau lewat API murni labelnya mungkin tidak muncul (fitur berbayar), jadi kalau perlu label pasti, `web_search`/`webfetch` ke halaman explorer address tsb bisa membantu.

## Solana — Solscan / RPC publik
Solscan menyediakan explorer publik (situs) untuk cek saldo & histori transaksi Solana; untuk akses API terstruktur biasanya butuh key (ada free tier terbatas). Alternatif keyless: panggil RPC publik Solana langsung untuk saldo:
```
POST https://api.mainnet-beta.solana.com
Body: {"jsonrpc":"2.0","id":1,"method":"getBalance","params":["{address}"]}
```
(RPC publik Solana sering rate-limited ketat — untuk pemakaian lebih berat sarankan user pakai RPC provider gratis seperti Helius free tier.)

## Bitcoin — Blockchair / Blockchain.com
```
GET https://api.blockchair.com/bitcoin/dashboards/address/{address}
GET https://blockchain.info/rawaddr/{address}     # alternatif, keyless, format lama tapi masih jalan
```
Mengembalikan saldo, jumlah transaksi, total received/sent — cukup untuk profil wallet BTC dasar.

## Cross-check keamanan address
Sebelum menyimpulkan sebuah wallet "aman untuk dipercaya" (mis. sebelum approve token/transfer), cek dulu apakah address itu masuk daftar alamat berbahaya via **GoPlus Malicious Address API** (lihat `05-security-rugpull.md`), khususnya kalau user bertanya "aman gak kirim ke address ini" atau "kenapa wallet saya diblokir platform X".

## Format ringkasan wallet analysis
- Alamat + chain + saldo native + top 5 holding token by value (kalau bisa dihitung dari harga CoinGecko).
- Aktivitas terakhir (tanggal transaksi terbaru, jenis aktivitas).
- Flag risiko kalau ada (interaksi dengan kontrak scam yang diketahui, dst).
- Jangan pernah menyimpulkan identitas asli pemilik wallet — cukup deskripsikan pola on-chain yang terlihat.
