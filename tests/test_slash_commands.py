"""Test untuk garwa/cli/slash_commands.py: 3 command baru.

Berkas ini fokus pada /github-token, /github-max, dan /news-lang, termasuk
mutasi state tools, persistensi ke config, dan masking token.
"""

from garwa import config
from garwa import tools as tools_module
from garwa.cli import slash_commands as sc


class _Args:
    """Minimal mock args; cukup memuat atribut yang diakses handler."""

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _run(cmd_line, **args_kw):
    args = _Args(**args_kw)
    return sc.handle_slash_command(cmd_line, args, session_id="s1", system_content="")


def test_github_token_unknown_returns_skip():
    res = _run("/github-token")
    assert res["action"] == "skip"


def test_github_token_mutates_state_and_persists(tmp_path, capsys):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    old = tools_module.state.GITHUB_TOKEN
    try:
        res = _run("/github-token ghp_abcd1234")
        assert res["action"] == "skip"
        assert tools_module.state.GITHUB_TOKEN == "ghp_abcd1234"
        cfg = config.load_user_config()
        assert cfg["github_token"] == "ghp_abcd1234"
        out = capsys.readouterr().out
        assert "****1234" in out
        assert "ghp_abcd1234" not in out
    finally:
        tools_module.state.GITHUB_TOKEN = old


def test_github_token_set_persists(tmp_path):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    old = tools_module.state.GITHUB_TOKEN
    try:
        res = _run("/github-token ghp_new5678")
        assert res["action"] == "skip"
        assert tools_module.state.GITHUB_TOKEN == "ghp_new5678"
        cfg = config.load_user_config()
        assert cfg["github_token"] == "ghp_new5678"
    finally:
        tools_module.state.GITHUB_TOKEN = old


def test_github_token_query_masks_current(tmp_path, capsys):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    old = tools_module.state.GITHUB_TOKEN
    try:
        tools_module.state.GITHUB_TOKEN = "ghp_super_secret_9999"
        _run("/github-token")
        out = capsys.readouterr().out
        assert "****9999" in out
        assert "ghp_super_secret_9999" not in out
    finally:
        tools_module.state.GITHUB_TOKEN = old


def test_github_max_mutates_state_and_persists(tmp_path):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    old = tools_module.state._GITHUB_MAX_CONTENT
    try:
        res = _run("/github-max 5000")
        assert res["action"] == "skip"
        assert tools_module.state._GITHUB_MAX_CONTENT == 5000
        cfg = config.load_user_config()
        assert cfg["github_max"] == "5000"
    finally:
        tools_module.state._GITHUB_MAX_CONTENT = old


def test_github_max_invalid_rejected(tmp_path, capsys):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    old = tools_module.state._GITHUB_MAX_CONTENT
    try:
        res = _run("/github-max -5")
        assert res["action"] == "skip"
        assert tools_module.state._GITHUB_MAX_CONTENT == old
        out = capsys.readouterr().out
        assert "tidak valid" in out
    finally:
        tools_module.state._GITHUB_MAX_CONTENT = old


def test_news_lang_mutates_state_and_persists(tmp_path):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    old = (tools_module.state.GOOGLE_NEWS_HL,
           tools_module.state.GOOGLE_NEWS_GL,
           tools_module.state.GOOGLE_NEWS_CEID)
    try:
        res = _run("/news-lang en")
        assert res["action"] == "skip"
        assert tools_module.state.GOOGLE_NEWS_HL == "en"
        assert tools_module.state.GOOGLE_NEWS_GL == "US"
        assert tools_module.state.GOOGLE_NEWS_CEID == "US:en"
        cfg = config.load_user_config()
        assert cfg["news_lang"] == "en"
    finally:
        (tools_module.state.GOOGLE_NEWS_HL,
         tools_module.state.GOOGLE_NEWS_GL,
         tools_module.state.GOOGLE_NEWS_CEID) = old


def test_news_lang_unknown_rejected(tmp_path, capsys):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    old = tools_module.state.GOOGLE_NEWS_HL
    try:
        res = _run("/news-lang zz")
        assert res["action"] == "skip"
        assert tools_module.state.GOOGLE_NEWS_HL == old
        out = capsys.readouterr().out
        assert "tidak dikenal" in out
    finally:
        tools_module.state.GOOGLE_NEWS_HL = old


def test_commands_registered():
    assert "github-token" in sc.COMMANDS
    assert "github-max" in sc.COMMANDS
    assert "news-lang" in sc.COMMANDS
    assert "github-token" in sc._COMMANDS_WITH_ARGS
    assert "github-max" in sc._COMMANDS_WITH_ARGS
    assert "news-lang" in sc._COMMANDS_WITH_ARGS
