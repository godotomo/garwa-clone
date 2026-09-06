"""tools/output_compressor.py
Kompresi output CLI yang *format-aware* untuk mengurangi token yang masuk
context window, tanpa kehilangan informasi penting (error/diff/traceback).

Motivasi (riset repo `ppgranger/token-saver`): output terminal yang dibaca
coding agent (git diff, pytest, npm/pip install, dsb.) sering 60-99% noise.
Strategi yang dipakai di sini adalah format-aware parsing (deterministik,
~ms, tanpa panggilan LLM tambahan), BUKAN blind truncation yang berisiko
membuang error di tengah output.

Prinsip keamanan (safety-net):
  - `is_critical()` adalah SATU definisi "garis yang tidak boleh hilang".
  - Command GAGAL (exit_code != 0) TIDAK dikompres agresif.
  - Setelah kompresi, garis kritis yang hilang di-re-append (recover).
  - Gate rasio: hasil kompresi dibuang bila tidak lebih kecil dari minimum.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Cleanup generik & deteksi garis kritis
# ---------------------------------------------------------------------------

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07")
_NUMERIC_RE = re.compile(r"\d+(\.\d+)?")

_CRITICAL_CI = re.compile(
    r"\b("
    r"error|errors|failed|failure|failures|fatal|panic|panicked|"
    r"exception|traceback|assert|assertion|denied|refused|timeout|timed"
    r")\b"
    r"|^\s*(FAIL|ERR)\b"
    r"|\[(ERROR|FATAL|CRITICAL)\]"
    r"|\b\w+Error\b"
    r"|\b\w+Exception\b",
    re.IGNORECASE,
)
_CRITICAL_CS = re.compile(
    r"^\s*E\b"
    r"|\b(E[A-Z]{3,}|SIG[A-Z]{3,})\b"
)


def is_critical(line: str) -> bool:
    """True bila baris tampak melaporkan kegagalan yang wajib dipertahankan."""
    return bool(_CRITICAL_CI.search(line) or _CRITICAL_CS.search(line))


def _critical_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip() and is_critical(ln)]


def _missing_critical(original: str, compressed: str) -> list[str]:
    return [line for line in _critical_lines(original) if line not in compressed]


def _clean(lines: list[str]) -> list[str]:
    """Cleanup ringan yang selalu aman: strip ANSI + collapse baris kosong."""
    lines = [ANSI_RE.sub("", ln).rstrip() for ln in lines]
    result: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        result.append(line)
        prev_blank = is_blank
    return result


# ---------------------------------------------------------------------------
# Processor pytest
# ---------------------------------------------------------------------------

_PYTEST_RE = re.compile(
    r"\b(pytest|py\.test|python[23]?(?:\.\d+)?\s+-m\s+pytest"
    r"|(?:poetry|uv|pipx)\s+run\s+pytest)\b"
)

_MAX_TRACEBACK_LINES = 30


def _truncate_traceback(block: list[str]) -> list[str]:
    if len(block) <= _MAX_TRACEBACK_LINES:
        return block
    keep_head = _MAX_TRACEBACK_LINES // 2
    keep_tail = _MAX_TRACEBACK_LINES - keep_head
    omitted = len(block) - keep_head - keep_tail
    return [
        *block[:keep_head],
        f"    ... ({omitted} traceback lines truncated)",
        *block[-keep_tail:],
    ]


def _collapse_warnings(warning_lines: list[str]) -> list[str]:
    by_type: dict[str, list[str]] = {}
    for line in warning_lines:
        m = re.search(r"(\w+Warning):\s*(.+)", line)
        if m:
            by_type.setdefault(m.group(1), []).append(line)
        else:
            by_type.setdefault("other", []).append(line)

    if not by_type:
        return []

    result: list[str] = []
    total = sum(len(v) for v in by_type.values())
    parts = [
        f"{wtype} x{len(instances)}"
        for wtype, instances in sorted(by_type.items(), key=lambda x: -len(x[1]))
        if wtype != "other"
    ]
    if parts:
        result.append(f"Warnings ({total}): {', '.join(parts)}")
        most_common = max(by_type.items(), key=lambda x: len(x[1]))
        if most_common[1]:
            result.append(f"  e.g. {most_common[1][0]}")
    return result


def _compress_pytest(lines: list[str]) -> str:
    result: list[str] = []
    in_failure = False
    in_warnings = False
    failure_block: list[str] = []
    warning_lines: list[str] = []
    summary_lines: list[str] = []
    passed_count = 0
    any_skipped = False  # ada baris noise (progress bar dll.) yang di-skip

    for line in lines:
        s = line.strip()
        if re.match(r"^(collecting|collected)\s", s):
            continue
        if re.match(r"^(platform|rootdir|configfile|plugins|cachedir)[\s:]", s):
            continue

        if re.match(r"^=+ FAILURES =+", s):
            in_failure = True
            in_warnings = False
            result.append(line)
            continue

        if re.match(r"^=+ warnings summary =+", s):
            in_warnings = True
            in_failure = False
            if failure_block:
                result.extend(_truncate_traceback(failure_block))
                failure_block = []
            continue

        if in_warnings:
            if re.match(r"^=+.*=+$", s):
                in_warnings = False
                if warning_lines:
                    result.extend(_collapse_warnings(warning_lines))
                    warning_lines = []
                summary_lines.append(line)
            else:
                if s and not s.startswith("--"):
                    warning_lines.append(s)
            continue

        if in_failure:
            if re.match(r"^_+ .+ _+$", s):
                if failure_block:
                    result.extend(_truncate_traceback(failure_block))
                    failure_block = []
                result.append(line)
                continue
            if re.match(r"^=+ (short test summary|warnings summary|\d+ (failed|passed|error))", s):
                in_failure = False
                if failure_block:
                    result.extend(_truncate_traceback(failure_block))
                    failure_block = []
                if "warnings summary" in s:
                    in_warnings = True
                else:
                    result.append(line)
            elif re.match(r"^=+.*=+$", s) and "FAILURES" not in s:
                in_failure = False
                if failure_block:
                    result.extend(_truncate_traceback(failure_block))
                    failure_block = []
                result.append(line)
            else:
                failure_block.append(line)
            continue

        # Progress bar gaya pytest: ".... [ 42%]" atau "..... [100%]".
        # Ini noise murni — lewati tanpa dihitung sebagai test.
        if re.match(r"^[.sFEx]*\s*\[\s*\d+%\]\s*$", s) or re.match(r"^[.sFEx]+$", s):
            any_skipped = True
            continue

        if re.search(r"\bPASSED\b", s):
            passed_count += 1
            continue

        if re.search(r"\bFAILED\b|\bERROR\b", s):
            result.append(line)
            continue

        if re.match(r"^=+.*=+$", s) and "test session starts" not in s:
            summary_lines.append(line)
            continue

        if re.match(r"^(FAILED|ERROR)\s", s):
            result.append(line)

    if warning_lines:
        result.extend(_collapse_warnings(warning_lines))
    if failure_block:
        result.extend(_truncate_traceback(failure_block))

    if passed_count > 0:
        result.insert(0, f"[{passed_count} tests passed]")

    result.extend(summary_lines)
    if result:
        return "\n".join(result)
    # Semua baris adalah noise (progress bar) dan tidak ada summary yang
    # tersisa — jangan kembalikan output asli yang panjang; cukup ringkasan
    # eksplisit supaya model tahu test berjalan normal.
    if any_skipped:
        return "[pytest progress output suppressed]"
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Processor git
# ---------------------------------------------------------------------------

_GIT_OPTS = (
    r"(?:-C\s+\S+\s+|--no-pager\s+|-c\s+\S+\s+"
    r"|--git-dir(?:=|\s+)\S+\s+|--work-tree(?:=|\s+)\S+\s+)*"
)
_GIT_CMD_RE = re.compile(
    rf"\bgit\s+{_GIT_OPTS}(status|diff|log|show|push|pull|fetch|clone|branch|stash|reflog|remote|blame|cherry-pick|rebase|merge)\b"
)

_MAX_DIFF_CONTEXT = 3
_MAX_LOG_ENTRIES = 10

_LOCK_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Pipfile.lock", "Cargo.lock", "composer.lock", "Gemfile.lock",
    "go.sum", "bun.lockb",
}


def _git_subcmd(command: str) -> str | None:
    m = _GIT_CMD_RE.search(command)
    return m.group(1) if m else None


def _trim_diff_context(lines: list[str]) -> str:
    result: list[str] = []
    pending_context: list[str] = []

    def flush() -> None:
        if pending_context:
            if len(pending_context) > _MAX_DIFF_CONTEXT:
                result.extend(pending_context[:_MAX_DIFF_CONTEXT])
                result.append(f"... ({len(pending_context) - _MAX_DIFF_CONTEXT} unchanged context lines)")
            else:
                result.extend(pending_context)
            pending_context.clear()

    for line in lines:
        is_change = line.startswith(("+", "-", "@@", "diff --git", "... "))
        if is_change:
            flush()
            result.append(line)
        else:
            pending_context.append(line)
    flush()
    return "\n".join(result)


def _compress_git_diff(lines: list[str]) -> str:
    out: list[str] = []
    current_lockfile: str | None = None
    lock_count = 0

    for line in lines:
        if line.startswith("diff --git"):
            if current_lockfile is not None:
                out.append(f"diff --git {current_lockfile}")
                out.append(f"  (lockfile changed, {lock_count} lines)")
            m = re.match(r"^diff --git a/(.+?) b/", line)
            fname = m.group(1).rsplit("/", 1)[-1] if m else ""
            if fname in _LOCK_FILES:
                current_lockfile = fname
                lock_count = 0
            else:
                current_lockfile = None
                out.append(line)
            continue

        if current_lockfile is not None:
            lock_count += 1
            continue

        out.append(line)

    if current_lockfile is not None:
        out.append(f"diff --git {current_lockfile}")
        out.append(f"  (lockfile changed, {lock_count} lines)")

    return _trim_diff_context(out)


def _compress_git_log(lines: list[str]) -> str:
    entries: list[str] = []
    current_hash = ""
    current_msg = ""
    for line in lines:
        if line.startswith("commit "):
            if current_hash:
                entries.append(f"{current_hash} {current_msg}".strip())
            current_hash = line.split()[1][:8]
            current_msg = ""
        elif line.strip() and not line.startswith(("Author:", "Merge:", "Date:")) and not current_msg:
            current_msg = line.strip()
    if current_hash:
        entries.append(f"{current_hash} {current_msg}".strip())

    if len(entries) <= _MAX_LOG_ENTRIES:
        return "\n".join(entries) if entries else "\n".join(lines)
    return "\n".join(entries[:_MAX_LOG_ENTRIES]) + f"\n... ({len(entries) - _MAX_LOG_ENTRIES} more commits)"


def _compress_git_status(lines: list[str]) -> str:
    result: list[str] = []
    counts: dict[str, int] = {}
    files: list[str] = []
    header: list[str] = []
    code_map = {
        "modified:": "M", "new file:": "A", "deleted:": "D", "renamed:": "R",
        "copied:": "C", "typechange:": "T",
    }
    for line in lines:
        s = line.strip()
        if s.startswith("## "):
            header.append(f"On branch {s[3:].split('...')[0]}")
            continue
        if s.startswith(("On branch", "Your branch", "HEAD detached", "nothing to commit", "no changes added")):
            header.append(s)
            continue
        if s.startswith(("Untracked files:", "Changes", "Unmerged")):
            continue
        if s.startswith("("):
            continue
        m = re.match(r"^([MADRCTU?! ]{1,2})\s+(.+)$", s)
        if m:
            code = m.group(1).strip() or "?"
            path = m.group(2).strip().strip('"')
            counts[code] = counts.get(code, 0) + 1
            files.append(f"{code} {path}")
            continue
        prefix = s.split(":")[0]
        if prefix in code_map:
            path = s.split(":", 1)[1].strip()
            counts[code_map[prefix]] = counts.get(code_map[prefix], 0) + 1
            files.append(f"{code_map[prefix]} {path}")

    if header:
        result.append(" | ".join(header))
    if counts:
        total = sum(counts.values())
        parts = [f"{k}:{v}" for k, v in sorted(counts.items())]
        result.append(f"Files: {total} ({', '.join(parts)})")
    for f in files[:50]:
        result.append(f"  {f}")
    if len(files) > 50:
        result.append(f"  ... ({len(files) - 50} more)")
    return "\n".join(result) if result else "\n".join(lines)


def _compress_git_transfer(lines: list[str]) -> str:
    important: list[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if re.match(r"^(Receiving|Resolving|Counting|Compressing|remote:\s*(Counting|Compressing|Total|Enumerating))", s):
            continue
        if re.search(r"\d+%", s):
            continue
        important.append(s)
    if important:
        return "\n".join(important)
    for line in reversed(lines):
        if line.strip():
            return line.strip()
    return "\n".join(lines)


def _compress_git(command: str, lines: list[str]) -> str:
    subcmd = _git_subcmd(command)
    if subcmd == "diff":
        return _compress_git_diff(lines)
    if subcmd == "log":
        return _compress_git_log(lines)
    if subcmd == "status":
        return _compress_git_status(lines)
    if subcmd in ("push", "pull", "fetch", "clone"):
        return _compress_git_transfer(lines)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Processor install (npm / pip)
# ---------------------------------------------------------------------------

_NPM_INSTALL_RE = re.compile(r"\b(npm|yarn|pnpm|bun)\s+(install|add|i)\b")
_PIP_INSTALL_RE = re.compile(
    r"\b(pip|pip3|python[23]?(?:\.\d+)?\s+-m\s+pip)\s+install\b"
)


def _compress_install(lines: list[str]) -> str:
    out: list[str] = []
    added = 0
    for line in lines:
        s = line.strip()
        if not s:
            continue
        m = re.search(r"added\s+(\d+)\s+package", s)
        if m:
            added = int(m.group(1))
        if re.match(r"^(added|removed|changed|audited|found|up to date|npm (warn|error)|WARN|ERROR)\b", s, re.IGNORECASE):
            out.append(s)
        elif re.match(r"^(Collecting|Downloading|Requirement already satisfied|Installing collected|Successfully installed)\b", s):
            out.append(s)
    if added and not out:
        out.append(f"added {added} packages")
    return "\n".join(out) if out else "\n".join(lines)


# ---------------------------------------------------------------------------
# Engine utama
# ---------------------------------------------------------------------------

#: Rasio minimum agar hasil kompresi diterima (0.05 = harus >=5% lebih kecil).
MIN_COMPRESSION_RATIO = 0.05
#: Output di bawah panjang ini (bytes) tidak dikompres (tidak worth).
MIN_INPUT_LENGTH = 500
#: Max garis kritis yang di-recover saat hilang.
RECOVER_CRITICAL_LINES = 20


def compress_output(command: str, output: str, exit_code: int | None = None) -> str:
    """Kompres output command untuk mengurangi token, dengan safety-net.

    Return teks hasil (mungkin == output bila tidak layak/aman dikompres).

    Aturan routing:
      - exit_code != 0  -> HANYA cleanup ringan (jangan sentuh isi error).
      - output terlalu pendek -> tidak dikompres.
      - selain itu, coba processor spesifik (pytest / git / install),
        lalu cleanup generik, lalu recover garis kritis yang hilang,
        lalu gate rasio (tolak hasil bila tidak cukup kecil).
    """
    if not output:
        return output

    # Command gagal: jangan kompres agresif. Hanya strip ANSI + collapse blank.
    if exit_code is not None and exit_code != 0:
        cleaned = "\n".join(_clean(output.splitlines()))
        return cleaned if len(cleaned) < len(output) else output

    if len(output) < MIN_INPUT_LENGTH:
        return output

    lines = output.splitlines()
    compressed: str | None = None

    if _PYTEST_RE.search(command):
        compressed = _compress_pytest(lines)
    elif _GIT_CMD_RE.search(command):
        compressed = _compress_git(command, lines)
    elif _NPM_INSTALL_RE.search(command) or _PIP_INSTALL_RE.search(command):
        compressed = _compress_install(lines)

    if compressed is None or compressed == output:
        return output

    # Cleanup generik ringan setelah processor spesifik.
    compressed = "\n".join(_clean(compressed.splitlines()))

    # Safety-net: re-append garis kritis yang hilang (cap agar tidak membanjiri).
    missing = _missing_critical(output, compressed)[:RECOVER_CRITICAL_LINES]
    if missing:
        note = f"[garwa] {len(missing)} error line(s) recovered"
        compressed = "\n".join([compressed, note, *missing])

    # Gate rasio: jangan pernah mengembalikan hasil yang tidak lebih kecil.
    gain = (len(output) - len(compressed)) / len(output) if len(output) > 0 else 0
    if len(compressed) >= len(output) or gain < MIN_COMPRESSION_RATIO:
        return output

    return compressed
