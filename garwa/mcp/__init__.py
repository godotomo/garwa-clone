"""garwa/mcp/__init__.py

Integrasi MCP (Model Context Protocol): Garwa bertindak sebagai **MCP client**
yang mengonsumsi tools dari MCP server eksternal (stdio / streamable_http).

Alur:
  1. `load_mcp_config(path)` membaca file konfigurasi (format mirip blok
     `mcpServers` Claude Desktop) dan mengembalikan daftar `MCPServerConfig`.
  2. `MCPToolRegistry` menyambungkan ke tiap server, mengambil daftar tool
     (`list_tools`), lalu mengonversi schema MCP ke format TOOLS Garwa
     (prefix `mcp.<server>.<tool>`).
  3. Tool MCP didaftarkan ke `TOOLS` global saat startup CLI (lihat
     `garwa/cli/main.py`), sehingga mesin eksekusi tool Garwa yang sudah ada
     (`execute_tool` / `run_tool_with_runtime`) tidak perlu diubah.

Seluruh operasi SDK MCP bersifat async; modul ini menyediakan jembatan
sync<->async (satu event loop di thread daemon + `asyncio.run_coroutine_threadsafe`)
agar bisa dipanggil dari pipeline CLI yang sinkron.
"""
from .client import (
    DEFAULT_MCP_CONFIG_PATH,
    MCPServerConfig,
    MCPTransport,
    MCPToolRegistry,
    load_mcp_config,
    save_mcp_config,
    get_global_registry,
    set_global_registry,
    mcp_available,
    mcp_import_error,
)

__all__ = [
    "DEFAULT_MCP_CONFIG_PATH",
    "MCPServerConfig",
    "MCPTransport",
    "MCPToolRegistry",
    "load_mcp_config",
    "save_mcp_config",
    "get_global_registry",
    "set_global_registry",
    "mcp_available",
    "mcp_import_error",
]
