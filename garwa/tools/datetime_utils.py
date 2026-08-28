"""tools/datetime_utils.py
Dipecah otomatis dari tools.py (lihat tools/_state.py untuk state bersama).
"""
from datetime import datetime

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



def _now_wib() -> datetime:
    return datetime.now(state._WIB)


def tool_local_now() -> str:
    """Kembalikan tanggal dan jam saat ini dalam WIB (UTC+7).

    Tool ini dipakai sebelum pencarian berita relatif seperti "hari ini",
    "terbaru", "saat ini", "kemarin", atau "minggu ini", dan untuk kebutuhan
    lain yang membutuhkan tanggal/waktu aktual. Nilai berasal dari clock mesin
    yang menjalankan CLI, bukan dari pengetahuan model.
    """
    now = _now_wib()
    hari = state._HARI_ID[now.weekday()]
    return f"{hari}, {now.strftime('%Y-%m-%d %H:%M:%S')} WIB (UTC+7)"
