# Analisis Kuantitatif ala Hedge Fund — VaR, CVaR, Monte Carlo, dan Lainnya

Bagian ini menambahkan lapisan **manajemen risiko kuantitatif** di atas pipeline analisis dasar (`agents-framework.md`). Hedge fund tidak hanya bertanya "naik atau turun?" — mereka mengukur **berapa besar kerugian potensial, seberapa sering, dan bagaimana distribusi hasil di banyak skenario**. Gunakan bagian ini setiap kali user menyebut: VaR, CVaR/Expected Shortfall, Monte Carlo, Sharpe/Sortino ratio, drawdown, position sizing/Kelly, korelasi portofolio, stress test, atau minta "analisis risiko kuantitatif"/"analisis matematis".

Semua perhitungan di sini **wajib** dilakukan lewat `scripts/quant_risk.py` (pandas/numpy) — jangan menghitung integral/statistik distribusi secara mental, hasilnya tidak presisi dan bisa menyesatkan untuk keputusan yang melibatkan uang riil.

Di mana ini masuk ke pipeline 5-tahap: jalankan sebagai **input tambahan untuk Tim Manajemen Risiko** (tahap 4) — angka VaR/CVaR/Sharpe memberi dasar kuantitatif untuk debat agresif/konservatif/netral, bukan sekadar opini kualitatif.

---

## 1. Value at Risk (VaR)

**Definisi**: estimasi kerugian maksimum (dalam mata uang atau %) yang *tidak akan dilampaui* dengan tingkat keyakinan tertentu (biasa 95% atau 99%) dalam periode tertentu (biasa 1 hari atau 10 hari).

Tiga metode, masing-masing punya trade-off — sajikan idealnya ketiganya untuk cross-check, bukan cuma satu:

**a. Historical Simulation VaR**
- Ambil data return historis aktual (mis. 250-500 hari terakhir), urutkan dari terburuk ke terbaik, ambil persentil ke-(100-confidence).
- Kelebihan: tidak mengasumsikan distribusi normal, menangkap kejadian nyata yang sudah pernah terjadi.
- Kekurangan: terbatas oleh apa yang *sudah pernah* terjadi di window historis — tidak menangkap kejadian ekstrem baru.

**b. Parametric VaR (Variance-Covariance)**
- Formula: `VaR = -(μ + z_score × σ) × nilai_portofolio`, di mana `z_score` untuk 95% ≈ 1.645, untuk 99% ≈ 2.326.
- Asumsi return terdistribusi normal — **asumsi ini sering dilanggar di pasar riil** (fat tails, terutama kripto & saham dengan berita mendadak). Selalu sebutkan asumsi ini sebagai keterbatasan saat melaporkan.

**c. Monte Carlo VaR**
- Simulasikan ribuan skenario harga masa depan (lihat bagian Monte Carlo di bawah), hitung distribusi P&L dari simulasi, ambil persentil yang sama seperti historical VaR.
- Kelebihan: bisa memasukkan asumsi distribusi custom (bukan cuma normal) dan skenario non-linear (opsi, portofolio kompleks).

## 2. Conditional VaR / Expected Shortfall (CVaR/ES)

- **Definisi**: rata-rata kerugian **di luar** batas VaR — menjawab pertanyaan "kalau skenario terburuk itu terjadi, seberapa buruk rata-ratanya?"
- Formula: rata-rata dari semua observasi return yang berada di ekor terburuk (di bawah threshold VaR).
- **Kenapa hedge fund lebih suka CVaR daripada VaR saja**: VaR tidak bilang apa-apa soal seberapa parah kerugian *setelah* melewati batas itu — CVaR menutup celah ini. CVaR juga secara matematis "coherent" (subadditive), sementara VaR tidak selalu.
- Selalu laporkan VaR **dan** CVaR berdampingan, jangan salah satu saja.

## 3. Simulasi Monte Carlo

**Model dasar — Geometric Brownian Motion (GBM)**, model klasik untuk simulasi harga aset:

```
S(t+1) = S(t) × exp[(μ - σ²/2)Δt + σ√Δt × Z]
```
di mana `μ` = expected return (drift), `σ` = volatilitas, `Z` = angka acak dari distribusi normal standar, `Δt` = langkah waktu (mis. 1/252 untuk harian).

**Alur kerja**:
1. Estimasi `μ` dan `σ` dari data historis (return harian, lalu anualisasi).
2. Jalankan ribuan (mis. 10.000) simulasi jalur harga ke depan N hari.
3. Dari kumpulan hasil akhir simulasi, ambil:
   - Distribusi harga/return (persentil 5/25/50/75/95)
   - VaR & CVaR Monte Carlo (lihat di atas)
   - Probabilitas mencapai target tertentu (mis. "berapa persen skenario yang mencapai take-profit sebelum stop-loss?")

**Kegunaan untuk trading/hedge fund**:
- Stress-test posisi: "kalau saya masuk sekarang, seperti apa distribusi hasil dalam 30 hari ke depan?"
- Position sizing: kombinasikan dengan Kelly Criterion (di bawah) untuk melihat risiko *ruin* pada ukuran posisi berbeda.
- Bukan prediksi pasti — GBM mengasumsikan return log-normal & volatilitas konstan, dua asumsi yang sering dilanggar pasar riil (volatility clustering, jumps). Sebutkan ini sebagai keterbatasan.

## 4. Rasio Kinerja Disesuaikan Risiko

- **Sharpe Ratio** = `(return rata-rata - risk-free rate) / std deviasi return`, dianualisasi dengan `×√252` (harian) atau `×√12` (bulanan). Mengukur return per unit total risiko (naik & turun dihitung sama).
- **Sortino Ratio** = sama seperti Sharpe tapi penyebutnya hanya **downside deviation** (std deviasi dari return negatif saja) — lebih relevan karena investor biasanya tidak keberatan dengan volatilitas ke arah untung.
- **Calmar Ratio** = `return tahunan / |maximum drawdown|` — menghubungkan return dengan risiko penurunan terbesar yang pernah dialami, populer di kalangan CTA/managed futures fund.

## 5. Maximum Drawdown

- Definisi: penurunan terbesar dari puncak (peak) ke titik terendah (trough) berikutnya sebelum rekor tertinggi baru tercapai, dalam persen.
- Formula: `Drawdown(t) = (Nilai(t) - Peak_sejauh_ini) / Peak_sejauh_ini`; Max Drawdown = nilai minimum dari seluruh seri drawdown.
- Sertakan juga **durasi** drawdown (berapa lama sampai pulih) — MDD besar dengan pemulihan cepat berbeda risikonya dari MDD kecil yang tidak kunjung pulih.

## 6. Volatilitas, Korelasi, dan Beta

- **Volatilitas tahunan** = `std deviasi return harian × √252`.
- **Matriks korelasi/kovarians** antar-aset — penting untuk portofolio multi-aset: aset dengan korelasi tinggi tidak memberi diversifikasi nyata meski namanya berbeda-beda.
- **Beta terhadap benchmark** (mis. IHSG untuk saham IDX, S&P 500 untuk saham AS) = `Cov(return_aset, return_benchmark) / Var(return_benchmark)` — mengukur sensitivitas pergerakan aset relatif terhadap pasar luas.

## 7. Kelly Criterion (Position Sizing)

- Formula (versi sederhana untuk taruhan biner win/loss): `f* = W - [(1-W)/R]`, di mana `W` = win rate historis, `R` = rasio rata-rata untung/rata-rata rugi.
- `f*` = fraksi optimal modal yang secara matematis memaksimalkan pertumbuhan jangka panjang — **tapi Kelly penuh terlalu agresif untuk kebanyakan trader** (drawdown antar-jalan bisa sangat dalam). Praktik umum hedge fund/trader profesional: pakai **fractional Kelly** (mis. 25-50% dari `f*`) untuk redam volatilitas ekuitas.
- Selalu sampaikan `f*` sebagai *referensi teoretis*, bukan instruksi langsung — jangan pernah menyarankan ukuran posisi pasti tanpa tahu modal & toleransi risiko user secara eksplisit.

## 8. Optimasi Portofolio (Markowitz Mean-Variance)

- Untuk pertanyaan yang melibatkan >1 aset ("bagaimana alokasi optimal antara BBCA, TLKM, dan emas?"): hitung expected return & matriks kovarians tiap aset, lalu cari bobot portofolio yang memaksimalkan return untuk tingkat risiko tertentu (atau minimalkan risiko untuk target return tertentu) — ini **efficient frontier**.
- Portofolio dengan Sharpe ratio tertinggi di sepanjang efficient frontier disebut **tangency portfolio**.
- Keterbatasan yang wajib disebutkan: hasil sangat sensitif terhadap estimasi expected return (yang sulit diprediksi akurat) — praktisi sering lebih percaya pada estimasi kovarians/volatilitas daripada estimasi return saat pakai model ini.

## 9. Skewness, Kurtosis & Fat Tails

- **Skewness**: distribusi return miring ke kiri (negative skew, umum di saham — crash besar sesekali) atau kanan (positive skew).
- **Kurtosis**: seberapa "gemuk" ekor distribusi dibanding normal (excess kurtosis > 0 = fat tails, kejadian ekstrem lebih sering dari yang diprediksi model normal).
- Kripto & saham individual biasanya punya fat tails signifikan — ini alasan kenapa Parametric VaR (asumsi normal) sering **meremehkan** risiko ekor untuk aset-aset ini. Selalu bandingkan dengan Historical/Monte Carlo VaR sebagai koreksi.

## 10. Stress Testing / Scenario Analysis

- Selain simulasi statistik, terapkan skenario historis konkret: "apa yang terjadi ke portofolio ini kalau kondisi seperti [crash Maret 2020 / taper tantrum 2013 / krisis 2008 / jatuhnya LUNA 2022] terulang?"
- Cari via `web_search` besaran pergerakan historis aset sejenis di periode krisis tersebut, lalu terapkan sebagai shock ke posisi saat ini — ini melengkapi VaR/Monte Carlo yang berbasis data "normal", karena krisis nyata sering di luar apa yang tertangkap model statistik biasa.

---

## Cara pakai `scripts/quant_risk.py`

```bash
pip install pandas numpy --break-system-packages   # sekali saja bila belum ada
python scripts/quant_risk.py data.csv --confidence 0.95 0.99 --mc-days 30 --mc-sims 10000
```

Input: CSV dengan kolom `date,close` minimal (kolom lain diabaikan). Skrip otomatis menghitung log-return harian dari kolom `close`.

Output mencakup: VaR & CVaR (historical, parametric, Monte Carlo) di tiap tingkat keyakinan yang diminta, Sharpe/Sortino/Calmar ratio (anualisasi), maximum drawdown + durasi, volatilitas tahunan, skewness/kurtosis, serta ringkasan distribusi hasil simulasi Monte Carlo N-hari ke depan.

Untuk analisis multi-aset (korelasi, optimasi portofolio), gunakan `--portfolio` dengan beberapa file CSV sekaligus — lihat `--help` skrip untuk opsi lengkap.

## Cara menyajikan angka-angka ini ke user

Jangan lempar angka mentah tanpa konteks. Format yang baik:

> "VaR harian 95%: -3.2% (artinya dalam kondisi normal, kerugian sehari tidak diperkirakan melebihi 3.2% dari nilai posisi, 95% dari waktu). CVaR 95%: -5.1% (tapi kalau skenario 5% terburuk itu terjadi, rata-rata kerugiannya sekitar 5.1%). Catatan: estimasi ini berbasis 250 hari data terakhir dan mengasumsikan pola volatilitas serupa berlanjut — kejadian di luar itu (mis. berita mendadak) bisa melebihi angka ini."

Selalu sertakan: metode yang dipakai, periode data, tingkat keyakinan, dan keterbatasan asumsi — persis seperti risk report internal hedge fund, bukan angka ajaib tanpa konteks.
