"""
test_system_warning.py
Uji pemrosesan dan penyuntikan tag `<systemwarning>...</systemwarning>`.

Fokus:
- Ekstraksi konten dari tag (extract_system_warnings).
- Pembersihan tag dari teks (strip_system_warnings).
- Deteksi keberadaan tag (has_system_warning).
- Pembangunan blok warning (build_system_warning_block).
- Penyuntikan ke DB sebagai pesan kind="system_warning" yang di-pin
  (inject_system_warning) dan pemastian ia ikut dikirim utuh oleh
  build_context_messages().
"""

import pytest

from garwa import db as dbmod
from garwa.cli.system_warning import (
    build_system_warning_block,
    extract_system_warnings,
    has_system_warning,
    inject_system_warning,
    strip_system_warnings,
)
from garwa.context_manager import build_context_messages


# ---------------------------------------------------------------- ekstraksi

def test_extract_system_warnings_multi():
    text = (
        "<systemwarning>Parser DEX manual deterministik.</systemwarning>\n"
        "Baik, jalankan dump string methods.\n"
        "<systemwarning>Catatan: bug potensial pada insnlen.</systemwarning>"
    )
    warnings = extract_system_warnings(text)
    assert warnings == [
        "Parser DEX manual deterministik.",
        "Catatan: bug potensial pada insnlen.",
    ]


def test_extract_system_warnings_none():
    assert extract_system_warnings("tidak ada tag di sini") == []
    assert extract_system_warnings("") == []
    assert extract_system_warnings(None) == []


def test_extract_system_warnings_multiline_content():
    text = "<systemwarning>\nbaris satu\nbaris dua\n</systemwarning>"
    assert extract_system_warnings(text) == ["baris satu\nbaris dua"]


def test_extract_system_warnings_case_insensitive():
    text = "<SYSTEMWARNING>konten</SYSTEMWARNING>"
    assert extract_system_warnings(text) == ["konten"]


# ---------------------------------------------------------------- strip

def test_strip_system_warnings_removes_blocks():
    text = (
        "<systemwarning>instruksi rahasia</systemwarning>"
        "teks yang terlihat"
    )
    assert strip_system_warnings(text) == "teks yang terlihat"


def test_strip_system_warnings_keeps_text_without_tags():
    assert strip_system_warnings("hanya teks biasa") == "hanya teks biasa"
    assert strip_system_warnings("") == ""
    assert strip_system_warnings(None) is None


def test_strip_system_warnings_multiple():
    # Tag yang dihapus tidak menyisakan spasi, jadi teks di kedua sisi
    # menyambung langsung ("satu" + "dua" = "satudua"). Ini perilaku yang
    # diharapkan: strip hanya menghapus blok tag + kontennya.
    text = (
        "<systemwarning>a</systemwarning>satu"
        "<systemwarning>b</systemwarning>dua"
    )
    assert strip_system_warnings(text) == "satudua"


# ---------------------------------------------------------------- deteksi

def test_has_system_warning():
    assert has_system_warning("<systemwarning>x</systemwarning>") is True
    assert has_system_warning("tidak ada") is False
    assert has_system_warning("") is False
    assert has_system_warning(None) is False


# ---------------------------------------------------------------- build block

def test_build_block_from_list():
    block = build_system_warning_block(["instruksi A", "instruksi B"])
    assert block.count("<systemwarning>") == 2
    assert "instruksi A" in block
    assert "instruksi B" in block


def test_build_block_from_string():
    block = build_system_warning_block("satu warning")
    assert block.count("<systemwarning>") == 1
    assert "satu warning" in block


def test_build_block_empty():
    assert build_system_warning_block(None) == ""
    assert build_system_warning_block([]) == ""
    assert build_system_warning_block("   ") == ""


# ---------------------------------------------------------------- inject

def test_inject_system_warning_saves_pinned(db_path, session_id):
    mid = inject_system_warning(db_path, session_id, "instruksi sistem aktif")
    rows = dbmod.get_all_messages(db_path, session_id)
    assert len(rows) == 1
    r = rows[0]
    assert r["kind"] == "system_warning"
    assert r["pinned"] == 1
    assert "<systemwarning>" in r["content"]
    assert "instruksi sistem aktif" in r["content"]


def test_inject_system_warning_included_in_context(db_path, session_id):
    inject_system_warning(db_path, session_id, "instruksi sistem aktif")
    dbmod.add_message(db_path, session_id, "user", "lanjutkan task", kind="chat")

    msgs = build_context_messages(db_path, session_id, "system prompt")
    # system + system_warning + user chat
    assert len(msgs) == 3
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "<systemwarning>" in msgs[1]["content"]
    assert "instruksi sistem aktif" in msgs[1]["content"]
    assert msgs[2]["content"] == "lanjutkan task"


def test_inject_system_warning_requires_content(db_path, session_id):
    with pytest.raises(ValueError):
        inject_system_warning(db_path, session_id, None)
    with pytest.raises(ValueError):
        inject_system_warning(db_path, session_id, "   ")