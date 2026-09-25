"""test_agent_loop_loop_correction.py

Regresi: saat LLM terdeteksi degenerate loop (RepetitionLoopError), percobaan
berikutnya HARUS menerima instruksi koreksi di percakapan -- bukan konteks
identik. Tanpa ini, model mengulang pola yang sama dan seluruh retry
(termasuk giliran) berakhir sia-sia.
"""

import argparse
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from garwa.cli import agent_loop as al  # noqa: E402
from garwa.cli import _state as state  # noqa: E402
from garwa.cli.llm_errors import RepetitionLoopError  # noqa: E402
from garwa.tools import _state as tstate  # noqa: E402
from garwa import db as dbmod  # noqa: E402


class _LoopThenFinal:
    """Percobaan 1 -> RepetitionLoopError; percobaan 2 -> jawaban final."""

    def __init__(self):
        self.calls = 0

    def __call__(self, *a, **kw):
        self.calls += 1
        if self.calls == 1:
            raise RepetitionLoopError("degenerate loop untuk test")
        return "Selesai, sudah dikoreksi."


@pytest.fixture
def env(tmp_path, monkeypatch):
    old_db = tstate.DB_PATH
    old_work = tstate.WORKDIR
    old_sid = tstate.SESSION_ID
    tstate.DB_PATH = str(tmp_path / "test.db")
    tstate.WORKDIR = str(tmp_path)
    db_path = tstate.DB_PATH
    dbmod.init_db(db_path)
    sid = dbmod.create_session(db_path, str(tmp_path), title="loop-corr")
    tstate.SESSION_ID = sid
    args = argparse.Namespace(
        db_path=db_path,
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
    # Jangan benar-benar tidur di test.
    monkeypatch.setattr(state, "LOOP_BREAK_COOLDOWN_SECONDS", 0)
    yield args, db_path, sid
    tstate.DB_PATH = old_db
    tstate.WORKDIR = old_work
    tstate.SESSION_ID = old_sid
    state.reset_session_state(sid)


def test_loop_error_injects_correction_message(env, monkeypatch):
    args, db_path, sid = env
    fake = _LoopThenFinal()
    monkeypatch.setattr("garwa.cli.agent_loop.call_llama_server", fake)

    al.run_agent_loop(args, sid, "test system")

    assert fake.calls >= 2, "harus retry setelah RepetitionLoopError"
    msgs = dbmod.get_all_messages(db_path, sid)
    combined = "\n".join(m.get("content", "") for m in msgs)
    assert "[LOOP]" in combined, (
        "percakapan harus memuat koreksi [LOOP] agar model tidak mengulang "
        "pola yang sama pada percobaan berikutnya"
    )
    assert "JANGAN mengulang" in combined
