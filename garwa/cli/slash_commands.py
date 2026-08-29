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
from ..mcp import (
    DEFAULT_MCP_CONFIG_PATH,
    MCPServerConfig,
    MCPToolRegistry,
    MCPTransport,
    get_global_registry,
    mcp_available,
    save_mcp_config,
    set_global_registry,
)
from ..tools import TOOLS
from .colors import C
from .colors import c
from .skills import build_system_prompt


# Nama command yang TIDAK boleh dianggap sebagai pesan biasa ke model.
# Kunci = nama command (tanpa '/'), nilai = deskripsi singkat untuk /help.
COMMANDS = {
    "help": "Tampilkan daftar perintah slash ini",
    "clear": "Bersihkan layar terminal (Ctrl+L)",
    "new": "Mulai sesi baru (histori sesi lama tetap tersimpan)",
    "resume": "Lanjutkan sesi: /resume <session_id>, atau /resume untuk sesi terbuka terakhir",
    "api-model": "Ganti model aktif: /api-model <nama> (mis. /api-model deepseek-v4-flash-0731)",
    "api-url": "Ganti endpoint server model: /api-url <http://host:port>",
    "api-key": "Ganti API key server model: /api-key <kunci> (kosongkan untuk menghapus)",
    "ctx": "Ubah context window (token): /ctx <angka>",
    "github-token": "Ganti token GitHub: /github-token <token> (kosongkan untuk menghapus)",
    "github-max": "Batas konten file yang dibaca GitHub (karakter): /github-max <angka>",
    "firecrawl-key": "Ganti API key Firecrawl: /firecrawl-key <token> (kosongkan untuk menghapus)",
    "news-lang": "Bahasa hasil pencarian berita: /news-lang <kode> (mis. id, en, de, ja)",
    "approve": "Toggle auto-approve (lewati konfirmasi aksi destruktif) on/off",
    "pin": "Pin pesan penting agar tidak ikut diringkas: /pin <id> [<id> ...] (lihat /messages)",
    "unpin": "Lepas pin dari pesan: /unpin <id> [<id> ...]",
    "pinned": "Tampilkan daftar pesan yang sedang di-pin",
    "messages": "Tampilkan daftar pesan sesi ini beserta ID-nya (untuk /pin & /unpin)",
    "todos": "Cetak plan/todo list sesi ini ke layar",
    "tools": "Tampilkan daftar tool yang tersedia",
    "mcp-server": "Kelola server MCP: /mcp-server list | add <nama> <cmd> [args...] | remove <nama>",
    "mcp-api-key": "Set API key/header untuk server MCP HTTP: /mcp-api-key <nama> <key>",
    "mcp-enable": "Aktifkan/nonaktifkan server MCP: /mcp-enable <nama> [on|off]",
    "exit": "Selesai & simpan sesi (alias: /quit)",
    "quit": "Selesai & simpan sesi (alias: /exit)",
}

# Command yang butuh argumen tambahan.
_COMMANDS_WITH_ARGS = {"resume", "api-model", "api-url", "api-key", "ctx", "github-token", "github-max", "firecrawl-key", "news-lang", "pin", "unpin"}


def _print_help() -> None:
    print(c("Perintah slash:", C.BOLD))
    width = max(len(name) for name in COMMANDS)
    for name, desc in COMMANDS.items():
        print(c(f"  /{name.ljust(width)}  {desc}", C.DIM))


def _clear_screen() -> None:
    # ANSI clear + home cursor. Bekerja di hampir semua terminal modern.
    print("\x1b[2J\x1b[H", end="")


def _print_todos(db_path: str, session_id: str) -> None:
    todos = dbmod.get_todos(db_path, session_id)
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


def _parse_ids_arg(arg: str) -> list[int]:
    """Parse satu/beberapa message_id dari argumen, dipisah spasi atau koma.

    Contoh: "3", "3,5,8", "3 5 8" → [3, 5, 8]. Elemen non-angka diabaikan.
    """
    ids: list[int] = []
    for token in arg.replace(",", " ").split():
        mid = _parse_int_arg(token)
        if mid is not None:
            ids.append(mid)
    return ids


def _print_mcp_servers() -> None:
    """Cetak daftar server MCP yang terkonfigurasi + status koneksinya."""
    if not mcp_available():
        print(c("[mcp] Modul 'mcp' tidak terinstall. Install: pip install 'mcp>=2.0'", C.YELLOW))
        return
    registry = get_global_registry()
    if registry is None:
        print(c("[mcp] MCP belum aktif (tidak ada server terkonfigurasi).", C.DIM))
        return
    if not registry.configs:
        print(c("[mcp] Tidak ada server MCP terkonfigurasi.", C.DIM))
        return
    print(c("Server MCP:", C.BOLD))
    for cfg in registry.configs:
        state_mark = c("[ON]", C.GREEN) if cfg.enabled else c("[OFF]", C.DIM)
        connected = "terhubung" if cfg.name in registry._connected else "putus"
        tools_n = len(registry._server_tool_names.get(cfg.name, []))
        print(f"  {state_mark} {cfg.name} ({cfg.transport}) — {connected}, {tools_n} tool")
    print(c("Gunakan /mcp-server add <nama> <cmd> [args...] untuk menambah.", C.DIM))


def _rebuild_tools_and_registry() -> None:
    """Sinkronkan TOOLS global & tool_runtime.REGISTRY dari registry MCP.

    Setelah tool MCP ditambah/dihapus on-the-fly, TOOLS harus di-update dan
    `_init_tool_registry()` dipanggil ulang agar REGISTRY ikut dibangun ulang
    (fungsi ini idempoten; aman dipanggil kapan pun).
    """
    from .tool_schema import _init_tool_registry

    registry = get_global_registry()
    # Hapus semua tool ber-prefix mcp.* dari TOOLS, lalu daftarkan ulang dari registry.
    for key in [k for k in TOOLS if k.startswith("mcp.")]:
        TOOLS.pop(key, None)
    if registry is not None:
        TOOLS.update(registry.list_tools())
    _init_tool_registry()


def _require_mcp_registry() -> "MCPToolRegistry | None":
    """Kembalikan registry global, atau cetak pesan & None bila MCP tak aktif."""
    if not mcp_available():
        print(c("[mcp] Modul 'mcp' tidak terinstall. Install: pip install 'mcp>=2.0'", C.YELLOW))
        return None
    registry = get_global_registry()
    if registry is None:
        print(c("[mcp] MCP belum aktif. Tambahkan server dulu via /mcp-server add, "
                "lalu mulai ulang CLI untuk mengaktifkannya.", C.YELLOW))
        return None
    return registry


def _mcp_config_path(args) -> str:
    """Path file konfigurasi MCP (flag --mcp-config atau default)."""
    path = getattr(args, "mcp_config", None)
    return path or DEFAULT_MCP_CONFIG_PATH


def _persist_mcp(registry: "MCPToolRegistry", args) -> None:
    """Tulis konfigurasi MCP saat ini ke disk (lintas sesi)."""
    try:
        path = save_mcp_config(registry.configs, _mcp_config_path(args))
        print(c(f"[mcp] konfigurasi tersimpan di {path} (lintas sesi).", C.DIM))
    except OSError as e:
        print(c(f"[mcp] gagal menyimpan konfigurasi: {e}", C.RED))


def _get_or_create_registry() -> "MCPToolRegistry | None":
    """Kembalikan registry global; buat baru bila belum ada (untuk /mcp-server add)."""
    if not mcp_available():
        print(c("[mcp] Modul 'mcp' tidak terinstall. Install: pip install 'mcp>=2.0'", C.YELLOW))
        return None
    registry = get_global_registry()
    if registry is None:
        registry = MCPToolRegistry([])
        set_global_registry(registry)
    return registry


def _handle_mcp_server(arg: str, args) -> dict:
    """Implementasi /mcp-server list | add <nama> <cmd> [args...] | remove <nama>."""
    if not arg or arg.strip() == "list":
        _print_mcp_servers()
        return {"action": "skip"}

    sub, _, rest = arg.strip().partition(" ")
    sub = sub.lower()
    rest = rest.strip()

    if sub == "list":
        _print_mcp_servers()
        return {"action": "skip"}

    if sub == "remove":
        if not rest:
            print(c("[mcp-server] gunakan: /mcp-server remove <nama>", C.YELLOW))
            return {"action": "skip"}
        registry = _require_mcp_registry()
        if registry is None:
            return {"action": "skip"}
        if not registry.remove_server(rest):
            print(c(f"[mcp-server] server '{rest}' tidak ditemukan.", C.RED))
            return {"action": "skip"}
        _rebuild_tools_and_registry()
        _persist_mcp(registry, args)
        print(c(f"[mcp-server] server '{rest}' dihapus.", C.GREEN))
        return {"action": "skip"}

    if sub == "add":
        if not rest:
            print(c("[mcp-server] gunakan: /mcp-server add <nama> <cmd> [args...]", C.YELLOW))
            return {"action": "skip"}
        name, _, cmd_rest = rest.partition(" ")
        name = name.strip()
        cmd_rest = cmd_rest.strip()
        if not name or not cmd_rest:
            print(c("[mcp-server] gunakan: /mcp-server add <nama> <cmd> [args...]", C.YELLOW))
            return {"action": "skip"}
        # Dukungan transport http: /mcp-server add <nama> http <url>
        transport = MCPTransport.STDIO
        command = None
        cmd_args: list = []
        url = None
        if cmd_rest.startswith("http://") or cmd_rest.startswith("https://"):
            transport = MCPTransport.STREAMABLE_HTTP
            url = cmd_rest
        else:
            pieces = cmd_rest.split()
            command = pieces[0]
            cmd_args = pieces[1:]
        cfg = MCPServerConfig(
            name=name,
            transport=transport,
            command=command,
            args=cmd_args,
            url=url,
            enabled=True,
        )
        registry = _get_or_create_registry()
        if registry is None:
            return {"action": "skip"}
        if not registry.add_server(cfg, connect=True):
            print(c(f"[mcp-server] server '{name}' sudah ada (hapus dulu via /mcp-server remove).", C.RED))
            return {"action": "skip"}
        _rebuild_tools_and_registry()
        _persist_mcp(registry, args)
        print(c(f"[mcp-server] server '{name}' ditambahkan & disambungkan.", C.GREEN))
        return {"action": "skip"}

    print(c(f"[mcp-server] sub-perintah tidak dikenal: '{sub}'. "
            "Gunakan: list | add <nama> <cmd> [args...] | remove <nama>", C.YELLOW))
    return {"action": "skip"}


def _handle_mcp_api_key(arg: str, args) -> dict:
    """Implementasi /mcp-api-key <nama> <key> (set header Authorization untuk HTTP)."""
    if not arg:
        print(c("[mcp-api-key] gunakan: /mcp-api-key <nama> <key>", C.YELLOW))
        return {"action": "skip"}
    name, _, key = arg.strip().partition(" ")
    name = name.strip()
    key = key.strip()
    registry = _require_mcp_registry()
    if registry is None:
        return {"action": "skip"}
    cfg = registry._find_config(name)
    if cfg is None:
        print(c(f"[mcp-api-key] server '{name}' tidak ditemukan.", C.RED))
        return {"action": "skip"}
    if cfg.transport != MCPTransport.STREAMABLE_HTTP:
        print(c(f"[mcp-api-key] server '{name}' bukan HTTP (transport {cfg.transport}); "
                "API key hanya relevan untuk server streamable_http.", C.YELLOW))
        return {"action": "skip"}
    if not key:
        cfg.headers.pop("Authorization", None)
        print(c(f"[mcp-api-key] Authorization server '{name}' dihapus.", C.GREEN))
    else:
        cfg.headers["Authorization"] = f"Bearer {key}"
        _rebuild_tools_and_registry()  # refresh (header dipakai saat connect)
        print(c(f"[mcp-api-key] Authorization server '{name}' di-set (Bearer ****{key[-4:]}).", C.GREEN))
    _persist_mcp(registry, args)
    return {"action": "skip"}


def _handle_mcp_enable(arg: str, args) -> dict:
    """Implementasi /mcp-enable <nama> [on|off] (toggle koneksi server)."""
    if not arg:
        print(c("[mcp-enable] gunakan: /mcp-enable <nama> [on|off]", C.YELLOW))
        return {"action": "skip"}
    name, _, flag = arg.strip().partition(" ")
    name = name.strip()
    flag = flag.strip().lower()
    registry = _require_mcp_registry()
    if registry is None:
        return {"action": "skip"}
    cfg = registry._find_config(name)
    if cfg is None:
        print(c(f"[mcp-enable] server '{name}' tidak ditemukan.", C.RED))
        return {"action": "skip"}
    if flag in ("on", "1", "true", "yes"):
        enabled = True
    elif flag in ("off", "0", "false", "no"):
        enabled = False
    else:
        enabled = not cfg.enabled  # toggle
    ok = registry.set_server_enabled(name, enabled)
    if enabled and not ok:
        print(c(f"[mcp-enable] gagal menyambungkan server '{name}'.", C.RED))
        return {"action": "skip"}
    _rebuild_tools_and_registry()
    _persist_mcp(registry, args)
    state = "diaktifkan" if enabled else "dinonaktifkan"
    print(c(f"[mcp-enable] server '{name}' {state}.", C.GREEN))
    return {"action": "skip"}


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
    if not parts:
        # Input hanya "/" tanpa nama command -> perlakukan sebagai pesan
        # biasa ke model (bukan crash).
        return {"action": "continue"}
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
        _print_todos(args.db_path, session_id)
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

    if name == "api-model":
        if not arg:
            print(c(f"[api-model] model aktif saat ini: {args.model}", C.DIM))
            print(c("Gunakan: /api-model <nama> untuk menggantinya.", C.DIM))
            return {"action": "skip"}
        args.model = arg.strip()
        config.save_user_config(model=args.model)
        print(c(f"[api-model] model aktif diubah ke: {args.model}", C.GREEN))
        print(c(f"[api-model] tersimpan di {config.USER_CONFIG_PATH} (lintas sesi).", C.DIM))
        return {"action": "skip"}

    if name == "api-url":
        if not arg:
            print(c(f"[api-url] endpoint server model saat ini: {args.url}", C.DIM))
            print(c("Gunakan: /api-url <http://host:port> untuk menggantinya.", C.DIM))
            return {"action": "skip"}
        # Validasi ringan: endpoint harus berupa URL http(s).
        if not (arg.startswith("http://") or arg.startswith("https://")):
            print(c(
                f"[api-url] nilai tidak valid: '{arg}'. Harus diawali http:// atau https://.",
                C.RED,
            ))
            return {"action": "skip"}
        args.url = arg.rstrip("/")
        config.save_user_config(url=args.url)
        print(c(f"[api-url] endpoint server model diubah ke: {args.url}", C.GREEN))
        print(c(f"[api-url] tersimpan di {config.USER_CONFIG_PATH} (lintas sesi).", C.DIM))
        return {"action": "skip"}

    if name == "api-key":
        if not arg:
            # Tanpa argumen: hapus API key dari config (sesuai teks help
            # "kosongkan untuk menghapus"), lalu reset nilai aktif ke kosong.
            removed = config.remove_user_config_key("api_key")
            args.api_key = ""
            if removed:
                print(c("[api-key] API key dihapus dari konfigurasi.", C.GREEN))
                print(c(f"[api-key] tersimpan di {config.USER_CONFIG_PATH} (lintas sesi).", C.DIM))
            else:
                print(c("[api-key] tidak ada API key tersimpan untuk dihapus.", C.DIM))
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

    if name == "firecrawl-key":
        if not arg:
            cur = tools_module.state.FIRECRAWL_API_KEY
            masked = "****" + cur[-4:] if cur else "(kosong)"
            print(c(f"[firecrawl-key] API key Firecrawl saat ini: {masked}", C.DIM))
            print(c("Gunakan: /firecrawl-key <token> untuk menggantinya (kosongkan untuk menghapus).", C.DIM))
            return {"action": "skip"}
        tools_module.state.FIRECRAWL_API_KEY = arg.strip()
        config.save_user_config(firecrawl_token=tools_module.state.FIRECRAWL_API_KEY)
        masked = "****" + tools_module.state.FIRECRAWL_API_KEY[-4:]
        print(c(f"[firecrawl-key] API key Firecrawl diubah ke: {masked}", C.GREEN))
        print(c(f"[firecrawl-key] tersimpan di {config.USER_CONFIG_PATH} (lintas sesi).", C.DIM))
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

    if name == "mcp-server":
        return _handle_mcp_server(arg, args)

    if name == "mcp-api-key":
        return _handle_mcp_api_key(arg, args)

    if name == "mcp-enable":
        return _handle_mcp_enable(arg, args)

    if name in ("pin", "unpin"):
        ids = _parse_ids_arg(arg)
        if not ids:
            print(c(f"[{name}] gunakan: /{name} <message_id> [<message_id> ...] "
                    f"(pisahkan dengan spasi/koma; lihat /messages)", C.RED))
            return {"action": "skip"}
        target = name == "pin"
        state = "di-pin" if target else "di-unpin"
        ok, missing = 0, []
        for mid in ids:
            msg = dbmod.get_message(args.db_path, session_id, mid)
            if not msg:
                missing.append(mid)
                continue
            dbmod.set_message_pinned(args.db_path, session_id, mid, pinned=target)
            ok += 1
            print(c(f"[{name}] pesan #{mid} ({msg['role']}) sekarang {state}"
                    + (" -> tidak ikut diringkas." if target else "."), C.GREEN))
        if missing:
            print(c(f"[{name}] tidak ditemukan di sesi ini: "
                    + ", ".join(f"#{m}" for m in missing), C.RED))
        if ok == 0:
            return {"action": "skip"}
        return {"action": "skip"}

    if name == "pinned":
        pinned = dbmod.get_pinned_messages(args.db_path, session_id)
        if not pinned:
            print(c("[pinned] tidak ada pesan yang di-pin. Gunakan /pin <message_id>.", C.DIM))
            return {"action": "skip"}
        print(c(f"[pinned] {len(pinned)} pesan di-pin (dikirim utuh tiap giliran):", C.BOLD))
        for p in pinned:
            preview = p["content"].replace("\n", " ")[:80]
            print(c(f"  #{p['id']} [{p['role']}] {preview}", C.DIM))
        return {"action": "skip"}

    if name == "messages":
        msgs = dbmod.get_all_messages(args.db_path, session_id)
        if not msgs:
            print(c("[messages] belum ada pesan di sesi ini.", C.DIM))
            return {"action": "skip"}
        print(c(f"[messages] {len(msgs)} pesan di sesi ini (pakai ID untuk /pin & /unpin):", C.BOLD))
        for m in msgs:
            preview = m["content"].replace("\n", " ")[:80]
            pin_flag = " [PIN]" if m.get("pinned") else ""
            print(c(f"  #{m['id']} [{m['role']}]{pin_flag} {preview}", C.DIM))
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
