# 04 — Checklist Manual Code Review

Checklist ini adalah bagian **paling penting** dari audit — tool otomatis tidak bisa menangkap kerentanan logika bisnis. Lakukan review baris-per-baris dengan checklist berikut.

## A. Access Control

- [ ] Fungsi sensitif (withdraw, mint, setOwner, setFee, pause) dilindungi modifier yang benar (`onlyOwner`, `onlyRole`, dll)?
- [ ] Apakah ada fungsi `initialize` (proxy pattern) yang bisa di-front-run oleh attacker untuk mengambil alih kontrak?
- [ ] Apakah `tx.origin` digunakan untuk otorisasi? (harusnya `msg.sender`) — SWC-115
- [ ] Apakah ada fungsi `public`/`external` yang seharusnya `internal`/`private`?
- [ ] Apakah `owner` bisa diubah tanpa verifikasi (harusnya `Ownable2Step` untuk keamanan)?
- [ ] Apakah ada fungsi yang bisa dipanggil siapa saja tapi seharusnya dibatasi?

## B. Reentrancy

- [ ] Apakah ada pemanggilan eksternal (`call`, `transfer`, `send`, interaksi ERC-20) **sebelum** update state? — SWC-107
- [ ] Apakah pola **checks-effects-interactions** diikuti?
- [ ] Apakah `ReentrancyGuard` digunakan pada fungsi yang menangani dana?
- [ ] Apakah ada reentrancy via fallback/receive function?
- [ ] Apakah ada reentrancy lintas-kontrak (cross-function)?

## C. Arithmetic & Overflow

- [ ] Apakah Solidity <0.8 tanpa SafeMath? (overflow/underflow) — SWC-101
- [ ] Apakah ada pembagian yang bisa menghasilkan rounding error / pembagian nol?
- [ ] Apakah ada operasi aritmatika pada nilai yang bisa dimanipulasi user?
- [ ] Apakah ada `unchecked` block yang berbahaya?

## D. Token Handling

- [ ] Apakah `transfer`/`transferFrom` return value dicek? (harusnya `SafeERC20`) — SWC-104
- [ ] Apakah ada race condition pada `approve` (harusnya `increaseAllowance`/`decreaseAllowance`)?
- [ ] Apakah kontrak kompatibel dengan **fee-on-transfer** token? (balance berubah saat transfer)
- [ ] Apakah kontrak kompatibel dengan **rebasing** token?
- [ ] Apakah kontrak kompatibel dengan token yang tidak mengembalikan `bool` (USDT)?
- [ ] Apakah ada asumsi jumlah token yang diterima = jumlah yang diminta?

## E. External Calls

- [ ] Apakah `call`/`delegatecall` menggunakan data dari user? — SWC-112
- [ ] Apakah return value dari `call` dicek? (gagal harus revert)
- [ ] Apakah ada `delegatecall` ke kontrak yang bisa diubah?
- [ ] Apakah gas limit pada `call` cukup?
- [ ] Apakah ada `selfdestruct`? — SWC-106

## F. Logic & State

- [ ] Apakah ada variabel state yang bisa diubah tak terduga?
- [ ] Apakah ada kondisi yang membuat fungsi tidak bisa dipanggil (DoS)?
- [ ] Apakah ada loop yang bisa macet (gas limit)?
- [ ] Apakah `block.timestamp`/`block.number` digunakan untuk keputusan penting? — SWC-116, SWC-114
- [ ] Apakah ada perbandingan exact dengan `block.timestamp` (harusnya `>=`/`<=`)?
- [ ] Apakah ada `require` yang bisa di-bypass?

## G. Front-running & MEV

- [ ] Apakah ada transaksi yang bisa di-sandwich (DEX swap)?
- [ ] Apakah ada order dependency (hasil tergantung urutan transaksi)?
- [ ] Apakah ada fungsi yang mengungkap informasi sebelum eksekusi (commit-reveal dibutuhkan)?

## H. Gas & Optimasi (bukan keamanan, tapi penting)

- [ ] Apakah ada loop yang boros gas?
- [ ] Apakah ada penyimpanan state yang tidak perlu?

## I. Standar & Kompatibilitas

- [ ] Apakah ERC-20/721/1155 diimplementasikan dengan benar (lihat `06-openzeppelin-standards.md`)?
- [ ] Apakah event dipancarkan dengan benar?
- [ ] Apakah ada fungsi yang menyimpang dari standar?

## J. Proxy & Upgradeability

- [ ] Apakah storage layout konsisten antara implementasi dan proxy?
- [ ] Apakah ada fungsi yang bisa merusak storage slot?
- [ ] Apakah `initialize` dilindungi dari front-running?

## Cara Menggunakan Checklist

1. Baca setiap fungsi dan centang item yang relevan.
2. Untuk setiap item yang bermasalah, catat: **lokasi (file:baris)**, **deskripsi**, **dampak**, **tingkat keparahan**.
3. Untuk temuan yang berpotensi dieksploitasi, tulis PoC di Foundry (lihat `05-foundry-testing.md`).
4. Petakan ke SWC (lihat `07-top20-bugs-swc.md`).
