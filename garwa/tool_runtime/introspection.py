"""tool_runtime/introspection.py
Dipecah otomatis dari tool_runtime.py (lihat _shared.py untuk konstanta bersama).
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from . import _shared as shared


def parse_argument_description(description: str) -> Dict[str, Any]:
    """Parse deskripsi argumen string menjadi dict skema terstruktur.

    Mengembalikan dict dengan keys: type, description, required, default
    (default hanya disertakan bila ada). Meniru opencode yang punya skema
    eksplisit per argumen.
    """
    m = shared._TYPE_RE.match(description)
    result: Dict[str, Any] = {"type": "string", "description": description.strip()}
    if not m:
        return result

    raw_type = m.group(1).strip().lower()
    result["type"] = shared._TYPE_MAP.get(raw_type, "string")

    meta = m.group(2) or ""
    result["description"] = m.group(3).strip() or description.strip()

    if "wajib" in meta or "required" in meta:
        result["required"] = True
    else:
        result["required"] = False

    dm = re.search(r"default\s+([^,)]+)", meta)
    if dm:
        raw_default = dm.group(1).strip()
        result["default"] = _coerce_default(raw_default, result["type"])

    return result


def _coerce_default(raw: str, type_name: str) -> Any:
    """Koersi string default ke tipe Python sesuai type JSON Schema."""
    raw = raw.strip().strip("'\"")
    if type_name == "integer":
        try:
            return int(raw)
        except ValueError:
            return raw
    if type_name == "number":
        try:
            return float(raw)
        except ValueError:
            return raw
    if type_name == "boolean":
        if raw.lower() in ("true", "1", "yes"):
            return True
        if raw.lower() in ("false", "0", "no"):
            return False
        return raw
    return raw


def build_openai_tools_payload(tools: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Bangun field 'tools' ala OpenAI function-calling dengan tipe AKURAT.

    Menggantikan build_openai_tools_payload() lama di cli.py yang memberi
    type "string" untuk semua argumen. Sekarang tipe diekstrak dari
    deskripsi argumen (string/integer/boolean/array/object) sehingga model
    tahu bentuk argumen yang benar.

    Args:
        tools: dict TOOLS dari tools.py ({nama: {schema: {...}}}).
    """
    tools_payload = []
    for name, spec in tools.items():
        s = spec["schema"]
        properties: Dict[str, Any] = {}
        required: List[str] = []
        for argname, argdesc in s["arguments"].items():
            parsed = parse_argument_description(argdesc)
            prop: Dict[str, Any] = {"type": parsed["type"], "description": parsed["description"]}
            if "default" in parsed:
                prop["default"] = parsed["default"]
            properties[argname] = prop
            if parsed.get("required"):
                required.append(argname)
        tools_payload.append({
            "type": "function",
            "function": {
                "name": name,
                "description": s["description"],
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        })
    return tools_payload
