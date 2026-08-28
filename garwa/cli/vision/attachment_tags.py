"""cli/vision/attachment_tags.py
Dipecah lebih lanjut dari cli/vision.py.
"""

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from .. import _state as state



def _split_text_and_attachment_tags(text: str):
    """Pecah `text` jadi list of ('text', str) / ('tag', re.Match) berurutan
    berdasarkan semua kemunculan <file_attachment .../>, supaya potongan teks
    di sekitar tag tetap utuh & urut saat direkonstruksi jadi content blocks.
    """
    parts = []
    last_end = 0
    for m in state._FILE_ATTACHMENT_TAG_RE.finditer(text):
        if m.start() > last_end:
            parts.append(("text", text[last_end:m.start()]))
        parts.append(("tag", m))
        last_end = m.end()
    if last_end < len(text):
        parts.append(("text", text[last_end:]))
    return parts


def _inject_attachment_instructions(messages: list) -> list:
    """Salin `messages` dengan menambahkan ATTACHMENT_INSTRUCTIONS ke pesan
    user yang content-nya (string) mengandung tag attachment
    (<file_attachment atau <pasted_attachment). Pesan lain dibiarkan apa
    adanya. Tidak memodifikasi `messages` in place dan TIDAK menyentuh
    database -- murni transformasi payload request, jadi instruksi tidak
    menumpuk di history dan tidak membebani giliran tanpa lampiran.

    Dipanggil SEBELUM _prepare_messages_for_vision(), sehingga instruksi
    ikut menjadi bagian teks yang diproses vision (untuk gambar yang
    di-embed jadi list content block).
    """
    out = []
    for msg in messages:
        content = msg.get("content") if isinstance(msg, dict) else None
        if (
            isinstance(msg, dict)
            and msg.get("role") == "user"
            and isinstance(content, str)
            and ("<file_attachment" in content or "<pasted_attachment" in content)
        ):
            new_msg = dict(msg)
            new_msg["content"] = state.ATTACHMENT_INSTRUCTIONS + "\n\n" + content
            out.append(new_msg)
        else:
            out.append(msg)
    return out
