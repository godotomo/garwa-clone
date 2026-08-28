"""cli/markdown_render/reasoning_preview.py
Dipecah lebih lanjut dari cli/markdown_render.py.
"""
import os
import shutil
import sys

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from .. import _state as state
from ..colors import C
from ..colors import c
from ..text_utils import _truncate_display



class ReasoningPreview:
    """Live preview *bounded* untuk `reasoning_content` di mode NORMAL
    (bukan --debug).

    Sebelum ini, reasoning_content dari model (mis. Garwa/model reasoning
    lain lewat server model) hanya terlihat lewat --debug (SSE-RAW mentah).
    Di mode normal ia sama sekali tidak ditampilkan -- padahal server bisa
    diam cukup lama saat model "berpikir" sebelum delta 'content' asli
    mulai mengalir, sehingga terasa seperti stuck.

    Class ini menampilkan sampai REASONING_PREVIEW_MAX_LINES baris TERAKHIR
    dari reasoning secara live-redraw (mirip preview baris aktif di
    MarkdownTerminalRenderer, tapi jauh lebih sederhana: reasoning bukan
    Markdown dan tidak perlu di-commit permanen). Begitu delta 'content'
    asli mulai datang -- atau stream berakhir/gagal -- seluruh preview ini
    DIHAPUS dari layar lewat close(): reasoning trace tidak pernah menjadi
    bagian permanen dari transcript terminal, sama seperti sebelumnya.

    Hanya aktif di TTY interaktif sungguhan (sama seperti live-redraw di
    MarkdownTerminalRenderer); di luar itu (pipe/redirect/TERM=dumb) tidak
    melakukan apa-apa, karena --debug sudah tersedia untuk kasus tsb.
    """

    def __init__(self):
        self.live = sys.stdout.isatty() and os.environ.get("TERM", "") != "dumb"
        self.buffer = ""     # sisa baris reasoning yang belum '\n'
        self.lines = []      # baris final terakhir, bounded
        self.drawn_rows = 0
        self.closed = False

    def _cols(self) -> int:
        try:
            return max(shutil.get_terminal_size(fallback=(80, 24)).columns, 1)
        except Exception:
            return 80

    def _raw(self, text: str):
        if text:
            sys.stdout.write(text)
            sys.stdout.flush()

    def _erase(self):
        if not self.live or self.drawn_rows <= 0:
            self.drawn_rows = 0
            return
        if self.drawn_rows > 1:
            self._raw(f"\x1b[{self.drawn_rows - 1}A")
        self._raw("\x1b[1G\x1b[0J")
        self.drawn_rows = 0

    def _rows_to_draw(self) -> list:
        cols = self._cols()
        body = list(self.lines)
        if self.buffer:
            body.append(self.buffer)
        body = body[-state.REASONING_PREVIEW_MAX_LINES:]
        rows = [c(_truncate_display("  " + ln, max(cols - 2, 1)), C.DIM) for ln in body]
        return [c("[thinking...]", C.CYAN)] + rows

    def _redraw(self):
        if not self.live or self.closed:
            return
        self._erase()
        rows = self._rows_to_draw()
        self._raw("\n".join(rows))
        self.drawn_rows = len(rows)

    def feed(self, text: str):
        if self.closed or not text or not self.live:
            return
        self.buffer += text
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            self.lines.append(line)
            self.lines = self.lines[-state.REASONING_PREVIEW_MAX_LINES:]
        self._redraw()

    def close(self):
        """Hapus preview dari layar. Aman dipanggil berkali-kali/kapan saja
        (termasuk kalau belum pernah menerima reasoning sama sekali).
        """
        if self.closed:
            return
        self._erase()
        self.closed = True
