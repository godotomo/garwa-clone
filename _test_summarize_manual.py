#!/usr/bin/env python3
"""
Tes manual fitur summarize + instruksi aktif (garwa).

TIDAK menyentuh DB sesi asli: memakai DB sementara (tempfile).

Cara pakai:
    python3 _test_summarize_manual.py            # mode stub (tanpa server)
    python3 _test_summarize_manual.py --live     # panggil model sungguhan (butuh server LLM running)
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from garwa import context_manager as cm
from garwa import db as dbmod
from garwa import config


def _seed(db_path, session_id, n=40):
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        content = (
            f"pesan ke-{i}: saya perlu membaca file config dan mengubah "
            "beberapa nilai di dalamnya agar sesuai dengan instruksi "
            "selalu gunakan bahasa Indonesia dan jangan hapus file penting. "
            "kata kata kata kata kata kata kata kata kata kata kata kata "
            "kata kata kata kata kata kata kata kata kata kata kata kata "
        )
        dbmod.add_message(db_path, session_id, role, content)


def main():
    live = "--live" in sys.argv
    db_path = os.path.join(tempfile.mkdtemp(), "test.db")
    dbmod.init_db(db_path)
    session_id = dbmod.create_session(db_path, workdir=os.getcwd(), title="test-summarize")

    _seed(db_path, session_id, n=40)
    print(f"[i] DB sementara : {db_path}")
    print(f"[i] session_id   : {session_id}")
    print(f"[i] pesan        : {len(dbmod.get_all_messages(db_path, session_id))}")

    # Konfigurasi dari runtime (url/model/api_key).
    config.load_user_config()
    url = config.LLAMA_URL
    model = config.LLAMA_MODEL
    api_key = config.LLAMA_API_KEY
    print(f"[i] url  : {url}")
    print(f"[i] model: {model}")
    print(f"[i] mode : {'LIVE (model sungguhan)' if live else 'STUB (tanpa server)'}")

    if live:
        # Panggil model sungguhan via _summarize_text.
        result = cm.maybe_summarize(
            db_path, session_id, url, model,
            context_window_tokens=2000, api_key=api_key,
            system_prompt="Sistem coding agent.",
        )
    else:
        # Stub: tiru respons model yang mengembalikan dict JSON.
        def fake_summarize(url_, model_, text, api_key="", progress=None):
            print("\n----- CHUNK YANG DIKIRIM KE MODEL (300 char pertama) -----")
            print(text[:300])
            print("...\n------------------------------------------------------------")
            return {
                "narasi": (
                    "User sedang mengerjakan task edit file config. "
                    "Belum selesai, perlu lanjut."
                ),
                "instruksi_aktif": [
                    "selalu gunakan bahasa Indonesia",
                    "jangan hapus file penting",
                    "output summarize wajib JSON murni tanpa fence",
                ],
            }

        cm._summarize_text = fake_summarize
        result = cm.maybe_summarize(
            db_path, session_id, url, model,
            context_window_tokens=2000, api_key=api_key,
            system_prompt="Sistem coding agent.",
        )

    print("\n===== HASIL =====")
    print(f"maybe_summarize -> {result}")
    summary = dbmod.get_latest_summary(db_path, session_id)
    if summary:
        print(f"summary_text   : {summary['summary_text']!r}")
        print(f"upto_message_id: {summary['upto_message_id']}")
        print(f"active_instructions ({len(summary['active_instructions'])}):")
        for s in summary["active_instructions"]:
            print(f"  - {s}")
    else:
        print("TIDAK ADA SUMMARY (returned False)")

    # Verifikasi injeksi blok instruksi aktif ke konteks.
    print("\n===== BUILD CONTEXT (cek blok <instruksi_aktif>) =====")
    msgs = cm.build_context_messages(db_path, session_id, "SYS")
    print(f"jumlah messages: {len(msgs)}")
    for m in msgs[:3]:
        role = m["role"]
        content = m["content"]
        if role == "system":
            print(f"[system] {content[:80]}...")
        else:
            if "<instruksi_aktif>" in content:
                print(f"[{role}] <-- MENGANDUNG blok instruksi_aktif")
                # cetak hanya baris instruksi
                for line in content.splitlines():
                    if line.startswith("- "):
                        print("        " + line)
            else:
                print(f"[{role}] {content[:80]}...")

    print("\n[s] selesai. DB sementara tidak dihapus: " + db_path)


if __name__ == "__main__":
    main()
