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
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager

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
    created_at  REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS summaries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL,
    upto_message_id     INTEGER NOT NULL,   -- messages dengan id <= ini sudah terangkum
    summary_text        TEXT NOT NULL,
    active_instructions TEXT,               -- JSON array string; instruksi aktif verbatim (ATURAN 1)
    created_at          REAL NOT NULL
);

-- CATATAN: `todos.session_id` SENGAJA tanpa FOREIGN KEY (beda dengan
-- `messages.session_id` di bawah) supaya todo tetap bisa dibaca walau baris
-- `sessions` terkait sudah dihapus. Kalau perilaku ini tidak diinginkan,
-- tambahkan FK yang sama seperti di `messages`.
CREATE TABLE IF NOT EXISTS todos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    position    INTEGER NOT NULL,
    content     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | in_progress | done | cancelled
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_todos_session ON todos(session_id, position);

CREATE TABLE IF NOT EXISTS project_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    workdir     TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    updated_at  REAL NOT NULL,
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
"""


@contextmanager
def connect(db_path: str = DEFAULT_DB_PATH):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    except Exception:

        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str = DEFAULT_DB_PATH):
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        # Migrasi ringan: DB lama (sebelum kolom `pinned` ada) tidak akan
        # mendapat kolom itu dari CREATE TABLE IF NOT EXISTS. Tambahkan
        # secara idempoten kalau belum ada.
        cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
        if "pinned" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")

        # Migrasi ringan: kolom `active_instructions` di tabel summaries
        # (menyimpan instruksi aktif verbatim hasil summarize sebagai JSON
        # array string). DB lama tidak akan mendapatnya dari CREATE TABLE
        # IF NOT EXISTS, jadi tambahkan secara idempoten kalau belum ada.
        scol = [r[1] for r in conn.execute("PRAGMA table_info(summaries)").fetchall()]
        if "active_instructions" not in scol:
            conn.execute("ALTER TABLE summaries ADD COLUMN active_instructions TEXT")



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



def add_message(db_path: str, session_id: str, role: str, content: str, kind: str = "chat") -> int:
    now = time.time()
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO messages (session_id, role, content, kind, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, kind, now),
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



def replace_todos(db_path: str, session_id: str, items: list):
    """items: list of {"content": str, "status": str}. Full replace (mirip TodoWrite).

    Raises:
        ValueError: kalau ada item yang bukan dict, tidak punya key
            "content", atau "content"-nya bukan string. Validasi di depan
            (sebelum menyentuh DB) membuat kontrak eksplisit dan kegagalan
            langsung jelas.
    """
    for i, item in enumerate(items):
        if not isinstance(item, dict) or "content" not in item or not isinstance(item["content"], str):
            raise ValueError(
                f"items[{i}] tidak valid untuk replace_todos(): harus dict dengan "
                f"key 'content' bertipe str. Diterima: {item!r}"
            )

    now = time.time()
    with connect(db_path) as conn:
        conn.execute("DELETE FROM todos WHERE session_id = ?", (session_id,))
        for i, item in enumerate(items):
            conn.execute(
                "INSERT INTO todos (session_id, position, content, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, i, item["content"], item.get("status", "pending"), now, now),
            )


def get_todos(db_path: str, session_id: str):
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM todos WHERE session_id = ? ORDER BY position ASC", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]



def set_note(db_path: str, workdir: str, key: str, value: str):
    now = time.time()
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO project_notes (workdir, key, value, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(workdir, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (workdir, key, value, now),
        )


def get_notes(db_path: str, workdir: str):
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM project_notes WHERE workdir = ? ORDER BY updated_at DESC", (workdir,)
        ).fetchall()
        return [dict(r) for r in rows]



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