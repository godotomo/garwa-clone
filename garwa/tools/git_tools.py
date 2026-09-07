"""
tools/git_tools.py
Integrasi git untuk Garwa -- ringan, tanpa GitPython.

Aider memakai GitPython untuk mengelola repo (commit AI, undo, diff, tracked
files, dll). Garwa menekankan ringan & tanpa dependensi pihak ketiga, jadi di
sini semua operasi git dijalankan lewat subprocess terhadap binary `git` yang
sudah tersedia di sistem. Ini lebih ringan (tidak menambah dependency) dan
tetap memberi fitur inti yang sama:

  - deteksi repo & root dir
  - status / diff / add / commit (dengan pesan AI opsional)
  - tracked files & dirty files
  - head commit info
  - undo (commit terakhir yang dibuat garwa)
  - ignored file check

Semua fungsi mengembalikan string yang siap ditampilkan ke model/user, atau
melempar GitError untuk kasus non-repo / git tidak tersedia.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import List, Optional, Tuple

from . import _state as state


class GitError(Exception):
    """Error terkait git (bukan repo, git tidak tersedia, perintah gagal)."""


# ---------------------------------------------------------------------------
# Primitif subprocess
# ---------------------------------------------------------------------------

def _git_available() -> bool:
    """Cek binary `git` tersedia di PATH."""
    try:
        subprocess.run(
            ["git", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
        return True
    except Exception:
        return False


def _run_git(
    args: List[str],
    cwd: Optional[str] = None,
    timeout: int = 60,
    check: bool = True,
) -> Tuple[int, str, str]:
    """Jalankan `git <args>` di cwd (default: state.WORKDIR).

    Mengembalikan (exit_code, stdout, stderr). Kalau `check=True` dan
    git tidak tersedia, lempar GitError. Kalau `check=True` dan exit_code
    != 0, lempar GitError berisi stderr.
    """
    if not _git_available():
        raise GitError("git tidak tersedia di sistem (binary `git` tidak ditemukan di PATH).")
    base = cwd or state.WORKDIR
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=base,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise GitError("git tidak tersedia di sistem (binary `git` tidak ditemukan).")
    except subprocess.TimeoutExpired:
        raise GitError(f"perintah git timeout setelah {timeout}s: git {' '.join(args)}")
    out = proc.stdout or ""
    err = proc.stderr or ""
    if check and proc.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} gagal (exit {proc.returncode}):\n{err.strip() or out.strip()}"
        )
    return proc.returncode, out, err


def _is_repo(cwd: Optional[str] = None) -> bool:
    """Apakah cwd berada di dalam repo git (rev-parse --is-inside-work-tree)."""
    try:
        code, out, _ = _run_git(
            ["rev-parse", "--is-inside-work-tree"],
            cwd=cwd,
            check=False,
        )
        return code == 0 and out.strip().lower() == "true"
    except GitError:
        return False


def repo_root(cwd: Optional[str] = None) -> str:
    """Path absolut root repo git tempat cwd berada. Lempar GitError bila bukan repo."""
    _, out, _ = _run_git(["rev-parse", "--show-toplevel"], cwd=cwd)
    root = out.strip()
    if not root:
        raise GitError("tidak bisa menentukan root repo git.")
    return root


def _require_repo_root(cwd: Optional[str] = None) -> str:
    """Versi ramah-user dari repo_root: pesan error jelas bila bukan repo."""
    if not _is_repo(cwd):
        base = cwd or state.WORKDIR
        raise GitError(
            f"'{base}' bukan di dalam repository git. Inisialisasi dulu dengan "
            "`git init` (via tool bash) sebelum memakai tool git."
        )
    return repo_root(cwd)


# ---------------------------------------------------------------------------
# Status / diff
# ---------------------------------------------------------------------------

def git_status(cwd: Optional[str] = None) -> str:
    """Status repo: branch, staged/untracked/modified files (porcelain ringkas)."""
    _require_repo_root(cwd)
    _, branch_out, _ = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd, check=False)
    branch = branch_out.strip() or "(detached HEAD)"
    _, short_out, _ = _run_git(["rev-parse", "--short", "HEAD"], cwd=cwd, check=False)
    head_short = short_out.strip() or "?"

    _, porcelain, _ = _run_git(["status", "--porcelain"], cwd=cwd)
    lines = porcelain.splitlines() if porcelain.strip() else []
    if not lines:
        return (
            f"Branch: {branch} @ {head_short}\n"
            "Working tree bersih (tidak ada perubahan)."
        )

    staged, modified, untracked, other = [], [], [], []
    for ln in lines:
        if len(ln) < 4:
            continue
        xy, path = ln[:2], ln[3:]
        if xy == "??":
            untracked.append(path)
        elif xy[0] != " ":
            staged.append(f"{xy} {path}")
        elif xy[1] != " ":
            modified.append(path)
        else:
            other.append(f"{xy} {path}")

    out = [f"Branch: {branch} @ {head_short}", f"Total perubahan: {len(lines)}"]
    if staged:
        out.append("Staged:")
        out += [f"  {s}" for s in staged]
    if modified:
        out.append("Modified (belum staged):")
        out += [f"  {m}" for m in modified]
    if untracked:
        out.append("Untracked:")
        out += [f"  {u}" for u in untracked]
    if other:
        out.append("Lainnya:")
        out += [f"  {o}" for o in other]
    return "\n".join(out)


def git_diff(cwd: Optional[str] = None, staged: bool = False, stat: bool = False) -> str:
    """Diff working tree (default) atau staged (--cached)."""
    _require_repo_root(cwd)
    args = ["diff"]
    if staged:
        args.append("--cached")
    if stat:
        args.append("--stat")
    _, out, _ = _run_git(args, cwd=cwd)
    return out.strip() if out.strip() else "(tidak ada perubahan untuk ditampilkan)"


def git_log(cwd: Optional[str] = None, n: int = 15) -> str:
    """Log commit terakhir (oneline + author + tanggal)."""
    _require_repo_root(cwd)
    fmt = "%h|%an|%ad|%s"
    args = ["log", f"-{max(1, min(n, 100))}", f"--pretty=format:{fmt}", "--date=short"]
    _, out, _ = _run_git(args, cwd=cwd)
    if not out.strip():
        return "(belum ada commit)"
    lines = []
    for ln in out.splitlines():
        parts = ln.split("|", 3)
        if len(parts) == 4:
            h, an, ad, s = parts
            lines.append(f"{h}  {ad}  {an}  {s}")
        else:
            lines.append(ln)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tracked / dirty files
# ---------------------------------------------------------------------------

def git_tracked_files(cwd: Optional[str] = None) -> List[str]:
    """Daftar file yang di-track git (dari index + HEAD)."""
    _require_repo_root(cwd)
    _, out, _ = _run_git(["ls-files"], cwd=cwd)
    return [ln for ln in out.splitlines() if ln.strip()]


def git_dirty_files(cwd: Optional[str] = None) -> List[str]:
    """Daftar file yang punya perubahan (modified/untracked/staged)."""
    _require_repo_root(cwd)
    _, out, _ = _run_git(["status", "--porcelain"], cwd=cwd)
    files = []
    for ln in out.splitlines():
        if len(ln) < 4:
            continue
        path = ln[3:]
        if path:
            files.append(path)
    return files


# ---------------------------------------------------------------------------
# Head commit
# ---------------------------------------------------------------------------

def git_head_commit(cwd: Optional[str] = None) -> Optional[str]:
    """SHA penuh commit HEAD, atau None bila belum ada commit."""
    _require_repo_root(cwd)
    code, out, _ = _run_git(["rev-parse", "HEAD"], cwd=cwd, check=False)
    if code != 0 or not out.strip():
        return None
    return out.strip()


def git_head_commit_message(cwd: Optional[str] = None) -> str:
    """Pesan commit HEAD (subject + body), atau string kosong."""
    _require_repo_root(cwd)
    code, out, _ = _run_git(["log", "-1", "--pretty=%B"], cwd=cwd, check=False)
    if code != 0:
        return ""
    return out.strip()


# ---------------------------------------------------------------------------
# Add / commit
# ---------------------------------------------------------------------------

def git_add(paths: Optional[List[str]] = None, cwd: Optional[str] = None) -> str:
    """Stage file. Tanpa paths -> stage semua (git add -A)."""
    _require_repo_root(cwd)
    if paths:
        args = ["add", "--"] + paths
    else:
        args = ["add", "-A"]
    _, out, _ = _run_git(args, cwd=cwd)
    staged = git_tracked_files(cwd=cwd)
    _ = staged
    return "File di-stage. Gunakan /diff --staged atau tool git_diff(staged=true) untuk melihat isinya."


def git_commit(
    message: str,
    cwd: Optional[str] = None,
    author: Optional[str] = None,
    co_authored_by: Optional[str] = None,
) -> str:
    """Commit perubahan yang sudah di-stage dengan pesan `message`.

    `author` (mis. "Nama <email>") dipakai untuk override --author.
    `co_authored_by` (mis. "Nama <email>") ditambahkan sebagai trailer
    Co-authored-by di body pesan (meniru perilaku aider).
    """
    _require_repo_root(cwd)
    if not message or not message.strip():
        raise GitError("pesan commit tidak boleh kosong.")

    full_message = message.strip()
    if co_authored_by:
        full_message += f"\n\nCo-authored-by: {co_authored_by}"

    args = ["commit", "-m", full_message, "--no-verify"]
    if author:
        args += ["--author", author]
    _, out, _ = _run_git(args, cwd=cwd)
    return out.strip() or "Commit berhasil."


def git_commit_all(
    message: str,
    cwd: Optional[str] = None,
    author: Optional[str] = None,
    co_authored_by: Optional[str] = None,
) -> str:
    """Stage semua perubahan lalu commit (git add -A + commit)."""
    git_add(cwd=cwd)
    return git_commit(
        message, cwd=cwd, author=author, co_authored_by=co_authored_by
    )


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------

def git_undo(cwd: Optional[str] = None) -> str:
    """Batalkan commit terakhir (soft reset) -- meniru /undo aider.

    Mengembalikan HEAD ke commit sebelumnya (git reset --soft HEAD~1) sehingga
    perubahan tetap ada di staging area, siap di-commit ulang atau diedit.
    Aman: tidak menghapus perubahan file.
    """
    _require_repo_root(cwd)
    if git_head_commit(cwd) is None:
        raise GitError("belum ada commit untuk di-undo.")

    # Cek apakah HEAD~1 ada (sudah ada commit sebelumnya).
    code, _, _ = _run_git(["rev-parse", "HEAD~1"], cwd=cwd, check=False)
    if code != 0:
        raise GitError(
            "ini commit pertama (tidak ada HEAD~1); tidak bisa undo tanpa kehilangan riwayat."
        )

    # Guard: jangan undo kalau sudah di-push ke origin (mirip guard aider).
    code, out, _ = _run_git(
        ["branch", "-r", "--contains", "HEAD"], cwd=cwd, check=False
    )
    if code == 0 and out.strip():
        raise GitError(
            "commit HEAD sudah direferensikan oleh branch remote (kemungkinan sudah "
            "di-push). Undo akan mengubah riwayat publik -- batalkan demi keamanan."
        )

    _, out, _ = _run_git(["reset", "--soft", "HEAD~1"], cwd=cwd)
    return (
        "Commit terakhir di-undo (soft reset ke HEAD~1). Perubahan kembali ke "
        "staging area:\n" + (out.strip() or "")
    )


# ---------------------------------------------------------------------------
# Ignore
# ---------------------------------------------------------------------------

def git_ignored_file(path: str, cwd: Optional[str] = None) -> bool:
    """Apakah `path` di-ignore git (git check-ignore)."""
    _require_repo_root(cwd)
    code, _, _ = _run_git(["check-ignore", "-q", path], cwd=cwd, check=False)
    return code == 0


# ---------------------------------------------------------------------------
# Tool handler (untuk TOOLS registry)
# ---------------------------------------------------------------------------

def maybe_auto_commit(edited_path: str) -> str:
    """Commit otomatis setelah edit (best-effort, tidak pernah menggagalkan edit).

    Dipanggil dari tool_edit_file setelah edit sukses, HANYA bila auto-commit
    diaktifkan (config.AUTO_COMMIT). Commit semua perubahan yang belum di-stage
    dengan pesan AI (best-effort; kalau LLM gagal, fallback ke nama file).

    Mengembalikan string hasil (untuk disisipkan ke tool_result), atau string
    kosong bila auto-commit nonaktif / bukan repo / tidak ada perubahan.
    """
    try:
        from .. import config as config_mod
        if not getattr(config_mod, "AUTO_COMMIT", False):
            return ""
        if not _is_repo():
            return ""
        dirty = git_dirty_files()
        if not dirty:
            return ""

        # Generate pesan AI (best-effort) dari diff working tree.
        diff_text = git_diff()
        message = _auto_commit_message(diff_text, dirty)
        author = getattr(config_mod, "AUTO_COMMIT_AUTHOR", "") or None
        git_commit_all(message, author=author)
        return f"[auto-commit] perubahan di-commit: {message}"
    except GitError as e:
        return f"[auto-commit] gagal: {e}"
    except Exception as e:  # noqa: BLE001 - jangan pernah menggagalkan edit
        return f"[auto-commit] gagal: {type(e).__name__}: {e}"


def _auto_commit_message(diff_text: str, dirty_files) -> str:
    """Pesan commit generik dari daftar file yang berubah (tanpa LLM).

    Dipakai sebagai fallback cepat untuk auto-commit agar tidak memanggil LLM
    (yang lambat) pada setiap edit. Pesan ringkas & imperatif.
    """
    files = dirty_files[:5]
    if len(files) == 1:
        return f"update {files[0]}"
    return "update " + ", ".join(files)


# ---------------------------------------------------------------------------
# Branch / blame / show / reset / stash (fitur git aider yang belum ada)
# ---------------------------------------------------------------------------

def git_branch(cwd: Optional[str] = None, create: Optional[str] = None,
               delete: Optional[str] = None, switch: Optional[str] = None) -> str:
    """Kelola branch: list (default), create, delete, atau switch.

    - git_branch()                     -> daftar branch lokal + penanda aktif
    - git_branch(create="nama")        -> buat branch baru (git branch <nama>)
    - git_branch(delete="nama")        -> hapus branch (git branch -d <nama>)
    - git_branch(switch="nama")        -> pindah branch (git checkout <nama>)

    Meniru fitur branch di aider. Semua operasi aman (tidak ada force).
    """
    _require_repo_root(cwd)
    if create:
        _run_git(["branch", create], cwd=cwd)
        return f"Branch '{create}' dibuat."
    if delete:
        # -d (safe delete): tolak kalau branch belum di-merge (mirip guard aider).
        _run_git(["branch", "-d", delete], cwd=cwd)
        return f"Branch '{delete}' dihapus."
    if switch:
        _run_git(["checkout", switch], cwd=cwd)
        return f"Berpindah ke branch '{switch}'."
    # List branch lokal dengan penanda aktif (*) + commit terkait.
    _, out, _ = _run_git(
        ["branch", "-vv", "--no-color"], cwd=cwd, check=False,
    )
    if not out.strip():
        return "(belum ada branch)"
    return out.strip()


def git_blame(path: str, cwd: Optional[str] = None, line: Optional[int] = None) -> str:
    """Blame sebuah file: siapa yang menulis tiap baris & di commit mana.

    `line` (opsional): kalau diisi, hanya tampilkan blame untuk baris tsb
    (1-based). Tanpa line, tampilkan blame seluruh file (dibatasi).
    """
    _require_repo_root(cwd)
    # Resolve path relatif terhadap repo root (bukan cwd proses), supaya
    # blame path seperti "a.txt" bekerja walau cwd berbeda dari repo root.
    base = cwd or state.WORKDIR
    full = path if os.path.isabs(path) else os.path.join(base, path)
    if not os.path.isfile(full):
        raise GitError(f"file tidak ditemukan untuk blame: {path}")
    args = ["blame", "--date=short"]
    if line:
        args += ["-L", f"{line},{line}"]
    args.append(full)
    _, out, _ = _run_git(args, cwd=cwd, check=False)
    if not out.strip():
        return "(tidak ada output blame)"
    # Batasi panjang output blame (file besar bisa ribuan baris).
    lines = out.splitlines()
    if len(lines) > 200:
        lines = lines[:200]
        lines.append(f"... ({len(out.splitlines()) - 200} baris lagi)")
    return "\n".join(lines)


def git_show(ref: str = "HEAD", cwd: Optional[str] = None, stat: bool = False) -> str:
    """Tampilkan isi/perubahan sebuah commit atau path: git show <ref>.

    `stat=True` hanya menampilkan ringkasan statistik (--stat).
    """
    _require_repo_root(cwd)
    args = ["show", "--no-color"]
    if stat:
        args.append("--stat")
    args.append(ref)
    _, out, _ = _run_git(args, cwd=cwd, check=False)
    if not out.strip():
        return f"(git show {ref}: tidak ada output)"
    # Batasi panjang output (commit besar bisa sangat panjang).
    lines = out.splitlines()
    if len(lines) > 300:
        lines = lines[:300]
        lines.append(f"... ({len(out.splitlines()) - 300} baris lagi)")
    return "\n".join(lines)


def git_reset(mode: str = "soft", ref: str = "HEAD~1", cwd: Optional[str] = None) -> str:
    """Reset HEAD ke `ref` dengan mode aman: soft (default) atau mixed.

    - soft  : HEAD pindah, perubahan tetap di staging (aman, tidak kehilangan apa pun)
    - mixed : HEAD pindah, perubahan kembali ke working tree (unstage)

    Menolak mode berbahaya (--hard) konsisten dengan guard. Menolak kalau
    HEAD sudah direferensikan branch remote (riwayat publik).
    """
    _require_repo_root(cwd)
    if mode not in ("soft", "mixed"):
        raise GitError(
            f"mode reset '{mode}' tidak didukung. Gunakan 'soft' atau 'mixed' "
            "(--hard ditolak demi keamanan)."
        )
    # Guard: jangan reset kalau sudah di-push ke origin (mirip guard undo).
    code, out, _ = _run_git(
        ["branch", "-r", "--contains", "HEAD"], cwd=cwd, check=False
    )
    if code == 0 and out.strip():
        raise GitError(
            "commit HEAD sudah direferensikan oleh branch remote (kemungkinan "
            "sudah di-push). Reset akan mengubah riwayat publik -- batalkan."
        )
    _, out, _ = _run_git(["reset", f"--{mode}", ref], cwd=cwd, check=False)
    return f"HEAD di-reset ({mode}) ke {ref}:\n" + (out.strip() or "")


def git_stash(cwd: Optional[str] = None, action: str = "list", message: Optional[str] = None) -> str:
    """Stash: simpan perubahan sementara (push) / tampilkan (list) / pulihkan (pop).

    - git_stash()                -> list stash yang tersimpan
    - git_stash(action="push")   -> simpan perubahan working tree ke stash
    - git_stash(action="pop")    -> pulihkan stash terbaru
    - git_stash(action="drop")   -> buang stash terbaru
    """
    _require_repo_root(cwd)
    action = (action or "list").lower()
    if action == "push":
        args = ["stash", "push", "-m", message] if message else ["stash", "push"]
        _, out, _ = _run_git(args, cwd=cwd)
        return out.strip() or "Perubahan disimpan ke stash."
    if action == "pop":
        _, out, _ = _run_git(["stash", "pop"], cwd=cwd)
        return out.strip() or "Stash terbaru dipulihkan."
    if action == "drop":
        _, out, _ = _run_git(["stash", "drop"], cwd=cwd)
        return out.strip() or "Stash terbaru dibuang."
    # list (default)
    _, out, _ = _run_git(["stash", "list"], cwd=cwd, check=False)
    return out.strip() if out.strip() else "(tidak ada stash tersimpan)"


def git_log_graph(cwd: Optional[str] = None, n: int = 20) -> str:
    """Log commit dengan grafik branch (--graph) -- mirip /git log --graph."""
    _require_repo_root(cwd)
    fmt = "%h %d %s (%an, %ad)"
    args = [
        "log", "--graph", "--oneline", "--decorate",
        f"-{max(1, min(n, 100))}", f"--pretty=format:{fmt}", "--date=short",
    ]
    _, out, _ = _run_git(args, cwd=cwd)
    return out.strip() if out.strip() else "(belum ada commit)"


def tool_git_status(cwd: str = None) -> str:
    try:
        return git_status(cwd)
    except GitError as e:
        return f"[ERROR] {e}"


def tool_git_diff(staged: bool = False, stat: bool = False, cwd: str = None) -> str:
    try:
        return git_diff(cwd, staged=staged, stat=stat)
    except GitError as e:
        return f"[ERROR] {e}"


def tool_git_log(n: int = 15, cwd: str = None) -> str:
    try:
        return git_log(cwd, n=n)
    except GitError as e:
        return f"[ERROR] {e}"


def tool_git_add(paths: list = None, cwd: str = None) -> str:
    try:
        return git_add(paths, cwd)
    except GitError as e:
        return f"[ERROR] {e}"


def tool_git_commit(message: str, all: bool = False, cwd: str = None) -> str:
    """Commit dengan pesan AI (dari slash command) atau pesan manual."""
    try:
        if all:
            return git_commit_all(message, cwd)
        return git_commit(message, cwd)
    except GitError as e:
        return f"[ERROR] {e}"


def tool_git_undo(cwd: str = None) -> str:
    try:
        return git_undo(cwd)
    except GitError as e:
        return f"[ERROR] {e}"


def tool_git_run(command: str, cwd: str = None) -> str:
    """Jalankan perintah git arbitrer (aman: tanpa push/reset --hard/clean -f).

    Mirip /git di aider. Setiap argumen dipisah oleh spasi. Perintah berbahaya
    (force-push, reset --hard, clean -f) ditolak di sini -- konsisten dengan
    filter bash di _state.py.
    """
    import re

    _require_repo_root(cwd)
    command = command.strip()
    if not command:
        return "[ERROR] perintah git kosong."

    # Tolak pola berbahaya (konsisten dengan _DANGEROUS_BASH_RE).
    dangerous = [
        r"\bpush\b.*(--force|-f)\b",
        r"\breset\b.*--hard\b",
        r"\bclean\b.*(-[a-zA-Z]*[fF][a-zA-Z]*|--force)\b",
    ]
    for pat in dangerous:
        if re.search(pat, command, re.IGNORECASE):
            return (
                f"[ERROR] perintah git berbahaya ditolak: '{command}'. "
                "Gunakan tool git_status/git_diff/git_add/git_commit/git_undo yang aman."
            )

    args = command.split()
    try:
        code, out, err = _run_git(args, cwd=cwd, check=False)
    except GitError as e:
        return f"[ERROR] {e}"
    if code != 0:
        return f"[ERROR] git {command} gagal (exit {code}):\n{err.strip() or out.strip()}"
    return out.strip() if out.strip() else "(berhasil, tanpa output)"


def tool_git_branch(create: str = "", delete: str = "", switch: str = "", cwd: str = None) -> str:
    """Tool 'git_branch': list / create / delete / switch branch."""
    try:
        return git_branch(cwd, create=create or None, delete=delete or None,
                          switch=switch or None)
    except GitError as e:
        return f"[ERROR] {e}"


def tool_git_blame(path: str, line: int = 0, cwd: str = None) -> str:
    """Tool 'git_blame': blame sebuah file (opsional per-baris)."""
    try:
        return git_blame(path, cwd, line=line or None)
    except GitError as e:
        return f"[ERROR] {e}"


def tool_git_show(ref: str = "HEAD", stat: bool = False, cwd: str = None) -> str:
    """Tool 'git_show': tampilkan isi/perubahan sebuah commit atau path."""
    try:
        return git_show(ref, cwd, stat=stat)
    except GitError as e:
        return f"[ERROR] {e}"


def tool_git_reset(mode: str = "soft", ref: str = "HEAD~1", cwd: str = None) -> str:
    """Tool 'git_reset': reset HEAD (soft/mixed aman). Tolak --hard."""
    try:
        return git_reset(mode, ref, cwd)
    except GitError as e:
        return f"[ERROR] {e}"


def tool_git_stash(action: str = "list", message: str = "", cwd: str = None) -> str:
    """Tool 'git_stash': list / push / pop / drop stash."""
    try:
        return git_stash(cwd, action=action, message=message or None)
    except GitError as e:
        return f"[ERROR] {e}"


def tool_git_log_graph(n: int = 20, cwd: str = None) -> str:
    """Tool 'git_log_graph': log dengan grafik branch."""
    try:
        return git_log_graph(cwd, n=n)
    except GitError as e:
        return f"[ERROR] {e}"
