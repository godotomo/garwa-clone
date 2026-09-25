"""tests/test_progress_bar.py
Test untuk `garwa.cli.progress.ProgressBar`.

Fokus regresi yang dilaporkan user di Termux:
  1. Lebar terminal salah terdeteksi (fallback 80 padahal layar 48) -> bar
     terpotong/wrap. Deteksi lebar harus menghormati env `COLUMNS`.
  2. Baris TIDAK boleh selebar terminal penuh (memicu auto-wrap) -> maksimal
     `width - 1` kolom.
  3. Tata letak: bar + persentase di baris PERTAMA, teks status di baris
     KEDUA (tulisan dipindah ke bawah, kecuali persentase).
  4. Update berulang di TTY memakai cursor-up yang benar (tidak menumpuk).
"""
import io
import os

import pytest

from garwa.cli import progress as P


class FakeTTY(io.StringIO):
    def isatty(self):
        return True


class FakePipe(io.StringIO):
    def isatty(self):
        return False


# ---------------------------------------------------------------------------
# Deteksi lebar terminal
# ---------------------------------------------------------------------------

def test_term_width_honors_columns_env(monkeypatch):
    """`COLUMNS` harus dipakai (shutil) walau `os.get_terminal_size` gagal
    (kasus Termux: Permission denied)."""
    monkeypatch.setenv("COLUMNS", "48")
    monkeypatch.setattr(os, "get_terminal_size",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("denied")))
    assert P._term_width() == 48


def test_term_width_fallback_when_no_columns(monkeypatch):
    monkeypatch.delenv("COLUMNS", raising=False)
    monkeypatch.delenv("LINES", raising=False)
    monkeypatch.setattr(os, "get_terminal_size",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("denied")))
    # shutil juga gagal -> fallback 80.
    assert P._term_width() == 80


# ---------------------------------------------------------------------------
# Layout: bar di atas, teks di bawah
# ---------------------------------------------------------------------------

def test_layout_bar_first_message_second():
    s = FakeTTY()
    pb = P.ProgressBar("mengirim ke model X", stream=s, width=48)
    pb.set_progress(0.5)
    lines = s.getvalue().split("\n")
    # Baris 1 memuat bar + persentase, TIDAK memuat teks pesan.
    assert "50%" in lines[0]
    assert "█" in lines[0]
    assert "mengirim ke model X" not in lines[0]
    # Baris 2 memuat teks pesan.
    assert "mengirim ke model X" in lines[1]


def test_line_never_reaches_full_terminal_width():
    """Tidak ada baris yang selebar terminal penuh (pemicu auto-wrap)."""
    for width in (20, 48, 80, 120):
        s = FakeTTY()
        pb = P.ProgressBar("pesan yang cukup panjang untuk diuji", stream=s,
                           width=width)
        pb.update(0.42, "pesan yang cukup panjang untuk diuji")
        for ln in s.getvalue().replace("\r", "").split("\n"):
            # Buang ANSI escape + padding trailing untuk mengukur konten nyata.
            assert len(ln.rstrip()) <= width - 1, (
                f"baris melebihi lebar aman pada width={width}: {ln!r}"
            )


def test_bar_uses_almost_full_width():
    """Bar harus memakai hampir seluruh lebar layar (bukan hanya 1 bar)."""
    s = FakeTTY()
    pb = P.ProgressBar("", stream=s, width=48)
    pb.set_progress(1.0)
    line1 = s.getvalue().split("\n")[0].replace("\r", "")
    bar = line1[line1.index("[") + 1:line1.index("]")]
    # Pada 100%, bar terisi penuh dan panjangnya mendekati lebar layar.
    assert bar.count("█") == len(bar)
    assert len(bar) >= 40, f"bar terlalu pendek: {len(bar)}"


def test_percentage_stays_on_bar_line():
    s = FakeTTY()
    pb = P.ProgressBar("teks status", stream=s, width=48)
    pb.set_progress(0.07)
    line1 = s.getvalue().split("\n")[0]
    assert "  7%" in line1


# ---------------------------------------------------------------------------
# Update berulang
# ---------------------------------------------------------------------------

def test_tty_update_uses_cursor_up():
    s = FakeTTY()
    pb = P.ProgressBar("awal", stream=s, width=48)
    pb.set_progress(0.1)
    pb.update(0.5, "tengah")
    pb.update(1.0, "akhir")
    out = s.getvalue()
    # Setiap render setelah yang pertama menaikkan kursor 1 baris (2 baris blok).
    assert out.count("\x1b[1A") == 2
    assert "akhir" in out


def test_non_tty_prints_single_block():
    s = FakePipe()
    pb = P.ProgressBar("pesan", stream=s, width=48)
    pb.set_progress(0.1)
    pb.update(0.5, "pesan baru")
    pb.update(1.0, "pesan akhir")
    out = s.getvalue()
    # Non-TTY: hanya blok pertama yang dicetak, update berikutnya diabaikan.
    assert out.count("pesan") == 1
    assert "pesan baru" not in out
    assert "pesan akhir" not in out


def test_message_truncated_with_ellipsis():
    s = FakeTTY()
    long_msg = "x" * 500
    pb = P.ProgressBar(long_msg, stream=s, width=48)
    pb.set_progress(0.5)
    lines = s.getvalue().split("\n")
    assert len(lines[1].rstrip()) <= 47
    assert lines[1].rstrip().endswith("…")


# ---------------------------------------------------------------------------
# Kemajuan otomatis (creep) -- regresi bug "bar mentok di 25%"
# ---------------------------------------------------------------------------

def _force_elapsed(pb, seconds):
    """Mundurkan waktu mulai creep supaya `_creep_advance()` melihat sudah
    berjalan `seconds` detik (menghindari tes yang benar-benar tidur)."""
    pb._creep_t0 -= seconds


def _fraction_of(pb):
    return pb._fraction


def test_creep_advances_over_time():
    """Creep harus menaikkan fraksi seiring waktu (bukan diam di titik awal)."""
    s = FakeTTY()
    pb = P.ProgressBar("", stream=s, width=48)
    pb.start_creep(base=0.0, span=0.25)
    assert _fraction_of(pb) == 0.0
    seen = []
    for secs in (0.5, 2.0, 6.0, 20.0):
        _force_elapsed(pb, secs)
        pb._creep_advance()
        seen.append(round(_fraction_of(pb), 4))
    # Monoton naik dan benar-benar bergerak.
    assert seen == sorted(seen), seen
    assert seen[0] > 0.0
    assert seen[-1] > seen[0]


def test_creep_half_life_is_half_of_span():
    """`ratio(t) = t/(t+half_life)` -> pada t == half_life tepat separuh span."""
    s = FakeTTY()
    pb = P.ProgressBar("", stream=s, width=48)
    pb.start_creep(base=0.0, span=0.4, half_life=6.0)
    _force_elapsed(pb, 6.0)
    pb._creep_advance()
    # Toleransi longgar: waktu nyata terus berjalan antara start_creep() dan
    # pemeriksaan (beberapa mikrodetik), jadi elapsed sedikit di atas 6.0.
    assert abs(_fraction_of(pb) - 0.2) < 5e-3


def test_creep_never_passes_base_plus_span():
    """Creep TIDAK boleh melewati base+span: 100% hanya dari finish()."""
    s = FakeTTY()
    pb = P.ProgressBar("", stream=s, width=48)
    pb.start_creep(base=0.25, span=0.2)
    _force_elapsed(pb, 100_000.0)
    pb._creep_advance()
    assert _fraction_of(pb) <= 0.25 + 0.2 + 1e-9


def test_creep_span_clamped_to_not_exceed_100_percent():
    """Caller yang memberi span berlebih tetap tidak boleh melewati 100%."""
    s = FakeTTY()
    pb = P.ProgressBar("", stream=s, width=48)
    pb.start_creep(base=0.8, span=5.0)
    _force_elapsed(pb, 100_000.0)
    pb._creep_advance()
    assert _fraction_of(pb) <= 1.0


def test_creep_never_moves_backwards_after_manual_update():
    """Pembaruan manual yang sudah lebih tinggi tidak boleh diturunkan creep."""
    s = FakeTTY()
    pb = P.ProgressBar("", stream=s, width=48)
    pb.start_creep(base=0.0, span=0.25)
    pb.set_progress(0.9)
    _force_elapsed(pb, 1.0)
    pb._creep_advance()
    assert _fraction_of(pb) == 0.9


def test_finish_prints_permanent_100_percent_line():
    """Tanpa finish(), 100% tak pernah terlihat (blok live dihapus saat exit)."""
    s = FakeTTY()
    pb = P.ProgressBar("ringkasan selesai", stream=s, width=48)
    pb.set_progress(0.3)
    pb.finish()
    out = s.getvalue()
    assert "100%" in out
    assert "ringkasan selesai" in out


def test_finish_stops_creep_thread():
    """Creep harus berhenti setelah finish() supaya tidak menggambar ulang."""
    s = FakeTTY()
    pb = P.ProgressBar("", stream=s, width=48)
    pb.start_creep(base=0.0, span=0.5, interval=0.01)
    assert pb._creep_thread is not None
    pb.finish()
    assert pb._creep_thread is None
    assert _fraction_of(pb) == 1.0


def test_exit_after_finish_keeps_final_line():
    """Baris final 100% sengaja ditinggal; __exit__ tidak menghapusnya."""
    s = FakeTTY()
    with P.ProgressBar("selesai", stream=s, width=48) as pb:
        pb.set_progress(0.5)
        pb.finish()
    assert "100%" in s.getvalue()


def test_creep_not_started_on_non_tty():
    """Di non-TTY tidak ada thread creep (pembaruan tak akan terlihat)."""
    s = FakePipe()
    pb = P.ProgressBar("pesan", stream=s, width=48)
    pb.start_creep(base=0.0, span=0.5)
    assert pb._creep_thread is None


def test_non_tty_finish_still_prints_final_line():
    """Non-TTY tetap dapat satu baris 100% agar user tahu pekerjaan tuntas."""
    s = FakePipe()
    pb = P.ProgressBar("pesan", stream=s, width=48)
    pb.set_progress(0.1)
    pb.finish()
    out = s.getvalue()
    # Blok awal (10%) + baris final (100%).
    assert " 10%" in out
    assert "100%" in out


def test_ascii_mode_uses_hash_characters(monkeypatch):
    """`GARWA_PROGRESS_ASCII=1` -> bar memakai '#' agar aman di terminal
    tanpa glyph blok Unicode."""
    monkeypatch.setenv("GARWA_PROGRESS_ASCII", "1")
    assert P._bar_chars() == ("#", "-")
    s = FakeTTY()
    pb = P.ProgressBar("", stream=s, width=20)
    pb.set_progress(1.0)
    line1 = s.getvalue().split("\n")[0]
    assert "#" in line1
    assert "█" not in line1
