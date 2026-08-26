"""
test_token_utils.py
Uji estimasi token (garwa/token_utils.py).

Fokus:
- count_tokens: teks kosong, None-safe, fallback heuristik, konsistensi.
- count_messages_tokens: overhead per pesan, list kosong.
- Perilaku fallback ketika tiktoken tidak tersedia.
"""

import pytest

from garwa import token_utils


def test_count_tokens_empty():
    assert token_utils.count_tokens("") == 0
    assert token_utils.count_tokens(None) == 0


def test_count_tokens_positive():
    assert token_utils.count_tokens("hello world") >= 1


def test_count_tokens_monotonic():
    a = token_utils.count_tokens("short")
    b = token_utils.count_tokens("a much longer piece of text here")
    assert b >= a


def test_count_tokens_fallback_ratio():
    # Verifikasi heuristik fallback hanya relevan kalau tiktoken tidak ada.
    # Kalau tiktoken terinstall, kita tidak bisa memaksa path fallback, jadi
    # test ini hanya memastikan hasilnya masuk akal (>= 1 dan konsisten).
    text = "x" * 350
    n = token_utils.count_tokens(text)
    assert n >= 1
    if token_utils._ENC is None:
        assert n == 100  # 350 / 3.5


def test_count_messages_tokens_empty_list():
    assert token_utils.count_messages_tokens([]) == 0


def test_count_messages_tokens_overhead():
    # Setiap pesan menambah overhead 4 token.
    one = token_utils.count_messages_tokens([{"content": "abc"}])
    two = token_utils.count_messages_tokens([{"content": "abc"}, {"content": "abc"}])
    assert two == one + token_utils.count_tokens("abc") + 4


def test_count_messages_tokens_ignores_missing_content():
    # Pesan tanpa key "content" diperlakukan sebagai teks kosong (0 token +
    # overhead 4).
    n = token_utils.count_messages_tokens([{"role": "user"}])
    assert n == 4
