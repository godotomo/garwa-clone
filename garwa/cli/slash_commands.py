"""cli/slash_commands.py
Perintah-perintah slash (diawali '/') untuk mode interaktif Garwa CLI.

Dibuat terpisah dari main.py supaya daftar command, parsing, dan help
mudah dirawat & diuji. Fungsi utama `handle_slash_command` TIDAK
mengeksekusi aksi yang mengubah alur loop (seperti ganti sesi / keluar)
secara langsung -- ia mengembalikan dict "aksi" yang diinterpretasikan
oleh loop di main.py, sehingga alur kontrol tetap satu tempat.
"""
from .. import config
from .. import context_manager
from .. import db as dbmod
from .. import tools as tools_module
from . import _state as state
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
from ..tools.git_tools import (
    GitError,
    git_add,
    git_blame,
    git_branch,
    git_commit,
    git_commit_all,
    git_diff,
    git_dirty_files,
    git_head_commit,
    git_log,
    git_log_graph,
    git_reset,
    git_show,
    git_stash,
    git_status,
    git_undo,
    _is_repo,
    _require_repo_root,
)
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
    "reserve": "Token cadangan untuk respons (token): /reserve <angka>",
    "summarize-threshold": "Rasio ambang ringkasan (0.0-1.0): /summarize-threshold <rasio>",
    "keep-tail": "Jumlah pesan terakhir yang dipertahankan saat ringkas: /keep-tail <angka>",
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
    "compact": "Ringkas riwayat percakapan sesi ini secara manual (hemat konteks)",
    "cost": "Tampilkan pemakaian token & estimasi biaya sesi ini",
    "status": "Tampilkan status sesi saat ini (model, context, token, workdir, dll)",
    "model": "Ganti model aktif (alias /api-model): /model <nama>",
    "memory": "Kelola catatan proyek (remember): /memory list | show <key> | forget <key>",
    "sessions": "Tampilkan daftar sesi tersimpan untuk workdir ini",
    "summary": "Tampilkan ringkasan percakapan terakhir sesi ini",
    "export": "Ekspor seluruh riwayat percakapan sesi ini ke file Markdown",
    "mcp-server": "Kelola server MCP: /mcp-server list | add <nama> <cmd> [args...] | remove <nama>",
    "mcp-api-key": "Set API key/header untuk server MCP HTTP: /mcp-api-key <nama> <key>",
    "mcp-enable": "Aktifkan/nonaktifkan server MCP: /mcp-enable <nama> [on|off]",
    "exit": "Selesai & simpan sesi (alias: /quit)",
    "quit": "Selesai & simpan sesi (alias: /exit)",
    "git": "Jalankan perintah git arbitrer: /git <perintah> (mis. /git branch, /git show). Perintah berbahaya (force-push, reset --hard, clean -f) ditolak.",
    "git-status": "Tampilkan status repository git (branch, file staged/modified/untracked)",
    "git-diff": "Tampilkan diff perubahan: /git-diff [--staged] [--stat]",
    "git-log": "Tampilkan riwayat commit terakhir: /git-log [n]",
    "git-add": "Stage file ke git: /git-add [path...] (tanpa argumen = stage semua)",
    "git-commit": "Commit perubahan yang sudah di-stage: /git-commit <pesan> (atau /git-commit --all <pesan> untuk stage semua dulu)",
    "git-undo": "Batalkan commit terakhir (soft reset ke HEAD~1)",
    "git-branch": "Kelola branch git: /git-branch [create <nama>|delete <nama>|switch <nama>] (tanpa argumen = list)",
    "git-blame": "Blame sebuah file: /git-blame <path> [line] (siapa menulis tiap baris)",
    "git-show": "Tampilkan isi/perubahan commit: /git-show [ref] [--stat] (default HEAD)",
    "git-reset": "Reset HEAD: /git-reset [soft|mixed] [ref] (default soft HEAD~1; --hard ditolak)",
    "git-stash": "Stash: /git-stash [list|push|pop|drop] [pesan]",
    "git-log-graph": "Log commit dengan grafik branch: /git-log-graph [n]",
    "auto-commit": "Aktifkan/nonaktifkan commit otomatis setelah edit: /auto-commit on|off",
    "undo": "Batalkan giliran terakhir (hapus pesan user + semua balasan model/tool dari DB)",
    "retry": "Ulangi giliran terakhir: kirim ulang pesan user terakhir ke model",
    "search": "Cari pesan lintas sesi (cross-session memory): /search <query>",
    "personality": "Set persona lintas sesi: /personality <deskripsi> (kosongkan untuk hapus)",
    "usage": "Tampilkan pemakaian token lintas sesi (aggregate)",
}

# Command yang butuh argumen tambahan.
_COMMANDS_WITH_ARGS = {"resume", "api-model", "api-url", "api-key", "ctx", "reserve", "summarize-threshold", "keep-tail", "github-token", "github-max", "firecrawl-key", "news-lang", "pin", "unpin", "model", "memory", "git", "git-diff", "git-log", "git-add", "git-commit", "git-branch", "git-blame", "git-show", "git-reset", "git-stash", "git-log-graph"}


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


def _parse_float_arg(arg: str) -> float | None:
    try:
        return float(arg)
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


def _handle_compact(args, session_id: str, system_content: str = "") -> None:
    """Ringkas riwayat percakapan sesi ini SECARA MANUAL.

    Memanggil `maybe_summarize` dengan threshold yang dipaksa (1.0) supaya
    ringkasan selalu terpicu (bukan menunggu threshold otomatis). Ini
    memangkas konteks lama jadi satu summary dan menyimpannya ke DB, sehingga
    giliran berikutnya memakai context yang lebih ringan.
    """
    try:
        summarized = context_manager.maybe_summarize(
            db_path=args.db_path,
            session_id=session_id,
            url=args.url,
            model=getattr(args, "summarize_model", None) or args.model,
            context_window_tokens=args.context_window,
            api_key=args.api_key,
            system_prompt=system_content or "",
            reserve_for_response=getattr(args, "reserve_for_response", None) or 0,
            summarize_threshold_ratio=1.0,   # paksa ringkas
            keep_tail_messages=getattr(args, "keep_tail_messages", None) or 2,
        )
    except Exception as e:  # noqa: BLE001
        print(c(f"[compact] gagal meringkas: {type(e).__name__}: {e}", C.RED))
        return
    if summarized:
        print(c("[compact] konteks berhasil diringkas.", C.GREEN))
    else:
        print(c("[compact] riwayat terlalu pendek untuk diringkas, atau sudah ringkas.", C.DIM))


def _handle_cost(args, session_id: str) -> None:
    """Tampilkan pemakaian token & estimasi biaya sesi ini."""
    usage = state.get_session_state().get("token_usage", {})
    prompt = usage.get("prompt_tokens", 0)
    completion = usage.get("completion_tokens", 0)
    reasoning = usage.get("reasoning_tokens", 0)
    total = usage.get("total", prompt + completion)
    tool_calls = state.get_session_state().get("tool_calls", 0)
    errors = state.get_session_state().get("error_total", 0)

    print(c(f"[cost] Pemakaian token sesi ini ({session_id}):", C.BOLD))
    print(c(f"  prompt     : {prompt:,}", C.DIM))
    print(c(f"  completion : {completion:,}", C.DIM))
    if reasoning:
        print(c(f"  reasoning  : {reasoning:,}", C.DIM))
    print(c(f"  total      : {total:,}", C.BOLD))
    print(c(f"  tool calls : {tool_calls}", C.DIM))
    print(c(f"  error      : {errors}", C.DIM))
    # Estimasi biaya kasar (per 1M token, USD) -- hanya perkiraan.
    # Harga bervariasi per model/provider; ini indikasi kasar.
    est = (prompt * 0.15 + completion * 0.60) / 1_000_000
    print(c(f"  estimasi   : ~${est:.4f} (indikasi kasar, harga bervariasi)", C.YELLOW))


def _handle_personality(args, arg: str) -> None:
    """Set/hapus persona lintas sesi."""
    if not arg:
        config.remove_user_config_key("personality")
        print(c("[personality] persona dihapus (kembali ke default).", C.GREEN))
        return
    config.save_user_config(personality=arg)
    print(c(f"[personality] persona diset: {arg}", C.GREEN))
    print(c("[personality] tersimpan lintas sesi. Berlaku pada sesi baru.", C.DIM))


def _handle_usage(args, session_id: str) -> None:
    """Tampilkan agregasi pemakaian token lintas sesi."""
    agg = dbmod.aggregate_token_usage(args.db_path, workdir=args.workdir)
    print(c("[usage] Pemakaian token lintas sesi (workdir ini):", C.BOLD))
    print(c(f"  total token : {agg['total_tokens']:,}", C.DIM))
    print(c(f"  tool calls  : {agg['tool_calls']}", C.DIM))
    print(c(f"  error       : {agg['errors']}", C.DIM))
    if agg["per_day"]:
        print(c("  per hari    :", C.DIM))
        for day, tokens in list(agg["per_day"].items())[:10]:
            print(c(f"    {day}: {tokens:,}", C.DIM))
    if agg["per_tool"]:
        print(c("  per tool    :", C.DIM))
        for tool, count in list(agg["per_tool"].items())[:10]:
            print(c(f"    {tool}: {count}x", C.DIM))


def _handle_status(args, session_id: str) -> None:
    """Tampilkan status sesi saat ini."""
    usage = state.get_session_state().get("token_usage", {})
    total = usage.get("total", 0)
    tool_calls = state.get_session_state().get("tool_calls", 0)
    errors = state.get_session_state().get("error_total", 0)
    start_time = state.get_session_state().get("start_time")

    print(c(f"[status] Sesi aktif: {session_id}", C.BOLD))
    print(c(f"  model        : {args.model}", C.DIM))
    print(c(f"  endpoint     : {args.url}", C.DIM))
    print(c(f"  workdir      : {getattr(args, 'workdir', '')}", C.DIM))
    print(c(f"  context      : {args.context_window} token", C.DIM))
    print(c(f"  reserve      : {getattr(args, 'reserve_for_response', '')} token", C.DIM))
    print(c(f"  auto-approve : {'AKTIF' if getattr(args, 'auto_approve', False) else 'nonaktif'}", C.DIM))
    print(c(f"  token total  : {total:,}", C.DIM))
    print(c(f"  tool calls   : {tool_calls}", C.DIM))
    print(c(f"  error        : {errors}", C.DIM))
    if start_time:
        import time as _time
        elapsed = _time.time() - start_time
        print(c(f"  durasi sesi  : {elapsed:.0f}s", C.DIM))


def _handle_memory(args, arg: str) -> None:
    """Kelola catatan proyek (remember/recall): list | show <key> | forget <key>."""
    parts = arg.split(None, 1)
    sub = parts[0].lower() if parts else "list"
    key = parts[1].strip() if len(parts) > 1 else ""
    workdir = getattr(args, "workdir", "") or ""

    if sub == "list":
        notes = dbmod.get_notes(args.db_path, workdir)
        if not notes:
            print(c("[memory] belum ada catatan proyek untuk workdir ini.", C.DIM))
            return
        print(c(f"[memory] {len(notes)} catatan proyek:", C.BOLD))
        for n in notes:
            preview = (n.get("value") or "").replace("\n", " ")[:60]
            print(c(f"  {n['key']}  — {preview}", C.DIM))
        return

    if sub == "show":
        if not key:
            print(c("[memory] gunakan: /memory show <key>", C.RED))
            return
        notes = dbmod.get_notes(args.db_path, workdir)
        match = next((n for n in notes if n["key"] == key), None)
        if not match:
            print(c(f"[memory] catatan '{key}' tidak ditemukan.", C.RED))
            return
        print(c(f"[memory] {key}:", C.BOLD))
        print((match.get("value") or ""))
        return

    if sub == "forget":
        if not key:
            print(c("[memory] gunakan: /memory forget <key>", C.RED))
            return
        try:
            dbmod.delete_note(args.db_path, workdir, key)
            print(c(f"[memory] catatan '{key}' dihapus.", C.GREEN))
        except Exception as e:  # noqa: BLE001
            print(c(f"[memory] gagal menghapus '{key}': {type(e).__name__}: {e}", C.RED))
        return

    print(c(f"[memory] sub-perintah tidak dikenal: '{sub}'. Gunakan list | show <key> | forget <key>.", C.RED))


def _handle_sessions(args, session_id: str) -> None:
    """Tampilkan daftar sesi tersimpan untuk workdir ini."""
    workdir = getattr(args, "workdir", "") or ""
    try:
        rows = dbmod.list_sessions(args.db_path, workdir=workdir, limit=20)
    except Exception as e:  # noqa: BLE001
        print(c(f"[sessions] gagal membaca sesi: {type(e).__name__}: {e}", C.RED))
        return
    if not rows:
        print(c("[sessions] belum ada sesi tersimpan untuk workdir ini.", C.DIM))
        return
    print(c(f"[sessions] {len(rows)} sesi tersimpan:", C.BOLD))
    for r in rows:
        mark = "*" if r["id"] == session_id else " "
        title = (r.get("title") or "")[:40]
        status = r.get("status", "?")
        print(c(f"  {mark} {r['id']}  [{status}]  {title}", C.DIM))
    print(c("  (* = sesi aktif)", C.DIM))


def _handle_summary(args, session_id: str) -> None:
    """Tampilkan ringkasan percakapan terakhir sesi ini."""
    try:
        summary = dbmod.get_latest_summary(args.db_path, session_id)
    except Exception as e:  # noqa: BLE001
        print(c(f"[summary] gagal membaca ringkasan: {type(e).__name__}: {e}", C.RED))
        return
    if not summary:
        print(c("[summary] belum ada ringkasan untuk sesi ini.", C.DIM))
        return
    print(c(f"[summary] ringkasan s.d. pesan #{summary.get('upto_message_id')}:", C.BOLD))
    print(summary.get("summary_text", ""))


def _handle_export(args, session_id: str) -> None:
    """Ekspor seluruh riwayat percakapan sesi ini ke file Markdown."""
    import datetime
    import os

    try:
        messages = dbmod.get_all_messages(args.db_path, session_id)
    except Exception as e:  # noqa: BLE001
        print(c(f"[export] gagal membaca pesan: {type(e).__name__}: {e}", C.RED))
        return
    if not messages:
        print(c("[export] tidak ada pesan untuk diekspor.", C.DIM))
        return

    workdir = getattr(args, "workdir", "") or os.getcwd()
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"garwa_export_{session_id}_{ts}.md"
    path = os.path.join(workdir, fname)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# Garwa — ekspor sesi {session_id}\n\n")
            f.write(f"- workdir: `{workdir}`\n")
            f.write(f"- waktu: {datetime.datetime.now().isoformat()}\n\n")
            f.write("---\n\n")
            for m in messages:
                role = m.get("role", "?")
                content = (m.get("content") or "").strip()
                kind = m.get("kind", "chat")
                label = f"**{role}**"
                if kind not in ("chat", "user", "assistant"):
                    label += f" `({kind})`"
                f.write(f"{label}\n\n{content}\n\n---\n\n")
    except Exception as e:  # noqa: BLE001
        print(c(f"[export] gagal menulis file: {type(e).__name__}: {e}", C.RED))
        return
    print(c(f"[export] {len(messages)} pesan diekspor ke: {path}", C.GREEN))


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
    """Kembalikan registry global, atau cetak pesan & None bila belum ada.

    Operasi konfigurasi (add/remove/api-key/enable off) hanya memanipulasi
    file konfigurasi JSON dan TIDAK memerlukan SDK MCP terinstall. Jadi di
    sini tidak lagi menolak saat `mcp` belum terinstall; koneksi nyata tetap
    mengecek SDK di dalam MCPToolRegistry.connect_all/connect_server.
    """
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
    """Kembalikan registry global; buat baru bila belum ada (untuk /mcp-server add).

    Tidak menolak saat SDK `mcp` belum terinstall: penambahan server hanya
    memanipulasi konfigurasi (file JSON), dan koneksi nyata tetap best-effort
    (dicek SDK-nya di dalam MCPToolRegistry). Jadi user bisa mengonfigurasi
    server lebih dulu, lalu install SDK dan sambungkan via /mcp-enable on.
    """
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


# ---------------------------------------------------------------------------
# Slash commands git
# ---------------------------------------------------------------------------

GIT_COMMIT_SYSTEM = (
    "Kamu adalah asisten yang menulis pesan commit git yang ringkas dan jelas. "
    "Analisis diff berikut dan tulis SATU pesan commit (subject baris tunggal, "
    "imperatif, maksimal ~72 karakter). Jangan tambahkan penjelasan lain, "
    "jangan pakai markdown, jangan kutip. Fokus pada 'apa' yang berubah dan "
    "'kenapa' secara singkat."
)


def _generate_commit_message(diff_text: str, args) -> str:
    """Hasilkan pesan commit dari diff via LLM nonstream (best-effort).

    Kalau LLM gagal / tidak tersedia, fallback ke pesan generik dari daftar
    file yang berubah. Mengembalikan string pesan commit (tanpa trailing).
    """
    diff_text = (diff_text or "").strip()
    if not diff_text:
        return "update"

    url = getattr(args, "url", None) or config.LLAMA_URL
    model = getattr(args, "model", None) or config.LLAMA_MODEL
    api_key = getattr(args, "api_key", None) or config.LLAMA_API_KEY

    # Batasi diff agar tidak overflow context (potong ke tail).
    max_chars = 12000
    if len(diff_text) > max_chars:
        diff_text = diff_text[-max_chars:]

    try:
        import requests
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": GIT_COMMIT_SYSTEM},
                {"role": "user", "content": diff_text},
            ],
            "temperature": 0.2,
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        msg = (content or "").strip().splitlines()[0].strip()
        if msg:
            return msg[:200]
    except Exception:  # noqa: BLE001 - best-effort, jangan crash
        pass

    # Fallback: daftar file yang berubah.
    files = git_dirty_files()
    if files:
        return "update: " + ", ".join(files[:5])
    return "update"


def _handle_git_status(args, arg: str) -> None:
    try:
        print(git_status())
    except GitError as e:
        print(c(f"[git-status] {e}", C.RED))


def _handle_git_diff(args, arg: str) -> None:
    staged = "--staged" in arg or "--cached" in arg
    stat = "--stat" in arg
    try:
        print(git_diff(staged=staged, stat=stat))
    except GitError as e:
        print(c(f"[git-diff] {e}", C.RED))


def _handle_git_log(args, arg: str) -> None:
    n = 15
    for tok in arg.split():
        if tok.isdigit():
            n = int(tok)
            break
    try:
        print(git_log(n=n))
    except GitError as e:
        print(c(f"[git-log] {e}", C.RED))


def _handle_git_add(args, arg: str) -> None:
    paths = [p for p in arg.split() if p.strip()]
    try:
        git_add(paths or None)
        print(c("[git-add] file di-stage.", C.GREEN))
    except GitError as e:
        print(c(f"[git-add] {e}", C.RED))


def _handle_git_commit(args, arg: str) -> None:
    # Dukungan /git-commit (pesan manual) dan /git-commit (AI) dan
    # /git-commit --all <pesan>.
    if not _is_repo():
        print(c("[git-commit] bukan repository git.", C.RED))
        return

    message = arg.strip()
    if message.startswith("--all"):
        message = message[len("--all"):].strip()

    # Cek apakah ada perubahan yang belum di-stage.
    dirty = git_dirty_files()
    if not dirty:
        print(c("[git-commit] tidak ada perubahan untuk di-commit.", C.DIM))
        return

    # Kalau tidak ada pesan -> generate AI dari diff working tree.
    if not message:
        diff_text = git_diff()
        message = _generate_commit_message(diff_text, args)
        print(c(f"[git-commit] pesan AI: {message}", C.DIM))

    # Selalu stage semua lalu commit (perilaku /commit aider).
    try:
        result = git_commit_all(message)
        print(c(f"[git-commit] {result}", C.GREEN))
    except GitError as e:
        print(c(f"[git-commit] {e}", C.RED))


def _handle_git_undo(args, arg: str) -> None:
    try:
        print(c(f"[git-undo] {git_undo()}", C.GREEN))
    except GitError as e:
        print(c(f"[git-undo] {e}", C.RED))


def _handle_git_branch(args, arg: str) -> None:
    create = delete = switch = ""
    toks = arg.split()
    if toks:
        op = toks[0].lower()
        name = toks[1] if len(toks) > 1 else ""
        if op in ("create", "-c", "new"):
            create = name
        elif op in ("delete", "-d", "del", "rm"):
            delete = name
        elif op in ("switch", "checkout", "co", "-s"):
            switch = name
        elif op in ("list", "ls", "-l"):
            pass  # list default
        else:
            # Perilaku /git-branch <nama> -> buat branch baru (mirip git branch <nama>)
            create = op
    try:
        print(c(f"[git-branch] {git_branch(create=create, delete=delete, switch=switch)}", C.GREEN))
    except GitError as e:
        print(c(f"[git-branch] {e}", C.RED))


def _handle_git_blame(args, arg: str) -> None:
    toks = arg.split()
    if not toks:
        print(c("[git-blame] gunakan: /git-blame <path> [line]", C.YELLOW))
        return
    path = toks[0]
    line = 0
    if len(toks) > 1 and toks[1].isdigit():
        line = int(toks[1])
    try:
        print(git_blame(path, line=line or None))
    except GitError as e:
        print(c(f"[git-blame] {e}", C.RED))


def _handle_git_show(args, arg: str) -> None:
    stat = "--stat" in arg
    ref = "HEAD"
    for tok in arg.split():
        if tok != "--stat":
            ref = tok
            break
    try:
        print(git_show(ref, stat=stat))
    except GitError as e:
        print(c(f"[git-show] {e}", C.RED))


def _handle_git_reset(args, arg: str) -> None:
    toks = arg.split()
    mode = "soft"
    ref = "HEAD~1"
    for tok in toks:
        if tok in ("soft", "mixed"):
            mode = tok
        elif tok.startswith("HEAD") or tok.startswith("~") or tok.isdigit() or ".." in tok:
            ref = tok
    if "--hard" in toks:
        print(c("[git-reset] --hard ditolak demi keamanan. Gunakan 'soft' atau 'mixed'.", C.RED))
        return
    try:
        print(c(f"[git-reset] {git_reset(mode, ref)}", C.GREEN))
    except GitError as e:
        print(c(f"[git-reset] {e}", C.RED))


def _handle_git_stash(args, arg: str) -> None:
    toks = arg.split()
    action = "list"
    message = ""
    if toks:
        action = toks[0].lower()
        message = " ".join(toks[1:])
    try:
        print(c(f"[git-stash] {git_stash(action=action, message=message)}", C.GREEN))
    except GitError as e:
        print(c(f"[git-stash] {e}", C.RED))


def _handle_git_log_graph(args, arg: str) -> None:
    n = 20
    for tok in arg.split():
        if tok.isdigit():
            n = int(tok)
            break
    try:
        print(git_log_graph(n=n))
    except GitError as e:
        print(c(f"[git-log-graph] {e}", C.RED))


def _handle_git(args, arg: str) -> None:
    from ..tools.git_tools import tool_git_run
    print(tool_git_run(arg))


def _handle_auto_commit(args, arg: str) -> None:
    flag = arg.strip().lower()
    if flag in ("on", "1", "true", "yes"):
        enabled = True
    elif flag in ("off", "0", "false", "no"):
        enabled = False
    else:
        print(c("[auto-commit] gunakan: /auto-commit on|off", C.YELLOW))
        return
    config.save_user_config(auto_commit=enabled)
    config._reload_values()
    status = "AKTIF" if enabled else "nonaktif"
    print(c(f"[auto-commit] commit otomatis setelah edit sekarang {status}.", C.GREEN))
    if enabled:
        print(c("[auto-commit] setiap edit yang sukses akan di-commit otomatis dengan pesan AI.", C.DIM))


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
        config.save_user_config(context_window=n)
        print(c(f"[ctx] context window diubah ke: {args.context_window} token", C.GREEN))
        print(c(f"[ctx] tersimpan di {config.USER_CONFIG_PATH} (lintas sesi).", C.DIM))
        return {"action": "skip"}

    if name == "reserve":
        if not arg:
            print(c(f"[reserve] token cadangan untuk respons saat ini: {args.reserve_for_response} token", C.DIM))
            print(c("Gunakan: /reserve <angka> untuk mengubahnya.", C.DIM))
            return {"action": "skip"}
        n = _parse_int_arg(arg)
        if n is None or n <= 0:
            print(c(f"[reserve] nilai tidak valid: '{arg}'. Gunakan angka positif.", C.RED))
            return {"action": "skip"}
        args.reserve_for_response = n
        config.save_user_config(reserve_for_response=n)
        print(c(f"[reserve] token cadangan respons diubah ke: {n} token", C.GREEN))
        print(c(f"[reserve] tersimpan di {config.USER_CONFIG_PATH} (lintas sesi).", C.DIM))
        return {"action": "skip"}

    if name == "summarize-threshold":
        if not arg:
            print(c(f"[summarize-threshold] rasio ambang ringkasan saat ini: {args.summarize_threshold_ratio}", C.DIM))
            print(c("Gunakan: /summarize-threshold <0.0-1.0> untuk mengubahnya.", C.DIM))
            return {"action": "skip"}
        v = _parse_float_arg(arg)
        if v is None or not (0.0 < v <= 1.0):
            print(c(f"[summarize-threshold] nilai tidak valid: '{arg}'. Gunakan angka 0.0-1.0.", C.RED))
            return {"action": "skip"}
        args.summarize_threshold_ratio = v
        config.save_user_config(summarize_threshold_ratio=v)
        print(c(f"[summarize-threshold] rasio ambang ringkasan diubah ke: {v}", C.GREEN))
        print(c(f"[summarize-threshold] tersimpan di {config.USER_CONFIG_PATH} (lintas sesi).", C.DIM))
        return {"action": "skip"}

    if name == "keep-tail":
        if not arg:
            print(c(f"[keep-tail] jumlah pesan terakhir yang dipertahankan saat ini: {args.keep_tail_messages}", C.DIM))
            print(c("Gunakan: /keep-tail <angka> untuk mengubahnya.", C.DIM))
            return {"action": "skip"}
        n = _parse_int_arg(arg)
        if n is None or n < 0:
            print(c(f"[keep-tail] nilai tidak valid: '{arg}'. Gunakan angka >= 0.", C.RED))
            return {"action": "skip"}
        args.keep_tail_messages = n
        config.save_user_config(keep_tail_messages=n)
        print(c(f"[keep-tail] jumlah pesan ekor diubah ke: {n}", C.GREEN))
        print(c(f"[keep-tail] tersimpan di {config.USER_CONFIG_PATH} (lintas sesi).", C.DIM))
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

    if name == "model":
        # Alias /api-model: konsisten dengan ekosistem (Claude Code memakai /model).
        if not arg:
            print(c(f"[model] model aktif saat ini: {args.model}", C.DIM))
            print(c("Gunakan: /model <nama> untuk menggantinya (alias /api-model).", C.DIM))
            return {"action": "skip"}
        args.model = arg.strip()
        config.save_user_config(model=args.model)
        print(c(f"[model] model aktif diubah ke: {args.model}", C.GREEN))
        print(c(f"[model] tersimpan di {config.USER_CONFIG_PATH} (lintas sesi).", C.DIM))
        return {"action": "skip"}

    if name == "compact":
        _handle_compact(args, session_id, system_content)
        return {"action": "skip"}

    if name == "cost":
        _handle_cost(args, session_id)
        return {"action": "skip"}

    if name == "status":
        _handle_status(args, session_id)
        return {"action": "skip"}

    if name == "memory":
        _handle_memory(args, arg)
        return {"action": "skip"}

    if name == "sessions":
        _handle_sessions(args, session_id)
        return {"action": "skip"}

    if name == "summary":
        _handle_summary(args, session_id)
        return {"action": "skip"}

    if name == "export":
        _handle_export(args, session_id)
        return {"action": "skip"}

    if name == "git-status":
        _handle_git_status(args, arg)
        return {"action": "skip"}

    if name == "git-diff":
        _handle_git_diff(args, arg)
        return {"action": "skip"}

    if name == "git-log":
        _handle_git_log(args, arg)
        return {"action": "skip"}

    if name == "git-add":
        _handle_git_add(args, arg)
        return {"action": "skip"}

    if name == "git-commit":
        _handle_git_commit(args, arg)
        return {"action": "skip"}

    if name == "git-undo":
        _handle_git_undo(args, arg)
        return {"action": "skip"}

    if name == "git-branch":
        _handle_git_branch(args, arg)
        return {"action": "skip"}

    if name == "git-blame":
        _handle_git_blame(args, arg)
        return {"action": "skip"}

    if name == "git-show":
        _handle_git_show(args, arg)
        return {"action": "skip"}

    if name == "git-reset":
        _handle_git_reset(args, arg)
        return {"action": "skip"}

    if name == "git-stash":
        _handle_git_stash(args, arg)
        return {"action": "skip"}

    if name == "git-log-graph":
        _handle_git_log_graph(args, arg)
        return {"action": "skip"}

    if name == "git":
        _handle_git(args, arg)
        return {"action": "skip"}

    if name == "auto-commit":
        _handle_auto_commit(args, arg)
        return {"action": "skip"}

    if name == "undo":
        span = dbmod.get_last_turn_span(args.db_path, session_id)
        if not span:
            print(c("[undo] tidak ada giliran user untuk dibatalkan.", C.YELLOW))
            return {"action": "skip"}
        deleted = dbmod.delete_messages_after(args.db_path, session_id, span["start_id"])
        if deleted:
            print(c(f"[undo] giliran terakhir dibatalkan ({deleted} pesan dihapus).", C.GREEN))
        else:
            print(c("[undo] giliran terakhir dibatalkan.", C.GREEN))
        dbmod.touch_session(args.db_path, session_id)
        return {"action": "skip"}

    if name == "retry":
        span = dbmod.get_last_turn_span(args.db_path, session_id)
        if not span:
            print(c("[retry] tidak ada giliran user untuk diulang.", C.YELLOW))
            return {"action": "skip"}
        # Hapus balasan giliran terakhir (assistant/tool) tapi PERTAHANKAN
        # pesan user-nya, supaya main.py bisa mengirim ulang ke model.
        deleted = dbmod.delete_messages_after(args.db_path, session_id, span["start_id"])
        print(c(f"[retry] mengulang giliran terakhir ({deleted} pesan balasan dihapus).", C.GREEN))
        return {"action": "retry", "session_id": session_id}

    if name == "search":
        if not arg:
            print(c("Gunakan: /search <query> untuk mencari pesan lintas sesi.", C.DIM))
            return {"action": "skip"}
        results = dbmod.search_messages(args.db_path, arg, workdir=args.workdir, limit=15)
        if not results:
            print(c(f"[search] tidak ada hasil untuk '{arg}'.", C.YELLOW))
            return {"action": "skip"}
        print(c(f"[search] {len(results)} hasil untuk '{arg}':", C.BOLD))
        for i, r in enumerate(results, 1):
            snippet = r["content"].replace("\n", " ")[:120]
            sid = r["session_id"][:8]
            print(c(f"  {i}. [{sid}] {snippet}", C.DIM))
        return {"action": "skip"}

    if name == "personality":
        _handle_personality(args, arg)
        return {"action": "skip"}

    if name == "usage":
        _handle_usage(args, session_id)
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
