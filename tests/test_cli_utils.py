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

import json as _json
import os
import pytest

from garwa import db as dbmod
from garwa.cli import _state as state
from garwa.cli import json_repair, llm_errors, slash_commands, stream_parse, text_utils
from garwa.cli.main import _build_prompt_label, _build_status_info
from garwa.cli.main import HISTORY_DIR, HISTORY_FILE, HISTORY_MAX
from garwa.cli.main import _init_readline_history, _save_readline_history
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


class TestDetectRepetition:
    def test_repeated_line_detected(self):
        text = "line one\n" * state.REPEAT_MAX_OCCUR
        assert text_utils._detect_repetition(text) is True

    def test_short_text_not_repetitive(self):
        assert text_utils._detect_repetition("just a short response") is False

    def test_repeated_unit_detected(self):
        unit = "x" * state.REPEAT_MIN_UNIT_LEN
        text = unit * state.REPEAT_MAX_OCCUR
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
        r = slash_commands.handle_slash_command("/model llama3", args, "s1", "sys")
        assert r["action"] == "skip"
        assert args.model == "llama3"

    def test_model_no_arg_shows_current(self, capsys):
        args = _Args()
        r = slash_commands.handle_slash_command("/model", args, "s1", "sys")
        assert r["action"] == "skip"
        assert args.model == "deepseek-v4-flash-0731"

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
        assert "<bottom-toolbar.sandbox>sandbox:ON</bottom-toolbar.sandbox>" in html
        assert "<bottom-toolbar.auto.off>auto:OFF</bottom-toolbar.auto.off>" in html

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
