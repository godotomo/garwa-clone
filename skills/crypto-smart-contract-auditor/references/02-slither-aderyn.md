# 02 — Slither & Aderyn (Static Analysis)

Panduan penggunaan Slither dan Aderyn untuk static analysis smart contract, beserta interpretasi hasil.

## Slither

### Menjalankan Slither

```bash
# Analisis satu file
slither path/to/Contract.sol

# Analisis seluruh proyek (Hardhat/Foundry)
slither .

# Dengan remapping OpenZeppelin (Foundry)
slither . --foundry-out-directory out

# Output JSON (untuk parsing)
slither path/to/Contract.sol --json report.json

# Hanya printer tertentu
slither path/to/Contract.sol --print human-summary
slither path/to/Contract.sol --print contract-summary
slither path/to/Contract.sol --print call-graph
```

### Detektor bawaan Slither (contoh penting)

| Detektor | Kerentanan | SWC |
|---|---|---|
| `reentrancy-eth` | Reentrancy via ETH | SWC-107 |
| `reentrancy-no-eth` | Reentrancy via token | SWC-107 |
| `unchecked-transfer` | Transfer tanpa cek return | SWC-104 |
| `arbitrary-send-erc20` | Transfer ERC-20 ke alamat arbitrer | SWC-104 |
| `arbitrary-send-eth` | Transfer ETH ke alamat arbitrer | SWC-105 |
| `uninitialized-state` | State variable tidak diinisialisasi | SWC-109 |
| `controlled-delegatecall` | Delegatecall dengan input user | SWC-112 |
| `suicidal` | Fungsi yang bisa selfdestruct | SWC-106 |
| `tx-origin` | Penggunaan tx.origin | SWC-115 |
| `timestamp` | Manipulasi block.timestamp | SWC-116 |
| `assembly` | Penggunaan assembly | — |
| `low-level-calls` | Pemanggilan low-level | — |
| `uninitialized-function-pointer` | Function pointer tak diinisialisasi | SWC-109 |
| `incorrect-equality` | Perbandingan dengan nilai exact (block.timestamp) | — |

### Interpretasi Hasil Slither

- Slither menghasilkan **banyak false positive**. Setiap temuan harus **diverifikasi manual** dengan membaca kode di sekitar lokasi yang ditunjuk.
- Perhatikan **konteks**: mis. `unchecked-transfer` mungkin aman jika token yang dipakai selalu mengembalikan `true` (seperti OpenZeppelin ERC-20), tapi berbahaya untuk token lain.
- Slither tidak mendeteksi kerentanan logika bisnis yang kompleks — itu tugas manual review.

## Aderyn

### Menjalankan Aderyn

```bash
# Analisis proyek
aderyn .

# Output ke file
aderyn . -o report.md

# Analisis satu file
aderyn path/to/Contract.sol
```

### Keunggulan Aderyn

- Sangat cepat (ditulis dalam Rust).
- Mendeteksi pola berbahaya modern, termasuk masalah terkait ERC-20, access control, dan reentrancy.
- Mudah diintegrasikan ke editor/CI.

### Interpretasi Hasil Aderyn

- Sama seperti Slither: verifikasi manual setiap temuan.
- Aderyn memberi konteks baris dan fungsi yang membantu pelacakan.

## Praktik Terbaik

1. Jalankan **kedua tool** (Slither + Aderyn) dan **bandingkan** hasilnya — temuan yang muncul di keduanya lebih kredibel.
2. **Jangan langsung percaya** — baca kode di sekitar setiap temuan.
3. Kategorikan temuan: **Critical / High / Medium / Low / Informational**.
4. Simpan output mentah tool di folder `reports/` sebagai bukti.
5. Untuk temuan yang berpotensi dieksploitasi, lanjutkan ke **Fase 4 (Foundry PoC)** untuk membuktikan.
