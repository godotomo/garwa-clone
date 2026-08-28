"""cli/overnight/task_runner.py
Dipecah lebih lanjut dari cli/overnight.py.
"""
import time

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from ... import db as dbmod
from .. import _state as state
from ..agent_loop import run_agent_loop
from ..colors import C
from ..colors import c
from .session_setup import _start_overnight_session



def _run_one_overnight_task(args, label: str, task_text: str) -> dict:
    """Jalankan satu task overnight di sesinya sendiri (fresh session, tanpa
    histori sesi lain) dan kembalikan ringkasan hasilnya. Dipakai baik untuk
    antrean task awal maupun untuk giliran ulang --repeat-until-done.
    """
    task_start = time.time()
    title = f"overnight: {task_text.splitlines()[0][:60]}"
    session_id, system_content = _start_overnight_session(args, title)

    full_task = task_text
    if args.plan_file:
        full_task = state.PLAN_FILE_PROTOCOL.format(plan_file=args.plan_file, task=task_text)

    dbmod.add_message(args.db_path, session_id, "user", full_task, kind="chat")

    status, error_text = "completed", None
    try:
        run_agent_loop(args, session_id, system_content)
    except KeyboardInterrupt:
        status = "interrupted"
        print(c("\n[INTERRUPTED] Ctrl+C -- menghentikan mode overnight.", C.YELLOW))
    except Exception as e:
        status = "failed"
        error_text = f"{type(e).__name__}: {e}"
        print(c(f"\n[ERROR] Task '{label}' gagal: {error_text}", C.RED))

    if status == "interrupted":
        dbmod.touch_session(args.db_path, session_id)
    else:
        dbmod.end_session(args.db_path, session_id)

    return {
        "label": label, "task": task_text, "session_id": session_id,
        "status": status, "error": error_text,
        "elapsed_sec": round(time.time() - task_start, 1),
    }


def _print_result_line(r: dict):
    mark, color = {
        "completed": ("✓", C.GREEN),
        "failed": ("✗", C.RED),
        "interrupted": ("⚠", C.YELLOW),
    }[r["status"]]
    first_line = r["task"].splitlines()[0][:80]
    print(c(f"  [{mark}] {r['label']} ({r['elapsed_sec']}s) session={r['session_id']} -- {first_line}", color))
    if r["error"]:
        print(c(f"        error: {r['error']}", C.DIM))
