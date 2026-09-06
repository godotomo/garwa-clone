"""Verifikasi sementara: semua slash command baru terekspos & berfungsi."""
import os
import tempfile

from garwa.cli import slash_commands as sc
from garwa import db as dbmod


def _make_args(db_path, workdir):
    class A:
        pass
    a = A()
    a.db_path = db_path
    a.workdir = workdir
    a.model = "test-model"
    a.url = "http://localhost:9999"
    a.api_key = "k"
    a.context_window = 8000
    a.reserve_for_response = 0
    a.summarize_model = None
    a.keep_tail_messages = None
    a.session_title = None
    a.skills_dir = ""
    a.full_tool_schema_text = ""
    a.auto_approve = False
    return a


def test_all_new_commands_exposed():
    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "test.db")
        dbmod.init_db(db_path)
        workdir = os.path.join(td, "proj")
        os.makedirs(workdir, exist_ok=True)
        sid = dbmod.create_session(db_path, workdir, title="t")
        dbmod.add_message(db_path, sid, "user", "halo", kind="chat")
        dbmod.add_message(db_path, sid, "assistant", "hai", kind="chat")
        dbmod.set_note(db_path, workdir, "k1", "nilai satu")
        args = _make_args(db_path, workdir)

        # cost
        r = sc.handle_slash_command("/cost", args, sid, "")
        assert r == {"action": "skip"}

        # status
        r = sc.handle_slash_command("/status", args, sid, "")
        assert r == {"action": "skip"}

        # memory list
        r = sc.handle_slash_command("/memory list", args, sid, "")
        assert r == {"action": "skip"}

        # memory show
        r = sc.handle_slash_command("/memory show k1", args, sid, "")
        assert r == {"action": "skip"}

        # memory forget
        r = sc.handle_slash_command("/memory forget k1", args, sid, "")
        assert r == {"action": "skip"}
        assert dbmod.get_notes(db_path, workdir) == []

        # sessions
        r = sc.handle_slash_command("/sessions", args, sid, "")
        assert r == {"action": "skip"}

        # summary (belum ada summary -> skip, tidak crash)
        r = sc.handle_slash_command("/summary", args, sid, "")
        assert r == {"action": "skip"}

        # summary dengan data -> menampilkan isi
        dbmod.save_summary(db_path, sid, upto_message_id=2,
                           summary_text="ringkasan uji", active_instructions=[])
        r = sc.handle_slash_command("/summary", args, sid, "")
        assert r == {"action": "skip"}

        # export -> file markdown dibuat
        r = sc.handle_slash_command("/export", args, sid, "")
        assert r == {"action": "skip"}
        exports = [f for f in os.listdir(workdir) if f.startswith("garwa_export_")]
        assert exports, "file export tidak dibuat"
        with open(os.path.join(workdir, exports[0]), encoding="utf-8") as f:
            content = f.read()
        assert "halo" in content and "hai" in content

        # compact (server tidak hidup -> harus fallback tanpa crash)
        r = sc.handle_slash_command("/compact", args, sid, "sys")
        assert r == {"action": "skip"}
