"""cli/auto_mode.py
Dipecah otomatis dari cli.py (lihat cli/_state.py untuk state bersama).
"""
import re
import sys

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from .. import db as dbmod
from .agent_loop import run_agent_loop
from .colors import C
from .colors import c



def run_auto_mode(args, session_id: str, system_content: str):
    task = args.task
    if not task and args.tasks_file:
        tasks = parse_tasks_file(args.tasks_file)
        if not tasks:
            print(c(f"[ERROR] --tasks-file '{args.tasks_file}' kosong atau tidak berisi task valid.", C.RED))
            sys.exit(1)
        task = tasks[0]
        if len(tasks) > 1:
            print(c(
                f"[INFO] --tasks-file berisi {len(tasks)} task; mode --auto hanya "
                "menjalankan task pertama. Gunakan --overnight untuk menjalankan semuanya.",
                C.YELLOW,
            ))
    if not task:
        print(c("[ERROR] Mode --auto butuh --task \"...\" atau --tasks-file <path>.", C.RED))
        sys.exit(1)

    print(c(f"[AUTO] Menjalankan task: {task}", C.CYAN))
    print()
    dbmod.add_message(args.db_path, session_id, "user", task, kind="chat")

    try:
        run_agent_loop(args, session_id, system_content)
    except KeyboardInterrupt:
        print(c("\n[INTERRUPTED] Mode auto dibatalkan (Ctrl+C).", C.YELLOW))
        dbmod.touch_session(args.db_path, session_id)
        sys.exit(130)
    except Exception as e:
        print(c(f"\n[ERROR] Mode auto berhenti karena error: {type(e).__name__}: {e}", C.RED))
        dbmod.touch_session(args.db_path, session_id)
        sys.exit(1)

    dbmod.touch_session(args.db_path, session_id)
    print()
    print(c(f"[AUTO] Selesai. Lanjutkan sesi ini dengan: --resume {session_id}", C.DIM))


def parse_tasks_file(path: str) -> list:
    """Parse file daftar task.

    Default: satu task per baris non-kosong (baris berawalan '#' = komentar,
    diabaikan). Kalau file mengandung baris pemisah '---' (3+ dash), file
    diperlakukan sebagai blok multi-baris per task: tiap blok di antara
    pemisah menjadi satu task (baris komentar '#' di dalam blok tetap
    diabaikan), berguna untuk task panjang/instruksi multi-paragraf.
    """
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    blocks = re.split(r"\n[ \t]*-{3,}[ \t]*\n", "\n" + content.strip("\n") + "\n")
    blocks = [b.strip("\n") for b in blocks]

    if len(blocks) > 1:
        tasks = []
        for block in blocks:
            lines = [ln for ln in block.splitlines() if not ln.strip().startswith("#")]
            task = "\n".join(lines).strip()
            if task:
                tasks.append(task)
        return tasks

    tasks = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tasks.append(line)
    return tasks
