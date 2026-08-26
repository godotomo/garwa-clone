# Rug Pull Detection & Audit Keamanan Smart Contract

Ini bagian paling kritis — **selalu gunakan minimal 2 sumber independen** sebelum menyimpulkan sebuah token "aman". Jangan pernah bilang "100% aman"; bahasa yang tepat adalah "tidak ditemukan red flag pada sinyal X, Y, Z per tanggal ini" — kondisi kontrak bisa berubah (upgrade proxy, ownership pindah tangan, dst).

## 1. GoPlus Security — Token Security API (sumber utama, keyless untuk pemakaian ringan)

Base URL: `https://api.gopluslabs.io/api/v1/`. Tanpa API key bisa langsung dipakai dengan rate limit standar; daftar API key gratis di gopluslabs.io kalau butuh limit lebih tinggi/batch query.

```
GET https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={address}
```
`chain_id` numerik sama seperti Etherscan V2 (1=Ethereum, 56=BSC, 137=Polygon, 42161=Arbitrum, dst — cek `references/02-whale-onchain.md`).

Untuk Solana (chain berbeda, endpoint terpisah):
```
GET https://api.gopluslabs.io/api/v1/solana/token_security?contract_addresses={mint_address}
```

Field kunci yang WAJIB dicek & dijelaskan ke user (bukan cuma disebut, tapi diinterpretasikan):

| Field | Artinya | Red flag kalau... |
|---|---|---|
| `is_open_source` | Source code kontrak diverifikasi publik | `0` (tidak verified) → sangat mencurigakan, tidak bisa diaudit sama sekali |
| `is_proxy` | Kontrak proxy (logic bisa diganti setelah deploy) | `1` tanpa timelock/governance transparan → dev bisa ubah aturan main kapan saja |
| `is_mintable` | Ada fungsi mint token baru | `1` + owner belum renounce → suplai bisa digelembungkan sepihak |
| `owner_address` / `owner_change_balance` | Siapa pemilik kontrak & apakah bisa ubah saldo user | Owner masih EOA aktif (bukan 0x000...dead / renounced) → risiko kontrol sepihak |
| `can_take_back_ownership` | Ownership yang "sudah dilepas" ternyata bisa diambil lagi | `1` → renounce ownership itu palsu/jebakan |
| `hidden_owner` | Ada owner tersembunyi di luar field owner biasa | `1` → red flag serius |
| `selfdestruct` | Kontrak bisa dihancurkan (menghapus semua fungsi/saldo) | `1` |
| `buy_tax` / `sell_tax` | Pajak otomatis saat beli/jual | Sell tax tinggi (>10-20%) atau timpang jauh dari buy tax → sinyal honeypot terselubung |
| `cannot_buy` / `cannot_sell_all` | Simulasi transaksi gagal | `1` pada salah satunya → indikasi honeypot |
| `is_honeypot` | Hasil deteksi honeypot langsung dari GoPlus | `1` → JANGAN disentuh |
| `slippage_modifiable` | Pajak/slippage bisa diubah dev kapan saja setelah deploy | `1` → dev bisa naikkan sell tax jadi 99% mendadak |
| `is_blacklisted` / `is_whitelisted` | Ada fungsi blokir/izinkan wallet tertentu | `1` pada blacklist → dev bisa blokir wallet tertentu dari jual |
| `lp_holders` / `lp_total_supply` & apakah LP terkunci | Distribusi & status lock liquidity pool | LP mayoritas dipegang 1 wallet dev & tidak terkunci → risiko rug likuiditas klasik |
| `holder_count` & top holder % (`holders` array) | Konsentrasi kepemilikan | Top 1-10 holder (di luar LP/exchange/burn) pegang porsi sangat besar (>50%) → risiko dump besar sepihak |
| `trust_list` / `is_in_dex` | Terdaftar di DEX aggregator besar & terverifikasi | Tidak ada di DEX besar sama sekali padahal diklaim "sudah listing" → cek ulang klaim proyek |

## 2. Honeypot.is — simulasi beli/jual langsung (keyless, EVM: Ethereum/BSC/Base)
```
GET https://api.honeypot.is/v2/IsHoneypot?address={token_address}&chainID={chainID}
```
Field penting: `honeypotResult.isHoneypot` + `honeypotResult.honeypotReason`, `simulationResult.buyTax`, `simulationResult.sellTax`, `simulationResult.transferTax`, `simulationResult.maxSell`. Ini melakukan **simulasi transaksi nyata**, jadi lebih definitif daripada analisis statis kode — pakai sebagai cross-check kedua setelah GoPlus.

## 3. RugCheck.xyz — khusus Solana (API key gratis, ada API publik terdokumentasi Swagger)
```
GET https://api.rugcheck.xyz/v1/tokens/{mint}/report
```
Mengecek: mint authority & freeze authority (aktif/revoked), distribusi holder, status LP, dan pola risiko spesifik Solana lainnya. Solana tidak punya konsep "source code kontrak" seperti EVM (logic ada di program terpisah), jadi otoritas mint/freeze adalah pengganti sinyal utamanya.

## 4. Checklist audit manual tambahan (kalau butuh lebih dalam dari API)
- **Source code kontrak** (`getsourcecode` Etherscan API) → cek fungsi mencurigakan: `mint`, `blacklist`, `setFee`, `pause`, `_beforeTokenTransfer` dengan logic aneh, backdoor `owner`-only yang bisa tarik saldo user.
- **Umur & aktivitas kontrak** — kontrak baru dideploy <7 hari + volume tiba-tiba tinggi = pola klasik pump-and-dump/rug cepat.
- **Tim & transparansi** — proyek anonim total bukan otomatis scam, tapi menaikkan risiko; cek apakah ada audit pihak ketiga (CertiK, SlowMist, PeckShield, Hacken, dll) yang link laporannya bisa diverifikasi via `web_search`.
- **Distribusi supply awal** — alokasi tim/marketing besar tanpa vesting/lock jelas = risiko dump terjadwal.
- **Cek DexScreener** (`references/02-whale-onchain.md`) untuk rasio buy/sell mencurigakan dan likuiditas tipis relatif FDV.

## 5. Kesimpulan level risiko — format wajib
Jangan cuma bilang "aman" atau "bahaya". Gunakan struktur ini:

```
Level Risiko: [Low / Medium / High / Critical]

Temuan yang mendukung:
- [flag konkret 1, dengan angka/field asli, sumber]
- [flag konkret 2]
...

Temuan positif (kalau ada):
- [mis. ownership renounced, source verified, LP terkunci 1 tahun]

Yang perlu diverifikasi sendiri oleh user:
- [hal yang API tidak bisa cek, mis. reputasi tim, roadmap realistis]
```

Kriteria kasar:
- **Critical**: `is_honeypot=1`, atau `cannot_sell_all=1`, atau sell tax >50%, atau owner masih bisa ambil semua dana user.
- **High**: source code tidak verified, mint function aktif tanpa renounce, LP tidak terkunci & mayoritas di 1 wallet, top holder >50% di luar LP/burn.
- **Medium**: proxy upgradeable tanpa timelock, buy/sell tax sedang (5-15%) tapi konsisten, holder cukup terkonsentrasi tapi tidak ekstrem.
- **Low**: source verified, ownership renounced/timelocked, LP terkunci jangka panjang & mayoritas, tidak ada fungsi mint/blacklist aktif, distribusi holder wajar, honeypot check bersih di ≥2 sumber. Tetap ingatkan: rendah ≠ nol risiko (harga tetap volatil, tim tetap bisa gagal eksekusi).
