"""cli/reasoning_strip.py
Pembersihan "chain of thought" / reasoning yang BOCOR ke dalam field
`content` sebagai teks biasa.

Latar belakang:
- Backend yang benar memisahkan reasoning ke field terpisah
  (`reasoning_content` / `reasoning` / `reasoning_details`). Field ini sudah
  dipisahkan oleh `stream_parse._extract_stream_reasoning()` dan TIDAK pernah
  digabung ke `assistant_text` (lihat stream_call.py / nonstream_call.py),
  sehingga tidak bocor ke respon pengguna.

- Namun, sebagian model/backend (terutama yang di-quantize atau yang
  memakai template chat khusus) menulis reasoning LANGSUNG di dalam field
  `content`, dibungkus tag eksplisit seperti `<thinking>...</thinking>`,
  `<|start_of_thought|>...</|end_of_thought|>`, `[REASONING]...[/REASONING]`,
  atau komentar HTML `<!-- thinking -->...<!-- /thinking -->`. Tanpa
  pembersihan, blok ini ikut disimpan ke DB dan ditampilkan ke user sebagai
  bagian dari jawaban -- itulah "kebocoran reasoning" yang tidak diinginkan.

Modul ini menyediakan `strip_reasoning_tags()` untuk menghapus blok reasoning
yang TERTUTUP RAPI (ada pembuka dan penutup yang cocok) dari teks jawaban
model. Hanya blok yang well-formed yang dihapus -- teks biasa yang memuat
kata "thinking" sebagai topik pembahasan TIDAK disentuh, supaya tidak
menghapus konten yang sah.
"""

import re

# Kumpulan tag reasoning yang umum dipakai model/backend. Nama tag dibatasi
# ke kata-kata khas reasoning supaya tidak salah hapus tag lain yang sah.
_REASONING_TAG_NAMES = (
    "thinking",
    "thought",
    "reasoning",
    "analysis",
    "cot",            # chain-of-thought singkatan
    "scratchpad",
)

# ---------------------------------------------------------------------------
# 1. Blok XML-like: <thinking>...</thinking> (dan varian case-insensitive,
#    whitespace di dalam tag, serta tag pembuka/penutup yang sama namanya).
# ---------------------------------------------------------------------------
_xml_names = "|".join(_REASONING_TAG_NAMES)
_XML_BLOCK_RE = re.compile(
    rf"<\s*(?:{_xml_names})\s*>(.*?)<\s*/\s*(?:{_xml_names})\s*>",
    re.IGNORECASE | re.DOTALL,
)

# ---------------------------------------------------------------------------
# 2. Blok pipe-style: <|thinking|>...</|thinking|>, <|start_of_thought|>...
#    <|end_of_thought|>. Handle pasangan start/end yang berbeda namanya.
# ---------------------------------------------------------------------------
_PIPE_OPEN_RE = re.compile(
    r"<\|\s*(?:start_of_)?(?:thinking|thought|reasoning|analysis|cot)\s*\|>",
    re.IGNORECASE,
)
_PIPE_CLOSE_RE = re.compile(
    r"<\|\s*/?\s*(?:end_of_)?(?:thinking|thought|reasoning|analysis|cot)\s*\|>",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# 3. Blok bracket-style: [THINKING]...[/THINKING], [REASONING]...[/REASONING]
# ---------------------------------------------------------------------------
_bracket_names = "|".join(_REASONING_TAG_NAMES)
_BRACKET_BLOCK_RE = re.compile(
    rf"\[\s*(?:{_bracket_names})\s*\](.*?)\[\s*/\s*(?:{_bracket_names})\s*\]",
    re.IGNORECASE | re.DOTALL,
)

# ---------------------------------------------------------------------------
# 4. Blok komentar HTML: <!-- thinking -->...<!-- /thinking -->
# ---------------------------------------------------------------------------
_COMMENT_BLOCK_RE = re.compile(
    rf"<!--\s*(?:{_xml_names})\s*-->(.*?)<!--\s*/\s*(?:{_xml_names})\s*-->",
    re.IGNORECASE | re.DOTALL,
)


def _strip_pipe_blocks(text: str) -> str:
    """Hapus blok pipe-style <|thinking|>...</|thinking|> secara iteratif.

    Dipakai fungsi tersendiri karena pembuka/penutupnya bisa beda nama
    (start_of_thought vs end_of_thought), jadi tidak bisa diwakili satu
    regex simetris. Iterasi sampai tidak ada lagi pasangan terbuka.
    """
    while True:
        open_match = _PIPE_OPEN_RE.search(text)
        if not open_match:
            return text
        close_match = _PIPE_CLOSE_RE.search(text, open_match.end())
        if not close_match:
            # Ada pembuka tanpa penutup -- biarkan apa adanya (bukan blok
            # yang rapi), jangan hapus setengah.
            return text
        text = text[: open_match.start()] + text[close_match.end():]


def strip_reasoning_tags(text: str) -> str:
    """Hapus blok reasoning yang bocor sebagai teks biasa di dalam `content`.

    Menghapus blok yang well-formed (pembuka + penutup cocok) dari format:
    - XML-like: `<thinking>...</thinking>`, `<reasoning>...</reasoning>`
    - Pipe-style: `<|thinking|>...</|thinking|>`,
      `<|start_of_thought|>...</|end_of_thought|>`
    - Bracket-style: `[THINKING]...[/THINKING]`
    - HTML comment: `<!-- thinking -->...<!-- /thinking -->`

    Hanya blok yang tertutup rapi yang dihapus. Teks biasa yang memuat kata
    "thinking" sebagai topik TIDAK disentuh. Kalau tidak ada blok yang cocok,
    `text` dikembalikan apa adanya (no-op, aman dipanggil untuk setiap balasan
    model).
    """
    if not text:
        return text
    result = _XML_BLOCK_RE.sub("", text)
    result = _BRACKET_BLOCK_RE.sub("", result)
    result = _COMMENT_BLOCK_RE.sub("", result)
    result = _strip_pipe_blocks(result)
    return result.strip()


def has_reasoning_tags(text: str) -> bool:
    """True kalau `text` mengandung setidaknya satu blok reasoning yang
    well-formed (pembuka + penutup cocok). Berguna untuk diagnostik/debug."""
    if not text:
        return False
    if _XML_BLOCK_RE.search(text):
        return True
    if _BRACKET_BLOCK_RE.search(text):
        return True
    if _COMMENT_BLOCK_RE.search(text):
        return True
    # Pipe-style: butuh minimal satu pasangan terbuka+tertutup.
    open_m = _PIPE_OPEN_RE.search(text)
    if open_m and _PIPE_CLOSE_RE.search(text, open_m.end()):
        return True
    return False