# Template Laporan Riset Kripto

Gunakan struktur ini untuk "analisis lengkap koin/token", sesuaikan/pangkas bagian yang tidak relevan kalau user cuma minta satu aspek spesifik (mis. cuma minta cek rug pull saja, tidak usah paksakan semua bagian).

```markdown
## [Nama Koin/Token] ([TICKER]) — Ringkasan Riset
*Data diambil: [tanggal & waktu], sumber: [daftar sumber yang benar-benar dipakai]*

### 📊 Data Pasar
- Harga: $X (▲/▼ X% 24h, X% 7d)
- Market Cap: $X (Rank #X)
- Volume 24h: $X
- Supply: beredar X / total X / max X

### 🐋 Whale & On-Chain
- [Temuan transaksi besar/pola holder/likuiditas, dengan angka & sumber konkret]
- [Klasifikasi: akumulasi / distribusi / netral, dengan alasan]

### 🔐 Keamanan & Risiko Rug Pull
- Level Risiko: [Low/Medium/High/Critical]
- [Ringkas 3-5 temuan kunci dari checklist di 05-security-rugpull.md]

### 📰 Sentimen & Berita
- Fear & Greed Index: X ([klasifikasi]), tren [naik/turun] dari X hari lalu
- Katalis berita terkini: [2-4 poin dengan tanggal]
- Konteks makro relevan: [The Fed / regulasi / dll kalau relevan]
- Kesimpulan sentimen: [Bullish/Bearish/Netral-campuran] — [alasan]

### 🧭 Sintesis
[2-4 kalimat menghubungkan semua bagian di atas — bukan pengulangan, tapi insight: mis. "harga naik didorong sentimen positif berita X, tapi whale justru net outflow ke exchange, sementara audit kontrak bersih — kombinasi ini menunjukkan..."]

---
⚠️ **Ini bukan nasihat keuangan.** Data di atas adalah hasil riset dari sumber publik untuk tujuan edukasi; harga kripto sangat volatil dan setiap keputusan investasi sepenuhnya risiko & tanggung jawab Anda sendiri. Selalu DYOR (Do Your Own Research) dan pertimbangkan konsultasi dengan penasihat keuangan berlisensi untuk keputusan besar.
```

## Prinsip tambahan
- Kalau data untuk satu bagian tidak berhasil diambil, tulis eksplisit: *"Data on-chain tidak dapat diambil karena [alasan] — analisis di bawah hanya berdasarkan data pasar & sentimen."* Jangan hapus bagian itu diam-diam.
- Untuk perbandingan banyak koin sekaligus, pertimbangkan tabel markdown ringkas alih-alih mengulang template penuh per koin.
- Bahasa mengikuti bahasa user (Indonesia kalau user pakai Indonesia).
