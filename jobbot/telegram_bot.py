"""jobbot/telegram_bot.py - Bot Telegram dua arah (menerima file & perintah).

Bot ini MELENGKAPI reporter.py yang hanya satu arah (kirim laporan).
Dengan bot ini, user bisa:
  - Mengirim file (JSON, gambar, dokumen, dll) -> otomatis tersimpan ke filesystem
  - Mengirim perintah singkat -> dijalankan (autopilot, status, laporan, dll)

Menggunakan Telegram Bot API + long polling (getUpdates), tanpa library eksternal
selain `requests` (sudah dipakai reporter.py).

Setup:
  - Token bot sama dengan JOB_TELEGRAM_TOKEN (dari @BotFather)
  - Opsional set JOB_TELEGRAM_ADMIN_ID (chat_id user) agar hanya user tertentu
    yang boleh memberi perintah. Kosongkan untuk menerima semua.

Menjalankan:
  python -m jobbot.cli bot            # polling sekali
  python -m jobbot.cli bot --forever  # polling terus (long-running)
"""
import os
import time
from typing import Optional

import requests

from . import db  # memicu _load_dotenv() agar .env terbaca


# Direktori tempat file yang dikirim user disimpan.
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "inbox")


def _ensure_upload_dir() -> str:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    return UPLOAD_DIR


class TelegramBot:
    def __init__(self, token: str = None, admin_id: str = None):
        self.token = (token or os.environ.get("JOB_TELEGRAM_TOKEN")
                      or os.environ.get("TELEGRAM_TOKEN"))
        self.admin_id = (admin_id or os.environ.get("JOB_TELEGRAM_ADMIN_ID")
                         or os.environ.get("TELEGRAM_ADMIN_ID"))
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self._offset = 0

    # ------------------------------------------------------------------ #
    # API primitives
    # ------------------------------------------------------------------ #
    def _call(self, method: str, **params) -> Optional[dict]:
        if not self.token:
            print("[bot] TOKEN belum diset (JOB_TELEGRAM_TOKEN)")
            return None
        try:
            resp = requests.post(f"{self.api_url}/{method}",
                                 data=params, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            print(f"[bot] {method} failed -- {e}")
            return None

    def get_updates(self, timeout: int = 30) -> list:
        data = self._call("getUpdates", offset=self._offset,
                          timeout=timeout, allowed_updates='["message"]')
        if not data or not data.get("ok"):
            return []
        updates = data.get("result", [])
        if updates:
            self._offset = updates[-1]["update_id"] + 1
        return updates

    def send_message(self, chat_id, text: str, reply_to: int = None) -> bool:
        params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_to:
            params["reply_to_message_id"] = reply_to
        data = self._call("sendMessage", **params)
        return bool(data and data.get("ok"))

    def download_file(self, file_id: str, dest_path: str) -> bool:
        """Download file via getFile -> file_path, simpan ke dest_path."""
        data = self._call("getFile", file_id=file_id)
        if not data or not data.get("ok"):
            print("[bot] getFile gagal")
            return False
        file_path = data["result"].get("file_path")
        if not file_path:
            print("[bot] file_path kosong")
            return False
        url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        try:
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            with open(dest_path, "wb") as f:
                f.write(r.content)
            return True
        except requests.RequestException as e:
            print(f"[bot] download gagal -- {e}")
            return False

    # ------------------------------------------------------------------ #
    # Authorization
    # ------------------------------------------------------------------ #
    def _allowed(self, chat_id) -> bool:
        if not self.admin_id:
            return True
        return str(chat_id) == str(self.admin_id)

    # ------------------------------------------------------------------ #
    # Message handlers
    # ------------------------------------------------------------------ #
    def handle_message(self, msg: dict) -> None:
        chat_id = msg["chat"]["id"]
        msg_id = msg.get("message_id")

        if not self._allowed(chat_id):
            self.send_message(chat_id, "⛔ Akses ditolak. Anda bukan admin.",
                              reply_to=msg_id)
            return

        # --- File terkirim ---
        if msg.get("document"):
            self._handle_document(chat_id, msg_id, msg["document"])
            return
        if msg.get("photo"):
            # Ambil foto resolusi tertinggi
            photo = msg["photo"][-1]
            self._handle_file(chat_id, msg_id, photo["file_id"],
                              "photo.jpg", "gambar")
            return

        # --- Teks / perintah ---
        text = (msg.get("text") or "").strip()
        if not text:
            self.send_message(chat_id, "❓ Pesan kosong.", reply_to=msg_id)
            return
        self._handle_command(chat_id, msg_id, text)

    def _handle_document(self, chat_id, msg_id, doc: dict) -> None:
        file_id = doc.get("file_id")
        filename = doc.get("file_name") or "file.bin"
        # Sanitasi nama file (hindari path traversal)
        filename = os.path.basename(filename)
        dest = os.path.join(_ensure_upload_dir(), filename)
        if self.download_file(file_id, dest):
            size = os.path.getsize(dest)
            self.send_message(
                chat_id,
                f"✅ File diterima: <code>{filename}</code> ({size} bytes)\n"
                f"Tersimpan di <code>inbox/{filename}</code>",
                reply_to=msg_id,
            )
        else:
            self.send_message(chat_id, "❌ Gagal mengunduh file.",
                              reply_to=msg_id)

    def _handle_file(self, chat_id, msg_id, file_id, filename, label) -> None:
        dest = os.path.join(_ensure_upload_dir(), filename)
        if self.download_file(file_id, dest):
            size = os.path.getsize(dest)
            self.send_message(
                chat_id,
                f"✅ {label.capitalize()} diterima: <code>{filename}</code> "
                f"({size} bytes)",
                reply_to=msg_id,
            )
        else:
            self.send_message(chat_id, f"❌ Gagal mengunduh {label}.",
                              reply_to=msg_id)

    def _handle_command(self, chat_id, msg_id, text: str) -> None:
        cmd = text.lower().split()[0]
        reply = None

        if cmd in ("/start", "/help", "help"):
            reply = self._help_text()
        elif cmd in ("/status", "status"):
            reply = self._cmd_status()
        elif cmd in ("/autopilot", "autopilot", "jalankan autopilot"):
            reply = self._cmd_autopilot()
        elif cmd in ("/report", "report", "kirim laporan"):
            reply = self._cmd_report()
        elif cmd in ("/earnings", "earnings"):
            reply = self._cmd_earnings()
        elif cmd in ("/files", "files", "daftar file"):
            reply = self._cmd_files()
        elif cmd in ("/inbox", "inbox", "cek email", "email masuk"):
            reply = self._cmd_inbox()
        elif cmd in ("/reply", "reply"):
            reply = self._cmd_reply(text)
        else:
            reply = ("❓ Perintah tidak dikenal.\n\n" + self._help_text())

        self.send_message(chat_id, reply, reply_to=msg_id)

    # ------------------------------------------------------------------ #
    # Command implementations
    # ------------------------------------------------------------------ #
    def _help_text(self) -> str:
        return (
            "<b>🤖 Jobbot Bot — Perintah tersedia</b>\n\n"
            "📎 <b>Kirim file</b> (JSON/gambar/dokumen) untuk menyimpannya\n"
            "   ke <code>inbox/</code> di filesystem.\n\n"
            "<b>Perintah:</b>\n"
            "/status — statistik & earnings\n"
            "/autopilot — jalankan pipeline autonomous\n"
            "/report — kirim laporan ke channel\n"
            "/earnings — ringkasan pendapatan\n"
            "/files — daftar file di inbox\n"
            "/inbox — cek email masuk (belum dibaca)\n"
            "/reply <nomor> — balas email masuk\n"
            "/help — bantuan ini"
        )

    def _cmd_status(self) -> str:
        try:
            conn = db.get_conn()
            from .models import get_earnings_summary, application_count
            from .workflow import contract_summary
            s = get_earnings_summary(conn)
            apps = application_count(conn)
            c = contract_summary(conn)
            conn.close()
            return (
                "<b>📊 STATUS</b>\n\n"
                f"💰 Hari ini: ${s['today_usd']:.2f} "
                f"({s['today_pct']}% dari ${s['target_daily_usd']:.0f})\n"
                f"💵 Total: ${s['total_usd']:.2f}\n"
                f"📤 Aplikasi: {apps}\n"
                f"📝 Kontrak aktif: {c.get('active', 0)}\n"
                f"✅ Kontrak selesai: {c.get('completed', 0)}"
            )
        except Exception as e:
            return f"❌ Gagal baca status: {e}"

    def _cmd_autopilot(self) -> str:
        try:
            from .autopilot import run_cycle
            stats = run_cycle(max_deliverables=3)
            lines = ["<b>🤖 AUTOPILOT SELESAI</b>\n"]
            for k, v in stats.items():
                lines.append(f"{k}: {v}")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Autopilot gagal: {e}"

    def _cmd_report(self) -> str:
        try:
            conn = db.get_conn()
            from .models import get_all_jobs
            from .reporter import TelegramReporter, format_daily_summary
            jobs = get_all_jobs(conn)
            conn.close()
            reporter = TelegramReporter()
            if not (reporter.token and reporter.channel_id):
                return "❌ Channel belum diset."
            reporter.send_jobs_batch(jobs)
            reporter.send_message(format_daily_summary(jobs))
            return f"✅ Laporan {len(jobs)} job dikirim ke channel."
        except Exception as e:
            return f"❌ Report gagal: {e}"

    def _cmd_earnings(self) -> str:
        try:
            conn = db.get_conn()
            from .models import get_earnings_summary
            s = get_earnings_summary(conn)
            conn.close()
            return (
                "<b>💰 EARNINGS</b>\n\n"
                f"Target: ${s['target_daily_usd']:.0f}/hari\n"
                f"Hari ini: ${s['today_usd']:.2f} ({s['today_pct']}%)\n"
                f"Sisa: ${s['remaining_today']:.2f}\n"
                f"Total: ${s['total_usd']:.2f}"
            )
        except Exception as e:
            return f"❌ Gagal baca earnings: {e}"

    def _cmd_files(self) -> str:
        d = _ensure_upload_dir()
        try:
            files = sorted(os.listdir(d))
        except OSError:
            files = []
        if not files:
            return "📂 Inbox kosong."
        lines = ["<b>📂 File di inbox</b>\n"]
        for f in files:
            p = os.path.join(d, f)
            size = os.path.getsize(p) if os.path.isfile(p) else 0
            lines.append(f"• <code>{f}</code> ({size} bytes)")
        return "\n".join(lines)

    def _cmd_inbox(self) -> str:
        try:
            from .imap_inbox import ImapInbox
            imap = ImapInbox()
            emails = imap.list_unread(limit=10)
            if not emails:
                return "📭 Tidak ada email masuk (belum dibaca)."
            lines = ["<b>📥 EMAIL MASUK (unread)</b>\n"]
            for e in emails:
                sender = e["from"].split("<")[0].strip() or e["from"]
                lines.append(
                    f"<b>#{e['num']}</b> {e['subject']}\n"
                    f"   dari: {sender}\n"
                    f"   {e['date'][:16].replace('T', ' ')}\n"
                )
            lines.append("\nBalas dengan: <code>/reply &lt;nomor&gt;</code>")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Gagal cek inbox: {e}\n\nPastikan IMAP sudah di-enable di Gmail settings."

    def _cmd_reply(self, text: str) -> str:
        parts = text.split()
        if len(parts) < 2:
            return "❌ Format: <code>/reply &lt;nomor&gt;</code>\nContoh: <code>/reply 3</code>"
        num = parts[1]
        try:
            from .imap_inbox import ImapInbox
            from .auto_reply import generate_reply
            imap = ImapInbox()
            info = imap.read_email(num)
            if not info:
                return f"❌ Email #{num} tidak ditemukan."
            # Balas cerdas (deteksi intent + kontekstual)
            body, intent = generate_reply(info)
            ok = imap.reply_email(num, body)
            if ok:
                return (f"✅ Email #{num} dibalas (intent: <b>{intent}</b>).\n\n"
                        f"Ke: {info['from']}\nSubjek: {info['subject']}")
            return f"❌ Gagal membalas email #{num}."
        except Exception as e:
            return f"❌ Gagal balas: {e}"

    # ------------------------------------------------------------------ #
    # Polling loop
    # ------------------------------------------------------------------ #
    def poll_once(self, timeout: int = 30) -> int:
        """Polling satu batch update. Return jumlah pesan diproses."""
        updates = self.get_updates(timeout=timeout)
        count = 0
        for u in updates:
            if "message" not in u:
                continue
            try:
                self.handle_message(u["message"])
                count += 1
            except Exception as e:
                print(f"[bot] error handle message -- {e}")
        return count

    def run_forever(self, poll_timeout: int = 30) -> None:
        """Long-polling tanpa henti."""
        print(f"[bot] mulai polling (token={'set' if self.token else 'KOSONG'}, "
              f"admin={self.admin_id or 'semua'})")
        while True:
            try:
                self.poll_once(timeout=poll_timeout)
            except KeyboardInterrupt:
                print("[bot] berhenti.")
                break
            except Exception as e:
                print(f"[bot] error loop -- {e}")
                time.sleep(5)


def run_bot(forever: bool = False, admin_id: str = None) -> None:
    bot = TelegramBot(admin_id=admin_id)
    if not bot.token:
        print("[bot] JOB_TELEGRAM_TOKEN belum diset di .env")
        return
    if forever:
        bot.run_forever()
    else:
        print("[bot] polling sekali...")
        n = bot.poll_once()
        print(f"[bot] {n} pesan diproses")
