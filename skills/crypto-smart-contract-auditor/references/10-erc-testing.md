# 10 — Pengujian Standar ERC/EIP (Foundry Test)

Panduan menulis test untuk memverifikasi kepatuhan kontrak terhadap standar ERC/EIP, termasuk standar terbaru. Gunakan bersama `09-erc-eip-standards.md`.

## Setup

```bash
forge init erc-test
cd erc-test
forge install OpenZeppelin/openzeppelin-contracts
forge install Vectorized/solady  # opsional, implementasi gas-optimized
```

## 1. Test ERC-20 (Fungible Token)

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test, console} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {MyToken} from "../src/MyToken.sol";

contract ERC20Test is Test {
    MyToken public token;
    address alice = address(0xA11CE);
    address bob = address(0xB0B);

    function setUp() public {
        token = new MyToken();
        token.mint(alice, 1000 ether);
    }

    function test_balanceOf() public view {
        assertEq(token.balanceOf(alice), 1000 ether);
    }

    function test_transfer() public {
        vm.prank(alice);
        bool ok = token.transfer(bob, 100 ether);
        assertTrue(ok);
        assertEq(token.balanceOf(alice), 900 ether);
        assertEq(token.balanceOf(bob), 100 ether);
    }

    function test_transfer_emitsEvent() public {
        vm.prank(alice);
        vm.expectEmit(true, true, true, true);
        emit IERC20.Transfer(alice, bob, 100 ether);
        token.transfer(bob, 100 ether);
    }

    function test_approve_raceCondition() public {
        // approve race condition: spender bisa menghabiskan allowance lama
        vm.prank(alice);
        token.approve(bob, 100 ether);
        vm.prank(bob);
        token.transferFrom(alice, bob, 100 ether);
        // sekarang allowance 0, tapi jika alice approve lagi 100, bob bisa pakai 200
        // rekomendasi: gunakan increaseAllowance/decreaseAllowance
    }

    function test_transfer_insufficientBalance_reverts() public {
        vm.prank(bob); // bob tidak punya token
        vm.expectRevert();
        token.transfer(alice, 1);
    }
}
```

## 2. Test ERC-721 (NFT)

```solidity
contract ERC721Test is Test {
    MyNFT public nft;
    address alice = address(0xA11CE);

    function setUp() public {
        nft = new MyNFT();
        nft.mint(alice, 1);
    }

    function test_ownerOf() public view {
        assertEq(nft.ownerOf(1), alice);
    }

    function test_safeTransferFrom_receiver() public {
        // kontrak yang tidak implement onERC721Received harus revert
        vm.prank(alice);
        vm.expectRevert();
        nft.safeTransferFrom(alice, address(this), 1); // Test contract tidak implement onERC721Received
    }

    function test_transferFrom_works() public {
        vm.prank(alice);
        nft.transferFrom(alice, bob, 1);
        assertEq(nft.ownerOf(1), bob);
    }
}
```

## 3. Test ERC-1155 (Multi-Token)

```solidity
contract ERC1155Test is Test {
    MyMulti public multi;

    function setUp() public {
        multi = new MyMulti();
        multi.mint(alice, 1, 100);
        multi.mint(alice, 2, 50);
    }

    function test_balanceOfBatch() public view {
        uint256[] memory ids = new uint256[](2);
        ids[0] = 1; ids[1] = 2;
        address[] memory owners = new address[](2);
        owners[0] = alice; owners[1] = alice;
        uint256[] memory balances = multi.balanceOfBatch(owners, ids);
        assertEq(balances[0], 100);
        assertEq(balances[1], 50);
    }

    function test_safeBatchTransferFrom() public {
        uint256[] memory ids = new uint256[](2);
        ids[0] = 1; ids[1] = 2;
        uint256[] memory amounts = new uint256[](2);
        amounts[0] = 10; amounts[1] = 5;
        vm.prank(alice);
        multi.safeBatchTransferFrom(alice, bob, ids, amounts, "");
        assertEq(multi.balanceOf(bob, 1), 10);
        assertEq(multi.balanceOf(bob, 2), 5);
    }
}
```

## 4. Test ERC-4626 (Tokenized Vault) — Standar Terbaru & Penting

```solidity
contract ERC4626Test is Test {
    MyVault public vault;
    IERC20 public asset;
    address alice = address(0xA11CE);

    function setUp() public {
        asset = new MyToken();
        vault = new MyVault(address(asset));
        asset.mint(alice, 1000 ether);
        vm.startPrank(alice);
        asset.approve(address(vault), type(uint256).max);
        vm.stopPrank();
    }

    function test_deposit_rounding() public {
        vm.prank(alice);
        uint256 shares = vault.deposit(100 ether, alice);
        // deposit harus round DOWN untuk shares (tidak memberi keuntungan ke depositor)
        assertLe(shares, vault.convertToShares(100 ether));
    }

    function test_withdraw_rounding() public {
        vm.prank(alice);
        vault.deposit(100 ether, alice);
        vm.prank(alice);
        uint256 assets = vault.withdraw(100 ether, alice, alice);
        // withdraw harus round DOWN untuk assets (tidak merugikan vault)
        assertLe(assets, 100 ether);
    }

    function test_preview_consistency() public {
        vm.prank(alice);
        uint256 shares = vault.previewDeposit(100 ether);
        vm.prank(alice);
        uint256 actual = vault.deposit(100 ether, alice);
        assertEq(shares, actual); // preview harus konsisten dengan aktual
    }

    function test_inflationAttack() public {
        // Donation attack: attacker deposit 1 wei lalu donate besar untuk manipulasi rasio
        vm.prank(alice);
        vault.deposit(1, alice); // deposit minimal
        // donate langsung ke vault
        asset.transfer(address(vault), 1000 ether);
        // sekarang rasio share/asset terdistorsi
        // korban berikutnya dapat share sangat sedikit
        // proteksi: virtual offset, minimum deposit, atau rounding yang benar
    }

    function test_totalAssets() public view {
        assertEq(vault.totalAssets(), asset.balanceOf(address(vault)));
    }
}
```

## 5. Test ERC-2612 (Permit / EIP-712)

```solidity
contract ERC2612Test is Test {
    MyToken public token;
    uint256 aliceKey = 0xA11CE;
    address alice = vm.addr(aliceKey);
    address bob = address(0xB0B);

    function setUp() public {
        token = new MyToken();
        token.mint(alice, 1000 ether);
    }

    function test_permit() public {
        uint256 deadline = block.timestamp + 1 days;
        // build EIP-712 digest
        bytes32 digest = keccak256(abi.encodePacked(
            "\x19\x01",
            token.DOMAIN_SEPARATOR(),
            keccak256(abi.encode(
                keccak256("Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)"),
                alice, bob, 100 ether, token.nonces(alice), deadline
            ))
        ));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(aliceKey, digest);
        token.permit(alice, bob, 100 ether, deadline, v, r, s);
        assertEq(token.allowance(alice, bob), 100 ether);
    }

    function test_permit_replayProtection() public {
        uint256 deadline = block.timestamp + 1 days;
        bytes32 digest = keccak256(abi.encodePacked(
            "\x19\x01",
            token.DOMAIN_SEPARATOR(),
            keccak256(abi.encode(
                keccak256("Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)"),
                alice, bob, 100 ether, token.nonces(alice), deadline
            ))
        ));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(aliceKey, digest);
        token.permit(alice, bob, 100 ether, deadline, v, r, s);
        // replay harus revert karena nonce sudah bertambah
        vm.expectRevert();
        token.permit(alice, bob, 100 ether, deadline, v, r, s);
    }

    function test_permit_expiredDeadline_reverts() public {
        uint256 deadline = block.timestamp - 1; // sudah lewat
        bytes32 digest = keccak256(abi.encodePacked(
            "\x19\x01",
            token.DOMAIN_SEPARATOR(),
            keccak256(abi.encode(
                keccak256("Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)"),
                alice, bob, 100 ether, token.nonces(alice), deadline
            ))
        ));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(aliceKey, digest);
        vm.expectRevert();
        token.permit(alice, bob, 100 ether, deadline, v, r, s);
    }
}
```

## 6. Test ERC-165 (Interface Detection)

```solidity
contract ERC165Test is Test {
    function test_supportsInterface() public {
        MyNFT nft = new MyNFT();
        // ERC-165
        assertTrue(nft.supportsInterface(0x01ffc9a7));
        // ERC-721
        assertTrue(nft.supportsInterface(0x80ac58cd));
        // ERC-721 Metadata
        assertTrue(nft.supportsInterface(0x5b5e139f));
        // ERC-2981 Royalty
        assertTrue(nft.supportsInterface(0x2a55205a));
        // Interface tidak dikenal harus false
        assertFalse(nft.supportsInterface(0xffffffff));
    }
}
```

## 7. Test ERC-1271 (Signature Validation untuk Kontrak)

```solidity
contract ERC1271Test is Test {
    function test_isValidSignature() public {
        SmartWallet wallet = new SmartWallet();
        bytes32 hash = keccak256("hello");
        bytes memory sig = abi.encodePacked(wallet.owner()); // signature sederhana
        bytes4 result = wallet.isValidSignature(hash, sig);
        assertEq(result, 0x1626ba7e); // MAGICVALUE
    }
}
```

## 8. Test ERC-2981 (NFT Royalty)

```solidity
contract ERC2981Test is Test {
    function test_royaltyInfo() public {
        MyNFT nft = new MyNFT();
        nft.setDefaultRoyalty(alice, 500); // 5%
        (address receiver, uint256 amount) = nft.royaltyInfo(1, 1000);
        assertEq(receiver, alice);
        assertEq(amount, 50); // 5% dari 1000
    }
}
```

## 9. Test ERC-4337 (Account Abstraction) — Ringkas

```solidity
contract ERC4337Test is Test {
    function test_userOp_validation() public {
        // Verifikasi UserOperation: signature, nonce, paymaster
        // Ini kompleks; fokus pada:
        // - signature valid
        // - nonce tidak di-replay
        // - paymaster membayar gas dengan benar
        // - EntryPoint tidak bisa di-front-run
    }
}
```

## 10. Test ERC-3156 (Flash Loan)

```solidity
contract ERC3156Test is Test {
    function test_flashLoan() public {
        MyFlashLender lender = new MyFlashLender();
        // borrower harus membayar kembali + fee dalam callback
        // pastikan fee dihitung benar dan repayment diverifikasi
    }
}
```

## Cheatsheet: Interface ID (ERC-165)

| Standar | Interface ID |
|---|---|
| ERC-165 | `0x01ffc9a7` |
| ERC-721 | `0x80ac58cd` |
| ERC-721 Metadata | `0x5b5e139f` |
| ERC-721 Enumerable | `0x780e9d63` |
| ERC-1155 | `0xd9b67a26` |
| ERC-1155 Metadata URI | `0x0e89341c` |
| ERC-2981 Royalty | `0x2a55205a` |
| ERC-1271 | `0x1626ba7e` |
| ERC-4626 | `0xce96cb77` (deposit/mint), `0xba087652` (withdraw/redeem) |

## Praktik Terbaik

1. **Test setiap standar yang diklaim kontrak** — jika kontrak bilang ERC-4626, test semua fungsi wajib.
2. **Test rounding direction** untuk ERC-4626 (sangat penting).
3. **Test replay protection** untuk ERC-2612/4494 (nonce, deadline, chain ID).
4. **Test interface detection** (ERC-165) untuk memastikan integrasi benar.
5. **Test edge case**: zero address, zero amount, max uint, expired deadline.
6. **Gunakan OpenZeppelin/Solady sebagai referensi** implementasi yang benar.
7. Untuk standar **draft** (ERC-404, ERC-6551), tandai risiko dan test dengan hati-hati.
