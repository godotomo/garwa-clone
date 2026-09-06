"""tests/test_sub_agent_stress.py
Stress test untuk tool sub-agent `spawn_agent` (rilis v0.5.0).

Tujuan: menguji STABILITAS dan ISOLASI sub-agent tanpa memanggil server model
sungguhan (menghemat token/biaya). `call_llama_server` dimock sehingga
sub-agent bisa dijalankan berkali-kali dengan cepat dan deterministik.

Yang diuji:
  - Menjalankan BANYAK sub-agent berturut-turut (sekuensial) tidak crash.
  - Setiap sub-agent membuat sub-session terpisah (`sub_<hex>`) di DB.
  - Final report dari sub-agent dikembalikan dengan benar.
  - State per-session (ContextVar) terisolasi: menjalankan sub-agent tidak
    mencemari state sesi induk.
  - Tool `spawn_agent` menolak input invalid dengan rapi (bukan crash).
"""
import json

import pytest

from garwa import db as dbmod
from garwa.cli import _state as cli_state
from garwa.tools import _state as tstate
from garwa.tools.sub_agent import tool_spawn_agent


# ---------------------------------------------------------------------------
# Mock LLM: mengembalikan satu tool_call lalu jawaban akhir.
# ---------------------------------------------------------------------------
class _FakeLLM:
    """Simulasi respon model. Urutan respon dikontrol via `responses`.

    Setiap elemen `responses` adalah dict:
      {"type": "tool", "name": "...", "arguments": {...}}
      {"type": "answer", "text": "..."}
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, url, model, messages, stream=True, api_key="",
                 debug=False, temperature=0.2):
        self.calls += 1
        if not self.responses:
            return "Selesai."
        step = self.responses.pop(0)
        if step["type"] == "tool":
            args_json = json.dumps(step["arguments"], ensure_ascii=False)
            return (
                f"<tool_call>\n"
                f"{json.dumps({'name': step['name'], 'arguments': args_json}, ensure_ascii=False)}\n"
                f"</tool_call>"
            )
        return step["text"]


@pytest.fixture
def fake_llm(monkeypatch):
    """Pasang mock call_llama_server di agent_loop."""
    def _install(responses):
        fake = _FakeLLM(responses)
        monkeypatch.setattr(
            "garwa.cli.agent_loop.call_llama_server", fake
        )
        return fake
    return _install


@pytest.fixture
def sub_state(db_path):
    """Set state tools (DB_PATH, WORKDIR, SESSION_ID) untuk sub-agent."""
    old_db = tstate.DB_PATH
    old_work = tstate.WORKDIR
    old_sid = tstate.SESSION_ID
    tstate.DB_PATH = db_path
    tstate.WORKDIR = "/tmp/stress-workdir"
    tstate.SESSION_ID = "parent-session"
    yield
    tstate.DB_PATH = old_db
    tstate.WORKDIR = old_work
    tstate.SESSION_ID = old_sid


def _count_sub_sessions(db_path):
    """Hitung sesi ber-awalan `sub_` di DB."""
    rows = dbmod.list_sessions(db_path)
    return sum(1 for r in rows if r["id"].startswith("sub_"))


def _count_parent_sessions(db_path):
    rows = dbmod.list_sessions(db_path)
    return sum(1 for r in rows if not r["id"].startswith("sub_"))


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

def test_spawn_runs_and_returns_final_report(fake_llm, sub_state, db_path):
    """Sub-agent dengan satu tool_call lalu jawaban akhir mengembalikan
    final report dan membuat sub-session."""
    fake = fake_llm([
        {"type": "tool", "name": "local_now", "arguments": {}},
        {"type": "answer", "text": "Laporan: pekerjaan selesai."},
    ])
    result = tool_spawn_agent("kerjakan riset singkat", role="general")
    assert "FINAL REPORT" in result
    assert "Laporan: pekerjaan selesai." in result
    assert fake.calls >= 2
    # Sub-session dibuat.
    assert _count_sub_sessions(db_path) == 1


def test_spawn_multiple_sequential_no_crash(fake_llm, sub_state, db_path):
    """Menjalankan banyak sub-agent berturut-turut tidak crash dan setiap
    sub-agent punya sub-session sendiri."""
    fake = fake_llm([
        {"type": "answer", "text": "hasil-A"},
        {"type": "answer", "text": "hasil-B"},
        {"type": "answer", "text": "hasil-C"},
        {"type": "answer", "text": "hasil-D"},
        {"type": "answer", "text": "hasil-E"},
    ])
    for i in range(5):
        result = tool_spawn_agent(f"task-{i}", role="general")
        assert "FINAL REPORT" in result
        assert f"hasil-{chr(65+i)}" in result  # A,B,C,D,E
    # 5 sub-session terpisah.
    assert _count_sub_sessions(db_path) == 5


def test_spawn_isolates_state_from_parent(fake_llm, sub_state, db_path):
    """State per-session (ContextVar) sub-agent tidak mencemari sesi induk."""
    # Reset state induk ke nilai awal.
    cli_state.reset_session_state("parent-session")
    parent_before = cli_state.get_session_state()["tool_calls"]

    fake = fake_llm([
        {"type": "tool", "name": "local_now", "arguments": {}},
        {"type": "answer", "text": "laporan sub"},
    ])
    tool_spawn_agent("task", role="general")

    # State induk tidak bertambah karena sub-agent memakai context sendiri
    # (tool_calls sub-agent tidak bocor ke parent).
    parent_after = cli_state.get_session_state()["tool_calls"]
    assert parent_after == parent_before


def test_spawn_creates_isolated_sub_session(fake_llm, sub_state, db_path):
    """Sub-session dibuat terpisah, tidak menambah sesi induk."""
    # Buat satu sesi induk.
    parent = dbmod.create_session(db_path, workdir="/tmp/stress-workdir", title="parent")
    assert _count_parent_sessions(db_path) == 1

    fake = fake_llm([
        {"type": "answer", "text": "laporan"},
    ])
    result = tool_spawn_agent("task", role="explore")
    assert "FINAL REPORT" in result

    # Sesi induk tetap 1, sub-session bertambah 1.
    assert _count_parent_sessions(db_path) == 1
    assert _count_sub_sessions(db_path) == 1


def test_spawn_handles_llm_error_gracefully(fake_llm, sub_state, db_path):
    """Kalau LLM melempar exception, sub-agent mengembalikan pesan error
    (bukan crash ke caller)."""
    def _boom(*a, **k):
        raise RuntimeError("server down")
    import garwa.cli.agent_loop as al
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(al, "call_llama_server", _boom)
    try:
        result = tool_spawn_agent("task", role="general")
    finally:
        monkeypatch.undo()
    assert result.startswith("[SUB-AGENT:general]")
    assert "RuntimeError" in result or "server down" in result


def test_spawn_rejects_invalid_task(sub_state):
    """Task kosong ditolak tanpa menyentuh LLM."""
    result = tool_spawn_agent("")
    assert result.startswith("[ERROR]")
    assert "task" in result


def test_spawn_role_explore_uses_explore_prompt(fake_llm, sub_state, db_path):
    """Role `explore` memakai system prompt explore (memeriksa bahwa sub-agent
    tidak crash dan mengembalikan report)."""
    fake = fake_llm([
        {"type": "answer", "text": "temuan eksplorasi"},
    ])
    result = tool_spawn_agent("petakan struktur modul", role="explore")
    assert "FINAL REPORT" in result
    assert "temuan eksplorasi" in result
    assert _count_sub_sessions(db_path) == 1
