"""cli/main.py
Dipecah otomatis dari cli.py (lihat cli/_state.py untuk state bersama).
"""
import argparse
import os
import sys
import time
from typing import Optional

try:

    import readline  # noqa: F401
except ImportError:
    readline = None

import requests

from .. import config
from .. import db as dbmod
from .. import tools as tools_module
from . import _state as state
from .. import __version__
from .agent_loop import run_agent_loop
from .auto_mode import run_auto_mode
from .colors import C
from .colors import c
from .file_drop import _extract_dropped_paths
from .file_drop import handle_dropped_files
from .llm_client import _apply_detected_n_ctx
from .llm_client import check_llama_server_connection
from .overnight import run_overnight_mode
from .paste_input import _describe_paste
from .paste_input import _format_pasted_attachment
from .prompt_ui import prompt_with_status
from .skills import build_system_prompt
from .slash_commands import handle_slash_command
from .text_utils import confirm
from .tool_schema import _init_tool_registry
from ..mcp import MCPToolRegistry, load_mcp_config, mcp_available
from ..mcp.client import set_global_registry


# Lokasi file history readline (persisten antar sesi CLI).
HISTORY_DIR = os.path.join(os.path.expanduser("~"), ".garwa")
HISTORY_FILE = os.path.join(HISTORY_DIR, "history.txt")
HISTORY_MAX = 1000


def _init_readline_history() -> None:
    """Load history readline dari disk (persisten antar sesi).

    History disimpan per mesin di ~/.garwa/history.txt agar perintah yang
    pernah diketik (prompt, slash-command) bisa dinavigasi ulang dengan
    panah atas/bawah meski CLI sudah ditutup lalu dibuka lagi.
    """
    if readline is None:
        return  # platform tanpa modul readline (mis. Windows murni)
    try:
        os.makedirs(HISTORY_DIR, exist_ok=True)
        if os.path.exists(HISTORY_FILE):
            readline.read_history_file(HISTORY_FILE)
        readline.set_history_length(HISTORY_MAX)
    except Exception:
        # History bersifat best-effort; kegagalan tidak boleh menghentikan CLI.
        pass


def _save_readline_history() -> None:
    """Simpan history readline ke disk saat CLI berhenti."""
    if readline is None:
        return
    try:
        os.makedirs(HISTORY_DIR, exist_ok=True)
        readline.write_history_file(HISTORY_FILE)
    except Exception:
        pass




def _init_mcp(mcp_config: Optional[str]) -> Optional[MCPToolRegistry]:
    """Inisialisasi integrasi MCP dan daftarkan tool eksternal ke TOOLS.

    Membaca konfigurasi (default ~/.config/garwa/mcp.json), menyambungkan ke
    tiap server, mengambil daftar tool, lalu mendaftarkannya ke `TOOLS`
    dengan prefix `mcp.<server>.<tool>`. Mengembalikan registry (untuk
    dibersihkan saat shutdown) atau None bila tidak ada konfigurasi / SDK
    tidak tersedia.
    """
    if not mcp_available():
        print(c(
            "[WARN] Modul 'mcp' tidak terinstall. Integrasi MCP dinonaktifkan. "
            "Install dengan: pip install 'mcp>=2.0'",
            C.YELLOW,
        ))
        return None

    configs = load_mcp_config(mcp_config)
    if not configs:
        return None

    registry = MCPToolRegistry(configs)
    registry.connect_all()
    tools = registry.list_tools()
    if tools:
        tools_module.TOOLS.update(tools)
        # Tool MCP ditambahkan ke TOOLS setelah _init_tool_registry() dipanggil
        # di main(); panggil ulang agar tool MCP ikut terdaftar di REGISTRY
        # (fungsi ini idempoten -- menimpa key yang sama).
        _init_tool_registry()
        set_global_registry(registry)
        print(c(
            f"[MCP] Terhubung ke {len(registry._connected)} server, "
            f"{registry.tool_count()} tool eksternal didaftarkan "
            f"(prefix 'mcp.<server>.<tool>').",
            C.GREEN,
        ))
    else:
        print(c("[MCP] Tidak ada tool MCP yang berhasil didaftarkan.", C.YELLOW))
    return registry


def _close_mcp(registry: Optional[MCPToolRegistry]) -> None:
    """Tutup koneksi ke semua server MCP saat aplikasi keluar.

    Idempoten dan aman dipanggil di tiap titik keluar main() -- registry
    None (MCP tidak aktif) langsung diabaikan.
    """
    if registry is not None:
        try:
            registry.close_all()
        except Exception as e:  # noqa: BLE001 - cleanup tak boleh menggagalkan exit
            print(c(f"[WARN] Gagal menutup koneksi MCP: {e}", C.YELLOW))


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
    parser.add_argument("--max-tool-iters", type=int, default=100,
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
    parser.add_argument("--mcp-config", default=None, metavar="FILE",
                        help="Path ke file konfigurasi MCP (format mirip mcpServers Claude "
                             "Desktop). Default: ~/.config/garwa/mcp.json. Tool dari server "
                             "MCP didaftarkan dengan prefix 'mcp.<server>.<tool>'.")
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
        C.BOLD_CYAN,
    ))
    print(c(f"Garwa CLI v{__version__} — coding agent lokal", C.BOLD))
    print(c("Email: info@garwa.id", C.DIM))
    print(c("Website: www.garwa.id", C.DIM))
    print()

    os.environ["GARWA_WORKDIR"] = args.workdir
    tools_module.state.WORKDIR = args.workdir

    tools_module.state.SANDBOX_ENABLED = not args.no_sandbox

    tools_module.state.SKILLS_DIR = args.skills_dir

    tools_module.state.ALLOWED_EXTERNAL_PATHS = set()

    _init_tool_registry()

    # Integrasi MCP: daftarkan tool dari MCP server eksternal (jika ada).
    # Tool MCP didaftarkan ke TOOLS dengan prefix 'mcp.<server>.<tool>' dan
    # handler yang membungkus ClientSession.call_tool. Mesin eksekusi tool
    # Garwa (execute_tool / run_tool_with_runtime) tidak diubah.
    _mcp_registry = _init_mcp(args.mcp_config)

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
        _close_mcp(_mcp_registry)
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
    state.TOOL_CALL_TOTAL = 0
    state.TOKEN_USAGE_TOTAL = {"prompt_tokens": 0, "completion_tokens": 0,
                               "reasoning_tokens": 0, "total": 0}
    state.SESSION_START_TIME = time.time()
    state.ERROR_TOTAL = 0
    os.environ["GARWA_DB_PATH"] = args.db_path
    os.environ["GARWA_SESSION_ID"] = session_id

    print(c(f"{state.AGENT_NAME} CLI — coding agent lokal (Ctrl+C untuk keluar)", C.BOLD_CYAN))
    print(c(f"server model: {args.url}", C.DIM))
    print(c(f"model       : {model_id or args.model}", C.BOLD_BLUE))
    print(c(
        f"auth        : {'aktif (API key di-set)' if args.api_key else 'TIDAK aktif (tanpa API key)'}",
        C.GREEN if args.api_key else C.RED,
    ))
    print(c(f"workdir     : {args.workdir}", C.DIM))
    print(c(f"mode        : {'auto' if args.auto else 'interaktif'}", C.BOLD_MAGENTA))
    print(c(f"auto-approve: {args.auto_approve}", C.DIM))
    print(c(f"debug       : {args.debug}{' (lihat STDERR)' if args.debug else ''}", C.DIM))
    print(c(
        f"session     : {session_id} ({'dilanjutkan' if resumed else 'baru'})",
        C.BOLD_GREEN if resumed else C.BOLD_YELLOW,
    ))
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
        try:
            run_auto_mode(args, session_id, system_content)
        finally:
            _close_mcp(_mcp_registry)
        return

    workdir_label = os.path.basename(os.path.normpath(args.workdir)) or args.workdir
    prompt_label = _build_prompt_label(args, session_id, workdir_label)
    _init_readline_history()
    try:
        while True:
            try:
                user_input = prompt_with_status(
                    f"{prompt_label} ❯ ",
                    _build_status_info(args, session_id),
                )
            except (EOFError, KeyboardInterrupt):
                dbmod.touch_session(args.db_path, session_id)
                print(f"\nSampai jumpa. Lanjutkan sesi ini dengan: --resume {session_id}")
                break

            if not user_input.strip():
                continue

            # --- Slash-command (diproses sebelum drop file / paste / ke model) ---
            if user_input.strip().startswith("/"):
                result = handle_slash_command(user_input, args, session_id, system_content)
                action = result.get("action", "continue")

                if action == "exit":
                    dbmod.end_session(args.db_path, session_id)
                    break

                if action in ("new_session", "resume"):
                    # Ganti sesi aktif: simpan env/state baru, lanjut loop.
                    session_id = result["session_id"]
                    system_content = result["system_content"]
                    tools_module.state.SESSION_ID = session_id
                    state.TOOL_CALL_TOTAL = 0
                    state.TOKEN_USAGE_TOTAL = {"prompt_tokens": 0, "completion_tokens": 0,
                                               "reasoning_tokens": 0, "total": 0}
                    state.SESSION_START_TIME = time.time()
                    state.ERROR_TOTAL = 0
                    os.environ["GARWA_SESSION_ID"] = session_id
                    prompt_label = _build_prompt_label(args, session_id, workdir_label)
                    continue

                if action == "skip":
                    # Beberapa slash-command (/approve, /api-model, /ctx) mengubah
                    # args -- rebuild label status bar supaya prompt ikut update.
                    prompt_label = _build_prompt_label(args, session_id, workdir_label)
                    continue

                # action == "continue" -> command tak dikenal, jatuh ke bawah
                # sebagai pesan biasa ke model.

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

                state._accumulate_error()
                print(c(
                    f"\n[ERROR] Giliran ini gagal karena masalah koneksi/streaming "
                    f"ke server model ({type(e).__name__}: {e}). Sesi tetap "
                    f"jalan -- coba kirim pesan lagi, atau periksa apakah "
                    f"server model masih hidup.",
                    C.RED,
                ))
                dbmod.touch_session(args.db_path, session_id)
            except Exception as e:

                state._accumulate_error()
                print(c(
                    f"\n[ERROR] Giliran ini berhenti karena error tak terduga: "
                    f"{type(e).__name__}: {e}. Kembali ke prompt.",
                    C.RED,
                ))
                dbmod.touch_session(args.db_path, session_id)

            print()
    finally:
        _save_readline_history()
        _close_mcp(_mcp_registry)


def _build_prompt_label(args, session_id, workdir_label):
    """Buat label prompt ringkas: `garwa@workdir`.

    Info detail (model, context window, session id, status auto-approve)
    dipindah ke status bar terpisah lewat _build_status_info() supaya
    prompt tetap pendek dan tidak memenuhi baris.
    """
    return f"garwa@{workdir_label}"


def _build_status_info(args, session_id):
    """Buat string info status bar (model, ctx, ses, tools, sandbox, auto)
    secara real-time dari args (yang bisa berubah via slash-command).

    Didesain untuk dicetak sebagai baris status redup tepat di atas prompt,
    sehingga prompt utama tetap ringkas (`garwa@workdir ❯`).
    """
    model = getattr(args, "model", "?")
    ctx = getattr(args, "context_window", None)
    auto = getattr(args, "auto_approve", False)
    sandbox = getattr(tools_module.state, "SANDBOX_ENABLED", True)
    tools_count = getattr(state, "TOOL_CALL_TOTAL", 0)

    parts = [f"[{model}]"]
    if ctx:
        parts.append(f"ctx:{ctx}")
    parts.append(f"ses:{session_id[:8]}")
    parts.append(f"tools:{tools_count}")
    # Pemakaian token global (akumulasi lintas giliran dalam sesi ini).
    usage_total = getattr(state, "TOKEN_USAGE_TOTAL", None)
    if usage_total:
        parts.append(f"tok:{usage_total.get('total', 0)}")
    # Sandbox & auto-approve selalu ditampilkan eksplisit (ON/OFF) supaya
    # user sadar mode keamanan & persetujuan yang sedang aktif -- tidak
    # hanya muncul saat ON seperti sebelumnya.
    parts.append(f"sandbox:{'ON' if sandbox else 'OFF'}")
    parts.append(f"auto:{'ON' if auto else 'OFF'}")
    # Workdir aktif -- penting saat user pindah direktori via slash-command.
    workdir = getattr(tools_module.state, "WORKDIR", None)
    if workdir:
        parts.append(f"wd:{os.path.basename(os.path.normpath(workdir)) or workdir}")
    # Durasi sesi berjalan (sejak SESSION_START_TIME di-set).
    start = getattr(state, "SESSION_START_TIME", None)
    if start:
        elapsed = int(time.time() - start)
        if elapsed >= 3600:
            dur = f"{elapsed // 3600}h{elapsed % 3600 // 60}m"
        elif elapsed >= 60:
            dur = f"{elapsed // 60}m"
        else:
            dur = f"{elapsed}s"
        parts.append(f"dur:{dur}")
    # Jumlah giliran yang gagal karena error dalam sesi ini.
    err = getattr(state, "ERROR_TOTAL", 0)
    if err:
        parts.append(f"err:{err}")
    return " ".join(parts)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:

        print("\n[INTERRUPTED] Dibatalkan (Ctrl+C).")
        sys.exit(130)
    except Exception as e:

        print(f"\n[ERROR] {state.AGENT_NAME} CLI berhenti karena error tak terduga: {type(e).__name__}: {e}")
        sys.exit(1)
