#!/usr/bin/env python3
"""
Menghitung indikator teknikal (SMA, EMA, RSI, MACD, Bollinger Bands, ATR)
dari file CSV OHLCV.

Format CSV yang diharapkan (header wajib ada, urutan kolom bebas):
    date,open,high,low,close,volume

Penggunaan:
    python compute_indicators.py data.csv
    python compute_indicators.py data.csv --rsi-period 14 --sma 20 50 200
"""

import argparse
import sys

import numpy as np
import pandas as pd


def compute_sma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(window=period).mean()


def compute_ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = compute_ema(close, fast)
    ema_slow = compute_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = compute_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_bollinger(close: pd.Series, period: int = 20, num_std: float = 2.0):
    mid = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window=period).mean()


def qualitative_rsi(value: float) -> str:
    if pd.isna(value):
        return "data tidak cukup"
    if value >= 70:
        return "overbought (potensi koreksi)"
    if value <= 30:
        return "oversold (potensi rebound)"
    return "netral"


def qualitative_macd(hist_last: float, hist_prev: float) -> str:
    if pd.isna(hist_last) or pd.isna(hist_prev):
        return "data tidak cukup"
    if hist_last > 0 and hist_prev <= 0:
        return "baru bersilangan bullish (MACD memotong ke atas signal line)"
    if hist_last < 0 and hist_prev >= 0:
        return "baru bersilangan bearish (MACD memotong ke bawah signal line)"
    if hist_last > 0:
        return "momentum bullish berlanjut"
    return "momentum bearish berlanjut"


def main():
    parser = argparse.ArgumentParser(description="Hitung indikator teknikal dari CSV OHLCV")
    parser.add_argument("csv_path", help="Path ke file CSV (kolom: date,open,high,low,close,volume)")
    parser.add_argument("--rsi-period", type=int, default=14)
    parser.add_argument("--sma", type=int, nargs="*", default=[20, 50, 200], help="Periode SMA yang dihitung")
    parser.add_argument("--bb-period", type=int, default=20)
    parser.add_argument("--atr-period", type=int, default=14)
    args = parser.parse_args()

    df = pd.read_csv(args.csv_path)
    df.columns = [c.strip().lower() for c in df.columns]

    required = {"date", "close"}
    if not required.issubset(df.columns):
        sys.exit(f"CSV harus punya minimal kolom: {required}. Kolom ditemukan: {list(df.columns)}")

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    close = df["close"]

    print(f"Data: {len(df)} baris, dari {df['date'].iloc[0].date()} sampai {df['date'].iloc[-1].date()}\n")

    # SMA
    print("=== Moving Averages ===")
    for p in args.sma:
        sma = compute_sma(close, p)
        last = sma.iloc[-1]
        pos = "di atas" if close.iloc[-1] > last else "di bawah"
        print(f"SMA{p}: {last:,.2f}  (harga close saat ini {pos} SMA{p})")

    # RSI
    print("\n=== RSI ===")
    rsi = compute_rsi(close, args.rsi_period)
    rsi_last = rsi.iloc[-1]
    print(f"RSI({args.rsi_period}): {rsi_last:.2f} -> {qualitative_rsi(rsi_last)}")

    # MACD
    print("\n=== MACD ===")
    macd_line, signal_line, hist = compute_macd(close)
    print(f"MACD line: {macd_line.iloc[-1]:.4f}")
    print(f"Signal line: {signal_line.iloc[-1]:.4f}")
    print(f"Histogram: {hist.iloc[-1]:.4f} -> {qualitative_macd(hist.iloc[-1], hist.iloc[-2])}")

    # Bollinger Bands
    print("\n=== Bollinger Bands ===")
    upper, mid, lower = compute_bollinger(close, args.bb_period)
    print(f"Upper: {upper.iloc[-1]:,.2f} | Mid: {mid.iloc[-1]:,.2f} | Lower: {lower.iloc[-1]:,.2f}")
    last_close = close.iloc[-1]
    if last_close >= upper.iloc[-1]:
        print("Posisi harga: di/atas upper band (overbought jangka pendek atau breakout kuat)")
    elif last_close <= lower.iloc[-1]:
        print("Posisi harga: di/bawah lower band (oversold jangka pendek atau breakdown kuat)")
    else:
        print("Posisi harga: di dalam band (netral)")

    # ATR (butuh high/low)
    if {"high", "low"}.issubset(df.columns):
        print("\n=== ATR (volatilitas) ===")
        atr = compute_atr(df["high"], df["low"], close, args.atr_period)
        atr_last = atr.iloc[-1]
        print(f"ATR({args.atr_period}): {atr_last:,.2f}")
        print(f"Saran jarak stop-loss (1.5x ATR): {1.5 * atr_last:,.2f} dari harga entry")
    else:
        print("\n(ATR dilewati — kolom high/low tidak tersedia di CSV)")

    print("\nCatatan: indikator ini bersifat lagging (berbasis data historis).")
    print("Gabungkan minimal 2-3 sinyal yang saling mengonfirmasi sebelum menyimpulkan.")


if __name__ == "__main__":
    main()
