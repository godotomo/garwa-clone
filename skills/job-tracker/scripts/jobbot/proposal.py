"""jobbot/proposal.py - Proposal/cover letter generator.

Auto-generate proposal lamaran yang personal untuk tiap job, berdasarkan
judul, deskripsi, skills, dan profil freelancer. Mendukung berbagai role:
developer, designer, writer, web3/solidity, data/ML, dll.

Profil freelancer dikonfigurasi via env var (lihat PROFILES) atau di-override
lewat argumen CLI.
"""
import os
import re
from typing import Optional

from .models import Job


# Profil default freelancer (bisa di-override via env JOB_PROFILE_*).
# Format: nama -> {title, skills, bio, portfolio}
DEFAULT_PROFILE = {
    "name": os.environ.get("JOB_PROFILE_NAME", "Your Name"),
    "title": os.environ.get("JOB_PROFILE_TITLE", "Full-Stack Developer"),
    "skills": os.environ.get(
        "JOB_PROFILE_SKILLS",
        "Python, JavaScript, TypeScript, React, Node.js, SQL, Docker",
    ),
    "bio": os.environ.get(
        "JOB_PROFILE_BIO",
        "Experienced developer with 5+ years building production web apps, "
        "APIs, and smart contracts.",
    ),
    "portfolio": os.environ.get("JOB_PROFILE_PORTFOLIO", ""),
    "rate": os.environ.get("JOB_PROFILE_RATE", "50"),  # USD/jam default
}


# Template per role. {name}, {title}, {skills}, {bio}, {portfolio}, {rate},
# {job_title}, {company}, {job_skills}, {job_desc_snippet}
TEMPLATES = {
    "developer": (
        "Hi! I'm {name}, a {title} with hands-on experience in {skills}.\n\n"
        "I read your posting for \"{job_title}\" at {company} and I'm confident "
        "I can deliver. {bio}\n\n"
        "Here's how I'd approach it:\n"
        "1. Understand requirements & scope clearly\n"
        "2. Deliver a clean, tested, documented solution\n"
        "3. Iterate based on your feedback until you're satisfied\n\n"
        "{portfolio_line}"
        "I can start immediately and my rate is ${rate}/hr. "
        "Happy to jump on a quick call to align.\n\n"
        "Best,\n{name}"
    ),
    "designer": (
        "Hi! I'm {name}, a designer specializing in {skills}.\n\n"
        "Your project \"{job_title}\" at {company} caught my eye. {bio}\n\n"
        "My process:\n"
        "1. Research & moodboard\n"
        "2. Wireframes / high-fidelity mockups\n"
        "3. Revisions until pixel-perfect\n\n"
        "{portfolio_line}"
        "Rate: ${rate}/hr. Available to start now.\n\n"
        "Best,\n{name}"
    ),
    "writer": (
        "Hi! I'm {name}, a writer covering {skills}.\n\n"
        "I'd love to write \"{job_title}\" for {company}. {bio}\n\n"
        "I deliver well-researched, engaging, SEO-friendly content on time. "
        "Samples available on request.\n\n"
        "{portfolio_line}"
        "Rate: ${rate}/hr (or per-word if preferred).\n\n"
        "Best,\n{name}"
    ),
    "web3": (
        "Hi! I'm {name}, a Web3 developer focused on {skills}.\n\n"
        "I'm excited about \"{job_title}\" at {company}. {bio}\n\n"
        "I have shipped smart contracts (Solidity), dApps, and audited code. "
        "I care about gas optimization and security best practices.\n\n"
        "{portfolio_line}"
        "Rate: ${rate}/hr. Ready to start.\n\n"
        "Best,\n{name}"
    ),
    "data": (
        "Hi! I'm {name}, a data professional skilled in {skills}.\n\n"
        "Your opening \"{job_title}\" at {company} is a great fit. {bio}\n\n"
        "I can clean, analyze, model, and visualize data into actionable "
        "insights, with reproducible pipelines.\n\n"
        "{portfolio_line}"
        "Rate: ${rate}/hr.\n\n"
        "Best,\n{name}"
    ),
    "security": (
        "Hi! I'm {name}, a security researcher specializing in {skills}.\n\n"
        "I'm interested in your program \"{job_title}\" at {company}. {bio}\n\n"
        "My approach:\n"
        "1. Scope mapping & threat modeling\n"
        "2. Manual testing + automated scanning (SAST/DAST)\n"
        "3. Clear, reproducible reports with severity & CVSS\n\n"
        "{portfolio_line}"
        "I follow responsible disclosure and can start immediately.\n\n"
        "Best,\n{name}"
    ),
    "generic": (
        "Hi! I'm {name}, a {title} with expertise in {skills}.\n\n"
        "I'm very interested in \"{job_title}\" at {company}. {bio}\n\n"
        "I'm reliable, communicate clearly, and deliver quality work on "
        "deadline. I'd be glad to discuss how I can help.\n\n"
        "{portfolio_line}"
        "Rate: ${rate}/hr.\n\n"
        "Best,\n{name}"
    ),
}


def _detect_role(job: Job) -> str:
    """Deteksi role dari judul + skills + kategori (BUKAN deskripsi).

    Deskripsi sengaja TIDAK dipakai agar role mengikuti posisi sebenarnya,
    bukan kata kunci kebetulan di body. Prioritas: web3 > developer > data
    > designer > writer. Developer dicek sebelum data supaya "software
    engineer" / "ai engineer" tetap jadi developer (bukan data analysis).
    """
    text = " ".join(filter(None, [
        job.title or "",
        job.skills or "",
        job.category or "",
    ])).lower()

    # Program bug bounty (kategori eksplisit) -> security
    if "bug-bounty" in text or "bug bounty" in text:
        return "security"

    web3_kw = ["solidity", "smart contract", "web3", "blockchain", "defi",
               "ethereum", "nft", "evm", "crypto", "token", "dapp"]
    security_kw = ["security", "pentest", "penetration", "bug bounty",
                   "bugbounty", "vulnerability", "audit", "red team",
                   "application security", "appsec", "infosec", "cybersecurity",
                   "exploit", "reverse engineer", "malware", "threat"]
    dev_kw = ["developer", "engineer", "programmer", "full-stack", "fullstack",
              "frontend", "front-end", "backend", "back-end", "react", "node",
              "python", "javascript", "typescript", "software", "api",
              "devops", "sre", "mobile", "android", "ios", "golang", "rust",
              "java", "c++", "c#", "php", "ruby", "kotlin", "swift"]
    data_kw = ["data scientist", "data analyst", "data engineer",
               "machine learning", "deep learning", "data science",
               "analytics", "pandas", "llm", "artificial intelligence",
               "ml engineer", "mlops", "ai engineer", "prompt engineer",
               "algorithm", "nlp", "computer vision", "ai/ml", "ai ml",
               "generative ai", "genai", "agentic"]
    design_kw = ["design", "ui/ux", "figma", "graphic", "illustrator",
                 "photoshop", "branding", "visual", "wireframe",
                 "user flow", "ui kit", "prototype", "mockup", "product design",
                 "visual design", "interaction design", "information architecture"]
    writer_kw = ["writer", "content", "copywrit", "blog", "editor",
                 "seo", "technical writing", "ghostwrit"]

    if any(k in text for k in web3_kw):
        return "web3"
    if any(k in text for k in security_kw):
        return "security"
    if any(k in text for k in data_kw):
        return "data"
    if any(k in text for k in dev_kw):
        return "developer"
    if any(k in text for k in design_kw):
        return "designer"
    if any(k in text for k in writer_kw):
        return "writer"
    return "developer"


def _snippet(desc: str, n: int = 160) -> str:
    """Potong deskripsi jadi snippet singkat untuk referensi."""
    if not desc:
        return ""
    desc = re.sub(r"\s+", " ", desc).strip()
    return desc[:n] + ("..." if len(desc) > n else "")


def generate_proposal(job: Job, profile: dict = None) -> str:
    """Generate proposal personal untuk satu job."""
    p = {**DEFAULT_PROFILE, **(profile or {})}
    role = _detect_role(job)
    template = TEMPLATES.get(role, TEMPLATES["generic"])

    portfolio_line = ""
    if p.get("portfolio"):
        portfolio_line = f"Portfolio: {p['portfolio']}\n\n"

    return template.format(
        name=p.get("name") or "Your Name",
        title=p.get("title") or "Freelancer",
        skills=p.get("skills") or "relevant technologies",
        bio=p.get("bio") or "",
        portfolio_line=portfolio_line,
        rate=p.get("rate") or "50",
        job_title=job.title or "(this project)",
        company=job.company or "your team",
        job_skills=job.skills or "",
        job_desc_snippet=_snippet(job.description),
    )


def generate_batch(jobs: list[Job], profile: dict = None) -> dict[str, str]:
    """Generate proposal untuk banyak job. Return {job_id: proposal}."""
    out = {}
    for job in jobs:
        out[job.job_id] = generate_proposal(job, profile)
    return out
