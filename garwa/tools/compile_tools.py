"""tools/compile_tools.py
Compiler error locator — "poor-man's LSP" untuk Garwa.

Tujuan: memberi model error compiler yang TERSTRUKTUR (file:line:col + kode +
pesan) + snippet konteks AST (tree-sitter) tanpa LSP, tanpa daemon, tanpa
pihak ketiga. Kompilasi yang dipakai adalah mode CEPAT & error-only:
  - Python : `python -m py_compile` (hanya syntax, tanpa eksekusi)
  - Rust   : `rustc --emit=metadata --error-format=short` (atau `cargo check`)
  - C/C++  : `clang -fsyntax-only` (tanpa emit binary)
  - Go     : `go build ./...` (incremental + cepat)
  - Java   : `javac -d <tmp>` (hanya compile, tanpa run)
  - TS     : `tsc --noEmit` (hanya type-check, tanpa emit)
Semua berjalan lokal & tanpa dependency pihak ketiga (compiler native sistem).

Modul ini MURNI parsing & deteksi — TIDAK menyentuh DB/state, sehingga mudah
diuji unit dengan fixture string.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple

from . import _state as state

# Nama bahasa -> (ekstensi, compiler command template). Command memakai
# placeholder {path} (path file) / {tmp} (dir temp). Tiap compiler memakai
# flag CEPAT + ERROR-ONLY.
_COMPILERS: Dict[str, dict] = {
    "python": {
        "exts": {".py", ".pyi"},
        "cmd": ["python3", "-m", "py_compile", "{path}"],
        "note": "python -m py_compile (syntax check)",
    },
    "rust": {
        "exts": {".rs"},
        # --emit=metadata: hanya parse+type-check tanpa codegen (jauh lebih cepat)
        "cmd": ["rustc", "--emit=metadata", "--error-format=short", "{path}"],
        "note": "rustc --emit=metadata (type-check cepat)",
    },
    "c": {
        "exts": {".c", ".h"},
        # -fsyntax-only: parse + semantic check tanpa emit object/binary
        "cmd": ["clang", "-fsyntax-only", "-fno-diagnostics-fixit-info", "{path}"],
        "note": "clang -fsyntax-only",
    },
    "cpp": {
        "exts": {".cpp", ".cc", ".hpp", ".cxx"},
        "cmd": ["clang++", "-fsyntax-only", "-fno-diagnostics-fixit-info", "{path}"],
        "note": "clang++ -fsyntax-only",
    },
    "go": {
        "exts": {".go"},
        # go build sudah incremental + cepat; hanya compile, tanpa run
        "cmd": ["go", "build", "./..."],
        "note": "go build ./...",
    },
    "java": {
        "exts": {".java"},
        # compile ke dir temp agar tidak mengotori workdir
        "cmd": ["javac", "-d", "{tmp}", "{path}"],
        "note": "javac -d <tmp> (compile-only)",
    },
    "typescript": {
        "exts": {".ts", ".tsx", ".mts", ".cts"},
        # tsc --noEmit: type-check tanpa emit
        "cmd": ["tsc", "--noEmit", "{path}"],
        "note": "tsc --noEmit (type-check)",
    },
}

# Alias ekstensi -> bahasa (supaya konsisten dengan repo_map.EXT_LANG).
EXT_TO_LANG: Dict[str, str] = {}
for _lang, _cfg in _COMPILERS.items():
    for _ext in _cfg["exts"]:
        EXT_TO_LANG[_ext] = _lang


# ---------------------------------------------------------------------------
# Parser output compiler -> baris terstruktur
# ---------------------------------------------------------------------------
# Pola output compiler umum (dari rustc/clang/gcc/javac/go/tsc):
#   file:line:col: [E-code] pesan
#   file:line:col: error: pesan
#   file:line: error: pesan
#   file: error: pesan
_COMPILER_ERR_RE = re.compile(
    r"^(?P<file>[^\s:][^:\n]*?):(?P<line>\d+)(?::(?P<col>\d+))?:\s*"
    r"(?P<level>error|warning|note|help)\s*:?\s*"
    r"(?P<code>\[[^\]]+\]|[A-Z]{1,4}\d{3,5})?\s*:?\s*(?P<msg>.+)$"
)
# Pola baris kelanjutan (indentasi 4+ spasi / baris lanjutan pesan)
_CONTINUATION_RE = re.compile(r"^\s{4,}\S|^\s{2,}[\^~]")
# Pola baris dari go build: "./main.go:12:3: undefined: foo"
_GO_ERR_RE = re.compile(
    r"^(?P<file>\.?/?[^\s:]+\.go):(?P<line>\d+)(?::(?P<col>\d+))?:\s*"
    r"(?P<msg>.+)$"
)
# Pola tsc: "src/index.ts(12,5): error TS2322: Type 'x' is not assignable..."
_TSC_ERR_RE = re.compile(
    r"^(?P<file>[^\s:][^:\n]*?)\((?P<line>\d+),(?P<col>\d+)\):\s*"
    r"(?P<level>error|warning)\s+(?P<code>TS\d+):\s*(?P<msg>.+)$"
)


def _extract_errors(text: str) -> List[dict]:
    """Parse output compiler jadi list dict {file,line,col,level,code,msg}.

    Menangkap baris error utama + baris kelanjutan (indentasi) sebagai
    bagian pesan. Menghasilkan struktur yang sama untuk semua compiler
    (rustc/clang/gcc/javac/go/tsc) supaya konsisten & murah token.
    """
    errors: List[dict] = []
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = (_COMPILER_ERR_RE.match(line) or _GO_ERR_RE.match(line)
             or _TSC_ERR_RE.match(line))
        if m:
            d = m.groupdict()
            # normalisasi path relatif (bisa "src/main.rs" atau "./src/main.rs")
            f = d.get("file") or ""
            if f.startswith("./"):
                f = f[2:]
            level = (d.get("level") or "error").lower()
            code = d.get("code") or ""
            if code:
                code = code.strip("[]")
            msg = (d.get("msg") or "").strip()
            # kode trailing dari gcc/clang: "... [-Wunused-variable]" atau
            # "... [-Werror=format]" — tarik ke field `code` kalau belum ada.
            if not code:
                m_trail = re.search(r"\[(-W[^\]]+)\]$", msg)
                if m_trail:
                    code = m_trail.group(1)
                    msg = msg[: m_trail.start()].rstrip()
            # kumpulkan baris kelanjutan (indentasi lebih dalam) sbg konteks
            j = i + 1
            while j < n:
                cont = lines[j]
                if _CONTINUATION_RE.match(cont):
                    msg += "\n" + cont.strip()
                    j += 1
                else:
                    break
            errors.append({
                "file": f,
                "line": int(d.get("line") or 0),
                "col": int(d.get("col") or 0) if d.get("col") else None,
                "level": level,
                "code": code,
                "msg": msg,
            })
            i = j
        else:
            i += 1
    return errors


# Format ringkas satu error (murah token + presisi untuk model)
def _format_error(e: dict, base_dir: str = "") -> str:
    loc = e["file"]
    if base_dir and loc.startswith(base_dir):
        loc = os.path.relpath(loc, base_dir)
    col = f":{e['col']}" if e.get("col") else ""
    code = f" [{e['code']}]" if e.get("code") else ""
    level = e.get("level") or "error"
    msg = e["msg"].replace("\n", " ⏎ ")
    return f"{loc}:{e['line']}{col}: {level}{code}: {msg}"


def _dedupe(errors: List[dict]) -> List[dict]:
    seen = set()
    out = []
    for e in errors:
        key = (e["file"], e["line"], e["col"], e["level"], e["code"], e["msg"][:120])
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


# ---------------------------------------------------------------------------
# Deteksi bahasa dari ekstensi
# ---------------------------------------------------------------------------

def detect_language(path: str) -> Optional[str]:
    """Deteksi bahasa dari ekstensi file. None kalau tak dikenal."""
    ext = os.path.splitext(path)[1].lower()
    return EXT_TO_LANG.get(ext)


# ---------------------------------------------------------------------------
# Jalankan compiler (local, cepat, error-only)
# ---------------------------------------------------------------------------

def _run(cmd: List[str], cwd: str, timeout: int) -> Tuple[str, int]:
    """Jalankan command, kembalikan (stdout+stderr, exit_code)."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            start_new_session=True,
        )
        return proc.stdout or "", proc.returncode
    except subprocess.TimeoutExpired:
        return f"[garwa] check timeout setelah {timeout}s", 124
    except FileNotFoundError:
        return f"[garwa] compiler '{cmd[0]}' tidak ditemukan di PATH", 127
    except Exception as e:  # noqa: BLE001
        return f"[garwa] gagal menjalankan compiler: {e}", 1


def _compile_file(path: str, lang: str, timeout: int) -> Tuple[str, int, str]:
    """Jalankan compiler untuk satu file. Kembalikan (output, exit_code, note).

    Untuk bahasa yang butuh project context (java), command memakai cwd =
    direktori file (bukan workdir) supaya bisa menemukan file lain. Untuk
    python/c/cpp cukup file saja.
    """
    cfg = _COMPILERS.get(lang)
    if not cfg:
        return f"[garwa] bahasa '{lang}' tidak didukung check", 1, ""

    cwd = os.path.dirname(os.path.abspath(path)) or "."
    tmp = ""
    try:
        if lang in ("java",):
            tmp = tempfile.mkdtemp(prefix="garwa-check-")
        cmd = [c.replace("{path}", os.path.abspath(path))
                 .replace("{tmp}", tmp)
               for c in cfg["cmd"]]
        out, code = _run(cmd, cwd=cwd, timeout=timeout)
        return out, code, cfg["note"]
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def _compile_dir_go(path: str, timeout: int) -> Tuple[str, int, str]:
    """Untuk Go: compile seluruh package di direktori file (go build ./...)."""
    cwd = os.path.dirname(os.path.abspath(path)) or "."
    out, code = _run(["go", "build", "./..."], cwd=cwd, timeout=timeout)
    return out, code, "go build ./..."


def _check_python_syntax(path: str, timeout: int) -> Tuple[str, int, str]:
    """Syntax check Python IN-PROCESS via compile().

    Lebih cepat & bersih daripada `python -m py_compile`: tidak membuat
    __pycache__ di workdir user, tidak butuh subprocess, dan output error
    bisa kita format terstruktur (file:line:col: error: SyntaxError: ...).
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            src = f.read()
        compile(src, path, "exec")
        return "", 0, "python syntax (compile) check"
    except SyntaxError as e:
        line = e.lineno or 1
        col = e.offset or 1
        msg = e.msg or "invalid syntax"
        # sertakan baris sumber + caret supaya model langsung paham konteks
        ctx = ""
        if line > 0:
            lines = src.splitlines()
            if line - 1 < len(lines):
                ctx = lines[line - 1]
        out = (
            f"{path}:{line}:{col}: error: SyntaxError: {msg}\n"
            f"    {ctx}\n    {' ' * (col - 1)}^"
        )
        return out, 1, "python syntax (compile) check"
    except Exception as e:  # noqa: BLE001
        return f"{path}:1:1: error: {e}", 1, "python syntax (compile) check"


# ---------------------------------------------------------------------------
# API utama tool
# ---------------------------------------------------------------------------

def check_file(path: str, timeout: int = 120) -> str:
    """Periksa satu file: jalankan compiler cepat + parse error terstruktur.

    Kembalikan string siap-tampil ke model. Format:
      [check] <file> — <note>
      <error1>
      <error2>
      ...
      (N error, X warning)
    Kalau bersih: "[check] OK — tidak ada error."
    """
    timeout = float(timeout) if not isinstance(timeout, (int, float)) else timeout
    if timeout <= 0:
        timeout = 120
    timeout = max(1, min(timeout, 1800))

    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return f"[ERROR] File tidak ditemukan: {path}"

    lang = detect_language(path)
    if lang is None:
        return (
            f"[ERROR] Bahasa file tidak dikenal untuk check: {path}\n"
            "Ekstensi yang didukung: " + ", ".join(sorted(EXT_TO_LANG)) + "."
        )

    if lang == "go":
        out, code, note = _compile_dir_go(path, timeout)
    elif lang == "python":
        out, code, note = _check_python_syntax(path, timeout)
    else:
        out, code, note = _compile_file(path, lang, timeout)

    errors = _dedupe(_extract_errors(out))
    n_err = sum(1 for e in errors if e["level"] == "error")
    n_warn = sum(1 for e in errors if e["level"] == "warning")

    if code == 0 and not errors:
        return f"[check] OK — {note}\n(tidak ada error/warning)"

    # Format hasil
    lines = [f"[check] {os.path.basename(path)} — {note} (exit={code})"]
    if errors:
        # dedupe per file sudah; ambil max 40 error (murah token + fokus)
        for e in errors[:40]:
            lines.append(_format_error(e, base_dir=os.path.dirname(path)))
        if len(errors) > 40:
            lines.append(f"... ({len(errors) - 40} error/warning lagi)")
    else:
        # Compiler error tapi parser tak menemukan pola -> tampilkan output mentah (cap)
        raw = out.strip()
        if len(raw) > 3000:
            raw = raw[:1500] + "\n...[[dipotong]]\n" + raw[-1500:]
        lines.append("(tidak ada pola error terdeteksi — output mentah):")
        lines.append(raw)
    lines.append(f"({n_err} error, {n_warn} warning)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Snippet konteks AST (poor-man's LSP) — delegasi ke repo_map.py
# ---------------------------------------------------------------------------
# repo_map.py adalah single source of truth untuk ekstraksi simbol AST
# (tree-sitter) + snippet konteks posisi. compile_tools hanya mendelegasikan
# supaya tidak ada dua implementasi yang menyimpang. Fallback otomatis ke
# baris sekitar posisi bila tree-sitter tak tersedia.

def snippet_for_position(path: str, line: int, radius: int = 5) -> str:
    """Ambil snippet konteks di sekitar posisi `line` (1-based) pada `path`.

    Delegasi ke garwa.repo_map.snippet_for_position (tree-sitter bila ada,
    fallback baris sekitar posisi). '' bila path tidak ada.
    """
    if not os.path.isfile(path):
        return f"[snippet] File tidak ditemukan: {path}"
    try:
        from .. import repo_map as repo_map_mod
        return repo_map_mod.snippet_for_position(path, line, radius)
    except Exception:
        # fallback lokal minimal (jangan pernah crash tool)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except Exception as e:
            return f"[snippet] Gagal membaca {path}: {e}"
        lo = max(0, line - 1 - radius)
        hi = min(len(lines), line - 1 + radius + 1)
        ctx = "\n".join(f"{i + 1:6d}\t{lines[i]}" for i in range(lo, hi))
        return f"[snippet] {os.path.basename(path)} (fallback, sekitar baris {line}):\n{ctx}"


# ---------------------------------------------------------------------------
# Auto-check cache (P3): hash konten file per jalur, supaya edit_file tidak
# re-check file yang isinya tidak berubah.
# ---------------------------------------------------------------------------
_check_cache: Dict[str, str] = {}  # path -> sha256 konten

def file_hash(path: str) -> str:
    """SHA-256 konten file (untuk cache auto-check). '' kalau gagal baca."""
    try:
        import hashlib
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return ""


def should_recheck(path: str, content_hash: str) -> bool:
    """True kalau konten file saat ini != hash terakhir yang di-check.

    Auto-check edit_file memakai ini supaya tidak compile ulang file yang
    tidak berubah (hemat waktu & komputasi di loop agen).
    """
    cur = file_hash(path)
    if not cur or not content_hash:
        return True
    return _check_cache.get(path) != cur


def mark_checked(path: str) -> None:
    """Tandai path sebagai sudah di-check (simpan hash konten)."""
    h = file_hash(path)
    if h:
        _check_cache[os.path.abspath(path)] = h


# ---------------------------------------------------------------------------
# Wrapper tool (didaftarkan di garwa/tools/__init__.py)
# ---------------------------------------------------------------------------

def tool_check(path: str, timeout: int = 120) -> str:
    """Tool 'check': jalankan compiler cepat untuk satu file, kembalikan
    error terstruktur file:line:col + snippet konteks baris error pertama."""
    from .sandbox import SandboxViolation, _resolve_readonly
    try:
        p = _resolve_readonly(path)
    except SandboxViolation as e:
        return f"[ERROR] {e}"
    result = check_file(p, timeout=timeout)
    # Bila ada error, sisipkan snippet konteks baris error pertama supaya
    # model langsung melihat kode yang bermasalah (poor-man's LSP).
    m = re.search(r"^([^:\n]+):(\d+):", result, re.M)
    if m and "OK" not in result.splitlines()[0]:
        err_file = m.group(1)
        err_line = int(m.group(2))
        err_path = os.path.join(state.WORKDIR, err_file) if not os.path.isabs(err_file) else err_file
        if os.path.isfile(err_path):
            result += "\n" + snippet_for_position(err_path, err_line)
    return result


def tool_snippet(path: str, line: int, radius: int = 5) -> str:
    """Tool 'snippet': ambil konteks AST (tree-sitter) / baris di sekitar
    posisi tertentu pada sebuah file."""
    from .sandbox import SandboxViolation, _resolve_readonly
    try:
        p = _resolve_readonly(path)
    except SandboxViolation as e:
        return f"[ERROR] {e}"
    return snippet_for_position(p, line, radius)


# TODO: auto-check hook untuk edit_file (P3) — dipanggil dari filesystem.py
def maybe_auto_check(path: str) -> str:
    """Auto-check cepat setelah edit: '' kalau bahasa tak dikenal / file tak
    berubah sejak check terakhir; selain itu hasil check_file() ringkas.

    Dipakai oleh tool_edit_file P3: jalankan HANYA untuk file yang bahasa-nya
    dikenali & isinya berubah sejak check terakhir (cache hash)."""
    try:
        from .sandbox import _resolve_readonly
        p = _resolve_readonly(path)
    except Exception:
        return ""
    if not os.path.isfile(p):
        return ""
    lang = detect_language(p)
    if lang is None:
        return ""
    h = file_hash(p)
    if not should_recheck(p, h):
        return ""
    mark_checked(p)
    # check cepat dengan timeout kecil (auto-check tidak boleh lama)
    return check_file(p, timeout=60)
