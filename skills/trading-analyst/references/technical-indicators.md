# Indikator Teknikal — Formula & Interpretasi

Semua indikator ini dihitung dari data OHLCV historis (bukan dari ingatan LLM). Gunakan `scripts/compute_indicators.py` setelah data harga terkumpul. Bagian ini menjelaskan formula ringkas + cara membacanya, supaya laporan tidak sekadar melempar angka.

## Moving Averages (SMA / EMA)
- **SMA (Simple Moving Average)**: rata-rata harga close selama N periode.
- **EMA (Exponential Moving Average)**: rata-rata dengan bobot lebih besar ke harga terbaru.
- Interpretasi: harga di atas MA jangka panjang (mis. MA200) = tren naik struktural. Persilangan MA pendek memotong ke atas MA panjang ("golden cross") = sinyal bullish; kebalikannya ("death cross") = bearish.

## RSI (Relative Strength Index)
- Formula: `RSI = 100 - (100 / (1 + RS))`, di mana `RS = rata-rata kenaikan / rata-rata penurunan` selama periode N (umum: 14).
- Interpretasi: RSI > 70 = overbought (potensi koreksi), RSI < 30 = oversold (potensi rebound). Divergensi RSI vs harga (harga naik tapi RSI turun) sering jadi sinyal pelemahan momentum sebelum terlihat di harga.

## MACD (Moving Average Convergence Divergence)
- Formula: `MACD line = EMA12 - EMA26`; `Signal line = EMA9 dari MACD line`; `Histogram = MACD line - Signal line`.
- Interpretasi: MACD line memotong ke atas Signal line = sinyal beli; memotong ke bawah = sinyal jual. Histogram mengecil = momentum melemah meski tren belum berbalik.

## Bollinger Bands
- Formula: `Middle Band = SMA20`; `Upper/Lower Band = Middle ± (2 × standar deviasi 20 periode)`.
- Interpretasi: harga menyentuh upper band = potensi overbought jangka pendek (atau breakout kuat jika disertai volume tinggi); band menyempit ("squeeze") = volatilitas rendah, sering mendahului pergerakan besar (arah belum tentu).

## ATR (Average True Range)
- Mengukur volatilitas absolut (bukan arah). Berguna untuk menentukan jarak stop-loss yang proporsional terhadap volatilitas aset (mis. stop-loss = 1.5×ATR di bawah entry), alih-alih persentase tetap yang tidak mempertimbangkan karakter volatilitas tiap aset.

## Volume
- Konfirmasi tren: kenaikan harga dengan volume tinggi lebih meyakinkan daripada kenaikan dengan volume tipis.
- Volume spike tanpa pergerakan harga signifikan kadang menandakan akumulasi/distribusi diam-diam oleh pemain besar.

## Cara pakai bersama `scripts/compute_indicators.py`

1. Kumpulkan data historis (lihat `data-sources.md`) — minimal butuh close price harian; idealnya OHLCV lengkap untuk ATR/Bollinger.
2. Simpan sebagai CSV dengan kolom: `date,open,high,low,close,volume`.
3. Jalankan:
   ```bash
   pip install pandas numpy --break-system-packages   # sekali saja bila belum ada
   python scripts/compute_indicators.py data.csv
   ```
4. Skrip mencetak tabel ringkas nilai terakhir tiap indikator + sinyal kualitatif (overbought/oversold/netral dsb) yang bisa langsung dikutip di laporan Analis Teknikal.

## Batasan penting
- Indikator teknikal bersifat *lagging* (berbasis data masa lalu) — jangan sajikan sebagai prediksi pasti.
- Kombinasikan minimal 2-3 indikator yang saling mengonfirmasi sebelum menyimpulkan sinyal kuat; satu indikator sendirian sering memberi sinyal palsu (whipsaw), terutama di pasar sideways.
