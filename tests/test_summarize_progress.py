"""tests/test_summarize_progress.py
Regresi bug yang dilaporkan user di Termux:

    "progress bar tidak terlihat ada kemajuan, hanya 25% saja,
     pengguna ingin melihat progress bar bisa berjalan dari 0-100%"

Akar masalah: `_summarize_text` memanggil `progress(attempt, total)` SEKALI
per percobaan, dan callback lama memakai `fraction = (attempt + 1) / total`.
Dengan `SUMMARIZE_MAX_RETRIES = 3` maka `total = 4`, jadi percobaan pertama
menampilkan 1/4 = 25% lalu diam selama `requests.post()` yang blocking --
bar tampak macet.

Perbaikan (lihat garwa/cli/progress.py + garwa/context_manager.py):
- Callback TIDAK memakai rumus (attempt+1)/total lagi. Ia hanya memanggil
  `start_creep()`, yang menaikkan fraksi mengikuti WAKTU selama menunggu.
- Hanya ada SATU plafon global (CREEP_CEILING = 95%). Tiap percobaan yang
  di-retry MELANJUTKAN pendakian dari posisi terakhir (bar tidak pernah turun).
  Sengaja BUKAN irisan per percobaan: dengan 4 percobaan, irisan pertama
  berhenti di ~24% sehingga permintaan pertama yang lama membuat bar mandek
  di ~24% -- gejalanya kembali.
- Puncak 100% dipatok `spinner.finish()` setelah ringkasan benar-benar
  didapat, jadi bar tidak pernah mengaku selesai terlalu dini.

Tes di sini menguji ALIRAN fraksi pada jalur PRODUKSI (maybe_summarize ->
_summarize_text -> ProgressBar), bukan hanya API ProgressBar.
"""

import json as jsonlib

import pytest

from garwa import context_manager as cm
from garwa.cli import progress as P


# ---------------------------------------------------------------------------
# Stub requests: percobaan pertama SELALU gagal (Timeout, retryable) supaya
# retry benar-benar teruji, percobaan kedua berhasil.
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _TimeoutStub(Exception):
    pass


class _RequestsStub:
    """Duck-type minimal dari modul `requests` yang dipakai context_manager."""

    Timeout = _TimeoutStub
    ConnectionError = _TimeoutStub
    HTTPError = _TimeoutStub
    RequestException = _TimeoutStub

    def __init__(self, fail_first: int = 1):
        self.fail_first = fail_first
        self.calls = 0

    def post(self, url, json=None, headers=None, timeout=None):  # noqa: A002
        self.calls += 1
        if self.calls <= self.fail_first:
            raise _TimeoutStub("server lambat (simulasi)")
        body = {"narasi": "RINGKASAN", "instruksi_aktif": []}
        payload = {"choices": [{"message": {"content": jsonlib.dumps(body)}}]}
        return _Resp(payload)


class RecordingBar(P.ProgressBar):
    """ProgressBar yang merekam semua fraksi yang pernah dirender."""

    instances = []

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fractions = []
        RecordingBar.instances.append(self)

    def _render(self):
        super()._render()
        self.fractions.append(self._fraction)

    def finish(self, *a, **kw):
        # finish() mematakan 100% lewat `_fraction = 1.0` lalu menulis baris
        # final TANPA memanggil _render(), jadi fraksi akhir harus direkam di
        # sini agar tes bisa memastikan bar benar-benar sampai 100%.
        super().finish(*a, **kw)
        self.fractions.append(self._fraction)


@pytest.fixture()
def recorded_bar(monkeypatch):
    RecordingBar.instances = []
    monkeypatch.setattr(cm, "ProgressBar", RecordingBar)
    return RecordingBar


# ---------------------------------------------------------------------------
# Helper: pakai dbmod langsung (bukan fixture db) supaya tes ini mandiri.
# ---------------------------------------------------------------------------

from garwa import db as dbmod  # noqa: E402


def cm_db_add(db_path, sid, role, content):
    return dbmod.add_message(db_path, sid, role, content)


def _seed(db_path, session_id, n=30):
    for _ in range(n):
        cm_db_add(db_path, session_id, "user", "kata " * 50)


# ---------------------------------------------------------------------------
# Tes
# ---------------------------------------------------------------------------

def test_progress_callback_only_starts_creep(monkeypatch):
    """Callback sekarang TIDAK menghitung fraksi sendiri: ia hanya memulai
    creep. Inilah inti perbaikan -- rumus (attempt+1)/total = 25% sudah hilang.

    Diuji lewat `_summarize_text` (yang memanggil callback per percobaan):
    total percobaan harus tetap dilaporkan, tapi tidak ada lagi fraksi mentah
    yang dipatok langsung oleh callback.
    """
    stub = _RequestsStub(fail_first=1)
    monkeypatch.setattr(cm, "_get_requests", lambda: stub)
    # Backoff tidak perlu benar-benar tidur saat tes.
    monkeypatch.setattr(cm.time, "sleep", lambda s: None)

    seen = []

    def fake_progress(attempt, total_arg):
        seen.append((attempt, total_arg))

    out = cm._summarize_text(
        "http://x", "model", "teks", progress=fake_progress
    )

    assert out["narasi"] == "RINGKASAN"
    assert stub.calls == 2, "percobaan pertama harus di-retry sekali"
    total = cm.SUMMARIZE_MAX_RETRIES + 1
    assert [a for a, _ in seen] == [0, 1], seen
    assert all(t == total for _, t in seen), seen


def test_maybe_summarize_bar_moves_from_0_to_100(recorded_bar, monkeypatch, db_path, session_id):
    """Jalur produksi: bar harus bergerak dari 0% dan berakhir di 100%."""
    _seed(db_path, session_id)

    stub = _RequestsStub(fail_first=1)
    monkeypatch.setattr(cm, "_get_requests", lambda: stub)
    monkeypatch.setattr(cm.time, "sleep", lambda s: None)

    result = cm.maybe_summarize(
        db_path, session_id, "http://x", "model", context_window_tokens=2000
    )
    assert result is True

    assert len(recorded_bar.instances) == 1
    fr = recorded_bar.instances[0].fractions
    # 1) Bar bergerak: ada lebih dari satu nilai fraksi yang berbeda.
    assert len(set(fr)) > 1, f"bar tidak bergerak: {fr}"
    # 2) Bar dimulai dari 0% (bukan melompat ke 25%).
    assert fr[0] == 0.0
    # 3) Bar berakhir di 100% (dipatok finish(), bukan ditebak creep).
    assert fr[-1] == 1.0, f"bar tidak sampai 100%: {fr[-1]}"
    # 4) Monoton tidak turun.
    assert fr == sorted(fr), f"bar mundur: {fr}"


def test_first_attempt_does_not_jump_to_25_percent(recorded_bar, monkeypatch, db_path, session_id):
    """Regresi inti: percobaan PERTAMA tidak boleh langsung melompat ke 25%."""
    _seed(db_path, session_id)

    stub = _RequestsStub(fail_first=0)  # berhasil di percobaan pertama
    monkeypatch.setattr(cm, "_get_requests", lambda: stub)
    monkeypatch.setattr(cm.time, "sleep", lambda s: None)

    assert cm.maybe_summarize(
        db_path, session_id, "http://x", "model", context_window_tokens=2000
    ) is True

    fr = recorded_bar.instances[0].fractions
    assert fr[0] == 0.0
    assert fr[0] != 0.25


def test_retry_continues_climbing_instead_of_restarting(recorded_bar, monkeypatch):
    """Bar tidak boleh TURUN saat percobaan di-retry.

    Ini yang membedakan desain lama (irisan per percobaan: percobaan kedua
    melompat naik ke 25%+ lalu creep dari titik baru) dengan desain baru
    (satu plafon global, creep melanjutkan dari posisi terakhir).
    """
    bar = RecordingBar("", stream=_FakeTTY(), width=48)
    bar.start_creep(base=0.0)
    # Simulasi waktu berjalan 20 detik -> creep naik cukup jauh.
    bar._creep_t0 -= 20.0
    bar._creep_advance()
    first = bar.fraction
    assert first > 0.0

    # Percobaan di-retry: start_creep() lagi (seperti callback pada attempt ke-2).
    bar.start_creep(message="percobaan 2")
    assert bar.fraction >= first, "bar mundur saat retry"


def test_creep_ceiling_keeps_room_before_100(monkeypatch):
    """Creep otomatis tidak boleh mencapai 100%: 100% hanya dari finish()."""
    bar = RecordingBar("", stream=_FakeTTY(), width=48)
    bar.start_creep(base=0.0)
    # Waktu sangat lama -> mendekati asimtot plafon, bukan 100%.
    bar._creep_t0 -= 10_000_000.0
    bar._creep_advance()
    assert bar.fraction <= P.CREEP_CEILING + 1e-9
    assert bar.fraction < 1.0


def test_long_single_request_never_stalls_at_a_slice_ceiling(recorded_bar, monkeypatch):
    """Regresi penting dari desain IRISAN per percobaan.

    Dengan irisan per percobaan (total=4), langit-langit percobaan pertama
    adalah 0.25*0.95 = 0.2375. Permintaan pertama yang berjalan lama akan
    mentok di ~24% -- persis gejala "hanya 25% saja".
    """
    bar = RecordingBar("", stream=_FakeTTY(), width=48)
    bar.start_creep(base=0.0, span=None)
    # Permintaan berlangsung 3 menit (180 detik).
    bar._creep_t0 -= 180.0
    bar._creep_advance()
    assert bar.fraction > 0.90, (
        f"bar berhenti di {bar.fraction:.3f} untuk permintaan 3 menit; "
        "ini gejala 'mentok di 25%' kalau plafon terlalu rendah"
    )


# ---------------------------------------------------------------------------
# FakeTTY kecil (tidak diimpor dari modul lain supaya tes ini mandiri).
# ---------------------------------------------------------------------------

class _FakeTTY:
    def __init__(self):
        self._buf = []

    def isatty(self):
        return True

    def write(self, s):
        self._buf.append(s)

    def flush(self):
        pass

    def getvalue(self):
        return "".join(self._buf)
