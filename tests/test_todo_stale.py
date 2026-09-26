"""test_todo_stale.py

Regresi untuk mekanisme "todo wajib ditutup" (todo basi / menggantung).

Latar belakang:
    Todo disimpan per WORKDIR dan `todo_write` bersifat FULL REPLACE, artinya
    SETIAP baris ditulis ulang tiap giliran -- termasuk `updated_at`. Kalau
    hanya `updated_at` yang dipakai, mustahil membedakan "baris ditulis ulang"
    dari "status benar-benar berubah". Kolom `status_since` menutup celah itu:
    nilainya hanya berubah kalau status item berubah.

    Di atas kolom itu, `garwa/todo_utils.py` menghitung umur status dan
    menandai item pending/in_progress yang sudah melewati ambang sebagai
    [STALE]. Deteksi ini dipakai konsisten oleh tool (todo_read/todo_write)
    dan sisi CLI (startup, /todos, pesan lanjutan autopilot), karena todo
    yang tidak pernah ditutup akan dibaca model di sesi berikutnya dan
    menyesatkannya.
"""
import argparse
import os
import sqlite3
import sys
import time

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from garwa import db as dbmod  # noqa: E402
from garwa import todo_utils as tu  # noqa: E402
from garwa.cli import _state as state  # noqa: E402
from garwa.tools import _state as tstate  # noqa: E402
from garwa.tools import session_tools as st  # noqa: E402


HOUR = 3600.0


def _cli_main_mod():
    """Ambil MODUL garwa.cli.main (bukan fungsi `main` yang di-re-export).

    `from garwa.cli import main` mengembalikan FUNGSI `main` karena
    `garwa/cli/__init__.py` mengekspor ulang entry point-nya sebagai `main`.
    Helper privat `_warn_stale_todos` hanya ada di modulnya, jadi harus
    diimpor lewat importlib.
    """
    import importlib

    return importlib.import_module("garwa.cli.main")


def _age_rows(db_path, workdir, content, seconds):
    """Geser `status_since` sebuah baris ke masa lalu (simulasi item menua).

    Dilakukan lewat SQL langsung karena jalur normal (replace_todos) memang
    SENGAJA mempertahankan status_since -- jadi tidak ada API publik untuk
    memalsukan umur, dan itu memang perilaku yang diuji.
    """
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE todos SET status_since = ? WHERE workdir = ? AND content = ?",
            (time.time() - seconds, workdir, content),
        )


@pytest.fixture
def workdir(tmp_path):
    return str(tmp_path)


@pytest.fixture
def tool_env(tmp_path, db_path, workdir):
    """Arahkan state tool ke DB/workdir sementara (dipakai todo_read/write)."""
    old = (tstate.DB_PATH, tstate.WORKDIR, tstate.SESSION_ID)
    tstate.DB_PATH = db_path
    tstate.WORKDIR = workdir
    sid = dbmod.create_session(db_path, workdir=workdir, title="stale")
    tstate.SESSION_ID = sid
    yield db_path, workdir, sid
    tstate.DB_PATH, tstate.WORKDIR, tstate.SESSION_ID = old


# --------------------------------------------------------------------------- #
# Unit: format_age
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("secs,expected", [
    (0, "<1m"),
    (59, "<1m"),
    (60, "1m"),
    (90 * 60, "1j 30m"),
    (2 * HOUR, "2j"),
    (25 * HOUR, "1h 1j"),
    (48 * HOUR, "2h"),
])
def test_format_age(secs, expected):
    assert tu.format_age(secs) == expected


def test_format_age_tolerates_garbage():
    assert tu.format_age(None) == "<1m"
    assert tu.format_age("bukan angka") == "-"


# --------------------------------------------------------------------------- #
# Unit: ambang basi (env dibaca ulang tiap panggilan)
# --------------------------------------------------------------------------- #

def test_threshold_default(monkeypatch):
    monkeypatch.delenv("GARWA_TODO_STALE_HOURS", raising=False)
    assert tu.stale_threshold_seconds() == tu.DEFAULT_STALE_HOURS * HOUR


def test_threshold_env_override(monkeypatch):
    monkeypatch.setenv("GARWA_TODO_STALE_HOURS", "0.5")
    assert tu.stale_threshold_seconds() == pytest.approx(1800.0)


def test_threshold_env_read_again_without_restart(monkeypatch):
    """Env dibaca ulang tiap panggilan (bukan konstanta saat import)."""
    monkeypatch.setenv("GARWA_TODO_STALE_HOURS", "1")
    assert tu.stale_threshold_seconds() == HOUR
    monkeypatch.setenv("GARWA_TODO_STALE_HOURS", "3")
    assert tu.stale_threshold_seconds() == 3 * HOUR


def test_threshold_zero_disables(monkeypatch):
    monkeypatch.setenv("GARWA_TODO_STALE_HOURS", "0")
    assert tu.stale_threshold_seconds() == 0.0


def test_threshold_invalid_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("GARWA_TODO_STALE_HOURS", "abc")
    assert tu.stale_threshold_seconds() == tu.DEFAULT_STALE_HOURS * HOUR
    monkeypatch.setenv("GARWA_TODO_STALE_HOURS", "-5")
    assert tu.stale_threshold_seconds() == 0.0


# --------------------------------------------------------------------------- #
# Unit: age_seconds / is_stale
# --------------------------------------------------------------------------- #

def test_age_seconds_prefers_status_since():
    now = 1_000_000.0
    row = {"status_since": now - 120, "updated_at": now - 5, "created_at": now - 999}
    assert tu.age_seconds(row, now=now) == 120


def test_age_seconds_falls_back_to_updated_at_then_created_at():
    now = 1_000_000.0
    assert tu.age_seconds({"updated_at": now - 30, "created_at": now - 500}, now=now) == 30
    assert tu.age_seconds({"created_at": now - 77}, now=now) == 77


def test_age_seconds_never_negative_and_safe_on_empty():
    now = 1_000_000.0
    assert tu.age_seconds({"status_since": now + 500}, now=now) == 0
    assert tu.age_seconds({}, now=now) == 0
    assert tu.age_seconds(None, now=now) == 0


def test_is_stale_only_for_active_items():
    now = 1_000_000.0
    old = now - 10 * HOUR
    assert tu.is_stale({"status": "pending", "status_since": old}, HOUR, now=now) is True
    assert tu.is_stale({"status": "in_progress", "status_since": old}, HOUR, now=now) is True
    # Item yang SUDAH selesai tidak pernah dianggap basi walau tuanya berhari-hari.
    assert tu.is_stale({"status": "done", "status_since": old}, HOUR, now=now) is False
    assert tu.is_stale({"status": "cancelled", "status_since": old}, HOUR, now=now) is False


def test_is_stale_respects_threshold_and_disable():
    now = 1_000_000.0
    row = {"status": "pending", "status_since": now - 2 * HOUR}
    assert tu.is_stale(row, 1 * HOUR, now=now) is True
    assert tu.is_stale(row, 5 * HOUR, now=now) is False
    assert tu.is_stale(row, 0, now=now) is False  # 0 = deteksi dimatikan


# --------------------------------------------------------------------------- #
# Unit: format_rows / find_stale / stale_summary
# --------------------------------------------------------------------------- #

def test_format_rows_marks_and_age(monkeypatch):
    monkeypatch.setenv("GARWA_TODO_STALE_HOURS", "6")
    now = 1_000_000.0
    rows = [
        {"content": "baru", "status": "pending", "status_since": now - 60},
        {"content": "lama", "status": "in_progress", "status_since": now - 8 * HOUR},
        {"content": "selesai", "status": "done", "status_since": now - 100 * HOUR},
        {"content": "batal", "status": "cancelled", "status_since": now - 100 * HOUR},
    ]
    lines = tu.format_rows(rows, now=now)
    assert lines[0] == "[ ] baru  (1m)"
    assert lines[1] == f"[~] lama  (8j) {tu.STALE_TAG}"
    # done/cancelled: penanda status tetap, tapi tanpa umur & tanpa STALE.
    assert lines[2] == "[x] selesai"
    assert lines[3] == "[-] batal"


def test_format_rows_with_age_disabled_and_indent():
    rows = [{"content": "x", "status": "pending", "status_since": time.time() - 99 * HOUR}]
    assert tu.format_rows(rows, threshold_seconds=1, with_age=False, indent="  ") == ["  [ ] x"]


def test_find_stale_sorted_oldest_first():
    now = 1_000_000.0
    rows = [
        {"content": "a", "status": "pending", "status_since": now - 2 * HOUR},
        {"content": "b", "status": "pending", "status_since": now - 30 * HOUR},
        {"content": "c", "status": "done", "status_since": now - 90 * HOUR},
        {"content": "d", "status": "in_progress", "status_since": now - 12 * HOUR},
    ]
    stale = tu.find_stale(rows, HOUR, now=now)
    assert [r["content"] for r in stale] == ["b", "d", "a"]


def test_stale_summary_and_empty_cases(monkeypatch):
    now = 1_000_000.0
    assert tu.stale_summary([], HOUR, now=now) == ""
    fresh = [{"content": "a", "status": "pending", "status_since": now - 60}]
    assert tu.stale_summary(fresh, HOUR, now=now) == ""
    stale = [{"content": "a", "status": "pending", "status_since": now - 3 * HOUR}]
    txt = tu.stale_summary(stale, HOUR, now=now)
    assert "1 item" in txt and "3j" in txt
    # Ambang 0 -> deteksi dimatikan sepenuhnya.
    assert tu.stale_summary(stale, 0, now=now) == ""


# --------------------------------------------------------------------------- #
# db: status_since dipertahankan / diperbarui
# --------------------------------------------------------------------------- #

def test_replace_todos_keeps_status_since_when_status_unchanged(db_path, workdir):
    dbmod.replace_todos(db_path, workdir, [{"content": "a", "status": "pending"}])
    first = dbmod.get_todos(db_path, workdir=workdir)[0]["status_since"]
    time.sleep(0.02)
    dbmod.replace_todos(db_path, workdir, [{"content": "a", "status": "pending"}])
    row = dbmod.get_todos(db_path, workdir=workdir)[0]
    assert row["status_since"] == first, (
        "full replace TIDAK boleh menyegarkan status_since kalau status sama -- "
        "kalau ini gagal, semua todo selalu tampak 'baru' dan deteksi basi mati"
    )
    assert row["updated_at"] > first, "updated_at tetap ditulis ulang (memang perilakunya)"


def test_replace_todos_resets_status_since_on_status_change(db_path, workdir):
    dbmod.replace_todos(db_path, workdir, [{"content": "a", "status": "pending"}])
    first = dbmod.get_todos(db_path, workdir=workdir)[0]["status_since"]
    time.sleep(0.02)
    dbmod.replace_todos(db_path, workdir, [{"content": "a", "status": "in_progress"}])
    row = dbmod.get_todos(db_path, workdir=workdir)[0]
    assert row["status_since"] > first


def test_replace_todos_new_item_gets_fresh_status_since(db_path, workdir):
    dbmod.replace_todos(db_path, workdir, [{"content": "lama", "status": "pending"}])
    _age_rows(db_path, workdir, "lama", 10 * HOUR)
    dbmod.replace_todos(db_path, workdir, [
        {"content": "lama", "status": "pending"},
        {"content": "baru", "status": "pending"},
    ])
    rows = {r["content"]: r for r in dbmod.get_todos(db_path, workdir=workdir)}
    assert tu.age_seconds(rows["lama"]) > 9 * HOUR, "item lama harus tetap menua"
    assert tu.age_seconds(rows["baru"]) < 60, "item baru mulai dari nol"


def test_migration_backfills_status_since_from_updated_at(tmp_path):
    """DB lama (tanpa kolom status_since) tidak boleh membuat semua todo
    tampak 'epoch 0' alias basi berhari-hari."""
    path = str(tmp_path / "old.db")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE todos (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_id TEXT NOT NULL, workdir TEXT NOT NULL DEFAULT '', "
            "position INTEGER NOT NULL, content TEXT NOT NULL, "
            "status TEXT NOT NULL DEFAULT 'pending', created_at REAL NOT NULL, "
            "updated_at REAL NOT NULL)"
        )
        conn.execute(
            "INSERT INTO todos (session_id, workdir, position, content, status, "
            "created_at, updated_at) VALUES ('s', 'w', 0, 'lama', 'pending', ?, ?)",
            (time.time() - 100 * HOUR, time.time() - 100 * HOUR),
        )
    dbmod.init_db(path)
    row = dbmod.get_todos(path, workdir="w")[0]
    assert row["status_since"] == row["updated_at"]


def test_get_stale_todos_filters_and_sorts(db_path, workdir):
    dbmod.replace_todos(db_path, workdir, [
        {"content": "segar", "status": "pending"},
        {"content": "lama-1", "status": "pending"},
        {"content": "lama-2", "status": "in_progress"},
        {"content": "selesai", "status": "done"},
    ])
    _age_rows(db_path, workdir, "lama-1", 5 * HOUR)
    _age_rows(db_path, workdir, "lama-2", 20 * HOUR)
    _age_rows(db_path, workdir, "selesai", 50 * HOUR)
    stale = dbmod.get_stale_todos(db_path, workdir, 2 * HOUR)
    assert [r["content"] for r in stale] == ["lama-2", "lama-1"]
    assert all(r["status"] != "done" for r in stale)


def test_get_stale_todos_threshold_zero_or_disabled(db_path, workdir):
    dbmod.replace_todos(db_path, workdir, [{"content": "a", "status": "pending"}])
    _age_rows(db_path, workdir, "a", 99 * HOUR)
    assert dbmod.get_stale_todos(db_path, workdir, 0) == []
    assert dbmod.get_stale_todos(db_path, workdir, None) == []


# --------------------------------------------------------------------------- #
# tools: todo_read / todo_write
# --------------------------------------------------------------------------- #

def test_todo_read_shows_age_and_stale_tag(tool_env, monkeypatch):
    db_path, workdir, sid = tool_env
    monkeypatch.setenv("GARWA_TODO_STALE_HOURS", "6")
    dbmod.replace_todos(db_path, workdir, [
        {"content": "menggantung", "status": "in_progress"},
        {"content": "selesai", "status": "done"},
    ], session_id=sid)
    _age_rows(db_path, workdir, "menggantung", 9 * HOUR)

    out = st.tool_todo_read()
    assert "[~] menggantung" in out
    assert tu.STALE_TAG in out
    assert "[WARN]" in out
    assert "item aktif" in out
    # Item done tampil, tapi tanpa umur (tidak relevan lagi).
    assert "[x] selesai" in out


def test_todo_read_quiet_when_all_fresh(tool_env, monkeypatch):
    db_path, workdir, sid = tool_env
    monkeypatch.setenv("GARWA_TODO_STALE_HOURS", "6")
    dbmod.replace_todos(db_path, workdir, [{"content": "baru", "status": "pending"}],
                        session_id=sid)
    out = st.tool_todo_read()
    assert tu.STALE_TAG not in out
    assert "[WARN]" not in out


def test_todo_write_warns_when_item_dropped(tool_env):
    db_path, workdir, sid = tool_env
    st.tool_todo_write([
        {"content": "satu", "status": "pending"},
        {"content": "dua", "status": "pending"},
    ])
    out = st.tool_todo_write([{"content": "satu", "status": "pending"}])
    assert out.startswith("[OK]")
    assert "HILANG" in out
    assert "dua" in out


def test_todo_write_preserves_unmentioned_done(tool_env):
    """Item selesai yang lupa disalin TIDAK lagi terhapus diam-diam.

    Ini menutup mode kegagalan nyata: model menulis ulang daftar tanpa
    menyalin item lama yang sudah `done`, dan sebelumnya item itu hilang
    (plus memicu WARN palsu "HILANG").
    """
    db_path, workdir, sid = tool_env
    st.tool_todo_write([
        {"content": "rumah", "status": "done"},
        {"content": "lanjut", "status": "in_progress"},
    ])
    out = st.tool_todo_write([{"content": "lanjut", "status": "done"}])
    assert out.startswith("[OK]")
    assert "HILANG" not in out
    assert "[x] rumah" in out
    assert [t["content"] for t in dbmod.get_todos(db_path, workdir=workdir)] == ["lanjut", "rumah"]


def test_todo_write_remove_drops_finished_explicitly(tool_env):
    db_path, workdir, sid = tool_env
    st.tool_todo_write([{"content": "lama", "status": "done"}])
    out = st.tool_todo_write([], remove=["lama"])
    assert out.startswith("[OK]")
    assert dbmod.get_todos(db_path, workdir=workdir) == []


def test_todo_write_warns_on_regression(tool_env):
    db_path, workdir, sid = tool_env
    st.tool_todo_write([{"content": "satu", "status": "done"}])
    out = st.tool_todo_write([{"content": "satu", "status": "pending"}])
    assert out.startswith("[OK]")
    assert "SELESAI" in out and "-> pending" in out


def test_todo_write_reports_stale_summary(tool_env, monkeypatch):
    """Menulis ulang daftar TIDAK boleh menyembunyikan item yang sudah basi."""
    db_path, workdir, sid = tool_env
    monkeypatch.setenv("GARWA_TODO_STALE_HOURS", "6")
    st.tool_todo_write([{"content": "menggantung", "status": "pending"}])
    _age_rows(db_path, workdir, "menggantung", 12 * HOUR)
    out = st.tool_todo_write([{"content": "menggantung", "status": "pending"}])
    assert out.startswith("[OK]")
    assert "basi" in out
    assert "12j" in out


def test_todo_write_no_stale_warning_after_being_closed(tool_env, monkeypatch):
    """Item yang sudah lama menggantung lalu DITUTUP -> tidak lagi diperingatkan."""
    db_path, workdir, sid = tool_env
    monkeypatch.setenv("GARWA_TODO_STALE_HOURS", "6")
    st.tool_todo_write([{"content": "menggantung", "status": "pending"}])
    _age_rows(db_path, workdir, "menggantung", 12 * HOUR)
    out = st.tool_todo_write([{"content": "menggantung", "status": "done"}])
    assert out.startswith("[OK]")
    assert "basi" not in out
    row = dbmod.get_todos(db_path, workdir=workdir)[0]
    assert tu.is_stale(row) is False


# --------------------------------------------------------------------------- #
# CLI: peringatan startup
# --------------------------------------------------------------------------- #

def test_warn_stale_todos_prints_once(db_path, workdir, monkeypatch, capsys):
    cli_main = _cli_main_mod()

    monkeypatch.setenv("GARWA_TODO_STALE_HOURS", "6")
    dbmod.replace_todos(db_path, workdir, [{"content": "menggantung", "status": "pending"}])
    _age_rows(db_path, workdir, "menggantung", 30 * HOUR)
    cli_main._warn_stale_todos(db_path, workdir)
    out = capsys.readouterr().out
    assert "BASI" in out
    assert "1h 6j" in out or "30j" in out


def test_warn_stale_todos_silent_when_fresh(db_path, workdir, monkeypatch, capsys):
    cli_main = _cli_main_mod()

    monkeypatch.setenv("GARWA_TODO_STALE_HOURS", "6")
    dbmod.replace_todos(db_path, workdir, [{"content": "baru", "status": "pending"}])
    cli_main._warn_stale_todos(db_path, workdir)
    assert "BASI" not in capsys.readouterr().out


def test_warn_stale_todos_never_raises_on_bad_db(tmp_path, capsys):
    """Peringatan startup tidak boleh menghalangi sesi dimulai."""
    cli_main = _cli_main_mod()

    cli_main._warn_stale_todos(str(tmp_path / "tidak-ada.db"), str(tmp_path))
    assert "BASI" not in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# agent_loop: autopilot berhenti saat model berputar tanpa progres
# --------------------------------------------------------------------------- #

class _NoToolCall:
    """Selalu menjawab prosa tanpa tool_call; teksnya berbeda tiap panggilan
    supaya loop-guard tidak lebih dulu menyala."""

    _PROSE = [
        "Saya rasa bagian konfigurasi sudah saya tinjau dan tidak ada sisa masalah.",
        "Menurut saya penamaan variabel lokal sudah cukup jelas untuk dibaca ulang.",
        "Dokumentasi singkat bisa ditambahkan pada berkas README proyek ini.",
        "Ada kemungkinan kecil race condition pada saat penutupan koneksi database.",
        "Ringkasan akhir: pemetaan kolom sudah dipindahkan ke modul terpisah sendiri.",
    ]

    def __init__(self):
        self.calls = 0

    def __call__(self, *a, **kw):
        self.calls += 1
        return self._PROSE[(self.calls - 1) % len(self._PROSE)]


@pytest.fixture
def loop_env(tmp_path, db_path, monkeypatch):
    from garwa.cli import agent_loop as al  # noqa: F401  (import check)

    workdir = str(tmp_path)
    sid = dbmod.create_session(db_path, workdir=workdir, title="stuck")
    args = argparse.Namespace(
        db_path=db_path,
        session_id=sid,
        auto_approve=True,
        context_window=8192,
        max_tokens=1024,
        model="test-model",
        url="http://localhost:1",
        api_key="",
        workdir=workdir,
        reasoning=False,
        temperature=0.0,
        system_prompt="test",
        verbose=False,
        no_stream=True,
        debug=False,
    )
    monkeypatch.setattr(state, "LOOP_BREAK_COOLDOWN_SECONDS", 0)
    yield args, db_path, workdir, sid
    state.set_autopilot(False, sid)
    state.reset_session_state(sid)


def test_autopilot_stops_when_model_makes_no_progress(loop_env, monkeypatch):
    """Autopilot mengirim pesan lanjutan; kalau daftar todo TIDAK berubah
    sama sekali, ia harus berhenti (bukan menyuntik sampai batas maksimum)."""
    from garwa.cli import agent_loop as al

    args, db_path, workdir, sid = loop_env
    dbmod.replace_todos(db_path, workdir, [{"content": "tugas abadi", "status": "pending"}])
    state.set_autopilot(True, sid)
    monkeypatch.setattr(state, "AUTOPILOT_STUCK_LIMIT", 2)
    monkeypatch.setattr(state, "AUTOPILOT_MAX_CONTINUES", 20)
    fake = _NoToolCall()
    monkeypatch.setattr("garwa.cli.agent_loop.call_llama_server", fake)

    al.run_agent_loop(args, sid, "test system")

    assert fake.calls == 3, (
        f"stuck-limit 2 -> 2 suntikan lalu berhenti (dapat {fake.calls} panggilan)"
    )
    assert state.get_autopilot(sid) is False
    combined = "\n".join(m.get("content", "") for m in dbmod.get_all_messages(db_path, sid))
    assert "[AUTOPILOT]" in combined


def test_autopilot_progress_resets_stuck_counter(loop_env, monkeypatch):
    """Selama todo berubah (progres nyata), autopilot tidak dihentikan oleh
    penghitung stuck -- yang membatasinya adalah AUTOPILOT_MAX_CONTINUES."""
    from garwa.cli import agent_loop as al

    args, db_path, workdir, sid = loop_env
    dbmod.replace_todos(db_path, workdir, [{"content": "tugas", "status": "pending"}])
    state.set_autopilot(True, sid)
    monkeypatch.setattr(state, "AUTOPILOT_STUCK_LIMIT", 1)
    monkeypatch.setattr(state, "AUTOPILOT_MAX_CONTINUES", 2)

    # Model "berprogres": setiap kali dipanggil, status todo berubah.
    counter = {"n": 0}

    def _progressing(*a, **kw):
        counter["n"] += 1
        status = "in_progress" if counter["n"] == 1 else "pending"
        dbmod.replace_todos(db_path, workdir, [{"content": "tugas", "status": status}])
        return _NoToolCall._PROSE[(counter["n"] - 1) % len(_NoToolCall._PROSE)]

    monkeypatch.setattr("garwa.cli.agent_loop.call_llama_server", _progressing)

    al.run_agent_loop(args, sid, "test system")

    # 1 percobaan awal + 2 suntikan (batas AUTOPILOT_MAX_CONTINUES) = 3.
    assert counter["n"] == 3, f"batas continues harus dihormati (dapat {counter['n']})"
    assert state.get_autopilot(sid) is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([os.path.abspath(__file__), "-q"]))
