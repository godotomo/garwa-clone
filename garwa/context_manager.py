"""
context_manager.py
Manajemen context window: menghitung token, memutuskan kapan meringkas
(summarize) riwayat lama, dan membangun ulang daftar `messages` yang
dikirim ke model LANGSUNG DARI DATABASE setiap giliran.

Strategi ringkas ala "summary + tail":
- Kalau sudah ada summary tersimpan (tabel `summaries`), pakai itu sebagai
  pembuka konteks, lalu sambung dengan pesan-pesan mentah SETELAH pesan
  terakhir yang sudah tercakup summary tsb.
- Kalau belum ada summary, pakai seluruh riwayat mentah.
- Setiap giliran, `maybe_summarize()` dipanggil dulu: kalau total token
  riwayat yang belum diringkas sudah melewati SUMMARIZE_THRESHOLD_RATIO
  dari context window, model diminta meringkas semua pesan lama (kecuali
  KEEP_TAIL_MESSAGES pesan terakhir) jadi satu paragraf ringkas.
"""

import functools
import hashlib
import heapq
import json
import logging
import math
import re
import sys
import threading
import time
from collections import Counter

from . import db as dbmod
from . import token_utils
from .cli.colors import C
from .cli.colors import c
from .cli.progress import ProgressBar

logger = logging.getLogger(__name__)

_requests = None


def _get_requests():
    """Lazy-import requests (hanya saat summarize/ringkasan benar-benar
    dipanggil) supaya startup CLI tidak memuat library berat requests
    (~300ms) kalau fitur ringkasan tidak dipakai. Konsisten dengan pola
    lazy-load di cli/llm_client/*."""
    global _requests
    if _requests is None:
        import requests
        _requests = requests
    return _requests

SUMMARIZE_THRESHOLD_RATIO = 0.2    # ringkas kalau pemakaian > 35% dari budget context
KEEP_TAIL_MESSAGES = 8              # jumlah pesan mentah terbaru yang selalu dipertahankan utuh
RESERVE_FOR_RESPONSE = 1024*2         # token yang disisakan untuk jawaban model + tool_result berikutnya
# Deprecated: dulu lantai `hard_budget` riwayat di prepare_context_messages().
# Sejak keputusan desain "tanpa trim" (pesan selalu dikirim apa adanya, budget
# riil ditangani agent_loop/server via ContextExceededError), hard_budget sudah
# tidak dihitung lagi. Konstanta dipertahankan agar import lama tidak pecah.
MIN_CONTEXT_WINDOW_HISTORY_FLOOR = 256  # tidak dipakai lagi
MIN_MESSAGES_TO_SUMMARIZE = KEEP_TAIL_MESSAGES + 4  # jangan ringkas kalau riwayat masih pendek

SUMMARIZE_REQUEST_TIMEOUT_SECONDS = 180

SUMMARIZE_MAX_RETRIES = 3          # total percobaan = 1 + SUMMARIZE_MAX_RETRIES
SUMMARIZE_RETRY_BASE_DELAY = 2.0   # detik, delay pertama; digandakan tiap retry
SUMMARIZE_RETRY_MAX_DELAY = 15.0   # batas atas delay antar-retry (detik)

# Batas input (karakter) untuk model ringkasan. Model ringkasan sama dengan
# model utama, jadi batas ini dipatok agar chunk ringkasan TIDAK overflow
# context window server -> error 400 -> ringkasan gagal total (bad-request
# BUKAN retryable). Default 100k karakter sebagai pengaman.
# Dinaikkan ke 300k agar chunk ringkasan besar (~0.3M karakter) tidak
# terpotong dari HEAD — memotong hanya akan membuang konteks penting.
# Tetap di bawah ~75k token (~300k karakter) agar aman untuk context
# window 128k+; model ringkasan sama dengan model utama.
SUMMARIZE_MAX_INPUT_CHARS = 300_000
# Rasio warning: log ke.debug kalau chunk mendekati/lewati batas input.
SUMMARIZE_WARN_RATIO = 0.9

# ---------------------------------------------------------------------------
# Batas blok "CATATAN PROYEK PERSISTEN" (tabel project_notes, ditulis via tool
# `remember`) yang disuntikkan ke system prompt SETIAP giliran.
#
# Masalah yang diatasi: catatan `remember` bersifat persisten lintas sesi dan
# TIDAK ikut diringkas, jadi jumlahnya terus bertambah dan biaya tetap per
# giliran membengkak (di proyek ini ~21 catatan = ~43k karakter = ~12.9k token).
#
# Strategi "tidak kehilangan konteks":
#   - SEMUA key catatan tetap disuntikkan (model tetap tahu catatan apa saja
#     yang ada, jadi tidak ada catatan yang hilang dari konteks).
#   - Catatan yang panjang dipangkas dari TENGAH (head + tail dipertahankan)
#     dengan penanda jelas "[…sisa dipangkas…]", bukan dari awal/akhir, agar
#     deskripsi (awal) dan kesimpulan/verifikasi (akhir) tetap utuh.
#   - Budget total dibagi merata ke semua catatan, sehingga tidak ada catatan
#     yang dikorbankan penuh demi catatan lain.
# ---------------------------------------------------------------------------
# Batas total blok catatan (karakter). ~12k karakter ≈ ~3.4k token (vs 43k
# sebelumnya). Sesuaikan bila perlu.
PROJECT_NOTES_MAX_TOTAL_CHARS = 12_000
# Batas atas per-catatan (karakter) sebelum dipangkas dari tengah.
PROJECT_NOTES_MAX_PER_NOTE_CHARS = 900
# Catatan yang lebih panjang dari ini akan diringkas via LLM (bukan di-trim)
# agar konteks penting tidak hilang. Nilai pendek = lebih banyak catatan
# diringkas, tapi lebih hemat token.
PROJECT_NOTES_SUMMARIZE_MIN_CHARS = 500


def _pairing_safe_split(rows: list, split_at: int) -> int:
    """Geser index pemisah `split_at` (rows[:split_at] vs rows[split_at:])
    supaya TIDAK PERNAH memisahkan pasangan tool_call/tool_result ke dua
    sisi yang berbeda. Setiap tool_call disimpan sebagai SATU baris
    `assistant` (kind="chat") langsung diikuti SATU baris `user`
    (kind="tool_result") di urutan `id`.

    Kalau rows[split_at] adalah tool_result, berarti tool_call pasangannya
    (rows[split_at-1]) jatuh ke sisi "lama" sementara tool_result-nya ke
    sisi "baru" -- geser split_at mundur sampai titik potong tidak lagi
    jatuh tepat sebelum tool_result mana pun, supaya pasangan tetap utuh.
    """
    while 0 < split_at < len(rows) and rows[split_at].get("kind") == "tool_result":
        split_at -= 1
    return split_at


#: Cache hasil hitung token tools_payload, keyed by hash konten (MD5 dari
#: serialisasi JSON). tools_payload dibangun SEKALI per sesi dan tidak dimutasi
#: antar giliran, jadi menghitung ulang json.dumps + count_tokens setiap
#: giliran (dipanggil 2x: budget & build_context) adalah buang-buang.
#:
#: Kenapa hash konten, bukan id(objek)? Cache berbasis id() TIDAK aman: begitu
#: objek di-GC, CPython bisa me-reuse id untuk objek baru, sehingga dua payload
#: berbeda bisa punya id sama -> collision -> nilai token yang salah. Hash
#: konten menghindari itu sepenuhnya: payload dengan isi sama berbagi cache,
#: payload berbeda selalu punya key berbeda (MD5 collision praktis mustahil).
#:
#: Thread-safety: sub-agent paralel (spawn_agents_parallel) bisa memanggil ini
#: dari beberapa thread sekaligus. dict biasa tidak aman untuk operasi set/get
#: bersamaan (race condition bisa kehilangan entry), jadi semua akses ke cache
#: dilindungi lock.
_TOOLS_PAYLOAD_TOKENS_CACHE: dict = {}
_TOOLS_PAYLOAD_TOKENS_LOCK = threading.Lock()


def _tools_payload_tokens(tools_payload) -> int:
    """Hitung berapa token yang dipakai field `"tools"` ala OpenAI kalau
    disertakan di request (lihat build_openai_tools_payload() di cli.py).
    Server juga menghitung token `"tools"` sebagai bagian dari prompt, jadi
    budget harus memperhitungkannya untuk menghindari ContextExceededError.

    Dihitung dari representasi JSON-nya (persis seperti yang akan dikirim
    di payload), bukan diestimasi. Return 0 kalau tools_payload kosong/None.
    Hasil di-cache per-konten (lihat _TOOLS_PAYLOAD_TOKENS_CACHE) sehingga
    tidak dihitung ulang setiap giliran. Thread-safe (dilindungi lock).
    """
    if not tools_payload:
        return 0
    # Serialisasi untuk KEY cache: urutan kunci distabilkan + compact supaya
    # payload dengan isi sama (walau urutan field beda) berbagi cache. Ini
    # TIDAK dipakai untuk menghitung token (lihat di bawah).
    try:
        key_serialized = json.dumps(
            tools_payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        # Payload tidak bisa diserialisasi -> hitung langsung tanpa cache.
        try:
            return token_utils.count_tokens(json.dumps(tools_payload, ensure_ascii=False))
        except Exception:
            return 0
    key = hashlib.md5(key_serialized.encode("utf-8")).hexdigest()
    with _TOOLS_PAYLOAD_TOKENS_LOCK:
        cached = _TOOLS_PAYLOAD_TOKENS_CACHE.get(key)
        if cached is not None:
            return cached
    # Hitung token dari serialisasi DEFAULT (json.dumps tanpa sort_keys, dengan
    # spasi) -- persis representasi yang dikirim ke server via `json=payload`
    # (httpx/_requests memakai json.dumps default). Ini menjamin estimasi token
    # akurat terhadap apa yang benar-benar dihitung server.
    try:
        wire_serialized = json.dumps(tools_payload, ensure_ascii=False)
        n = token_utils.count_tokens(wire_serialized)
    except Exception:

        return 0
    with _TOOLS_PAYLOAD_TOKENS_LOCK:
        _TOOLS_PAYLOAD_TOKENS_CACHE[key] = n
    return n

SUMMARIZE_SYSTEM = (
    "Anda adalah asisten yang meringkas riwayat percakapan dari sebuah coding-agent "
    "CLI (mirip coding-agent CLI pada umumnya). Ringkas riwayat berikut sepadat mungkin, "
    "TAPI ikuti aturan berikut dengan TEPAT:\n\n"
    "ATURAN 1 - SALIN VERBATIM (WAJIB, jangan diringkas/diparafrase):\n"
    "  - Setiap INSTRUKSI, aturan, preferensi, atau permintaan dari user yang MASHI "
    "    AKTIF / belum selesai dikerjakan. Salin kata-per-kata dalam tanda kutip.\n"
    "  - Setiap keputusan arsitektur/desain yang sudah disepakati.\n"
    "  - Setiap format/protokol/konvensi yang harus diikuti (mis. format output, "
    "    aturan pemanggilan tool, struktur file).\n"
    "  - Setiap catatan atau kesimpulan yang ditandai penting oleh model/asisten "
    "    (mis. yang diawali 'CATATAN:', 'PENTING:', atau sejenisnya).\n\n"
    "ATURAN 2 - RINGKAS (boleh dipadatkan, tapi inti wajib utuh):\n"
    "  - File yang sudah dibaca/ditulis/diedit beserta inti perubahannya.\n"
    "  - Hasil penting dari perintah bash/tool (mis. error yang belum selesai "
    "    ditangani, output test yang relevan).\n"
    "  - Task/plan yang masih berjalan atau belum selesai.\n\n"
    "ATURAN 3 - LARANGAN:\n"
    "  - JANGAN menambahkan opini, instruksi baru, atau tool_call baru -- ini murni "
    "    ringkasan naratif.\n"
    "  - JANGAN menghilangkan instruksi aktif walau terasa panjang; lebih baik "
    "    ringkasan sedikit lebih panjang daripada kehilangan instruksi penting.\n\n"
    "FORMAT OUTPUT (WAJIB JSON, tidak boleh teks lain di luar JSON):\n"
    "Kembalikan SATU objek JSON dengan dua field:\n"
    "  {\n"
    "    \"narasi\": \"<ringkasan naratif bebas berisi ATURAN 2, poin-poin singkat berbahasa Indonesia>\",\n"
    "    \"instruksi_aktif\": [\"<verbatim ATURAN 1 item 1>\", \"<verbatim ATURAN 1 item 2>\", ...]\n"
    "  }\n"
    "Aturan:\n"
    "  - Setiap item ATURAN 1 (instruksi aktif yang masih berlaku, keputusan desain, "
    "    format/protokol/konvensi yang harus diikuti, catatan penting) disalin "
    "    KATA-PER-KATA dalam satu string di array `instruksi_aktif`.\n"
    "  - Kalau tidak ada instruksi aktif, `instruksi_aktif` boleh berupa array kosong [].\n"
    "  - `narasi` berisi ringkasan ATURAN 2 (file/hasil tool/plan yang belum selesai).\n"
    "  - JANGAN menaruh instruksi aktif di dalam `narasi`; taruh di `instruksi_aktif`.\n"
    "  - JANGAN membungkus JSON dengan ```fence``` atau teks penjelasan apa pun."
)

# Prompt untuk meringkas SATU catatan proyek persisten (`remember`) via LLM.
# Berbeda dari SUMMARIZE_SYSTEM (yang meringkas riwayat percakapan), prompt ini
# khusus meringkas catatan teknis/desain agar konteks penting TIDAK hilang saat
# catatan panjang disuntikkan ke system prompt setiap giliran. Output berupa
# teks ringkasan padat (bukan JSON) yang mempertahankan inti, keputusan desain,
# dan kesimpulan/verifikasi.
NOTE_SUMMARIZE_SYSTEM = (
    "Anda adalah asisten yang meringkas SATU catatan proyek persisten (ditulis "
    "via tool `remember` oleh coding-agent CLI) menjadi ringkasan PADAT untuk "
    "disuntikkan ke konteks model setiap giliran.\n\n"
    "Tujuan: mengurangi biaya token, TAPI JANGAN kehilangan konteks penting.\n\n"
    "ATURAN:\n"
    "1. Pertahankan SEMUA informasi penting: keputusan desain/arsitektur, "
    "   angka/versi/konstanta kunci, hasil verifikasi, peringatan/jebakan, "
    "   instruksi yang masih aktif, dan kesimpulan.\n"
    "2. Buang hanya detail yang redundan/pengulangan, contoh ilustratif yang "
    "   panjang, atau catatan prosedural yang sudah jelas dari konteks.\n"
    "3. Output berupa SATU paragraf ringkas (maksimal ~350 kata) dalam bahasa "
    "   Indonesia, tanpa JSON, tanpa markdown heading, tanpa teks pengantar.\n"
    "4. Kalau catatan berisi banyak poin terstruktur, pertahankan poin-poinnya "
    "   tapi padatkan tiap poin.\n"
)


def _trim_note_middle(value: str, max_chars: int) -> str:
    """Pangkas isi catatan dari TENGAH (head + tail dipertahankan) agar konteks
    awal (deskripsi) dan akhir (kesimpulan/verifikasi) tidak hilang.

    Strategi ini dipilih supaya "tidak kehilangan konteks": memotong dari awal
    atau akhir berisiko membuang bagian penting (mis. keputusan desain di akhir
    atau judul di awal). Memotong dari tengah menjaga kedua ujung tetap utuh.
    """
    if len(value) <= max_chars:
        return value
    if max_chars <= 40:
        return value[: max_chars // 2] + "…"
    head = max_chars // 2
    tail = max_chars - head
    return value[:head] + "\n[…sisa dipangkas…]\n" + value[-tail:]


# ---------------------------------------------------------------------------
# Fallback cerdas: extractive summarization berbasis sentence scoring
# (diadaptasi dari pendekatan TextDigest -- pure Python, stdlib only).
# Dipakai ketika ringkasan LLM (kolom `summary`) belum tersedia / gagal.
# Alih-alih memotong mentah dari tengah (yang bisa membuang kalimat penting),
# fallback ini MEMILIH kalimat paling informatif dan menyusunnya kembali
# dalam urutan asli -- jadi konteks penting dipertahankan secara context-aware.
# ---------------------------------------------------------------------------

# Kata yang hampir tidak membawa makna (dipakai untuk tokenisasi ringan).
_NOTE_STOPWORDS = {
    "a", "about", "above", "after", "again", "all", "also", "am", "an", "and",
    "any", "are", "as", "at", "be", "because", "been", "before", "being", "but",
    "by", "can", "did", "do", "does", "down", "during", "each", "few", "for",
    "from", "had", "has", "have", "having", "he", "her", "here", "him", "his",
    "how", "i", "if", "in", "into", "is", "it", "its", "just", "me", "more",
    "most", "my", "no", "nor", "not", "now", "of", "off", "on", "once", "only",
    "or", "other", "our", "out", "over", "own", "same", "she", "should", "so",
    "some", "such", "than", "that", "the", "their", "them", "then", "there",
    "these", "they", "this", "those", "through", "to", "too", "under", "until",
    "up", "very", "was", "we", "were", "what", "when", "where", "which", "while",
    "who", "why", "will", "with", "you", "your", "yang", "dan", "ke", "dari",
    "ini", "itu", "untuk", "dengan", "pada", "di", "adalah", "tidak", "akan",
    "juga", "sudah", "telah", "agar", "supaya", "bila", "kalau", "jika", "saat",
}

# Penanda penting: kalimat yang mengandung salah satunya diberi bobot ekstra
# karena biasanya memuat keputusan/instruksi/verifikasi yang wajib dipertahankan.
_NOTE_IMPORTANT_MARKERS = (
    "penting", "catatan", "wajib", "jangan", "harus", "jebakan", "verifikasi",
    "terbukti", "berhasil", "selesai", "keputusan", "konvensi", "hasil terukur",
    "constraints", "jangan lupa", "perhatian", "bug", "fix", "jangan dilanggar",
    "kompatibilitas", "hati-hati",
)

# Kata/frasa yang menandakan baris adalah bagian dari poin terstruktur (bullet).
_NOTE_BULLET_MARKERS = ("- ", "* ", "• ", "1. ", "2. ", "3. ", "4. ", "5. ",
                        "6. ", "7. ", "8. ", "9. ", "0. ")

# Stopword khusus skor relevansi catatan (query user terakhir). Dikonstankan di
# level modul supaya tidak dibangun ulang tiap panggilan -- sebelumnya himpunan
# ini di-construct di dalam _note_relevance_score yang dipanggil sekali per
# catatan per giliran (84x/giliran pada proyek besar).
_NOTE_QUERY_STOPWORDS = frozenset({
    "yang", "dengan", "untuk", "dari", "pada", "adalah", "agar", "dalam",
    "tidak", "sudah", "akan", "harus", "bisa", "kalau", "maka", "jika",
    "karena", "setelah", "sebelum", "the", "and", "for", "with", "that",
    "this", "what", "how", "when", "where", "why", "are", "was", "not",
    "but", "you", "your", "have", "has", "into", "about", "them", "then",
    "they", "there", "their", "from", "than", "also", "just", "make",
    "please", "code", "file", "fix", "add", "need",
})


@functools.lru_cache(maxsize=8192)
def _note_tokenize(sentence: str) -> tuple:
    """Lowercase + ekstrak kata bermakna (buang stopword & kata pendek).

    Di-cache: kalimat yang sama di-tokenisasi berkali-kali lintas giliran
    (skoring per-catatan per-giliran). Mengembalikan tuple (immutable) agar
    aman dibagikan antar pemanggil.
    """
    words = re.findall(r"[a-z0-9_]+", sentence.lower())
    return tuple(w for w in words if w not in _NOTE_STOPWORDS and len(w) > 2)


@functools.lru_cache(maxsize=2048)
def _note_sentences(value: str) -> tuple:
    """Pecah catatan jadi daftar (kalimat, posisi_awal) dengan heuristik.

    Catatan `remember` sering berupa poin terstruktur (bullet) yang tidak
    selalu berakhir dengan titik. Kita pecah per baris kalau barisnya pendek
    (terlihat seperti bullet/poin), dan per kalimat (. ! ?) untuk teks
    mengalir. Posisi awal dipakai untuk menyusun ulang dalam urutan asli.
    """
    result = []
    cursor = 0
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            cursor += len(raw_line) + 1
            continue
        if _NOTE_BULLET_MARKERS and any(line.startswith(m) for m in _NOTE_BULLET_MARKERS):
            # Baris bullet: perlakukan seluruh baris sebagai satu "kalimat".
            result.append((line, cursor))
            cursor += len(raw_line) + 1
        else:
            # Teks mengalir: pecah per kalimat. Setiap kalimat diberi posisi
            # inkremental (cursor + offset) agar urutan asli tetap terjaga
            # saat disusun ulang -- kalimat dalam satu baris tidak boleh
            # berbagi posisi yang sama.
            offset = 0
            for sent in re.split(r"(?<=[.!?])\s+", line):
                if len(sent.split()) > 2:  # buang fragmen 1-2 kata (noise)
                    result.append((sent, cursor + offset))
                    offset += 1
            cursor += len(raw_line) + 1 + offset
    # Gabungkan kalimat yang sangat pendek (<=2 kata) ke kalimat berikutnya?
    # Tidak perlu -- buang saja yang <=2 kata, itu biasanya heading/noise.
    return tuple(result)


def _note_score_sentences(sentences: list) -> list:
    """Berikan skor ke tiap (kalimat, posisi) berbasis word-frequency + bobot
    penanda penting. Kembalikan list (skor, posisi, kalimat) yang sudah diurut.
    """
    counts = Counter()
    for sent, _pos in sentences:
        counts.update(_note_tokenize(sent))
    if not counts:
        return []
    most_common = max(counts.values())
    word_scores = {w: c / most_common for w, c in counts.items()}

    scored = []
    for sent, pos in sentences:
        words = _note_tokenize(sent)
        if not words:
            continue
        # Skor dasar: jumlah bobot kata / sqrt(panjang) supaya kalimat panjang
        # tidak menang hanya karena panjang (pola TextDigest).
        base = sum(word_scores.get(w, 0) for w in words) / math.sqrt(len(words))
        # Bonus untuk kalimat yang memuat penanda penting.
        low = sent.lower()
        if any(m in low for m in _NOTE_IMPORTANT_MARKERS):
            base *= 1.5
        scored.append((base, pos, sent))
    return scored


@functools.lru_cache(maxsize=2048)
def _extractive_summarize_note(value: str, max_chars: int) -> str:
    """Fallback cerdas: pilih kalimat paling informatif (extractive) lalu
    susun ulang dalam urutan asli, dibatasi `max_chars`.

    Ini menggantikan pemangkasan mentah dari tengah: alih-alih membuang
    bagian tengah, kita MEMILIH kalimat-kalimat yang paling padat informasi
    (termasuk yang bertanda PENTING/CATATAN/WAJIB) dan mempertahankannya,
    sehingga konteks penting tetap utuh secara context-aware.
    """
    if len(value) <= max_chars:
        return value
    sentences = _note_sentences(value)
    if not sentences:
        return _trim_note_middle(value, max_chars)

    scored = _note_score_sentences(sentences)
    if not scored:
        return _trim_note_middle(value, max_chars)

    # Ambil kalimat ber-skor tertinggi sampai muat dalam budget.
    ordered = sorted(scored, reverse=True)
    chosen = []
    budget = max_chars
    for _score, _pos, sent in ordered:
        if len(sent) + 1 > budget:
            continue
        chosen.append((_pos, sent))
        budget -= len(sent) + 1
    if not chosen:
        # Kalimat terpanjang pun tak muat: ambil kalimat skor tertinggi,
        # pangkas dari tengah sebagai jaring pengaman terakhir.
        best = ordered[0][2]
        return _trim_note_middle(best, max_chars)

    # Susun ulang dalam urutan asli supaya ringkasan tetap mengalir.
    chosen.sort(key=lambda item: item[0])
    return " ".join(sent for _pos, sent in chosen)


def _summarize_note_text(url: str, model: str, note_text: str, api_key: str = "") -> str:
    """Ringkas SATU catatan via LLM menjadi ringkasan padat (plain text).

    Mengembalikan teks ringkasan. Kalau gagal (server error / response tidak
    valid), kembalikan string kosong agar pemanggil bisa fallback ke trim.
    """
    if not note_text.strip():
        return ""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": NOTE_SUMMARIZE_SYSTEM},
            {"role": "user", "content": note_text},
        ],
        "temperature": 0.2,
        "stream": False,
    }
    try:
        resp = _get_requests().post(
            url, json=payload, headers=_auth_headers(api_key),
            timeout=SUMMARIZE_REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return (content or "").strip()
    except Exception:  # noqa: BLE001 - ringkasan catatan opsional, jangan crash
        logger.warning("gagal meringkas catatan via LLM", exc_info=True)
        return ""


def _ensure_note_summaries(db_path: str, session_id: str, url: str, model: str,
                           api_key: str = "", force: bool = False) -> None:
    """Ringkas catatan `remember` yang panjang via LLM dan simpan ke kolom
    `summary` (sekali per catatan). Dipanggil di awal prepare_context_messages
    sehingga _project_notes_section bisa memakai ringkasan LLM (bukan trim)
    untuk catatan panjang -- konteks penting tidak hilang.

    Catatan yang sudah punya `summary` TIDAK diringkas ulang (hemat biaya).
    `force=True` memaksa ringkas ulang (mis. untuk pengujian). Catatan pendek
    (<= PROJECT_NOTES_SUMMARIZE_MIN_CHARS) tidak perlu diringkas.
    """
    try:
        session = dbmod.get_session(db_path, session_id)
        if not session:
            return
        workdir = session.get("workdir") or ""
        notes = dbmod.get_notes(db_path, workdir)
    except Exception:
        logger.warning("gagal membaca project_notes untuk ringkasan session_id=%s",
                       session_id, exc_info=True)
        return
    for note in notes:
        key = note.get("key") or ""
        value = note.get("value") or ""
        if not value.strip():
            continue
        if len(value) <= PROJECT_NOTES_SUMMARIZE_MIN_CHARS:
            continue
        if not force and (note.get("summary") or "").strip():
            continue  # sudah diringkas sebelumnya
        summary = _summarize_note_text(url, model, value, api_key=api_key)
        if summary:
            dbmod.set_note_summary(db_path, workdir, key, summary)


@functools.lru_cache(maxsize=512)
def _note_query_tokens(query_lower: str) -> tuple:
    """Token bermakna dari query (sudah di-lowercase). Hasil di-cache: query
    sama dipakai ulang untuk SEMUA catatan pada giliran yang sama, jadi
    tokenisasi ini cukup sekali per giliran (bukan per catatan)."""
    return tuple(
        t for t in re.findall(r"[a-z0-9_]+", query_lower)
        if len(t) >= 4 and t not in _NOTE_QUERY_STOPWORDS
    )


@functools.lru_cache(maxsize=4096)
def _note_corpus_tokens(key_lower: str, value_lower: str) -> frozenset:
    """Himpunan token catatan (key+value, lowercase). Di-cache karena catatan
    yang sama di-skor berulang kali antar giliran (dan di dalam satu giliran
    bila section dibangun beberapa kali)."""
    return frozenset(re.findall(r"[a-z0-9_]+", f"{key_lower} {value_lower}"))


@functools.lru_cache(maxsize=4096)
def _note_key_tokens(key_lower: str) -> frozenset:
    """Token khusus bagian key (untuk bonus kecocokan key). Di-cache idem."""
    return frozenset(re.findall(r"[a-z0-9_]+", key_lower))


@functools.lru_cache(maxsize=4096)
def _note_corpus_text(key_lower: str, value_lower: str) -> str:
    """Token corpus digabung dengan spasi, untuk uji cepat "apakah token query
    muncul sebagai substring SEBUAH token corpus".

    Kenapa aman (tidak ada false positive lintas-token): token hanya berisi
    [a-z0-9_], sedangkan separator adalah spasi. Token query juga hanya
    [a-z0-9_], jadi ia tidak mungkin melintasi batas spasi antar token corpus.
    Dengan ini, `any(t in c for c in corpus_tokens)` bisa diganti satu operasi
    `t in corpus_text` alih-alih loop generator panjang (bottleneck profil).
    """
    return " ".join(_note_corpus_tokens(key_lower, value_lower))


@functools.lru_cache(maxsize=4096)
def _note_key_text(key_lower: str) -> str:
    """Versi teks bagian key (token dipisah spasi) untuk uji substring cepat."""
    return " ".join(_note_key_tokens(key_lower))


# Panjang maksimum token yang boleh dipecah jadi semua substring (O(len^2)).
# Token normal (kata, identifier) jauh di bawah ini; yang melewatinya biasanya
# hash/base64/base36 tanpa spasi, dan untuk itu enumerasi substring jadi mahal
# -> pakai fallback loop langsung.
_SUBTOKEN_MAX_LEN = 24


@functools.lru_cache(maxsize=8192)
def _subtoken_forms(token: str) -> frozenset:
    """Semua substring `token` (termasuk token itu sendiri), sebagai frozenset.

    Dipakai untuk menjawab "adakah token corpus yang menjadi substring token
    query ini" (`c in t`) tanpa mengulang loop atas SELURUH token corpus di
    setiap query token: cukup `not _subtoken_forms(t).isdisjoint(corpus)`.
    `set.isdisjoint` berjalan di level C, jadi jauh lebih murah daripada
    generator Python per query token (bottleneck pada profil: 1,8 juta
    panggilan genexpr).

    Jumlah bentuk hanya O(len^2) dan hanya dipanggil untuk token pendek
    (<= _SUBTOKEN_MAX_LEN), tetapi hasilnya tetap di-cache karena fungsi ini
    dipanggil berulang tiap giliran dengan query token yang sama.
    """
    n = len(token)
    return frozenset(token[i:j] for i in range(n) for j in range(i + 1, n + 1))


def _partial_token_match(token: str, corpus: frozenset, corpus_text: str) -> bool:
    """True bila ada token corpus yang memuat `token`, ATAU token corpus yang
    menjadi substring `token` -- bentuk partial match di `_note_relevance_score`.

    Dua jalur, keduanya EKSA dan menghasilkan boolean yang sama:
    - `token in corpus_text`: ada token corpus yang MEMUAT token (uji substring
      di level C; aman karena separatornya spasi dan token hanya [a-z0-9_]).
    - `not _subtoken_forms(token).isdisjoint(corpus)`: ada token corpus yang
      MENJADI substring token, juga diuji di level C lewat himpunan.
    Untuk token yang sangat panjang (mis. hash), enumerasi substring dibatasi
    demi memori dan diganti loop langsung -- hasilnya tetap sama.
    """
    if token in corpus_text:
        return True
    if len(token) <= _SUBTOKEN_MAX_LEN:
        return not _subtoken_forms(token).isdisjoint(corpus)
    return any(c in token for c in corpus)


def _note_relevance_score(note: dict, query: str) -> float:
    """Skor relevansi sebuah catatan terhadap query (teks user terakhir).

    Memakai kombinasi murah & deterministik (tanpa embedding/LLM):
      1. Jaccard similarity antara token catatan (key+value) dan token query
         -- lebih baik daripada hit/miss mentah karena menormalisasi panjang.
      2. Partial token match (prefix/substring) untuk menangkap kata yang
         hanya sebagian cocok (mis. query "repo_map" vs catatan "repo_mapping").
      3. Bobot ekstra untuk kecocokan di KEY (lebih penting daripada value).

    Tujuannya bukan presisi sempurna, melainkan MENURUNKAN biaya tetap dengan
    memberi budget lebih besar ke catatan yang tampaknya relevan dengan
    pertanyaan saat ini, sambil memastikan catatan yang jelas tidak relevan
    hanya menampilkan key-nya.

    Catatan performa: tokenisasi query/catatan di-cache (lihat
    _note_query_tokens/_note_corpus_tokens/_note_key_tokens) supaya fungsi ini
    yang dipanggil sekali per catatan per giliran tidak mengulang regex.
    """
    if not query.strip():
        return 0.0
    key = (note.get("key") or "").lower()
    value = (note.get("value") or "").lower()
    q_tokens = _note_query_tokens(query.lower())
    if not q_tokens:
        return 0.0
    corpus_tokens = _note_corpus_tokens(key, value)
    if not corpus_tokens:
        return 0.0

    # Teks token (dipisah spasi) sekali per catatan: uji "t adalah substring
    # SEBUAH token corpus" jadi satu operasi `in` pada string, bukan loop
    # generator atas korpus (bottleneck utama pada profil -- 1,8 juta panggilan
    # genexpr per benchmark). Aman karena token hanya [a-z0-9_] dan tidak
    # mungkin melintasi separator spasi.
    corpus_text = _note_corpus_text(key, value)
    key_text = _note_key_text(key)

    # 1) Exact token overlap (Jaccard) antara query dan corpus.
    exact_hits = sum(1 for t in q_tokens if t in corpus_tokens)
    union = len(set(q_tokens) | corpus_tokens)
    jaccard = exact_hits / union if union else 0.0

    # 2) Partial match: query token yang muncul sebagai prefix/substring token
    #    corpus (atau sebaliknya). Menangkap infleksi/varian nama.
    #    `t in corpus_text`  -> ada token corpus yang MEMUAT t (t in c).
    #    `not _subtoken_forms(t).isdisjoint(corpus_tokens)` -> ada token corpus
    #    yang MENJADI substring t (c in t), diuji di level C lewat set.
    partial_hits = 0
    for t in q_tokens:
        if _partial_token_match(t, corpus_tokens, corpus_text):
            partial_hits += 1
    partial = partial_hits / len(q_tokens)

    # 3) Key match: query token yang muncul di key (bobot ekstra).
    key_tokens = _note_key_tokens(key)
    key_hits = sum(
        1
        for t in q_tokens
        if t in key_tokens or _partial_token_match(t, key_tokens, key_text)
    )
    key_frac = key_hits / len(q_tokens)

    # Gabungan: Jaccard dominan, partial menaikkan, key memberi bonus.
    score = jaccard * 1.0 + partial * 0.4 + key_frac * 0.6
    return score


def _project_notes_section(db_path: str, session_id: str) -> str:
    """Bangun blok teks berisi catatan proyek persisten (tabel project_notes,
    ditulis via tool `remember`) untuk workdir sesi ini.

    Catatan ini persisten lintas sesi dan TIDAK ikut diringkas/dibuang oleh
    summarization, jadi menyuntikkannya ke system prompt setiap giliran
    menjamin instruksi/preferensi/keputusan yang disimpan via `remember`
    tetap tampil utuh di konteks model -- tidak hilang walau riwayat
    percakapan sudah diringkas berkali-kali.

    Poin #6 rilis v0.5.0 (Retrieval-based notes): untuk menurunkan biaya
    tetap per giliran, catatan diurutkan berdasarkan RELEVANSI terhadap pesan
    user terakhir (via _note_relevance_score). Catatan yang relevan mendapat
    budget penuh (value/ringkasan utuh), sedangkan catatan yang jelas tidak
    relevan hanya menampilkan KEY-nya (model tetap tahu catatan itu ada,
    tapi value tidak memakan token). Ini mempertahankan keputusan desain
    "SEMUA key catatan tetap disuntikkan" sambil mengurangi biaya value yang
    tidak relevan.

    Pembatasan tetap berlaku: total blok dibatasi PROJECT_NOTES_MAX_TOTAL_CHARS
    dan per-catatan PROJECT_NOTES_MAX_PER_NOTE_CHARS.
    """
    try:
        session = dbmod.get_session(db_path, session_id)
        if not session:
            return ""
        notes = dbmod.get_notes(db_path, session.get("workdir") or "")
    except Exception:
        logger.warning("gagal membaca project_notes untuk session_id=%s", session_id, exc_info=True)
        return ""
    if not notes:
        return ""

    # --- Retrieval: ambil pesan user terakhir sebagai query relevansi ---
    # Pakai query terarah (LIMIT 1) alih-alih get_all_messages() yang menarik
    # seluruh riwayat hanya untuk satu pesan -- hemat query DB per giliran.
    query = ""
    try:
        last = dbmod.get_last_user_message(db_path, session_id)
        query = last.get("content") or ""
    except Exception:
        query = ""

    # Render blok ada di fungsi MURNI terpisah (di-cache) supaya pemanggilan
    # berulang dalam satu giliran -- build_context_messages(), maybe_summarize(),
    # dan build ulang saat retry budget -- tidak mengulang pekerjaan berat.
    # Data catatan dinormalkan ke tuple-of-tuple (hashable) sebagai bagian kunci
    # cache, jadi tidak ada risiko tabrakan hash: data berubah -> kunci berubah.
    notes_data = tuple(
        (
            n.get("key") or "",
            n.get("value") or "",
            n.get("summary") or "",
            n.get("updated_at") or 0,
        )
        for n in notes
    )
    return _render_notes_block(notes_data, query)


@functools.lru_cache(maxsize=8)
def _render_notes_block(notes_data: tuple, query: str) -> str:
    """Render blok catatan proyek (murni, tanpa I/O) -- lihat
    `_project_notes_section` untuk dokumentasi perilaku lengkapnya."""
    notes = [
        {"key": k, "value": v, "summary": s, "updated_at": u}
        for (k, v, s, u) in notes_data
    ]

    # Urutkan catatan: relevan dulu, lalu tetap dalam urutan updated_at DESC
    # sebagai tie-breaker (catatan terbaru lebih relevan).
    scored = []
    for note in notes:
        score = _note_relevance_score(note, query)
        scored.append((score, note))
    scored.sort(key=lambda x: (x[0], x[1].get("updated_at") or 0), reverse=True)

    # Pass 1: budget total dibagi merata ke semua catatan, tapi tidak melebihi
    # batas per-catatan. Catatan yang lebih pendek dari jatahnya menyisakan
    # ruang yang bisa dipakai catatan lain.
    n = len(notes)
    per_note_budget = max(
        PROJECT_NOTES_MAX_TOTAL_CHARS // n,
        40,
    )
    per_note_budget = min(per_note_budget, PROJECT_NOTES_MAX_PER_NOTE_CHARS)
    lines = []
    for score, note in scored:
        key = note.get("key") or ""
        value = note.get("value") or ""
        # Poin #6: catatan yang TIDAK relevan (skor 0) hanya menampilkan key,
        # bukan value -- hemat token tanpa menyembunyikan keberadaan catatan.
        if score <= 0.0 and query.strip():
            lines.append(f"- {key}: (tidak relevan dengan pertanyaan saat ini)")
            continue
        # Prioritas: pakai ringkasan LLM (kolom `summary`) bila tersedia,
        # karena itu mempertahankan konteks penting tanpa kehilangan inti.
        # Fallback ke pemangkasan dari tengah hanya untuk catatan yang belum
        # sempat diringkas (mis. LLM summarize belum dijalankan / gagal).
        summary = note.get("summary") or ""
        if summary.strip():
            display = summary.strip()
        else:
            display = _extractive_summarize_note(value, per_note_budget)
        lines.append(f"- {key}: {display}")

    # Pass 2: pastikan total blok (termasuk prefix "- key:") benar-benar tidak
    # melebihi PROJECT_NOTES_MAX_TOTAL_CHARS. Kalau masih lewat, pangkas lagi
    # catatan TERPANJANG dulu (berulang) sampai muat. Ini menjaga batas total
    # tetap dihormati walau ada banyak key panjang.
    header = (
        "\n\nCATATAN PROYEK PERSISTEN (disimpan user/model via tool `remember`, "
        "jangan dianggap usang walau riwayat sudah diringkas):\n"
    )
    total = len(header) + sum(len(l) for l in lines)
    # Heap baris terpanjang: menghindari `max(range(n), key=len)` yang O(n)
    # tiap iterasi (O(n^2) total; profil lama: 604k panggilan lambda).
    # Entri disimpan sebagai (-panjang, indeks) supaya pada panjang sama,
    # indeks terkecil menang -- sama dengan perilaku max() lama.
    heap = [(-len(l), i) for i, l in enumerate(lines)]
    heapq.heapify(heap)
    while total > PROJECT_NOTES_MAX_TOTAL_CHARS and len(lines) > 1:
        # Buang entri kedaluwarsa: panjang tersimpan tidak lagi cocok dengan
        # baris saat ini (baris pernah dipangkas di iterasi sebelumnya).
        while heap and -heap[0][0] != len(lines[heap[0][1]]):
            heapq.heappop(heap)
        idx = heap[0][1] if heap else -1
        if idx < 0:
            break
        heapq.heappop(heap)
        key = scored[idx][1].get("key") or ""
        value = scored[idx][1].get("value") or ""
        # Pangkas setengah dari BUDGET SAAT INI (yang menghasilkan cur_len),
        # bukan dari panjang value penuh -- supaya new_line selalu lebih pendek
        # dari cur_len dan loop benar-benar menyusut.
        cur_len = len(lines[idx])
        prefix = len(f"- {key}: ")
        cur_budget = max(cur_len - prefix, 40)
        new_budget = max(cur_budget // 2, 40)
        new_line = f"- {key}: {_extractive_summarize_note(value, new_budget)}"
        if len(new_line) >= cur_len:
            break  # tidak bisa menyusut lagi
        total -= cur_len - len(new_line)
        lines[idx] = new_line
        # Masukkan kembali bentuk barunya supaya iterasi berikutnya tetap
        # memangkat baris TERPANJANG saat ini.
        heapq.heappush(heap, (-len(new_line), idx))

    return header + "\n".join(lines)


def build_context_messages(db_path: str, session_id: str, system_prompt: str) -> list:
    """Bangun ulang list `messages` (format OpenAI chat: role/content) dari DB:
    system prompt + ringkasan terakhir (kalau ada) + pesan mentah setelah itu."""
    system_prompt = system_prompt + _project_notes_section(db_path, session_id)
    out = [{"role": "system", "content": system_prompt}]

    summary = dbmod.get_latest_summary(db_path, session_id)
    if summary:
        summary_content = (
            "<ringkasan_percakapan_sebelumnya>\n"
            f"{summary['summary_text']}\n"
            "</ringkasan_percakapan_sebelumnya>"
        )
        # Lapis 2 (konteks-tidak-hilang): instruksi aktif disimpan oleh model
        # summarize (kolom active_instructions) dan disuntikkan utuh setiap
        # giliran supaya keputusan desain / aturan penting tidak pernah
        # hilang walau riwayat sudah diringkas.
        active_instr = summary.get("active_instructions") or []
        if active_instr:
            instr_block = "\n".join(f"- {s}" for s in active_instr)
            summary_content += (
                "\n\n<instruksi_aktif>\n"
                "Instruksi berikut masih berlaku dan WAJIB diikuti verbatim:\n"
                f"{instr_block}\n"
                "</instruksi_aktif>"
            )
        out.append({"role": "user", "content": summary_content})
        out.append({
            "role": "assistant",
            "content": "Baik, saya sudah paham konteks sesi sebelumnya. Lanjutkan.",
        })
        rows = dbmod.get_messages_after(db_path, session_id, summary["upto_message_id"])
    else:
        rows = dbmod.get_all_messages(db_path, session_id)

    # Pesan yang di-pin harus selalu dikirim utuh, bahkan yang berada di
    # bagian riwayat yang sudah diringkas (id <= upto_message_id). Ambil
    # semua pesan pin, lalu gabungkan dengan rows yang sudah ada, urutkan
    # berdasarkan id agar urutan kronologis tetap terjaga.
    pinned = dbmod.get_pinned_messages(db_path, session_id)
    seen_ids = {r["id"] for r in rows}
    for p in pinned:
        if p["id"] not in seen_ids:
            rows.append(p)
    rows.sort(key=lambda r: r["id"])

    for r in rows:
        if r["role"] in ("user", "assistant"):
            out.append({"role": r["role"], "content": r["content"]})

    return out


def _auth_headers(api_key: str = "") -> dict:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _is_retryable_error(exc: Exception) -> bool:
    """Apakah kegagalan request layak dicoba ulang?

    Retry hanya untuk kegagalan yang SEMENTARA dan berpeluang pulih:
    - requests.Timeout (termasuk ReadTimeout/ConnectTimeout) -- server lambat
      atau sesaat tidak responsif.
    - requests.ConnectionError -- jaringan putus sesaat / server restart.
    - HTTP 429 (rate limit) dan 5xx (server error) -- server sibuk/error
      sementara.

    TIDAK di-retry: 4xx lain (400/401/403/404/422) karena itu error
    permanen dari sisi request/payload -- retry hanya buang waktu.
    """
    _req = _get_requests()
    if isinstance(exc, _req.Timeout):
        return True
    if isinstance(exc, _req.ConnectionError):
        return True
    if isinstance(exc, _req.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        return status is not None and (status == 429 or status >= 500)
    return False


def _parse_summary_output(raw: str) -> dict:
    """Parse output model summarize menjadi dict {"narasi", "instruksi_aktif"}.

    Model diinstruksikan (SUMMARIZE_SYSTEM) untuk mengembalikan JSON murni
    dengan dua field. Tapi model kadang membungkusnya dengan ```fence``` atau
    menambahkan teks di luar JSON. Fungsi ini mencoba beberapa strategi dan
    selalu fallback ke teks mentah sebagai `narasi` (instruksi_aktif=[]) agar
    tidak pernah kehilangan ringkasan.
    """
    text = (raw or "").strip()
    if not text:
        return {"narasi": "", "instruksi_aktif": []}

    candidates = [text]
    # Strategi 1: ambil blok yang dibungkus ```json ... ``` / ``` ... ```
    marker = "```"
    if marker in text:
        parts = text.split(marker)
        for i in range(1, len(parts), 2):
            block = parts[i].strip()
            if block.startswith("json"):
                block = block[4:].strip()
            if block:
                candidates.insert(0, block)

    for cand in candidates:
        try:
            parsed = json.loads(cand)
        except (ValueError, TypeError):
            continue
        if not isinstance(parsed, dict):
            continue
        narasi = parsed.get("narasi")
        instr = parsed.get("instruksi_aktif", [])
        if not isinstance(instr, list):
            instr = []
        instr = [str(x) for x in instr if str(x).strip()]
        if isinstance(narasi, str):
            return {"narasi": narasi.strip(), "instruksi_aktif": instr}

    # Fallback: bukan JSON valid -> perlakukan seluruh teks sebagai narasi.
    return {"narasi": text, "instruksi_aktif": []}


def _summarize_text(url: str, model: str, text_to_summarize: str, api_key: str = "",
                    progress=None) -> dict:
    # --- Guard token/character input (pencegahan overflow context window) ---
    # Model ringkasan = model utama; chunk yang terlalu besar akan overflow
    # context window server -> HTTP 400 -> ringkasan gagal total. Karena
    # instruksi/pesan terbaru adalah yang paling penting, potong ke tail.
    n_chars = len(text_to_summarize)
    if n_chars > SUMMARIZE_MAX_INPUT_CHARS:
        cut_at = n_chars - SUMMARIZE_MAX_INPUT_CHARS
        logger.warning(
            "chunk ringkasan %.1fM karakter > batas %.0f karakter; "
            "memotong %d karakter dari HEAD (menyimpan tail).",
            n_chars / 1e6, SUMMARIZE_MAX_INPUT_CHARS, cut_at,
        )
        text_to_summarize = text_to_summarize[-SUMMARIZE_MAX_INPUT_CHARS:]

    logger.debug(
        "summarization input: %d karakter, %.1f token; "
        "batas %d karakter (%.1f token), rasio %.2f.",
        n_chars,
        token_utils.count_tokens(text_to_summarize),
        SUMMARIZE_MAX_INPUT_CHARS,
        SUMMARIZE_MAX_INPUT_CHARS // 4,
        n_chars / SUMMARIZE_MAX_INPUT_CHARS,
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SUMMARIZE_SYSTEM},
            {"role": "user", "content": text_to_summarize},
        ],
        "temperature": 0.2,
        "stream": False,
    }
    last_exc: Exception | None = None
    for attempt in range(SUMMARIZE_MAX_RETRIES + 1):
        if progress is not None:
            try:
                progress(attempt, SUMMARIZE_MAX_RETRIES + 1)
            except Exception:
                pass
        try:
            resp = _get_requests().post(
                url, json=payload, headers=_auth_headers(api_key),
                timeout=SUMMARIZE_REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return _parse_summary_output(content)
        except Exception as exc:  # noqa: BLE001 - tangkap semua, filter di bawah
            last_exc = exc
            if not _is_retryable_error(exc):
                raise
            if attempt >= SUMMARIZE_MAX_RETRIES:
                break
            delay = min(
                SUMMARIZE_RETRY_BASE_DELAY * (2 ** attempt),
                SUMMARIZE_RETRY_MAX_DELAY,
            )
            logger.warning(
                "summarization request gagal (percobaan %d/%d): %s. "
                "Retry dalam %.1f detik.",
                attempt + 1, SUMMARIZE_MAX_RETRIES + 1, exc, delay,
            )
            time.sleep(delay)
    raise last_exc


def _print_summary_result(summary_text: str, max_chars: int = 400) -> None:
    """Cetak hasil ringkasan yang baru dibuat ke console, dipotong supaya
    tidak membanjiri layar. Hanya aktif kalau stdout adalah terminal."""
    if not sys.stdout.isatty():
        return
    preview = summary_text.strip().replace("\n", " ")
    if len(preview) > max_chars:
        preview = preview[:max_chars].rstrip() + "…"
    print(c("  └─ ringkasan dibuat:", C.BOLD_GREEN))
    print(c(f"     {preview}", C.DIM))
    print()


def maybe_summarize(db_path: str, session_id: str, url: str, model: str,
                     context_window_tokens: int, api_key: str = "",
                     tools_payload=None, system_prompt: str = "",
                     reserve_for_response: int = RESERVE_FOR_RESPONSE,
                     summarize_threshold_ratio: float = SUMMARIZE_THRESHOLD_RATIO,
                     keep_tail_messages: int = KEEP_TAIL_MESSAGES) -> bool:
    """Cek apakah riwayat mentah (yang belum tercakup summary) sudah melewati
    threshold token. Kalau iya, ringkas semua pesan lama (kecuali
    KEEP_TAIL_MESSAGES terakhir) jadi satu summary baru dan simpan ke DB.
    Return True kalau summarization benar-benar terjadi.

    `tools_payload` (opsional): field "tools" ala OpenAI yang IKUT dikirim
    di request sungguhan ke server (lihat build_openai_tools_payload() di
    cli.py). Token-nya dikurangkan dari budget di sini juga, supaya
    keputusan "sudah waktunya ringkas atau belum" konsisten dengan budget
    riil yang dipakai prepare_context_messages() -- kalau tidak, threshold
    ringkas bisa telat terpicu (baru ringkas setelah messages+tools
    SUNGGUHAN sudah kepepet/melebihi context window server).

    `system_prompt` (opsional): teks system prompt yang SELALU disisipkan
    di depan context oleh build_context_messages(). SEBELUMNYA parameter
    ini tidak ada, sehingga budget summarize hanya menghitung history +
    summary dan MENGABAIKAN system prompt (~ribuan token) yang selalu
    terkirim -- akibatnya keputusan "sudah waktunya ringkas" meleset ke
    atas (telat terpicu) karena menganggap context lebih pendek dari
    kenyataan. Dengan menghitungnya, threshold ringkas konsisten dengan
    total request sungguhan."""
    summary = dbmod.get_latest_summary(db_path, session_id)
    if summary:
        rows = dbmod.get_messages_after(db_path, session_id, summary["upto_message_id"])
        prior_summary_text = summary["summary_text"]
    else:
        rows = dbmod.get_all_messages(db_path, session_id)
        prior_summary_text = None

    rows = [r for r in rows if r["role"] in ("user", "assistant")]

    budget = context_window_tokens - reserve_for_response - _tools_payload_tokens(tools_payload)
    # system prompt selalu terkirim; sertakan juga catatan proyek persisten yang
    # disuntikkan oleh build_context_messages() supaya budget konsisten.
    total_tokens = token_utils.count_tokens(system_prompt + _project_notes_section(db_path, session_id))
    total_tokens += token_utils.count_messages_tokens(
        [{"content": r["content"]} for r in rows]
    )
    # Pesan pinned yang berada di luar `rows` (mis. sebelum summary) tetap
    # dikirim utuh oleh build_context_messages, jadi sertakan token-nya agar
    # budget konsisten dengan request sungguhan.
    pinned_extra = dbmod.get_pinned_messages(db_path, session_id)
    seen_ids = {r["id"] for r in rows}
    extra = [p for p in pinned_extra if p["id"] not in seen_ids]
    if extra:
        total_tokens += token_utils.count_messages_tokens(
            [{"content": r["content"]} for r in extra]
        )
    if prior_summary_text:
        total_tokens += token_utils.count_tokens(prior_summary_text)

    if total_tokens <= budget * summarize_threshold_ratio:
        return False
    if len(rows) < keep_tail_messages + 4:
        return False  # riwayat masih terlalu pendek, tidak worth diringkas

    split_at = _pairing_safe_split(rows, len(rows) - keep_tail_messages)
    to_summarize = rows[:split_at]
    # Pesan yang di-pin tidak boleh ikut diringkas: instruksi/aturan penting
    # harus tetap utuh dikirim setiap giliran (lihat build_context_messages).
    to_summarize = [r for r in to_summarize if not r.get("pinned")]
    if not to_summarize:
        return False

    chunk_text = "\n\n".join(
        f"[{r['role'].upper()} #{r['id']}]\n{r['content']}" for r in to_summarize
    )
    if prior_summary_text:
        chunk_text = f"[RINGKASAN SEBELUMNYA]\n{prior_summary_text}\n\n{chunk_text}"

    try:
        with ProgressBar("Meringkas riwayat percakapan...") as spinner:
            def _progress(attempt: int, total: int) -> None:
                # Bar TIDAK boleh melompat langsung ke (attempt+1)/total: satu
                # permintaan HTTP tidak melaporkan kemajuan apa pun, jadi bar
                # akan berhenti di 1/total (mis. 25%) selama menunggu dan
                # tampak macet.
                #
                # Jangan pula memberi tiap percobaan IRISAN bar sendiri
                # ([attempt/total, (attempt+1)/total * 0.95]): dengan 4
                # percobaan, irisan pertama berhenti di ~24%, sehingga
                # permintaan pertama yang berjalan lama membuat bar mandek di
                # ~24% -- gejalanya kembali.
                #
                # Yang dipakai sekarang: SATU plafon global (CREEP_CEILING =
                # 95%) untuk keseluruhan operasi. Tanpa argumen `span`,
                # start_creep() mendaki dari fraksi sekarang menuju plafon itu
                # mengikuti waktu, dan karena bar tidak pernah turun, percobaan
                # retry cukup melanjutkan pendakian dari posisi terakhir.
                # Puncak 100% dipatok spinner.finish() setelah ringkasan
                # benar-benar didapat.
                spinner.start_creep(
                    message=(
                        f"mengirim ke model {model} "
                        f"(percobaan {attempt + 1}/{total})"
                    ),
                )

            new_summary = _summarize_text(
                url, model, chunk_text,
                api_key=api_key, progress=_progress,
            )
            spinner.finish("ringkasan selesai")
        upto_id = to_summarize[-1]["id"]
        # Verifikasi: kalau model mengembalikan narasi kosong (JSON valid tapi
        # field narasi tidak ada / kosong), jangan simpan summary kosong yang
        # bisa menghilangkan konteks. Anggap gagal dan biarkan giliran
        # berikutnya mencoba lagi.
        if not (new_summary.get("narasi") or "").strip():
            logger.warning(
                "maybe_summarize: model mengembalikan narasi kosong untuk "
                "session_id=%s; summary tidak disimpan", session_id,
            )
            return False
        # Instruksi aktif: gabungkan yang baru dengan yang lama (yang masih
        # berada di summary sebelumnya) supaya tidak ada instruksi yang hilang
        # saat ringkasan bertumpuk.
        active_instructions = list(new_summary.get("instruksi_aktif", []))
        if prior_summary_text:
            prior_instr = summary.get("active_instructions") or []
            for s in prior_instr:
                if s not in active_instructions:
                    active_instructions.append(s)
        dbmod.save_summary(
            db_path, session_id, upto_id,
            new_summary.get("narasi", ""),
            active_instructions=active_instructions,
        )
        _print_summary_result(new_summary.get("narasi", ""))
    except Exception:

        logger.warning(
            "maybe_summarize gagal untuk session_id=%s (server ringkasan "
            "bermasalah atau penyimpanan summary ke DB gagal)",
            session_id, exc_info=True,
        )
        return False

    return True

def prepare_context_messages(
    db_path: str,
    session_id: str,
    system_prompt: str,
    url: str,
    model: str,
    context_window_tokens: int,
    api_key: str = "",
    tools_payload=None,
    reserve_for_response: int = RESERVE_FOR_RESPONSE,
    summarize_threshold_ratio: float = SUMMARIZE_THRESHOLD_RATIO,
    keep_tail_messages: int = KEEP_TAIL_MESSAGES,
    summarize_model: str = "",
) -> list:
    """Summarize if needed, lalu rebuild context messages dari DB.

    Fungsi ini TIDAK memangkas/memtrim pesan mentah (keputusan desain "tanpa
    trim"): kalau summarize sudah berhasil tapi total masih melebihi budget,
    pesan tetap dikirim apa adanya dan agent_loop/server yang menangani
    ContextExceededError dengan retry budget lebih ketat (memicu summarize
    lebih agresif pada giliran berikutnya).

    `tools_payload` (opsional, backward-compatible -- default None berarti
    perilaku identik dengan sebelum parameter ini ada): field "tools" ala
    OpenAI yang benar-benar disertakan di request llama-server (lihat
    build_openai_tools_payload() di cli.py). Server menghitung token field
    ini sebagai bagian dari prompt; parameter ini diteruskan ke
    maybe_summarize() supaya anggaran ringkas (threshold) memperhitungkan
    token tools, bukan cuma token `messages` -- lihat _tools_payload_tokens().
    """
    if context_window_tokens <= reserve_for_response + 128:
        raise ValueError(
            f"context_window_tokens terlalu kecil: {context_window_tokens}. "
            f"Harus lebih besar dari reserve_for_response ({reserve_for_response}) + 128."
        )

    # CATATAN PERFORMA: `_tools_payload_tokens(tools_payload)` dulu dihitung di
    # sini untuk mengurangkan token tools dari hard_budget `messages`. Karena
    # hard_budget (dan pemangkasan) sudah tidak ada lagi -- pesan selalu
    # dikirim apa adanya -- hasilnya tidak dipakai di sini. Token tools tetap
    # dihitung di maybe_summarize() (yang memakai hasil cache per-konten yang
    # sama), jadi anggaran ringkas tetap konsisten dengan request sungguhan.

    # Ringkas catatan `remember` yang panjang via LLM (sekali per catatan,
    # disimpan di kolom `summary`) sehingga _project_notes_section memakai
    # ringkasan LLM, bukan trim, untuk catatan panjang -- konteks penting
    # tidak hilang. Gagal ringkas = fallback ke trim (tidak crash).
    # Poin #4 rilis v0.5.0: `summarize_model` terpisah (opsional) untuk
    # summarization riwayat & catatan. Kalau kosong, pakai `model` utama.
    _sum_model = summarize_model or model
    try:
        _ensure_note_summaries(
            db_path, session_id, url, _sum_model, api_key=api_key,
        )
    except Exception:  # noqa: BLE001 - ringkasan catatan opsional
        logger.warning("gagal memastikan ringkasan catatan utk session_id=%s", session_id,
                       exc_info=True)

    # Ringkas riwayat lama via LLM (efek samping: menyimpan summary ke DB
    # yang dipakai build_context_messages). Return value (apakah summarize
    # terjadi) tidak lagi dibutuhkan -- sejak keputusan desain "tanpa trim",
    # kita selalu mengirim pesan apa adanya, tidak memotong tail.
    maybe_summarize(
        db_path=db_path,
        session_id=session_id,
        url=url,
        model=_sum_model,
        context_window_tokens=context_window_tokens,
        api_key=api_key,
        tools_payload=tools_payload,
        system_prompt=system_prompt,
        reserve_for_response=reserve_for_response,
        summarize_threshold_ratio=summarize_threshold_ratio,
        keep_tail_messages=keep_tail_messages,
    )

    messages = build_context_messages(
        db_path=db_path,
        session_id=session_id,
        system_prompt=system_prompt,
    )

    # CATATAN PERFORMA: di sini SEBELUMNYA dihitung
    #   hard_budget = max(context_window_tokens - reserve_for_response - tools_tokens,
    #                     MIN_CONTEXT_WINDOW_HISTORY_FLOOR)
    #   if count_messages_tokens(messages) <= hard_budget: return messages
    # Nilai `hard_budget` dan hasil count_messages_tokens itu TIDAK PERNAH
    # dipakai: kedua cabang di bawah mengembalikan `messages` yang sama persis,
    # sehingga komputasi token termahal per giliran itu sia-sia (dead code).
    # Perhitungan dihapus; keputusan budget riil ditangani agent_loop/server
    # lewat ContextExceededError (lihat penjelasan di bawah).
    #
    # KEPUTUSAN DESAIN (per komitmen): JANGAN pernah memotong/trim pesan
    # mentah untuk menghemat konteks. Trim di sini dulu memotong `tail`
    # (= messages[1:]) dari index 0, yaitu menghapus SUMMARY + pesan-pesan
    # PALING LAMA yang justru sudah diringkas -- menghilangkan konteks lama
    # yang sudah terangkum tanpa manfaat apa pun (konteks yang tersisa justru
    # pesan terbaru yang belum terangkum). Ini bertentangan dengan prinsip
    # "konteks tidak boleh hilang diam-diam".
    #
    # Yang benar: kalau summarize sudah berhasil tapi total masih melebihi
    # hard budget, kirim pesan APA ADANYA (seperti saat summarize gagal).
    # Server/agent_loop yang menangani ContextExceededError dengan retry
    # budget lebih ketat -- yang memicu summarize lebih agresif pada giliran
    # berikutnya. DB penuh tetap utuh; tidak ada konteks yang dibuang.
    return messages