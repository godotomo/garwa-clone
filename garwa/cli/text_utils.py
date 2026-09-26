"""cli/text_utils.py
Dipecah otomatis dari cli.py (lihat cli/_state.py untuk state bersama).
"""
import difflib
import json
import re
import unicodedata
from collections import Counter

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from . import _state as state
from .colors import C
from .colors import c
from .colors import c_prompt
from .spinner import pause_all_spinners
from .spinner import resume_all_spinners



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
        # Keduanya berisi tool_call: loop hanya jika seluruh MULTISET signature
        # identik. Perbandingan multiset (Counter) membuat URUTAN tool_call
        # tidak relevan: [read_file, write_file] dan [write_file, read_file]
        # adalah loop yang sama. Jumlah kemunculan tetap diperhitungkan:
        # [read_file] vs [read_file, read_file] BUKAN loop (respon kedua
        # menambah tool = langkah progresif yang sah).
        return 1.0 if Counter(sig_a) == Counter(sig_b) else 0.0
    if sig_a is not None or sig_b is not None:
        # Satu berisi tool_call, satu tidak: jelas langkah berbeda, bukan loop.
        return 0.0
    return _similarity(a, b)


def _longest_line_run(text: str) -> tuple[str, int]:
    """Cari run terpanjang baris non-kosong yang identik BERTURUT-TURUT.

    Mengembalikan (baris, panjang_run) atau ("", 0) bila tidak ada.

    Sengaja memakai run berturut-turut (bukan total kemunculan di seluruh
    teks): jawaban wajar acap memuat baris struktur markdown yang identik
    tetapi TERSEBAR, mis. fence '```' / '```python' untuk setiap blok kode,
    baris pemisah '---' antar seksi, atau header tabel yang sama untuk
    beberapa tabel berbeda. Menghitung total kemunculan membuat jawaban
    normal berisi >=5 blok kode salah diklasifikasikan sebagai degenerate
    loop -> stream dihentikan di tengah jawaban dan giliran berhenti
    sebelum tugas selesai. Loop degeneratif yang nyata mengulang baris yang
    sama secara BERTURUT-TURUT, jadi run adalah sinyal yang tepat.
    """
    if not text:
        return "", 0

    best_line = ""
    best_run = 0
    cur_line = ""
    cur_run = 0
    for raw in text.split("\n"):
        ln = raw.strip()
        if not ln:
            # Baris kosong memutus run: bukan bagian dari repetisi.
            cur_line, cur_run = "", 0
            continue
        if ln == cur_line:
            cur_run += 1
        else:
            cur_line, cur_run = ln, 1
        if cur_run > best_run:
            best_line, best_run = cur_line, cur_run
    return best_line, best_run


# Periode maksimum siklus baris yang diperiksa _longest_line_cycle. Pola
# degenerate yang terverifikasi di produksi (mis. spam tag penutup tool_call
# bergantian) berperiode 4; 8 memberi margin untuk varian serupa tanpa
# membuka celah false-positive pada struktur markdown wajar (blok kode/tabel)
# yang periodenya biasanya jauh lebih besar.
_CYCLE_MAX_PERIOD = 8


def _longest_line_cycle(text: str):
    """Cari siklus baris berulang: blok `p` baris non-kosong yang identik
    BERTURUT-TURUT minimal REPEAT_MAX_OCCUR kali, untuk p >= 2.

    Melengkapi _longest_line_run (yang hanya menangani p == 1, yaitu baris
    yang sama persis berulang). Loop degenerate nyata sering berbentuk SIKLUS
    periodik, bukan baris tunggal berulang: mis. model memuntahkan tag penutup
    tool_call secara bergantian (tag A, tag B, tag C, tag B, lalu terulang).
    Di sini TIDAK ada baris yang berulang berturut-turut (run maksimum = 1),
    sehingga _longest_line_run melaporkan "tidak ada repetisi" padahal jelas
    degenerate. Siklus berperiode 4 inilah yang ditangkap fungsi ini.

    Baris kosong memutus siklus (konsisten dengan _longest_line_run): jawaban
    wajar memakai baris kosong sebagai pemisah antar-seksi, jadi blok yang
    memuat baris kosong sengaja TIDAK dianggap siklus.

    Mengembalikan (period, repeat_count, sample_block) atau (0, 0, []) bila
    tidak ada siklus yang mencapai ambang.
    """
    if not text:
        return 0, 0, []

    lines = [ln.strip() for ln in text.split("\n")]
    n = len(lines)
    best = (0, 0, [])
    for p in range(2, _CYCLE_MAX_PERIOD + 1):
        i = 0
        while i + p <= n:
            block = lines[i:i + p]
            if any(not x for x in block):
                # Baris kosong di dalam blok -> bukan siklus; maju satu baris.
                i += 1
                continue
            reps = 1
            j = i + p
            while j + p <= n and lines[j:j + p] == block:
                reps += 1
                j += p
            if reps >= state.REPEAT_MAX_OCCUR and reps * p > best[1] * best[0]:
                best = (p, reps, block)
            # Lewati seluruh run yang baru ditemukan supaya tidak dihitung
            # ulang dari posisi bergeser (mis. siklus p=2 juga terlihat sebagai
            # p=4 dengan setengah repetisi).
            i = j if reps > 1 else i + 1
    return best


# Tanda baca yang dibuang di ujung baris saat menormalkan bentuk baris untuk
# perbandingan pola. Sengaja TIDAK memuat '-', '*', '#', '>', '|', '`':
# karakter itu adalah penanda struktur markdown (butir daftar, heading,
# blockquote, tabel, fence) yang justru pembeda penting antar-baris. Kalau
# ikut dibuang, baris pemisah '---' akan menyusut jadi string kosong dan
# menyamar sebagai baris kosong -- persis yang membuat dokumen ber-'---'
# antar-seksi salah dianggap pola degenerate.
_PATTERN_TRIM_CHARS = ".,;:!?\u2026\"'\u2019\u201c\u201d \t"


def _normalize_line(line: str) -> str:
    """Bentuk normal satu baris untuk perbandingan pola.

    Huruf kecil + spasi dirapatkan + tanda baca ujung dibuang, supaya variasi
    sepele ("Ok." vs "ok", "Baik, saya tulis." vs "Baik saya tulis") dihitung
    sebagai baris yang sama. Ini yang membuat deteksi berbasis POLA, bukan
    pencocokan frasa: tidak ada kalimat yang di-hardcode, hanya bentuk normal
    baris yang dibandingkan.
    """
    t = _normalize_ws(line).lower()
    return t.strip(_PATTERN_TRIM_CHARS)


def _line_similarity(a: str, b: str) -> float:
    """Kemiripan dua baris ternormalisasi: rasio token yang sama
    (irisan / jumlah token terbanyak).

    Dipakai sinyal pola LUNAK untuk menangkap unit yang kembali walau
    kalimatnya tidak persis sama antar-iterasi (mis. "baik saya tulis" vs
    "baik akan saya tulis" = 3/4). Baris kosong hanya cocok dengan baris
    kosong.
    """
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def _pattern_block_ok(
    block: list[str],
    min_text_lines: int = 1,
    allow_short_single: bool = False,
) -> bool:
    """Blok layak diuji sebagai unit pola: harus memuat baris KOSONG sekaligus
    baris BERISI yang cukup.

    (a) Tanpa baris kosong -> itu wilayah _longest_line_cycle (ambang 5);
        melewatinya menjaga agar ambang lebih rendah di sinyal pola tidak
        ikut menurunkan ambang sinyal siklus yang sudah ada.
    (b) Baris berisi kurang dari `min_text_lines` -> unit terlalu tipis untuk
        disebut pola. Khusus sinyal LUNAK, `min_text_lines=2` mengecualikan
        unit [teks, kosong]: itu setara "baris berselang-seling dengan baris
        kosong", bentuk yang terlalu umum di markdown (daftar berbutir, seksi
        pendek) sehingga dengan pencocokan lunak ia akan menuduh jawaban wajar
        sebagai loop.
    (c) Pengecualian untuk (b): `allow_short_single=True` menerima unit dengan
        SATU baris berisi asalkan baris itu PENDEK (<= PATTERN_SHORT_LINE_MAX).
        Ini menangkap loop "acknowledgement pendek diulang dengan sedikit
        variasi kata" ("Baik saya tulis." / "Baik saya tulis ya." / "Baik saya
        akan tulis.") yang lolos dari sinyal EKSAK karena barisnya tidak lagi
        identik. Batas panjang itu yang menjaga agar unit [kalimat-penuh,
        kosong] -- bentuk dokumen wajar -- tidak ikut dianggap loop.
    """
    if not any(not x for x in block):
        return False
    text_lines = [x for x in block if x]
    if len(text_lines) >= min_text_lines:
        return True
    return (
        allow_short_single
        and len(text_lines) == 1
        and len(text_lines[0]) <= state.PATTERN_SHORT_LINE_MAX
    )


def _scan_pattern_cycle(
    lines: list[str],
    raw: list[str],
    min_reps: int,
    matcher,
    min_text_lines: int = 1,
    allow_short_single: bool = False,
):
    """Pemindai umum siklus pola: untuk setiap periode p, cari blok yang
    berulang BERTURUT-TURUT minimal `min_reps` kali menurut `matcher`.

    Dipakai dua sinyal: pola EKSAK (matcher = kesamaan bentuk normal) dan pola
    LUNAK (matcher = kemiripan token antar-baris, `min_text_lines=2` +
    `allow_short_single=True`). Mengembalikan (period, repeat_count,
    sample_block) atau (0, 0, []) bila tidak ada.
    """
    n = len(lines)
    best = (0, 0, [])
    for p in range(2, state.PATTERN_SHAPE_MAX_PERIOD + 1):
        i = 0
        while i + p <= n:
            block = lines[i:i + p]
            if not _pattern_block_ok(block, min_text_lines, allow_short_single):
                i += 1
                continue
            reps = 1
            j = i + p
            while j + p <= n and matcher(block, lines[j:j + p]):
                reps += 1
                j += p
            if reps >= min_reps and reps * p > best[1] * best[0]:
                best = (p, reps, raw[i:i + p])
            # Lewati seluruh run yang baru ditemukan supaya tidak dihitung
            # ulang dari posisi bergeser (mis. siklus p=2 juga terlihat
            # sebagai p=4 dengan setengah repetisi).
            i = j if reps > 1 else i + 1
    return best


# Penanda struktur markdown di awal baris: butir daftar, heading, blockquote,
# tabel, fence, dan penomoran ("1." / "2)"). Baris yang diawali penanda ini
# TIDAK pernah dianggap "baris sangat pendek" pada pencocokan pola: daftar
# berbutir yang butirnya berbeda isi ("- Item satu" / "- Item dua") adalah
# struktur dokumen yang wajar, bukan pengulangan. Ini alasan yang sama dengan
# mengapa _PATTERN_TRIM_CHARS sengaja tidak membuang karakter penanda ini.
_PATTERN_MARKER_CHARS = "-*#|>`+~="


def _has_pattern_marker(line: str) -> bool:
    """True bila baris diawali penanda struktur markdown atau penomoran."""
    s = line.lstrip()
    if not s:
        return False
    if s[0] in _PATTERN_MARKER_CHARS:
        return True
    return bool(re.match(r"^\d+\s*[.)\]:]", s))


# Kata bilangan/urutan yang lazim dipakai untuk MENOMORI butir. Dua baris yang
# bedanya hanya pada token ini adalah enumerasi -- konten yang memang sengaja
# berbeda tiap butir -- bukan pengulangan pola.
_ENUM_WORDS = frozenset({
    "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan",
    "sembilan", "sepuluh", "sebelas",
    "pertama", "kedua", "ketiga", "keempat", "kelima", "keenam", "ketujuh",
    "kedelapan", "kesembilan", "kesepuluh",
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "first", "second", "third", "fourth", "fifth", "sixth", "seventh",
    "eighth", "ninth", "tenth",
})


def _is_enumeration_token(tok: str) -> bool:
    """Token penomoran: angka murni atau kata bilangan/urutan."""
    return tok.isdigit() or tok in _ENUM_WORDS


def _differs_only_by_enumeration(x: str, y: str) -> bool:
    """True bila satu-satunya beda antara dua baris ternormalisasi adalah token
    PENOMORAN: angka ("langkah 1" vs "langkah 2") atau kata bilangan/urutan
    ("item satu" vs "item dua").

    Perbedaan seperti itu adalah enumerasi -- konten yang memang sengaja
    berbeda tiap baris -- bukan pengulangan. Tanpa pembeda ini, dokumen wajar
    berisi lima langkah bernomor (atau daftar tanpa penanda berisi "Item satu",
    "Item dua", ...) dengan kalimat yang sama akan dihitung sebagai unit pola
    yang kembali dan salah ditandai loop.
    """
    # Token dibandingkan setelah tanda baca ujungnya dibuang, supaya penomoran
    # yang menempel pada tanda baca ("1:" / "2.") tetap terbaca sebagai angka.
    tx = [w.strip(_PATTERN_TRIM_CHARS) for w in x.split()]
    ty = [w.strip(_PATTERN_TRIM_CHARS) for w in y.split()]
    if len(tx) != len(ty):
        return False
    diff = [(p, q) for p, q in zip(tx, ty) if p != q]
    if not diff:
        return False
    return all(_is_enumeration_token(p) and _is_enumeration_token(q) for p, q in diff)


def _is_tiny_line(line: str) -> bool:
    """Baris "sangat pendek": terlalu sedikit sinyal isi untuk dibandingkan."""
    return len(line) <= state.PATTERN_TINY_LINE_MAX


def _common_prefix_len(a: str, b: str) -> int:
    n = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        n += 1
    return n


def _tiny_line_match(x: str, y: str) -> bool:
    """Cocokkan dua baris SANGAT PENDEK berdasarkan BENTUK, bukan isi.

    Baris sependek "Ok." / "Oke." / "Ok ya." / "Oke deh." tidak berbagi satu
    token pun yang sama (irisan token = 0) padahal jelas varian dari unit yang
    sama -- inilah inti deteksi berbasis POLA: yang dibandingkan BENTUK kata,
    bukan daftar frasa tertentu. Dua baris sangat pendek dianggap satu pola
    bila kata PERTAMANYA berkerabat morfologis: salah satu awalan (prefix) yang
    lain, minimal 2 karakter.

      - "ok" ~ "oke" ~ "ok ya" ~ "oke deh"  -> semua berawalan "ok"  (cocok)
      - "pendahuluan" ~ "pembahasan"        -> "pendahuluan"/"pembahasan"
                                               bukan awalan satu sama lain
                                               (tidak cocok)

    Inilah yang memisahkan loop "acknowledgement pendek" (kata yang sama
    diulang dengan variasi ejaan) dari daftar/outline wajar (judul seksi yang
    memang kata berbeda). Tidak ada satu frasa pun yang di-hardcode.
    """
    if x == y:
        return True
    if not x or not y:
        return False
    fx = x.split()[0]
    fy = y.split()[0]
    if fx == fy:
        return True
    if len(fx) < 2 or len(fy) < 2:
        return False
    return fx.startswith(fy) or fy.startswith(fx)


def _fuzzy_block_match(a: list[str], b: list[str]) -> bool:
    """Dua blok dianggap unit pola yang sama bila pola kosong/berisinya sama
    DAN setiap baris berisi cocok menurut BENTUK/POLAnya (bukan daftar kata).

    Inilah yang membuat deteksi tetap bekerja saat KATA-nya berubah tapi
    POLA-nya sama: unit "Ok. / Baik saya tulis." yang di iterasi berikutnya
    menjadi "Siap. / Baik akan saya tulis." tetap cocok.

    Tiga aturan per pasangan baris:

      1. Baris SANGAT PENDEK (<= PATTERN_TINY_LINE_MAX) dibandingkan lewat
         _tiny_line_match -- berbasis BENTUK kata pertama, bukan irisan token.
         Ini yang menangkap loop "Ok. / Oke. / Ok ya. / Oke deh." yang tidak
         berbagi satu token pun tapi jelas pola yang sama.
      2. Baris biasa dibandingkan lewat _line_similarity >= PATTERN_LINE_SIMILARITY.
      3. Baris yang berbeda HANYA pada token PENOMORAN (angka / kata bilangan)
         TIDAK dihitung sebagai pengulangan -- lihat _differs_only_by_enumeration.
         Ini yang menjaga daftar bernomor ("Langkah 1: ..." / "Langkah 2: ...")
         dan daftar tanpa penanda ("Item satu" / "Item dua") tetap dianggap
         enumerasi wajar, bukan loop.

    Baris ber-penanda markdown (butir "- ", heading "# ", tabel "| ") juga
    dikecualikan dari aturan 1: daftar berbutir yang butirnya berbeda isi
    ("- Item satu" vs "- Item dua") adalah struktur dokumen wajar.
    """
    for x, y in zip(a, b):
        if not x or not y:
            if x != y:
                return False
            continue
        if _differs_only_by_enumeration(x, y):
            return False
        if (
            _is_tiny_line(x)
            and _is_tiny_line(y)
            and not _has_pattern_marker(x)
            and not _has_pattern_marker(y)
        ):
            if not _tiny_line_match(x, y):
                return False
            continue
        if _line_similarity(x, y) < state.PATTERN_LINE_SIMILARITY:
            return False
    return True


def _longest_pattern_cycle(text: str):
    """Cari SIKLUS POLA: blok `p` baris (2 <= p <= PATTERN_SHAPE_MAX_PERIOD)
    yang kembali muncul BERTURUT-TURUT minimal PATTERN_CYCLE_MIN_REPS kali,
    dengan baris KOSONG dihitung sebagai bagian dari unit pengulangan.

    Ini menutup lubang yang dua sinyal sebelumnya sama-sama buta. Pola
    degenerate yang paling sering muncul di produksi berbentuk paragraf
    pendek yang dipisah baris kosong lalu diulang, mis::

        Ok.
        <kosong>
        Baik saya tulis.
        <kosong>
        Ok.
        <kosong>
        Baik saya tulis.
        <kosong>
        Ok.
        <kosong>
        Baik saya tulis.

    Pada teks seperti itu:
      - _longest_line_run  : run maksimum 1 (tidak ada baris yang berulang
                             BERTURUT-TURUT), jadi tidak melihat apa pun;
      - _longest_line_cycle: setiap blok memuat baris kosong sehingga
                             dilewati, jadi tidak melihat apa pun.
    Yang jelas berulang di sana adalah UNIT-nya (periodenya), bukan katanya:
    rangkaian [Ok., kosong, Baik saya tulis., kosong] muncul 3x berturut-turut.
    Fungsi ini mendeteksi UNIT berulang itu. Isi barisnya boleh apa saja --
    yang diperiksa adalah apakah rangkaian baris yang sama kembali muncul
    secara periodik, jadi pola "acknowledgement pendek / pernyataan pendek"
    yang kalimatnya diganti-ganti pun tetap tertangkap selama unitnya utuh.

    Perbandingan memakai bentuk NORMAL baris (huruf kecil, spasi dirapatkan,
    tanda baca di ujung dibuang) supaya variasi kata sepele -- "Ok." vs "ok",
    "Baik saya tulis." vs "Baik, saya tulis" -- tetap dihitung sebagai unit
    yang sama. Yang dibandingkan tetap RANGKAIAN unit, bukan daftar frasa
    tertentu: tidak ada satu pun kalimat yang di-hardcode.

    Sengaja TIDAK memakai pencocokan bentuk murni (hanya panjang baris, isi
    diabaikan). Pendekatan itu terlihat paling "pola", tetapi salah tuduh pada
    jawaban wajar: daftar berbutir yang dipisah baris kosong ("- Item satu",
    kosong, "- Item dua", ...), tiga seksi pendek ("Judul A", kosong, "Isi A.",
    kosong, "Judul B", ...), atau dokumen ber-"---" antar-seksi semuanya
    membentuk siklus bentuk [pendek, kosong] yang berulang >= 3x, padahal
    isinya jelas berbeda dan jawabannya normal. Karena itu isi baris tetap
    ikut dibandingkan (dalam bentuk normal) -- itulah yang membedakan "unit
    yang benar-benar kembali" dari "dokumen yang kebetulan berstruktur sama".

    Syarat "blok harus memuat baris kosong" bukan sekadar tambahan: siklus yang
    TIDAK memuat baris kosong sudah ditangani _longest_line_cycle dengan ambang
    REPEAT_MAX_OCCUR (5), jadi sinyal ini murni aditif untuk kasus yang belum
    tercakup -- dan ambangnya boleh lebih rendah (3) karena satu unit
    multi-baris yang kembali 3x sudah menandakan mesin terjebak.

    Mengembalikan (period, repeat_count, sample_block) atau (0, 0, []).
    """
    if not text:
        return 0, 0, []

    raw = [ln.strip() for ln in text.split("\n")]
    lines = [_normalize_line(ln) for ln in raw]
    return _scan_pattern_cycle(
        lines,
        raw,
        state.PATTERN_CYCLE_MIN_REPS,
        lambda a, b: a == b,
    )


def _longest_fuzzy_pattern_cycle(text: str):
    """Sinyal pola LUNAK: unit pola yang sama kembali berulang walau ISI
    barisnya tidak persis sama antar-iterasi.

    _longest_pattern_cycle menuntut baris yang identik (setelah normalisasi),
    jadi ia gagal begitu model mengganti sedikit kalimatnya tiap putaran --
    justru gejala loop yang paling umum: "Baik saya tulis." lalu "Baik, akan
    saya tulis." lalu "Baik saya tulis sekarang.". Yang tetap SAMA adalah
    POLA-nya (acknowledgement pendek + pernyataan pendek, dipisah baris
    kosong), bukan katanya. Fungsi ini membandingkan unit secara lunak
    (kemiripan token per baris) sehingga pola seperti itu tertangkap.

    Ambangnya (PATTERN_SHAPE_MIN_REPS) sengaja LEBIH TINGGI dari pola eksak,
    karena pencocokan lunak mengabaikan sebagian isi: dokumen wajar yang
    kebetulan mirip antar-seksi bisa ikut cocok, jadi perlu pengulangan yang
    sudah tidak wajar (5x) sebelum dianggap loop.
    """
    if not text:
        return 0, 0, []

    raw = [ln.strip() for ln in text.split("\n")]
    lines = [_normalize_line(ln) for ln in raw]
    return _scan_pattern_cycle(
        lines,
        raw,
        state.PATTERN_SHAPE_MIN_REPS,
        _fuzzy_block_match,
        min_text_lines=2,
        allow_short_single=True,
    )


def _find_repeated_text(text: str, max_sample: int = 160) -> str:
    """Ambil contoh baris/siklus/pola yang paling sering diulang berturut-turut.

    Mengembalikan string pendek (<= max_sample karakter) berisi sample +
    jumlah kemunculan, atau "" kalau tidak ada yang terulang.
    Memakai definisi run/siklus/pola yang sama dengan _detect_repetition supaya
    pesan [LOOP] selalu konsisten dengan keputusan deteksinya.
    """
    if not text:
        return ""

    most_line, line_n = _longest_line_run(text)
    # Run baris tunggal yang sudah mencapai ambang adalah sinyal terkuat dan
    # paling mudah dibaca manusia -> laporkan lebih dulu.
    if line_n >= state.REPEAT_MAX_OCCUR:
        return f"baris {line_n}x: {most_line[:max_sample]!r}"

    period, reps, block = _longest_line_cycle(text)
    if period and reps * period > line_n:
        sample = " | ".join(block)
        return f"siklus {period} baris x {reps}: {sample[:max_sample]!r}"

    p_pattern, reps_pattern, block_pattern = _longest_pattern_cycle(text)
    if p_pattern:
        sample = " | ".join(x or "<kosong>" for x in block_pattern)
        return f"pola {p_pattern} baris x {reps_pattern}: {sample[:max_sample]!r}"

    p_fuzzy, reps_fuzzy, block_fuzzy = _longest_fuzzy_pattern_cycle(text)
    if p_fuzzy:
        sample = " | ".join(x or "<kosong>" for x in block_fuzzy)
        return (
            f"pola {p_fuzzy} baris x {reps_fuzzy} (mirip): "
            f"{sample[:max_sample]!r}"
        )

    if line_n < 2:
        return ""
    return f"baris {line_n}x: {most_line[:max_sample]!r}"


def _detect_repetition(text: str) -> bool:
    """Deteksi degenerate loop pada teks SATU respon.

    Tiga sinyal (semuanya menuntut pengulangan BERTURUT-TURUT, bukan total
    kemunculan tersebar -- lihat _longest_line_run untuk alasannya):

      1. Baris non-kosong yang persis sama muncul minimal REPEAT_MAX_OCCUR
         kali berturut-turut (p == 1).
      2. SIKLUS periodik: blok p baris (2 <= p <= _CYCLE_MAX_PERIOD) yang
         identik berulang minimal REPEAT_MAX_OCCUR kali berturut-turut.
         Menangkap pola seperti spam tag bergantian yang lolos dari sinyal 1
         karena tidak ada baris yang berulang berurutan.
      3. SIKLUS POLA: blok p baris (2 <= p <= PATTERN_SHAPE_MAX_PERIOD) yang
         kembali muncul minimal PATTERN_CYCLE_MIN_REPS kali, dengan baris
         KOSONG dihitung sebagai bagian unit. Menangkap pola paragraf pendek
         dipisah baris kosong lalu diulang (mis. "Ok." / "Baik saya tulis."
         bergantian) yang lolos dari sinyal 1 dan 2 karena baris kosong
         memutus run sekaligus membuat blok siklus dilewati.

    Ketiganya membandingkan RANGKAIAN baris (struktur/urutan unit), bukan
    daftar kata tertentu: tidak ada satu pun frasa yang di-hardcode, jadi
    kalimat yang isinya berbeda-beda pun tertangkap selama unitnya kembali
    berulang. Lihat _longest_pattern_cycle untuk alasan pencocokan bentuk
    ("panjang baris saja") sengaja TIDAK dipakai.
    """
    if not text:
        return False

    _, line_n = _longest_line_run(text)
    if line_n >= state.REPEAT_MAX_OCCUR:
        return True

    _period, reps, _block = _longest_line_cycle(text)
    if reps >= state.REPEAT_MAX_OCCUR:
        return True

    _p, pattern_reps, _blk = _longest_pattern_cycle(text)
    if pattern_reps >= state.PATTERN_CYCLE_MIN_REPS:
        return True

    # 4. SIKLUS POLA LUNAK: sama seperti sinyal 3, tetapi isi barisnya boleh
    #    berbeda antar-iterasi selama POLA unitnya masih sama (kemiripan token
    #    >= PATTERN_LINE_SIMILARITY). Ini menangkap loop yang paling sering
    #    terjadi di praktik: model mengulang unit "acknowledgement pendek +
    #    pernyataan pendek" sambil mengganti sedikit kalimatnya tiap putaran,
    #    sehingga sinyal 3 (yang menuntut baris identik) tidak melihat apa pun.
    #    Ambangnya lebih tinggi (PATTERN_SHAPE_MIN_REPS) karena pencocokan
    #    lunak memang lebih longgar.
    _pf, fuzzy_reps, _bf = _longest_fuzzy_pattern_cycle(text)
    return fuzzy_reps >= state.PATTERN_SHAPE_MIN_REPS


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
    """Minta konfirmasi ya/tidak ke user.

    Fail-safe: kalau stdin tidak tersedia (EOF pada mode non-interaktif
    seperti --auto/--overnight, atau Ctrl-D), anggap TOLAK (False) -- tidak
    pernah crash. Ini penting karena konfirmasi path eksternal (di luar
    workdir) TETAP wajib diminta walau --auto-approve aktif; pada mode
    non-interaktif yang tanpa stdin, jawaban otomatis yang aman adalah tolak.
    """
    # Hentikan sementara spinner yang mungkin aktif sebelum membaca stdin,
    # supaya prompt konfirmasi tidak tertutup karakter spinner. Ini pengaman
    # ganda (agent_loop.py sudah mencegah spinner untuk tool yang berpotensi
    # prompt). Spinner dilanjutkan lagi setelah input selesai dibaca.
    pause_all_spinners()
    try:
        ans = input(c_prompt(f"  {prompt} [y/N] ", C.YELLOW)).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print(c(
            "  [KONFIRMASI] Input tidak tersedia (non-interaktif) -> "
            "dianggap TOLAK.",
            C.YELLOW,
        ))
        return False
    finally:
        resume_all_spinners()
    return ans in ("y", "yes")
