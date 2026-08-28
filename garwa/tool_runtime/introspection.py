"""tool_runtime/introspection.py
Dipecah otomatis dari tool_runtime.py (lihat _shared.py untuk konstanta bersama).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple
from . import _shared as shared


def parse_argument_description(description: str) -> Dict[str, Any]:
    """Parse deskripsi argumen string menjadi dict skema terstruktur.

    Mengembalikan dict dengan keys: type, description, required, default
    (default hanya disertakan bila ada). Meniru opencode yang punya skema
    eksplisit per argumen.

    Tahan-banting: bila `description` sudah berupa dict (format JSON-Schema
    / inputSchema), dikembalikan apa adanya tanpa parsing teks.
    """
    if isinstance(description, dict):
        return dict(description)

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


def _schema_to_legacy(schema: Dict[str, Any]) -> str:
    """Konversi satu argumen JSON-Schema (dict) menjadi string deskriptif.

    Dipakai oleh cli/tool_schema/schema_text.py (mode full) untuk menulis
    deskripsi argumen sebagai teks di system prompt. Sumber kebenaran adalah
    `inputSchema` (JSON-Schema); fungsi ini hanya memformatnya ke teks.

    Format output: "<tipe> (wajib/opsional, default X) - deskripsi".
    """
    type_name = schema.get("type", "any")
    if isinstance(type_name, list):  # union type, ambil yang pertama
        type_name = type_name[0] if type_name else "any"

    meta_parts: List[str] = []
    if schema.get("required"):
        meta_parts.append("wajib")
    else:
        meta_parts.append("opsional")
    if "default" in schema:
        meta_parts.append(f"default {schema['default']}")

    desc = schema.get("description", "").strip()
    meta = ", ".join(meta_parts)
    if meta and desc:
        return f"{type_name} ({meta}) - {desc}"
    if meta:
        return f"{type_name} ({meta})"
    return f"{type_name} - {desc}" if desc else type_name


def _resolve_schema(schema: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Normalisasi definisi argumen dari schema menjadi (properties, required).

    Sumber kebenaran kanonik adalah `schema["inputSchema"]` berformat
    **JSON-Schema penuh**:
        {"type": "object", "properties": {name: {JSON-Schema}}, "required": [...]}

    Fallback untuk transisi:
      - `inputSchema` format flat lama: {name: {type, required, description}}
      - `arguments` legacy: {name: "string deskriptif"} (di-parse via
        parse_argument_description).

    Nilai setiap property selalu berupa dict JSON-Schema (berisi setidaknya
    `type` dan `description`; plus `default`/`minimum`/`maximum`/`enum`/
    `items` bila ada di sumber). `required` selalu berupa list nama argumen.

    Returns:
        (properties: Dict[str, Dict], required: List[str])
    """
    if schema.get("inputSchema"):
        ins = schema["inputSchema"]
        # Format penuh (kanonik): punya key "type" level-atas bernilai "object".
        if isinstance(ins, dict) and ins.get("type") == "object":
            props = ins.get("properties", {}) or {}
            req = ins.get("required", []) or []
            return props, list(req)
        # Format flat lama: {name: {...}} tanpa "type" level-atas.
        if isinstance(ins, dict):
            props = dict(ins)
            req = [n for n, p in props.items() if isinstance(p, dict) and p.get("required")]
            return props, req

    # Fallback: arguments legacy berupa string deskriptif.
    props: Dict[str, Any] = {}
    req: List[str] = []
    for name, argdesc in (schema.get("arguments") or {}).items():
        parsed = parse_argument_description(argdesc)
        prop: Dict[str, Any] = {"type": parsed["type"], "description": parsed["description"]}
        if "default" in parsed:
            prop["default"] = parsed["default"]
        props[name] = prop
        if parsed.get("required"):
            req.append(name)
    return props, req


def _resolve_arguments(schema: Dict[str, Any]) -> Dict[str, Any]:
    """(Deprecated) Ambil dict property {name: JSON-Schema} dari schema.

    Dipertahankan agar pemanggil lama tetap berfungsi. Untuk kebutuhan
    `required`, gunakan `_resolve_schema(schema)` yang mengembalikan
    (properties, required).
    """
    props, _ = _resolve_schema(schema)
    return props


def build_openai_tools_payload(tools: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Bangun field 'tools' ala OpenAI function-calling dengan tipe AKURAT.

    Menggantikan build_openai_tools_payload() lama di cli.py yang memberi
    type "string" untuk semua argumen. Sekarang tipe diekstrak dari
    `inputSchema` (JSON-Schema kanonik) atau dari deskripsi argumen
    (string/integer/boolean/array/object) sehingga model tahu bentuk argumen
    yang benar. Constraint JSON-Schema (default/minimum/maximum/enum/items)
    ikut diteruskan agar model menghasilkan argumen yang valid.

    Args:
        tools: dict TOOLS dari tools.py ({nama: {schema: {...}}}).
    """
    tools_payload = []
    for name, spec in tools.items():
        s = spec["schema"]
        properties, required = _resolve_schema(s)
        props_out: Dict[str, Any] = {}
        for argname, prop in properties.items():
            if not isinstance(prop, dict):
                prop = parse_argument_description(str(prop))
            out: Dict[str, Any] = {
                "type": prop.get("type", "string"),
                "description": prop.get("description", ""),
            }
            for key in ("default", "minimum", "maximum", "enum", "items", "format", "pattern"):
                if key in prop:
                    out[key] = prop[key]
            props_out[argname] = out
        tools_payload.append({
            "type": "function",
            "function": {
                "name": name,
                "description": s["description"],
                "parameters": {
                    "type": "object",
                    "properties": props_out,
                    "required": required,
                },
            },
        })
    return tools_payload
