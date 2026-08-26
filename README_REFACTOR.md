# Garwa - hasil refactor struktur folder

File asli (9 file, ~9.000 baris, terbesar `cli.py` 4.720 baris) sudah
dipecah jadi package `garwa/` dengan 51 file kecil per tanggung jawab.
Tidak ada logika yang ditulis ulang secara manual -- pemecahan dilakukan
secara MEKANIS lewat script berbasis AST (`ast.walk` + splice teks presisi
per-token) supaya:

- Setiap fungsi/class dipindah APA ADANYA (termasuk komentar & docstring
  asli, tidak pakai `ast.unparse` yang akan membuang komentar).
- Semua referensi ke variabel/konstanta module-level yang dipindah ke
  file `_state.py` / `_shared.py` diganti otomatis jadi `state.NAMA`
  secara presisi per-karakter (bukan cari-ganti teks bebas), supaya tidak
  menyentuh isi string literal atau komentar yang kebetulan menyebut nama
  yang sama.

## Struktur folder

```
garwa/
  __init__.py
  __main__.py            entry point: python -m garwa
  config.py               (tidak diubah, sudah kecil & fokus)
  db.py                    (tidak diubah)
  token_utils.py            (tidak diubah)
  context_manager.py         (tidak diubah)
  repo_map.py                 (tidak diubah)

  security/                  <- dipecah dari security.py
    __init__.py / _shared.py / findings.py / process_utils.py /
    dast.py / orchestrator.py
    scanners/                   <- dipecah lebih lanjut dari scanners.py
      __init__.py / common.py / semgrep.py / osv.py / pip_audit.py /
      dep_scan.py / gitleaks.py / trivy.py   (satu file per scanner)

  tool_runtime/                <- dipecah dari tool_runtime.py
    __init__.py / _shared.py / errors.py / copy_utils.py / hooks.py /
    registry.py / introspection.py / executor.py

  tools/                        <- dipecah dari tools.py
    __init__.py / _state.py / sandbox.py / datetime_utils.py /
    web_search.py / github.py / filesystem.py / webfetch.py /
    security_tool.py / bash_tool.py / repo_tools.py / session_tools.py

  cli/                           <- dipecah dari cli.py (file terbesar, ~4700 baris)
    __init__.py / _state.py / colors.py / text_utils.py / paste_input.py /
    file_drop.py / llm_errors.py / stream_parse.py / json_repair.py /
    mojibake.py / tool_exec.py / agent_loop.py / auto_mode.py / main.py

    markdown_render/                <- dipecah lebih lanjut dari markdown_render.py
      __init__.py / latex.py / inline.py / tables.py /
      reasoning_preview.py / terminal_renderer.py

    tool_schema/                    <- dipecah lebih lanjut dari tool_schema.py
      __init__.py / alt_syntax.py / schema_text.py / native_calls.py

    vision/                         <- dipecah lebih lanjut dari vision.py
      __init__.py / cache.py / image_encoding.py / attachment_tags.py / messages.py

    skills/                         <- dipecah lebih lanjut dari skills.py
      __init__.py / frontmatter.py / discovery.py / system_prompt.py

    overnight/                      <- dipecah lebih lanjut dari overnight.py
      __init__.py / tee_stdout.py / session_setup.py / task_runner.py / mode.py

    llm_client/                     <- dipecah lebih lanjut dari llm_client.py (871 baris)
      __init__.py / connection.py / openrouter_cache.py / debug_log.py /
      stream_call.py / nonstream_call.py / dispatch.py

garwa_cli.py                    convenience runner di root: `python garwa_cli.py`
requirements.txt
```

**Total 86 file .py**, dari 9 file asli. Yang masih >300 baris hanyalah
yang SECARA STRUKTURAL merupakan satu fungsi tunggal raksasa
(`cli/agent_loop.py` -- fungsi `run_agent_loop`, 552 baris; `cli/main.py`
-- fungsi `main`, 398 baris) atau file yang memang isinya utuh dari awal
dan tidak diminta diubah (`context_manager.py`, `repo_map.py`, `db.py`).
Lihat "Kalau mau dipecah lebih jauh lagi" di bawah.

### Re-export lewat `__init__.py` supaya tidak ada yang perlu diubah

Tujuh target (`markdown_render`, `tool_schema`, `vision`, `skills`,
`overnight`, `llm_client`, `security/scanners`) diubah dari file
tunggal (`markdown_render.py`) menjadi FOLDER bernama sama
(`markdown_render/`) berisi `__init__.py` yang me-re-export semua nama
publiknya. Python tidak membedakan `from .markdown_render import X`
mengambil dari modul tunggal atau dari package -- jadi file lain yang
sudah mengimpor dari sana (`agent_loop.py`, `main.py`, dll) TIDAK perlu
diubah sama sekali.

## Kalau mau dipecah lebih jauh lagi

`cli/agent_loop.py` (fungsi `run_agent_loop`, 552 baris) dan
`cli/main.py` (fungsi `main`, 398 baris) SECARA STRUKTURAL adalah SATU
fungsi Python tunggal masing-masing -- bukan kumpulan beberapa
fungsi/class top-level seperti file lain. Memecahnya lebih jauh tidak
bisa dilakukan secara mekanis (pindah blok kode apa adanya); harus
mengekstrak bagian dalam fungsi jadi fungsi-fungsi helper baru --
memutuskan parameter apa yang perlu dioper, variabel lokal apa yang
perlu dikembalikan, dst. Ini masuk kategori refactor logika, bukan lagi
reorganisasi file, dan risikonya lebih tinggi untuk mengubah perilaku
tanpa sengaja. Saya bisa lakukan ini juga kalau diminta, tapi butuh
pengujian lebih hati-hati (idealnya beberapa sesi chat nyata) dibanding
pemecahan mekanis yang sudah dilakukan sejauh ini.

## Kenapa ada `_state.py` / `_shared.py` di setiap package pecahan?

`tools.py` dan `cli.py` asli punya variabel module-level yang di-mutate
DARI LUAR file itu sendiri, misalnya di `cli.py`:

```python
tools_module.WORKDIR = args.workdir
tools_module.SANDBOX_ENABLED = not args.no_sandbox
tools_module.ALLOWED_EXTERNAL_PATHS = set()
```

Kalau variabel semacam ini "dikawinkan" begitu saja ke beberapa file
terpisah dengan `from .other_module import WORKDIR`, tiap file akan
punya SALINAN nilai sendiri-sendiri pada saat import, dan mutasi dari
`cli.py` setelahnya tidak akan pernah terlihat oleh file lain -- bug
yang sangat halus dan mudah lolos saat pemecahan file manual.

Solusinya: semua variabel begini dipindah ke satu file `_state.py`
(untuk `tools/`) atau `_state.py` (untuk `cli/`), dan SEMUA file lain
mengaksesnya lewat atribut modul (`state.WORKDIR`), bukan `from ... import`.
`cli.py` sekarang melakukan:

```python
tools_module.state.WORKDIR = args.workdir
```

sudah diverifikasi (lihat bagian "Yang sudah diverifikasi" di bawah)
bahwa mutasi ini benar-benar terlihat oleh semua submodule `tools/`.

Untuk `security.py` dan `tool_runtime.py`, tidak ditemukan pola mutasi
dari luar seperti ini, jadi konstanta bersama (`_shared.py`) cukup
diimpor biasa.

## Yang sudah diverifikasi

- **Sintaks**: `python -m compileall garwa` bersih di seluruh 86 file.
- **Import**: seluruh package (`garwa`, `garwa.cli`, `garwa.tools`,
  `garwa.tool_runtime`, `garwa.security`, `garwa.db`, `garwa.config`,
  `garwa.context_manager`, `garwa.repo_map`, `garwa.token_utils`)
  berhasil diimpor tanpa error, termasuk optional dependency yang tidak
  terinstall di sandbox ini (`tiktoken`, `tree-sitter-language-pack`) --
  fallback bawaan tetap aktif seperti aslinya.
- **Tidak ada referensi "yatim"**: script verifikasi otomatis mengecek
  bahwa TIDAK ADA satu pun referensi ke nama state/shared yang lolos
  tanpa di-rename jadi `state.NAMA`/`shared.NAMA` di seluruh 4 package
  besar (`tools`, `security`, `tool_runtime`, `cli`) -- 0 ditemukan.
- **`TOOLS` registry**: jumlah entri persis sama dengan file asli (20 tool).
- **State bersama benar-benar "hidup"**: uji end-to-end --
  `tools_module.state.WORKDIR` di-set dari luar package, lalu
  `tool_write_file()` (di `filesystem.py`) dan resolusi path di
  `_resolve()` (di `sandbox.py`, FILE BERBEDA) terbukti memakai nilai
  yang sama persis -- ini skenario yang paling rawan pecah kalau
  pemecahan file dilakukan sembarangan.
- **Fungsi murni** (`db.py`, `repo_map.py`, `json_repair.extract_tool_call`,
  `text_utils`, `markdown_render`) diuji manual dengan input contoh dan
  memberi output yang benar.

## Yang BELUM diverifikasi (keterbatasan sandbox ini)

- Tidak ada koneksi ke llama-server sungguhan, jadi `llm_client.py`
  (HTTP call ke model) belum diuji end-to-end dengan model asli.
- Tidak ada test suite otomatis di repo asli, jadi verifikasi di atas
  bersifat structural + smoke test manual, bukan regression test
  lengkap. Sangat disarankan menjalankan `garwa_cli.py` di lingkungan
  Anda sendiri (dengan llama-server aktif) untuk satu-dua sesi chat
  normal sebelum menghapus file `.py` lama.
- Beberapa file masih relatif besar (`llm_client.py` ~870 baris,
  `agent_loop.py` ~550 baris, `markdown_render.py` ~540 baris) --
  sudah jauh lebih kecil dari `cli.py` asli, tapi bisa dipecah lebih
  jauh lagi kalau Anda mau (mis. `llm_client.py` bisa dipisah jadi
  "openrouter cache handling" vs "core HTTP call").

## Cara pakai

```bash
pip install -r requirements.txt
python garwa_cli.py --help
# atau
python -m garwa --help
```

Environment variable yang dipakai (lihat `garwa/config.py`) sama persis
seperti sebelumnya: `GITHUB_TOKEN`, `GOOGLE_NEWS_HL/GL/CEID`,
`GITHUB_MAX_CONTENT`, `LLAMA_URL`, `LLAMA_API_KEY`.

## Folder `skills/`

Simpan skill Anda di `skills/<nama-skill>/SKILL.md` -- **sejajar (sibling)
dengan folder `garwa/` dan `garwa_cli.py`**, persis di root repo ini
(sudah disertakan satu contoh: `skills/contoh-skill/SKILL.md`). Ini
identik dengan lokasi default `cli.py` yang asli (dulu `DEFAULT_SKILLS_DIR`
dihitung relatif terhadap lokasi `cli.py` sendiri, yang ada di root repo).

```
repo-root/
  garwa/
  garwa_cli.py
  requirements.txt
  skills/                    <- taruh di sini
    nama-skill-anda/
      SKILL.md
      references/            (opsional)
      scripts/                (opsional)
      assets/                  (opsional)
```

Format `SKILL.md` minimal:

```markdown
---
name: nama-skill-anda
description: >
  Deskripsi singkat kapan skill ini relevan dipakai (ditampilkan
  ke system prompt sebagai ringkasan skill yang tersedia).
---

Instruksi lengkap skill di sini (baru dimuat penuh kalau dipakai).
```

Kalau Anda ingin lokasi lain, pakai flag `--skills-dir /path/lain` saat
menjalankan `python garwa_cli.py` -- tidak wajib pakai lokasi default.

**Catatan penting hasil refactor:** di `cli.py` ASLI, `DEFAULT_SKILLS_DIR`
dihitung dari `os.path.dirname(os.path.abspath(__file__))` (folder tempat
`cli.py` berada). Setelah dipecah, `cli.py` menjadi `garwa/cli/_state.py`,
jadi kalau dihitung apa adanya, hasilnya SALAH -- akan menunjuk ke
`garwa/cli/skills/` yang notabene folder *kode Python* subpackage skills
(`discovery.py`, dkk), bukan folder markdown skill Anda. Saya sudah
memperbaiki ini supaya `DEFAULT_SKILLS_DIR` tetap menunjuk ke
`<repo_root>/skills` seperti perilaku aslinya -- lihat komentar di
`garwa/cli/_state.py`.
