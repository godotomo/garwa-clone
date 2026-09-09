"""cli/ndjson.py
Emitter NDJSON (Newline-Delimited JSON) untuk output terstruktur `--json`.

Saat CLI dijalankan dengan `--json`, output manusia (banner, status, ringkasan
berwarna, dll) diredam dan sebagai gantinya CLI mengeluarkan SATU objek JSON
per baris (NDJSON) ke stdout. Ini memudahkan konsumsi programatik: setiap
baris adalah event terstruktur dengan field `type` dan `seq` (urutan).

Event yang di-emit (dari agent_loop):
  - "session_start"  : sesi dimulai (session_id, workdir, model).
  - "assistant"      : teks yang ditulis model (text).
  - "tool_call"      : model memanggil tool (name, arguments).
  - "tool_result"    : hasil eksekusi tool (name, ok, result).
  - "summary"        : ringkasan akhir giliran (tool_calls, errors, duration,
                       tokens).
  - "error"          : kesalahan giliran (message).

Emitter menulis ke `sys.__stdout__` (stream asli) sehingga tetap keluar walau
`sys.stdout` sedang diarahkan ke null oleh `suppress_human_output()`.
"""
import contextlib
import io
import json
import sys


class NDJSONEmitter:
    """Menulis satu objek JSON per baris ke stream tertentu."""

    def __init__(self, stream=None):
        self.stream = stream if stream is not None else sys.__stdout__
        self.seq = 0

    def emit(self, event: str, **fields):
        self.seq += 1
        rec = {"type": event, "seq": self.seq}
        rec.update(fields)
        self.stream.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        self.stream.flush()


_emitter = None


def setup(stream=None) -> NDJSONEmitter:
    """Aktifkan emitter global (dipanggil sekali oleh main() saat --json)."""
    global _emitter
    _emitter = NDJSONEmitter(stream)
    return _emitter


def get_emitter():
    return _emitter


def emit(event: str, **fields):
    """Emit event NDJSON; no-op kalau emitter belum di-setup."""
    e = _emitter
    if e is not None:
        e.emit(event, **fields)


@contextlib.contextmanager
def suppress_human_output():
    """Context manager: saat --json aktif, arahkan sys.stdout (output manusia
    berwarna/banner) ke buffer null supaya stdout bersih hanya berisi NDJSON.

    Emitter menulis ke sys.__stdout__ sehingga tidak ikut teredam.
    """
    old = sys.stdout
    sys.stdout = io.StringIO()
    try:
        yield
    finally:
        sys.stdout = old
