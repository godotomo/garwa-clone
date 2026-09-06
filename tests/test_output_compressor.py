"""Test untuk garwa/tools/output_compressor.py — kompresi output format-aware.

Fokus utama: TIDAK boleh kehilangan informasi penting (error/diff/traceback),
dan hasil kompresi harus benar-benar lebih kecil (gate rasio).
"""

import pytest

from garwa.tools.output_compressor import (
    MIN_COMPRESSION_RATIO,
    compress_output,
    is_critical,
)


# ---------------------------------------------------------------------------
# is_critical
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "line",
    [
        "error: something broke",
        "FAILED tests/test_a.py::test_z - AssertionError: 1 != 2",
        "    ValueError: bad value",
        "[ERROR] command failed",
        "    E   AssertionError: assert 1 == 2",
        "TimeoutError: operation timed out",
        "Traceback (most recent call last):",
        "    pytest.exceptions.Failed: boom",
    ],
)
def test_is_critical_true(line):
    assert is_critical(line) is True


@pytest.mark.parametrize(
    "line",
    [
        "    foo bar baz",
        "test_001 PASSED",
        "........................................ [  9%]",
        "1 passed in 0.5s",
        "On branch main",
    ],
)
def test_is_critical_false(line):
    assert is_critical(line) is False


# ---------------------------------------------------------------------------
# Exit code != 0 -> jangan kompres agresif
# ---------------------------------------------------------------------------

def test_failed_command_not_aggressively_compressed():
    raw = (
        "Traceback (most recent call last):\n"
        "  File \"app.py\", line 5, in <module>\n"
        "    main()\n"
        "  File \"app.py\", line 8, in main\n"
        "    raise ValueError(\"boom\")\n"
        "ValueError: boom\n"
        + "\n".join(f"noise line {i}" for i in range(200))
    )
    out = compress_output("pytest", raw, exit_code=1)
    # Boleh di-cleanup ringan (ANSI/blank), tapi error harus tetap ada
    assert "ValueError: boom" in out
    assert "Traceback" in out


# ---------------------------------------------------------------------------
# pytest
# ---------------------------------------------------------------------------

def test_pytest_progress_suppressed():
    lines = ["." * 40 + f" [{pct:3d}%]" for pct in range(0, 101, 10)]
    raw = "\n".join(lines)
    out = compress_output("python -m pytest", raw, exit_code=0)
    assert out == "[pytest progress output suppressed]"


def test_pytest_passes_collapse_to_count_and_keep_failures():
    lines = [f"test_case_{i:03d} PASSED" for i in range(200)]
    lines += [
        "=================================== FAILURES ===================================",
        "____________________ test_broken ____________________",
        "    def test_broken():",
        ">       assert 1 == 2",
        "E       AssertionError: assert 1 == 2",
        "",
        "tests/test_x.py:10: AssertionError",
        "========================= 2 failed, 200 passed ===========================",
    ]
    raw = "\n".join(lines)
    out = compress_output("pytest -q", raw, exit_code=0)
    assert "[200 tests passed]" in out
    assert "AssertionError: assert 1 == 2" in out
    assert "tests/test_x.py:10: AssertionError" in out
    assert "2 failed" in out
    # Harus benar-benar lebih kecil
    assert len(out) < len(raw) * (1 - MIN_COMPRESSION_RATIO)


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------

def test_git_diff_keeps_changes_trims_context():
    lines = ["diff --git a/src/foo.py b/src/foo.py", "@@ -1,120 +1,122 @@"]
    lines += [f"     context line {i} unchanged" for i in range(100)]
    lines += ["-    old_value = compute(0)", "+    new_value = compute_better(0)"]
    lines += [f"     trailing context {i} unchanged" for i in range(40)]
    raw = "\n".join(lines)
    out = compress_output("git diff", raw, exit_code=0)
    # Perubahan wajib dipertahankan
    assert "-    old_value = compute(0)" in out
    assert "+    new_value = compute_better(0)" in out
    # Context dipangkas
    assert "unchanged context lines" in out
    assert len(out) < len(raw) * (1 - MIN_COMPRESSION_RATIO)


def test_git_status_compact():
    lines = ["## main...origin/main"]
    lines += [f" M file_{i:03d}.py" for i in range(60)]
    raw = "\n".join(lines)
    out = compress_output("git status", raw, exit_code=0)
    assert "On branch main" in out
    assert "Files: 60" in out
    assert "(10 more)" in out
    assert len(out) < len(raw)


# ---------------------------------------------------------------------------
# Gate rasio & output pendek
# ---------------------------------------------------------------------------

def test_short_output_not_compressed():
    raw = "1 passed in 0.5s"
    out = compress_output("pytest", raw, exit_code=0)
    assert out == raw


def test_output_not_worsened():
    # Output yang sudah padat (tanpa noise) tidak boleh jadi lebih besar
    raw = "\n".join(f"line {i} with some text" for i in range(50))
    out = compress_output("git log", raw, exit_code=0)
    assert len(out) <= len(raw) + 1  # boleh sama / sedikit (wrapper)
