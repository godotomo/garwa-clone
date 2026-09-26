"""
db.py
Lapisan persistensi SQLite untuk Garwa.

Tujuan:
- Sesi (session) bisa di-resume setelah CLI ditutup (Ctrl+C / crash).
- Riwayat percakapan penuh disimpan permanen (walau context yang dikirim
  ke model di-summarize/dipangkas -- lihat context_manager.py).
- Plan/todo list persisten per sesi (mirip TodoWrite pada agent CLI).
- Project memory (catatan singkat key-value) persisten per workdir, lintas sesi.
- Cache outline/tag file (dari tree-sitter) supaya tidak parse ulang file
  yang belum berubah (dicek lewat mtime+ukuran).

Semua fungsi di sini sengaja synchronous & sederhana (pakai stdlib sqlite3)
karena CLI ini single-user, single-process, single-threaded per giliran.
"""

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.path.join(os.path.expanduser("~"), ".garwa", "garwa.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    workdir     TEXT NOT NULL,
    title       TEXT,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    ended       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,          -- system | user | assistant
    content     TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'chat',  -- chat | tool_call | tool_result | summary
    pinned      INTEGER NOT NULL DEFAULT 0,   -- 1 = pesan penting yg TIDAK ikut diringkas
    meta        TEXT,                          -- JSON: tool_name, args, is_error, token_estimate (data training)
    created_at  REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
-- Index PARSIAL untuk pesan yang di-pin. Tabel `messages` bisa puluhan ribu
-- baris, sedangkan pesan pinned biasanya SANGAT sedikit (sering nol). Tanpa
-- index ini, `SELECT * FROM messages WHERE session_id=? AND pinned=1`
-- memakai idx_messages_session lalu harus membuka tabel utama untuk SETIAP
-- baris sesi tersebut (ribuan kali) hanya untuk membaca kolom `pinned` --
-- terukur ~15 ms per panggilan pada sesi 7.2k pesan, dan fungsi ini
-- dipanggil 2x tiap giliran. Index parsial hanya memuat baris pinned
-- sehingga pencariannya ~0.02 ms.
CREATE INDEX IF NOT EXISTS idx_messages_pinned ON messages(session_id, id) WHERE pinned = 1;

CREATE TABLE IF NOT EXISTS summaries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL,
    upto_message_id     INTEGER NOT NULL,   -- messages dengan id <= ini sudah terangkum
    summary_text        TEXT NOT NULL,
    active_instructions TEXT,               -- JSON array string; instruksi aktif verbatim (ATURAN 1)
    created_at          REAL NOT NULL
);
-- Tanpa index ini, `ORDER BY id DESC LIMIT 1` pada `summaries` memindai +
-- mengurutkan SELURUH baris tabel (ribuan baris lintas semua sesi) tiap
-- giliran -- terukur ~2.3 ms vs ~0.12 ms dengan index.
CREATE INDEX IF NOT EXISTS idx_summaries_session ON summaries(session_id, id DESC);

-- CATATAN: `todos.session_id` SENGAJA tanpa FOREIGN KEY (beda dengan
-- `messages.session_id` di bawah) supaya todo tetap bisa dibaca walau baris
-- `sessions` terkait sudah dihapus. Kalau perilaku ini tidak diinginkan,
-- tambahkan FK yang sama seperti di `messages`.
CREATE TABLE IF NOT EXISTS todos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    workdir     TEXT NOT NULL DEFAULT '',
    position    INTEGER NOT NULL,
    content     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | in_progress | done | cancelled
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    -- Kapan status item ini TERAKHIR BERUBAH (bukan kapan barisnya ditulis).
    -- Dipakai untuk menghitung umur status -> mendeteksi todo yang menggantung
    -- / basi (mis. `in_progress` yang tidak pernah ditutup berhari-hari).
    -- Full replace (todo_write) menulis ulang semua baris tiap giliran, jadi
    -- `updated_at` saja TIDAK bisa dipakai sebagai penanda "sejak kapan".
    status_since REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_todos_session ON todos(session_id, position);
CREATE INDEX IF NOT EXISTS idx_todos_workdir ON todos(workdir, position);

CREATE TABLE IF NOT EXISTS project_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    workdir     TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    updated_at  REAL NOT NULL,
    summary     TEXT,
    UNIQUE(workdir, key)
);

CREATE TABLE IF NOT EXISTS file_cache (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    workdir     TEXT NOT NULL,
    path        TEXT NOT NULL,
    mtime       REAL NOT NULL,
    size        INTEGER NOT NULL,
    outline     TEXT NOT NULL,
    lang        TEXT,
    updated_at  REAL NOT NULL,
    UNIQUE(workdir, path)
);

-- Pemetaan chat Telegram -> sesi Garwa. Dipakai oleh gateway Telegram
-- (garwa/telegram_gateway.py) supaya tiap chat punya riwayat percakapan
-- sendiri (session_id terpisah), dan bisa di-resume antar sesi bot.
CREATE TABLE IF NOT EXISTS telegram_bindings (
    chat_id     TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    updated_at  REAL NOT NULL
);
"""


#: timeout (detik) SQLite busy-handler per statement. Diturunkan dari 30 ke
#: nilai ini supaya operasi yang menunggu lock tidak menggantung terlalu lama
#: saat sub-agent paralel menulis ke DB yang sama. WAL memungkinkan banyak
#: reader + satu writer, tapi writer tetap diserialisasi; busy_timeout memberi
#: jeda tunggu per statement sebelum melempar OperationalError.
DB_BUSY_TIMEOUT = 30
#: Jeda (detik) antar-retry saat DB terkunci. Dipakai oleh helper
#: `_retry_connect` yang bisa dipanggil pemanggil bila perlu (busy_timeout
#: saja kadang tidak cukup untuk writer yang memegang lock sangat lama).
DB_BUSY_RETRY_DELAY = 0.05


# ---------------------------------------------------------------------------
# Connection scope: berbagi SATU koneksi SQLite untuk banyak `connect()`
# bersarang ke db_path yang sama.
#
# Masalah (terukur di sesi optimasi P3): membuka koneksi SQLite BUKAN sekadar
# membuka file. Query pertama pada koneksi baru harus memuat skema + cache
# halaman, sehingga koneksi baru terukur ~1.5-2 ms lebih mahal daripada koneksi
# yang sudah "panas" -- dan biaya itu TIDAK hilang dengan menghapus PRAGMA
# journal_mode=WAL (A/B: WAL pragma hanya 0.12 ms/koneksi, tapi churn
# buka/tutup ~1.7 ms/koneksi). Satu giliran normal memanggil `connect()` 5-6x
# (build_context_messages + maybe_summarize + helper di bawahnya), churn itu
# sendiri terukur ~10 ms/giliran.
#
# Solusi: `connection_scope()` membuka satu koneksi bersama; semua `connect()`
# di dalam blok itu memakainya tanpa membuka/menutup sendiri. Commit + close
# hanya sekali di akhir scope terluar.
#
# Sifat yang dipertahankan:
#   * Reentrant: scope bersarang (kedalaman > 0) tidak membuka koneksi baru.
#   * Per-thread: koneksi tidak boleh dipakai lintas thread (sqlite3), jadi
#     state scope disimpan di `threading.local()` -- sub-agent paralel
#     (spawn_agents_parallel) masing-masing punya koneksinya sendiri.
#   * Per-path: scope untuk db_path berbeda tidak saling berbagi koneksi.
#   * Semantik commit: exception yang keluar dari scope terluar -> rollback;
#     selain itu -> commit. Sama seperti `connect()` tunggal.
#   * `connect()` di dalam scope bersifat read+write biasa (tanpa commit
#     sendiri); karena semuanya satu koneksi, penulisan juga langsung terlihat
#     oleh pembacaan berikutnya di scope yang sama -- konsisten.
# ---------------------------------------------------------------------------

_SCOPE_STATE = threading.local()


def _scope_map() -> dict:
    """Peta {path absolut: entri scope} untuk thread saat ini."""
    store = getattr(_SCOPE_STATE, "store", None)
    if store is None:
        store = _SCOPE_STATE.store = {}
    return store


def _scope_exit(store: dict, key: str, ent: dict, ok: bool) -> None:
    store.pop(key, None)
    conn = ent["conn"]
    try:
        if ok:
            conn.commit()
        else:
            conn.rollback()
    except Exception:
        logger.warning("connection_scope: gagal menutup transaksi", exc_info=True)
    finally:
        try:
            conn.close()
        except Exception:
            logger.warning("connection_scope: gagal menutup koneksi", exc_info=True)


@contextmanager
def connection_scope(db_path: str = DEFAULT_DB_PATH):
    """Bagikan satu koneksi untuk semua `connect()` ke `db_path` di dalam blok.

    Dipakai untuk operasi baca/tulis beruntun dalam satu giliran (mis.
    `build_context_messages()` + `maybe_summarize()`) supaya tidak membuka
    koneksi baru 5-6x. Lihat blok komentar di atas untuk detail & sifatnya.
    """
    store = _scope_map()
    key = os.path.abspath(db_path)
    ent = store.get(key)
    if ent is not None:
        # Scope bersarang: cukup tambah kedalaman; commit/close di level terluar.
        ent["depth"] += 1
        try:
            yield ent["conn"]
        finally:
            ent["depth"] -= 1
        return
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = _open_conn(db_path)
    ent = {"conn": conn, "depth": 1}
    store[key] = ent
    ok = True
    try:
        yield conn
    except Exception:
        ok = False
        raise
    finally:
        _scope_exit(store, key, ent, ok)


@contextmanager
def connect(db_path: str = DEFAULT_DB_PATH):
    ent = _scope_map().get(os.path.abspath(db_path))
    if ent is not None:
        # Di dalam connection_scope: pakai koneksi bersama; JANGAN commit/close
        # sendiri (biar scope terluar yang menutup sekali).
        yield ent["conn"]
        return
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = _open_conn(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:

        conn.rollback()
        raise
    finally:
        conn.close()


def _open_conn(db_path: str):
    """Buka koneksi SQLite dengan busy_timeout yang panjang (tahan terhadap
    lock sementara dari writer lain, mis. sub-agent paralel)."""
    conn = sqlite3.connect(db_path, timeout=DB_BUSY_TIMEOUT)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute(f"PRAGMA busy_timeout={int(DB_BUSY_TIMEOUT * 1000)};")
    return conn


def _is_busy_error(exc: Exception) -> bool:
    """True kalau exception SQLite karena database terkunci (busy/locked)."""
    msg = str(exc)
    return "database is locked" in msg or "database table is locked" in msg


def ensure_todos_columns(conn) -> None:
    """Migrasi kolom tabel `todos` secara idempoten (aman dipanggil berkali-kali).

    `CREATE TABLE IF NOT EXISTS` TIDAK menambahkan kolom baru ke tabel yang
    sudah ada, jadi DB lama harus dimigrasi eksplisit. Dipanggil dari
    `init_db()` **dan** dari awal `replace_todos()`: kalau hanya mengandalkan
    `init_db()`, jalur yang tidak lewat `init_db` (pemakaian programatik,
    sub-agent, skrip) akan gagal keras dengan
    `OperationalError: table todos has no column named status_since` dan
    todo-nya hilang tanpa disimpan.

    Migrasi yang dilakukan:
      * `workdir` (todo milik PROYEK, bukan sesi) + backfill dari `sessions`.
      * `status_since` (kapan status terakhir BERUBAH) + backfill dari
        `updated_at`, supaya todo lama tidak tampak "berumur nol"
        (epoch 0 = 1 Jan 1970) dan salah ditandai basi berhari-hari.
    """
    tcol = [r[1] for r in conn.execute("PRAGMA table_info(todos)").fetchall()]
    if not tcol:
        # Tabel (atau seluruh skema) belum ada -- buat sekarang. Semua
        # pernyataan di SCHEMA memakai IF NOT EXISTS sehingga idempoten.
        conn.executescript(SCHEMA)
        tcol = [r[1] for r in conn.execute("PRAGMA table_info(todos)").fetchall()]
        if not tcol:
            return
    if "workdir" not in tcol:
        conn.execute("ALTER TABLE todos ADD COLUMN workdir TEXT NOT NULL DEFAULT ''")
        # Backfill: isi workdir dari tabel sessions berdasarkan session_id
        # untuk todo lama yang masih punya sesi terkait.
        try:
            conn.execute(
                "UPDATE todos SET workdir = COALESCE("
                "(SELECT s.workdir FROM sessions s WHERE s.id = todos.session_id), '') "
                "WHERE workdir = ''"
            )
        except Exception:
            pass
    if "status_since" not in tcol:
        conn.execute("ALTER TABLE todos ADD COLUMN status_since REAL NOT NULL DEFAULT 0")
    try:
        conn.execute("UPDATE todos SET status_since = updated_at WHERE status_since = 0")
    except Exception:
        pass


def init_db(db_path: str = DEFAULT_DB_PATH):
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        # Migrasi ringan: DB lama (sebelum kolom `pinned` ada) tidak akan
        # mendapat kolom itu dari CREATE TABLE IF NOT EXISTS. Tambahkan
        # secara idempoten kalau belum ada.
        cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
        if "pinned" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")

        # Migrasi ringan: kolom `meta` di tabel messages (JSON berisi
        # tool_name, args, is_error, token_estimate untuk data training).
        # DB lama tidak akan mendapatnya dari CREATE TABLE IF NOT EXISTS.
        if "meta" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN meta TEXT")

        # Migrasi ringan: kolom `active_instructions` di tabel summaries
        # (menyimpan instruksi aktif verbatim hasil summarize sebagai JSON
        # array string). DB lama tidak akan mendapatnya dari CREATE TABLE
        # IF NOT EXISTS, jadi tambahkan secara idempoten kalau belum ada.
        scol = [r[1] for r in conn.execute("PRAGMA table_info(summaries)").fetchall()]
        if "active_instructions" not in scol:
            conn.execute("ALTER TABLE summaries ADD COLUMN active_instructions TEXT")

        # Migrasi ringan: kolom `summary` di tabel project_notes (ringkasan
        # catatan via LLM untuk diringkas di konteks tanpa kehilangan konteks
        # penting). DB lama tidak akan mendapatnya dari CREATE TABLE IF NOT
        # EXISTS, jadi tambahkan secara idempoten kalau belum ada.
        ncol = [r[1] for r in conn.execute("PRAGMA table_info(project_notes)").fetchall()]
        if "summary" not in ncol:
            conn.execute("ALTER TABLE project_notes ADD COLUMN summary TEXT")

        # Migrasi ringan tabel `todos` (workdir + status_since). Dipakai juga
        # oleh replace_todos() supaya jalur yang tidak lewat init_db() tetap
        # aman. Lihat ensure_todos_columns().
        ensure_todos_columns(conn)



def create_session(db_path: str, workdir: str, title: str = None) -> str:
    now = time.time()

    last_err = None
    for _ in range(5):
        sid = uuid.uuid4().hex[:12]
        try:
            with connect(db_path) as conn:
                conn.execute(
                    "INSERT INTO sessions (id, workdir, title, created_at, updated_at, ended) "
                    "VALUES (?, ?, ?, ?, ?, 0)",
                    (sid, workdir, title, now, now),
                )
            return sid
        except sqlite3.IntegrityError as e:
            last_err = e
            continue
    raise last_err


def create_sub_session(db_path: str, workdir: str, title: str = None) -> str:
    """Buat sesi SUB-AGENT dengan id ber-awalan `sub_`.

    Sub-agent memakai sesi terpisah (context window sendiri) supaya tidak
    mencemari sesi induk. Id `sub_<hex>` membuatnya mudah dibedakan dari sesi
    interaktif biasa di `list_sessions` / analisis DB.
    """
    now = time.time()
    last_err = None
    for _ in range(5):
        sid = "sub_" + uuid.uuid4().hex[:12]
        try:
            with connect(db_path) as conn:
                conn.execute(
                    "INSERT INTO sessions (id, workdir, title, created_at, updated_at, ended) "
                    "VALUES (?, ?, ?, ?, ?, 0)",
                    (sid, workdir, title, now, now),
                )
            return sid
        except sqlite3.IntegrityError as e:
            last_err = e
            continue
    raise last_err


def touch_session(db_path: str, session_id: str):
    with connect(db_path) as conn:
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (time.time(), session_id))


def end_session(db_path: str, session_id: str):
    with connect(db_path) as conn:
        conn.execute("UPDATE sessions SET ended = 1, updated_at = ? WHERE id = ?",
                     (time.time(), session_id))


def get_session(db_path: str, session_id: str):
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None


def list_sessions(db_path: str, workdir: str = None, limit: int = 20):
    with connect(db_path) as conn:
        if workdir:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE workdir = ? ORDER BY updated_at DESC LIMIT ?",
                (workdir, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def latest_open_session(db_path: str, workdir: str):
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE workdir = ? AND ended = 0 "
            "ORDER BY updated_at DESC LIMIT 1",
            (workdir,),
        ).fetchone()
        return dict(row) if row else None



def add_message(db_path: str, session_id: str, role: str, content: str, kind: str = "chat",
                meta: dict = None) -> int:
    """Tambahkan satu pesan ke sesi.

    `meta` (opsional): dict JSON yang disimpan di kolom `meta` (mis.
    {"tool_name": ..., "args": ..., "is_error": ..., "token_estimate": ...})
    untuk data training. Dibuat agar backward-compatible: kalau None,
    kolom meta diisi NULL (perilaku lama).
    """
    now = time.time()
    meta_json = json.dumps(meta, ensure_ascii=False) if meta is not None else None
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO messages (session_id, role, content, kind, meta, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, role, content, kind, meta_json, now),
        )
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        return cur.lastrowid


def set_message_pinned(db_path: str, session_id: str, message_id: int, pinned: bool = True):
    """Tandai/lepas tanda sebuah pesan sebagai 'penting' (pinned).

    Pesan yang di-pin TIDAK akan ikut diringkas oleh summarization dan
    selalu dikirim utuh ke model setiap giliran, sehingga instruksi/aturan
    penting tidak hilang walau riwayat sudah diringkas.
    """
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE messages SET pinned = ? WHERE session_id = ? AND id = ?",
            (1 if pinned else 0, session_id, message_id),
        )


def get_pinned_messages(db_path: str, session_id: str):
    """Ambil semua pesan yang di-pin (pinned = 1) untuk sesi ini, urut by id."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? AND pinned = 1 ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_message(db_path: str, session_id: str, message_id: int):
    """Ambil satu pesan milik sesi ini, atau None kalau tidak ada."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? AND id = ?",
            (session_id, message_id),
        ).fetchone()
        return dict(row) if row else None


def get_all_messages(db_path: str, session_id: str):
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_messages_after(db_path: str, session_id: str, after_id: int):
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? AND id > ? ORDER BY id ASC",
            (session_id, after_id),
        ).fetchall()
        return [dict(r) for r in rows]


def get_last_user_message(db_path: str, session_id: str) -> dict:
    """Ambil pesan user chat TERAKHIR untuk sesi ini.

    Query terarah (ORDER BY id DESC LIMIT 1) -- jauh lebih ringan daripada
    get_all_messages() yang menarik seluruh riwayat. Dipakai untuk retrieval
    relevansi catatan proyek (query singkat) tanpa memuat semua pesan.
    """
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? AND role = 'user' "
            "AND kind = 'chat' ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return dict(row) if row else {}


def delete_messages_after(db_path: str, session_id: str, after_id: int) -> int:
    """Hapus SEMUA pesan dengan id > after_id pada sesi ini.

    Dipakai untuk `/undo` (batalkan giliran terakhir): hapus semua pesan
    (user prompt + assistant + tool calls) yang muncul SETELAH pesan user
    terakhir yang diinginkan. Mengembalikan jumlah baris yang dihapus.
    """
    with connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM messages WHERE session_id = ? AND id > ?",
            (session_id, after_id),
        )
        return cur.rowcount


def get_last_turn_span(db_path: str, session_id: str) -> dict:
    """Ambil rentang id pesan milik giliran (turn) TERAKHIR.

    Sebuah giliran dimulai oleh pesan user `kind='chat'` dan berisi semua
    pesan berikutnya (assistant, tool_call, tool_result) sampai sebelum
    pesan user berikutnya. Mengembalikan dict {"user_id": int, "start_id": int}
    atau {} bila tidak ada giliran user. start_id = id pesan user giliran itu.
    """
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM messages WHERE session_id = ? AND role = 'user' "
            "AND kind = 'chat' ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if not row:
            return {}
        return {"user_id": row["id"], "start_id": row["id"]}


def aggregate_token_usage(db_path: str, workdir: str = None, days: int = None) -> dict:
    """Agregasi pemakaian token lintas sesi dari kolom `meta` messages.

    `meta` berisi JSON {"token_estimate": int, "tool_name": str, ...} untuk
    setiap tool call. Fungsi ini menjumlahkan token_estimate per hari dan
    per tool, plus jumlah tool call & error, untuk workdir (atau semua sesi
    bila workdir None). Opsional `days` membatasi ke N hari terakhir.

    Mengembalikan dict: {"total_tokens", "tool_calls", "errors",
    "per_day": {YYYY-MM-DD: tokens}, "per_tool": {tool: count}}.
    """
    with connect(db_path) as conn:
        params = []
        where = ""
        if workdir:
            where = "WHERE s.workdir = ?"
            params.append(workdir)
        rows = conn.execute(
            "SELECT m.meta, m.created_at, s.workdir AS wd "
            f"FROM messages m JOIN sessions s ON s.id = m.session_id {where}",
            params,
        ).fetchall()
    import datetime as _dt
    total_tokens = 0
    tool_calls = 0
    errors = 0
    per_day = {}
    per_tool = {}
    cutoff = None
    if days:
        cutoff = time.time() - days * 86400
    for r in rows:
        if cutoff and r["created_at"] < cutoff:
            continue
        meta = {}
        if r["meta"]:
            try:
                meta = json.loads(r["meta"])
            except (ValueError, TypeError):
                meta = {}
        est = meta.get("token_estimate") or 0
        total_tokens += est
        if meta.get("tool_name"):
            tool_calls += 1
            per_tool[meta["tool_name"]] = per_tool.get(meta["tool_name"], 0) + 1
        if meta.get("is_error"):
            errors += 1
        day = _dt.datetime.fromtimestamp(r["created_at"]).strftime("%Y-%m-%d")
        per_day[day] = per_day.get(day, 0) + est
    return {
        "total_tokens": total_tokens,
        "tool_calls": tool_calls,
        "errors": errors,
        "per_day": dict(sorted(per_day.items(), reverse=True)),
        "per_tool": dict(sorted(per_tool.items(), key=lambda kv: -kv[1])),
    }


def search_messages(db_path: str, query: str, workdir: str = None,
                    limit: int = 20) -> list:
    """Cari pesan lintas sesi (cross-session memory search) memakai FTS5.

    Membuat tabel FTS virtual `messages_fts` yang menyalin konten pesan
    user/assistant dari SEMUA sesi di workdir yang sama. Query memakai
    FTS5 MATCH dengan fallback ke LIKE kalau query mengandung karakter
    yang tidak valid untuk FTS syntax.

    Mengembalikan daftar dict: {"session_id", "role", "content",
    "created_at", "session_title"}.
    """
    with connect(db_path) as conn:
        # Buat tabel FTS5 virtual (idempoten) kalau belum ada.
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts "
            "USING fts5(content, session_id UNINDEXED, role UNINDEXED, created_at UNINDEXED)"
        )
        # Sinkronkan: hapus semua lalu isi ulang dari messages (ringan untuk
        # volume sesi lokal; cukup untuk kebutuhan cross-session recall).
        conn.execute("DELETE FROM messages_fts")
        conn.execute(
            "INSERT INTO messages_fts (content, session_id, role, created_at) "
            "SELECT content, session_id, role, CAST(created_at AS TEXT) "
            "FROM messages WHERE role IN ('user', 'assistant') AND kind = 'chat'"
        )
        # Query FTS dengan escaping aman.
        safe = " ".join(
            f'"{t}"' for t in query.replace('"', " ").split() if t
        )
        try:
            rows = conn.execute(
                "SELECT m.id, m.session_id, m.role, m.content, m.created_at, "
                "       s.title AS session_title "
                "FROM messages_fts f "
                "JOIN messages m ON m.id = f.rowid "
                "LEFT JOIN sessions s ON s.id = f.session_id "
                "WHERE messages_fts MATCH ? "
                "ORDER BY bm25(messages_fts) ASC LIMIT ?",
                (safe, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            # FTS syntax error -> fallback LIKE scan.
            rows = conn.execute(
                "SELECT id, session_id, role, content, created_at, NULL AS session_title "
                "FROM messages WHERE role IN ('user', 'assistant') AND kind = 'chat' "
                "AND content LIKE ? ORDER BY id DESC LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
        return [dict(r) for r in rows]



def save_summary(db_path: str, session_id: str, upto_message_id: int, summary_text: str,
                 active_instructions: list = None):
    """Simpan ringkasan percakapan.

    `active_instructions` (opsional): daftar string instruksi aktif yang
    disalin verbatim oleh model summarize (ATURAN 1). Disimpan sebagai JSON
    array string di kolom `active_instructions` supaya bisa disuntikkan
    utuh ke context setiap giliran (lihat build_context_messages).
    """
    if active_instructions is None:
        active_instructions = []
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO summaries (session_id, upto_message_id, summary_text, "
            "active_instructions, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, upto_message_id, summary_text,
             json.dumps(active_instructions, ensure_ascii=False), time.time()),
        )


def get_latest_summary(db_path: str, session_id: str):
    """Ambil ringkasan terakhir, dengan kolom `active_instructions` di-parse
    dari JSON menjadi list string (fallback: [] kalau NULL/rusak)."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM summaries WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        raw = d.get("active_instructions")
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    d["active_instructions"] = [str(x) for x in parsed]
                else:
                    d["active_instructions"] = []
            except (ValueError, TypeError):
                d["active_instructions"] = []
        else:
            d["active_instructions"] = []
        return d



def replace_todos(db_path: str, workdir: str, items: list, session_id: str = None):
    """items: list of {"content": str, "status": str}. Full replace (mirip TodoWrite).

    Todo disimpan per WORKDIR (milik proyek), bukan per sesi, sehingga sesi
    baru di workdir yang sama tetap bisa mengakses todo pending. `workdir`
    adalah kunci utama; `session_id` (opsional) tetap dicatat untuk jejak
    asal dan backward-compat.

    Raises:
        ValueError: kalau `workdir` kosong/None, atau ada item yang bukan dict,
            tidak punya key "content", atau "content"-nya bukan string.
            Validasi di depan (sebelum menyentuh DB) membuat kontrak eksplisit
            dan kegagalan langsung jelas.

    `workdir` WAJIB: itu kunci isolasi antar proyek. Menulis dengan workdir
    kosong akan membuat todo "yatim" -- tersimpan di DB tapi tidak lagi
    terbaca proyek mana pun (karena semua pembacaan di-key oleh workdir),
    jadi lebih baik gagal keras di sini.

    Status tracking (`status_since`):
        Karena full replace menulis ulang SEMUA baris setiap giliran,
        `updated_at` selalu ikut berubah walau status item tidak berubah --
        sehingga tidak bisa dipakai untuk mengukur "sejak kapan item ini
        menggantung". `status_since` dipertahankan dari baris lama saat
        `(content, status)` SAMA, dan di-set ke `now` saat item baru muncul
        atau statusnya berubah. Itulah dasar deteksi todo basi.
    """
    # Isolasi antar proyek bertumpu pada workdir sebagai kunci. Menulis tanpa
    # workdir = menulis baris yang tidak akan pernah terbaca lagi.
    if not workdir or not str(workdir).strip():
        raise ValueError(
            "replace_todos() membutuhkan 'workdir' yang tidak kosong: todo "
            "disimpan per proyek (workdir), dan baris tanpa workdir tidak akan "
            "terbaca oleh proyek mana pun."
        )

    for i, item in enumerate(items):
        if not isinstance(item, dict) or "content" not in item or not isinstance(item["content"], str):
            raise ValueError(
                f"items[{i}] tidak valid untuk replace_todos(): harus dict dengan "
                f"key 'content' bertipe str. Diterima: {item!r}"
            )

    now = time.time()
    with connect(db_path) as conn:
        # Pastikan kolom yang dibutuhkan ada SEBELUM menulis. Tanpa ini, DB
        # lama yang belum lewat init_db() akan gagal keras
        # ("table todos has no column named status_since") dan todo-nya tidak
        # tersimpan sama sekali. Idempoten: cepat kalau kolom sudah ada.
        ensure_todos_columns(conn)
        # Snapshot baris lama SEBELUM delete untuk mempertahankan jejak waktu
        # (created_at & status_since) item yang tidak berubah.
        prev = {}
        try:
            rows = conn.execute(
                "SELECT content, status, created_at, status_since FROM todos "
                "WHERE workdir = ? ORDER BY position ASC",
                (workdir,),
            ).fetchall()
            for r in rows:
                prev.setdefault(r["content"], []).append(dict(r))
        except Exception:
            prev = {}

        conn.execute("DELETE FROM todos WHERE workdir = ?", (workdir,))
        for i, item in enumerate(items):
            status = item.get("status", "pending") or "pending"
            content = item["content"]
            created_at = now
            status_since = now
            # Cocokkan dengan baris lama ber-content sama (kalau ada lebih dari
            # satu baris identik, ambil yang paling depan / FIFO).
            bucket = prev.get(content)
            if bucket:
                old = bucket.pop(0)
                created_at = old.get("created_at") or now
                if old.get("status") == status:
                    # Status tidak berubah -> umur status diteruskan.
                    status_since = old.get("status_since") or old.get("created_at") or now
            conn.execute(
                "INSERT INTO todos (session_id, workdir, position, content, status, "
                "created_at, updated_at, status_since) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id or "", workdir, i, content, status, created_at, now, status_since),
            )


def get_todos(db_path: str, workdir: str = None, session_id: str = None):
    """Ambil todo MILIK SATU PROYEK (workdir). Prioritas: workdir.

    Kalau `workdir` diberikan, kembalikan todo untuk workdir itu (terlepas
    dari sesi mana yang menulisnya). Kalau hanya `session_id` (backward-compat),
    kembalikan todo yang ditulis sesi itu.

    KEDUANYA KOSONG -> kembalikan `[]`, BUKAN semua todo. Todo bersifat per
    workdir (sama seperti catatan proyek di `get_notes`); mengembalikan seluruh
    isi tabel akan membuat satu proyek membaca rencana proyek LAIN, dan itu
    persis kebocoran yang harus dicegah. Dulu fungsi ini mengembalikan semua
    baris saat tanpa scope -- perilaku itu dihapus.
    """
    if not workdir and not session_id:
        logger.warning(
            "get_todos() dipanggil tanpa workdir/session_id -> mengembalikan kosong "
            "(todo bersifat per-workdir; seluruh isi tabel tidak boleh dibocorkan)"
        )
        return []
    with connect(db_path) as conn:
        if workdir:
            rows = conn.execute(
                "SELECT * FROM todos WHERE workdir = ? ORDER BY position ASC", (workdir,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM todos WHERE session_id = ? ORDER BY position ASC", (session_id,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_pending_todos(db_path: str, workdir: str):
    """Todo yang masih pending/in_progress untuk sebuah workdir (lintas sesi).

    Dipakai untuk memberi tahu pengguna kalau ada rencana yang belum selesai
    di proyek yang sama, walau mereka masuk lewat sesi baru (tanpa --resume).
    """
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM todos WHERE workdir = ? AND status IN ('pending', 'in_progress') "
            "ORDER BY position ASC",
            (workdir,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_stale_todos(db_path: str, workdir: str, threshold_seconds: float):
    """Todo pending/in_progress yang statusnya sudah TIDAK berubah selama
    minimal `threshold_seconds` (lihat kolom `status_since`).

    Ini dasar deteksi todo BASI: item yang menggantung terlalu lama hampir
    selalu berarti model lupa menutupnya (menandai done) atau pekerjaannya
    ditinggalkan. Dikembalikan berurut dari yang PALING lama menggantung.
    """
    if not threshold_seconds or threshold_seconds <= 0:
        return []
    try:
        rows = get_pending_todos(db_path, workdir)
    except Exception:  # noqa: BLE001 - deteksi basi tidak boleh menggagalkan giliran
        return []
    now = time.time()
    stale = []
    for r in rows:
        since = r.get("status_since") or r.get("updated_at") or r.get("created_at") or 0
        r = dict(r)
        r["age_seconds"] = max(0.0, now - float(since or 0)) if since else 0.0
        if since and r["age_seconds"] >= threshold_seconds:
            stale.append(r)
    stale.sort(key=lambda x: x["age_seconds"], reverse=True)
    return stale



def set_note(db_path: str, workdir: str, key: str, value: str):
    now = time.time()
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO project_notes (workdir, key, value, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(workdir, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (workdir, key, value, now),
        )


def set_note_summary(db_path: str, workdir: str, key: str, summary: str):
    """Simpan ringkasan LLM untuk sebuah catatan (kolom `summary`).

    Catatan penuh (`value`) TIDAK diubah — ringkasan hanya disimpan sebagai
    tampilan terpotong untuk konteks, sehingga konteks penting yang coba
    dipertahankan oleh LLM tidak hilang, dan catatan asli tetap utuh di DB.
    """
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE project_notes SET summary = ?, updated_at = updated_at "
            "WHERE workdir = ? AND key = ?",
            (summary, workdir, key),
        )


def get_notes(db_path: str, workdir: str):
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM project_notes WHERE workdir = ? ORDER BY updated_at DESC", (workdir,)
        ).fetchall()
        return [dict(r) for r in rows]


def delete_note(db_path: str, workdir: str, key: str) -> bool:
    """Hapus satu catatan proyek. Return True kalau ada baris yang terhapus."""
    with connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM project_notes WHERE workdir = ? AND key = ?",
            (workdir, key),
        )
        return cur.rowcount > 0



def get_cached_outline(db_path: str, workdir: str, path: str, mtime: float, size: int):
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM file_cache WHERE workdir = ? AND path = ?", (workdir, path)
        ).fetchone()
        if row and row["mtime"] == mtime and row["size"] == size:
            return dict(row)
        return None


def set_cached_outline(db_path: str, workdir: str, path: str, mtime: float, size: int,
                        outline: str, lang: str = None):
    now = time.time()
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO file_cache (workdir, path, mtime, size, outline, lang, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(workdir, path) DO UPDATE SET mtime=excluded.mtime, size=excluded.size, "
            "outline=excluded.outline, lang=excluded.lang, updated_at=excluded.updated_at",
            (workdir, path, mtime, size, outline, lang, now),
        )


# ---------------------------------------------------------------------------
# Binding chat Telegram -> sesi Garwa (dipakai gateway Telegram)
# ---------------------------------------------------------------------------
def get_telegram_binding(db_path: str, chat_id: str):
    """Ambil binding chat_id -> session_id. Return dict atau None."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM telegram_bindings WHERE chat_id = ?", (str(chat_id),)
        ).fetchone()
        return dict(row) if row else None


def set_telegram_binding(db_path: str, chat_id: str, session_id: str):
    """Simpan (atau perbarui) binding chat_id -> session_id."""
    now = time.time()
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO telegram_bindings (chat_id, session_id, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET session_id=excluded.session_id, "
            "updated_at=excluded.updated_at",
            (str(chat_id), session_id, now),
        )


def delete_telegram_binding(db_path: str, chat_id: str) -> bool:
    """Hapus binding satu chat. Return True kalau ada baris terhapus."""
    with connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM telegram_bindings WHERE chat_id = ?", (str(chat_id),)
        )
        return cur.rowcount > 0