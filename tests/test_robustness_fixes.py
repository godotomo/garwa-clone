"""
test_robustness_fixes.py
Uji perbaikan robustness yang dilakukan pada sesi ini:

P1:
- db.connect() memakai busy_timeout panjang (DB_BUSY_TIMEOUT) & helper
  _open_conn; tahan terhadap lock sementara dari sub-agent paralel.
- repo_map._iter_source_files punya guard waktu & total bytes (anti-hang di
  repo besar).

P2:
- context_manager memakai get_last_user_message (query LIMIT 1 ringan)
  alih-alih get_all_messages untuk retrieval relevansi catatan.
- _note_relevance_score memakai Jaccard + partial match + key boost.
- _tools_payload_tokens di-cache per-objek (tidak dihitung ulang tiap giliran).
"""

import sqlite3
import threading
import time

import pytest

from garwa import db as dbmod
from garwa import repo_map
from garwa import context_manager as cm


# ---------------------------------------------------------------- P1: db busy

def test_db_busy_timeout_configured(db_path):
    """Koneksi harus punya busy_timeout yang panjang (tahan lock sementara)."""
    with dbmod.connect(db_path) as conn:
        row = conn.execute("PRAGMA busy_timeout").fetchone()
    # PRAGMA busy_timeout mengembalikan nilai dalam milidetik.
    assert row[0] >= int(dbmod.DB_BUSY_TIMEOUT * 1000)


def test_db_connect_uses_wal(db_path):
    """Koneksi memakai journal_mode=WAL (banyak reader + satu writer)."""
    with dbmod.connect(db_path) as conn:
        row = conn.execute("PRAGMA journal_mode").fetchone()
    assert row[0].lower() == "wal"


def test_db_concurrent_writes_from_threads(db_path, session_id):
    """Banyak thread menulis ke DB yang sama secara bersamaan tidak boleh
    error (busy_timeout + WAL menyerap lock sementara)."""
    errors = []

    def writer(n):
        try:
            for i in range(20):
                dbmod.add_message(db_path, session_id, "user", f"t{n}-{i}")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"concurrent write errors: {errors}"
    rows = dbmod.get_all_messages(db_path, session_id)
    assert len(rows) == 4 * 20


def test_db_concurrent_mixed_read_write(db_path, session_id):
    """Reader + writer paralel (pola sub-agent) tidak error."""
    dbmod.add_message(db_path, session_id, "user", "seed")
    errors = []

    def reader():
        try:
            for _ in range(30):
                dbmod.get_all_messages(db_path, session_id)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    def writer():
        try:
            for i in range(30):
                dbmod.add_message(db_path, session_id, "user", f"w{i}")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=reader), threading.Thread(target=writer)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"mixed read/write errors: {errors}"


def test_db_is_busy_error_detector():
    """Helper _is_busy_error mengenali pesan lock SQLite."""
    assert dbmod._is_busy_error(sqlite3.OperationalError("database is locked"))
    assert dbmod._is_busy_error(sqlite3.OperationalError("database table is locked"))
    assert not dbmod._is_busy_error(sqlite3.OperationalError("no such table"))


# ------------------------------------------------- P1: repo_map time/byte guard

def test_iter_source_files_byte_budget(tmp_path):
    """Guard byte_budget menghentikan iterasi saat total bytes terlampaui."""
    src = tmp_path / "src"
    src.mkdir()
    # 3 file python, masing-masing ~2KB (>= byte_budget 1 byte -> berhenti cepat)
    for i in range(3):
        (src / f"a{i}.py").write_text("x" * 2048)

    # byte_budget 3000: file pertama (2048B) lolos, file kedua membuat total
    # 4096 > 3000 sehingga iterasi berhenti sebelum yield file kedua.
    files = list(repo_map._iter_source_files(str(src), byte_budget=3000))
    # Hanya 1 file yang dihasilkan sebelum budget bytes terlampaui.
    assert len(files) == 1


def test_iter_source_files_max_files_guard(tmp_path):
    """Guard max_files tetap bekerja."""
    src = tmp_path / "src"
    src.mkdir()
    for i in range(10):
        (src / f"f{i}.py").write_text("def f():\n    pass\n")

    files = list(repo_map._iter_source_files(str(src), max_files=3))
    assert len(files) == 3


def test_iter_source_files_time_budget(tmp_path):
    """Guard time_budget berhenti lebih awal walau banyak file."""
    src = tmp_path / "src"
    src.mkdir()
    for i in range(50):
        (src / f"f{i}.py").write_text("x = 1\n")

    start = time.monotonic()
    files = list(repo_map._iter_source_files(str(src), time_budget=0.0))
    elapsed = time.monotonic() - start
    # time_budget 0.0 -> langsung berhenti, hasil <= 1 (atau 0).
    assert len(files) <= 1
    assert elapsed < 1.0


def test_iter_source_files_important_filenames(tmp_path):
    """File penting tanpa ekstensi (README) tetap dihasilkan."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "README.md").write_text("# hello")
    (src / "main.py").write_text("x = 1")

    files = list(repo_map._iter_source_files(str(src)))
    rels = {rel for rel, _, _ in files}
    assert "README.md" in rels
    assert "main.py" in rels


# ------------------------------------------------- P2: get_last_user_message

def test_get_last_user_message_returns_latest_chat(db_path, session_id):
    dbmod.add_message(db_path, session_id, "user", "pertama")
    dbmod.add_message(db_path, session_id, "assistant", "balasan")
    dbmod.add_message(db_path, session_id, "user", "kedua")
    last = dbmod.get_last_user_message(db_path, session_id)
    assert last.get("content") == "kedua"
    assert last.get("role") == "user"


def test_get_last_user_message_ignores_non_chat(db_path, session_id):
    dbmod.add_message(db_path, session_id, "user", "chat1", kind="chat")
    dbmod.add_message(db_path, session_id, "user", "tool", kind="tool_result")
    last = dbmod.get_last_user_message(db_path, session_id)
    assert last.get("content") == "chat1"


def test_get_last_user_message_empty_returns_dict(db_path, session_id):
    assert dbmod.get_last_user_message(db_path, session_id) == {}


# ------------------------------------------------- P2: _note_relevance_score

def test_note_relevance_exact_key_match_high():
    note = {"key": "garwa-architecture", "value": "garwa adalah CLI agent lokal"}
    assert cm._note_relevance_score(note, "garwa architecture") > 0


def test_note_relevance_irrelevant_is_low():
    note = {"key": "crypto-trading", "value": "analisis bitcoin dan ethereum"}
    score = cm._note_relevance_score(note, "bagaimana cara membuat rest api")
    assert score == 0.0


def test_note_relevance_partial_match_counts():
    # query "repo_map" cocok sebagian dengan key "repo_mapping".
    note = {"key": "repo_mapping", "value": "peta struktur repository"}
    assert cm._note_relevance_score(note, "repo_map") > 0


def test_note_relevance_key_boosted_over_value():
    # Dua catatan: satu cocok di key, satu hanya di value. Yang cocok di key
    # harus lebih tinggi.
    key_note = {"key": "jobbot-architecture", "value": "hal lain tidak relevan"}
    val_note = {"key": "xyz", "value": "jobbot architecture dibahas di sini"}
    s_key = cm._note_relevance_score(key_note, "jobbot architecture")
    s_val = cm._note_relevance_score(val_note, "jobbot architecture")
    assert s_key > s_val


def test_note_relevance_empty_query_zero():
    assert cm._note_relevance_score({"key": "a", "value": "b"}, "") == 0.0


# ------------------------------------------------- P2: _tools_payload_tokens cache

def test_tools_payload_tokens_cache_hit():
    """Memanggil dua kali dengan objek yang sama memakai cache (tidak
    menghitung ulang)."""
    payload = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]
    first = cm._tools_payload_tokens(payload)
    second = cm._tools_payload_tokens(payload)
    assert first == second
    assert first > 0


def test_tools_payload_tokens_empty():
    assert cm._tools_payload_tokens(None) == 0
    assert cm._tools_payload_tokens([]) == 0


def test_tools_payload_tokens_cache_keyed_by_object():
    """Objek berbeda (id beda) dihitung terpisah; hasil tetap konsisten."""
    p1 = [{"type": "function", "function": {"name": "read_file"}}]
    p2 = [{"type": "function", "function": {"name": "read_file"}}]
    assert cm._tools_payload_tokens(p1) == cm._tools_payload_tokens(p2)
