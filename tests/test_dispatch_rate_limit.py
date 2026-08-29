"""Test penanganan error rate-limit / concurrent-limit / server-error di
garwa/cli/llm_client/dispatch.py.

Fokus:
1. _is_concurrent_limit_error() mendeteksi HTTP 429 dengan body berisi
   penanda "concurrent_limit" / "bersamaan" / "concurrent".
2. _is_rate_limit_error() tetap mendeteksi 429 biasa (bukan concurrent).
3. call_llama_server() memilih backoff & jumlah percobaan yang tepat per
   kategori error (concurrent > rate-limit > server-error).
4. Timeout stream/nonstream memakai konstanta STREAM_TIMEOUT_SECONDS /
   NONSTREAM_TIMEOUT_SECONDS (bukan hardcoded 300).
"""
import requests
import pytest

from garwa.cli import _state as state
from garwa.cli.llm_client import dispatch
from garwa.cli.llm_client import nonstream_call
from garwa.cli.llm_client import stream_call


def _http_error_429(body: str) -> requests.exceptions.HTTPError:
    resp = requests.Response()
    resp.status_code = 429
    resp._content = body.encode("utf-8")
    resp.headers["Content-Type"] = "application/json"
    return requests.exceptions.HTTPError(response=resp)


def _http_error_500() -> requests.exceptions.HTTPError:
    resp = requests.Response()
    resp.status_code = 500
    resp._content = b"internal error"
    return requests.exceptions.HTTPError(response=resp)


# ---------------------------------------------------------------------------
# Deteksi kategori error
# ---------------------------------------------------------------------------

class TestConcurrentLimitDetection:
    def test_detects_concurrent_limit_code(self):
        e = _http_error_429(
            '{"error":{"code":"concurrent_limit","message":"Batas request '
            'bersamaan tercapai (1/1).","type":"rate_limit_error"}}'
        )
        assert dispatch._is_concurrent_limit_error(e) is True

    def test_detects_concurrent_keyword(self):
        e = _http_error_429('{"error":{"code":"concurrent_limit"}}')
        assert dispatch._is_concurrent_limit_error(e) is True

    def test_plain_rate_limit_not_concurrent(self):
        e = _http_error_429('{"error":{"type":"rate_limit_error"}}')
        assert dispatch._is_concurrent_limit_error(e) is False
        assert dispatch._is_rate_limit_error(e) is True

    def test_500_not_concurrent(self):
        assert dispatch._is_concurrent_limit_error(_http_error_500()) is False


class TestRateLimitDetection:
    def test_plain_429_detected_as_rate_limit(self):
        e = _http_error_429('{"error":{"type":"rate_limit_error"}}')
        assert dispatch._is_rate_limit_error(e) is True

    def test_concurrent_also_detected_as_rate_limit(self):
        # concurrent_limit juga HTTP 429, jadi _is_rate_limit_error tetap True.
        e = _http_error_429(
            '{"error":{"code":"concurrent_limit","type":"rate_limit_error"}}'
        )
        assert dispatch._is_rate_limit_error(e) is True

    def test_500_not_rate_limit(self):
        assert dispatch._is_rate_limit_error(_http_error_500()) is False


# ---------------------------------------------------------------------------
# call_llama_server memilih backoff/attempts yang tepat
# ---------------------------------------------------------------------------

class TestCallLlamaServerRetry:
    def test_concurrent_uses_long_backoff_and_more_attempts(self, monkeypatch):
        """Concurrent limit harus pakai CONCURRENT_LIMIT_BACKOFF_SECONDS dan
        CONCURRENT_LIMIT_RETRY_ATTEMPTS (lebih banyak dari rate-limit biasa)."""
        attempts = []
        backoffs = []

        def fake_stream(*a, **k):
            raise _http_error_429(
                '{"error":{"code":"concurrent_limit","type":"rate_limit_error"}}'
            )

        monkeypatch.setattr(dispatch, "_call_llama_server_stream", fake_stream)
        monkeypatch.setattr(dispatch, "_countdown_sleep",
                            lambda sec, label: backoffs.append(sec))

        with pytest.raises(requests.exceptions.HTTPError):
            dispatch.call_llama_server("http://x", "m", [])

        expected_attempts = state.CONCURRENT_LIMIT_RETRY_ATTEMPTS
        expected_backoff = state.CONCURRENT_LIMIT_BACKOFF_SECONDS
        assert len(backoffs) == expected_attempts - 1
        assert backoffs == expected_backoff[:expected_attempts - 1]

    def test_rate_limit_uses_short_backoff(self, monkeypatch):
        attempts = []
        backoffs = []

        def fake_stream(*a, **k):
            raise _http_error_429('{"error":{"type":"rate_limit_error"}}')

        monkeypatch.setattr(dispatch, "_call_llama_server_stream", fake_stream)
        monkeypatch.setattr(dispatch, "_countdown_sleep",
                            lambda sec, label: backoffs.append(sec))

        with pytest.raises(requests.exceptions.HTTPError):
            dispatch.call_llama_server("http://x", "m", [])

        expected_attempts = state.RATE_LIMIT_RETRY_ATTEMPTS
        expected_backoff = state.RATE_LIMIT_BACKOFF_SECONDS
        assert len(backoffs) == expected_attempts - 1
        assert backoffs == expected_backoff[:expected_attempts - 1]

    def test_server_error_uses_server_backoff(self, monkeypatch):
        backoffs = []

        def fake_stream(*a, **k):
            raise _http_error_500()

        monkeypatch.setattr(dispatch, "_call_llama_server_stream", fake_stream)
        monkeypatch.setattr(dispatch, "_countdown_sleep",
                            lambda sec, label: backoffs.append(sec))

        with pytest.raises(requests.exceptions.HTTPError):
            dispatch.call_llama_server("http://x", "m", [])

        expected_attempts = state.SERVER_ERROR_RETRY_ATTEMPTS
        expected_backoff = state.SERVER_ERROR_BACKOFF_SECONDS
        assert len(backoffs) == expected_attempts - 1
        assert backoffs == expected_backoff[:expected_attempts - 1]

    def test_non_retryable_error_raises_immediately(self, monkeypatch):
        def fake_stream(*a, **k):
            raise ValueError("bukan error retry")

        monkeypatch.setattr(dispatch, "_call_llama_server_stream", fake_stream)
        monkeypatch.setattr(dispatch, "_countdown_sleep",
                            lambda sec, label: pytest.fail("tidak boleh sleep"))

        with pytest.raises(ValueError):
            dispatch.call_llama_server("http://x", "m", [])


# ---------------------------------------------------------------------------
# Timeout memakai konstanta baru (bukan hardcoded 300)
# ---------------------------------------------------------------------------

class TestTimeoutConstants:
    def test_stream_timeout_uses_constant(self, monkeypatch):
        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                pass

            def iter_lines(self, decode_unicode=False):
                return iter([])

            def close(self):
                pass

        def fake_post(url, json=None, headers=None, timeout=None, stream=None):
            captured["timeout"] = timeout
            return FakeResponse()

        monkeypatch.setattr(stream_call.requests, "post", fake_post)
        stream_call._call_llama_server_stream("http://x", "m", [])
        assert captured["timeout"] == state.STREAM_TIMEOUT_SECONDS
        assert state.STREAM_TIMEOUT_SECONDS < 300  # diturunkan dari 300

    def test_nonstream_timeout_uses_constant(self, monkeypatch):
        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": "hi"},
                                     "finish_reason": "stop"}]}

            def close(self):
                pass

        def fake_post(url, json=None, headers=None, timeout=None):
            captured["timeout"] = timeout
            return FakeResponse()

        monkeypatch.setattr(nonstream_call.requests, "post", fake_post)
        nonstream_call._call_llama_server_nonstream("http://x", "m", [])
        assert captured["timeout"] == state.NONSTREAM_TIMEOUT_SECONDS
        assert state.NONSTREAM_TIMEOUT_SECONDS < 300
