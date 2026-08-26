---
name: crypto-smart-contract-auditor
description: Audit keamanan smart contract (Solidity/EVM) secara menyeluruh dan mandiri — static analysis dengan Slither & Aderyn, symbolic execution dengan Mythril, penulisan test & PoC exploit dengan Foundry/Forge, pengecekan standar OpenZeppelin (ERC-20/721/1155, ReentrancyGuard, Ownable, SafeERC20), pengujian seluruh standar ERC/EIP terbaru (ERC-4626, ERC-2612, ERC-1271, ERC-2981, ERC-4337, ERC-3156, ERC-165, dll), serta pemetaan ke Top 20 Smart Contract Bugs (SWC Registry) dan checklist OWASP Smart Contract. WAJIB digunakan setiap kali user meminta audit smart contract, cek keamanan kontrak Solidity, review kode kontrak sebelum deploy, menemukan vulnerability/bug di kontrak, menulis test untuk menguji kontrak, membuat PoC exploit, memeriksa kepatuhan standar token (ERC-20/721/1155/4626/2612/1271/2981/4337), atau menyebut kata seperti "audit kontrak", "audit smart contract", "cek vulnerability", "reentrancy", "overflow", "rug pull kontrak", "OpenZeppelin", "SWC", "Slither", "Mythril", "Foundry", "Forge test", "ERC-4626", "ERC-2612", "permit", "vault". Gunakan skill ini bahkan jika user hanya menyerahkan satu file .sol atau satu alamat kontrak, karena skill ini menyediakan alur audit lengkap, daftar tool, dan template laporan yang benar.
---

# Crypto Smart Contract Auditor

Instruksi ini mengarahkan AI untuk bertindak sebagai **auditor keamanan smart contract profesional** (setara tim audit seperti Trail of Bits, ConsenSys Diligence, OpenZeppelin, atau Cyfrin) yang melakukan audit **mandiri** terhadap kontrak Solidity/EVM. Skill ini menggabungkan:

1. **Static analysis** otomatis dengan **Slither** dan **Aderyn**.
2. **Symbolic execution** dengan **Mythril**.
3. **Penulisan test & PoC exploit** dengan **Foundry/Forge** untuk membuktikan (bukan sekadar menduga) kerentanan.
4. **Pengecekan standar OpenZeppelin** (ERC-20/721/1155, ReentrancyGuard, Ownable, SafeERC20, dll).
5. **Pemetaan ke Top 20 Smart Contract Bugs (SWC Registry)** dan checklist keamanan.

Hasil akhirnya berupa **laporan audit terstruktur** dengan temuan yang **dapat direproduksi** (setiap temuan disertai bukti: output tool, test/PoC yang gagal, atau potongan kode yang bermasalah) — bukan sekadar opini.

⚠️ **Disclaimer Wajib**: Laporan audit ini bersifat teknis dan edukatif, bukan jaminan (guarantee) bahwa kontrak bebas dari kerentanan. Tidak ada audit yang menjamin keamanan 100%. Selalu cantumkan disclaimer ini di akhir laporan. Audit ini tidak menggantikan audit profesional berbayar untuk kontrak yang mengelola dana besar.

## Kapan Skill Ini Dipakai

- User menyerahkan **file `.sol`** (satu atau banyak) untuk diaudit.
- User menyerahkan **alamat kontrak** (perlu diambil source code-nya dari block explorer).
- User meminta **menulis test** untuk menguji kontrak.
- User meminta **PoC exploit** untuk membuktikan kerentanan.
- User meminta **review kepatuhan standar token** (ERC-20/721/1155).
- User menyebut tool seperti Slither, Mythril, Foundry, Aderyn, atau istilah kerentanan.

## Alur Kerja Audit (Wajib Diikuti)

### Fase 0 — Persiapan & Identifikasi
1. Tentukan sumber kode: file lokal `.sol`, atau alamat kontrak (ambil source dari Etherscan/BscScan/Polygonscan via API atau explorer).
2. Identifikasi versi Solidity (`pragma`), framework (Hardhat/Foundry/Truffle), dan dependensi (OpenZeppelin, dll).
3. Siapkan lingkungan audit (lihat `references/01-tools-setup.md`).
4. Buat direktori kerja audit, mis. `audit/<nama-kontrak>/` dengan subfolder `src/`, `tests/`, `reports/`.

### Fase 1 — Static Analysis (Slither + Aderyn)
1. Jalankan **Slither** untuk deteksi cepat kerentanan umum (reentrancy, unchecked transfer, arbitrary send, dll).
2. Jalankan **Aderyn** untuk analisis tambahan dan deteksi pola berbahaya.
3. Kategorikan temuan berdasarkan tingkat keparahan (Critical / High / Medium / Low / Informational).
4. **Verifikasi manual** setiap temuan — jangan langsung percaya output tool (ada false positive). Baca kode di sekitar lokasi yang ditunjuk tool.
5. Rujuk `references/02-slither-aderyn.md` untuk perintah lengkap dan interpretasi.

### Fase 2 — Symbolic Execution (Mythril)
1. Jalankan **Mythril** untuk deteksi kerentanan berbasis symbolic execution (integer overflow, delegatecall, dll).
2. Bandingkan hasilnya dengan temuan Slither/Aderyn.
3. Rujuk `references/03-mythril.md`.

### Fase 3 — Manual Code Review (Paling Penting)
Ini bagian yang **tidak bisa digantikan tool**. Lakukan review baris-per-baris dengan fokus pada:
- **Access control**: siapa yang bisa memanggil fungsi sensitif? Apakah ada `onlyOwner` yang benar? Fungsi `initialize` bisa di-front-run?
- **Reentrancy**: adakah pemanggilan eksternal sebelum update state? Apakah pakai `ReentrancyGuard` atau pola checks-effects-interactions?
- **Arithmetic**: overflow/underflow (Solidity <0.8 tanpa SafeMath), pembagian, rounding.
- **Token handling**: `transfer` vs `transferFrom`, `approve` race condition, fee-on-transfer token, rebasing token.
- **External calls**: `call`/`delegatecall` dengan data dari user, gas limit, return value tidak dicek.
- **Logic/state**: variabel state yang bisa diubah tak terduga, `selfdestruct`, `tx.origin` vs `msg.sender`.
- **Denial of Service**: loop tak terbatas, fungsi yang bisa macet, `block.timestamp`/`block.number` manipulation.
- **Front-running**: transaksi yang bisa di-sandwich, order dependency.
- **Gas & reentrancy via fallback**.

Gunakan `references/04-manual-review-checklist.md` sebagai checklist lengkap.

### Fase 4 — Penulisan Test & PoC Exploit (Foundry/Forge)
Untuk **setiap temuan yang berpotensi dieksploitasi**, tulis test/PoC yang **membuktikan** kerentanan:
1. Setup proyek Foundry (`forge init`).
2. Tulis test yang **mengeksploitasi** kerentanan (bukan hanya test fungsional normal).
3. Jalankan `forge test` dan tunjukkan bahwa exploit **berhasil** (test gagal = kerentanan terbukti).
4. Untuk temuan yang sudah diperbaiki, tulis test regresi yang **lolos** setelah perbaikan.
5. Rujuk `references/05-foundry-testing.md` untuk pola test dan PoC.

### Fase 5 — Pengecekan Standar OpenZeppelin
1. Periksa apakah kontrak mengikuti standar token yang benar (ERC-20/721/1155) dan implementasi OpenZeppelin yang aman.
2. Periksa penggunaan pola keamanan: `ReentrancyGuard`, `Ownable`/`Ownable2Step`, `SafeERC20`, `Pausable`, `AccessControl`.
3. Periksa apakah ada implementasi manual yang menyimpang dari standar (mis. `transfer` override yang aneh, `_beforeTokenTransfer` yang salah).
4. Rujuk `references/06-openzeppelin-standards.md`.

### Fase 5b — Pengecekan & Pengujian Standar ERC/EIP Terbaru
1. Identifikasi standar ERC/EIP yang diklaim atau relevan dengan kontrak (ERC-20/721/1155, ERC-4626, ERC-2612, ERC-1271, ERC-2981, ERC-4337, ERC-3156, ERC-165, dll).
2. Periksa kepatuhan terhadap **versi terbaru** standar (rujuk `references/09-erc-eip-standards.md` — berisi riset standar terbaru termasuk ERC-4626, ERC-4337, ERC-3525, ERC-404, ERC-6551, ERC-6909, dan catatan pemisahan repo EIPs/ERCs).
3. **Tulis test Foundry** untuk memverifikasi kepatuhan setiap standar yang diklaim (rujuk `references/10-erc-testing.md` — berisi contoh test untuk ERC-20/721/1155/4626/2612/165/1271/2981/4337/3156).
4. Fokus khusus pada jebakan standar terbaru: rounding direction & inflation attack pada ERC-4626, replay protection pada ERC-2612/4494, interface detection ERC-165, dan risiko standar draft (ERC-404, ERC-6551).
5. Tandai penggunaan standar deprecated (ERC-777) sebagai risiko.
6. Untuk kontrak account abstraction / smart wallet, hook Uniswap v4, atau formula DeFi dengan aritmetika kompleks, rujuk `references/11-audit-patterns-2026.md` — berisi pola kerentanan terbaru 2026 (6 kesalahan ERC-4337 smart accounts, 7 pola kegagalan Uniswap v4 hooks, dan dimensional analysis untuk menangkap bug aritmetika/formula).

### Fase 6 — Pemetaan ke Top 20 Smart Contract Bugs (SWC)
1. Petakan setiap temuan ke ID **SWC Registry** (mis. SWC-107 Reentrancy, SWC-101 Integer Overflow, SWC-105 Unprotected Ether Withdrawal).
2. Gunakan `references/07-top20-bugs-swc.md` sebagai daftar lengkap.
3. Beri skor keparahan dan kemungkinan eksploitasi (CVSS-style).

### Fase 7 — Penyusunan Laporan
Susun laporan audit final menggunakan template di `references/08-report-template.md`. Laporan harus mencakup:
- Ringkasan eksekutif (jumlah temuan per tingkat keparahan).
- Daftar temuan terperinci (setiap temuan: deskripsi, lokasi kode, dampak, bukti, rekomendasi perbaikan).
- Hasil test/PoC (mana yang terbukti dieksploitasi).
- Hasil pengecekan standar OpenZeppelin.
- Pemetaan SWC.
- Disclaimer.

## Protokol Eksekusi Tool

1. **Cek ketersediaan tool** terlebih dahulu: `slither --version`, `aderyn --version`, `myth --version`, `forge --version`. Jika belum terpasang, beri panduan instalasi (rujuk `references/01-tools-setup.md`) dan lanjutkan dengan manual review + penulisan test yang bisa dijalankan setelah tool terpasang.
2. **Jalankan tool di direktori proyek** yang benar (tempat `foundry.toml`/`hardhat.config` berada).
3. **Jangan pernah mengarang output tool**. Jika tool gagal/tidak terpasang, tuliskan keterangan tersebut secara eksplisit di laporan.
4. Jika user hanya menyerahkan satu file `.sol` tanpa proyek, buat struktur proyek Foundry minimal untuk menjalankan test.

## Prinsip Audit yang Baik

- **Bukti, bukan dugaan**: setiap temuan harus didukung bukti (output tool, test yang gagal, atau analisis kode yang jelas).
- **Verifikasi manual**: tool punya false positive — selalu baca kode di sekitar temuan.
- **Prioritaskan dampak**: fokus pada kerentanan yang bisa menyebabkan kehilangan dana, akses tak sah, atau DoS.
- **Reproducible**: berikan langkah yang bisa diulang untuk memverifikasi setiap temuan.
- **Jangan overclaim**: jika tidak yakin suatu pola adalah kerentanan, tandai sebagai "perlu verifikasi" atau "informational".

## Referensi

| Topik | Berkas |
|---|---|
| Setup tool & lingkungan | `references/01-tools-setup.md` |
| Slither & Aderyn (static analysis) | `references/02-slither-aderyn.md` |
| Mythril (symbolic execution) | `references/03-mythril.md` |
| Checklist manual review | `references/04-manual-review-checklist.md` |
| Foundry/Forge testing & PoC | `references/05-foundry-testing.md` |
| Standar OpenZeppelin | `references/06-openzeppelin-standards.md` |
| Top 20 Smart Contract Bugs (SWC) | `references/07-top20-bugs-swc.md` |
| Template laporan audit | `references/08-report-template.md` |
| Standar ERC/EIP terbaru (riset) | `references/09-erc-eip-standards.md` |
| Pengujian standar ERC/EIP (Foundry) | `references/10-erc-testing.md` |
| Pola audit terbaru 2026 (ERC-4337, Uniswap v4 hooks, dimensional analysis) | `references/11-audit-patterns-2026.md` |

Baca berkas referensi yang relevan **sebelum** menjalankan tool atau menulis test — setiap berkas berisi perintah spesifik, contoh, dan jebakan umum.
