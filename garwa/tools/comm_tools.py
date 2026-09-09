"""tools/comm_tools.py
Tool komunikasi & penjadwalan untuk Garwa: email (SMTP kirim + IMAP baca/balas),
Telegram (kirim pesan), dan cron/scheduling (jadwal tugas berulang).

Kredensial dibaca dari environment (prioritas env proses > file `.env` yang
dimuat oleh garwa.config). Prefiks yang didukung:
  - Email : GARWA_EMAIL_* | JOB_EMAIL_* | EMAIL_*
  - Telegram : GARWA_TELEGRAM_* | JOB_TELEGRAM_* | TELEGRAM_*

Semua tool bersifat "best-effort" dan mengembalikan string yang model-safe
(tidak melempar keluar). Koneksi gagal -> pesan error jelas, bukan crash.
"""
from __future__ import annotations

import email as email_mod
import json
import os
import smtplib
import time
from datetime import datetime, timezone
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime

from . import _state as state
from ._cron_expr import validate_cron_expr as _validate_cron_expr_strict
from .. import db as dbmod

try:
    from .. import config as config_mod
except ImportError:
    config_mod = None

try:
    import imaplib
except ImportError:
    imaplib = None


# ---------------------------------------------------------------------------
# Helpers konfigurasi (baca dari garwa.config yang sudah menangani env+.env)
# ---------------------------------------------------------------------------
def _get(name: str, default: str = "") -> str:
    """Baca nilai config dengan prioritas: env proses > modul config > default.

    Env proses MENANG atas nilai statis `config_mod` karena gateway Telegram
    meng-override `GARWA_TELEGRAM_CHAT_ID` per-turn via os.environ (lihat
    telegram_gateway._run_agent_turn_worker) supaya hasil agent (voice,
    send_document, send_telegram) selalu terkirim balik ke chat asal. Nilai
    `config_mod.TELEGRAM_CHAT_ID` di-freeze saat import (baris 357 config.py),
    jadi kalau diutamakan, override env per-turn akan diabaikan dan pesan
    nyasar ke channel default.
    """
    env = os.environ.get(name)
    if env and env.strip():
        return env.strip()
    if config_mod is not None:
        v = getattr(config_mod, name, None)
        if v:
            return str(v)
    return os.environ.get(name, default) or default


def _email_user() -> str:
    return _get("EMAIL_USER")


def _email_pass() -> str:
    return _get("EMAIL_PASS")


def _email_recipient() -> str:
    return _get("EMAIL_RECIPIENT")


def _smtp_host() -> str:
    return _get("EMAIL_SMTP_HOST") or "smtp.gmail.com"


def _smtp_port() -> int:
    try:
        return int(_get("EMAIL_SMTP_PORT") or 587)
    except (TypeError, ValueError):
        return 587


def _imap_host() -> str:
    return _get("EMAIL_IMAP_HOST") or "imap.gmail.com"


def _imap_port() -> int:
    try:
        return int(_get("EMAIL_IMAP_PORT") or 993)
    except (TypeError, ValueError):
        return 993


def _telegram_token() -> str:
    return _get("TELEGRAM_TOKEN")


def _telegram_chat_id() -> str:
    return _get("TELEGRAM_CHAT_ID")


# ---------------------------------------------------------------------------
# Email helpers
# ---------------------------------------------------------------------------
def _decode_mime_header(s: str) -> str:
    """Decode header MIME-encoded (RFC 2047)."""
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


def _extract_body(msg) -> str:
    """Ambil teks body (prioritas text/plain, fallback html)."""
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
                text = payload.decode(part.get_content_charset() or "utf-8", errors="replace") if payload else ""
            elif ctype == "text/html" and not html:
                payload = part.get_payload(decode=True)
                html = payload.decode(part.get_content_charset() or "utf-8", errors="replace") if payload else ""
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            if msg.get_content_type() == "text/html":
                html = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
            else:
                text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return text or html or ""


def tool_send_email(to: str = None, subject: str = "", body: str = "", html: bool = False) -> str:
    """Kirim email via SMTP (default smtp.gmail.com:587 + STARTTLS).

    `to` opsional: kalau kosong memakai EMAIL_RECIPIENT dari env/.env.
    """
    user = _email_user()
    password = _email_pass()
    recipient = (to or "").strip() or _email_recipient()
    if not (user and password and recipient):
        return ("[ERROR: send_email] Kredensial email belum diset. Set env "
                "GARWA_EMAIL_USER, GARWA_EMAIL_PASS, dan (opsional) GARWA_EMAIL_RECIPIENT "
                "atau isi `to`.")
    subject = subject or "(tanpa subjek)"
    msg = MIMEMultipart()
    msg["From"] = user
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html" if html else "plain", "utf-8"))

    host = _smtp_host()
    port = _smtp_port()
    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            s.login(user, password)
            s.send_message(msg)
        return f"[send_email] OK - terkirim ke {recipient} via {host}:{port}."
    except Exception as e:
        return f"[ERROR: send_email] Gagal kirim via {host}:{port}: {e}"


def tool_read_inbox(limit: int = 10) -> str:
    """Baca email masuk (belum dibaca) via IMAP. Return daftar ringkas."""
    if imaplib is None:
        return "[ERROR: read_inbox] Modul imaplib tidak tersedia."
    user = _email_user()
    password = _email_pass()
    if not (user and password):
        return "[ERROR: read_inbox] GARWA_EMAIL_USER/PASS belum diset."
    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 10

    host = _imap_host()
    port = _imap_port()
    try:
        conn = imaplib.IMAP4_SSL(host, port)
        conn.login(user, password)
    except Exception as e:
        return f"[ERROR: read_inbox] Gagal konek IMAP {host}:{port}: {e}"

    try:
        conn.select("INBOX")
        typ, data = conn.search(None, "UNSEEN")
        if typ != "OK":
            return "[read_inbox] Query UNSEEN gagal."
        ids = data[0].split()
        if not ids:
            return "[read_inbox] Tidak ada email belum dibaca."
        ids = list(reversed(ids))[:limit]
        lines = [f"[read_inbox] {len(ids)} email belum dibaca (terbaru dulu):"]
        for num in ids:
            try:
                typ2, d2 = conn.fetch(num, "(RFC822)")
                if typ2 != "OK" or not d2 or not d2[0]:
                    continue
                m = email_mod.message_from_bytes(d2[0][1])
                subj = _decode_mime_header(m.get("Subject", ""))
                frm = _decode_mime_header(m.get("From", ""))
                date_str = m.get("Date", "")
                try:
                    dt = parsedate_to_datetime(date_str)
                    when = dt.astimezone().strftime("%Y-%m-%d %H:%M")
                except Exception:
                    when = date_str or "?"
                lines.append(f"  #{num.decode()} | {when} | {frm} | {subj}")
            except Exception as e:
                lines.append(f"  #{num.decode()} | gagal baca: {e}")
        return "\n".join(lines)
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def tool_read_email(num: str) -> str:
    """Baca isi lengkap satu email (by sequence number, tanpa tandai dibaca)."""
    if imaplib is None:
        return "[ERROR: read_email] Modul imaplib tidak tersedia."
    user = _email_user()
    password = _email_pass()
    if not (user and password):
        return "[ERROR: read_email] GARWA_EMAIL_USER/PASS belum diset."
    num = str(num or "").strip()
    if not num:
        return "[ERROR: read_email] Nomor email wajib diisi."
    host = _imap_host()
    port = _imap_port()
    try:
        conn = imaplib.IMAP4_SSL(host, port)
        conn.login(user, password)
    except Exception as e:
        return f"[ERROR: read_email] Gagal konek IMAP: {e}"
    try:
        conn.select("INBOX")
        typ, data = conn.fetch(num.encode(), "(RFC822)")
        if typ != "OK" or not data or not data[0]:
            return f"[ERROR: read_email] Email #{num} tidak ditemukan."
        m = email_mod.message_from_bytes(data[0][1])
        return (
            f"[read_email #{num}]\n"
            f"From: {_decode_mime_header(m.get('From', ''))}\n"
            f"To: {_decode_mime_header(m.get('To', ''))}\n"
            f"Subject: {_decode_mime_header(m.get('Subject', ''))}\n"
            f"Date: {m.get('Date', '')}\n\n"
            f"{_extract_body(m)}"
        )
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def tool_reply_email(num: str, body: str) -> str:
    """Balas email masuk (baca via IMAP, kirim via SMTP)."""
    if imaplib is None:
        return "[ERROR: reply_email] Modul imaplib tidak tersedia."
    user = _email_user()
    password = _email_pass()
    if not (user and password):
        return "[ERROR: reply_email] GARWA_EMAIL_USER/PASS belum diset."
    num = str(num or "").strip()
    body = body or ""
    if not num or not body:
        return "[ERROR: reply_email] `num` dan `body` wajib diisi."

    host = _imap_host()
    port = _imap_port()
    try:
        conn = imaplib.IMAP4_SSL(host, port)
        conn.login(user, password)
    except Exception as e:
        return f"[ERROR: reply_email] Gagal konek IMAP: {e}"
    info = None
    try:
        conn.select("INBOX")
        typ, data = conn.fetch(num.encode(), "(RFC822)")
        if typ == "OK" and data and data[0]:
            orig = email_mod.message_from_bytes(data[0][1])
            info = {
                "from": _decode_mime_header(orig.get("From", "")),
                "subject": _decode_mime_header(orig.get("Subject", "")),
                "message_id": orig.get("Message-ID", ""),
            }
    except Exception as e:
        return f"[ERROR: reply_email] Gagal baca email #{num}: {e}"
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    if not info:
        return f"[ERROR: reply_email] Email #{num} tidak ditemukan."

    reply_to = info["from"]
    addr = reply_to
    if "<" in reply_to and ">" in reply_to:
        addr = reply_to[reply_to.find("<") + 1:reply_to.find(">")]
    subject = info["subject"]
    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject

    msg = email_mod.message.EmailMessage()
    msg["From"] = user
    msg["To"] = addr
    msg["Subject"] = subject
    if info.get("message_id"):
        msg["In-Reply-To"] = info["message_id"]
    msg.set_content(body)

    try:
        with smtplib.SMTP(_smtp_host(), _smtp_port(), timeout=30) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            s.login(user, password)
            s.send_message(msg)
        return f"[reply_email] OK - balasan ke {addr} (subjek: {subject})."
    except Exception as e:
        return f"[ERROR: reply_email] Gagal kirim balasan: {e}"


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
def _tg_api_url() -> str:
    return f"https://api.telegram.org/bot{_telegram_token()}"


def tool_send_telegram(text: str, chat_id: str = None) -> str:
    """Kirim pesan teks ke Telegram (Bot API). `chat_id` opsional (fallback env)."""
    token = _telegram_token()
    target = (chat_id or "").strip() or _telegram_chat_id()
    text = text or ""
    if not token or not target:
        return ("[ERROR: send_telegram] GARWA_TELEGRAM_TOKEN dan "
                "GARWA_TELEGRAM_CHAT_ID (atau `chat_id`) belum diset.")
    if not text.strip():
        return "[ERROR: send_telegram] `text` tidak boleh kosong."

    requests = _get_requests()
    if requests is None:
        return "[ERROR: send_telegram] pustaka 'requests' tidak tersedia."
    try:
        resp = requests.post(
            f"{_tg_api_url()}/sendMessage",
            # SENG AJA tanpa parse_mode: teks dari agent/cron sering mengandung
            # karakter HTML mentah (<path>, <file>, dll) yang bikin API 400
            # kalau parse_mode=HTML. Plain text paling aman untuk produksi --
            # konsisten dengan telegram_gateway.send_message().
            data={"chat_id": target, "text": text},
            timeout=30,
        )
        resp.raise_for_status()
        ok = resp.json().get("ok", False)
        return "[send_telegram] OK - pesan terkirim." if ok else f"[ERROR: send_telegram] respon tidak ok: {resp.text[:300]}"
    except Exception as e:
        return f"[ERROR: send_telegram] Gagal kirim: {e}"


# ---------------------------------------------------------------------------
# Cron / scheduling (jadwal tugas berulang, persisten di DB Garwa)
# ---------------------------------------------------------------------------
# Jadwal disimpan di tabel `scheduled_tasks` (kolom: id, name, schedule_expr,
# action, payload, enabled, last_run, created_at). `schedule_expr` memakai
# format cron 5-field: "minute hour day-of-month month day-of-week".
#
# Tool ini HANYA mengelola jadwal (CRUD). Eksekusi nyata butuh runner yang
# membaca tabel ini tiap menit: `python -m garwa.tools.cron_runner` atau via
# system cron. Lihat docstring modul di bagian bawah.

def _cron_table_sql() -> str:
    return """
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    schedule_expr TEXT NOT NULL,
    action        TEXT NOT NULL,           -- 'send_email' | 'send_telegram' | 'bash'
    payload       TEXT,                    -- JSON: {to, subject, body, text, chat_id, command, ...}
    enabled       INTEGER NOT NULL DEFAULT 1,
    last_run      REAL,
    created_at    REAL NOT NULL,
    running       INTEGER NOT NULL DEFAULT 0,   -- anti-double-run: 1 saat sedang dieksekusi
    claimed_at    REAL,                         -- timestamp claim (untuk deteksi stale)
    UNIQUE(name)
);
"""


def _ensure_cron_table(db_path: str) -> None:
    with dbmod.connect(db_path) as conn:
        conn.executescript(_cron_table_sql())
        # Migrasi ringan: DB lama (sebelum kolom `running`/`claimed_at` ada)
        # tidak akan mendapat kolom itu dari CREATE TABLE IF NOT EXISTS.
        cols = [r[1] for r in conn.execute("PRAGMA table_info(scheduled_tasks)").fetchall()]
        if "running" not in cols:
            conn.execute("ALTER TABLE scheduled_tasks ADD COLUMN running INTEGER NOT NULL DEFAULT 0")
        if "claimed_at" not in cols:
            conn.execute("ALTER TABLE scheduled_tasks ADD COLUMN claimed_at REAL")


def _cron_db_path() -> str:
    return getattr(state, "DB_PATH", None) or dbmod.DEFAULT_DB_PATH


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_cron_expr(expr: str) -> bool:
    """Validasi ketat format cron 5-field (delegasi ke _cron_expr)."""
    return _validate_cron_expr_strict(expr)


def tool_schedule_task(name: str, schedule_expr: str, action: str,
                       payload: dict = None) -> str:
    """Daftarkan jadwal tugas berulang (cron 5-field). Persisten di DB.

    action: 'send_email' | 'send_telegram' | 'bash'.
    payload: dict JSON tergantung action, mis. untuk send_email:
        {"to": "...", "subject": "...", "body": "..."}
        untuk send_telegram: {"text": "..."} atau {"text": "...", "chat_id": "..."}
        untuk bash: {"command": "..."}
    schedule_expr: "menit jam hari bulan hari_minggu" (mis. "0 9 * * *" = tiap 09:00).
    """
    name = str(name or "").strip()
    schedule_expr = str(schedule_expr or "").strip()
    action = str(action or "").strip().lower()
    if not name or not schedule_expr or not action:
        return "[ERROR: schedule_task] `name`, `schedule_expr`, dan `action` wajib diisi."
    if action not in ("send_email", "send_telegram", "bash"):
        return "[ERROR: schedule_task] action harus salah satu dari: send_email, send_telegram, bash."
    if not _validate_cron_expr(schedule_expr):
        return ("[ERROR: schedule_task] schedule_expr harus cron 5-field, mis. '0 9 * * *'. "
                f"Diterima: {schedule_expr!r}")

    payload_json = json.dumps(payload if isinstance(payload, dict) else {},
                              ensure_ascii=False)
    db_path = _cron_db_path()
    _ensure_cron_table(db_path)
    try:
        with dbmod.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO scheduled_tasks (name, schedule_expr, action, payload, enabled, created_at) "
                "VALUES (?, ?, ?, ?, 1, ?) "
                "ON CONFLICT(name) DO UPDATE SET schedule_expr=excluded.schedule_expr, "
                "action=excluded.action, payload=excluded.payload, enabled=1",
                (name, schedule_expr, action, payload_json, time.time()),
            )
        return f"[schedule_task] OK - '{name}' dijadwalkan ({schedule_expr}) aksi {action}."
    except Exception as e:
        return f"[ERROR: schedule_task] Gagal simpan jadwal: {e}"


def tool_list_schedules() -> str:
    """Tampilkan semua jadwal cron yang terdaftar."""
    db_path = _cron_db_path()
    _ensure_cron_table(db_path)
    try:
        with dbmod.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT id, name, schedule_expr, action, enabled, last_run FROM scheduled_tasks ORDER BY id"
            ).fetchall()
    except Exception as e:
        return f"[ERROR: list_schedules] Gagal baca: {e}"
    if not rows:
        return "[list_schedules] Belum ada jadwal terdaftar."
    lines = [f"[list_schedules] {len(rows)} jadwal:"]
    for r in rows:
        st = "aktif" if r["enabled"] else "nonaktif"
        last = ""
        if r["last_run"]:
            try:
                last = datetime.fromtimestamp(r["last_run"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            except Exception:
                last = str(r["last_run"])
        lines.append(
            f"  #{r['id']} {r['name']} | {r['schedule_expr']} | {r['action']} "
            f"| {st} | last: {last or '-'}"
        )
    return "\n".join(lines)


def tool_remove_schedule(name: str) -> str:
    """Hapus jadwal cron berdasarkan nama."""
    name = str(name or "").strip()
    if not name:
        return "[ERROR: remove_schedule] `name` wajib diisi."
    db_path = _cron_db_path()
    _ensure_cron_table(db_path)
    try:
        with dbmod.connect(db_path) as conn:
            cur = conn.execute("DELETE FROM scheduled_tasks WHERE name = ?", (name,))
        if cur.rowcount:
            return f"[remove_schedule] OK - '{name}' dihapus."
        return f"[remove_schedule] Jadwal '{name}' tidak ditemukan."
    except Exception as e:
        return f"[ERROR: remove_schedule] Gagal hapus: {e}"


def _set_schedule_enabled(name: str, enabled: int, verb: str) -> str:
    """Helper: set kolom `enabled` pada satu jadwal (1 = aktif, 0 = nonaktif)."""
    name = str(name or "").strip()
    if not name:
        return f"[ERROR: {verb}] `name` wajib diisi."
    db_path = _cron_db_path()
    _ensure_cron_table(db_path)
    try:
        with dbmod.connect(db_path) as conn:
            cur = conn.execute(
                "UPDATE scheduled_tasks SET enabled = ? WHERE name = ?",
                (enabled, name),
            )
        if cur.rowcount:
            label = "diaktifkan" if enabled else "dinonaktifkan"
            return f"[{verb}] OK - '{name}' {label}."
        return f"[ERROR: {verb}] Jadwal '{name}' tidak ditemukan."
    except Exception as e:
        return f"[ERROR: {verb}] Gagal ubah status: {e}"


def tool_enable_schedule(name: str) -> str:
    """Aktifkan kembali jadwal cron yang sebelumnya dinonaktifkan."""
    return _set_schedule_enabled(name, 1, "enable_schedule")


def tool_disable_schedule(name: str) -> str:
    """Nonaktifkan sementara jadwal cron (tanpa menghapusnya)."""
    return _set_schedule_enabled(name, 0, "disable_schedule")


# Lazy requests (hindari import berat saat modul di-load).
_requests = None


def _get_requests():
    global _requests
    if _requests is None:
        import requests
        _requests = requests
    return _requests


# ---------------------------------------------------------------------------
# Kirim file / audio ke Telegram (send_document, text_to_speech)
# ---------------------------------------------------------------------------
# `chat_id` default diambil dari env GARWA_TELEGRAM_CHAT_ID (konsisten dengan
# tool_send_telegram). Di gateway, chat_id asal di-set via env per-turn supaya
# hasil agent terkirim balik ke chat yang sama.
def _tg_send_multipart(method: str, chat_id: str, files: dict, caption: str = "") -> str:
    requests = _get_requests()
    token = _telegram_token()
    if not token or not chat_id:
        return f"[ERROR: {method}] GARWA_TELEGRAM_TOKEN dan chat_id belum diset."
    try:
        data = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption
        resp = requests.post(
            f"{_tg_api_url()}/{method}",
            data=data,
            files=files,
            timeout=120,
        )
        resp.raise_for_status()
        ok = resp.json().get("ok", False)
        return f"[{method}] OK." if ok else f"[ERROR: {method}] respon tidak ok: {resp.text[:300]}"
    except Exception as e:
        return f"[ERROR: {method}] Gagal kirim: {e}"


def _resolve_tg_target(chat_id: str) -> str:
    return (chat_id or "").strip() or _telegram_chat_id()


def tool_send_document(file_path: str, caption: str = "", chat_id: str = None) -> str:
    """Kirim satu file (PDF, teks, gambar, dsb) ke Telegram sebagai attachment.

    `file_path` wajib ada di disk. `caption` opsional. `chat_id` opsional
    (fallback env GARWA_TELEGRAM_CHAT_ID). Untuk mengirim beberapa file /
    proyek sekaligus, zip dulu lalu kirim zip-nya.
    """
    if not file_path:
        return "[ERROR: send_document] `file_path` tidak boleh kosong."
    if not os.path.isfile(file_path):
        return f"[ERROR: send_document] file tidak ditemukan: {file_path}"
    target = _resolve_tg_target(chat_id)
    if not target:
        return "[ERROR: send_document] chat_id tidak diset (env GARWA_TELEGRAM_CHAT_ID)."
    fname = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        return _tg_send_multipart(
            "sendDocument", target,
            {"document": (fname, f)},
            caption=caption,
        )


def tool_text_to_speech(text: str, output_path: str = "", voice: str = None,
                        chat_id: str = None) -> str:
    """Sintesis teks jadi audio (TTS) lalu kirim ke Telegram sebagai voice/audio.

    `output_path` opsional (default: file temp mp3). `voice` opsional (edge-tts).
    `chat_id` opsional (fallback env). Provider diatur via GARWA_TTS_PROVIDER.
    """
    text = (text or "").strip()
    if not text:
        return "[ERROR: text_to_speech] `text` tidak boleh kosong."
    target = _resolve_tg_target(chat_id)
    if not target:
        return "[ERROR: text_to_speech] chat_id tidak diset (env GARWA_TELEGRAM_CHAT_ID)."

    # Import lazy supaya gateway tetap jalan tanpa dependensi TTS.
    from .tts import text_to_speech as _tts

    if not output_path:
        output_path = os.path.join(
            os.environ.get("TMPDIR", "/tmp"), f"garwa_tts_{int(time.time())}.mp3"
        )
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    res = _tts(text, output_path, voice=voice)
    if not res.get("success"):
        return f"[ERROR: text_to_speech] {res.get('error', 'gagal')}"
    audio_path = res["path"]
    ext = os.path.splitext(audio_path)[1].lower()
    with open(audio_path, "rb") as f:
        # .ogg/.opus -> sendVoice (voice bubble); .mp3/.m4a -> sendAudio; else document.
        if ext in (".ogg", ".opus"):
            return _tg_send_multipart(
                "sendVoice", target, {"voice": (os.path.basename(audio_path), f)}
            )
        if ext in (".mp3", ".m4a"):
            return _tg_send_multipart(
                "sendAudio", target, {"audio": (os.path.basename(audio_path), f)}
            )
        return _tg_send_multipart(
            "sendDocument", target, {"document": (os.path.basename(audio_path), f)}
        )
