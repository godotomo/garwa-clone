"""cli/vision/messages.py
Dipecah lebih lanjut dari cli/vision.py.
"""
import argparse
import base64
import copy
import difflib
import json
import mimetypes
import os
import re
import select
import shlex
import shutil
import sys
import time
import unicodedata
from collections import OrderedDict
from datetime import datetime
from urllib.parse import unquote, urlparse

try:

    import readline  # noqa: F401
except ImportError:
    readline = None

import requests

from ...tools import TOOLS
from .. import _state as state
from ..file_drop import _human_size
from .attachment_tags import _split_text_and_attachment_tags
from .image_encoding import _encode_image_for_vision



def _build_vision_content(text: str):
    """Ubah satu string pesan (yang mungkin berisi satu/lebih tag
    <file_attachment .../>) jadi:
      - string apa adanya kalau tidak ada gambar yang berhasil di-embed
        (tidak ada tag sama sekali, semua tag "dokumen", status
        "denied_by_user", atau gagal di-encode) -- supaya payload tidak
        berubah bentuk tanpa perlu untuk giliran yang tidak melibatkan
        vision.
      - list content block ala OpenAI (`[{"type": "text", ...},
        {"type": "image_url", ...}, ...]`) kalau minimal SATU gambar
        berhasil di-embed.

    Tag <file_attachment> aslinya SELALU dipertahankan apa adanya di teks
    (bukan dihapus/diganti) -- model tetap melihat metadata path/status
    persis seperti sebelumnya, blok image_url cuma DITAMBAHKAN di
    sampingnya. Ini menjaga kompatibilitas dengan instruksi system prompt
    yang sudah menjelaskan arti atribut "status" pada tag tsb.

    Gambar dengan status "denied_by_user" TIDAK PERNAH di-embed, sama
    sekali tidak peduli formatnya -- itu keputusan approval user yang
    wajib dihormati, bukan cuma soal teknis format didukung/tidak.
    """
    parts = _split_text_and_attachment_tags(text)
    if not any(kind == "tag" for kind, _ in parts):
        return text

    blocks = []
    buffer = []
    embedded_any = False

    def flush_text():
        joined = "".join(buffer)
        if joined:
            blocks.append({"type": "text", "text": joined})
        buffer.clear()

    for kind, val in parts:
        if kind == "text":
            buffer.append(val)
            continue

        m = val
        path, tag_kind, mime, _size_str, status = m.groups()

        buffer.append(m.group(0))

        if tag_kind != "gambar":
            continue
        if status == "denied_by_user":
            continue
        if status not in ("workdir", "approved_external"):

            continue

        data_url, err = _encode_image_for_vision(path, mime)
        if data_url is None:
            buffer.append(
                f'\n[CATATAN SISTEM: gambar "{path}" TIDAK dilampirkan sebagai '
                f"vision input -- {err} Anda hanya melihat metadata di atas "
                "untuk file ini.]\n"
            )
            continue

        flush_text()
        blocks.append({"type": "image_url", "image_url": {"url": data_url}})
        embedded_any = True

    flush_text()

    if not embedded_any:

        return "".join(b["text"] for b in blocks if b["type"] == "text")
    return blocks


def _prepare_messages_for_vision(messages: list) -> list:
    """Salin `messages` (list of {"role", "content", ...}) dengan setiap
    pesan yang mengandung tag <file_attachment kind="gambar" .../> yang
    disetujui & berformat didukung diubah jadi content multimodal berisi
    base64 data-URI, supaya model BENAR-BENAR menerima piksel gambarnya
    lewat endpoint /v1/chat/completions -- bukan cuma path & metadata teks
    seperti sebelumnya.

    Tidak memodifikasi `messages` in place dan TIDAK menyentuh database --
    ini murni transformasi pada payload yang mau dikirim ke server untuk
    request saat ini. Riwayat yang tersimpan di SQLite tetap ringan (teks
    biasa berisi tag), jadi ukuran DB tidak membengkak oleh base64.

    Fail-soft secara menyeluruh: exception apa pun di jalur encoding
    gambar (bug tak terduga, dsb) ditangkap per-pesan supaya SATU lampiran
    bermasalah tidak pernah menggagalkan seluruh giliran chat -- pesan itu
    jatuh kembali ke bentuk teks aslinya (perilaku lama: model cuma lihat
    metadata untuk pesan tsb saja, pesan lain tidak terpengaruh).
    """
    out = []
    for msg in messages:
        content = msg.get("content") if isinstance(msg, dict) else None
        if (
            not isinstance(msg, dict)
            or msg.get("role") != "user"
            or not isinstance(content, str)
            or "<file_attachment" not in content
        ):
            out.append(msg)
            continue
        try:
            new_content = _build_vision_content(content)
        except Exception as e:
            new_content = content
            if os.environ.get("GARWA_DEBUG_VISION"):
                sys.stderr.write(f"[VISION-ERROR] gagal memproses attachment: {e}\n")
        if new_content is content:
            out.append(msg)
        else:
            new_msg = dict(msg)
            new_msg["content"] = new_content
            out.append(new_msg)
    return out
