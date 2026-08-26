"""cli/main.py
Dipecah otomatis dari cli.py (lihat cli/_state.py untuk state bersama).
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

from ..tools import TOOLS
from .. import config
from .. import db as dbmod
from .. import tools as tools_module
from . import _state as state
from .agent_loop import run_agent_loop
from .auto_mode import run_auto_mode
from .colors import C
from .colors import c
from .colors import c_prompt
from .file_drop import _extract_dropped_paths
from .file_drop import handle_dropped_files
from .llm_client import _apply_detected_n_ctx
from .llm_client import check_llama_server_connection
from .overnight import run_overnight_mode
from .paste_input import _describe_paste
from .paste_input import _format_pasted_attachment
from .paste_input import read_user_input
from .skills import build_system_prompt
from .text_utils import confirm
from .tool_schema import _init_tool_registry



def main():
    parser = argparse.ArgumentParser(description="CLI coding agent lokal untuk Garwa via server OpenAI-compatible (server model, vLLM, dsb.)")
    parser.add_argument("--url", default=config.LLAMA_URL,
                         help="Endpoint chat completions server model "
                              "(default dari config.LLAMA_URL / env LLAMA_URL)")
    parser.add_argument("--api-key", default=config.LLAMA_API_KEY,
                         help="API key server model, dikirim sebagai header "
                              "Authorization: Bearer <key> (default dari "
                              "config.LLAMA_API_KEY / env LLAMA_API_KEY). "
                              "Kosongkan kalau server tidak pakai --api-key.")
    parser.add_argument("--model", default="deepseek-v4-flash-0731",
                         help="Nama model (server biasanya mengabaikan field ini, tapi tetap dikirim)")
    parser.add_argument("--temperature", type=float, default=0.6,
                         help="Sampling temperature. Untuk model DeepSeek-R1 "
                              "disarankan 0.5-0.7 (default 0.6) untuk mencegah "
                              "endless repetition / output tidak koheren. "
                              "Default lama CLI ini 0.2.")
    parser.add_argument("--skills-dir", default=state.DEFAULT_SKILLS_DIR,
                         help="Folder berisi paket skills (tiap subfolder punya SKILL.md), "
                              f"default: {state.DEFAULT_SKILLS_DIR}")
    parser.add_argument("--workdir", default=os.getcwd(), help="Working directory untuk tool file/bash")
    parser.add_argument("--no-sandbox", action="store_true",
                         help="Nonaktifkan sandbox: izinkan tool file/bash mengakses path di luar "
                              "--workdir (default: sandbox aktif, path di luar workdir ditolak). "
                              "Hati-hati -- ini membuka akses baca/tulis/eksekusi ke seluruh sistem.")
    parser.add_argument("--auto-approve", action="store_true",
                         help="Lewati konfirmasi untuk aksi destruktif (bash/write_file/edit_file)")
    parser.add_argument("--max-tool-iters", type=int, default=1000,
                         help="Batas jumlah pemanggilan tool berturut-turut per giliran user")
    parser.add_argument("--max-image-mb", type=float, default=8.0,
                         help="Batas ukuran (MB, sebelum base64) untuk gambar yang di-drop "
                              "yang mau dikirim sebagai vision input ke model. Gambar di atas "
                              "batas ini tetap dilampirkan sebagai tag metadata seperti biasa, "
                              "tapi TIDAK ikut isi visualnya (default: 8)")
    parser.add_argument("--context-window", type=int, default=131072,
                         help="Ukuran context window server model dalam token")
    parser.add_argument("--no-stream", action="store_true",
                         help="Matikan SSE streaming dan gunakan response JSON biasa")
    parser.add_argument("--full-tool-schema-text", action="store_true",
                         help="Tulis skema argumen tool LENGKAP sebagai teks di system "
                              "prompt (perilaku lama), selain field \"tools\" JSON. "
                              "Default: system prompt hanya memuat daftar nama tool + "
                              "deskripsi singkat, karena skema lengkap sudah dikirim "
                              "lewat field \"tools\" ala OpenAI di tiap request. Pakai "
                              "flag ini kalau server/model TIDAK memproses field "
                              "\"tools\" (mis. server tanpa --jinja, atau model yang "
                              "tidak dilatih untuk native tool-calling).")
    parser.add_argument("--skip-server-check", action="store_true",
                         help="Lewati pengecekan koneksi ke server model saat startup "
                              "(default: CLI mengecek endpoint /v1/models dulu sebelum "
                              "masuk ke prompt/menjalankan task -- sekalian membaca model "
                              "yang aktif untuk banner & prompt CLI -- supaya masalah "
                              "'server belum jalan/--url salah' ketahuan lebih awal, "
                              "bukan setelah mengetik pesan pertama).")
    parser.add_argument("--debug", action="store_true",
                         help="Aktifkan mode debug: cetak request (payload) dan SELURUH respon "
                              "mentah dari server model (tiap chunk SSE, baris yang gagal "
                              "di-parse, delta yang diekstrak, full JSON, dst) ke STDERR. "
                              "Berguna kalau ada bagian respon yang tampak belum ter-parsing "
                              "dengan benar. Simpan ke file dengan: ... --debug 2> debug.log")
    parser.add_argument("--db-path", default=dbmod.DEFAULT_DB_PATH,
                         help="Path file SQLite untuk histori sesi/plan/catatan proyek")
    parser.add_argument("--resume", nargs="?", const="__latest__", default=None, metavar="SESSION_ID",
                         help="Lanjutkan sesi sebelumnya. Tanpa nilai: lanjutkan sesi terbuka terakhir "
                              "di workdir ini. Dengan nilai: lanjutkan session id spesifik.")
    parser.add_argument("--list-sessions", action="store_true",
                         help="Tampilkan daftar sesi tersimpan untuk workdir ini lalu keluar")
    parser.add_argument("--session-title", default=None,
                         help="Judul opsional untuk sesi baru")
    parser.add_argument("--auto", action="store_true",
                         help="Mode auto: jalankan satu task secara non-interaktif lalu keluar "
                              "(pakai --task atau --tasks-file). Otomatis mengaktifkan --auto-approve.")
    parser.add_argument("--overnight", action="store_true",
                         help="Mode overnight: jalankan banyak task berurutan tanpa pengawasan, "
                              "tiap task di sesi baru, lanjut ke task berikutnya walau ada error "
                              "(kecuali --stop-on-error), seluruh transkrip dicatat ke file log. "
                              "Otomatis mengaktifkan --auto-approve.")
    parser.add_argument("--task", default=None,
                         help="Instruksi task untuk mode --auto (task tunggal), atau ditambahkan "
                              "sebagai task pertama untuk mode --overnight.")
    parser.add_argument("--tasks-file", default=None,
                         help="File berisi daftar task: satu per baris (baris '#' diabaikan), atau "
                              "blok multi-baris dipisah baris '---'. Dipakai mode --overnight (semua "
                              "task) atau --auto (hanya task pertama).")
    parser.add_argument("--overnight-log", default=None,
                         help="Path file log untuk mode --overnight (default: "
                              "<workdir>/.garwa_overnight/overnight_<timestamp>.log)")
    parser.add_argument("--stop-on-error", action="store_true",
                         help="Mode --overnight: hentikan seluruh antrian task begitu satu task "
                              "gagal, alih-alih lanjut ke task berikutnya (default: lanjut).")
    parser.add_argument("--plan-file", default=None, metavar="FILE",
                         help="Mode --overnight: nama file checklist markdown (relatif ke --workdir, "
                              "mis. tasks.md) berisi baris '- [ ] task' / '- [x] task'. Kalau diisi, "
                              "tiap giliran overnight diberi instruksi untuk membaca & memperbarui "
                              "file ini (checklist adalah satu-satunya memori bersama antar sesi).")
    parser.add_argument("--repeat-until-done", action="store_true",
                         help="Mode --overnight: setelah antrean --task/--tasks-file selesai, terus "
                              "ulangi task TERAKHIR di sesi baru selama --plan-file masih punya "
                              "'- [ ]' yang belum tercentang. Wajib dipakai bersama --plan-file.")
    parser.add_argument("--max-repeats", type=int, default=50,
                         help="Batas jumlah pengulangan untuk --repeat-until-done (default: 50)")
    args = parser.parse_args()

    if args.auto and args.overnight:
        print(c("[ERROR] --auto dan --overnight tidak bisa dipakai bersamaan.", C.RED))
        sys.exit(2)

    if args.max_image_mb <= 0:
        print(c("[ERROR] --max-image-mb harus lebih besar dari 0.", C.RED))
        sys.exit(2)
    state.MAX_VISION_IMAGE_BYTES = int(args.max_image_mb * 1024 * 1024)

    if (args.auto or args.overnight) and not args.auto_approve:
        print(c(
            f"[INFO] Mode {'--auto' if args.auto else '--overnight'} aktif -> --auto-approve "
            "otomatis diaktifkan (tidak ada manusia untuk menjawab konfirmasi).",
            C.YELLOW,
        ))
        args.auto_approve = True

    print(c(
        "  ██████╗  █████╗ ██████╗ ██╗    ██╗ █████╗ \n"
        " ██╔════╝ ██╔══██╗██╔══██╗██║    ██║██╔══██╗\n"
        " ██║  ███╗███████║██████╔╝██║ █╗ ██║███████║\n"
        " ╚██████╔╝██║  ██║██║  ██║╚███╔███╔╝██║  ██║\n",
        C.BOLD,
    ))
    print(c("Email: info@garwa.id", C.DIM))
    print(c("Website: www.garwa.id", C.DIM))
    print()

    os.environ["GARWA_WORKDIR"] = args.workdir
    tools_module.state.WORKDIR = args.workdir

    tools_module.state.SANDBOX_ENABLED = not args.no_sandbox

    tools_module.state.SKILLS_DIR = args.skills_dir

    tools_module.state.ALLOWED_EXTERNAL_PATHS = set()

    _init_tool_registry()

    try:
        dbmod.init_db(args.db_path)
    except Exception as e:

        print(c(f"[ERROR] Gagal menyiapkan database sesi di '{args.db_path}': {type(e).__name__}: {e}", C.RED))
        sys.exit(1)

    if args.list_sessions:
        rows = dbmod.list_sessions(args.db_path, workdir=args.workdir)
        if not rows:
            print(c("(belum ada sesi tersimpan untuk workdir ini)", C.DIM))
        for r in rows:
            status = "terbuka" if not r["ended"] else "selesai"
            title = r["title"] or "(tanpa judul)"
            print(f"{r['id']}  [{status}]  {title}")
        return

    model_id = None
    if not args.skip_server_check and not args.overnight:

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
                f"[WARN] Tidak bisa menjangkau server model di {args.url} ({detail}). "
                "Pastikan server model sudah berjalan dan --url mengarah ke alamat "
                "yang benar.",
                C.RED,
            ))
            if args.auto:

                print(c(
                    "[ERROR] Mode --auto butuh server model aktif sejak awal. "
                    "Jalankan server model dulu, atau lewati pengecekan ini "
                    "dengan --skip-server-check kalau Anda yakin ini false negative "
                    "(mis. server tidak punya endpoint /v1/models).",
                    C.RED,
                ))
                sys.exit(1)
            if not confirm("Tetap masuk ke CLI meski begitu?"):
                sys.exit(1)
        print()

    if args.overnight:

        run_overnight_mode(args)
        return

    session = None
    if args.resume:
        if args.resume == "__latest__":
            session = dbmod.latest_open_session(args.db_path, args.workdir)
            if not session:
                print(c("Tidak ada sesi terbuka untuk workdir ini, membuat sesi baru.", C.YELLOW))
        else:
            session = dbmod.get_session(args.db_path, args.resume)
            if not session:
                print(c(f"Sesi '{args.resume}' tidak ditemukan, membuat sesi baru.", C.YELLOW))

    resumed = session is not None
    if session is None:
        session_id = dbmod.create_session(args.db_path, args.workdir, title=args.session_title)
    else:
        session_id = session["id"]

    tools_module.state.DB_PATH = args.db_path
    tools_module.state.SESSION_ID = session_id
    os.environ["GARWA_DB_PATH"] = args.db_path
    os.environ["GARWA_SESSION_ID"] = session_id

    print(c(f"{state.AGENT_NAME} CLI — coding agent lokal (Ctrl+C untuk keluar)", C.BOLD))
    print(c(f"server model: {args.url}", C.DIM))
    print(c(f"model       : {model_id or args.model}", C.DIM))
    print(c(
        f"auth        : {'aktif (API key di-set)' if args.api_key else 'TIDAK aktif (tanpa API key)'}",
        C.DIM,
    ))
    print(c(f"workdir     : {args.workdir}", C.DIM))
    print(c(f"mode        : {'auto' if args.auto else 'interaktif'}", C.DIM))
    print(c(f"auto-approve: {args.auto_approve}", C.DIM))
    print(c(f"debug       : {args.debug}{' (lihat STDERR)' if args.debug else ''}", C.DIM))
    print(c(f"session     : {session_id} ({'dilanjutkan' if resumed else 'baru'})", C.DIM))
    print()

    system_content = build_system_prompt(args.workdir, args.skills_dir,
                                         full_tool_schema=args.full_tool_schema_text)

    if not resumed:
        dbmod.add_message(
            args.db_path,
            session_id,
            "system",
            system_content,
            kind="chat",
        )

    if resumed:
        todos = dbmod.get_todos(args.db_path, session_id)
        if todos:
            print(c(f"({len(todos)} item plan tersimpan -- gunakan tool todo_read untuk melihatnya)", C.DIM))

    if args.auto:
        run_auto_mode(args, session_id, system_content)
        return

    while True:
        try:
            user_input = read_user_input(c_prompt("You> ", C.GREEN))
        except (EOFError, KeyboardInterrupt):
            dbmod.touch_session(args.db_path, session_id)
            print(f"\nSampai jumpa. Lanjutkan sesi ini dengan: --resume {session_id}")
            break

        if not user_input.strip():
            continue
        if user_input.strip() in ("/exit", "/quit"):
            dbmod.end_session(args.db_path, session_id)
            break

        dropped_paths = _extract_dropped_paths(user_input)
        if dropped_paths:

            try:
                message_to_store = handle_dropped_files(dropped_paths, args.workdir)
            except (EOFError, KeyboardInterrupt):

                print(c(
                    "\n[DIBATALKAN] Konfirmasi lampiran file dibatalkan. "
                    "Kembali ke prompt.",
                    C.YELLOW,
                ))
                continue
            if not message_to_store:

                continue
        elif "\n" in user_input:

            print(c(_describe_paste(user_input), C.DIM))
            message_to_store = _format_pasted_attachment(user_input)
        else:
            message_to_store = user_input

        dbmod.add_message(args.db_path, session_id, "user", message_to_store, kind="chat")

        try:
            run_agent_loop(args, session_id, system_content)
        except KeyboardInterrupt:

            print(c(
                "\n[INTERRUPTED] Giliran dibatalkan (Ctrl+C). Kembali ke prompt.",
                C.YELLOW,
            ))
            dbmod.touch_session(args.db_path, session_id)
        except requests.exceptions.RequestException as e:

            print(c(
                f"\n[ERROR] Giliran ini gagal karena masalah koneksi/streaming "
                f"ke server model ({type(e).__name__}: {e}). Sesi tetap "
                f"jalan -- coba kirim pesan lagi, atau periksa apakah "
                f"server model masih hidup.",
                C.RED,
            ))
            dbmod.touch_session(args.db_path, session_id)
        except Exception as e:

            print(c(
                f"\n[ERROR] Giliran ini berhenti karena error tak terduga: "
                f"{type(e).__name__}: {e}. Kembali ke prompt.",
                C.RED,
            ))
            dbmod.touch_session(args.db_path, session_id)

        print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:

        print("\n[INTERRUPTED] Dibatalkan (Ctrl+C).")
        sys.exit(130)
    except Exception as e:

        print(f"\n[ERROR] {state.AGENT_NAME} CLI berhenti karena error tak terduga: {type(e).__name__}: {e}")
        sys.exit(1)
