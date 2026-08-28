"""cli/overnight/tee_stdout.py
Dipecah lebih lanjut dari cli/overnight.py.
"""
import re

try:

    import readline  # noqa: F401
except ImportError:
    readline = None





class _TeeStdout:
    """Duplikasi semua yang ditulis ke stdout juga ke file log.

    Kode ANSI (warna/cursor movement) dibuang sebelum ditulis ke file supaya
    file log overnight tetap bersih dan bisa dibaca ulang keesokan harinya.
    Terminal asli tetap menerima output apa adanya (termasuk warna).
    """

    _ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

    def __init__(self, real, log_file):
        self._real = real
        self._log = log_file

    def write(self, text):
        self._real.write(text)
        try:
            self._log.write(self._ANSI_RE.sub("", text))
        except Exception:
            pass
        return len(text)

    def flush(self):
        self._real.flush()
        try:
            self._log.flush()
        except Exception:
            pass

    def isatty(self):
        return self._real.isatty()

    def __getattr__(self, name):
        return getattr(self._real, name)
