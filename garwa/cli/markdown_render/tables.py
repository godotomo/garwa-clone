"""cli/markdown_render/tables.py
Dipecah lebih lanjut dari cli/markdown_render.py.
"""
import re

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from .. import _state as state
from ..text_utils import _terminal_width
from ..text_utils import _truncate_display
from .inline import _render_inline_markdown



def _is_table_row(line: str) -> bool:
    """Deteksi row Markdown table secara konservatif."""
    stripped = line.strip()
    if "|" not in stripped:
        return False
    if stripped.startswith("```") or stripped.startswith("~~~"):
        return False
    cells = stripped.strip("|").split("|")
    return len(cells) >= 2


def _is_table_separator(line: str) -> bool:
    cells = line.strip().strip("|").split("|")
    if len(cells) < 2:
        return False
    for cell in cells:
        cell = cell.strip()
        if not re.fullmatch(r":?-{1,}:?", cell):
            return False
    return True


def _split_table_row(line: str) -> list:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _render_table(lines: list) -> str:
    """Render tabel Markdown ke tabel Unicode bounded.

    Tidak pernah memproses code fence karena caller hanya mengirim tabel di
    luar code. Cell Markdown/LaTeX tetap dirender setelah struktur tabel aman.
    """
    if len(lines) < 2 or not _is_table_separator(lines[1]):
        return "\n".join(lines)

    header = _split_table_row(lines[0])
    separator = _split_table_row(lines[1])
    rows = [_split_table_row(x) for x in lines[2:]]

    ncols = min(max(len(header), *(len(r) for r in rows)), state.TABLE_MAX_COLUMNS)
    header = header[:ncols]
    rows = [r[:ncols] + [""] * max(0, ncols - len(r)) for r in rows]
    separator = separator[:ncols]

    def cell_text(value):
        return _render_inline_markdown(value).replace("\n", " ")

    all_rows = [[cell_text(x) for x in header]]
    all_rows.extend([[cell_text(x) for x in row] for row in rows])

    widths = []
    for col in range(ncols):
        width = max(_terminal_width(row[col]) for row in all_rows)
        widths.append(min(max(width, 1), state.TABLE_MAX_CELL_WIDTH))

    def fit(value, width):
        value = _truncate_display(value, width)
        pad = max(0, width - _terminal_width(value))
        return value + " " * pad

    def border(left, mid, right, char="─"):
        return left + mid.join(char * (w + 2) for w in widths) + right

    out = [border("┌", "┬", "┐")]
    out.append("│" + "│".join(" " + fit(all_rows[0][i], widths[i]) + " " for i in range(ncols)) + "│")
    out.append(border("├", "┼", "┤"))
    for row in all_rows[1:]:
        out.append("│" + "│".join(" " + fit(row[i], widths[i]) + " " for i in range(ncols)) + "│")
    out.append(border("└", "┴", "┘"))
    return "\n".join(out)
