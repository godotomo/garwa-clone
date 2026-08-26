"""cli/markdown_render/terminal_renderer.py
Dipecah lebih lanjut dari cli/markdown_render.py.
"""
import argparse
import base64
import copy
import difflib
import json
import mimetypes
import os
import re
import select
import shlex
import shutil
import sys
import time
import unicodedata
from collections import OrderedDict
from datetime import datetime
from urllib.parse import unquote, urlparse

try:

    import readline  # noqa: F401
except ImportError:
    readline = None

import requests

from ...tools import TOOLS
from .. import _state as state
from ..colors import C
from ..colors import c
from ..text_utils import _terminal_width
from ..text_utils import _truncate_display
from .inline import _render_inline_markdown
from .tables import _is_table_row
from .tables import _is_table_separator
from .tables import _render_table



class MarkdownTerminalRenderer:
    """Renderer incremental Markdown + LaTeX + table dengan bounded buffers
    dan live redraw per-baris supaya streaming terasa realtime di TTY.

    - Baris yang SEDANG diketik (belum ada '\n') di-redraw in-place memakai
      cursor movement ANSI standar, sehingga bold/heading/dll langsung
      terlihat begitu penanda Markdown-nya lengkap.
    - Baris yang SUDAH final (menerima '\n') di-COMMIT permanen dan TIDAK
      PERNAH digambar ulang lagi -- biaya redraw tetap O(panjang baris aktif).
    - Baris kandidat tabel tetap ditahan (hidden) sampai strukturnya jelas;
      preview live-nya otomatis dihapus begitu baris final ternyata bagian
      dari tabel.
    - Buffer tetap bounded; baris sangat panjang tanpa newline di-flush
      sebagai teks polos (safety valve) dan berhenti di-redraw.
    - Di luar TTY interaktif (pipe/redirect/TERM=dumb), otomatis kembali ke
      perilaku tulis-setiap-baris-sekali, tanpa trik cursor.
    - ESC mentah dari model (\x1b) selalu dibuang di titik masuk paling awal
      (feed), termasuk untuk konten di dalam fenced code block.
    """

    def __init__(self):

        self.PREFIX_TEXT = f"{state.AGENT_NAME}> "

        self.buffer = ""            # raw text baris yang belum final
        self.table_lines = []
        self.table_bytes = 0
        self.in_code = False
        self.closed = False

        self.prefix_written = False

        self.on_prefix_row = False

        self.live = sys.stdout.isatty() and os.environ.get("TERM", "") != "dumb"
        self.drawn_rows = 0  # baris terminal yang ditempati preview live (0 = tidak ada)
        self._safety_valve = False  # True selama baris berjalan sudah di-flush polos (lihat feed())


    def _raw(self, text: str):
        if text:
            sys.stdout.write(text)
            sys.stdout.flush()

    def _cols(self) -> int:
        try:
            return max(shutil.get_terminal_size(fallback=(80, 24)).columns, 1)
        except Exception:
            return 80

    def _ensure_prefix(self):
        if not self.prefix_written:
            self.prefix_written = True
            self.on_prefix_row = True
            self._raw(c(self.PREFIX_TEXT, C.BLUE))

    def _commit_newline(self):
        """Tulis newline sungguhan; sesudah ini prefix tidak lagi relevan
        untuk perhitungan kolom (cursor sudah pindah ke baris baru).
        """
        self._raw("\n")
        self.on_prefix_row = False


    def _prefix_offset(self) -> int:
        return len(self.PREFIX_TEXT) if self.on_prefix_row else 0

    def _rows_for(self, width: int) -> int:
        if width <= 0:
            return 0
        cols = self._cols()
        first = max(cols - self._prefix_offset(), 1)
        if width <= first:
            return 1
        return 1 + -(-(width - first) // cols)

    def _erase_preview(self):
        """Hapus apa pun yang sedang tergambar sebagai preview baris aktif.
        Aman dipanggil kapan saja, termasuk saat tidak ada yang tergambar.
        """
        if not self.live or self.drawn_rows <= 0:
            self.drawn_rows = 0
            return
        if self.drawn_rows > 1:
            self._raw(f"\x1b[{self.drawn_rows - 1}A")
        self._raw(f"\x1b[{self._prefix_offset() + 1}G\x1b[0J")
        self.drawn_rows = 0

    def _draw_preview(self, rendered_text: str):
        if not self.live:
            return
        self._ensure_prefix()
        self._raw(rendered_text)
        self.drawn_rows = self._rows_for(_terminal_width(rendered_text)) if rendered_text else 0

    def _update_preview(self):
        """Gambar ulang baris yang sedang berjalan (self.buffer) di tempat."""
        if not self.live or self.closed or self._safety_valve:
            return
        rendered = self._preview_text(self.buffer)
        self._erase_preview()
        self._draw_preview(rendered)

    def _preview_text(self, line: str) -> str:
        """Render TANPA efek samping untuk baris yang belum final. Tidak
        pernah mengubah self.in_code -- itu hanya boleh terjadi sekali,
        secara otoritatif, saat baris benar-benar final (lihat
        _render_and_toggle).
        """
        if self.in_code:
            return line
        if re.match(r"^\s*(```+|~~~+)", line):
            return line
        return _render_inline_markdown(line)

    def _render_and_toggle(self, line: str) -> str:
        """Satu-satunya tempat status in_code (fenced code) berubah. Dipanggil
        tepat sekali per baris, hanya saat baris tsb final.
        """
        fence = re.match(r"^\s*(```+|~~~+)", line)
        if fence:
            self.in_code = not self.in_code
            return line
        if self.in_code:
            return line
        return _render_inline_markdown(line)


    def _flush_table(self, force_plain=False):
        if not self.table_lines:
            return

        lines = self.table_lines
        self.table_lines = []
        self.table_bytes = 0

        if force_plain or len(lines) < 2 or not _is_table_separator(lines[1]):
            rendered = "\n".join(lines)
        else:
            rendered = _render_table(lines)

        self._ensure_prefix()
        self._raw(rendered)
        self._commit_newline()

    def _hide_into_table(self, line: str):

        self._erase_preview()
        self.table_lines.append(line)
        self.table_bytes += len(line)

    def _commit_visible_line(self, line: str):

        rendered = self._render_and_toggle(line)
        self._erase_preview()
        self._ensure_prefix()
        self._raw(rendered)
        self._commit_newline()

    def _finalize_line(self, line: str):
        if self.in_code:
            self._commit_visible_line(line)
            return

        fence = re.match(r"^\s*(```+|~~~+)", line)
        if fence:
            self._flush_table()
            self._commit_visible_line(line)
            return

        if self.table_lines:
            if len(self.table_lines) == 1:

                if _is_table_separator(line):
                    self._hide_into_table(line)
                    return
                self._flush_table(force_plain=True)
            else:
                if _is_table_row(line):
                    self._hide_into_table(line)
                    if (len(self.table_lines) >= state.TABLE_MAX_ROWS or
                            self.table_bytes >= state.TABLE_BUFFER_LIMIT):
                        self._flush_table(force_plain=True)
                    return
                self._flush_table()

        if _is_table_row(line):
            self._hide_into_table(line)
        else:
            self._commit_visible_line(line)


    def feed(self, text: str):
        if self.closed or not text:
            return

        text = text.replace("\x1b", "")

        self.buffer += text

        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            self._safety_valve = False
            self._finalize_line(line)

        if len(self.buffer) > state.MARKDOWN_BUFFER_LIMIT:

            self._flush_table(force_plain=True)
            self._erase_preview()
            self._ensure_prefix()
            self._safety_valve = True
            while len(self.buffer) > state.MARKDOWN_FLUSH_CHUNK:
                self._raw(self.buffer[:state.MARKDOWN_FLUSH_CHUNK])
                self.buffer = self.buffer[state.MARKDOWN_FLUSH_CHUNK:]
        else:
            self._update_preview()

    def abort(self):
        """Best-effort cleanup kalau streaming berhenti tidak normal (error
        jaringan, Ctrl+C) di tengah sebuah baris. Membiarkan apa pun yang
        sudah terlihat di layar apa adanya, cukup memindahkan cursor ke
        baris baru -- supaya pesan [ERROR]/[INTERRUPTED] yang dicetak
        sesudah ini tidak nyambung di baris yang sama dengan preview live
        yang belum sempat dihapus.
        """
        if self.closed:
            return
        if self.drawn_rows > 0:
            self._raw("\n")
            self.on_prefix_row = False
            self.drawn_rows = 0
        self._safety_valve = True
        self.closed = True

    def finish(self):
        if self.closed:
            return

        emitted_newline = False

        if self.buffer:
            self._finalize_line(self.buffer)
            self.buffer = ""
            emitted_newline = True

        if self.table_lines:
            self._flush_table()
            emitted_newline = True

        if self.prefix_written and not emitted_newline:

            self._raw("\n")
        self.closed = True


def _render_markdown_once(text: str):
    renderer = MarkdownTerminalRenderer()
    renderer.feed(text)
    renderer.finish()
