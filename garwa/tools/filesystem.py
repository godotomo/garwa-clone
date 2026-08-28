"""tools/filesystem.py
Dipecah otomatis dari tools.py (lihat tools/_state.py untuk state bersama).
"""
import os
import glob
import shlex
import difflib
import tempfile

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
from .bash_tool import _cap_output
from .bash_tool import tool_bash
from .sandbox import SandboxViolation
from .sandbox import _resolve
from .sandbox import _resolve_readonly
from .sandbox import _touch



def tool_glob(pattern: str, path: str = ".", limit: int = None) -> str:
    """Cari file dengan glob pattern di dalam WORKDIR (atau subdirektori).

    Port dari opencode `tool/glob.ts`. Mengembalikan daftar path relatif
    terhadap WORKDIR, satu per baris. Gunakan path relatif untuk mempersempit
    pencarian dan limit untuk membatasi jumlah hasil.
    """
    pattern = str(pattern or "").strip()
    if not pattern:
        return "[ERROR] pattern wajib diisi."
    if limit is not None:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = None
    if limit is not None and limit <= 0:
        limit = None

    # Path pencarian dikunci ke dalam WORKDIR (sandbox). Tolak path absolut
    # atau yang keluar dari WORKDIR lewat "../".
    search_dir = str(path or ".").strip() or "."
    base = os.path.realpath(state.WORKDIR)
    target = os.path.realpath(os.path.join(base, search_dir))
    if state.SANDBOX_ENABLED and not (target == base or target.startswith(base + os.sep)):
        return f"[ERROR] path di luar WORKDIR tidak diizinkan: {path!r}"

    try:
        matches = glob.glob(os.path.join(target, pattern), recursive=True)
    except Exception as e:
        return f"[ERROR] glob gagal -- {e}"

    # Urutkan agar deterministik, filter hanya file (bukan direktori),
    # lalu jadikan relatif terhadap WORKDIR.
    matches = sorted(m for m in matches if os.path.isfile(m))
    if limit is not None:
        matches = matches[:limit]

    if not matches:
        return "[glob] Tidak ada file yang cocok."

    rel = [os.path.relpath(m, base) for m in matches]
    return "[glob] " + str(len(rel)) + " file cocok:\n" + "\n".join(rel)


def _coerce_optional_int(value, arg_name: str):
    """Model kadang mengirim angka sebagai string (mis. \"1\", \"15\") karena
    JSON yang ditulisnya tidak selalu konsisten tipe datanya. Signature
    `start_line: int = None` cuma type hint, TIDAK memaksa konversi -- kalau
    dibiarkan string, operasi aritmatika seperti `start_line - 1` akan crash
    dengan "unsupported operand type(s) for -: 'str' and 'int'". Konversi
    eksplisit di sini supaya tool tetap jalan berapa pun tipe yang dikirim
    model, dan gagal dengan pesan jelas kalau memang bukan angka valid.
    Sama seperti fix _coerce timeout di tool_bash().
    """
    if value is None or isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"Argumen {arg_name} tidak valid: {value!r} (harus berupa angka baris)")


def tool_read_file(path: str, start_line: int = None, end_line: int = None) -> str:
    try:
        start_line = _coerce_optional_int(start_line, "start_line")
        end_line = _coerce_optional_int(end_line, "end_line")
    except ValueError as e:
        return f"[ERROR] {e}"
    try:
        p = _resolve_readonly(path)
    except SandboxViolation as e:
        return f"[ERROR] {e}"
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        _touch(os.path.relpath(p, state.WORKDIR))
        if start_line or end_line:
            start = (start_line or 1) - 1
            end = end_line or len(lines)
            lines = lines[start:end]
            offset = start + 1
        else:
            offset = 1
        numbered = "".join(f"{i + offset:6d}\t{line}" for i, line in enumerate(lines))
        return _cap_output(numbered) if numbered else "(file kosong)"
    except FileNotFoundError:
        return f"[ERROR] File tidak ditemukan: {p}"
    except Exception as e:
        return f"[ERROR] {e}"


def _atomic_write(target_path: str, content: str, encoding: str = "utf-8"):
    """Tulis `content` ke `target_path` secara atomik.

    SEBELUMNYA: write_file/edit_file menulis langsung ke path target lewat
    `open(p, "w")`. Kalau proses terhenti paksa di tengah penulisan (crash,
    SIGKILL dari luar, disk penuh), file bisa tertinggal dalam keadaan
    setengah tertulis/korup -- pembaca lain (atau CLI ini sendiri saat
    resume) akan melihat konten campuran lama+baru yang tidak valid.

    Fix: tulis ke file sementara di direktori YANG SAMA (supaya rename di
    bawah tetap dalam filesystem yang sama dan benar-benar atomik), fsync,
    baru os.replace() ke path target -- os.replace() pada POSIX dijamin
    atomik, jadi pembaca lain selalu melihat versi lama utuh atau versi
    baru utuh, tidak pernah campuran.
    """
    directory = os.path.dirname(target_path) or "."
    fd, tmp_path = tempfile.mkstemp(
        dir=directory, prefix=".tmp-" + os.path.basename(target_path) + "-"
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def tool_write_file(path: str, content: str) -> str:
    try:
        p = _resolve(path)
    except SandboxViolation as e:
        return f"[ERROR] {e}"
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        exists = os.path.exists(p)
        _atomic_write(p, content)
        _touch(os.path.relpath(p, state.WORKDIR))
        return f"[OK] File {'ditimpa' if exists else 'dibuat'}: {p} ({len(content)} bytes)"
    except Exception as e:
        return f"[ERROR] {e}"


def tool_edit_file(path: str, old_str: str, new_str: str) -> str:
    try:
        p = _resolve(path)
    except SandboxViolation as e:
        return f"[ERROR] {e}"

    try:
        mtime_before = os.path.getmtime(p)
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return f"[ERROR] File tidak ditemukan: {p}"
    except UnicodeDecodeError as e:
        return f"[ERROR] File {p} bukan teks UTF-8 valid, tidak bisa diedit: {e}"
    except PermissionError as e:
        return f"[ERROR] Tidak ada izin membaca {p}: {e}"

    count = content.count(old_str)
    if count == 0:
        return "[ERROR] old_str tidak ditemukan di file. Pastikan teks sama persis (termasuk whitespace)."
    if count > 1:
        return f"[ERROR] old_str muncul {count} kali, harus unik. Perluas konteks old_str."

    new_content = content.replace(old_str, new_str)

    # Mitigasi TOCTOU: kalau file berubah di antara read dan write ini (mis.
    # diedit manual di editor lain, atau sesi CLI lain di workdir yang sama),
    # menimpa begitu saja akan diam-diam membuang perubahan tsb. Deteksi
    # lewat mtime dan tolak overwrite kalau file sudah berubah sejak dibaca --
    # model bisa read_file ulang lalu coba edit_file lagi dengan konteks baru.
    try:
        mtime_now = os.path.getmtime(p)
    except OSError:
        mtime_now = mtime_before
    if mtime_now != mtime_before:
        return (
            f"[ERROR] File {p} berubah di luar CLI ini sejak terakhir dibaca "
            "(kemungkinan diedit proses/editor lain). Edit dibatalkan supaya "
            "tidak menimpa perubahan tersebut. Baca ulang file (read_file) "
            "lalu coba edit_file lagi."
        )

    try:
        # Sama seperti write_file: tulis atomik (temp file + os.replace)
        # supaya crash/kill di tengah tulis tidak meninggalkan file dalam
        # keadaan setengah teredit.
        _atomic_write(p, new_content)
    except PermissionError as e:
        return f"[ERROR] Tidak ada izin menulis {p}: {e}"
    except OSError as e:
        return f"[ERROR] Gagal menulis {p}: {e}"

    _touch(os.path.relpath(p, state.WORKDIR))

    diff = "\n".join(
        difflib.unified_diff(
            content.splitlines(), new_content.splitlines(),
            fromfile=path, tofile=path, lineterm="", n=2
        )
    )
    return f"[OK] File diedit: {p}\n{diff[:2000]}"


def tool_list_dir(path: str = ".") -> str:
    try:
        p = _resolve_readonly(path)
    except SandboxViolation as e:
        return f"[ERROR] {e}"
    try:
        entries = sorted(os.listdir(p))
        lines = []
        for e in entries:
            full = os.path.join(p, e)
            tag = "DIR " if os.path.isdir(full) else "FILE"
            lines.append(f"[{tag}] {e}")
        return "\n".join(lines) if lines else "(direktori kosong)"
    except Exception as e:
        return f"[ERROR] {e}"


def tool_grep(pattern: str, path: str = ".", glob: str = "*") -> str:
    try:
        resolved = _resolve_readonly(path)
    except SandboxViolation as e:
        return f"[ERROR] {e}"
    # PENTING: sebelumnya `glob` disisipkan mentah ke dalam '{glob}' dan
    # pattern/path di-quote pakai repr() Python (bukan shell-escaping yang
    # benar) -- keduanya bisa dieksploitasi untuk command injection lewat
    # shell=True di tool_bash, dan tool ini ditandai non-destructive
    # (berjalan tanpa konfirmasi user). Semua argumen sekarang di-quote
    # dengan shlex.quote() yang memang dirancang untuk POSIX shell.
    # Flag `-E` (ERE) sengaja dipakai karena pola alternation (`a|b|c`)
    # adalah penggunaan umum untuk pencarian multi-simbol; dengan BRE
    # (default) karakter `|` diperlakukan literal sehingga query seperti
    # `^def |^class |^TOOLS` mengembalikan kosong.
    cmd = (
        f"grep -rnE --include={shlex.quote(glob)} -- "
        f"{shlex.quote(pattern)} {shlex.quote(resolved)} | head -100"
    )
    return tool_bash(cmd)
