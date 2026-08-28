"""cli/llm_errors.py
Dipecah otomatis dari cli.py (lihat cli/_state.py untuk state bersama).
"""

try:

    import readline  # noqa: F401
except ImportError:
    readline = None





class LlamaServerStreamError(Exception):
    """Server mengirim chunk SSE berisi field 'error' eksplisit di tengah
    stream (bukan HTTP error di awal request, tapi error yang muncul setelah
    streaming sudah mulai -- mis. OOM di tengah generate). Sebelumnya
    _extract_stream_content() diam-diam mengembalikan "" untuk kasus ini,
    membuatnya terlihat identik dengan 'tidak ada delta baru' padahal server
    sedang melaporkan kegagalan eksplisit.
    """


class ContextExceededError(Exception):
    """Request ditolak server model dengan HTTP 400 karena jumlah token
    prompt melebihi context window server yang sedang aktif
    (body error punya "type": "exceed_context_size_error"). Dibedakan dari
    HTTPError generik supaya run_agent_loop() bisa menangkapnya secara
    spesifik dan mencoba ulang SEKALI dengan budget trimming yang lebih
    ketat -- lihat _parse_context_exceeded() dan run_agent_loop().

    n_ctx / n_prompt_tokens diisi langsung dari body error server (field
    resmi server model) kalau berhasil diparse; None kalau body tidak
    sesuai format yang diharapkan (klasifikasi "context exceeded"-nya tetap
    dipertahankan dari status/type response, cuma detail angkanya hilang).
    """

    def __init__(self, message: str, n_ctx: int = None, n_prompt_tokens: int = None):
        super().__init__(message)
        self.n_ctx = n_ctx
        self.n_prompt_tokens = n_prompt_tokens


class RepetitionLoopError(Exception):
    """Model jatuh ke degenerate loop DI DALAM SATU respon: mulai mengulang
    kalimat/baris yang sama persis berulang-ulang (intra-response repetition)
    tanpa pernah maju. Stream dihentikan lebih awal untuk menghemat token.

    Dibedakan dari exception lain supaya run_agent_loop() bisa menangkapnya
    secara spesifik: hentikan giliran, tunggu cooldown singkat
    (LOOP_BREAK_COOLDOWN_SECONDS), lalu lanjutkan proses terakhir -- alih-alih
    membiarkan loop membakar seluruh budget output.
    """


class TruncatedGenerationError(Exception):
    """Generation dihentikan PAKSA oleh server karena kehabisan batas token
    output (finish_reason di antara TRUNCATION_FINISH_REASONS), SEBELUM
    model sempat menghasilkan konten terlihat ATAU tool_call apa pun untuk
    giliran ini.

    Kasus khas: seluruh budget completion_tokens habis dipakai untuk
    `reasoning_content` ("chain of thought" internal), dan chunk SSE
    terakhir sebelum [DONE] punya "choices": [] (cuma berisi field
    "usage" ringkasan) -- jadi `content` yang terkumpul benar-benar string
    kosong.

    Dibedakan dari exception lain supaya run_agent_loop() bisa menangkapnya
    secara spesifik: beri tahu user+model apa yang terjadi (termasuk statistik
    token kalau tersedia dari field "usage"), suntikkan instruksi eksplisit
    ke model supaya lebih ringkas, lalu retry terbatas -- BUKAN diam-diam
    dianggap giliran selesai.
    """

    def __init__(self, message: str, finish_reason: str = None,
                 completion_tokens: int = None, reasoning_tokens: int = None):
        super().__init__(message)
        self.finish_reason = finish_reason
        self.completion_tokens = completion_tokens
        self.reasoning_tokens = reasoning_tokens


def _parse_context_exceeded(response):
    """Cek apakah `response` (400 Bad Request dari server model) adalah
    error 'exceed_context_size_error', dan kalau ya, parse n_ctx &
    n_prompt_tokens dari body JSON-nya menjadi ContextExceededError.

    Format body yang diharapkan (server model / llama.cpp):
        {"error": {"code": 400, "message": "...",
                   "type": "exceed_context_size_error",
                   "n_prompt_tokens": 85043, "n_ctx": 65536}}

    Return None kalau response bukan 400, bukan JSON, atau bukan error
    jenis ini (mis. 400 karena payload malformed lain) -- supaya caller
    tetap memperlakukannya sebagai HTTPError generik seperti sebelumnya,
    bukan dianggap context-exceeded secara keliru.
    """
    if response is None or response.status_code != 400:
        return None
    try:
        data = response.json()
    except Exception:
        return None
    err = data.get("error") if isinstance(data, dict) else None
    if not isinstance(err, dict):
        return None
    if err.get("type") != "exceed_context_size_error":
        return None
    message = err.get("message") or "request melebihi context size server"
    n_ctx = err.get("n_ctx")
    n_prompt_tokens = err.get("n_prompt_tokens")
    try:
        n_ctx = int(n_ctx) if n_ctx is not None else None
    except (TypeError, ValueError):
        n_ctx = None
    try:
        n_prompt_tokens = int(n_prompt_tokens) if n_prompt_tokens is not None else None
    except (TypeError, ValueError):
        n_prompt_tokens = None
    return ContextExceededError(message, n_ctx=n_ctx, n_prompt_tokens=n_prompt_tokens)
