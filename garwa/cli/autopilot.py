"""cli/autopilot.py
Mekanisme AUTOPILOT (/autopilot on|off).

Latar belakang (sisi KLIEN, bukan sisi model): kadang model mengakhiri giliran
tanpa mengirim satu pun tool_call walau rencana (todo list) proyek masih jauh
dari selesai -- respon bisa kosong, atau cuma prosa, atau blok tool_call yang
tidak bisa di-parse. Dari titik pandang klien itu "STOP" yang tampak wajar,
padahal pekerjaan belum selesai. Garwa tidak boleh menebak isi pikiran model,
jadi solusinya adalah saklar eksplisit milik user:

    /autopilot on     -> selama masih ada todo pending/in_progress, giliran
                         TIDAK berhenti ketika model berhenti mengirim tool_call;
                         klien menyuntikkan pesan lanjutan supaya model
                         melanjutkan pekerjaan.
    /autopilot off    -> kembali ke perilaku normal (berhenti saat tidak ada
                         tool_call).

Autopilot MEMATIKAN DIRINYA SENDIRI ketika sudah tidak ada todo pending lagi
dan model tetap tidak memanggil tool -- artinya seluruh rencana sudah selesai,
sehingga tidak ada alasan menyuntikkan pesan lanjutan. Ada juga batas jumlah
iterasi otomatis (`GARWA_AUTOPILOT_MAX`, default 20) sebagai pengaman supaya
tidak jadi loop tak berujung kalau todo tidak pernah ditutup model.

Pesan yang disuntikkan berisi:
  1. daftar todo yang masih pending (dengan tanda [ ] / [~]), dan
  2. opsional, hasil analisa agen lain -- khususnya agen "reviewer": user bisa
     melampirkan catatan bebas saat mengaktifkan
     (`/autopilot on <pesan/analisa reviewer>`), dan/atau menyimpan catatan
     proyek berkunci REVIEWER_NOTE_KEY (lewat `remember`//memory) yang akan
     ikut disertakan pada setiap suntikan.

Semua helper di sini murni membaca state (DB) dan menyusun teks; TIDAK ada efek
samping selain itu, supaya mudah diuji.
"""
from .. import db as dbmod

# Kunci catatan proyek (tabel project_notes) yang isinya dianggap hasil analisa
# agen reviewer. Kalau ada, isinya disertakan pada setiap pesan lanjutan
# autopilot supaya model melihat temuan reviewer, bukan hanya daftar todo.
REVIEWER_NOTE_KEY = "reviewer"

# Kata-kata yang menandakan "lanjutkan" / "nyalakan" / "matikan".
_ON_WORDS = ("on", "1", "true", "yes", "aktif", "ya")
_OFF_WORDS = ("off", "0", "false", "no", "nonaktif", "tidak")


def parse_toggle(arg: str):
    """Parse argumen /autopilot menjadi (enabled, note).

    Mengembalikan (None, None) kalau argumen TIDAK dikenali sebagai on/off,
    sehingga pemanggil bisa mencetak petunjuk pemakaian.

    Sisa argumen setelah kata on/off diperlakukan sebagai catatan tambahan
    (mis. analisa agen reviewer):
        /autopilot on reviewer: bagian X masih pakai API lama
    """
    parts = (arg or "").strip().split(None, 1)
    if not parts:
        return None, None
    flag = parts[0].strip().lower()
    note = parts[1].strip() if len(parts) > 1 else ""
    if flag in _ON_WORDS:
        return True, note
    if flag in _OFF_WORDS:
        return False, note
    return None, None


def get_pending_todos(db_path: str, workdir: str) -> list:
    """Todo pending/in_progress untuk `workdir` (lintas sesi).

    Membungkus dbmod.get_pending_todos dengan penjagaan: kalau DB belum/tidak
    bisa dibaca, kembalikan list kosong -- autopilot TIDAK boleh membuat giliran
    crash hanya karena soal todo.
    """
    try:
        return dbmod.get_pending_todos(db_path, workdir) or []
    except Exception:  # noqa: BLE001 - todo opsional, jangan sampai menggagalkan giliran
        return []


def get_reviewer_note(db_path: str, workdir: str) -> str:
    """Ambil catatan hasil analisa agen reviewer (kalau ada) untuk `workdir`."""
    try:
        notes = dbmod.get_notes(db_path, workdir) or []
    except Exception:  # noqa: BLE001 - catatan opsional
        return ""
    for n in notes:
        if (n.get("key") or "") == REVIEWER_NOTE_KEY:
            value = (n.get("value") or "").strip()
            if value:
                return value
    return ""


def _format_todos(todos: list) -> str:
    """Format todo pending menjadi daftar bertanda [ ] / [~]."""
    lines = []
    for t in todos:
        status = t.get("status") or "pending"
        mark = "[~]" if status == "in_progress" else "[ ]"
        content = (t.get("content") or "").strip().replace("\n", " ")
        if len(content) > 200:
            content = content[:197] + "..."
        lines.append(f"  {mark} {content}")
    return "\n".join(lines)


def build_continue_message(db_path: str, workdir: str, note: str = "") -> str:
    """Susun pesan lanjutan autopilot (string siap dikirim sebagai pesan user).

    Bentuknya dibungkus <tool_result> agar konsisten dengan koreksi otomatis
    lain yang sudah ada di agent_loop (mis. [MALFORMED]).
    """
    todos = get_pending_todos(db_path, workdir)
    reviewer = get_reviewer_note(db_path, workdir)
    if note:
        # Catatan sesi ini menang atas catatan proyek: user baru saja
        # menempelkannya saat mengaktifkan autopilot.
        if reviewer:
            reviewer = f"{note}\n\n(Catatan proyek reviewer: {reviewer})"
        else:
            reviewer = note

    parts = [
        "<tool_result>",
        "[AUTOPILOT] Anda (model) mengakhiri giliran tanpa memanggil tool, "
        "padahal rencana proyek BELUM selesai. Autopilot aktif, jadi giliran "
        "dilanjutkan otomatis. Lanjutkan pekerjaan dari todo yang masih "
        "pending/in_progress di bawah ini; panggil tool yang diperlukan, dan "
        "tandai todo sebagai done lewat todo_write HANYA setelah benar-benar "
        "selesai.",
    ]
    if todos:
        parts.append(f"\nTodo yang belum selesai ({len(todos)} item):")
        parts.append(_format_todos(todos))
    if reviewer:
        parts.append("\nHasil analisa agen reviewer yang perlu ditindaklanjuti:")
        parts.append(reviewer)
    parts.append(
        "\nKalau SEMUA todo sudah benar-benar selesai, tuliskan ringkasan "
        "singkat hasil pekerjaan tanpa memanggil tool lagi -- autopilot akan "
        "berhenti sendiri saat tidak ada todo yang tersisa."
    )
    parts.append("</tool_result>")
    return "\n".join(parts)
