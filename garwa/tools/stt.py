"""garwa/tools/stt.py
Speech-to-Text (STT) untuk Garwa -- transkripsi audio/voice message.

Provider pluggable & ringan (pola lazy-import + fallback otomatis yang sama
dengan tool Garwa lain, jadi tanpa dependensi pun gateway tetap berjalan):

  GARWA_STT_PROVIDER  (default: "auto")
    - "auto"  : coba cloud (groq) dulu kalau ada API key, else lokal (faster-whisper).
    - "groq"  : Groq Whisper API (butuh GARWA_GROQ_API_KEY). Cepat, gratis, tanpa
                model lokal di RAM. Format audio didukung: flac, mp3, mp4, mpeg,
                mpga, m4a, ogg, wav, webm.
    - "local" : faster-whisper (butuh `faster-whisper` + model diunduh sekali).
                Gratis penuh, offline, tapi butuh RAM/CPU lebih.
    - "none"  : matikan STT (voice message ditolak dengan pesan jelas).

  GARWA_STT_MODEL    : model lokal faster-whisper (default "tiny" -- ringan).
  GARWA_STT_LANGUAGE : hint bahasa (default "" = auto-detect).

Fungsi publik:
  - transcribe_audio(path) -> dict {success, transcript, provider, error}
  - resolve_stt_provider() -> str  (provider aktif, untuk help/status)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from typing import Optional

from . import _state as state

# Provider lokal singleton (faster-whisper model). Dilindungi lock supaya
# beberapa voice message yang masuk bersamaan tidak load model dua kali.
_local_model = None
_local_model_name = None
_local_model_lock = threading.Lock()


def _get(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return v.strip() if v and v.strip() else default


def _groq_api_key() -> str:
    return _get("GARWA_GROQ_API_KEY") or _get("GROQ_API_KEY")


def _has_groq() -> bool:
    try:
        import groq  # noqa: F401
        return bool(_groq_api_key())
    except Exception:
        return False


def _has_faster_whisper() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def resolve_stt_provider() -> str:
    """Provider STT aktif (untuk help/status). Tidak pernah raise."""
    cfg = (_get("GARWA_STT_PROVIDER") or "auto").strip().lower()
    if cfg == "none":
        return "none"
    if cfg == "groq":
        return "groq" if _has_groq() else "none"
    if cfg == "local":
        return "local" if _has_faster_whisper() else "none"
    # auto
    if _has_groq():
        return "groq"
    if _has_faster_whisper():
        return "local"
    return "none"


def _error(msg: str, provider: str = "") -> dict:
    return {"success": False, "transcript": "", "provider": provider or "none", "error": msg}


def _ok(transcript: str, provider: str) -> dict:
    return {"success": True, "transcript": transcript, "provider": provider, "error": ""}


# ---------------------------------------------------------------------------
# Groq (cloud)
# ---------------------------------------------------------------------------
def _transcribe_groq(path: str) -> dict:
    import groq

    client = groq.Groq(api_key=_groq_api_key())
    with open(path, "rb") as f:
        resp = client.audio.transcriptions.create(
            file=(os.path.basename(path), f),
            model="whisper-large-v3-turbo",
        )
    text = (resp.text or "").strip()
    if not text:
        return _error("Groq mengembalikan transkripsi kosong.", "groq")
    return _ok(text, "groq")


# ---------------------------------------------------------------------------
# Local (faster-whisper)
# ---------------------------------------------------------------------------
def _load_local_model(model: str):
    global _local_model, _local_model_name
    if _local_model is not None and _local_model_name == model:
        return _local_model
    from faster_whisper import WhisperModel

    # device cpu; compute_type int8 = ringan di Termux/Android.
    _local_model = WhisperModel(model, device="cpu", compute_type="int8")
    _local_model_name = model
    return _local_model


def _transcribe_local(path: str, model: str, language: str) -> dict:
    with _local_model_lock:
        whisper = _load_local_model(model)
        segments, info = whisper.transcribe(
            path,
            language=language or None,
            beam_size=1,
            vad_filter=True,
        )
        parts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
    text = " ".join(parts).strip()
    if not text:
        return _error("faster-whisper tidak menghasilkan teks.", "local")
    return _ok(text, "local")


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
def transcribe_audio(path: str, model: Optional[str] = None, language: Optional[str] = None) -> dict:
    """Transkripsi audio `path`. Tidak pernah raise -- selalu kembalikan dict
    envelope {success, transcript, provider, error}."""
    if not path or not os.path.isfile(path):
        return _error("file audio tidak ditemukan.")
    try:
        size = os.path.getsize(path)
    except OSError as e:
        return _error(f"gagal membaca ukuran file: {e}")
    if size <= 0:
        return _error("file audio kosong.")

    provider = resolve_stt_provider()
    if provider == "none":
        return _error(
            "STT tidak tersedia. Pasang GARWA_GROQ_API_KEY (cloud) atau install "
            "`faster-whisper` (lokal)."
        )
    try:
        if provider == "groq":
            return _transcribe_groq(path)
        if provider == "local":
            return _transcribe_local(
                path,
                model or (_get("GARWA_STT_MODEL") or "tiny"),
                language or (_get("GARWA_STT_LANGUAGE") or ""),
            )
        return _error(f"provider STT tak dikenal: {provider}")
    except Exception as e:  # pragma: no cover - backend errors bervariasi
        return _error(f"{provider} gagal: {type(e).__name__}: {e}", provider)


def transcribe_audio_local_fallback(path: str, model: Optional[str] = None,
                                    language: Optional[str] = None) -> dict:
    """Fallback khusus: paksa provider lokal (dipakai kalau cloud gagal)."""
    if not _has_faster_whisper():
        return _error("faster-whisper tidak terinstall; fallback lokal tidak tersedia.", "local")
    try:
        return _transcribe_local(
            path,
            model or (_get("GARWA_STT_MODEL") or "tiny"),
            language or (_get("GARWA_STT_LANGUAGE") or ""),
        )
    except Exception as e:  # pragma: no cover
        return _error(f"fallback lokal gagal: {type(e).__name__}: {e}", "local")
