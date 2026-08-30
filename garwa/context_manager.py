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

import json
import logging
import sys
import time

import requests

from . import db as dbmod
from . import token_utils
from .cli.colors import C
from .cli.colors import c
from .cli.progress import Spinner

logger = logging.getLogger(__name__)

SUMMARIZE_THRESHOLD_RATIO = 0.2    # ringkas kalau pemakaian > 35% dari budget context
KEEP_TAIL_MESSAGES = 8              # jumlah pesan mentah terbaru yang selalu dipertahankan utuh
RESERVE_FOR_RESPONSE = 1024*2         # token yang disisakan untuk jawaban model + tool_result berikutnya
MIN_CONTEXT_WINDOW_HISTORY_FLOOR = 256  # lantai hard_budget riwayat, lihat prepare_context_messages()
MIN_MESSAGES_TO_SUMMARIZE = KEEP_TAIL_MESSAGES + 4  # jangan ringkas kalau riwayat masih pendek

SUMMARIZE_REQUEST_TIMEOUT_SECONDS = 60

SUMMARIZE_MAX_RETRIES = 3          # total percobaan = 1 + SUMMARIZE_MAX_RETRIES
SUMMARIZE_RETRY_BASE_DELAY = 2.0   # detik, delay pertama; digandakan tiap retry
SUMMARIZE_RETRY_MAX_DELAY = 15.0   # batas atas delay antar-retry (detik)


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


def _tools_payload_tokens(tools_payload) -> int:
    """Hitung berapa token yang dipakai field `"tools"` ala OpenAI kalau
    disertakan di request (lihat build_openai_tools_payload() di cli.py).
    Server juga menghitung token `"tools"` sebagai bagian dari prompt, jadi
    budget harus memperhitungkannya untuk menghindari ContextExceededError.

    Dihitung dari representasi JSON-nya (persis seperti yang akan dikirim
    di payload), bukan diestimasi. Return 0 kalau tools_payload kosong/None.
    """
    if not tools_payload:
        return 0
    try:
        return token_utils.count_tokens(json.dumps(tools_payload, ensure_ascii=False))
    except Exception:

        return 0

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


def _project_notes_section(db_path: str, session_id: str) -> str:
    """Bangun blok teks berisi catatan proyek persisten (tabel project_notes,
    ditulis via tool `remember`) untuk workdir sesi ini.

    Catatan ini persisten lintas sesi dan TIDAK ikut diringkas/dibuang oleh
    summarization, jadi menyuntikkannya ke system prompt setiap giliran
    menjamin instruksi/preferensi/keputusan yang disimpan via `remember`
    tetap tampil utuh di konteks model -- tidak hilang walau riwayat
    percakapan sudah diringkas berkali-kali.
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
    lines = [f"- {n['key']}: {n['value']}" for n in notes]
    return (
        "\n\nCATATAN PROYEK PERSISTEN (disimpan user/model via tool `remember`, "
        "jangan dianggap usang walau riwayat sudah diringkas):\n"
        + "\n".join(lines)
    )


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
    if isinstance(exc, requests.Timeout):
        return True
    if isinstance(exc, requests.ConnectionError):
        return True
    if isinstance(exc, requests.HTTPError):
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
            resp = requests.post(
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
        with Spinner("Meringkas riwayat percakapan...") as spinner:
            def _progress(attempt: int, total: int) -> None:
                fraction = (attempt + 1) / total
                spinner.set_progress(fraction)
                spinner.set_status(
                    f"mengirim ke model {model} (percobaan {attempt + 1}/{total})"
                )

            new_summary = _summarize_text(
                url, model, chunk_text,
                api_key=api_key, progress=_progress,
            )
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
) -> list:
    """Summarize if needed, rebuild context from DB, then enforce a hard budget.

    `tools_payload` (opsional, backward-compatible -- default None berarti
    perilaku identik dengan sebelum parameter ini ada): field "tools" ala
    OpenAI yang benar-benar disertakan di request llama-server (lihat
    build_openai_tools_payload() di cli.py). Server menghitung token field
    ini sebagai bagian dari prompt, tapi SEBELUM perubahan ini
    context_manager sama sekali tidak tahu field itu ada, sehingga budget
    `messages` yang dihitung di sini bisa "pas" padahal request sungguhan
    (messages + tools) sudah melebihi context window server -- lihat
    _tools_payload_tokens() untuk detail. Dengan parameter ini, token
    tools ikut direservasi di hard_budget SEBELUM messages dipangkas.
    """
    if context_window_tokens <= reserve_for_response + 128:
        raise ValueError(
            f"context_window_tokens terlalu kecil: {context_window_tokens}. "
            f"Harus lebih besar dari reserve_for_response ({reserve_for_response}) + 128."
        )

    tools_tokens = _tools_payload_tokens(tools_payload)

    maybe_summarize(
        db_path=db_path,
        session_id=session_id,
        url=url,
        model=model,
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

    hard_budget = context_window_tokens - reserve_for_response - tools_tokens

    hard_budget = max(hard_budget, MIN_CONTEXT_WINDOW_HISTORY_FLOOR)
    if token_utils.count_messages_tokens(messages) <= hard_budget:
        return messages

    if len(messages) <= 1:
        return messages

    system_message = messages[0]
    tail = messages[1:]

    system_tokens = token_utils.count_messages_tokens([system_message])
    tail_tokens = [token_utils.count_messages_tokens([m]) for m in tail]
    total = system_tokens + sum(tail_tokens)

    start = 0
    while start < len(tail) and total > hard_budget:
        total -= tail_tokens[start]
        start += 1

    while start < len(tail) and tail[start].get("kind") == "tool_result":
        start += 1

    return [system_message] + tail[start:]