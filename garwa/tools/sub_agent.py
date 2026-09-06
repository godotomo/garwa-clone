"""tools/sub_agent.py
Tool `spawn_agent` -- sub-agent in-process (rilis v0.5.0).

Sub-agent diimplementasikan IN-PROCESS (bukan service-based) karena Garwa
adalah agent lokal yang jalan di satu mesin; service/microservices hanya
menambah latensi, kompleksitas deployment, dan overhead komunikasi
antar-proses tanpa manfaat nyata. Lihat catatan `garwa-subagent-research`.

Cara kerja:
  1. Tool `spawn_agent` dipanggil oleh agent induk dengan argumen `task`
     (dan opsional `role`, `max_iters`).
  2. Sub-session baru dibuat via `dbmod.create_sub_session()` (id `sub_<hex>`)
     dengan workdir yang sama dengan sesi induk, sehingga sub-agent punya
     context window SENDIRI dan tidak mencemari riwayat sesi induk.
  3. Pesan user = task ditambahkan ke sub-session.
  4. `run_agent_loop()` dipanggil REKURSIF dengan `AgentConfig` yang disalin
     dari config aktif (state tools), plus system prompt khusus per role.
  5. Final report (teks terlihat terakhir dari assistant) dikembalikan sebagai
     hasil tool ke agent induk, yang bisa memutuskan langkah selanjutnya.

Role bawaan (built-in): `general` (default) dan `explore`. Role menentukan
system prompt khusus yang memberi sub-agent fokus/tujuan berbeda dari induk.
"""
import json
import os

from .. import db as dbmod
from . import _state as state


# ---------------------------------------------------------------------------
# Role definitions (built-in)
# ---------------------------------------------------------------------------
ROLE_PROMPTS = {
    "general": (
        "Anda adalah sub-agent GENERAL yang bekerja atas perintah agent induk. "
        "Fokuslah menyelesaikan task yang diberikan secara mandiri dan teliti. "
        "Gunakan tool yang tersedia (bash, read_file, grep, glob, dll) untuk "
        "investigasi dan pengerjaan. Akhiri dengan laporan ringkas (final "
        "report) berisi: apa yang dikerjakan, hasil/kesimpulan, dan kendala "
        "(kalau ada). Jangan menulis instruksi untuk agent induk; cukup "
        "berikan laporan faktual."
    ),
    "explore": (
        "Anda adalah sub-agent EXPLORE (penjelajah kode). Tugas Anda adalah "
        "MEMAHAMI sebuah area kode/repo secara menyeluruh lalu melaporkan "
        "temuan. Gunakan repo_map, outline_file, read_file, grep, glob untuk "
        "memetakan struktur dan alur. Akhiri dengan laporan terstruktur: "
        "arsitektur/struktur, file & simbol kunci, dependensi, dan hal "
        "penting lain yang relevan dengan task. Jangan mengubah file -- "
        "Anda hanya meneliti dan melaporkan."
    ),
}


def _resolve_role(role: str) -> str:
    """Pilih system prompt untuk role; fallback ke `general` untuk role yang
    tidak dikenal (jangan crash hanya karena nama role salah)."""
    r = (role or "").strip().lower()
    return ROLE_PROMPTS.get(r, ROLE_PROMPTS["general"])


def _make_sub_config() -> "object":
    """Buat `AgentConfig` untuk sub-agent dengan menyalin nilai dari state
    tools aktif (WORKDIR, DB_PATH, dll). Lazy-import `AgentConfig` di dalam
    fungsi supaya modul ini tidak memicu circular import saat tools/__init__
    diimpor di top-level.

    Mengembalikan None kalau komponen cli belum tersedia (mis. saat tools
    dipakai di luar konteks agent loop).
    """
    try:
        from ..cli.agent_config import AgentConfig
    except Exception:
        return None

    # Ambil nilai dari state tools (diset oleh cli/main.py saat startup).
    db_path = getattr(state, "DB_PATH", None) or ""
    workdir = getattr(state, "WORKDIR", None) or os.getcwd()

    cfg = AgentConfig(
        db_path=db_path,
        workdir=workdir,
        auto_approve=True,          # sub-agent jalan tanpa konfirmasi interaktif
        max_tool_iters=40,          # batas aman; bisa ditimpa per-panggilan
        # Server model diisi dari env/config aktif supaya sub-agent memakai
        # model yang sama dengan induk.
        url=os.environ.get("GARWA_MODEL_URL", ""),
        api_key=os.environ.get("GARWA_API_KEY", ""),
        model=os.environ.get("GARWA_MODEL", ""),
        no_stream=True,             # sub-agent tidak perlu streaming ke terminal
    )
    return cfg


def tool_spawn_agent(task: str, role: str = "general", max_iters: int = 40) -> str:
    """Jalankan sub-agent in-process untuk menyelesaikan `task`.

    Membuat sub-session terpisah (context window sendiri), memanggil
    `run_agent_loop` rekursif, dan mengembalikan final report sub-agent
    sebagai hasil tool.
    """
    task = str(task or "").strip()
    if not task:
        return "[ERROR] Argumen 'task' wajib diisi dan tidak boleh kosong."

    db_path = getattr(state, "DB_PATH", None) or ""
    workdir = getattr(state, "WORKDIR", None) or os.getcwd()
    if not db_path:
        return "[ERROR] DB_PATH belum diset; sub-agent tidak bisa membuat sesi."

    # Buat sub-session dengan workdir yang sama dengan induk.
    try:
        sub_sid = dbmod.create_sub_session(db_path, workdir, title=f"sub-agent:{role}")
    except Exception as e:
        return f"[ERROR] Gagal membuat sub-session: {type(e).__name__}: {e}"

    # Tambahkan pesan user = task ke sub-session.
    try:
        dbmod.add_message(db_path, sub_sid, "user", task, kind="chat")
    except Exception as e:
        return f"[ERROR] Gagal menulis task ke sub-session: {type(e).__name__}: {e}"

    # Lazy-import agent_loop / AgentConfig (hindari circular import top-level).
    try:
        from ..cli.agent_config import AgentConfig
        from ..cli.agent_loop import run_agent_loop
    except Exception as e:
        return f"[ERROR] Komponen cli tidak tersedia untuk sub-agent: {type(e).__name__}: {e}"

    cfg = _make_sub_config()
    if cfg is None:
        return "[ERROR] Gagal membuat konfigurasi sub-agent (AgentConfig tidak tersedia)."

    # Timpa max_tool_iters sesuai argumen tool (dibatasi atas).
    try:
        cfg.max_tool_iters = max(1, min(int(max_iters or 0) or 40, 100))
    except (TypeError, ValueError):
        cfg.max_tool_iters = 40

    # System prompt khusus role.
    system_content = _resolve_role(role)

    # Simpan state sesi aktif sub-agent selama loop berjalan, lalu pulihkan.
    prev_session = getattr(state, "SESSION_ID", None)
    try:
        state.SESSION_ID = sub_sid
        final_report = run_agent_loop(cfg, sub_sid, system_content)
    except KeyboardInterrupt:
        final_report = "[INTERRUPTED] Sub-agent dibatalkan (Ctrl+C)."
    except Exception as e:
        final_report = f"[ERROR] Sub-agent gagal: {type(e).__name__}: {e}"
    finally:
        state.SESSION_ID = prev_session

    try:
        dbmod.touch_session(db_path, sub_sid)
    except Exception:
        pass

    return (
        f"[SUB-AGENT:{role}] selesai (session {sub_sid}).\n"
        f"FINAL REPORT:\n{final_report}"
    )
