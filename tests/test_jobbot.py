"""Test dasar untuk jobbot (db, models, scraper)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jobbot import db, models


def test_db_init():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        db.init_db(tmp.name)
        conn = db.get_conn(tmp.name)
        progress = models.get_progress(conn)
        assert progress["id"] == 1
        assert progress["jobs_scraped_total"] == 0
        conn.close()
    finally:
        os.unlink(tmp.name)


def test_job_upsert_dedup():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        db.init_db(tmp.name)
        conn = db.get_conn(tmp.name)
        job = models.Job(
            platform="test", job_id="1", title="Test Job",
            company="Acme", url="https://example.com",
        )
        models.upsert_job(conn, job)
        models.upsert_job(conn, job)  # dedup
        jobs = models.get_all_jobs(conn)
        assert len(jobs) == 1
        conn.close()
    finally:
        os.unlink(tmp.name)


def test_remoteok_scraper_parse():
    from jobbot.scraper import RemoteOKScraper
    s = RemoteOKScraper()
    item = {
        "id": "123", "position": "Python Developer",
        "company": "Acme", "location": "Remote",
    }
    job = s._parse(item)
    assert job.platform == "remote-ok"
    assert job.title == "Python Developer"
    assert job.company == "Acme"


if __name__ == "__main__":
    test_db_init()
    test_job_upsert_dedup()
    test_remoteok_scraper_parse()
    print("All jobbot tests passed")
