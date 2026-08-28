"""cli/text_utils.py
Dipecah otomatis dari cli.py (lihat cli/_state.py untuk state bersama).
"""
import difflib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


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


# Stopword bahasa Indonesia untuk sinyal kemiripan konten (parafrase).
# Kata-kata fungsi/gramatikal ini tidak membawa makna substantif sehingga
# diabaikan saat membandingkan "isi" dua kalimat.
_CONTENT_STOPWORDS = frozenset(
    """yang dan di ke dari pada dengan untuk dalam ini itu akan saya kamu
    anda kita mereka adalah merupakan terdapat berisi ada telah sudah tidak
    juga atau tapi tetapi karena jadi maka bisa dapat harus lebih sangat
    paling hanya semua seluruh para oleh sebagai secara serta antara yaitu
    yakni seperti sepertinya kalau jika bila saat ketika sementara setelah
    sebelum dgn utk dll dst misal sbb""".split()
)


def _content_tokens(text: str) -> list:
    """Token kata konten (bukan stopword) dari teks, lowercase."""
    return [
        t for t in re.findall(r"[a-z0-9]+", text.lower())
        if t not in _CONTENT_STOPWORDS
    ]


def _stem_light(word: str) -> str:
    """Stemmer Indonesia ringan (afiks umum) untuk menyamakan bentuk kata.

    Hanya menangkap satu lapis sufiks + satu lapis prefiks dengan panjang
    minimum agar tidak merusak kata pendek. Cukup untuk deteksi parafrase
    seperti "memproses"/"pemrosesan" -> "proses"/"roses".
    """
    w = word
    for suf in ("kan", "an", "i", "lah", "kah", "pun", "nya", "ku", "mu"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[:-len(suf)]
            break
    for pre in ("meng", "meny", "mem", "men", "me",
                "peng", "peny", "pem", "pen", "pe",
                "ber", "bel", "ter", "di", "ke"):
        if w.startswith(pre) and len(w) - len(pre) >= 3:
            w = w[len(pre):]
            break
    return w


def _content_match_score(t1: str, t2: str) -> float:
    """Skor kecocokan dua token konten (0, 0.8, atau 1.0).

    1.0 = identik atau stem sama; 0.8 = berbagi substring panjang (>=4);
    0.0 = tidak berhubungan.
    """
    if t1 == t2:
        return 1.0
    s1, s2 = _stem_light(t1), _stem_light(t2)
    if s1 == s2:
        return 1.0
    if len(s1) >= 4 and len(s2) >= 4:
        for length in range(min(len(s1), len(s2)), 3, -1):
            if any(
                s1[i:i + length] == s2[j:j + length]
                for i in range(len(s1) - length + 1)
                for j in range(len(s2) - length + 1)
            ):
                return 0.8
    return 0.0


def _content_similarity(a: str, b: str) -> float:
    """Kemiripan berbasis kata konten (anti-stopword) dengan stemming ringan.

    Menggunakan bidirectional coverage: setiap token di teks yang lebih
    pendek harus punya pasangan yang cocok di teks lain, dan sebaliknya.
    Ambil min dari dua arah supaya teks yang hanya "berisi subset" kata
    teks lain (mis. "Saya membaca file" vs "Saya sudah membaca file dan
    menemukan fungsi utama") tidak dianggap sangat mirip.

    Nilai 0 jika salah satu teks tidak punya token konten.
    """
    ca = _content_tokens(a)
    cb = _content_tokens(b)
    if not ca or not cb:
        return 0.0

    def _dir_coverage(x, y):
        # Berapa proporsi token dari x yang punya pasangan cocok di y.
        # (Bukan iterasi atas yang lebih pendek, supaya kedua arah benar-benar
        # dihitung -- sehingga teks yang hanya berisi subset token teks lain
        # tidak dianggap sangat mirip.)
        matched = sum(
            1 for t in x
            if max((_content_match_score(t, u) for u in y), default=0.0) >= 0.8
        )
        return matched / len(x)

    return min(_dir_coverage(ca, cb), _dir_coverage(cb, ca))


def _similarity(a: str, b: str) -> float:
    """Skor kemiripan 0..1 antara dua string, menggabungkan lima sinyal:

    1. SequenceMatcher pada teks asli (LCS-based, sensitif urutan kata)
    2. Jaccard similarity pada token kata (tahan terhadap perubahan urutan,
       cocok untuk deteksi parafrase)
    3. SequenceMatcher pada teks yang sudah dinormalisasi entitasnya
       (mendeteksi template loop meski nama file/URL/angka berbeda)
    4. Character n-gram similarity (3-gram) -- menangkap parafrase dengan
       diksi berbeda tapi masih banyak substring yang tumpang tindih.
    5. Content-word similarity (anti-stopword + stemming ringan) -- menangkap
       parafrase pendek yang mengganti kata fungsi dan mengubah urutan kata,
       yang lolos dari keempat sinyal di atas (mis. "memproses" vs
       "pemrosesan").

    Return max dari kelimanya. 1.0 = identik secara struktural atau leksikal.
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

    # 5. Content-word similarity -- tangkap parafrase pendek yang mengganti
    #    kata fungsi & mengubah urutan kata (lolos dari 4 sinyal di atas).
    content_sim = _content_similarity(a, b)

    return max(seq_sim, jaccard, ent_sim, char_ngram_sim, content_sim)


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


# ----------------------------------------------------------------------
# Tool-call parsing untuk deteksi loop antar-respon.
#
# Masalah: _similarity memakai _normalize_entities yang mengganti path file
# menjadi __FILE__ dan angka menjadi __NUM__. Akibatnya dua tool_call yang
# BERBEDA (mis. read_file dengan path/baris berbeda) menjadi identik setelah
# normalisasi entitas, sehingga dianggap "loop" padahal itu langkah progresif
# yang sah (membaca file/baris berikutnya). Delimiter <tool_call> yang selalu
# sama di setiap tool_call juga memperparah kemiripan tekstual.
#
# Solusi: deteksi loop antar-respon harus membandingkan tool_call secara
# EKSPLISIT (nama + seluruh argumen harus identik persis), bukan teks mentah.
# ----------------------------------------------------------------------

_TOOL_CALL_BLOCK_RE = re.compile(
    r"<tool_call>\s*(.*?)\s*</tool_call>",
    re.DOTALL,
)


def _extract_tool_calls(text: str) -> list:
    """Ekstrak semua blok <tool_call>...</tool_call> dari `text` menjadi list
    dict {'name': str, 'arguments': dict}. Blok yang JSON-nya gagal di-parse
    diabaikan (memperbaiki JSON adalah tanggung jawab json_repair, bukan di
    sini). Mengembalikan list kosong kalau tidak ada tool_call yang valid.
    """
    out = []
    for raw in _TOOL_CALL_BLOCK_RE.findall(text):
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if not isinstance(obj, dict) or "name" not in obj:
            continue
        args = obj.get("arguments")
        if not isinstance(args, dict):
            args = {}
        out.append({"name": str(obj.get("name", "")), "arguments": args})
    return out


def _call_signature(call: dict):
    """Representasi kanonik (hashable) dari SATU tool_call: (name, sorted args).
    Argumen di-serialize JSON dengan sort_keys supaya urutan key tidak
    memengaruhi kesamaan (dua dict dengan isi sama tapi urutan beda = sama).
    """
    args = tuple(sorted(
        (k, json.dumps(v, sort_keys=True, ensure_ascii=False))
        for k, v in call["arguments"].items()
    ))
    return (call["name"], args)


def _tool_call_signatures(text: str):
    """Tuple signature dari SEMUA tool_call dalam `text`, atau None kalau tidak
    ada tool_call valid sama sekali. Dipakai untuk membandingkan dua respon.
    """
    calls = _extract_tool_calls(text)
    if not calls:
        return None
    return tuple(_call_signature(c) for c in calls)


def _loop_similarity(a: str, b: str) -> float:
    """Skor kemiripan khusus untuk deteksi loop ANTAR-RESPON.

    Berbeda dari _similarity: kalau KEDUA respon berisi tool_call, kita
    bandingkan tool_call-nya secara eksplisit (nama + seluruh argumen harus
    identik persis). Dua tool_call yang berbeda argumennya (mis. read_file
    dengan path/baris berbeda) adalah langkah PROGRESIF yang sah, BUKAN loop,
    meskipun secara tekstual mirip (delimiter <tool_call> sama, template JSON
    sama, dan _normalize_entities akan menyamakan path/angka).

    Kalau salah satu/keduanya tidak berisi tool_call, fallback ke _similarity.
    """
    sig_a = _tool_call_signatures(a)
    sig_b = _tool_call_signatures(b)
    if sig_a is not None and sig_b is not None:
        # Keduanya berisi tool_call: loop hanya jika seluruh signature identik.
        return 1.0 if sig_a == sig_b else 0.0
    if sig_a is not None or sig_b is not None:
        # Satu berisi tool_call, satu tidak: jelas langkah berbeda, bukan loop.
        return 0.0
    return _similarity(a, b)


def _find_repeated_text(text: str, max_sample: int = 160) -> str:
    """Ekstrak contoh kata/baris yang paling mungkin jadi sumber loop, untuk
    ditampilkan di pesan [LOOP] agar debugging lebih jelas.

    Strategi (makin spesifik makin diprioritaskan):
      0. Tool-call yang sama persis (nama + argumen) muncul >= 2x.
      1. Baris non-kosong yang muncul paling banyak (LINE-REPEAT).
      2. Kata konten (anti-stopword) yang muncul paling banyak.
      3. Kalimat/segmen pendek yang paling sering muncul sebagai substring.

    Mengembalikan string pendek (<= max_sample karakter) berisi sample + jumlah
    kemunculan, atau string kosong kalau tidak ada tanda repetisi yang jelas.
    """
    if not text:
        return ""

    # 0. Tool-call repeat: sumber loop paling jelas dan informatif. Delimiter
    #    <tool_call>/</tool_call> sengaja TIDAK dihitung (selalu muncul di setiap
    #    tool_call, jadi bukan indikasi repetisi), hanya nama+argumen yang sama.
    calls = _extract_tool_calls(text)
    if len(calls) >= 2:
        from collections import Counter
        sig_counts = Counter(_call_signature(c) for c in calls)
        most_sig, sig_n = sig_counts.most_common(1)[0]
        if sig_n >= 2:
            name, args = most_sig
            sample = f"{name} {dict(args)}"
            if len(sample) <= max_sample:
                return f"tool_call {sig_n}x: {sample!r}"
            return f"tool_call {sig_n}x: {name!r}"

    lines = [ln.strip() for ln in text.split("\n")]
    non_empty = [
        ln for ln in lines
        if ln and ln not in ("<tool_call>", "</tool_call>")
    ]

    # 1. Baris paling sering muncul (kandidat LINE-REPEAT).
    if non_empty:
        from collections import Counter
        line_counts = Counter(non_empty)
        most_line, line_n = line_counts.most_common(1)[0]
        if line_n >= 2 and len(most_line) <= max_sample:
            return f"baris {line_n}x: {most_line[:max_sample]!r}"

    # 2. Kalimat/segmen pendek yang paling sering muncul (lebih informatif
    #    daripada kata, dan menangkap loop kalimat penuh dalam satu baris).
    sentences = re.split(r"[.!?]\s|\n", text)
    sentences = [
        s.strip() for s in sentences
        if len(s.strip()) >= 8 and s.strip() not in ("<tool_call>", "</tool_call>")
    ]
    if sentences:
        from collections import Counter
        sent_counts = Counter(sentences)
        most_sent, sent_n = sent_counts.most_common(1)[0]
        if sent_n >= 2:
            return f"kalimat {sent_n}x: {most_sent[:max_sample]!r}"

    # 3. Kata konten paling sering muncul (fallback terakhir).
    tokens = re.findall(r"[A-Za-z0-9_]+", text.lower())
    stop = {
        "yang", "dan", "di", "ke", "dari", "ini", "itu", "untuk", "dengan",
        "pada", "adalah", "akan", "tidak", "the", "and", "of", "to", "in",
        "a", "is", "for", "on", "with", "as", "at", "by", "or", "an",
        "tool_call", "tool",
    }
    content_tokens = [t for t in tokens if t not in stop and len(t) > 1]
    if content_tokens:
        from collections import Counter
        token_counts = Counter(content_tokens)
        most_token, token_n = token_counts.most_common(1)[0]
        if token_n >= 3:
            return f"kata {token_n}x: {most_token!r}"

    return ""


def _detect_repetition(text: str, strict: bool = True) -> bool:
    """Deteksi pola repetisi/degenerasi di dalam satu respon.

    Mengembalikan True kalau teks yang sudah terkumpul menunjukkan tanda
    loop: baris yang sama muncul minimal REPEAT_MAX_OCCUR kali, ATAU segmen
    terakhir (unit) muncul berkali-kali di seluruh teks, ATAU ada substring
    berulang (n-gram) dengan panjang cukup di posisi mana pun, ATAU simbol
    separator (---, ===, ***) berulang terus-menerus.

    ``strict`` membedakan dua konteks pemakaian:
    - ``strict=True`` (default): untuk jawaban asli (content). Model tidak
      seharusnya menulis ulang kalimat yang identik berkali-kali, jadi
      ambang line-repeat ketat (REPEAT_MAX_OCCUR).
    - ``strict=False``: untuk reasoning (chain of thought). Model secara
      natural menulis ulang rencana/konsep yang sama sebagai bagian normal
      berpikir, sehingga ambang line-repeat dilonggarkan
      (REPEAT_MAX_OCCUR_REASONING) untuk menekan false positive.

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
    # 0b. Fence-run detection: fence markdown (```, ```python, ~~~, ...)
    #     yang muncul BERURUTAN tanpa konten di antaranya adalah loop
    #     degenerate (mirip separator bertumpuk). Fence yang TERSebar di
    #     antara konten adalah markdown sah (banyak blok kode pendek) dan
    #     TIDAK ditandai di sini.
    # ------------------------------------------------------------------
    fence_pattern = re.compile(r'^[\s]*`{3,}[\w+\-.]*[\s]*$|^[\s]*~{3,}[\w+\-.]*[\s]*$')
    fence_run = 0
    max_fence_run = 0
    for ln in text.split("\n"):
        if fence_pattern.match(ln):
            fence_run += 1
            if fence_run > max_fence_run:
                max_fence_run = fence_run
        elif ln.strip() == "":
            continue  # baris kosong tidak memutus run
        else:
            fence_run = 0  # konten memutus run
    if max_fence_run >= state.SEPARATOR_REPEAT_THRESHOLD:
        if _dbg:
            _warn_repetition(
                "FENCE-REPEAT",
                f"fence markdown muncul {max_fence_run}x berurutan (threshold={state.SEPARATOR_REPEAT_THRESHOLD})",
                text[:200],
            )
        return True

    # ------------------------------------------------------------------
    # 1. Line-repeat: baris yang sama muncul >= threshold kali.
    #    Baris pendek (1-2 karakter) yang berupa simbol repetitif tetap
    #    diperiksa; hanya baris kosong yang diabaikan.
    #    Ambang bergantung pada `strict`: content ketat (REPEAT_MAX_OCCUR),
    #    reasoning longgar (REPEAT_MAX_OCCUR_REASONING).
    # ------------------------------------------------------------------
    line_repeat_threshold = (
        state.REPEAT_MAX_OCCUR if strict else state.REPEAT_MAX_OCCUR_REASONING
    )
    # fence_pattern sudah didefinisikan di bagian 0b.
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
            # Fence markdown yang TERSebar di antara konten juga bukan loop
            # (sama seperti separator). Fence bertumpuk tanpa konten tetap
            # ditangkap oleh separator-run / diversity check.
            if fence_pattern.match(ln):
                continue
            # Delimiter tool_call (<tool_call>, </tool_call>) SELALU muncul
            # di setiap tool_call, jadi bukan indikasi repetisi. Menghitungnya
            # sebagai LINE-REPEAT memicu false positive saat model sah
            # mengirim beberapa tool_call berbeda (mis. read_file beberapa
            # file/baris). Repetisi tool_call yang SEBENARNYA (nama+argumen
            # identik) ditangkap oleh _find_repeated_text / _loop_similarity.
            if ln in ("<tool_call>", "</tool_call>"):
                continue
            line_counts[ln] = line_counts.get(ln, 0) + 1
            if line_counts[ln] >= line_repeat_threshold:
                if _dbg:
                    _warn_repetition(
                        "LINE-REPEAT",
                        f"baris muncul {line_counts[ln]}x "
                        f"(threshold={line_repeat_threshold}, strict={strict})",
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
            diversity_threshold = (
                state.REPEAT_DIVERSITY_THRESHOLD
                if strict
                else state.REPEAT_DIVERSITY_THRESHOLD_REASONING
            )
            if diversity < diversity_threshold:
                if _dbg:
                    _warn_repetition(
                        "LOW-DIVERSITY",
                        f"rasio n-gram unik {diversity:.3f} < threshold "
                        f"{diversity_threshold} "
                        f"(window={window}, total={len(grams)}, strict={strict})",
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
