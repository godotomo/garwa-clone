"""cli/llm_client/debug_log.py
Dipecah lebih lanjut dari cli/llm_client.py.
"""
import json
import sys

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from .. import _state as state
from ..colors import C
from ..colors import c



def _debug_log(label: str, text: str):
    """Cetak baris debug ke STDERR (bukan stdout), supaya tidak mengganggu
    live-redraw markdown renderer yang mengasumsikan hanya dirinya yang
    menyentuh stdout selama streaming. Kalau Anda ingin menyimpan seluruh
    debug log ke file di mode interaktif/auto, jalankan CLI dengan:
    ... --debug 2> debug.log
    Di mode --overnight, output ini otomatis ikut ditulis ke file log
    overnight juga (lihat _DEBUG_EXTRA_SINK), tanpa perlu redirect manual.
    """
    prefix = c(f"[DEBUG {label}]", C.CYAN) if sys.stderr.isatty() else f"[DEBUG {label}]"
    sys.stderr.write(f"{prefix} {text}\n")
    sys.stderr.flush()
    sink = state._DEBUG_EXTRA_SINK[0]
    if sink is not None:
        try:
            sink.write(f"[DEBUG {label}] {text}\n")
            sink.flush()
        except Exception:
            pass


def _redact_vision_payload_for_debug(payload: dict) -> dict:
    """Salinan `payload` dengan data-URI base64 gambar diganti placeholder
    pendek (mis. "data:image/png;base64,<redacted, 183042 char>"), supaya
    log --debug tidak dibanjiri ratusan KB base64 yang tidak berguna buat
    troubleshooting (yang biasa perlu dicek justru role/urutan
    pesan/tool_call, bukan isi mentah gambarnya). Fail-soft: kalau bentuk
    payload tidak sesuai dugaan, balikin apa adanya tanpa error.
    """
    try:
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return payload
        new_messages = []
        changed = False
        for msg in messages:
            content = msg.get("content") if isinstance(msg, dict) else None
            if not isinstance(content, list):
                new_messages.append(msg)
                continue
            new_blocks = []
            msg_changed = False
            for block in content:
                url = None
                if isinstance(block, dict) and block.get("type") == "image_url":
                    image_url = block.get("image_url")
                    if isinstance(image_url, dict):
                        url = image_url.get("url")
                if isinstance(url, str) and url.startswith("data:") and len(url) > 100:
                    header = url.split(",", 1)[0]
                    new_blocks.append({
                        "type": "image_url",
                        "image_url": {"url": f"{header},<redacted, {len(url)} char>"},
                    })
                    msg_changed = True
                else:
                    new_blocks.append(block)
            if msg_changed:
                new_msg = dict(msg)
                new_msg["content"] = new_blocks
                new_messages.append(new_msg)
                changed = True
            else:
                new_messages.append(msg)
        if not changed:
            return payload
        new_payload = dict(payload)
        new_payload["messages"] = new_messages
        return new_payload
    except Exception:
        return payload


def _debug_payload_preview(payload: dict, limit: int = 4000) -> str:
    redacted = _redact_vision_payload_for_debug(payload)
    raw = json.dumps(redacted, ensure_ascii=False)
    return raw if len(raw) <= limit else raw[:limit] + f"...(dipotong, total {len(raw)} char)"
