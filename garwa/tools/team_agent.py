"""tools/team_agent.py
Tool `team_run` -- koordinator Agent Teams (port konsep Cline teams).

Garwa sudah punya sub-agent in-process (`spawn_agent` / `spawn_agents_parallel`
di `sub_agent.py`). Koordinator Agent Teams menambahkan lapisan orkestrasi di
atasnya: sekelompok anggota tim, masing-masing dengan ROLE PROMPT custom,
menyelesaikan task-nya sendiri lalu hasilnya digabungkan menjadi satu laporan
terstruktur.

Perbedaan dengan `spawn_agents_parallel`:
  - `spawn_agents_parallel`: semua task memakai role yang SAMA.
  - `team_run`: tiap anggota punya `rolePrompt` (system prompt) sendiri,
    sehingga bisa jadi tim heterogen (mis. satu anggota "arsitek", satu
    "reviewer", satu "implementor") yang bekerja pada task berbeda lalu
    hasilnya dikonvergensikan.

Cara kerja:
  1. Tool `team_run` dipanggil dengan daftar anggota `members`
     [{agentId, rolePrompt, task, max_iters?}] plus opsional `objective`.
  2. Setiap anggota dijalankan sebagai sub-agent in-process di thread sendiri
     (isolasi ContextVar per-thread, sama seperti spawn_agents_parallel).
  3. Laporan tiap anggota dikumpulkan dan digabung menjadi satu string
     terstruktur yang dikembalikan ke agent induk (koordinator), yang bisa
     menyintesis hasil akhir.
"""
import concurrent.futures as cf
import contextvars

from .. import db as dbmod
from . import _state as state
from .sub_agent import _capture_stdout, _run_sub_agent_with_system


def _run_team_member_one(idx: int, agent_id: str, role_prompt: str,
                         task: str, max_iters: int) -> dict:
    """Jalankan SATU anggota tim dalam context terisolasi (thread). Mengembalikan
    dict {idx, agent_id, ok, report, error}. `idx` untuk mengurutkan ulang.

    Fungsi ini TIDAK PERNAH melempar exception: semua kegagalan (termasuk
    BaseException) ditangkap dan dikembalikan sebagai hasil GAGAL, supaya satu
    anggota tim bermasalah tidak merobohkan anggota lain.
    """
    ctx = contextvars.copy_context()
    # Isolasi stdout per-thread (thread-local, bukan tukar sys.stdout global).
    capture = _capture_stdout()

    def _run():
        with capture:
            return _run_sub_agent_with_system(
                task=task, system_content=role_prompt,
                role=agent_id, max_iters=max_iters)

    try:
        result = ctx.run(_run)
    except BaseException as e:  # noqa: BLE001 -- isolasi wajib, jangan bocor
        return {"idx": idx, "agent_id": agent_id, "ok": False,
                "report": f"[ERROR] thread anggota tim gagal: {type(e).__name__}: {e}",
                "log": capture.getvalue()}
    return {"idx": idx, "agent_id": agent_id, "ok": True, "report": result,
            "log": capture.getvalue()}


def tool_team_run(members: list, objective: str = "",
                  max_workers: int = 4) -> str:
    """Jalankan koordinator Agent Teams: beberapa anggota tim (masing-masing
    dengan role prompt custom) menyelesaikan task-nya secara paralel, lalu
    hasil digabung menjadi satu laporan terstruktur.

    Args:
        members: list[dict] -- daftar anggota tim. Tiap dict:
            {agentId (str, wajib), rolePrompt (str, wajib), task (str, wajib),
             max_iters (int, opsional, default 40)}.
        objective: str opsional -- tujuan keseluruhan tim (untuk konteks).
        max_workers: int -- jumlah thread paralel maksimum (default 4).
    """
    if not members or not isinstance(members, list):
        return "[ERROR] Argumen 'members' wajib berupa list non-kosong."

    # Validasi & normalisasi anggota.
    parsed = []
    for i, m in enumerate(members):
        if not isinstance(m, dict):
            return f"[ERROR] Anggota tim #{i + 1} harus berupa objek (dict)."
        agent_id = str(m.get("agentId") or m.get("agent_id") or "").strip()
        task = str(m.get("task") or "").strip()
        role_prompt = str(m.get("rolePrompt") or m.get("role_prompt") or "").strip()
        if not agent_id:
            return f"[ERROR] Anggota tim #{i + 1} wajib punya 'agentId'."
        if not task:
            return f"[ERROR] Anggota tim '{agent_id}' wajib punya 'task'."
        if not role_prompt:
            role_prompt = (
                "Anda adalah anggota tim yang bekerja atas perintah koordinator. "
                f"AgentId Anda: {agent_id}. Selesaikan task yang diberikan secara "
                "mandiri dan teliti, lalu akhiri dengan laporan ringkas."
            )
        try:
            mi = max(1, min(int(m.get("max_iters", 40) or 40), 100))
        except (TypeError, ValueError):
            mi = 40
        parsed.append({"idx": i, "agent_id": agent_id, "task": task,
                       "role_prompt": role_prompt, "max_iters": mi})

    # Jalankan semua anggota secara paralel.
    results = []
    with cf.ThreadPoolExecutor(max_workers=max(1, int(max_workers or 1))) as pool:
        futures = {
            pool.submit(_run_team_member_one, p["idx"], p["agent_id"],
                        p["role_prompt"], p["task"], p["max_iters"]): p
            for p in parsed
        }
        for f in cf.as_completed(futures):
            p = futures[f]
            try:
                results.append(f.result())
            except BaseException as e:  # noqa: BLE001 -- jangan robohkan batch
                # _run_team_member_one seharusnya tidak pernah melempar, tapi
                # kalau ada jalur tak terduga, catat sebagai hasil GAGAL untuk
                # anggota itu saja -- anggota lain tetap dilaporkan.
                results.append({
                    "idx": p["idx"], "agent_id": p["agent_id"], "ok": False,
                    "report": f"[ERROR] anggota tim gagal di level thread pool: "
                              f"{type(e).__name__}: {e}",
                    "log": "",
                })

    # Urutkan ulang sesuai urutan members asli.
    results.sort(key=lambda r: r["idx"])

    header = f"[TEAM] {len(results)} anggota tim selesai."
    if objective:
        header += f"\nObjective: {objective}"
    lines = [header]
    for r in results:
        status = "OK" if r["ok"] else "GAGAL"
        lines.append(f"\n=== Anggota: {r['agent_id']} [{status}] ===")
        lines.append(r["report"])
        if r.get("log"):
            lines.append(f"\n--- log stdout {r['agent_id']} ---")
            lines.append(r["log"].strip())
    return "\n".join(lines)
