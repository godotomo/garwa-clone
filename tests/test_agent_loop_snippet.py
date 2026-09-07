"""test_agent_loop_snippet.py
Integrasi P3: saat tool 'check' error di agent_loop, snippet konteks AST
otomatis disisipkan ke tool_result berikutnya (poor-man's LSP).

Prinsip:
  - Mock call_llama_server supaya model memanggil tool 'check' pada file
    Python invalid, lalu berhenti (tidak panggil tool lagi).
  - Verifikasi bahwa pesan tool_result yang disimpan ke DB berisi snippet
    konteks (baris error) — baik dari tool_check sendiri maupun guard loop.
"""

import argparse
import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from garwa.cli import agent_loop as al  # noqa: E402
from garwa.cli import _state as state  # noqa: E402
from garwa.tools import _state as tstate  # noqa: E402
from garwa import db as dbmod  # noqa: E402


class _FakeLLM:
    """Mengembalikan tool_call 'check' sekali, lalu jawaban teks final."""

    def __init__(self, check_args):
        self.check_args = check_args
        self.calls = 0

    def __call__(self, *a, **kw):
        self.calls += 1
        if self.calls == 1:
            return (
                "<tool_call>\n"
                + json.dumps(
                    {"name": "check", "arguments": self.check_args},
                    ensure_ascii=False,
                )
                + "\n</tool_call>"
            )
        return "Selesai, sudah diperiksa."


@pytest.fixture
def fake_llm(monkeypatch):
    def _install(check_args):
        fake = _FakeLLM(check_args)
        monkeypatch.setattr(
            "garwa.cli.agent_loop.call_llama_server", fake
        )
        return fake
    return _install


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Set state tools (DB_PATH, WORKDIR, SESSION_ID) + AgentConfig."""
    old_db = tstate.DB_PATH
    old_work = tstate.WORKDIR
    old_sid = tstate.SESSION_ID
    tstate.DB_PATH = str(tmp_path / "test.db")
    tstate.WORKDIR = str(tmp_path)
    tstate.SESSION_ID = "snippet-session"
    db_path = tstate.DB_PATH
    dbmod.init_db(db_path)  # pastikan schema ada
    sid = dbmod.create_session(db_path, str(tmp_path), title="snippet-test")
    tstate.SESSION_ID = sid
    # AgentConfig minimal via argparse.Namespace (coerce_agent_config butuh ini)
    args = argparse.Namespace(
        db_path=tstate.DB_PATH,
        session_id=sid,
        auto_approve=True,
        context_window=8192,
        max_tokens=1024,
        model="test-model",
        url="http://localhost:1",
        api_key="",
        workdir=str(tmp_path),
        reasoning=False,
        temperature=0.0,
        system_prompt="test",
        verbose=False,
        no_stream=True,
        debug=False,
    )
    yield args, db_path, sid
    tstate.DB_PATH = old_db
    tstate.WORKDIR = old_work
    tstate.SESSION_ID = old_sid
    # Reset state sesi (tool_calls/token) supaya tidak bocor ke test lain.
    state.reset_session_state(old_sid)


def test_agent_loop_injects_snippet_on_check_error(fake_llm, env):
    args, db_path, sid = env
    # file Python invalid di WORKDIR
    bad_path = os.path.join(tstate.WORKDIR, "bad.py")
    with open(bad_path, "w", encoding="utf-8") as f:
        f.write("def foo(:\n    pass\n")
    fake_llm({"path": bad_path, "timeout": 30})
    al.run_agent_loop(args, sid, "test system")
    # cari pesan tool_result di DB yang berisi hasil check
    msgs = dbmod.get_all_messages(db_path, sid)
    tool_results = [m for m in msgs if m.get("kind") == "tool_result"]
    assert tool_results, "harus ada tool_result"
    combined = "\n".join(m.get("content", "") for m in tool_results)
    assert "error" in combined.lower()
    # snippet konteks AST disisipkan (dari tool_check atau guard loop)
    assert "[snippet]" in combined or "def foo(:" in combined
