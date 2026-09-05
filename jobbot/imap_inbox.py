"""jobbot/imap_inbox.py - Baca & balas email masuk via IMAP (Gmail pribadi).

Ini MELENGKAPI email_report.py (SMTP, hanya kirim). Dengan IMAP, kita bisa:
  - list_unread()   : daftar email masuk yang belum dibaca
  - read_email(uid) : baca isi satu email (subject, from, body)
  - mark_read(uid)  : tandai sudah dibaca
  - reply_email(uid, body) : balas (baca via IMAP, kirim via SMTP)
  - watch(callback, interval) : polling realtime (bukan push, tapi tiap N detik)

Setup (sekali, manual di Gmail):
  1. Buka Gmail -> Settings (⚙️) -> See all settings -> Forwarding and POP/IMAP
  2. Di bagian "IMAP access", pilih "Enable IMAP", lalu Save Changes.

Kredensial: pakai App Password yang SAMA dengan SMTP (JOB_EMAIL_PASS).
  JOB_EMAIL_USER / JOB_EMAIL_PASS (app password) sudah ada di .env.

Default: imap.gmail.com:993 (SSL).
"""
import email
import os
import smtplib
import time
from datetime import datetime, timezone
from email.header import decode_header
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
from typing import Callable, Optional

import imaplib

from . import db  # memicu _load_dotenv() agar .env terbaca


IMAP_HOST_DEFAULT = "imap.gmail.com"
IMAP_PORT_DEFAULT = 993


def _decode_mime(s: str) -> str:
    """Decode header yang mungkin MIME-encoded (RFC 2047)."""
    if not s:
        return ""
    parts = decode_header(s)
    out = []
    for text, charset in parts:
        if isinstance(text, bytes):
            out.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _extract_body(msg: email.message.Message) -> str:
    """Ambil teks body dari pesan (prioritas text/plain, fallback html)."""
    text = ""
    html = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp:
                continue
            if ctype == "text/plain" and not text:
                payload = part.get_payload(decode=True)
                text = payload.decode(part.get_content_charset() or "utf-8",
                                      errors="replace") if payload else ""
            elif ctype == "text/html" and not html:
                payload = part.get_payload(decode=True)
                html = payload.decode(part.get_content_charset() or "utf-8",
                                      errors="replace") if payload else ""
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            if msg.get_content_type() == "text/html":
                html = payload.decode(msg.get_content_charset() or "utf-8",
                                      errors="replace")
            else:
                text = payload.decode(msg.get_content_charset() or "utf-8",
                                      errors="replace")
    return text or html or ""


class ImapInbox:
    def __init__(self, user=None, password=None,
                 imap_host=None, imap_port=None):
        self.user = user or os.environ.get("JOB_EMAIL_USER") or os.environ.get("EMAIL_USER")
        self.password = password or os.environ.get("JOB_EMAIL_PASS") or os.environ.get("EMAIL_PASS")
        self.imap_host = imap_host or os.environ.get("JOB_EMAIL_IMAP") or IMAP_HOST_DEFAULT
        self.imap_port = int(imap_port or os.environ.get("JOB_EMAIL_IMAP_PORT") or IMAP_PORT_DEFAULT)

    # ------------------------------------------------------------------ #
    # Koneksi
    # ------------------------------------------------------------------ #
    def _connect(self) -> imaplib.IMAP4_SSL:
        if not (self.user and self.password):
            raise RuntimeError("[imap] JOB_EMAIL_USER/PASS belum diset di .env")
        conn = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        conn.login(self.user, self.password)
        return conn

    # ------------------------------------------------------------------ #
    # Baca
    # ------------------------------------------------------------------ #
    def list_unread(self, limit: int = 20) -> list:
        """Return list dict email belum dibaca, urut terbaru dulu."""
        conn = self._connect()
        try:
            conn.select("INBOX")
            typ, data = conn.search(None, "UNSEEN")
            if typ != "OK":
                return []
            ids = data[0].split()
            if not ids:
                return []
            # Urutkan UID menurun (terbaru dulu), ambil `limit`
            ids = list(reversed(ids))[:limit]
            results = []
            for num in ids:
                info = self._fetch(conn, num)
                if info:
                    results.append(info)
            return results
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def _fetch(self, conn, num: bytes) -> Optional[dict]:
        """Fetch satu email by sequence number -> dict."""
        try:
            typ, data = conn.fetch(num, "(RFC822)")
            if typ != "OK" or not data or not data[0]:
                return None
            raw = data[0][1]
            msg = email.message_from_bytes(raw)
            subject = _decode_mime(msg.get("Subject", ""))
            from_ = _decode_mime(msg.get("From", ""))
            to_ = _decode_mime(msg.get("To", ""))
            date_str = msg.get("Date", "")
            try:
                dt = parsedate_to_datetime(date_str)
            except Exception:
                dt = datetime.now(timezone.utc)
            body = _extract_body(msg)
            return {
                "num": num.decode(),
                "subject": subject,
                "from": from_,
                "to": to_,
                "date": dt.isoformat(),
                "body": body,
            }
        except Exception as e:
            print(f"[imap] fetch {num} gagal -- {e}")
            return None

    def read_email(self, num) -> Optional[dict]:
        """Baca satu email (tanpa menandai dibaca)."""
        conn = self._connect()
        try:
            conn.select("INBOX")
            return self._fetch(conn, num.encode() if isinstance(num, str) else num)
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # Tandai
    # ------------------------------------------------------------------ #
    def mark_read(self, num) -> bool:
        conn = self._connect()
        try:
            conn.select("INBOX")
            typ, _ = conn.store(num, "+FLAGS", "\\Seen")
            return typ == "OK"
        except Exception as e:
            print(f"[imap] mark_read {num} gagal -- {e}")
            return False
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # Balas
    # ------------------------------------------------------------------ #
    def reply_email(self, num, body: str, subject_prefix: str = "Re: ") -> bool:
        """Balas email: baca via IMAP, kirim balasan via SMTP."""
        info = self.read_email(num)
        if not info:
            print("[imap] tidak bisa baca email untuk dibalas")
            return False
        reply_to = info["from"]
        # Ekstrak alamat email murni dari "Nama <email@x.com>"
        addr = reply_to
        if "<" in reply_to and ">" in reply_to:
            addr = reply_to[reply_to.find("<") + 1:reply_to.find(">")]
        subject = info["subject"]
        if not subject.lower().startswith("re:"):
            subject = subject_prefix + subject

        msg = email.message.EmailMessage()
        msg["From"] = self.user
        msg["To"] = addr
        msg["Subject"] = subject
        msg["In-Reply-To"] = info.get("message_id", "")
        msg.set_content(body)

        try:
            with smtplib.SMTP("smtp.gmail.com", 587) as s:
                s.starttls()
                s.login(self.user, self.password)
                s.send_message(msg)
            # Tandai sudah dibaca setelah dibalas
            self.mark_read(num)
            return True
        except Exception as e:
            print(f"[imap] reply gagal -- {e}")
            return False

    # ------------------------------------------------------------------ #
    # Watch (polling realtime)
    # ------------------------------------------------------------------ #
    def watch(self, callback: Callable[[dict], None],
              interval: int = 60, max_iterations: int = None) -> None:
        """Polling inbox tiap `interval` detik, panggil callback untuk tiap email baru.

        callback menerima dict hasil list_unread (satu email).
        Email yang sudah diproses callback ditandai dibaca.
        """
        print(f"[imap] watch mulai (interval={interval}s, "
              f"max_iterations={max_iterations or 'infinite'})")
        seen = set()
        it = 0
        while max_iterations is None or it < max_iterations:
            it += 1
            try:
                for info in self.list_unread(limit=50):
                    key = info["num"]
                    if key in seen:
                        continue
                    seen.add(key)
                    try:
                        callback(info)
                        # Tandai dibaca setelah callback sukses
                        self.mark_read(info["num"])
                    except Exception as e:
                        print(f"[imap] callback gagal -- {e}")
            except Exception as e:
                print(f"[imap] watch error -- {e}")
            time.sleep(interval)


def auto_reply_handler(imap: ImapInbox, reply_body: str):
    """Buat handler callback yang membalas setiap email masuk dengan teks tetap."""
    def handler(info: dict):
        print(f"[imap] email masuk dari {info['from']} — membalas...")
        ok = imap.reply_email(info["num"], reply_body)
        print(f"[imap] balas {'OK' if ok else 'GAGAL'}")
    return handler


def run_watch(interval: int = 60, reply_body: str = None,
              max_iterations: int = None, smart: bool = False) -> None:
    """Entrypoint: jalankan watch loop (dengan auto-reply opsional).

    smart=True -> pakai auto_reply cerdas (deteksi intent + balas kontekstual).
    reply_body -> balas dengan teks tetap (mengalahkan smart).
    """
    imap = ImapInbox()
    if reply_body:
        handler = auto_reply_handler(imap, reply_body)
    elif smart:
        from .auto_reply import make_auto_reply_callback
        handler = make_auto_reply_callback(imap)
    else:
        def handler(info: dict):
            print(f"[imap] email masuk: {info['from']} — {info['subject']}")
    imap.watch(handler, interval=interval, max_iterations=max_iterations)
