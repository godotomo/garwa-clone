"""cli/agent_loop.py
Dipecah otomatis dari cli.py (lihat cli/_state.py untuk state bersama).
"""
import json
import time

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from .. import context_manager
from .. import db as dbmod
from . import _state as state
from .colors import C
from .colors import c
from .json_repair import extract_tool_call
from .llm_client import call_llama_server
from .llm_errors import ContextExceededError
from .llm_errors import RepetitionLoopError
from .llm_errors import TruncatedGenerationError
from .markdown_render import _render_markdown_once
from .spinner import Spinner
from .text_utils import _find_repeated_text
from .text_utils import _loop_similarity
from .tool_exec import execute_tool
from .tool_schema import _convert_alt_tool_call_syntax
from .tool_schema import build_openai_tools_payload
from .vision import _inject_attachment_instructions
from .vision import _prepare_messages_for_vision


def _shorten(text: str, limit: int = 160) -> str:
    """Ringkas teks untuk ditampilkan di pesan [LOOP].

    Menghapus whitespace berlebih dan memotong ke `limit` karakter supaya
    pesan loop tetap ringkas namun tetap menunjukkan KEBIASAAN yang diulang
    (mis. tool_call yang sama persis antar-iterasi, yang tidak tertangkap
    oleh `_find_repeated_text` karena repetisinya antar-respon, bukan
    internal dalam satu respon).
    """
    if not text:
        return ""
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."



def run_agent_loop(args, session_id: str, system_content: str) -> str:
    """Jalankan giliran agent sampai model berhenti memanggil tool.

    Mengasumsikan pesan user untuk giliran ini SUDAH ditambahkan ke DB oleh
    caller (persis seperti perilaku loop interaktif sebelum refactor ini).
    Mengembalikan teks terlihat (non tool_call) terakhir dari assistant,
    supaya caller non-interaktif (mode --auto/--overnight) bisa memakainya
    kalau perlu, tanpa mengubah cara loop interaktif bekerja.
    """
    last_visible = ""

    _tool_call_seq = 0

    _loop_history = []  # daftar (assistant_text) dari iterasi-iterasi terakhir
    _loop_interventions = 0  # berapa kali kita sudah menyuntikkan peringatan loop

    _error_history = []  # daftar fingerprint error dari iterasi-iterasi terakhir
    _error_interventions = 0  # berapa kali kita sudah menyuntikkan peringatan error

    _truncation_count = 0
    _MAX_TRUNCATION_RETRIES = 2

    _loop_count = 0
    _MAX_LOOP_RETRIES = 2

    _t_start = time.monotonic()          # awal giliran (untuk durasi total)
    _iteration_count = 0                 # jumlah iterasi loop (putaran model)
    _error_count = 0                     # jumlah tool_call yang menghasilkan error

    def _emit_summary():
        """Cetak ringkasan akhir giliran: jumlah tool call, sukses/error,
        durasi total, dan jumlah iterasi. Dipanggil di setiap titik return
        (termasuk jalur berhenti paksa karena loop/truncation/error-loop)
        supaya pengguna selalu mendapat gambaran singkat aktivitas giliran.
        """
        _t_total = time.monotonic() - _t_start
        _success = _tool_call_seq - _error_count
        print(c("─" * 60, C.DIM))
        print(c("  Ringkasan giliran", C.BOLD))
        print(c(
            f"  tool calls : {_tool_call_seq}  (✓{_success} ✗{_error_count})",
            C.BOLD_GREEN if _error_count == 0 else C.YELLOW,
        ))
        print(c(f"  durasi     : {_t_total:.1f}s", C.DIM))
        print(c(f"  iterasi    : {_iteration_count}", C.DIM))
        if _truncation_count:
            print(c(f"  truncasi   : {_truncation_count}x", C.YELLOW))
        if _loop_count:
            print(c(f"  loop       : {_loop_count}x", C.YELLOW))

    def _build_context_messages(context_window_tokens: int):
        """Rakit `messages` dari histori DB via context_manager, memakai
        `context_window_tokens` sebagai budget trimming/summarization.

        Diekstrak jadi closure lokal (bukan lagi inline di badan loop)
        supaya BISA dipanggil DUA KALI dalam satu iterasi giliran yang sama
        -- sekali dengan args.context_window normal, dan sekali lagi dengan
        budget yang dipersempit kalau percobaan pertama ditolak server
        dengan ContextExceededError (lihat blok try/except di bawah).
        Tanpa ekstraksi ini, logic compat lama/baru context_manager di atas
        harus diduplikasi manual di jalur retry -- rawan divergen.
        """

        if hasattr(context_manager, "prepare_context_messages"):

            kwargs = dict(
                db_path=args.db_path,
                session_id=session_id,
                system_prompt=system_content,
                url=args.url,
                model=args.model,
                context_window_tokens=context_window_tokens,
                api_key=args.api_key,

                tools_payload=build_openai_tools_payload(),
            )
            # Hanya teruskan parameter tuning kalau benar-benar diset user
            # (melalui flag CLI atau config); kalau None, biarkan context_manager
            # memakai defaultnya sendiri supaya tidak menimpa dengan None.
            for _key in ("reserve_for_response", "summarize_threshold_ratio", "keep_tail_messages"):
                _val = getattr(args, _key, None)
                if _val is not None:
                    kwargs[_key] = _val
            while True:
                try:
                    return context_manager.prepare_context_messages(**kwargs)
                except TypeError:
                    if "tools_payload" in kwargs:
                        if not state._WARNED_CONTEXT_MANAGER_NO_TOOLS_BUDGET[0]:
                            print(c(
                                "[WARN] context_manager.py versi ini belum mendukung "
                                "parameter tools_payload -- budget token field "
                                "\"tools\" TIDAK direservasi saat trimming/"
                                "summarization history, request bisa lebih gampang "
                                "kena ContextExceededError. Update context_manager.py juga.",
                                C.YELLOW,
                            ))
                            state._WARNED_CONTEXT_MANAGER_NO_TOOLS_BUDGET[0] = True
                        kwargs.pop("tools_payload")
                        continue
                    if "api_key" in kwargs:
                        if args.api_key and not state._WARNED_CONTEXT_MANAGER_NO_AUTH[0]:
                            print(c(
                                "[WARN] context_manager.py versi ini belum mendukung "
                                "parameter api_key -- request summarization TIDAK "
                                "membawa API key dan bisa gagal 401 kalau server "
                                "mewajibkannya. Update context_manager.py juga.",
                                C.YELLOW,
                            ))
                            state._WARNED_CONTEXT_MANAGER_NO_AUTH[0] = True
                        kwargs.pop("api_key")
                        continue
                    raise
        else:

            ms_kwargs = dict(
                db_path=args.db_path,
                session_id=session_id,
                url=args.url,
                model=args.model,
                context_window_tokens=context_window_tokens,
                api_key=args.api_key,
                tools_payload=build_openai_tools_payload(),
                system_prompt=system_content,
            )
            while True:
                try:
                    context_manager.maybe_summarize(**ms_kwargs)
                    break
                except TypeError:
                    if "system_prompt" in ms_kwargs:
                        ms_kwargs.pop("system_prompt")
                        continue
                    if "tools_payload" in ms_kwargs:
                        if not state._WARNED_CONTEXT_MANAGER_NO_TOOLS_BUDGET[0]:
                            print(c(
                                "[WARN] context_manager.py versi ini belum mendukung "
                                "parameter tools_payload -- budget token field "
                                "\"tools\" TIDAK direservasi saat summarization. "
                                "Update context_manager.py juga.",
                                C.YELLOW,
                            ))
                            state._WARNED_CONTEXT_MANAGER_NO_TOOLS_BUDGET[0] = True
                        ms_kwargs.pop("tools_payload")
                        continue
                    if "api_key" in ms_kwargs:
                        if args.api_key and not state._WARNED_CONTEXT_MANAGER_NO_AUTH[0]:
                            print(c(
                                "[WARN] context_manager.py versi ini belum mendukung "
                                "parameter api_key -- request summarization TIDAK "
                                "membawa API key dan bisa gagal 401 kalau server "
                                "mewajibkannya. Update context_manager.py juga.",
                                C.YELLOW,
                            ))
                            state._WARNED_CONTEXT_MANAGER_NO_AUTH[0] = True
                        ms_kwargs.pop("api_key")
                        continue
                    raise
            return context_manager.build_context_messages(
                db_path=args.db_path,
                session_id=session_id,
                system_prompt=system_content,
            )

    for _ in range(args.max_tool_iters):
        _iteration_count += 1
        print(c("─" * 60, C.DIM))
        attempt_budget = args.context_window
        messages = _build_context_messages(attempt_budget)

        messages = _inject_attachment_instructions(messages)

        vision_messages = _prepare_messages_for_vision(messages)

        try:
            assistant_text = call_llama_server(
                args.url, args.model, vision_messages, stream=not args.no_stream,
                api_key=args.api_key, debug=args.debug, temperature=args.temperature,
            )
        except ContextExceededError as e:

            overage = None
            if e.n_prompt_tokens is not None and e.n_ctx is not None:
                overage = e.n_prompt_tokens - e.n_ctx

            if overage is not None and overage > 0:

                retry_budget = attempt_budget - overage - state.CONTEXT_WINDOW_SAFETY_MARGIN
            else:

                retry_budget = attempt_budget // 2

            if retry_budget >= attempt_budget:
                retry_budget = attempt_budget - max(attempt_budget // 4, 1024)
            retry_budget = max(retry_budget, state.MIN_CONTEXT_WINDOW)

            overage_note = f", overage server {overage} token" if overage is not None else ""
            print(c(
                f"[RETRY] context_manager meleset dari budget yang diminta "
                f"(diberi {attempt_budget} token, server melaporkan prompt "
                f"{e.n_prompt_tokens if e.n_prompt_tokens is not None else '?'} "
                f"token{overage_note}). Mencoba ulang dengan budget lebih "
                f"ketat: {retry_budget} token (sebelumnya {attempt_budget}).",
                C.YELLOW,
            ))

            args.context_window = retry_budget
            messages = _build_context_messages(retry_budget)
            vision_messages = _prepare_messages_for_vision(messages)
            try:
                assistant_text = call_llama_server(
                    args.url, args.model, vision_messages, stream=not args.no_stream,
                    api_key=args.api_key, debug=args.debug, temperature=args.temperature,
                )
            except ContextExceededError:

                print(c(
                    "[ERROR] Retry dengan budget lebih ketat tetap gagal. "
                    "Kalau overage server dari attempt_budget di atas jauh "
                    "lebih besar dari histori percakapan yang wajar, "
                    "kemungkinan penyebabnya BUKAN histori panjang, "
                    "melainkan bagian FIXED dari request (system prompt "
                    "berisi daftar tool + skill, dan/atau field \"tools\" "
                    "JSON yang mengulang skema tool yang sama -- lihat "
                    "build_tool_schema_text()/build_openai_tools_payload()) "
                    "yang tidak ikut dipangkas oleh context_manager sama "
                    "sekali. Cek proporsi ukuran system prompt vs total "
                    "payload di log --debug; pertimbangkan menaikkan "
                    "--ctx-size server, atau memangkas system prompt "
                    "(mis. kurangi jumlah skill yang di-index, atau jangan "
                    "duplikasi skema tool ke system prompt teks kalau "
                    "\"tools\" JSON native sudah dipakai).",
                    C.RED,
                ))
                raise
        except RepetitionLoopError as e:

            _loop_count += 1

            if _loop_count > _MAX_LOOP_RETRIES:

                _rep_detail = str(e.args[0]) if e.args else ""
                print(c(
                    f"\n[LOOP] Respon model berulang (degenerate loop) "
                    f"{_loop_count}x berturut-turut tanpa pernah "
                    f"menghasilkan jawaban/tool_call. "
                    "Menghentikan giliran ini -- kemungkinan model terjebak "
                    "dalam pola repetitif yang tidak bisa dipatahkan."
                    + (f"\n  {_rep_detail}" if _rep_detail else ""),
                    C.RED,
                ))
                _emit_summary()
                return last_visible

            print(c(
                f"  [LOOP] Respon model berulang di dalam satu respon "
                f"(degenerate loop). Menunggu {state.LOOP_BREAK_COOLDOWN_SECONDS} "
                f"detik lalu melanjutkan proses terakhir...",
                C.YELLOW,
            ))
            time.sleep(state.LOOP_BREAK_COOLDOWN_SECONDS)
            continue
        except TruncatedGenerationError as e:

            _truncation_count += 1
            stats = []
            if e.finish_reason:
                stats.append(f"finish_reason={e.finish_reason}")
            if e.completion_tokens is not None:
                stats.append(f"completion_tokens={e.completion_tokens}")
            if e.reasoning_tokens is not None:
                stats.append(f"reasoning_tokens={e.reasoning_tokens}")
            stats_str = f" ({', '.join(stats)})" if stats else ""

            if _truncation_count > _MAX_TRUNCATION_RETRIES:

                print(c(
                    f"\n[TRUNCATED] Model kehabisan batas token output "
                    f"{_truncation_count}x berturut-turut tanpa pernah "
                    f"menghasilkan jawaban/tool_call{stats_str}. "
                    "Menghentikan giliran ini -- kemungkinan model butuh "
                    "reasoning yang jauh lebih panjang dari budget output "
                    "yang tersedia untuk task ini, atau server perlu "
                    "batas token (max_tokens/n_predict) yang lebih besar.",
                    C.RED,
                ))
                _emit_summary()
                return last_visible

            print(c(
                f"\n[TRUNCATED] Respon model terpotong -- kehabisan batas "
                f"token output SEBELUM menghasilkan jawaban/tool_call apa "
                f"pun{stats_str}. Menyuntikkan instruksi agar model lebih "
                "ringkas dan mencoba lagi...",
                C.YELLOW,
            ))
            truncation_warning = (
                "<tool_result>\n"
                "[TRUNCATED] Respon Anda (model) SEBELUMNYA terpotong "
                "paksa oleh server karena kehabisan batas token output -- "
                "SEBELUM Anda sempat menuliskan jawaban atau tool_call "
                "apa pun. Kemungkinan besar penyebabnya: proses berpikir "
                "internal (reasoning/chain-of-thought) Anda terlalu "
                "panjang dan menghabiskan seluruh budget token yang "
                "tersedia. Pada percobaan berikutnya: PERSINGKAT proses "
                "berpikir Anda secara signifikan, dan langsung ke inti -- "
                "tool_call atau jawaban akhir yang ringkas. Jangan ulangi "
                "proses berpikir yang sama panjangnya.\n"
                "</tool_result>"
            )
            dbmod.add_message(
                args.db_path,
                session_id,
                "user",
                truncation_warning,
                kind="tool_result",
            )
            continue

        _truncation_count = 0
        _loop_count = 0

        assistant_text = _convert_alt_tool_call_syntax(assistant_text)

        _loop_history.append(assistant_text)
        if len(_loop_history) > state.LOOP_REPEAT_WINDOW:
            _loop_history.pop(0)

        # --- Unified loop detection (perbaikan Bug 10,11,12,13,14) ---
        # Skip empty responses
        if assistant_text.strip() == "":
            _is_loop = False
            _repeat_count = 0
        else:
            # Window tanpa item yang baru di-append (Bug 11: jangan hitung diri sendiri)
            window_prev = _loop_history[:-1]

            # 1. Direct check: berapa item di window yang mirip (≥threshold)
            #    dengan respons saat ini? Exact match (similarity=1.0) otomatis
            #    termasuk -- tidak lagi dipisah (Bug 12: unified exact+similarity).
            _repeat_count = sum(
                1 for prev in window_prev
                if _loop_similarity(prev, assistant_text) >= state.LOOP_SIMILARITY_THRESHOLD
            )

            # 2. Alternating pattern detection (Bug 10: A/B/A/B).
            #    twin_count lama menghitung JUMLAH ITEM BERBEDA yang punya
            #    kembaran, sehingga pola 2-siklus A/B/A/B selalu jenuh di 2
            #    (hanya ada 2 item berbeda) dan tidak pernah mencapai threshold.
            #    Akibatnya loop alternating berkelanjutan (A/B/A/B/A/B...)
            #    tidak pernah terdeteksi (Bug 16).
            #
            #    FIXED: hitung JUMLAH KEMUNCULAN item yang berulang dalam
            #    window (item yang muncul >= 2x, dihitung setiap kemunculannya).
            #    Untuk window [A,B,A,B]: item berulang = A(2) + B(2) = 4 >= 3
            #    → pola alternating berkelanjutan terdeteksi.
            _twin_count = 0
            for i, item in enumerate(_loop_history):
                # item punya kembaran di posisi lain dalam window (bukan hanya
                # sebelumnya) → dihitung. Ini menghitung SEMUA kemunculan item
                # yang berulang: [A,B,A,B] → A(0,2) + B(1,3) = 4.
                if any(
                    _loop_similarity(item, _loop_history[j]) >= state.LOOP_SIMILARITY_THRESHOLD
                    for j in range(len(_loop_history))
                    if j != i
                ):
                    _twin_count += 1

            # twin_count = jumlah item (termasuk posisi pertama) yang punya
            # kembaran. Nilai maksimum = LOOP_REPEAT_WINDOW (window penuh semua
            # identik). Threshold window-1 menangkap pola alternating
            # berkelanjutan (mis. [A,B,A,B] → 4) tanpa false-positive pada
            # window yang hanya punya 1 duplikat (mis. [A,B,C,A] → 2).
            _is_loop = (
                _repeat_count >= state.LOOP_REPEAT_THRESHOLD
                or _twin_count >= state.LOOP_REPEAT_WINDOW - 1
            )

        if _is_loop:
            if _loop_interventions < 1:

                _loop_interventions += 1
                _rep = _find_repeated_text(assistant_text) or _shorten(assistant_text)
                print(c(
                    f"  [LOOP] Model mengulang respon yang sama "
                    f"({_repeat_count}x dalam {state.LOOP_REPEAT_WINDOW} iterasi "
                    f"terakhir). Menyuntikkan peringatan agar model berhenti "
                    f"mengulang dan mengambil langkah baru..."
                    + (f"\n  ulang: {_rep}" if _rep else ""),
                    C.YELLOW,
                ))
                loop_warning = (
                    "<tool_result>\n"
                    "[LOOP-DETECTED] PERINGATAN TEGAS: Anda (model) baru saja "
                    "mengulang respon yang SAMA PERSIS beberapa kali "
                    "berturut-turut tanpa pernah maju. Ini indikasi jelas "
                    "Anda terjebak dalam loop yang tidak produktif.\n"
                    + (f"RESPON YANG DIULANG: {_rep}\n" if _rep else "")
                    + "\n"
                    "INSTRUKSI WAJIB -- JANGAN ULANGI RESPON YANG SAMA:\n"
                    "1. BERHENTI SEKARANG juga mengulang respon/tool_call yang "
                    "identik dengan yang sudah Anda kirim sebelumnya.\n"
                    "2. JANGAN memanggil tool yang sama dengan argumen yang "
                    "sama persis seperti yang baru saja gagal/berulang.\n"
                    "3. Ambil langkah BARU yang berbeda dari semua langkah "
                    "sebelumnya: periksa ulang hasil tool terakhir, lalu "
                    "lanjutkan ke langkah berikutnya yang BELUM pernah "
                    "dicoba.\n"
                    "4. Kalau semua langkah yang masuk akal sudah dicoba dan "
                    "tidak ada yang berhasil, BERHENTI mencoba dan berikan "
                    "jawaban akhir yang jujur tentang apa yang sudah "
                    "dikerjakan dan apa yang gagal.\n"
                    "\n"
                    "Mengulang respon yang sama lagi akan dianggap sebagai "
                    "kegagalan dan giliran ini akan dihentikan paksa.\n"
                    "</tool_result>"
                )
                dbmod.add_message(
                    args.db_path,
                    session_id,
                    "user",
                    loop_warning,
                    kind="tool_result",
                )
                continue
            else:

                _rep = _find_repeated_text(assistant_text) or _shorten(assistant_text)
                print(c(
                    f"  [LOOP] Model masih mengulang respon yang sama "
                    f"({_repeat_count}x dalam {state.LOOP_REPEAT_WINDOW} iterasi "
                    f"terakhir) meski sudah diperingatkan. Menghentikan "
                    f"giliran ini untuk mencegah loop tak berujung."
                    + (f"\n  ulang: {_rep}" if _rep else ""),
                    C.RED,
                ))

                print(c(
                    f"  [LOOP] Menunggu {state.LOOP_BREAK_COOLDOWN_SECONDS} detik "
                    f"sebelum melanjutkan proses terakhir...",
                    C.DIM,
                ))
                time.sleep(state.LOOP_BREAK_COOLDOWN_SECONDS)
                _emit_summary()
                return last_visible

        dbmod.add_message(
            args.db_path,
            session_id,
            "assistant",
            assistant_text,
            kind="chat",
        )

        visible_text = state.TOOL_CALL_RE.sub("", assistant_text).strip()
        if visible_text:
            last_visible = visible_text
        if args.no_stream and visible_text:
            _render_markdown_once(visible_text)

        name, arguments = extract_tool_call(assistant_text)

        if name is None:
            _emit_summary()
            return last_visible

        if name == "PARSE_ERROR":
            error_msg = (
                f"[ERROR] tool_call JSON tidak valid: {arguments}. "
                "Perbaiki format JSON dan coba lagi."
            )
            print(c(f"  {error_msg}", C.RED))

            # Track PARSE_ERROR di history yang sama dengan error tool biasa,
            # supaya model yang terus-menerus menghasilkan JSON tidak valid
            # (mis. placeholder '...') ikut terdeteksi sebagai loop dan bisa
            # dipaksa berhenti, bukan loop tak berujung tanpa intervensi.
            _parse_fp = f"PARSE_ERROR::{arguments.strip()}"
            _error_history.append(_parse_fp)
            if len(_error_history) > state.ERROR_REPEAT_WINDOW:
                _error_history.pop(0)
            _parse_repeat_count = _error_history.count(_parse_fp)
            _is_parse_loop = _parse_repeat_count >= state.ERROR_REPEAT_THRESHOLD

            if _is_parse_loop and _error_interventions < 1:
                _error_interventions += 1
                print(c(
                    f"  [ERROR-LOOP] Model mengulang tool_call JSON yang "
                    f"tidak valid ({_parse_repeat_count}x dalam "
                    f"{state.ERROR_REPEAT_WINDOW} iterasi terakhir). "
                    f"Menyuntikkan peringatan tegas agar model memperbaiki "
                    f"format JSON-nya..."
                    + (f"\n  ulang: {_shorten(arguments)}" if arguments else ""),
                    C.YELLOW,
                ))
                tool_result_msg = (
                    "<tool_result>\n"
                    "[ERROR-LOOP-DETECTED] PERINGATAN TEGAS: Anda (model) "
                    "berulang kali menghasilkan tool_call dengan JSON yang "
                    "TIDAK VALID (format sama/serupa) tanpa pernah "
                    "memperbaikinya.\n"
                    + (f"JSON YANG GAGAL: {_shorten(arguments)}\n" if arguments else "")
                    + "\n"
                    "INSTRUKSI WAJIB:\n"
                    "1. BERHENTI mengulang tool_call dengan format yang sama.\n"
                    "2. Periksa pesan error di atas dengan saksama dan "
                    "PERBAIKI format JSON Anda secara fundamental (jangan "
                    "sekadar mengirim ulang hal yang sama).\n"
                    "3. Kalau Anda menulis '...' (ellipsis) sebagai "
                    "placeholder, ganti dengan field lengkap yang valid.\n"
                    "4. Kalau sudah tidak ada cara yang benar, BERHENTI dan "
                    "berikan jawaban akhir yang jujur.\n"
                    "\n"
                    "Mengulang JSON tidak valid yang sama lagi akan "
                    "dianggap kegagalan dan giliran ini dihentikan paksa.\n"
                    "</tool_result>"
                )
                dbmod.add_message(
                    args.db_path,
                    session_id,
                    "user",
                    tool_result_msg,
                    kind="tool_result",
                )
                continue

            if _is_parse_loop:
                print(c(
                    f"  [ERROR-LOOP] Model masih mengulang tool_call JSON "
                    f"yang tidak valid ({_parse_repeat_count}x dalam "
                    f"{state.ERROR_REPEAT_WINDOW} iterasi terakhir) meski "
                    f"sudah diperingatkan. Menghentikan giliran ini untuk "
                    f"mencegah loop tak berujung."
                    + (f"\n  ulang: {_shorten(arguments)}" if arguments else ""),
                    C.RED,
                ))
                print(c(
                    f"  [ERROR-LOOP] Menunggu {state.LOOP_BREAK_COOLDOWN_SECONDS} "
                    f"detik sebelum melanjutkan proses terakhir...",
                    C.DIM,
                ))
                time.sleep(state.LOOP_BREAK_COOLDOWN_SECONDS)
                _emit_summary()
                return last_visible

            tool_result_msg = (
                "<tool_result>\n"
                f"[ERROR] tool_call JSON tidak valid: {arguments}.\n"
                "\n"
                "INSTRUKSI TEGAS: JANGAN mengulang tool_call yang sama "
                "persis dengan yang baru saja gagal di-parse. Periksa "
                "kembali format JSON Anda -- pastikan sintaksnya valid "
                "(tanda kutip ganda, koma, kurung kurawal seimbang) -- "
                "lalu kirim tool_call yang BENAR dan BERBEDA. Kalau Anda "
                "terus mengulang tool_call yang sama, giliran ini akan "
                "dihentikan paksa.\n"
                "</tool_result>"
            )
            dbmod.add_message(
                args.db_path,
                session_id,
                "user",
                tool_result_msg,
                kind="tool_result",
            )
            continue

        _tool_call_seq += 1
        state._tool_call_index.set(_tool_call_seq)
        _t0 = time.monotonic()
        if args.auto_approve:
            # Mode non-interaktif: tidak ada prompt konfirmasi stdin, jadi
            # aman menampilkan spinner selama tool berjalan.
            with Spinner(f"menjalankan {name}"):
                result = execute_tool(name, arguments, args.auto_approve)
        else:
            # Mode interaktif: tool yang destruktif/force bisa memunculkan
            # prompt konfirmasi lewat stdin. Spinner ditiadakan agar prompt
            # tidak bertabrakan dengan karakter spinner di terminal.
            result = execute_tool(name, arguments, args.auto_approve)
        _elapsed = time.monotonic() - _t0
        _is_error = result.strip().startswith("[ERROR]") or result.strip().startswith("[DITOLAK]")
        _icon = "✗" if _is_error else "✓"
        _status_color = C.BOLD_RED if _is_error else C.BOLD_GREEN
        print(c(
            f"  {_icon} {name} ({_elapsed:.2f}s)",
            _status_color,
        ))
        print(c("  ← hasil:", C.MAGENTA))
        preview = result if len(result) < 1500 else result[:1500] + "\n...(dipotong)"
        print(c(preview, C.DIM))

        _is_error = result.strip().startswith("[ERROR]") or result.strip().startswith("[DITOLAK]")
        if _is_error:
            _error_count += 1

            try:
                _arg_fp = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
            except (TypeError, ValueError):
                _arg_fp = repr(arguments)
            _error_fp = f"{name}::{_arg_fp}::{result.strip()}"
            _error_history.append(_error_fp)
            if len(_error_history) > state.ERROR_REPEAT_WINDOW:
                _error_history.pop(0)

            _error_repeat_count = _error_history.count(_error_fp)
            _is_error_loop = _error_repeat_count >= state.ERROR_REPEAT_THRESHOLD

            if _is_error_loop:
                _err_detail = f"{name} {_shorten(_arg_fp)}"
                if _error_interventions < 1:

                    _error_interventions += 1
                    print(c(
                        f"  [ERROR-LOOP] Model mengulang tool_call yang "
                        f"menghasilkan error yang sama "
                        f"({_error_repeat_count}x dalam {state.ERROR_REPEAT_WINDOW} "
                        f"iterasi terakhir). Menyuntikkan peringatan tegas "
                        f"agar model berhenti mengulang dan mengambil "
                        f"langkah baru..."
                        + (f"\n  ulang: {_err_detail}" if _err_detail else ""),
                        C.YELLOW,
                    ))
                    error_loop_warning = (
                        "<tool_result>\n"
                        "[ERROR-LOOP-DETECTED] PERINGATAN TEGAS: Anda (model) "
                        "baru saja memanggil tool yang sama dengan argumen "
                        "yang sama (atau hampir sama) beberapa kali "
                        "berturut-turut, dan SETIAP KALI mendapat ERROR yang "
                        "sama persis -- tanpa pernah maju. Ini indikasi "
                        "jelas Anda terjebak dalam loop yang tidak "
                        "produktif.\n"
                        + (f"TOOL_CALL YANG DIULANG: {_err_detail}\n" if _err_detail else "")
                        + "\n"
                        "INSTRUKSI WAJIB -- JANGAN ULANGI RESPON YANG SAMA:\n"
                        "1. BERHENTI SEKARANG juga memanggil tool yang sama "
                        "dengan argumen yang sama persis seperti yang baru "
                        "saja gagal.\n"
                        "2. JANGAN mengulang tool_call yang identik dengan "
                        "yang sudah Anda kirim sebelumnya.\n"
                        "3. Ambil langkah BARU yang berbeda dari semua "
                        "langkah sebelumnya: periksa ulang pesan error "
                        "terakhir dengan saksama, pahami AKAR MASALAHNYA, "
                        "lalu perbaiki argumen/strategi Anda secara "
                        "fundamental -- jangan sekadar mengirim ulang hal "
                        "yang sama.\n"
                        "4. Kalau semua langkah yang masuk akal sudah "
                        "dicoba dan tidak ada yang berhasil, BERHENTI "
                        "mencoba dan berikan jawaban akhir yang jujur "
                        "tentang apa yang sudah dikerjakan dan apa yang "
                        "gagal.\n"
                        "\n"
                        "Mengulang tool_call yang sama lagi akan dianggap "
                        "sebagai kegagalan dan giliran ini akan dihentikan "
                        "paksa.\n"
                        "</tool_result>"
                    )
                    dbmod.add_message(
                        args.db_path,
                        session_id,
                        "user",
                        error_loop_warning,
                        kind="tool_result",
                    )
                    continue
                else:

                    print(c(
                        f"  [ERROR-LOOP] Model masih mengulang tool_call "
                        f"yang menghasilkan error yang sama "
                        f"({_error_repeat_count}x dalam {state.ERROR_REPEAT_WINDOW} "
                        f"iterasi terakhir) meski sudah diperingatkan. "
                        f"Menghentikan giliran ini untuk mencegah loop tak "
                        f"berujung."
                        + (f"\n  ulang: {_err_detail}" if _err_detail else ""),
                        C.RED,
                    ))
                    print(c(
                        f"  [ERROR-LOOP] Menunggu {state.LOOP_BREAK_COOLDOWN_SECONDS} "
                        f"detik sebelum melanjutkan proses terakhir...",
                        C.DIM,
                    ))
                    time.sleep(state.LOOP_BREAK_COOLDOWN_SECONDS)
                    _emit_summary()
                    return last_visible

        tool_result_msg = f"<tool_result>\n{result}\n</tool_result>"
        dbmod.add_message(
            args.db_path,
            session_id,
            "user",
            tool_result_msg,
            kind="tool_result",
        )

        # Pacing antar request: jeda singkat setelah setiap tool call sukses
        # sebelum iterasi berikutnya memicu request model lagi. Mencegah
        # deretan tool_call cepat (bash/read_file/grep) membanjiri proxy
        # publik dan memicu rate limit HTTP 429 (lihat TOOL_CALL_PACING_SECONDS).
        time.sleep(state.TOOL_CALL_PACING_SECONDS)
    else:
        print(c(
            f"[WARN] Batas {args.max_tool_iters} pemanggilan tool tercapai "
            "untuk giliran ini.",
            C.YELLOW,
        ))
    _emit_summary()
    return last_visible
