"""tests/test_sub_agent_safety.py
Test untuk perbaikan keamanan/observabilitas sub-agent:

  1. Guard kedalaman rekursi (`GARWA_SUBAGENT_MAX_DEPTH`) -- mencegah sub-agent
     memanggil sub-agent tanpa batas (tiap tingkat = 1 thread + 1 sesi DB +
     token LLM).
  2. Field `sid` pada hasil sub-agent (paralel) terisi session sub-agent nyata,
     bukan None.
  3. Watchdog stall: status berkala + penanda "TERLIHAT MACET" untuk sub-agent
     yang menggantung tanpa kabar.
  4. Timeout batch paralel (`GARWA_SUBAGENT_TIMEOUT`) -- satu task menggantung
     TIDAK memblokir seluruh chat, dan dilaporkan EKSPLISIT sebagai timeout.
  5. Slash command `/agents` (+ `/agents clear`).

Semua test memakai LLM tiruan (tanpa server model sungguhan).
"""
import json
import threading
import time

import pytest

from garwa import db as dbmod
from garwa import subagent_registry as registry
from garwa import subagent_status as substatus
from garwa.cli import slash_commands as sc
from garwa.tools import _state as tstate
from garwa.tools import sub_agent


# ---------------------------------------------------------------------------
# Fixture & helper
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_registry():
    """Bersihkan state GLOBAL proses (registry + watchdog sub-agent).

    `subagent_status` menyimpan event/thread module-level yang bertahan antar
    test: kalau `_keepalive_stop` sudah ter-`set()` dari test sebelumnya,
    `_keepalive_loop` langsung keluar dan test watchdog jadi palsu-gagal.
    """
    registry.clear()
    with substatus._BATCH_LOCK:
        substatus._BATCH.update(active=False, total=0, workers=0,
                                started=None, done=0, ok=0, err=0)
    substatus._keepalive_stop.clear()
    substatus._keepalive_thread = None
    # `_keepalive_alive` menandai "watchdog generasi sekarang hidup". Wajib
    # di-reset: kalau test sebelumnya meninggalkannya True, `_ensure_keepalive`
    # mengira sudah ada watchdog dan tidak membuat thread baru.
    substatus._keepalive_alive = False
    substatus._keepalive_gen = 0
    yield
    registry.clear()
    substatus._keepalive_stop.set()
    substatus._keepalive_thread = None
    substatus._keepalive_alive = False
    substatus._keepalive_gen = 0


@pytest.fixture
def sub_env(db_path, monkeypatch):
    """Set state tools (DB_PATH/WORKDIR/SESSION_ID) + kedalaman 0."""
    monkeypatch.setenv("GARWA_SUBAGENT_STATUS", "1")
    old_db = tstate.DB_PATH
    old_work = tstate.WORKDIR
    tstate.DB_PATH = db_path
    tstate.WORKDIR = "/tmp/stress-workdir"
    tstate.set_session_id("parent-session")
    prev_depth = tstate.set_subagent_depth(0)
    yield db_path
    tstate.DB_PATH = old_db
    tstate.WORKDIR = old_work
    tstate.set_subagent_depth(prev_depth)


class _FakeLLM:
    """LLM tiruan: `responder(n, messages)` menentukan teks balasan call ke-n."""

    def __init__(self, responder):
        self._lock = threading.Lock()
        self.responder = responder
        self.calls = []
        self.depths = []

    def __call__(self, url, model, messages, stream=True, api_key="",
                 debug=False, temperature=0.2):
        with self._lock:
            n = len(self.calls) + 1
            self.calls.append(list(messages))
            self.depths.append(tstate.get_subagent_depth())
        return self.responder(n, messages)


def _tool_call_text(name, arguments):
    """Bentuk teks tool_call yang dikenali extractor agent_loop.

    `arguments` HARUS berupa objek JSON (bukan string ber-JSON): extractor
    menolak string dengan PARSE_ERROR "arguments harus berupa objek JSON".
    """
    return (
        "<tool_call>\n"
        + json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False)
        + "\n</tool_call>"
    )


def _sub_sessions(db_path):
    return [r for r in dbmod.list_sessions(db_path) if r["id"].startswith("sub_")]


def _run_agents(capsys, arg=""):
    class _A:
        pass

    line = "/agents" + (f" {arg}" if arg else "")
    res = sc.handle_slash_command(line, _A(), session_id="s1", system_content="")
    return res, capsys.readouterr().out


# ---------------------------------------------------------------------------
# 1. Guard kedalaman rekursi
# ---------------------------------------------------------------------------

def test_max_subagent_depth_default(monkeypatch):
    monkeypatch.delenv("GARWA_SUBAGENT_MAX_DEPTH", raising=False)
    assert sub_agent.SUBAGENT_MAX_DEPTH_DEFAULT == 2
    assert sub_agent._max_subagent_depth() == 2


@pytest.mark.parametrize("raw,expected", [
    ("1", 1), ("3", 3), ("0", 0), ("-5", -5), ("abc", 2), ("", 2), ("  ", 2),
])
def test_max_subagent_depth_env(monkeypatch, raw, expected):
    monkeypatch.setenv("GARWA_SUBAGENT_MAX_DEPTH", raw)
    assert sub_agent._max_subagent_depth() == expected


def test_depth_guard_rejects_before_creating_anything(sub_env, db_path, monkeypatch):
    """Di kedalaman maks, spawn ditolak TANPA membuat record/sesi (murah)."""
    monkeypatch.setenv("GARWA_SUBAGENT_MAX_DEPTH", "2")
    tstate.set_subagent_depth(2)
    res = sub_agent.tool_spawn_agent("tugas terlalu dalam")
    assert res.startswith("[ERROR]")
    assert "Kedalaman sub-agent melebihi batas" in res
    assert registry.list_records() == []
    assert _sub_sessions(db_path) == []


def test_depth_guard_disabled_when_env_zero(sub_env, db_path, monkeypatch):
    """GARWA_SUBAGENT_MAX_DEPTH=0 -> guard mati (di kedalaman berapapun lanjut)."""
    monkeypatch.setenv("GARWA_SUBAGENT_MAX_DEPTH", "0")
    monkeypatch.setattr("garwa.cli.agent_loop.call_llama_server",
                        _FakeLLM(lambda n, m: "laporan"))
    tstate.set_subagent_depth(7)
    res = sub_agent.tool_spawn_agent("tugas")
    assert "laporan" in res
    assert "Kedalaman sub-agent melebihi batas" not in res
    assert len(_sub_sessions(db_path)) == 1


def test_sub_agent_depth_raised_inside_loop_then_restored(sub_env, monkeypatch):
    """Kedalaman naik +1 selama loop sub-agent, lalu dipulihkan setelahnya."""
    monkeypatch.setenv("GARWA_SUBAGENT_MAX_DEPTH", "2")
    fake = _FakeLLM(lambda n, m: "selesai")
    monkeypatch.setattr("garwa.cli.agent_loop.call_llama_server", fake)
    res = sub_agent.tool_spawn_agent("tugas")
    assert "selesai" in res
    assert fake.depths == [1], fake.depths
    assert tstate.get_subagent_depth() == 0


def test_recursion_guard_stops_nested_spawn(sub_env, db_path, monkeypatch):
    """sub-agent yang memanggil spawn_agent lagi diblokir di tingkat maks.

    max_depth=2 -> root(0) -> A(1) -> B(2); B yang mencoba spawn LAGI ditolak.
    """
    monkeypatch.setenv("GARWA_SUBAGENT_MAX_DEPTH", "2")
    seen = []

    def responder(n, messages):
        seen.append([dict(m) for m in messages])
        # n=1 root -> A (depth 1); n=2 A -> B (depth 2); n=3 B mencoba spawn
        # LAGI -> ditolak guard; n=4 B menyerah & melapor selesai.
        if n <= 3:
            return _tool_call_text("spawn_agent", {"task": f"anak-{n}"})
        return "selesai"

    fake = _FakeLLM(responder)
    monkeypatch.setattr("garwa.cli.agent_loop.call_llama_server", fake)
    res = sub_agent.tool_spawn_agent("tugas-akar")
    assert "selesai" in res
    # Hanya 2 sub-session (A dan B); percobaan spawn di B tidak membuat sesi.
    assert len(_sub_sessions(db_path)) == 2
    # Pesan guard muncul sebagai hasil tool di percakapan B.
    assert any("Kedalaman sub-agent melebihi batas" in str(m.get("content", ""))
               for msgs in seen for m in msgs)
    # Kedalaman tetap dipulihkan walau ada penolakan di tengah.
    assert tstate.get_subagent_depth() == 0


# ---------------------------------------------------------------------------
# 2. Field sid hasil sub-agent
# ---------------------------------------------------------------------------

def test_sub_agent_result_encodes_session_sid(sub_env, monkeypatch):
    monkeypatch.setattr("garwa.cli.agent_loop.call_llama_server",
                        _FakeLLM(lambda n, m: "laporan"))
    res = sub_agent.tool_spawn_agent("tugas")
    assert "session sub_" in res
    assert "FINAL REPORT:" in res


def test_parallel_result_has_real_sid(sub_env, db_path, monkeypatch):
    """Field `sid` hasil paralel diambil dari context sub-agent (bukan None)."""
    monkeypatch.setattr("garwa.cli.agent_loop.call_llama_server",
                        _FakeLLM(lambda n, m: f"laporan-{n}"))
    out = sub_agent.tool_spawn_agents_parallel(["a", "b"], max_workers=2)
    assert out.count("session=sub_") == 2
    assert "session=None" not in out
    subs = {r["id"] for r in _sub_sessions(db_path)}
    for sid in subs:
        assert f"session={sid}" in out


# ---------------------------------------------------------------------------
# 3. Watchdog stall / keepalive
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("15", 15.0), ("0.5", 0.5), ("abc", 15.0),
])
def test_keepalive_interval_env(monkeypatch, raw, expected):
    monkeypatch.setenv("GARWA_SUBAGENT_KEEPALIVE", raw)
    assert substatus._keepalive_interval() == expected


@pytest.mark.parametrize("raw,expected", [
    ("60", 60.0), ("0", 0.0), ("-3", 0.0), ("abc", 60.0),
])
def test_stall_after_env(monkeypatch, raw, expected):
    monkeypatch.setenv("GARWA_SUBAGENT_STALL", raw)
    assert substatus._stall_after() == expected


def _spawn_raw_loop():
    """Jalankan `_keepalive_loop` mentah (di luar `_ensure_keepalive`).

    Signature loop kini `(stop, gen)`: event stop milik generasi thread ini
    (supaya request-stop generasi lama tidak mematikan generasi baru).
    """
    stop = threading.Event()
    t = threading.Thread(target=substatus._keepalive_loop, args=(stop, 0),
                         daemon=True)
    t.start()
    return t, stop


def _drain_keepalive(lines, want, timeout=3.0):
    """Jalankan keepalive di thread sampai `want` muncul (atau timeout)."""
    t, _stop = _spawn_raw_loop()
    deadline = time.time() + timeout
    while time.time() < deadline and not any(want in l for l in lines):
        time.sleep(0.02)
    return t


def test_keepalive_marks_stalled_sub_agent(monkeypatch):
    lines = []
    monkeypatch.setattr(substatus, "_emit", lambda s: lines.append(s))
    monkeypatch.setenv("GARWA_SUBAGENT_KEEPALIVE", "0.05")
    monkeypatch.setenv("GARWA_SUBAGENT_STALL", "10")

    rid = registry.register_start("general", "task yang menggantung")
    registry.update(rid, started_at=time.time() - 120)

    t = _drain_keepalive(lines, "TERLIHAT MACET")
    registry.mark_done(rid, registry.STATUS_SUCCESS)
    t.join(timeout=2)
    assert any("masih berjalan" in l for l in lines), lines
    assert any("TERLIHAT MACET" in l for l in lines), lines
    assert any(rid in l for l in lines), lines


def test_keepalive_no_stall_marker_when_disabled(monkeypatch):
    """GARWA_SUBAGENT_STALL=0 -> tetap ada kabar berkala, tanpa tanda MACET."""
    lines = []
    monkeypatch.setattr(substatus, "_emit", lambda s: lines.append(s))
    monkeypatch.setenv("GARWA_SUBAGENT_KEEPALIVE", "0.05")
    monkeypatch.setenv("GARWA_SUBAGENT_STALL", "0")

    rid = registry.register_start("general", "task lambat biasa")
    registry.update(rid, started_at=time.time() - 120)

    t = _drain_keepalive(lines, "masih berjalan")
    registry.mark_done(rid, registry.STATUS_SUCCESS)
    t.join(timeout=2)
    assert any("masih berjalan" in l for l in lines), lines
    assert not any("TERLIHAT MACET" in l for l in lines), lines


def test_keepalive_thread_stops_when_nothing_running(monkeypatch):
    """Keepalive berhenti sendiri setelah tidak ada record RUNNING."""
    monkeypatch.setattr(substatus, "_emit", lambda s: None)
    monkeypatch.setenv("GARWA_SUBAGENT_KEEPALIVE", "0.05")
    monkeypatch.setenv("GARWA_SUBAGENT_STALL", "0")

    rid = registry.register_start("general", "task")
    t, _stop = _spawn_raw_loop()
    time.sleep(0.15)
    assert t.is_alive()
    registry.mark_done(rid, registry.STATUS_SUCCESS)
    t.join(timeout=2)
    assert not t.is_alive()


def test_keepalive_disabled_by_env(monkeypatch):
    monkeypatch.setenv("GARWA_SUBAGENT_KEEPALIVE", "0")
    substatus._ensure_keepalive()
    assert substatus._keepalive_thread is None


# --- Regresi: watchdog TIDAK boleh hilang untuk sub-agent berikutnya -------
# Bug nyata: notify_done sub-agent #1 men-set `_keepalive_stop` generasi lama.
# Sub-agent #2 lalu memanggil `_ensure_keepalive`, melihat thread lama masih
# `is_alive()` (belum selesai unwind) -> early-return TANPA membuat watchdog,
# lalu thread lama keluar -> sub-agent #2 berjalan tanpa satu pun baris
# "masih berjalan"/"MACET".

def test_request_stop_clears_alive_flag(monkeypatch):
    """Request stop harus menurunkan `_keepalive_alive` (bukan hanya set event)."""
    monkeypatch.setenv("GARWA_SUBAGENT_KEEPALIVE", "30")
    substatus._keepalive_alive = True
    substatus._request_keepalive_stop()
    assert substatus._keepalive_stop.is_set()
    assert substatus._keepalive_alive is False


def test_ensure_keepalive_spawns_new_generation_after_stop(monkeypatch):
    """URUTAN NYATA: start -> done (stop) -> start => watchdog baru dibuat.

    Inilah regresi aslinya. `notify_done` memanggil `_request_keepalive_stop()`
    (event lama ter-set), lalu sub-agent berikutnya memanggil
    `_ensure_keepalive()`. Dulu pengecekannya `is_alive()` pada thread lama yang
    belum selesai unwind -> early-return tanpa watchdog.
    """
    monkeypatch.setenv("GARWA_SUBAGENT_KEEPALIVE", "30")

    substatus._ensure_keepalive()             # generasi #1 (sub-agent #1)
    gen1 = substatus._keepalive_gen
    assert gen1 >= 1

    substatus._request_keepalive_stop()       # dipanggil saat sub-agent #1 selesai
    assert substatus._keepalive_stop.is_set()
    assert substatus._keepalive_alive is False, "fix: request-stop turunkan flag"

    substatus._ensure_keepalive()             # sub-agent #2 minta watchdog
    try:
        assert substatus._keepalive_gen == gen1 + 1, "wajib generasi baru"
        assert substatus._keepalive_stop.is_set() is False, "event generasi baru"
        assert substatus._keepalive_alive is True
        assert substatus._keepalive_thread is not None
        assert substatus._keepalive_thread.is_alive()
    finally:
        substatus._request_keepalive_stop()
        if substatus._keepalive_thread is not None:
            substatus._keepalive_thread.join(timeout=2)


def test_ensure_keepalive_reuses_live_watchdog(monkeypatch):
    """Kalau watchdog generasi sekarang masih hidup, JANGAN buat thread baru."""
    monkeypatch.setenv("GARWA_SUBAGENT_KEEPALIVE", "30")
    substatus._ensure_keepalive()
    first = substatus._keepalive_thread
    gen_first = substatus._keepalive_gen
    try:
        substatus._ensure_keepalive()
        assert substatus._keepalive_thread is first
        assert substatus._keepalive_gen == gen_first
    finally:
        substatus._request_keepalive_stop()
        first.join(timeout=2)


def test_stale_generation_does_not_clobber_new_watchdog(monkeypatch):
    """Loop generasi LAMA yang telat bangun tak boleh mematikan flag generasi baru."""
    monkeypatch.setenv("GARWA_SUBAGENT_KEEPALIVE", "30")
    substatus._keepalive_gen = 5
    substatus._keepalive_alive = True      # milik generasi 5 (terkini)
    substatus._mark_keepalive_exit(4)      # generasi usang
    assert substatus._keepalive_alive is True
    substatus._mark_keepalive_exit(5)      # generasi terkini
    assert substatus._keepalive_alive is False


# ---------------------------------------------------------------------------
# 4. Timeout batch paralel
# ---------------------------------------------------------------------------

def test_parallel_batch_timeout_reported_explicitly(sub_env, monkeypatch):
    """Satu task menggantung -> dilaporkan 'task timeout' tanpa memblokir lama."""
    monkeypatch.setenv("GARWA_SUBAGENT_TIMEOUT", "0.15")
    monkeypatch.setenv("GARWA_SUBAGENT_KEEPALIVE", "0")

    def _hang(idx, task, role, max_iters):
        time.sleep(1.5)
        return {"idx": idx, "sid": None, "role": role, "ok": True,
                "report": "terlambat", "log": ""}

    monkeypatch.setattr(sub_agent, "_run_sub_agent_one", _hang)
    t0 = time.monotonic()
    out = sub_agent.tool_spawn_agents_parallel(["lambat"], max_workers=1)
    elapsed = time.monotonic() - t0
    assert "task timeout" in out
    assert "[SUB-AGENT-PARALEL] 1 sub-agent selesai." in out
    assert elapsed < 1.0, elapsed


def test_parallel_timeout_zero_means_no_deadline(sub_env, monkeypatch):
    monkeypatch.setenv("GARWA_SUBAGENT_TIMEOUT", "0")
    monkeypatch.setenv("GARWA_SUBAGENT_KEEPALIVE", "0")
    monkeypatch.setattr("garwa.cli.agent_loop.call_llama_server",
                        _FakeLLM(lambda n, m: "laporan"))
    out = sub_agent.tool_spawn_agents_parallel(["a", "b"], max_workers=2)
    assert "laporan" in out
    assert "task timeout" not in out


# ---------------------------------------------------------------------------
# 5. Slash command /agents
# ---------------------------------------------------------------------------

def test_agents_empty(capsys):
    res, out = _run_agents(capsys)
    assert res["action"] == "skip"
    assert "belum ada sub-agent" in out


def test_agents_lists_running_and_finished(capsys):
    rid = registry.register_start("general", "task panjang")
    registry.set_session(rid, "sub_abc123")
    done = registry.register_start("explore", "task selesai")
    registry.mark_done(done, registry.STATUS_SUCCESS)

    res, out = _run_agents(capsys)
    assert res["action"] == "skip"
    assert "1 berjalan, 1 selesai" in out
    assert "sub_abc123" in out
    assert "task panjang" in out
    assert "task selesai" in out
    assert "tidak bisa menerima input baru" in out


def test_agents_marks_stalled_running(capsys, monkeypatch):
    monkeypatch.setenv("GARWA_SUBAGENT_STALL", "10")
    rid = registry.register_start("general", "task macet")
    registry.update(rid, started_at=time.time() - 120)
    res, out = _run_agents(capsys)
    assert res["action"] == "skip"
    assert "MACET?" in out


def test_agents_shows_error_reason(capsys):
    rid = registry.register_start("general", "task gagal")
    registry.mark_done(rid, registry.STATUS_ERROR, error="RuntimeError: server down")
    res, out = _run_agents(capsys)
    assert res["action"] == "skip"
    assert "RuntimeError: server down" in out


def test_agents_clear_keeps_running(capsys):
    keep = registry.register_start("general", "masih jalan")
    registry.set_session(keep, "sub_keep1")
    done = registry.register_start("general", "sudah selesai")
    registry.mark_done(done, registry.STATUS_SUCCESS)

    res, out = _run_agents(capsys, "clear")
    assert res["action"] == "skip"
    assert "dibuang" in out
    recs = registry.list_records()
    assert len(recs) == 1
    assert recs[0]["status"] == registry.STATUS_RUNNING
    assert recs[0]["task"] == "masih jalan"
    assert recs[0]["session_id"] == "sub_keep1"


def test_agents_clear_all_when_nothing_running(capsys):
    done = registry.register_start("general", "x")
    registry.mark_done(done, registry.STATUS_ERROR, error="boom")
    res, out = _run_agents(capsys, "clear")
    assert res["action"] == "skip"
    assert "dibersihkan" in out
    assert registry.list_records() == []


def test_agents_registered_in_commands():
    assert "agents" in sc.COMMANDS
    assert "agents" in sc._COMMANDS_WITH_ARGS
