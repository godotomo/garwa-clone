"""
test_token_utils.py
Uji estimasi token (garwa/token_utils.py).

Fokus:
- count_tokens: teks kosong, None-safe, tiktoken bila tersedia, fallback.
- count_messages_tokens: berbasis JSON (akurat), overhead chat template,
  list kosong.
- count_json_tokens: objek None-safe.
- Perilaku fallback ketika tiktoken tidak tersedia.
"""

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
        # Fallback dinamis: teks tanpa whitespace memakai rasio 3.2.
        assert n == int(350 / 3.2)


def test_count_messages_tokens_empty_list():
    assert token_utils.count_messages_tokens([]) == 0


def test_count_messages_tokens_adds_chat_overhead():
    # count_messages_tokens menghitung JSON penuh pesan + overhead chat
    # template per pesan. Dua pesan identik harus lebih besar dari satu.
    one = token_utils.count_messages_tokens([{"role": "user", "content": "abc"}])
    two = token_utils.count_messages_tokens(
        [{"role": "user", "content": "abc"}, {"role": "user", "content": "abc"}]
    )
    assert two > one
    # Overhead per pesan ditambahkan: selisih minimal = overhead satu pesan.
    assert two - one >= token_utils.CHAT_TEMPLATE_OVERHEAD_PER_MESSAGE


def test_count_messages_tokens_uses_full_json():
    # Pesan dengan field role + content dihitung dari JSON lengkapnya, jadi
    # hasilnya lebih besar daripada sekadar count_tokens(content) + overhead.
    content = "halo apa kabar"
    single = token_utils.count_messages_tokens([{"role": "user", "content": content}])
    assert single > token_utils.count_tokens(content)


def test_count_json_tokens_none_safe():
    assert token_utils.count_json_tokens(None) == 0
    assert token_utils.count_json_tokens({}) >= 0


def test_count_json_tokens_positive():
    obj = {"tools": [{"type": "function", "name": "read_file"}]}
    assert token_utils.count_json_tokens(obj) >= 1