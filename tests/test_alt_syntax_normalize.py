"""test_alt_syntax_normalize.py

Normalizer sintaks tool_call ASING -> blok resmi `<tool_call>{json}</tool_call>`.

Keluarga sintaks yang dinormalkan (semua ditemukan di data produksi):
  * DSML (`<|DSML|` / `｜｜DSML｜｜`, pemisah U+FF5C fullwidth solidus);
  * XML `<invoke name="...">` + `<parameter name="...">`;
  * `<function=name>` / `<function name=...>` (penutup sering hilang);
  * tag varian spasi/pipa (`<tool call>`, `<tool_call|>`).

Kontrak penting: normalizer dipanggil di HULU (agent_loop sebelum ekstraksi),
sehingga blok yang DIEKSEKUSI = blok yang dinormalkan. Blok resmi yang JSON-nya
SUDAH valid dilindungi (tidak disentuh) supaya isi string argumen yang memuat
teks mirip tag tidak merusak JSON.
"""

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from garwa.cli import _state as state  # noqa: E402
from garwa.cli.json_repair import extract_tool_calls  # noqa: E402
from garwa.cli.tool_schema.alt_syntax import (  # noqa: E402
    _convert_alt_tool_call_syntax,
    _normalize_alt_forms,
)


def _first_call(text):
    """Normalkan lalu ekstrak; kembalikan (name, arguments) pertama."""
    calls = extract_tool_calls(_convert_alt_tool_call_syntax(text))
    assert calls, f"tidak ada tool_call yang berhasil diekstrak dari: {text!r}"
    return calls[0]


class TestDsmlSyntax:
    def test_fullwidth_dsml_invoke(self):
        text = (
            "<\uff5c\uff5cDSML\uff5c\uff5c invoke name=\"bash\">\n"
            "<\uff5c\uff5cDSML\uff5c\uff5c parameter name=\"command\">ls -la"
            "</\uff5c\uff5cDSML\uff5c\uff5c parameter>\n"
            "</\uff5c\uff5cDSML\uff5c\uff5c invoke>"
        )
        name, args = _first_call(text)
        assert name == "bash"
        assert args["command"] == "ls -la"

    def test_ascii_pipe_dsml(self):
        text = (
            "<|DSML| invoke name=\"read_file\">\n"
            "<|DSML| parameter name=\"path\">main.py</|DSML| parameter>\n"
            "</|DSML| invoke>"
        )
        name, args = _first_call(text)
        assert name == "read_file"
        assert args["path"] == "main.py"

    def test_dsml_marks_do_not_leak_into_output(self):
        text = "<\uff5c\uff5cDSML\uff5c\uff5c invoke name=\"bash\">x</\uff5c\uff5cDSML\uff5c\uff5c invoke>"
        out = _convert_alt_tool_call_syntax(text)
        assert "\uff5c" not in out
        assert "DSML" not in out


class TestXmlInvokeSyntax:
    def test_invoke_with_parameters(self):
        text = (
            "<invoke name=\"edit_file\">\n"
            "<parameter name=\"path\">a.py</parameter>\n"
            "<parameter name=\"old_str\">foo</parameter>\n"
            "<parameter name=\"new_str\">bar</parameter>\n"
            "</invoke>"
        )
        name, args = _first_call(text)
        assert name == "edit_file"
        assert args == {"path": "a.py", "old_str": "foo", "new_str": "bar"}

    def test_invoke_missing_closer_still_converted(self):
        # Penutup invoke sering hilang; harus tetap dikonversi sampai akhir teks.
        text = (
            "<invoke name=\"bash\">\n"
            "<parameter name=\"command\">pwd</parameter>"
        )
        name, args = _first_call(text)
        assert name == "bash"
        assert args["command"] == "pwd"

    def test_invoke_without_parameters_left_as_is(self):
        # Tidak ada parameter -> bukan tool_call; jangan bikin blok JSON kosong.
        text = "<invoke name=\"bash\"></invoke>"
        out = _convert_alt_tool_call_syntax(text)
        assert state.TOOL_OPEN not in out


class TestFunctionSyntax:
    def test_function_eq_name(self):
        text = (
            "<function=bash>\n"
            "<parameter name=\"command\">echo hi</parameter>\n"
            "</function>"
        )
        name, args = _first_call(text)
        assert name == "bash"
        assert args["command"] == "echo hi"

    def test_function_name_attr(self):
        text = (
            "<function name=\"grep\">\n"
            "<parameter name=\"pattern\">TODO</parameter>\n"
            "</function>"
        )
        name, args = _first_call(text)
        assert name == "grep"
        assert args["pattern"] == "TODO"

    def test_function_missing_closer(self):
        # Data nyata: penutup function hilang, isi berhenti di akhir teks.
        text = (
            "<function=read_file>\n"
            "<parameter name=\"path\">x.txt</parameter>"
        )
        name, args = _first_call(text)
        assert name == "read_file"
        assert args["path"] == "x.txt"


class TestCallTagVariants:
    def test_space_variant_tag(self):
        text = "<tool call>\n{\"name\": \"bash\", \"arguments\": {\"command\": \"pwd\"}}\n</tool call>"
        name, args = _first_call(text)
        assert name == "bash"
        assert args["command"] == "pwd"

    def test_pipe_variant_tag(self):
        text = "<tool_call|>\n{\"name\": \"bash\", \"arguments\": {\"command\": \"pwd\"}}\n<tool_call|>"
        name, args = _first_call(text)
        assert name == "bash"
        assert args["command"] == "pwd"

    def test_alias_name_mapped(self):
        text = "<invoke name=\"read\"><parameter name=\"path\">f.py</parameter></invoke>"
        name, args = _first_call(text)
        assert name == "read_file"
        assert args["path"] == "f.py"

    def test_namespace_name_mapped(self):
        text = "<invoke name=\"fs.read_file\"><parameter name=\"path\">f.py</parameter></invoke>"
        name, args = _first_call(text)
        assert name == "read_file"


class TestProtectionOfValidBlocks:
    def test_valid_block_untouched_by_normalizer(self):
        # Isi string argumen memuat teks mirip tag; JSON valid HARUS utuh.
        payload = {
            "name": "write_file",
            "arguments": {"path": "a.md", "content": "contoh <function=foo> dan <parameter name=x>"},
        }
        text = state.TOOL_OPEN + "\n" + json.dumps(payload) + "\n" + state.TOOL_CLOSE
        out = _convert_alt_tool_call_syntax(text)
        name, args = extract_tool_calls(out)[0]
        assert name == "write_file"
        assert args["content"] == "contoh <function=foo> dan <parameter name=x>"

    def test_no_op_when_no_alt_syntax(self):
        text = "Cuma teks biasa tanpa pemanggilan tool."
        assert _convert_alt_tool_call_syntax(text) == text

    def test_empty_text(self):
        assert _convert_alt_tool_call_syntax("") == ""


class TestStrayTagCleanup:
    def test_dangling_closer_dropped(self):
        text = "hasil selesai\n</tool_call>\n"
        out = _convert_alt_tool_call_syntax(text)
        assert "</tool_call>" not in out

    def test_real_call_after_noise_still_executed(self):
        text = (
            "blah </tool_call> blah\n"
            "<tool_call>\n{\"name\": \"bash\", \"arguments\": {\"command\": \"pwd\"}}\n</tool_call>"
        )
        name, args = _first_call(text)
        assert name == "bash"
        assert args["command"] == "pwd"

    def test_normalize_alt_forms_no_drop_keeps_pairing_decision(self):
        # drop_stray_tags=False menunda pembuangan (dipakai per-potongan teks).
        text = "x</tool_call>y"
        assert _normalize_alt_forms(text, drop_stray_tags=False) == text
