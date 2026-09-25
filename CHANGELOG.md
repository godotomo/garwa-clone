# Changelog

Semua perubahan penting pada proyek ini akan dicatat di file ini.

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id/1.1.0/),
dan versi mengikuti [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Autopilot sisi klien (`/autopilot on|off`)** — saat aktif, giliran tidak
  berhenti hanya karena model berhenti mengirim `tool_call` selama masih ada
  todo berstatus `pending`/`in_progress`. Klien menyuntikkan pesan lanjutan
  berisi daftar todo yang belum selesai (opsional plus catatan reviewer dari
  `/autopilot on <catatan>` atau catatan proyek kunci `reviewer`). Autopilot
  mematikan dirinya sendiri begitu tidak ada todo tersisa dan model tetap tidak
  memanggil tool; ada juga pengaman `GARWA_AUTOPILOT_MAX` (bawaan 20) supaya
  tidak menjadi loop tak berujung. Flag disimpan per-sesi di memori
  (`garwa/cli/_state.py`), logika murni di `garwa/cli/autopilot.py`, titik
  suntik di `garwa/cli/agent_loop.py`.
- **Pewarnaan diff pada output tool** — hasil `edit_file`/`write_file`
  (dan `/git-diff`) kini diwarnai bila stdout adalah TTY: header diff
  (`---`/`+++`/`@@`/`diff --git`) sian, baris `+` hijau, baris `-` merah,
  baris `\ No newline` kuning, konteks diredupkan (dim). Bila output bukan diff
  (mis. pesan biasa) atau stdout bukan TTY (pipe/redirect), teks dikembalikan
  apa adanya tanpa kode ANSI. Helper: `garwa/cli/colors.py::colorize_diff` +
  `looks_like_diff`; seam `_stdout_is_tty()` dipakai agar mudah diuji.
  Integrasi: `garwa/cli/agent_loop.py` (hasil tool) dan
  `garwa/cli/slash_commands.py` (`/git-diff`). Tes:
  `tests/test_diff_color.py` (14 tes).
- **`/max-tool-iters <angka>`** — mengubah batas pemanggilan tool per giliran
  saat runtime (tanpa argumen = tampilkan nilai berlaku; `0` = kembali ke
  default dari `config.MAX_TOOL_ITERS`/env `GARWA_MAX_TOOL_ITERS`). Nilai
  dipersistenkan ke `~/.config/garwa/config`.
- **Deteksi todo basi (`status_since` + `[STALE]`)** — todo disimpan per
  WORKDIR dan `todo_write` bersifat *full replace*, jadi SEMUA baris ditulis
  ulang tiap giliran termasuk `updated_at`; `updated_at` karena itu tidak bisa
  menjawab "sejak kapan item ini menggantung". Kolom baru `status_since`
  (REAL NOT NULL DEFAULT 0) menutup celah itu: nilainya **dipertahankan** dari
  baris lama saat `(content, status)` sama, dan di-set ke `now` hanya saat item
  baru muncul atau statusnya berubah. Migrasi idempoten menambah kolom bila
  belum ada lalu mem-*backfill* `status_since = updated_at` supaya todo lama
  tidak mendadak tampak berumur nol (epoch 0 → salah ditandai basi berhari-hari).
  Modul baru `garwa/todo_utils.py` (murni format/perhitungan, tanpa I/O) dipakai
  seragam oleh tool (`tools/session_tools.py`: `todo_read`/`todo_write`) dan sisi
  CLI (`cli/main.py`, `cli/autopilot.py`, `cli/slash_commands.py`): item
  pending/in_progress yang statusnya tidak berubah melewati ambang ditandai
  `[STALE]` beserta umurnya (mis. `[~] refactor parser  (2j 5m) [STALE]`).
  Ambang diatur `GARWA_TODO_STALE_HOURS` (bawaan `6.0`, `0` = matikan) dan
  **dibaca ulang tiap panggilan** sehingga bisa diubah tanpa restart. Sesi baru
  maupun resume mencetak peringatan jumlah item basi di awal sesi, dan helper
  `db.get_stale_todos()` mengembalikan item kedaluwarsa berurut dari yang paling
  lama menggantung. Semua jalur deteksi dibungkus aman: gagal → list kosong,
  tidak pernah menggagalkan giliran. Autopilot juga memakai ini: `todo_read`
  menyertakan ringkasan item aktif dan `[WARN]` basi, sedangkan pesan lanjutan
  menyebut item yang masih menggantung.
- **Autopilot berhenti saat model berputar tanpa progres** — sebelumnya
  autopilot hanya dibatasi `GARWA_AUTOPILOT_MAX` (bawaan 20), sehingga model
  yang berhenti berulang tanpa mengubah daftar/status todo tetap disuntik
  sampai batas maksimum. Sekarang sidik jari daftar todo (tuple
  `(content, status)`) dibandingkan dengan suntikan sebelumnya; kalau
  berturut-turut `GARWA_AUTOPILOT_STUCK` kali (bawaan 2) sidik jarinya TIDAK
  berubah, autopilot mematikan dirinya sendiri dan melaporkan item yang masih
  menggantung. Selama todo benar-benar berubah, penghitung stuck di-reset dan
  yang membatasi hanyalah `GARWA_AUTOPILOT_MAX`.

### Changed

- **Batas default pemanggilan tool per giliran dinaikkan 100 → 500**
  (`config.MAX_TOOL_ITERS`). Autopilot menyuntikkan pesan lanjutan, jadi batas
  lama membuat rencana panjang kena potong di tengah. Nilai `0` pada
  `--max-tool-iters`/`AgentConfig.max_tool_iters` kini berarti "pakai default",
  bukan benar-benar nol iterasi.

### Fixed

- **`db.py` — `get_todos()` tanpa scope membaca todo SELURUH proyek.** Todo
  sudah disimpan per `workdir` (sama seperti catatan proyek), tetapi bila
  `workdir` **dan** `session_id` sama-sama kosong fungsi ini mengembalikan
  **seluruh baris tabel** — satu proyek bisa membaca rencana proyek lain, persis
  kebocoran yang harus dicegah. **Fix:** tanpa scope sekarang mengembalikan `[]`
  disertai `logger.warning` (pemanggil salah pakai tetap terlihat di log, tapi
  tidak ada data yang bocor). Regresi: `test_get_todos_without_scope_returns_empty`.
- **`db.py` — `replace_todos()` menerima `workdir` kosong (todo "yatim").**
  Menulis todo tanpa `workdir` menghasilkan baris yang tersimpan di DB tetapi
  tidak lagi terbaca proyek mana pun, karena semua pembacaan di-key oleh
  `workdir`. **Fix:** `workdir` kosong/None/whitespace kini `raise ValueError`
  (gagal keras lebih baik daripada data tak terjangkau). Regresi:
  `test_replace_todos_requires_workdir`.
- **`telegram_gateway.py` — todo gateway Telegram memakai cwd, bukan `--workdir`.**
  Mode `--bot` keluar dari `main.py` **sebelum** baris `tools_module.state.WORKDIR = args.workdir`,
  sehingga `_prepare_state()` menyiapkan DB/sesi dengan workdir yang benar tapi
  membiarkan `state.WORKDIR` (dipakai `todo_write`/`todo_read`, path sandbox, dan
  cwd `bash`) menunjuk `os.getcwd()` proses. Akibatnya gateway dijalankan dengan
  `--workdir` eksplisit tetap membaca/menulis todo proyek lain (dan menandai file
  ter-touch di proyek yang salah). **Fix:** `_prepare_state()` kini menyelaraskan
  `state.WORKDIR` **dan** env `GARWA_WORKDIR` ke `self._workdir()` — satu sumber
  kebenaran yang sama dengan nama sesi dan system prompt. Regresi:
  `test_prepare_state_aligns_workdir` di `tests/test_telegram_gateway.py`.
- **`db.py` — `replace_todos` gagal keras di DB lama (todo tidak tersimpan).**
  Kolom `workdir`/`status_since` hanya ditambahkan di dalam `init_db()`, padahal
  `CREATE TABLE IF NOT EXISTS` tidak menyentuh tabel yang sudah ada. Jalur yang
  tidak melewati `init_db()` (pemakaian programatik, sub-agent, skrip) karena itu
  melempar `OperationalError: table todos has no column named status_since` dan
  todo-nya **hilang tanpa tersimpan**. Ini terbukti pada DB produksi
  `~/.garwa/garwa.db` yang masih berkolom lama. **Fix:** migrasi diekstrak ke
  `db.ensure_todos_columns(conn)` (idempoten; menambah `workdir` + *backfill*
  dari `sessions`, menambah `status_since` + *backfill* dari `updated_at`, dan
  membuat skema bila tabel belum ada) yang kini dipanggil dari `init_db()`
  **dan** di awal `replace_todos()`, sehingga semua jalur masuk aman. Regresi
  ditutup 4 test baru di `tests/test_db.py` (DB lama tanpa `init_db`, DB kosong,
  idempotensi, dan preservasi `status_since` setelah migrasi).
- **Deteksi todo basi di `todo_write` tidak pernah menyala.** Deteksi
  memakai daftar hasil normalisasi dari *input* model, padahal item input hanya
  berisi `{content, status}` tanpa `status_since`; umurnya karenanya selalu
  dihitung nol detik sehingga `[WARN]` basi mustahil muncul. **Fix:** setelah
  penulisan, baris dibaca ULANG dari DB (`db.get_todos`) — di situlah
  `status_since` hasil preservasi `replace_todos` berada — lalu diringkas dengan
  `todo_utils.stale_summary`. Kegagalan baca DB diabaikan (deteksi basi tidak
  boleh menggagalkan giliran).
- **`agent_loop.py` — autopilot melaporkan alasan berhenti yang salah.**
  Ketika autopilot berhenti karena *stuck* (tidak ada progres), kode tetap
  melanjutkan ke pesan "batas pesan lanjutan (`GARWA_AUTOPILOT_MAX`) tercapai",
  sehingga user melihat dua alasan berhenti sekaligus dan yang kedua menyesatkan.
  **Fix:** flag `_stopped_stuck` dipakai untuk menekan pesan batas lanjutan.
- **`subagent_status.py` — watchdog sub-agent bisa mati diam-diam (race
  keepalive).** State keepalive dulu global dan tidak bergenerasi: ketika
  sub-agent pertama selesai, `notify_done()` men-set `_keepalive_stop` milik
  generasi berjalan; sub-agent kedua yang dipanggil setelah itu menemukan
  thread watchdog lama masih `is_alive()` (belum sempat unwind) sehingga
  `_ensure_keepalive()` *early-return* tanpa menyalakan watchdog baru — begitu
  thread lama keluar, sub-agent kedua berjalan **tanpa satu pun baris status**
  (`masih berjalan`/`MACET`). **Fix:** state watchdog dibuat per-generasi
  (`_keepalive_stop` baru + `_keepalive_gen` + `_keepalive_alive` tiap spawn),
  `_ensure_keepalive()` memeriksa flag `_keepalive_alive` alih-alih
  `is_alive()`, penambahan `_request_keepalive_stop()` (yang juga mengecek ulang
  `_any_running()` di dalam lock agar tidak mematikan watchdog generasi baru)
  dan `_mark_keepalive_exit(gen)` (generasi usang yang telat bangun tidak
  meng-clobber generasi baru). Regresi ditutup 4 test baru di
  `tests/test_sub_agent_safety.py`.
- **`dispatch.py` / `stream_call.py` — koneksi terputus di tengah stream
  langsung mematikan seluruh giliran.** `ChunkedEncodingError` (mis.
  `Connection broken: ConnectionAbortedError(103, 'Software caused connection
  abort')` dari server model di balik tunnel) adalah subclass
  `RequestException` tetapi **bukan** subclass `ConnectionError`, sehingga lolos
  dari semua pemeriksaan retry yang ada (yang hanya menangani 429 dan 5xx).
  **Fix:** fungsi baru `_is_connection_error()` + 4 percobaan total (1 awal +
  3× retry, jeda 3 detik) via env `GARWA_CONNECTION_RETRY`. Pesan di
  `stream_call.py` diubah jadi netral (`[STREAM] Koneksi terputus...`) supaya
  tidak berbunyi seperti kegagalan final padahal retry berikutnya bisa
  berhasil. Error konfigurasi (`InvalidURL`/`MissingSchema`, subclass
  `ValueError`) tetap dilempar segera — retry tidak akan menolongnya.
- **Progress bar ringkasan riwayat mandek di 25%.** `_summarize_text`
  memanggil callback `progress(attempt, total)` **sekali per percobaan**, dan
  callback lama menghitung `fraction = (attempt + 1) / total` dengan
  `total = SUMMARIZE_MAX_RETRIES + 1 = 4`. Jadi percobaan pertama mematok bar
  di 1/4 = 25% lalu diam selama `requests.post()` yang blocking (bisa
  menit-an) — bar tampak macet dan user mengira prosesnya berhenti.
  **Fix:** rumus lompat itu dihapus. `ProgressBar.start_creep()` sekarang
  menaikkan fraksi mengikuti WAKTU dengan kurva hiperbolik
  `ratio(t) = t / (t + half_life)` (bawaan `half_life = 6 s`) menuju satu
  plafon global `CREEP_CEILING = 0.95`; percobaan yang di-retry **melanjutkan**
  pendakian dari posisi terakhir (bar monoton, tidak pernah turun), dan puncak
  100% hanya dipatok `finish()` setelah ringkasan benar-benar didapat — jadi
  bar tidak pernah mengaku selesai terlalu dini. Creep hanya dinyalakan di TTY
  (di pipe/redirect tetap dicetak satu blok status, aman memory buffer) dan
  lebar bar dibatasi `lebar_terminal - 1` supaya tidak memicu auto-wrap.
  Desain lama yang memberi **irisan per percobaan**
  (`[attempt/total, (attempt+1)/total * 0.95]`) sengaja dibuang: irisan pertama
  berhenti di 23,75%, yaitu gejala "mentok di 25%" itu sendiri. Untuk terminal
  tanpa glyph blok Unicode, env `GARWA_PROGRESS_ASCII=1` membuat bar memakai
  `#`/`-`. Alur fraksi diuji di jalur produksi
  (`tests/test_summarize_progress.py`).
- **Polusi lintas-tes menyembunyikan regresi di suite penuh.** Enam tes di
  `tests/test_context_manager.py` menugaskan `cm._summarize_text = fake_summarize`
  langsung ke atribut modul sehingga **tidak pernah dipulihkan**; setelah file
  itu berjalan, fungsi asli tertimpa fake milik tes terakhir (yang
  mengembalikan `{"narasi": "   "}`). Akibatnya tes progress bar **lulus saat
  dijalankan sendiri tetapi gagal di suite penuh**. **Fix:** semua penugasan
  diganti `monkeypatch.setattr(...)` sehingga otomatis dipulihkan.

### Tests

- **`tests/test_todo_stale.py`** (39 tes) — regresi untuk todo basi: helper murni
  (`format_age`, `age_seconds`, `is_stale`, `format_rows`, `find_stale`,
  `stale_summary`, ambang dari env yang dibaca ulang tiap panggilan), perilaku DB
  (`status_since` dipertahankan saat status sama, di-reset saat berubah, item baru
  mulai dari nol, backfill migrasi, `get_stale_todos` memfilter & mengurut),
  tool `todo_read`/`todo_write` (umur, `[STALE]`, `[WARN]` item hilang/regresi/basi,
  tidak memperingatkan lagi setelah item ditutup), `cli.main._warn_stale_todos`
  (cetak sekali, senyap bila segar, tidak melempar saat DB buruk), dan autopilot
  *stuck* di `agent_loop`. Ditambah penyesuaian
  `tests/test_autopilot.py::test_autopilot_is_bounded` (menetralkan stuck-limit
  agar tes batas suntikan tidak lagi bergantung pada jalur stuck).
- **`tests/test_db.py`** (+4 tes) — migrasi tabel `todos`: `replace_todos` pada
  DB lama tanpa `init_db()` (dulu hard-fail), pembuatan skema pada DB kosong,
  idempotensi `ensure_todos_columns`, dan `status_since` tetap dipertahankan
  setelah migrasi.

## [0.5.3] - 2026-09-25

Rilis perbaikan bug hasil audit menyeluruh (P0–P3). Fokus: integritas git index,
keandalan pemanggilan tool (multi-blok + template literal), deteksi *degenerate
loop* yang salah positif, dan sejumlah bug fungsional di tools.

### Fixed — P0 (kritis)

- **`checkpoints.py` — index git terklobber tiap giliran** (`_create_untracked_commit`).
  `git read-tree HEAD` / `read-tree --empty` dijalankan TANPA `GIT_INDEX_FILE`,
  sehingga menulis ke `.git/index` **asli** dan mengosongkannya (index 33 KB → 65 B).
  Akibatnya seluruh file tracked tampak `D` (deleted) dan `git commit` bisa
  menghapus semua file dari history. **Fix:** teruskan env `GIT_INDEX_FILE` ke
  KEDUA `read-tree` (dan semua operasi index lain), plus **guard otomatis**:
  salinan `.git/index` sebelum operasi, dipulihkan bila isinya berubah.
- **`agent_loop.py` — hanya blok `tool_call` PERTAMA yang dieksekusi.**
  `extract_tool_call()` memakai `re.search` (match pertama) sedangkan pembersih
  `visible_text` menghapus SEMUA blok → blok ke-2..n hilang tanpa eksekusi.
  Karena `todo_write` bersifat *full-replace*, todo jadi parsial (sebagian `done`,
  sisanya tidak tersimpan) — inilah penyebab keluhan "todo sebagian tidak
  terupdate padahal sudah dikerjakan". **Fix:** fungsi baru
  `json_repair.extract_tool_calls()` (multi-blok) + `agent_loop` mengeksekusi
  SEMUA blok secara berurutan.
- **`agent_loop.py` — giliran berhenti senyap** saat tidak ada `tool_call` valid.
  **Fix:** emit pesan eksplisit `[STOP] Tidak ada tool_call valid dalam respon
  model.` sebelum `_emit_summary()` + `return`.
- **`json_repair.py` — contoh TEMPLATE literal dianggap `tool_call` nyata.**
  Contoh di system prompt yang berisi nama tool bertanda sudut + `...`
  (placeholder) dikutip model di prosa → diparse sebagai tool_call →
  `PARSE_ERROR` → memicu jalur `[LOOP]`/`[STOP]` palsu dan **membuang tool_call
  asli di blok berikutnya**. **Fix:** guard konservatif yang butuh KEDUANYA —
  (a) nama bertanda sudut (`<...>`) DAN (b) ada `...` — maka blok di-skip sebagai
  template, bukan tool_call. Tool_call nyata tidak memakai nama bertanda sudut,
  sehingga risiko menelan pemanggilan sungguhan sangat kecil.
- **`sub_agent.py` — `spawn_agents_parallel` tanpa admission-control/timeout, memblokir seluruh chat.**
  Terbukti 4 sub-agent paralel saling `429 concurrent_limit` (6.5 s vs ideal 0.5 s;
  backoff asli 30–120 s ⇒ bisa 5+ menit), dan `execute_tool` dipanggil sinkron
  sehingga chat terblokir sampai batch selesai. **Fix:** irama deadline batch
  (`GARWA_SUBAGENT_TIMEOUT`, default 900 s/task × jumlah gelombang), laporan
  timeout per task, dan opsi keepalive (`GARWA_SUBAGENT_KEEPALIVE`).

### Fixed — P1

- **`agent_loop.py` — hook `PostToolUse` gagal di tool PERTAMA tiap giliran.**
  `_is_error` dipakai di `run_hooks(is_error=_is_error, ...)` sebelum di-assign
  (`UnboundLocalError`; hook dilewati pada iterasi 1, normal di iterasi berikutnya).
  **Fix:** hitung status error SEBELUM pemanggilan hook.
- **`json_repair.py` — matcher `tool_call` non-greedy `\{.*?\}`.** JSON dengan
  `}` di dalam string terpotong, dan fragmen prosa/kutipan bisa disalahartikan
  sebagai tool_call (memicu `PARSE_ERROR` palsu + kebocoran blok mentah ke
  `visible_text`). **Fix:** *brace-matcher* berimbang berbasis
  `json.JSONDecoder().raw_decode` yang menghormati string/escape.
- **`json_repair.py` — klasifikasi error keliru.** Diagnosa memakai `"..." in raw_json`
  sehingga error yang akar masalahnya *Unterminated string* salah dilaporkan
  sebagai soal placeholder ellipsis (dan `...` valid di dalam string ikut ditolak).
  **Fix:** klasifikasikan lewat `e.msg` (mis. *Unterminated string* → "string tidak
  ditutup") dan pesan `...` hanya bila benar-benar placeholder.
- **`comm_tools.py` — override `chat_id` per-turn diabaikan.**
  `_telegram_chat_id()` membaca env tanpa prefix (`TELEGRAM_CHAT_ID`), sedangkan
  gateway men-set `GARWA_TELEGRAM_CHAT_ID` per-turn → hasil agent (voice/document/
  pesan) nyasar ke channel default. **Fix:** prioritaskan `GARWA_TELEGRAM_CHAT_ID`
  dari env proses, fallback ke config.
- **`webfetch.py` — `NameError` saat parsing HTML.** Kode memakai `BeautifulSoup`
  langsung padahal hanya `_BeautifulSoup` yang di-bind dan `_get_bs4()` tak pernah
  dipanggil. **Fix:** pakai `_get_bs4()` dengan penanganan bila `bs4` tak tersedia.
- **`agent_loop.py` — pembersih `visible_text` tidak konsisten dengan extractor.**
  **Fix:** pakai matcher yang SAMA (`strip_tool_call_blocks`) agar sisa sintaks
  gagal-konversi tidak tampil ke user.

### Fixed — P2

- **`json_repair.py` — `{...}` → `PARSE_ERROR` berpesan jelas** (sebelumnya
  `(None, None)` senyap yang memicu jalur berhenti bisu).
- **Code fence & literal** — docstring/contoh sintaks `tool_call` di dalam file
  yang ditulis agent tidak lagi diperlakukan sebagai tool_call nyata (diverifikasi
  lewat repro khusus; 0 kasus nyata di DB).

### Fixed — P3 (kebersihan kode)

- **`repo_map.py`** — hapus redefinisi `_get_parser` (sudah ada di atas).
- **`cli/tool_schema/__init__.py`** — tandai re-export lewat `__all__` (pyflakes
  4.0.0 menghormati `__all__`, sedangkan `# noqa` tidak).
- **`checkpoints.py`** — rapikan sisa referensi `sqlite3` yang tak terpakai.

### Changed

- **`cli/todo_coalesce.py` (baru)** — gabungkan >1 blok `todo_write` dalam satu
  giliran menjadi satu panggilan (blok terakhir menang untuk item duplikat),
  mencegah todo parsial.
- **`cli/text_utils.py`** — deteksi *degenerate loop* memakai *run* baris identik
  berurutan (`_longest_line_run`, `REPEAT_MAX_OCCUR`) alih-alih total kemunculan,
  mengurangi salah positif pada output normal (mis. fence ```python berulang).
- **`cli/agent_loop.py`** — jalur `[LOOP]`/`RepetitionLoopError` kini MENYUNTIKKAN
  pesan koreksi ke percakapan sebelum retry, agar percobaan berikutnya tidak
  mengirim konteks identik dan mengulang pola yang sama.
- **`subagent_status.py`** — header paralel kini melaporkan progress berkala
  (keepalive) sehingga tidak terlihat "menggantung".

### Tests

- `tests/test_todo_coalesce.py` (baru) — 10 test koalesensi `todo_write`,
  termasuk end-to-end "semua todo tersimpan".
- `tests/test_agent_loop_loop_correction.py` (baru) — memastikan koreksi `[LOOP]`
  disuntikkan ke percakapan.
- Repro/verifikasi tambahan: multi-blok tool_call, template-quote, guard git index,
  matcher brace berimbang. `pytest -q` **exit 0** (0 regresi); pyflakes bersih.

## [0.5.2] - 2026-09-09

Penyempurnaan system prompt agar lebih general & adaptif (tidak hanya coding
CLI), diadaptasi dari prinsip behavior-spec Hermes Agent tanpa mengadopsi
penuh konsepnya.

### Changed
- **Identity lebih general & adaptif**: baris "asisten coding CLI" diganti
  menjadi "asisten AI yang adaptif" — apa pun yang diminta user (coding,
  riset, menulis, analisis data, desain, atau tugas umum) dikerjakan dengan
  tool yang tersedia, bukan terpaku pada satu jenis tugas.
- **Blok `CARANYA BERPERILAKU` baru**: sizing reply (panjang jawaban sesuai
  bobot permintaan), tanpa filler/restate/narrate, klaim polos, depth earned
  (bukan default) — diadaptasi dari `DEFAULT_AGENT_IDENTITY` hermes-agent.
- **Blok `BAHASA RESPONS` baru**: ikuti bahasa yang dipakai user (Indonesia/
  Inggris), tanpa mencampur tanpa alasan.
- **Blok `ATURAN TAMBAHAN` baru**:
  - Tanya dulu (1 pertanyaan singkat) saat permintaan ambigu, kecuali konteks jelas.
  - Konfirmasi ke user sebelum perintah destruktif (hapus file, force-push, dsb).
  - Jangan memanggil tool berlebihan; jawab langsung kalau sudah jelas.
  - Laporkan error tool apa adanya, jangan menebak/mengarang hasil.

### Internal
- `system_prompt.py`: struktur prompt ditata ulang menjadi identity →
  workdir → personality → tools → skills → env hint → perilaku → bahasa →
  aturan tambahan → format tool call.

### Tests
- Suite total: **682 passed, 1 skipped** (0 regresi).

---

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
