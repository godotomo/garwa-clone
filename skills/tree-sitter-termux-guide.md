# Panduan Tree-Sitter di Lingkungan Termux (Android)

> **Untuk model (LLM) yang bekerja di repo Garwa di Termux/Android.** Dokumen ini
> adalah acuan dari pengalaman nyata yang sudah diverifikasi — bukan teori.
> Baca ini SEBELUM mencoba menginstal, memuat, atau memperbaiki tree-sitter di
> Termux, supaya tidak membuang waktu pada jalan buntu yang sudah diketahui.

---

## 1. Ringkasan Eksekutif (TL;DR)

- **Python di Termux ini = 3.14.6.** Banyak wheel `.abi3.so` untuk tree-sitter
  **TIDAK bisa dimuat** di Python 3.14 Termux.
- **JANGAN andalkan `tree_sitter_language_pack` atau grammar individual pip**
  (`tree_sitter_python`, dll.) — keduanya gagal `dlopen` di sini.
- **SOLUSI YANG TERBUKTI BERHASIL:** pakai **grammar C native Termux** yang
  diinstall lewat `pkg install tree-sitter-<lang>`, dimuat via `ctypes` +
  `Language(ptr)` (int pointer). Sudah terintegrasi di `garwa/repo_map.py`.
- Test `test_parse_cache` & `test_repo_map_graph` kini **lulus** setelah solusi ini.

---

## 2. Lingkungan

| Item | Nilai |
|---|---|
| OS | Termux (Android, aarch64) |
| Python | 3.14.6 |
| tree-sitter core (pip) | 0.26.0 — **import OK, berfungsi** |
| tree_sitter_language_pack | 1.16.2 — **GAGAL dimuat** |
| tree_sitter_python (pip) | 0.25.0 — **GAGAL dimuat** |
| Rust toolchain | rustc 1.98.0 + cargo (tersedia) |
| PREFIX | `/data/data/com.termux/files/usr` |

---

## 3. Masalah yang Ditemukan (Akar Masalah)

### 3.1 `tree_sitter_language_pack` gagal dimuat
```python
from tree_sitter_language_pack import get_parser
# ImportError: dlopen failed: cannot locate symbol "PyExc_TypeError"
#   referenced by ".../tree_sitter_language_pack/_native.abi3.so"
```

### 3.2 Grammar individual pip gagal dimuat
```python
import tree_sitter_python
# ImportError: dlopen failed: cannot locate symbol
#   "tree_sitter_python_external_scanner_create"
#   referenced by ".../tree_sitter_python/_binding.abi3.so"
```

**Penyebab:** wheel `.abi3.so` (stable ABI) tidak kompatibel dengan CPython 3.14
di Termux/Android. Ini **pola yang sama** dengan masalah `pyexpat`/`libexpat`
yang tercatat di catatan `termux-pip-libexpat-fix` — masalah ABI `.so` di Termux.

**Kesimpulan:** jangan coba-coba menginstall ulang atau build wheel `.abi3.so`
untuk tree-sitter di Python 3.14 Termux. Itu jalan buntu.

---

## 4. Solusi yang Terbukti: Grammar C Native Termux

Termux menyediakan grammar tree-sitter sebagai **paket native C** yang di-build
khusus untuk platform ini (bukan `.abi3.so`).

### 4.1 Install grammar native
```bash
pkg install -y \
  tree-sitter-python tree-sitter-javascript tree-sitter-go tree-sitter-rust \
  tree-sitter-c tree-sitter-java tree-sitter-json tree-sitter-yaml \
  tree-sitter-html tree-sitter-css tree-sitter-bash
```
> Catatan: `tree-sitter-typescript` dan `tree-sitter-cpp` **tidak tersedia**
> sebagai paket terpisah di repo Termux. JavaScript mencakup TSX/TS sebagian.

### 4.2 Lokasi grammar native
Setelah install, grammar tersedia di:
```
$PREFIX/lib/libtree-sitter-<lang>.so
# contoh:
#   /data/data/com.termux/files/usr/lib/libtree-sitter-python.so
#   /data/data/com.termux/files/usr/lib/libtree-sitter-javascript.so
```

### 4.3 Memuat grammar via ctypes (pola yang benar)
```python
import ctypes
from tree_sitter import Language, Parser

lib = ctypes.CDLL("/data/data/com.termux/files/usr/lib/libtree-sitter-python.so")
fn = lib.tree_sitter_python          # nama fungsi C per bahasa
fn.restype = ctypes.c_void_p
ptr = fn()                           # const TSLanguage*
lang = Language(ptr)                 # int pointer (deprecated tapi stabil)
parser = Parser(lang)
tree = parser.parse(b"x = 1\ny = 2\n")
print(tree.root_node.type)           # -> module
```

**Poin penting:**
- `Language(ptr)` menerima **integer pointer** (`PyLong`). Ini deprecated tapi
  stabil dan aman untuk grammar static native. (Jangan pakai capsule manual —
  nama capsule harus `"tree_sitter.Language"` dan pendekatan ctypes capsule
  bisa segfault.)
- Nama fungsi C per bahasa = `tree_sitter_<lang>` (ctypes `getattr`).
- Grammar native yang tersedia & terverifikasi: **bash, c, css, go, html,
  java, javascript, json, python, rust, yaml** (11 bahasa).

### 4.4 Integrasi di repo Garwa
Sudah diimplementasikan sebagai **tier #3** di `garwa/repo_map.py`:
- Fungsi `_native_termux_parser(lang)` — memuat grammar native Termux via
  ctypes, cache per-thread (thread-local, aman untuk sub-agent paralel).
- Dipanggil di `_get_parser(lang)` setelah language-pack & grammar individual
  gagal, sebelum fallback `tree_sitter_languages`.

Urutan prioritas loader di `_get_parser`:
1. `tree_sitter_language_pack` (primary — tapi gagal di Termux 3.14)
2. grammar individual pip (`tree_sitter_<lang>`)
3. **grammar C native Termux** (`pkg install tree-sitter-<lang>`) ← solusi ini
4. `tree_sitter_languages` (fallback lama)

---

## 5. API tree-sitter 0.26 (yang relevan)

- `Language(ptr)` — class; menerima int pointer (deprecated) atau capsule.
- `Parser(lang)` atau `Parser().language = lang` (API baru; `set_language()`
  lama sudah HAPUS sejak 0.25).
- Node: `type`, `parent`, `start_point/end_point/start_byte/end_byte`,
  `child_by_field_name`, `named_children`, `is_error`, `is_missing`,
  `has_error`.
- Snippet konteks: `descendant_for_point_range((r1,c1),(r2,c2))` → node
  terkecil yang meliputi rentang; `named_descendant_for_point_range(...)` hanya
  node bernama.
- Incremental parse: `tree.edit(...)` (6 argumen byte+point) →
  `parser.parse(new_src, old_tree)` → `tree.changed_ranges(new_tree)`.
- `Query(Language, source)` — class (bukan `Language.query()`).

---

## 6. Verifikasi / Test

Setelah solusi diterapkan, test berikut **lulus** (sebelumnya gagal):
```
tests/test_repo_map_graph.py   # 9 passed
tests/test_parse_cache.py      # 10 passed
tests/test_robustness_fixes.py # lulus
tests/test_oklch.py            # 12 passed (skill frontend-design)
```

Cara cek cepat apakah loader bekerja:
```python
import sys; sys.path.insert(0, ".")
from garwa import repo_map as rm
p = rm._get_parser("python")
print(p is not None)   # True
print(p.parse(b"x=1\n").root_node.type)  # module
```

---

## 7. Do & Don't (Ringkasan Praktis)

**DO:**
- Pakai grammar C native Termux (`pkg install tree-sitter-<lang>`) + ctypes +
  `Language(ptr)`.
- Gunakan `_native_termux_parser()` yang sudah ada di `garwa/repo_map.py`.
- Set `fn.restype = ctypes.c_void_p` sebelum memanggil fungsi grammar.
- Simpan parser per-thread (thread-local) — objek Parser tree-sitter **tidak
  thread-safe** untuk parse bersamaan (sub-agent paralel).

**DON'T:**
- Jangan andalkan `tree_sitter_language_pack` di Termux Python 3.14 (gagal
  `dlopen`).
- Jangan andalkan `tree_sitter_python` pip (gagal `dlopen`).
- Jangan build ulang wheel `.abi3.so` — jalan buntu di 3.14 Termux.
- Jangan buat capsule manual via ctypes untuk `Language` — bisa **segfault**
  (exit code -11). Pakai int pointer `Language(ptr)`.
- Jangan coba `tree-sitter-typescript`/`tree-sitter-cpp` via `pkg` — tidak ada.

---

## 8. Referensi Terkait

- Catatan proyek: `termux-treesitter-abi3-fix` (solusi ini, terverifikasi).
- Catatan proyek: `termux-pip-libexpat-fix` (pola masalah ABI `.so` serupa).
- Catatan proyek: `garwa-treesitter-runtime-research` (riset API py-tree-sitter).
- Kode: `garwa/repo_map.py` → `_native_termux_parser()` & `_get_parser()`.
