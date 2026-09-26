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


def _find_repeated_text(text: str, max_sample: int = 160) -> str:
    """Ambil contoh baris/siklus yang paling sering diulang berturut-turut.

    Mengembalikan string pendek (<= max_sample karakter) berisi sample +
    jumlah kemunculan, atau "" kalau tidak ada yang terulang.
    Memakai definisi run/siklus yang sama dengan _detect_repetition supaya
    pesan [LOOP] selalu konsisten dengan keputusan deteksinya.
    """
    if not text:
        return ""

    most_line, line_n = _longest_line_run(text)
    period, reps, block = _longest_line_cycle(text)
    # Pilih sinyal yang mencakup lebih banyak baris (run p=1 vs siklus p>=2).
    if period and reps * period > line_n:
        sample = " | ".join(block)
        return f"siklus {period} baris x {reps}: {sample[:max_sample]!r}"
    if line_n < 2:
        return ""
    return f"baris {line_n}x: {most_line[:max_sample]!r}"


def _detect_repetition(text: str) -> bool:
    """Deteksi degenerate loop pada teks SATU respon.

    Dua sinyal (keduanya menuntut pengulangan BERTURUT-TURUT, bukan total
    kemunculan tersebar -- lihat _longest_line_run untuk alasannya):

      1. Baris non-kosong yang persis sama muncul minimal REPEAT_MAX_OCCUR
         kali berturut-turut (p == 1).
      2. SIKLUS periodik: blok p baris (2 <= p <= _CYCLE_MAX_PERIOD) yang
         identik berulang minimal REPEAT_MAX_OCCUR kali berturut-turut.
         Menangkap pola seperti spam tag bergantian yang lolos dari sinyal 1
         karena tidak ada baris yang berulang berurutan.
    """
    if not text:
        return False

    _, line_n = _longest_line_run(text)
    if line_n >= state.REPEAT_MAX_OCCUR:
        return True

    _period, reps, _block = _longest_line_cycle(text)
    return reps >= state.REPEAT_MAX_OCCUR


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
