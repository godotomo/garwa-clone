"""tests/test_sub_agent_parallel_e2e.py
Pengujian NYATA (integration) end-to-end sub-agen paralel terhadap server model
sungguhan (bukan mock). Memanggil `tool_spawn_agents_parallel` dengan task nyata
yang memakai tool `local_now` untuk membuktikan sub-agen benar-benar bekerja
paralel di server model sungguhan.

PENTING: test ini memakai server model sungguhan (biaya token) dan membutuhkan
API key. Karena itu DI-SKIP SECARA DEFAULT dan hanya dijalankan saat env
`GARWA_E2E=1` di-set:

    GARWA_E2E=1 python -m pytest tests/test_sub_agent_parallel_e2e.py -v

Menggunakan DB sementara (tmp_path) agar tidak menyentuh DB user asli.
"""
import os

import pytest

from garwa import config
from garwa import db as dbmod
from garwa.tools import _state as tstate
from garwa.tools.sub_agent import tool_spawn_agents_parallel


pytestmark = pytest.mark.skipif(
    os.environ.get("GARWA_E2E") != "1",
    reason="Test end-to-end memakai server model nyata; set GARWA_E2E=1 untuk menjalankan.",
)


def test_parallel_e2e_real_server(db_path):
    """Jalankan beberapa sub-agen paralel terhadap server sungguhan dan
    verifikasi: (1) semua menghasilkan report, (2) sub-session dibuat,
    (3) sesi induk tetap utuh (isolasi ContextVar)."""
    assert config.LLAMA_API_KEY, "Butuh API key untuk pengujian end-to-end."

    tstate.DB_PATH = db_path
    tstate.WORKDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tstate.set_session_id("parent-session")

    tasks = [
        "Berapa tanggal dan jam sekarang? Gunakan tool local_now, lalu jawab singkat.",
        "Berapa hasil 17 * 23? Hitung sendiri lalu jawab singkat.",
        "Sebutkan 3 tool yang tersedia di agent ini berdasarkan daftar tool yang kamu tahu.",
    ]

    result = tool_spawn_agents_parallel(tasks, role="general", max_workers=3)

    # Semua task menghasilkan laporan (header Task #1/#2/#3 hadir).
    assert "Task #1" in result
    assert "Task #2" in result
    assert "Task #3" in result
    assert "[SUB-AGENT-PARALEL] 3 sub-agent selesai." in result

    # Sub-session dibuat untuk semua task.
    rows = dbmod.list_sessions(db_path)
    subs = [r for r in rows if r["id"].startswith("sub_")]
    assert len(subs) == 3, f"Ekspektasi 3 sub-session, dapat {len(subs)}"

    # Isolasi sesi induk terjaga.
    assert tstate.get_session_id() == "parent-session", "Sesi induk berubah!"
