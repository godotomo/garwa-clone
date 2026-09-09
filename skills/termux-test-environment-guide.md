# Panduan Menjalankan Test & Lingkungan di Termux (Android)

> **Untuk model (LLM) yang bekerja di repo Garwa di Termux/Android.** Dokumen ini
> adalah acuan dari pengalaman nyata yang sudah diverifikasi — bukan teori.
> Baca ini SEBELUM menjalankan test, menginstal pustaka, atau menulis ke path
> di Termux, supaya tidak membuang waktu pada jebakan lingkungan yang sudah
> diketahui. Ini **bukan skill** — hanya catatan lingkungan, maka diletakkan
> langsung di folder `skills/` tanpa subfolder.

---

## 1. Ringkasan Eksekutif (TL;DR)

- **Python di Termux ini = 3.14.6.** Python **sistem** (`/data/data/.../usr/bin/python`)
  TIDAK punya pustaka runtime (requests, tiktoken, dll). Selalu pakai **venv**.
- **Cara menjalankan test yang benar:** `.venv/bin/python -m pytest ...`
  (bukan `python -m pytest` yang memakai Python sistem tanpa deps).
- **`/tmp` TIDAK bisa ditulis** di Termux (`Permission denied`). Jangan pernah
  redirect output test ke `/tmp/...` — tulis ke working dir (root repo).
- **`${PIPESTATUS[0]}` TIDAK didukung** oleh shell Termux (`sh` = dash) →
  `Bad substitution`. Jangan pakai pola itu di skrip bash.
- **Ringkasan pytest DISEMBUNYIKAN** oleh `output_compressor` Garwa (tool bash
  membungkus output). Jangan andalkan teks `N passed`. Gunakan **exit code**
  (`echo $?`) sebagai indikator lulus/gagal.
- **`mcp`/`cryptography` GAGAL dimuat** di Python 3.14 Termux (ABI `.so`).
  Ini OPSIONAL — Garwa punya fallback otomatis (`garwa/mcp/client.py`) yang
  membuat CLI tetap jalan & konfigurasi `/mcp-*` berfungsi. TAPI fallback itu
  **TIDAK** memberikan koneksi MCP nyata (batasan lengkap + solusi ada di
  bagian 3.5). Solusi yang TERBUKTI berhasil untuk koneksi MCP nyata: salin
  `cryptography` dari paket sistem Termux ke venv (bukan Python 3.11, bukan
  rebuild — keduanya tidak perlu/gagal).

---

## 2. Lingkungan

| Item | Nilai |
|---|---|
| OS | Termux (Android, aarch64) |
| Python sistem | 3.14.6 (`/data/data/com.termux/files/usr/bin/python`) |
| Python venv | `.venv/bin/python` = 3.14.6, punya requests/tiktoken/tree_sitter/httpx/bs4/prompt_toolkit |
| Python venv-test | `.venv-test/bin/python` = 3.14.6, punya requests/tiktoken/tree_sitter/httpx/bs4/prompt_toolkit/pytest (setelah `pip install -r requirements.txt`); `mcp` tetap gagal import (ABI) |
| Shell | `sh` = dash (`/data/data/com.termux/files/usr/bin/sh`) — tanpa `${PIPESTATUS[@]}` |
| PREFIX | `/data/data/com.termux/files/usr` |
| Pustaka sistem | via `pkg install` (bukan `apt`/`pip` untuk paket C native) |

---

## 3. Jebakan Lingkungan yang Sudah Diverifikasi

### 3.1 Python sistem tidak punya deps runtime
```bash
python -c "import requests, tiktoken, tree_sitter"
# ModuleNotFoundError: No module named 'tiktoken'
```
**Solusi:** selalu pakai venv:
```bash
.venv/bin/python -c "import requests, tiktoken, tree_sitter, httpx, bs4, prompt_toolkit"
# runtime deps OK
```

### 3.2 `/tmp` tidak bisa ditulis
```bash
echo x > /tmp/testout.txt
# sh: 1: cannot create /tmp/testout.txt: Permission denied
```
**Solusi:** tulis file sementara ke **working dir** (root repo), mis. `testout.log`,
lalu hapus setelah selesai. Jangan pernah bergantung pada `/tmp`.

### 3.3 `${PIPESTATUS[0]}` tidak didukung (shell dash)
```bash
.venv/bin/python -m pytest -q | grep passed
echo "${PIPESTATUS[0]}"   # <-- GAGAL
# sh: 1: Bad substitution
```
**Solusi:** jangan pakai `PIPESTATUS`. Redirect ke file dulu lalu baca exit code:
```bash
.venv/bin/python -m pytest -q > testout.log 2>&1
echo "EXIT=$?"   # 0 = semua lulus
```

### 3.4 Ringkasan pytest disembunyikan oleh output_compressor Garwa
Ketika test dijalankan lewat tool bash Garwa, output progress bar diringkas
menjadi `[pytest progress output suppressed]` atau hanya baris titik — ringkasan
`N passed / N failed` TIDAK terlihat.
**Solusi:** gunakan **exit code** (`echo $?`) sebagai kebenaran. Exit 0 = semua
lulus. Untuk jumlah test, pakai `--co` (collect-only) lalu jumlahkan:
```bash
.venv/bin/python -m pytest --co -q 2>&1 | grep -oE ": [0-9]+$" | awk -F': ' '{s+=$2} END {print "TOTAL:", s}'
```

### 3.5 `mcp` / `cryptography` ABI gagal di Python 3.14
```python
import mcp
# ImportError: dlopen failed: cannot locate symbol "PyModule_Type"
#   referenced by ".../cryptography/hazmat/bindings/_rust.abi3.so"
```
**Penyebab:** wheel `.abi3.so` tidak kompatibel dengan CPython 3.14 Termux
(pola sama dengan tree-sitter & libexpat). `mcp` bersifat **opsional** — Garwa
punya fallback otomatis (`garwa/mcp/client.py`), jadi CLI tetap jalan.

**PENTING — batasan fallback `garwa/mcp/client.py`:**
Fallback `client.py` HANYA memastikan CLI tidak crash + operasi konfigurasi
(`/mcp-server add/remove`, `/mcp-enable off`) tetap jalan. Ia **BUKAN pengganti
SDK MCP** — semua fungsionalitas inti (`ClientSession`, `stdio_client`,
`streamable_http_client`) di-import langsung dari paket `mcp`. Ketika
`import mcp` gagal, `mcp_available()` = `False` dan `connect_all()` langsung
`return` tanpa melakukan apa pun. Artinya **koneksi MCP nyata + pemanggilan tool
TIDAK bisa dilakukan** dengan fallback ini. Fallback hanya safety net agar CLI
tidak crash, BUKAN kemampuan MCP client penuh.

**Solusi TERBUKTI BERHASIL (2026): salin `cryptography` dari paket sistem Termux.**

Akar masalah: wheel `cryptography` dari pip (di-build oleh Rust 1.98) menghasilkan
`_rust.abi3.so` yang TIDAK bisa di-load oleh CPython 3.14 Termux. Tapi paket
sistem Termux `python-cryptography` (via `pkg install python-cryptography`,
sudah terinstall di `/data/data/.../usr/lib/python3.14/site-packages`) di-build
dengan toolchain yang benar dan **berfungsi penuh** (`_rust` OK).

Solusi: salin folder `cryptography` yang berfungsi dari site-packages sistem ke
venv (menimpa yang rusak dari pip):
```bash
SRC="/data/data/com.termux/files/usr/lib/python3.14/site-packages/cryptography"
DST=".venv-test/lib/python3.14/site-packages/cryptography"
rm -rf "$DST" && cp -r "$SRC" "$DST"

# Verifikasi
.venv-test/bin/python -c "import cryptography; from cryptography.hazmat.bindings import _rust; print('_rust OK')"
.venv-test/bin/python -c "import mcp; print('mcp OK')"
.venv-test/bin/python -c "from garwa.mcp import client; print('mcp_available:', client.mcp_available())"
```

> **HASIL VERIFIKASI NYATA (2026):** Setelah salin, `import mcp` BERHASIL dan
> `garwa.mcp.client.mcp_available()` = `True`, `mcp_import_error()` = `None`.
> Koneksi MCP nyata kini berfungsi penuh di `.venv-test` (Python 3.14.6).

**Opsi yang TIDAK perlu / GAGAL (jangan ulangi):**
- **Python 3.11** — TIDAK perlu; terjebak di versi python berbeda dari yang
  sedang dipakai (3.14.6). Hindari kecuali ada alasan kuat.
- **Rebuild `cryptography` dari source** (`pip install --no-binary cryptography
  --force-reinstall`) — GAGAL. `cryptography` v50 selalu menghasilkan
  `_rust.abi3.so` (stable ABI3) bahkan dari source, dan hasil build Rust 1.98
  tetap tidak bisa di-link ke CPython 3.14 Termux. Simbol `PyModule_Type` ada di
  `libpython3.14.so`, tapi link ABI3 tetap gagal.

### 3.6 `.venv` vs `.venv-test` — deps berbeda
- `.venv` (produksi): punya requests, tiktoken, tree_sitter, httpx, bs4,
  prompt_toolkit. `mcp` import GAGAL (ABI cryptography di Py 3.14).
- `.venv-test` (test): awalnya punya mcp/fastapi tapi **TIDAK punya requests**,
  dan **TIDAK punya pip** (harus di-bootstrap dulu via `ensurepip`).
  Setelah `pip install -r requirements.txt`, `.venv-test` sekarang punya
  requests/tiktoken/tree_sitter/httpx/bs4/prompt_toolkit/pytest — lengkap untuk
  suite penuh. `mcp` tetap gagal import (ABI), `fastapi` TIDAK terinstall
  (tidak wajib — hanya string template deliverable jobbot, bukan import runtime).
**Solusi:** untuk menjalankan seluruh suite test, pakai **`.venv/bin/python`**
atau **`.venv-test/bin/python`** (keduanya sekarang punya requests). Kalau butuh
koneksi MCP nyata, lihat Opsi A/B di bagian 3.5.

**Catatan bootstrap pip di venv tanpa pip:**
```bash
.venv-test/bin/python -m ensurepip --upgrade   # pasang pip
.venv-test/bin/pip install -r requirements.txt # pasang semua deps sekaligus
```

### 3.7 `grep` dengan backslash ganda → warning `stray \`
```bash
grep -oE '\"[a-z]+\"' file   # <-- GAGAL / warning: stray \ before "
```
**Solusi:** pakai **single quote** untuk pola yang mengandung backslash, atau
hindari escape ganda. Contoh benar:
```bash
grep -oE '"[a-z0-9-]+"' file
```

---

## 4. Cara Menjalankan Test yang Benar

```bash
cd /data/data/com.termux/files/home/garwa-coder-v2

# 1) Seluruh suite (pakai venv!) — andalkan EXIT code, bukan ringkasan teks
.venv/bin/python -m pytest -p no:cacheprovider -q > /dev/null 2>&1
echo "PYTEST_EXIT_CODE=$?"   # 0 = semua lulus

# 2) Satu file test
.venv/bin/python -m pytest tests/test_hermes_features.py -v 2>&1 | tail -30

# 3) Hitung total test yang dikumpulkan
.venv/bin/python -m pytest --co -q 2>&1 | grep -oE ": [0-9]+$" | awk -F': ' '{s+=$2} END {print "TOTAL:", s}'
```

> Catatan: `pytest.ini` memuat `addopts = -q`, jadi output sudah ringkas.
> `-p no:cacheprovider` menghindari cache `.pytest_cache`.

**Status suite terakhir (2026-09-09):** **683 passed, 1 skipped, 0 regresi**
(exit code 0). Test baru `tests/test_hermes_features.py` (17 test) untuk fitur
Hermes: `/undo`, `/retry`, `/search`, `/personality`, `/usage`.

---

## 5. Pustaka Sistem yang Dibutuhkan (via `pkg install`)

Pustaka **C native** di Termux TIDAK diinstall lewat pip — pakai `pkg install`:

```bash
# Tree-sitter grammar native (untuk repo_map / poor-man's LSP) — WAJIB kalau
# mau outline AST. Tanpa ini fallback ke regex (kurang akurat).
pkg install -y \
  tree-sitter-python tree-sitter-javascript tree-sitter-go tree-sitter-rust \
  tree-sitter-c tree-sitter-java tree-sitter-json tree-sitter-yaml \
  tree-sitter-html tree-sitter-css tree-sitter-bash

# libexpat — WAJIB supaya pyexpat/pip bekerja (tanpa ini pip install gagal:
# "cannot locate symbol PyExc_TypeError" / pyexpat error)
pkg install -y libexpat

# Toolchain untuk build dari source (kalau wheel tidak tersedia)
pkg install -y binutils rust
```

---

## 6. Do & Don't (Ringkasan Praktis)

**DO:**
- Selalu pakai `.venv/bin/python` untuk menjalankan test & import deps.
- Andalkan **exit code** (`echo $?`) untuk menentukan lulus/gagal test.
- Tulis file sementara ke **working dir**, bukan `/tmp`.
- Pakai `pkg install` untuk pustaka C native (tree-sitter, libexpat, dll).
- Pakai single quote untuk pola grep yang mengandung backslash.

**DON'T:**
- Jangan pakai `python -m pytest` (Python sistem tanpa deps) — pasti gagal import.
- Jangan redirect test ke `/tmp/...` — `Permission denied`.
- Jangan pakai `${PIPESTATUS[0]}` di bash Termux — `Bad substitution`.
- Jangan andalkan teks `N passed` dari output test — disembunyikan compressor.
- Jangan coba perbaiki `mcp`/`cryptography` ABI di Python 3.14 kecuali wajib.
- Jangan jalankan suite penuh dengan `.venv-test` — tidak punya requests.

---

## 7. Referensi Terkait

- Catatan proyek: `termux-treesitter-abi3-fix` (grammar native Termux + ctypes).
- Catatan proyek: `termux-pip-libexpat-fix` (libexpat untuk pip/pyexpat).
- File: `skills/tree-sitter-termux-guide.md` (cara memuat grammar native).
- File: `install.sh` (instalasi venv + launcher; lihat bagian Termux).
