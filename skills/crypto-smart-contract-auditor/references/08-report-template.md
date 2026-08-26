# 08 — Template Laporan Audit Smart Contract

Gunakan template ini untuk menyusun laporan audit final. Isi setiap bagian dengan data nyata dari hasil audit.

---

# Laporan Audit Smart Contract

## 1. Informasi Umum

| Field | Nilai |
|---|---|
| **Nama Kontrak** | `<nama kontrak>` |
| **Alamat Kontrak** | `<address>` (jika ada) |
| **Jaringan/Chain** | `<Ethereum / BSC / Polygon / dll>` |
| **Versi Solidity** | `<0.8.x>` |
| **Framework** | `<Foundry / Hardhat / Truffle>` |
| **Tanggal Audit** | `<tanggal>` |
| **Auditor** | `<nama / AI-assisted>` |
| **Metodologi** | Static analysis (Slither, Aderyn), Symbolic execution (Mythril), Manual review, Foundry PoC |

## 2. Ringkasan Eksekutif

- Total temuan: **X** (Critical: X, High: X, Medium: X, Low: X, Informational: X)
- Kontrak ini mengelola dana: **Ya / Tidak**
- Risiko keseluruhan: **Critical / High / Medium / Low**
- Kesimpulan singkat (2-3 kalimat).

## 3. Ringkasan Temuan

| # | Severity | Deskripsi | SWC | Lokasi | Status |
|---|---|---|---|---|---|
| 1 | Critical | Reentrancy pada withdraw | SWC-107 | `src/Bank.sol:45` | Terbukti (PoC) |
| 2 | High | Unprotected withdrawal | SWC-105 | `src/Vault.sol:30` | Terbukti (PoC) |
| ... | ... | ... | ... | ... | ... |

## 4. Temuan Detail

### Temuan 1 — `<Judul>` (Critical)

- **SWC**: SWC-107 (Reentrancy)
- **Lokasi**: `src/Bank.sol:45-52`
- **Deskripsi**: ...
- **Dampak**: Attacker bisa menarik dana berulang kali dan menguras kontrak.
- **Bukti**:
  - Output Slither: ...
  - PoC Foundry: `test/ReentrancyPoC.t.sol` — test `test_reentrancyExploit` **gagal** (bank terkuras).
  - Potongan kode bermasalah:
    ```solidity
    (bool ok, ) = msg.sender.call{value: bal}("");
    require(ok);
    balances[msg.sender] = 0; // update state SETELAH call
    ```
- **Rekomendasi**: Terapkan pola checks-effects-interactions atau gunakan `ReentrancyGuard`. Update state sebelum pemanggilan eksternal.

### Temuan 2 — ...

*(ulangi untuk setiap temuan)*

## 5. Hasil Static Analysis (Slither & Aderyn)

- Tool yang dijalankan: Slither vX, Aderyn vX
- Perintah: `slither .`, `aderyn .`
- Temuan otomatis yang terverifikasi: ...
- Temuan otomatis yang false positive: ...
- Output mentah disimpan di: `reports/slither.json`, `reports/aderyn.md`

## 6. Hasil Symbolic Execution (Mythril)

- Tool: Mythril vX
- Perintah: `myth analyze ...`
- Temuan & counterexample: ...

## 7. Hasil Test & PoC (Foundry)

- Perintah: `forge test`
- Hasil: X test lolos, Y test gagal (menunjukkan kerentanan)
- Daftar PoC yang membuktikan kerentanan: ...

## 8. Pengecekan Standar OpenZeppelin

- Standar token: ERC-20 / ERC-721 / ERC-1155 / Bukan token
- Kepatuhan: Lolos / Tidak (rincian)
- Pola keamanan yang digunakan: ReentrancyGuard, Ownable, SafeERC20, Pausable, AccessControl, dll.
- Pola yang hilang: ...

## 9. Pemetaan SWC

| Temuan | SWC ID | Nama |
|---|---|---|
| 1 | SWC-107 | Reentrancy |
| ... | ... | ... |

## 10. Rekomendasi Prioritas

1. **Critical**: Perbaiki reentrancy segera sebelum deploy.
2. **High**: ...
3. ...

## 11. Disclaimer

> Laporan audit ini dibuat untuk tujuan riset dan edukasi teknis. Audit ini **tidak menjamin** kontrak bebas dari kerentanan — tidak ada audit yang menjamin keamanan 100%. Temuan didasarkan pada analisis pada tanggal tertentu dan kondisi kode saat itu. Untuk kontrak yang mengelola dana besar, disarankan audit profesional berbayar tambahan oleh tim independen. Laporan ini bukan nasihat keuangan.
