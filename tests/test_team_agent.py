"""tests/test_team_agent.py
Test untuk koordinator Agent Teams `team_run`.

Berfokus pada bagian yang bisa diuji tanpa memanggil LLM sungguhan:
  - `tool_team_run` terdaftar di TOOLS dengan schema yang benar.
  - Validasi argumen: members kosong, bukan list, item bukan dict, agentId
    kosong, task kosong, rolePrompt kosong (fallback ke default).
  - Koordinator menghasilkan header/laporan terstruktur.
  - Anggota dengan task kosong ditolak sebelum menyentuh LLM.
"""
import pytest

from garwa.tools import TOOLS
from garwa.tools.team_agent import tool_team_run


def test_team_run_registered():
    assert "team_run" in TOOLS
    schema = TOOLS["team_run"]["schema"]
    assert schema["name"] == "team_run"
    props = schema["inputSchema"]["properties"]
    assert "members" in props
    assert "objective" in props
    assert "max_workers" in props
    # members wajib
    assert "members" in schema["inputSchema"]["required"]


def test_team_run_members_required():
    # members kosong / None
    assert "[ERROR]" in tool_team_run(members=[])
    assert "[ERROR]" in tool_team_run(members=None)


def test_team_run_members_not_list():
    assert "[ERROR]" in tool_team_run(members="bukan-list")


def test_team_run_member_not_dict():
    res = tool_team_run(members=["bukan-dict"])
    assert "[ERROR]" in res
    assert "objek" in res


def test_team_run_missing_agent_id():
    res = tool_team_run(members=[{"task": "x", "rolePrompt": "y"}])
    assert "[ERROR]" in res
    assert "agentId" in res


def test_team_run_missing_task():
    res = tool_team_run(members=[{"agentId": "a", "rolePrompt": "y"}])
    assert "[ERROR]" in res
    assert "task" in res


def test_team_run_missing_role_prompt_fallback(monkeypatch):
    # rolePrompt kosong -> fallback ke default, tidak error.
    # Mock runner sub-agent supaya test TIDAK memanggil LLM sungguhan.
    monkeypatch.setattr(
        "garwa.tools.team_agent._run_sub_agent_with_system",
        lambda **kw: "laporan-mock",
    )
    res = tool_team_run(members=[{"agentId": "a", "task": "x"}])
    assert "[TEAM]" in res


def test_team_run_header_and_structure(monkeypatch):
    # Uji struktur header/laporan TANPA memanggil LLM: mock runner sub-agent.
    # (Sebelumnya test ini mengandalkan asumsi DB_PATH kosong, padahal
    #  DB_PATH punya default ~/.garwa/garwa.db sehingga memicu panggilan LLM
    #  nyata dan menggantung.)
    monkeypatch.setattr(
        "garwa.tools.team_agent._run_sub_agent_with_system",
        lambda **kw: f"laporan-{kw.get('role')}",
    )
    res = tool_team_run(
        members=[
            {"agentId": "arsitek", "rolePrompt": "Anda arsitek", "task": "t1"},
            {"agentId": "reviewer", "rolePrompt": "Anda reviewer", "task": "t2"},
        ],
        objective="Bangun fitur X",
    )
    assert "[TEAM] 2 anggota tim selesai" in res
    assert "Objective: Bangun fitur X" in res
    assert "=== Anggota: arsitek" in res
    assert "=== Anggota: reviewer" in res
    assert "laporan-arsitek" in res
    assert "laporan-reviewer" in res
