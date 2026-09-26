"""tools/session_tools.py
Dipecah otomatis dari tools.py (lihat tools/_state.py untuk state bersama).
"""
import json
import ast

from .. import db as dbmod
from .. import todo_utils

try:
    from .. import repo_map as repo_map_mod
except ImportError:
    # repo_map hanya dipakai oleh tool repo_map/outline_file (opsional).
    # Jangan sampai seluruh tools.py (dan cli.py yang meng-import-nya
    # di top-level) gagal start hanya karena modul opsional ini belum ada.
    repo_map_mod = None

try:
    from .. import security as security_mod
except ImportError:
    security_mod = None

try:
    from .. import config as config_mod
except ImportError:
    config_mod = None
from . import _state as state



def _require_session() -> str:
    if not state.SESSION_ID:
        return ("[ERROR] Tidak ada sesi aktif untuk menyimpan todo (SESSION_ID belum diset). "
                "Ini seharusnya otomatis diset oleh cli.py saat startup.")
    return ""


def tool_todo_write(todos: list, remove=None) -> str:
    err = _require_session()
    if err:
        return err
    # SEBELUMNYA: fungsi ini HANYA menerima `todos` sebagai list Python.
    # Tapi model (terutama lewat JSON tool-calling) sering mengirim argumen
    # sebagai STRING JSON (mis. '"[{\\"content\\": ...}]"') karena escaping
    # berlapis, atau sebagai string yang berisi representasi list. Kalau
    # dibiarkan, isinstance(todos, list) gagal dan fungsi selalu menolak
    # dengan "[ERROR] ... harus berupa list". Fix: kalau `todos` berupa
    # string, coba parse sebagai JSON (atau ast.literal_eval) dulu sebelum
    # validasi tipe.
    if isinstance(todos, str):
        s = todos.strip()
        try:
            todos = json.loads(s)
        except Exception:
            try:
                todos = ast.literal_eval(s)
            except Exception:
                return "[ERROR] Argumen 'todos' berupa string tapi tidak bisa di-parse sebagai list JSON."
    if not isinstance(todos, list):
        return "[ERROR] Argumen 'todos' harus berupa list of {content, status}."

    normalized = []
    valid_status = {"pending", "in_progress", "done", "cancelled"}
    for item in todos:
        if isinstance(item, str):
            normalized.append({"content": item, "status": "pending"})
        elif isinstance(item, dict) and "content" in item:
            status = item.get("status", "pending")
            if status not in valid_status:
                status = "pending"
            normalized.append({"content": item["content"], "status": status})
        else:
            return f"[ERROR] Item todo tidak valid: {item!r}"

    # `remove`: daftar content yang dibuang EKSPLISIT (termasuk item done/
    # cancelled yang seharusnya dipertahankan). Sama seperti `todos`, model bisa
    # mengirimnya sebagai string JSON/representasi list -> parse dulu.
    remove_list = None
    if remove is not None:
        if isinstance(remove, str):
            s_rm = remove.strip()
            try:
                remove_list = json.loads(s_rm)
            except Exception:
                try:
                    remove_list = ast.literal_eval(s_rm)
                except Exception:
                    # Bukan JSON/list -> anggap satu content tunggal.
                    remove_list = s_rm
        else:
            remove_list = remove
        if isinstance(remove_list, str):
            remove_list = [remove_list]
        if not isinstance(remove_list, (list, tuple, set)):
            return "[ERROR] Argumen 'remove' harus berupa list of content (str) yang dibuang."
        remove_list = [r for r in remove_list if isinstance(r, str)]

    # SEBELUMNYA: dbmod.replace_todos() (menyentuh SQLite lewat db.py) tidak
    # dibungkus try/except sama sekali. replace_todos() sendiri bisa
    # melempar ValueError (item tidak valid) atau exception SQLite mentah
    # (mis. "database is locked" kalau ada write lain yang overlap, lihat
    # db.py) -- keduanya sebelumnya merambat naik tanpa tertangani sampai
    # ke dispatcher tool-call di cli.py, alih-alih dikembalikan sebagai
    # "[ERROR] ..." yang konsisten seperti handler lain.
    # Snapshot todo SEBELUM replace untuk mendeteksi:
    #   1. item yang HILANG (ada sebelumnya, tidak ada sekarang) -- full replace
    #      berarti model "menghapus" item hanya dengan tidak menyebutkannya,
    #      dan itu sering TIDAK disengaja (daftar kepotong / lupa disalin).
    #   2. REGRESI (done -> pending/in_progress) yang hampir selalu kekeliruan.
    # Keduanya dikembalikan sebagai peringatan, bukan error: penulisan tetap
    # dilakukan supaya model tidak terjebak loop, tapi diberi tahu agar sadar.
    try:
        prev_rows = dbmod.get_todos(state.DB_PATH, workdir=state.WORKDIR)
    except Exception:
        prev_rows = []

    # `preserve_finished=True`: item lama yang sudah done/cancelled dan tidak
    # disebut lagi dipertahankan otomatis -- mode kegagalan "item hilang karena
    # lupa disalin" hilang. Untuk membuang item selesai, model memakai `remove`.
    remove_set = set(remove_list or [])
    try:
        dbmod.replace_todos(state.DB_PATH, state.WORKDIR, normalized,
                            session_id=state.SESSION_ID,
                            remove=remove_list, preserve_finished=True)
    except ValueError as e:
        return f"[ERROR] Data todo tidak valid: {e}"
    except Exception as e:
        return f"[ERROR] Gagal menyimpan plan/todo ke database: {type(e).__name__}: {e}"

    # Baris lengkap hasil tulisan (termasuk item selesai yang dipertahankan).
    try:
        saved_rows = dbmod.get_todos(state.DB_PATH, workdir=state.WORKDIR)
    except Exception:
        saved_rows = None

    lines = ["[OK] Plan diperbarui:"]
    marks = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]", "cancelled": "[-]"}
    for item in (saved_rows if saved_rows else normalized):
        lines.append(f"  {marks.get(item['status'], '[ ]')} {item['content']}")

    # --- Deteksi item aktif yang hilang & regresi ---------------------------
    # Dengan preserve_finished, item done/cancelled TIDAK lagi dihitung hilang
    # (dipertahankan otomatis). Yang masih berharga untuk diperingatkan adalah
    # item AKTIF (pending/in_progress) yang lenyap tanpa disebut -- itu bisa
    # berarti rencana terpotong.
    new_status = {}
    for item in normalized:
        new_status[item["content"]] = item["status"]
    dropped, regressed = [], []
    for old in prev_rows:
        content = old.get("content")
        new = new_status.get(content)
        if new is None:
            if content in remove_set:
                continue  # dibuang sengaja
            if old.get("status") in ("done", "cancelled"):
                continue  # dipertahankan otomatis oleh preserve_finished
            dropped.append(old)
        elif old.get("status") in ("done", "cancelled") and new in ("pending", "in_progress"):
            regressed.append((old, new))
    if dropped:
        lines.append("")
        lines.append(f"[WARN] {len(dropped)} todo AKTIF sebelumnya HILANG dari daftar ini "
                     "(status aktif dan tidak disebut = dihapus; item selesai "
                     "dipertahankan otomatis):")
        for old in dropped:
            lines.append(f"  {marks.get(old.get('status'), '[ ]')} {old.get('content')}")
        lines.append("       Kalau ini tidak disengaja, kirim ulang todo_write dengan item itu disertakan.")
    if regressed:
        lines.append("")
        lines.append(f"[WARN] {len(regressed)} todo berstatus SELESAI tapi dikembalikan ke status aktif:")
        for old, new in regressed:
            lines.append(f"  {old.get('content')}: {old.get('status')} -> {new}")

    # --- Deteksi todo yang menggantung terlalu lama (basi) ------------------
    # PENTING: dibaca ULANG dari DB, bukan dari `normalized`. Item input hanya
    # berisi {content, status} tanpa `status_since`, sehingga umurnya selalu
    # dihitung 0 detik dan deteksi basi tidak akan pernah menyala. Baris hasil
    # tulisan di DB-lah yang membawa `status_since` hasil preservasi
    # replace_todos (status sama -> waktu lama dipertahankan). `saved_rows`
    # sudah dibaca di atas (untuk menampilkan daftar hasil tulisan).
    if saved_rows:
        stale_now = todo_utils.stale_summary(saved_rows)
        if stale_now:
            lines.append("")
            lines.append(f"[WARN] {stale_now}")
    return "\n".join(lines)


def tool_todo_read() -> str:
    err = _require_session()
    if err:
        return err
    # SEBELUMNYA: dbmod.get_todos() tidak dibungkus try/except -- exception
    # SQLite mentah (mis. "database is locked") bisa merambat sampai ke
    # dispatcher cli.py. Lihat catatan sama di tool_todo_write.
    try:
        rows = dbmod.get_todos(state.DB_PATH, workdir=state.WORKDIR)
    except Exception as e:
        return f"[ERROR] Gagal membaca plan/todo dari database: {type(e).__name__}: {e}"
    if not rows:
        return "(belum ada todo/plan untuk sesi ini)"
    # Tampilkan umur STATUS tiap item aktif + penanda [STALE] kalau sudah
    # menggantung melewati ambang. Dulu hanya teks polos, sehingga model tidak
    # punya cara mengetahui item mana yang sudah basi -- padahal todo ini dibaca
    # lintas sesi dan yang basi menyesatkan sesi berikutnya.
    lines = todo_utils.format_rows(rows)
    summary = todo_utils.stale_summary(rows)
    if summary:
        lines.append("")
        lines.append(f"[WARN] {summary}")
    active = [r for r in rows if (r.get("status") or "pending") in ("pending", "in_progress")]
    if active:
        oldest = max(todo_utils.age_seconds(r) for r in active)
        lines.append("")
        lines.append(f"[INFO] {len(active)} item aktif; status terlama belum berubah {todo_utils.format_age(oldest)}. "
                     "Tandai done lewat todo_write begitu pekerjaannya benar-benar selesai.")
    return "\n".join(lines)


def tool_remember(key: str, value: str) -> str:
    # SEBELUMNYA: dbmod.set_note() (INSERT ... ON CONFLICT ke SQLite via
    # db.py) dipanggil tanpa try/except sama sekali -- beda dari semua
    # handler lain di file ini yang selalu mengembalikan string
    # "[ERROR] ..." saat gagal. Kalau SQLite melempar OperationalError
    # ("database is locked", bisa terjadi karena WAL tetap menyerialkan
    # antar-writer -- lihat db.py -- kalau add_message() dari cli.py
    # kebetulan menulis di window yang sama) atau exception lain apa pun,
    # itu akan merambat MENTAH ke dispatcher tool-call di cli.py alih-alih
    # jadi pesan tool yang rapi. Ini kandidat utama untuk gejala seperti
    # "Tool '{...}' tidak dikenal" yang muncul tepat setelah panggilan
    # remember, karena bentuk pesan itu bukan berasal dari tools.py.
    key = str(key or "").strip()
    if not key:
        return "[ERROR] Argumen 'key' wajib diisi dan tidak boleh kosong."
    if value is None:
        return "[ERROR] Argumen 'value' wajib diisi."
    try:
        dbmod.set_note(state.DB_PATH, state.WORKDIR, key, str(value))
    except Exception as e:
        return f"[ERROR] Gagal menyimpan catatan proyek '{key}': {type(e).__name__}: {e}"
    return f"[OK] Catatan proyek disimpan: {key} = {value}"


def tool_recall(key: str = None) -> str:
    # SEBELUMNYA: dbmod.get_notes() tidak dibungkus try/except. Lihat
    # catatan yang sama di tool_remember di atas.
    try:
        notes = dbmod.get_notes(state.DB_PATH, state.WORKDIR)
    except Exception as e:
        return f"[ERROR] Gagal membaca catatan proyek: {type(e).__name__}: {e}"
    if key:
        notes = [n for n in notes if n["key"] == key]
    if not notes:
        return "(tidak ada catatan proyek tersimpan)"
    return "\n".join(f"{n['key']}: {n['value']}" for n in notes)
