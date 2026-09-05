"""jobbot/models.py - Model & operasi CRUD untuk schema database.

Mengadopsi pola hermes product-price-monitor: simpan state ke storage lokal
(JSON/SQLite), dedup via unique key, simpan statistik harian. Di sini state
disimpan ke SQLite (jobs, applications, progress).
"""
from datetime import datetime, timezone
from typing import Optional

from . import db


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Job:
    """Representasi satu lowongan freelance."""

    def __init__(self, platform, job_id, title=None, company=None,
                 location=None, rate_min=None, rate_max=None,
                 rate_currency=None, budget_min=None, budget_max=None,
                 description=None, url=None, posted_at=None, skills=None,
                 category=None, job_type=None, is_remote=True, raw_json=None):
        self.platform = platform
        self.job_id = str(job_id)
        self.title = title
        self.company = company
        self.location = location
        self.rate_min = rate_min
        self.rate_max = rate_max
        self.rate_currency = rate_currency or "USD"
        self.budget_min = budget_min
        self.budget_max = budget_max
        self.description = description
        self.url = url
        self.posted_at = posted_at
        self.skills = skills
        self.category = category
        self.job_type = job_type
        self.is_remote = 1 if is_remote else 0
        self.raw_json = raw_json

    def to_row(self) -> dict:
        return {
            "platform": self.platform,
            "job_id": self.job_id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "rate_min": self.rate_min,
            "rate_max": self.rate_max,
            "rate_currency": self.rate_currency,
            "budget_min": self.budget_min,
            "budget_max": self.budget_max,
            "description": self.description,
            "url": self.url,
            "posted_at": self.posted_at,
            "skills": ",".join(self.skills) if isinstance(self.skills, list) else self.skills,
            "category": self.category,
            "job_type": self.job_type,
            "is_remote": self.is_remote,
            "raw_json": self.raw_json,
            "created_at": now_iso(),
        }


def upsert_job(conn, job: Job) -> bool:
    """Simpan atau update lowongan. Return True kalau job baru (belum ada)."""
    row = job.to_row()
    conn.execute(
        """
        INSERT INTO jobs (platform, job_id, title, company, location,
                          rate_min, rate_max, rate_currency, budget_min,
                          budget_max, description, url, posted_at, skills,
                          category, job_type, is_remote, raw_json, created_at)
        VALUES (:platform, :job_id, :title, :company, :location,
                :rate_min, :rate_max, :rate_currency, :budget_min,
                :budget_max, :description, :url, :posted_at, :skills,
                :category, :job_type, :is_remote, :raw_json, :created_at)
        ON CONFLICT(platform, job_id) DO UPDATE SET
            title=excluded.title, company=excluded.company,
            location=excluded.location, rate_min=excluded.rate_min,
            rate_max=excluded.rate_max, budget_min=excluded.budget_min,
            budget_max=excluded.budget_max, description=excluded.description,
            url=excluded.url, posted_at=excluded.posted_at,
            skills=excluded.skills, category=excluded.category,
            job_type=excluded.job_type, is_remote=excluded.is_remote
        """,
        row,
    )
    conn.commit()
    return True


def get_all_jobs(conn) -> list[dict]:
    cur = conn.execute(
        "SELECT * FROM jobs ORDER BY (posted_at IS NULL), posted_at DESC"
    )
    return [dict(r) for r in cur.fetchall()]


def get_new_jobs(conn, platform=None) -> list[dict]:
    """Ambil job yang posted_at >= 24 jam lalu? Tidak - ambil yang belum pernah"""
    # Kita tandai job baru lewat created_at hari ini.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if platform:
        cur = conn.execute(
            "SELECT * FROM jobs WHERE platform=? AND created_at LIKE ? ORDER BY posted_at DESC",
            (platform, f"{today}%"),
        )
    else:
        cur = conn.execute(
            "SELECT * FROM jobs WHERE created_at LIKE ? ORDER BY posted_at DESC",
            (f"{today}%",),
        )
    return [dict(r) for r in cur.fetchall()]


def application_count(conn) -> int:
    cur = conn.execute("SELECT COUNT(*) AS c FROM applications")
    return cur.fetchone()["c"]


def add_application(conn, app: dict) -> None:
    conn.execute(
        """
        INSERT INTO applications (platform, job_id, title, url,
                                  proposal_amount, status, applied_at, feedback, created_at)
        VALUES (:platform, :job_id, :title, :url, :proposal_amount,
                :status, :applied_at, :feedback, :created_at)
        """,
        {**app, "created_at": now_iso()},
    )
    conn.commit()


def update_progress(conn, **fields) -> None:
    now = now_iso()
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(
        f"UPDATE progress SET {sets}, updated_at=? WHERE id=1",
        [*fields.values(), now],
    )
    conn.commit()


def get_progress(conn) -> dict:
    cur = conn.execute("SELECT * FROM progress WHERE id=1")
    return dict(cur.fetchone())


def increment_scraped(conn, n: int = 1) -> None:
    conn.execute(
        "UPDATE progress SET jobs_scraped_total = jobs_scraped_total + ?, updated_at=? WHERE id=1",
        (n, now_iso()),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Earnings tracking
# ---------------------------------------------------------------------------

TARGET_DAILY_USD = 50.0


def add_earning(conn, amount: float, date: str = None, source: str = None,
                note: str = None) -> None:
    """Catat satu pendapatan. Update progress total & harian."""
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn.execute(
        """
        INSERT INTO daily_earnings (date, amount, source, note, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (date, amount, source, note, now_iso()),
    )
    # Update progress
    conn.execute(
        "UPDATE progress SET earnings_usd_total = earnings_usd_total + ?, updated_at=? WHERE id=1",
        (amount, now_iso()),
    )
    if date == datetime.now(timezone.utc).strftime("%Y-%m-%d"):
        conn.execute(
            "UPDATE progress SET last_day_earnings_usd = last_day_earnings_usd + ?, updated_at=? WHERE id=1",
            (amount, now_iso()),
        )
    conn.commit()


def get_earnings(conn, date: str = None) -> list[dict]:
    """Ambil daftar pendapatan. Kalau date kosong, ambil semua."""
    if date:
        cur = conn.execute(
            "SELECT * FROM daily_earnings WHERE date=? ORDER BY created_at DESC",
            (date,),
        )
    else:
        cur = conn.execute(
            "SELECT * FROM daily_earnings ORDER BY date DESC, created_at DESC"
        )
    return [dict(r) for r in cur.fetchall()]


def get_earnings_summary(conn) -> dict:
    """Ringkasan pendapatan: total, hari ini, target, persentase."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    total = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS t FROM daily_earnings"
    ).fetchone()["t"]
    today_total = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS t FROM daily_earnings WHERE date=?",
        (today,),
    ).fetchone()["t"]
    return {
        "total_usd": total,
        "today_usd": today_total,
        "target_daily_usd": TARGET_DAILY_USD,
        "today_pct": round(today_total / TARGET_DAILY_USD * 100, 1) if TARGET_DAILY_USD else 0,
        "remaining_today": max(0.0, TARGET_DAILY_USD - today_total),
    }


# ---------------------------------------------------------------------------
# High-value job filtering
# ---------------------------------------------------------------------------

def _job_value(job: dict) -> float:
    """Estimasi 'nilai' sebuah job dalam USD.

    Prioritas: budget (total proyek) > rate (per jam). Return 0 kalau tidak
    ada info gaji/budget sama sekali.
    """
    budget = job.get("budget_min") or job.get("budget_max")
    if budget:
        return float(budget)
    rate = job.get("rate_min") or job.get("rate_max")
    if rate:
        return float(rate)
    return 0.0


def get_high_value_jobs(conn, min_budget: float = 0.0,
                        min_rate: float = 0.0, limit: int = 50) -> list[dict]:
    """Ambil job bernilai tinggi, diurutkan dari nilai tertinggi.

    - min_budget: filter total budget proyek >= nilai ini (USD)
    - min_rate:   filter rate per jam >= nilai ini (USD)
    Job yang memenuhi salah satu kriteria akan masuk, lalu diurutkan menurun
    berdasarkan estimasi nilai.
    """
    jobs = get_all_jobs(conn)
    filtered = []
    for j in jobs:
        budget = j.get("budget_min") or j.get("budget_max")
        rate = j.get("rate_min") or j.get("rate_max")
        if min_budget and budget and float(budget) >= min_budget:
            filtered.append(j)
        elif min_rate and rate and float(rate) >= min_rate:
            filtered.append(j)
        elif not min_budget and not min_rate:
            # tanpa filter, ambil semua yang punya info nilai
            if budget or rate:
                filtered.append(j)
    filtered.sort(key=_job_value, reverse=True)
    return filtered[:limit]