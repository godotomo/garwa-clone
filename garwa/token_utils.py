"""
token_utils.py
Estimasi jumlah token tanpa perlu tokenizer asli model (Garwa pakai
SentencePiece, tapi kita tidak mau menambah dependency berat/besar hanya
untuk estimasi). Dipakai untuk keputusan "kapan harus summarize context".

Heuristik: untuk campuran kode+teks bahasa Inggris/Indonesia, rasio umum
adalah sekitar 3.3-4 karakter per token. Kita pakai 3.5 sebagai pertengahan
yang sedikit konservatif (estimasi token sedikit LEBIH BESAR dari kenyataan
lebih aman daripada under-estimate, karena tujuannya mencegah overflow).

Kalau paket `tiktoken` kebetulan terinstall, kita pakai itu untuk hasil
lebih presisi (walau bukan tokenizer asli Garwa, cukup dekat untuk tujuan
budgeting).
"""

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENC = None

CHARS_PER_TOKEN = 3.5


def count_tokens(text: str) -> int:
    if not text:
        return 0
    if _ENC is not None:
        try:
            return len(_ENC.encode(text, disallowed_special=()))
        except Exception:
            pass
    return max(1, int(len(text) / CHARS_PER_TOKEN))


def count_messages_tokens(messages: list) -> int:
    total = 0
    for m in messages:
        content = m.get("content", "")
        total += count_tokens(content) + 4  # overhead per pesan (role, separators)
    return total
