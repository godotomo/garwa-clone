"""cli/tool_schema/alt_syntax.py
Dipecah lebih lanjut dari cli/tool_schema.py.
"""
import json
import re

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from .. import _state as state



def _parse_alt_tool_call_args(raw_args: str) -> dict:
    """Parse isi `{...}` format tool_call alternatif (key:<|"|>value<|"|>,
    dipisah koma) jadi dict argumen Python biasa. Bukan JSON, jadi tidak
    memakai json.loads() -- tiap value pada format ini selalu string.
    """
    arguments = {}
    for key, value in state._ALT_TOOL_ARG_RE.findall(raw_args):
        arguments[key] = value
    return arguments


def _convert_alt_tool_call_syntax(text: str) -> str:
    """Ubah semua blok tool_call format ALTERNATIF di `text` (lihat komentar
    di atas ALT_TOOL_CALL_RE) menjadi blok resmi
    `<tool_call>{"name": ..., "arguments": {...}}</tool_call>`.

    Kalau tidak ada blok format alternatif ditemukan, `text` dikembalikan
    apa adanya (no-op) -- aman dipanggil untuk SETIAP balasan model, bukan
    cuma yang memakai format alternatif.
    """
    if "<|tool_call>" not in text:
        return text

    def _replace(match: "re.Match") -> str:
        alt_name = match.group(1)
        raw_args = match.group(2)
        real_name = state.ALT_TOOL_NAME_ALIASES.get(alt_name.lower(), alt_name.lower())
        arguments = _parse_alt_tool_call_args(raw_args)
        payload = json.dumps({"name": real_name, "arguments": arguments}, ensure_ascii=False)
        return f"{state.TOOL_OPEN}\n{payload}\n{state.TOOL_CLOSE}"

    return state.ALT_TOOL_CALL_RE.sub(_replace, text)
