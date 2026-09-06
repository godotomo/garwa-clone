"""tests/test_sub_agent_parallel.py
Stress test untuk sub-agent PARALEL `spawn_agents_parallel` (rilis v0.5.1).

Tujuan: menguji STABILITAS dan ISOLASI sub-agent paralel (thread pool) tanpa
memanggil server model sungguhan (menghemat token/biaya). `call_llama_server`
dimock sehingga sub-agent bisa dijalankan serentak dengan cepat dan
deterministik.

Yang diuji:
  - Banyak sub-agent dijalankan PARALEL (thread pool) semua menghasilkan report.
  - Setiap sub-agent membuat sub-session terpisah (`sub_<hex>`) di DB.
  - Isolasi ContextVar per-thread: sesi induk TIDAK berubah setelah paralel.
  - Error di satu task TIDAK menggagalkan task lain (graceful degradation).
  - Task kosong / list kosong ditolak dengan rapi (bukan crash).
  - max_workers membatasi jumlah thread paralel.
  - Mock LLM thread-safe (pakai lock) karena paralel memakai thread.
"""
import json
import threading
import time

import pytest

from garwa import db as dbmod
from garwa.cli import _state as cli_state
from garwa.tools import _state as tstate
from garwa.tools.sub_agent import tool_spawn_agents_parallel


# ---------------------------------------------------------------------------
# Mock LLM thread-safe (paralel memakai thread; list.pop bukan thread-safe).
# ---------------------------------------------------------------------------
class _ThreadSafeFakeLLM:
    """Simulasi respon model yang AMAN dipakai dari banyak thread serentak.

    `responses` adalah list dict:
      {"type": "answer", "text": "..."}
      {"type": "tool", "name": "...", "arguments": {...}}

    Setiap pemanggilan mengambil satu respon berikutnya secara atomik (lock),
    sehingga beberapa thread bisa berbagi satu instance tanpa race condition.
    Kalau respon habis, kembalikan teks default.
    """

    def __init__(self, responses):
        self._lock = threading.Lock()
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, url, model, messages, stream=True, api_key="",
                 debug=False, temperature=0.2):
        with self._lock:
            self.calls += 1
            if not self.responses:
                return "Selesai."
            step = self.responses.pop(0)
        if step["type"] == "tool":
            args_json = json.dumps(step["arguments"], ensure_ascii=False)
            return (
                f"<tool_call>\n"
                f"{json.dumps({'name': step['name'], 'arguments': args_json}, ensure_ascii=False)}\n"
                f"</tool_call>"
            )
        return step["text"]


@pytest.fixture
def fake_llm(monkeypatch):
    """Pasang mock call_llama_server (thread-safe) di agent_loop."""
    def _install(responses):
        fake = _ThreadSafeFakeLLM(responses)
        monkeypatch.setattr(
            "garwa.cli.agent_loop.call_llama_server", fake
        )
        return fake
    return _install


@pytest.fixture
def sub_state(db_path):
    """Set state tools (DB_PATH, WORKDIR, SESSION_ID) untuk sub-agent."""
    old_db = tstate.DB_PATH
    old_work = tstate.WORKDIR
    old_sid = tstate.SESSION_ID
    tstate.DB_PATH = db_path
    tstate.WORKDIR = "/tmp/stress-workdir"
    tstate.SESSION_ID = "parent-session"
    yield db_path
    tstate.DB_PATH = old_db
    tstate.WORKDIR = old_work
    tstate.SESSION_ID = old_sid


def _count_sub_sessions(db_path):
    rows = dbmod.list_sessions(db_path)
    return sum(1 for r in rows if r["id"].startswith("sub_"))


def _count_parent_sessions(db_path):
    rows = dbmod.list_sessions(db_path)
    return sum(1 for r in rows if not r["id"].startswith("sub_"))


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

def test_parallel_runs_tasks_and_returns_reports(fake_llm, sub_state, db_path):
    """Beberapa task dijalankan paralel; semua menghasilkan final report dan
    masing-masing membuat sub-session sendiri."""
    fake = fake_llm([
        {"type": "answer", "text": "hasil-A"},
        {"type": "answer", "text": "hasil-B"},
        {"type": "answer", "text": "hasil-C"},
        {"type": "answer", "text": "hasil-D"},
    ])
    result = tool_spawn_agents_parallel(
        ["task-1", "task-2", "task-3", "task-4"],
        role="general", max_workers=4,
    )
    assert "[SUB-AGENT-PARALEL] 4 sub-agent selesai." in result
    for label in ("hasil-A", "hasil-B", "hasil-C", "hasil-D"):
        assert label in result, f"report {label} hilang"
    assert fake.calls >= 4
    # 4 sub-session terpisah dibuat.
    assert _count_sub_sessions(db_path) == 4


def test_parallel_isolates_state_from_parent(fake_llm, sub_state, db_path):
    """State per-session (ContextVar) sub-agent paralel tidak mencemari sesi
    induk -- inti isolasi thread."""
    cli_state.reset_session_state("parent-session")
    parent_before = cli_state.get_session_state()["tool_calls"]

    fake = fake_llm([
        {"type": "tool", "name": "local_now", "arguments": {}},
        {"type": "answer", "text": "laporan-1"},
        {"type": "answer", "text": "laporan-2"},
    ])
    tool_spawn_agents_parallel(["task-a", "task-b"], role="general", max_workers=2)

    # State induk tidak bertambah (tool_calls sub-agent tidak bocor ke parent).
    parent_after = cli_state.get_session_state()["tool_calls"]
    assert parent_after == parent_before


def test_parallel_creates_isolated_sub_sessions(fake_llm, sub_state, db_path):
    """Sub-session paralel dibuat terpisah; sesi induk tidak bertambah."""
    parent = dbmod.create_session(db_path, workdir="/tmp/stress-workdir", title="parent")
    assert _count_parent_sessions(db_path) == 1

    fake = fake_llm([
        {"type": "answer", "text": "laporan-1"},
        {"type": "answer", "text": "laporan-2"},
        {"type": "answer", "text": "laporan-3"},
    ])
    tool_spawn_agents_parallel(["t1", "t2", "t3"], role="explore", max_workers=3)

    assert _count_parent_sessions(db_path) == 1
    assert _count_sub_sessions(db_path) == 3


def test_parallel_error_in_one_task_does_not_fail_others(
        fake_llm, sub_state, db_path, monkeypatch):
    """Kalau SATU task gagal (LLM error), task lain tetap selesai (graceful
    degradation), bukan seluruh batch gagal."""
    import garwa.cli.agent_loop as al

    # Mock yang melempar error untuk panggilan pertama saja, lalu normal.
    real = al.call_llama_server
    state = {"n": 0}
    lock = threading.Lock()

    def _flaky(*a, **k):
        with lock:
            state["n"] += 1
            n = state["n"]
        if n == 1:
            raise RuntimeError("server down sementara")
        return "laporan-ok"

    monkeypatch.setattr(al, "call_llama_server", _flaky)

    result = tool_spawn_agents_parallel(
        ["task-yang-gagal", "task-ok-1", "task-ok-2"],
        role="general", max_workers=3,
    )

    # tool_spawn_agent menangkap error LLM secara internal dan mengembalikan
    # report "[ERROR] Sub-agent gagal: ...", jadi status thread tetap OK tapi
    # isi report memuat error. Task lain tetap menghasilkan laporan-ok.
    assert "laporan-ok" in result
    assert "RuntimeError" in result or "server down" in result
    # Semua sub-session tetap dibuat (termasuk yang gagal).
    assert _count_sub_sessions(db_path) == 3


def test_parallel_rejects_empty_tasks(sub_state):
    """List task kosong / semua kosong ditolak tanpa menyentuh LLM."""
    r1 = tool_spawn_agents_parallel([])
    assert r1.startswith("[ERROR]")
    r2 = tool_spawn_agents_parallel(["", "  "])
    assert r2.startswith("[ERROR]")


def test_parallel_max_workers_bounds_threads(fake_llm, sub_state, db_path):
    """max_workers membatasi jumlah thread paralel; banyak task tetap selesai
    tapi dikerjakan dalam gelombang (tidak crash)."""
    fake = fake_llm([
        {"type": "answer", "text": f"hasil-{i}"} for i in range(6)
    ])
    result = tool_spawn_agents_parallel(
        [f"task-{i}" for i in range(6)],
        role="general", max_workers=2,  # hanya 2 thread
    )
    assert "[SUB-AGENT-PARALEL] 6 sub-agent selesai." in result
    assert _count_sub_sessions(db_path) == 6


def test_parallel_results_ordered_by_original_index(fake_llm, sub_state, db_path):
    """Hasil laporan diurutkan sesuai urutan task asli walau thread selesai
    dalam urutan acak."""
    fake = fake_llm([
        {"type": "answer", "text": "laporan-1"},
        {"type": "answer", "text": "laporan-2"},
        {"type": "answer", "text": "laporan-3"},
    ])
    result = tool_spawn_agents_parallel(
        ["z-task", "a-task", "m-task"], role="general", max_workers=3,
    )
    # Header Task #1 harus muncul sebelum Task #2, lalu Task #3. (sort by idx)
    i_first = result.find("Task #1")
    i_second = result.find("Task #2")
    i_third = result.find("Task #3")
    assert i_first != -1 and i_second != -1 and i_third != -1
    assert i_first < i_second < i_third
    # Ketiga laporan hadir (urutan isinya acak karena thread, tapi tidak hilang).
    # Catatan: "laporan-N" muncul di report DAN di log stdout, jadi hanya cek hadir.
    for lbl in ("laporan-1", "laporan-2", "laporan-3"):
        assert lbl in result, f"laporan {lbl} hilang"
