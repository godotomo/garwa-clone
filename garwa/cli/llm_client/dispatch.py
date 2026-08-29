"""cli/llm_client/dispatch.py
Dipecah lebih lanjut dari cli/llm_client.py.
"""
import shutil
import sys
import time

try:

    import readline  # noqa: F401
except ImportError:
    readline = None

import requests

from .. import _state as state
from ..colors import C
from ..colors import c
from ..text_utils import _resp_text_utf8
from .nonstream_call import _call_llama_server_nonstream
from .stream_call import _call_llama_server_stream



def _is_rate_limit_error(e: Exception) -> bool:
    """Deteksi error rate limit (HTTP 429) dari exception yang dilempar
    _call_llama_server_stream()/_call_llama_server_nonstream().

    Server proxy/tunnel (mis. 9inference.cloud) sering membalas 429 dengan
    body JSON berisi type "rate_limit_error" / code "rate_limit_exceeded"
    saat kita mengirim terlalu banyak request dalam waktu singkat. Deteksi
    ini dipakai call_llama_server() untuk retry dengan sleep (backoff),
    alih-alih langsung menyerah dan mematikan giliran.

    Return True kalau exception adalah HTTPError dengan status 429, ATAU
    body response-nya mengandung penanda rate_limit (untuk jaga-jaga kalau
    status code-nya bukan 429 tapi body-nya bilang rate limit).
    """
    if isinstance(e, requests.exceptions.HTTPError):
        resp = e.response
        if resp is not None and resp.status_code == 429:
            return True

        if resp is not None:
            try:
                body = _resp_text_utf8(resp).lower()
            except Exception:
                body = ""
            if "rate_limit" in body or "too many requests" in body:
                return True
    return False


def _is_concurrent_limit_error(e: Exception) -> bool:
    """Deteksi error batas konkurensi (HTTP 429 dengan code "concurrent_limit").

    Beberapa server proxy (mis. openagentic.id) hanya mengizinkan sejumlah
    request AKTIF dalam satu waktu (biasanya 1/1). Kalau request sebelumnya
    masih diproses server, request berikut langsung ditolak 429 dengan body:

        {"error":{"code":"concurrent_limit",
                   "message":"Batas request bersamaan tercapai (1/1)...",
                   "type":"rate_limit_error"}}

    Ini BEDA dari rate-limit biasa ("terlalu banyak request per menit"): di
    sini kita harus menunggu request sebelumnya SELESAI (bisa sampai timeout
    stream), jadi backoff-nya harus jauh lebih panjang. Deteksi ini dipakai
    call_llama_server() untuk memilih backoff concurrent khusus.

    Return True kalau exception adalah HTTPError dengan status 429 DAN body
    response-nya mengandung penanda "concurrent_limit" / "bersamaan".
    """
    if isinstance(e, requests.exceptions.HTTPError):
        resp = e.response
        if resp is not None and resp.status_code == 429:
            try:
                body = _resp_text_utf8(resp).lower()
            except Exception:
                body = ""
            if "concurrent_limit" in body or "bersamaan" in body or "concurrent" in body:
                return True
    return False


def _is_server_error(e: Exception) -> bool:
    """Deteksi error server (HTTP 5xx) dari exception yang dilempar
    _call_llama_server_stream()/_call_llama_server_nonstream().

    HTTP 5xx (500 Internal Server Error, 502 Bad Gateway, 503 Service
    Unavailable, 504 Gateway Timeout, dan sejenisnya) berarti server
    model/proxy di depannya sedang bermasalah -- overload, restart,
    upstream down, dsb. Sering kali ini bersifat sementara, jadi alih-alih
    langsung mematikan seluruh giliran, call_llama_server() akan menunggu
    SERVER_ERROR_BACKOFF_SECONDS (30 detik) lalu mencoba ulang beberapa
    kali, persis seperti penanganan rate limit (HTTP 429).

    Return True kalau exception adalah HTTPError dengan status code 500-599.
    """
    if isinstance(e, requests.exceptions.HTTPError):
        resp = e.response
        if resp is not None and resp.status_code is not None:
            return 500 <= resp.status_code < 600
    return False


def _countdown_sleep(seconds: float, label: str) -> None:
    """Tidur `seconds` detik sambil menampilkan animasi hitung mundur
    (spinner + angka mundur + bilah progress) di satu baris yang di-rewrite
    via carriage return.

    Aman untuk non-TTY: kalau stdout bukan terminal (pipe/file, mode
    --auto/--overnight), langsung time.sleep() polos tanpa output apa pun
    supaya tidak mengotori log.
    """
    if not sys.stdout.isatty():
        time.sleep(seconds)
        return
    frames = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    term_w = shutil.get_terminal_size().columns or 80
    start = time.monotonic()
    idx = 0
    while True:
        elapsed = time.monotonic() - start
        if elapsed >= seconds:
            break
        remaining = max(0, seconds - elapsed)
        fraction = elapsed / seconds
        # Bilah progress 20 kolom.
        filled = int(round(fraction * 20))
        bar = "█" * filled + "░" * (20 - filled)
        frame = frames[idx % len(frames)]
        line = (
            c(f"{frame} {label} ", C.BOLD_CYAN)
            + c(f"[{bar}]", C.BOLD_CYAN)
            + c(f" {remaining:4.0f}s ", C.BOLD_WHITE)
            + c("menunggu...", C.DIM)
        )
        sys.stdout.write("\r" + line)
        sys.stdout.flush()
        idx += 1
        time.sleep(0.1)
    # Bersihkan baris.
    sys.stdout.write("\r" + " " * term_w + "\r")
    sys.stdout.flush()


def call_llama_server(url: str, model: str, messages: list,
                      temperature: float = 0.2, stream: bool = True,
                      api_key: str = "", debug: bool = False) -> str:
    """Call server model, streaming by default.

    The returned value is ALWAYS the complete assistant text, so the existing
    tool parser/context/DB pipeline remains unchanged.

    api_key: kalau diisi, dikirim sebagai header "Authorization: Bearer
    <api_key>" -- WAJIB kalau server model dijalankan dengan flag --api-key
    (lihat notebook llama_server_cloudflare_tunnel_v2.ipynb). Sebelumnya CLI
    ini tidak pernah mengirim header ini sama sekali, jadi semua request akan
    gagal 401 kalau server mewajibkan API key.

    debug: kalau True, cetak request (payload) dan seluruh respon mentah
    server (tiap chunk SSE / body JSON) ke STDERR, termasuk baris yang
    gagal di-parse dan diam-diam dilewati saat debug=False. Dipakai untuk
    mendiagnosis kasus "ada bagian respon yang belum ter-parsing dengan
    benar" tanpa harus menebak-nebak dari perilaku CLI.

    Rate limit (HTTP 429): kalau server membalas 429 (terlalu banyak
    request), fungsi ini menunggu 30 detik lalu mencoba ulang, maksimal
    RATE_LIMIT_RETRY_ATTEMPTS percobaan total. Ini mencegah seluruh giliran
    gagal hanya karena kita kebetulan kena rate limit sesaat -- yang umum
    terjadi di proxy publik.

    Error server (HTTP 5xx): kalau server membalas 500/502/503/504 (atau
    status 5xx lain -- overload, restart, upstream down), fungsi ini juga
    menunggu 30 detik lalu mencoba ulang, maksimal
    SERVER_ERROR_RETRY_ATTEMPTS percobaan total, persis seperti penanganan
    rate limit. Error 5xx sering bersifat sementara, jadi jangan langsung
    mematikan seluruh giliran.
    """
    max_loop_attempts = max(
        state.RATE_LIMIT_RETRY_ATTEMPTS,
        state.CONCURRENT_LIMIT_RETRY_ATTEMPTS,
        state.SERVER_ERROR_RETRY_ATTEMPTS,
    )
    for attempt in range(1, max_loop_attempts + 1):
        try:
            if stream:
                result = _call_llama_server_stream(url, model, messages, temperature,
                                                    api_key=api_key,
                                                    debug=debug)
            else:
                result = _call_llama_server_nonstream(url, model, messages, temperature,
                                                       api_key=api_key,
                                                       debug=debug)
            return result
        except Exception as e:
            is_concurrent = _is_concurrent_limit_error(e)
            is_rate_limit = _is_rate_limit_error(e)
            is_server_error = _is_server_error(e)
            if not (is_concurrent or is_rate_limit or is_server_error):
                raise
            if is_concurrent:
                max_attempts = state.CONCURRENT_LIMIT_RETRY_ATTEMPTS
            elif is_rate_limit:
                max_attempts = state.RATE_LIMIT_RETRY_ATTEMPTS
            else:
                max_attempts = state.SERVER_ERROR_RETRY_ATTEMPTS
            if attempt >= max_attempts:

                if is_concurrent:
                    print(c(
                        f"[ERROR] Batas request bersamaan (concurrent limit) masih "
                        f"berlanjut setelah {max_attempts} percobaan. Coba lagi nanti.",
                        C.RED,
                    ))
                elif is_rate_limit:
                    print(c(
                        f"[ERROR] Rate limit (HTTP 429) masih berlanjut setelah "
                        f"{max_attempts} percobaan. Coba lagi nanti.",
                        C.RED,
                    ))
                else:
                    print(c(
                        f"[ERROR] Error server (HTTP {e.response.status_code if e.response is not None else '5xx'}) "
                        f"masih berlanjut setelah {max_attempts} percobaan. Coba lagi nanti.",
                        C.RED,
                    ))
                raise
            if is_concurrent:
                backoff = state.CONCURRENT_LIMIT_BACKOFF_SECONDS
            elif is_rate_limit:
                backoff = state.RATE_LIMIT_BACKOFF_SECONDS
            else:
                backoff = state.SERVER_ERROR_BACKOFF_SECONDS
            sleep_sec = backoff[attempt - 1]
            if is_concurrent:
                print(c(
                    f"[CONCURRENT-LIMIT] Server hanya mengizinkan 1 request aktif "
                    f"dan request sebelumnya masih berjalan. Menunggu {sleep_sec} "
                    f"detik lalu mencoba ulang (percobaan {attempt + 1}/{max_attempts})...",
                    C.YELLOW,
                ))
            elif is_rate_limit:
                print(c(
                    f"[RATE-LIMIT] Server membalas 429 (terlalu banyak request). "
                    f"Menunggu {sleep_sec} detik lalu mencoba ulang "
                    f"(percobaan {attempt + 1}/{max_attempts})...",
                    C.YELLOW,
                ))
            else:
                status = e.response.status_code if e.response is not None else "5xx"
                print(c(
                    f"[SERVER-ERROR] Server membalas HTTP {status} (server error). "
                    f"Menunggu {sleep_sec} detik lalu mencoba ulang "
                    f"(percobaan {attempt + 1}/{max_attempts})...",
                    C.YELLOW,
                ))
            _countdown_sleep(sleep_sec, f"percobaan {attempt + 1}/{max_attempts}")
