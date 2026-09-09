"""Test Plan/Act mode Garwa (fitur port dari Cline).

Verifikasi tiga lapis penerapan plan mode:
  1. Filter field "tools" payload -- tool mutating dihilangkan.
  2. Blokir eksekusi tool mutating di agent_loop (defense-in-depth).
  3. Instruksi plan mode disuntikkan ke system prompt.
Plus slash-command /plan, /act, /mode dan indikator status bar.
"""

import sys
import os

# Pastikan root repo masuk path supaya `import garwa` jalan.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from garwa.cli import _state as state
from garwa.cli.plan_mode import (
    BLOCKED_TOOLS_IN_PLAN_MODE,
    is_tool_blocked_in_plan_mode,
    filter_tools_payload,
    plan_mode_system_prompt,
    format_plan_blocked_tool_error,
)
from garwa.cli.tool_schema.schema_text import build_openai_tools_payload
from garwa.tools import TOOLS


def _reset_mode():
    state.reset_session_state("test-plan-mode")
    state.set_mode("act")


def setup_function(func):
    _reset_mode()


def teardown_function(func):
    _reset_mode()


# --- Lapis 1: filter payload ---

def test_default_mode_is_act():
    _reset_mode()
    assert state.get_mode() == "act"


def test_set_mode_valid():
    state.set_mode("plan")
    assert state.get_mode() == "plan"
    state.set_mode("act")
    assert state.get_mode() == "act"


def test_set_mode_invalid_raises():
    try:
        state.set_mode("banana")
        assert False, "harus raise ValueError"
    except ValueError:
        pass


def test_filter_payload_act_keeps_all():
    payload = build_openai_tools_payload()
    all_names = {t["function"]["name"] for t in payload}
    assert all_names == set(TOOLS.keys())
    assert len(all_names) == len(TOOLS)


def test_filter_payload_plan_removes_mutating():
    payload = build_openai_tools_payload()
    filtered = filter_tools_payload(payload, "plan")
    filtered_names = {t["function"]["name"] for t in filtered}
    # Tool mutating harus hilang
    for blocked in BLOCKED_TOOLS_IN_PLAN_MODE:
        assert blocked not in filtered_names, f"{blocked} harus diblokir di plan"
    # Tool read-only penting harus tetap ada
    for keep in ("read_file", "grep", "list_dir", "repo_map", "outline_file",
                 "web_search", "todo_write", "todo_read", "recall"):
        assert keep in filtered_names, f"{keep} harus tetap tersedia di plan"


def test_build_payload_plan_mode_active():
    # build_openai_tools_payload() membaca state.get_mode() -> harus memfilter
    state.set_mode("plan")
    payload = build_openai_tools_payload()
    names = {t["function"]["name"] for t in payload}
    assert "write_file" not in names
    assert "bash" not in names
    assert "read_file" in names


# --- Lapis 2: blokir tool ---

def test_is_tool_blocked():
    assert is_tool_blocked_in_plan_mode("bash")
    assert is_tool_blocked_in_plan_mode("write_file")
    assert is_tool_blocked_in_plan_mode("edit_file")
    assert is_tool_blocked_in_plan_mode("git_commit")
    assert is_tool_blocked_in_plan_mode("send_email")
    assert not is_tool_blocked_in_plan_mode("read_file")
    assert not is_tool_blocked_in_plan_mode("grep")
    assert not is_tool_blocked_in_plan_mode("todo_write")


def test_format_blocked_error_mentions_plan_mode():
    err = format_plan_blocked_tool_error("write_file")
    assert "PLAN MODE" in err
    assert "write_file" in err
    assert "read-only" in err or "read_file" in err


# --- Lapis 3: instruksi system prompt ---

def test_plan_mode_system_prompt_empty_in_act():
    assert plan_mode_system_prompt("act") == ""


def test_plan_mode_system_prompt_nonempty_in_plan():
    prompt = plan_mode_system_prompt("plan")
    assert "PLAN MODE" in prompt
    assert "todo_write" in prompt
    assert "/act" in prompt


# --- Slash-command behavior (via state helpers dipakai handler) ---

def test_slash_plan_act_roundtrip():
    # Simulasi apa yang dilakukan handler /plan dan /act pada state.
    state.set_mode("plan")
    assert state.get_mode() == "plan"
    state.set_mode("act")
    assert state.get_mode() == "act"


def test_plan_blocklist_does_not_include_readonly():
    # Pastikan tool read-only inti TIDAK masuk blocklist.
    for keep in ("read_file", "grep", "list_dir", "repo_map", "outline_file",
                 "glob", "snippet", "check", "webfetch", "web_search",
                 "git_status", "git_diff", "git_log", "todo_read", "recall"):
        assert keep not in BLOCKED_TOOLS_IN_PLAN_MODE, f"{keep} tidak boleh diblokir"
