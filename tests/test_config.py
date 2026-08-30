"""Test untuk garwa/config.py: persistensi user config & prioritas nilai.

Config memakai nilai module-level yang dihitung saat import, jadi test
prioritas env vs config memakai `importlib.reload` agar nilai dihitung
ulang dengan env yang sudah di-mock.
"""

from garwa import config


def test_news_lang_to_params_known():
    assert config.news_lang_to_params("id") == ("id", "ID", "ID:id")
    assert config.news_lang_to_params("en") == ("en", "US", "US:en")
    assert config.news_lang_to_params("de") == ("de", "DE", "DE:de")
    assert config.news_lang_to_params("JA") == ("ja", "JP", "JP:ja")


def test_news_lang_to_params_unknown_falls_back_to_id():
    assert config.news_lang_to_params("zz") == ("id", "ID", "ID:id")
    assert config.news_lang_to_params("") == ("id", "ID", "ID:id")
    assert config.news_lang_to_params(None) == ("id", "ID", "ID:id")


def test_save_and_load_github_token(tmp_path):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    config.save_user_config(github_token="ghp_abcdef1234")
    cfg = config.load_user_config()
    assert cfg["github_token"] == "ghp_abcdef1234"


def test_save_and_load_github_max(tmp_path):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    config.save_user_config(github_max=5000)
    cfg = config.load_user_config()
    assert cfg["github_max"] == "5000"


def test_save_and_load_news_lang(tmp_path):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    config.save_user_config(news_lang="en")
    cfg = config.load_user_config()
    assert cfg["news_lang"] == "en"


def test_save_does_not_clear_existing_keys(tmp_path):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    config.save_user_config(url="http://a", api_key="k1")
    config.save_user_config(github_token="tok")
    cfg = config.load_user_config()
    assert cfg["url"] == "http://a"
    assert cfg["api_key"] == "k1"
    assert cfg["github_token"] == "tok"


def test_github_token_env_wins_over_config(tmp_path, monkeypatch):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    config.save_user_config(github_token="from_config")
    monkeypatch.setenv("GITHUB_TOKEN", "from_env")
    config._reload_values()
    assert config.GITHUB_TOKEN == "from_env"


def test_github_token_config_used_when_no_env(tmp_path, monkeypatch):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    config.save_user_config(github_token="from_config")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    config._reload_values()
    assert config.GITHUB_TOKEN == "from_config"


def test_news_lang_config_drives_params_when_no_env(tmp_path, monkeypatch):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    config.save_user_config(news_lang="en")
    for var in ("GOOGLE_NEWS_HL", "GOOGLE_NEWS_GL", "GOOGLE_NEWS_CEID"):
        monkeypatch.delenv(var, raising=False)
    config._reload_values()
    assert config.GOOGLE_NEWS_HL == "en"
    assert config.GOOGLE_NEWS_GL == "US"
    assert config.GOOGLE_NEWS_CEID == "US:en"


def test_news_lang_env_wins_over_config(tmp_path, monkeypatch):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    config.save_user_config(news_lang="id")
    monkeypatch.setenv("GOOGLE_NEWS_HL", "fr")
    monkeypatch.setenv("GOOGLE_NEWS_GL", "FR")
    monkeypatch.setenv("GOOGLE_NEWS_CEID", "FR:fr")
    config._reload_values()
    assert config.GOOGLE_NEWS_HL == "fr"
    assert config.GOOGLE_NEWS_GL == "FR"
    assert config.GOOGLE_NEWS_CEID == "FR:fr"


def test_github_max_config_used_when_no_env(tmp_path, monkeypatch):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    config.save_user_config(github_max=777)
    monkeypatch.delenv("GITHUB_MAX_CONTENT", raising=False)
    config._reload_values()
    assert config.GITHUB_MAX_CONTENT == 777


def test_github_max_default(tmp_path, monkeypatch):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    monkeypatch.delenv("GITHUB_MAX_CONTENT", raising=False)
    config._reload_values()
    assert config.GITHUB_MAX_CONTENT == 12000


def test_github_max_invalid_config_does_not_crash(tmp_path, monkeypatch):
    """BUG REGRESI: nilai `github_max` non-numerik di config pengguna tidak
    boleh membuat _reload_values() (dan import config) melempar ValueError.
    Sebelumnya int() langsung dijalankan pada nilai config -> crash seluruh CLI.
    """
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    with open(config.USER_CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write("github_max=abc\n")
    monkeypatch.delenv("GITHUB_MAX_CONTENT", raising=False)
    # Tidak boleh melempar exception; harus jatuh ke default 12000.
    config._reload_values()
    assert config.GITHUB_MAX_CONTENT == 12000


def test_github_max_empty_config_uses_default(tmp_path, monkeypatch):
    config.USER_CONFIG_PATH = str(tmp_path / "cfg")
    with open(config.USER_CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write("github_max=\n")
    monkeypatch.delenv("GITHUB_MAX_CONTENT", raising=False)
    config._reload_values()
    assert config.GITHUB_MAX_CONTENT == 12000
