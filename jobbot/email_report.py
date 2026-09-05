"""jobbot/email_report.py - Laporan email lowongan via SMTP.

Setup (set env):
  JOB_EMAIL_USER, JOB_EMAIL_PASS (app password)
  JOB_EMAIL_RECIPIENT (tujuan)

Default: smtp.gmail.com:587
"""
import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .models import Job


class EmailReporter:
    def __init__(self, user=None, password=None, recipient=None,
                 smtp_host=None, smtp_port=None):
        self.user = user or os.environ.get("JOB_EMAIL_USER") or os.environ.get("EMAIL_USER")
        self.password = password or os.environ.get("JOB_EMAIL_PASS") or os.environ.get("EMAIL_PASS")
        self.recipient = recipient or os.environ.get("JOB_EMAIL_RECIPIENT") or os.environ.get("EMAIL_RECIPIENT")
        self.smtp_host = smtp_host or os.environ.get("JOB_EMAIL_SMTP") or "smtp.gmail.com"
        self.smtp_port = int(smtp_port or os.environ.get("JOB_EMAIL_SMTP_PORT") or "587")

    def _build_body(self, jobs, applied=0):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            "<h2>Daily Job Report</h2>",
            f"<p><b>{len(jobs)}</b> jobs found · <b>{applied}</b> applications sent</p>",
            "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse'>",
            "<tr><th>Platform</th><th>Title</th><th>Company</th><th>Location</th><th>Rate</th><th>Link</th></tr>",
        ]
        for j in jobs:
            rate = self._format_rate(j)
            lines.append(
                f"<tr><td>{j.platform}</td><td>{j.title or '?'}</td>"
                f"<td>{j.company or '?'}</td><td>{j.location or 'Remote'}</td>"
                f"<td>{rate}</td><td><a href='{j.url}'>View</a></td></tr>"
            )
        lines.append("</table>")
        lines.append(f"<p><i>Generated: {now}</i></p>")
        return "\\n".join(lines)

    def _format_rate(self, j):
        if j.rate_min and j.rate_max:
            return f"${j.rate_min}-{j.rate_max}/hr"
        if j.rate_min:
            return f"${j.rate_min}+/hr"
        if j.budget_min and j.budget_max:
            return f"${j.budget_min}-${j.budget_max}"
        return "Negotiable"

    def send(self, jobs, applied=0, subject=None):
        if not (self.user and self.password and self.recipient):
            print("[email] USER/PASS/RECIPIENT belum diset")
            return False
        subject = subject or f"Daily Job Report - {datetime.now(timezone.utc):%Y-%m-%d}"
        msg = MIMEMultipart()
        msg["From"] = self.user
        msg["To"] = self.recipient
        msg["Subject"] = subject
        body = self._build_body(jobs, applied)
        msg.attach(MIMEText(body, "html"))
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as s:
                s.starttls()
                s.login(self.user, self.password)
                s.send_message(msg)
            return True
        except Exception as e:
            print(f"[email] send failed -- {e}")
            return False
