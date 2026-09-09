"""Jembatan (bridge) dari skill job-tracker ke fitur runtime Garwa.

Prinsip arsitektur (sesuai instruksi): Garwa adalah runner utama. Skill
job-tracker TIDAK boleh menduplikasi fitur yang sudah ada di Garwa. Modul
yang sebelumnya dobel (email_report, gmail, imap_inbox, telegram_bot, cron,
google_auth, google_drive) sudah dihapus. Fitur tersebut dipanggil lewat
modul ini:

  - Email/IMAP/Telegram/Cron  -> garwa.tools.comm_tools (tool_*)
  - Google Workspace          -> skill google-workspace (scripts/google_api.py)

DB skill TETAP terpisah dari DB runtime Garwa (lihat db.py / DB_PATH).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Lokasi skill google-workspace (relatif terhadap skill job-tracker ini).
# ---------------------------------------------------------------------------
_SKILLS_DIR = Path(__file__).resolve().parents[3]  # .../skills
_GWS_SCRIPT = _SKILLS_DIR / "google-workspace" / "scripts" / "google_api.py"


def _gws(*args: str) -> dict:
    """Jalankan CLI skill google-workspace dan parse output JSON baris terakhir."""
    if not _GWS_SCRIPT.exists():
        raise RuntimeError(
            f"skill google-workspace tidak ditemukan: {_GWS_SCRIPT}. "
            "Pastikan skills/google-workspace/scripts/google_api.py ada."
        )
    proc = subprocess.run(
        [sys.executable, str(_GWS_SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"google_api.py gagal ({proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    # Output bisa multi-baris; ambil objek JSON terakhir.
    for line in reversed(proc.stdout.strip().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"google_api.py tidak mengembalikan JSON: {proc.stdout}")


# ---------------------------------------------------------------------------
# Email / IMAP  (via garwa comm_tools)
# ---------------------------------------------------------------------------
def _comm_tools():
    """Import garwa.tools.comm_tools (lazy, agar jobbot bisa jalan standalone)."""
    from garwa.tools import comm_tools
    return comm_tools


def send_email(to: str, subject: str, body: str, html: bool = False) -> bool:
    """Kirim email via SMTP Garwa. Return True jika berhasil."""
    ct = _comm_tools()
    res = ct.tool_send_email(to=to, subject=subject, body=body, html=html)
    return "OK" in res and "ERROR" not in res


def list_unread(limit: int = 20) -> list:
    """Baca email belum dibaca via IMAP Garwa. Return list dict {num, from, subject, date}."""
    ct = _comm_tools()
    res = ct.tool_read_inbox(limit=limit)
    emails = []
    for line in res.splitlines():
        line = line.strip()
        # Format: #<num> | <date> | <from> | <subject>
        if not line.startswith("#"):
            continue
        parts = line.split(" | ", 3)
        if len(parts) < 4:
            continue
        num = parts[0].lstrip("#")
        emails.append({
            "num": num,
            "date": parts[1].strip(),
            "from": parts[2].strip(),
            "subject": parts[3].strip(),
        })
    return emails


def read_email(num) -> dict:
    """Baca isi lengkap satu email via IMAP Garwa. Return dict."""
    ct = _comm_tools()
    res = ct.tool_read_email(str(num))
    info = {"num": str(num), "from": "", "subject": "", "body": "", "date": ""}
    for line in res.splitlines():
        line = line.strip()
        if line.startswith("From:"):
            info["from"] = line[5:].strip()
        elif line.startswith("To:"):
            info["to"] = line[3:].strip()
        elif line.startswith("Subject:"):
            info["subject"] = line[8:].strip()
        elif line.startswith("Date:"):
            info["date"] = line[5:].strip()
        elif line.startswith("[read_email"):
            continue
        else:
            info["body"] += line + "\n"
    info["body"] = info["body"].strip()
    return info


def reply_email(num, body: str) -> bool:
    """Balas email via IMAP+SMTP Garwa. Return True jika berhasil."""
    ct = _comm_tools()
    res = ct.tool_reply_email(str(num), body)
    return "OK" in res and "ERROR" not in res


# ---------------------------------------------------------------------------
# Telegram  (via garwa comm_tools)
# ---------------------------------------------------------------------------
def send_telegram(text: str, chat_id: str = None) -> bool:
    """Kirim pesan Telegram via Garwa. Return True jika berhasil."""
    ct = _comm_tools()
    res = ct.tool_send_telegram(text=text, chat_id=chat_id)
    return "OK" in res and "ERROR" not in res


# ---------------------------------------------------------------------------
# Google Workspace  (via skill google-workspace CLI)
# ---------------------------------------------------------------------------
_SETUP_SCRIPT = _SKILLS_DIR / "google-workspace" / "scripts" / "setup.py"


def setup_oauth(check: bool = False) -> None:
    """Delegasi ke skill google-workspace (scripts/setup.py).

    check=True -> jalankan `setup.py --check` (cetak AUTHENTICATED / NOT_AUTHENTICATED).
    check=False -> jalankan `setup.py --auth-url` lalu pandu user tukar kode
    (alur multi-langkah, lihat SKILL.md google-workspace).
    """
    if not _SETUP_SCRIPT.exists():
        raise RuntimeError(f"skill google-workspace tidak ditemukan: {_SETUP_SCRIPT}")
    args = ["--check"] if check else ["--auth-url"]
    proc = subprocess.run(
        [sys.executable, str(_SETUP_SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=180,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    combined = f"{out}\n{err}".strip()
    # NOT_AUTHENTICATED adalah status yang wajar (belum setup), bukan error fatal.
    if proc.returncode != 0 and "NOT_AUTHENTICATED" not in combined:
        raise RuntimeError(f"setup.py gagal ({proc.returncode}): {err or out}")
    print(combined)


def create_drive_folder(name: str, parent_id: str = None) -> str:
    args = ["drive", "create-folder", name]
    if parent_id:
        args += ["--parent", parent_id]
    res = _gws(*args)
    return res.get("id", "")


def create_google_sheet(title: str, headers=None, folder_id: str = None) -> tuple:
    """Buat Google Sheet. Return (sheet_id, url).

    Catatan: CLI skill google-workspace tidak mendukung penempatan sheet ke
    folder saat create (folder hanya untuk Drive files). `folder_id` diabaikan
    untuk sheet; gunakan upload ke Drive bila perlu memindahkan.
    """
    args = ["sheets", "create", "--title", title]
    res = _gws(*args)
    sheet_id = res.get("spreadsheetId", "")
    url = res.get("spreadsheetUrl", "")
    if headers:
        values = json.dumps([headers])
        args2 = ["sheets", "update", sheet_id, "A1", "--values", values]
        _gws(*args2)
    return sheet_id, url


def append_google_sheet(sheet_id: str, range_name: str, rows) -> None:
    """Append rows (list of list) ke Google Sheet."""
    values = json.dumps(rows, ensure_ascii=False)
    args = ["sheets", "append", sheet_id, range_name, "--values", values]
    _gws(*args)


def create_google_doc(title: str, content: str = "", folder_id: str = None) -> str:
    """Buat Google Doc. Return doc_id."""
    args = ["docs", "create", "--title", title]
    if content:
        args += ["--body", content]
    res = _gws(*args)
    return res.get("documentId", "")


def upload_file_to_drive(local_path: str, folder_id: str = None, filename: str = None) -> str:
    """Upload file ke Drive. Return file_id."""
    args = ["drive", "upload", local_path]
    if filename:
        args += ["--name", filename]
    if folder_id:
        args += ["--parent", folder_id]
    res = _gws(*args)
    return res.get("id", "")


class EmailReporter:
    """Laporan email via SMTP Garwa (kompatibel dengan API email_report lama)."""

    def __init__(self, user=None, password=None, recipient=None,
                 smtp_host=None, smtp_port=None):
        self.user = user or os.environ.get("JOB_EMAIL_USER") or os.environ.get("EMAIL_USER")
        self.password = password or os.environ.get("JOB_EMAIL_PASS") or os.environ.get("EMAIL_PASS")
        self.recipient = recipient or os.environ.get("JOB_EMAIL_RECIPIENT") or os.environ.get("EMAIL_RECIPIENT")
        self.smtp_host = smtp_host or os.environ.get("JOB_EMAIL_SMTP") or "smtp.gmail.com"
        self.smtp_port = int(smtp_port or os.environ.get("JOB_EMAIL_SMTP_PORT") or "587")

    def _format_rate(self, j):
        if getattr(j, "rate_min", None) and getattr(j, "rate_max", None):
            return f"${j.rate_min}-{j.rate_max}/hr"
        if getattr(j, "rate_min", None):
            return f"${j.rate_min}+/hr"
        if getattr(j, "budget_min", None) and getattr(j, "budget_max", None):
            return f"${j.budget_min}-${j.budget_max}"
        return "Negotiable"

    def _build_body(self, jobs, applied=0):
        from datetime import datetime, timezone
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
                f"<td>{j.company or '?'}</td><td>{getattr(j, 'location', None) or 'Remote'}</td>"
                f"<td>{rate}</td><td><a href='{j.url}'>View</a></td></tr>"
            )
        lines.append("</table>")
        lines.append(f"<p><i>Generated: {now}</i></p>")
        return "\n".join(lines)

    def send(self, jobs, applied=0, subject=None):
        if not (self.user and self.password and self.recipient):
            print("[email] USER/PASS/RECIPIENT belum diset")
            return False
        from datetime import datetime, timezone
        subject = subject or f"Daily Job Report - {datetime.now(timezone.utc):%Y-%m-%d}"
        body = self._build_body(jobs, applied)
        return send_email(to=self.recipient, subject=subject, body=body, html=True)


# ---------------------------------------------------------------------------
# IMAP watch (polling + auto-reply). Fitur unik jobbot (tidak ada di Garwa).
# ---------------------------------------------------------------------------
def watch(interval: int = 60, reply_body: str = None, max_iterations: int = None,
          smart: bool = False) -> None:
    """Polling inbox via IMAP Garwa. Bila ada email baru, balas (opsional).

    - reply_body: jika diisi, balas semua email baru dengan teks tetap.
    - smart: jika True, pakai auto_reply.generate_reply() (deteksi intent + LLM).
    - max_iterations: None = infinite.
    """
    import time
    from . import auto_reply

    iteration = 0
    seen = set()
    print(f"[watch] IMAP watch started (interval={interval}s)")
    while max_iterations is None or iteration < max_iterations:
        try:
            emails = list_unread(limit=50)
            for e in emails:
                key = e["num"]
                if key in seen:
                    continue
                seen.add(key)
                if not (reply_body or smart):
                    print(f"[watch] email baru #{key} ({e['from']}): {e['subject']}")
                    continue
                if smart:
                    body, intent = auto_reply.generate_reply(e)
                    print(f"[watch] #{key} -> intent={intent}, balas {e['from']}")
                else:
                    body = reply_body
                    print(f"[watch] #{key} -> balas {e['from']} (fixed body)")
                ok = reply_email(key, body)
                print(f"[watch] balas #{key}: {'OK' if ok else 'GAGAL'}")
        except Exception as ex:
            print(f"[watch] error: {ex}")
        time.sleep(interval)
        iteration += 1
