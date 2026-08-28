"""garwa/mcp/client.py

Klien MCP untuk Garwa -- menghubungkan Garwa (sebagai MCP client) ke MCP
server eksternal dan mengekspos tool-toolnya sebagai tool Garwa biasa.

Desain:
  - Mesin eksekusi tool Garwa (`execute_tool` / `run_tool_with_runtime`)
    TIDAK diubah. Tool MCP didaftarkan ke `TOOLS` global dengan nama
    ber-prefix `mcp.<server>.<tool>` dan handler yang membungkus pemanggilan
    `ClientSession.call_tool`.
  - Seluruh operasi SDK MCP bersifat async. Karena pipeline CLI Garwa
    sinkron, modul ini menjalankan satu event loop di thread daemon dan
    mem-bridge panggilan sync -> async lewat
    `asyncio.run_coroutine_threadsafe(...).result()`.
  - Session MCP bersifat persisten selama proses CLI hidup; ditutup saat
    shutdown (lihat `close_all`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("garwa.mcp")

# ---------------------------------------------------------------------------
# Import opsional SDK MCP. Kalau tidak terinstall, CLI tetap berjalan tanpa
# tool MCP (fallback otomatis). `mcp_available` memberi tahu pemanggil.
# ---------------------------------------------------------------------------
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamable_http_client

    _MCP_IMPORT_ERROR: Optional[str] = None
except Exception as _e:  # noqa: BLE001
    _MCP_IMPORT_ERROR = f"{type(_e).__name__}: {_e}"
    ClientSession = None  # type: ignore
    StdioServerParameters = None  # type: ignore
    stdio_client = None  # type: ignore
    streamable_http_client = None  # type: ignore


mcp_import_error = _MCP_IMPORT_ERROR


def mcp_available() -> bool:
    """True kalau SDK MCP berhasil diimpor."""
    return _MCP_IMPORT_ERROR is None


# ---------------------------------------------------------------------------
# Konfigurasi
# ---------------------------------------------------------------------------
class MCPTransport:
    """Transport MCP yang didukung."""

    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


@dataclass
class MCPServerConfig:
    """Konfigurasi satu MCP server.

    Format ini sengaja dibuat mirip blok `mcpServers` Claude Desktop agar
    file konfigurasi mudah dipahami dan bisa dipakai ulang.
    """

    name: str
    transport: str = MCPTransport.STDIO
    command: Optional[str] = None          # stdio: perintah untuk dijalankan
    args: List[str] = field(default_factory=list)  # stdio: argumen perintah
    env: Dict[str, str] = field(default_factory=dict)  # stdio: env tambahan
    cwd: Optional[str] = None              # stdio: working directory
    url: Optional[str] = None              # streamable_http: endpoint URL
    headers: Dict[str, str] = field(default_factory=dict)  # streamable_http: header HTTP
    enabled: bool = True

    @property
    def display_name(self) -> str:
        return self.name

    def to_stdlib_params(self) -> "StdioServerParameters":
        """Bangun StdioServerParameters untuk transport stdio."""
        if StdioServerParameters is None:
            raise RuntimeError("SDK MCP tidak terinstall (mcp>=2.0).")
        env = dict(os.environ)
        env.update(self.env)
        return StdioServerParameters(
            command=self.command,
            args=list(self.args),
            env=env,
            cwd=self.cwd,
        )


# ---------------------------------------------------------------------------
# Loader konfigurasi
# ---------------------------------------------------------------------------
DEFAULT_MCP_CONFIG_PATH = os.path.join(
    os.path.expanduser("~"), ".config", "garwa", "mcp.json"
)


def load_mcp_config(path: Optional[str] = None) -> List[MCPServerConfig]:
    """Baca file konfigurasi MCP dan kembalikan daftar server.

    Format file (JSON), mirip `mcpServers` Claude Desktop::

        {
          "mcpServers": {
            "filesystem": {
              "command": "npx",
              "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
              "env": {"FOO": "bar"}
            },
            "weather": {
              "type": "streamable_http",
              "url": "https://example.com/mcp"
            }
          }
        }

    Setiap entry bisa memakai key tambahan: `transport` ("stdio" default /
    "streamable_http"), `cwd`, `headers`, `enabled`. Bila `path` tidak
    diberikan, dipakai `~/.config/garwa/mcp.json`; bila file itu tidak ada,
    dikembalikan daftar kosong.
    """
    if path is None:
        path = DEFAULT_MCP_CONFIG_PATH

    if not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Gagal membaca konfigurasi MCP %s: %s", path, e)
        return []

    servers = data.get("mcpServers", data) if isinstance(data, dict) else {}
    if not isinstance(servers, dict):
        return []

    configs: List[MCPServerConfig] = []
    for name, raw in servers.items():
        if not isinstance(raw, dict):
            continue
        transport = raw.get("transport") or raw.get("type") or MCPTransport.STDIO
        if transport not in (MCPTransport.STDIO, MCPTransport.STREAMABLE_HTTP):
            logger.warning("Server MCP '%s': transport '%s' tidak didukung, dilewati.", name, transport)
            continue
        cfg = MCPServerConfig(
            name=name,
            transport=transport,
            command=raw.get("command"),
            args=list(raw.get("args") or []),
            env=dict(raw.get("env") or {}),
            cwd=raw.get("cwd"),
            url=raw.get("url"),
            headers=dict(raw.get("headers") or {}),
            enabled=bool(raw.get("enabled", True)),
        )
        configs.append(cfg)
    return configs


def save_mcp_config(configs: List[MCPServerConfig], path: Optional[str] = None) -> str:
    """Tulis daftar server MCP ke file konfigurasi JSON (format mcpServers).

    Dipakai slash-command `/mcp-server` dkk. untuk mempersist perubahan
    on-the-fly lintas sesi. Mengembalikan path file yang ditulis.
    """
    if path is None:
        path = DEFAULT_MCP_CONFIG_PATH

    servers: Dict[str, Any] = {}
    for cfg in configs:
        entry: Dict[str, Any] = {"enabled": cfg.enabled}
        if cfg.transport == MCPTransport.STDIO:
            entry["command"] = cfg.command
            if cfg.args:
                entry["args"] = list(cfg.args)
            if cfg.env:
                entry["env"] = dict(cfg.env)
            if cfg.cwd:
                entry["cwd"] = cfg.cwd
        else:
            entry["type"] = MCPTransport.STREAMABLE_HTTP
            if cfg.url:
                entry["url"] = cfg.url
            if cfg.headers:
                entry["headers"] = dict(cfg.headers)
        servers[cfg.name] = entry

    payload = {"mcpServers": servers}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


# ---------------------------------------------------------------------------
# Konversi schema MCP -> format TOOLS Garwa
# ---------------------------------------------------------------------------
def _destructive_from_annotations(annotations: Any) -> bool:
    """Ekstrak flag destructive dari `Tool.annotations` MCP.

    `annotations.destructiveHint` (default False). Bila annotations None
    atau field tidak tersedia, dianggap tidak destruktif.
    """
    if annotations is None:
        return False
    try:
        return bool(getattr(annotations, "destructiveHint", False))
    except Exception:  # noqa: BLE001
        return False


def _mcp_tool_to_spec(server_name: str, tool: Any) -> Dict[str, Any]:
    """Konversi satu `Tool` MCP menjadi spec TOOLS Garwa.

    Spec berisi `schema` (name/description/inputSchema) dan `handler` yang
    membungkus pemanggilan `call_tool`. Nama tool Garwa diberi prefix
    `mcp.<server>.<tool>` agar tidak bentrok dengan tool bawaan.
    """
    tool_name = getattr(tool, "name", None) or "unnamed"
    full_name = f"mcp.{server_name}.{tool_name}"

    description = getattr(tool, "description", "") or ""
    input_schema = getattr(tool, "inputSchema", None) or {"type": "object", "properties": {}}

    # Normalisasi: pastikan inputSchema punya bentuk JSON-Schema penuh.
    if isinstance(input_schema, dict) and input_schema.get("type") != "object":
        # Beberapa server mengirim {name: {schema}} tanpa "type":"object" level-atas.
        input_schema = {
            "type": "object",
            "properties": input_schema,
            "required": [
                n for n, p in input_schema.items()
                if isinstance(p, dict) and p.get("required")
            ],
        }

    schema = {
        "name": full_name,
        "description": description,
        "inputSchema": input_schema,
    }

    destructive = _destructive_from_annotations(getattr(tool, "annotations", None))

    return {
        "schema": schema,
        "destructive": destructive,
        "handler": _make_mcp_handler(server_name, tool_name),
    }


def _make_mcp_handler(server_name: str, tool_name: str) -> Callable[..., str]:
    """Buat handler sinkron yang memanggil tool MCP via bridge async.

    Handler menerima `**kwargs` (argumen tool yang sudah divalidasi Garwa)
    lalu meneruskan ke `ClientSession.call_tool`. Hasil `CallToolResult`
    dirangkai menjadi string teks (konten teks digabung; blok non-teks
    diserialisasi sebagai JSON).
    """
    def handler(**kwargs: Any) -> str:
        registry = _get_global_registry()
        return registry.call_tool_sync(server_name, tool_name, kwargs)

    return handler


# ---------------------------------------------------------------------------
# Bridge sync <-> async + registry global
# ---------------------------------------------------------------------------
class _MCPSession:
    """Satu sesi MCP yang persisten beserta sumber daya transportnya.

    Mencakup context manager transport (stdio/http), read/write stream, dan
    `ClientSession`. Context manager DAN stream disimpan sebagai atribut agar
    tidak di-GC -- kalau context manager transport (yang mengelola task group
    dan proses server) hilang, `aclose()` akan menutup stream/proses dan
    membuat pemanggilan berikutnya gagal dengan BrokenResourceError.
    """

    def __init__(
        self,
        cm: Any,
        read_stream: Any,
        write_stream: Any,
        session: ClientSession,
    ) -> None:
        self.cm = cm
        self.read_stream = read_stream
        self.write_stream = write_stream
        self.session = session

    async def close(self) -> None:
        """Tutup session lalu context manager transport (best-effort)."""
        try:
            await self.session.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass
        try:
            await self.cm.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass


class _MCPBridge:
    """Satu event loop di thread daemon + jembatan sync<->async.

    Menampung session MCP yang persisten per server dan mengeksekusi
    coroutine dari thread lain via `asyncio.run_coroutine_threadsafe`.
    """

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._sessions: Dict[str, _MCPSession] = {}
        self._lock = threading.Lock()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None and self._loop.is_running():
            return self._loop
        loop = asyncio.new_event_loop()
        self._loop = loop
        self._thread = threading.Thread(
            target=self._run_loop, args=(loop,), name="garwa-mcp-loop", daemon=True
        )
        self._thread.start()
        return loop

    def _run_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def run_coro(self, coro: Any, timeout: float = 60.0) -> Any:
        """Jalankan coroutine di loop thread daemon, tunggu hasilnya (sync)."""
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)

    def get_session(self, server_name: str) -> Optional[_MCPSession]:
        with self._lock:
            return self._sessions.get(server_name)

    def set_session(self, server_name: str, session: _MCPSession) -> None:
        with self._lock:
            self._sessions[server_name] = session

    def close_session(self, server_name: str) -> None:
        """Tutup satu session MCP (best-effort) dan hapus dari map."""
        with self._lock:
            session = self._sessions.pop(server_name, None)
        if session is not None and self._loop is not None:
            try:
                self.run_coro(session.close(), timeout=10.0)
            except Exception:  # noqa: BLE001
                pass

    def close_all(self) -> None:
        """Tutup semua session MCP dan hentikan loop (best-effort)."""
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        if sessions and self._loop is not None:
            async def _close():
                for s in sessions:
                    try:
                        await s.close()
                    except Exception:  # noqa: BLE001
                        pass
            try:
                self.run_coro(_close(), timeout=10.0)
            except Exception:  # noqa: BLE001
                pass
        if self._loop is not None and self._thread is not None:
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:  # noqa: BLE001
                pass


_bridge = _MCPBridge()


def _get_global_registry() -> "MCPToolRegistry":
    """Akses registry global (di-set saat startup CLI)."""
    reg = getattr(_get_global_registry, "_registry", None)
    if reg is None:
        raise RuntimeError("MCPToolRegistry belum diinisialisasi.")
    return reg


def get_global_registry() -> Optional["MCPToolRegistry"]:
    """Akses registry global dengan aman; None bila MCP belum aktif.

    Dipakai slash-command `/mcp-*` untuk memanipulasi server on-the-fly
    tanpa harus tahu apakah MCP sudah diinisialisasi.
    """
    return getattr(_get_global_registry, "_registry", None)


class MCPToolRegistry:
    """Registry tool MCP: koneksi ke server + daftar tool eksternal.

    Setelah `connect_all()` dan `list_tools()`, hasilnya berupa dict
    {nama_tool_garwa: spec} yang bisa di-`update` ke `TOOLS` global.
    """

    def __init__(self, configs: List[MCPServerConfig]) -> None:
        self.configs = configs
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._server_tool_names: Dict[str, List[str]] = {}
        self._connected: List[str] = []

    # -- koneksi ----------------------------------------------------------
    async def _connect_stdio(self, cfg: MCPServerConfig) -> _MCPSession:
        params = cfg.to_stdlib_params()
        cm = stdio_client(params)
        read_stream, write_stream = await cm.__aenter__()
        session = ClientSession(read_stream, write_stream)
        await session.__aenter__()
        await session.initialize()
        return _MCPSession(cm, read_stream, write_stream, session)

    async def _connect_http(self, cfg: MCPServerConfig) -> _MCPSession:
        # streamable_http_client tidak menerima argumen `headers`; header harus
        # dibawa lewat httpx.AsyncClient yang diteruskan sebagai `http_client`.
        http_client = None
        if cfg.headers:
            try:
                import httpx

                http_client = httpx.AsyncClient(headers=cfg.headers)
            except Exception as e:  # noqa: BLE001
                logger.warning("Gagal membuat httpx.AsyncClient untuk '%s': %s", cfg.name, e)
        cm = streamable_http_client(cfg.url, http_client=http_client)
        read_stream, write_stream, _get_session_id = await cm.__aenter__()
        session = ClientSession(read_stream, write_stream)
        await session.__aenter__()
        await session.initialize()
        return _MCPSession(cm, read_stream, write_stream, session)

    def connect_all(self, timeout: float = 30.0) -> None:
        """Sambungkan ke semua server yang enabled. Server gagal dilewati."""
        if not mcp_available():
            logger.warning("SDK MCP tidak terinstall (%s). Tool MCP dinonaktifkan.", mcp_import_error)
            return
        for cfg in self.configs:
            if not cfg.enabled:
                continue
            try:
                if cfg.transport == MCPTransport.STDIO:
                    session = _bridge.run_coro(self._connect_stdio(cfg), timeout=timeout)
                else:
                    session = _bridge.run_coro(self._connect_http(cfg), timeout=timeout)
                _bridge.set_session(cfg.name, session)
                self._connected.append(cfg.name)
                logger.info("MCP server '%s' terhubung (%s).", cfg.name, cfg.transport)
            except Exception as e:  # noqa: BLE001
                logger.warning("Gagal terhubung ke MCP server '%s': %s", cfg.name, e)

    # -- manajemen server on-the-fly (dipakai slash-command /mcp-*) --------
    def _find_config(self, name: str) -> Optional[MCPServerConfig]:
        for cfg in self.configs:
            if cfg.name == name:
                return cfg
        return None

    def connect_server(self, name: str, timeout: float = 30.0) -> bool:
        """Sambungkan (ulang) satu server dan muat ulang tool-nya.

        Server harus sudah ada di `self.configs`. Dipakai saat user
        menambah server baru atau men-toggle enabled dari off -> on.
        """
        cfg = self._find_config(name)
        if cfg is None:
            return False
        if not mcp_available():
            return False
        if cfg.name not in self._connected:
            try:
                if cfg.transport == MCPTransport.STDIO:
                    session = _bridge.run_coro(self._connect_stdio(cfg), timeout=timeout)
                else:
                    session = _bridge.run_coro(self._connect_http(cfg), timeout=timeout)
                _bridge.set_session(cfg.name, session)
                self._connected.append(cfg.name)
                logger.info("MCP server '%s' terhubung (%s).", cfg.name, cfg.transport)
            except Exception as e:  # noqa: BLE001
                logger.warning("Gagal terhubung ke MCP server '%s': %s", cfg.name, e)
                return False
        return self._load_server_tools(cfg, timeout=timeout)

    def _load_server_tools(self, cfg: MCPServerConfig, timeout: float = 30.0) -> bool:
        """Ambil daftar tool satu server dan update `self._tools` + TOOLS global."""
        if cfg.name not in self._connected:
            return False
        try:
            tools = _bridge.run_coro(self._list_tools_async(cfg), timeout=timeout)
        except Exception as e:  # noqa: BLE001
            logger.warning("Gagal list_tools dari MCP server '%s': %s", cfg.name, e)
            return False
        # Hapus tool lama dari server ini, lalu daftarkan ulang.
        for full_name in self._server_tool_names.get(cfg.name, []):
            self._tools.pop(full_name, None)
        names = []
        for t in tools:
            spec = _mcp_tool_to_spec(cfg.name, t)
            full_name = spec["schema"]["name"]
            self._tools[full_name] = spec
            names.append(full_name)
        self._server_tool_names[cfg.name] = names
        return True

    def disconnect_server(self, name: str) -> bool:
        """Tutup koneksi & hapus tool server dari registry (tanpa hapus config)."""
        cfg = self._find_config(name)
        if cfg is None:
            return False
        _bridge.close_session(cfg.name)
        if cfg.name in self._connected:
            self._connected.remove(cfg.name)
        for full_name in self._server_tool_names.get(cfg.name, []):
            self._tools.pop(full_name, None)
        self._server_tool_names[cfg.name] = []
        return True

    def add_server(self, config: MCPServerConfig, connect: bool = True) -> bool:
        """Tambah server baru ke daftar config. Bila `connect`, langsung sambungkan."""
        if self._find_config(config.name) is not None:
            return False
        self.configs.append(config)
        if not connect:
            return True
        return self.connect_server(config.name)

    def remove_server(self, name: str) -> bool:
        """Hapus server dari config + tutup koneksi + buang tool-nya."""
        cfg = self._find_config(name)
        if cfg is None:
            return False
        self.disconnect_server(name)
        self.configs = [c for c in self.configs if c.name != name]
        return True

    def set_server_enabled(self, name: str, enabled: bool, timeout: float = 30.0) -> bool:
        """Ubah flag `enabled` server. On -> sambungkan; Off -> putuskan."""
        cfg = self._find_config(name)
        if cfg is None:
            return False
        cfg.enabled = enabled
        if enabled:
            return self.connect_server(name, timeout=timeout)
        self.disconnect_server(name)
        return True

    # -- daftar tool ------------------------------------------------------
    async def _list_tools_async(self, cfg: MCPServerConfig) -> List[Any]:
        mcp_session = _bridge.get_session(cfg.name)
        if mcp_session is None:
            return []
        result = await mcp_session.session.list_tools()
        return list(result.tools)

    def list_tools(self, timeout: float = 30.0) -> Dict[str, Dict[str, Any]]:
        """Ambil daftar tool dari semua server dan bangun spec TOOLS Garwa."""
        self._tools = {}
        for cfg in self.configs:
            if cfg.name not in self._connected:
                continue
            try:
                tools = _bridge.run_coro(self._list_tools_async(cfg), timeout=timeout)
            except Exception as e:  # noqa: BLE001
                logger.warning("Gagal list_tools dari MCP server '%s': %s", cfg.name, e)
                continue
            names = []
            for t in tools:
                spec = _mcp_tool_to_spec(cfg.name, t)
                full_name = spec["schema"]["name"]
                self._tools[full_name] = spec
                names.append(full_name)
            self._server_tool_names[cfg.name] = names
        return self._tools

    # -- pemanggilan (dipakai handler) ------------------------------------
    async def _call_tool_async(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> str:
        mcp_session = _bridge.get_session(server_name)
        if mcp_session is None:
            return f"[ERROR] MCP server '{server_name}' tidak terhubung."
        result = await mcp_session.session.call_tool(tool_name, arguments)
        return _format_call_tool_result(result)

    def call_tool_sync(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> str:
        try:
            return _bridge.run_coro(
                self._call_tool_async(server_name, tool_name, arguments), timeout=120.0
            )
        except Exception as e:  # noqa: BLE001
            return f"[ERROR] Panggilan tool MCP '{server_name}.{tool_name}' gagal: {e}"

    # -- utilitas ----------------------------------------------------------
    def tool_count(self) -> int:
        return len(self._tools)

    def close_all(self) -> None:
        _bridge.close_all()


def _format_call_tool_result(result: Any) -> str:
    """Rangkai CallToolResult menjadi string teks untuk model."""
    parts: List[str] = []
    for block in getattr(result, "content", []) or []:
        block_type = getattr(block, "type", "")
        if block_type == "text":
            text = getattr(block, "text", "")
            if text:
                parts.append(text)
        else:
            # Blok non-teks (image, resource, dll): serialisasi best-effort.
            try:
                parts.append(json.dumps(block.model_dump(), ensure_ascii=False))
            except Exception:  # noqa: BLE001
                parts.append(str(block))
    if not parts:
        parts.append("(tool MCP tidak mengembalikan konten teks)")
    if getattr(result, "isError", False):
        return "[MCP ERROR]\n" + "\n".join(parts)
    return "\n".join(parts)


# Registry global (di-set saat startup CLI oleh main.py).
def set_global_registry(registry: MCPToolRegistry) -> None:
    _get_global_registry._registry = registry  # type: ignore[attr-defined]
