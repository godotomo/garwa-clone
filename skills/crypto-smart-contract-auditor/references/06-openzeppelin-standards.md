# 06 — Standar OpenZeppelin & Pola Keamanan

Panduan pengecekan kepatuhan kontrak terhadap standar token dan pola keamanan OpenZeppelin.

## Standar Token

### ERC-20 (Fungible Token)
Implementasi aman: `@openzeppelin/contracts/token/ERC20/ERC20.sol`

Fungsi wajib:
- `totalSupply()`, `balanceOf(address)`, `transfer(address,uint)`, `allowance(address,address)`, `approve(address,uint)`, `transferFrom(address,address,uint)`

Event wajib:
- `Transfer(from, to, value)`, `Approval(owner, spender, value)`

**Poin audit ERC-20:**
- `transfer`/`transferFrom` harus mengembalikan `bool` dan memancarkan `Transfer`.
- `approve` punya race condition — gunakan `increaseAllowance`/`decreaseAllowance` untuk spender yang tidak dipercaya.
- `_beforeTokenTransfer`/`_afterTokenTransfer` hooks untuk logika tambahan.
- Jangan override `transfer` dengan logika aneh (mis. menahan token).

### ERC-721 (Non-Fungible Token / NFT)
Implementasi aman: `@openzeppelin/contracts/token/ERC721/ERC721.sol`

Fungsi wajib: `balanceOf`, `ownerOf`, `safeTransferFrom`, `transferFrom`, `approve`, `setApprovalForAll`, `getApproved`, `isApprovedForAll`.

**Poin audit ERC-721:**
- Gunakan `safeTransferFrom` (bukan `transferFrom`) untuk mencegah token terkunci di kontrak yang tidak bisa menerima NFT.
- `_mint` vs `_safeMint` — `_safeMint` memanggil `onERC721Received` untuk mencegah token terkunci.
- Cek `_beforeTokenTransfer` untuk pausable/access control.
- Metadata URI bisa diubah? (jika `setTokenURI` publik tanpa kontrol = masalah).

### ERC-1155 (Multi-Token)
Implementasi aman: `@openzeppelin/contracts/token/ERC1155/ERC1155.sol`

Fungsi wajib: `balanceOf`, `balanceOfBatch`, `setApprovalForAll`, `isApprovedForAll`, `safeTransferFrom`, `safeBatchTransferFrom`.

**Poin audit ERC-1155:**
- `safeTransferFrom`/`safeBatchTransferFrom` harus memanggil `onERC1155Received`/`onERC1155BatchReceived`.
- Cek `_beforeTokenTransfer` untuk pausable/access control.

## Pola Keamanan OpenZeppelin

### ReentrancyGuard
```solidity
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
contract MyContract is ReentrancyGuard {
    function withdraw() external nonReentrant {
        // aman dari reentrancy
    }
}
```
**Gunakan** pada fungsi yang menangani dana atau pemanggilan eksternal.

### Ownable / Ownable2Step
```solidity
import "@openzeppelin/contracts/access/Ownable.sol";
contract MyContract is Ownable {
    function setFee(uint f) external onlyOwner { ... }
}
```
**Ownable2Step** lebih aman (owner baru harus menerima) — gunakan untuk mencegah salah transfer ownership.

### AccessControl (RBAC)
```solidity
import "@openzeppelin/contracts/access/AccessControl.sol";
contract MyContract is AccessControl {
    bytes32 public constant MINTER_ROLE = keccak256("MINTER_ROLE");
    function mint(...) external onlyRole(MINTER_ROLE) { ... }
}
```
**Gunakan** untuk sistem multi-role yang kompleks.

### SafeERC20
```solidity
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
using SafeERC20 for IERC20;
IERC20(token).safeTransfer(to, amount); // cek return value otomatis
```
**Gunakan** untuk semua interaksi ERC-20 — menangani token yang tidak mengembalikan `bool` (USDT) dan memastikan return dicek.

### Pausable
```solidity
import "@openzeppelin/contracts/security/Pausable.sol";
contract MyContract is Pausable {
    function withdraw() external whenNotPaused { ... }
}
```
**Gunakan** untuk emergency pause pada fungsi yang menangani dana.

### Initializable (Proxy Pattern)
```solidity
import "@openzeppelin/contracts/proxy/utils/Initializable.sol";
contract MyContract is Initializable {
    function initialize(address _owner) public initializer { ... }
}
```
**Poin audit:** `initialize` harus dilindungi `initializer` agar tidak bisa di-front-run. Gunakan `_disableInitializers()` di constructor implementasi.

## Checklist Kepatuhan Standar

- [ ] Kontrak mengimplementasikan standar token yang benar (ERC-20/721/1155)?
- [ ] Semua fungsi wajib dan event ada?
- [ ] `transfer`/`transferFrom` mengembalikan `bool` dan memancarkan event?
- [ ] Interaksi ERC-20 menggunakan `SafeERC20`?
- [ ] Fungsi penanganan dana menggunakan `ReentrancyGuard`?
- [ ] Access control menggunakan `Ownable`/`AccessControl` yang benar?
- [ ] Ada `Pausable` untuk emergency?
- [ ] Proxy pattern menggunakan `Initializable` dengan benar?
- [ ] Tidak ada override yang menyimpang dari standar?
- [ ] Tidak ada fungsi yang bisa mengubah metadata/URI tanpa kontrol?

## Jebakan Umum

1. **Implementasi manual ERC-20** sering salah (lupa event, return value, dsb) — sarankan pakai OpenZeppelin.
2. **`transfer` vs `safeTransfer`** — `transfer` tidak cek return, bisa gagal diam-diam.
3. **`_mint` vs `_safeMint`** — `_mint` bisa mengunci NFT di kontrak yang tidak bisa menerima.
4. **`approve` race condition** — gunakan `increaseAllowance`.
5. **Proxy tanpa `_disableInitializers`** — bisa di-front-run.
6. **Fee-on-transfer / rebasing token** — asumsi balance salah.
