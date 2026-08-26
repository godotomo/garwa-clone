# 03 — Mythril (Symbolic Execution)

Panduan penggunaan Mythril untuk analisis smart contract berbasis symbolic execution.

## Apa itu Mythril

Mythril (dari ConsenSys Diligence) menganalisis **EVM bytecode** menggunakan symbolic execution dan constraint solving (z3) untuk menemukan jalur eksekusi yang bisa mengeksploitasi kerentanan. Berbeda dengan Slither (static analysis), Mythril mengeksplorasi jalur eksekusi secara simbolik sehingga bisa menemukan bug yang bergantung pada kondisi runtime.

## Menjalankan Mythril

```bash
# Analisis file Solidity (Mythril akan compile dulu)
myth analyze path/to/Contract.sol

# Analisis bytecode
myth analyze --bin-runtime 0x<bytecode>

# Analisis dengan alamat kontrak (perlu RPC)
myth analyze -a 0x<address> --rpc <rpc-url>

# Batasi kedalaman eksekusi (untuk kecepatan)
myth analyze path/to/Contract.sol --execution-timeout 60

# Output JSON
myth analyze path/to/Contract.sol --json
```

## Kerentanan yang Dideteksi Mythril

| Kerentanan | SWC |
|---|---|
| Integer Overflow/Underflow | SWC-101 |
| Reentrancy | SWC-107 |
| Unprotected Ether Withdrawal | SWC-105 |
| Delegatecall ke alamat arbitrer | SWC-112 |
| Unchecked Send/Transfer | SWC-104 |
| State variable tak diinisialisasi | SWC-109 |
| Assertion failure | SWC-110 |
| Exception disorder | SWC-113 |
| Timestamp dependency | SWC-116 |
| Block number dependency | SWC-114 |
| Selfdestruct | SWC-106 |

## Interpretasi Hasil Mythril

- Mythril menghasilkan **counterexample** (jalur transaksi yang memicu bug) — ini sangat berguna sebagai bukti.
- Mythril bisa lambat pada kontrak kompleks. Gunakan `--execution-timeout` untuk membatasi.
- Mythril juga punya **false positive** — verifikasi manual tetap wajib.
- Counterexample dari Mythril bisa dijadikan dasar untuk menulis PoC di Foundry.

## Contoh Output

Mythril menampilkan jalur transaksi yang memicu kerentanan, misalnya:

```
SWC ID: 107
Title: Reentrancy
Impact: ...
Transaction Sequence:
1. Caller: 0x... , Data: ...
2. Caller: 0x... , Data: ...
```

Gunakan urutan transaksi ini untuk menyusun test/PoC di Foundry (lihat `05-foundry-testing.md`).

## Praktik Terbaik

1. Jalankan Mythril **setelah** Slither/Aderyn untuk menambah kedalaman analisis.
2. Fokuskan Mythril pada fungsi-fungsi yang menangani dana atau pemanggilan eksternal.
3. Simpan output mentah sebagai bukti di folder `reports/`.
4. Gunakan counterexample Mythril untuk menulis PoC yang membuktikan kerentanan.
