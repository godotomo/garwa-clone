"""tests/test_sub_agent_isolation.py
Test ketahanan (fault isolation) sub-agent paralel & Agent Teams.

Fokus: satu sub-agent/anggota tim yang gagal TIDAK boleh merobohkan yang lain,
dan isolasi stdout per-thread harus benar (tidak ada race pada `sys.stdout`
global). Semua test di sini memakai mock -- tidak memanggil LLM sungguhan.

Yang diuji:
  - `_run_sub_agent_one` tidak pernah melempar, bahkan saat `tool_spawn_agent`
    melempar BaseException (SystemExit/KeyboardInterrupt).
  - `tool_spawn_agents_parallel` tetap melaporkan SEMUA task walau satu task
    melempar BaseException.
  - Isolasi stdout per-thread: log tiap sub-agent hanya berisi output-nya
    sendiri, tidak tercampur dengan thread lain.
  - `_run_team_member_one` tidak pernah melempar saat anggota gagal.
  - `team_run` tetap melaporkan semua anggota walau satu melempar.
"""
import sys
import threading
import time

from garwa.tools import sub_agent as sa
from garwa.tools import team_agent as ta


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _patch_spawn(monkeypatch, fn):
    """Ganti `tool_spawn_agent` di namespace sub_agent (dipakai oleh
    _run_sub_agent_one)."""
    monkeypatch.setattr(sa, "tool_spawn_agent", fn)


# ---------------------------------------------------------------------------
# _run_sub_agent_one: tidak boleh melempar
# ---------------------------------------------------------------------------

def test_run_one_never_raises_on_baseexception(monkeypatch):
    """SystemExit (BaseException, bukan Exception) dari sub-agent harus
    ditangkap dan dikembalikan sebagai hasil GAGAL -- bukan bocor ke pemanggil."""
    def _boom(**kwargs):
        raise SystemExit("keluar paksa")

    _patch_spawn(monkeypatch, _boom)
    res = sa._run_sub_agent_one(0, "task", "general", 5)
    assert res["ok"] is False
    assert "SystemExit" in res["report"]
    assert res["idx"] == 0


def test_run_one_never_raises_on_keyboardinterrupt(monkeypatch):
    def _boom(**kwargs):
        raise KeyboardInterrupt()

    _patch_spawn(monkeypatch, _boom)
    res = sa._run_sub_agent_one(1, "task", "general", 5)
    assert res["ok"] is False
    assert "KeyboardInterrupt" in res["report"]


def test_run_one_success_path(monkeypatch):
    _patch_spawn(monkeypatch, lambda **kwargs: "laporan-ok")
    res = sa._run_sub_agent_one(0, "task", "general", 5)
    assert res["ok"] is True
    assert res["report"] == "laporan-ok"


# ---------------------------------------------------------------------------
# spawn_agents_parallel: batch tidak roboh
# ---------------------------------------------------------------------------

def test_parallel_survives_baseexception_in_one_task(monkeypatch):
    """Satu task melempar SystemExit; task lain tetap dilaporkan."""
    def _fn(task, role="general", max_iters=40):
        if task == "gagal":
            raise SystemExit("boom")
        return f"ok:{task}"

    _patch_spawn(monkeypatch, _fn)
    out = sa.tool_spawn_agents_parallel(
        ["gagal", "baik-1", "baik-2"], role="general", max_workers=3,
    )
    assert "[SUB-AGENT-PARALEL] 3 sub-agent selesai." in out
    assert "ok:baik-1" in out
    assert "ok:baik-2" in out
    assert "SystemExit" in out
    # Task #1 (yang gagal) tetap muncul dengan status GAGAL.
    assert "Task #1 (general) [GAGAL]" in out


def test_parallel_stdout_isolation(monkeypatch):
    """Log stdout tiap sub-agent tidak tercampur: tiap thread hanya melihat
    output-nya sendiri walau menulis bersamaan (uji race pada sys.stdout)."""
    barrier = threading.Barrier(4, timeout=10)

    def _fn(task, role="general", max_iters=40):
        # Semua thread menulis bersamaan setelah barrier -> memaksa interleaving
        # kalau stdout tidak diisolasi per-thread.
        barrier.wait()
        for _ in range(20):
            print(f"LOG-{task}")
            time.sleep(0.001)
        return f"report-{task}"

    _patch_spawn(monkeypatch, _fn)
    out = sa.tool_spawn_agents_parallel(
        ["A", "B", "C", "D"], role="general", max_workers=4,
    )

    # Tiap blok log task harus hanya berisi penanda task itu sendiri.
    for label in ("A", "B", "C", "D"):
        marker = f"--- log stdout task #{ord(label) - 64} ---"
        start = out.find(marker)
        assert start != -1, f"blok log {label} tidak ada"
        nxt = out.find("--- log stdout task #", start + len(marker))
        block = out[start:nxt if nxt != -1 else len(out)]
        for other in ("A", "B", "C", "D"):
            if other == label:
                continue
            assert f"LOG-{other}" not in block, (
                f"log task {label} tercampur output task {other}"
            )


# ---------------------------------------------------------------------------
# team_agent: isolasi anggota
# ---------------------------------------------------------------------------

def test_team_member_never_raises(monkeypatch):
    def _boom(**kwargs):
        raise RuntimeError("anggota mati")

    monkeypatch.setattr(ta, "_run_sub_agent_with_system", _boom)
    res = ta._run_team_member_one(0, "arsitek", "prompt", "task", 5)
    assert res["ok"] is False
    assert "RuntimeError" in res["report"]


def test_team_run_survives_member_baseexception(monkeypatch):
    def _fn(task, system_content, role="general", max_iters=40):
        if role == "rusak":
            raise SystemExit("boom")
        return f"ok:{role}"

    monkeypatch.setattr(ta, "_run_sub_agent_with_system", _fn)
    out = ta.tool_team_run(members=[
        {"agentId": "rusak", "rolePrompt": "p", "task": "t1"},
        {"agentId": "sehat-1", "rolePrompt": "p", "task": "t2"},
        {"agentId": "sehat-2", "rolePrompt": "p", "task": "t3"},
    ])
    assert "[TEAM] 3 anggota tim selesai." in out
    assert "ok:sehat-1" in out
    assert "ok:sehat-2" in out
    assert "SystemExit" in out
    assert "=== Anggota: rusak [GAGAL] ===" in out


def test_stdout_proxy_restores_original(monkeypatch):
    """Setelah capture selesai, stdout proses kembali meneruskan ke stdout
    asli (bukan buffer mati)."""
    _patch_spawn(monkeypatch, lambda **kwargs: "ok")
    sa._run_sub_agent_one(0, "task", "general", 5)
    # stdout saat ini harus proxy yang meneruskan ke real stdout.
    assert isinstance(sys.stdout, sa._ThreadLocalStdout)
    # Tanpa buffer thread-local aktif, write harus diteruskan ke real stdout.
    assert getattr(sa._stdout_local, "buffer", None) is None
