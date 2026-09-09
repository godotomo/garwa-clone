"""Test untuk modul garwa/checkpoints.py (Checkpoints + /undo berbasis git)."""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from garwa.checkpoints import (  # noqa: E402
    _git_available,
    _is_repo,
    create_checkpoint,
    delete_checkpoints,
    list_checkpoints,
    restore_checkpoint,
)


@pytest.fixture
def git_repo(tmp_path):
    """Buat repo git kecil dengan satu file ter-track."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    f = repo / "a.txt"
    f.write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


@pytest.fixture
def db_path(tmp_path):
    # DB di LUAR repo (kasus nyata: DB Garwa di ~/.garwa, bukan di workdir).
    return str(tmp_path / "garwa.db")


def test_git_available():
    assert _git_available() is True


def test_is_repo(git_repo):
    assert _is_repo(str(git_repo)) is True


def test_is_not_repo(tmp_path):
    assert _is_repo(str(tmp_path)) is False


def test_create_checkpoint_clean_tree(git_repo, db_path):
    # Tree bersih -> checkpoint kind='head'
    meta = create_checkpoint(db_path, "sess1", cwd=str(git_repo), message="turn 1")
    assert meta["repo"] is True
    assert meta["kind"] == "head"
    assert meta["ref"] is not None
    cps = list_checkpoints(db_path, "sess1")
    assert len(cps) == 1
    assert cps[0]["kind"] == "head"


def test_create_checkpoint_dirty_tree(git_repo, db_path):
    # Modifikasi file -> checkpoint kind='stash'
    (git_repo / "a.txt").write_text("hello changed\n")
    meta = create_checkpoint(db_path, "sess1", cwd=str(git_repo), message="turn 1")
    assert meta["repo"] is True
    assert meta["kind"] in ("stash", "head")
    cps = list_checkpoints(db_path, "sess1")
    assert len(cps) == 1


def test_create_checkpoint_untracked(git_repo, db_path):
    # File untracked -> checkpoint tetap dibuat
    (git_repo / "new.txt").write_text("new\n")
    meta = create_checkpoint(db_path, "sess1", cwd=str(git_repo))
    assert meta["repo"] is True
    cps = list_checkpoints(db_path, "sess1")
    assert len(cps) == 1


def test_create_checkpoint_non_repo(tmp_path, db_path):
    meta = create_checkpoint(db_path, "sess1", cwd=str(tmp_path))
    assert meta["repo"] is False
    assert meta["skipped"] is True
    assert list_checkpoints(db_path, "sess1") == []


def test_restore_no_checkpoint(git_repo, db_path):
    res = restore_checkpoint(db_path, "sess1", cwd=str(git_repo))
    assert res["restored"] is False
    assert res["reason"] == "no_checkpoint"


def test_restore_clean(git_repo, db_path):
    create_checkpoint(db_path, "sess1", cwd=str(git_repo))
    res = restore_checkpoint(db_path, "sess1", cwd=str(git_repo))
    assert res["restored"] is True


def test_restore_dirty_then_undo(git_repo, db_path):
    # Snapshot saat tree bersih (turn 1) -> kind='head'
    create_checkpoint(db_path, "sess1", cwd=str(git_repo), message="turn 1")
    # Agent turn 1 mengubah file
    (git_repo / "a.txt").write_text("agent turn1\n")
    # Snapshot sebelum turn 2 -> kind='stash' (menangkap "agent turn1")
    create_checkpoint(db_path, "sess1", cwd=str(git_repo), message="turn 2")
    # Agent turn 2 mengubah file lagi
    (git_repo / "a.txt").write_text("agent turn2\n")
    # /undo turn 2 -> restore checkpoint turn 2 (stash) = "agent turn1"
    res = restore_checkpoint(db_path, "sess1", cwd=str(git_repo))
    assert res["restored"] is True
    assert res["kind"] == "stash"
    assert (git_repo / "a.txt").read_text() == "agent turn1\n"


def test_delete_checkpoints(git_repo, db_path):
    create_checkpoint(db_path, "sess1", cwd=str(git_repo))
    create_checkpoint(db_path, "sess1", cwd=str(git_repo))
    assert len(list_checkpoints(db_path, "sess1")) == 2
    n = delete_checkpoints(db_path, "sess1")
    assert n == 2
    assert list_checkpoints(db_path, "sess1") == []
