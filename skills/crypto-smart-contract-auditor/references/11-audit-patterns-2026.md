# Pola Audit Terbaru (2026) — ERC-4337 Smart Accounts, Uniswap v4 Hooks, Dimensional Analysis

> Sumber: riset Trail of Bits 2026 (blog.trailofbits.com). Topik-topik ini adalah area kerentanan
> terbaru yang sering muncul di audit smart contract modern. Gunakan sebagai checklist tambahan
> di luar referensi 04 (manual review) dan 09 (standar ERC/EIP).

---

## 1. ERC-4337 Smart Account — 6 Kesalahan Umum

Account abstraction (ERC-4337) mengubah model "private key bisa melakukan apa saja" menjadi sistem
yang dapat diprogram (batching, recovery, spending limit, gas fleksibel). Namun programmability ini
memperkenalkan risiko: satu bug bisa sama fatalnya dengan bocornya private key.

**Alur ERC-4337 singkat:**
1. User membangun & menandatangani `UserOperation` off-chain (berisi `callData`, `nonce`, parameter gas, `paymaster`, signature).
2. Bundler mensimulasikan lokal, lalu batch & submit ke `EntryPoint.handleOps`.
3. `EntryPoint` memanggil `validateUserOp` pada smart account (verifikasi signature + gas coverage). Jika ada paymaster, EntryPoint juga memvalidasi paymaster.
4. Setelah validasi lolos, `EntryPoint` memanggil balik ke account untuk mengeksekusi operasi.

### Kesalahan 1 — Access Control yang Salah
Jika siapa pun bisa memanggil fungsi `execute` (atau apa pun yang memindahkan dana) secara langsung,
mereka bisa menguras wallet. Hanya `EntryPoint` (atau modul executor yang diverifikasi, mis. ERC-7579)
yang boleh memicu jalur privileged.

```solidity
// RENTAN: siapa pun bisa memanggil
function execute(address target, uint256 value, bytes calldata data) external {
    (bool ok,) = target.call{value: value}(data);
    require(ok, "exec failed");
}

// AMAN: hanya EntryPoint
address public immutable entryPoint;
function execute(address target, uint256 value, bytes calldata data) external {
    require(msg.sender == entryPoint, "not entryPoint");
    (bool ok,) = target.call{value: value}(data);
    require(ok, "exec failed");
}
```

Periksa **setiap** fungsi external/public: selain akses EntryPoint, beberapa fungsi perlu dibatasi
hanya ke account itu sendiri (mis. untuk admin task seperti install/uninstall module, ubah validator, upgrade).

### Kesalahan 2 — Validasi Signature Tidak Lengkap (terutama field gas)
Kesalahan serius: account hanya memverifikasi aksi yang dimaksud (mis. `callData`) tetapi **menghilangkan
field gas**: `preVerificationGas`, `verificationGasLimit`, `callGasLimit`, `maxFeePerGas`, `maxPriorityFeePerGas`.

Semua nilai ini bagian dari payload dan harus ditandatangani & dicek oleh validator. Karena EntryPoint
menghitung & menyelesaikan fee memakai parameter ini, field yang tidak terikat kriptografis ke signature
dan tidak di-sanity-check bisa diubah bundler/frontrunner. Dengan menggelembungkan `preVerificationGas`
(bagian yang mengkompensasi bundler untuk calldata/overhead), attacker bisa membuat account membayar
lebih dan menguras ETH.

```solidity
// RENTAN: hanya mengecek callData
function validateUserOp(UserOperation calldata op, bytes32, uint256) external returns (uint256) {
    require(_isApprovedCall(op.callData, op.signature), "bad sig");
    return 0;
}

// AMAN: tanda tangani seluruh userOpHash
function validateUserOp(UserOperation calldata op, bytes32 userOpHash, uint256) external returns (uint256) {
    require(_isApprovedCall(userOpHash, op.signature), "bad sig");
    return 0;
}
```

**Praktik baik:** gunakan `userOpHash` dari EntryPoint (sudah termasuk field gas by spec). Jika harus
fleksibel, terapkan cap ketat & reasonability check pada tiap field gas.

### Kesalahan 3 — Modifikasi State Saat Validasi
Menulis state di `validateUserOp` lalu menggunakannya saat eksekusi berbahaya, karena EntryPoint
memvalidasi **semua** op dalam satu bundle **sebelum** mengeksekusi salah satunya. Jika Anda meng-cache
signer yang di-recover ke storage saat validasi lalu memakainya di `execute`, validasi op lain bisa
menimpanya sebelum op Anda berjalan.

```solidity
// RENTAN: menyimpan signer ke storage saat validasi
function validateUserOp(UserOperation calldata op, bytes32 userOpHash, uint256) external returns (uint256) {
    address signer = recover(userOpHash, op.signature);
    require(signer == owner1 || signer == owner2, "unauthorized");
    pendingSigner = signer; // DANGEROUS: bisa di-clobber validasi lain
    return 0;
}
```

**Praktik baik:**
- Jangan modifikasi state account saat fase validasi.
- Ingat semantik batch: semua validasi jalan sebelum eksekusi; "approval" yang ditulis saat validasi bisa ditimpa validasi op berikutnya.
- Gunakan mapping keyed by `userOpHash` untuk data sementara, dan hapus deterministik setelah dipakai — tapi lebih baik jangan persist apa pun.

### Kesalahan 4 — Serangan Replay Signature ERC-1271
ERC-1271 adalah standar kontrak memvalidasi signature. Jebakan umum: memverifikasi bahwa owner
menandatangani hash **tanpa mengikat** signature ke smart account spesifik dan chain. Jika owner yang
sama mengontrol banyak smart account, atau akun yang sama ada di banyak chain, signature untuk akun A
bisa di-replay ke akun B atau chain lain.

```solidity
// RENTAN: recover atas raw hash, tidak terikat ke kontrak/chainId
function isValidSignature(bytes32 hash, bytes calldata sig) external view returns (bytes4) {
    return ECDSA.recover(hash, sig) == owner ? MAGIC : 0xffffffff;
}

// AMAN: EIP-712 domain-separated (verifyingContract + chainId)
function isValidSignature(bytes32 hash, bytes calldata sig) external view returns (bytes4) {
    bytes32 structHash = keccak256(abi.encode(TYPEHASH, hash));
    bytes32 digest = _hashTypedDataV4(structHash);
    return ECDSA.recover(digest, sig) == owner ? MAGIC : 0xffffffff;
}
```

**Praktik baik:**
- Selalu verifikasi EIP-712 typed data agar domain mengikat signature ke chainId + alamat smart account.
- Enforce return magic value ERC-1271 yang tepat (`0x1626ba7e`) saat sukses; selain itu gagal.
- Uji kasus negatif eksplisit: signature sama di akun berbeda, di chain berbeda, dan setelah nonce/owner berubah.

### Kesalahan 5 — "Revert Tidak Menyelamatkan Anda" di ERC-4337
Setelah `validateUserOp` sukses, bundler **tetap dibayar** walau eksekusi nanti revert (sama seperti
transaksi Ethereum normal: miner tetap dapat fee walau tx gagal). Suksesnya `validateUserOp` mengikat
Anda untuk membayar gas. Jika validasi terlalu permisif dan menerima op yang pasti gagal saat eksekusi,
bundler jahat bisa submit berulang kali dan mengumpulkan gas dari account tanpa ada yang berguna terjadi.

Masalah terkait: paymaster yang membayar EntryPoint dari pool bersama saat `validateUserOp`, lalu mencoba
menagih user di `postOp`. `postOp` bisa revert (state buruk, arithmetic error, external call berisiko),
dan revert di `postOp` **tidak membatalkan** pembayaran yang sudah terjadi saat validasi. Attacker bisa
berulang kali lolos validasi sambil memaksa `postOp` gagal (mis. menarik ETH dari pool saat eksekusi userOp) → menguras pool.

**Praktik baik:**
- Jangan andalkan `postOp` untuk invariant inti. Debit fee dari escrow/deposit per-user saat validasi, sehingga uang aman sebelum eksekusi.
- Perlakukan `postOp` sebagai bookkeeping best-effort: minimal, bounded, dan dirancang tidak pernah revert.
- Uji path sukses DAN revert. Ingat: begitu `validateUserOp` sukses, account membayar gas.

### Kesalahan 6 — Akun ERC-4337 Lama vs ERC-7702
ERC-7702 memungkinkan EOA bertindak sementara sebagai smart account dengan mengaktifkan kode untuk
durasi satu transaksi (menjalankan implementasi wallet di konteks EOA). Ini membuka **initialization race**:
jika logic mengharapkan panggilan `initialize(owner)`, attacker yang melihat delegasi 7702 bisa front-run
dengan transaksi inisialisasi sendiri dan menetapkan dirinya sebagai owner.

```solidity
// AMAN: hanya bisa diinisialisasi ketika account mengeksekusi sebagai dirinya sendiri (mis. di bawah 7702)
function initialize(address newOwner) external {
    require(msg.sender == address(this), "init: only self");
    require(owner == address(0), "already inited");
    owner = newOwner;
}
```

Ini bekerja karena selama transaksi 7702, panggilan yang dieksekusi oleh EOA-as-contract memiliki
`msg.sender == address(this)`, sementara transaksi eksternal acak tidak bisa memenuhi kondisi itu.

**Praktik baik:**
- Wajibkan `msg.sender == address(this)` dan `owner == address(0)` di `initialize`; single-use dan mustahil dipanggil eksternal.
- Buat smart account terpisah untuk EOA yang di-enable ERC-7702 vs akun non-7702 untuk mengisolasi alur inisialisasi & manajemen.

### Checklist Pra-merge Smart Account (ERC-4337)
- Gunakan `userOpHash` EntryPoint untuk validasi.
- Batasi `execute`/fungsi privileged ke EntryPoint (dan self jika perlu).
- Jaga `validateUserOp` stateless: jangan tulis ke storage.
- Paksa EIP-712 untuk ERC-1271 dan pesan bertanda tangan lain.
- Buat `postOp` minimal, bounded, dan non-reverting.
- Untuk ERC-7702, izinkan init hanya saat `msg.sender == address(this)`, sekali saja.
- Tambahkan banyak end-to-end test pada path sukses dan revert.

---

## 2. Uniswap v4 Hooks — 7 Pola Kegagalan

Uniswap v4 memindahkan beberapa tanggung jawab keamanan ke kode aplikasi & hook. Insiden Cork (~$12M,
Mei 2025) dan Bunni (~$8.4M, September 2025) muncul dari logika authorization & accounting khusus-aplikasi
yang dibangun di sekitar hook — bukan dari cacat inti protokol v4 / PoolManager.

**Yang dijamin PoolManager:** mekanika protokol v4 (aturan inisialisasi pool, matematika swap & likuiditas,
sekuensing callback hook, settlement akhir sesi). `unlock()` memicu callback, lalu memeriksa tidak ada
currency delta yang belum diselesaikan (`CurrencyNotSettled`).

**Tanggung jawab hook developer:** siapa yang bisa memanggil path privileged, pool mana yang legitimate,
bagaimana balance & delta kustom dihitung, dan apakah integrasi eksternal bisa gagal/reenter dengan aman.

### Pola 1 — "Siapa pun bisa memanggil hook Anda"
Hook callback adalah fungsi external. Tanpa cek caller, attacker bisa memanggil callback langsung dengan
parameter jahat. Path `unlockCallback` yang longgar juga bisa menjangkau aksi internal yang seharusnya
tidak bisa dipanggil.

**Fix:** gunakan `BaseHook` untuk hook entrypoint dan `SafeCallback` untuk `unlockCallback`. Tambahkan
cek caller setara pada path yang tidak tercakup. Contoh Cork: data dari path tidak tepercaya mencapai
logic hook yang memengaruhi redemption → akses-control gap + pricing issue → drain dana.

```solidity
modifier onlyPoolManager() {
    if (msg.sender != address(poolManager)) revert NotPoolManager();
    _;
}
```

### Pola 2 — Memperlakukan pool mana pun sebagai legitimate
Pembuatan pool lewat PoolManager permissionless secara default. Kecuali hook membatasi inisialisasi di
`beforeInitialize`, siapa pun bisa membuat pool dengan alamat hook Anda. Jika hook mempercayai `PoolKey`
yang disuplai user tanpa validasi, attacker bisa mengarahkan logic Anda lewat pool jahat (currency & parameter pilihan mereka).

Dua risiko langsung: (a) jika hook menyimpan data per-pool keyed by `PoolId`, pool baru mendapat slot
mapping sendiri yang bisa dipengaruhi attacker; (b) `currency0`/`currency1` dipilih attacker — jika
ERC-20, interaksi token bisa memicu perilaku jahat atau reenter fungsi hook lain di tengah alur.

**Fix:** ikat hook ke pool kanonik saat deploy/konfigurasi tepercaya, atau maintain allowlist ketat.
Re-check `PoolId` yang diturunkan pada setiap path yang dikontrol user.

```solidity
PoolId poolId = key.toId();
if (!allowedPools[poolId]) revert InvalidPool();
```

### Pola 3 — Custom accounting bocorkan nilai
Delta adalah perubahan saldo currency bertanda yang terutang ke/dari PoolManager. Begitu hook menyentuh
delta, tanda salah, rounding error, atau mencampur bucket balance bisa diam-diam bocorkan nilai. Bug ini
subtle karena settlement hanya memeriksa delta currency sesi terselesaikan; **tidak memvalidasi accounting
internal hook**. Accounting hook bisa salah walau settlement sukses.

- **Return-delta hooks** bisa bergerak melampaui bookkeeping fee. Jika `BeforeSwapDelta` mengonsumsi
  seluruh amount yang ditentukan user, PoolManager tidak punya sisa untuk concentrated-liquidity swap;
  hook yang menyuplai trade disebut **NoOp swap**. Perlakukan sebagai AMM kustom: uji konservasi, price
  bounds, rounding, dan returned delta terhadap balance riil.
- **Dynamic fees** price-sensitive: pool dynamic-fee bisa menerima fee override per-swap dari `beforeSwap`,
  dan hook bisa update LP fee tersimpan. Batasi setiap fee, batasi kecepatan perubahan privileged, jangan
  turunkan langsung dari input yang bisa dimanipulasi murah oleh attacker.
- **Token non-standar:** fee-on-transfer (amount diterima < amount dikirim), rebasing (balance berubah
  tanpa transfer), callback-enabled (reenter), pausable/blacklistable (blokir settlement). Nyatakan
  perilaku mana yang didukung dan uji accounting terhadap perubahan balance yang diamati.

**Tiga invariant accounting yang wajib diuji untuk hook yang memindahkan nilai:**
1. Tidak ada user yang menerima output yang tidak ditagih oleh accounting.
2. Round-trip dalam satu transaksi tidak bisa menciptakan nilai hanya dari accounting.
3. Accounting internal cocok dengan balance aset aktual.

**Fix:** pisahkan dana LP, fee, dan insentif di bucket terpisah. Label setiap balance & delta (siapa
pemiliknya, siapa yang bisa memindahkannya). Contoh Bunni: bug rounding di accounting idle-balance
BunniHook — attacker mendorong price tick pool dengan flash loan, lalu membuat 44 withdrawal kecil yang
masing-masing menyusutkan active balance tak proporsional terhadap shares yang dibakar → profit.

### Pola 4 — Logic benar, hook salah
`beforeSwap` dieksekusi dengan state pre-swap; `afterSwap` melihat state post-swap. Kode yang benar di
satu hook bisa tidak aman di hook lain. Masalah timing sama berlaku untuk callback likuiditas. Sering
ditemukan: developer menaruh logic yang butuh hasil swap final di `beforeSwap` (bekerja pada data basi).

**Fix:** verifikasi logic Anda ada di hook yang tepat untuk state yang dibutuhkan.

### Pola 5 — Address bits adalah bagian dari API
Di v4, alamat hook sendiri meng-encode hook function mana yang akan dipanggil PoolManager (via
`hasPermission` membaca bit dari alamat). Desain ini membuat alamat yang di-deploy jadi bagian dari API
hook. Tiga mismatch permission yang bermasalah:
- **Callback bit set + callback hilang** → transaksi revert.
- **Callback diimplementasi + bit callback hilang** → PoolManager tidak memanggilnya.
- **Return-delta bit hilang** → PoolManager mungkin memanggil callback tapi memperlakukan delta yang
  dikembalikan sebagai nol (mis. hook mencatat fee padahal PoolManager mengabaikan delta).

Jika alamat hook menunjuk ke proxy, bit permission tetap tapi upgrade bisa mengubah kode yang dijangkau
alamat itu — review admin upgrade, delay, storage layout, dan implementation check sebagai bagian dari
security boundary. Prefer deployment immutable & versioned.

**Fix:** inherit `BaseHook` dan jaga `getHookPermissions()` sinkron dengan callback & return delta yang
dipakai. `BaseHook` memvalidasi bit alamat yang di-deploy cocok dengan permission yang dideklarasikan.

### Pola 6 — Kegagalan hook bisa memblokir aksi pool
Hook callback dieksekusi dalam transaksi yang sama dengan aksi pool. Jika reward distribution, dust
cleanup, atau kode non-esensial revert di dalam callback `afterRemoveLiquidity`, user tidak bisa keluar
dari posisi. Sama untuk swap saat kode non-esensial revert di `afterSwap`. PoolManager menjaga eksekusi
atomik dengan me-revert aksi induk.

External read yang wajib bisa menyebabkan DoS: jika price feed menolak data basi, lending protocol pause,
atau dependensi lain revert, callback bisa me-revert swap/withdrawal user. Untuk tiap dependensi, putuskan
path mana yang harus fail-closed dan mana yang bisa degrade tanpa memblokir exit aman. **Jangan pernah
diam-diam memakai data harga basi.**

**Fix:** jauhkan kode non-esensial dari alur user utama. Bungkus external call opsional dalam `try/catch`,
atau pindahkan logic opsional ke fungsi terpisah yang bisa dipanggil user setelah exit. Untuk dependensi
kritis-keamanan, validasi freshness & bounds, berikan fallback exit-safe eksplisit bila desain mengizinkan.

### Pola 7 — State bisa berubah selama sekuens callback
Saat di-enable, `beforeSwap` dan `afterSwap` berjalan dalam swap yang sama, tapi nilai yang di-cache di
antaranya tidak otomatis aman. Hook bisa memanggil kontrak eksternal, dan satu kontrak hook bisa melayani
banyak pool. Aksi nested bisa mengubah shared hook storage, pool state, balance, atau data oracle sebelum
sekuens callback luar selesai.

**Fix:** hindari shared scratch state. Jika data harus menyeberang callback, key dengan `PoolId` + caller,
tolak operasi yang overlap selama state itu live, dan bersihkan setelah dipakai. Terapkan
checks-effects-interactions sebelum external call, dan uji nested swap & perubahan likuiditas di banyak
pool yang berbagi hook.

### Checklist Membangun Hook v4 yang Aman (8 item)
1. Gate setiap callback & unlock path: `BaseHook` untuk hook entrypoint, `SafeCallback` untuk `unlockCallback`.
2. Allowlist pool, bukan cuma token: ikat ke `PoolKey` spesifik atau maintain allowlist ketat.
3. Label setiap balance & delta: siapa pemilik, siapa yang bisa memindahkan, perilaku token apa yang didukung.
4. Pisahkan dana LP, fee, dan insentif — jangan campur bucket balance.
5. Jauhkan kode non-esensial dari alur user utama (reward/oracle/cleanup jangan blokir exit aman).
6. Verifikasi address permission: inherit `BaseHook`, pastikan bit alamat cocok dengan permission. Jika upgradeable, review proxy & kontrol upgrade terpisah.
7. Fuzz nested callbacks, fee extremes, pool jahat, dan token jahat/non-standar (Echidna & Medusa untuk skenario adversarial, bukan cuma happy path).
8. Isolasi callback state: key data sementara dengan PoolId + caller, tolak operasi overlap, bersihkan setelah dipakai.

### Checklist Audit Hook v4 (7 pertanyaan)
1. Bisakah attacker memanggil callback langsung? Cek setiap fungsi external untuk access control.
2. Bisakah attacker mengarahkan logic lewat pool jahat? Telusuri bagaimana `PoolKey` divalidasi.
3. Siapa pemilik setiap balance & delta, dan bisakah return delta / dynamic fee bocorkan nilai? Uji konservasi, price bounds, fee limits.
4. Apa yang terjadi jika reward/cleanup/oracle revert selama `removeLiquidity`? Uji failure path & dependency outage.
5. Apakah permission bits, fungsi yang diimplementasi, nilai yang dikembalikan, dan path upgrade proxy semuanya cocok? Verifikasi address flags & upgrade controls.
6. Apa yang rusak jika hook, token, atau input fee jahat? Asumsikan counterparty adversarial.
7. Bisakah state berubah antar callback? Uji aksi nested di banyak pool yang berbagi hook.

---

## 3. Dimensional Analysis untuk DeFi — Menangkap Bug Aritmetika

Dimensional analysis memungkinkan Anda menyingkirkan seluruh kategori bug logika & aritmetika yang
menghantui formula DeFi — tanpa perubahan kode, cukup penalaran lebih baik.

**Aturan emas:** kedua sisi persamaan harus memiliki dimensi yang sama, dan Anda tidak bisa menambah/
mengurangi kuantitas dengan dimensi berbeda.

### Konsep dimensi DeFi
- Physics: length, mass, time, dll. DeFi punya "dimensi" sendiri: token, price, liquidity.
- Contoh salah: `K = x + y` di AMM (x = jumlah token A, y = jumlah token B). Menambahkan keduanya sama
  tidak bermaknanya seperti menambah jarak dan waktu. (Kecuali **stable pool** di mana token dirancang
  near-equal value → diperlakukan sebagai dimensi yang sama.)
- **Liquidity** di Uniswap v3: `Liquidity = sqrt(x·y)`. Dimensinya `sqrt([A]·[B])`. `x·y` mendefinisikan
  hubungan konservasi yang mengatur swap; k dan liquidity adalah dimensi turunan.

### Contoh formula price yang salah
**Contoh 1:** `Price = (jumlah token A) / liquidity`
- Price yang benar: `Price B in terms of A = [A]/[B]`.
- Dimensi ruas kanan: `[A]/sqrt([A]·[B]) = sqrt([A]/[B])` → itu **akar kuadrat dari price**, bukan price.
- Formula salah — dimensi kiri ≠ kanan.

**Contoh 2:** Mana yang salah?
- `K = (A)² · Price(B in A)` → `[A]² · [A]/[B] = [A]³/[B]` → TIDAK valid (K = [A]·[B]).
- `K = (A)² / Price(B in A)` → `[A]² / ([A]/[B]) = [A]·[B]` → VALID.

**Contoh 3 (vulnerability nyata, audit CAP Labs TOB-CAP-17):**
```solidity
uint256 pricePerFullShare = IERC4626(_asset).convertToAssets(capTokenDecimals);
latestAnswer = latestAnswer * pricePerFullShare / capTokenDecimals;
```
`convertToAssets` ERC-4626 mengharapkan **jumlah aset** sebagai satu-satunya input, tapi implementasi CAP
mengirim **decimals**! Itu persis jenis issue yang bisa ditangkap dimensional analysis cepat tanpa tahu
isi codebase.

### Praktik terbaik
- **Jadikan dimensi eksplisit & konsisten:** putuskan representasi (mis. `tok`, `UoA`, `shares`) dan
  terapkan seragam di seluruh codebase.
- **Selalu dokumentasikan scale bersama dimensi:** di DeFi, decimals mismatch sering sama berbahayanya
  dengan dimensi mismatch. Sertakan fixed-point precision (mis. `D18`, `D27`) di samping anotasi dimensi.
- **Anotasi input, output, dan state variable:** dimensi safety rusak jika hanya storage yang didokumentasikan.
- **Prefer clarity atas brevity:** nama variabel/komentar sedikit lebih panjang jauh lebih murah daripada bug aritmetika subtle.
- **Dokumentasikan konversi eksplisit:** saat nilai berubah dimensi/scale (shares→assets, token→unit of account), tambahkan komentar singkat menjelaskan transformasi.

Contoh anotasi gaya Reserve Protocol (komentar dimensi + scale):
```solidity
/// @param weights D27{tok/BU} Basket weight ranges for the basket unit definition; cannot be empty [0, 1e54]
/// @param prices  D27{UoA/tok} Prices for each token in terms of the unit of account; cannot be empty (0, 1e45]
/// @param limits  D18{BU/share} Target number of baskets should have at end of rebalance (0, 1e27]
/// @param ttl     {s} The amount of time the rebalance is valid
function startRebalance(...)
```

**Catatan:** Solidity tidak punya sistem units-of-measure (tidak seperti F# `float<m/s>`), jadi developer
harus meniru lewat komentar & konvensi penamaan. Tooling masa depan (Slither-based linting/static analysis)
bisa meng-infer, propagate, dan cek "units"/"dimensions" lintas codebase, menandai mismatch seperti
Solidity memperingatkan tipe yang tidak kompatibel.

---

## Ringkasan: Topik Audit yang Harus Dicek (2026)

| Area | Poin fokus utama |
|---|---|
| ERC-4337 smart accounts | Access control `execute`, validasi penuh field gas, stateless `validateUserOp`, replay ERC-1271 (EIP-712), jangan andalkan postOp/revert, init race ERC-7702 |
| Uniswap v4 hooks | Cek caller callback, allowlist pool, accounting delta/rounding, hook yang tepat (before vs after), address permission bits, jangan blokir exit, isolasi state antar callback |
| Dimensional analysis | Homogenitas formula, decimals vs dimensi, anotasi unit/scale konsisten, cek konversi shares↔assets |
