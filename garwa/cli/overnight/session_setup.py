"""cli/overnight/session_setup.py
Dipecah lebih lanjut dari cli/overnight.py.
"""
import os

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from ... import db as dbmod
from ... import tools as tools_module
from .. import _state as state
from ..skills import build_system_prompt



def _start_overnight_session(args, title: str):
    session_id = dbmod.create_session(args.db_path, args.workdir, title=title)
    tools_module.state.SESSION_ID = session_id
    os.environ["GARWA_SESSION_ID"] = session_id
    system_content = build_system_prompt(args.workdir, args.skills_dir,
                                         full_tool_schema=args.full_tool_schema_text)
    dbmod.add_message(args.db_path, session_id, "system", system_content, kind="chat")
    return session_id, system_content


def _read_plan_status(plan_path: str):
    """Hitung jumlah checkbox tercentang/belum di file plan (mis. tasks.md).
    Kalau file belum ada, dianggap (0, 0) -- loop --repeat-until-done tidak
    akan jalan sebelum file itu benar-benar dibuat oleh task pertama.
    """
    if not os.path.isfile(plan_path):
        return 0, 0
    with open(plan_path, "r", encoding="utf-8") as f:
        content = f.read()
    checked = len(state._CHECKBOX_CHECKED_RE.findall(content))
    unchecked = len(state._CHECKBOX_UNCHECKED_RE.findall(content))
    return checked + unchecked, unchecked
