"""cli/plan_mode.py

Plan/Act mode (fitur yang di-port dari Cline).

Plan mode membatasi agent agar HANYA memakai tool read-only (eksplorasi &
analisis) dan TIDAK bisa mengubah file/sistem. Ini memungkinkan user
meminta agent menyusun rencana dulu, meninjau rencananya, lalu beralih ke
act mode (/act) untuk mengeksekusi.

Penerapan berlapis (defense-in-depth), mengikuti catatan riset Cline:
  1. Tool FILTERING di field "tools" payload -- tool yang mengubah file/
     sistem dihilangkan dari payload yang dikirim ke model, jadi model
     bahkan TIDAK melihat tool tersebut tersedia.
  2. Tool BLOCKING di agent_loop -- kalau model tetap memanggil tool yang
     diblokir (mis. karena payload di-cache atau model menyimpang), eksekusi
     ditolak dan pesan error dikembalikan sebagai tool_result.
  3. Instruksi EXPLISIT di system prompt -- model diberi tahu sedang dalam
     plan mode dan tidak boleh mengubah apa pun.
"""

# Tool yang DIBLOKIR di plan mode. Semua tool lain dianggap read-only.
#
# Ini whitelist-reverse: daftar tool yang MENGUBAH file/sistem. Tool yang
# tidak tercantum di sini dianggap aman untuk eksplorasi (read_file, grep,
# list_dir, repo_map, outline_file, web_search, github_search_*, dsb).
#
# Catatan per tool:
#   - bash: berpotensi mengubah file/sistem -> diblokir SELALU di plan mode.
#     (Cline memakai command-guard blacklist untuk mengizinkan bash read-only,
#     tapi di Garwa bash tool tidak membedakan read/write dengan mudah, jadi
#     kita blokir total -- user bisa beralih ke /act untuk menjalankan bash.)
#   - write_file/edit_file: jelas mengubah file.
#   - todo_write: mengubah plan/todo. Di plan mode kita INGIN agent bisa
#     menulis rencana, jadi todo_write TIDAK diblokir (rencana = todo list).
#   - remember: menulis catatan proyek (persisten). Diizinkan di plan mode
#     karena itu bagian dari menyusun rencana/knowledge, bukan mengubah kode.
#   - spawn_agent/spawn_agents_parallel: sub-agent bisa memanggil tool apa
#     pun. Di plan mode kita blokir agar sub-agent tidak bisa mengubah file
#     lewat jalur ini (sub-agent mewarisi mode plan dari induk, lihat
#     agent_loop / tool_runtime).
#   - git_* mutating: git_add/commit/undo/reset/stash(push)/branch(create/
#     delete)/run -- semua mengubah repo. Yang read-only (git_status/diff/
#     log/blame/show/log_graph/stash list) dibiarkan.
#   - send_* / schedule_* / reply_email / text_to_speech: efek samping
#     eksternal (kirim email/telegram, jadwal, TTS). Diblokir di plan mode
#     karena itu aksi, bukan eksplorasi.
#   - security_scan: read-only (audit lokal), diizinkan.
BLOCKED_TOOLS_IN_PLAN_MODE = {
    # File/sistem mutasi
    "bash",
    "write_file",
    "edit_file",
    # Sub-agent (bisa memanggil tool apa pun)
    "spawn_agent",
    "spawn_agents_parallel",
    # Git mutating
    "git_add",
    "git_commit",
    "git_undo",
    "git_reset",
    "git_stash",  # push/pop/drop mengubah; list aman tapi tool ini campur
    "git_branch",  # create/delete mengubah
    "git_run",  # bisa menjalankan perintah git apa pun
    # Efek samping eksternal (aksi, bukan eksplorasi)
    "send_email",
    "reply_email",
    "send_telegram",
    "send_document",
    "text_to_speech",
    "schedule_task",
    "remove_schedule",
    "enable_schedule",
    "disable_schedule",
}


def is_tool_blocked_in_plan_mode(name: str) -> bool:
    """True kalau tool `name` diblokir di plan mode."""
    return name in BLOCKED_TOOLS_IN_PLAN_MODE


def filter_tools_payload(tools_payload: list, mode: str) -> list:
    """Filter field 'tools' OpenAI payload sesuai mode aktif.

    Di plan mode, tool yang mengubah file/sistem dihilangkan dari payload
    sehingga model tidak melihatnya sebagai opsi. Di act mode, payload
    dikembalikan apa adanya.
    """
    if mode != "plan":
        return tools_payload
    return [
        t for t in tools_payload
        if not is_tool_blocked_in_plan_mode(t.get("function", {}).get("name", ""))
    ]


# Instruksi yang disuntikkan ke system prompt saat plan mode aktif.
PLAN_MODE_SYSTEM_PROMPT = """\
## PLAN MODE AKTIF

Anda sedang berada dalam PLAN MODE. Tujuan Anda adalah MENYUSUN RENCANA,
bukan mengeksekusi.

ATURAN WAJIB:
1. Gunakan HANYA tool read-only untuk mengeksplorasi & menganalisis:
   read_file, list_dir, grep, repo_map, outline_file, glob, snippet, check,
   web_search, github_search_*, github_read_file, firecrawl_*, webfetch,
   git_status, git_diff, git_log, git_blame, git_show, git_log_graph,
   local_now, security_scan, todo_read, recall.
2. JANGAN mengubah file, repo, atau sistem. Tool seperti write_file,
   edit_file, bash, git_add/commit, send_*, schedule_* TIDAK tersedia.
3. Susun rencana yang jelas dan konkret menggunakan tool todo_write
   (tulis langkah-langkah sebagai todo list). Rencana harus cukup detail
   untuk dieksekusi nanti di act mode.
4. Akhiri dengan ringkasan rencana Anda dan minta user untuk beralih ke
   act mode (/act) agar rencana dieksekusi.

Setelah user menyetujui rencana dan beralih ke act mode (/act), Anda akan
mengeksekusinya dengan tool lengkap.
"""


def plan_mode_system_prompt(mode: str) -> str:
    """Kembalikan instruksi plan mode untuk disuntikkan ke system prompt,
    atau string kosong kalau mode bukan 'plan'."""
    return PLAN_MODE_SYSTEM_PROMPT if mode == "plan" else ""


def format_plan_blocked_tool_error(name: str) -> str:
    """Tool error yang dikembalikan saat model memanggil tool yang diblokir
    di plan mode (defense-in-depth layer 2)."""
    return (
        f"<tool_result>\n"
        f"[ERROR] Tool `{name}` diblokir di PLAN MODE: tool ini dapat mengubah "
        f"file/repo/sistem, dan perubahan dilarang dalam plan mode.\n"
        f"\n"
        f"ANDA SEDANG DI PLAN MODE -- eksplorasi, analisis, dan susun rencana; "
        f"jangan membuat perubahan. Gunakan tool read-only (read_file, grep, "
        f"list_dir, repo_map, outline_file, web_search, dsb) untuk meneliti "
        f"proyek, dan tulis rencana Anda dengan todo_write.\n"
        f"Kalau perubahan ini bagian dari tugas, masukkan ke rencana Anda "
        f"supaya bisa dieksekusi setelah user beralih ke act mode (/act).\n"
        f"</tool_result>"
    )
