"""test_autopilot.py

Regresi untuk fitur /autopilot (sisi KLIEN garwa, bukan sisi model):

  /autopilot on -> selama masih ada todo pending/in_progress, giliran TIDAK
                   berhenti ketika model berhenti mengirim tool_call; klien
                   menyuntikkan pesan lanjutan (berisi daftar todo + opsional
                   catatan agen reviewer) supaya model melanjutkan pekerjaan.
  /autopilot off -> perilaku normal.
  Autopilot mematikan dirinya sendiri saat tidak ada todo pending lagi, dan
  dibatasi AUTOPILOT_MAX_CONTINUES supaya tidak jadi loop tak berujung.
"""

import argparse
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from garwa.cli import _state as state  # noqa: E402
from garwa.cli import agent_loop as al  # noqa: E402
from garwa.cli import autopilot as ap  # noqa: E402
from garwa.tools import _state as tstate  # noqa: E402
from garwa import db as dbmod  # noqa: E402


def _seed_todos(db_path, workdir, items):
    dbmod.replace_todos(
        db_path,
        workdir,
        [{"content": c, "status": s} for c, s in items],
        session_id="seed",
    )


# Kalimat prosa yang BENAR-BENAR berbeda satu sama lain (bukan sekadar beda
# angka) supaya deteksi loop tidak ikut menyala. Penting: `_loop_similarity`
# menormalisasi angka/path/string terkuot menjadi placeholder, jadi varian
# "ringkasan ke-1/ke-2/..." justru dianggap respon IDENTIK dan memicu [LOOP]
# lebih dulu daripada jalur autopilot yang sedang diuji.
_PROSE = [
    "Sepertinya seluruh berkas konfigurasi sudah saya tinjau dan tidak ada sisa.",
    "Menurut saya parser argumen kini sudah menangani kasus tanda kutip ganjil.",
    "Bagian dokumentasi bisa ditambahkan contoh pemakaian singkat di README.",
    "Ada kemungkinan race condition kecil pada penutupan koneksi database.",
    "Ringkasan akhir: logika pemetaan kolom sudah dipindahkan ke modul terpisah.",
    "Selanjutnya saya sarankan menambah pengujian untuk jalur galat jaringan.",
    "Struktur folder saat ini sudah konsisten dengan konvensi proyek ini.",
    "Sisa pekerjaan tampaknya hanya merapikan penamaan variabel lokal.",
]


class _NoToolCall:
    """Selalu menjawab prosa TANPA tool_call (pola yang memicu STOP).

    Teksnya dibuat BERBEDA tiap panggilan supaya deteksi loop tidak ikut
    menyala -- yang sedang diuji di sini adalah autopilot, bukan loop guard.
    """

    def __init__(self):
        self.calls = 0

    def __call__(self, *a, **kw):
        self.calls += 1
        return _PROSE[(self.calls - 1) % len(_PROSE)]


@pytest.fixture
def env(tmp_path, monkeypatch):
    old_db = tstate.DB_PATH
    old_work = tstate.WORKDIR
    old_sid = tstate.SESSION_ID
    tstate.DB_PATH = str(tmp_path / "test.db")
    tstate.WORKDIR = str(tmp_path)
    db_path = tstate.DB_PATH
    dbmod.init_db(db_path)
    sid = dbmod.create_session(db_path, str(tmp_path), title="autopilot")
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
    state.set_autopilot(False, sid)
    tstate.DB_PATH = old_db
    tstate.WORKDIR = old_work
    tstate.SESSION_ID = old_sid
    state.reset_session_state(sid)


# --------------------------------------------------------------------------- #
# Unit: parse_toggle
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("arg", ["on", "ON", "1", "true", "yes", "aktif", "ya"])
def test_parse_toggle_on_variants(arg):
    enabled, note = ap.parse_toggle(arg)
    assert enabled is True
    assert note == ""


@pytest.mark.parametrize("arg", ["off", "OFF", "0", "false", "no", "nonaktif", "tidak"])
def test_parse_toggle_off_variants(arg):
    enabled, note = ap.parse_toggle(arg)
    assert enabled is False
    assert note == ""


def test_parse_toggle_unrecognized_returns_none():
    """Argumen tak dikenal -> (None, None) supaya handler mencetak petunjuk."""
    assert ap.parse_toggle("") == (None, None)
    assert ap.parse_toggle("   ") == (None, None)
    assert ap.parse_toggle("mungkin") == (None, None)


def test_parse_toggle_keeps_note_from_reviewer():
    enabled, note = ap.parse_toggle("on reviewer: bagian X masih pakai API lama")
    assert enabled is True
    assert note == "reviewer: bagian X masih pakai API lama"


# --------------------------------------------------------------------------- #
# Unit: build_continue_message
# --------------------------------------------------------------------------- #

def test_build_continue_message_lists_pending_todos(env):
    args, db_path, sid = env
    _seed_todos(
        db_path,
        args.workdir,
        [
            ("Perbaiki parser JSON", "pending"),
            ("Tulis test regresi", "in_progress"),
            ("Update CHANGELOG", "done"),  # done tidak boleh ikut disebut
        ],
    )
    msg = ap.build_continue_message(db_path, args.workdir)
    assert msg.startswith("<tool_result>")
    assert msg.rstrip().endswith("</tool_result>")
    assert "[AUTOPILOT]" in msg
    assert "[ ] Perbaiki parser JSON" in msg
    assert "[~] Tulis test regresi" in msg
    assert "Update CHANGELOG" not in msg


def test_build_continue_message_includes_reviewer_note_from_project(env):
    args, db_path, sid = env
    _seed_todos(db_path, args.workdir, [("Satu todo", "pending")])
    dbmod.set_note(db_path, args.workdir, ap.REVIEWER_NOTE_KEY, "curigai fungsi foo()")
    msg = ap.build_continue_message(db_path, args.workdir)
    assert "curigai fungsi foo()" in msg
    assert "reviewer" in msg.lower()


def test_build_continue_message_includes_adhoc_note_over_project_note(env):
    """Catatan sesi ini menang, catatan proyek tetap ikut (sebagai konteks)."""
    args, db_path, sid = env
    _seed_todos(db_path, args.workdir, [("Satu todo", "pending")])
    dbmod.set_note(db_path, args.workdir, ap.REVIEWER_NOTE_KEY, "proyek: A")
    msg = ap.build_continue_message(db_path, args.workdir, note="sesi: B")
    assert "sesi: B" in msg
    assert "proyek: A" in msg


# --------------------------------------------------------------------------- #
# Integrasi: agent_loop pada titik STOP
# --------------------------------------------------------------------------- #

def test_autopilot_injects_continue_while_todos_pending(env, monkeypatch):
    """Autopilot aktif + todo pending -> STOP ditahan, pesan disuntikkan."""
    args, db_path, sid = env
    _seed_todos(db_path, args.workdir, [("Tugas belum selesai", "pending")])
    state.set_autopilot(True, sid)
    fake = _NoToolCall()
    monkeypatch.setattr("garwa.cli.agent_loop.call_llama_server", fake)

    al.run_agent_loop(args, sid, "test system")

    assert fake.calls >= 2, (
        "giliran harus dilanjutkan (panggilan model berikutnya), bukan berhenti "
        "saat model pertama kali tidak memanggil tool"
    )
    combined = "\n".join(
        m.get("content", "") for m in dbmod.get_all_messages(db_path, sid)
    )
    assert "[AUTOPILOT]" in combined
    assert "Tugas belum selesai" in combined


def test_autopilot_off_keeps_normal_stop(env, monkeypatch):
    """Tanpa autopilot: tidak ada pesan lanjutan (hanya nudge TODO-CHECK sekali).

    Nudge TODO-CHECK adalah perilaku BERBEDA dari autopilot: ia tidak
    melanjutkan pekerjaan berulang kali, hanya menahan giliran SEKALI supaya
    model sempat menutup status todo yang masih aktif.
    """
    args, db_path, sid = env
    _seed_todos(db_path, args.workdir, [("Tugas belum selesai", "pending")])
    fake = _NoToolCall()
    monkeypatch.setattr("garwa.cli.agent_loop.call_llama_server", fake)

    al.run_agent_loop(args, sid, "test system")

    assert fake.calls == 2, (
        "tanpa autopilot: 1 percobaan + 1 nudge TODO-CHECK, lalu STOP"
    )
    combined = "\n".join(
        m.get("content", "") for m in dbmod.get_all_messages(db_path, sid)
    )
    assert "[AUTOPILOT]" not in combined


# --------------------------------------------------------------------------- #
# Unit: build_status_review_message (/todo-check)
# --------------------------------------------------------------------------- #

def test_status_review_message_lists_active_todos(env):
    args, db_path, sid = env
    _seed_todos(
        db_path,
        args.workdir,
        [
            ("Perbaiki parser JSON", "pending"),
            ("Tulis test regresi", "in_progress"),
            ("Update CHANGELOG", "done"),  # item selesai tidak boleh disebut
        ],
    )
    msg = ap.build_status_review_message(db_path, args.workdir)
    assert msg.startswith("<tool_result>")
    assert msg.rstrip().endswith("</tool_result>")
    assert "[TODO-CHECK]" in msg
    assert "[ ] Perbaiki parser JSON" in msg
    assert "[~] Tulis test regresi" in msg
    assert "Update CHANGELOG" not in msg


def test_status_review_message_never_auto_assigns_status(env):
    """Pesan harus meminta MODEL memutuskan, bukan mengklaim status apa pun."""
    args, db_path, sid = env
    _seed_todos(db_path, args.workdir, [("Satu todo", "pending")])
    msg = ap.build_status_review_message(db_path, args.workdir)
    assert "hanya Anda yang tahu" in msg
    assert "todo_write" in msg
    # Klien tidak pernah menandai done sendiri.
    assert "[x]" not in msg


def test_status_review_message_injects_once_and_stops(env, monkeypatch):
    """Nudge hanya SEKALI per giliran; sesudahnya giliran benar-benar ditutup."""
    args, db_path, sid = env
    _seed_todos(db_path, args.workdir, [("Tugas menggantung", "pending")])
    fake = _NoToolCall()
    monkeypatch.setattr("garwa.cli.agent_loop.call_llama_server", fake)

    al.run_agent_loop(args, sid, "test system")

    assert fake.calls == 2, f"harus tepat 2 percobaan (dapat {fake.calls})"
    combined = "\n".join(
        m.get("content", "") for m in dbmod.get_all_messages(db_path, sid)
    )
    assert combined.count("[TODO-CHECK]") == 1, (
        "nudge tidak boleh disuntikkan lebih dari sekali pada satu giliran"
    )


def test_status_review_disabled_by_env(env, monkeypatch):
    """TODO_STATUS_REVIEW_MAX=0 -> perilaku lama (STOP langsung)."""
    args, db_path, sid = env
    _seed_todos(db_path, args.workdir, [("Tugas menggantung", "pending")])
    monkeypatch.setattr(state, "TODO_STATUS_REVIEW_MAX", 0)
    fake = _NoToolCall()
    monkeypatch.setattr("garwa.cli.agent_loop.call_llama_server", fake)

    al.run_agent_loop(args, sid, "test system")

    assert fake.calls == 1
    combined = "\n".join(
        m.get("content", "") for m in dbmod.get_all_messages(db_path, sid)
    )
    assert "[TODO-CHECK]" not in combined


def test_status_review_skipped_when_no_active_todos(env, monkeypatch):
    """Tidak ada todo aktif -> tidak ada nudge, giliran berhenti normal."""
    args, db_path, sid = env
    _seed_todos(db_path, args.workdir, [("Sudah selesai", "done")])
    fake = _NoToolCall()
    monkeypatch.setattr("garwa.cli.agent_loop.call_llama_server", fake)

    al.run_agent_loop(args, sid, "test system")

    assert fake.calls == 1
    combined = "\n".join(
        m.get("content", "") for m in dbmod.get_all_messages(db_path, sid)
    )
    assert "[TODO-CHECK]" not in combined


def test_status_review_does_not_stack_with_autopilot(env, monkeypatch):
    """Autopilot aktif -> nudge TODO-CHECK TIDAK ikut menyala."""
    args, db_path, sid = env
    _seed_todos(db_path, args.workdir, [("Tugas belum selesai", "pending")])
    state.set_autopilot(True, sid)
    monkeypatch.setattr(state, "AUTOPILOT_STUCK_LIMIT", 1)
    fake = _NoToolCall()
    monkeypatch.setattr("garwa.cli.agent_loop.call_llama_server", fake)

    al.run_agent_loop(args, sid, "test system")

    combined = "\n".join(
        m.get("content", "") for m in dbmod.get_all_messages(db_path, sid)
    )
    assert "[AUTOPILOT]" in combined
    assert "[TODO-CHECK]" not in combined, (
        "autopilot sudah menangani kasus ini; nudge tambahan hanya menabraknya"
    )


def test_autopilot_disables_itself_when_no_todos_left(env, monkeypatch):
    """Tidak ada todo pending -> autopilot mematikan diri, STOP normal."""
    args, db_path, sid = env
    state.set_autopilot(True, sid)
    fake = _NoToolCall()
    monkeypatch.setattr("garwa.cli.agent_loop.call_llama_server", fake)

    al.run_agent_loop(args, sid, "test system")

    assert fake.calls == 1
    assert state.get_autopilot(sid) is False, (
        "autopilot harus mati sendiri saat sudah tidak ada todo pending"
    )
    combined = "\n".join(
        m.get("content", "") for m in dbmod.get_all_messages(db_path, sid)
    )
    assert "[AUTOPILOT]" not in combined


def test_autopilot_is_bounded(env, monkeypatch):
    """Todo yang tak pernah ditutup tidak boleh membuat loop tak berujung."""
    args, db_path, sid = env
    _seed_todos(db_path, args.workdir, [("Tugas abadi", "pending")])
    state.set_autopilot(True, sid)
    monkeypatch.setattr(state, "AUTOPILOT_MAX_CONTINUES", 3)
    # Tes ini fokus pada batas JUMLAH suntikan, bukan pada deteksi "stuck".
    # Karena `_NoToolCall` memang tidak pernah mengubah todo, stuck-limit akan
    # memicu lebih dulu kalau tidak dinetralkan; deteksi stuck diuji terpisah
    # (lihat test_autopilot_stops_when_model_makes_no_progress).
    monkeypatch.setattr(state, "AUTOPILOT_STUCK_LIMIT", 999)
    fake = _NoToolCall()
    monkeypatch.setattr("garwa.cli.agent_loop.call_llama_server", fake)

    al.run_agent_loop(args, sid, "test system")

    # 1 percobaan awal + 3 suntikan; percobaan ke-4 sudah melewati batas -> stop.
    assert fake.calls == 4, f"jumlah percobaan harus dibatasi (dapat {fake.calls})"
    assert state.get_autopilot(sid) is False


def test_autopilot_flag_is_per_session():
    """/autopilot hanya mengubah sesi yang dituju."""
    state.set_autopilot(True, "sess-A")
    assert state.get_autopilot("sess-A") is True
    assert state.get_autopilot("sess-B") is False
    state.set_autopilot(False, "sess-A")
    assert state.get_autopilot("sess-A") is False
