"""tests/test_ndjson.py
Test untuk emitter NDJSON output terstruktur (`--json`).

Berfokus pada bagian yang bisa diuji tanpa memanggil LLM sungguhan:
  - NDJSONEmitter menulis SATU objek JSON per baris dengan field `type` dan
    `seq` yang bertambah.
  - emit() global no-op kalau emitter belum di-setup (aman dipanggil dari
    agent_loop walau --json tidak aktif).
  - suppress_human_output mengalihkan sys.stdout ke buffer (output manusia
    diredam) TANPA mengganggu emitter yang menulis ke sys.__stdout__.
  - setup() mengembalikan emitter dan mengaktifkan emit() global.
"""
import io
import json
import sys

import pytest

from garwa.cli.ndjson import (
    NDJSONEmitter,
    emit,
    get_emitter,
    setup,
    suppress_human_output,
)


def test_emitter_writes_one_json_per_line():
    buf = io.StringIO()
    em = NDJSONEmitter(buf)
    em.emit("session_start", session_id="s1", workdir="/tmp")
    em.emit("assistant", text="halo")
    em.emit("tool_call", name="bash", arguments={"cmd": "ls"})
    lines = buf.getvalue().strip().split("\n")
    assert len(lines) == 3
    recs = [json.loads(l) for l in lines]
    # field type & seq
    assert [r["type"] for r in recs] == ["session_start", "assistant", "tool_call"]
    assert [r["seq"] for r in recs] == [1, 2, 3]
    # field tambahan
    assert recs[0]["session_id"] == "s1"
    assert recs[1]["text"] == "halo"
    assert recs[2]["arguments"] == {"cmd": "ls"}


def test_emitter_ensure_ascii_false():
    buf = io.StringIO()
    em = NDJSONEmitter(buf)
    em.emit("assistant", text="halo dunia 你好")
    rec = json.loads(buf.getvalue().strip())
    assert rec["text"] == "halo dunia 你好"


def test_emit_global_noop_without_setup():
    # Sebelum setup, emit() global tidak melakukan apa-apa (tidak crash).
    get_emitter()  # mungkin None
    emit("assistant", text="x")  # harus no-op


def test_setup_activates_global_emit():
    buf = io.StringIO()
    em = setup(buf)
    assert get_emitter() is em
    emit("summary", tool_calls=2, errors=0)
    rec = json.loads(buf.getvalue().strip())
    assert rec["type"] == "summary"
    assert rec["tool_calls"] == 2


def test_suppress_human_output_redirects_stdout():
    buf = io.StringIO()
    setup(buf)  # emitter menulis ke buf (bukan sys.__stdout__)
    original = sys.stdout
    with suppress_human_output():
        # sys.stdout sekarang buffer null (berbeda dari aslinya)
        assert sys.stdout is not original
        print("ini output manusia yang harus diredam")
    # stdout pulih ke nilai sebelum context
    assert sys.stdout is original
    # Emitter tetap bisa menulis ke bufernya sendiri.
    emit("assistant", text="tetap keluar")
    rec = json.loads(buf.getvalue().strip().split("\n")[-1])
    assert rec["type"] == "assistant"


def test_suppress_human_output_restores_on_exception():
    original = sys.stdout
    with pytest.raises(RuntimeError):
        with suppress_human_output():
            raise RuntimeError("boom")
    assert sys.stdout is original
