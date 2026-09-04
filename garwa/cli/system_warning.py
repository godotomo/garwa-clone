"""cli/system_warning.py
Utilitas untuk memproses dan menyuntikkan tag `<systemwarning>...</systemwarning>`
ke dalam alur percakapan agent.

Konsep:
- `systemwarning` adalah mekanisme prompt-injection prioritas tinggi. Sistem
  menyuntikkan arahan/konteks/peringatan ke dalam alur percakapan sebagai
  pesan `user` dengan `kind="system_warning"`, dibungkus tag
  `<systemwarning>...</systemwarning>` supaya model mengenalinya sebagai
  instruksi sistem yang WAJIB dipatuhi (bukan pertanyaan user biasa).

- Tag ini TIDAK boleh bocor ke output yang ditampilkan ke user terminal.
  Karena itu `strip_system_warnings()` dipakai untuk membersihkan teks
  sebelum dicetak/dikembalikan sebagai jawaban terlihat.

- Karena `system_warning` adalah instruksi aktif yang masih berlaku, pesan
  dengan `kind="system_warning"` dipertahankan utuh oleh context_manager
  (tidak ikut dibuang saat trimming hard-budget) selama masih dalam window.
"""

import re

# Tag pembuka/penutup systemwarning. Dibuat case-insensitive dan toleran
# terhadap spasi/whitespace di dalam tag (mis. `<systemwarning >`).
_OPEN_RE = re.compile(r"<\s*systemwarning\s*>", re.IGNORECASE)
_CLOSE_RE = re.compile(r"<\s*/\s*systemwarning\s*>", re.IGNORECASE)

# Pola lengkap satu blok: <systemwarning>...</systemwarning> (non-greedy,
# DOTALL supaya bisa lintas baris).
_BLOCK_RE = re.compile(
    r"<\s*systemwarning\s*>(.*?)<\s*/\s*systemwarning\s*>",
    re.IGNORECASE | re.DOTALL,
)


def extract_system_warnings(text: str) -> list:
    """Ekstrak daftar konten dari semua tag `<systemwarning>...</systemwarning>`
    yang ada di `text`, urut sesuai kemunculannya.

    Konten dikembalikan apa adanya (termasuk whitespace interior), hanya
    di-strip di tepi. Kalau tidak ada tag, kembalikan list kosong.
    """
    if not text:
        return []
    return [m.group(1).strip() for m in _BLOCK_RE.finditer(text)]


def strip_system_warnings(text: str) -> str:
    """Hapus SELURUH blok `<systemwarning>...</systemwarning>` (termasuk
    kontennya) dari `text`. Dipakai untuk membersihkan output sebelum
    ditampilkan ke user terminal, supaya instruksi internal tidak bocor.

    Kalau tidak ada tag, `text` dikembalikan apa adanya.
    """
    if not text:
        return text
    return _BLOCK_RE.sub("", text).strip()


def has_system_warning(text: str) -> bool:
    """True kalau `text` mengandung setidaknya satu tag systemwarning."""
    return bool(text) and _BLOCK_RE.search(text) is not None


def build_system_warning_block(warnings) -> str:
    """Bangun SATU blok pesan user yang memuat semua warning sistem aktif,
    masing-masing dibungkus tag `<systemwarning>...</systemwarning>`.

    `warnings` bisa berupa:
    - list[str] (daftar konten warning), atau
    - str tunggal (satu konten warning).

    Hasilnya dipakai sebagai `content` ketika menyuntikkan via
    `inject_system_warning()`. Blok yang dihasilkan menjaga urutan dan
    memisahkan tiap warning dengan baris kosong.
    """
    if warnings is None:
        return ""
    if isinstance(warnings, str):
        warnings = [warnings]
    parts = []
    for w in warnings:
        w = str(w).strip()
        if w:
            parts.append(f"<systemwarning>\n{w}\n</systemwarning>")
    return "\n\n".join(parts)


def inject_system_warning(db_path: str, session_id: str, warnings) -> int:
    """Suntikkan satu/beberapa warning sistem ke dalam alur percakapan.

    Menyimpan SATU pesan `user` dengan `kind="system_warning"` yang berisi
    blok `<systemwarning>...</systemwarning>` dari `warnings`. Pesan ini
    dikirim ke model pada giliran berikutnya sebagai instruksi prioritas
    tinggi.

    Args:
        db_path: path file DB sesi.
        session_id: id sesi percakapan.
        warnings: str tunggal, list[str], atau None.

    Returns:
        id baris pesan yang baru disimpan.

    Catatan: pesan yang disuntikkan otomatis di-pin (pinned=1). Ini penting
    karena `system_warning` adalah instruksi aktif yang harus selalu dikirim
    utuh ke model setiap giliran -- sama seperti pesan pinned yang
    dikecualikan dari summarization dan selalu dipertahankan oleh
    build_context_messages() (lihat context_manager.py). Tanpa di-pin,
    warning yang berada di bagian riwayat yang sudah diringkas (id <=
    upto_message_id) bisa tidak lagi dikirim ke model.
    """
    from .. import db as dbmod

    block = build_system_warning_block(warnings)
    if not block:
        raise ValueError("inject_system_warning: tidak ada konten warning untuk disuntikkan")
    msg_id = dbmod.add_message(
        db_path,
        session_id,
        "user",
        block,
        kind="system_warning",
    )
    dbmod.set_message_pinned(db_path, session_id, msg_id, pinned=True)
    return msg_id