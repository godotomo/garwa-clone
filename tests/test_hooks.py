"""Test Hooks HookControl Garwa (fitur port dari Cline).

Verifikasi:
  - Parsing output HOOK_CONTROL\t<json> (cancel/review/overrideInput/context).
  - Merge beberapa HookControl (cancel/review OR, overrideInput terakhir menang).
  - Infer interpreter dari shebang/ekstensi.
  - run_hooks best-effort: tidak ada file -> HookControl kosong.
  - Integrasi end-to-end: skrip hook sungguhan via subprocess.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from garwa.hooks import (
    HOOK_FILE_EVENT_MAP,
    HookControl,
    _infer_command,
    _merge_controls,
    _parse_hook_control,
    _run_one_hook,
    run_hooks,
    build_payload,
)


# --- Parsing ---

def test_parse_cancel():
    c = _parse_hook_control('HOOK_CONTROL\t{"cancel":true,"errorMessage":"blocked"}')
    assert c is not None
    assert c.cancel is True
    assert c.cancelReason == "blocked"
    assert c.context is None  # cancel -> pesan jadi reason, bukan context


def test_parse_cancel_legacy_context():
    c = _parse_hook_control('HOOK_CONTROL\t{"cancel":true,"context":"legacy"}')
    assert c is not None
    assert c.cancel is True
    assert c.cancelReason == "legacy"


def test_parse_review():
    c = _parse_hook_control('HOOK_CONTROL\t{"review":true,"context":"needs-check"}')
    assert c is not None
    assert c.review is True
    assert c.context == "needs-check"
    assert c.cancel is False


def test_parse_override_input():
    c = _parse_hook_control('HOOK_CONTROL\t{"overrideInput":{"path":"/tmp/x"}}')
    assert c is not None
    assert c.overrideInput == {"path": "/tmp/x"}


def test_parse_context_modification():
    c = _parse_hook_control('HOOK_CONTROL\t{"contextModification":"LINT: 2 errors"}')
    assert c is not None
    assert c.context == "LINT: 2 errors"


def test_parse_invalid_returns_none():
    assert _parse_hook_control("no control here") is None
    assert _parse_hook_control('HOOK_CONTROL\tnot-json') is None
    assert _parse_hook_control("") is None


def test_parse_embedded_in_log():
    # HOOK_CONTROL bisa muncul di tengah output log lain.
    c = _parse_hook_control('some log line\nHOOK_CONTROL\t{"cancel":false,"context":"ok"}')
    assert c is not None
    assert c.cancel is False
    assert c.context == "ok"


# --- Merge ---

def test_merge_cancel_or():
    merged = _merge_controls([
        HookControl(cancel=False, context="a"),
        HookControl(cancel=True, cancelReason="stop"),
    ])
    assert merged.cancel is True
    assert merged.cancelReason == "stop"
    assert merged.context == "a"


def test_merge_override_last_wins():
    merged = _merge_controls([
        HookControl(overrideInput={"a": 1}),
        HookControl(overrideInput={"b": 2}),
    ])
    assert merged.overrideInput == {"b": 2}


def test_merge_context_joins_newline():
    merged = _merge_controls([
        HookControl(context="first"),
        HookControl(context="second"),
    ])
    assert merged.context == "first\nsecond"


def test_merge_review_or():
    merged = _merge_controls([
        HookControl(review=False),
        HookControl(review=True),
    ])
    assert merged.review is True


def test_merge_empty():
    merged = _merge_controls([])
    assert merged.cancel is False
    assert merged.review is False
    assert merged.overrideInput is None
    assert merged.context is None


# --- Infer command ---

def test_infer_shebang():
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
        f.write("#!/usr/bin/env bash\necho hi\n")
        path = f.name
    cmd = _infer_command(path)
    assert cmd[0] == "bash"  # env di-strip, bash diambil
    assert cmd[-1] == path
    os.unlink(path)


def test_infer_py_extension():
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write("print('hi')\n")
        path = f.name
    cmd = _infer_command(path)
    assert cmd[0] == "python3"
    assert cmd[-1] == path
    os.unlink(path)


def test_infer_bash_default():
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("echo hi\n")
        path = f.name
    cmd = _infer_command(path)
    assert cmd[0] == "bash"
    os.unlink(path)


# --- run_hooks best-effort ---

def test_run_hooks_no_files(tmp_path):
    # Tidak ada folder .garwa/hooks -> HookControl kosong.
    ctrl = run_hooks("tool_call", {"x": 1}, str(tmp_path))
    assert ctrl.cancel is False
    assert ctrl.review is False


def test_run_hooks_missing_dir(tmp_path):
    ctrl = run_hooks("agent_end", {}, str(tmp_path / "nonexistent"))
    assert ctrl.cancel is False


# --- run_hooks end-to-end dengan skrip sungguhan ---

def test_run_hooks_actual_script(tmp_path):
    hooks_dir = tmp_path / ".garwa" / "hooks"
    hooks_dir.mkdir(parents=True)
    # PreToolUse hook yang selalu cancel.
    script = hooks_dir / "PreToolUse.sh"
    script.write_text(
        "#!/bin/bash\n"
        "cat >/dev/null\n"  # baca payload stdin
        "echo 'HOOK_CONTROL\t{\"cancel\":true,\"errorMessage\":\"policy\"}'\n"
    )
    script.chmod(0o755)
    ctrl = run_hooks("tool_call", {"tool_name": "write_file"}, str(tmp_path))
    assert ctrl.cancel is True
    assert ctrl.cancelReason == "policy"


def test_run_hooks_actual_script_override(tmp_path):
    hooks_dir = tmp_path / ".garwa" / "hooks"
    hooks_dir.mkdir(parents=True)
    script = hooks_dir / "PreToolUse.py"
    script.write_text(
        "import sys, json\n"
        "json.load(sys.stdin)\n"
        "print('HOOK_CONTROL\\t' + json.dumps({'overrideInput': {'path': '/tmp/x'}}))\n"
    )
    ctrl = run_hooks("tool_call", {"tool_name": "write_file"}, str(tmp_path))
    assert ctrl.overrideInput == {"path": "/tmp/x"}


def test_run_hooks_actual_script_context(tmp_path):
    hooks_dir = tmp_path / ".garwa" / "hooks"
    hooks_dir.mkdir(parents=True)
    script = hooks_dir / "PostToolUse.sh"
    script.write_text(
        "#!/bin/bash\n"
        "cat >/dev/null\n"
        "echo 'HOOK_CONTROL\t{\"context\":\"NOTE: build passed\"}'\n"
    )
    script.chmod(0o755)
    ctrl = run_hooks("tool_result", {"tool_name": "bash"}, str(tmp_path))
    assert ctrl.context == "NOTE: build passed"


def test_build_payload_has_timestamp():
    p = build_payload(event="tool_call", tool_name="x")
    assert p["event"] == "tool_call"
    assert p["tool_name"] == "x"
    assert "timestamp" in p


def test_event_map_matches():
    assert HOOK_FILE_EVENT_MAP["UserPromptSubmit"] == "prompt_submit"
    assert HOOK_FILE_EVENT_MAP["PreToolUse"] == "tool_call"
    assert HOOK_FILE_EVENT_MAP["PostToolUse"] == "tool_result"
    assert HOOK_FILE_EVENT_MAP["TaskComplete"] == "agent_end"
