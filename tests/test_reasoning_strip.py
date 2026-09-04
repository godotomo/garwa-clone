"""
test_reasoning_strip.py
Uji pembersihan reasoning/chain-of-thought yang bocor sebagai teks biasa
di dalam field `content` (garwa/cli/reasoning_strip.py).

Fokus:
- Menghapus blok reasoning well-formed dari berbagai format tag.
- TIDAK menyentuh teks biasa yang memuat kata "thinking" sebagai topik.
- Tidak menghapus pembuka tanpa penutup (hindari memotong konten sah).
- Deteksi keberadaan blok reasoning (has_reasoning_tags).
"""

import pytest

from garwa.cli.reasoning_strip import has_reasoning_tags, strip_reasoning_tags


# ---------------------------------------------------------------- XML-like

def test_strip_xml_thinking():
    out = strip_reasoning_tags("<thinking>rencana rahasia</thinking>Jawaban akhir")
    assert out == "Jawaban akhir"


def test_strip_xml_reasoning_in_middle():
    out = strip_reasoning_tags("Awal <reasoning>analisis</reasoning> Akhir")
    assert out == "Awal  Akhir"


def test_strip_xml_multiline():
    out = strip_reasoning_tags("<thinking>\nbaris1\nbaris2\n</thinking>Hasil")
    assert out == "Hasil"


def test_strip_xml_case_insensitive():
    out = strip_reasoning_tags("<THINKING>rahasia</THINKING>teks")
    assert out == "teks"


# ---------------------------------------------------------------- pipe-style

def test_strip_pipe_start_end_thought():
    out = strip_reasoning_tags("X <|start_of_thought|>cogitasi<|end_of_thought|> Y")
    assert out == "X  Y"


def test_strip_pipe_simple():
    out = strip_reasoning_tags("A <|thinking|>pikir<|/thinking|> B")
    assert out == "A  B"


# ---------------------------------------------------------------- bracket

def test_strip_bracket():
    out = strip_reasoning_tags("X [REASONING]rahasia[/REASONING] Y")
    assert out == "X  Y"


def test_strip_bracket_case_insensitive():
    out = strip_reasoning_tags("A [Thought]pikir[/thought] B")
    assert out == "A  B"


# ---------------------------------------------------------------- html comment

def test_strip_html_comment():
    out = strip_reasoning_tags("A <!-- thinking -->rahasia<!-- /thinking --> B")
    assert out == "A  B"


# ---------------------------------------------------------------- keamanan

def test_strip_keeps_plain_text_with_thinking_word():
    # Kata "thinking" sebagai topik pembahasan TIDAK boleh dihapus.
    out = strip_reasoning_tags("teks biasa tentang thinking sebagai topik")
    assert out == "teks biasa tentang thinking sebagai topik"


def test_strip_keeps_unclosed_tag():
    # Pembuka tanpa penutup bukan blok well-formed -- jangan hapus setengah.
    out = strip_reasoning_tags("X <thinking>tidak tertutup Y")
    assert out == "X <thinking>tidak tertutup Y"


def test_strip_keeps_none_and_empty():
    assert strip_reasoning_tags("") == ""
    assert strip_reasoning_tags(None) is None


def test_strip_noop_without_tags():
    assert strip_reasoning_tags("jawaban normal tanpa tag") == "jawaban normal tanpa tag"


# ---------------------------------------------------------------- has_reasoning_tags

def test_has_reasoning_tags_various():
    assert has_reasoning_tags("<thinking>x</thinking>") is True
    assert has_reasoning_tags("<|start_of_thought|>x<|end_of_thought|>") is True
    assert has_reasoning_tags("[THOUGHT]x[/THOUGHT]") is True
    assert has_reasoning_tags("<!-- analysis -->x<!-- /analysis -->") is True


def test_has_reasoning_tags_none():
    assert has_reasoning_tags("teks biasa") is False
    assert has_reasoning_tags("") is False
    assert has_reasoning_tags(None) is False


def test_has_reasoning_tags_unclosed():
    assert has_reasoning_tags("<thinking>tidak tertutup") is False