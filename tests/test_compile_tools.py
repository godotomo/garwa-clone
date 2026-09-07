"""test_compile_tools.py
Unit test untuk tools/compile_tools.py — compiler error locator ("poor-man's LSP").

Prinsip:
  - Test parser output compiler MURNI dengan fixture string (tanpa menjalankan
    compiler eksternal apa pun) — cepat, deterministik, portable.
  - Test integrasi tool 'check' via registry TOOLS dengan file Python sungguhan
    (pakai compile() in-process, tidak butuh compiler eksternal).
  - Test 'snippet' fallback (tree-sitter opsional).
"""

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from garwa.tools import TOOLS  # noqa: E402
from garwa.tools import _state as shared_state  # noqa: E402
from garwa.tools import compile_tools as ct  # noqa: E402


# ---------------------------------------------------------------------------
# Deteksi bahasa
# ---------------------------------------------------------------------------

def test_detect_language():
    assert ct.detect_language("foo.py") == "python"
    assert ct.detect_language("main.rs") == "rust"
    assert ct.detect_language("a.cpp") == "cpp"
    assert ct.detect_language("b.h") == "c"
    assert ct.detect_language("main.go") == "go"
    assert ct.detect_language("App.java") == "java"
    assert ct.detect_language("index.ts") == "typescript"
    assert ct.detect_language("index.tsx") == "typescript"
    assert ct.detect_language("README.md") is None
    assert ct.detect_language("noext") is None


# ---------------------------------------------------------------------------
# Parser output compiler (fixture murni, tanpa menjalankan compiler)
# ---------------------------------------------------------------------------

def test_parse_rustc_short_format():
    out = """src/main.rs:12:9: error[E0308]: mismatched types
 --> src/main.rs:12:9
  |
12 |     let x: u32 = y;
  |         ^ expected `u32`, found `i32`
  |
help: change the type

src/main.rs:40:7: error[E0599]: no method named `foo` found for struct `Bar` in the current scope
"""
    errs = ct._extract_errors(out)
    assert len(errs) == 2, errs
    e = errs[0]
    assert e["file"] == "src/main.rs"
    assert e["line"] == 12
    assert e["col"] == 9
    assert e["code"] == "E0308"
    assert e["level"] == "error"
    assert "mismatched types" in e["msg"]
    assert errs[1]["code"] == "E0599"


def test_parse_clang_style():
    out = """main.c:5:10: error: use of undeclared identifier 'foo'
    return foo + 1;
           ^
main.c:9:2: warning: unused variable 'x' [-Wunused-variable]
"""
    errs = ct._extract_errors(out)
    assert len(errs) == 2, errs
    assert errs[0]["file"] == "main.c" and errs[0]["line"] == 5 and errs[0]["col"] == 10
    assert errs[0]["level"] == "error" and errs[0]["code"] == ""
    assert errs[1]["level"] == "warning"
    assert errs[1]["code"] == "-Wunused-variable"  # trailing bracket ditarik


def test_parse_go_build():
    out = """# my/pkg
./main.go:12:3: undefined: foo
github.com/x/y/z.go:5:2: imported and not used: "fmt"
"""
    errs = ct._extract_errors(out)
    assert len(errs) == 2, errs
    assert errs[0]["file"] == "main.go" and errs[0]["line"] == 12 and errs[0]["col"] == 3
    assert "undefined: foo" in errs[0]["msg"]


def test_parse_tsc():
    out = "src/index.ts(12,5): error TS2322: Type 'x' is not assignable to type 'y'.\n"
    errs = ct._extract_errors(out)
    assert len(errs) == 1, errs
    assert errs[0]["file"] == "src/index.ts"
    assert errs[0]["line"] == 12 and errs[0]["col"] == 5
    assert errs[0]["code"] == "TS2322"
    assert errs[0]["level"] == "error"


def test_parse_javac():
    out = """App.java:3: error: cannot find symbol
  class Foo {
  ^
  symbol:   method bar()
1 error
"""
    errs = ct._extract_errors(out)
    assert len(errs) == 1, errs
    assert errs[0]["file"] == "App.java" and errs[0]["line"] == 3
    assert errs[0]["level"] == "error"


def test_dedupe():
    out = "a.py:1:1: error: boom\na.py:1:1: error: boom\na.py:2:1: error: other\n"
    errs = ct._extract_errors(out)
    assert len(ct._dedupe(errs)) == 2


def test_format_error():
    e = {"file": "src/main.rs", "line": 12, "col": 9, "level": "error",
         "code": "E0308", "msg": "mismatched types"}
    s = ct._format_error(e)
    assert "src/main.rs:12:9" in s and "[E0308]" in s and "mismatched types" in s


# ---------------------------------------------------------------------------
# check_file — Python in-process (tidak butuh compiler eksternal)
# ---------------------------------------------------------------------------

def test_check_file_python_valid(tmp_path):
    p = tmp_path / "ok.py"
    p.write_text("x = 1\nprint(x)\n")
    r = ct.check_file(str(p), timeout=30)
    assert "OK" in r and "tidak ada error" in r


def test_check_file_python_invalid(tmp_path):
    p = tmp_path / "bad.py"
    p.write_text("def foo(:\n    pass\n")
    r = ct.check_file(str(p), timeout=30)
    assert "exit=1" in r or "error" in r.lower()
    # harus terstruktur file:line:col
    errs = ct._extract_errors(r)
    assert errs and errs[0]["level"] == "error"
    assert errs[0]["file"].endswith("bad.py")
    assert errs[0]["line"] == 1


def test_check_file_missing(tmp_path):
    r = ct.check_file(str(tmp_path / "nope.py"), timeout=5)
    assert "File tidak ditemukan" in r


def test_check_file_unknown_lang(tmp_path):
    p = tmp_path / "data.bin"
    p.write_bytes(b"\x00\x01")
    r = ct.check_file(str(p), timeout=5)
    assert "tidak dikenal" in r


# ---------------------------------------------------------------------------
# Snippet (fallback regex — tree-sitter opsional)
# ---------------------------------------------------------------------------

def test_snippet_fallback(tmp_path):
    p = tmp_path / "sample.py"
    p.write_text("def foo():\n    x = 1\n    return x\n")
    r = ct.snippet_for_position(str(p), 2, radius=1)
    assert r.startswith("[snippet]")
    assert "x = 1" in r
    assert "def foo():" in r


def test_snippet_missing_file(tmp_path):
    r = ct.snippet_for_position(str(tmp_path / "nope.py"), 1)
    assert "tidak ditemukan" in r


# ---------------------------------------------------------------------------
# Integrasi registry TOOLS
# ---------------------------------------------------------------------------

def _workdir_file(tmp_path, name: str, content: str):
    """Tulis file di dalam WORKDIR sandbox aktif (ganti WORKDIR sementara).

    CATATAN: WORKDIR tetap diubah sampai test selesai (tidak di-restore di
    sini), karena handler tool memanggil _resolve_readonly yang membaca
    state.WORKDIR. Test harus memanggil handler SEBELUM memulihkan WORKDIR.
    """
    shared_state.WORKDIR = str(tmp_path)
    p = os.path.join(shared_state.WORKDIR, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return p


def test_check_tool_registered():
    assert "check" in TOOLS
    assert TOOLS["check"]["destructive"] is False
    assert TOOLS["check"]["schema"]["name"] == "check"
    assert "path" in TOOLS["check"]["schema"]["inputSchema"]["properties"]
    assert "snippet" in TOOLS
    assert TOOLS["snippet"]["schema"]["name"] == "snippet"


def test_tool_check_integration(tmp_path):
    bad = _workdir_file(tmp_path, "bad.py", "def foo(:\n    pass\n")
    r = TOOLS["check"]["handler"](bad, timeout=30)
    assert "error" in r.lower()
    # tool_check menambahkan snippet konteks baris error pertama
    assert "[snippet]" in r or "def foo(:" in r


def test_tool_snippet_integration(tmp_path):
    p = _workdir_file(tmp_path, "s.py", "x = 1\n")
    r = TOOLS["snippet"]["handler"](p, 1)
    assert r.startswith("[snippet]")
