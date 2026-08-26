---
name: crypto-data-fetcher
description: Ambil data pasar kripto, on-chain, dan audit keamanan token dari API publik gratis (CoinGecko, DexScreener, GoPlus Security, Alternative.me Fear & Greed). Gunakan skill ini setiap kali user meminta harga koin, market cap, volume, likuiditas DEX, audit keamanan smart contract, atau indeks sentimen pasar — bahkan jika hanya menyebut satu aspek. Menyediakan endpoint keyless yang sudah terverifikasi dan cara parsing respons yang benar.
---

# Crypto Data Fetcher

Skill ini membungkus pipeline pengambilan data kripto dari API publik gratis yang **sudah terverifikasi berfungsi** (diuji dengan data asli). Gunakan untuk mengambil data pasar, on-chain, keamanan token, dan sentimen.

## Endpoint Terverifikasi (Keyless)

| Kebutuhan | Endpoint | Catatan |
|---|---|---|
| Harga/market cap/volume | `https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_market_cap=true&include_24hr_change=true` | Keyless |
| Detail koin (ATH/ATL/supply) | `https://api.coingecko.com/api/v3/coins/{id}?localization=false&tickers=false&market_data=true` | Keyless |
| Likuiditas DEX | `https://api.dexscreener.com/latest/dex/search?q={SYMBOL}` | Keyless |
| Audit keamanan token | `https://api.gopluslabs.io/api/v1/token_security/{chainId}?contract_addresses={ADDR}` | Keyless |
| Fear & Greed Index | `https://api.alternative.me/fng/?limit={N}` | Keyless |

## ⚠️ Jebakan Parsing (PENTING)

1. **GoPlus Security** mengembalikan kunci respons dalam **huruf kecil (lowercase)**: `is_honeypot`, `is_open_source`, `buy_tax`, `sell_tax`, `holder_count`, `is_proxy`, `creator_address`. BUKAN camelCase. Field seperti `is_owner_renounced`/`can_take_back_ownership` TIDAK selalu ada di respons — jangan anggap error, cukup lewati.
2. **CoinGecko** `/coins/{id}` memerlukan `market_data=true` untuk mendapatkan ATH/ATL/supply.
3. **DexScreener** respons `pairs` bisa kosong jika simbol tidak ditemukan — selalu cek panjang array.

## Contoh Python (urllib, tanpa dependency)

```python
import urllib.request, json
def get(url):
    req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=20))

# Harga BTC
d = get('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_market_cap=true&include_24hr_change=true')
print(d['bitcoin'])

# Audit keamanan USDC (Ethereum chainId=1)
d = get('https://api.gopluslabs.io/api/v1/token_security/1?contract_addresses=0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48')
tok = list(d['result'].values())[0]
print('honeypot:', tok.get('is_honeypot'), '| open_source:', tok.get('is_open_source'), '| buy_tax:', tok.get('buy_tax'))
```

## Alur Kerja

1. Identifikasi aset: nama koin (via CoinGecko) atau token kontrak (via GoPlus/DexScreener).
2. Ambil data pasar via CoinGecko.
3. Jika token di luar Top 30 atau diminta audit: ambil data keamanan via GoPlus.
4. Ambil sentimen via Fear & Greed.
5. Sajikan data dengan sumber & timestamp. Jangan pernah mengarang data — jika API gagal, tulis keterangan eksplisit.

## Disclaimer

Data untuk riset/edukasi, bukan nasihat keuangan. Selalu DYOR.
