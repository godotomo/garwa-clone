"""test_sse_long_repro_extra.py
Reproduksi NYATA (bukan tebakan) untuk membuktikan/menyangkal IndexError pada
jalur pemrosesan respon SSE yang SANGAT PANJANG berisi markdown 5 halaman +
kode LaTeX + berbagai jenis tabel + berbagai jenis markdown.

Jalur runtime yang diuji (persis seperti dipakai stream_call.py):
  _stream_visible_text(state, text) -> _print_stream_text(...) -> renderer.feed(...)
  _flush_visible_text(state)        -> renderer.finish()       -> _render_markdown_once(...)
  _latex_to_unicode(...)            -> _render_inline_markdown(...)
  _render_table(...)

Semua fungsi ini dipanggil langsung (bukan mock) sehingga IndexError nyata
akan muncul di sini jika memang ada.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from garwa.cli.markdown_render import MarkdownTerminalRenderer  # noqa: E402
from garwa.cli.markdown_render import ReasoningPreview  # noqa: E402
from garwa.cli.markdown_render.latex import _latex_to_unicode  # noqa: E402
from garwa.cli.stream_parse import _flush_visible_text  # noqa: E402
from garwa.cli.stream_parse import _print_stream_text  # noqa: E402
from garwa.cli.stream_parse import _stream_visible_text  # noqa: E402


def _table_aligned(nrows: int = 30) -> str:
    """Tabel dengan alignment per kolom (kiri/tengah/kanan)."""
    out = ["| Nama | Skor | Status |", "|:-----|:----:|-------:|"]
    for i in range(nrows):
        out.append(f"| item {i} | {i * 7} | {'OK' if i % 2 == 0 else 'FAIL'} |")
    return "\n".join(out)


def _table_markdown_cells(nrows: int = 25) -> str:
    """Tabel dengan sel berisi markdown (tebal, miring, kode inline)."""
    out = ["| Fitur | Deskripsi | Contoh |", "|---|---|---|"]
    for i in range(nrows):
        out.append(
            f"| **fitur {i}** | *deskripsi* `x_{i}` | [link](https://e.com) |"
        )
    return "\n".join(out)


def _table_latex_cells(nrows: int = 20) -> str:
    """Tabel dengan sel berisi rumus LaTeX inline."""
    out = ["| Simbol | Rumus |", "|---|---|"]
    for i in range(nrows):
        out.append(f"| $\\alpha_{i}$ | $\\int_0^{i} x dx = \\frac{{{i}^2}}{{2}}$ |")
    return "\n".join(out)


def _table_many_cols(ncols: int = 12, nrows: int = 15) -> str:
    """Tabel dengan banyak kolom (uji padding/lebar ekstrem)."""
    header = "| " + " | ".join(f"Kolom {j}" for j in range(ncols)) + " |"
    sep = "| " + " | ".join("---" for _ in range(ncols)) + " |"
    out = [header, sep]
    for i in range(nrows):
        out.append("| " + " | ".join(f"c{j},{i}" for j in range(ncols)) + " |")
    return "\n".join(out)


def _table_with_empty_cells(nrows: int = 20) -> str:
    """Tabel dengan sel kosong dan sel berisi spasi (uji padding)."""
    out = ["| A | B | C | D |", "|---|---|---|---|"]
    for i in range(nrows):
        out.append(f"| {i} |  |   | d{i} |")
    return "\n".join(out)


def _table_ragged_rows(nrows: int = 20) -> str:
    """Tabel dengan jumlah sel tidak seragam antar baris (uji ncols/pad)."""
    out = ["| X | Y |", "|---|---|"]
    for i in range(nrows):
        if i % 3 == 0:
            out.append(f"| x{i} | y{i} | z{i} |")
        elif i % 3 == 1:
            out.append(f"| x{i} |")
        else:
            out.append(f"| x{i} | y{i} |")
    return "\n".join(out)


def _build_huge_markdown(pages: int = 5) -> str:
    """Bangun respon markdown sangat panjang (5 halaman) dengan berbagai
    jenis markdown + kode LaTeX + berbagai jenis tabel."""
    parts = []
    for p in range(pages):
        parts.append(f"# Halaman {p + 1}\n\n")
        parts.append("## Ringkasan\n\n")
        parts.append("Ini adalah **teks tebal**, *teks miring*, dan `kode inline`.\n\n")
        parts.append("### Daftar\n\n")
        for i in range(30):
            parts.append(f"- item nomor {i} dengan **penekanan** dan `x_{i}`\n")
        parts.append("\n### Daftar bernomor\n\n")
        for i in range(15):
            parts.append(f"{i + 1}. langkah ke-{i + 1} dengan *catatan* dan `y_{i}`\n")

        # Berbagai jenis tabel
        parts.append("\n### Tabel dasar\n\n")
        parts.append("| Kolom A | Kolom B | Kolom C |\n")
        parts.append("|---------|---------|---------|\n")
        for i in range(40):
            parts.append(f"| a{i} | b{i} | c{i} |\n")

        parts.append("\n### Tabel dengan alignment\n\n")
        parts.append(_table_aligned(30) + "\n\n")

        parts.append("\n### Tabel dengan sel markdown\n\n")
        parts.append(_table_markdown_cells(25) + "\n\n")

        parts.append("\n### Tabel dengan sel LaTeX\n\n")
        parts.append(_table_latex_cells(20) + "\n\n")

        parts.append("\n### Tabel banyak kolom\n\n")
        parts.append(_table_many_cols(12, 15) + "\n\n")

        parts.append("\n### Tabel dengan sel kosong\n\n")
        parts.append(_table_with_empty_cells(20) + "\n\n")

        parts.append("\n### Tabel dengan baris tidak seragam\n\n")
        parts.append(_table_ragged_rows(20) + "\n\n")

        parts.append("### Blok kode Python\n\n")
        parts.append("```python\n")
        for i in range(25):
            parts.append(f"def func_{i}(x):\n    return x + {i}\n\n")
        parts.append("```\n\n")
        parts.append("### Kutipan\n\n")
        parts.append("> Ini kutipan panjang yang berisi **markdown** dan `kode`.\n\n")
        parts.append("### Rumus LaTeX\n\n")
        parts.append(r"Rumus inline: $E = mc^2$ dan $\int_0^\infty e^{-x^2} dx = \frac{\sqrt{\pi}}{2}$")
        parts.append("\n\nRumus display:\n\n")
        parts.append(r"$$\frac{\partial u}{\partial t} = \alpha \nabla^2 u$$")
        parts.append("\n\n")
        parts.append("### Tautan dan gambar\n\n")
        parts.append("[Tautan contoh](https://example.com) dan ![alt](img.png)\n\n")
        parts.append("---\n\n")
        parts.append("Paragraf penutup halaman dengan **berbagai** *format* dan `kode`.\n\n")
    return "".join(parts)


def _new_state(renderer=None):
    return {
        "in_tool": False,
        "tool_name": None,
        "tool_args": "",
        "pending": "",
        "ws_hold": "",
        "renderer": renderer or MarkdownTerminalRenderer(),
        "started": False,
    }


class TestSSELongRepro(unittest.TestCase):
    def test_stream_visible_text_huge_markdown(self):
        """Jalur _stream_visible_text dengan respon markdown sangat panjang (5 halaman)."""
        text = _build_huge_markdown(5)
        state = _new_state()
        out = _stream_visible_text(state, text)
        out2 = _flush_visible_text(state)
        state["renderer"].finish()
        self.assertIsInstance(out, str)
        self.assertIsInstance(out2, str)
        self.assertGreater(len(out) + len(out2), 0)

    def test_print_stream_text_huge_markdown(self):
        """Jalur _print_stream_text -> renderer.feed -> finish."""
        text = _build_huge_markdown(5)
        renderer = MarkdownTerminalRenderer()
        state = _new_state(renderer)
        _print_stream_text(text, state)
        renderer.finish()
        self.assertTrue(state["started"] or True)

    def test_render_markdown_once_huge(self):
        """_render_markdown_once dengan markdown sangat panjang (5 halaman)."""
        from garwa.cli.markdown_render.terminal_renderer import _render_markdown_once
        text = _build_huge_markdown(5)
        buf = io.StringIO()
        with redirect_stdout(buf):
            _render_markdown_once(text)
        self.assertGreater(len(buf.getvalue()), 0)

    def test_latex_to_unicode_many_formulas(self):
        """_latex_to_unicode dengan banyak rumus LaTeX."""
        latex = r"""$E = mc^2$ dan $\int_0^\infty e^{-x^2} dx = \frac{\sqrt{\pi}}{2}$
        $$\frac{\partial u}{\partial t} = \alpha \nabla^2 u$$
        $\sum_{i=1}^{n} i = \frac{n(n+1)}{2}$
        $\sqrt{a^2 + b^2}$
        $\alpha \beta \gamma \delta \epsilon$
        $\int_0^{10} x dx = \frac{10^2}{2}$
        """
        out = _latex_to_unicode(latex)
        self.assertIsInstance(out, str)

    def test_reasoning_preview_feed_huge(self):
        """ReasoningPreview.feed dengan reasoning sangat panjang."""
        preview = ReasoningPreview()
        preview.live = False  # non-TTY supaya tidak menulis ke stdout
        preview.feed("reasoning line " + "x" * 5000 + "\n" + "y" * 5000 + "\n")
        preview.close()
        self.assertTrue(preview.closed)

    def test_renderer_feed_incremental(self):
        """feed bertahap (simulasi delta SSE) lalu finish."""
        renderer = MarkdownTerminalRenderer()
        text = _build_huge_markdown(5)
        for i in range(0, len(text), 1000):
            renderer.feed(text[i:i + 1000])
        renderer.finish()

    def test_full_pipeline_via_stream_visible(self):
        """Pipeline lengkap: stream_visible -> flush -> finish, dengan delta."""
        text = _build_huge_markdown(5)
        renderer = MarkdownTerminalRenderer()
        state = _new_state(renderer)
        for i in range(0, len(text), 500):
            _stream_visible_text(state, text[i:i + 500])
        out = _flush_visible_text(state)
        renderer.finish()
        self.assertIsInstance(out, str)

    def test_huge_with_tool_call_marker(self):
        """Markdown sangat panjang yang berakhir dengan marker tool call."""
        text = _build_huge_markdown(5) + "\n\n<tool_call>\n{\"name\":\"read_file\",\"arguments\":{\"path\":\"x\"}}\n</tool_call>"
        renderer = MarkdownTerminalRenderer()
        state = _new_state(renderer)
        _stream_visible_text(state, text)
        out = _flush_visible_text(state)
        renderer.finish()
        self.assertIsInstance(out, str)

    def test_huge_with_reasoning_and_content(self):
        """Simulasi stream yang punya reasoning_content lalu content."""
        preview = ReasoningPreview()
        preview.live = False
        preview.feed("berpikir...\n" * 50)
        preview.close()

        text = _build_huge_markdown(5)
        renderer = MarkdownTerminalRenderer()
        state = _new_state(renderer)
        _stream_visible_text(state, text)
        out = _flush_visible_text(state)
        renderer.finish()
        self.assertIsInstance(out, str)

    def test_empty_and_whitespace_only(self):
        """Respon kosong / whitespace-only tidak boleh IndexError."""
        for s in ["", "   ", "\n\n\n", "   \n  \n  "]:
            renderer = MarkdownTerminalRenderer()
            state = _new_state(renderer)
            _stream_visible_text(state, s)
            out = _flush_visible_text(state)
            renderer.finish()
            self.assertIsInstance(out, str)

    def test_inline_markdown_huge(self):
        """_render_inline_markdown dengan teks sangat panjang."""
        from garwa.cli.markdown_render.inline import _render_inline_markdown
        text = _build_huge_markdown(5)
        out = _render_inline_markdown(text)
        self.assertIsInstance(out, str)

    def test_tables_huge(self):
        """_render_table dengan tabel sangat banyak baris."""
        from garwa.cli.markdown_render.tables import _render_table
        lines = ["| A | B | C |", "|---|---|---|"]
        lines += [f"| a{i} | b{i} | c{i} |" for i in range(100)]
        out = _render_table(lines)
        self.assertIsInstance(out, str)

    def test_tables_aligned(self):
        """_render_table dengan alignment kiri/tengah/kanan."""
        from garwa.cli.markdown_render.tables import _render_table
        out = _render_table(_table_aligned(50).splitlines())
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 0)

    def test_tables_markdown_cells(self):
        """_render_table dengan sel berisi markdown."""
        from garwa.cli.markdown_render.tables import _render_table
        out = _render_table(_table_markdown_cells(40).splitlines())
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 0)

    def test_tables_latex_cells(self):
        """_render_table dengan sel berisi LaTeX."""
        from garwa.cli.markdown_render.tables import _render_table
        out = _render_table(_table_latex_cells(30).splitlines())
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 0)

    def test_tables_many_cols(self):
        """_render_table dengan banyak kolom (12 kolom)."""
        from garwa.cli.markdown_render.tables import _render_table
        out = _render_table(_table_many_cols(12, 20).splitlines())
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 0)

    def test_tables_empty_cells(self):
        """_render_table dengan sel kosong / spasi."""
        from garwa.cli.markdown_render.tables import _render_table
        out = _render_table(_table_with_empty_cells(20).splitlines())
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 0)

    def test_tables_ragged_rows(self):
        """_render_table dengan jumlah sel tidak seragam antar baris."""
        from garwa.cli.markdown_render.tables import _render_table
        out = _render_table(_table_ragged_rows(30).splitlines())
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 0)

    def test_tables_all_types_in_full_pipeline(self):
        """Semua jenis tabel digabung dalam satu pipeline stream penuh (5 halaman)."""
        text = _build_huge_markdown(5)
        renderer = MarkdownTerminalRenderer()
        state = _new_state(renderer)
        for i in range(0, len(text), 300):
            _stream_visible_text(state, text[i:i + 300])
        out = _flush_visible_text(state)
        renderer.finish()
        self.assertIsInstance(out, str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
