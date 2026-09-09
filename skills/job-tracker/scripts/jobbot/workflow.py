"""jobbot/workflow.py - Manajemen siklus hidup pekerjaan (contract lifecycle).

State machine pekerjaan freelance:
  applied -> accepted -> in_progress -> delivered -> (revision) -> completed
                                          ^                          |
                                          +------ revision ---------+

Fungsi-fungsi di sini mengelola kontrak (contracts) dan deliverables,
mulai dari menerima tawaran, mengerjakan, mengirim hasil, hingga revisi
dan penyelesaian. Terintegrasi dengan earnings tracking.

Status kontrak:
  - accepted     : tawaran diterima, belum mulai
  - in_progress  : sedang dikerjakan
  - delivered    : hasil sudah dikirim, menunggu review klien
  - revision     : klien minta revisi
  - completed    : selesai & dibayar
  - cancelled    : batal
"""
from datetime import datetime, timezone

from . import db
from .models import now_iso, add_earning


VALID_STATUSES = {
    "accepted", "in_progress", "delivered", "revision", "completed", "cancelled",
}


def create_contract(conn, platform, job_id, title=None, company=None, url=None,
                    rate=None, budget=None, deadline=None, notes=None) -> int:
    """Buat kontrak baru (status awal 'accepted'). Return contract id."""
    cur = conn.execute(
        """
        INSERT INTO contracts (platform, job_id, title, company, url, rate,
                               budget, deadline, status, notes, started_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'accepted', ?, ?, ?)
        """,
        (platform, str(job_id), title, company, url, rate, budget, deadline,
         notes, now_iso(), now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def get_contract(conn, contract_id: int) -> dict:
    cur = conn.execute("SELECT * FROM contracts WHERE id=?", (contract_id,))
    row = cur.fetchone()
    return dict(row) if row else None


def get_contract_by_job(conn, platform, job_id) -> dict:
    cur = conn.execute(
        "SELECT * FROM contracts WHERE platform=? AND job_id=?",
        (platform, str(job_id)),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def list_contracts(conn, status=None) -> list[dict]:
    if status:
        cur = conn.execute(
            "SELECT * FROM contracts WHERE status=? ORDER BY created_at DESC",
            (status,),
        )
    else:
        cur = conn.execute("SELECT * FROM contracts ORDER BY created_at DESC")
    return [dict(r) for r in cur.fetchall()]


def set_status(conn, contract_id: int, status: str, **fields) -> None:
    """Update status kontrak + field opsional (deadline, notes, dll)."""
    if status not in VALID_STATUSES:
        raise ValueError(f"status tidak valid: {status}")
    now = now_iso()
    sets = ["status=?"]
    params = [status]
    for k, v in fields.items():
        if k in ("deadline", "notes", "title", "company", "rate", "budget"):
            sets.append(f"{k}=?")
            params.append(v)
    # timestamp otomatis berdasarkan status
    if status == "in_progress":
        sets.append("started_at=?")
        params.append(now)
    elif status == "delivered":
        sets.append("delivered_at=?")
        params.append(now)
    elif status == "completed":
        sets.append("completed_at=?")
        params.append(now)
    sets.append("updated_at=?")
    params.append(now)
    params.append(contract_id)
    conn.execute(f"UPDATE contracts SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()


def add_deliverable(conn, contract_id: int, name, path=None, description=None,
                    version: int = 1, status: str = "submitted") -> int:
    """Catat satu deliverable (file hasil kerja). Return deliverable id."""
    cur = conn.execute(
        """
        INSERT INTO deliverables (contract_id, name, path, description,
                                  version, status, submitted_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (contract_id, name, path, description, version, status,
         now_iso(), now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def list_deliverables(conn, contract_id: int) -> list[dict]:
    cur = conn.execute(
        "SELECT * FROM deliverables WHERE contract_id=? ORDER BY version DESC",
        (contract_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def add_revision(conn, contract_id: int, feedback: str) -> None:
    """Klien minta revisi: set status revision + simpan feedback di deliverable terakhir."""
    set_status(conn, contract_id, "revision")
    cur = conn.execute(
        "SELECT id FROM deliverables WHERE contract_id=? ORDER BY version DESC LIMIT 1",
        (contract_id,),
    )
    row = cur.fetchone()
    if row:
        conn.execute(
            "UPDATE deliverables SET feedback=?, status='revision_requested' WHERE id=?",
            (feedback, row["id"]),
        )
        conn.commit()


def complete_contract(conn, contract_id: int, amount: float = None,
                      source: str = None, note: str = None) -> None:
    """Tandai kontrak selesai & catat pendapatan (bila ada)."""
    set_status(conn, contract_id, "completed")
    if amount:
        c = get_contract(conn, contract_id)
        add_earning(conn, amount, source=source or c.get("platform"),
                    note=note or f"Contract #{contract_id}: {c.get('title') or ''}")


def contract_summary(conn) -> dict:
    """Ringkasan pipeline kontrak."""
    out = {}
    for s in VALID_STATUSES:
        cur = conn.execute("SELECT COUNT(*) AS c FROM contracts WHERE status=?", (s,))
        out[s] = cur.fetchone()["c"]
    return out
