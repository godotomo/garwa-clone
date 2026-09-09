"""garwa/hooks.py

Hooks HookControl (fitur yang di-port dari Cline).

Hooks memungkinkan user mendefinisikan skrip eksternal yang dipanggil pada
titik-titik tertentu dalam siklus hidup agent. Skrip bisa mengendalikan
eksekusi lewat output `HOOK_CONTROL\t<json>` dengan field:

  - cancel: boolean. True -> hentikan eksekusi (tool/turn). cancelReason
    dipakai sebagai alasan.
  - review: boolean. True -> minta konfirmasi user sebelum eksekusi tool
    (berguna untuk tool yang mengubah file saat auto-approve OFF).
  - overrideInput: objek -> ganti argumen tool sebelum dieksekusi.
  - context / contextModification: string -> suntikkan konteks ke pesan
    (dipakai sebagai appendContext setelah tool / sebelum turn).

Konfigurasi: folder `<workdir>/.garwa/hooks/` berisi file skrip yang
dinamai sesuai event (ekstensi opsional, interpreter di-infer dari shebang
atau ekstensi):

  - UserPromptSubmit  -> dijalankan sebelum user message diproses.
  - PreToolUse        -> dijalankan sebelum tool dieksekusi.
  - PostToolUse       -> dijalankan setelah tool dieksekusi.
  - TaskComplete      -> dijalankan di akhir giliran yang berhasil.

Payload JSON dikirim ke skrip via stdin (baris terakhir). Skrip menulis
`HOOK_CONTROL\t<json>` ke stdout untuk mengendalikan eksekusi.

Semua hook best-effort: kegagalan skrip TIDAK menggagalkan agent (hanya
di-log), kecuali skrip secara eksplisit mengeluarkan cancel:true.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Nama file konfigurasi hook -> event internal.
HOOK_FILE_EVENT_MAP = {
    "UserPromptSubmit": "prompt_submit",
    "PreToolUse": "tool_call",
    "PostToolUse": "tool_result",
    "TaskComplete": "agent_end",
}

# Ekstensi file skrip yang dikenali + interpreter default.
_EXT_INTERPRETER = {
    ".sh": ["bash"],
    ".bash": ["bash"],
    ".zsh": ["zsh"],
    ".py": ["python3"],
    ".js": ["node"],
    ".mjs": ["node"],
    ".cjs": ["node"],
    ".ts": ["bun", "run"],
    ".mts": ["bun", "run"],
    ".cts": ["bun", "run"],
    ".ps1": ["pwsh", "-File"],
}

HOOKS_DIR_NAME = ".garwa/hooks"


@dataclass
class HookControl:
    """Hasil kontrol dari satu hook (atau gabungan beberapa hook)."""

    cancel: bool = False
    cancelReason: Optional[str] = None
    review: bool = False
    overrideInput: Optional[Any] = None
    context: Optional[str] = None


def _merge_controls(controls: List[HookControl]) -> HookControl:
    """Gabungkan beberapa HookControl (semantik menyerupai Cline mergeHookControls)."""
    if not controls:
        return HookControl()
    merged = HookControl()
    contexts: List[str] = []
    reasons: List[str] = []
    for c in controls:
        merged.cancel = merged.cancel or c.cancel
        merged.review = merged.review or c.review
        if c.context:
            contexts.append(c.context)
        if c.cancelReason:
            reasons.append(c.cancelReason)
        if c.overrideInput is not None:
            merged.overrideInput = c.overrideInput
    merged.context = "\n".join(contexts) or None
    merged.cancelReason = "\n".join(reasons) or None
    return merged


def _parse_hook_control(raw: str) -> Optional[HookControl]:
    """Parse satu baris `HOOK_CONTROL\t<json>` menjadi HookControl."""
    if not raw:
        return None
    # Cari awalan HOOK_CONTROL di mana pun dalam output (bisa ada log lain).
    idx = raw.find("HOOK_CONTROL")
    if idx == -1:
        return None
    after = raw[idx + len("HOOK_CONTROL"):]
    if not after.startswith("\t"):
        return None
    data_str = after[1:].strip()
    try:
        data = json.loads(data_str)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    cancel = data.get("cancel") is True
    review = data.get("review") is True
    injectable = data.get("context")
    if not isinstance(injectable, str):
        injectable = data.get("contextModification")
    error_msg = data.get("errorMessage")
    if isinstance(error_msg, str) and error_msg.strip():
        error_msg = error_msg.strip()
    else:
        error_msg = None
    cancel_reason = None
    context = None
    if cancel:
        # Hook yang cancel: pesannya jadi alasan, bukan konteks.
        cancel_reason = error_msg or (injectable if isinstance(injectable, str) else None)
    else:
        context = injectable if isinstance(injectable, str) else None
    override_input = data.get("overrideInput") if "overrideInput" in data else None
    return HookControl(
        cancel=cancel,
        cancelReason=cancel_reason,
        review=review,
        overrideInput=override_input,
        context=context,
    )


def _infer_command(path: str) -> List[str]:
    """Infer interpreter dari shebang atau ekstensi file."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            first = f.readline().strip()
        if first.startswith("#!"):
            tokens = first[2:].strip().split()
            if tokens:
                # Normalisasi `#!/usr/bin/env bash` -> `bash` (strip env).
                if tokens[0].split("/")[-1] == "env":
                    tokens = tokens[1:]
                return tokens + [path]
    except OSError:
        pass
    _, ext = os.path.splitext(path)
    interp = _EXT_INTERPRETER.get(ext.lower())
    if interp:
        return interp + [path]
    # Default: bash untuk file tanpa ekstensi/shebang (legacy).
    return ["bash", path]


def _list_hook_files(workdir: str, event: str) -> List[str]:
    """Daftar file skrip hook untuk satu event di <workdir>/.garwa/hooks/."""
    hooks_dir = os.path.join(workdir, HOOKS_DIR_NAME)
    if not os.path.isdir(hooks_dir):
        return []
    files = []
    try:
        for entry in os.listdir(hooks_dir):
            full = os.path.join(hooks_dir, entry)
            if not os.path.isfile(full):
                continue
            base = entry
            for ext in _EXT_INTERPRETER:
                if base.endswith(ext):
                    base = base[: -len(ext)]
                    break
            if base in HOOK_FILE_EVENT_MAP and HOOK_FILE_EVENT_MAP[base] == event:
                files.append(full)
    except OSError:
        return []
    return sorted(files)


def _run_one_hook(command: List[str], payload: Dict[str, Any], timeout: float = 30.0) -> Optional[HookControl]:
    """Jalankan satu skrip hook, kirim payload via stdin, parse kontrol."""
    try:
        proc = subprocess.run(
            command,
            input=json.dumps(payload) + "\n",
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        sys.stderr.write(f"[hooks] gagal jalankan {' '.join(command)}: {type(e).__name__}: {e}\n")
        return None
    # Cari HOOK_CONTROL di stdout (stderr dipakai untuk log).
    return _parse_hook_control(proc.stdout or "")


def run_hooks(event: str, payload: Dict[str, Any], workdir: str) -> HookControl:
    """Jalankan semua skrip hook untuk `event` dan gabungkan kontrolnya.

    Best-effort: kegagalan skrip tidak dilempar; hanya di-log. Kontrol
    digabung (cancel/review OR, overrideInput terakhir menang, context
    digabung newline).
    """
    files = _list_hook_files(workdir, event)
    if not files:
        return HookControl()
    controls: List[HookControl] = []
    for f in files:
        try:
            cmd = _infer_command(f)
        except Exception:  # noqa: BLE001
            continue
        ctrl = _run_one_hook(cmd, payload)
        if ctrl is not None:
            controls.append(ctrl)
    return _merge_controls(controls)


def build_payload(**kwargs: Any) -> Dict[str, Any]:
    """Bangun payload standar untuk hook (timestamp, workdir, dll)."""
    payload = {
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }
    payload.update(kwargs)
    return payload
