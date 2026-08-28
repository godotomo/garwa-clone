"""
conftest.py
Fixtures bersama untuk seluruh test suite Garwa.

Prinsip:
- Semua test yang menyentuh DB memakai fixture `db_path` yang menunjuk ke
  file SQLite sementara (tmp_path) sehingga tidak pernah menyentuh DB user
  asli di ~/.garwa.
- Fixture `db_path` sudah di-init (schema dibuat) dan siap dipakai.
"""

import os
import sys

import pytest

# Pastikan root proyek ada di sys.path supaya `import garwa` selalu berhasil
# walau pytest dijalankan dari direktori lain.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from garwa import config  # noqa: E402
from garwa import db as dbmod  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_user_config(tmp_path):
    """Arahkan file konfigurasi pengguna ke tmp_path agar test tidak pernah
    menulis/membaca ~/.config/garwa/config milik user asli."""
    config.USER_CONFIG_PATH = str(tmp_path / "garwa_config")
    yield
    config.USER_CONFIG_PATH = os.path.expanduser("~/.config/garwa/config")


@pytest.fixture
def db_path(tmp_path):
    """Path DB SQLite sementara yang sudah di-init (schema terpasang)."""
    path = str(tmp_path / "test.db")
    dbmod.init_db(path)
    return path


@pytest.fixture
def session_id(db_path):
    """Buat satu sesi di DB sementara dan kembalikan id-nya."""
    return dbmod.create_session(db_path, workdir="/tmp/test-workdir", title="test")


@pytest.fixture
def sample_session(db_path):
    """Sesi yang sudah diisi beberapa pesan chat untuk test context building."""
    sid = dbmod.create_session(db_path, workdir="/tmp/test-workdir", title="ctx")
    dbmod.add_message(db_path, sid, "user", "Halo, apa kabar?")
    dbmod.add_message(db_path, sid, "assistant", "Baik, terima kasih.")
    dbmod.add_message(db_path, sid, "user", "Tolong refactor file main.py")
    dbmod.add_message(db_path, sid, "assistant", "Siap, saya akan kerjakan.")
    return sid
