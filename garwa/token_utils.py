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

import hashlib
import json
import os
import threading

# PENTING (optimasi startup): `tiktoken` cukup berat untuk diimpor (~0.35s).
# Karena itu import dilakukan LAZY -- hanya saat count_tokens() pertama kali
# benar-benar membutuhkannya. Sebelum itu, _ENC tetap None dan dipakai
# heuristik fallback. Ini menghilangkan ~0.35s dari import `garwa.cli.main`.
_ENC = None
_ENC_LOADED = False
_ENC_LOCK = threading.Lock()


def _load_encoding() -> None:
    """Muat encoding tiktoken secara lazy (thread-safe, idempoten).

    Mengisi _ENC dengan objek encoding tiktoken, atau membiarkannya None
    bila tiktoken tidak tersedia / gagal dimuat. Hanya dijalankan sekali.
    """
    global _ENC, _ENC_LOADED

    if _ENC_LOADED:
        return
    with _ENC_LOCK:
        if _ENC_LOADED:
            return
        _ENC_LOADED = True
        try:
            import tiktoken

            enc_name = os.environ.get("GARWA_TIKTOKEN_ENCODING", "cl100k_base")
            _ENC = tiktoken.get_encoding(enc_name)
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


# Cache token untuk TEKS UTUH (bukan per-item payload JSON).
#
# Masalah: dalam satu giliran, string besar yang SAMA di-tokenisasi berulang
# kali -- system prompt + notes_block dan prior_summary dihitung di
# maybe_summarize(), lalu notes_block/summary juga ikut dihitung lagi saat
# giliran berikutnya (notes_block hanya berubah kalau catatan berubah).
# Terukur ~37 ms untuk system+notes dan ~33 ms untuk prior_summary per sesi;
# hampir semuanya terbuang karena isinya identik antar giliran.
#
# Solusi: simpan hasil tokenisasi per hash KONTEN (+ nama encoding, karena
# encoding berbeda = tokenisasi berbeda). Kunci memakai hash konten, BUKAN
# id(objek) -- id() tidak aman karena GC bisa me-reuse id untuk objek baru
# (lihat catatan yang sama di cache per-item di bawah).
#
# Nilai TIDAK berubah: cache hanya mememo hasil tokenisasi yang sama persis,
# jadi keputusan budget tetap identik dengan tanpa cache.
_TEXT_TOKENS_CACHE: dict = {}
_TEXT_TOKENS_LOCK = threading.Lock()
_TEXT_TOKENS_CACHE_MAX = 8192


def count_tokens(text: str) -> int:
    """Hitung jumlah token untuk satu string teks.

    Memakai tiktoken bila tersedia (wajib), fallback ke heuristik dinamis.
    Hasil di-cache per hash konten supaya teks yang sama (mis. notes_block,
    prior summary) tidak di-tokenisasi ulang setiap giliran.
    """
    if not text:
        return 0
    _load_encoding()
    key = (os.environ.get("GARWA_TIKTOKEN_ENCODING", "cl100k_base"),
           hashlib.md5(text.encode("utf-8", "surrogatepass")).hexdigest())
    with _TEXT_TOKENS_LOCK:
        cached = _TEXT_TOKENS_CACHE.get(key)
    if cached is not None:
        return cached
    if _ENC is not None:
        try:
            n = len(_ENC.encode(text, disallowed_special=()))
        except Exception:
            n = _fallback_count_tokens(text)
    else:
        n = _fallback_count_tokens(text)
    with _TEXT_TOKENS_LOCK:
        if len(_TEXT_TOKENS_CACHE) >= _TEXT_TOKENS_CACHE_MAX:
            _TEXT_TOKENS_CACHE.clear()
        _TEXT_TOKENS_CACHE[key] = n
    return n


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


# ---------------------------------------------------------------------------
# Cache token per-pesan + jalur cepat aditif untuk count_messages_tokens.
#
# Masalah: count_messages_tokens dipanggil berkali-kali per giliran atas
# payload yang sebagian besar isinya SAMA (riwayat percakapan hanya
# bertambah satu pesan tiap giliran). Meng-encode ulang seluruh daftar
# pesan setiap kali berarti biaya O(panjang total riwayat) per panggilan,
# padahal hampir semua item sudah pernah dihitung.
#
# Solusi: tokenisasi daftar pesan dipecah per-pesan lalu dijumlahkan. JSON
# payload berbentuk
#     "[" + m0 + ", " + m1 + ", " + ... + ", " + m_{n-1} + "]"
# Bila tiap item di-encode dengan pemisah ", " MENEMPEL di belakangnya,
# jumlah bagian-bagian itu LEBIH BESAR daripada tokenisasi utuh, karena
# pasangan ", {" yang tadinya menyatu jadi satu token kini terpisah oleh
# batas encode. Kelebihannya KONSTAN per batas:
#     C = tok(", ") + tok("{") - tok(", {")
# C diturunkan dari tokenizer saat runtime (bukan konstanta ajaib) dan
# diverifikasi sekali lewat self-test pada encoding yang aktif; kalau
# self-test gagal, jalur cepat otomatis dinonaktifkan (fallback eksak).
#
# Hasil verifikasi (repo ini, cl100k_base): fast path EKSAK pada 173 sesi /
# 87.671 pesan di DB produksi (n maksimum 7207 pesan) plus uji sintetis
# unicode/emoji/kode. Bentuk lain (item bukan dict, atau dict kosong)
# TIDAK memakai fast path -- langsung fallback ke tokenisasi JSON penuh,
# yang juga eksak.
#
# Kenapa key cache = hash KONTEN, bukan id(objek)? id() TIDAK aman: begitu
# objek di-GC, CPython bisa me-reuse id untuk objek baru -> collision ->
# token salah. Hash konten menghindari itu dan membuat item berisi sama
# (walau objek berbeda) berbagi cache.
#
# Thread-safety: sub-agent paralel bisa memanggil ini dari beberapa thread
# sekaligus, jadi semua akses cache dilindungi lock.
_MSG_ITEM_TOKENS_CACHE: dict = {}
_MSG_ITEM_TOKENS_LOCK = threading.Lock()
_MSG_ITEM_TOKENS_CACHE_MAX = 200_000

# None = belum dihitung; >= 0 = C terverifikasi; -1 = jalur cepat dinonaktifkan.
_FAST_CORRECTION = None
_FAST_CORRECTION_LOCK = threading.Lock()


# Cache token untuk potongan TEPI payload: head = "[" + s0 + ", " dan
# tail = s_{n-1} + "]". Keduanya hanya bergantung pada item itu sendiri, tapi
# SEBELUMNYA dihitung ulang setiap panggilan count_messages_tokens(): pada
# giliran normal item pertama SELALU system prompt (ribuan token) dan item
# terakhir selalu pesan user terakhir, jadi keduanya termasuk bagian termahal
# dari perhitungan (~6 ms/sesi terukur, dengan outlier sampai 726 ms ketika
# prompt besar). Di-cache per-hash-konten, sama seperti item tengah.
_MSG_EDGE_TOKENS_CACHE: dict = {}
_MSG_EDGE_TOKENS_LOCK = threading.Lock()
_MSG_EDGE_TOKENS_CACHE_MAX = 20_000


def _msg_edge_tokens(serialized: str, kind: str) -> int:
    """Token potongan tepi: head="["+s+", ", tail=s+"]", solo="["+s+"]".

    Hasil selalu identik dengan tokenisasi langsung (tidak ada aproksimasi),
    jadi nilai token tidak berubah -- hanya di-cache per hash konten item.
    """
    payload = (
        "[" + serialized + ", " if kind == "head"
        else "[" + serialized + "]" if kind == "solo"
        else serialized + "]"
    )
    key = (kind, hashlib.md5(serialized.encode("utf-8")).hexdigest())
    with _MSG_EDGE_TOKENS_LOCK:
        cached = _MSG_EDGE_TOKENS_CACHE.get(key)
    if cached is not None:
        return cached
    n = count_tokens(payload)
    with _MSG_EDGE_TOKENS_LOCK:
        if len(_MSG_EDGE_TOKENS_CACHE) >= _MSG_EDGE_TOKENS_CACHE_MAX:
            _MSG_EDGE_TOKENS_CACHE.clear()
        _MSG_EDGE_TOKENS_CACHE[key] = n
    return n


def _msg_item_tokens(serialized: str) -> int:
    """Token dari satu item pesan JSON dengan pemisah ", " menempel."""
    key = hashlib.md5(serialized.encode("utf-8")).hexdigest()
    with _MSG_ITEM_TOKENS_LOCK:
        cached = _MSG_ITEM_TOKENS_CACHE.get(key)
    if cached is not None:
        return cached
    n = count_tokens(serialized + ", ")
    with _MSG_ITEM_TOKENS_LOCK:
        if len(_MSG_ITEM_TOKENS_CACHE) >= _MSG_ITEM_TOKENS_CACHE_MAX:
            _MSG_ITEM_TOKENS_CACHE.clear()
        _MSG_ITEM_TOKENS_CACHE[key] = n
    return n


def _boundary_correction():
    """Derivasikan koreksi batas C untuk jalur cepat, atau None bila tidak
    bisa dipakai.

    C dihitung dari tokenizer pada encoding aktif, lalu DIVERIFIKASI dengan
    self-test kecil (payload 3 pesan realistis, dibandingkan dengan
    tokenisasi utuh). Kalau hasilnya tidak identik, jalur cepat
    dinonaktifkan supaya nilai token tidak pernah salah. Hasil di-cache.
    """
    global _FAST_CORRECTION
    if _FAST_CORRECTION is not None:
        return None if _FAST_CORRECTION < 0 else _FAST_CORRECTION
    with _FAST_CORRECTION_LOCK:
        if _FAST_CORRECTION is not None:
            return None if _FAST_CORRECTION < 0 else _FAST_CORRECTION
        c = -1
        try:
            c = count_tokens(", ") + count_tokens("{") - count_tokens(", {")
            probe = [
                json.dumps({"role": r, "content": t}, ensure_ascii=False)
                for r, t in (("system", "s"), ("user", "hello"),
                             ("assistant", "ok"), ("user", "lanjut"))
            ]
            exact = count_tokens("[" + ", ".join(probe) + "]")
            fast = (
                count_tokens("[" + probe[0] + ", ")
                + sum(count_tokens(p + ", ") for p in probe[1:-1])
                + count_tokens(probe[-1] + "]")
                - c * (len(probe) - 1)
            )
            if fast != exact:
                c = -1
        except Exception:
            c = -1
        _FAST_CORRECTION = c
        return None if c < 0 else c


def _count_messages_json_tokens(messages) -> int:
    """Token dari representasi JSON `messages` (tanpa overhead chat).

    Fast path: jumlah token per-pesan (di-cache) dikurangi koreksi batas.
    Fallback eksak: tokenisasi JSON penuh -- dipakai bila payload bukan
    daftar dict non-kosong, atau jalur cepat tidak bisa diverifikasi.
    """
    if not isinstance(messages, list) or not messages:
        return count_json_tokens(messages)
    # Gerbang bentuk: jalur cepat hanya untuk daftar dict NON-KOSONG (bentuk
    # yang selalu dihasilkan build_context_messages, {role, content, ...}).
    if not all(isinstance(m, dict) and m for m in messages):
        return count_json_tokens(messages)
    try:
        serialized = [json.dumps(m, ensure_ascii=False) for m in messages]
    except (TypeError, ValueError):
        return count_json_tokens(messages)
    if not all(s.startswith("{") and s.endswith("}") for s in serialized):
        return count_json_tokens(messages)
    correction = _boundary_correction()
    if correction is None:
        return count_tokens("[" + ", ".join(serialized) + "]")
    n = len(serialized)
    if n == 1:
        return _msg_edge_tokens(serialized[0], "solo")
    head = _msg_edge_tokens(serialized[0], "head")
    tail = _msg_edge_tokens(serialized[-1], "tail")
    mids = 0
    for s in serialized[1:-1]:
        mids += _msg_item_tokens(s)
    return head + mids + tail - correction * (n - 1)


def count_messages_tokens(messages: list) -> int:
    """Hitung jumlah token untuk satu daftar pesan OpenAI-chat.

    Strategi: encode SELURUH daftar pesan sebagai satu JSON string (persis
    seperti yang dikirim server dalam payload request), lalu tambahkan
    overhead chat template per pesan. Ini jauh lebih akurat daripada
    `len(content)/rasio + overhead tetap` karena:
    - menyertakan field `role`, `content`, dan struktur lain;
    - menangkap tokenisasi nyata dari karakter non-ASCII dan kode;
    - konsisten dengan cara `_tools_payload_tokens` menghitung payload tools.

    Selama payload berbentuk daftar dict non-kosong (bentuk yang selalu
    dihasilkan build_context_messages), hasil untuk setiap pesan dihitung
    lewat cache per-pesan + jalur cepat aditif yang EKSAK (lihat
    _count_messages_json_tokens). Untuk bentuk lain, fallback ke tokenisasi
    JSON penuh apa adanya (juga eksak, hanya lebih lambat).

    Kalau `messages` kosong, return 0.
    """
    if not messages:
        return 0
    total = _count_messages_json_tokens(messages)
    total += CHAT_TEMPLATE_OVERHEAD_PER_MESSAGE * len(messages)
    return total