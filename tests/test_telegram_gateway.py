"""tests/test_telegram_gateway.py
Test hermetic untuk gateway Telegram Garwa (garwa/telegram_gateway.py).

Cakupan:
  - Registrasi/helpers: _chunk_text, _escape, _allowed (auth admin + allow_all).
  - Mapping chat -> sesi di DB sementara (buat/resume/delete binding).
  - Perintah /start /help /new /status /exit (tanpa jaringan, mock requests).
  - Agent turn: pesan biasa -> add_message ke DB + busy-ack + kirim last_visible.
  - Polling: getUpdates di-mock, handle_message dipanggil, offset naik.

Test sengaja TIDAK menyentuh jaringan Telegram: semua requests.post di-mock.
"""
from __future__ import annotations

import argparse
import os
import tempfile

import pytest

from garwa import db as dbmod
from garwa.telegram_gateway import TelegramGateway, _chunk_text, _escape


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_args(db_path: str, workdir: str) -> argparse.Namespace:
    """Args dummy mirip hasil parser CLI (field yang dipakai gateway)."""
    return argparse.Namespace(
        db_path=db_path,
        workdir=workdir,
        skills_dir="",
        full_tool_schema_text=False,
        auto_approve=False,
        model="test-model",
        context_window=8192,
        reserve_for_response=1024,
        summarize_threshold_ratio=0.7,
        keep_tail_messages=5,
        api_key="",
        url="http://localhost:1",
        session_title="telegram",
    )


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.fixture
def gw(monkeypatch, tmp_path):
    """Gateway dengan token dummy + DB sementara + requests.post di-mock."""
    db_path = str(tmp_path / "test.db")
    dbmod.init_db(db_path)
    offset_file = str(tmp_path / "offset.txt")

    calls = []

    def fake_post(url, data=None, timeout=None):
        calls.append((url, dict(data or {})))
        method = url.rsplit("/", 1)[-1]
        if method == "getUpdates":
            return FakeResponse({"ok": True, "result": []})
        if method == "sendMessage":
            return FakeResponse({"ok": True, "result": {"message_id": 1}})
        return FakeResponse({"ok": True, "result": []})

    monkeypatch.setattr("requests.post", fake_post)

    args = _make_args(db_path, str(tmp_path))
    g = TelegramGateway(args=args, token="dummy:token", admin_id="777",
                        allow_all=False, offset_file=offset_file)
    g._calls = calls
    return g


# ---------------------------------------------------------------------------
# Helpers murni
# ---------------------------------------------------------------------------
def test_chunk_text():
    assert _chunk_text("abc", 50) == ["abc"]
    assert _chunk_text("a" * 100, 50) == ["a" * 50, "a" * 50]
    assert _chunk_text("", 50) == [""]


def test_escape():
    assert _escape("<b>&") == "&lt;b&gt;&amp;"
    assert _escape("plain") == "plain"


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------
def test_auth_admin_only(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test.db")
    dbmod.init_db(db_path)
    g = TelegramGateway(args=_make_args(db_path, str(tmp_path)),
                        token="", admin_id="777", allow_all=False,
                        offset_file=str(tmp_path / "o.txt"))
    assert g._allowed("777", None) is True      # chat_id == admin
    assert g._allowed("999", None) is False     # bukan admin
    assert g._allowed("999", "777") is True     # user_id == admin


def test_auth_no_admin_denies(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test.db")
    dbmod.init_db(db_path)
    g = TelegramGateway(args=_make_args(db_path, str(tmp_path)),
                        token="", admin_id="", allow_all=False,
                        offset_file=str(tmp_path / "o.txt"))
    assert g._allowed("777", None) is False


def test_auth_allow_all(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test.db")
    dbmod.init_db(db_path)
    g = TelegramGateway(args=_make_args(db_path, str(tmp_path)),
                        token="", admin_id="777", allow_all=True,
                        offset_file=str(tmp_path / "o.txt"))
    assert g._allowed("999", None) is True


# ---------------------------------------------------------------------------
# Mapping chat -> sesi
# ---------------------------------------------------------------------------
def test_session_created_and_resumed(gw):
    sid1 = gw._session_for_chat("111")
    assert sid1
    # Binding tersimpan + system prompt disuntikkan.
    b = dbmod.get_telegram_binding(gw._db_path(), "111")
    assert b and b["session_id"] == sid1
    with dbmod.connect(gw._db_path()) as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM messages WHERE session_id=? AND role='system'",
                         (sid1,)).fetchone()["n"]
    assert n == 1

    # Resume: chat yang sama mengembalikan sesi yang sama.
    sid2 = gw._session_for_chat("111")
    assert sid2 == sid1

    # /new -> sesi baru berbeda.
    sid3 = gw._new_session("111")
    assert sid3 != sid1


def test_exit_closes_session(gw):
    sid = gw._session_for_chat("111")
    gw._handle_command("111", 1, "/exit")
    sess = dbmod.get_session(gw._db_path(), sid)
    assert sess and sess["ended"] == 1
    assert dbmod.get_telegram_binding(gw._db_path(), "111") is None


# ---------------------------------------------------------------------------
# Perintah bot
# ---------------------------------------------------------------------------
def test_help_command(gw):
    gw._handle_command("777", 10, "/help")
    sent = [p for (u, p) in gw._calls if u.endswith("/sendMessage")]
    assert sent and "Garwa Telegram Gateway" in sent[0]["text"]


def test_status_command(gw):
    gw._session_for_chat("777")
    gw._handle_command("777", 10, "/status")
    sent = [p for (u, p) in gw._calls if u.endswith("/sendMessage")]
    assert sent and "Sesi aktif" in sent[-1]["text"]


def test_unknown_slash_falls_to_agent(gw, monkeypatch):
    """Slash tak dikenal diteruskan ke agent turn (add_message + busy-ack)."""
    seen = {}

    def fake_loop(args, session_id, system_content):
        seen["session_id"] = session_id
        seen["system"] = bool(system_content)
        return "hasil dari agent"

    monkeypatch.setattr("garwa.telegram_gateway.run_agent_loop", fake_loop)
    gw._handle_command("777", 10, "/xyzzy-unknown")
    gw._join_threads()
    assert seen.get("session_id")
    assert seen.get("system") is True
    sent = [p for (u, p) in gw._calls if u.endswith("/sendMessage")]
    texts = [p["text"] for p in sent]
    assert any("hasil dari agent" in t for t in texts)
    # user message tersimpan di DB
    with dbmod.connect(gw._db_path()) as conn:
        row = conn.execute(
            "SELECT content FROM messages WHERE session_id=? AND role='user' ORDER BY id DESC LIMIT 1",
            (seen["session_id"],),
        ).fetchone()
    assert row and row["content"] == "/xyzzy-unknown"


# ---------------------------------------------------------------------------
# Agent turn (pesan biasa)
# ---------------------------------------------------------------------------
def test_agent_turn_flow(gw, monkeypatch):
    seen = {}

    def fake_loop(args, session_id, system_content):
        seen["args_auto_approve"] = getattr(args, "auto_approve", None)
        seen["session_id"] = session_id
        return "Balasan: halo"

    monkeypatch.setattr("garwa.telegram_gateway.run_agent_loop", fake_loop)
    gw.handle_message({"chat": {"id": "777"}, "from": {"id": "777"},
                       "message_id": 5, "text": "Halo Garwa"})
    gw._join_threads()

    sent = [p for (u, p) in gw._calls if u.endswith("/sendMessage")]
    texts = [p["text"] for p in sent]
    # busy-ack lalu hasil
    assert any("sedang memproses" in t for t in texts)
    assert any("Balasan: halo" in t for t in texts)
    # auto-approve diaktifkan (non-interaktif)
    assert seen["args_auto_approve"] is True


def test_agent_turn_empty_reply(gw, monkeypatch):
    monkeypatch.setattr("garwa.telegram_gateway.run_agent_loop",
                        lambda *a, **k: "")
    gw.handle_message({"chat": {"id": "777"}, "from": {"id": "777"},
                       "message_id": 6, "text": "hitung 1+1"})
    gw._join_threads()
    sent = [p for (u, p) in gw._calls if u.endswith("/sendMessage")]
    texts = [p["text"] for p in sent]
    assert any("Selesai" in t for t in texts)


def test_agent_turn_error(gw, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("server mati")

    monkeypatch.setattr("garwa.telegram_gateway.run_agent_loop", boom)
    gw.handle_message({"chat": {"id": "777"}, "from": {"id": "777"},
                       "message_id": 7, "text": "tes"})
    gw._join_threads()
    sent = [p for (u, p) in gw._calls if u.endswith("/sendMessage")]
    texts = [p["text"] for p in sent]
    assert any("Error saat memproses" in t and "server mati" in t for t in texts)


# ---------------------------------------------------------------------------
# Authorization di handle_message
# ---------------------------------------------------------------------------
def test_deny_non_admin(gw):
    gw.handle_message({"chat": {"id": "999"}, "from": {"id": "999"},
                       "message_id": 1, "text": "Halo"})
    sent = [p for (u, p) in gw._calls if u.endswith("/sendMessage")]
    texts = [p["text"] for p in sent]
    assert any("Akses ditolak" in t for t in texts)


def test_empty_message(gw):
    gw.handle_message({"chat": {"id": "777"}, "from": {"id": "777"},
                       "message_id": 1, "text": "   "})
    sent = [p for (u, p) in gw._calls if u.endswith("/sendMessage")]
    texts = [p["text"] for p in sent]
    assert any("Pesan kosong" in t for t in texts)


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------
def test_poll_once_processes_updates(gw, monkeypatch):
    # Mock get_updates agar mengembalikan 2 pesan.
    monkeypatch.setattr(gw, "get_updates", lambda timeout=30: [
        {"update_id": 1, "message": {"chat": {"id": "777"}, "from": {"id": "777"},
                                     "message_id": 1, "text": "/help"}},
        {"update_id": 2, "message": {"chat": {"id": "777"}, "from": {"id": "777"},
                                     "message_id": 2, "text": "hai"}},
    ])
    monkeypatch.setattr(gw, "_run_agent_turn", lambda *a, **k: None)
    n = gw.poll_once(timeout=5)
    assert n == 2


# ---------------------------------------------------------------------------
# Integrasi cron ke gateway
# ---------------------------------------------------------------------------
def test_maybe_run_cron_runs_once_per_minute(gw, monkeypatch):
    """_maybe_run_cron memanggil cron_runner.run_due() paling banyak sekali per
    menit (anti double-run), dan tidak error saat cron_runner None."""
    calls = {"n": 0}

    def fake_run_due():
        calls["n"] += 1
        return [("jadwal", "[cron bash] exit=0: ok")]

    monkeypatch.setattr(gw, "_last_cron_minute", None)
    monkeypatch.setattr("garwa.telegram_gateway.cron_runner", None)
    # cron_runner None -> tidak crash, tidak memanggil apa pun.
    gw._maybe_run_cron()
    assert calls["n"] == 0

    # Simulasikan cron_runner ada.
    import types
    fake_mod = types.SimpleNamespace(run_due=fake_run_due)
    monkeypatch.setattr("garwa.telegram_gateway.cron_runner", fake_mod)
    gw._last_cron_minute = None
    gw._maybe_run_cron()
    gw._maybe_run_cron()  # menit sama -> tidak dipanggil lagi
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# Slash command baru: /stop, /todos, /memory, /sessions, /model
# ---------------------------------------------------------------------------
def test_stop_no_active_session(gw):
    """/stop tanpa sesi aktif -> pesan tidak ada proses."""
    gw._handle_command("777", 50, "/stop")
    sent = [p for (u, p) in gw._calls if u.endswith("/sendMessage")]
    texts = [p["text"] for p in sent]
    assert any("Tidak ada proses" in t for t in texts)


def test_stop_with_active_session(gw, monkeypatch):
    """/stop menandai interrupt untuk sesi yang sedang diproses."""
    import garwa.cli._state as st
    st._INTERRUPT_FLAGS.clear()
    sid = "sess-stop-test"
    gw._active_sessions["777"] = sid
    gw._handle_command("777", 51, "/stop")
    assert st.interrupt_requested(sid) is True
    sent = [p for (u, p) in gw._calls if u.endswith("/sendMessage")]
    texts = [p["text"] for p in sent]
    assert any("berhenti diterima" in t for t in texts)
    st._INTERRUPT_FLAGS.clear()


def test_slash_delegates_to_cli(gw, monkeypatch):
    """/todos didelegasikan ke handle_slash_command CLI (bukan duplikasi logika),
    dan output stdout-nya dikirim ke chat."""
    import garwa.telegram_gateway as tgw

    seen = {}

    def fake_handle(cmd_line, args, session_id, system_content):
        seen["cmd"] = cmd_line
        seen["session_id"] = session_id
        print("Plan sesi (2 item):")
        print("  [~] kerjakan A")
        print("  [ ] kerjakan B")
        return {"action": "skip"}

    monkeypatch.setattr(tgw, "handle_slash_command", fake_handle)
    gw._handle_command("777", 60, "/todos")
    assert seen.get("cmd") == "/todos"
    assert seen.get("session_id")
    sent = [p for (u, p) in gw._calls if u.endswith("/sendMessage")]
    texts = [p["text"] for p in sent]
    assert any("kerjakan A" in t for t in texts)
    assert any("kerjakan B" in t for t in texts)


def test_slash_continue_falls_to_agent(gw, monkeypatch):
    """/git-status (action continue) jatuh ke agent turn."""
    import garwa.telegram_gateway as tgw

    def fake_handle(cmd_line, args, session_id, system_content):
        return {"action": "continue"}

    monkeypatch.setattr(tgw, "handle_slash_command", fake_handle)
    monkeypatch.setattr(tgw, "run_agent_loop", lambda *a, **k: "dari agent")
    gw._handle_command("777", 65, "/git-status")
    gw._join_threads()
    sent = [p for (u, p) in gw._calls if u.endswith("/sendMessage")]
    texts = [p["text"] for p in sent]
    assert any("dari agent" in t for t in texts)


def test_slash_exit_closes_session(gw, monkeypatch):
    """/exit (action exit) menutup sesi + menghapus binding."""
    import garwa.telegram_gateway as tgw

    db_path = gw._db_path()
    sid = dbmod.create_session(db_path, str(gw._workdir()), title="telegram:777")
    dbmod.set_telegram_binding(db_path, "777", sid)

    def fake_handle(cmd_line, args, session_id, system_content):
        return {"action": "exit"}

    monkeypatch.setattr(tgw, "handle_slash_command", fake_handle)
    gw._handle_command("777", 66, "/exit")
    assert dbmod.get_telegram_binding(db_path, "777") is None
    sent = [p for (u, p) in gw._calls if u.endswith("/sendMessage")]
    texts = [p["text"] for p in sent]
    assert any("Sesi ditutup" in t or "🔚" in t for t in texts)


def test_slash_new_session_updates_binding(gw, monkeypatch):
    """/new (action new_session) meng-update binding ke sesi baru."""
    import garwa.telegram_gateway as tgw

    db_path = gw._db_path()
    old_sid = dbmod.create_session(db_path, str(gw._workdir()), title="telegram:777")
    dbmod.set_telegram_binding(db_path, "777", old_sid)
    new_sid = dbmod.create_session(db_path, str(gw._workdir()), title="baru")

    def fake_handle(cmd_line, args, session_id, system_content):
        return {"action": "new_session", "session_id": new_sid, "system_content": "sys"}

    monkeypatch.setattr(tgw, "handle_slash_command", fake_handle)
    gw._handle_command("777", 67, "/new")
    assert dbmod.get_telegram_binding(db_path, "777")["session_id"] == new_sid


# ---------------------------------------------------------------------------
# Cron delivery ke Telegram
# ---------------------------------------------------------------------------
def test_deliver_cron_sends_to_admin(gw):
    """Hasil cron dikirim ke chat admin."""
    gw._deliver_cron(chat_id=None, name="jadwal", res="exit=0 ok")
    sent = [p for (u, p) in gw._calls if u.endswith("/sendMessage")]
    texts = [p["text"] for p in sent]
    assert any("jadwal" in t and "exit=0 ok" in t for t in texts)


def test_deliver_cron_no_token_no_send(gw):
    """Tanpa token, cron tidak dikirim (tidak crash)."""
    gw.token = ""
    gw.api_url = ""
    gw._deliver_cron(chat_id=None, name="jadwal", res="ok")
    sent = [p for (u, p) in gw._calls if u.endswith("/sendMessage")]
    # Tidak ada pengiriman baru (mock masih mencatat dari test sebelumnya)
    assert all("Cron" not in p["text"] for (u, p) in sent)
