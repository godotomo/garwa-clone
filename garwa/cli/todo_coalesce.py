"""cli/todo_coalesce.py

Koalesensi beberapa blok `todo_write` dalam SATU giliran.

Latar belakang bug: `todo_write` bersifat FULL REPLACE per workdir (lihat
`db.replace_todos`). Kalau model memecah daftar todo ke beberapa blok
`<tool_call>` dalam satu respon (pola yang sering muncul di model kecil),
mengeksekusi semuanya berurutan membuat blok TERAKHIR menimpa blok
sebelumnya -> todo tersimpan PARSIAL. Ini penyebab keluhan "todo sudah
dikerjakan semua tapi yang terbaca hanya beberapa".

Bukti sebelum perbaikan (tmp_repro/verify_todo_multi.py):
    5 blok x 1 item  -> 1 baris tersimpan  (PARSIAL)
    1 blok  x 5 item -> 5 baris tersimpan  (BENAR)

Solusi: gabung item dari semua blok `todo_write` pada giliran yang sama
(union berdasarkan `content`, blok yang lebih belakang menang), lalu
eksekusi sekali saja di posisi blok pertama.
"""
import json

from .colors import C
from .colors import c


def _items_of(args):
    """Ambil list item todo dari argumen satu blok tool_call."""
    if not isinstance(args, dict):
        return []
    items = args.get("todos")
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except Exception:
            return []
    return items if isinstance(items, list) else []


def coalesce_todo_writes(tool_calls, on_merge=None):
    """Gabungkan >1 blok `todo_write` dalam satu giliran menjadi satu panggilan.

    `tool_calls` adalah list `(name, arguments)`. Mengembalikan list baru
    (tidak memutasi input). Kalau blok `todo_write` <= 1, list asli
    dikembalikan apa adanya. `on_merge(n_blocks, n_items)` opsional untuk
    pelaporan (mis. cetak pesan) -- supaya modul ini tidak memaksa I/O.
    """
    idxs = [i for i, (n, _a) in enumerate(tool_calls) if n == "todo_write"]
    if len(idxs) < 2:
        return tool_calls

    merged = []
    seen = {}
    for i in idxs:
        for it in _items_of(tool_calls[i][1]):
            if isinstance(it, str):
                it = {"content": it, "status": "pending"}
            if not isinstance(it, dict) or "content" not in it:
                continue
            key = str(it["content"])
            entry = {"content": key, "status": str(it.get("status", "pending"))}
            if key in seen:
                merged[seen[key]] = entry
            else:
                seen[key] = len(merged)
                merged.append(entry)

    if not merged:
        return tool_calls

    if on_merge is not None:
        try:
            on_merge(len(idxs), len(merged))
        except Exception:  # noqa: BLE001 - pelaporan tidak boleh menggagalkan giliran
            pass

    first = idxs[0]
    out = []
    for i, tc in enumerate(tool_calls):
        if i == first:
            out.append(("todo_write", {"todos": merged}))
        elif i in idxs:
            continue
        else:
            out.append(tc)
    return out


def _report(n_blocks, n_items):
    print(c(
        f"  [TODO] {n_blocks} blok todo_write digabung menjadi 1 panggilan "
        f"({n_items} item) agar FULL REPLACE tidak saling menimpa.",
        C.DIM,
    ))


def coalesce_todo_writes_verbose(tool_calls):
    """Varian siap pakai dari agent_loop: koalesensi + cetak pesan ringkas."""
    return coalesce_todo_writes(tool_calls, on_merge=_report)
