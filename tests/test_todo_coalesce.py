"""Unit test koalesensi todo_write per giliran.

Latar belakang (P0): `todo_write` bersifat FULL REPLACE per workdir. Kalau
model memecah daftar todo ke beberapa blok `<tool_call>` dalam SATU respon,
eksekusi berurutan membuat blok terakhir menimpa blok sebelumnya -> todo
tersimpan PARSIAL. Bukti pra-perbaikan (tmp_repro/verify_todo_multi.py):
5 blok x 1 item -> hanya 1 baris tersimpan.
"""
import json
import os

import pytest

from garwa import db as dbmod
from garwa.cli.json_repair import extract_tool_calls
from garwa.cli.todo_coalesce import coalesce_todo_writes


def _blk(todos):
    return (
        "<tool_call>"
        + json.dumps({"name": "todo_write", "arguments": {"todos": todos}})
        + "</tool_call>"
    )


def test_single_block_untouched():
    one = [("todo_write", {"todos": [{"content": "z", "status": "pending"}]})]
    assert coalesce_todo_writes(one) is one


def test_non_todo_calls_untouched():
    calls = [("bash", {"command": "ls"}), ("read_file", {"path": "a"})]
    assert coalesce_todo_writes(calls) is calls


def test_five_blocks_x_one_item_merged_into_one():
    todos = [{"content": f"task {ch}", "status": "done"} for ch in "ABCDE"]
    calls = extract_tool_calls("\n".join(_blk([t]) for t in todos))
    assert len(calls) == 5

    merged = coalesce_todo_writes(calls)
    assert len(merged) == 1
    assert merged[0][0] == "todo_write"
    assert [i["content"] for i in merged[0][1]["todos"]] == [t["content"] for t in todos]
    assert all(i["status"] == "done" for i in merged[0][1]["todos"])


def test_merge_preserves_surrounding_order_and_keeps_first_position():
    mixed = [
        ("todo_write", {"todos": [{"content": "x", "status": "done"}]}),
        ("bash", {"command": "echo hi"}),
        ("todo_write", {"todos": [{"content": "y", "status": "pending"}]}),
    ]
    merged = coalesce_todo_writes(mixed)
    assert [n for n, _ in merged] == ["todo_write", "bash"]
    assert merged[0][1]["todos"] == [
        {"content": "x", "status": "done"},
        {"content": "y", "status": "pending"},
    ]


def test_duplicate_content_later_block_wins():
    dup = [
        ("todo_write", {"todos": [{"content": "a", "status": "pending"}]}),
        ("todo_write", {"todos": [{"content": "a", "status": "done"}]}),
    ]
    merged = coalesce_todo_writes(dup)
    assert merged[0][1]["todos"] == [{"content": "a", "status": "done"}]


def test_string_items_and_json_string_args():
    dup = [
        ("todo_write", {"todos": ["plain string"]}),
        ("todo_write", {"todos": json.dumps([{"content": "b", "status": "done"}])}),
    ]
    merged = coalesce_todo_writes(dup)
    assert merged[0][1]["todos"] == [
        {"content": "plain string", "status": "pending"},
        {"content": "b", "status": "done"},
    ]


def test_unparseable_args_falls_back_to_original():
    calls = [
        ("todo_write", {"todos": "bukan json sama sekali"}),
        ("todo_write", {"todos": "juga bukan json"}),
    ]
    assert coalesce_todo_writes(calls) is calls


def test_on_merge_callback_reports_counts():
    seen = []
    todos = [{"content": "a", "status": "done"}, {"content": "b", "status": "done"}]
    calls = [("todo_write", {"todos": [t]}) for t in todos]
    coalesce_todo_writes(calls, on_merge=lambda n, m: seen.append((n, m)))
    assert seen == [(2, 2)]


def test_on_merge_callback_exception_does_not_break():
    calls = [
        ("todo_write", {"todos": [{"content": "a", "status": "done"}]}),
        ("todo_write", {"todos": [{"content": "b", "status": "done"}]}),
    ]

    def boom(_n, _m):
        raise RuntimeError("callback rusak")

    merged = coalesce_todo_writes(calls, on_merge=boom)
    assert len(merged) == 1
    assert len(merged[0][1]["todos"]) == 2


def test_end_to_end_all_todos_persisted(tmp_path):
    """Regression inti: 5 blok x 1 item harus tersimpan 5/5, bukan 1/5."""
    from garwa.tools import _state as tstate
    from garwa.tools.session_tools import tool_todo_write

    dbp = str(tmp_path / "todos.db")
    dbmod.init_db(dbp)

    todos = [{"content": f"task {ch}", "status": "done"} for ch in "ABCDE"]
    calls = extract_tool_calls("\n".join(_blk([t]) for t in todos))
    merged = coalesce_todo_writes(calls)

    old = (tstate.DB_PATH, tstate.WORKDIR, tstate.SESSION_ID)
    try:
        tstate.DB_PATH = dbp
        tstate.WORKDIR = str(tmp_path)
        tstate.SESSION_ID = "sess-1"
        for name, args in merged:
            out = tool_todo_write(args["todos"])
            assert out.startswith("[OK]"), out
        rows = dbmod.get_todos(dbp, workdir=str(tmp_path))
    finally:
        tstate.DB_PATH, tstate.WORKDIR, tstate.SESSION_ID = old

    assert len(rows) == 5, f"todo tersimpan parsial: {len(rows)}/5"
    assert {r["content"] for r in rows} == {f"task {ch}" for ch in "ABCDE"}
    assert all(r["status"] == "done" for r in rows)


if __name__ == "__main__":
    raise SystemExit(pytest.main([os.path.abspath(__file__), "-q"]))


def test_coalesce_merges_remove_argument():
    """`remove` WAJIB ikut saat blok digabung.

    Kalau tidak, permintaan buang eksplisit pada blok kedua/ketiga hilang
    begitu koalesensi menyatukan semuanya menjadi satu panggilan.
    """
    calls = [
        ("todo_write", {"todos": [{"content": "a", "status": "pending"}]}),
        ("todo_write", {"todos": [{"content": "b", "status": "pending"}], "remove": "lama1"}),
        ("todo_write", {"todos": [], "remove": ["lama2", "a"]}),
    ]
    merged = coalesce_todo_writes(calls)
    assert len(merged) == 1
    name, args = merged[0]
    assert name == "todo_write"
    assert {t["content"] for t in args["todos"]} == {"a", "b"}
    assert args["remove"] == ["lama1", "lama2", "a"]


def test_coalesce_remove_only_does_not_drop_call():
    """Blok `todo_write` yang HANYA membuang item (todos kosong) tetap dijalankan."""
    calls = [
        ("todo_write", {"todos": [], "remove": ["x"]}),
        ("todo_write", {"todos": [], "remove": ["y"]}),
    ]
    merged = coalesce_todo_writes(calls)
    assert len(merged) == 1
    assert merged[0][1]["remove"] == ["x", "y"]
