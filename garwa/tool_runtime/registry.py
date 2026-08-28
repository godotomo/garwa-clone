"""tool_runtime/registry.py
Dipecah otomatis dari tool_runtime.py (lihat _shared.py untuk konstanta bersama).
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple
from . import _shared as shared



class ToolRegistry:
    """Registry tool yang mendukung namespace hierarkis + pencarian.

    TOOLS di tools.py tetap flat (agar tidak merusak pipeline lama), tapi
    registry ini menambahkan lapisan namespace di atasnya: tool bisa
    diakses lewat path bertitik (mis. "fs.read_file") dan dicari lewat
    query teks dengan budget/limit.

    Namespace dipetakan lewat register_namespace(), mis.:
        registry.register_namespace("fs", {"read": "read_file", "write": "write_file"})
    sehingga "fs.read" -> "read_file".
    """

    def __init__(self) -> None:

        self._aliases: Dict[str, str] = {}

        self._descriptions: Dict[str, str] = {}

    def register_namespace(self, namespace: str, mapping: Dict[str, str]) -> None:
        """Daftarkan alias namespace ke nama tool flat.

        Args:
            namespace: prefix namespace, mis. "fs".
            mapping: {subpath: nama_tool_flat}, mis. {"read": "read_file"}.
        """
        for subpath, tool_name in mapping.items():
            full_path = f"{namespace}.{subpath}" if namespace else subpath
            self._aliases[full_path] = tool_name

    def register_tool(self, name: str, description: str) -> None:
        """Daftarkan deskripsi tool flat untuk pencarian."""
        self._descriptions[name] = description

    def clear(self) -> None:
        """Kosongkan semua alias & deskripsi (dipakai saat rebuild registry)."""
        self._aliases.clear()
        self._descriptions.clear()

    def resolve(self, name: str) -> str:
        """Resolve nama (bisa path namespace) ke nama tool flat.

        Mengembalikan nama tool flat, atau None kalau tidak dikenal.
        """
        if name in self._aliases:
            return self._aliases[name]
        return name

    def search(
        self,
        query: str = "",
        namespace: str = "",
        limit: int = shared.DEFAULT_SEARCH_LIMIT,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Cari tool berdasarkan query teks (ala opencode SearchOutput).

        Returns:
            dict dengan keys: items (list {path, description, signature}),
            remaining (int), next (dict {offset} | None).
        """
        if limit < 1:
            limit = shared.DEFAULT_SEARCH_LIMIT
        if offset < 0:
            offset = 0

        q = query.strip().lower()
        ns_prefix = f"{namespace}." if namespace else ""

        paths: Dict[str, str] = {}
        for alias, tool_name in self._aliases.items():
            if namespace and not alias.startswith(ns_prefix):
                continue
            paths[alias] = tool_name
        for name in self._descriptions:
            if namespace and not name.startswith(ns_prefix):
                continue
            paths.setdefault(name, name)

        matched: List[Tuple[str, str]] = []
        for path, tool_name in paths.items():
            desc = self._descriptions.get(tool_name, "")
            haystack = f"{path} {desc}".lower()
            if not q or q in haystack:
                matched.append((path, tool_name))

        matched.sort(key=lambda p: (q not in p[0], p[0]))

        total = len(matched)
        items = []
        for path, tool_name in matched[offset:offset + limit]:
            desc = self._descriptions.get(tool_name, "")
            items.append({
                "path": path,
                "description": desc,
                "signature": _signature_for(tool_name),
            })

        remaining = max(0, total - (offset + len(items)))
        next_offset = offset + len(items) if remaining > 0 else None

        return {
            "items": items,
            "remaining": remaining,
            "next": {"offset": next_offset} if next_offset is not None else None,
        }


def _signature_for(tool_name: str) -> str:
    """Bangun signature ringkas untuk tool (ala opencode signature)."""

    sig = shared._SIGNATURES.get(tool_name)
    if sig is not None:
        return sig
    return f"{tool_name}(...)"


def register_signature(tool_name: str, signature: str) -> None:
    """Daftarkan signature tool untuk pencarian/katalog."""
    shared._SIGNATURES[tool_name] = signature


def clear_signatures() -> None:
    """Kosongkan semua signature (dipakai saat rebuild registry)."""
    shared._SIGNATURES.clear()


REGISTRY = ToolRegistry()
