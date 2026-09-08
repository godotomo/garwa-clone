"""tests/test_comm_tools.py
Test hermetic untuk tool komunikasi & penjadwalan Garwa (comm_tools + cron_runner).

Cakupan:
  - Registrasi 8 tool baru di registry TOOLS (schema valid, handler callable).
  - Validasi error saat kredensial kosong (tanpa jaringan nyata).
  - Logika pencocokan cron 5-field (cron_runner._cron_matches / _field_matches).
  - CRUD jadwal di DB sementara (schedule_task/list_schedules/remove_schedule).

Test sengaja TIDAK menyentuh jaringan: jalur SMTP/IMAP/Telegram yang butuh
kredensial nyata hanya diuji pada cabang "kredensial belum diset".
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone

import pytest

from garwa.tools import TOOLS
from garwa.tools import comm_tools
from garwa.tools import cron_runner

WIB = timezone(timedelta(hours=7))

NEW_TOOLS = [
    "send_email", "read_inbox", "read_email", "reply_email",
    "send_telegram", "schedule_task", "list_schedules", "remove_schedule",
]


# ---------------------------------------------------------------------------
# Registrasi
# ---------------------------------------------------------------------------
def test_new_tools_registered():
    for name in NEW_TOOLS:
        assert name in TOOLS, f"{name} harus terdaftar"
        spec = TOOLS[name]
        assert callable(spec["handler"])
        assert spec["schema"]["name"] == name
        assert "inputSchema" in spec["schema"]
        assert "properties" in spec["schema"]["inputSchema"]


def test_send_email_requires_credentials(monkeypatch):
    # Kosongkan kredensial agar jatuh ke jalur error (tanpa jaringan).
    monkeypatch.setattr(comm_tools.config_mod, "EMAIL_USER", "")
    monkeypatch.setattr(comm_tools.config_mod, "EMAIL_PASS", "")
    monkeypatch.setattr(comm_tools.config_mod, "EMAIL_RECIPIENT", "")
    r = comm_tools.tool_send_email(body="halo")
    assert "[ERROR: send_email]" in r


def test_send_telegram_requires_token(monkeypatch):
    monkeypatch.setattr(comm_tools.config_mod, "TELEGRAM_TOKEN", "")
    monkeypatch.setattr(comm_tools.config_mod, "TELEGRAM_CHAT_ID", "")
    r = comm_tools.tool_send_telegram(text="halo")
    assert "[ERROR: send_telegram]" in r


def test_read_inbox_requires_credentials(monkeypatch):
    monkeypatch.setattr(comm_tools.config_mod, "EMAIL_USER", "")
    monkeypatch.setattr(comm_tools.config_mod, "EMAIL_PASS", "")
    r = comm_tools.tool_read_inbox()
    assert "[ERROR: read_inbox]" in r


# ---------------------------------------------------------------------------
# Decode header & body (pure, tanpa jaringan)
# ---------------------------------------------------------------------------
def test_decode_mime_header_plain_and_encoded():
    assert comm_tools._decode_mime_header("Halo") == "Halo"
    assert comm_tools._decode_mime_header("") == ""
    # RFC 2047 encoded-word
    enc = "=?utf-8?q?Halo_Dunia?="
    assert comm_tools._decode_mime_header(enc) == "Halo Dunia"


def test_extract_body_prefers_plain_text():
    import email as email_mod
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    m = MIMEMultipart()
    m.attach(MIMEText("isi plain", "plain", "utf-8"))
    m.attach(MIMEText("<b>isi html</b>", "html", "utf-8"))
    raw = m.as_string().encode()
    parsed = email_mod.message_from_bytes(raw)
    body = comm_tools._extract_body(parsed)
    assert "isi plain" in body


# ---------------------------------------------------------------------------
# Pencocokan cron
# ---------------------------------------------------------------------------
def test_cron_matches_basic():
    d = datetime(2026, 1, 1, 9, 0, tzinfo=WIB)
    assert cron_runner._cron_matches("0 9 * * *", d)
    assert not cron_runner._cron_matches("0 9 * * *", datetime(2026, 1, 1, 9, 5, tzinfo=WIB))


def test_cron_step_and_range():
    assert cron_runner._cron_matches("*/15 * * * *", datetime(2026, 1, 1, 9, 45, tzinfo=WIB))
    assert not cron_runner._cron_matches("*/15 * * * *", datetime(2026, 1, 1, 9, 46, tzinfo=WIB))
    assert cron_runner._cron_matches("0 9-17 * * *", datetime(2026, 1, 1, 12, 0, tzinfo=WIB))
    assert not cron_runner._cron_matches("0 9-17 * * *", datetime(2026, 1, 1, 18, 0, tzinfo=WIB))


def test_cron_list_and_dow():
    assert cron_runner._cron_matches("0 9,12 * * *", datetime(2026, 1, 1, 12, 0, tzinfo=WIB))
    # 2026-01-05 = Senin (dow=1), 2026-01-04 = Minggu (dow=0)
    assert cron_runner._cron_matches("0 9 * * 1", datetime(2026, 1, 5, 9, 0, tzinfo=WIB))
    assert cron_runner._cron_matches("0 9 * * 0", datetime(2026, 1, 4, 9, 0, tzinfo=WIB))
    assert not cron_runner._cron_matches("0 9 * * 1", datetime(2026, 1, 6, 9, 0, tzinfo=WIB))


def test_cron_invalid_expr():
    assert not cron_runner._cron_matches("bad expr", datetime(2026, 1, 1, 9, 0, tzinfo=WIB))


# ---------------------------------------------------------------------------
# CRUD jadwal di DB sementara
# ---------------------------------------------------------------------------
@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(comm_tools.state, "DB_PATH", db_path)
    comm_tools._ensure_cron_table(db_path)
    return db_path


def test_schedule_list_remove(tmp_db):
    r = comm_tools.tool_schedule_task(
        name="pagi", schedule_expr="0 9 * * *", action="send_telegram",
        payload={"text": "selamat pagi"},
    )
    assert "[schedule_task] OK" in r

    listing = comm_tools.tool_list_schedules()
    assert "pagi" in listing
    assert "0 9 * * *" in listing

    # Duplikat nama -> upsert (tetap 1 baris).
    comm_tools.tool_schedule_task(
        name="pagi", schedule_expr="0 10 * * *", action="send_telegram",
        payload={"text": "jam 10"},
    )
    listing2 = comm_tools.tool_list_schedules()
    assert listing2.count("pagi") == 1
    assert "0 10 * * *" in listing2

    r = comm_tools.tool_remove_schedule("pagi")
    assert "[remove_schedule] OK" in r
    assert "pagi" not in comm_tools.tool_list_schedules()


def test_schedule_invalid_action(tmp_db):
    r = comm_tools.tool_schedule_task(name="x", schedule_expr="0 9 * * *", action="bogus")
    assert "[ERROR: schedule_task]" in r


def test_schedule_invalid_cron_expr(tmp_db):
    r = comm_tools.tool_schedule_task(name="x", schedule_expr="0 9", action="bash")
    assert "[ERROR: schedule_task]" in r


def test_remove_missing(tmp_db):
    r = comm_tools.tool_remove_schedule("tidak-ada")
    assert "tidak ditemukan" in r


# ---------------------------------------------------------------------------
# Runner: run_due mengeksekusi task due dan update last_run
# ---------------------------------------------------------------------------
def test_run_due_executes_due_task(tmp_db, monkeypatch):
    comm_tools.tool_schedule_task(
        name="pagi", schedule_expr="* * * * *", action="bash",
        payload={"command": "echo halo"},
    )
    # Jalankan pada menit berapa pun -> "* * * * *" selalu due.
    results = cron_runner.run_due()
    assert any(name == "pagi" for name, _ in results)

    # last_run harus ter-update (nilai float > 0).
    with comm_tools.dbmod.connect(tmp_db) as conn:
        row = conn.execute("SELECT last_run FROM scheduled_tasks WHERE name='pagi'").fetchone()
    assert row["last_run"] is not None and row["last_run"] > 0


# ---------------------------------------------------------------------------
# Perbaikan robustness cron
# ---------------------------------------------------------------------------
def test_validate_cron_expr_strict():
    # Valid
    assert cron_runner._cron_matches("0 9 * * *", datetime(2026, 1, 1, 9, 0, tzinfo=WIB))
    # Invalid: field di luar rentang / sintaks salah harus ditolak oleh validator.
    from garwa.tools._cron_expr import validate_cron_expr
    assert validate_cron_expr("0 9 * * *")
    assert not validate_cron_expr("0 99 * * *")   # jam > 23
    assert not validate_cron_expr("60 * * * *")    # menit > 59
    assert not validate_cron_expr("abc * * * *")   # bukan angka
    assert not validate_cron_expr("0 9")           # kurang 5 field
    assert not validate_cron_expr("0 9 * * 8")     # dow > 7
    assert not validate_cron_expr("0 9 32 * *")    # dom > 31
    assert not validate_cron_expr("0 9 * 13 *")    # bulan > 12


def test_schedule_task_rejects_invalid_expr(tmp_db):
    r = comm_tools.tool_schedule_task(name="x", schedule_expr="0 99 * * *", action="bash")
    assert "[ERROR: schedule_task]" in r
    # Tidak boleh tersimpan.
    assert "x" not in comm_tools.tool_list_schedules()


def test_schedule_task_accepts_steps_and_ranges(tmp_db):
    r = comm_tools.tool_schedule_task(name="ok", schedule_expr="*/15 9-17 * * 1-5", action="bash")
    assert "[schedule_task] OK" in r


def test_run_due_skips_running_task(tmp_db):
    """Task yang sudah di-claim (running=1, claimed_at segar) tidak dieksekusi
    ulang oleh run_due berikutnya (anti-double-run)."""
    comm_tools.tool_schedule_task(
        name="t", schedule_expr="* * * * *", action="bash",
        payload={"command": "echo halo"},
    )
    with comm_tools.dbmod.connect(tmp_db) as conn:
        # Simulasikan runner lain sedang memproses task ini.
        conn.execute(
            "UPDATE scheduled_tasks SET running=1, claimed_at=? WHERE name='t'",
            (time.time(),),
        )
    results = cron_runner.run_due()
    # Karena sudah running, task tidak boleh dieksekusi lagi.
    assert not any(name == "t" for name, _ in results)


def test_run_due_reclaims_stale_task(tmp_db):
    """Task yang claim-nya sudah basi (> CLAIM_STALE_SECONDS) boleh di-claim ulang."""
    comm_tools.tool_schedule_task(
        name="t", schedule_expr="* * * * *", action="bash",
        payload={"command": "echo halo"},
    )
    with comm_tools.dbmod.connect(tmp_db) as conn:
        conn.execute(
            "UPDATE scheduled_tasks SET running=1, claimed_at=? WHERE name='t'",
            (time.time() - cron_runner.CLAIM_STALE_SECONDS - 10,),
        )
    results = cron_runner.run_due()
    assert any(name == "t" for name, _ in results)


def test_run_due_logs_to_schedule_runs(tmp_db):
    """Setelah eksekusi, hasil tercatat di tabel schedule_runs (audit trail)."""
    comm_tools.tool_schedule_task(
        name="logme", schedule_expr="* * * * *", action="bash",
        payload={"command": "echo audit"},
    )
    cron_runner.run_due()
    with comm_tools.dbmod.connect(tmp_db) as conn:
        rows = conn.execute("SELECT * FROM schedule_runs").fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "logme"
    assert rows[0]["status"] == "ok"


def test_seconds_until_next_minute():
    val = cron_runner._seconds_until_next_minute()
    assert 0 < val <= 60


# ---------------------------------------------------------------------------
# Catch-up / missed-run
# ---------------------------------------------------------------------------
def test_missed_slots_hourly():
    """Cron '0 * * * *' (tiap jam) dengan last_run 2 jam lalu -> slot jam 11 terlewat."""
    from datetime import timedelta as _td
    now_local = datetime(2026, 1, 1, 12, 0, tzinfo=WIB)
    last_run = (now_local - _td(hours=2)).timestamp()  # = 10:00 (sudah dijalankan)
    slots = cron_runner._missed_slots("0 * * * *", last_run, now_local)
    # Slot jam 11 terlewat (jam 10 sudah dijalankan; jam 12 = sekarang,
    # ditangani run_due terpisah, bukan catch-up).
    assert len(slots) == 1
    assert slots[0].hour == 11


def test_missed_slots_every_minute_bounded():
    """Cron '* * * * *' dengan last_run sangat lama -> dibatasi MAX_CATCHUP_MINUTES."""
    now_local = datetime(2026, 1, 1, 12, 0, tzinfo=WIB)
    last_run = (now_local - timedelta(hours=5)).timestamp()
    slots = cron_runner._missed_slots("* * * * *", last_run, now_local)
    assert len(slots) <= cron_runner.MAX_CATCHUP_MINUTES


def test_missed_slots_none_when_no_last_run():
    now_local = datetime(2026, 1, 1, 12, 0, tzinfo=WIB)
    assert cron_runner._missed_slots("* * * * *", None, now_local) == []


def test_run_due_catches_up_missed_runs(tmp_db):
    """Task dengan last_run 2 menit lalu & cron '* * * * *' dijalankan ulang
    untuk slot yang terlewat (catch-up), bukan hanya slot sekarang."""
    comm_tools.tool_schedule_task(
        name="catchup", schedule_expr="* * * * *", action="bash",
        payload={"command": "echo catchup"},
    )
    now_local = datetime(2026, 1, 1, 12, 0, tzinfo=WIB)
    # Set last_run 2 menit lalu (jam 11:58).
    last_run = (now_local - timedelta(minutes=2)).timestamp()
    with comm_tools.dbmod.connect(tmp_db) as conn:
        conn.execute("UPDATE scheduled_tasks SET last_run=? WHERE name='catchup'", (last_run,))
    results = cron_runner.run_due(now=now_local)
    # Slot 11:59 terlewat (catch-up) + slot 12:00 (sekarang) = 2 eksekusi.
    assert results.count(("catchup", results[0][1])) >= 1
    # Pastikan dieksekusi lebih dari sekali (catch-up + sekarang).
    names = [n for n, _ in results]
    assert names.count("catchup") >= 2


# ---------------------------------------------------------------------------
# Perbaikan lanjutan robustness cron (P1-P4)
# ---------------------------------------------------------------------------
def test_cron_bash_rejects_dangerous_command(tmp_db):
    """Aksi cron bash harus menolak command berbahaya (guard keamanan)."""
    comm_tools.tool_schedule_task(
        name="danger", schedule_expr="* * * * *", action="bash",
        payload={"command": "rm -rf /"},
    )
    results = cron_runner.run_due()
    # Task dieksekusi tapi hasilnya penolakan, bukan eksekusi nyata.
    assert any(name == "danger" for name, _ in results)
    res = dict(results)["danger"]
    assert "DITOLAK" in res


def test_cron_bash_allows_safe_command(tmp_db):
    comm_tools.tool_schedule_task(
        name="safe", schedule_expr="* * * * *", action="bash",
        payload={"command": "echo aman"},
    )
    results = cron_runner.run_due()
    res = dict(results)["safe"]
    assert "DITOLAK" not in res
    assert "aman" in res


def test_enable_disable_schedule(tmp_db):
    comm_tools.tool_schedule_task(
        name="jadwal", schedule_expr="0 9 * * *", action="bash",
        payload={"command": "echo x"},
    )
    # Disable -> jadwal tidak dieksekusi oleh run_due.
    assert "[disable_schedule] OK" in comm_tools.tool_disable_schedule("jadwal")
    assert "nonaktif" in comm_tools.tool_list_schedules()
    # Enable -> aktif kembali.
    assert "[enable_schedule] OK" in comm_tools.tool_enable_schedule("jadwal")
    assert "aktif" in comm_tools.tool_list_schedules()
    # Enable/disable jadwal yang tidak ada -> error.
    assert "[ERROR: enable_schedule]" in comm_tools.tool_enable_schedule("tidak-ada")
    assert "[ERROR: disable_schedule]" in comm_tools.tool_disable_schedule("tidak-ada")


def test_retry_transient_email(monkeypatch, tmp_db):
    """Aksi send_email yang gagal transien di-retry hingga berhasil."""
    calls = {"n": 0}

    def fake_send_email(**kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            return "[ERROR: send_email] Gagal kirim: network down"
        return "[send_email] OK - terkirim."

    monkeypatch.setattr(comm_tools, "tool_send_email", fake_send_email)
    # Task dengan action send_email.
    task = {"action": "send_email", "payload": json.dumps({})}
    res = cron_runner._execute_task_with_timeout(task)
    assert "OK" in res
    assert calls["n"] == 3


def test_no_retry_for_bash(monkeypatch, tmp_db):
    """Aksi bash TIDAK di-retry (bisa non-idempotent)."""
    calls = {"n": 0}

    def fake_execute(task):
        calls["n"] += 1
        return "[cron bash] exit=1: gagal"

    monkeypatch.setattr(cron_runner, "_execute_task", fake_execute)
    task = {"action": "bash", "payload": json.dumps({"command": "false"})}
    res = cron_runner._execute_task_with_timeout(task)
    assert calls["n"] == 1
