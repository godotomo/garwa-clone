"""tests/test_stt_tts_media.py
Test hermetic untuk integrasi STT/TTS + transfer file/gambar via Telegram.

Cakupan:
  - stt.transcribe_audio: envelope error (file tak ada/kosong, provider none).
  - stt.resolve_stt_provider: pilihan provider berdasarkan env + lib tersedia.
  - tts.text_to_speech: envelope error (teks kosong, provider none).
  - comm_tools.tool_send_document: kirim file via multipart (mock requests).
  - comm_tools.tool_text_to_speech: TTS + kirim audio (mock tts + requests).
  - telegram_gateway._handle_media_message: voice/audio/document/photo
    (download di-mock, STT di-mock) menghasilkan teks agent turn yang benar.
  - telegram_gateway env chat_id: send_document terkirim ke chat asal.

Tidak menyentuh jaringan: semua requests.post / requests.get di-mock.
"""
from __future__ import annotations

import argparse
import os
import tempfile

import pytest

from garwa import db as dbmod
from garwa.tools import stt, tts
from garwa.tools import comm_tools
from garwa.telegram_gateway import TelegramGateway


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_args(db_path: str, workdir: str) -> argparse.Namespace:
    return argparse.Namespace(
        db_path=db_path,
        workdir=workdir,
        skills_dir="",
        full_tool_schema_text=False,
        auto_approve=False,
        model="test-model",
        context_window=8192,
        reserve_for_response=1024,
        summarize_threshold_ratio=0.7,
        keep_tail_messages=5,
        api_key="",
        url="http://localhost:1",
        session_title="telegram",
    )


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.fixture
def gw(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test.db")
    dbmod.init_db(db_path)
    offset_file = str(tmp_path / "offset.txt")

    calls = []

    def fake_post(url, data=None, timeout=None, files=None):
        calls.append((url, dict(data or {}), files))
        method = url.rsplit("/", 1)[-1]
        if method == "getUpdates":
            return FakeResponse({"ok": True, "result": []})
        if method == "sendMessage":
            return FakeResponse({"ok": True, "result": {"message_id": 1}})
        if method == "getFile":
            return FakeResponse({"ok": True, "result": {"file_path": "docs/file.ogg"}})
        return FakeResponse({"ok": True, "result": []})

    monkeypatch.setattr("requests.post", fake_post)

    class FakeGetResponse:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            return None

    def fake_get(url, timeout=None):
        return FakeGetResponse(b"FAKE-AUDIO-BYTES")

    monkeypatch.setattr("requests.get", fake_get)

    args = _make_args(db_path, str(tmp_path))
    g = TelegramGateway(args=args, token="dummy:token", admin_id="777",
                        allow_all=False, offset_file=offset_file)
    g._calls = calls
    return g


# ---------------------------------------------------------------------------
# STT
# ---------------------------------------------------------------------------
def test_stt_missing_file(monkeypatch):
    monkeypatch.setenv("GARWA_STT_PROVIDER", "none")
    res = stt.transcribe_audio("/nonexistent/file.ogg")
    assert res["success"] is False
    assert res["error"]


def test_stt_empty_file(monkeypatch, tmp_path):
    monkeypatch.setenv("GARWA_STT_PROVIDER", "none")
    p = tmp_path / "empty.ogg"
    p.write_bytes(b"")
    res = stt.transcribe_audio(str(p))
    assert res["success"] is False
    assert "kosong" in res["error"]


def test_stt_provider_none(monkeypatch, tmp_path):
    monkeypatch.setenv("GARWA_STT_PROVIDER", "none")
    p = tmp_path / "a.ogg"
    p.write_bytes(b"x")
    res = stt.transcribe_audio(str(p))
    assert res["success"] is False
    assert "STT tidak tersedia" in res["error"]


def test_stt_resolve_groq(monkeypatch):
    monkeypatch.setenv("GARWA_STT_PROVIDER", "groq")
    monkeypatch.setenv("GARWA_GROQ_API_KEY", "test-key")
    monkeypatch.setattr(stt, "_has_groq", lambda: True)
    monkeypatch.setattr(stt, "_has_faster_whisper", lambda: False)
    assert stt.resolve_stt_provider() == "groq"


def test_stt_resolve_auto_fallback_local(monkeypatch):
    monkeypatch.delenv("GARWA_STT_PROVIDER", raising=False)
    monkeypatch.setattr(stt, "_has_groq", lambda: False)
    monkeypatch.setattr(stt, "_has_faster_whisper", lambda: True)
    assert stt.resolve_stt_provider() == "local"


def test_stt_resolve_auto_none(monkeypatch):
    monkeypatch.delenv("GARWA_STT_PROVIDER", raising=False)
    monkeypatch.setattr(stt, "_has_groq", lambda: False)
    monkeypatch.setattr(stt, "_has_faster_whisper", lambda: False)
    assert stt.resolve_stt_provider() == "none"


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------
def test_tts_empty_text(monkeypatch):
    monkeypatch.setenv("GARWA_TTS_PROVIDER", "none")
    res = tts.text_to_speech("", "/tmp/x.mp3")
    assert res["success"] is False
    assert "teks kosong" in res["error"]


def test_tts_provider_none(monkeypatch, tmp_path):
    monkeypatch.setenv("GARWA_TTS_PROVIDER", "none")
    res = tts.text_to_speech("halo", str(tmp_path / "x.mp3"))
    assert res["success"] is False
    assert "TTS tidak tersedia" in res["error"]


def test_tts_resolve_edge(monkeypatch):
    monkeypatch.setenv("GARWA_TTS_PROVIDER", "edge-tts")
    monkeypatch.setattr(tts, "_has_edge_tts", lambda: True)
    monkeypatch.setattr(tts, "_has_espeak", lambda: False)
    assert tts.resolve_tts_provider() == "edge-tts"


def test_tts_resolve_none(monkeypatch):
    monkeypatch.setenv("GARWA_TTS_PROVIDER", "auto")
    monkeypatch.setattr(tts, "_has_edge_tts", lambda: False)
    monkeypatch.setattr(tts, "_has_espeak", lambda: False)
    assert tts.resolve_tts_provider() == "none"


# ---------------------------------------------------------------------------
# comm_tools: send_document & text_to_speech
# ---------------------------------------------------------------------------
def test_send_document_missing_file(monkeypatch):
    res = comm_tools.tool_send_document("/nonexistent.pdf")
    assert "tidak ditemukan" in res


def test_send_document_success(monkeypatch, tmp_path):
    monkeypatch.setenv("GARWA_TELEGRAM_TOKEN", "dummy:token")
    monkeypatch.setenv("GARWA_TELEGRAM_CHAT_ID", "777")
    p = tmp_path / "report.pdf"
    p.write_bytes(b"%PDF-fake")

    captured = {}

    def fake_post(url, data=None, files=None, timeout=None):
        captured["url"] = url
        captured["files"] = files
        return FakeResponse({"ok": True, "result": {"message_id": 1}})

    monkeypatch.setattr("requests.post", fake_post)
    res = comm_tools.tool_send_document(str(p), caption="laporan")
    assert "OK" in res
    assert "sendDocument" in captured["url"]
    assert captured["files"]["document"][0] == "report.pdf"


def test_text_to_speech_success(monkeypatch, tmp_path):
    monkeypatch.setenv("GARWA_TELEGRAM_TOKEN", "dummy:token")
    monkeypatch.setenv("GARWA_TELEGRAM_CHAT_ID", "777")
    audio = tmp_path / "out.mp3"
    audio.write_bytes(b"MP3-FAKE")

    captured = {}

    def fake_post(url, data=None, files=None, timeout=None):
        captured["url"] = url
        captured["files"] = files
        return FakeResponse({"ok": True, "result": {"message_id": 1}})

    monkeypatch.setattr("requests.post", fake_post)

    # Mock tts.text_to_speech agar tidak perlu backend nyata.
    monkeypatch.setattr(
        "garwa.tools.tts.text_to_speech",
        lambda text, path, voice=None: {"success": True, "path": str(audio),
                                         "provider": "edge-tts", "error": ""},
    )
    res = comm_tools.tool_text_to_speech("halo dunia", output_path=str(audio))
    assert "OK" in res
    assert "sendAudio" in captured["url"]


# ---------------------------------------------------------------------------
# telegram_gateway: media message handling
# ---------------------------------------------------------------------------
def test_gateway_voice_message_transcribes(monkeypatch, gw):
    """Voice message -> download -> STT -> agent turn dgn teks transkrip."""
    monkeypatch.setattr(
        "garwa.telegram_gateway.TelegramGateway._transcribe",
        lambda self, path: "hasil transkripsi suara",
    )
    # Tangkap teks yang masuk ke agent turn.
    captured = {}
    monkeypatch.setattr(
        "garwa.telegram_gateway.TelegramGateway._run_agent_turn",
        lambda self, chat, mid, text: captured.update({"text": text}),
    )
    msg = {
        "message_id": 10,
        "chat": {"id": 777},
        "from": {"id": 777},
        "voice": {"file_id": "VOICE1"},
    }
    gw.handle_message(msg)
    assert captured.get("text") == "hasil transkripsi suara"


def test_gateway_document_attachment(monkeypatch, gw):
    """Document -> download -> agent turn dgn tag <file_attachment>."""
    inbox = gw._inbox_dir()
    captured = {}
    monkeypatch.setattr(
        "garwa.telegram_gateway.TelegramGateway._run_agent_turn",
        lambda self, chat, mid, text: captured.update({"text": text}),
    )
    msg = {
        "message_id": 11,
        "chat": {"id": 777},
        "from": {"id": 777},
        "document": {"file_id": "DOC1", "file_name": "analisa.pdf"},
    }
    gw.handle_message(msg)
    assert captured.get("text")
    assert "<file_attachment" in captured["text"]
    assert 'kind="dokumen"' in captured["text"]
    assert "analisa.pdf" in captured["text"]


def test_gateway_photo_attachment(monkeypatch, gw):
    """Photo -> download -> agent turn dgn tag kind=gambar (vision)."""
    captured = {}
    monkeypatch.setattr(
        "garwa.telegram_gateway.TelegramGateway._run_agent_turn",
        lambda self, chat, mid, text: captured.update({"text": text}),
    )
    msg = {
        "message_id": 12,
        "chat": {"id": 777},
        "from": {"id": 777},
        "photo": [{"file_id": "LOW"}, {"file_id": "HIGH"}],
    }
    gw.handle_message(msg)
    assert captured.get("text")
    assert 'kind="gambar"' in captured["text"]
    assert 'status="workdir"' in captured["text"]


def test_gateway_env_chat_id_set(monkeypatch, gw):
    """_run_agent_turn_worker set GARWA_TELEGRAM_CHAT_ID utk send_document."""
    monkeypatch.setattr(
        "garwa.telegram_gateway.run_agent_loop",
        lambda *a, **k: "selesai",
    )
    # Panggil worker langsung (tanpa thread) supaya deterministik.
    gw._run_agent_turn_worker(777, 1, "buat laporan")
    # Env harus di-restore setelah turn (karena tidak ada nilai sebelumnya).
    assert "GARWA_TELEGRAM_CHAT_ID" not in os.environ
