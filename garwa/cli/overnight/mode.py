"""cli/overnight/mode.py
Dipecah lebih lanjut dari cli/overnight.py.
"""
import argparse
import base64
import copy
import difflib
import json
import mimetypes
import os
import re
import select
import shlex
import shutil
import sys
import time
import unicodedata
from collections import OrderedDict
from datetime import datetime
from urllib.parse import unquote, urlparse

try:

    import readline  # noqa: F401
except ImportError:
    readline = None

import requests

from ...tools import TOOLS
from .. import _state as state
from ..agent_loop import run_agent_loop
from ..auto_mode import parse_tasks_file
from ..colors import C
from ..colors import c
from ..llm_client import _apply_detected_n_ctx
from ..llm_client import check_llama_server_connection
from ..skills import build_system_prompt
from .session_setup import _read_plan_status
from .task_runner import _print_result_line
from .task_runner import _run_one_overnight_task
from .tee_stdout import _TeeStdout



def run_overnight_mode(args):
    tasks = []
    if args.tasks_file:
        tasks = parse_tasks_file(args.tasks_file)
    if args.task:
        tasks = [args.task] + tasks
    if not tasks:
        print(c(
            "[ERROR] Mode --overnight butuh --tasks-file <path> (satu task per baris) "
            "dan/atau --task \"...\".",
            C.RED,
        ))
        sys.exit(1)
    if args.repeat_until_done and not args.plan_file:
        print(c("[ERROR] --repeat-until-done butuh --plan-file <nama_file> (mis. tasks.md).", C.RED))
        sys.exit(1)

    plan_path = None
    if args.plan_file:
        plan_path = args.plan_file if os.path.isabs(args.plan_file) else \
            os.path.join(args.workdir, args.plan_file)

    log_dir = os.path.dirname(args.overnight_log) if args.overnight_log else \
        os.path.join(args.workdir, ".garwa_overnight")
    log_path = args.overnight_log or os.path.join(
        log_dir, f"overnight_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    try:
        os.makedirs(log_dir or ".", exist_ok=True)
        log_file = open(log_path, "a", encoding="utf-8")
    except OSError as e:

        print(c(f"[ERROR] Tidak bisa membuka file log overnight '{log_path}': {e}", C.RED))
        sys.exit(1)

    orig_stdout = sys.stdout
    sys.stdout = _TeeStdout(orig_stdout, log_file)

    try:

        model_id = None
        if not args.skip_server_check:
            print(c(f"[CHECK] Mengecek koneksi ke server model di {args.url} ...", C.DIM))
            ok, detail, model_id, n_ctx = check_llama_server_connection(args.url, args.api_key)
            if ok:
                if model_id:
                    print(c(f"[OK] server model terjangkau. Model aktif: {model_id}", C.GREEN))
                else:
                    print(c(
                        "[OK] server model terjangkau (nama model tidak terbaca dari "
                        "/v1/models -- tetap lanjut).",
                        C.GREEN,
                    ))
                if n_ctx:
                    _apply_detected_n_ctx(args, n_ctx, source_label="/props")
                else:
                    print(c(
                        "[WARN] Tidak bisa membaca n_ctx dari /props -- tetap pakai "
                        f"asumsi statis --context-window={args.context_window}. Kalau "
                        "ini beda dari ctx-size sungguhan di server, request masih "
                        "bisa ditolak 400 (tapi sekarang otomatis di-retry, lihat "
                        "penanganan ContextExceededError).",
                        C.YELLOW,
                    ))
            else:
                print(c(
                    f"[ERROR] Tidak bisa menjangkau server model di {args.url} ({detail}). "
                    "Mode --overnight tidak ada manusia untuk menjawab konfirmasi, jadi "
                    "berhenti sekarang alih-alih menjalankan antrean task yang pasti "
                    "gagal semua. Jalankan server model dulu, atau lewati pengecekan "
                    "ini dengan --skip-server-check kalau Anda yakin ini false negative "
                    "(mis. server tidak punya endpoint /v1/models).",
                    C.RED,
                ))
                sys.exit(1)
            print()

        print(c(f"{state.AGENT_NAME} CLI — mode overnight (tanpa pengawasan)", C.BOLD))
        print(c(f"server model      : {args.url}", C.DIM))
        print(c(f"model             : {model_id or args.model}", C.DIM))
        print(c(f"workdir           : {args.workdir}", C.DIM))
        print(c(f"jumlah task awal  : {len(tasks)}", C.DIM))
        print(c(f"stop-on-error     : {args.stop_on_error}", C.DIM))
        print(c(f"debug             : {args.debug}{' (lihat STDERR)' if args.debug else ''}", C.DIM))
        if args.plan_file:
            print(c(f"plan file         : {args.plan_file}", C.DIM))
            print(c(f"repeat-until-done : {args.repeat_until_done} (max {args.max_repeats}x)", C.DIM))
        print(c(f"log file          : {log_path}", C.DIM))
        print()

        results = []
        start_all = time.time()
        stopped_early = False

        for i, task in enumerate(tasks, start=1):
            print(c(
                f"--- [{i}/{len(tasks)}] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---",
                C.MAGENTA,
            ))
            print(c(f"Task: {task}", C.BOLD))
            print()

            r = _run_one_overnight_task(args, f"#{i}", task)
            results.append(r)
            print()

            if r["status"] == "interrupted":
                stopped_early = True
                break
            if r["status"] == "failed" and args.stop_on_error:
                print(c("[STOP] --stop-on-error aktif, menghentikan sisa task.", C.YELLOW))
                stopped_early = True
                break

        if args.repeat_until_done and not stopped_early and tasks:
            last_task = tasks[-1]
            repeats = 0
            while repeats < args.max_repeats:
                total, unchecked = _read_plan_status(plan_path)
                if unchecked <= 0:
                    if total > 0:
                        print(c(f"[PLAN] Semua {total} item di {args.plan_file} sudah tercentang. Berhenti mengulang.", C.GREEN))
                    else:
                        print(c(f"[PLAN] {args.plan_file} belum ditemukan/berisi checklist -- berhenti mengulang.", C.YELLOW))
                    break
                repeats += 1
                print(c(
                    f"--- [ulang #{repeats}/{args.max_repeats}] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                    f"-- {unchecked}/{total} item belum selesai di {args.plan_file} ---",
                    C.MAGENTA,
                ))
                print(c(f"Task: {last_task}", C.BOLD))
                print()

                r = _run_one_overnight_task(args, f"ulang#{repeats}", last_task)
                results.append(r)
                print()

                if r["status"] == "interrupted":
                    break
                if r["status"] == "failed" and args.stop_on_error:
                    print(c("[STOP] --stop-on-error aktif, menghentikan pengulangan.", C.YELLOW))
                    break
            else:
                print(c(f"[PLAN] Batas --max-repeats ({args.max_repeats}) tercapai, masih ada item belum selesai.", C.YELLOW))

        total_elapsed = time.time() - start_all
        completed = sum(1 for r in results if r["status"] == "completed")
        failed = sum(1 for r in results if r["status"] == "failed")

        print(c("=== Ringkasan overnight ===", C.BOLD))
        for r in results:
            _print_result_line(r)
        print(c(
            f"Total: {len(results)} giliran dijalankan, {completed} selesai, "
            f"{failed} gagal, durasi {total_elapsed / 60:.1f} menit.",
            C.BOLD,
        ))
        if plan_path:
            total, unchecked = _read_plan_status(plan_path)
            if total:
                print(c(f"Status {args.plan_file}: {total - unchecked}/{total} item tercentang.", C.DIM))
        print(c(f"Log lengkap tersimpan di: {log_path}", C.DIM))
    finally:
        sys.stdout = orig_stdout
        log_file.close()
