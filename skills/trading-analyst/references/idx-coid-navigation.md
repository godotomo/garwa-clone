# Panduan Navigasi & Pengambilan Data dari idx.co.id

Referensi ini berisi **peta navigasi persis** website resmi Bursa Efek Indonesia (`www.idx.co.id`) beserta struktur URL, pola path file, dan cara mengambil data laporan keuangan/aksi korporasi. Berlaku untuk lingkungan Garwa yang hanya punya `web_search` dan `webfetch`.

> **Catatan teknis penting:** `idx.co.id` adalah aplikasi **Nuxt.js SPA (server-side rendered)**. `webfetch` dengan `format: "html"` akan menangkap **data JSON state Nuxt yang tertanam di HTML** — ini jauh lebih berguna daripada `format: "markdown"` (yang hanya menangkap teks navigasi). Gunakan `format: "html"` untuk halaman-halaman data idx.co.id, lalu baca bagian `window.__NUXT__` / data JSON di dalamnya.

---

## 1. Peta URL halaman utama (terkonfirmasi dari state menu Nuxt)

Semua URL di bawah terverifikasi dari data menu website. Prefiks bahasa: `/id/` (Indonesia), `/en/` (Inggris).

### Perusahaan Tercatat → Laporan & data emiten
| Halaman | URL |
|---|---|
| **Laporan Keuangan & Tahunan** | `/id/perusahaan-tercatat/laporan-keuangan-dan-tahunan/` |
| Profil Perusahaan Tercatat | `/id/perusahaan-tercatat/profil-perusahaan-tercatat/` |
| **Aksi Korporasi** | `/id/perusahaan-tercatat/aksi-korporasi/` |
| Keterbukaan Informasi | `/id/perusahaan-tercatat/keterbukaan-informasi/` |
| Kalender Perusahaan Tercatat | `/id/perusahaan-tercatat/kalender-perusahaan-tercatat/` |
| Notasi Khusus | `/id/perusahaan-tercatat/notasi-khusus/` |
| Data Kepemilikan Saham | `/id/perusahaan-tercatat/data-kepemilikan-saham/` |
| Laporan Riset Ekuitas | `/id/perusahaan-tercatat/laporan-riset-ekuitas/` |
| Free Float Perusahaan Tercatat | `/id/perusahaan-tercatat/free-float-perusahaan-tercatat/` |
| XBRL | `/id/perusahaan-tercatat/xbrl/` |
| Aktivitas Pencatatan | `/id/perusahaan-tercatat/aktivitas-pencatatan/` |
| Prospektus | `/id/perusahaan-tercatat/prospektus/` |
| Daftar Efek Pemantauan Khusus | `/id/perusahaan-tercatat/daftar-efek-pemantauan-khusus/` |
| Kepemilikan Saham Terkonsentrasi Tinggi | `/id/perusahaan-tercatat/kepemilikan-saham-terkonsentrasi-tinggi/` |
| Suspensi > 6 Bulan | `/id/perusahaan-tercatat/suspensi-lebih-dari-6-bulan/` |
| Sanksi | `/id/perusahaan-tercatat/sanksi/` |

### Data Pasar → Ringkasan perdagangan
| Halaman | URL |
|---|---|
| Ringkasan Perdagangan & Rekapitulasi | `/id/data-pasar/ringkasan-perdagangan/ringkasan-perdagangan-dan-rekapitulasi` |
| Ringkasan Indeks | `/id/data-pasar/ringkasan-perdagangan/ringkasan-indeks` |
| Ringkasan Saham | `/id/data-pasar/ringkasan-perdagangan/ringkasan-saham/` |
| Ringkasan Broker | `/id/data-pasar/ringkasan-perdagangan/ringkasan-broker/` |
| Ringkasan P/E | `/id/data-pasar/ringkasan-perdagangan/ringkasan-ped/` |
| Daftar Saham | `/id/data-pasar/data-saham/daftar-saham/` |
| Data ETF | `/id/data-pasar/data-exchange-traded-fund-etf/daftar-exchange-traded-fund-etf/` |
| Informasi INAV ETF | `/id/data-pasar/data-exchange-traded-fund-etf/informasi-indicative-net-asset-value-inav-etf/` |
| Structured Warrant | `/id/data-pasar/structured-warrant-sw/...` |
| Data DIRE & DINFRA | `/id/data-pasar/dire-dinfra/` |
| Pinjam Meminjam Efek | `/id/data-pasar/pinjam-meminjam-efek/` |

### Berita & Pengumuman
| Halaman | URL |
|---|---|
| Berita | `/id/berita/berita/` |
| Siaran Pers | `/id/berita/siaran-pers/` |
| Artikel | `/id/berita/artikel/` |
| Pengumuman | `/id/berita/pengumuman/` |
| **Unusual Market Activity (UMA)** | `/id/berita/unusual-market-activity-uma/` |
| **Suspensi** | `/id/berita/suspensi/` |
| Efek Tidak Dijamin (ETD) | `/id/berita/efek-tidak-dijamin-etd/` |
| Transaksi Dipisahkan (TD) | `/id/berita/transaksi-dipisahkan-td/` |

### InvestHub & lainnya
| Halaman | URL |
|---|---|
| Stock Screener | `/id/investhub/stock-screener/` |
| Perpajakan | `/id/investhub/perpajakan/` |
| Jam & Mekanisme Perdagangan | `/id/produk-layanan/jam-dan-mekanisme-perdagangan/` |
| Jadwal Libur Bursa | `/id/tentang-bei/jadwal-libur-bursa/` |

### Situs eksternal terkait BEI
| Situs | Kegunaan |
|---|---|
| `gopublic.idx.co.id` | Pusat Info Go Public (IPO) |
| `ticmidata.co.id` | Perpustakaan pasar modal (TICMI) |
| `sustainability.idx.co.id` | Rating & penerapan ESG |
| `www.e-ipo.co.id` | e-IPO |
| `idxislamic.idx.co.id` | Pasar modal syariah |

---

## 2. Pengambilan Laporan Keuangan (prioritas utama)

### 2.1 Halaman sumber
Buka **Laporan Keuangan & Tahunan**: `https://www.idx.co.id/id/perusahaan-tercatat/laporan-keuangan-dan-tahunan/` dengan `webfetch` format **html**.

### 2.2 Filter yang tersedia di halaman
- **sort**: KodeEmiten A-Z / Z-A, Laporan terbaru, File terbanyak/tersedikit.
- **period**: Triwulan 1, Triwulan 2, Triwulan 3, Tahunan.
- **selectedYear**: tahun laporan.
- **typeReport / typeStock / selectedEmiten / itemsPerPage**.

### 2.3 Periode pelaporan (kode internal)
- `TW1` = Triwulan 1 (Q1)
- `TW2` = Triwulan 2 (Q2)
- `TW3` = Triwulan 3 (Q3)
- `audit` = Tahunan (audited)

### 2.4 Struktur path file laporan (terkonfirmasi dari data JSON)
```
/Portals/0/StaticData/ListedCompanies/Corporate_Actions/New_Info_JSX/Jenis_Informasi/
01_Laporan_Keuangan/02_Soft_Copy_Laporan_Keuangan/
Laporan Keuangan Tahun {TAHUN}/{PERIODE}/{KODE}/...
```

### 2.5 Nama file per emiten (foldernya berisi beberapa file)
- `FinancialStatement-{TAHUN}-{PERIODE}-{KODE}.pdf` — laporan keuangan (PDF)
- `FinancialStatement-{TAHUN}-{PERIODE}-{KODE}.xlsx` — laporan keuangan (Excel)
- `instance.zip` — file XBRL
- `inlineXBRL.zip` — XBRL inline
- PDF laporan lengkap (mis. `"ADHI LK_31 MARET 2026.pdf"`)
- Surat Pernyataan Direksi

> Setiap file punya metadata `File_Modified` (timestamp unggahan, mis. `2026-04-30`) — berguna untuk memastikan laporan yang diambil adalah versi terbaru.

### 2.6 Cara kerja di praktik
1. `webfetch` halaman laporan keuangan dengan `format: "html"`.
2. Cari di data JSON state Nuxt: kode emiten (mis. `ADHI`, `ADMF`, `ACES`, `AALI`, `BBRI`) dan path file di bawah `02_Soft_Copy_Laporan_Keuangan`.
3. Untuk laporan terbaru, filter `selectedYear` + `period` yang relevan.
4. Catat `File_Modified` untuk verifikasi kelengkapan/kebaruan.
5. Jika path file PDF/XLSX muncul di data, boleh langsung di-`webfetch` untuk mengunduh isinya (jangan menyusun URL dari ingatan — ambil dari data JSON yang tertanam).

### 2.7 Membaca laporan keuangan (bagian dari analisa fundamental)

Laporan keuangan emiten IDX tersedia di idx.co.id dalam format `.xlsx`, `.pdf`, atau XBRL. Untuk analisa fundamental, baca file tersebut dan ekstrak tiga komponen inti:

- **Laporan Posisi Keuangan (Neraca)** — aset, liabilitas, ekuitas.
- **Laporan Laba Rugi** — pendapatan, beban, laba (rugi).
- **Laporan Arus Kas** — arus kas aktivitas operasi/investasi/pendanaan.

Setiap perusahaan punya struktur laporan & format yang berbeda-beda, jadi **jangan menghafal atau mengasumsikan struktur spesifik** (mis. nama sheet, penamaan label, atau tata letak kolom). Cara yang benar: **buka file, baca isi barisnya, lalu kenali tiap bagian laporan dari isinya** (cari kata kunci seperti `aset`, `liabilitas`, `ekuitas`, `pendapatan`, `beban`, `laba (rugi)`, `arus kas`). Pastikan angka yang dipakai benar-benar ada (bukan label kosong), dan perhatikan satuan & periode yang dipakai sebelum membandingkan angka.

> **Penting:** jangan pernah menebak isi file. Jika ekstraksi gagal atau hasil tidak terbaca bersih, laporkan keterbatasan itu di laporan dan minta fallback ke sumber lain (RTI/Stockbit) alih-alih mengarang angka.


---

## 3. Pengambilan Aksi Korporasi

### 3.1 Halaman sumber
Buka **Aksi Korporasi**: `https://www.idx.co.id/id/perusahaan-tercatat/aksi-korporasi/` dengan `webfetch` format **html**.

### 3.2 Jenis aksi korporasi yang tersedia (dari data JSON)
- IPO / Company Listing
- HMETD (right issue)
- Stock Split
- Saham Bonus
- Dividen Saham
- Private Placement
- ESOP / MSOP
- Konversi Saham
- Penggabungan Usaha (merger)
- Delisting / Partial Delisting / Pencatatan Kembali Sebagian
- Pengurangan Modal
- Reverse Stock
- Obligasi Wajib Konversi
- Transaksi Material

### 3.3 Cara kerja di praktik
1. `webfetch` halaman aksi korporasi dengan `format: "html"`.
2. Data JSON berisi daftar aksi korporasi dengan kode emiten, jenis aksi, dan tanggal (cum-date/ex-date, tanggal efektif, dsb).
3. Untuk katalis jangka pendek, fokus pada: **dividen (cum/ex-date)**, **right issue (HMETD)**, **stock split**, **suspensi/UMA**.
4. Silangkan dengan halaman Berita → UMA/Suspensi untuk konteks.

---

## 4. Data Pasar & Ringkasan Perdagangan

Untuk harga/OHLCV saham IDX, gunakan halaman **Ringkasan Saham** atau **Ringkasan Perdagangan**:
- `https://www.idx.co.id/id/data-pasar/ringkasan-perdagangan/ringkasan-saham/`
- `https://www.idx.co.id/id/data-pasar/ringkasan-perdagangan/ringkasan-perdagangan-dan-rekapitulasi`

Ambil dengan `format: "html"` untuk mendapatkan data numerik yang tertanam di state Nuxt. Ini sumber resmi paling andal untuk harga saham IDX (prioritas 1 dalam fallback `data-sources.md`).

---

## 5. Tips teknis pengambilan

1. **Selalu `web_search` dulu** untuk memunculkan URL idx.co.id di percakapan, baru `webfetch` (konsisten dengan prinsip `data-sources.md`).
2. **Gunakan `format: "html"`** untuk halaman data — jangan `markdown` (hanya menangkap navigasi).
3. **Baca data JSON `window.__NUXT__`** yang tertanam — sumber data terstruktur (kode emiten, path file, timestamp, tanggal aksi korporasi).
4. **Jangan menyusun URL API/path file dari ingatan** — selalu ambil dari data JSON yang tertanam di halaman.
5. **Catat timestamp** — data pasar IDX punya delay; nyatakan "data per [waktu]" di laporan.
6. **Silangkan angka kritis** dengan minimal 2 sumber (idx.co.id + RTI/Stockbit) untuk keputusan beli/jual.
