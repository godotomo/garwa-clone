"""Test retry/backoff anti rate-limit (429) di jobbot/llm_filter.py."""
import os
import sys
import unittest
from unittest.mock import patch, Mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
# jobbot kini adalah skill (skills/job-tracker/scripts/jobbot)
sys.path.insert(0, os.path.join(_ROOT, "skills", "job-tracker", "scripts"))

from jobbot.llm_filter import (
    _should_retry,
    _backoff_delay,
    _classify_llm,
    LLM_MAX_RETRIES,
)
from jobbot.models import Job


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeHTTPError(Exception):
    def __init__(self, status_code):
        self.response = FakeResponse(status_code)
        super().__init__(f"HTTP {status_code}")


def make_job(title="Senior React Developer", company="Lemon.io"):
    return Job(platform="test", job_id="1", title=title, company=company,
               description="Build React apps", skills="react")


class TestShouldRetry(unittest.TestCase):
    def test_retry_on_429(self):
        self.assertTrue(_should_retry(FakeHTTPError(429)))

    def test_retry_on_500(self):
        self.assertTrue(_should_retry(FakeHTTPError(500)))

    def test_retry_on_503(self):
        self.assertTrue(_should_retry(FakeHTTPError(503)))

    def test_no_retry_on_400(self):
        self.assertFalse(_should_retry(FakeHTTPError(400)))

    def test_no_retry_on_401(self):
        self.assertFalse(_should_retry(FakeHTTPError(401)))

    def test_no_retry_on_generic(self):
        self.assertFalse(_should_retry(ValueError("boom")))


class TestBackoffDelay(unittest.TestCase):
    def test_delay_bounded(self):
        for attempt in range(6):
            d = _backoff_delay(attempt)
            self.assertGreaterEqual(d, 0.0)
            self.assertLessEqual(d, 15.0)

    def test_delay_increases_with_attempt(self):
        # Dengan full jitter, upper bound naik eksponensial.
        upper0 = min(15.0, 1.0 * (2 ** 0))
        upper2 = min(15.0, 1.0 * (2 ** 2))
        self.assertLess(upper0, upper2)


class TestClassifyLlmRetry(unittest.TestCase):
    @patch("jobbot.llm_filter._llm_available", return_value=True)
    @patch("jobbot.llm_filter._llm_config",
           return_value=("key", "https://api.test/v1/chat/completions", "model"))
    @patch("jobbot.llm_filter.time.sleep", return_value=None)
    def test_retries_then_succeeds(self, mock_sleep, mock_cfg, mock_avail):
        """429 dulu, lalu sukses pada percobaan kedua."""
        good = Mock()
        good.raise_for_status = lambda: None
        good.json.return_value = {
            "choices": [{"message": {"content": '{"relevant": true, "role": "developer", "subtype": "web", "reason": "ok"}'}}]
        }
        bad = Mock()
        bad.raise_for_status.side_effect = FakeHTTPError(429)

        with patch("requests.post", side_effect=[bad, good]) as mock_post:
            result = _classify_llm(make_job())

        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "llm")
        self.assertEqual(result["role"], "developer")
        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("jobbot.llm_filter._llm_available", return_value=True)
    @patch("jobbot.llm_filter._llm_config",
           return_value=("key", "https://api.test/v1/chat/completions", "model"))
    @patch("jobbot.llm_filter.time.sleep", return_value=None)
    def test_gives_up_after_max_retries(self, mock_sleep, mock_cfg, mock_avail):
        """Selalu 429 -> fallback None setelah LLM_MAX_RETRIES percobaan."""
        bad = Mock()
        bad.raise_for_status.side_effect = FakeHTTPError(429)

        with patch("requests.post", return_value=bad) as mock_post:
            result = _classify_llm(make_job())

        self.assertIsNone(result)
        self.assertEqual(mock_post.call_count, LLM_MAX_RETRIES)
        self.assertEqual(mock_sleep.call_count, LLM_MAX_RETRIES - 1)

    @patch("jobbot.llm_filter._llm_available", return_value=True)
    @patch("jobbot.llm_filter._llm_config",
           return_value=("key", "https://api.test/v1/chat/completions", "model"))
    @patch("jobbot.llm_filter.time.sleep", return_value=None)
    def test_no_retry_on_400(self, mock_sleep, mock_cfg, mock_avail):
        """400 (bad request) -> tidak retry, langsung fallback."""
        bad = Mock()
        bad.raise_for_status.side_effect = FakeHTTPError(400)

        with patch("requests.post", return_value=bad) as mock_post:
            result = _classify_llm(make_job())

        self.assertIsNone(result)
        self.assertEqual(mock_post.call_count, 1)
        mock_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
