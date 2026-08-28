"""tools/sandbox.py
Dipecah otomatis dari tools.py (lihat tools/_state.py untuk state bersama).
"""
import os

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



def _touch(rel_path: str):
    with state._RECENTLY_TOUCHED_LOCK:
        if rel_path in state._RECENTLY_TOUCHED:
            state._RECENTLY_TOUCHED.remove(rel_path)
        state._RECENTLY_TOUCHED.insert(0, rel_path)
        del state._RECENTLY_TOUCHED[state._MAX_RECENT:]


class SandboxViolation(Exception):
    """Dilempar saat path yang diminta berada di luar WORKDIR."""


def _resolve(path: str) -> str:
    """
    Resolve path relatif terhadap WORKDIR, dan tolak path yang keluar
    dari WORKDIR (baik lewat path absolut maupun "../..") kalau sandbox aktif.
    """
    candidate = path if os.path.isabs(path) else os.path.join(state.WORKDIR, path)
    real_candidate = os.path.realpath(candidate)
    real_workdir = os.path.realpath(state.WORKDIR)

    if state.SANDBOX_ENABLED:
        # commonpath aman dari trik "/workdir-evil" yang cuma nge-prefix string
        try:
            common = os.path.commonpath([real_candidate, real_workdir])
        except ValueError:
            # beda drive (Windows) dsb -> pasti di luar sandbox
            common = None
        if common != real_workdir:
            raise SandboxViolation(
                f"Path '{path}' berada di luar workdir yang diizinkan ({real_workdir}). "
                f"Jalankan dengan --no-sandbox jika ini disengaja."
            )

    return real_candidate


def _resolve_readonly(path: str) -> str:
    """
    Sama seperti _resolve(), tapi kalau path di luar WORKDIR ditolak,
    coba sekali lagi terhadap SKILLS_DIR (kalau diset) sebelum menyerah.

    Dipakai HANYA oleh tool baca-saja (read_file/list_dir/grep/
    outline_file) supaya isi skill -- termasuk file di dalam
    references/scripts/assets, bukan cuma SKILL.md -- bisa dibaca model
    walau skills_dir terinstal di luar workdir project (kasus umum: CLI
    diinstal di /opt/garwa, sementara user menjalankannya dengan
    --workdir /home/user/proyek-mereka). Tool destruktif TIDAK memakai
    fungsi ini, jadi skill tetap read-only bagi model.
    """
    try:
        return _resolve(path)
    except SandboxViolation:
        if not state.SANDBOX_ENABLED:
            raise
        candidate = path if os.path.isabs(path) else os.path.join(state.WORKDIR, path)
        real_candidate = os.path.realpath(candidate)

        # Jalur 1: file eksternal yang sudah disetujui user lewat drag-drop
        # (lihat ALLOWED_EXTERNAL_PATHS di atas). Cek dulu karena ini paling
        # spesifik -- path individual yang eksplisit disetujui user.
        if real_candidate in state.ALLOWED_EXTERNAL_PATHS:
            return real_candidate

        # Jalur 2: folder skills (SKILL.md + references/scripts/assets).
        if not state.SKILLS_DIR:
            raise
        real_skills_dir = os.path.realpath(state.SKILLS_DIR)
        try:
            common = os.path.commonpath([real_candidate, real_skills_dir])
        except ValueError:
            common = None
        if common != real_skills_dir:
            raise SandboxViolation(
                f"Path '{path}' berada di luar workdir ({os.path.realpath(state.WORKDIR)}) "
                f"maupun skills-dir ({real_skills_dir}) yang diizinkan."
            )
        return real_candidate
