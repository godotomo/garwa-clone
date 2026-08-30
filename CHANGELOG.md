# Changelog

Semua perubahan penting pada proyek ini akan dicatat di file ini.

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id/1.1.0/),
dan versi mengikuti [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-08-30

### Added
- **Total token per giliran di ringkasan**: ringkasan akhir giliran kini menampilkan baris `token` berisi total token yang dihabiskan pada giliran tersebut saja (input + output), dihitung dari selisih akumulasi `TOKEN_USAGE_TOTAL` antara awal dan akhir `run_agent_loop`. Nilai global tetap terakumulasi normal (tidak di-reset) sehingga konsisten dengan status bar, dan aman ketika backend tidak mengirim field `usage` (tampil `0`).
- **Parameter context-window & summarization dapat dikonfigurasi**: key `context_window`, `reserve_for_response`, `summarize_threshold_ratio`, dan `keep_tail_messages` diekspos di config, dengan guard nilai invalid yang jatuh ke default (tidak crash saat import).
- **Slash-command baru** untuk mengatur konteks secara runtime yang persist lintas sesi via `save_user_config`:
  - `/ctx` — atur ukuran context-window
  - `/reserve` — atur token cadangan untuk respons
  - `/summarize-threshold` — atur rasio ambang summarization
  - `/keep-tail` — atur jumlah pesan akhir yang dipertahankan
- **Penyimpanan & penyuntikan instruksi aktif pada summarization**: `SUMMARIZE_SYSTEM` kini menghasilkan output JSON murni `{narasi, instruksi_aktif}`; `maybe_summarize` menggabungkan instruksi lama + baru (dengan deduplikasi), dan `build_context_messages` menyuntikkan blok `<instruksi_aktif>` setiap giliran agar konteks tidak hilang. DB mendapat kolom `summaries.active_instructions` (JSON) dengan migrasi idempoten.
- **Persistensi konfigurasi lintas sesi**: `model`, `url`, `api_key` (serta `github_token`, `github_max`, `news_lang`, `firecrawl_token`) kini disimpan di `~/.config/garwa/config`; prioritas env > config > default. Default `--url/--api-key/--model` diambil dari config.

### Changed
- **Optimasi besar system prompt**: daftar tool diubah dari `- nama: deskripsi` (1.083 token) menjadi hanya `- nama` (95 token). Deskripsi + skema argumen tetap dikirim setiap request via field `tools` ala OpenAI (`build_openai_tools_payload`), sehingga tidak menghilangkan informasi untuk model. **Dampak terukur** (tiktoken cl100k): system prompt 3.161 → 2.174 token (**hemat 987 token/giliran, 31.2%**); proyeksi 10 giliran = 9.870, 50 = 49.350, 100 = 98.700, 200 = 197.400 token.
- **`context_manager` menerima parameter baru** (`reserve_for_response`, `summarize_threshold_ratio`, `keep_tail_messages`) alih-alih membaca konstanta module-level, dengan wiring ke `agent_loop.py` dan `main.py`.
- **Pembuatan tabel Markdown lebih aman**: `ncols` dihitung dengan aman saat rows kosong (menghindari `TypeError: 'int' not iterable`), dan header, separator, serta rows di-pad ke `ncols` agar tidak memicu `IndexError`.

### Fixed
- **Installer kini menambahkan `PREFIX` ke PATH secara persisten**: `install.sh` sebelumnya hanya menampilkan hint manual sehingga `garwa` tidak ditemukan setelah restart terminal di macOS. Kini `ensure_prefix_in_path()` mengekspor `PREFIX` ke PATH sesi aktif, mendeteksi shell profile (`.zshrc`, `.bash_profile`/`.bashrc`, fallback `.profile`), menambahkan baris export bila belum ada, idempoten, dan fallback aman saat file profile tidak dapat ditulis.
- **`/api-key` tanpa argumen kini benar-benar menghapus key**: sesuai help *"kosongkan untuk menghapus"*, perintah tanpa argumen menghapus key dari config dan me-reset nilai aktif; pesan "tersimpan" hanya muncul saat ada perubahan.

### Removed
- **3 test SSE repro lama yang tidak lagi relevan** dihapus: `test_sse_long_repro.py`, `test_sse_long_repro_extra.py`, `test_sse_stress_extreme.py` (total 44 test; suite 405 → 361, waktu 93.59s → 18.36s).
- **File tes manual di root** dihapus dan dipindah ke `tests/`: `_test_5page_agentloop.py`, `_test_5page_latex.py`, `_test_summarize_manual.py`.

### Internal
- Sinkronisasi `__version__` ke `0.2.0` dan bump versi di `README.md` (dasar menuju rilis `0.3.0`).

### Tests
- Suite total: **362 passed** (setelah penambahan test baru pasca-penghapusan test SSE repro).
- Test baru mencakup: total token per giliran (`test_token_total_reflects_turn_usage`), mutasi & persistensi parameter konfigurasi baru, roundtrip/merge/parse narasi kosong/injeksi blok instruksi aktif, dan penghapusan api-key (ada & kosong).

---

## [0.2.0] - (sebelumnya)

*Riwayat versi 0.2.0 dan sebelumnya belum dicatat di file ini.*
