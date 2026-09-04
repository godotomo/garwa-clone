"""Unit test untuk modul MCP Garwa (garwa/mcp).

Fokus pada logika yang bisa diuji deterministik tanpa server MCP eksternal:
- load/save konfigurasi (format mcpServers)
- konversi tool MCP -> spec TOOLS Garwa (_mcp_tool_to_spec)
- slash-command /mcp-server, /mcp-api-key, /mcp-enable (dengan mock bridge)
"""

import asyncio
import json
import os
import types

import pytest

from garwa.mcp import client as mcp_client
from garwa.mcp.client import (
    DEFAULT_MCP_CONFIG_PATH,
    MCPServerConfig,
    MCPToolRegistry,
    MCPTransport,
    _mcp_tool_to_spec,
    load_mcp_config,
    save_mcp_config,
)
from garwa.cli import slash_commands as sc
from garwa.tools import TOOLS


@pytest.fixture(autouse=True)
def _reset_global_registry():
    """Bersihkan registry global & tool MCP agar tiap test terisolasi."""
    yield
    mcp_client.set_global_registry(None)
    for key in [k for k in TOOLS if k.startswith("mcp.")]:
        TOOLS.pop(key, None)


# ---------------------------------------------------------------------------
# Konfigurasi: load / save
# ---------------------------------------------------------------------------
def test_load_mcp_config_returns_empty_when_missing(tmp_path):
    cfg = load_mcp_config(str(tmp_path / "nope.json"))
    assert cfg == []


def test_save_and_load_roundtrip_stdio(tmp_path):
    path = str(tmp_path / "mcp.json")
    configs = [
        MCPServerConfig(
            name="demo",
            transport=MCPTransport.STDIO,
            command="python",
            args=["-m", "server"],
            env={"FOO": "bar"},
            cwd="/tmp",
        )
    ]
    saved = save_mcp_config(configs, path)
    assert saved == path
    loaded = load_mcp_config(path)
    assert len(loaded) == 1
    c = loaded[0]
    assert c.name == "demo"
    assert c.transport == MCPTransport.STDIO
    assert c.command == "python"
    assert c.args == ["-m", "server"]
    assert c.env == {"FOO": "bar"}
    assert c.cwd == "/tmp"
    assert c.enabled is True


def test_save_and_load_roundtrip_http(tmp_path):
    path = str(tmp_path / "mcp.json")
    configs = [
        MCPServerConfig(
            name="remote",
            transport=MCPTransport.STREAMABLE_HTTP,
            url="https://example.com/mcp",
            headers={"Authorization": "Bearer sekret"},
            enabled=False,
        )
    ]
    save_mcp_config(configs, path)
    loaded = load_mcp_config(path)
    assert len(loaded) == 1
    c = loaded[0]
    assert c.transport == MCPTransport.STREAMABLE_HTTP
    assert c.url == "https://example.com/mcp"
    assert c.headers == {"Authorization": "Bearer sekret"}
    assert c.enabled is False


def test_load_skips_unsupported_transport(tmp_path):
    path = str(tmp_path / "mcp.json")
    with open(path, "w") as f:
        json.dump({"mcpServers": {"bad": {"type": "sse", "url": "x"}}}, f)
    loaded = load_mcp_config(path)
    assert loaded == []


def test_default_path_is_under_user_config():
    assert DEFAULT_MCP_CONFIG_PATH.endswith(os.path.join(".config", "garwa", "mcp.json"))


# ---------------------------------------------------------------------------
# Konversi tool MCP -> spec TOOLS Garwa
# ---------------------------------------------------------------------------
class _FakeTool:
    def __init__(self, name, description="", input_schema=None, annotations=None):
        self.name = name
        self.description = description
        self.inputSchema = input_schema or {"type": "object", "properties": {}}
        self.annotations = annotations


def test_mcp_tool_to_spec_prefixes_name():
    tool = _FakeTool("add", description="menjumlah")
    spec = _mcp_tool_to_spec("demo", tool)
    assert spec["schema"]["name"] == "mcp.demo.add"
    assert spec["schema"]["description"] == "menjumlah"
    assert spec["destructive"] is False
    assert callable(spec["handler"])


def test_mcp_tool_to_spec_normalizes_input_schema():
    tool = _FakeTool(
        "echo",
        input_schema={"message": {"type": "string", "required": True}},
    )
    spec = _mcp_tool_to_spec("demo", tool)
    schema = spec["schema"]["inputSchema"]
    assert schema["type"] == "object"
    assert "message" in schema["properties"]
    assert schema["required"] == ["message"]


def test_mcp_tool_to_spec_destructive_flag():
    ann = types.SimpleNamespace(destructiveHint=True)
    tool = _FakeTool("wipe", annotations=ann)
    spec = _mcp_tool_to_spec("demo", tool)
    assert spec["destructive"] is True


# ---------------------------------------------------------------------------
# Registry: manajemen server tanpa koneksi nyata
# ---------------------------------------------------------------------------
def test_registry_add_remove_without_connect():
    reg = MCPToolRegistry([])
    cfg = MCPServerConfig(name="x", transport=MCPTransport.STDIO, command="true")
    assert reg.add_server(cfg, connect=False) is True
    assert reg._find_config("x") is cfg
    # duplikat ditolak
    assert reg.add_server(cfg, connect=False) is False
    assert reg.remove_server("x") is True
    assert reg._find_config("x") is None
    assert reg.remove_server("x") is False


def test_registry_set_enabled_off_disconnects_and_persists_flag():
    reg = MCPToolRegistry([])
    cfg = MCPServerConfig(name="x", transport=MCPTransport.STDIO, command="true")
    reg.add_server(cfg, connect=False)
    # off: tidak perlu koneksi
    assert reg.set_server_enabled("x", False) is True
    assert cfg.enabled is False
    # on: koneksi gagal karena mcp tidak tersedia / command tak ada -> False
    # (kita hanya pastikan flag tidak berubah bila gagal)
    assert cfg.enabled is False


# ---------------------------------------------------------------------------
# Slash-command MCP (mock bridge agar deterministik)
# ---------------------------------------------------------------------------
class _Args:
    def __init__(self, mcp_config):
        self.mcp_config = mcp_config
        self.db_path = ":memory:"
        self.workdir = "."
        self.skills_dir = None
        self.session_title = None


def _run(cmd_line, mcp_config):
    return sc.handle_slash_command(
        cmd_line, _Args(mcp_config), session_id="s1", system_content=""
    )


def _make_fake_bridge(monkeypatch):
    """Gantikan _bridge dengan stub yang selalu 'berhasil' connect & list tools.

    `run_coro` menerima coroutine sungguhan dan menutupnya (mengembalikan
    list kosong) agar tidak memicu RuntimeWarning \"coroutine never awaited\".
    """

    def run_coro(coro, timeout=60.0):
        coro.close()
        return []

    fake = types.SimpleNamespace(
        run_coro=run_coro,
        set_session=lambda name, session: None,
        get_session=lambda name: None,
        close_session=lambda name: None,
        close_all=lambda: None,
    )
    monkeypatch.setattr(mcp_client, "_bridge", fake)


def test_slash_mcp_server_add_http_persists(tmp_path, monkeypatch):
    _make_fake_bridge(monkeypatch)
    cfg_path = str(tmp_path / "mcp.json")
    res = _run("/mcp-server add remote https://example.com/mcp", cfg_path)
    assert res["action"] == "skip"
    loaded = load_mcp_config(cfg_path)
    assert len(loaded) == 1
    assert loaded[0].name == "remote"
    assert loaded[0].transport == MCPTransport.STREAMABLE_HTTP
    assert loaded[0].url == "https://example.com/mcp"


def test_slash_mcp_api_key_masks_and_persists(tmp_path, monkeypatch, capsys):
    _make_fake_bridge(monkeypatch)
    cfg_path = str(tmp_path / "mcp.json")
    _run("/mcp-server add remote https://example.com/mcp", cfg_path)
    res = _run("/mcp-api-key remote sk-super-secret-9876", cfg_path)
    assert res["action"] == "skip"
    loaded = load_mcp_config(cfg_path)
    assert loaded[0].headers["Authorization"] == "Bearer sk-super-secret-9876"
    out = capsys.readouterr().out
    assert "****9876" in out
    assert "sk-super-secret-9876" not in out


def test_slash_mcp_api_key_removes(tmp_path, monkeypatch):
    _make_fake_bridge(monkeypatch)
    cfg_path = str(tmp_path / "mcp.json")
    _run("/mcp-server add remote https://example.com/mcp", cfg_path)
    _run("/mcp-api-key remote somekey", cfg_path)
    _run("/mcp-api-key remote", cfg_path)
    loaded = load_mcp_config(cfg_path)
    assert "Authorization" not in loaded[0].headers


def test_slash_mcp_api_key_rejects_stdio(tmp_path, monkeypatch, capsys):
    _make_fake_bridge(monkeypatch)
    cfg_path = str(tmp_path / "mcp.json")
    _run("/mcp-server add demo python -m server", cfg_path)
    res = _run("/mcp-api-key demo somekey", cfg_path)
    assert res["action"] == "skip"
    out = capsys.readouterr().out
    assert "bukan HTTP" in out


def test_slash_mcp_enable_off_persists(tmp_path, monkeypatch):
    _make_fake_bridge(monkeypatch)
    cfg_path = str(tmp_path / "mcp.json")
    _run("/mcp-server add demo python -m server", cfg_path)
    _run("/mcp-enable demo off", cfg_path)
    loaded = load_mcp_config(cfg_path)
    assert loaded[0].enabled is False


def test_slash_mcp_remove_persists(tmp_path, monkeypatch):
    _make_fake_bridge(monkeypatch)
    cfg_path = str(tmp_path / "mcp.json")
    _run("/mcp-server add demo python -m server", cfg_path)
    _run("/mcp-server remove demo", cfg_path)
    loaded = load_mcp_config(cfg_path)
    assert loaded == []


def test_slash_mcp_duplicate_rejected(tmp_path, monkeypatch, capsys):
    _make_fake_bridge(monkeypatch)
    cfg_path = str(tmp_path / "mcp.json")
    _run("/mcp-server add demo python -m server", cfg_path)
    res = _run("/mcp-server add demo python -m server", cfg_path)
    assert res["action"] == "skip"
    out = capsys.readouterr().out
    assert "sudah ada" in out


def test_slash_mcp_commands_registered():
    assert "mcp-server" in sc.COMMANDS
    assert "mcp-api-key" in sc.COMMANDS
    assert "mcp-enable" in sc.COMMANDS


# ---------------------------------------------------------------------------
# Regression: bug fix
# ---------------------------------------------------------------------------
def test_save_mcp_config_without_parent_dir(tmp_path, monkeypatch):
    """save_mcp_config tidak crash saat path tidak punya komponen direktori.

    Dulu `os.makedirs(os.path.dirname(path))` memanggil `makedirs("")` yang
    melempar FileNotFoundError. Path tanpa direktori disimulasikan dengan
    monkeypatch `os.path.dirname` agar mengembalikan string kosong.
    """
    import os as _os

    monkeypatch.setattr(_os.path, "dirname", lambda p: "")
    cfg = MCPServerConfig(name="x", transport=MCPTransport.STDIO, command="true")
    # path relatif tanpa direktori; dijalankan di tmp_path (cwd test)
    monkeypatch.chdir(tmp_path)
    saved = save_mcp_config([cfg], "mcp_noparent.json")
    assert os.path.exists(saved)
    loaded = load_mcp_config(saved)
    assert len(loaded) == 1 and loaded[0].name == "x"


def test_ensure_loop_is_thread_safe(monkeypatch):
    """_ensure_loop hanya boleh membuat satu loop meski dipanggil concurrent.

    _bridge._lock menjamin inisialisasi loop terjadi sekali saja. Banyak
    thread memanggil _ensure_loop serentak; hasil harus loop yang sama dan
    _thread dibuat tepat satu kali.
    """
    import threading

    bridge = mcp_client._MCPBridge()
    created = []
    _orig_new_event_loop = asyncio.new_event_loop

    def make_loop():
        loop = _orig_new_event_loop()
        created.append(loop)
        return loop

    monkeypatch.setattr(asyncio, "new_event_loop", make_loop)

    results = []

    def worker():
        results.append(bridge._ensure_loop())

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Semua thread mendapatkan loop yang sama, loop dibuat tepat satu kali.
    assert len(set(id(r) for r in results)) == 1
    assert len(created) == 1
    assert bridge._loop is not None
    assert bridge._thread is not None
    assert bridge._thread.is_alive()
