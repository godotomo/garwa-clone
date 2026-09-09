"""Kirim proposal email yang dipersonalisasi untuk job-job paling cocok.

Memilih job relevan (developer/designer/writer/web3/data/security) dari DB,
membuat proposal singkat per job, lalu kirim via SMTP ke JOB_EMAIL_RECIPIENT.
Proposal berisi ringkasan kemampuan + deliverable yang bisa dikerjakan langsung.
"""
import os
import sqlite3

PORTFOLIO = {
    "developer": "Full-stack developer (React/Next.js, FastAPI, Python, Node.js, Docker, CI/CD, cloud AWS/GCP/Azure).",
    "designer": "UI/UX & brand designer (wireframe, design system, landing page, logo/brand kit, Figma-style deliverables).",
    "writer": "Content & technical writer (SEO articles, copywriting, technical documentation, blog posts).",
    "web3": "Web3/smart contract developer (Solidity, Hardhat, DeFi, NFT, security audit checklist).",
    "data": "Data scientist / ML engineer (Python, pandas, scikit-learn, LLM, analytics, MLOps).",
    "security": "Security auditor / pentester (SAST, dependency audit, secret scan, IaC, DAST).",
}


def _pick_top_jobs(conn, limit=10):
    """Pilih job relevan terbaik dari DB (yang bisa dikerjakan langsung)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, platform, job_id, title, company, url, rate_min, rate_max,
               budget_min, budget_max, skills, category, description
        FROM jobs
        WHERE title IS NOT NULL AND LENGTH(title) > 5
        ORDER BY rowid DESC
    """)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]

    # Keyword relevan per role
    role_keywords = {
        "developer": ["developer", "engineer", "react", "python", "javascript",
                      "typescript", "node", "fullstack", "full-stack", "backend",
                      "frontend", "api", "django", "golang", "devops", "sre"],
        "designer": ["designer", "ui", "ux", "graphic", "brand", "visual",
                     "wireframe", "landing page", "figma"],
        "writer": ["writer", "copywriter", "content", "blog", "article",
                   "technical writer", "editor", "seo"],
        "web3": ["solidity", "web3", "blockchain", "smart contract", "defi",
                 "nft", "crypto developer"],
        "data": ["data scientist", "data analyst", "data engineer", "ml engineer",
                 "machine learning", "llm", "ai engineer"],
        "security": ["security", "pentest", "bug bounty", "appsec", "security audit"],
    }

    picked = []
    seen = set()
    for r in rows:
        rec = dict(zip(cols, r))
        title = (rec.get("title") or "").lower()
        skills = (str(rec.get("skills") or "")).lower()
        cat = (str(rec.get("category") or "")).lower()
        text = f"{title} {skills} {cat}"
        role = None
        for rl, kws in role_keywords.items():
            if any(k in text for k in kws):
                role = rl
                break
        if not role:
            continue
        key = (rec["platform"], rec["job_id"])
        if key in seen:
            continue
        seen.add(key)
        rec["role"] = role
        picked.append(rec)
        if len(picked) >= limit:
            break
    return picked


def _rate_str(rec):
    if rec.get("rate_min") and rec.get("rate_max"):
        return f"${rec['rate_min']}-{rec['rate_max']}/hr"
    if rec.get("rate_min"):
        return f"${rec['rate_min']}+/hr"
    if rec.get("budget_min") and rec.get("budget_max"):
        return f"${rec['budget_min']}-${rec['budget_max']}"
    return "Negotiable"


def _build_proposal(rec):
    role = rec["role"]
    portfolio = PORTFOLIO.get(role, PORTFOLIO["developer"])
    title = rec.get("title") or "your project"
    company = rec.get("company") or "your company"
    return (
        f"<h3>Proposal: {title}</h3>"
        f"<p><b>Company:</b> {company} · <b>Rate:</b> {_rate_str(rec)}</p>"
        f"<p>Hello {company} team,</p>"
        f"<p>I'm a freelance {role} ready to start immediately. "
        f"<b>Portfolio:</b> {portfolio}</p>"
        f"<p>I can deliver high-quality work on this project directly and "
        f"provide a working deliverable (code/design/article/contract) for your review. "
        f"I have hands-on experience delivering production-ready results remotely.</p>"
        f"<p>Link: <a href='{rec.get('url') or '#'}'>{rec.get('url') or '#'}</a></p>"
        f"<hr>"
    )


def send_proposals(recipient=None, limit=10, subject=None):
    recipient = recipient or os.environ.get("JOB_EMAIL_RECIPIENT") or os.environ.get("EMAIL_RECIPIENT")
    if not recipient:
        print("[proposal] RECIPIENT belum diset")
        return False

    from ._garwa_bridge import send_email
    from .db import DB_PATH

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        jobs = _pick_top_jobs(conn, limit=limit)
    finally:
        conn.close()

    if not jobs:
        print("[proposal] tidak ada job relevan ditemukan")
        return False

    body_parts = [
        "<h2>Freelance Proposals — Ready to Work</h2>",
        f"<p><b>{len(jobs)}</b> job proposals prepared for immediate delivery.</p>",
    ]
    for rec in jobs:
        body_parts.append(_build_proposal(rec))
    body_parts.append("<p><i>Generated by Garwa Jobbot — deliverables ready on request.</i></p>")
    body = "\n".join(body_parts)

    subject = subject or f"Freelance Proposals ({len(jobs)} jobs) - ready to work"
    ok = send_email(to=recipient, subject=subject, body=body, html=True)
    print(f"[proposal] email sent: {ok} ({len(jobs)} proposals)")
    return ok


if __name__ == "__main__":
    send_proposals()
