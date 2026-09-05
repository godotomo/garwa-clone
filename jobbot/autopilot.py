"""jobbot/autopilot.py - Pipeline autonomous end-to-end (tanpa interaksi manusia).

Menjalankan seluruh siklus pekerjaan freelance secara otomatis dan long-running:

  scrape -> rank high-value -> generate proposal -> buat kontrak (simulasi
  tawaran diterima) -> produksi deliverable nyata (executor) -> report
  Telegram -> (opsional) Google Workspace.

Dirancang untuk target $50/hari: setiap siklus memproduksi deliverable nyata
untuk job bernilai tinggi, mencatat kontrak & earning, lalu melaporkan hasil.

Cara pakai:
  # Sekali jalan (foreground)
  python -m jobbot.autopilot

  # Long-running loop (interval detik antar siklus)
  python -m jobbot.autopilot --interval 3600

  # Sekali jalan, batasi jumlah deliverable yang diproduksi
  python -m jobbot.autopilot --max-deliverables 3

Tidak ada langkah yang butuh konfirmasi/approve: semua tulis file, update DB,
dan report dijalankan langsung. Hanya perintah berbahaya (rm -rf dsb.) yang
ditunda — dan autopilot tidak memakainya.
"""
import argparse
import os
import time
from datetime import datetime, timezone

from . import db
from .models import (
    Job, get_all_jobs, get_high_value_jobs, add_earning,
    get_earnings_summary, upsert_job,
)
from .scraper import scrape_all
from .proposal import generate_proposal, _detect_role
from .workflow import (
    create_contract, get_contract_by_job,
    contract_summary,
)
from .executor import execute_job
from .llm_filter import classify_job
from .reporter import TelegramReporter, format_daily_summary


# Keyword default untuk 4 role (developer, designer, writer, web3)
DEFAULT_KEYWORDS = [
    "python developer", "javascript developer", "react developer",
    "full stack developer", "frontend developer", "backend developer",
    "ui ux designer", "graphic designer", "brand designer",
    "content writer", "technical writer", "copywriter",
    "solidity developer", "web3 developer", "blockchain developer",
    "smart contract developer",
]

# Platform keyless yang terverifikasi (hindari yang flaky/anti-bot)
DEFAULT_PLATFORMS = [
    "remote-ok", "remotive", "working-nomads", "jobicy",
    "arbeitnow", "jobscollider",
    "hackerone", "yeswehack",
]


# Keyword relevan untuk 4 role (developer, designer, writer, web3).
# Job di luar ini (mis. VP, sales, HR, finance) di-skip.
ROLE_KEYWORDS = [
    # developer
    "developer", "engineer", "programmer", "software", "full stack", "fullstack",
    "frontend", "front-end", "backend", "back-end", "react", "node", "python",
    "javascript", "typescript", "java", "php", "golang", "ruby", "c++",
    "c#", "kotlin", "swift", "mobile", "android", "ios", "devops", "sre",
    "cloud", "api", "database", "sql", "web app", "webapp",
    # designer
    "designer", "design", "ui/ux", "ui ux", "figma", "graphic", "illustrator",
    "photoshop", "branding", "visual", "creative", "logo",
    # writer
    "writer", "content", "copywrit", "blog", "editor", "seo", "technical writing",
    "ghostwrit", "journalist", "proofread",
    # web3
    "solidity", "smart contract", "web3", "blockchain", "defi", "ethereum",
    "nft", "evm", "crypto", "token", "dapp", "rust",
    # security / bug bounty
    "security", "pentest", "penetration", "bug bounty", "bugbounty",
    "vulnerability", "audit", "red team", "appsec", "infosec",
    "cybersecurity", "exploit", "reverse engineer", "malware", "threat",
]


# Posisi yang TIDAK bisa dikerjakan langsung sebagai individual contributor.
# Job yang judulnya mengandung salah satu kata ini di-skip, meskipun deskripsi
# atau skills-nya menyebut kata teknis. Ini mencegah autopilot "mengambil semua
# pekerjaan" termasuk posisi manajerial/eksekutif/non-teknis.
EXCLUDE_TITLE_KEYWORDS = [
    # eksekutif / C-level / leadership
    "vice president", "v.p.", "chief ", "cto", "ceo", "coo", "cfo",
    "cmo", "cio", "cpo", "president", "executive", "founder", "co-founder",
    "cofounder", "director", "head of", "principal", "partner",
    # manajerial
    "manager", "management", "team lead", "engineering lead", "engineering manager",
    "dev manager", "development manager", "supervisor", "coordinator",
    # non-teknis / sales / marketing / HR / finance / ops / support
    "sales", "marketing", "growth", "business development", "biz dev",
    "account ", "recruiter", "recruiting", "human resources", "talent",
    "finance", "accounting", "bookkeep", "operations", "customer success",
    "customer support", "support specialist", "community manager",
    "product manager", "project manager", "program manager", "account manager",
    "office manager", "data entry", "virtual assistant", "administrative",
    "legal", "lawyer", "attorney", "compliance", "customer service",
    "technical support", "help desk", "helpdesk", "it support",
]


def _is_relevant(job: Job) -> bool:
    """Cek apakah job relevan & PASTI bisa dikerjakan langsung.

    Dua lapis filter:
      1. Exclude: judul mengandung posisi manajerial/eksekutif/non-teknis.
      2. Require: judul (bukan cuma deskripsi) mengandung kata role teknis.

    Khusus bug bounty (kategori 'bug-bounty' dari HackerOne/YesWeHack),
    program SELALU relevan karena kita memang mengerjakan security audit.
    """
    title_text = " ".join(filter(None, [
        job.title or "",
        job.skills or "",
        job.category or "",
    ])).lower()

    full_text = " ".join(filter(None, [
        job.title or "",
        job.skills or "",
        job.category or "",
        (job.description or "")[:300],
    ])).lower()

    # Bug bounty program selalu relevan (security audit adalah role kita)
    if "bug-bounty" in full_text or "bug bounty" in full_text:
        return True

    # 1. Exclude posisi yang tidak bisa dikerjakan langsung
    if any(k in title_text for k in EXCLUDE_TITLE_KEYWORDS):
        return False

    # 2. Judul harus mengandung kata role teknis (bukan cuma deskripsi)
    return any(k in title_text for k in ROLE_KEYWORDS)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _log(msg: str) -> None:
    print(f"[autopilot] {_now()} {msg}", flush=True)


def run_cycle(max_deliverables: int = 3, min_budget: float = 0.0,
              keywords=None, platforms=None, report_google: bool = False,
              report_email: bool = False,
              simulate_accept: bool = True) -> dict:
    """Jalankan satu siklus penuh. Return dict statistik.

    Alur:
      1. Scrape semua platform keyless -> simpan ke DB (dedup).
      2. Rank job bernilai tinggi (budget/rate terbesar).
      3. Untuk top-N job, generate proposal + buat kontrak (simulasi diterima).
      4. Produksi deliverable nyata via executor, set status delivered.
      5. Report ringkasan ke Telegram.
      6. (opsional) Laporan Google Workspace.
      7. (opsional) Kirim laporan email via SMTP.
    """
    db.init_db()
    conn = db.get_conn()
    stats = {
        "scraped": 0,
        "high_value": 0,
        "proposals": 0,
        "contracts_created": 0,
        "deliverables": 0,
        "earnings_today": 0.0,
        "errors": [],
    }

    try:
        # --- 1. Scrape ---
        _log(f"scraping {len(platforms or DEFAULT_PLATFORMS)} platforms...")
        results = scrape_all(keywords or DEFAULT_KEYWORDS,
                             platforms or DEFAULT_PLATFORMS, limit=20, conn=conn)
        stats["scraped"] = sum(len(v) for v in results.values())
        _log(f"scraped {stats['scraped']} jobs")

        # --- 2. Rank high-value ---
        high = get_high_value_jobs(conn, min_budget=min_budget, limit=50)
        stats["high_value"] = len(high)
        _log(f"high-value candidates: {len(high)}")

        # --- 3-4. Proposal + kontrak + deliverable ---
        produced = 0
        for j in high:
            if produced >= max_deliverables:
                break
            job = Job(
                platform=j["platform"], job_id=j["job_id"],
                title=j["title"], company=j["company"],
                url=j.get("url"), description=j.get("description"),
                skills=j.get("skills"), category=j.get("category"),
                budget_min=j.get("budget_min"), budget_max=j.get("budget_max"),
                rate_min=j.get("rate_min"), rate_max=j.get("rate_max"),
            )
            role = _detect_role(job)

            # Klasifikasi cerdas (LLM) + fallback heuristik
            cls = classify_job(job)

            # Skip job yang tidak relevan dengan role kita
            if not cls["relevant"]:
                continue

            # Role dari klasifikasi (LLM bisa mengoreksi role regex)
            role = cls["role"]
            subtype = cls.get("subtype", "")

            # Skip kalau sudah ada kontrak untuk job ini
            if get_contract_by_job(conn, job.platform, job.job_id):
                continue

            # Generate proposal
            proposal = generate_proposal(job)
            stats["proposals"] += 1

            # Buat kontrak (simulasi tawaran diterima)
            budget = j.get("budget_min") or j.get("budget_max")
            rate = j.get("rate_min") or j.get("rate_max")
            cid = create_contract(
                conn, job.platform, job.job_id,
                title=job.title, company=job.company, url=job.url,
                rate=rate, budget=budget,
                notes=f"Auto-proposal: {proposal[:200]}",
            )
            stats["contracts_created"] += 1

            # Produksi deliverable nyata
            try:
                result = execute_job(job, role=role, subtype=subtype)
                # Catat deliverable + set delivered
                from .workflow import add_deliverable, set_status
                add_deliverable(
                    conn, cid, name=result["summary"], path=result["path"],
                    description=f"{role} deliverable: {', '.join(result['files'][:5])}",
                )
                set_status(conn, cid, "delivered")
                stats["deliverables"] += 1
                produced += 1
                _log(f"[{role}] produced: {result['summary']}")
            except Exception as e:
                stats["errors"].append(f"{job.title}: {e}")
                _log(f"ERROR producing {job.title}: {e}")

        # --- 5. Report Telegram ---
        reporter = TelegramReporter()
        if reporter.token and reporter.channel_id:
            summ = format_daily_summary(
                [Job(platform=j["platform"], job_id=j["job_id"],
                     title=j["title"], company=j["company"])
                 for j in high[:10]],
                applied=stats["contracts_created"],
            )
            reporter.send_message(summ)
            _log("reported to Telegram")

        # --- 6. Google Workspace (opsional) ---
        if report_google:
            try:
                from .google_drive import create_drive_folder, create_google_sheet, append_google_sheet
                folder = create_drive_folder(f"Jobbot Autopilot {datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
                sheet_id, url = create_google_sheet("Autopilot Summary", headers=[
                    "time", "scraped", "high_value", "proposals",
                    "contracts", "deliverables"], folder_id=folder)
                append_google_sheet(sheet_id, "A2", [[
                    _now(), stats["scraped"], stats["high_value"],
                    stats["proposals"], stats["contracts_created"],
                    stats["deliverables"],
                ]])
                _log(f"Google sheet: {url}")
            except Exception as e:
                _log(f"Google report skipped: {e}")

        # --- 7. Email report (opsional) ---
        if report_email:
            try:
                from .email_report import EmailReporter
                emailer = EmailReporter()
                if emailer.user and emailer.password and emailer.recipient:
                    email_jobs = [
                        Job(platform=j["platform"], job_id=j["job_id"],
                            title=j["title"], company=j["company"],
                            url=j.get("url"), rate_min=j.get("rate_min"),
                            rate_max=j.get("rate_max"),
                            budget_min=j.get("budget_min"),
                            budget_max=j.get("budget_max"))
                        for j in high[:20]
                    ]
                    ok = emailer.send(
                        email_jobs, applied=stats["contracts_created"],
                        subject=f"[Jobbot] Autopilot report - {datetime.now(timezone.utc):%Y-%m-%d %H:%M}",
                    )
                    _log(f"email report sent: {ok}")
                else:
                    _log("email report skipped: JOB_EMAIL_* belum diset")
            except Exception as e:
                _log(f"email report failed: {e}")

        # --- Earnings snapshot ---
        stats["earnings_today"] = get_earnings_summary(conn)["today_usd"]

    finally:
        conn.close()

    return stats


def run_forever(interval_seconds: int = 3600, max_cycles: int = None, **kwargs):
    """Long-running loop: jalankan siklus berulang tanpa interaksi."""
    cycle = 0
    _log(f"autopilot started (interval={interval_seconds}s, max_cycles={max_cycles or 'infinite'})")
    while max_cycles is None or cycle < max_cycles:
        try:
            stats = run_cycle(**kwargs)
            _log(f"cycle #{cycle+1} done: {stats}")
        except Exception as e:
            _log(f"cycle #{cycle+1} ERROR: {e}")
        cycle += 1
        if max_cycles is not None and cycle >= max_cycles:
            break
        _log(f"sleeping {interval_seconds}s...")
        time.sleep(interval_seconds)


def main():
    parser = argparse.ArgumentParser(description="Jobbot autonomous pipeline")
    parser.add_argument("--interval", type=int, default=0,
                        help="Detik antar siklus (0 = sekali jalan)")
    parser.add_argument("--max-cycles", type=int, default=None,
                        help="Maksimal siklus (default infinite bila interval>0)")
    parser.add_argument("--max-deliverables", type=int, default=3,
                        help="Maksimal deliverable per siklus")
    parser.add_argument("--min-budget", type=float, default=0.0,
                        help="Filter minimal budget (USD)")
    parser.add_argument("--keywords", default=None, help="Keyword dipisah koma")
    parser.add_argument("--platforms", default=None, help="Platform dipisah koma")
    parser.add_argument("--report-google", action="store_true",
                        help="Juga buat laporan Google Workspace")
    parser.add_argument("--report-email", action="store_true",
                        help="Juga kirim laporan email via SMTP")
    args = parser.parse_args()

    kwargs = dict(
        max_deliverables=args.max_deliverables,
        min_budget=args.min_budget,
        keywords=args.keywords.split(",") if args.keywords else None,
        platforms=args.platforms.split(",") if args.platforms else None,
        report_google=args.report_google,
        report_email=args.report_email,
    )

    if args.interval > 0:
        run_forever(args.interval, args.max_cycles, **kwargs)
    else:
        stats = run_cycle(**kwargs)
        print("\n=== AUTOPILOT CYCLE RESULT ===")
        for k, v in stats.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
