"""garwa/telegram_gateway.py
Gateway Telegram dua arah untuk Garwa: user mengirim perintah/pertanyaan dari
chat Telegram, Garwa menjalankan agent loop (tool, file, bash, dll) di mesin
lokal, lalu membalas hasilnya kembali ke chat asal.

Pola (diadaptasi dari hermes-agent NousResearch + jobbot/telegram_bot.py):
  - Long polling getUpdates (tanpa library eksternal, cukup `requests`).
  - Allowlist admin: hanya TELEGRAM_ADMIN_ID yang boleh memberi perintah.
  - Setiap chat Telegram punya SESSION Garwa sendiri (tabel telegram_bindings),
    jadi riwayat percakapan per-chat terpisah dan bisa di-resume.
  - Pesan diteruskan ke `run_agent_loop` (pola yang sama dengan mode --auto),
    lalu `last_visible` dikirim balik ke chat asal (delivery ke origin).
  - Busy-ack "⏳ ..." dikirim sebelum proses, hasil menyusul setelah selesai.

Kredensial (garwa.config, yang membaca env + .env):
  - GARWA_TELEGRAM_TOKEN | JOB_TELEGRAM_TOKEN | TELEGRAM_TOKEN
  - GARWA_TELEGRAM_ADMIN_ID | JOB_TELEGRAM_ADMIN_ID | TELEGRAM_ADMIN_ID
  - GARWA_TELEGRAM_ALLOW_ALL (true) = izinkan SEMUA user (dev only)

Menjalankan:
  python -m garwa --bot                  # polling sekali
  python -m garwa --bot --forever        # polling terus-menerus
"""
from __future__ import annotations

import contextlib
import html
import io
import os
import threading
import time
from typing import Optional

import requests

from . import db as dbmod
from . import tools as tools_module
from .cli import _state as cli_state
from .cli.agent_loop import run_agent_loop
from .cli.skills.system_prompt import build_system_prompt
from .cli.slash_commands import handle_slash_command

try:
    from .tools import cron_runner
except ImportError:  # pragma: no cover - cron opsional
    cron_runner = None

try:
    from . import config as config_mod
except ImportError:  # pragma: no cover
    config_mod = None

# Batas panjang satu pesan Telegram (API max 4096; kita pakai 4000 aman).
MAX_MSG = 4000


# ---------------------------------------------------------------------------
# Helpers konfigurasi (konsisten dengan tools/comm_tools.py)
# ---------------------------------------------------------------------------
def _get(name: str, default: str = "") -> str:
    if config_mod is not None:
        v = getattr(config_mod, name, None)
        if v:
            return str(v)
    return os.environ.get(name, default) or default


def _bot_token() -> str:
    return _get("TELEGRAM_TOKEN")


def _admin_id() -> str:
    return _get("TELEGRAM_ADMIN_ID")


def _allow_all() -> bool:
    return _get("GARWA_TELEGRAM_ALLOW_ALL", "").strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Helpers teks
# ---------------------------------------------------------------------------
def _chunk_text(text: str, limit: int = MAX_MSG) -> list:
    """Pecah teks panjang menjadi beberapa pesan (batas API Telegram)."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks


def _escape(text: str) -> str:
    """Escape karakter khusus HTML."""
    return html.escape(text, quote=False)


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------
class TelegramGateway:
    def __init__(self, args=None, token: str = None, admin_id: str = None,
                 allow_all: bool = None, offset_file: str = None):
        self.args = args  # AgentConfig / argparse.Namespace untuk run_agent_loop
        # `token=None` -> baca dari env/config; `token=""` -> paksa tanpa token
        # (dipakai test untuk memverifikasi cabang "kredensial belum diset").
        self.token = _bot_token() if token is None else token
        self.admin_id = str(admin_id) if admin_id is not None else _admin_id()
        self.allow_all = _allow_all() if allow_all is None else allow_all
        self.api_url = f"https://api.telegram.org/bot{self.token}" if self.token else ""
        self._offset = 0
        self._last_cron_minute = None  # anti double-run cron dalam satu menit
        # Sesi yang sedang diproses agent turn (chat_id -> session_id), supaya
        # /stop bisa menandai interrupt untuk sesi yang benar lintas thread.
        self._active_sessions: dict = {}
        # Thread agent turn aktif (untuk join di test / shutdown bersih).
        self._threads: list = []
        self._offset_file = offset_file or os.environ.get(
            "GARWA_TELEGRAM_OFFSET_FILE",
            os.path.join(os.path.expanduser("~"), ".garwa", "telegram_offset.txt"),
        )
        self._load_offset()

    # -- offset persistence (hindari duplikasi update setelah restart) ------
    def _load_offset(self) -> None:
        try:
            with open(self._offset_file, "r", encoding="utf-8") as f:
                self._offset = int(f.read().strip() or 0)
        except (OSError, ValueError):
            self._offset = 0

    def _save_offset(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._offset_file), exist_ok=True)
            with open(self._offset_file, "w", encoding="utf-8") as f:
                f.write(str(self._offset))
        except OSError:
            pass  # non-fatal; offset tetap di memori

    # -- API primitives ------------------------------------------------------
    def _call(self, method: str, **params) -> Optional[dict]:
        if not self.token:
            return None
        try:
            resp = requests.post(f"{self.api_url}/{method}", data=params, timeout=65)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            return None

    def get_updates(self, timeout: int = 30) -> list:
        data = self._call(
            "getUpdates", offset=self._offset,
            timeout=timeout, allowed_updates='["message"]',
        )
        if not data or not data.get("ok"):
            return []
        updates = data.get("result", [])
        if updates:
            self._offset = updates[-1]["update_id"] + 1
            self._save_offset()
        return updates

    def send_message(self, chat_id, text: str, reply_to: int = None) -> bool:
        if not self.token or not text:
            return False
        ok = True
        for chunk in _chunk_text(text):
            params = {"chat_id": chat_id, "text": chunk}
            if reply_to is not None:
                params["reply_to_message_id"] = reply_to
            # SENG AJA tanpa parse_mode: hasil agent sering mengandung karakter
            # HTML mentah (<path>, <file>, dll) yang bikin API 400 kalau
            # parse_mode=HTML. Plain text paling aman untuk produksi.
            data = self._call("sendMessage", **params)
            ok = ok and bool(data and data.get("ok"))
        return ok

    # -- authorization --------------------------------------------------------
    def _allowed(self, chat_id, user_id=None) -> bool:
        if self.allow_all:
            return True
        if not self.admin_id:
            return False  # admin belum diset -> tolak semua (aman)
        if str(chat_id) == str(self.admin_id):
            return True
        if user_id is not None and str(user_id) == str(self.admin_id):
            return True
        return False

    # -- session management ----------------------------------------------------
    def _session_for_chat(self, chat_id) -> str:
        """Resume sesi yang ter-binding, atau buat sesi baru untuk chat ini."""
        db_path = self._db_path()
        binding = dbmod.get_telegram_binding(db_path, str(chat_id))
        if binding:
            sess = dbmod.get_session(db_path, binding["session_id"])
            if sess and not sess.get("ended"):
                return sess["id"]
        # Buat sesi baru ber-title telegram:<chat_id>
        sid = dbmod.create_session(db_path, self._workdir(), title=f"telegram:{chat_id}")
        dbmod.set_telegram_binding(db_path, str(chat_id), sid)
        # Suntik system prompt (pola sama seperti main.py sesi baru)
        system_content = self._system_content()
        dbmod.add_message(db_path, sid, "system", system_content, kind="chat")
        return sid

    def _new_session(self, chat_id) -> str:
        """Paksa buat sesi baru (perintah /new). Hapus binding lama dulu."""
        db_path = self._db_path()
        dbmod.delete_telegram_binding(db_path, str(chat_id))
        return self._session_for_chat(chat_id)

    def _db_path(self) -> str:
        if self.args is not None:
            p = getattr(self.args, "db_path", None)
            if p:
                return p
        return os.environ.get("GARWA_DB_PATH") or dbmod.DEFAULT_DB_PATH

    def _workdir(self) -> str:
        if self.args is not None:
            w = getattr(self.args, "workdir", None)
            if w:
                return w
        return os.environ.get("GARWA_WORKDIR") or os.getcwd()

    def _system_content(self) -> str:
        workdir = self._workdir()
        skills_dir = getattr(self.args, "skills_dir", "") or cli_state.DEFAULT_SKILLS_DIR
        full_schema = bool(getattr(self.args, "full_tool_schema_text", False))
        return build_system_prompt(workdir, skills_dir, full_tool_schema=full_schema)

    def _prepare_state(self, session_id: str) -> None:
        """Set state global + env supaya run_agent_loop memakai sesi yang benar."""
        db_path = self._db_path()
        tools_module.state.DB_PATH = db_path
        tools_module.state.set_session_id(session_id)
        cli_state.reset_session_state(session_id)
        cli_state.get_session_state()["start_time"] = time.time()
        os.environ["GARWA_DB_PATH"] = db_path
        os.environ["GARWA_SESSION_ID"] = session_id

    # -- command handlers -----------------------------------------------------
    def _handle_command(self, chat_id, msg_id, text: str) -> None:
        """Proses slash-command dari chat Telegram.

        Memanfaatkan `handle_slash_command` dari CLI (satu-satunya sumber
        kebenaran untuk /model, /memory, /todos, /sessions, /status, /git-*,
        dll) dengan menangkap output stdout-nya dan mengirimkannya ke chat.
        Hanya command yang spesifik gateway (/start, /help, /stop) yang
        ditangani lokal; sisanya di-delegate ke CLI supaya tidak ada logika
        duplikat yang bisa bentrok.
        """
        cmd = text.strip().split()[0].lower()

        # Command spesifik gateway (tidak ada di CLI).
        if cmd in ("/start", "/help", "help"):
            self.send_message(chat_id, self._help_text(), reply_to=msg_id)
            return
        if cmd in ("/stop", "stop", "berhenti"):
            self._handle_stop(chat_id, msg_id)
            return

        # Delegasikan ke CLI. Siapkan sesi dulu supaya handle_slash_command
        # memakai binding yang benar.
        db_path = self._db_path()
        session_id = self._session_for_chat(chat_id)
        self._prepare_state(session_id)

        # Tangkap output stdout dari handler CLI (semua _handle_* mencetak).
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = handle_slash_command(text, self.args, session_id, self._system_content())
        out = buf.getvalue().strip()

        action = result.get("action", "continue")

        if action == "exit":
            # /exit atau /quit: tutup sesi bot (hapus binding).
            binding = dbmod.get_telegram_binding(db_path, str(chat_id))
            if binding:
                dbmod.end_session(db_path, binding["session_id"])
                dbmod.delete_telegram_binding(db_path, str(chat_id))
            self.send_message(
                chat_id,
                out or "🔚 Sesi ditutup. Kirim pesan apa pun untuk membuat sesi baru.",
                reply_to=msg_id,
            )
            return

        if action in ("new_session", "resume"):
            # Ganti sesi aktif (pola sama seperti main.py). Binding Telegram
            # perlu di-update ke sesi baru supaya pesan berikutnya memakainya.
            new_sid = result["session_id"]
            dbmod.set_telegram_binding(db_path, str(chat_id), new_sid)
            self._prepare_state(new_sid)
            self.send_message(
                chat_id,
                out or f"🆕 Sesi aktif: <code>{_escape(new_sid)}</code>",
                reply_to=msg_id,
            )
            return

        # action == "skip" (command sudah dieksekusi CLI) atau "continue"
        # (command tak dikenal). Untuk "continue", jatuh ke agent turn.
        if action == "continue":
            self._run_agent_turn(chat_id, msg_id, text)
            return

        # "skip": kirim output CLI ke chat.
        self.send_message(
            chat_id,
            out or "✅ Perintah dieksekusi.",
            reply_to=msg_id,
        )

    def _help_text(self) -> str:
        return (
            "🤖 Garwa Telegram Gateway\n"
            "Kirim pertanyaan/perintah, Garwa akan menjalankannya di mesin "
            "lokal (baca/tulis file, jalankan bash, git, dll) lalu membalas "
            "hasilnya ke sini.\n\n"
            "Perintah:\n"
            "/start — mulai / bantuan\n"
            "/help — bantuan ini\n"
            "/new — mulai sesi percakapan baru\n"
            "/status — info sesi saat ini\n"
            "/todos — tampilkan todo list sesi ini\n"
            "/memory — kelola catatan proyek (list | show <key> | forget <key>)\n"
            "/sessions — daftar sesi tersimpan\n"
            "/model — lihat/ganti model aktif (/model <nama>)\n"
            "/stop — batalkan proses yang sedang berjalan\n"
            "/exit — tutup sesi bot\n\n"
            "Semua perintah lain (termasuk /git-..., /email, dll) diteruskan "
            "ke agent Garwa sebagai pesan biasa."
        )

    def _status_text(self, chat_id) -> str:
        db_path = self._db_path()
        binding = dbmod.get_telegram_binding(db_path, str(chat_id))
        if not binding:
            return "📭 Belum ada sesi untuk chat ini. Kirim pesan untuk memulai."
        sess = dbmod.get_session(db_path, binding["session_id"])
        if not sess:
            return "📭 Sesi ter-binding tidak ditemukan."
        try:
            with dbmod.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM messages WHERE session_id = ?",
                    (sess["id"],),
                ).fetchone()
                n_msgs = row["n"] if row else 0
        except Exception:
            n_msgs = "?"
        title = sess.get("title") or "(tanpa judul)"
        return (
            "📊 STATUS\n\n"
            f"Sesi: {_escape(sess['id'])}\n"
            f"Judul: {_escape(title)}\n"
            f"Pesan tersimpan: {n_msgs}\n"
            f"Workdir: {_escape(sess.get('workdir') or '')}"
        )

    # -- agent turn -----------------------------------------------------------------
    def _run_agent_turn(self, chat_id, msg_id, text: str) -> None:
        # Jalankan agent turn di thread daemon supaya polling tetap bisa
        # memproses update lain (termasuk /stop) selama turn berjalan. Interrupt
        # lintas thread memakai flag per-session di cli_state (bukan ContextVar,
        # karena context tidak menular antar thread).
        t = threading.Thread(
            target=self._run_agent_turn_worker,
            args=(chat_id, msg_id, text),
            daemon=True,
        )
        self._threads.append(t)
        t.start()

    def _join_threads(self, timeout: float = 10.0) -> None:
        """Tunggu semua thread agent turn selesai (dipakai test & shutdown)."""
        for t in list(self._threads):
            t.join(timeout=timeout)
        self._threads.clear()

    def _run_agent_turn_worker(self, chat_id, msg_id, text: str) -> None:
        # Non-interaktif: tidak ada manusia untuk konfirmasi -> auto-approve.
        if self.args is not None:
            self.args.auto_approve = True

        db_path = self._db_path()
        session_id = self._session_for_chat(chat_id)
        self._prepare_state(session_id)
        self._active_sessions[str(chat_id)] = session_id
        # Bersihkan flag interrupt lama (kalau ada sisa dari turn sebelumnya).
        cli_state.clear_interrupt(session_id)

        dbmod.add_message(db_path, session_id, "user", text, kind="chat")

        # Busy-ack
        self.send_message(chat_id, "⏳ Garwa sedang memproses...", reply_to=msg_id)

        try:
            last_visible = run_agent_loop(self.args, session_id, self._system_content())
        except KeyboardInterrupt:
            dbmod.touch_session(db_path, session_id)
            self.send_message(chat_id, "🛑 Diproses dibatalkan.", reply_to=msg_id)
            return
        except Exception as e:
            dbmod.touch_session(db_path, session_id)
            self.send_message(
                chat_id,
                f"❌ Error saat memproses: {type(e).__name__}: {e}",
                reply_to=msg_id,
            )
            return
        finally:
            self._active_sessions.pop(str(chat_id), None)
            cli_state.clear_interrupt(session_id)

        dbmod.touch_session(db_path, session_id)
        if last_visible and last_visible.strip():
            self.send_message(chat_id, last_visible, reply_to=msg_id)
        else:
            self.send_message(chat_id, "✅ Selesai (tanpa balasan teks).", reply_to=msg_id)

    # -- slash command handlers baru ------------------------------------------------
    def _handle_stop(self, chat_id, msg_id) -> None:
        session_id = self._active_sessions.get(str(chat_id))
        if not session_id:
            self.send_message(
                chat_id,
                "🛑 Tidak ada proses yang sedang berjalan untuk chat ini.",
                reply_to=msg_id,
            )
            return
        cli_state.request_interrupt(session_id)
        self.send_message(
            chat_id,
            "🛑 Perintah berhenti diterima. Garwa akan berhenti secepatnya...",
            reply_to=msg_id,
        )

    # -- message dispatch --------------------------------------------------------------
    def handle_message(self, msg: dict) -> None:
        chat_id = msg.get("chat", {}).get("id")
        if chat_id is None:
            return
        user_id = msg.get("from", {}).get("id")
        msg_id = msg.get("message_id")

        if not self._allowed(chat_id, user_id):
            self.send_message(
                chat_id,
                "⛔ Akses ditolak. Chat ini tidak terdaftar sebagai admin.",
                reply_to=msg_id,
            )
            return

        text = (msg.get("text") or "").strip()
        if not text:
            self.send_message(chat_id, "❓ Pesan kosong.", reply_to=msg_id)
            return

        if text.startswith("/"):
            self._handle_command(chat_id, msg_id, text)
        else:
            self._run_agent_turn(chat_id, msg_id, text)

    # -- polling loop ------------------------------------------------------------------
    def poll_once(self, timeout: int = 30) -> int:
        """Polling satu batch update. Return jumlah pesan yang diproses."""
        updates = self.get_updates(timeout=timeout)
        count = 0
        for u in updates:
            if "message" not in u:
                continue
            try:
                self.handle_message(u["message"])
                count += 1
            except Exception as e:
                print(f"[telegram-gateway] error handle message: {type(e).__name__}: {e}")
        return count

    def _maybe_run_cron(self) -> None:
        """Jalankan cron_runner.run_due() paling banyak sekali per menit.

        Integrasi cron ke gateway: saat `--bot --forever` berjalan, jadwal cron
        ikut dieksekusi tiap menit tanpa perlu proses/crontab terpisah.
        Anti-double-run per menit via `_last_cron_minute` (di samping claim
        atomik di cron_runner sendiri).
        """
        if cron_runner is None:
            return
        now_min = int(time.time() // 60)
        if self._last_cron_minute == now_min:
            return
        self._last_cron_minute = now_min
        try:
            results = cron_runner.run_due()
            for name, res in results:
                print(f"[cron] {name}: {res}", flush=True)
                self._deliver_cron(chat_id=None, name=name, res=res)
        except Exception as e:  # noqa: BLE001 - cron tidak boleh mematikan gateway
            print(f"[cron] error: {type(e).__name__}: {e}", flush=True)

    def _deliver_cron(self, chat_id, name: str, res: str) -> None:
        """Kirim hasil eksekusi cron ke chat Telegram admin (default) atau ke
        chat yang meminta. Kalau tidak ada admin & allow_all, tidak dikirim
        (hanya log stdout)."""
        # Prioritas: chat yang meminta jadwal cron (kalau ada), lalu admin.
        target = chat_id or self.admin_id
        if not target or not self.token:
            return
        try:
            self.send_message(
                target,
                f"⏰ <b>Cron: {_escape(name)}</b>\n{_escape(res)}",
            )
        except Exception as e:  # noqa: BLE001
            print(f"[cron] gagal kirim ke telegram: {type(e).__name__}: {e}", flush=True)

    def run_forever(self, poll_timeout: int = 30) -> None:
        print(f"[telegram-gateway] mulai polling (token={'set' if self.token else 'KOSONG'}, "
              f"admin={self.admin_id or 'TIDAK DISET'}, allow_all={self.allow_all})")
        if not self.token:
            print("[telegram-gateway] TELEGRAM_TOKEN belum diset -- tidak bisa polling.")
            return
        while True:
            try:
                self.poll_once(timeout=poll_timeout)
                self._maybe_run_cron()
            except KeyboardInterrupt:
                print("[telegram-gateway] berhenti.")
                break
            except Exception as e:
                print(f"[telegram-gateway] error loop: {type(e).__name__}: {e}")
                time.sleep(5)


def run_gateway(args, forever: bool = False) -> None:
    """Entry point dari CLI: buat gateway lalu polling sekali / selamanya."""
    gw = TelegramGateway(args=args)
    if not gw.token:
        print("[telegram-gateway] TELEGRAM_TOKEN belum diset di env/.env -- abort.")
        return
    if forever:
        gw.run_forever()
    else:
        print("[telegram-gateway] polling sekali...")
        n = gw.poll_once()
        print(f"[telegram-gateway] {n} pesan diproses")
