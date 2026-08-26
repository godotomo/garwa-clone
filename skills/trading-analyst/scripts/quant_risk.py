#!/usr/bin/env python3
"""
Analisis kuantitatif ala hedge fund: VaR, CVaR, Monte Carlo, Sharpe/Sortino/Calmar,
max drawdown, volatilitas, skewness/kurtosis, dan (opsional) korelasi & optimasi
portofolio sederhana untuk multi-aset.

Input tunggal (single asset):
    python quant_risk.py data.csv --confidence 0.95 0.99 --mc-days 30 --mc-sims 10000

Input multi-aset (portofolio: korelasi + efficient frontier sederhana):
    python quant_risk.py --portfolio a.csv b.csv c.csv --weights 0.4 0.3 0.3

Format CSV: minimal kolom 'date' dan 'close' (kolom lain diabaikan).
"""

import argparse
import sys

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def load_returns(csv_path: str) -> pd.Series:
    df = pd.read_csv(csv_path)
    df.columns = [c.strip().lower() for c in df.columns]
    if "close" not in df.columns:
        sys.exit(f"'{csv_path}' harus punya kolom 'close'. Kolom ditemukan: {list(df.columns)}")
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
    close = df["close"].reset_index(drop=True)
    log_returns = np.log(close / close.shift(1)).dropna()
    return log_returns.reset_index(drop=True)


# ---------- VaR / CVaR ----------

def historical_var_cvar(returns: pd.Series, confidence: float):
    alpha = 1 - confidence
    sorted_r = returns.sort_values().reset_index(drop=True)
    idx = int(np.floor(alpha * len(sorted_r)))
    idx = max(idx, 0)
    var = sorted_r.iloc[idx]
    tail = sorted_r.iloc[: idx + 1] if idx + 1 > 0 else sorted_r.iloc[:1]
    cvar = tail.mean()
    return var, cvar


def parametric_var_cvar(returns: pd.Series, confidence: float):
    from scipy.stats import norm

    mu = returns.mean()
    sigma = returns.std()
    z = norm.ppf(1 - confidence)
    var = mu + z * sigma
    # CVaR analitik untuk distribusi normal
    cvar = mu - sigma * norm.pdf(z) / (1 - confidence)
    return var, cvar


def monte_carlo_paths(mu: float, sigma: float, s0: float, days: int, n_sims: int, seed: int = 42):
    rng = np.random.default_rng(seed)
    dt = 1.0
    z = rng.standard_normal((n_sims, days))
    daily_returns = (mu - 0.5 * sigma ** 2) * dt + sigma * np.sqrt(dt) * z
    log_paths = np.cumsum(daily_returns, axis=1)
    price_paths = s0 * np.exp(log_paths)
    return price_paths  # shape: (n_sims, days)


def monte_carlo_var_cvar(mu, sigma, confidence: float, n_sims: int = 10000, seed: int = 42):
    rng = np.random.default_rng(seed)
    sim_returns = rng.normal(mu, sigma, n_sims)
    return historical_var_cvar(pd.Series(sim_returns), confidence)


# ---------- Rasio kinerja ----------

def sharpe_ratio(returns: pd.Series, risk_free_annual: float = 0.0) -> float:
    rf_daily = risk_free_annual / TRADING_DAYS
    excess = returns - rf_daily
    if excess.std() == 0:
        return float("nan")
    return (excess.mean() / excess.std()) * np.sqrt(TRADING_DAYS)


def sortino_ratio(returns: pd.Series, risk_free_annual: float = 0.0) -> float:
    rf_daily = risk_free_annual / TRADING_DAYS
    excess = returns - rf_daily
    downside = excess[excess < 0]
    downside_std = downside.std()
    if downside_std == 0 or np.isnan(downside_std):
        return float("nan")
    return (excess.mean() / downside_std) * np.sqrt(TRADING_DAYS)


def max_drawdown(returns: pd.Series):
    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()
    trough_idx = dd.idxmin()
    peak_idx = cum.iloc[: trough_idx + 1].idxmax()
    duration = trough_idx - peak_idx
    return mdd, int(duration)


def calmar_ratio(returns: pd.Series) -> float:
    mdd, _ = max_drawdown(returns)
    annual_return = returns.mean() * TRADING_DAYS
    if mdd == 0:
        return float("nan")
    return annual_return / abs(mdd)


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return float("nan")
    r = avg_win / abs(avg_loss)
    return win_rate - (1 - win_rate) / r


# ---------- Analisis tunggal ----------

def analyze_single(csv_path: str, confidences, mc_days: int, mc_sims: int):
    returns = load_returns(csv_path)
    if len(returns) < 30:
        print(f"⚠️  Peringatan: hanya {len(returns)} observasi return — hasil VaR/CVaR kurang andal (idealnya ≥250 hari).")

    mu = returns.mean()
    sigma = returns.std()
    annual_vol = sigma * np.sqrt(TRADING_DAYS)
    annual_return = mu * TRADING_DAYS

    print(f"\n=== Ringkasan Return ({len(returns)} observasi) ===")
    print(f"Return harian rata-rata: {mu:.5f} ({mu*100:.3f}%)")
    print(f"Volatilitas harian: {sigma:.5f} ({sigma*100:.3f}%)")
    print(f"Return tahunan (anualisasi): {annual_return*100:.2f}%")
    print(f"Volatilitas tahunan (anualisasi): {annual_vol*100:.2f}%")
    print(f"Skewness: {returns.skew():.3f}  |  Kurtosis (excess): {returns.kurt():.3f}")
    if returns.kurt() > 1:
        print("  -> Excess kurtosis tinggi: distribusi fat-tailed, Parametric VaR kemungkinan meremehkan risiko ekor.")

    print("\n=== VaR & CVaR (per hari) ===")
    for c in confidences:
        h_var, h_cvar = historical_var_cvar(returns, c)
        try:
            p_var, p_cvar = parametric_var_cvar(returns, c)
            p_str = f"Parametric: VaR {p_var*100:.2f}% | CVaR {p_cvar*100:.2f}%"
        except ImportError:
            p_str = "Parametric: (scipy tidak tersedia, dilewati)"
        mc_var, mc_cvar = monte_carlo_var_cvar(mu, sigma, c, n_sims=mc_sims)
        print(f"\nTingkat keyakinan {int(c*100)}%:")
        print(f"  Historical:  VaR {h_var*100:.2f}% | CVaR {h_cvar*100:.2f}%")
        print(f"  {p_str}")
        print(f"  Monte Carlo: VaR {mc_var*100:.2f}% | CVaR {mc_cvar*100:.2f}%")

    print("\n=== Rasio Kinerja Disesuaikan Risiko (anualisasi) ===")
    print(f"Sharpe Ratio: {sharpe_ratio(returns):.3f}")
    print(f"Sortino Ratio: {sortino_ratio(returns):.3f}")
    print(f"Calmar Ratio: {calmar_ratio(returns):.3f}")

    mdd, duration = max_drawdown(returns)
    print("\n=== Maximum Drawdown ===")
    print(f"Max Drawdown: {mdd*100:.2f}%  (durasi puncak-ke-lembah: {duration} periode)")

    print(f"\n=== Simulasi Monte Carlo ({mc_sims} jalur, {mc_days} hari ke depan) ===")
    s0 = 100.0  # basis 100 (persentase relatif), tidak perlu harga absolut
    paths = monte_carlo_paths(mu, sigma, s0, mc_days, mc_sims)
    final_vals = paths[:, -1]
    pct_return = (final_vals - s0) / s0 * 100
    percentiles = [5, 25, 50, 75, 95]
    print(f"Distribusi return kumulatif setelah {mc_days} hari (relatif terhadap hari ini):")
    for p in percentiles:
        val = np.percentile(pct_return, p)
        print(f"  Persentil {p}: {val:+.2f}%")
    prob_positive = (pct_return > 0).mean() * 100
    print(f"Probabilitas hasil positif setelah {mc_days} hari: {prob_positive:.1f}%")

    return returns


# ---------- Analisis portofolio (multi-aset) ----------

def analyze_portfolio(csv_paths, weights):
    returns_dict = {}
    for path in csv_paths:
        name = path.split("/")[-1].replace(".csv", "")
        returns_dict[name] = load_returns(path)

    min_len = min(len(r) for r in returns_dict.values())
    df = pd.DataFrame({name: r.iloc[-min_len:].reset_index(drop=True) for name, r in returns_dict.items()})

    print(f"\n=== Matriks Korelasi ({min_len} observasi terakhir, diselaraskan) ===")
    print(df.corr().round(3).to_string())

    print("\n=== Matriks Kovarians Tahunan ===")
    cov_annual = df.cov() * TRADING_DAYS
    print(cov_annual.round(5).to_string())

    if weights is None:
        weights = [1.0 / len(csv_paths)] * len(csv_paths)
    weights = np.array(weights)
    if not np.isclose(weights.sum(), 1.0):
        print(f"\n⚠️  Peringatan: bobot berjumlah {weights.sum():.3f}, bukan 1.0 — dinormalisasi otomatis.")
        weights = weights / weights.sum()

    mean_returns = df.mean().values * TRADING_DAYS
    port_return = float(np.dot(weights, mean_returns))
    port_vol = float(np.sqrt(weights @ (df.cov().values * TRADING_DAYS) @ weights))
    port_sharpe = port_return / port_vol if port_vol != 0 else float("nan")

    print(f"\n=== Portofolio dengan bobot {dict(zip(df.columns, np.round(weights, 3)))} ===")
    print(f"Expected return tahunan: {port_return*100:.2f}%")
    print(f"Volatilitas tahunan: {port_vol*100:.2f}%")
    print(f"Sharpe ratio (rf=0): {port_sharpe:.3f}")

    print("\nCatatan: expected return di sini adalah ekstrapolasi historis (mean masa lalu),")
    print("bukan prediksi — sangat sensitif terhadap periode data yang dipakai. Pertimbangkan")
    print("skenario/pandangan forward-looking di atas angka historis murni saat mengambil keputusan alokasi.")


def main():
    parser = argparse.ArgumentParser(description="Analisis kuantitatif ala hedge fund: VaR, CVaR, Monte Carlo, dsb.")
    parser.add_argument("csv_path", nargs="?", help="CSV data harga (kolom: date,close) untuk analisis aset tunggal")
    parser.add_argument("--confidence", type=float, nargs="*", default=[0.95, 0.99], help="Tingkat keyakinan VaR/CVaR")
    parser.add_argument("--mc-days", type=int, default=30, help="Horizon simulasi Monte Carlo (hari)")
    parser.add_argument("--mc-sims", type=int, default=10000, help="Jumlah simulasi Monte Carlo")
    parser.add_argument("--portfolio", nargs="*", help="Mode multi-aset: daftar path CSV untuk analisis korelasi/portofolio")
    parser.add_argument("--weights", type=float, nargs="*", help="Bobot portofolio (harus sejumlah file --portfolio, default: equal-weight)")
    args = parser.parse_args()

    if args.portfolio:
        analyze_portfolio(args.portfolio, args.weights)
    elif args.csv_path:
        analyze_single(args.csv_path, args.confidence, args.mc_days, args.mc_sims)
    else:
        parser.error("Berikan csv_path untuk analisis tunggal, atau --portfolio a.csv b.csv ... untuk multi-aset.")


if __name__ == "__main__":
    main()
