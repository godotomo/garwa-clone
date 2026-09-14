"""Status LIVE sub-agent ke stderr (garwa/subagent_status.py).

Menguji bahwa saat sub-agent mulai/selesai, baris status dicetak otomatis
ke stderr (bukan stdout) sehingga pengguna bisa melihat sub-agent apa saja
yang berjalan tanpa mengetik perintah.
"""
import io
import sys

import pytest

from garwa import subagent_registry as registry
from garwa import subagent_status as substatus


@pytest.fixture(autouse=True)
def _clean():
    registry.clear()
    yield
    registry.clear()


def test_notify_start_and_done(capsys):
    rec = registry.register_start("general", "kerjakan tugas X")
    registry.set_session(rec, "sub_abc")
    substatus.notify_start(rec, "general", "kerjakan tugas X")
    registry.mark_done(rec, registry.STATUS_SUCCESS)
    substatus.notify_done(rec, registry.STATUS_SUCCESS)

    err = capsys.readouterr().err
    assert "mulai" in err
    assert "general" in err
    assert rec in err
    assert "1 berjalan" in err
    assert "selesai" in err
    assert "sub_abc" in err


def test_notify_done_error(capsys):
    rec = registry.register_start("explore", "tugas gagal")
    registry.mark_done(rec, registry.STATUS_ERROR, error="ValueError: boom")
    substatus.notify_done(rec, registry.STATUS_ERROR, error="ValueError: boom")
    err = capsys.readouterr().err
    assert "gagal" in err
    assert "ValueError: boom" in err


def test_notify_done_interrupted(capsys):
    rec = registry.register_start("general", "batal")
    registry.mark_done(rec, registry.STATUS_INTERRUPTED, error="dibatalkan (Ctrl+C)")
    substatus.notify_done(rec, registry.STATUS_INTERRUPTED, error="dibatalkan (Ctrl+C)")
    err = capsys.readouterr().err
    assert "batal" in err


def test_notify_parallel_header(capsys):
    substatus.notify_parallel_header(3, 2)
    err = capsys.readouterr().err
    assert "3 task paralel" in err
    assert "max_workers=2" in err


def test_status_goes_to_stderr_not_stdout(capsys):
    rec = registry.register_start("general", "t")
    substatus.notify_start(rec, "general", "t")
    out = capsys.readouterr()
    assert out.out == ""
    assert "mulai" in out.err


def test_disabled_via_env(capsys, monkeypatch):
    monkeypatch.setenv("GARWA_SUBAGENT_STATUS", "0")
    rec = registry.register_start("general", "t")
    substatus.notify_start(rec, "general", "t")
    assert capsys.readouterr().err == ""


def test_fmt_duration():
    assert substatus._fmt_duration(3) == "3s"
    assert substatus._fmt_duration(80) == "1m20s"
    assert substatus._fmt_duration(7500) == "2h05m"
    assert substatus._fmt_duration(None) == "-"


def test_short_truncates():
    assert substatus._short("a\nb", 60) == "a b"
    assert len(substatus._short("x" * 200, 60)) == 60
