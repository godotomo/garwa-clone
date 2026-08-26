# 01 — Setup Tool & Lingkungan Audit

Panduan instalasi dan konfigurasi tool yang digunakan untuk audit smart contract Solidity/EVM.

## Prasyarat Umum

- **Python 3.8+** (untuk Slither, Mythril)
- **Node.js 16+** (untuk Hardhat, solc, OpenZeppelin)
- **Rust** (untuk Aderyn)
- **Git**

## 1. Slither (Static Analysis)

Slither adalah framework static analysis untuk Solidity dari Trail of Bits. Cepat, mendeteksi banyak kerentanan umum.

```bash
# Instalasi via pip
pip3 install slither-analyzer

# Cek versi
slither --version
```

### Dependensi tambahan (opsional, untuk deteksi lebih baik)
```bash
pip3 install solc-select
solc-select install 0.8.24
solc-select use 0.8.24
```

## 2. Aderyn (Static Analyzer, Rust)

Aderyn dari Cyfrin adalah static analyzer Solidity modern yang cepat dan mudah diintegrasikan.

```bash
# Instalasi via cargo
cargo install aderyn

# Atau via prebuilt binary (lihat release di GitHub Cyfrin/aderyn)
# Cek versi
aderyn --version
```

## 3. Mythril (Symbolic Execution)

Mythril dari ConsenSys Diligence menganalisis EVM bytecode dengan symbolic execution untuk mendeteksi kerentanan.

```bash
# Instalasi via pip
pip3 install mythril

# Cek versi
myth --version
```

> Catatan: Mythril membutuhkan `solc` dan terkadang `z3`/`z3-solver`. Jika instalasi bermasalah, pastikan `solc` tersedia di PATH.

## 4. Foundry (Forge — Testing & PoC)

Foundry adalah framework development Ethereum yang cepat, ditulis dalam Rust. `forge` untuk testing, `cast` untuk interaksi, `anvil` untuk node lokal.

```bash
# Instalasi via foundryup
curl -L https://foundry.paradigm.xyz | bash
foundryup

# Cek versi
forge --version
cast --version
anvil --version
```

### Inisialisasi proyek Foundry
```bash
forge init nama-proyek
cd nama-proyek
forge build
forge test
```

## 5. Hardhat (Alternatif, opsional)

```bash
npm init -y
npm install --save-dev hardhat
npx hardhat
```

## 6. OpenZeppelin Contracts (Standar)

```bash
# Di proyek Foundry
forge install OpenZeppelin/openzeppelin-contracts

# Di proyek Hardhat/npm
npm install @openzeppelin/contracts
```

## 7. Verifikasi Ketersediaan Tool

Sebelum memulai audit, jalankan:
```bash
slither --version
aderyn --version
myth --version
forge --version
```

Jika ada tool yang belum terpasang, beri tahu user dan berikan perintah instalasi di atas. **Lanjutkan audit dengan tool yang tersedia** + manual review + penulisan test (yang bisa dijalankan setelah tool terpasang).

## Struktur Direktori Audit yang Disarankan

```
audit/<nama-kontrak>/
├── src/          # kode kontrak yang diaudit
├── tests/        # test & PoC exploit (Foundry)
├── reports/      # laporan audit final
└── README.md     # ringkasan
```
