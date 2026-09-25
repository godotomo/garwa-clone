"""test_agent_loop_malformed_stop.py

Regresi P0 (STOP senyap): saat model menulis blok `<tool_call>` tetapi JSON-nya
TIDAK valid / TERPOTONG (kurung kurawal tak berimbang), `extract_tool_calls`
mengembalikan daftar kosong. Sebelum perbaikan, giliran langsung berhenti
dengan `[STOP] Tidak ada tool_call valid dalam respon model.` tanpa memberi
model kesempatan memperbaiki diri -- user harus memaksa lanjut manual.

Setelah perbaikan: giliran menyuntikkan koreksi `[MALFORMED]` dan mencoba lagi,
dibatasi `_MAX_MALFORMED_RETRIES` supaya tidak menjadi loop tak berujung.
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
from garwa.tools import _state as tstate  # noqa: E402
from garwa import db as dbmod  # noqa: E402


# Blok tool_call dengan JSON TERPOTONG (kurung kurawal tak berimbang) --
# persis pola yang menyebabkan [STOP] senyap di produksi.
_MALFORMED = (
    "Baik, saya periksa dulu.\n\n"
    "<tool_call>\n"
    '{"name": "bash", "arguments": {"command": "sed -n \'880,960p\' file.py"\n'
    "</tool_call>"
)


class _MalformedThenFinal:
    """Percobaan 1 -> tool_call terpotong; percobaan 2 -> jawaban final."""

    def __init__(self):
        self.calls = 0

    def __call__(self, *a, **kw):
        self.calls += 1
        if self.calls == 1:
            return _MALFORMED
        return "Selesai, sudah dikoreksi."


class _AlwaysMalformed:
    """Selalu mengembalikan tool_call terpotong (untuk uji batas retry)."""

    def __init__(self):
        self.calls = 0

    def __call__(self, *a, **kw):
        self.calls += 1
        return _MALFORMED


@pytest.fixture
def env(tmp_path, monkeypatch):
    old_db = tstate.DB_PATH
    old_work = tstate.WORKDIR
    old_sid = tstate.SESSION_ID
    tstate.DB_PATH = str(tmp_path / "test.db")
    tstate.WORKDIR = str(tmp_path)
    db_path = tstate.DB_PATH
    dbmod.init_db(db_path)
    sid = dbmod.create_session(db_path, str(tmp_path), title="malformed-stop")
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
    monkeypatch.setattr(state, "LOOP_BREAK_COOLDOWN_SECONDS", 0)
    yield args, db_path, sid
    tstate.DB_PATH = old_db
    tstate.WORKDIR = old_work
    tstate.SESSION_ID = old_sid
    state.reset_session_state(sid)


def test_malformed_tool_call_triggers_retry(env, monkeypatch):
    """Tool_call terpotong TIDAK boleh langsung [STOP] -- harus retry."""
    args, db_path, sid = env
    fake = _MalformedThenFinal()
    monkeypatch.setattr("garwa.cli.agent_loop.call_llama_server", fake)

    al.run_agent_loop(args, sid, "test system")

    assert fake.calls >= 2, (
        "giliran harus mencoba lagi setelah blok tool_call terpotong, "
        "bukan langsung berhenti senyap"
    )
    msgs = dbmod.get_all_messages(db_path, sid)
    combined = "\n".join(m.get("content", "") for m in msgs)
    assert "[MALFORMED]" in combined, (
        "percakapan harus memuat koreksi [MALFORMED] agar model tahu JSON-nya "
        "rusak dan bisa memperbaikinya pada percobaan berikutnya"
    )


def test_malformed_retry_is_bounded(env, monkeypatch):
    """Retry dibatasi: tidak boleh jadi loop tak berujung."""
    args, db_path, sid = env
    fake = _AlwaysMalformed()
    monkeypatch.setattr("garwa.cli.agent_loop.call_llama_server", fake)

    al.run_agent_loop(args, sid, "test system")

    assert fake.calls == 1 + al.__dict__.get(
        "_MAX_MALFORMED_RETRIES", 2
    ) or fake.calls <= 4, (
        f"jumlah percobaan harus terbatas, bukan tak berujung (dapat {fake.calls})"
    )


def test_malformed_correction_message_mentions_truncation(env, monkeypatch):
    """Pesan koreksi harus menyebut penyebab umum + saran memecah argumen."""
    args, db_path, sid = env
    fake = _AlwaysMalformed()
    monkeypatch.setattr("garwa.cli.agent_loop.call_llama_server", fake)

    al.run_agent_loop(args, sid, "test system")

    msgs = dbmod.get_all_messages(db_path, sid)
    combined = "\n".join(m.get("content", "") for m in msgs)
    assert "TERPOTONG" in combined
    assert "PECAH" in combined
