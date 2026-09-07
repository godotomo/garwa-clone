"""Test untuk integrasi git Garwa (tools/git_tools.py + slash commands git).

Membuat repo git sementara di tmp_path, menguji status/diff/add/commit/log/
undo, serta slash commands /git-status, /git-diff, /git-commit, /git-undo.
"""

import os
import subprocess

import pytest

from garwa import tools as tools_module
from garwa.cli import slash_commands as sc
from garwa.tools import git_tools as gt
from garwa.tools.git_tools import _auto_commit_message


def _git(*args, cwd):
    subprocess.run(["git"] + list(args), cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def git_repo(tmp_path):
    """Buat repo git sementara dengan satu file ber-commit."""
    _git("init", "-q", cwd=str(tmp_path))
    _git("config", "user.email", "test@example.com", cwd=str(tmp_path))
    _git("config", "user.name", "Test User", cwd=str(tmp_path))
    f = tmp_path / "a.txt"
    f.write_text("hello\n", encoding="utf-8")
    _git("add", "-A", cwd=str(tmp_path))
    _git("commit", "-q", "-m", "initial commit", cwd=str(tmp_path))
    return tmp_path


class _Args:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        # default yang dibutuhkan handler commit AI
        self.url = "http://localhost:9999"
        self.model = "test-model"
        self.api_key = ""


def _run(cmd_line, args):
    return sc.handle_slash_command(cmd_line, args, session_id="s1", system_content="")


# ---------------------------------------------------------------------------
# git_tools primitives
# ---------------------------------------------------------------------------

def test_is_repo_true(git_repo):
    assert gt._is_repo(cwd=str(git_repo))


def test_is_repo_false(tmp_path):
    assert not gt._is_repo(cwd=str(tmp_path))


def test_repo_root(git_repo):
    root = gt.repo_root(cwd=str(git_repo))
    assert os.path.realpath(root) == os.path.realpath(str(git_repo))


def test_git_status_clean(git_repo):
    out = gt.git_status(cwd=str(git_repo))
    assert "Branch:" in out
    assert "bersih" in out


def test_git_status_dirty(git_repo):
    (git_repo / "a.txt").write_text("hello world\n", encoding="utf-8")
    out = gt.git_status(cwd=str(git_repo))
    assert "a.txt" in out


def test_git_diff(git_repo):
    (git_repo / "a.txt").write_text("hello world\n", encoding="utf-8")
    out = gt.git_diff(cwd=str(git_repo))
    assert "+hello world" in out


def test_git_add_and_commit(git_repo):
    (git_repo / "a.txt").write_text("hello world\n", encoding="utf-8")
    gt.git_add(cwd=str(git_repo))
    gt.git_commit("update a.txt", cwd=str(git_repo))
    assert "update a.txt" in gt.git_log(cwd=str(git_repo), n=5)


def test_git_commit_all(git_repo):
    (git_repo / "b.txt").write_text("new\n", encoding="utf-8")
    gt.git_commit_all("add b.txt", cwd=str(git_repo))
    assert "add b.txt" in gt.git_log(cwd=str(git_repo), n=5)


def test_git_undo(git_repo):
    (git_repo / "a.txt").write_text("changed\n", encoding="utf-8")
    gt.git_commit_all("second", cwd=str(git_repo))
    head_before = gt.git_head_commit(cwd=str(git_repo))
    gt.git_undo(cwd=str(git_repo))
    head_after = gt.git_head_commit(cwd=str(git_repo))
    assert head_before != head_after
    # perubahan kembali ke working tree
    assert "changed" in (git_repo / "a.txt").read_text(encoding="utf-8")


def test_git_undo_first_commit_raises(git_repo):
    with pytest.raises(gt.GitError):
        gt.git_undo(cwd=str(git_repo))


def test_git_tracked_files(git_repo):
    files = gt.git_tracked_files(cwd=str(git_repo))
    assert "a.txt" in files


def test_git_dirty_files(git_repo):
    (git_repo / "c.txt").write_text("x\n", encoding="utf-8")
    dirty = gt.git_dirty_files(cwd=str(git_repo))
    assert "c.txt" in dirty


def test_git_run_blocks_dangerous(git_repo):
    out = gt.tool_git_run("push --force", cwd=str(git_repo))
    assert "ditolak" in out


def test_git_run_ok(git_repo):
    out = gt.tool_git_run("branch", cwd=str(git_repo))
    assert "master" in out or "main" in out


# ---------------------------------------------------------------------------
# slash commands git
# ---------------------------------------------------------------------------

def test_slash_git_status(git_repo, capsys):
    old = tools_module.state.WORKDIR
    tools_module.state.WORKDIR = str(git_repo)
    try:
        res = _run("/git-status", _Args())
        assert res["action"] == "skip"
        out = capsys.readouterr().out
        assert "Branch:" in out
    finally:
        tools_module.state.WORKDIR = old


def test_slash_git_diff(git_repo, capsys):
    (git_repo / "a.txt").write_text("hello world\n", encoding="utf-8")
    old = tools_module.state.WORKDIR
    tools_module.state.WORKDIR = str(git_repo)
    try:
        res = _run("/git-diff", _Args())
        assert res["action"] == "skip"
        out = capsys.readouterr().out
        assert "+hello world" in out
    finally:
        tools_module.state.WORKDIR = old


def test_slash_git_commit_manual(git_repo, capsys):
    (git_repo / "a.txt").write_text("hello world\n", encoding="utf-8")
    old = tools_module.state.WORKDIR
    tools_module.state.WORKDIR = str(git_repo)
    try:
        res = _run("/git-commit manual message", _Args())
        assert res["action"] == "skip"
        out = capsys.readouterr().out
        assert "manual message" in gt.git_log(cwd=str(git_repo), n=5)
    finally:
        tools_module.state.WORKDIR = old


def test_slash_git_undo(git_repo, capsys):
    (git_repo / "a.txt").write_text("changed\n", encoding="utf-8")
    gt.git_commit_all("second", cwd=str(git_repo))
    old = tools_module.state.WORKDIR
    tools_module.state.WORKDIR = str(git_repo)
    try:
        res = _run("/git-undo", _Args())
        assert res["action"] == "skip"
        out = capsys.readouterr().out
        assert "undo" in out.lower()
    finally:
        tools_module.state.WORKDIR = old


def test_slash_git_run(git_repo, capsys):
    old = tools_module.state.WORKDIR
    tools_module.state.WORKDIR = str(git_repo)
    try:
        res = _run("/git branch", _Args())
        assert res["action"] == "skip"
        out = capsys.readouterr().out
        assert "master" in out or "main" in out
    finally:
        tools_module.state.WORKDIR = old


# ---------------------------------------------------------------------------
# auto-commit
# ---------------------------------------------------------------------------

def test_auto_commit_message_single_file():
    assert _auto_commit_message("diff", ["a.txt"]) == "update a.txt"


def test_auto_commit_message_multi_file():
    msg = _auto_commit_message("diff", ["a.txt", "b.txt", "c.txt"])
    assert msg == "update a.txt, b.txt, c.txt"


def test_maybe_auto_commit_disabled_returns_empty(git_repo):
    old = tools_module.state.WORKDIR
    tools_module.state.WORKDIR = str(git_repo)
    try:
        from garwa import config
        old_val = config.AUTO_COMMIT
        config.AUTO_COMMIT = False
        try:
            (git_repo / "a.txt").write_text("changed\n", encoding="utf-8")
            assert gt.maybe_auto_commit("a.txt") == ""
        finally:
            config.AUTO_COMMIT = old_val
    finally:
        tools_module.state.WORKDIR = old


def test_maybe_auto_commit_enabled(git_repo):
    old = tools_module.state.WORKDIR
    tools_module.state.WORKDIR = str(git_repo)
    try:
        from garwa import config
        old_val = config.AUTO_COMMIT
        config.AUTO_COMMIT = True
        try:
            (git_repo / "a.txt").write_text("changed v2\n", encoding="utf-8")
            out = gt.maybe_auto_commit("a.txt")
            assert "auto-commit" in out
            # perubahan sudah di-commit
            assert gt.git_head_commit_message(cwd=str(git_repo)) != "initial commit"
        finally:
            config.AUTO_COMMIT = old_val
    finally:
        tools_module.state.WORKDIR = old


def test_slash_auto_commit_toggle(tmp_path, capsys):
    from garwa import config
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    old = config.AUTO_COMMIT
    try:
        res = _run("/auto-commit on", _Args())
        assert res["action"] == "skip"
        out = capsys.readouterr().out
        assert "AKTIF" in out
        assert config.AUTO_COMMIT is True
        cfg = config.load_user_config()
        assert cfg["auto_commit"] == "1"
    finally:
        config.AUTO_COMMIT = old
