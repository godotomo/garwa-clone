"""
test_context_manager.py
Uji manajemen context window (garwa/context_manager.py).

Fokus:
- build_context_messages: urutan system/summary/tail, filter role.
- _pairing_safe_split: tidak pernah memisah pasangan tool_call/tool_result.
- _tools_payload_tokens: estimasi token dari payload tools.
- maybe_summarize: threshold, retry, penyimpanan summary (dengan mock request).
- prepare_context_messages: hard budget, ValueError pada window kecil.
"""

import json

import pytest
import requests

from garwa import context_manager as cm
from garwa import db as dbmod


# ---------------------------------------------------------------- helpers

def _msg(db_path, sid, role, content, kind="chat"):
    return dbmod.add_message(db_path, sid, role, content, kind)


# ------------------------------------------------- build_context_messages

def test_build_context_messages_plain(db_path, session_id):
    dbmod.add_message(db_path, session_id, "user", "halo")
    dbmod.add_message(db_path, session_id, "assistant", "hai")
    msgs = cm.build_context_messages(db_path, session_id, "SYS")
    assert msgs[0] == {"role": "system", "content": "SYS"}
    assert msgs[1:] == [
        {"role": "user", "content": "halo"},
        {"role": "assistant", "content": "hai"},
    ]


def test_build_context_messages_filters_non_chat_roles(db_path, session_id):
    # Baris dengan role selain user/assistant harus diabaikan.
    dbmod.add_message(db_path, session_id, "user", "halo")
    dbmod.add_message(db_path, session_id, "tool_result", "hasil", kind="tool_result")
    msgs = cm.build_context_messages(db_path, session_id, "SYS")
    contents = [m["content"] for m in msgs]
    assert "hasil" not in contents


def test_build_context_messages_includes_summary(db_path, session_id):
    dbmod.add_message(db_path, session_id, "user", "pesan lama")
    dbmod.add_message(db_path, session_id, "assistant", "respon lama")
    dbmod.save_summary(db_path, session_id, 2, "RINGKASAN")
    dbmod.add_message(db_path, session_id, "user", "pesan baru")
    msgs = cm.build_context_messages(db_path, session_id, "SYS")
    # system + ringkasan(user) + ack(assistant) + pesan baru
    assert msgs[0]["role"] == "system"
    assert "RINGKASAN" in msgs[1]["content"]
    assert msgs[2]["role"] == "assistant"
    assert msgs[3] == {"role": "user", "content": "pesan baru"}
    # pesan lama tidak boleh ikut karena sudah tercakup summary
    assert "pesan lama" not in [m["content"] for m in msgs]


# ------------------------------------------------- _pairing_safe_split

def test_pairing_safe_split_no_tool_result():
    rows = [{"kind": "chat"}, {"kind": "chat"}, {"kind": "chat"}]
    assert cm._pairing_safe_split(rows, 2) == 2


def test_pairing_safe_split_avoids_splitting_tool_pair():
    # rows[2] adalah tool_result -> split harus digeser mundur.
    rows = [
        {"kind": "chat"},
        {"kind": "chat"},
        {"kind": "tool_result"},
        {"kind": "chat"},
    ]
    assert cm._pairing_safe_split(rows, 2) == 1


def test_pairing_safe_split_at_edges():
    rows = [{"kind": "tool_result"}, {"kind": "chat"}]
    # split_at=1 -> rows[1] chat, aman
    assert cm._pairing_safe_split(rows, 1) == 1
    # split_at di posisi 0 tidak boleh berubah (loop butuh 0 < split_at)
    assert cm._pairing_safe_split(rows, 0) == 0


# ------------------------------------------------- _tools_payload_tokens

def test_tools_payload_tokens_empty():
    assert cm._tools_payload_tokens(None) == 0
    assert cm._tools_payload_tokens({}) == 0
    assert cm._tools_payload_tokens([]) == 0


def test_tools_payload_tokens_counts_json():
    payload = {"tools": [{"type": "function", "function": {"name": "x"}}]}
    n = cm._tools_payload_tokens(payload)
    assert n > 0
    # Harus konsisten dengan count_tokens dari representasi JSON.
    expected = cm.token_utils.count_tokens(json.dumps(payload, ensure_ascii=False))
    assert n == expected


# ------------------------------------------------- maybe_summarize

def test_maybe_summarize_noop_when_under_threshold(db_path, session_id):
    dbmod.add_message(db_path, session_id, "user", "pendek")
    called = []

    def fake_summarize(url, model, text, api_key="", progress=None):
        called.append(text)
        return "ringkasan"

    cm._summarize_text = fake_summarize
    result = cm.maybe_summarize(
        db_path, session_id, "http://x", "model", context_window_tokens=100000
    )
    assert result is False
    assert called == []  # tidak boleh memanggil server


def test_maybe_summarize_skips_when_history_short(db_path, session_id):
    # Banyak pesan tapi pendek -> threshold token tidak terpenuhi.
    for i in range(30):
        dbmod.add_message(db_path, session_id, "user", "x")
    called = []

    def fake_summarize(url, model, text, api_key="", progress=None):
        called.append(text)
        return "ringkasan"

    cm._summarize_text = fake_summarize
    result = cm.maybe_summarize(
        db_path, session_id, "http://x", "model", context_window_tokens=100000
    )
    assert result is False
    assert called == []


def test_maybe_summarize_triggers_and_saves(db_path, session_id):
    # Banyak pesan panjang + window kecil -> harus memicu ringkasan.
    for i in range(30):
        dbmod.add_message(db_path, session_id, "user", "kata " * 50)
    called = []

    def fake_summarize(url, model, text, api_key="", progress=None):
        called.append(text)
        return "RINGKASAN BARU"

    cm._summarize_text = fake_summarize
    result = cm.maybe_summarize(
        db_path, session_id, "http://x", "model", context_window_tokens=2000
    )
    assert result is True
    assert len(called) == 1
    summary = dbmod.get_latest_summary(db_path, session_id)
    assert summary is not None
    assert summary["summary_text"] == "RINGKASAN BARU"
    # upto_message_id harus menunjuk pesan terakhir yang diringkas.
    assert summary["upto_message_id"] >= 1


def test_maybe_summarize_handles_failure_gracefully(db_path, session_id, monkeypatch):
    for i in range(30):
        dbmod.add_message(db_path, session_id, "user", "kata " * 50)

    def boom(url, model, text, api_key="", progress=None):
        raise requests.Timeout("server timeout")

    monkeypatch.setattr(cm, "_summarize_text", boom)
    result = cm.maybe_summarize(
        db_path, session_id, "http://x", "model", context_window_tokens=2000
    )
    assert result is False
    assert dbmod.get_latest_summary(db_path, session_id) is None


# ------------------------------------------------- prepare_context_messages

def test_prepare_context_messages_rejects_small_window(db_path, session_id):
    with pytest.raises(ValueError):
        cm.prepare_context_messages(
            db_path, session_id, "SYS", "http://x", "model",
            context_window_tokens=100,
        )


def test_prepare_context_messages_returns_messages(db_path, session_id):
    dbmod.add_message(db_path, session_id, "user", "halo")
    msgs = cm.prepare_context_messages(
        db_path, session_id, "SYS", "http://x", "model", context_window_tokens=100000
    )
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "SYS"


def test_prepare_context_messages_enforces_hard_budget(db_path, session_id):
    # Banyak pesan panjang dengan window kecil -> harus dipangkas.
    for i in range(50):
        dbmod.add_message(db_path, session_id, "user", "kata " * 100)
    msgs = cm.prepare_context_messages(
        db_path, session_id, "SYS", "http://x", "model", context_window_tokens=3000
    )
    total = cm.token_utils.count_messages_tokens(msgs)
    assert total <= 3000 - cm.RESERVE_FOR_RESPONSE
    # system message selalu dipertahankan.
    assert msgs[0]["role"] == "system"
