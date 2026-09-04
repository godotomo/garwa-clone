"""
token_utils.py
Perhitungan jumlah token untuk budgeting context window.

PRIORITAS: memakai `tiktoken` (tokenizer BPE OpenAI) untuk estimasi token
yang JAUH lebih presisi daripada heuristik karakter-per-token. Ini
divajibkan karena:
- heuristik `len(text) / rasio` sangat kasar dan tidak konsisten antara
  kode, teks Indonesia, angka, dan whitespace;
- tiktoken memberi hasil yang mendekati tokenisasi server model modern
  (llama.cpp / OpenAI-compatible), cukup untuk keputusan "kapan summarize"
  dan "berapa yang boleh masuk context".

Kalau `tiktoken` tidak tersedia (mis. belum diinstall), kita jatuh ke
heuristik yang lebih baik daripada `len/3.5` saja: kita pakai rasio
dinamis berdasarkan proporsi whitespace/angka, supaya kode (banyak
whitespace) dan teks biasa dihitung lebih masuk akal. Namun fallback ini
hanya jalan darurat; `tiktoken` tetap yang utama.

Catatan encoding: `cl100k_base` (GPT-3.5/GPT-4) dipakai sebagai default
karena paling umum dan stabil. Untuk model dengan tokenizer 200k (mis.
GPT-4o/o1) bisa dipakai `o200k_base`; keduanya cukup dekat untuk tujuan
budgeting. Jika env `GARWA_TIKTOKEN_ENCODING` diisi, encoding itu yang
dipakai (mis. "o200k_base").
"""

import json
import os

try:
    import tiktoken

    _ENC_NAME = os.environ.get("GARWA_TIKTOKEN_ENCODING", "cl100k_base")
    _ENC = tiktoken.get_encoding(_ENC_NAME)
except Exception:
    _ENC = None

# Rasio karakter-per-token fallback (dipakai hanya kalau tiktoken tidak ada).
CHARS_PER_TOKEN = 3.5
# Overhead chat template server per pesan (mis. token `<|im_start|>` /
# `<|im_end|>` + role + separator yang ditambahkan server DI LUAR payload
# JSON). Nilai konservatif untuk llama.cpp / OpenAI-compatible.
CHAT_TEMPLATE_OVERHEAD_PER_MESSAGE = 4


def _fallback_count_tokens(text: str) -> int:
    """Heuristik fallback tanpa tiktoken.

    Lebih baik dari `len/3.5` polos: kode dan teks dengan banyak whitespace
    cenderung punya token per karakter lebih rendah, sementara teks padat
    (angka, simbol) lebih tinggi. Kita pakai rasio dinamis sederhana.
    """
    if not text:
        return 0
    n_chars = len(text)
    # Proporsi whitespace (spasi, tab, newline) -- kode/format punya banyak.
    ws = sum(1 for ch in text if ch.isspace())
    ws_ratio = ws / n_chars
    # Kode (banyak whitespace) -> rasio lebih longgar (lebih sedikit token
    # per karakter); teks padat -> rasio lebih ketat.
    if ws_ratio > 0.25:
        ratio = 4.2
    elif ws_ratio > 0.10:
        ratio = 3.8
    else:
        ratio = 3.2
    return max(1, int(n_chars / ratio))


def count_tokens(text: str) -> int:
    """Hitung jumlah token untuk satu string teks.

    Memakai tiktoken bila tersedia (wajib), fallback ke heuristik dinamis.
    """
    if not text:
        return 0
    if _ENC is not None:
        try:
            return len(_ENC.encode(text, disallowed_special=()))
        except Exception:
            pass
    return _fallback_count_tokens(text)


def count_json_tokens(obj) -> int:
    """Hitung token dari representasi JSON sebuah objek (dict/list).

    Dipakai untuk menghitung token payload `tools`, `messages`, dsb. yang
    dikirim ke server sebagai JSON -- persis seperti yang akan di-tokenisasi
    server, sehingga estimasi lebih akurat daripada sekadar konten teks.
    """
    if obj is None:
        return 0
    try:
        return count_tokens(json.dumps(obj, ensure_ascii=False))
    except Exception:
        return 0


def count_messages_tokens(messages: list) -> int:
    """Hitung jumlah token untuk satu daftar pesan OpenAI-chat.

    Strategi: encode SELURUH daftar pesan sebagai satu JSON string (persis
    seperti yang dikirim server dalam payload request), lalu tambahkan
    overhead chat template per pesan. Ini jauh lebih akurat daripada
    `len(content)/rasio + overhead tetap` karena:
    - menyertakan field `role`, `content`, dan struktur lain;
    - menangkap tokenisasi nyata dari karakter non-ASCII dan kode;
    - konsisten dengan cara `_tools_payload_tokens` menghitung payload tools.

    Kalau `messages` kosong, return 0.
    """
    if not messages:
        return 0
    total = count_json_tokens(messages)
    total += CHAT_TEMPLATE_OVERHEAD_PER_MESSAGE * len(messages)
    return total