# 07 — Top 20 Smart Contract Bugs (SWC Registry)

Daftar 20 kerentanan smart contract paling umum berdasarkan **SWC Registry** (Smart Contract Weakness Classification, https://swcregistry.io) dan daftar "Top 20 Smart Contract Bugs" yang sering dirujuk komunitas. Gunakan daftar ini untuk memetakan setiap temuan audit.

## Daftar Lengkap

| # | SWC ID | Nama | Deskripsi Singkat | Severity Umum |
|---|---|---|---|---|
| 1 | SWC-101 | Integer Overflow and Underflow | Operasi aritmatika melebihi batas tipe data (Solidity <0.8 tanpa SafeMath) | High |
| 2 | SWC-102 | Outdated Compiler Version | Menggunakan versi compiler lama yang punya bug | Low |
| 3 | SWC-103 | Floating Pragma | `pragma` tidak dipin (bisa compile dengan versi berbeda) | Low |
| 4 | SWC-104 | Unchecked Call Return Value | Return value dari `call`/`transfer`/`transferFrom` tidak dicek | Medium |
| 5 | SWC-105 | Unprotected Ether Withdrawal | Fungsi withdraw tanpa access control | High |
| 6 | SWC-106 | Unprotected SELFDESTRUCT Instruction | `selfdestruct` bisa dipanggil siapa saja | High |
| 7 | SWC-107 | Reentrancy | Pemanggilan eksternal sebelum update state | Critical |
| 8 | SWC-108 | State Variable Default Visibility | Variabel state `public`/`internal` tidak dideklarasikan eksplisit | Medium |
| 9 | SWC-109 | Uninitialized Storage Pointer | Storage pointer tidak diinisialisasi | High |
| 10 | SWC-110 | Assert Violation | `assert` gagal (bug internal) | Medium |
| 11 | SWC-111 | Use of Deprecated Solidity Functions | Menggunakan fungsi deprecated (mis. `suicide`, `block.blockhash`) | Low |
| 12 | SWC-112 | Delegatecall to Untrusted Callee | `delegatecall` ke alamat yang bisa dikontrol user | Critical |
| 13 | SWC-113 | DoS with Failed Call | Pemanggilan eksternal yang gagal menghentikan fungsi | Medium |
| 14 | SWC-114 | Transaction Ordering Dependence | Hasil bergantung urutan transaksi (front-running) | Medium |
| 15 | SWC-115 | Authorization through tx.origin | Otorisasi via `tx.origin` bukan `msg.sender` | High |
| 16 | SWC-116 | Block Values as a Proxy for Time | Menggunakan `block.timestamp`/`block.number` untuk logika penting | Medium |
| 17 | SWC-117 | Signature Malleability | Signature bisa dimodifikasi tanpa invalid | Medium |
| 18 | SWC-118 | Incorrect Constructor Name | Constructor salah nama (Solidity <0.4.22) | High |
| 19 | SWC-119 | Shadowing State Variables | Variabel state di-shadow oleh variabel lokal | Low |
| 20 | SWC-120 | Weak Sources of Randomness from Chain Attributes | Randomness dari `blockhash`/`block.timestamp` bisa dimanipulasi | High |
| 21 | SWC-121 | Missing Protection against Signature Replay Attacks | Signature bisa di-replay di chain lain | Medium |
| 22 | SWC-122 | Uninitialized Function Pointer | Function pointer tak diinisialisasi | High |
| 23 | SWC-123 | Requirement Violation | `require` yang bisa dilanggar | Medium |
| 24 | SWC-124 | Write to Arbitrary Storage Location | Menulis ke storage arbitrer (via assembly) | High |
| 25 | SWC-125 | Incorrect Inheritance Order | Urutan inheritance salah | Medium |
| 26 | SWC-126 | Insufficient Gas Griefing | Gas tidak cukup untuk sub-call (griefing) | Medium |
| 27 | SWC-127 | Arbitrary Jump with Function Type Variable | Jump arbitrer via function type | High |
| 28 | SWC-128 | DoS With Block Gas Limit | Loop tak terbatas melebihi gas limit | Medium |
| 29 | SWC-129 | Typographical Error | Kesalahan ketik pada nama fungsi/variabel | Medium |
| 30 | SWC-130 | Improper Authorization | Otorisasi tidak tepat | High |
| 131 | SWC-131 | Presence of unused variables | Variabel tidak terpakai | Informational |
| 132 | SWC-132 | Unexpected Ether balance | Kontrak menerima ETH tak terduga | Informational |
| 133 | SWC-133 | Hash Collisions With Multiple Variable Length Arguments | Collision hash dengan argumen variabel | Medium |
| 134 | SWC-134 | Message call with hardcoded gas amount | `call` dengan gas hardcoded | Low |
| 135 | SWC-135 | Code With No Effects | Kode tanpa efek | Informational |
| 136 | SWC-136 | Unlocked Compiler Version | Compiler tidak dikunci | Low |
| 137 | SWC-137 | Missing Zero Address Validation | Tidak validasi alamat zero | Low |
| 138 | SWC-138 | Unprotected NFT Minting | Mint NFT tanpa kontrol | Medium |
| 139 | SWC-139 | Deprecated Selfdestruct | `selfdestruct` deprecated | Low |
| 140 | SWC-140 | Weak Randomness | Randomness lemah | High |
| 141 | SWC-141 | Incorrect Modifier | Modifier salah | Medium |
| 142 | SWC-142 | Unprotected Initializer | `initialize` tanpa proteksi | Critical |
| 143 | SWC-143 | Centralization Risk | Kontrol terpusat berlebihan | Medium |
| 144 | SWC-144 | Improper Verification of Cryptographic Signature | Verifikasi signature salah | High |
| 145 | SWC-145 | Excessive Gas Consumption | Konsumsi gas berlebihan | Low |
| 146 | SWC-146 | Missing Zero Address Validation | Validasi alamat zero hilang | Low |
| 147 | SWC-147 | Improper Initialization | Inisialisasi tidak tepat | High |
| 148 | SWC-148 | Improper Verification of Source Code | Verifikasi source code salah | Medium |
| 149 | SWC-149 | Unprotected Token Minting | Mint token tanpa kontrol | High |
| 150 | SWC-150 | Improper Verification of Ownership | Verifikasi kepemilikan salah | High |
| 151 | SWC-151 | Improper Verification of Function Arguments | Verifikasi argumen salah | Medium |
| 152 | SWC-152 | Improper Verification of Contract Address | Verifikasi alamat kontrak salah | Medium |
| 153 | SWC-153 | Improper Verification of Token Balance | Verifikasi balance token salah | Medium |
| 154 | SWC-154 | Improper Verification of Token Supply | Verifikasi supply token salah | Medium |
| 155 | SWC-155 | Improper Verification of Token Transfer | Verifikasi transfer token salah | Medium |
| 156 | SWC-156 | Improper Verification of Token Approval | Verifikasi approval token salah | Medium |
| 157 | SWC-157 | Improper Verification of Token Metadata | Verifikasi metadata token salah | Low |
| 158 | SWC-158 | Improper Verification of Token Standard | Verifikasi standar token salah | Medium |
| 159 | SWC-159 | Improper Verification of Token Contract | Verifikasi kontrak token salah | Medium |
| 160 | SWC-160 | Improper Verification of Token Owner | Verifikasi owner token salah | Medium |

## Top 20 yang Paling Sering Dieksploitasi (Fokus Audit)

Berdasarkan data eksploitasi nyata (rekt.news, DeFi exploits), kerentanan yang paling sering menyebabkan kehilangan dana:

1. **Reentrancy (SWC-107)** — drain dana via pemanggilan berulang.
2. **Access Control / Unprotected Withdrawal (SWC-105, SWC-130)** — siapa pun bisa menarik dana.
3. **Integer Overflow/Underflow (SWC-101)** — manipulasi balance.
4. **Oracle Manipulation** — manipulasi harga oracle (bukan SWC standar, tapi umum di DeFi).
5. **Flash Loan Attack** — kombinasi kerentanan dengan flash loan.
6. **Delegatecall to Untrusted Callee (SWC-112)** — eksekusi kode arbitrer.
7. **Unprotected Initializer (SWC-142)** — front-run `initialize` untuk mengambil alih proxy.
8. **Weak Randomness (SWC-120, SWC-140)** — prediksi hasil lotere/game.
9. **Signature Replay (SWC-121)** — replay transaksi di chain lain.
10. **Fee-on-transfer / Rebasing mismatch** — asumsi balance salah.
11. **Rounding Error** — pembagian yang menguntungkan attacker.
12. **Denial of Service (SWC-113, SWC-128)** — fungsi macet.
13. **tx.origin Authorization (SWC-115)** — phishing.
14. **Selfdestruct (SWC-106)** — hancurkan kontrak.
15. **Unchecked Call Return (SWC-104)** — transfer gagal diam-diam.
16. **Storage Collision (proxy)** — layout storage bentrok.
17. **Missing Zero Address Validation (SWC-137)** — token terkunci.
18. **Centralization Risk (SWC-143)** — admin bisa rug pull.
19. **Incorrect Inheritance Order (SWC-125)** — shadowing/override salah.
20. **Uninitialized Storage Pointer (SWC-109)** — baca/tulis storage salah.

## Cara Menggunakan Daftar Ini

1. Untuk setiap temuan audit, cari SWC ID yang paling sesuai.
2. Cantumkan SWC ID di laporan (mis. "SWC-107: Reentrancy").
3. Beri skor keparahan (Critical/High/Medium/Low) dan kemungkinan eksploitasi.
4. Gunakan daftar "paling sering dieksploitasi" sebagai prioritas review.
