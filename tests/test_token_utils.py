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

import json

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


# ---------------------------------------------------------------------------
# Optimasi P3: cache token potongan tepi (_msg_edge_tokens) + jalur cepat.
# ---------------------------------------------------------------------------

def _edge_payload(serialized, kind):
    if kind == "head":
        return "[" + serialized + ", "
    if kind == "solo":
        return "[" + serialized + "]"
    return serialized + "]"


def test_msg_edge_tokens_matches_direct_tokenization():
    # Cache TIDAK boleh mengubah nilai: hasilnya harus sama dengan tokenisasi
    # langsung potongan tepi, untuk setiap kind.
    serialized = '{"role": "user", "content": "halo dunia ini uji"}'
    for kind in ("head", "solo", "tail"):
        expected = token_utils.count_tokens(_edge_payload(serialized, kind))
        token_utils._MSG_EDGE_TOKENS_CACHE.clear()
        first = token_utils._msg_edge_tokens(serialized, kind)
        second = token_utils._msg_edge_tokens(serialized, kind)  # dari cache
        assert first == expected
        assert second == expected


def test_msg_edge_tokens_keys_do_not_collide_across_kinds():
    # Kunci cache memuat kind, jadi konten sama dengan potongan berbeda tidak
    # saling menimpa.
    serialized = '{"role": "assistant", "content": "ok"}'
    token_utils._MSG_EDGE_TOKENS_CACHE.clear()
    head = token_utils._msg_edge_tokens(serialized, "head")
    tail = token_utils._msg_edge_tokens(serialized, "tail")
    assert head == token_utils.count_tokens(_edge_payload(serialized, "head"))
    assert tail == token_utils.count_tokens(_edge_payload(serialized, "tail"))
    assert len(token_utils._MSG_EDGE_TOKENS_CACHE) == 2


def test_fast_path_matches_full_json_tokenization():
    # Jalur cepat aditif (per-item cache - koreksi batas) harus identik dengan
    # tokenisasi JSON penuh untuk payload bentuk nyata build_context_messages.
    payloads = [
        [{"role": "system", "content": "aturan penting"},
         {"role": "user", "content": "halo"},
         {"role": "assistant", "content": "hai"},
         {"role": "user", "content": "lanjut"}],
        [{"role": "user", "content": "solo"}],
        [{"role": "user", "content": "x"}, {"role": "user", "content": "y"}],
        [{"role": "system", "content": "多字节 ok 🚀"},
         {"role": "user", "content": "def f(x):\n    return x"}],
    ]
    for msgs in payloads:
        exact = token_utils.count_tokens(
            "[" + ", ".join(json.dumps(m, ensure_ascii=False) for m in msgs) + "]"
        )
        assert token_utils._count_messages_json_tokens(msgs) == exact


def test_fast_path_thread_safe_and_consistent():
    import threading

    msgs = [
        {"role": "system", "content": "aturan"},
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "c"},
    ]
    expected = token_utils._count_messages_json_tokens(msgs)
    token_utils._MSG_EDGE_TOKENS_CACHE.clear()
    token_utils._MSG_ITEM_TOKENS_CACHE.clear()
    results = []
    lock = threading.Lock()

    def worker():
        for _ in range(50):
            n = token_utils._count_messages_json_tokens(msgs)
            with lock:
                results.append(n)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [expected] * len(results)