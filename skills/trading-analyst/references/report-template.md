# Template Laporan Akhir

Gunakan struktur ini untuk analisis penuh (5 tahap). Untuk pertanyaan cepat, cukup ambil bagian yang relevan saja.

```markdown
## Analisis [Nama Aset / Ticker] — [Kelas Aset] — [Tanggal Analisis]

*Data diambil per [timestamp pencarian]. [Status pasar: buka/tutup jika relevan].*

### 1. Ringkasan Eksekutif
- **Rekomendasi**: BUY / HOLD / SELL
- **Tingkat keyakinan**: Tinggi / Sedang / Rendah
- **Horison**: Jangka pendek (hari-minggu) / menengah (bulan) / panjang (>1 tahun)
- Satu-dua kalimat inti alasan.

### 2. Analisis Fundamental
[Rasio kunci, tren pendapatan/laba, kesehatan neraca, valuasi relatif]

### 3. Analisis Teknikal
[Tren, level support/resistance, sinyal indikator (RSI/MACD/BB), konfirmasi volume]

### 4. Berita & Sentimen
[Katalis berita utama + pembacaan sentimen sosial, dengan sumber]

### 5. Debat Bull vs Bear
**Argumen Bullish**: ...
**Argumen Bearish**: ...
**Sintesis**: [poin mana yang lebih kuat dan mengapa]

### 6. Proposal Trader
- Entry: ...
- Stop-loss: ...
- Take-profit: ...
- Ukuran posisi: [kecil/eksploratif/penuh, dengan alasan]

### 7. Tinjauan Risiko

**Metrik kuantitatif** (dari `scripts/quant_risk.py`, sebutkan periode data & tingkat keyakinan):
- VaR harian [95%/99%]: ... (historical / parametric / Monte Carlo)
- CVaR harian [95%/99%]: ...
- Sharpe / Sortino / Calmar Ratio: ...
- Maximum Drawdown: ... (durasi: ...)
- Simulasi Monte Carlo [N hari]: rentang persentil 5-95, probabilitas hasil positif
- (Jika multi-aset) korelasi & kontribusi risiko portofolio

**Debat kualitatif**:
- Pandangan agresif: ...
- Pandangan konservatif: ...
- Pandangan netral: ...

### 8. Keputusan Akhir
[Keputusan final Manajer Portofolio — bisa berbeda dari proposal Trader jika tim risiko punya argumen kuat]

---
**Disclaimer**: Analisis ini dibuat untuk tujuan riset/edukasi, bukan nasihat keuangan, investasi, atau ajakan membeli/menjual instrumen tertentu. Data pasar bisa berubah cepat dan sumber pihak ketiga bisa memuat kesalahan. Selalu lakukan riset lanjutan dan pertimbangkan konsultasi dengan penasihat keuangan berlisensi serta profil risiko pribadi sebelum mengambil keputusan trading/investasi.
```
