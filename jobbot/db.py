"""jobbot/db.py - Schema database untuk job scraper & reporter.

Mengadopsi pola SQLite hermes (satu file DB, schema fleksibel) yang sudah
dites. Menyimpan:
  - jobs        : daftar lowongan yang di-scrap dari berbagai platform
  - applications : riwayat lamaran yang dikirim
  - progress    : state & statistik harian untuk laporan & cron tick

Schema dibuat fleksibel (kolom opsional) agar scraper multi-platform bisa
menulis field yang berbeda-beda tanpa gagal.
"""
import os
import sqlite3
import threading
from datetime import datetime, timezone

DB_PATH = "jobbot/jobs.db"


def _load_dotenv() -> None:
    """Muat variabel dari .env di root proyek (jika ada) ke os.environ.

    Dipanggil sekali saat import. Tidak menimpa env yang sudah ada.
    Format: satu `KEY=value` per baris, baris '#'/kosong diabaikan.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(root, ".env")
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                os.environ.setdefault(k, v)
    except (FileNotFoundError, OSError):
        pass


_load_dotenv()


def get_env(key: str, default: str = None) -> str | None:
    """Ambil env var. Mendukung prefix JOB_ (JOB_GITHUB_TOKEN -> GITHUB_TOKEN)
    agar token bisa disimpan terpisah dari env global Garwa.
    """
    val = os.environ.get(key)
    if val is not None:
        return val
    prefixed = f"JOB_{key}"
    val = os.environ.get(prefixed)
    if val is not None:
        return val
    return default


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    job_id TEXT NOT NULL,
    title TEXT,
    company TEXT,
    location TEXT,
    rate_min REAL,
    rate_max REAL,
    rate_currency TEXT,
    budget_min REAL,
    budget_max REAL,
    description TEXT,
    url TEXT,
    posted_at TEXT,
    skills TEXT,
    category TEXT,
    job_type TEXT,
    is_remote INTEGER DEFAULT 1,
    raw_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(platform, job_id)
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    job_id TEXT NOT NULL,
    title TEXT,
    url TEXT,
    proposal_amount REAL,
    status TEXT DEFAULT 'sent',
    applied_at TEXT,
    feedback TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS progress (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_run TEXT,
    jobs_scraped_total INTEGER DEFAULT 0,
    applications_total INTEGER DEFAULT 0,
    earnings_usd_total REAL DEFAULT 0,
    last_day_scraped INTEGER DEFAULT 0,
    last_day_earnings_usd REAL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_earnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    amount REAL NOT NULL,
    source TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(date, source, note)
);

CREATE TABLE IF NOT EXISTS contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    job_id TEXT NOT NULL,
    title TEXT,
    company TEXT,
    url TEXT,
    rate REAL,
    rate_currency TEXT DEFAULT 'USD',
    budget REAL,
    deadline TEXT,
    status TEXT DEFAULT 'accepted',
    started_at TEXT,
    delivered_at TEXT,
    completed_at TEXT,
    notes TEXT,
    updated_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(platform, job_id)
);

CREATE TABLE IF NOT EXISTS deliverables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id INTEGER NOT NULL,
    name TEXT,
    path TEXT,
    description TEXT,
    version INTEGER DEFAULT 1,
    status TEXT DEFAULT 'submitted',
    submitted_at TEXT,
    feedback TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(contract_id) REFERENCES contracts(id)
);
"""


def get_conn(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Buka koneksi SQLite dengan foreign_keys & row_factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    """Inisialisasi schema (idempoten)."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_conn(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO progress (id, last_run, updated_at) "
            "VALUES (1, NULL, ?)",
            (now,),
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"[db] {DB_PATH} initialized")
