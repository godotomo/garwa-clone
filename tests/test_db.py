"""
test_db.py
Uji lapisan persistensi SQLite (garwa/db.py).

Fokus:
- Lifecycle sesi (create → touch → end → get → list).
- Pesan (add, get_all, get_after) dan pemutakhiran updated_at sesi.
- Summary (save, get_latest).
- Todos (replace = full-replace, validasi input, get).
- Project notes (set/get dengan upsert).
- File cache (get/set dengan validasi mtime+size).
- Robustness: DB path di direktori yang belum ada.
"""

import sqlite3
import time

import pytest

from garwa import db as dbmod


# ---------------------------------------------------------------- sesi

def test_create_session_returns_unique_id(db_path):
    a = dbmod.create_session(db_path, workdir="/tmp/w", title="A")
    b = dbmod.create_session(db_path, workdir="/tmp/w", title="B")
    assert a != b
    assert len(a) == 12  # uuid4().hex[:12]


def test_create_session_creates_dir(tmp_path):
    nested = tmp_path / "a" / "b" / "c" / "db.sqlite"
    dbmod.init_db(str(nested))
    sid = dbmod.create_session(str(nested), workdir="/tmp/w")
    assert dbmod.get_session(str(nested), sid) is not None


def test_get_session_roundtrip(db_path):
    sid = dbmod.create_session(db_path, workdir="/tmp/w", title="Judul")
    row = dbmod.get_session(db_path, sid)
    assert row["id"] == sid
    assert row["workdir"] == "/tmp/w"
    assert row["title"] == "Judul"
    assert row["ended"] == 0


def test_get_session_missing_returns_none(db_path):
    assert dbmod.get_session(db_path, "tidak-ada") is None


def test_touch_session_updates_updated_at(db_path):
    sid = dbmod.create_session(db_path, "/tmp/w")
    before = dbmod.get_session(db_path, sid)["updated_at"]
    time.sleep(0.01)
    dbmod.touch_session(db_path, sid)
    after = dbmod.get_session(db_path, sid)["updated_at"]
    assert after >= before


def test_end_session_marks_ended(db_path):
    sid = dbmod.create_session(db_path, "/tmp/w")
    dbmod.end_session(db_path, sid)
    assert dbmod.get_session(db_path, sid)["ended"] == 1


def test_list_sessions_filters_by_workdir(db_path):
    s1 = dbmod.create_session(db_path, "/tmp/one")
    s2 = dbmod.create_session(db_path, "/tmp/two")
    dbmod.create_session(db_path, "/tmp/one")
    one = [s["id"] for s in dbmod.list_sessions(db_path, workdir="/tmp/one")]
    assert s1 in one
    assert s2 not in one


def test_latest_open_session(db_path):
    s1 = dbmod.create_session(db_path, "/tmp/w")
    dbmod.end_session(db_path, s1)
    s2 = dbmod.create_session(db_path, "/tmp/w")
    assert dbmod.latest_open_session(db_path, "/tmp/w")["id"] == s2


def test_latest_open_session_none_when_all_ended(db_path):
    s = dbmod.create_session(db_path, "/tmp/w")
    dbmod.end_session(db_path, s)
    assert dbmod.latest_open_session(db_path, "/tmp/w") is None


# ---------------------------------------------------------------- pesan

def test_add_message_returns_increasing_ids(db_path, session_id):
    i1 = dbmod.add_message(db_path, session_id, "user", "p1")
    i2 = dbmod.add_message(db_path, session_id, "assistant", "p2")
    assert i2 > i1


def test_get_all_messages_ordered(db_path, session_id):
    dbmod.add_message(db_path, session_id, "user", "pertama")
    dbmod.add_message(db_path, session_id, "assistant", "kedua")
    rows = dbmod.get_all_messages(db_path, session_id)
    assert [r["content"] for r in rows] == ["pertama", "kedua"]
    assert rows[0]["role"] == "user"
    assert rows[0]["kind"] == "chat"


def test_get_messages_after(db_path, session_id):
    i1 = dbmod.add_message(db_path, session_id, "user", "a")
    dbmod.add_message(db_path, session_id, "user", "b")
    dbmod.add_message(db_path, session_id, "user", "c")
    rows = dbmod.get_messages_after(db_path, session_id, i1)
    assert [r["content"] for r in rows] == ["b", "c"]


def test_add_message_updates_session_updated_at(db_path, session_id):
    before = dbmod.get_session(db_path, session_id)["updated_at"]
    time.sleep(0.01)
    dbmod.add_message(db_path, session_id, "user", "x")
    after = dbmod.get_session(db_path, session_id)["updated_at"]
    assert after > before


# ---------------------------------------------------------------- pinned

def test_message_pinned_default_false(db_path, session_id):
    i = dbmod.add_message(db_path, session_id, "user", "x")
    assert dbmod.get_message(db_path, session_id, i)["pinned"] == 0


def test_set_message_pinned_roundtrip(db_path, session_id):
    i = dbmod.add_message(db_path, session_id, "user", "penting")
    dbmod.set_message_pinned(db_path, session_id, i, True)
    assert dbmod.get_message(db_path, session_id, i)["pinned"] == 1
    dbmod.set_message_pinned(db_path, session_id, i, False)
    assert dbmod.get_message(db_path, session_id, i)["pinned"] == 0


def test_get_pinned_messages_ordered(db_path, session_id):
    a = dbmod.add_message(db_path, session_id, "user", "a")
    b = dbmod.add_message(db_path, session_id, "user", "b")
    c = dbmod.add_message(db_path, session_id, "user", "c")
    dbmod.set_message_pinned(db_path, session_id, b, True)
    dbmod.set_message_pinned(db_path, session_id, a, True)
    pinned = dbmod.get_pinned_messages(db_path, session_id)
    assert [p["id"] for p in pinned] == [a, b]
    assert [p["content"] for p in pinned] == ["a", "b"]


def test_get_pinned_messages_empty(db_path, session_id):
    dbmod.add_message(db_path, session_id, "user", "x")
    assert dbmod.get_pinned_messages(db_path, session_id) == []


def test_get_pinned_scoped_by_session(db_path):
    s1 = dbmod.create_session(db_path, "/tmp/w")
    s2 = dbmod.create_session(db_path, "/tmp/w")
    i = dbmod.add_message(db_path, s1, "user", "x")
    dbmod.set_message_pinned(db_path, s1, i, True)
    assert dbmod.get_pinned_messages(db_path, s2) == []


def test_get_message_missing_returns_none(db_path, session_id):
    assert dbmod.get_message(db_path, session_id, 9999) is None


def test_get_message_scoped_by_session(db_path):
    s1 = dbmod.create_session(db_path, "/tmp/w")
    s2 = dbmod.create_session(db_path, "/tmp/w")
    i = dbmod.add_message(db_path, s1, "user", "x")
    assert dbmod.get_message(db_path, s2, i) is None


# ---------------------------------------------------------------- summary

def test_summary_roundtrip(db_path, session_id):
    dbmod.save_summary(db_path, session_id, upto_message_id=5, summary_text="ringkas")
    s = dbmod.get_latest_summary(db_path, session_id)
    assert s["summary_text"] == "ringkas"
    assert s["upto_message_id"] == 5


def test_get_latest_summary_returns_most_recent(db_path, session_id):
    dbmod.save_summary(db_path, session_id, 3, "pertama")
    dbmod.save_summary(db_path, session_id, 7, "kedua")
    s = dbmod.get_latest_summary(db_path, session_id)
    assert s["summary_text"] == "kedua"
    assert s["upto_message_id"] == 7


def test_get_latest_summary_none_when_empty(db_path, session_id):
    assert dbmod.get_latest_summary(db_path, session_id) is None


def test_summary_roundtrip_active_instructions(db_path, session_id):
    dbmod.save_summary(
        db_path, session_id, upto_message_id=5, summary_text="ringkas",
        active_instructions=["instruksi A", "instruksi B"],
    )
    s = dbmod.get_latest_summary(db_path, session_id)
    assert s["summary_text"] == "ringkas"
    assert s["active_instructions"] == ["instruksi A", "instruksi B"]


def test_summary_active_instructions_default_empty(db_path, session_id):
    dbmod.save_summary(db_path, session_id, upto_message_id=5, summary_text="ringkas")
    s = dbmod.get_latest_summary(db_path, session_id)
    assert s["active_instructions"] == []


def test_summary_active_instructions_corrupt_json_falls_back_empty(db_path, session_id):
    # Simulasi data lama/rusak: tulis JSON tidak valid langsung ke kolom.
    dbmod.save_summary(db_path, session_id, 5, "ringkas")
    with dbmod.connect(db_path) as conn:
        conn.execute(
            "UPDATE summaries SET active_instructions = ? WHERE session_id = ?",
            ("{bukan json", session_id),
        )
    s = dbmod.get_latest_summary(db_path, session_id)
    assert s["active_instructions"] == []


# ---------------------------------------------------------------- todos

def test_replace_todos_full_replace(db_path, session_id):
    dbmod.replace_todos(db_path, session_id, [
        {"content": "a", "status": "pending"},
        {"content": "b", "status": "done"},
    ])
    dbmod.replace_todos(db_path, session_id, [{"content": "c"}])
    todos = dbmod.get_todos(db_path, session_id)
    assert len(todos) == 1
    assert todos[0]["content"] == "c"
    assert todos[0]["status"] == "pending"  # default


def test_replace_todos_preserves_order(db_path, session_id):
    dbmod.replace_todos(db_path, session_id, [
        {"content": "z", "status": "pending"},
        {"content": "a", "status": "done"},
        {"content": "m", "status": "pending"},
    ])
    todos = dbmod.get_todos(db_path, session_id)
    assert [t["content"] for t in todos] == ["z", "a", "m"]


def test_replace_todos_invalid_item_raises(db_path, session_id):
    with pytest.raises(ValueError):
        dbmod.replace_todos(db_path, session_id, [{"status": "done"}])  # tanpa content
    with pytest.raises(ValueError):
        dbmod.replace_todos(db_path, session_id, [{"content": 123}])  # content bukan str
    with pytest.raises(ValueError):
        dbmod.replace_todos(db_path, session_id, ["bukan-dict"])


def test_replace_todos_invalid_does_not_partially_write(db_path, session_id):
    # Item pertama valid, item kedua invalid -> seluruh operasi harus batal
    # (validasi dilakukan sebelum menyentuh DB).
    with pytest.raises(ValueError):
        dbmod.replace_todos(db_path, session_id, [
            {"content": "valid"},
            {"content": 999},
        ])
    assert dbmod.get_todos(db_path, session_id) == []


def test_get_todos_empty(db_path, session_id):
    assert dbmod.get_todos(db_path, session_id) == []


# ---------------------------------------------------------------- notes

def test_set_note_upsert(db_path):
    dbmod.set_note(db_path, "/tmp/w", "kunci", "nilai1")
    dbmod.set_note(db_path, "/tmp/w", "kunci", "nilai2")
    notes = dbmod.get_notes(db_path, "/tmp/w")
    assert len(notes) == 1
    assert notes[0]["value"] == "nilai2"


def test_get_notes_scoped_by_workdir(db_path):
    dbmod.set_note(db_path, "/tmp/w1", "k", "v")
    dbmod.set_note(db_path, "/tmp/w2", "k", "v")
    assert len(dbmod.get_notes(db_path, "/tmp/w1")) == 1
    assert len(dbmod.get_notes(db_path, "/tmp/w2")) == 1


# ---------------------------------------------------------------- file cache

def test_file_cache_roundtrip(db_path):
    dbmod.set_cached_outline(db_path, "/tmp/w", "src/a.py", 100.0, 500, "outline", lang="python")
    cached = dbmod.get_cached_outline(db_path, "/tmp/w", "src/a.py", 100.0, 500)
    assert cached is not None
    assert cached["outline"] == "outline"
    assert cached["lang"] == "python"


def test_file_cache_invalidated_on_mtime_change(db_path):
    dbmod.set_cached_outline(db_path, "/tmp/w", "src/a.py", 100.0, 500, "outline")
    assert dbmod.get_cached_outline(db_path, "/tmp/w", "src/a.py", 100.1, 500) is None


def test_file_cache_invalidated_on_size_change(db_path):
    dbmod.set_cached_outline(db_path, "/tmp/w", "src/a.py", 100.0, 500, "outline")
    assert dbmod.get_cached_outline(db_path, "/tmp/w", "src/a.py", 100.0, 501) is None


def test_file_cache_upsert_updates(db_path):
    dbmod.set_cached_outline(db_path, "/tmp/w", "src/a.py", 100.0, 500, "v1")
    dbmod.set_cached_outline(db_path, "/tmp/w", "src/a.py", 100.0, 500, "v2")
    cached = dbmod.get_cached_outline(db_path, "/tmp/w", "src/a.py", 100.0, 500)
    assert cached["outline"] == "v2"


# ---------------------------------------------------------------- robustness

def test_foreign_keys_enforced(db_path):
    # Menambah pesan ke sesi yang tidak ada harus gagal (FK ke sessions).
    with pytest.raises(sqlite3.IntegrityError):
        dbmod.add_message(db_path, "tidak-ada", "user", "x")
