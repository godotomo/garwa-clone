"""tools/_cron_expr.py
Logika bersama untuk ekspresi cron 5-field: pencocokan (`_cron_matches`) dan
validasi ketat (`validate_cron_expr`).

Dipisah ke modul sendiri supaya `comm_tools` (CRUD jadwal) dan `cron_runner`
(eksekusi) bisa berbagi logika TANPA circular import, dan agar validasi saat
insert (di comm_tools) konsisten dengan matcher saat eksekusi (di cron_runner).

Format: "menit jam hari bulan hari_minggu"
  - menit    : 0-59
  - jam      : 0-23
  - hari     : 1-31  (day of month)
  - bulan    : 1-12
  - hari_minggu: 0-7 (0 dan 7 = Minggu)

Tidak ada dependency eksternal (stdlib-only).
"""
from __future__ import annotations

import re
from datetime import datetime

# Rentang valid per field cron (untuk ekspansi '*' dan '*/n').
_FIELD_RANGES = {
    "minute": (0, 59),
    "hour": (0, 23),
    "dom": (1, 31),
    "month": (1, 12),
    "dow": (0, 7),  # 0 dan 7 sama-sama Minggu
}

# Urutan field + rentang, untuk validasi.
_FIELD_SPECS = [
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("dom", 1, 31),
    ("month", 1, 12),
    ("dow", 0, 7),
]

# Token valid per bagian field: angka, range a-b, step /n, atau kombinasi.
_TOKEN_RE = re.compile(
    r"^\*$|^\*/\d+$|^\d+(-\d+)?(/\d+)?$"
)


def _field_matches(field: str, value: int, field_name: str = "minute") -> bool:
    """Cocokkan satu field cron terhadap satu nilai integer.

    Mendukung: '*' (semua), angka, '*/n' (step), 'a-b' (range), 'a,b,c' (list),
    serta kombinasi 'a-b/n'.
    """
    field = field.strip()
    lo_default, hi_default = _FIELD_RANGES.get(field_name, (0, 59))
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            base, step_s = part.split("/", 1)
            try:
                step = int(step_s)
            except ValueError:
                step = 1
            part = base.strip()
        if part == "*":
            lo, hi = lo_default, hi_default
        elif "-" in part:
            a, b = part.split("-", 1)
            try:
                lo, hi = int(a), int(b)
            except ValueError:
                continue
        else:
            try:
                lo = hi = int(part)
            except ValueError:
                continue
        if lo <= value <= hi and (value - lo) % step == 0:
            return True
    return False


def _cron_matches(expr: str, dt: datetime) -> bool:
    """True bila ekspresi cron 5-field cocok dengan datetime `dt`."""
    parts = expr.split()
    if len(parts) != 5:
        return False
    minute, hour, dom, month, dow = parts
    # Hari dalam bulan dan hari dalam minggu: jika keduanya bukan '*', cron
    # standar (Vixie) memakai OR. Kami ikuti perilaku itu.
    dom_match = _field_matches(dom, dt.day, "dom")
    month_match = _field_matches(month, dt.month, "month")
    # weekday: 0 = Minggu (python: isoweekday() -> Senin=1..Minggu=7).
    dow_match = _field_matches(dow, (dt.isoweekday() % 7), "dow")
    if dom != "*" and dow != "*":
        day_ok = dom_match or dow_match
    else:
        day_ok = dom_match and dow_match
    return (
        _field_matches(minute, dt.minute, "minute")
        and _field_matches(hour, dt.hour, "hour")
        and month_match
        and day_ok
    )


def _valid_part(part: str, lo: int, hi: int) -> bool:
    """Validasi satu bagian field cron (setelah split koma).

    Mendukung: '*', '*/n', 'a', 'a-b', 'a-b/n'. Semua nilai harus dalam
    rentang [lo, hi]. Menolak sintaks tak dikenal.
    """
    part = part.strip()
    if not part:
        return False
    if not _TOKEN_RE.match(part):
        return False
    if part == "*":
        return True
    base = part
    step = 1
    if "/" in part:
        base, step_s = part.split("/", 1)
        step = int(step_s)
        if step <= 0:
            return False
    if base == "*":
        return True
    if "-" in base:
        a_s, b_s = base.split("-", 1)
        try:
            a, b = int(a_s), int(b_s)
        except ValueError:
            return False
        if not (lo <= a <= hi and lo <= b <= hi) or a > b:
            return False
    else:
        try:
            a = int(base)
        except ValueError:
            return False
        if not (lo <= a <= hi):
            return False
    return True


def validate_cron_expr(expr: str) -> bool:
    """Validasi ketat ekspresi cron 5-field. Return False bila invalid."""
    parts = str(expr or "").strip().split()
    if len(parts) != 5:
        return False
    for field, lo, hi in zip(parts, [s[1] for s in _FIELD_SPECS], [s[2] for s in _FIELD_SPECS]):
        for part in field.split(","):
            if not _valid_part(part, lo, hi):
                return False
    return True
