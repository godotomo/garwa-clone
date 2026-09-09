"""Test untuk fitur-fitur baru yang diambil dari Hermes Agent.

Berkas ini menguji:
- Fungsi DB: delete_messages_after, get_last_turn_span, search_messages,
  aggregate_token_usage.
- Slash command: /undo, /retry, /search, /personality, /usage.
- Penyuntikan personality ke system prompt.
"""

import time

import pytest

from garwa import config
from garwa import db as dbmod
from garwa.cli import slash_commands as sc
from garwa.cli.skills import system_prompt


class _Args:
    """Minimal mock args; cukup memuat atribut yang diakses handler."""

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _run(cmd_line, session_id="s1", **args_kw):
    args = _Args(**args_kw)
    return sc.handle_slash_command(cmd_line, args, session_id=session_id, system_content="")


# ---------------------------------------------------------------- DB helpers

def _seed_turn(db_path, sid):
    """Buat satu giliran: system + user chat + assistant + tool_call + result."""
    dbmod.add_message(db_path, sid, "system", "sys", kind="chat")
    user_id = dbmod.add_message(db_path, sid, "user", "halo", kind="chat")
    dbmod.add_message(db_path, sid, "assistant", "menjawab", kind="chat")
    dbmod.add_message(db_path, sid, "assistant", "tool_call", kind="tool_call",
                      meta={"tool_name": "bash", "token_estimate": 100})
    dbmod.add_message(db_path, sid, "user", "tool_result", kind="tool_result")
    return user_id


def test_get_last_turn_span(db_path):
    sid = dbmod.create_session(db_path, "/tmp/w")
    user_id = _seed_turn(db_path, sid)
    span = dbmod.get_last_turn_span(db_path, sid)
    assert span["start_id"] == user_id
    assert span["user_id"] == user_id


def test_get_last_turn_span_empty(db_path):
    sid = dbmod.create_session(db_path, "/tmp/w")
    assert dbmod.get_last_turn_span(db_path, sid) == {}


def test_delete_messages_after(db_path):
    sid = dbmod.create_session(db_path, "/tmp/w")
    user_id = _seed_turn(db_path, sid)
    deleted = dbmod.delete_messages_after(db_path, sid, user_id)
    # Menghapus assistant, tool_call, tool_result (3 pesan setelah user_id).
    assert deleted == 3
    remaining = dbmod.get_all_messages(db_path, sid)
    assert len(remaining) == 2  # system + user


def test_search_messages_fts(db_path):
    sid = dbmod.create_session(db_path, "/tmp/w", title="Sesi A")
    dbmod.add_message(db_path, sid, "user", "cara deploy ke termux", kind="chat")
    dbmod.add_message(db_path, sid, "assistant", "pakai pkg install", kind="chat")
    results = dbmod.search_messages(db_path, "termux")
    assert len(results) >= 1
    assert any("termux" in r["content"] for r in results)
    assert results[0]["session_title"] == "Sesi A"


def test_search_messages_no_result(db_path):
    sid = dbmod.create_session(db_path, "/tmp/w")
    dbmod.add_message(db_path, sid, "user", "halo dunia", kind="chat")
    assert dbmod.search_messages(db_path, "xyz-tidak-ada") == []


def test_aggregate_token_usage(db_path):
    sid = dbmod.create_session(db_path, "/tmp/w")
    dbmod.add_message(db_path, sid, "assistant", "t", kind="tool_call",
                      meta={"tool_name": "bash", "token_estimate": 150})
    dbmod.add_message(db_path, sid, "assistant", "t2", kind="tool_call",
                      meta={"tool_name": "read_file", "token_estimate": 50})
    dbmod.add_message(db_path, sid, "assistant", "t3", kind="tool_call",
                      meta={"tool_name": "bash", "token_estimate": 30, "is_error": True})
    agg = dbmod.aggregate_token_usage(db_path, workdir="/tmp/w")
    assert agg["total_tokens"] == 230
    assert agg["tool_calls"] == 3
    assert agg["errors"] == 1
    assert agg["per_tool"]["bash"] == 2
    assert agg["per_tool"]["read_file"] == 1


# ---------------------------------------------------------------- slash commands

def test_undo_deletes_last_turn(db_path, capsys):
    sid = dbmod.create_session(db_path, "/tmp/w")
    user_id = _seed_turn(db_path, sid)
    res = _run("/undo", session_id=sid, db_path=db_path, workdir="/tmp/w")
    assert res["action"] == "skip"
    remaining = dbmod.get_all_messages(db_path, sid)
    assert len(remaining) == 2  # system + user
    out = capsys.readouterr().out
    assert "dibatalkan" in out


def test_undo_no_turn(db_path, capsys):
    sid = dbmod.create_session(db_path, "/tmp/w")
    res = _run("/undo", db_path=db_path, workdir="/tmp/w")
    assert res["action"] == "skip"
    out = capsys.readouterr().out
    assert "tidak ada giliran" in out


def test_retry_returns_retry_action_and_keeps_user(db_path):
    sid = dbmod.create_session(db_path, "/tmp/w")
    user_id = _seed_turn(db_path, sid)
    res = _run("/retry", session_id=sid, db_path=db_path, workdir="/tmp/w")
    assert res["action"] == "retry"
    assert res["session_id"] == sid
    # Pesan user dipertahankan, balasan dihapus.
    remaining = dbmod.get_all_messages(db_path, sid)
    roles = [m["role"] for m in remaining]
    assert "user" in roles
    assert remaining[-1]["role"] == "user"
    assert remaining[-1]["kind"] == "chat"


def test_retry_no_turn(db_path, capsys):
    sid = dbmod.create_session(db_path, "/tmp/w")
    res = _run("/retry", db_path=db_path, workdir="/tmp/w")
    assert res["action"] == "skip"
    out = capsys.readouterr().out
    assert "tidak ada giliran" in out


def test_search_slash(db_path, capsys):
    sid = dbmod.create_session(db_path, "/tmp/w", title="Sesi")
    dbmod.add_message(db_path, sid, "user", "instalasi termux", kind="chat")
    res = _run("/search termux", db_path=db_path, workdir="/tmp/w")
    assert res["action"] == "skip"
    out = capsys.readouterr().out
    assert "instalasi termux" in out


def test_search_no_arg(db_path, capsys):
    res = _run("/search", db_path=db_path, workdir="/tmp/w")
    assert res["action"] == "skip"
    out = capsys.readouterr().out
    assert "query" in out


def test_personality_set(tmp_path, capsys):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    res = _run("/personality kamu ramah dan ringkas")
    assert res["action"] == "skip"
    cfg = config.load_user_config()
    assert cfg["personality"] == "kamu ramah dan ringkas"
    out = capsys.readouterr().out
    assert "personality" in out


def test_personality_remove(tmp_path, capsys):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    _run("/personality halo")
    res = _run("/personality")
    assert res["action"] == "skip"
    cfg = config.load_user_config()
    assert "personality" not in cfg


def test_usage_slash(db_path, capsys):
    sid = dbmod.create_session(db_path, "/tmp/w")
    dbmod.add_message(db_path, sid, "assistant", "t", kind="tool_call",
                      meta={"tool_name": "bash", "token_estimate": 100})
    res = _run("/usage", db_path=db_path, workdir="/tmp/w")
    assert res["action"] == "skip"
    out = capsys.readouterr().out
    assert "total token" in out


# ---------------------------------------------------------------- personality injection

def test_system_prompt_injects_personality(tmp_path):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    config.save_user_config(personality="kamu sangat teliti")
    prompt = system_prompt.build_system_prompt("/tmp/w", skills_dir=str(tmp_path / "skills"))
    assert "PERSONA: kamu sangat teliti" in prompt


def test_system_prompt_no_personality(tmp_path):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    prompt = system_prompt.build_system_prompt("/tmp/w", skills_dir=str(tmp_path / "skills"))
    assert "PERSONA:" not in prompt
