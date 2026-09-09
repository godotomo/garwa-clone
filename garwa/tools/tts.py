"""garwa/tools/tts.py
Text-to-Speech (TTS) untuk Garwa -- sintesis suara dari teks.

Provider pluggable & ringan (lazy-import + fallback otomatis):

  GARWA_TTS_PROVIDER  (default: "auto")
    - "auto"      : coba edge-tts (gratis, tanpa API key) dulu, else espeak-ng
                    (sistem, tanpa dependensi Python), else "none".
    - "edge-tts"  : Microsoft Edge TTS (butuh `edge-tts`). Gratis, kualitas
                    bagus, tanpa API key. Output mp3.
    - "espeak"    : espeak-ng via subprocess (tanpa dependensi Python, tersedia
                    via `pkg install espeak-ng` di Termux). Output wav.
    - "none"      : matikan TTS.

  GARWA_TTS_VOICE   : voice edge-tts (default "id-ID-ArdiNeural" untuk bahasa
                      Indonesia; lihat `edge-tts --list-voices`).
  GARWA_TTS_LANG    : bahasa espeak-ng (default "id").

Fungsi publik:
  - text_to_speech(text, output_path) -> dict {success, path, provider, error}
  - resolve_tts_provider() -> str
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional

from . import _state as state


def _get(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return v.strip() if v and v.strip() else default


def _has_edge_tts() -> bool:
    try:
        import edge_tts  # noqa: F401
        return True
    except Exception:
        return False


def _has_espeak() -> bool:
    return bool(shutil.which("espeak-ng") or shutil.which("espeak"))


def resolve_tts_provider() -> str:
    cfg = (_get("GARWA_TTS_PROVIDER") or "auto").strip().lower()
    if cfg == "none":
        return "none"
    if cfg == "edge-tts":
        return "edge-tts" if _has_edge_tts() else "none"
    if cfg == "espeak":
        return "espeak" if _has_espeak() else "none"
    # auto
    if _has_edge_tts():
        return "edge-tts"
    if _has_espeak():
        return "espeak"
    return "none"


def _error(msg: str, provider: str = "") -> dict:
    return {"success": False, "path": "", "provider": provider or "none", "error": msg}


def _ok(path: str, provider: str) -> dict:
    return {"success": True, "path": path, "provider": provider, "error": ""}


def _synthesize_edge_tts(text: str, output_path: str, voice: str) -> str:
    import edge_tts
    import asyncio

    async def _run():
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)

    asyncio.run(_run())
    return output_path


def _synthesize_espeak(text: str, output_path: str, lang: str) -> str:
    exe = "espeak-ng" if shutil.which("espeak-ng") else "espeak"
    # espeak-ng default wav; kalau output_path berakhiran .wav, tulis langsung.
    cmd = [exe, "-v", lang, "-w", output_path, text]
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    return output_path


def text_to_speech(text: str, output_path: str,
                   voice: Optional[str] = None, lang: Optional[str] = None) -> dict:
    """Sintesis `text` ke `output_path`. Tidak pernah raise. Output_path parent
    harus sudah ada (dibuat pemanggil)."""
    text = (text or "").strip()
    if not text:
        return _error("teks kosong.")
    if not output_path:
        return _error("output_path kosong.")

    provider = resolve_tts_provider()
    if provider == "none":
        return _error(
            "TTS tidak tersedia. Install `edge-tts` (gratis) atau `espeak-ng` "
            "(sistem) untuk mengaktifkan text-to-speech."
        )
    try:
        if provider == "edge-tts":
            v = voice or (_get("GARWA_TTS_VOICE") or "id-ID-ArdiNeural")
            _synthesize_edge_tts(text, output_path, v)
        elif provider == "espeak":
            l = lang or (_get("GARWA_TTS_LANG") or "id")
            _synthesize_espeak(text, output_path, l)
        else:
            return _error(f"provider TTS tak dikenal: {provider}")
        if not os.path.isfile(output_path) or os.path.getsize(output_path) <= 0:
            return _error("TTS tidak menghasilkan file.", provider)
        return _ok(output_path, provider)
    except Exception as e:  # pragma: no cover - backend errors bervariasi
        return _error(f"{provider} gagal: {type(e).__name__}: {e}", provider)
