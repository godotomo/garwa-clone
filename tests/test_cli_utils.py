"""
test_cli_utils.py
Uji utilitas CLI yang dipecah dari cli.py menjadi modul kecil.

Fokus:
- json_repair: perbaikan key/value tanpa kutip, kutip tunggal, escape tidak
  valid, dan extract_tool_call (termasuk kasus PARSE_ERROR & placeholder).
- stream_parse: ekstraksi content/reasoning/finish_reason/usage dari chunk
  SSE, serta _stream_visible_text/_flush_visible_text yang menyembunyikan
  blok <tool_call> walau marker terpotong antar chunk.
- text_utils: similarity, deteksi repetisi, lebar terminal, truncate, dan
  decode UTF-8 eksplisit.
- llm_errors: parsing error exceed_context_size_error dari respons 400.
"""

import io
import json as _json
import os
import random
import sys

import pytest

from garwa import config
from garwa import db as dbmod
from garwa.cli import _state as state
from garwa.cli import json_repair, llm_errors, slash_commands, spinner as spinner_mod, stream_parse, text_utils
from garwa.cli.main import _build_prompt_label, _build_status_info
from garwa.cli.main import HISTORY_FILE, HISTORY_MAX
from garwa.cli.prompt_ui import _format_toolbar


# ---------------------------------------------------------------------------
# json_repair
# ---------------------------------------------------------------------------

class TestRepairUnquotedKeys:
    def test_quotes_unquoted_keys(self):
        raw = '{name: "bash", arguments: {command: "ls"}}'
        assert json_repair._repair_unquoted_json_keys(raw) == (
            '{"name": "bash", "arguments": {"command": "ls"}}'
        )

    def test_leaves_already_quoted_keys_untouched(self):
        raw = '{"name": "bash", "arguments": {"command": "ls"}}'
        assert json_repair._repair_unquoted_json_keys(raw) == raw

    def test_does_not_quote_leading_digit(self):
        # Identifier yang diawali digit tidak memenuhi pola regex.
        raw = '{123: "x"}'
        assert json_repair._repair_unquoted_json_keys(raw) == raw


class TestRepairUnquotedValues:
    def test_quotes_unquoted_values(self):
        raw = '{"name": bash, "arguments": {"command": ls}}'
        assert json_repair._repair_unquoted_json_values(raw) == (
            '{"name": "bash", "arguments": {"command": "ls"}}'
        )

    def test_keeps_json_literals_and_numbers(self):
        raw = '{"ok": true, "n": 42, "x": null}'
        assert json_repair._repair_unquoted_json_values(raw) == raw


class TestRepairSingleQuoted:
    def test_converts_single_to_double_quotes(self):
        raw = "{'name': 'bash', 'arguments': {'command': 'ls'}}"
        assert json_repair._repair_single_quoted_json(raw) == (
            '{"name": "bash", "arguments": {"command": "ls"}}'
        )


class TestRepairInvalidEscapes:
    def test_doubles_invalid_backslash(self):
        raw = '{"a": "va\\\\lue"}'
        repaired = json_repair._repair_invalid_json_escapes(raw)
        # Hasil harus jadi JSON valid (backslash di-escape), value = "va\lue".
        assert _json.loads(repaired) == {"a": "va\\lue"}

    def test_returns_text_unchanged_when_valid(self):
        raw = '{"a": "value"}'
        assert json_repair._repair_invalid_json_escapes(raw) == raw


class TestExtractToolCall:
    def test_valid_json(self):
        open_t = "<tool_call" + ">"
        close_t = "</tool_call" + ">"
        text = open_t + '{"name": "bash", "arguments": {"command": "ls"}}' + close_t
        name, args = json_repair.extract_tool_call(text)
        assert name == "bash"
        assert args == {"command": "ls"}

    def test_unquoted_keys_and_values(self):
        open_t = "<tool_call" + ">"
        close_t = "</tool_call" + ">"
        text = open_t + "{name: bash, arguments: {command: ls}}" + close_t
        name, args = json_repair.extract_tool_call(text)
        assert name == "bash"
        assert args == {"command": "ls"}

    def test_single_quoted(self):
        open_t = "<tool_call" + ">"
        close_t = "</tool_call" + ">"
        text = open_t + "{'name': 'bash', 'arguments': {'command': 'ls'}}" + close_t
        name, args = json_repair.extract_tool_call(text)
        assert name == "bash"
        assert args == {"command": "ls"}

    def test_placeholder_returns_none(self):
        open_t = "<tool_call" + ">"
        close_t = "</tool_call" + ">"
        text = open_t + "{...}" + close_t
        assert json_repair.extract_tool_call(text) == (None, None)

    def test_placeholder_inside_field_returns_parse_error(self):
        open_t = "<tool_call" + ">"
        close_t = "</tool_call" + ">"
        text = open_t + '{"name": "bash", "arguments": {...}}' + close_t
        name, msg = json_repair.extract_tool_call(text)
        assert name == "PARSE_ERROR"
        assert "..." in msg
        assert "placeholder" in msg.lower() or "ellipsis" in msg.lower()

    def test_no_tool_call_returns_none(self):
        assert json_repair.extract_tool_call("just some text") == (None, None)

    def test_parse_error(self):
        open_t = "<tool_call" + ">"
        close_t = "</tool_call" + ">"
        text = open_t + "{not valid json here}" + close_t
        name, msg = json_repair.extract_tool_call(text)
        assert name == "PARSE_ERROR"
        assert isinstance(msg, str)

    def test_arguments_not_dict(self):
        open_t = "<tool_call" + ">"
        close_t = "</tool_call" + ">"
        text = open_t + '{"name": "bash", "arguments": "oops"}' + close_t
        name, msg = json_repair.extract_tool_call(text)
        assert name == "PARSE_ERROR"


# ---------------------------------------------------------------------------
# stream_parse
# ---------------------------------------------------------------------------

class TestExtractStreamContent:
    def test_raises_on_explicit_error(self):
        with pytest.raises(llm_errors.LlamaServerStreamError):
            stream_parse._extract_stream_content(
                {"error": {"message": "OOM during generate"}}
            )

    def test_empty_choices(self):
        assert stream_parse._extract_stream_content({"choices": []}) == ""

    def test_delta_content(self):
        obj = {"choices": [{"delta": {"content": "hello"}}]}
        assert stream_parse._extract_stream_content(obj) == "hello"

    def test_message_content_fallback(self):
        obj = {"choices": [{"message": {"content": "world"}}]}
        assert stream_parse._extract_stream_content(obj) == "world"

    def test_non_string_content(self):
        obj = {"choices": [{"delta": {"content": 123}}]}
        assert stream_parse._extract_stream_content(obj) == ""


class TestExtractStreamReasoning:
    def test_reasoning_from_delta(self):
        obj = {"choices": [{"delta": {"reasoning_content": "thinking"}}]}
        assert stream_parse._extract_stream_reasoning(obj) == "thinking"

    def test_reasoning_from_message(self):
        obj = {"choices": [{"message": {"reasoning_content": "cot"}}]}
        assert stream_parse._extract_stream_reasoning(obj) == "cot"

    def test_empty(self):
        assert stream_parse._extract_stream_reasoning({"choices": []}) == ""


class TestExtractStreamFinishReason:
    def test_none_when_no_choices(self):
        assert stream_parse._extract_stream_finish_reason({"choices": []}) is None

    def test_string_finish_reason(self):
        obj = {"choices": [{"finish_reason": "stop"}]}
        assert stream_parse._extract_stream_finish_reason(obj) == "stop"

    def test_non_string_finish_reason(self):
        obj = {"choices": [{"finish_reason": 7}]}
        assert stream_parse._extract_stream_finish_reason(obj) is None


class TestExtractStreamUsage:
    def test_dict_usage(self):
        obj = {"choices": [], "usage": {"completion_tokens": 5}}
        assert stream_parse._extract_stream_usage(obj) == {"completion_tokens": 5}

    def test_non_dict_usage(self):
        assert stream_parse._extract_stream_usage({"usage": 42}) is None

    def test_missing_usage(self):
        assert stream_parse._extract_stream_usage({}) is None


def _new_stream_state():
    return {"in_tool": False, "pending": "", "ws_hold": ""}


class TestStreamVisibleText:
    def test_plain_text(self):
        st = _new_stream_state()
        # Teks pendek menahan suffix (len(TOOL_OPEN)-1) untuk deteksi marker
        # terpotong; isi penuh keluar setelah flush.
        out = stream_parse._stream_visible_text(st, "hello world")
        assert out == "h"
        assert stream_parse._flush_visible_text(st) == "ello world"

    def test_hides_tool_call_block(self):
        st = _new_stream_state()
        open_t = "<tool_call" + ">"
        close_t = "</tool_call" + ">"
        text = "before " + open_t + '{"name": "bash"}' + close_t + " after"
        out = stream_parse._stream_visible_text(st, text)
        # Blok tool_call disembunyikan; sisa " after" masih ditahan.
        assert out == "before"
        assert stream_parse._flush_visible_text(st) == " after"

    def test_tool_marker_split_across_chunks(self):
        st = _new_stream_state()
        # _stream_visible_text mengembalikan output per-panggilan (tidak
        # terakumulasi); jumlahkan semua panggilan + flush untuk teks penuh.
        out1 = stream_parse._stream_visible_text(st, "before <tool_")
        out2 = stream_parse._stream_visible_text(st, 'call>{"name": "bash"}</tool_')
        out3 = stream_parse._stream_visible_text(st, "call> after")
        # Marker terpotong tetap disembunyikan; teks di kedua sisi digabung.
        assert out1 + out2 + out3 + stream_parse._flush_visible_text(st) == "before after"

    def test_discards_whitespace_before_tool_call(self):
        st = _new_stream_state()
        open_t = "<tool_call" + ">"
        close_t = "</tool_call" + ">"
        out = stream_parse._stream_visible_text(st, "selanjutnya.\n\n" + open_t + "{}\n" + close_t)
        assert out == "selanjutnya."
        assert stream_parse._flush_visible_text(st) == ""

    def test_empty_input(self):
        st = _new_stream_state()
        assert stream_parse._stream_visible_text(st, "") == ""


class TestFlushVisibleText:
    def test_flush_remaining(self):
        st = _new_stream_state()
        # "final words" = 11 karakter; suffix 10 karakter ditahan, jadi hanya
        # "f" yang keluar saat stream, sisanya keluar saat flush.
        assert stream_parse._stream_visible_text(st, "final words") == "f"
        assert stream_parse._flush_visible_text(st) == "inal words"

    def test_flush_inside_tool_returns_empty(self):
        st = _new_stream_state()
        stream_parse._stream_visible_text(st, "<tool_call" + ">")
        assert st["in_tool"] is True
        assert stream_parse._flush_visible_text(st) == ""


# ---------------------------------------------------------------------------
# text_utils
# ---------------------------------------------------------------------------

class TestSimilarity:
    def test_identical_after_ws_normalization(self):
        assert text_utils._similarity("a b c", "a  b\nc") == 1.0

    def test_completely_different(self):
        assert text_utils._similarity("hello", "world") < 0.5

    # ------------------------------------------------------------------
    # BUG 8: _similarity menggunakan SequenceMatcher.ratio() yang
    # mengukur similarity berbasis longest common subsequence, bukan
    # semantic/structural similarity. Dua teks dengan struktur kalimat
    # identik tapi kata kunci berbeda bisa dapat skor rendah.
    # ------------------------------------------------------------------
    def test_structural_similarity_missed_by_sequence_matcher(self):
        """FIXED: Entity normalization sekarang mendeteksi template loop.

        Dua teks dengan template sama tapi isi berbeda:
        - "Saya akan membaca file X.py" vs "Saya akan membaca file Y.py"
        Entity normalization mengganti nama file dengan __FILE__, sehingga
        keduanya menjadi identik secara struktural.
        """
        a = "Saya akan membaca file main.py untuk melihat isinya"
        b = "Saya akan membaca file utils.py untuk melihat isinya"
        sim = text_utils._similarity(a, b)
        # Struktur identik, entity normalization membuat keduanya mirip
        assert sim >= state.LOOP_SIMILARITY_THRESHOLD  # FIXED: >= 0.95

    # ------------------------------------------------------------------
    # BUG 9: _similarity tidak mendeteksi parafrase — kalimat yang sama
    # artinya tapi dikatakan dengan kata berbeda.
    # ------------------------------------------------------------------
    def test_paraphrase_detected(self):
        """BUG FIX (BUG 9): parafrase pendek kini terdeteksi.

        Sebelumnya "File ini berisi fungsi untuk memproses data" vs
        "Fungsi pemrosesan data terdapat dalam file ini" hanya mendapat
        similarity ~0.4 karena Jaccard dan char n-gram belum cukup
        menangkap parafrase pendek. Sinyal content-word (anti-stopword +
        stemming ringan) menaikkannya ke >= 0.95.
        """
        a = "File ini berisi fungsi untuk memproses data"
        b = "Fungsi pemrosesan data terdapat dalam file ini"
        sim = text_utils._similarity(a, b)
        assert sim >= state.LOOP_SIMILARITY_THRESHOLD

    # ------------------------------------------------------------------
    # Edge case: teks kosong
    # ------------------------------------------------------------------
    def test_empty_strings(self):
        assert text_utils._similarity("", "") == 1.0
        assert text_utils._similarity("hello", "") == 0.0

    # ------------------------------------------------------------------
    # Edge case: teks sangat pendek
    # ------------------------------------------------------------------
    def test_very_short_strings(self):
        """Teks pendek harusnya tidak false-positive similarity."""
        # "OK" vs "OK" — identik setelah normalisasi
        assert text_utils._similarity("OK", "OK") == 1.0
        # "OK" vs "NO" — sangat berbeda (2 karakter dari 2 = 0.5)
        assert text_utils._similarity("OK", "NO") <= 0.5

    # ------------------------------------------------------------------
    # Edge case: whitespace-only strings
    # ------------------------------------------------------------------
    def test_whitespace_only(self):
        assert text_utils._similarity("   ", "\n\n") == 1.0


# ---------------------------------------------------------------------------
# Loop detection logic (simulasi dari agent_loop.py baris ~410-500)
# ---------------------------------------------------------------------------

class TestLoopDetectionLogic:
    """Simulasi logika deteksi loop di agent_loop.py untuk mengungkap bug.

    Logika di agent_loop (disederhanakan):
    1. Setiap respons assistant disimpan ke _loop_history.
    2. Cek exact match: jika respons saat ini == salah satu di history.
    3. Cek similarity: jika _similarity(respon, prev) >= 0.95 untuk
       LOOP_REPEAT_THRESHOLD (2) respons terakhir.
    4. Jika terdeteksi: cooldown / break.
    """

    @staticmethod
    def _simulate_loop_check(history, new_response):
        """Simulasi loop check dari agent_loop.py (versi FIXED).

        Perbaikan vs versi lama:
        - Bug 11: window_prev = history[:-1] — tidak hitung diri sendiri
        - Bug 12: unified check — exact match (sim=1.0) termasuk similarity
        - Bug 10: twin_count — deteksi pola alternating A/B/A/B
        - Bug 13/14: window dibatasi LOOP_REPEAT_WINDOW
        """
        history.append(new_response)
        if len(history) > state.LOOP_REPEAT_WINDOW:
            history.pop(0)

        if new_response.strip() == "":
            return False, None

        # Window tanpa item yang baru di-append (Bug 11)
        window_prev = history[:-1]

        # Unified check: exact + similarity jadi satu (Bug 12)
        repeat_count = sum(
            1 for prev in window_prev
            if text_utils._similarity(prev, new_response) >= state.LOOP_SIMILARITY_THRESHOLD
        )

        # Alternating pattern detection (Bug 10: A/B/A/B)
        # twin_count = JUMLAH KEMUNCULAN item yang berulang dalam window
        # (item yang muncul >= 2x, dihitung setiap kemunculannya). Ini
        # menangkap pola alternating berkelanjutan (Bug 16): window
        # [A,B,A,B] → A(2)+B(2)=4 >= threshold 3.
        twin_count = 0
        for i, item in enumerate(history):
            if any(
                text_utils._similarity(item, history[j]) >= state.LOOP_SIMILARITY_THRESHOLD
                for j in range(len(history))
                if j != i
            ):
                twin_count += 1

        # twin_count = jumlah item (termasuk posisi pertama) yang punya
        # kembaran. Max = LOOP_REPEAT_WINDOW (window penuh identik).
        # Threshold window-1 menangkap alternating berkelanjutan tanpa
        # false-positive pada window dengan 1 duplikat ([A,B,C,A] → 2).
        is_loop = (
            repeat_count >= state.LOOP_REPEAT_THRESHOLD
            or twin_count >= state.LOOP_REPEAT_WINDOW - 1
        )

        if is_loop:
            kind = "similarity" if repeat_count >= state.LOOP_REPEAT_THRESHOLD else "alternating"
            return True, kind
        return False, None

    # ------------------------------------------------------------------
    # BUG 10: _similarity hanya membandingkan dua teks, tidak punya
    # memori jangka panjang. Pola A→B→A→B (di mana A mirip A dan B
    # mirip B, tapi A tidak mirip B) bisa lolos karena check hanya
    # pairwise dengan teks sebelumnya.
    # FIXED: unified loop detection dengan twin_count + repeat_count.
    # ------------------------------------------------------------------
    def test_pairwise_only_misses_alternating_pattern(self):
        """FIXED: unified detection sekarang menangkap pola berulang.

        Dua respons A dan B yang sangat berbeda, tapi muncul bergantian:
        repeat_count mendeteksi saat item yang sama muncul ≥ threshold kali
        dalam window, dan twin_count mendeteksi saat banyak item punya
        kembaran di window yang sama.
        """
        a = "Saya akan memproses file A sekarang"
        b = "Baik, saya akan menjalankan perintah shell untuk testing"
        # A dan B sangat berbeda — pairwise check lolos
        sim_ab = text_utils._similarity(a, b)
        assert sim_ab < state.LOOP_SIMILARITY_THRESHOLD

        # Pola [a, b, a] + new=b → window=[a,b,a,b]
        # repeat_count: b vs [a,b,a] → b vs b = 1 (< threshold 2)
        # twin_count (FIXED Bug 16): item berulang = a(2) + b(2) = 4 >= 3
        # → alternating 2-siklus A/B/A/B terdeteksi!
        history = [a, b, a]
        detected, kind = self._simulate_loop_check(history, b)
        assert detected is True  # FIXED: A/B/A/B alternating terdeteksi
        assert kind == "alternating"

        # 3 kemunculan item yang sama dalam window → tetap trigger
        # [a, b, a] + new=a → window=[a,b,a,a]
        # repeat_count: a vs [a,b,a] → a vs a, a vs a = 2 >= threshold 2
        history3 = ["Saya akan memproses file A sekarang",
                     "Baik, saya akan menjalankan perintah shell untuk testing",
                     "Saya akan memproses file A sekarang"]
        detected3, kind3 = self._simulate_loop_check(history3,
            "Saya akan memproses file A sekarang")
        assert detected3 is True  # FIXED: 3 kemunculan dalam window → trigger
        assert kind3 == "similarity"

    # ------------------------------------------------------------------
    # BUG 15: twin_count threshold = LOOP_REPEAT_WINDOW tidak pernah bisa
    # tercapai. twin_count menghitung item ke-i terhadap item j<i, sehingga
    # item pertama (i=0) tidak pernah dihitung → max = window - 1. Dengan
    # window=4, max twin_count=3 < threshold 4 → branch "alternating"
    # menjadi dead code (tidak pernah trigger). Threshold diperbaiki jadi
    # LOOP_REPEAT_WINDOW - 1 agar branch reachable.
    # ------------------------------------------------------------------
    def test_twin_count_threshold_reachable(self):
        """FIXED (Bug 15 + Bug 16): threshold twin_count = window-1.

        twin_count = JUMLAH KEMUNCULAN item yang berulang dalam window
        (termasuk posisi pertama). Max = LOOP_REPEAT_WINDOW (window penuh
        identik). Threshold window-1 menangkap pola alternating berkelanjutan
        (window [A,B,A,B] → 4) tanpa false-positive pada window yang hanya
        punya 1 duplikat (window [A,B,C,A] → 2).
        """
        a = "Saya akan memproses file A sekarang"
        b = "Baik, saya akan menjalankan perintah shell untuk testing"
        c = "Sekarang saya akan menulis laporan ke file output"
        assert text_utils._similarity(a, b) < state.LOOP_SIMILARITY_THRESHOLD
        assert text_utils._similarity(a, c) < state.LOOP_SIMILARITY_THRESHOLD
        assert text_utils._similarity(b, c) < state.LOOP_SIMILARITY_THRESHOLD

        # Window [A,B,C,A] → hanya A yang berulang (2x). twin_count per posisi:
        #   i=0(A): vs B,C,A → mirip → 1
        #   i=1(B): vs A,C,A → beda → 0
        #   i=2(C): vs A,B,A → beda → 0
        #   i=3(A): vs A,B,C → mirip → 1
        # twin_count=2 < 3 → TIDAK trigger (hanya 1 pasang duplikat)
        history = [a, b, c]
        detected, kind = self._simulate_loop_check(history, a)
        assert detected is False

        # Window [A,B,A,B] → A(2)+B(2)=4 >= 3 → trigger via branch
        # alternating (repeat_count=1 < 2, jadi bukan similarity).
        # Ini membuktikan branch alternating reachable (Bug 15) sekaligus
        # menangkap pola alternating berkelanjutan (Bug 16).
        history2 = [a, b, a]
        detected2, kind2 = self._simulate_loop_check(history2, b)
        assert detected2 is True
        assert kind2 == "alternating"

        # Window penuh semua identik [A,A,A,A] → twin_count=4 >= 3 → trigger
        # (via repeat branch karena repeat_count=3 >= 2, jadi kind=similarity)
        history4 = [a, a, a]
        detected4, kind4 = self._simulate_loop_check(history4, a)
        assert detected4 is True
        assert kind4 == "similarity"

    # ------------------------------------------------------------------
    # BUG 16: loop alternating berkelanjutan A/B/A/B/A/B... tidak pernah
    # terdeteksi. twin_count lama menghitung JUMLAH ITEM BERBEDA yang punya
    # kembaran (selalu jenuh di 2 untuk pola 2-siklus), bukan jumlah
    # kemunculan. FIXED: hitung JUMLAH KEMUNCULAN item yang berulang.
    # ------------------------------------------------------------------
    def test_continuous_alternating_pattern_detected(self):
        """FIXED (Bug 16): pola A/B/A/B/A/B... terdeteksi.

        twin_count = jumlah kemunculan item yang berulang dalam window.
        Window [A,B,A,B] → A(2)+B(2)=4 >= threshold 3 → loop terdeteksi,
        walau repeat_count = 1 (< threshold 2).
        """
        a = "Saya akan memproses file A sekarang"
        b = "Baik, saya akan menjalankan perintah shell untuk testing"
        assert text_utils._similarity(a, b) < state.LOOP_SIMILARITY_THRESHOLD

        # Simulasi loop berkelanjutan: A,B,A,B,A,B...
        # Untuk setiap langkah, window terakhir = [A,B,A,B] → harus terdeteksi
        # sebagai alternating (bukan similarity).
        history = [a, b, a]
        detected, kind = self._simulate_loop_check(history, b)
        assert detected is True
        assert kind == "alternating"

        # Lanjutkan siklus: next = a → window [b,a,b,a] → tetap terdeteksi
        history2 = [b, a, b]
        detected2, kind2 = self._simulate_loop_check(history2, a)
        assert detected2 is True
        assert kind2 == "alternating"

        # Lanjutkan lagi: next = b → window [a,b,a,b] → masih terdeteksi
        # (pola berkelanjutan tidak pernah "lolos")
        history3 = [a, b, a]
        detected3, kind3 = self._simulate_loop_check(history3, b)
        assert detected3 is True
        assert kind3 == "alternating"

    # ------------------------------------------------------------------
    # BUG 11: exact match check menggunakan `_loop_history.count()`
    # yang selalu >= 1 karena baru saja di-append. Threshold 2 berarti
    # hanya perlu 1 kemunculan sebelumnya untuk trigger.
    # FIXED: window_prev = history[:-1] — tidak hitung diri sendiri.
    # ------------------------------------------------------------------
    def test_exact_match_triggers_too_early(self):
        """FIXED: window_prev mengecualikan item yang baru di-append.

        Dulu: count() termasuk item baru → selalu >= 1, sehingga threshold 2
        hanya butuh 1 duplikat sebelumnya. Sekarang: window_prev = history[:-1]
        mengecualikan item baru, jadi repeat_count menghitung dengan benar.
        """
        history = ["respons A", "respons B"]
        new = "respons A"  # sudah pernah muncul 1x
        detected, kind = self._simulate_loop_check(history, new)
        # window_prev = ["respons A", "respons B"]
        # repeat_count: "respons A" vs ["respons A", "respons B"] → 1 match
        # 1 < threshold 2 → tidak trigger (butuh 2 duplikat sebelumnya)
        assert detected is False  # FIXED: tidak trigger terlalu awal

    # ------------------------------------------------------------------
    # BUG 12: similarity check mengecualikan exact match.
    # Kalau 2 respons mirip (≥0.95) + 1 respons identik (=1.0),
    # similarity check hanya menghitung yang mirip (2), dan exact
    # match check juga hanya menghitung yang identik (2).
    # Masing-masing di bawah threshold, padahal total 3 respons
    # highly similar.
    # FIXED: unified check — exact match (sim=1.0) termasuk similarity.
    # ------------------------------------------------------------------
    def test_similarity_excludes_exact_matches(self):
        """FIXED: unified check — exact match sekarang termasuk similarity.

        Dulu: exact dan similarity dipisah → celah di antaranya.
        Sekarang: repeat_count menghitung SEMUA item yang mirip (≥threshold),
        termasuk exact match (similarity=1.0).
        """
        a = "Saya akan membaca file main.py untuk analisis lebih lanjut"
        a2 = "Saya akan membaca file main.py untuk analisis lebih lanjut"  # identik dgn a
        a3 = "Saya akan membaca file main.py untuk analisis lebih lanjut."  # mirip (0.992)
        history = [a, a2]
        detected, kind = self._simulate_loop_check(history, a3)
        # window_prev = [a, a2]; repeat_count: a3 vs a (≥0.95) + a3 vs a2 (≥0.95) = 2
        # 2 >= threshold 2 → trigger!
        assert detected is True  # FIXED: unified check menangkap ini
        assert kind == "similarity"

    # ------------------------------------------------------------------
    # BUG 13: similarity check hanya mundur ke belakang (reversed),
    # tidak sliding window. Kalau history panjang dan 2 respons mirip
    # terpisah jauh, tidak terdeteksi.
    # FIXED: window dibatasi LOOP_REPEAT_WINDOW (4 item).
    # ------------------------------------------------------------------
    def test_similarity_only_recent_window(self):
        """FIXED: window dibatasi LOOP_REPEAT_WINDOW.

        Sekarang history hanya menyimpan maksimal LOOP_REPEAT_WINDOW item
        terakhir. Jadi 3 respons mirip berturut-turut tetap terdeteksi
        dalam window.
        """
        # 3 respons mirip berturut-turut dalam window 4 → terdeteksi
        a1 = "Saya akan membaca file target.py sekarang!"
        a2 = "Saya akan membaca file target.py sekarang"  # mirip a1
        a3 = "Saya akan membaca file target.py sekarang."  # mirip a1 & a2
        history = [a1, a2]
        detected, kind = self._simulate_loop_check(history, a3)
        # window_prev = [a1, a2]; repeat_count: a3 vs a1 + a3 vs a2 = 2 >= 2 → trigger
        assert detected is True  # FIXED: 3 respons mirip dalam window terdeteksi

    # ------------------------------------------------------------------
    # BUG 14: LOOP_REPEAT_WINDOW tidak digunakan di similarity check.
    # Konstanta LOOP_REPEAT_WINDOW=4 didefinisikan tapi similarity check
    # iterasi seluruh history (atau sampai ketemu exact match),
    # bukan dibatasi window.
    # FIXED: history dibatasi LOOP_REPEAT_WINDOW (pop(0) saat overflow).
    # ------------------------------------------------------------------
    def test_loop_repeat_window_not_enforced(self):
        """FIXED: LOOP_REPEAT_WINDOW sekarang digunakan untuk membatasi history.

        History hanya menyimpan maksimal LOOP_REPEAT_WINDOW item.
        Item lama di-pop saat overflow, sehingga similarity check
        hanya beroperasi dalam window terbatas.
        """
        assert state.LOOP_REPEAT_WINDOW == 4
        # Verifikasi: simulasi dengan history panjang akan dipotong ke window
        # Gunakan string tanpa angka (entity normalization membuat "unik 0" == "unik 96")
        history = ["respons alpha bravo charlie delta echo foxtrot golf hotel "
                   "india juliet kilo lima mike november oscar papa quebec romeo "
                   "sierra tango uniform victor whiskey xray yankee zulu"] * 100
        new = "respons alpha bravo charlie delta echo foxtrot golf hotel " \
              "india juliet kilo lima mike november oscar papa quebec romeo " \
              "sierra tango uniform victor whiskey xray yankee zulu"
        # new identik dengan semua item history (semua item sama)
        detected, kind = self._simulate_loop_check(history, new)
        # window hanya 4 item terakhir; repeat_count: 3 (3 item sebelumnya di window)
        # 3 >= threshold 2 → trigger
        assert detected is True  # FIXED: window membatasi, tapi 3 duplikat dalam window terdeteksi

    # ------------------------------------------------------------------
    # Edge case: history kosong
    # ------------------------------------------------------------------
    def test_empty_history(self):
        detected, kind = self._simulate_loop_check([], "respons pertama")
        assert detected is False

    # ------------------------------------------------------------------
    # Edge case: semua respons berbeda
    # ------------------------------------------------------------------
    def test_all_different_responses(self):
        history = ["respons A", "respons B", "respons C", "respons D"]
        detected, kind = self._simulate_loop_check(history, "respons E")
        assert detected is False


class TestDetectRepetition:
    def test_repeated_line_detected(self):
        text = "line one\n" * state.REPEAT_MAX_OCCUR
        assert text_utils._detect_repetition(text) is True

    def test_short_text_not_repetitive(self):
        assert text_utils._detect_repetition("just a short response") is False

    def test_repeated_unit_detected(self):
        unit = "x" * 100
        text = unit * state.REPEAT_MAX_OCCUR
        assert text_utils._detect_repetition(text) is True

    # ------------------------------------------------------------------
    # BUG FIX: Markdown normal yang memakai horizontal rule (---) untuk
    # memisahkan section TERSebar di antara konten tidak boleh ditandai
    # sebagai loop. Sebelumnya separator dihitung total di seluruh teks
    # sehingga 3x "---" (markdown umum) memicu false positive.
    # ------------------------------------------------------------------
    def test_markdown_horizontal_rules_spread_not_detected(self):
        text = (
            "# Panduan Upgrade macOS\n"
            "\n"
            "Peringatan penting sebelum mulai.\n"
            "\n"
            "---\n"
            "\n"
            "Langkah 1 — Cek versi macOS.\n"
            "\n"
            "---\n"
            "\n"
            "Langkah 2 — Backup data.\n"
            "\n"
            "---\n"
            "\n"
            "Kesimpulan.\n"
        )
        assert text_utils._detect_repetition(text) is False

    def test_many_markdown_horizontal_rules_spread_not_detected(self):
        # 5x "---" tersebar di antara konten -- sebelumnya memicu LINE-REPEAT.
        text = (
            "Section A\n"
            "\n"
            "---\n"
            "\n"
            "Konten A.\n"
            "\n"
            "---\n"
            "\n"
            "Section B\n"
            "\n"
            "---\n"
            "\n"
            "Konten B.\n"
            "\n"
            "---\n"
            "\n"
            "Section C\n"
            "\n"
            "---\n"
            "\n"
            "Konten C.\n"
        )
        assert text_utils._detect_repetition(text) is False

    def test_separator_stacked_detected(self):
        # Separator bertumpuk tanpa konten = loop degenerate, harus terdeteksi.
        assert text_utils._detect_repetition("---\n---\n---\n---\n---\n---\n") is True

    def test_separator_stacked_with_blank_lines_detected(self):
        # Baris kosong di antara separator tidak memutus run degenerate.
        text = "---\n\n---\n\n---\n\n---\n\n"
        assert text_utils._detect_repetition(text) is True

    # ------------------------------------------------------------------
    # BUG 1: N-gram hanya memeriksa blok yang aligned ke kelipatan ngram.
    # Kalau repetisi dimulai dari offset ganjil (bukan kelipatan 40),
    # blok-blok di offset 0, 40, 80 tidak akan identik satu sama lain
    # sehingga repetisi TIDAK terdeteksi.
    # ------------------------------------------------------------------
    def test_ngram_missed_due_to_offset_misalignment(self):
        """FIXED: multi-offset scanning menangkap repetisi meski offset tidak aligned.

        Teks: 5 karakter prefix acak + blok 40-char yang diulang 6x.
        Dulu: loop n-gram hanya dari offset 0 → blok pertama tercampur prefix.
        Sekarang: scan dari offset 0..39 memastikan setidaknya satu offset
        menghasilkan blok-blok aligned yang identik.
        """
        block = "A" * 100  # 100 'A'
        prefix = "12345"  # 5 karakter offset
        text = prefix + block * 6  # 6 blok
        # Multi-offset scan: offset 5 menghasilkan blok-blok "AAAA..."
        # yang aligned sempurna, 6 blok ≥ threshold → terdeteksi.
        assert text_utils._detect_repetition(text) is True  # FIXED: multi-offset

    # ------------------------------------------------------------------
    # BUG 2: N-gram hanya menghitung blok identik yang KONSEKUTIF.
    # Pola interleaved A, B, A, B, A tidak terdeteksi karena counter
    # reset setiap kali ketemu blok yang berbeda.
    # ------------------------------------------------------------------
    def test_ngram_missed_non_consecutive_pattern(self):
        """FIXED: pola interleaved A/B/A/B/A terdeteksi diversity check.

        N-gram check tahap 3 hanya menghitung blok identik yang
        berturut-turut, jadi count reset setiap ketemu B. Diversity check
        (tahap 4) tidak punya asumsi alignment: rolling n-gram di teks ini
        hanya menghasilkan ~0.195 n-gram unik, jauh di bawah threshold.
        """
        block_a = "A" * 100
        block_b = "B" * 100
        # A, B, A, B, A, B, A = 4x A, 3x B, total 7 blok
        text = (block_a + block_b) * 3 + block_a
        assert text_utils._detect_repetition(text) is True  # FIXED: diversity

    # ------------------------------------------------------------------
    # BUG 3: Baris pendek (< 3 karakter) diabaikan oleh line detection.
    # "OK" atau "no" yang berulang 100x tidak terdeteksi di level baris.
    # (Unit check mungkin menangkap kalau teks cukup panjang, tapi
    # untuk teks pendek-moderat, ini bisa lolos.)
    # ------------------------------------------------------------------
    def test_short_lines_ignored_by_line_detection(self):
        """FIXED: baris pendek (< 3 karakter) sekarang tetap diperiksa.

        Line detection tidak lagi mengabaikan baris < 3 karakter.
        "OK" yang berulang 15x sekarang terdeteksi sebagai repetisi.
        """
        # 15 baris "OK" — line check sekarang mendeteksi (len < 3 tetap dicek)
        text = "OK\n" * 15  # 45 karakter, 15 baris
        assert text_utils._detect_repetition(text) is True  # FIXED

    # ------------------------------------------------------------------
    # BUG 4: N-gram hanya memeriksa SATU ukuran (40 karakter).
    # Repetisi dengan ukuran berbeda (mis. 20 karakter berulang 10x)
    # tidak terdeteksi oleh n-gram check.
    # ------------------------------------------------------------------
    def test_ngram_single_scale_misses_other_sizes(self):
        """FIXED: repetisi 13-char non-aligned terdeteksi diversity check.

        Pola "Hello world! " lolos dari tahap 1-3 karena:
        1. Unit check: unit = text[-100:] tidak aligned dengan pola 13-char
           → hanya 2 kemunculan non-overlapping, < threshold 5.
        2. N-gram check: blok di offset kelipatan 25/60/120 tidak match
           karena pola 13-char tidak aligned dengan ukuran mana pun.
        Diversity check bebas alignment: rasio n-gram unik ~0.055.
        """
        segment = "Hello world! "  # 13 karakter
        text = segment * 20  # 260 karakter, 20x repetisi
        assert text_utils._detect_repetition(text) is True  # FIXED: diversity

    # ------------------------------------------------------------------
    # BUG 5: Unit check (`text.count()`) menghitung NON-OVERLAPPING.
    # Untuk teks yang sangat repetitif tapi unit overlap dengan dirinya
    # sendiri, count bisa lebih rendah dari yang diharapkan.
    # ------------------------------------------------------------------
    def test_unit_count_non_overlapping_undercounts(self):
        """BUG: text.count() non-overlapping bisa undercount.

        Python str.count() menghitung kemunculan non-overlapping.
        Untuk teks "aaaaa", "aa".count() = 2 (bukan 4).
        """
        # Buat teks di mana unit overlap dengan dirinya sendiri
        unit = "abcabcabca"  # 10 karakter, pola berulang "abc"
        text = unit * state.REPEAT_MAX_OCCUR  # 5x = 50 karakter
        # text.count(unit) = 5 (non-overlapping), jadi terdeteksi.
        # Tapi kalau kita buat lebih subtle:
        # Teks: "x" * 39 + unit * 6 = 39 + 60 = 99 karakter
        # unit = text[-40:] = "x" + unit[0:39] ... ini jadi tidak matching
        # Lebih baik: buat teks di mana unit yang diambil dari akhir
        # overlap dengan dirinya sendiri di tengah teks.
        #
        # Contoh konkret: teks = "ABABABAB..." pola AB berulang.
        # unit = text[-40:] = "ABABAB...", text.count(unit) non-overlapping.
        # Untuk teks 200 karakter "AB" berulang, unit 40-char "ABAB...",
        # non-overlapping count = 200/40 = 5, tepat threshold.
        # Tapi kalau teks 199 karakter, count = 4, < threshold.
        # Bug: teks 199 karakter "AB" berulang seharusnya tetap repetitif.
        # Teks: 199 karakter "AB" berulang
        text = "AB" * 99 + "A"  # 199 karakter
        # Unit = text[-100:], count non-overlapping < threshold 5 sehingga
        # unit check meleset. Diversity check menangkapnya: hanya 2 n-gram
        # unik dari 175 window → rasio 0.011.
        assert text_utils._detect_repetition(text) is True  # FIXED: diversity

    # ------------------------------------------------------------------
    # BUG 6: N-gram comparison bersifat EXACT. Variasi kecil seperti
    # whitespace atau punctuation yang berbeda tidak terdeteksi.
    # ------------------------------------------------------------------
    def test_ngram_exact_comparison_misses_near_duplicates(self):
        """FIXED: near-duplicate whitespace terdeteksi diversity check.

        Model mengulang kalimat sama dengan variasi whitespace. Line check
        gagal (semua 1 baris), unit check gagal (text[-100:] tidak match
        persis karena spasi ganda), n-gram exact juga gagal. Diversity check
        menormalkan whitespace lebih dulu → rasio n-gram unik ~0.184.
        """
        base = "The quick brown fox jumps over the lazy dog. "  # 45 karakter
        # Variasi: spasi ganda di beberapa tempat
        text = base + base.replace(" ", "  ") + base + base.replace(" ", "  ") + base + base.replace(" ", "  ")
        assert text_utils._detect_repetition(text) is True  # FIXED: diversity

    # ------------------------------------------------------------------
    # BUG 7: Deteksi hanya trigger kalau text SUDAH cukup panjang.
    # Model bisa menghasilkan output repetitif pendek (tapi tetap
    # degenerate) yang tidak terdeteksi karena belum mencapai batas
    # minimal pengecekan.
    # ------------------------------------------------------------------
    def test_repetition_not_checked_for_short_text(self):
        """FIXED: teks pendek sekarang diperiksa line-check.

        Dulu: teks < 200 karakter tidak dicek n-gram sama sekali.
        Sekarang: line check menangkap "OK" berulang 66x (66 baris identik
        >= REPEAT_MAX_OCCUR), jauh di bawah batas minimal pengecekan lama.
        """
        # 198 karakter "OK\n" berulang = 66 baris "OK"
        text = "OK\n" * 66  # 198 karakter
        # Line check: mendeteksi 66 baris "OK" identik ≥ 5
        assert text_utils._detect_repetition(text) is True  # FIXED

    # ------------------------------------------------------------------
    # Edge case: teks kosong
    # ------------------------------------------------------------------
    def test_empty_text(self):
        assert text_utils._detect_repetition("") is False

    # ------------------------------------------------------------------
    # Edge case: blok panjang yang diulang-ulang
    # ------------------------------------------------------------------
    def test_large_repeated_block_detected(self):
        """Blok panjang yang diulang-ulang terdeteksi sebagai repetisi."""
        block = "A" * 100
        text = block * 5  # 500 karakter
        assert text_utils._detect_repetition(text) is True

    # ------------------------------------------------------------------
    # Edge case: baris dengan tepat 3 karakter terdeteksi
    # ------------------------------------------------------------------
    def test_lines_exactly_three_chars_detected(self):
        text = "abc\n" * state.REPEAT_MAX_OCCUR
        assert text_utils._detect_repetition(text) is True

    # ------------------------------------------------------------------
    # Edge case: unit check mendeteksi walau line & n-gram gagal
    # ------------------------------------------------------------------
    def test_unit_check_as_last_resort(self):
        """Unit check harusnya menangkap repetisi yang lolos dari
        line check dan n-gram check."""
        # Teks dengan 1 baris panjang yang diulang-ulang
        unit = "Z" * 100
        text = unit * state.REPEAT_MAX_OCCUR
        # Line check: hanya 1 baris, tidak ada duplikat
        # Tapi ini memastikan unit check berfungsi sebagai last resort
        assert text_utils._detect_repetition(text) is True

    # ------------------------------------------------------------------
    # BUG FIX: Fence markdown (```python, ~~~, ...) yang TERSebar di antara
    # konten adalah sintaks sah untuk banyak blok kode pendek, bukan loop.
    # Sebelumnya baris fence yang identik dihitung oleh LINE-REPEAT sehingga
    # 5+ blok kode pendek memicu false positive.
    # ------------------------------------------------------------------
    def test_markdown_fence_spread_not_detected(self):
        blocks = []
        for i in range(6):
            blocks.append(
                f"```python\nx = {i}\n```\n\n"
                f"Langkah {i}: inisialisasi variabel x dengan nilai {i} "
                f"lalu lanjut ke tahap berikutnya dengan penjelasan unik."
            )
        text = "\n".join(blocks)
        assert text_utils._detect_repetition(text) is False

    def test_markdown_fence_spread_not_detected_reasoning(self):
        # Sama seperti di atas, tapi lewat jalur reasoning (strict=False).
        blocks = []
        for i in range(6):
            blocks.append(
                f"```python\nx = {i}\n```\n\n"
                f"Langkah {i}: inisialisasi variabel x dengan nilai {i} "
                f"lalu lanjut ke tahap berikutnya dengan penjelasan unik."
            )
        text = "\n".join(blocks)
        assert text_utils._detect_repetition(text, strict=False) is False

    def test_markdown_fence_stacked_detected(self):
        # Fence bertumpuk tanpa konten di antaranya = loop degenerate,
        # harus tetap terdeteksi (mirip separator bertumpuk).
        text = "```python\n" * 6
        assert text_utils._detect_repetition(text) is True

    def test_tilde_fence_spread_not_detected(self):
        # Fence tilde (~~~) juga pola fence: yang tersebar di antara konten
        # adalah markdown sah (banyak blok kode pendek), bukan loop.
        blocks = []
        for i in range(6):
            blocks.append(
                f"~~~python\nx = {i}\n~~~\n\n"
                f"Langkah {i}: inisialisasi variabel x dengan nilai {i} "
                f"lalu lanjut ke tahap berikutnya dengan penjelasan unik."
            )
        text = "\n".join(blocks)
        assert text_utils._detect_repetition(text) is False

    def test_tilde_fence_stacked_detected(self):
        # Fence tilde bertumpuk tanpa konten = loop degenerate, terdeteksi.
        text = "~~~\n" * 6
        assert text_utils._detect_repetition(text) is True

    def test_fence_and_separator_stacked_detected(self):
        # Kombinasi fence (```) dan separator (---) yang bertumpuk tanpa
        # konten di antaranya tetap loop degenerate dan harus terdeteksi,
        # walau tiap jenis baris hanya muncul 3x (di bawah threshold masing-
        # masing) -- gabungan run-nya yang membuatnya degenerate.
        # Diulang cukup panjang supaya diversity/n-gram check menangkapnya.
        text = "```\n---\n" * 40
        assert text_utils._detect_repetition(text) is True

    def test_fence_and_separator_spread_not_detected(self):
        # Fence dan separator yang TERSebar di antara konten unik adalah
        # markdown normal (blok kode pendek + horizontal rule), bukan loop.
        blocks = []
        for i in range(6):
            blocks.append(
                f"```python\nx = {i}\n```\n\n"
                f"---\n\n"
                f"Langkah {i}: inisialisasi variabel x dengan nilai {i} "
                f"lalu lanjut ke tahap berikutnya dengan penjelasan unik."
            )
        text = "\n".join(blocks)
        assert text_utils._detect_repetition(text) is False

    # ------------------------------------------------------------------
    # BUG FIX: Reasoning (chain of thought) memakai ambang longgar.
    # Model secara natural menulis ulang rencana/konsep yang sama di dalam
    # CoT, jadi deteksi yang terlalu agresif memicu false positive.
    # strict=False menaikkan ambang LINE-REPEAT (5 -> 8) dan melonggarkan
    # ambang diversity (0.35 -> 0.25).
    # ------------------------------------------------------------------
    def test_reasoning_line_repeat_less_strict(self):
        # 6x baris identik + banyak konten acak (diversity tinggi).
        # strict=True -> LINE-REPEAT (5x) True; strict=False -> threshold 8, lolos.
        repeated = "Baris identik yang diulang untuk tes line repeat.\n" * 6
        # Konten acak yang benar-benar beragam supaya diversity check tidak memicu.
        words = (
            "alpha bravo charlie delta echo foxtrot golf hotel india juliet "
            "kilo lima mike november oscar papa quebec romeo sierra tango "
            "uniform victor whiskey xray yankee zulu"
        ).split()
        random.seed(7)
        random_words = " ".join(random.choice(words) for _ in range(4000))
        text = repeated + random_words
        assert text_utils._detect_repetition(text, strict=True) is True
        assert text_utils._detect_repetition(text, strict=False) is False

    def test_reasoning_still_detects_true_loop(self):
        # Kalimat identik berulang 8x adalah loop sungguhan, harus tetap
        # terdeteksi bahkan dengan ambang longgar (strict=False).
        text = "Kita perlu menambahkan fitur baru pada modul konfigurasi. " * 8
        assert text_utils._detect_repetition(text, strict=False) is True

    # ------------------------------------------------------------------
    # BUG FIX: Baris tabel markdown ("| Tool | Fungsi |") yang identik
    # muncul di BANYAK tabel berbeda (header kolom yang sama) adalah
    # markdown SAH, bukan loop degenerate. Sebelumnya LINE-REPEAT
    # menghitung header "| Tool | Fungsi |" 5x (5 tabel) dan memicu
    # false positive. Header tersebar tidak boleh ditandai sebagai loop.
    # ------------------------------------------------------------------
    def test_markdown_table_headers_spread_not_detected(self):
        # 5 tabel berbeda, masing-masing dengan header "| Tool | Fungsi |"
        # yang sama -- ini jawaban sah yang menyusun banyak tabel.
        text = ""
        for i in range(5):
            text += f"{i}. Section {i}\n"
            text += "| Tool | Fungsi |\n"
            text += "|------|---------|\n"
            text += "| ffuf | fuzzer  |\n"
            text += "\n"
        assert text_utils._detect_repetition(text) is False

    def test_markdown_table_headers_many_spread_not_detected(self):
        # 8 tabel berbeda (melebihi REPEAT_MAX_OCCUR=5) -- masih sah,
        # header tersebar di antara konten tidak boleh jadi loop.
        text = ""
        for i in range(8):
            text += f"Section {i}\n"
            text += "| Tool | Fungsi |\n"
            text += "|------|---------|\n"
            text += "| nmap | scan   |\n"
            text += "\n"
        assert text_utils._detect_repetition(text) is False

    # Loop degenerate tabel: baris tabel IDENTIK yang diulang BERURUTAN
    # (tanpa konten lain) tetap harus terdeteksi sebagai loop.
    def test_table_row_run_stacked_detected(self):
        text = "| Tool | Fungsi |\n" * state.SEPARATOR_REPEAT_THRESHOLD
        assert text_utils._detect_repetition(text) is True

    def test_table_row_run_stacked_with_blank_lines_detected(self):
        # Baris kosong di antara baris tabel tidak memutus run degenerate.
        text = "| Tool | Fungsi |\n\n" * state.SEPARATOR_REPEAT_THRESHOLD
        assert text_utils._detect_repetition(text) is True


class TestTerminalWidth:
    def test_ansi_stripped(self):
        assert text_utils._terminal_width("\x1b[31mabc\x1b[0m") == 3

    def test_cjk_wide_chars(self):
        assert text_utils._terminal_width("ab中") == 4  # 1+1+2

    def test_plain_ascii(self):
        assert text_utils._terminal_width("hello") == 5


class TestTruncateDisplay:
    def test_does_not_truncate_when_within_limit(self):
        assert text_utils._truncate_display("hello", 10) == "hello"

    def test_truncates_and_adds_ellipsis(self):
        out = text_utils._truncate_display("hello world", 5)
        assert out.endswith("…")
        assert text_utils._terminal_width(out) <= 5


class TestRespTextUtf8:
    def test_none_response(self):
        assert text_utils._resp_text_utf8(None) == ""

    def test_decodes_utf8_content(self):
        class _Resp:
            content = "héllo".encode("utf-8")
            text = "mojibake"

        assert text_utils._resp_text_utf8(_Resp()) == "héllo"


# ---------------------------------------------------------------------------
# spinner -- spinner terminal ringan (menulis ke stderr, aman non-TTY)
# ---------------------------------------------------------------------------

class TestSpinnerTermWidth:
    def test_returns_positive_int(self):
        assert isinstance(spinner_mod._term_width(), int)
        assert spinner_mod._term_width() > 0

    def test_fallback_80_on_error(self, monkeypatch):
        import shutil
        monkeypatch.setattr(
            shutil, "get_terminal_size",
            lambda: (_ for _ in ()).throw(OSError("no tty")),
        )
        assert spinner_mod._term_width() == 80


class _FakeTime:
    """Pengganti modul time: sleep() langsung kembali tanpa menunggu."""

    def sleep(self, _seconds):
        return None


class _FakeStream:
    """Stream tiruan dengan buffer StringIO dan isatty() yang bisa diatur."""

    def __init__(self, isatty=True):
        self._buf = io.StringIO()
        self._isatty = isatty

    def isatty(self):
        return self._isatty

    def write(self, s):
        self._buf.write(s)

    def flush(self):
        pass

    @property
    def value(self):
        return self._buf.getvalue()


class _FakeStop:
    """Pengganti threading.Event: berhenti setelah sejumlah panggilan is_set()."""

    def __init__(self, stop_after=1):
        self._calls = 0
        self._stop_after = stop_after

    def is_set(self):
        self._calls += 1
        return self._calls > self._stop_after


class TestSpinner:
    def test_no_thread_when_not_tty(self, monkeypatch):
        """Kalau stream bukan terminal interaktif, spinner tidak boleh
        menyalakan thread (supaya tidak menulis karakter kontrol ke output
        yang dialihkan ke file/pipe)."""
        fake = _FakeStream(isatty=False)
        monkeypatch.setattr(sys, "stdout", fake)
        sp = spinner_mod.Spinner("pesan", stderr=False)
        with sp as entered:
            assert entered is sp
            assert sp._thread is None  # tidak ada thread
        assert sp._thread is None

    def test_thread_started_when_tty(self, monkeypatch):
        """Kalaupun stream terminal interaktif, spinner no-op TIDAK boleh
        menyalakan thread -- ini sengaja agar tidak menulis karakter kontrol
        (`\\r`) yang bisa menjadi spam frame di lingkungan tertentu."""
        fake = _FakeStream(isatty=True)
        monkeypatch.setattr(sys, "stdout", fake)
        sp = spinner_mod.Spinner("pesan", stderr=False)
        with sp:
            assert sp._thread is None  # no-op: tidak ada thread daemon
        assert sp._thread is None

    def test_exit_returns_false_without_thread(self, monkeypatch):
        """__exit__ harus mengembalikan False (tidak menelan exception)
        walau tidak ada thread yang berjalan."""
        fake = _FakeStream(isatty=False)
        monkeypatch.setattr(sys, "stdout", fake)
        sp = spinner_mod.Spinner("pesan", stderr=False)
        assert sp.__exit__(None, None, None) is False

    def test_fallback_frames_for_non_tty(self, monkeypatch):
        """Untuk stream non-TTY, frame yang dipakai adalah ASCII fallback
        (| / - \), bukan Braille."""
        fake = _FakeStream(isatty=False)
        monkeypatch.setattr(sys, "stdout", fake)
        sp = spinner_mod.Spinner("pesan", stderr=False)
        assert sp._frames == spinner_mod._FALLBACK_FRAMES

    def test_braille_frames_for_tty(self, monkeypatch):
        """Untuk stream TTY, frame Braille yang dipakai."""
        fake = _FakeStream(isatty=True)
        monkeypatch.setattr(sys, "stdout", fake)
        sp = spinner_mod.Spinner("pesan", stderr=False)
        assert sp._frames == spinner_mod._FRAMES

    def test_spin_writes_carriage_return_and_pads_to_term_width(self, monkeypatch):
        """_spin menulis baris diawali \\r dan mengisi spasi hingga selebar
        terminal agar tidak ada sisa karakter dari frame sebelumnya."""
        fake = _FakeStream(isatty=True)
        monkeypatch.setattr(sys, "stdout", fake)
        monkeypatch.setattr(spinner_mod, "_term_width", lambda: 20)
        monkeypatch.setattr(spinner_mod, "time", _FakeTime())
        sp = spinner_mod.Spinner("halo", stderr=False)
        sp._stop = _FakeStop(stop_after=1)  # tulis 1 frame lalu berhenti
        sp._spin()
        out = fake.value
        assert out.startswith("\r")
        assert " halo" in out
        # visual_len("⠋ halo") == 6 -> di-pad dengan 14 spasi.
        assert out.endswith(" " * 14)

    def test_spin_truncates_long_line_to_term_width(self, monkeypatch):
        """Kalau pesan lebih panjang dari lebar terminal, baris dipotong agar
        tidak line-wrap."""
        fake = _FakeStream(isatty=True)
        monkeypatch.setattr(sys, "stdout", fake)
        monkeypatch.setattr(spinner_mod, "_term_width", lambda: 8)
        monkeypatch.setattr(spinner_mod, "time", _FakeTime())
        sp = spinner_mod.Spinner("pesan yang sangat panjang sekali", stderr=False)
        sp._stop = _FakeStop(stop_after=1)
        sp._spin()
        # Baris polos (tanpa \r) tidak boleh melebihi lebar terminal.
        raw = fake.value.strip("\r")
        assert len(raw) <= 8


class TestSpinnerPauseResume:
    """Regresi: spinner harus bisa di-pause sementara dari thread lain (mis.
    confirm()) supaya prompt konfirmasi tidak tertutup karakter spinner."""

    def test_pause_clears_line_and_resume_clears_flag(self, monkeypatch):
        fake = _FakeStream(isatty=True)
        monkeypatch.setattr(sys, "stdout", fake)
        monkeypatch.setattr(spinner_mod, "_term_width", lambda: 20)
        sp = spinner_mod.Spinner("halo", stderr=False)
        assert not sp._paused.is_set()
        sp.pause()
        assert sp._paused.is_set()
        # Spinner no-op: pause() tidak menulis karakter apa pun ke stream
        # (tidak ada carriage-return/spasi) karena thread tidak pernah jalan.
        assert fake.value == ""
        sp.resume()
        assert not sp._paused.is_set()

    def test_spin_skips_writes_while_paused(self, monkeypatch):
        fake = _FakeStream(isatty=True)
        monkeypatch.setattr(sys, "stdout", fake)
        monkeypatch.setattr(spinner_mod, "_term_width", lambda: 20)
        monkeypatch.setattr(spinner_mod, "time", _FakeTime())
        sp = spinner_mod.Spinner("halo", stderr=False)
        sp._paused.set()  # mulai dalam keadaan di-pause
        sp._stop = _FakeStop(stop_after=5)
        sp._spin()
        # Tidak ada karakter frame yang ditulis selama di-pause (hanya
        # mungkin baris bersih dari pause(), yang tidak memakai frame).
        assert "⠋" not in fake.value

    def test_active_registry_tracks_and_discards(self, monkeypatch):
        fake = _FakeStream(isatty=True)
        monkeypatch.setattr(sys, "stdout", fake)
        sp = spinner_mod.Spinner("halo", stderr=False)
        with sp:
            assert sp in spinner_mod._ACTIVE_SPINNERS
        assert sp not in spinner_mod._ACTIVE_SPINNERS


class TestToolMayPrompt:
    """Regresi: _tool_may_prompt() harus menebak tool yang berpotensi
    memunculkan prompt konfirmasi walau auto-approve aktif, supaya spinner
    tidak menutupi prompt di agent_loop.py."""

    def _make(self):
        from garwa.cli import tool_exec
        return tool_exec._tool_may_prompt

    def test_non_destructive_safe_with_approve(self):
        fn = self._make()
        assert fn("read_file", {"path": "x.py"}, True) is False

    def test_any_tool_prompts_without_approve(self):
        fn = self._make()
        assert fn("read_file", {"path": "x.py"}, False) is True

    def test_write_external_path_prompts_with_approve(self, monkeypatch):
        from garwa import tools as tools_module
        monkeypatch.setattr(tools_module.state, "SANDBOX_ENABLED", True)
        monkeypatch.setattr(tools_module.state, "WORKDIR", "/workdir/proyek")
        fn = self._make()
        assert fn("write_file", {"path": "/tmp/luar.py"}, True) is True

    def test_write_internal_path_safe_with_approve(self, monkeypatch):
        from garwa import tools as tools_module
        monkeypatch.setattr(tools_module.state, "SANDBOX_ENABLED", True)
        monkeypatch.setattr(tools_module.state, "WORKDIR", "/workdir/proyek")
        fn = self._make()
        assert fn("write_file", {"path": "dalam.py"}, True) is False

    def test_risky_bash_prompts_with_approve(self, monkeypatch):
        from garwa import tools as tools_module
        monkeypatch.setattr(tools_module.state, "SANDBOX_ENABLED", True)
        fn = self._make()
        assert fn("bash", {"command": "rm -rf /tmp/x"}, True) is True

    def test_safe_bash_no_prompt_with_approve(self):
        fn = self._make()
        assert fn("bash", {"command": "ls -la"}, True) is False


# ---------------------------------------------------------------------------
# llm_errors
# ---------------------------------------------------------------------------

class TestParseContextExceeded:
    def _resp(self, status_code, body):
        class _Resp:
            def __init__(self, code, data):
                self.status_code = code
                self._data = data

            def json(self):
                return self._data

        return _Resp(status_code, body)

    def test_parses_context_exceeded(self):
        body = {
            "error": {
                "code": 400,
                "message": "context too big",
                "type": "exceed_context_size_error",
                "n_prompt_tokens": 85043,
                "n_ctx": 65536,
            }
        }
        err = llm_errors._parse_context_exceeded(self._resp(400, body))
        assert isinstance(err, llm_errors.ContextExceededError)
        assert err.n_prompt_tokens == 85043
        assert err.n_ctx == 65536
        assert "context too big" in str(err)

    def test_returns_none_for_non_400(self):
        assert llm_errors._parse_context_exceeded(self._resp(500, {})) is None

    def test_returns_none_for_wrong_type(self):
        body = {"error": {"type": "invalid_request_error"}}
        assert llm_errors._parse_context_exceeded(self._resp(400, body)) is None

    def test_returns_none_for_non_json(self):
        class _Resp:
            status_code = 400

            def json(self):
                raise ValueError("no json")

        assert llm_errors._parse_context_exceeded(_Resp()) is None

    def test_returns_none_for_none(self):
        assert llm_errors._parse_context_exceeded(None) is None


class TestErrorClasses:
    def test_context_exceeded_defaults(self):
        err = llm_errors.ContextExceededError("msg")
        assert err.n_ctx is None
        assert err.n_prompt_tokens is None

    def test_truncated_generation_fields(self):
        err = llm_errors.TruncatedGenerationError(
            "msg", finish_reason="length", completion_tokens=10, reasoning_tokens=5
        )
        assert err.finish_reason == "length"
        assert err.completion_tokens == 10
        assert err.reasoning_tokens == 5


# ---------------------------------------------------------------------------
# slash_commands
# ---------------------------------------------------------------------------

class _Args:
    """Stub sederhana meniru argparse.Namespace untuk handle_slash_command."""
    def __init__(self, **kw):
        self.db_path = ":memory:"
        self.workdir = "/tmp/garwa-test"
        self.skills_dir = ""
        self.full_tool_schema_text = False
        self.session_title = None
        self.auto_approve = False
        self.model = "deepseek-v4-flash-0731"
        self.url = "http://localhost:11434/v1"
        self.api_key = ""
        self.context_window = 131072
        for k, v in kw.items():
            setattr(self, k, v)


class TestSlashCommands:
    def test_non_slash_returns_continue(self):
        args = _Args()
        r = slash_commands.handle_slash_command("halo dunia", args, "s1", "sys")
        assert r["action"] == "continue"

    def test_help_returns_skip(self, capsys):
        args = _Args()
        r = slash_commands.handle_slash_command("/help", args, "s1", "sys")
        assert r["action"] == "skip"
        out = capsys.readouterr().out
        assert "/resume" in out and "/exit" in out

    def test_clear_returns_skip(self):
        args = _Args()
        r = slash_commands.handle_slash_command("/clear", args, "s1", "sys")
        assert r["action"] == "skip"

    def test_exit_returns_exit(self):
        args = _Args()
        r = slash_commands.handle_slash_command("/exit", args, "s1", "sys")
        assert r["action"] == "exit"

    def test_quit_returns_exit(self):
        args = _Args()
        r = slash_commands.handle_slash_command("/quit", args, "s1", "sys")
        assert r["action"] == "exit"

    def test_unknown_slash_falls_through(self):
        # Command tak dikenal dianggap pesan biasa (continue), bukan error.
        args = _Args()
        r = slash_commands.handle_slash_command("/foo bar", args, "s1", "sys")
        assert r["action"] == "continue"

    def test_approve_toggles(self, capsys):
        args = _Args(auto_approve=False)
        r = slash_commands.handle_slash_command("/approve", args, "s1", "sys")
        assert r["action"] == "skip"
        assert args.auto_approve is True
        r = slash_commands.handle_slash_command("/approve", args, "s1", "sys")
        assert args.auto_approve is False

    def test_model_set(self, capsys):
        args = _Args()
        r = slash_commands.handle_slash_command("/api-model llama3", args, "s1", "sys")
        assert r["action"] == "skip"
        assert args.model == "llama3"

    def test_model_no_arg_shows_current(self, capsys):
        args = _Args()
        r = slash_commands.handle_slash_command("/api-model", args, "s1", "sys")
        assert r["action"] == "skip"
        assert args.model == "deepseek-v4-flash-0731"

    def test_model_persists_to_config(self, capsys):
        args = _Args()
        r = slash_commands.handle_slash_command("/api-model gpt-4o-mini", args, "s1", "sys")
        assert r["action"] == "skip"
        assert args.model == "gpt-4o-mini"
        assert config.load_user_config().get("model") == "gpt-4o-mini"

    def test_model_strips_whitespace(self, capsys):
        args = _Args()
        slash_commands.handle_slash_command("/api-model   llama3.1  ", args, "s1", "sys")
        assert args.model == "llama3.1"
        assert config.load_user_config().get("model") == "llama3.1"

    def test_model_reload_from_config(self, monkeypatch):
        # Simulasi sesi baru: nilai model dibaca ulang dari file config.
        monkeypatch.delenv("LLAMA_MODEL", raising=False)
        config.save_user_config(model="qwen2.5-coder")
        config._reload_values()
        assert config.LLAMA_MODEL == "qwen2.5-coder"

    def test_model_env_overrides_config(self, monkeypatch):
        monkeypatch.setenv("LLAMA_MODEL", "env-model")
        config.save_user_config(model="cfg-model")
        config._reload_values()
        assert config.LLAMA_MODEL == "env-model"
        monkeypatch.delenv("LLAMA_MODEL", raising=False)
        config._reload_values()
        assert config.LLAMA_MODEL == "cfg-model"

    def test_url_set(self, capsys):
        args = _Args()
        r = slash_commands.handle_slash_command("/api-url http://localhost:8080/v1", args, "s1", "sys")
        assert r["action"] == "skip"
        assert args.url == "http://localhost:8080/v1"

    def test_url_strips_trailing_slash(self, capsys):
        args = _Args()
        r = slash_commands.handle_slash_command("/api-url http://localhost:8080/v1/", args, "s1", "sys")
        assert r["action"] == "skip"
        assert args.url == "http://localhost:8080/v1"

    def test_url_invalid_scheme_rejected(self, capsys):
        args = _Args()
        r = slash_commands.handle_slash_command("/api-url localhost:8080", args, "s1", "sys")
        assert r["action"] == "skip"
        assert args.url == "http://localhost:11434/v1"  # tidak berubah

    def test_url_no_arg_shows_current(self, capsys):
        args = _Args()
        r = slash_commands.handle_slash_command("/api-url", args, "s1", "sys")
        assert r["action"] == "skip"
        assert args.url == "http://localhost:11434/v1"

    def test_url_persists_to_config(self, capsys):
        args = _Args()
        r = slash_commands.handle_slash_command("/api-url http://localhost:9090/v1", args, "s1", "sys")
        assert r["action"] == "skip"
        assert args.url == "http://localhost:9090/v1"
        assert config.load_user_config().get("url") == "http://localhost:9090/v1"

    def test_api_key_persists_to_config(self, capsys):
        args = _Args()
        r = slash_commands.handle_slash_command("/api-key sk-persist123", args, "s1", "sys")
        assert r["action"] == "skip"
        assert args.api_key == "sk-persist123"
        assert config.load_user_config().get("api_key") == "sk-persist123"

    def test_api_key_set(self, capsys):
        args = _Args()
        r = slash_commands.handle_slash_command("/api-key sk-abc123", args, "s1", "sys")
        assert r["action"] == "skip"
        assert args.api_key == "sk-abc123"

    def test_api_key_no_arg_removes_key(self, capsys):
        # Tanpa argumen: /api-key harus benar-benar menghapus key dari config.
        args = _Args()
        slash_commands.handle_slash_command("/api-key sk-secret1234", args, "s1", "sys")
        assert config.load_user_config().get("api_key") == "sk-secret1234"
        r = slash_commands.handle_slash_command("/api-key", args, "s1", "sys")
        assert r["action"] == "skip"
        assert args.api_key == ""  # nilai aktif ikut direset
        assert "api_key" not in config.load_user_config()  # hilang dari file
        out = capsys.readouterr().out
        assert "sk-secret1234" not in out  # key tidak boleh bocor penuh

    def test_api_key_no_arg_when_empty(self, capsys):
        # Tanpa argumen saat memang tidak ada key: laporkan, tidak error.
        args = _Args(api_key="")
        r = slash_commands.handle_slash_command("/api-key", args, "s1", "sys")
        assert r["action"] == "skip"
        assert args.api_key == ""
        out = capsys.readouterr().out
        assert "tidak ada API key" in out

    def test_ctx_set_valid(self, capsys):
        args = _Args()
        r = slash_commands.handle_slash_command("/ctx 8192", args, "s1", "sys")
        assert r["action"] == "skip"
        assert args.context_window == 8192

    def test_ctx_invalid(self, capsys):
        args = _Args()
        r = slash_commands.handle_slash_command("/ctx abc", args, "s1", "sys")
        assert r["action"] == "skip"
        assert args.context_window == 131072  # tidak berubah

    def test_tools_lists(self, capsys):
        args = _Args()
        r = slash_commands.handle_slash_command("/tools", args, "s1", "sys")
        assert r["action"] == "skip"
        assert "Tool yang tersedia" in capsys.readouterr().out

    def test_todos_empty(self, capsys, tmp_path):
        args = _Args(db_path=str(tmp_path / "test.db"))
        state.DB_PATH = args.db_path
        dbmod.init_db(args.db_path)
        r = slash_commands.handle_slash_command("/todos", args, "s1", "sys")
        assert r["action"] == "skip"
        assert "belum ada plan" in capsys.readouterr().out

    def test_pin_single(self, capsys, tmp_path):
        args = _Args(db_path=str(tmp_path / "test.db"))
        state.DB_PATH = args.db_path
        dbmod.init_db(args.db_path)
        sid = dbmod.create_session(args.db_path, args.workdir)
        dbmod.add_message(args.db_path, sid, "user", "pesan penting", kind="chat")
        dbmod.add_message(args.db_path, sid, "assistant", "jawaban", kind="chat")
        r = slash_commands.handle_slash_command("/pin 1", args, sid, "sys")
        assert r["action"] == "skip"
        assert dbmod.get_message(args.db_path, sid, 1)["pinned"] == 1
        assert dbmod.get_message(args.db_path, sid, 2)["pinned"] == 0

    def test_pin_multi_comma_and_space(self, capsys, tmp_path):
        args = _Args(db_path=str(tmp_path / "test.db"))
        state.DB_PATH = args.db_path
        dbmod.init_db(args.db_path)
        sid = dbmod.create_session(args.db_path, args.workdir)
        for i in range(3):
            dbmod.add_message(args.db_path, sid, "user", f"msg {i}", kind="chat")
        r = slash_commands.handle_slash_command("/pin 1,3", args, sid, "sys")
        assert r["action"] == "skip"
        assert dbmod.get_message(args.db_path, sid, 1)["pinned"] == 1
        assert dbmod.get_message(args.db_path, sid, 2)["pinned"] == 0
        assert dbmod.get_message(args.db_path, sid, 3)["pinned"] == 1

    def test_pin_missing_id_reported(self, capsys, tmp_path):
        args = _Args(db_path=str(tmp_path / "test.db"))
        state.DB_PATH = args.db_path
        dbmod.init_db(args.db_path)
        sid = dbmod.create_session(args.db_path, args.workdir)
        dbmod.add_message(args.db_path, sid, "user", "satu", kind="chat")
        r = slash_commands.handle_slash_command("/pin 2 99 999", args, sid, "sys")
        assert r["action"] == "skip"
        out = capsys.readouterr().out
        assert "#99" in out and "#999" in out

    def test_unpin(self, capsys, tmp_path):
        args = _Args(db_path=str(tmp_path / "test.db"))
        state.DB_PATH = args.db_path
        dbmod.init_db(args.db_path)
        sid = dbmod.create_session(args.db_path, args.workdir)
        dbmod.add_message(args.db_path, sid, "user", "penting", kind="chat")
        dbmod.set_message_pinned(args.db_path, sid, 1, pinned=1)
        r = slash_commands.handle_slash_command("/unpin 1", args, sid, "sys")
        assert r["action"] == "skip"
        assert dbmod.get_message(args.db_path, sid, 1)["pinned"] == 0

    def test_pinned_lists(self, capsys, tmp_path):
        args = _Args(db_path=str(tmp_path / "test.db"))
        state.DB_PATH = args.db_path
        dbmod.init_db(args.db_path)
        sid = dbmod.create_session(args.db_path, args.workdir)
        dbmod.add_message(args.db_path, sid, "user", "konten rahasia", kind="chat")
        dbmod.set_message_pinned(args.db_path, sid, 1, pinned=1)
        r = slash_commands.handle_slash_command("/pinned", args, sid, "sys")
        assert r["action"] == "skip"
        out = capsys.readouterr().out
        assert "konten rahasia" in out

    def test_messages_shows_pin_flag(self, capsys, tmp_path):
        args = _Args(db_path=str(tmp_path / "test.db"))
        state.DB_PATH = args.db_path
        dbmod.init_db(args.db_path)
        sid = dbmod.create_session(args.db_path, args.workdir)
        dbmod.add_message(args.db_path, sid, "user", "halo", kind="chat")
        dbmod.set_message_pinned(args.db_path, sid, 1, pinned=1)
        r = slash_commands.handle_slash_command("/messages", args, sid, "sys")
        assert r["action"] == "skip"
        out = capsys.readouterr().out
        assert "[PIN]" in out

    def test_todos_with_items_shows_status(self, capsys, tmp_path):
        # Verifikasi perbaikan: status dibaca dari kolom `status`, bukan
        # key `done` yang tidak pernah ada -> setiap item harus punya mark
        # yang benar sesuai statusnya.
        args = _Args(db_path=str(tmp_path / "test.db"))
        state.DB_PATH = args.db_path
        dbmod.init_db(args.db_path)
        sid = dbmod.create_session(args.db_path, args.workdir)
        dbmod.add_message(args.db_path, sid, "user", "buat plan", kind="chat")
        dbmod.replace_todos(args.db_path, sid, [
            {"content": "task pending", "status": "pending"},
            {"content": "task selesai", "status": "done"},
            {"content": "task jalan", "status": "in_progress"},
            {"content": "task batal", "status": "cancelled"},
        ])
        r = slash_commands.handle_slash_command("/todos", args, sid, "sys")
        assert r["action"] == "skip"
        out = capsys.readouterr().out
        assert "[ ] task pending" in out
        assert "[x] task selesai" in out
        assert "[~] task jalan" in out
        assert "[-] task batal" in out


class TestPromptLabel:
    def test_prompt_label_basic(self):
        args = _Args()
        label = _build_prompt_label(args, "0123456789abcdef", "proj")
        assert label == "garwa@proj"

    def test_prompt_label_ignores_model(self):
        # Prompt utama ringkas; model tidak lagi ditampilkan di sini.
        args = _Args(model="llama-3.1-8b")
        label = _build_prompt_label(args, "0123456789abcdef", "proj")
        assert label == "garwa@proj"

    def test_status_info_basic(self):
        args = _Args()
        info = _build_status_info(args, "0123456789abcdef")
        assert "deepseek-v4-flash-0731" in info
        assert "ctx:131072" in info
        assert "ses:01234567" in info

    def test_status_info_auto_approve_flag(self):
        args = _Args(auto_approve=True)
        info = _build_status_info(args, "abc12345")
        assert "auto:ON" in info

    def test_status_info_no_auto_approve_shows_off(self):
        args = _Args(auto_approve=False)
        info = _build_status_info(args, "abc12345")
        assert "auto:OFF" in info

    def test_status_info_sandbox_flag(self):
        args = _Args()
        info = _build_status_info(args, "abc12345")
        # SANDBOX_ENABLED default True di tools/_state.py -> ON.
        assert "sandbox:ON" in info

    def test_status_info_tools_count(self):
        args = _Args()
        info = _build_status_info(args, "abc12345")
        assert "tools:0" in info

    def test_status_info_model_change_reflected(self):
        args = _Args(model="llama-3.1-8b")
        info = _build_status_info(args, "xyz78901")
        assert "llama-3.1-8b" in info
        assert "deepseek" not in info

    def test_status_info_session_id_shortened_to_8(self):
        args = _Args()
        info = _build_status_info(args, "abcdefghijklmnop")
        assert "ses:abcdefgh" in info
        assert "ijklmnop" not in info

    def test_status_info_ctx_zero_omitted(self):
        args = _Args(context_window=0)
        info = _build_status_info(args, "abc12345")
        assert "ctx:" not in info


# ---------------------------------------------------------------------------
# prompt_ui -- format toolbar status bar
# ---------------------------------------------------------------------------

class TestPromptToolbar:
    """Verifikasi _format_toolbar membungkus status_info jadi HTML berwarna
    untuk bottom_toolbar prompt_toolkit."""

    def test_empty_info_returns_empty(self):
        assert _format_toolbar("") == ""

    def test_colors_each_token(self):
        html = _format_toolbar("[deepseek-x] ctx:131072 ses:01234567 tools:3 sandbox:ON auto:OFF")
        assert "<bottom-toolbar.model>[deepseek-x]</bottom-toolbar.model>" in html
        assert "<bottom-toolbar.ctx>ctx:131072</bottom-toolbar.ctx>" in html
        assert "<bottom-toolbar.ses>ses:01234567</bottom-toolbar.ses>" in html
        assert "<bottom-toolbar.tools>tools:3</bottom-toolbar.tools>" in html
        assert "<bottom-toolbar.sandbox.on>sandbox:ON</bottom-toolbar.sandbox.on>" in html
        assert "<bottom-toolbar.auto.off>auto:OFF</bottom-toolbar.auto.off>" in html

    def test_sandbox_off_uses_off_class(self):
        html = _format_toolbar("[m] ctx:4096 ses:abc sandbox:OFF")
        assert "<bottom-toolbar.sandbox.off>sandbox:OFF</bottom-toolbar.sandbox.off>" in html
        assert "sandbox.on" not in html

    def test_sandbox_on_uses_on_class(self):
        html = _format_toolbar("[m] ctx:4096 ses:abc sandbox:ON")
        assert "<bottom-toolbar.sandbox.on>sandbox:ON</bottom-toolbar.sandbox.on>" in html
        assert "sandbox.off" not in html

    def test_auto_on_uses_red_class(self):
        html = _format_toolbar("[m] ctx:4096 ses:abc auto:ON")
        assert "<bottom-toolbar.auto>auto:ON</bottom-toolbar.auto>" in html
        assert "auto.off" not in html

    def test_without_auto_flag(self):
        html = _format_toolbar("[m] ctx:4096 ses:abc")
        assert "<bottom-toolbar.auto>" not in html

    def test_unknown_token_plain(self):
        html = _format_toolbar("[m] ctx:4096 ses:abc foo")
        assert "<bottom-toolbar>foo</bottom-toolbar>" in html


# ---------------------------------------------------------------------------
# agent_loop -- ringkasan akhir giliran
# ---------------------------------------------------------------------------

class TestTurnSummary:
    """Verifikasi ringkasan akhir giliran (jumlah tool call, sukses/error,
    durasi, iterasi) yang dicetak oleh run_agent_loop."""

    def _run(self, monkeypatch, capsys, tool_results=None, n_tool_iters=2,
             auto_approve=False):
        """Jalankan run_agent_loop dengan mock; tool_results dipakai berurutan
        oleh execute_tool. `n_tool_iters` = berapa iterasi pertama yang
        mengembalikan tool_call, sisanya jawaban akhir."""
        import argparse
        from garwa.cli import agent_loop

        count = {"n": 0}

        def fake_call(url, model, messages, **kw):
            count["n"] += 1
            if count["n"] <= n_tool_iters:
                return f"toolcall-{count['n']}"
            return "Ini jawaban akhir."

        monkeypatch.setattr(agent_loop, "call_llama_server", fake_call)
        monkeypatch.setattr(agent_loop, "_render_markdown_once", lambda t: None)
        monkeypatch.setattr(
            agent_loop.context_manager, "prepare_context_messages", lambda **kw: [],
        )
        monkeypatch.setattr(agent_loop, "build_openai_tools_payload", lambda: [])
        monkeypatch.setattr(agent_loop.dbmod, "add_message", lambda *a, **k: None)

        tc = {"n": 0}

        def fake_extract(text):
            tc["n"] += 1
            if tc["n"] <= n_tool_iters:
                return ("read_file", {"path": f"x{tc['n']}"})
            return (None, None)

        monkeypatch.setattr(agent_loop, "extract_tool_call", fake_extract)

        results = list(tool_results or [])
        monkeypatch.setattr(
            agent_loop, "execute_tool",
            lambda name, args, aa: results.pop(0),
        )

        args = argparse.Namespace(
            max_tool_iters=10, context_window=131072, url="http://x",
            model="m", no_stream=True, api_key=None, debug=False,
            temperature=0.7, db_path=":memory:", auto_approve=auto_approve,
        )
        out = agent_loop.run_agent_loop(args, "sess1", "sys")
        return out, capsys.readouterr().out

    def test_no_tool_calls(self, monkeypatch, capsys):
        out, text = self._run(monkeypatch, capsys, n_tool_iters=0)
        assert "Ringkasan giliran" in text
        assert "tool calls : 0  (✓0 ✗0)" in text
        assert "iterasi    : 1" in text
        assert "token      : 0" in text
        assert out == "Ini jawaban akhir."

    def test_one_successful_tool(self, monkeypatch, capsys):
        out, text = self._run(monkeypatch, capsys, n_tool_iters=1,
                              tool_results=["hasil sukses"])
        assert "tool calls : 1  (✓1 ✗0)" in text
        assert "iterasi    : 2" in text

    def test_mixed_success_and_error(self, monkeypatch, capsys):
        out, text = self._run(monkeypatch, capsys, n_tool_iters=2,
                              tool_results=["ok", "[ERROR] gagal"])
        assert "tool calls : 2  (✓1 ✗1)" in text
        assert "iterasi    : 3" in text

    def test_all_errors(self, monkeypatch, capsys):
        out, text = self._run(monkeypatch, capsys, n_tool_iters=2,
                              tool_results=["[ERROR] a", "[DITOLAK] b"])
        assert "tool calls : 2  (✓0 ✗2)" in text

    def test_summary_emitted_on_forced_stop(self, monkeypatch, capsys):
        # n_tool_iters besar + hasil error sama berulang -> error-loop stop
        out, text = self._run(monkeypatch, capsys, n_tool_iters=5,
                              tool_results=["[ERROR] sama"] * 10)
        assert "Ringkasan giliran" in text
        assert "tool calls :" in text

    def test_token_total_reflects_turn_usage(self, monkeypatch, capsys):
        # Verifikasi baris token = selisih akumulasi TOKEN_USAGE_TOTAL antara
        # awal dan akhir giliran (in+out), bukan nilai global kumulatif.
        import argparse
        from garwa.cli import agent_loop
        from garwa.cli import _state as state

        # Seed nilai global sebelum giliran (meniru sesi yang sudah berjalan).
        state.TOKEN_USAGE_TOTAL["prompt_tokens"] = 5000
        state.TOKEN_USAGE_TOTAL["completion_tokens"] = 3000
        state.TOKEN_USAGE_TOTAL["total"] = 8000

        # fake_call menambah usage tiap iterasi agar selisih terukur.
        calls = {"n": 0}

        def fake_call(url, model, messages, **kw):
            calls["n"] += 1
            state._accumulate_usage({"prompt_tokens": 100, "completion_tokens": 50})
            if calls["n"] <= 1:
                return "toolcall-1"
            return "Ini jawaban akhir."

        monkeypatch.setattr(agent_loop, "call_llama_server", fake_call)
        monkeypatch.setattr(agent_loop, "_render_markdown_once", lambda t: None)
        monkeypatch.setattr(
            agent_loop.context_manager, "prepare_context_messages", lambda **kw: [],
        )
        monkeypatch.setattr(agent_loop, "build_openai_tools_payload", lambda: [])
        monkeypatch.setattr(agent_loop.dbmod, "add_message", lambda *a, **k: None)

        tc = {"n": 0}

        def fake_extract(text):
            tc["n"] += 1
            if tc["n"] <= 1:
                return ("read_file", {"path": "x1"})
            return (None, None)

        monkeypatch.setattr(agent_loop, "extract_tool_call", fake_extract)
        monkeypatch.setattr(
            agent_loop, "execute_tool",
            lambda name, args, aa: "hasil sukses",
        )

        args = argparse.Namespace(
            max_tool_iters=10, context_window=131072, url="http://x",
            model="m", no_stream=True, api_key=None, debug=False,
            temperature=0.7, db_path=":memory:", auto_approve=False,
        )
        agent_loop.run_agent_loop(args, "sess1", "sys")
        text = capsys.readouterr().out

        assert "Ringkasan giliran" in text
        # 2 iterasi model -> 2x (100 prompt + 50 completion) = 300 token.
        assert "token      : 300" in text
        # Nilai global tetap terakumulasi (bukan di-reset oleh ringkasan).
        assert state.TOKEN_USAGE_TOTAL["total"] == 8300




class TestReadlineHistory:
    """Uji readline history persisten (~/.garwa/history.txt)."""

    def test_constants(self):
        assert HISTORY_MAX == 1000
        assert HISTORY_FILE.endswith(os.path.join(".garwa", "history.txt"))
        assert HISTORY_FILE.startswith(os.path.expanduser("~"))

    def test_init_creates_dir_and_loads_history(self, monkeypatch, tmp_path):
        import importlib
        m = importlib.import_module("garwa.cli.main")

        fake = tmp_path / "history.txt"
        fake.write_text("perintah pertama\nperintah kedua\n")
        monkeypatch.setattr(m, "HISTORY_FILE", str(fake))
        monkeypatch.setattr(m, "HISTORY_DIR", str(tmp_path))

        loaded = []
        set_len = []

        class FakeReadline:
            @staticmethod
            def read_history_file(path):
                loaded.append(path)

            @staticmethod
            def set_history_length(n):
                set_len.append(n)

        monkeypatch.setattr(m, "readline", FakeReadline)
        m._init_readline_history()

        assert loaded == [str(fake)]
        assert set_len == [1000]

    def test_init_does_nothing_without_readline(self, monkeypatch, tmp_path):
        import importlib
        m = importlib.import_module("garwa.cli.main")

        monkeypatch.setattr(m, "readline", None)
        m._init_readline_history()  # tidak boleh raise

    def test_save_writes_history(self, monkeypatch, tmp_path):
        import importlib
        m = importlib.import_module("garwa.cli.main")

        fake = tmp_path / "history.txt"
        monkeypatch.setattr(m, "HISTORY_FILE", str(fake))
        monkeypatch.setattr(m, "HISTORY_DIR", str(tmp_path))

        written = []

        class FakeReadline:
            @staticmethod
            def write_history_file(path):
                written.append(path)

        monkeypatch.setattr(m, "readline", FakeReadline)
        m._save_readline_history()

        assert written == [str(fake)]
        assert tmp_path.exists()

    def test_init_swallows_errors(self, monkeypatch, tmp_path):
        import importlib
        m = importlib.import_module("garwa.cli.main")

        monkeypatch.setattr(m, "HISTORY_FILE", str(tmp_path / "history.txt"))
        monkeypatch.setattr(m, "HISTORY_DIR", str(tmp_path / "sub" / "deep"))

        class FakeReadline:
            @staticmethod
            def read_history_file(path):
                raise OSError("tidak bisa baca")

            @staticmethod
            def set_history_length(n):
                raise RuntimeError("gagal set")

        monkeypatch.setattr(m, "readline", FakeReadline)
        m._init_readline_history()  # harus tetap diam

    def test_save_swallows_errors(self, monkeypatch, tmp_path):
        import importlib
        m = importlib.import_module("garwa.cli.main")

        monkeypatch.setattr(m, "HISTORY_FILE", str(tmp_path / "history.txt"))
        monkeypatch.setattr(m, "HISTORY_DIR", str(tmp_path / "sub" / "deep"))

        class FakeReadline:
            @staticmethod
            def write_history_file(path):
                raise OSError("tidak bisa tulis")

        monkeypatch.setattr(m, "readline", FakeReadline)
        m._save_readline_history()  # harus tetap diam
