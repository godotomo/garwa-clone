"""Checkpoint berbasis git untuk Garwa -- snapshot working tree per giliran.

Mekanisme meniru fitur Checkpoints Cline (git stash/commit-tree) dengan
pendekatan yang lebih ringan dan andal, tanpa GitPython:

  - SEBELUM sebuah giliran user diproses, kita membuat snapshot git dari
    working tree (perubahan tracked + untracked files) via `git stash create`
    yang dilengkapi parent ketiga untuk untracked files (commit-tree).
  - Snapshot disimpan di tabel DB `checkpoints` (per session), berisi SHA ref
    + metadata (waktu, jumlah file berubah, pesan).
  - `/undo` merestore checkpoint terakhir: `git stash apply` (atau
    `git checkout` untuk snapshot HEAD-only) untuk mengembalikan working tree,
    lalu menghapus pesan giliran dari DB.

Checkpoint bersifat best-effort: kalau bukan repo git atau git tidak tersedia,
fungsi ini tidak menggagalkan giliran -- hanya mencatat bahwa checkpoint
dilewati (supaya /undo tetap bisa menghapus pesan DB, hanya tanpa restore file).

Semua operasi git dijalankan via subprocess terhadap binary `git` (sama seperti
garwa/tools/git_tools.py), tanpa dependency eksternal.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from typing import Any, Dict, List, Optional

from .db import connect

# Prefiks untuk pesan stash snapshot, agar mudah dikenali & di-identifikasi.
STASH_PREFIX = "garwa checkpoint session="
CHECKPOINT_SCRATCH_PREFIX = "garwa-checkpoint"


class CheckpointError(Exception):
    """Error terkait checkpoint git (bukan repo, git tidak tersedia, gagal)."""


def _git_available() -> bool:
    try:
        subprocess.run(
            ["git", "--version"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return True
    except Exception:  # noqa: BLE001 - git tidak tersedia
        return False


def _run_git(
    args: List[str],
    cwd: Optional[str] = None,
    check: bool = True,
    timeout: int = 60,
) -> "subprocess.CompletedProcess[str]":
    """Jalankan `git <args>` di cwd (default: cwd saat ini)."""
    if not _git_available():
        raise CheckpointError(
            "git tidak tersedia di sistem (binary `git` tidak ditemukan di PATH)."
        )
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise CheckpointError(
            f"perintah git timeout setelah {timeout}s: git {' '.join(args)}"
        ) from e
    if check and proc.returncode != 0:
        raise CheckpointError(
            f"git {' '.join(args)} gagal (exit {proc.returncode}):\n"
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )
    return proc


def _is_repo(cwd: Optional[str] = None) -> bool:
    proc = _run_git(
        ["rev-parse", "--is-inside-work-tree"], cwd=cwd, check=False
    )
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def repo_root(cwd: Optional[str] = None) -> str:
    proc = _run_git(["rev-parse", "--show-toplevel"], cwd=cwd)
    root = proc.stdout.strip()
    if not root:
        raise CheckpointError("tidak bisa menentukan root repo git.")
    return root


def git_head_commit(cwd: Optional[str] = None) -> Optional[str]:
    proc = _run_git(["rev-parse", "HEAD"], cwd=cwd, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def git_dirty_files(cwd: Optional[str] = None) -> List[str]:
    """Daftar file yang berubah (tracked modified + untracked)."""
    proc = _run_git(["status", "--porcelain"], cwd=cwd)
    files: List[str] = []
    for line in proc.stdout.splitlines():
        line = line.rstrip("\n")
        if not line:
            continue
        # Format: "XY path" (2 char status + spasi + path)
        files.append(line[3:])
    return files


# ---------------------------------------------------------------------------
# Snapshot creation
# ---------------------------------------------------------------------------

def _create_untracked_commit(
    cwd: str, stash_ref: str, message: str
) -> Optional[str]:
    """Buat commit yang berisi untracked files sebagai parent ketiga stash.

    Mirip `git stash create --include-untracked`, tapi dijalankan tanpa
    memodifikasi working tree. Mengembalikan SHA commit snapshot, atau None
    bila tidak ada untracked files / gagal (fallback ke stash biasa).
    """
    # Cek ada untracked files atau tidak.
    proc = _run_git(["ls-files", "--others", "--exclude-standard"], cwd=cwd)
    untracked = [p for p in proc.stdout.splitlines() if p.strip()]
    if not untracked:
        return None

    # Buat index sementara berisi hanya untracked files.
    import tempfile
    fd, index_file = tempfile.mkstemp(prefix=CHECKPOINT_SCRATCH_PREFIX)
    os.close(fd)
    try:
        # reset index sementara
        _run_git(["read-tree", "HEAD"], cwd=cwd, check=False)
        env = dict(os.environ, GIT_INDEX_FILE=index_file)
        # Bersihkan index sementara (kosongkan) lalu tambah untracked.
        _run_git(["read-tree", "--empty"], cwd=cwd, check=False)
        # Stage untracked files ke index sementara.
        proc = subprocess.run(
            ["git", "add", "--", *untracked],
            cwd=cwd,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            check=False,
        )
        if proc.returncode != 0:
            return None
        # Commit tree dari index sementara.
        proc = subprocess.run(
            ["git", "write-tree"],
            cwd=cwd,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            check=False,
        )
        if proc.returncode != 0:
            return None
        tree = proc.stdout.strip()
        if not tree:
            return None
        # Parent: stash_ref^1 (base), stash_ref^2 (index), dan tree untracked.
        base = _run_git(["rev-parse", f"{stash_ref}^1"], cwd=cwd).stdout.strip()
        index_parent = _run_git(
            ["rev-parse", f"{stash_ref}^2"], cwd=cwd, check=False
        ).stdout.strip()
        parents = [base, index_parent] if index_parent else [base]
        proc = subprocess.run(
            ["git", "commit-tree", tree, "-m", message, *parents],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout.strip() or None
    finally:
        try:
            os.unlink(index_file)
        except OSError:
            pass


def create_checkpoint(
    db_path: str,
    session_id: str,
    cwd: Optional[str] = None,
    message: str = "",
) -> Dict[str, Any]:
    """Buat snapshot git working tree dan catat di DB.

    Mengembalikan dict metadata checkpoint. Best-effort: bila bukan repo git
    atau git tidak tersedia, kembalikan dict dengan `"repo": False` tanpa
    melempar -- supaya giliran tetap berjalan.
    """
    cwd = cwd or os.getcwd()
    if not _git_available() or not _is_repo(cwd):
        return {"repo": False, "skipped": True, "reason": "not_a_repo"}

    try:
        head = git_head_commit(cwd)
    except CheckpointError:
        head = None

    stamp = int(time.time())
    stash_message = f"{STASH_PREFIX}{session_id} @ {stamp} {message}".strip()

    # Snapshot tracked changes via `git stash create` (tidak memodifikasi tree).
    proc = _run_git(["stash", "create", stash_message], cwd=cwd, check=False)
    stash_ref = proc.stdout.strip()

    snapshot_ref: Optional[str] = None
    kind = "clean"
    dirty = git_dirty_files(cwd)

    if stash_ref:
        # Perluas dengan untracked files (parent ketiga) bila ada.
        untracked_ref = _create_untracked_commit(cwd, stash_ref, stash_message)
        snapshot_ref = untracked_ref or stash_ref
        kind = "stash"
    elif head:
        # Working tree bersih: snapshot cukup HEAD commit.
        snapshot_ref = head
        kind = "head"

    if not snapshot_ref:
        return {
            "repo": True,
            "skipped": True,
            "reason": "no_snapshot",
            "head": head,
        }

    metadata = {
        "repo": True,
        "session_id": session_id,
        "ref": snapshot_ref,
        "kind": kind,
        "head": head,
        "stash_ref": stash_ref,
        "created_at": stamp,
        "dirty_files": dirty,
        "message": message,
    }
    _save_checkpoint(db_path, session_id, metadata)
    return metadata


_CHECKPOINTS_DDL = """
CREATE TABLE IF NOT EXISTS checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    ref TEXT NOT NULL,
    kind TEXT NOT NULL,
    head TEXT,
    stash_ref TEXT,
    created_at INTEGER NOT NULL,
    dirty_files TEXT,
    message TEXT
)
"""


def _ensure_checkpoints_table(conn) -> None:
    conn.execute(_CHECKPOINTS_DDL)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_checkpoints_session "
        "ON checkpoints(session_id, id)"
    )


def _save_checkpoint(db_path: str, session_id: str, metadata: Dict[str, Any]) -> None:
    with connect(db_path) as conn:
        _ensure_checkpoints_table(conn)
        conn.execute(
            "INSERT INTO checkpoints "
            "(session_id, ref, kind, head, stash_ref, created_at, dirty_files, message) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                metadata["session_id"],
                metadata["ref"],
                metadata["kind"],
                metadata.get("head"),
                metadata.get("stash_ref"),
                metadata["created_at"],
                json.dumps(metadata.get("dirty_files", [])),
                metadata.get("message", ""),
            ),
        )


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

def _restore_stash(cwd: str, stash_ref: str) -> None:
    """Restore tracked files ke state snapshot via `git checkout <tree> -- .`.

    Checkpoint dibuat SEBELUM giliran, jadi working tree saat ini sudah berubah
    oleh agent. `git stash apply` hanya menerapkan diff (base -> snapshot) dan
    akan konflik dengan perubahan turn. Sebaliknya, `git checkout <tree> -- .`
    menimpa tracked files langsung ke state snapshot (hard restore) tanpa
    konflik. Untracked files baru TIDAK dihapus (konservatif, hindari
    `git clean` yang berisiko menghapus .venv/node_modules).
    """
    tree = _run_git(["rev-parse", f"{stash_ref}^{{tree}}"], cwd=cwd).stdout.strip()
    if not tree:
        raise CheckpointError("tidak bisa menentukan tree snapshot untuk restore.")
    proc = _run_git(["checkout", tree, "--", "."], cwd=cwd, check=False)
    if proc.returncode != 0:
        raise CheckpointError(
            f"git checkout snapshot gagal (exit {proc.returncode}):\n"
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )


def _restore_head(cwd: str, head: str) -> None:
    """Restore tracked files ke HEAD commit (untuk snapshot kind='head').

    Snapshot head = commit HEAD saat checkpoint dibuat (working tree bersih).
    Kalau agent mengubah file setelahnya dan kita /undo ke checkpoint head,
    `git checkout HEAD -- .` menimpa tracked files kembali ke state bersih.
    """
    if not head:
        return
    proc = _run_git(["checkout", head, "--", "."], cwd=cwd, check=False)
    if proc.returncode != 0:
        raise CheckpointError(
            f"git checkout HEAD snapshot gagal (exit {proc.returncode}):\n"
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )


def restore_checkpoint(
    db_path: str,
    session_id: str,
    cwd: Optional[str] = None,
    checkpoint_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Restore checkpoint terakhir (atau spesifik) untuk session.

    Mengembalikan dict hasil. Bila checkpoint berbasis stash, restore working
    tree. Bila kind='head', tidak ada perubahan file yang di-restore.
    """
    cwd = cwd or os.getcwd()
    with connect(db_path) as conn:
        _ensure_checkpoints_table(conn)
        if checkpoint_id is not None:
            row = conn.execute(
                "SELECT * FROM checkpoints WHERE id=? AND session_id=?",
                (checkpoint_id, session_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM checkpoints WHERE session_id=? "
                "ORDER BY id DESC LIMIT 1",
                (session_id,),
            ).fetchone()

    if not row:
        return {"restored": False, "reason": "no_checkpoint"}

    # `connect` dari db.py memakai sqlite3.Row (row_factory), jadi row TIDAK
    # punya `.description`. Akses via indeks dengan urutan kolom tabel yang
    # benar: id, session_id, ref, kind, head, stash_ref, created_at,
    # dirty_files, message.
    rec = {
        "id": row[0],
        "session_id": row[1],
        "ref": row[2],
        "kind": row[3],
        "head": row[4],
        "stash_ref": row[5],
        "created_at": row[6],
        "dirty_files": json.loads(row[7]) if row[7] else [],
        "message": row[8],
    }

    kind = rec.get("kind", "stash")
    ref = rec.get("ref")
    stash_ref = rec.get("stash_ref")

    if not _git_available() or not _is_repo(cwd):
        return {
            "restored": False,
            "reason": "not_a_repo",
            "checkpoint": rec,
        }

    try:
        if kind == "stash" and (stash_ref or ref):
            _restore_stash(cwd, stash_ref or ref)
            return {"restored": True, "kind": "stash", "checkpoint": rec}
        elif kind == "head":
            _restore_head(cwd, ref or "")
            return {"restored": True, "kind": "head", "checkpoint": rec}
        else:
            return {"restored": False, "reason": "unknown_kind", "checkpoint": rec}
    except CheckpointError as e:
        return {"restored": False, "reason": "restore_failed", "error": str(e)}


def list_checkpoints(db_path: str, session_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    with connect(db_path) as conn:
        _ensure_checkpoints_table(conn)
        rows = conn.execute(
            "SELECT * FROM checkpoints WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    result = []
    for row in rows:
        rec = {
            "id": row[0],
            "session_id": row[1],
            "ref": row[2],
            "kind": row[3],
            "head": row[4],
            "stash_ref": row[5],
            "created_at": row[6],
            "dirty_files": json.loads(row[7]) if row[7] else [],
            "message": row[8],
        }
        result.append(rec)
    return result


def delete_checkpoints(db_path: str, session_id: str) -> int:
    with connect(db_path) as conn:
        _ensure_checkpoints_table(conn)
        cur = conn.execute(
            "DELETE FROM checkpoints WHERE session_id=?", (session_id,)
        )
        return cur.rowcount
