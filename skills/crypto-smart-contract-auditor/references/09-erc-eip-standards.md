# 09 — Standar ERC/EIP Terbaru untuk EVM (Riset 2026)

Daftar standar token & interface EVM yang paling relevan untuk audit, termasuk standar terbaru. Sumber: repo resmi `ethereum/EIPs` dan `ethereum/ercs` (ERCs dipisah dari EIPs sejak 2024), serta OpenZeppelin.

> **Catatan penting**: Sejak 2024, repo `ethereum/EIPs` dipisah menjadi dua — **EIPs** (core protocol, networking, interface) dan **ERCs** (application layer). Semua ERC baru dan update harus diarahkan ke `github.com/ethereum/ercs`. Saat mengaudit, pastikan mengecek status terbaru standar di `eips.ethereum.org`.

## Kategori Standar

| Kategori | Contoh | Fokus Audit |
|---|---|---|
| **Token Fungible** | ERC-20, ERC-777, ERC-4626 | Transfer, approval, vault |
| **Token Non-Fungible** | ERC-721, ERC-1155, ERC-4906, ERC-4907 | NFT, metadata, rental |
| **Token Semi-Fungible** | ERC-1155, ERC-3525, ERC-404 | Multi-token, SFT |
| **Interface & Utilitas** | ERC-165, ERC-1271, ERC-2612, ERC-2981, ERC-4337 | Introspection, signature, permit, royalty, AA |
| **DeFi & Vault** | ERC-4626, ERC-20, ERC-3156 | Vault, flash loan |
| **Metadata & Data** | ERC-721 metadata, ERC-1155 metadata, ERC-1046 | URI, on-chain data |

## Standar Token Utama

### ERC-20 — Fungible Token (Final)
Standar paling dasar untuk token fungible.
- Fungsi: `totalSupply`, `balanceOf`, `transfer`, `allowance`, `approve`, `transferFrom`.
- Event: `Transfer`, `Approval`.
- **Poin audit**: return value `bool`, race condition `approve`, fee-on-transfer, rebasing.

### ERC-721 — Non-Fungible Token (Final)
Standar NFT.
- Fungsi: `balanceOf`, `ownerOf`, `safeTransferFrom`, `transferFrom`, `approve`, `setApprovalForAll`, `getApproved`, `isApprovedForAll`.
- **Poin audit**: `_safeMint` vs `_mint`, metadata URI control, `onERC721Received`.

### ERC-1155 — Multi Token Standard (Final)
Standar multi-token (fungible + non-fungible dalam satu kontrak).
- Fungsi: `balanceOf`, `balanceOfBatch`, `setApprovalForAll`, `isApprovedForAll`, `safeTransferFrom`, `safeBatchTransferFrom`.
- **Poin audit**: `onERC1155Received`, `onERC1155BatchReceived`, batch transfer.

### ERC-777 — Token Standard (Final, tapi **deprecated/tidak disarankan**)
Standar token lama dengan hook `tokensReceived`/`tokensToSend`.
- **Poin audit**: **JANGAN gunakan** — punya masalah reentrancy via hook dan operator. OpenZeppelin sudah menghapus dukungan. Jika ditemukan, tandai sebagai risiko.

### ERC-4626 — Tokenized Vault Standard (Final, terbaru & penting)
Standar vault yield-bearing. Sangat umum di DeFi modern.
- Fungsi: `asset`, `totalAssets`, `convertToShares`, `convertToAssets`, `previewDeposit`, `previewMint`, `previewWithdraw`, `previewRedeem`, `maxDeposit`, `maxMint`, `maxWithdraw`, `maxRedeem`, `deposit`, `mint`, `withdraw`, `redeem`.
- Event: `Deposit`, `Withdraw`.
- **Poin audit**:
  - **Rounding direction**: `deposit`/`mint` harus round down untuk shares; `withdraw`/`redeem` harus round down untuk assets. Salah rounding = kehilangan dana.
  - **Inflation attack**: attacker deposit pertama dengan jumlah kecil untuk memanipulasi rasio share/asset (donation attack). Gunakan virtual offset atau minimum deposit.
  - `preview*` harus konsisten dengan `deposit`/`withdraw` aktual.
  - `totalAssets` harus akurat (termasuk yield yang belum direalisasi).
  - Reentrancy pada `deposit`/`withdraw`.

### ERC-3525 — Semi-Fungible Token (Final)
Standar SFT (Semi-Fungible Token) — token dengan value dan slot.
- **Poin audit**: transfer value antar slot, approval, event.

### ERC-404 — Mixed ERC-20/ERC-721 (Draft/eksperimental)
Standar hibrida yang menggabungkan ERC-20 dan ERC-721 (token yang bisa dipecah jadi NFT).
- **Poin audit**: **MASIH DRAFT & eksperimental** — banyak bug dikenal. Hati-hati dengan reentrancy, mint/burn implisit, dan manipulasi balance.

## Interface & Utilitas

### ERC-165 — Standard Interface Detection (Final)
Deteksi interface yang didukung kontrak.
- Fungsi: `supportsInterface(bytes4)`.
- **Poin audit**: pastikan `supportsInterface` mengembalikan `true` untuk interface yang benar, dan `false` untuk yang tidak didukung.

### ERC-1271 — Standard Signature Validation (Final)
Validasi signature untuk kontrak (smart contract wallet).
- Fungsi: `isValidSignature(bytes32, bytes)`.
- **Poin audit**: verifikasi signature EIP-712, replay protection, malleability.

### ERC-2612 — Permit Extension for ERC-20 (Final)
`permit` — approval tanpa gas (off-chain signature).
- Fungsi: `permit(owner, spender, value, deadline, v, r, s)`, `nonces`, `DOMAIN_SEPARATOR`.
- **Poin audit**: **replay protection** (nonce), **deadline check**, signature malleability, chain ID dalam `DOMAIN_SEPARATOR` (mencegah replay lintas chain).

### ERC-2981 — NFT Royalty Standard (Final)
Standar royalty untuk NFT.
- Fungsi: `royaltyInfo(uint256, uint256)`.
- **Poin audit**: pastikan royalty dibayar benar, tidak bisa dimanipulasi.

### ERC-4337 — Account Abstraction (Final)
Standar smart contract wallet / account abstraction.
- Komponen: `UserOperation`, `EntryPoint`, `Paymaster`, `Account`.
- **Poin audit**: verifikasi signature, nonce, replay protection, paymaster logic, gas.

### ERC-3156 — Flash Loans (Final)
Standar flash loan.
- Fungsi: `maxFlashLoan`, `flashFee`, `flashLoan`.
- **Poin audit**: fee calculation, callback reentrancy, repayment.

### ERC-4906 — Metadata Update (Final)
Event untuk update metadata NFT.
- Event: `MetadataUpdate`, `BatchMetadataUpdate`.
- **Poin audit**: pastikan event dipancarkan saat metadata berubah.

### ERC-4907 — Rentable NFTs (Final)
Standar NFT rental.
- Fungsi: `setUser`, `userOf`, `userExpires`.
- **Poin audit**: expiry check, transfer saat rental aktif.

### ERC-1046 — Token Metadata (Draft)
Standar metadata on-chain untuk token.
- **Poin audit**: validasi URI, off-chain vs on-chain.

### ERC-20 Permit / ERC-4494 — ERC-721 Permit (Draft)
Permit untuk NFT.
- **Poin audit**: sama seperti ERC-2612 tapi untuk NFT.

## Standar Baru / Sedang Berkembang (2024-2026)

| ERC | Nama | Status | Catatan |
|---|---|---|---|
| ERC-4626 | Tokenized Vault | Final | Sangat penting di DeFi |
| ERC-4337 | Account Abstraction | Final | Wallet pintar |
| ERC-3525 | Semi-Fungible Token | Final | SFT |
| ERC-404 | Mixed ERC-20/721 | Draft | Eksperimental, banyak bug |
| ERC-6909 | Minimal Multi-Token | Draft | Alternatif ERC-1155 yang lebih murah gas |
| ERC-6551 | Token Bound Accounts | Draft | NFT punya wallet sendiri |
| ERC-7579 | Modular Smart Accounts | Draft | Modul untuk AA |
| ERC-6900 | Modular Smart Contract Accounts | Draft | Modul AA |
| ERC-7528 | Token Bound Accounts (alternatif) | Draft | |
| ERC-1155C | ERC-1155 dengan compliance | Draft | |
| ERC-20C | ERC-20 dengan compliance | Draft | |
| ERC-7802 | Cross-chain token standard | Draft | Interoperabilitas lintas chain |

## Checklist Audit Standar ERC/EIP

- [ ] Kontrak mengimplementasikan standar yang benar dan **versi terbaru**?
- [ ] Semua fungsi wajib dan event ada sesuai standar?
- [ ] `supportsInterface` (ERC-165) benar?
- [ ] ERC-4626: rounding direction benar? Ada proteksi inflation attack?
- [ ] ERC-2612/4494: replay protection (nonce + chain ID + deadline) benar?
- [ ] ERC-1271: validasi signature benar?
- [ ] ERC-4337: verifikasi UserOperation benar?
- [ ] ERC-3156: flash loan fee & repayment benar?
- [ ] Tidak menggunakan standar deprecated (ERC-777)?
- [ ] Standar draft (ERC-404, ERC-6551) ditangani dengan hati-hati?

## Referensi Resmi

- Repo EIPs: `github.com/ethereum/EIPs`
- Repo ERCs: `github.com/ethereum/ercs`
- Status page: `eips.ethereum.org`
- OpenZeppelin: `github.com/OpenZeppelin/openzeppelin-contracts`
- Solady (implementasi gas-optimized): `github.com/Vectorized/solady`
