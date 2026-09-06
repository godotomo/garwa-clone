"""tests/test_sub_agent.py
Test untuk tool sub-agent `spawn_agent` (rilis v0.5.0).

Berfokus pada bagian yang bisa diuji tanpa memanggil LLM sungguhan:
  - `create_sub_session` menghasilkan id ber-awalan `sub_` dan sesi valid.
  - `_resolve_role` memilih prompt yang tepat (general default, explore,
    fallback ke general untuk role tak dikenal).
  - Tool `spawn_agent` terdaftar di TOOLS dengan schema yang benar.
  - `tool_spawn_agent` menolak task kosong tanpa menyentuh LLM.
"""
import pytest

from garwa import db as dbmod
from garwa.tools import TOOLS
from garwa.tools.sub_agent import ROLE_PROMPTS, _resolve_role, tool_spawn_agent


def test_create_sub_session_prefix(db_path):
    sid = dbmod.create_sub_session(db_path, workdir="/tmp/sub-workdir", title="sub-agent:general")
    assert sid.startswith("sub_")
    sess = dbmod.get_session(db_path, sid)
    assert sess is not None
    assert sess["workdir"] == "/tmp/sub-workdir"
    assert sess["title"] == "sub-agent:general"
    assert sess["ended"] == 0


def test_create_sub_session_unique(db_path):
    a = dbmod.create_sub_session(db_path, workdir="/tmp/x")
    b = dbmod.create_sub_session(db_path, workdir="/tmp/x")
    assert a != b


def test_create_sub_session_isolated_from_normal(db_path):
    normal = dbmod.create_session(db_path, workdir="/tmp/x")
    sub = dbmod.create_sub_session(db_path, workdir="/tmp/x")
    assert not normal.startswith("sub_")
    assert sub.startswith("sub_")


def test_resolve_role_general_default():
    assert _resolve_role("") == ROLE_PROMPTS["general"]
    assert _resolve_role(None) == ROLE_PROMPTS["general"]
    assert _resolve_role("general") == ROLE_PROMPTS["general"]


def test_resolve_role_explore():
    assert _resolve_role("explore") == ROLE_PROMPTS["explore"]
    assert _resolve_role("EXPLORE") == ROLE_PROMPTS["explore"]
    assert _resolve_role(" Explore ") == ROLE_PROMPTS["explore"]


def test_resolve_role_unknown_falls_back_to_general():
    assert _resolve_role("nonexistent-role") == ROLE_PROMPTS["general"]


def test_spawn_agent_registered_in_tools():
    assert "spawn_agent" in TOOLS
    spec = TOOLS["spawn_agent"]
    assert spec["handler"] is tool_spawn_agent
    assert spec["destructive"] is False
    schema = spec["schema"]
    assert schema["name"] == "spawn_agent"
    props = schema["inputSchema"]["properties"]
    assert "task" in props
    assert "role" in props
    assert "max_iters" in props
    assert schema["inputSchema"]["required"] == ["task"]


def test_spawn_agent_rejects_empty_task(monkeypatch):
    # Pastikan tanpa DB_PATH pun, task kosong ditolak lebih dulu (tidak
    # menyentuh LLM / tidak crash).
    monkeypatch.delenv("GARWA_DB_PATH", raising=False)
    result = tool_spawn_agent("")
    assert result.startswith("[ERROR]")
    assert "task" in result


def test_spawn_agent_requires_db_path(monkeypatch):
    # Task valid tapi DB_PATH belum diset -> error yang jelas, bukan crash.
    monkeypatch.delenv("GARWA_DB_PATH", raising=False)
    from garwa.tools import _state as tstate
    old_db = tstate.DB_PATH
    old_work = tstate.WORKDIR
    try:
        tstate.DB_PATH = ""
        result = tool_spawn_agent("kerjakan sesuatu")
        assert result.startswith("[ERROR]")
        assert "DB_PATH" in result
    finally:
        tstate.DB_PATH = old_db
        tstate.WORKDIR = old_work
