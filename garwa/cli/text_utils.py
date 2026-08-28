"""cli/text_utils.py
Dipecah otomatis dari cli.py (lihat cli/_state.py untuk state bersama).
"""
import argparse
import base64
import copy
import difflib
import json
import mimetypes
import os
import re
import select
import shlex
import shutil
import sys
import time
import unicodedata
from collections import OrderedDict
from datetime import datetime
from urllib.parse import unquote, urlparse

try:

    import readline  # noqa: F401
except ImportError:
    readline = None

import requests

from ..tools import TOOLS
from . import _state as state
from .colors import C
from .colors import c_prompt



def _normalize_ws(text: str) -> str:
    """Normalisasi whitespace untuk perbandingan kemiripan: runtuhkan semua
    spasi/tab/newline beruntun jadi satu spasi, dan buang spasi di ujung.
    Ini membuat dua respon yang beda hanya di whitespace dianggap sama.
    """
    return " ".join(text.split())


def _normalize_entities(text: str) -> str:
    """Ganti entitas variabel (path file, URL, angka, quoted string) dengan
    placeholder supaya dua respon dengan template sama tapi isi berbeda
    (mis. beda nama file) tetap terdeteksi mirip secara struktural.

    Placeholder:
      __FILE__  : path file (contoh: main.py, /path/to/utils.js)
      __URL__   : URL (contoh: https://example.com)
      __NUM__   : angka desimal (contoh: 42, 100)
      __STR__   : quoted string (contoh: "hello world")
    """
    t = text
    # URL -- sebelum FILE agar tidak tertangkap sebagai file
    t = re.sub(r'https?://\S+', '__URL__', t)
    # Path file dengan ekstensi umum (1-6 karakter setelah titik)
    t = re.sub(r'\b[\w/.-]+\.\w{1,6}\b', '__FILE__', t)
    # Angka desimal
    t = re.sub(r'\b\d+\b', '__NUM__', t)
    # Quoted string (double & single)
    t = re.sub(r'"[^"]*"', '__STR__', t)
    t = re.sub(r"'[^']*'", '__STR__', t)
    return t


def _similarity(a: str, b: str) -> float:
    """Skor kemiripan 0..1 antara dua string, menggabungkan empat sinyal:

    1. SequenceMatcher pada teks asli (LCS-based, sensitif urutan kata)
    2. Jaccard similarity pada token kata (tahan terhadap perubahan urutan,
       cocok untuk deteksi parafrase)
    3. SequenceMatcher pada teks yang sudah dinormalisasi entitasnya
       (mendeteksi template loop meski nama file/URL/angka berbeda)
    4. Character n-gram similarity (3-gram) -- menangkap parafrase dengan
       diksi berbeda tapi masih banyak substring yang tumpang tindih.

    Return max dari keempatnya. 1.0 = identik secara struktural atau leksikal.
    """
    a_ws = _normalize_ws(a)
    b_ws = _normalize_ws(b)

    # 1. Original SequenceMatcher (LCS)
    seq_sim = difflib.SequenceMatcher(None, a_ws, b_ws).ratio()

    # 2. Token Jaccard -- tangkap parafrase / kata sama urutan beda
    tokens_a = set(a_ws.lower().split())
    tokens_b = set(b_ws.lower().split())
    union = tokens_a | tokens_b
    if union:
        jaccard = len(tokens_a & tokens_b) / len(union)
    else:
        jaccard = 1.0

    # 3. Entity-normalized -- tangkap template loop (beda nama file/dll)
    ent_a = _normalize_entities(a_ws)
    ent_b = _normalize_entities(b_ws)
    ent_sim = difflib.SequenceMatcher(None, ent_a, ent_b).ratio()

    # 4. Character 3-gram Jaccard -- robust terhadap perubahan urutan kata
    def _char_ngrams(s, n=3):
        if len(s) < n:
            return None  # terlalu pendek, tidak bisa dibandingkan
        return {s[i:i + n] for i in range(len(s) - n + 1)}
    nga = _char_ngrams(a_ws.lower())
    ngb = _char_ngrams(b_ws.lower())
    if nga is None or ngb is None:
        char_ngram_sim = 0.0  # salah satu terlalu pendek, fallback ke sinyal lain
    else:
        ng_union = nga | ngb
        if ng_union:
            char_ngram_sim = len(nga & ngb) / len(ng_union)
        else:
            char_ngram_sim = 1.0

    return max(seq_sim, jaccard, ent_sim, char_ngram_sim)


def _warn_repetition(kind: str, detail: str, sample: str) -> None:
    """Log diagnostik repetisi ke stderr (real-time, tidak buffered).
    Hanya dipanggil kalau env GARWA_DEBUG_REPETITION=1.
    """
    ts = datetime.now().strftime("%H:%M:%S")
    sys.stderr.write(
        f"\n[REP-DBG {ts}] {kind} | {detail}\n"
        f"  sample: {sample!r}\n"
    )
    sys.stderr.flush()


def _detect_repetition(text: str) -> bool:
    """Deteksi pola repetisi/degenerasi di dalam satu respon.

    Mengembalikan True kalau teks yang sudah terkumpul menunjukkan tanda
    loop: baris yang sama muncul minimal REPEAT_MAX_OCCUR kali, ATAU segmen
    terakhir (unit) muncul berkali-kali di seluruh teks, ATAU ada substring
    berulang (n-gram) dengan panjang cukup di posisi mana pun, ATAU simbol
    separator (---, ===, ***) berulang terus-menerus.

    Perbaikan dari versi sebelumnya:
    - Multi-scale n-gram (25, 60, 120 karakter) untuk menangkap repetisi
      di berbagai ukuran.
    - Near-duplicate detection: n-gram dibandingkan dengan toleransi
      fuzzy (normalisasi whitespace + rasio kemiripan) sehingga variasi
      kecil seperti spasi ganda tetap terdeteksi.
    - Separator detection: simbol seperti "---", "===", "***" yang
      berulang > SEPARATOR_REPEAT_THRESHOLD kali langsung terdeteksi.
    - Baris pendek (< 3 karakter) yang berupa simbol repetitif tetap
      diperiksa (kecuali benar-benar kosong).
    - Minimal teks untuk n-gram check diturunkan ke 125 karakter.

    Setel GARWA_DEBUG_REPETITION=1 untuk logging diagnostik real-time ke
    stderr setiap kali fungsi ini mencurigai adanya loop (termasuk yang
    akhirnya diputuskan false positive).
    """
    _dbg = os.environ.get("GARWA_DEBUG_REPETITION") == "1"

    # ------------------------------------------------------------------
    # 0. Separator detection: simbol berulang seperti ---, ===, ***, ...
    #    HANYA dianggap loop jika separator muncul BERURUTAN (bertumpuk
    #    tanpa konten di antaranya). Markdown normal sering memakai 3-5
    #    horizontal rules (---) yang TERSebar di antara section untuk
    #    memisahkan bagian -- itu bukan loop dan tidak boleh ditandai.
    #    Loop degenerate justru menghasilkan banyak separator berturut-
    #    turut (mis. "---\n---\n---\n...").
    # ------------------------------------------------------------------
    separator_pattern = re.compile(
        r'^[\s]*([\-=_*#~+]{2,})[\s]*$',
    )
    separator_run = 0
    max_separator_run = 0
    for ln in text.split("\n"):
        if separator_pattern.match(ln):
            separator_run += 1
            if separator_run > max_separator_run:
                max_separator_run = separator_run
        elif ln.strip() == "":
            # Baris kosong tidak memutus run: dalam loop degenerate
            # separator sering dipisah baris kosong ("---\n\n---\n\n---").
            continue
        else:
            # Baris berisi konten memutus run (markdown normal).
            separator_run = 0
    if max_separator_run >= state.SEPARATOR_REPEAT_THRESHOLD:
        if _dbg:
            _warn_repetition(
                "SEPARATOR-REPEAT",
                f"simbol separator muncul {max_separator_run}x berurutan (threshold={state.SEPARATOR_REPEAT_THRESHOLD})",
                text[:200],
            )
        return True

    # ------------------------------------------------------------------
    # 1. Line-repeat: baris yang sama muncul >= REPEAT_MAX_OCCUR kali.
    #    Baris pendek (1-2 karakter) yang berupa simbol repetitif tetap
    #    diperiksa; hanya baris kosong yang diabaikan.
    # ------------------------------------------------------------------
    lines = [ln.strip() for ln in text.split("\n")]
    # Filter: abaikan baris yang benar-benar kosong setelah strip
    non_empty_lines = [ln for ln in lines if ln]
    if non_empty_lines:
        line_counts: dict = {}
        for ln in non_empty_lines:
            # Baris yang hanya berisi simbol separator (---, ===, ***, ...)
            # TIDAK dihitung di sini: separator bertumpuk sudah ditangani
            # oleh separator-run detection di bagian 0, sedangkan separator
            # yang TERSebar di antara konten adalah markdown normal (bukan
            # loop) dan tidak boleh memicu LINE-REPEAT.
            if separator_pattern.match(ln):
                continue
            # Baris sangat pendek (1-2 karakter): hanya periksa kalau
            # isinya simbol repetitif (bukan teks biasa seperti "OK")
            if len(ln) < 3:
                # Tetap cek: "OK" 2 karakter yang berulang 5x juga repetitif
                pass
            line_counts[ln] = line_counts.get(ln, 0) + 1
            if line_counts[ln] >= state.REPEAT_MAX_OCCUR:
                if _dbg:
                    _warn_repetition(
                        "LINE-REPEAT",
                        f"baris muncul {line_counts[ln]}x (threshold={state.REPEAT_MAX_OCCUR})",
                        ln[:200],
                    )
                return True

    # ------------------------------------------------------------------
    # 2. Unit-repeat: segmen terakhir teks muncul berkali-kali.
    #    Verifikasi konteks sekitar setiap kemunculan untuk mengurangi
    #    false positive.
    # ------------------------------------------------------------------
    if len(text) >= state.REPEAT_MIN_UNIT_LEN:
        unit = text[-state.REPEAT_MIN_UNIT_LEN:]
        # Cari semua posisi kemunculan unit (non-overlapping).
        pos = 0
        occurrences = []
        while True:
            pos = text.find(unit, pos)
            if pos == -1:
                break
            occurrences.append(pos)
            pos += len(unit)

        if len(occurrences) >= state.REPEAT_MAX_OCCUR:
            # Verifikasi konteks sekitar.
            ctx_len = state.REPEAT_MIN_UNIT_LEN * 2
            windows = []
            for occ in occurrences[:50]:
                start = max(0, occ - ctx_len)
                end = min(len(text), occ + len(unit) + ctx_len)
                windows.append(text[start:end])

            similar_count = 1
            for w in windows[1:]:
                if _similarity(windows[0], w) >= state.LOOP_SIMILARITY_THRESHOLD:
                    similar_count += 1
            if similar_count >= state.REPEAT_MAX_OCCUR:
                if _dbg:
                    _warn_repetition(
                        "UNIT-REPEAT",
                        f"unit muncul {len(occurrences)}x, {similar_count} window mirip (threshold={state.REPEAT_MAX_OCCUR})",
                        unit[:200],
                    )
                return True

    # ------------------------------------------------------------------
    # 3. Multi-scale n-gram repeat dengan near-duplicate detection.
    #    Scan di 3 ukuran (25, 60, 120) untuk menangkap repetisi di
    #    berbagai skala. Setiap n-gram dibandingkan dengan toleransi
    #    fuzzy (normalisasi whitespace + rasio kemiripan) sehingga
    #    variasi kecil seperti spasi ganda tetap terdeteksi.
    # ------------------------------------------------------------------
    if len(text) >= state.REPEAT_NGRAM_MIN_TOTAL_LEN:
        for ngram_size in state.REPEAT_NGRAM_SCALES:
            if len(text) < ngram_size * state.REPEAT_NGRAM_MAX_OCCUR:
                continue  # teks terlalu pendek untuk skala ini

            # Normalisasi whitespace untuk perbandingan fuzzy
            text_normalized = _normalize_ws(text)

            for i in range(0, len(text) - ngram_size + 1, ngram_size):
                block = text[i:i + ngram_size]
                block_norm = _normalize_ws(block)
                count = 1
                j = i + ngram_size
                while j + ngram_size <= len(text):
                    candidate = text[j:j + ngram_size]
                    candidate_norm = _normalize_ws(candidate)

                    # Exact match ATAU near-duplicate (fuzzy)
                    if candidate == block:
                        count += 1
                    elif block_norm and candidate_norm:
                        # Gunakan rasio sederhana: berapa persen karakter berbeda
                        max_len = max(len(block_norm), len(candidate_norm))
                        if max_len > 0:
                            # Hitung perbedaan karakter
                            diff = sum(
                                1 for a, b in zip(block_norm, candidate_norm)
                                if a != b
                            ) + abs(len(block_norm) - len(candidate_norm))
                            if diff / max_len <= state.REPEAT_NGRAM_FUZZY_THRESHOLD:
                                count += 1
                            else:
                                break  # tidak mirip, hentikan
                        else:
                            break
                    else:
                        break  # tidak mirip, hentikan
                    j += ngram_size

                if count >= state.REPEAT_NGRAM_MAX_OCCUR:
                    if _dbg:
                        _warn_repetition(
                            "NGRAM-REPEAT",
                            f"n-gram ukuran {ngram_size} muncul {count}x (threshold={state.REPEAT_NGRAM_MAX_OCCUR})",
                            block[:200],
                        )
                    return True

    # ------------------------------------------------------------------
    # 4. Diversity check: rasio n-gram unik terhadap total n-gram.
    #    Tahap 1-3 semuanya bergantung pada blok yang aligned dan/atau
    #    konsekutif, sehingga lolos untuk pola seperti:
    #      - interleaved (A, B, A, B, A) -- counter reset tiap ketemu B
    #      - segmen pendek non-aligned ("Hello world! " 13 char)
    #      - unit overlap yang undercount karena str.find non-overlapping
    #      - near-duplicate whitespace di posisi tidak aligned
    #    Rolling window (stride 1) tidak punya asumsi alignment sama
    #    sekali: kalau teks benar-benar bervariasi, hampir semua n-gram
    #    unik. Normalisasi whitespace lebih dulu supaya variasi spasi
    #    tidak menyamarkan repetisi.
    # ------------------------------------------------------------------
    text_ws = _normalize_ws(text)
    window = state.REPEAT_DIVERSITY_WINDOW
    if len(text_ws) >= max(state.REPEAT_DIVERSITY_MIN_LEN, window + 5):
        grams = [
            text_ws[i:i + window]
            for i in range(len(text_ws) - window + 1)
        ]
        if grams:
            diversity = len(set(grams)) / len(grams)
            if diversity < state.REPEAT_DIVERSITY_THRESHOLD:
                if _dbg:
                    _warn_repetition(
                        "LOW-DIVERSITY",
                        f"rasio n-gram unik {diversity:.3f} < threshold "
                        f"{state.REPEAT_DIVERSITY_THRESHOLD} "
                        f"(window={window}, total={len(grams)})",
                        text_ws[-200:],
                    )
                return True

    return False


def _terminal_width(text: str) -> int:
    """Lebar terminal sederhana, mengabaikan ANSI dan menangani CJK/combining."""
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    width = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def _truncate_display(text: str, limit: int) -> str:
    if _terminal_width(text) <= limit:
        return text
    out = []
    width = 0
    for ch in text:
        w = 0 if unicodedata.combining(ch) else (
            2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        )
        if width + w > max(1, limit - 1):
            break
        out.append(ch)
        width += w
    return "".join(out).rstrip() + "…"


def _resp_text_utf8(response) -> str:
    """Ambil body response sebagai teks, di-decode UTF-8 secara eksplisit.

    `response.text` (properti bawaan requests) memakai `response.encoding`,
    yang ditebak dari header HTTP -- untuk media type text/*+json/event-stream
    tanpa parameter charset eksplisit, requests bisa menebak ISO-8859-1,
    bukan UTF-8 (lihat catatan panjang di _call_llama_server_stream()).
    server model (endpoint OpenAI-compatible) selalu berbicara UTF-8, jadi di
    sini kita decode langsung dari `response.content` (bytes mentah) dengan
    encoding yang benar, supaya pesan error yang ditampilkan ke user/model
    tidak ikut mojibake gara-gara tebakan encoding yang salah.
    """
    if response is None:
        return ""
    try:
        return response.content.decode("utf-8", errors="replace")
    except Exception:
        return response.text


def confirm(prompt: str) -> bool:
    ans = input(c_prompt(f"  {prompt} [y/N] ", C.YELLOW)).strip().lower()
    return ans in ("y", "yes")
