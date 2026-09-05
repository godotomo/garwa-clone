---
name: crypto-data-fetcher-endpoints
description: "Dokumentasi endpoint keyless (tanpa API key) + footguns parsing untuk crypto-data-fetcher. CoinGecko, DexScreener, GoPlus Security, Alternative.me."
---

# Crypto Data Fetcher — Endpoints & Footguns

Semua endpoint di bawah **keyless** (tidak butuh API key). Terverifikasi bekerja
dengan data asli. Gunakan `scripts/crypto_fetcher.py` untuk eksekusi, atau panggil
langsung endpoint ini jika butuh kontrol lebih.

## 1. CoinGecko

### `GET /api/v3/simple/price`
Harga, market cap, 24h change, volume.

```
https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd&include_market_cap=true&include_24hr_vol=true&include_24hr_change=true
```

Respons:
```json
{
  "bitcoin": {
    "usd": 64231.5,
    "usd_market_cap": 1265432100000,
    "usd_24h_vol": 28765432100,
    "usd_24h_change": -1.42
  }
}
```

**Footguns:**
- **WAJIB** `include_market_cap=true`, `include_24hr_vol=true`, dan `include_24hr_change=true` — tanpa flag ini field-nya tidak ada (bukan None, benar-benar hilang).
- Field-nya pakai prefix **`usd_`** (camelCase): `usd` (harga), `usd_market_cap`, `usd_24h_vol`, `usd_24h_change`. BUKAN `price_usd`/`market_cap_usd`/`volume_24h_usd`.
- `usd_24h_change` bisa `null` — cek None sebelum pakai.
- Multiple ids dipisah koma: `ids=bitcoin,ethereum`.
- Rate limit keyless ~10-30 req/menit. Terlalu cepat → 429. Tambahkan delay 1-2 detik antar panggilan berurutan.

### `GET /api/v3/coins/{id}`
Detail koin: ATH/ATL, supply, market data lengkap.

```
https://api.coingecko.com/api/v3/coins/bitcoin?localization=false&tickers=false&market_data=true
```

**Footguns:**
- **WAJIB** `market_data=true` — tanpa ini ATH/ATL/supply tidak akan muncul.
- `localization=false` dan `tickers=false` menghemat bandwidth (response jauh lebih kecil).
- Data di `market_data` (bukan root): `current_price`, `ath`, `ath_change_percentage`, `circulating_supply`, `total_supply`, `market_cap`.
- `id` adalah slug CoinGecko (mis. `bitcoin`, `tether`), BUKAN nama atau simbol. Cari dulu via `/search?query=X` kalau belum yakin slug-nya.
- Field field seperti `market_data.price_change_percentage_14d_in_currency` bisa `null` — jangan asumsikan selalu ada.

## 2. DexScreener

### `GET /latest/dex/search`
Likuiditas DEX, pairs, harga token per symbol.

```
https://api.dexscreener.com/latest/dex/search?q=USDC
```

Respons:
```json
{
  "pairs": [
    {
      "baseToken": {"symbol": "USDC", "address": "0xA0b8..."},
      "quoteToken": {"symbol": "WETH", "address": "0xC02..."},
      "priceUsd": "1.0001",
      "liquidity": {"usd": 45000000, "base": 22000000, "quote": 22000000},
      "volume": {"h24": 120000000, "h6": 30000000, "h1": 5000000},
      "infoUrl": "https://dexscreener.com/ethereum/0xpair..."
    }
  ]
}
```

**Footguns:**
- `pairs` bisa KOSONG (array `[]`) jika symbol tidak ditemukan — selalu cek panjang array sebelum akses `pairs[0]`.
- Data liquidity ada di `pairs[].liquidity.usd`, bukan field flat.
- `pairs[].infoUrl` — URL detail pair di DexScreener (berguna untuk referensi user).
- Token address bisa dicari via `baseToken.address` / `quoteToken.address`.
- Endpoint ini free tapi anti-bot; jangan dipanggil berulang super cepat.

## 3. GoPlus Security

### `GET /api/v1/token_security/{chainId}`
Audit keamanan token: honeypot, buy/sell tax, holder count, proxy, owner renounce.

```
https://api.gopluslabs.io/api/v1/token_security/1?contract_addresses=0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48
```

Respons:
```json
{
  "code": 0,
  "msg": "success",
  "result": {
    "1": {
      "is_honeypot": "false",
      "is_open_source": "true",
      "buy_tax": "0",
      "sell_tax": "0",
      "holder_count": "15234",
      "is_proxy": "false",
      "creator_address": "0x1234...",
      "is_owner_renounced": "true",
      "can_take_back_ownership": "false"
    }
  }
}
```

**Footguns (PENTING):**
- **KUNCI LOWERCASE + UNDERSCORE**: `is_honeypot`, `is_open_source`, `buy_tax`, `sell_tax`, `holder_count`, `is_proxy`, `creator_address`. BUKAN camelCase. Kalau pakai `isHoneypot` → KeyError.
- Nilai berupa **STRING** (`"0"`, `"false"`), bukan boolean/number. Konversi eksplisit: `int(data['buy_tax'])`, `data['is_honeypot'] == 'true'`.
- `result` di-key dengan **chain_id string** (`"1"`, `"56"`, `"137"`). Ambil via `list(result.values())[0]` atau `result[str(chain_id)]`.
- **chain_id**: Ethereum=1, BSC=56, Polygon=137, Arbitrum=42161, Base=8453, Optimism=10. Salah chain_id → result kosong.
- Field field opsional (`is_owner_renounced`, `can_take_back_ownership`) **tidak selalu ada** — pakai `.get()` dengan default, jangan akses langsung.
- `code: 0` = sukses. `code != 0` = error (cek `msg`).
- Token di chain yang tidak didukung GoPlus → result kosong.

### Chain ID Reference
| Chain | chain_id |
|---|---|
| Ethereum | 1 |
| BSC (BNB) | 56 |
| Polygon | 137 |
| Arbitrum | 42161 |
| Base | 8453 |
| Optimism | 10 |
| Avalanche | 43114 |

## 4. Alternative.me — Fear & Greed Index

### `GET /api/v1/fng`
Indeks sentimen pasar (0 = Extreme Fear, 100 = Extreme Greed).

```
https://api.alternative.me/fng/?limit=7
```

Respons:
```json
{
  "data": [
    {"value": "72", "value_classification": "Greed", "timestamp": 1756704000},
    {"value": "68", "value_classification": "Greed", "timestamp": 1756617600}
  ],
  "status": "success"
}
```

**Footguns:**
- Data di `data` (array), bukan root. `value` berupa string, konversi ke int.
- **WAJIB** field tanggalnya `timestamp` (epoch int SECONDS), BUKAN `date` (ISO string). Konversi ke tanggal: `datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()`. Kalau pakai key `date` → None.
- `value_classification` sudah categorize: Extreme Fear / Fear / Greed / Extreme Greed / Neutral.
- `limit` opsional, default 1 kalau tidak diset.

## 5. Praktik Terbaik Umum

- **Zero-dependency**: semua endpoint di atas bisa diakses via `urllib` (stdlib). Tidak perlu `requests` — lebih ringan dan tidak butuh install.
- **Timeout**: selalu set `timeout=20` — network di server/sandbox sering lambat.
- **User-Agent**: set `User-Agent` header, beberapa endpoint menolak default Python urllib UA.
- **Error handling**: bungkus semua `fetch()` — HTTP 429/503 biasa di endpoint free. Tampilkan error eksplisit, jangan crash.
- **Never fabricate**: kalau API gagal, tulis keterangan eksplisit ("data tidak tersedia"). Jangan mengarang angka.
- **Data for research/education**: jangan pernah menyajikan sebagai nasihat keuangan. Selalu DYOR.

## 6. Contoh Cepat (stdlib only)

```python
import urllib.request, json

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
    return json.load(urllib.request.urlopen(req, timeout=20))

# Harga BTC
d = fetch('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_market_cap=true&include_24hr_change=true')
print(d['bitcoin'])

# Audit keamanan USDC (Ethereum = 1)
d = fetch('https://api.gopluslabs.io/api/v1/token_security/1?contract_addresses=0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48')
tok = list(d['result'].values())[0]
print('honeypot:', tok.get('is_honeypot'), '| buy_tax:', tok.get('buy_tax'), '| sell_tax:', tok.get('sell_tax'))
```
