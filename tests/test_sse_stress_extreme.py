"""test_sse_stress_extreme.py
STRES TES EKSTREM (bukan tebakan) — memaksa batas-batas tabel markdown dan
jalur pemrosesan SSE dengan input patologis untuk membuktikan tidak ada
IndexError / crash pada jalur runtime nyata.

Batas yang diuji (dari garwa/cli/_state.py):
  TABLE_BUFFER_LIMIT     = 32 * 1024
  TABLE_MAX_ROWS         = 256
  TABLE_MAX_CELL_WIDTH   = 60
  TABLE_MAX_COLUMNS      = 20

Semua fungsi dipanggil langsung (bukan mock) sehingga IndexError nyata akan
muncul di sini jika memang ada.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from garwa.cli.markdown_render import MarkdownTerminalRenderer  # noqa: E402
from garwa.cli.markdown_render import ReasoningPreview  # noqa: E402
from garwa.cli.markdown_render.tables import _render_table  # noqa: E402
from garwa.cli.stream_parse import _flush_visible_text  # noqa: E402
from garwa.cli.stream_parse import _stream_visible_text  # noqa: E402


def _table_header_1col_rows_many(nrows: int = 50, ncols_data: int = 25) -> str:
    """Header 1 kolom tapi baris data punya 25 kolom (ncols dari data)."""
    out = ["| H |", "|---|"]
    for i in range(nrows):
        out.append("| " + " | ".join(f"v{j},{i}" for j in range(ncols_data)) + " |")
    return "\n".join(out)


def _table_header_many_rows_1col(ncols_h: int = 30, nrows: int = 40) -> str:
    """Header 30 kolom tapi baris data hanya 1 kolom (ncols dari header)."""
    out = ["| " + " | ".join(f"H{j}" for j in range(ncols_h)) + " |",
           "| " + " | ".join("---" for _ in range(ncols_h)) + " |"]
    for i in range(nrows):
        out.append(f"| only{i} |")
    return "\n".join(out)


def _table_over_max_cols(ncols: int = 60, nrows: int = 30) -> str:
    """Tabel dengan kolom melebihi TABLE_MAX_COLUMNS (20)."""
    out = ["| " + " | ".join(f"C{j}" for j in range(ncols)) + " |",
           "| " + " | ".join("---" for _ in range(ncols)) + " |"]
    for i in range(nrows):
        out.append("| " + " | ".join(f"x{j},{i}" for j in range(ncols)) + " |")
    return "\n".join(out)


def _table_over_max_rows(nrows: int = 500, ncols: int = 5) -> str:
    """Tabel dengan baris melebihi TABLE_MAX_ROWS (256)."""
    out = ["| " + " | ".join(f"C{j}" for j in range(ncols)) + " |",
           "| " + " | ".join("---" for _ in range(ncols)) + " |"]
    for i in range(nrows):
        out.append("| " + " | ".join(f"r{i}c{j}" for j in range(ncols)) + " |")
    return "\n".join(out)


def _table_huge_cells(nrows: int = 20) -> str:
    """Tabel dengan sel sangat panjang (melebihi TABLE_MAX_CELL_WIDTH=60)."""
    out = ["| Nama | Isi Panjang |", "|---|---|"]
    for i in range(nrows):
        out.append(f"| item {i} | {'x' * 500} dan **tebal** `kode` |")
    return "\n".join(out)


def _table_all_pathological() -> str:
    """Tabel menggabungkan semua kondisi patologis sekaligus."""
    ncols = 45  # > MAX_COLUMNS
    out = ["| " + " | ".join(f"H{j}" for j in range(ncols)) + " |",
           "| " + " | ".join(":---" for _ in range(ncols)) + " |"]
    for i in range(300):  # > MAX_ROWS
        if i % 5 == 0:
            # baris hanya 2 kolom (ragged ekstrem)
            out.append(f"| hanya{i} | {i} |")
        else:
            cells = [f"{'y' * 200}_{j}_{i}" for j in range(ncols)]
            out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def _fuzz_table(seed: int, nrows: int = 60) -> str:
    """Tabel fuzz dengan jumlah kolom acak per baris (deterministik)."""
    import random
    rng = random.Random(seed)
    ncols_h = rng.randint(1, 40)
    out = ["| " + " | ".join(f"H{j}" for j in range(ncols_h)) + " |",
           "| " + " | ".join("---" for _ in range(ncols_h)) + " |"]
    for i in range(nrows):
        nc = rng.randint(1, 50)
        cells = [f"c{j}i{i}" for j in range(nc)]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def _build_giant_markdown() -> str:
    """Markdown raksasa: 20 halaman + semua jenis tabel patologis
    diselingi kode blok, kutipan, LaTeX, list, dsb."""
    parts = []
    for p in range(20):
        parts.append(f"# Halaman {p + 1}\n\n")
        parts.append("## Intro\n\n")
        parts.append("**tebal** *miring* `kode` $E=mc^2$ dan [link](https://e.com)\n\n")
        parts.append("### List\n\n")
        for i in range(40):
            parts.append(f"- item {i} dengan `x_{i}`\n")
        parts.append("\n### Tabel dasar\n\n")
        parts.append("| A | B | C |\n|---|---|---|\n")
        for i in range(60):
            parts.append(f"| a{i} | b{i} | c{i} |\n")
        parts.append("\n### Tabel patologis (ragged + over-max)\n\n")
        parts.append(_table_all_pathological() + "\n\n")
        parts.append("\n### Tabel sel raksasa\n\n")
        parts.append(_table_huge_cells(20) + "\n\n")
        parts.append("\n### Kode blok\n\n")
        parts.append("```python\n")
        for i in range(30):
            parts.append(f"def f{i}(x):\n    return x + {i}\n\n")
        parts.append("```\n\n")
        parts.append("### Kutipan\n\n")
        parts.append("> kutipan **tebal** `kode`\n\n")
        parts.append("### LaTeX display\n\n")
        parts.append(r"$$\int_0^\infty e^{-x^2} dx = \frac{\sqrt{\pi}}{2}$$")
        parts.append("\n\n---\n\n")
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


class TestSSEStressExtreme(unittest.TestCase):
    def test_table_header_1col_rows_many(self):
        """Header 1 kolom, baris data 25 kolom -> ncols dari data, header dipad."""
        out = _render_table(_table_header_1col_rows_many().splitlines())
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 0)

    def test_table_header_many_rows_1col(self):
        """Header 30 kolom, baris data 1 kolom -> ncols dari header, rows dipad."""
        out = _render_table(_table_header_many_rows_1col().splitlines())
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 0)

    def test_table_over_max_columns(self):
        """Kolom 60 (> MAX_COLUMNS=20) harus dipotong tanpa crash."""
        out = _render_table(_table_over_max_cols(60, 30).splitlines())
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 0)

    def test_table_over_max_rows(self):
        """Baris 500 (> MAX_ROWS=256) harus diproses tanpa crash."""
        out = _render_table(_table_over_max_rows(500, 5).splitlines())
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 0)

    def test_table_huge_cells(self):
        """Sel 500 char (> MAX_CELL_WIDTH=60) harus di-truncate tanpa crash."""
        out = _render_table(_table_huge_cells(20).splitlines())
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 0)

    def test_table_all_pathological(self):
        """Semua kondisi patologis digabung dalam satu tabel."""
        out = _render_table(_table_all_pathological().splitlines())
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 0)

    def test_table_fuzz_many_seeds(self):
        """Fuzz 20 seed berbeda dengan jumlah kolom acak per baris."""
        for seed in range(20):
            out = _render_table(_fuzz_table(seed).splitlines())
            self.assertIsInstance(out, str)
            self.assertGreater(len(out), 0)

    def test_giant_markdown_full_pipeline(self):
        """Markdown raksasa 20 halaman lewat pipeline stream penuh."""
        text = _build_giant_markdown()
        renderer = MarkdownTerminalRenderer()
        state = _new_state(renderer)
        for i in range(0, len(text), 200):
            _stream_visible_text(state, text[i:i + 200])
        out = _flush_visible_text(state)
        renderer.finish()
        self.assertIsInstance(out, str)

    def test_giant_markdown_single_chunk(self):
        """Markdown raksasa 20 halaman dalam satu chunk besar."""
        text = _build_giant_markdown()
        renderer = MarkdownTerminalRenderer()
        state = _new_state(renderer)
        _stream_visible_text(state, text)
        out = _flush_visible_text(state)
        renderer.finish()
        self.assertIsInstance(out, str)

    def test_giant_markdown_random_chunks(self):
        """Markdown raksasa dipecah menjadi chunk ukuran acak (simulasi delta SSE)."""
        import random
        rng = random.Random(42)
        text = _build_giant_markdown()
        renderer = MarkdownTerminalRenderer()
        state = _new_state(renderer)
        i = 0
        while i < len(text):
            step = rng.randint(1, 300)
            _stream_visible_text(state, text[i:i + step])
            i += step
        out = _flush_visible_text(state)
        renderer.finish()
        self.assertIsInstance(out, str)

    def test_giant_markdown_with_tool_call(self):
        """Markdown raksasa diakhiri marker tool_call."""
        text = _build_giant_markdown() + "\n\n<tool_call>\n{\"name\":\"read_file\",\"arguments\":{\"path\":\"x\"}}\n</tool_call>"
        renderer = MarkdownTerminalRenderer()
        state = _new_state(renderer)
        _stream_visible_text(state, text)
        out = _flush_visible_text(state)
        renderer.finish()
        self.assertIsInstance(out, str)

    def test_giant_markdown_render_once(self):
        """_render_markdown_once dengan markdown raksasa."""
        from garwa.cli.markdown_render.terminal_renderer import _render_markdown_once
        text = _build_giant_markdown()
        buf = io.StringIO()
        with redirect_stdout(buf):
            _render_markdown_once(text)
        self.assertGreater(len(buf.getvalue()), 0)

    def test_reasoning_preview_extreme(self):
        """ReasoningPreview dengan input sangat besar dan banyak baris."""
        preview = ReasoningPreview()
        preview.live = False
        preview.feed("line " + "z" * 10000 + "\n" * 500)
        preview.close()
        self.assertTrue(preview.closed)

    def test_table_empty_separator_only(self):
        """Tabel dengan separator tak valid / baris tunggal tidak crash."""
        for lines in [
            ["| A | B |"],
            ["| A | B |", "| a | b |"],  # baris ke-2 bukan separator
            ["| A | B |", "|---|---|"],
            ["| A | B |", "| :--- | ---: |", "| x | y |"],
        ]:
            out = _render_table(lines)
            self.assertIsInstance(out, str)

    def test_table_cells_with_pipes_escaped(self):
        """Sel berisi pipe yang tidak di-escape (malformed) tidak crash."""
        out = _render_table(["| A | B |", "|---|---|", "| a|b | c |", "| d | e|f |"])
        self.assertIsInstance(out, str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
