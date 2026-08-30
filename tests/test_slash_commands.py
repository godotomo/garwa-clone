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


def _run_with_args(cmd_line, **args_kw):
    args = _Args(**args_kw)
    res = sc.handle_slash_command(cmd_line, args, session_id="s1", system_content="")
    return res, args


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


# --- Context-window & summarization params ---

def test_ctx_mutates_and_persists(tmp_path):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    res, args = _run_with_args("/ctx 65536", context_window=131072)
    assert res["action"] == "skip"
    assert args.context_window == 65536
    cfg = config.load_user_config()
    assert cfg["context_window"] == "65536"


def test_ctx_invalid_rejected(tmp_path, capsys):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    res = _run("/ctx abc", context_window=131072)
    assert res["action"] == "skip"
    out = capsys.readouterr().out
    assert "tidak valid" in out


def test_reserve_mutates_and_persists(tmp_path):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    res, args = _run_with_args("/reserve 4096", reserve_for_response=2048)
    assert res["action"] == "skip"
    assert args.reserve_for_response == 4096
    cfg = config.load_user_config()
    assert cfg["reserve_for_response"] == "4096"


def test_reserve_invalid_rejected(tmp_path, capsys):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    res = _run("/reserve 0", reserve_for_response=2048)
    assert res["action"] == "skip"
    out = capsys.readouterr().out
    assert "tidak valid" in out


def test_summarize_threshold_mutates_and_persists(tmp_path):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    res, args = _run_with_args("/summarize-threshold 0.5", summarize_threshold_ratio=0.2)
    assert res["action"] == "skip"
    assert args.summarize_threshold_ratio == 0.5
    cfg = config.load_user_config()
    assert cfg["summarize_threshold_ratio"] == "0.5"


def test_summarize_threshold_invalid_rejected(tmp_path, capsys):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    res = _run("/summarize-threshold 1.5", summarize_threshold_ratio=0.2)
    assert res["action"] == "skip"
    out = capsys.readouterr().out
    assert "tidak valid" in out


def test_keep_tail_mutates_and_persists(tmp_path):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    res, args = _run_with_args("/keep-tail 12", keep_tail_messages=8)
    assert res["action"] == "skip"
    assert args.keep_tail_messages == 12
    cfg = config.load_user_config()
    assert cfg["keep_tail_messages"] == "12"


def test_keep_tail_invalid_rejected(tmp_path, capsys):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    res = _run("/keep-tail -1", keep_tail_messages=8)
    assert res["action"] == "skip"
    out = capsys.readouterr().out
    assert "tidak valid" in out
