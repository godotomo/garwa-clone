"""
test_context_manager.py
Uji manajemen context window (garwa/context_manager.py).

Fokus:
- build_context_messages: urutan system/summary/tail, filter role.
- _pairing_safe_split: tidak pernah memisah pasangan tool_call/tool_result.
- _tools_payload_tokens: estimasi token dari payload tools.
- maybe_summarize: threshold, retry, penyimpanan summary (dengan mock request).
- prepare_context_messages: hard budget, ValueError pada window kecil.
"""

import json

import pytest
import requests

from garwa import context_manager as cm
from garwa import db as dbmod


# ---------------------------------------------------------------- helpers

def _msg(db_path, sid, role, content, kind="chat"):
    return dbmod.add_message(db_path, sid, role, content, kind)


# ------------------------------------------------- build_context_messages

def test_build_context_messages_plain(db_path, session_id):
    dbmod.add_message(db_path, session_id, "user", "halo")
    dbmod.add_message(db_path, session_id, "assistant", "hai")
    msgs = cm.build_context_messages(db_path, session_id, "SYS")
    assert msgs[0] == {"role": "system", "content": "SYS"}
    assert msgs[1:] == [
        {"role": "user", "content": "halo"},
        {"role": "assistant", "content": "hai"},
    ]


def test_build_context_messages_filters_non_chat_roles(db_path, session_id):
    # Baris dengan role selain user/assistant harus diabaikan.
    dbmod.add_message(db_path, session_id, "user", "halo")
    dbmod.add_message(db_path, session_id, "tool_result", "hasil", kind="tool_result")
    msgs = cm.build_context_messages(db_path, session_id, "SYS")
    contents = [m["content"] for m in msgs]
    assert "hasil" not in contents


def test_build_context_messages_includes_summary(db_path, session_id):
    dbmod.add_message(db_path, session_id, "user", "pesan lama")
    dbmod.add_message(db_path, session_id, "assistant", "respon lama")
    dbmod.save_summary(db_path, session_id, 2, "RINGKASAN")
    dbmod.add_message(db_path, session_id, "user", "pesan baru")
    msgs = cm.build_context_messages(db_path, session_id, "SYS")
    # system + ringkasan(user) + ack(assistant) + pesan baru
    assert msgs[0]["role"] == "system"
    assert "RINGKASAN" in msgs[1]["content"]
    assert msgs[2]["role"] == "assistant"
    assert msgs[3] == {"role": "user", "content": "pesan baru"}
    # pesan lama tidak boleh ikut karena sudah tercakup summary
    assert "pesan lama" not in [m["content"] for m in msgs]


# ------------------------------------------------- _pairing_safe_split

def test_pairing_safe_split_no_tool_result():
    rows = [{"kind": "chat"}, {"kind": "chat"}, {"kind": "chat"}]
    assert cm._pairing_safe_split(rows, 2) == 2


def test_pairing_safe_split_avoids_splitting_tool_pair():
    # rows[2] adalah tool_result -> split harus digeser mundur.
    rows = [
        {"kind": "chat"},
        {"kind": "chat"},
        {"kind": "tool_result"},
        {"kind": "chat"},
    ]
    assert cm._pairing_safe_split(rows, 2) == 1


def test_pairing_safe_split_at_edges():
    rows = [{"kind": "tool_result"}, {"kind": "chat"}]
    # split_at=1 -> rows[1] chat, aman
    assert cm._pairing_safe_split(rows, 1) == 1
    # split_at di posisi 0 tidak boleh berubah (loop butuh 0 < split_at)
    assert cm._pairing_safe_split(rows, 0) == 0


# ------------------------------------------------- _tools_payload_tokens

def test_tools_payload_tokens_empty():
    assert cm._tools_payload_tokens(None) == 0
    assert cm._tools_payload_tokens({}) == 0
    assert cm._tools_payload_tokens([]) == 0


def test_tools_payload_tokens_counts_json():
    payload = {"tools": [{"type": "function", "function": {"name": "x"}}]}
    n = cm._tools_payload_tokens(payload)
    assert n > 0
    # Harus konsisten dengan count_tokens dari representasi JSON.
    expected = cm.token_utils.count_tokens(json.dumps(payload, ensure_ascii=False))
    assert n == expected


# ------------------------------------------------- maybe_summarize

def test_maybe_summarize_noop_when_under_threshold(db_path, session_id, monkeypatch):
    dbmod.add_message(db_path, session_id, "user", "pendek")
    called = []

    def fake_summarize(url, model, text, api_key="", progress=None):
        called.append(text)
        return "ringkasan"

    monkeypatch.setattr(cm, "_summarize_text", fake_summarize)
    result = cm.maybe_summarize(
        db_path, session_id, "http://x", "model", context_window_tokens=100000
    )
    assert result is False
    assert called == []  # tidak boleh memanggil server


def test_maybe_summarize_skips_when_history_short(db_path, session_id, monkeypatch):
    # Banyak pesan tapi pendek -> threshold token tidak terpenuhi.
    for i in range(30):
        dbmod.add_message(db_path, session_id, "user", "x")
    called = []

    def fake_summarize(url, model, text, api_key="", progress=None):
        called.append(text)
        return "ringkasan"

    monkeypatch.setattr(cm, "_summarize_text", fake_summarize)
    result = cm.maybe_summarize(
        db_path, session_id, "http://x", "model", context_window_tokens=100000
    )
    assert result is False
    assert called == []


def test_maybe_summarize_triggers_and_saves(db_path, session_id, monkeypatch):
    # Banyak pesan panjang + window kecil -> harus memicu ringkasan.
    for i in range(30):
        dbmod.add_message(db_path, session_id, "user", "kata " * 50)
    called = []

    def fake_summarize(url, model, text, api_key="", progress=None):
        called.append(text)
        return {"narasi": "RINGKASAN BARU", "instruksi_aktif": []}

    monkeypatch.setattr(cm, "_summarize_text", fake_summarize)
    result = cm.maybe_summarize(
        db_path, session_id, "http://x", "model", context_window_tokens=2000
    )
    assert result is True
    assert len(called) == 1
    summary = dbmod.get_latest_summary(db_path, session_id)
    assert summary is not None
    assert summary["summary_text"] == "RINGKASAN BARU"
    # upto_message_id harus menunjuk pesan terakhir yang diringkas.
    assert summary["upto_message_id"] >= 1


def test_maybe_summarize_handles_failure_gracefully(db_path, session_id, monkeypatch):
    for i in range(30):
        dbmod.add_message(db_path, session_id, "user", "kata " * 50)

    def boom(url, model, text, api_key="", progress=None):
        raise requests.Timeout("server timeout")

    monkeypatch.setattr(cm, "_summarize_text", boom)
    result = cm.maybe_summarize(
        db_path, session_id, "http://x", "model", context_window_tokens=2000
    )
    assert result is False
    assert dbmod.get_latest_summary(db_path, session_id) is None


def test_maybe_summarize_saves_active_instructions(db_path, session_id, monkeypatch):
    for i in range(30):
        dbmod.add_message(db_path, session_id, "user", "kata " * 50)

    def fake_summarize(url, model, text, api_key="", progress=None):
        return {
            "narasi": "RINGKASAN",
            "instruksi_aktif": ["Selalu gunakan bahasa Indonesia", "Jangan hapus file config"],
        }

    monkeypatch.setattr(cm, "_summarize_text", fake_summarize)
    result = cm.maybe_summarize(
        db_path, session_id, "http://x", "model", context_window_tokens=2000
    )
    assert result is True
    summary = dbmod.get_latest_summary(db_path, session_id)
    assert summary["summary_text"] == "RINGKASAN"
    assert summary["active_instructions"] == [
        "Selalu gunakan bahasa Indonesia", "Jangan hapus file config",
    ]


def test_maybe_summarize_merges_prior_active_instructions(db_path, session_id, monkeypatch):
    # Summary pertama sudah menyimpan instruksi aktif.
    dbmod.save_summary(
        db_path, session_id, 1, "lama",
        active_instructions=["instruksi lama"],
    )
    for i in range(30):
        dbmod.add_message(db_path, session_id, "user", "kata " * 50)

    def fake_summarize(url, model, text, api_key="", progress=None):
        return {"narasi": "RINGKASAN BARU", "instruksi_aktif": ["instruksi baru"]}

    monkeypatch.setattr(cm, "_summarize_text", fake_summarize)
    result = cm.maybe_summarize(
        db_path, session_id, "http://x", "model", context_window_tokens=2000
    )
    assert result is True
    summary = dbmod.get_latest_summary(db_path, session_id)
    # Instruksi lama harus tetap ada (digabung, dedup).
    assert set(summary["active_instructions"]) == {"instruksi lama", "instruksi baru"}


def test_maybe_summarize_skips_when_narasi_empty(db_path, session_id, monkeypatch):
    for i in range(30):
        dbmod.add_message(db_path, session_id, "user", "kata " * 50)

    def fake_summarize(url, model, text, api_key="", progress=None):
        return {"narasi": "   ", "instruksi_aktif": ["x"]}

    monkeypatch.setattr(cm, "_summarize_text", fake_summarize)
    result = cm.maybe_summarize(
        db_path, session_id, "http://x", "model", context_window_tokens=2000
    )
    assert result is False
    assert dbmod.get_latest_summary(db_path, session_id) is None


# ------------------------------------------------- _parse_summary_output

def test_parse_summary_output_plain_json():
    out = cm._parse_summary_output(
        '{"narasi": "ringkasan", "instruksi_aktif": ["a", "b"]}'
    )
    assert out == {"narasi": "ringkasan", "instruksi_aktif": ["a", "b"]}


def test_parse_summary_output_fenced_json():
    raw = '```json\n{"narasi": "ringkasan", "instruksi_aktif": ["a"]}\n```'
    out = cm._parse_summary_output(raw)
    assert out["narasi"] == "ringkasan"
    assert out["instruksi_aktif"] == ["a"]


def test_parse_summary_output_fallback_to_plain_text():
    out = cm._parse_summary_output("ringkasan biasa tanpa json")
    assert out["narasi"] == "ringkasan biasa tanpa json"
    assert out["instruksi_aktif"] == []


def test_parse_summary_output_handles_non_list_instructions():
    raw = '{"narasi": "ringkasan", "instruksi_aktif": "bukan list"}'
    out = cm._parse_summary_output(raw)
    assert out["narasi"] == "ringkasan"
    assert out["instruksi_aktif"] == []


def test_parse_summary_output_empty():
    assert cm._parse_summary_output("") == {"narasi": "", "instruksi_aktif": []}


# ------------------------------------------------- build_context_messages: instruksi aktif

def test_build_context_messages_injects_active_instructions(db_path, session_id):
    dbmod.add_message(db_path, session_id, "user", "pesan lama")
    dbmod.save_summary(
        db_path, session_id, 1, "RINGKASAN",
        active_instructions=["Aturan: pakai JSON murni", "Jangan hapus file"],
    )
    dbmod.add_message(db_path, session_id, "user", "pesan baru")
    msgs = cm.build_context_messages(db_path, session_id, "SYS")
    summary_content = msgs[1]["content"]
    assert "<instruksi_aktif>" in summary_content
    assert "- Aturan: pakai JSON murni" in summary_content
    assert "- Jangan hapus file" in summary_content
    assert msgs[1]["role"] == "user"


def test_build_context_messages_no_instruksi_block_when_empty(db_path, session_id):
    dbmod.add_message(db_path, session_id, "user", "pesan lama")
    dbmod.save_summary(db_path, session_id, 1, "RINGKASAN")
    dbmod.add_message(db_path, session_id, "user", "pesan baru")
    msgs = cm.build_context_messages(db_path, session_id, "SYS")
    assert "<instruksi_aktif>" not in msgs[1]["content"]


# ------------------------------------------------- prepare_context_messages

def test_prepare_context_messages_rejects_small_window(db_path, session_id):
    with pytest.raises(ValueError):
        cm.prepare_context_messages(
            db_path, session_id, "SYS", "http://x", "model",
            context_window_tokens=100,
        )


def test_prepare_context_messages_returns_messages(db_path, session_id):
    dbmod.add_message(db_path, session_id, "user", "halo")
    msgs = cm.prepare_context_messages(
        db_path, session_id, "SYS", "http://x", "model", context_window_tokens=100000
    )
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "SYS"


def test_prepare_context_messages_summarizes_instead_of_trim(db_path, session_id, monkeypatch):
    # Banyak pesan panjang + window kecil -> harus DIRINGKAS (summarize),
    # BUKAN dipotong/trim pesan mentah. Semua pesan lama harus lewat jalur
    # summarize supaya tidak ada konteks yang hilang diam-diam.
    #
    # Keputusan desain (per komitmen): meskipun summarize sudah berhasil,
    # kalau total masih melebihi hard budget, pesan mentah TIDAK BOLEH
    # di-trim/dipotong (memotong = menghilangkan konteks). Pesan dikirim
    # apa adanya; ContextExceededError ditangani agent_loop dengan retry
    # budget lebih ketat.
    for i in range(50):
        dbmod.add_message(db_path, session_id, "user", "kata " * 100)

    def fake_summarize(url, model, text, api_key="", progress=None):
        return {"narasi": "RINGKASAN", "instruksi_aktif": []}

    monkeypatch.setattr(cm, "_summarize_text", fake_summarize)
    msgs = cm.prepare_context_messages(
        db_path, session_id, "SYS", "http://x", "model", context_window_tokens=3000
    )
    # system message selalu dipertahankan.
    assert msgs[0]["role"] == "system"
    # Harus ada ringkasan tersimpan (bukti pesan di-summarize, bukan di-trim).
    summary = dbmod.get_latest_summary(db_path, session_id)
    assert summary is not None
    assert summary["summary_text"] == "RINGKASAN"
    # TIDAK ada trim tambahan setelah summarize: meskipun total melebihi hard
    # budget, pesan yang dikembalikan harus IDENTIK dengan build_context_messages
    # (system + summary + ack + keep_tail pesan mentah). Konteks tidak boleh
    # hilang diam-diam; ContextExceededError ditangani agent_loop dengan retry.
    expected = cm.build_context_messages(db_path, session_id, "SYS")
    assert msgs == expected
    assert len(msgs) == 3 + cm.KEEP_TAIL_MESSAGES  # system+summary+ack+keep_tail


def test_prepare_context_messages_no_trim_when_summarize_fails(db_path, session_id, monkeypatch):
    # Kalau server ringkasan GAGAL (tidak bisa dijangkau), context TIDAK
    # boleh di-trim diam-diam: pesan mentah harus tetap dikirim apa adanya
    # (biarkan server/agent_loop menangani ContextExceededError), bukan
    # dibuang.
    for i in range(50):
        dbmod.add_message(db_path, session_id, "user", "kata " * 100)

    def boom(url, model, text, api_key="", progress=None):
        raise requests.Timeout("server ringkasan tidak terjangkau")

    monkeypatch.setattr(cm, "_summarize_text", boom)
    msgs = cm.prepare_context_messages(
        db_path, session_id, "SYS", "http://x", "model", context_window_tokens=3000
    )
    # Semua pesan mentah harus tetap ada (tidak ada yang di-trim).
    contents = [m["content"] for m in msgs]
    assert "kata kata kata" in contents[1]
    assert len(msgs) == 51  # system + 50 pesan mentah, tidak ada yang dibuang
    # Tidak boleh ada summary tersimpan (summarize gagal).
    assert dbmod.get_latest_summary(db_path, session_id) is None


# ---------------------------------------------------------------- project notes
def test_trim_note_middle_short_value_unchanged():
    v = "teks pendek"
    assert cm._trim_note_middle(v, 100) == v


def test_trim_note_middle_long_value_keeps_head_and_tail():
    v = "A" * 50 + "MIDDLE" + "B" * 50
    out = cm._trim_note_middle(v, 60)
    assert len(out) < len(v)
    # head dan tail dipertahankan, tengah dipangkas
    assert out.startswith("A" * 30)
    assert out.endswith("B" * 30)
    assert "…sisa dipangkas…" in out


# ------------------------------------------------- fallback extractive (context-aware)
def test_extractive_summarize_short_value_unchanged():
    v = "teks pendek saja"
    assert cm._extractive_summarize_note(v, 100) == v


def test_extractive_summarize_keeps_important_markers():
    # Kalimat bertanda PENTING/CATATAN harus dipertahankan walau di tengah.
    v = (
        "Deskripsi awal proyek yang panjang dan tidak terlalu penting. "
        "CATATAN: ini keputusan desain yang wajib dipertahankan. "
        "Detail teknis kecil yang bisa dibuang untuk menghemat ruang. "
        "PENTING: verifikasi konteks tetap utuh. "
        "Kesimpulan akhir."
    )
    out = cm._extractive_summarize_note(v, 200)
    assert len(out) <= 200 + 20  # toleransi
    assert "keputusan desain" in out
    assert "verifikasi konteks" in out


def test_extractive_summarize_preserves_original_order():
    v = (
        "Kalimat pertama yang penting sekali. "
        "Kalimat kedua yang juga penting. "
        "Kalimat ketiga yang kurang penting. "
        "Kalimat keempat yang cukup penting. "
    )
    out = cm._extractive_summarize_note(v, 100)
    # Kalimat yang terpilih harus tetap dalam urutan asli teks.
    positions = [out.find(s) for s in ("Kalimat pertama", "Kalimat kedua", "Kalimat keempat")]
    positions = [p for p in positions if p != -1]
    assert positions == sorted(positions)


def test_extractive_summarize_falls_back_to_trim_on_no_sentences():
    # Teks tanpa kalimat yang bisa dipecah (mis. satu kata panjang) -> trim.
    v = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    out = cm._extractive_summarize_note(v, 40)
    assert len(out) < len(v)


def test_project_notes_section_injects_all_keys(db_path, session_id):
    for i in range(5):
        dbmod.set_note(db_path, "/tmp/test-workdir", f"key{i}", "x" * 500)
    section = cm._project_notes_section(db_path, session_id)
    assert "CATATAN PROYEK PERSISTEN" in section
    for i in range(5):
        assert f"key{i}" in section


def test_project_notes_section_respects_total_budget(db_path, session_id):
    # Banyak catatan panjang -> total blok harus <= PROJECT_NOTES_MAX_TOTAL_CHARS
    for i in range(30):
        dbmod.set_note(db_path, "/tmp/test-workdir", f"k{i}", "z" * 2000)
    section = cm._project_notes_section(db_path, session_id)
    assert len(section) <= cm.PROJECT_NOTES_MAX_TOTAL_CHARS + 5  # toleransi kecil
    # semua key tetap ada
    for i in range(30):
        assert f"k{i}" in section


def test_project_notes_section_empty_when_no_session(db_path):
    assert cm._project_notes_section(db_path, "nonexistent-session") == ""


# ------------------------------------------------------ note summarization via LLM
def test_summarize_note_text_returns_content(db_path, monkeypatch):
    """_summarize_note_text memakai LLM dan mengembalikan teks ringkasan."""
    def fake_post(url, json=None, headers=None, timeout=None):
        class R:
            def raise_for_status(self):
                pass
            def json(self):
                return {"choices": [{"message": {"content": "Ringkasan padat."}}]}
        return R()
    # requests di-lazy-load (cm._get_requests). Panggil dulu agar _requests
    # ter-set, lalu patch atribut post-nya.
    monkeypatch.setattr(cm._get_requests(), "post", fake_post)
    out = cm._summarize_note_text("http://x", "m", "isi catatan panjang")
    assert out == "Ringkasan padat."


def test_summarize_note_text_returns_empty_on_error(db_path, monkeypatch):
    def boom(url, json=None, headers=None, timeout=None):
        raise cm._get_requests().Timeout("gagal")
    monkeypatch.setattr(cm._get_requests(), "post", boom)
    assert cm._summarize_note_text("http://x", "m", "isi") == ""


def test_ensure_note_summaries_fills_summary_for_long_notes(db_path, session_id, monkeypatch):
    """Catatan panjang diringkas via LLM dan disimpan ke kolom summary."""
    dbmod.set_note(db_path, "/tmp/test-workdir", "long1", "x" * 1000)
    dbmod.set_note(db_path, "/tmp/test-workdir", "short", "pendek")
    def fake_summarize(url, model, note_text, api_key=""):
        return f"ringkasan-{len(note_text)}"
    monkeypatch.setattr(cm, "_summarize_note_text", fake_summarize)
    cm._ensure_note_summaries(db_path, session_id, "http://x", "m", api_key="")
    notes = {n["key"]: n for n in dbmod.get_notes(db_path, "/tmp/test-workdir")}
    # catatan panjang dapat summary; catatan pendek tidak
    assert notes["long1"]["summary"] == "ringkasan-1000"
    assert notes["short"]["summary"] in (None, "")


def test_ensure_note_summaries_skips_when_already_summarized(db_path, session_id, monkeypatch):
    dbmod.set_note(db_path, "/tmp/test-workdir", "k", "x" * 1000)
    dbmod.set_note_summary(db_path, "/tmp/test-workdir", "k", "sudah ada")
    calls = []
    def fake_summarize(url, model, note_text, api_key=""):
        calls.append(note_text)
        return "baru"
    monkeypatch.setattr(cm, "_summarize_note_text", fake_summarize)
    cm._ensure_note_summaries(db_path, session_id, "http://x", "m", api_key="")
    assert calls == []  # tidak dipanggil ulang
    notes = {n["key"]: n for n in dbmod.get_notes(db_path, "/tmp/test-workdir")}
    assert notes["k"]["summary"] == "sudah ada"


def test_project_notes_section_uses_summary_when_available(db_path, session_id):
    dbmod.set_note(db_path, "/tmp/test-workdir", "k", "x" * 2000)
    dbmod.set_note_summary(db_path, "/tmp/test-workdir", "k", "RINGKASAN LLM")
    section = cm._project_notes_section(db_path, session_id)
    assert "RINGKASAN LLM" in section
    # ringkasan LLM dipakai, bukan trim (tidak ada penanda pemangkasan)
    assert "…sisa dipangkas…" not in section


# ------------------------------------- berbagi state baca per-giliran (P4)
#
# Satu giliran dulu membaca state yang PERSIS SAMA dua kali: sekali di
# maybe_summarize(), sekali di build_context_messages(). Dengan `state`, giliran
# yang tidak meringkas apa pun hanya membaca DB sekali. State HARUS diabaikan
# kalau ditandai stale (summary baru ditulis) supaya tidak memakai data basi.

def test_build_context_messages_uses_passed_state(db_path, session_id):
    dbmod.add_message(db_path, session_id, "user", "dari state")
    state = {
        "notes_block": "\n<notes>N</notes>",
        "summary": None,
        "rows": [{"id": 1, "role": "user", "content": "dari state"}],
        "pinned": [],
        "stale": False,
    }
    msgs = cm.build_context_messages(db_path, session_id, "SYS", state=state)
    assert msgs[0]["content"].startswith("SYS")
    assert "<notes>" in msgs[0]["content"]
    assert msgs[1] == {"role": "user", "content": "dari state"}


def test_build_context_messages_ignores_stale_state(db_path, session_id):
    dbmod.add_message(db_path, session_id, "user", "dari DB")
    stale = {
        "notes_block": "\n<notes>BASIS</notes>",
        "summary": None,
        "rows": [{"id": 1, "role": "user", "content": "dari state basi"}],
        "pinned": [],
        "stale": True,
    }
    msgs = cm.build_context_messages(db_path, session_id, "SYS", state=stale)
    # state basi diabaikan: isi diambil ulang dari DB, tanpa notes basi.
    assert msgs[1] == {"role": "user", "content": "dari DB"}
    assert "<notes>" not in msgs[0]["content"]


def test_prepare_context_messages_reuses_state_and_closes_scope(db_path, session_id, monkeypatch):
    """Dalam satu giliran, build_context_messages() TIDAK membuka koneksi DB
    sendiri: ia memakai state baca yang sudah dikumpulkan maybe_summarize().

    Sebelum P4 satu giliran membuka 4 koneksi (2 untuk pembacaan catatan di
    _ensure_note_summaries, 1 untuk maybe_summarize, 1 lagi untuk
    build_context_messages). Setelah P4 tinggal 3: build memakai state. Dua
    koneksi pertama (jalur ringkas catatan) SENGAJA tidak digabung ke scope
    yang sama karena jalur itu bisa memanggil LLM -- koneksi tidak boleh
    ditahan selama panggilan jaringan (lihat catatan di maybe_summarize).
    """
    dbmod.add_message(db_path, session_id, "user", "halo")

    opens = []
    real = dbmod._open_conn

    def counting(db_path_, *a, **kw):
        opens.append(db_path_)
        return real(db_path_, *a, **kw)

    monkeypatch.setattr(dbmod, "_open_conn", counting)

    real_build = cm.build_context_messages
    builds = []

    def spy_build(*args, **kwargs):
        before = len(opens)
        out = real_build(*args, **kwargs)
        builds.append(len(opens) - before)
        return out

    monkeypatch.setattr(cm, "build_context_messages", spy_build)
    msgs = cm.prepare_context_messages(
        db_path, session_id, "SYS", "http://x", "model", context_window_tokens=100000
    )
    assert msgs[0]["role"] == "system"
    assert len(builds) == 1, "build_context_messages harus dipanggil tepat sekali"
    # inti optimasi P4: build tidak menambah koneksi sama sekali
    assert builds[0] == 0
    assert len(opens) <= 3


def test_prepare_context_messages_invalidates_state_after_summary(db_path, session_id, monkeypatch):
    """Kalau maybe_summarize menulis summary baru, state ditandai stale sehingga
    build_context_messages membaca ulang dari DB (ringkasan harus yang baru,
    rows harus pesan setelah upto_id -- bukan data basi)."""
    for i in range(50):
        dbmod.add_message(db_path, session_id, "user", "kata " * 100)

    seen = {}

    def fake_summarize(url, model, text, api_key="", progress=None):
        return {"narasi": "RINGKASAN-BARU", "instruksi_aktif": []}

    monkeypatch.setattr(cm, "_summarize_text", fake_summarize)

    real_build = cm.build_context_messages

    def spy_build(*args, **kwargs):
        state = kwargs.get("state")
        seen["state"] = dict(state) if state else None
        return real_build(*args, **kwargs)

    monkeypatch.setattr(cm, "build_context_messages", spy_build)
    msgs = cm.prepare_context_messages(
        db_path, session_id, "SYS", "http://x", "model", context_window_tokens=3000
    )
    # summary tersimpan -> state yang diteruskan harus sudah stale
    assert dbmod.get_latest_summary(db_path, session_id)["summary_text"] == "RINGKASAN-BARU"
    assert seen["state"]["stale"] is True
    # dan hasil build memakai ringkasan BARU (bukan state basi sebelum summary)
    assert "RINGKASAN-BARU" in msgs[1]["content"]


def test_no_connection_held_during_summarize_llm_call(db_path, session_id, monkeypatch):
    """Tidak boleh ada koneksi DB yang ditahan selama panggilan LLM.

    SQLite mengunci penulisan pada level database; menahan koneksi (apalagi
    transaksi tulis) selama panggilan jaringan bisa memblokir proses lain
    (mis. gateway Telegram, sub-agent paralel) sampai detik-detik timeout.
    Jadi scope baca di maybe_summarize() harus SUDAH ditutup saat
    _summarize_text dipanggil.
    """
    for _ in range(60):
        dbmod.add_message(db_path, session_id, "user", "kata " * 80)

    held = {}

    def fake(url, model, text, api_key="", progress=None):
        held["n"] = len(dbmod._scope_map())
        return {"narasi": "RINGKASAN", "instruksi_aktif": []}

    monkeypatch.setattr(cm, "_summarize_text", fake)
    cm.prepare_context_messages(
        db_path, session_id, "SYS", "http://x", "model", context_window_tokens=4000
    )
    assert held["n"] == 0
    assert dbmod.get_latest_summary(db_path, session_id) is not None
