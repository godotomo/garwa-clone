"""cli/slash_commands.py
Perintah-perintah slash (diawali '/') untuk mode interaktif Garwa CLI.

Dibuat terpisah dari main.py supaya daftar command, parsing, dan help
mudah dirawat & diuji. Fungsi utama `handle_slash_command` TIDAK
mengeksekusi aksi yang mengubah alur loop (seperti ganti sesi / keluar)
secara langsung -- ia mengembalikan dict "aksi" yang diinterpretasikan
oleh loop di main.py, sehingga alur kontrol tetap satu tempat.
"""
from .. import config
from .. import db as dbmod
from .. import tools as tools_module
from ..tools import TOOLS
from . import _state as state
from .colors import C
from .colors import c
from .colors import c_prompt
from .skills import build_system_prompt


# Nama command yang TIDAK boleh dianggap sebagai pesan biasa ke model.
# Kunci = nama command (tanpa '/'), nilai = deskripsi singkat untuk /help.
COMMANDS = {
    "help": "Tampilkan daftar perintah slash ini",
    "clear": "Bersihkan layar terminal (Ctrl+L)",
    "new": "Mulai sesi baru (histori sesi lama tetap tersimpan)",
    "resume": "Lanjutkan sesi: /resume <session_id>, atau /resume untuk sesi terbuka terakhir",
    "model": "Ganti model aktif: /model <nama> (mis. /model deepseek-v4-flash-0731)",
    "url": "Ganti endpoint server model: /url <http://host:port>",
    "api-key": "Ganti API key server model: /api-key <kunci> (kosongkan untuk menghapus)",
    "ctx": "Ubah context window (token): /ctx <angka>",
    "github-token": "Ganti token GitHub: /github-token <token> (kosongkan untuk menghapus)",
    "github-max": "Batas konten file yang dibaca GitHub (karakter): /github-max <angka>",
    "news-lang": "Bahasa hasil pencarian berita: /news-lang <kode> (mis. id, en, de, ja)",
    "approve": "Toggle auto-approve (lewati konfirmasi aksi destruktif) on/off",
    "todos": "Cetak plan/todo list sesi ini ke layar",
    "tools": "Tampilkan daftar tool yang tersedia",
    "exit": "Selesai & simpan sesi (alias: /quit)",
    "quit": "Selesai & simpan sesi (alias: /exit)",
}

# Command yang butuh argumen tambahan.
_COMMANDS_WITH_ARGS = {"resume", "model", "url", "api-key", "ctx", "github-token", "github-max", "news-lang"}


def _print_help() -> None:
    print(c("Perintah slash:", C.BOLD))
    width = max(len(name) for name in COMMANDS)
    for name, desc in COMMANDS.items():
        print(c(f"  /{name.ljust(width)}  {desc}", C.DIM))


def _clear_screen() -> None:
    # ANSI clear + home cursor. Bekerja di hampir semua terminal modern.
    print("\x1b[2J\x1b[H", end="")


def _print_todos(session_id: str) -> None:
    todos = dbmod.get_todos(state.DB_PATH, session_id)
    if not todos:
        print(c("(belum ada plan/todo tersimpan untuk sesi ini)", C.DIM))
        return
    print(c(f"Plan sesi ({len(todos)} item):", C.BOLD))
    mark_by_status = {
        "pending": "[ ]",
        "in_progress": "[~]",
        "done": "[x]",
        "cancelled": "[-]",
    }
    for t in todos:
        status = t.get("status", "pending")
        mark = mark_by_status.get(status, "[ ]")
        print(f"  {mark} {t.get('content', '')}")


def _print_tools() -> None:
    if not TOOLS:
        print(c("(belum ada tool yang terdaftar)", C.DIM))
        return
    print(c("Tool yang tersedia:", C.BOLD))
    for key, spec in TOOLS.items():
        # TOOLS adalah dict: kunci = nama tool, nilai = dict {handler, destructive, schema}.
        schema = spec.get("schema", {}) if isinstance(spec, dict) else {}
        name = schema.get("name") or key
        desc = (schema.get("description", "") or "").strip().split("\n")[0]
        print(c(f"  {name}", C.GREEN) + (f"  — {desc}" if desc else ""))


def _parse_int_arg(arg: str) -> int | None:
    try:
        return int(arg)
    except (TypeError, ValueError):
        return None


def handle_slash_command(cmd_line: str, args, session_id: str, system_content: str) -> dict:
    """Proses satu baris slash-command.

    `cmd_line` adalah baris mentah yang DIAWALI '/'. Mengembalikan dict aksi
    yang dipahami loop di main.py:

      {"action": "continue"}    -> tidak ada efek samping, lanjut loop.
      {"action": "skip"}        -> command sudah dieksekusi (cetak), JANGAN
                                   kirim ke model, lanjut loop.
      {"action": "exit"}        -> keluar dari loop interaktif.
      {"action": "new_session"} -> ganti ke sesi baru; dict berisi
                                   session_id & system_content baru.
      {"action": "resume"}      -> ganti ke sesi lama; dict berisi
                                   session_id & system_content baru.
    """
    raw = cmd_line.strip()
    if not raw.startswith("/"):
        return {"action": "continue"}

    parts = raw[1:].split(None, 1)
    name = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if name in ("exit", "quit"):
        return {"action": "exit"}

    if name == "help":
        _print_help()
        return {"action": "skip"}

    if name == "clear":
        _clear_screen()
        return {"action": "skip"}

    if name == "todos":
        _print_todos(session_id)
        return {"action": "skip"}

    if name == "tools":
        _print_tools()
        return {"action": "skip"}

    if name == "approve":
        args.auto_approve = not args.auto_approve
        status = "AKTIF" if args.auto_approve else "nonaktif"
        print(c(f"[approve] auto-approve sekarang {status} "
                f"(lewati konfirmasi aksi destruktif).", C.YELLOW))
        return {"action": "skip"}

    if name == "model":
        if not arg:
            print(c(f"[model] model aktif saat ini: {args.model}", C.DIM))
            print(c("Gunakan: /model <nama> untuk menggantinya.", C.DIM))
            return {"action": "skip"}
        args.model = arg
        print(c(f"[model] model aktif diubah ke: {args.model}", C.GREEN))
        return {"action": "skip"}

    if name == "url":
        if not arg:
            print(c(f"[url] endpoint server model saat ini: {args.url}", C.DIM))
            print(c("Gunakan: /url <http://host:port> untuk menggantinya.", C.DIM))
            return {"action": "skip"}
        # Validasi ringan: endpoint harus berupa URL http(s).
        if not (arg.startswith("http://") or arg.startswith("https://")):
            print(c(
                f"[url] nilai tidak valid: '{arg}'. Harus diawali http:// atau https://.",
                C.RED,
            ))
            return {"action": "skip"}
        args.url = arg.rstrip("/")
        config.save_user_config(url=args.url)
        print(c(f"[url] endpoint server model diubah ke: {args.url}", C.GREEN))
        print(c(f"[url] tersimpan di {config.USER_CONFIG_PATH} (lintas sesi).", C.DIM))
        return {"action": "skip"}

    if name == "api-key":
        if not arg:
            masked = "****" + args.api_key[-4:] if args.api_key else "(kosong)"
            print(c(f"[api-key] API key saat ini: {masked}", C.DIM))
            print(c("Gunakan: /api-key <kunci> untuk menggantinya (kosongkan untuk menghapus).", C.DIM))
            return {"action": "skip"}
        args.api_key = arg
        config.save_user_config(api_key=args.api_key)
        masked = "****" + args.api_key[-4:]
        print(c(f"[api-key] API key server model diubah ke: {masked}", C.GREEN))
        print(c(f"[api-key] tersimpan di {config.USER_CONFIG_PATH} (lintas sesi).", C.DIM))
        return {"action": "skip"}

    if name == "ctx":
        if not arg:
            print(c(f"[ctx] context window saat ini: {args.context_window} token", C.DIM))
            print(c("Gunakan: /ctx <angka> untuk mengubahnya.", C.DIM))
            return {"action": "skip"}
        n = _parse_int_arg(arg)
        if n is None or n <= 0:
            print(c(f"[ctx] nilai tidak valid: '{arg}'. Gunakan angka positif.", C.RED))
            return {"action": "skip"}
        args.context_window = n
        print(c(f"[ctx] context window diubah ke: {args.context_window} token", C.GREEN))
        return {"action": "skip"}

    if name == "github-token":
        if not arg:
            cur = tools_module.state.GITHUB_TOKEN
            masked = "****" + cur[-4:] if cur else "(kosong)"
            print(c(f"[github-token] token GitHub saat ini: {masked}", C.DIM))
            print(c("Gunakan: /github-token <token> untuk menggantinya (kosongkan untuk menghapus).", C.DIM))
            return {"action": "skip"}
        tools_module.state.GITHUB_TOKEN = arg.strip()
        config.save_user_config(github_token=tools_module.state.GITHUB_TOKEN)
        masked = "****" + tools_module.state.GITHUB_TOKEN[-4:]
        print(c(f"[github-token] token GitHub diubah ke: {masked}", C.GREEN))
        print(c(f"[github-token] tersimpan di {config.USER_CONFIG_PATH} (lintas sesi).", C.DIM))
        return {"action": "skip"}

    if name == "github-max":
        if not arg:
            print(c(f"[github-max] batas konten file GitHub saat ini: {tools_module.state._GITHUB_MAX_CONTENT} karakter", C.DIM))
            print(c("Gunakan: /github-max <angka> untuk mengubahnya.", C.DIM))
            return {"action": "skip"}
        n = _parse_int_arg(arg)
        if n is None or n <= 0:
            print(c(f"[github-max] nilai tidak valid: '{arg}'. Gunakan angka positif.", C.RED))
            return {"action": "skip"}
        tools_module.state._GITHUB_MAX_CONTENT = n
        config.save_user_config(github_max=n)
        print(c(f"[github-max] batas konten file GitHub diubah ke: {n} karakter", C.GREEN))
        print(c(f"[github-max] tersimpan di {config.USER_CONFIG_PATH} (lintas sesi).", C.DIM))
        return {"action": "skip"}

    if name == "news-lang":
        if not arg:
            hl, gl, ceid = (tools_module.state.GOOGLE_NEWS_HL,
                            tools_module.state.GOOGLE_NEWS_GL,
                            tools_module.state.GOOGLE_NEWS_CEID)
            print(c(f"[news-lang] bahasa berita saat ini: hl={hl}, gl={gl}, ceid={ceid}", C.DIM))
            print(c("Gunakan: /news-lang <kode> (mis. id, en, de, ja) untuk mengubahnya.", C.DIM))
            return {"action": "skip"}
        lang = arg.strip().lower()
        hl, gl, ceid = config.news_lang_to_params(lang)
        if (hl, gl, ceid) == config.news_lang_to_params("id") and lang != "id":
            print(c(f"[news-lang] kode bahasa tidak dikenal: '{arg}'. Gunakan mis. id, en, de, ja.", C.RED))
            return {"action": "skip"}
        tools_module.state.GOOGLE_NEWS_HL = hl
        tools_module.state.GOOGLE_NEWS_GL = gl
        tools_module.state.GOOGLE_NEWS_CEID = ceid
        config.save_user_config(news_lang=lang)
        print(c(f"[news-lang] bahasa berita diubah ke: {lang} (hl={hl}, gl={gl}, ceid={ceid})", C.GREEN))
        print(c(f"[news-lang] tersimpan di {config.USER_CONFIG_PATH} (lintas sesi).", C.DIM))
        return {"action": "skip"}

    if name == "new":
        new_id = dbmod.create_session(args.db_path, args.workdir,
                                      title=args.session_title)
        print(c(f"[new] sesi baru dimulai: {new_id}", C.GREEN))
        new_system = build_system_prompt(args.workdir, args.skills_dir,
                                         full_tool_schema=args.full_tool_schema_text)
        dbmod.add_message(args.db_path, new_id, "system", new_system, kind="chat")
        return {"action": "new_session", "session_id": new_id, "system_content": new_system}

    if name == "resume":
        if arg:
            session = dbmod.get_session(args.db_path, arg)
            if not session:
                print(c(f"[resume] sesi '{arg}' tidak ditemukan.", C.RED))
                return {"action": "skip"}
            target_id = session["id"]
        else:
            session = dbmod.latest_open_session(args.db_path, args.workdir)
            if not session:
                print(c("[resume] tidak ada sesi terbuka untuk workdir ini.", C.YELLOW))
                return {"action": "skip"}
            target_id = session["id"]

        if target_id == session_id:
            print(c(f"[resume] sudah berada di sesi {target_id}.", C.DIM))
            return {"action": "skip"}
        new_system = build_system_prompt(args.workdir, args.skills_dir,
                                         full_tool_schema=args.full_tool_schema_text)
        print(c(f"[resume] lanjut ke sesi {target_id}.", C.GREEN))
        return {"action": "resume", "session_id": target_id, "system_content": new_system}

    # Command tidak dikenal -> anggap sebagai pesan biasa ke model,
    # supaya user bisa bicara dengan model tentang hal lain tanpa
    # terhalang. (Hanya command yang jelas-jelas slash yang ditangkap.)
    return {"action": "continue"}
