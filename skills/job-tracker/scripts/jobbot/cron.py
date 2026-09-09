"""jobbot/cron.py - Cron scheduler harian untuk job scraper.

Mengadopsi pola hermes product-price-monitor: foreground collection sekali,
simpan state ke storage lokal, jalankan via cron tick. Di sini kita simpan
state ke SQLite (progress table) dan jalankan via cron.

Cara pakai:
  # Via system cron (disarankan), jalankan sekali per hari:
  0 9 * * * cd /path/to/garwa-coder-v2 && python -m jobbot.cli run

  # Atau via ticker internal (background loop):
  python -m jobbot.cli tick --interval 3600
"""
import time
from datetime import datetime, timezone

from . import db
from .models import get_progress, update_progress, application_count
from .scraper import scrape_all
from .reporter import TelegramReporter, format_daily_summary


# Keyword default untuk scraping (developer, designer, writer, web3)
DEFAULT_KEYWORDS = [
    "python developer",
    "javascript developer",
    "web developer",
    "frontend developer",
    "backend developer",
    "full stack developer",
    "ui ux designer",
    "graphic designer",
    "content writer",
    "technical writer",
    "web3 developer",
    "solidity developer",
    "blockchain developer",
    "mobile developer",
    "data scientist",
    "machine learning",
    "devops engineer",
    "php developer",
    "react developer",
    "node.js developer",
]


def run_once(keywords=None, platforms=None, limit=20):
    """Jalankan sekali scraping + report. Return dict statistik."""
    keywords = keywords or DEFAULT_KEYWORDS
    conn = db.get_conn()
    try:
        results = scrape_all(keywords, platforms, limit, conn=conn)
        total = sum(len(v) for v in results.values())
        applied = application_count(conn)

        # Report ke Telegram
        reporter = TelegramReporter()
        if reporter.token and reporter.channel_id:
            all_jobs = [j for v in results.values() for j in v]
            reporter.send_jobs_batch(all_jobs)
            reporter.send_message(format_daily_summary(all_jobs, applied))

        # Update progress
        update_progress(conn, last_run=datetime.now(timezone.utc).isoformat())
        return {
            "total": total,
            "platforms": list(results.keys()),
            "applied": applied,
        }
    finally:
        conn.close()


def tick(interval_seconds=3600, max_iterations=None):
    """Background ticker. Jalankan scraping setiap interval."""
    iteration = 0
    print(f"[cron] ticker started (interval={interval_seconds}s)")
    while max_iterations is None or iteration < max_iterations:
        try:
            stats = run_once()
            print(f"[cron] run #{iteration+1}: {stats}")
        except Exception as e:
            print(f"[cron] error: {e}")
        time.sleep(interval_seconds)
        iteration += 1


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Jobbot cron scheduler")
    parser.add_argument("--interval", type=int, default=3600,
                        help="Detik antar tick (default 3600)")
    parser.add_argument("--iterations", type=int, default=None,
                        help="Maksimal iterasi (default infinite)")
    args = parser.parse_args()
    tick(interval_seconds=args.interval, max_iterations=args.iterations)
