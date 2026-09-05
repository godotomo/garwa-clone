"""jobbot/reporter.py - Telegram channel reporter.

Mengirim lowongan baru ke Telegram channel/group via Bot API.
Setup:
  - Buat bot via @BotFather -> dapatkan TOKEN
  - Tambahkan bot ke channel -> dapatkan CHANNEL_ID (mis. @channel atau -100... )
  - Set env: JOB_TELEGRAM_TOKEN, JOB_TELEGRAM_CHANNEL_ID
"""
import os
import time
from typing import Optional

import requests

from . import db  # memicu _load_dotenv() agar .env terbaca
from .models import Job


class TelegramReporter:
    def __init__(self, token: str = None, channel_id: str = None,
                 chat_id: str = None):
        self.token = token or os.environ.get("JOB_TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
        self.channel_id = (channel_id or os.environ.get("JOB_TELEGRAM_CHANNEL_ID")
                          or os.environ.get("TELEGRAM_CHANNEL_ID"))
        self.api_url = f"https://api.telegram.org/bot{self.token}"

    def send_message(self, text: str, chat_id: str = None,
                     max_retries: int = 3) -> bool:
        """Kirim pesan ke Telegram dengan retry + handling 429.

        Telegram membatasi ~30 pesan/det per bot. Bila kena 429
        (Too Many Requests), response body JSON berisi 'retry_after'
        (detik) — tunda lalu coba lagi.
        """
        chat_id = chat_id or self.channel_id
        if not self.token or not chat_id:
            print("[telegram] TOKEN/CHANNEL_ID belum diset")
            return False

        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    f"{self.api_url}/sendMessage",
                    data=payload,
                    timeout=30,
                )

                # 429 Too Many Requests: retry dengan retry_after.
                if resp.status_code == 429:
                    retry_after = 5
                    try:
                        retry_after = int(resp.json().get("retry_after", 5))
                    except (ValueError, TypeError):
                        pass
                    wait = min(max(retry_after, 1), 60)
                    print(f"[telegram] 429 rate limit (attempt {attempt+1}/{max_retries}), "
                          f"retry in {wait}s")
                    time.sleep(wait)
                    continue

                # 500/502/503/504: transient server error, retry singkat.
                if resp.status_code in (500, 502, 503, 504):
                    print(f"[telegram] server error {resp.status_code} (attempt {attempt+1}/{max_retries}), "
                          f"retry in 3s")
                    time.sleep(3)
                    continue

                resp.raise_for_status()
                return resp.json().get("ok", False)
            except requests.RequestException as e:
                print(f"[telegram] send failed (attempt {attempt+1}/{max_retries}): {e}")
                time.sleep(3)

        print("[telegram] send failed setelah retry")
        return False

    def send_job(self, job: Job) -> bool:
        title = job.title or "(tanpa judul)"
        company = job.company or "?"
        location = job.location or "Remote"
        rate = self._format_rate(job)
        posted = self._format_posted(job.posted_at)
        skills = f" · Skills: {job.skills}" if job.skills else ""
        text = (
            f"<b>🚀 NEW JOB</b>\n\n"
            f"<b>{title}</b>\n"
            f"🏢 {company}\n"
            f"📍 {location}\n"
            f"💰 {rate}\n"
            f"🕐 {posted}\n"
            f"{skills}\n\n"
            f"🔗 {job.url}\n\n"
            f"<i>Platform: {job.platform}</i>"
        )
        return self.send_message(text)

    def _format_posted(self, posted) -> str:
        """Normalisasi posted_at (bisa str ISO, int epoch, atau None)."""
        if not posted:
            return ""
        if isinstance(posted, (int, float)):
            try:
                from datetime import datetime, timezone
                return datetime.fromtimestamp(posted, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            except (ValueError, OSError):
                return str(posted)
        return str(posted)[:16]

    def send_jobs_batch(self, jobs: list[Job]) -> int:
        sent = 0
        for job in jobs:
            if self.send_job(job):
                sent += 1
            time.sleep(1)  # hindari rate limit
        return sent

    def _format_rate(self, job: Job) -> str:
        if job.rate_min and job.rate_max:
            return f"${job.rate_min}-{job.rate_max}/hr"
        if job.rate_min:
            return f"${job.rate_min}+/hr"
        if job.budget_min and job.budget_max:
            return f"${job.budget_min}-${job.budget_max}"
        if job.budget_min:
            return f"${job.budget_min}+"
        return "Negotiable"


def format_daily_summary(jobs: list[Job], applied: int = 0) -> str:
    total = len(jobs)
    platforms = sorted(set(j.platform for j in jobs))
    text = (
        f"<b>📊 DAILY JOB SUMMARY</b>\n\n"
        f"🔍 {total} jobs found\n"
        f"📤 {applied} applications sent\n"
        f"🌐 Platforms: {', '.join(platforms)}\n\n"
        f"<i>Scraped: {time.strftime('%Y-%m-%d %H:%M UTC')}</i>"
    )
    return text


def report_new_jobs(jobs: list[Job], reporter: TelegramReporter) -> int:
    return reporter.send_jobs_batch(jobs)
