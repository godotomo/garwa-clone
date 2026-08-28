"""cli/tool_schema/native_calls.py
Dipecah lebih lanjut dari cli/tool_schema.py.
"""
import json

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from .. import _state as state
from ..json_repair import _repair_invalid_json_escapes
from ..json_repair import _repair_single_quoted_json
from ..json_repair import _repair_unquoted_json_keys
from ..json_repair import _repair_unquoted_json_values


def _native_tool_call_to_block(tool_call: dict) -> str:
    """Ubah SATU entri tool_calls terstruktur (format native OpenAI:
    {"function": {"name": ..., "arguments": "<json string atau dict>"}})
    jadi blok teks "<tool_call>{...}</tool_call>" standar, supaya seluruh
    pipeline lama (extract_tool_call(), TOOL_CALL_RE, dst.) tetap berlaku
    tanpa diubah sama sekali. Selalu berhasil (tidak raise) -- kalau
    'arguments' ternyata bukan JSON valid, diteruskan apa adanya di bawah
    key "_raw" supaya errornya kelihatan jelas di <tool_result> alih-alih
    diam-diam hilang.
    """
    func = tool_call.get("function") or {}
    name = func.get("name") or ""
    raw_args = func.get("arguments")
    if isinstance(raw_args, dict):
        arguments = raw_args
    elif isinstance(raw_args, str) and raw_args.strip():
        try:
            arguments = json.loads(raw_args)
        except json.JSONDecodeError:

            candidates = [raw_args]
            for cand in (
                _repair_invalid_json_escapes(raw_args),
                _repair_unquoted_json_keys(raw_args),
                _repair_single_quoted_json(raw_args),
                _repair_unquoted_json_values(raw_args),
                _repair_unquoted_json_values(_repair_unquoted_json_keys(raw_args)),
            ):
                if cand not in candidates:
                    candidates.append(cand)
            arguments = None
            for cand in candidates:
                try:
                    arguments = json.loads(cand)
                    break
                except json.JSONDecodeError:
                    continue
            if arguments is None:
                arguments = {"_raw": raw_args}
    else:
        arguments = {}
    payload = json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False)
    return f"\n{state.TOOL_OPEN}\n{payload}\n{state.TOOL_CLOSE}"


def _native_tool_calls_to_blocks(tool_calls: list) -> str:

    if not tool_calls:
        return ''
    blocks = [_native_tool_call_to_block(tc) for tc in tool_calls]
    return chr(10).join(blocks)


def _accumulate_stream_tool_calls(obj: dict, state: dict) -> None:
    """Akumulasi delta.tool_calls (format native OpenAI STREAMING: tiap
    potongan SSE cuma bawa index + potongan nama/argumen) ke dalam `state`
    (dict index -> {"name": str, "arguments": str}, diisi/dipanggil untuk
    SETIAP chunk SSE). No-op kalau chunk ini tidak mengandung delta.tool_calls.
    `state` dimutasi in-place, mirip pola state machine lain di modul ini
    (mis. visible_state di _stream_visible_text()).
    """
    choices = obj.get("choices") or []
    if not choices:
        return
    delta = (choices[0] or {}).get("delta") or {}
    tool_call_deltas = delta.get("tool_calls")
    if not tool_call_deltas:
        return
    for tc in tool_call_deltas:
        idx = tc.get("index", 0)
        entry = state.setdefault(idx, {"name": "", "arguments": ""})
        func = tc.get("function") or {}
        if func.get("name"):
            entry["name"] += func["name"]
        if func.get("arguments"):
            entry["arguments"] += func["arguments"]
