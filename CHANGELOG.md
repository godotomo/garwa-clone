# Changelog

Semua perubahan penting pada proyek ini akan dicatat di file ini.

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id/1.1.0/),
dan versi mengikuti [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.1] - 2026-09-09

Fitur-fitur baru diambil dari Hermes Agent (nousresearch/hermes-agent) untuk
memperkuat Garwa sebagai agentic runtime yang ringan, robust, dan berjalan
di Termux. Semua fitur tetap memakai dependensi yang sudah ada (SQLite stdlib,
config) — tidak ada dependensi baru.

### Added
- **`/undo`** — batalkan giliran terakhir: hapus pesan user + semua balasan
  model/tool dari DB. Berguna saat hasil giliran tidak sesuai.
- **`/retry`** — ulangi giliran terakhir: kirim ulang pesan user terakhir ke
  model (balasan lama dihapus, pesan user dipertahankan). Aksi `"retry"`
  diproses di loop interaktif `main.py`.
- **`/search <query>`** — cross-session memory search memakai SQLite **FTS5**:
  cari pesan user/assistant lintas semua sesi di workdir yang sama, dengan
  fallback ke `LIKE` bila query tidak valid untuk FTS. Menampilkan 15 hasil
  teratas (session_id + snippet).
- **`/personality <deskripsi>`** — set persona lintas sesi (disimpan di
  config user). Kosongkan untuk menghapus. Persona disuntikkan sebagai blok
  `PERSONA:` di awal system prompt pada sesi berikutnya.
- **`/usage`** — agregasi pemakaian token lintas sesi dari kolom `meta`
  messages (total token, tool calls, error, per hari, per tool).

### Internal
- `db.py`: helper baru `delete_messages_after`, `get_last_turn_span`,
  `search_messages` (FTS5), `aggregate_token_usage`.
- `config.py`: kunci `personality` ditambahkan ke `_USER_CONFIG_KEYS` dan
  `save_user_config`.
- `system_prompt.py`: penyuntikan persona dari config ke system prompt.

### Tests
- Test baru `tests/test_hermes_features.py` (17 test): DB helpers, slash
  command `/undo` `/retry` `/search` `/personality` `/usage`, dan injeksi
  persona ke system prompt.
- Suite total: **683 passed, 1 skipped** (0 regresi).

---

## [0.5.0] - 2026-09-06

Rilis ini menyimpan seluruh pekerjaan perbaikan arsitektur yang disepakati (6 poin) plus fitur sub-agent in-process.

### Added
- **Sub-agent in-process (`spawn_agent`)**: tool baru untuk menjalankan sub-agent di sub-session terpisah (`sub_<hex>`) dengan context window sendiri dan role prompt sendiri. Role bawaan: `general` (default) dan `explore` (penjelajah kode yang hanya meneliti tanpa mengubah file). Diimplementasikan in-process (bukan service-based) karena modular monolith sudah cukup & lebih ringan untuk agent lokal satu mesin.
- **Kolom `meta` (JSON) di tabel `messages`** untuk data training: `tool_name`, `args`, `is_error`, `token_estimate` disimpan setiap tool call. Helper `_parse_meta` membuat pemakai messages (get_message/get_all_messages/get_messages_after) mendapat dict, bukan string JSON mentah.
- **Retrieval-based notes**: catatan proyek persisten diurutkan berdasarkan relevansi (keyword overlap) terhadap pesan user terakhir. Catatan relevan mendapat budget penuh; catatan yang jelas tidak relevan hanya menampilkan key-nya (tetap semua key disertakan, sesuai keputusan desain). Menurunkan biaya tetap per giliran tanpa menyembunyikan keberadaan catatan.

### Changed
- **`args` → `AgentConfig` dataclass** (prasyarat sub-agent): `run_agent_loop` menerima `AgentConfig` atau `argparse.Namespace` via `coerce_agent_config()` (non-destruktif). Kontrak tipe eksplisit untuk testability & sub-agent.
- **State per-session** (bukan module-global): prasyarat sub-agent paralel.
- **Hapus jalur context lama + blok `TypeError` fallback** di `agent_loop`: `prepare_context_messages` sudah mendukung semua parameter, jadi jalur lama/fallback hanya kode mati.
- **`summarize_model` terpisah** (opsional): model khusus untuk summarization menghemat biaya.

### Internal
- Helper `create_sub_session` di `db.py` untuk sesi sub-agent ber-awalan `sub_`.
- Sinkronisasi `__version__` ke `0.5.0`.

### Tests
- Suite total: **477 passed** (penambahan `tests/test_sub_agent.py`, 9 test).

---

## [0.4.0] - 2026-09-06

Rilis ini menyimpan seluruh pekerjaan yang sudah dikerjakan sejak 0.3.0: optimasi konteks, percepatan startup, cache control OpenRouter, retry anti-429, dan pipeline jobbot. *(Sub-agent + perbaikan arsitektur direncanakan untuk rilis berikutnya.)*

### Added
- **Ringkas catatan `remember` panjang via LLM**: catatan proyek persisten yang panjang diringkas lewat LLM (kolom `summary` di tabel `project_notes`) dengan fallback extractive context-aware. Catatan penuh (`value`) tetap utuh di DB; hanya representasi ringkas yang masuk konteks. Konstanta: `PROJECT_NOTES_MAX_TOTAL_CHARS=12_000`, `PROJECT_NOTES_MAX_PER_NOTE_CHARS=900`, `PROJECT_NOTES_SUMMARIZE_MIN_CHARS=500`.
- **Cache control OpenRouter untuk semua model**: `_wants_openrouter_cache_control` mengembalikan True untuk semua model yang lewat `openrouter.ai` (implicit/otomatis maupun explicit cache breakpoints), plus sticky routing session_id untuk memaksimalkan cache hit. Konstanta `OPENROUTER_MAX_CACHE_BREAKPOINTS=4` dan `OPENROUTER_CACHE_TAIL_BREAKPOINTS=3`.
- **Lazy-load startup**: `requests`, MCP SDK, dan `tiktoken` di-lazy-load sehingga startup CLI jauh lebih cepat (dari ~575ms ke ~431ms).
- **Retry/backoff anti-429 di LLM filter** (`jobbot/llm_filter.py`): `_classify_llm` kini memakai retry/backoff (exp + full jitter) pada {429,500,502,503,504} + ConnectionError/Timeout; 400/401 tidak di-retry.
- **Kirim proposal email personalisasi** (`jobbot/proposal_email.py`): pilih job relevan dari DB dan kirim proposal via SMTP.
- **Uji registrasi flow** (`tests/test_registration_flow.py`): deteksi kemampuan browser, deteksi strategi CAPTCHA (turnstile/recaptcha/hcaptcha/generic + sitekey + fallback human_required), dan ekstraksi OTP/link verifikasi via IMAP.

### Changed
- **Optimasi besar system prompt**: daftar tool dipersingkat (deskripsi + skema tetap dikirim via field `tools` ala OpenAI), hemat ~987 token/giliran (31.2%).
- **Ringkasan akhir giliran** kini menampilkan total token per giliran (input+output), dihitung dari selisih akumulasi `TOKEN_USAGE_TOTAL`.
- **Parameter context-window & summarization dapat dikonfigurasi** (`context_window`, `reserve_for_response`, `summarize_threshold_ratio`, `keep_tail_messages`) via config + slash-command `/ctx`, `/reserve`, `/summarize-threshold`, `/keep-tail`.

### Fixed
- **Bug `token:0`**: timings usage diekstrak dari `predict`/`prompt` fields di `stream_call.py` (`_extract_timings_usage`) sehingga token per giliran dilaporkan benar.
- **Argumen `--framework` di parser execute** (AttributeError saat `cmd_execute`).
- **Bug h-captcha hyphen** di deteksi strategi CAPTCHA.

### Internal
- Sinkronisasi `__version__` ke `0.4.0` dan bump versi di `README.md`.

### Tests
- Suite total: **468 passed** (penambahan test LLM filter retry + registrasi flow).

---

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
