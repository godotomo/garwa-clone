#!/usr/bin/env python3
"""
crypto_fetcher.py — Ambil data pasar, on-chain, dan audit keamanan token
dari API publik GRATIS (keyless). Tanpa dependency eksternal (stdlib only).

Endpoint:
  - CoinGecko      : harga, market cap, ATH/ATL, supply
  - DexScreener    : likuiditas DEX, pairs, harga token
  - GoPlus Security: audit keamanan token (honeypot, buy/sell tax, holder)
  - Alternative.me : Fear & Greed Index

Cara pakai:
  python3 crypto_fetcher.py price bitcoin ethereum
  python3 crypto_fetcher.py coin bitcoin
  python3 crypto_fetcher.py dex usdc
  python3 crypto_fetcher.py audit 1 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48
  python3 crypto_fetcher.py fng
  python3 crypto_fetcher.py audit 1 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 --json

Semua data untuk riset/edukasi, BUKAN nasihat keuangan. DYOR.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

UA = "Mozilla/5.0 (compatible; garwa-crypto-fetcher/1.0)"


def fetch(url: str, timeout: int = 20) -> Any:
    """Ambil URL, parse JSON. Kembalikan dict/list atau raise."""
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"[ERROR] HTTP {e.code} untuk {url}")
    except urllib.error.URLError as e:
        raise SystemExit(f"[ERROR] network: {e.reason} untuk {url}")
    return json.loads(raw)


def get_price(ids: list[str]) -> dict:
    ids_q = ",".join(ids)
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        f"?ids={ids_q}&vs_currencies=usd"
        "&include_market_cap=true&include_24hr_change=true&include_24hr_vol=true"
    )
    return fetch(url)


def get_coin(cid: str) -> dict:
    url = (
        f"https://api.coingecko.com/api/v3/coins/{urllib.parse.quote(cid)}"
        "?localization=false&tickers=false&market_data=true"
    )
    return fetch(url)


def get_dex(query: str) -> dict:
    url = (
        f"https://api.dexscreener.com/latest/dex/search"
        f"?q={urllib.parse.quote(query)}"
    )
    return fetch(url)


def get_audit(chain_id: str, addr: str) -> dict:
    url = (
        "https://api.gopluslabs.io/api/v1/token_security"
        f"/{chain_id}?contract_addresses={urllib.parse.quote(addr)}"
    )
    return fetch(url)


def get_fng(limit: int = 7) -> dict:
    url = f"https://api.alternative.me/fng/?limit={limit}"
    return fetch(url)


# --------------------------------------------------------------------------
# Formatter output
# --------------------------------------------------------------------------

def _fmt_usd(n: Any) -> str:
    try:
        return f"${float(n):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_big(n: Any) -> str:
    try:
        return f"${float(n):,.0f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_pct(n: Any) -> str:
    try:
        return f"{float(n):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_date(ts: Any) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        return ""


def out_price(ids: list[str]) -> None:
    d = get_price(ids)
    for cid, info in d.items():
        print(f"{cid}: {_fmt_usd(info.get('usd'))} "
              f"24h {_fmt_pct(info.get('usd_24h_change'))}% | "
              f"cap {_fmt_big(info.get('usd_market_cap'))} | "
              f"vol {_fmt_big(info.get('usd_24h_vol'))}")


def _usd(d: Any) -> Any:
    """Ambil nilai USD dari dict nested (CoinGecko) atau kembalikan scalar."""
    if isinstance(d, dict):
        return d.get("usd")
    return d


def out_coin(cid: str) -> None:
    c = get_coin(cid)
    md = c.get("market_data", {})
    print(f"Coin: {c.get('name')} ({c.get('symbol','').upper()})")
    print(f"  Harga      : {_fmt_usd(_usd(md.get('current_price')))}")
    print(f"  24h change : {_fmt_usd(md.get('price_change_24h'))} "
          f"({_fmt_pct(md.get('price_change_percentage_24h'))}%)")
    ath = _usd(md.get('ath'))
    ath_pct = _usd(md.get('ath_change_percentage'))
    print(f"  ATH        : {_fmt_usd(ath)} ({_fmt_pct(ath_pct)}%)")
    print(f"  ATL        : {_fmt_usd(_usd(md.get('atl')))}")
    print(f"  Supply     : {md.get('circulating_supply')} / {md.get('total_supply')}")
    print(f"  Market cap : {_fmt_big(_usd(md.get('market_cap')))}")
    print(f"  Volume 24h : {_fmt_big(_usd(md.get('total_volume')))}")


def out_dex(query: str) -> None:
    d = get_dex(query)
    pairs = d.get("pairs") or []
    if not pairs:
        print(f"[INFO] Tidak ada pair ditemukan untuk '{query}'. "
              "Coba simbol lain atau cek ejaan.")
        return
    print(f"DexScreener: {len(pairs)} pair untuk '{query}'. Top 5:")
    for p in pairs[:5]:
        base = p.get("baseToken", {}) or {}
        quote = p.get("quoteToken", {}) or {}
        info = p.get("infoUrl", "")
        print(f"  {base.get('symbol')}:{quote.get('symbol')} "
              f"= ${p.get('priceUsd')} | "
              f"liquidity {_fmt_big(p.get('liquidity', {}).get('usd'))} | "
              f"24h vol {_fmt_big(p.get('volume', {}).get('h24'))}")
        if info:
            print(f"      {info}")


def out_audit(chain_id: str, addr: str) -> None:
    """Audit keamanan token. GoPlus balik kunci lowercase."""
    d = get_audit(chain_id, addr)
    res = d.get("result") or {}
    data = next(iter(res.values()), {}) if res else {}
    if not data:
        print("[INFO] GoPlus tidak mengembalikan data untuk address ini. "
              "Pastikan chain_id benar (Ethereum=1, BSC=56, POL=137).")
        return
    # GoPlus menggunakan kunci lowercase + underscore
    honeypot = data.get("is_honeypot", "n/a")
    print(f"Audit keamanan token ({chain_id}) {addr}")
    print(f"  Honeypot      : {honeypot}")
    print(f"  Open source   : {data.get('is_open_source', 'n/a')}")
    print(f"  Buy tax       : {data.get('buy_tax', 'n/a')}%")
    print(f"  Sell tax      : {data.get('sell_tax', 'n/a')}%")
    print(f"  Holders       : {data.get('holder_count', 'n/a')}")
    print(f"  Proxy         : {data.get('is_proxy', 'n/a')}")
    # Field opsional — lewati kalau tidak ada
    ren = data.get("is_owner_renounced")
    if ren is not None:
        print(f"  Owner renounce: {ren}")
    can = data.get("can_take_back_ownership")
    if can is not None:
        print(f"  Back ownership: {can}")


def out_fng(limit: int = 7) -> None:
    d = get_fng(limit)
    vals = d.get("data") or []
    for v in vals:
        print(f"{v.get('value')} ({v.get('value_classification')}) — {_fmt_date(v.get('timestamp'))}")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Ambil data kripto dari API publik gratis (keyless)."
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("price", help="harga/market cap/volume beberapa koin")
    sp.add_argument("ids", nargs="+")

    sc = sub.add_parser("coin", help="detail koin (ATH/ATL/supply)")
    sc.add_argument("id")

    sd = sub.add_parser("dex", help="likuiditas DEX per simbol")
    sd.add_argument("query")

    sa = sub.add_parser("audit", help="audit keamanan token")
    sa.add_argument("chain_id")
    sa.add_argument("address")
    sa.add_argument("--json", action="store_true", help="cetak JSON mentah")

    sf = sub.add_parser("fng", help="Fear & Greed Index")
    sf.add_argument("--limit", type=int, default=7)

    args = p.parse_args(argv)

    if getattr(args, "json", False) and args.cmd == "audit":
        print(json.dumps(get_audit(args.chain_id, args.address), indent=2))
        return 0

    try:
        if args.cmd == "price":
            out_price(args.ids)
        elif args.cmd == "coin":
            out_coin(args.id)
        elif args.cmd == "dex":
            out_dex(args.query)
        elif args.cmd == "audit":
            out_audit(args.chain_id, args.address)
        elif args.cmd == "fng":
            out_fng(args.limit)
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
