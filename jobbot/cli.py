"""jobbot/cli.py - Entrypoint CLI untuk jobbot.

Cara pakai:
  python -m jobbot.cli --run                 # scraping + report sekali
  python -m jobbot.cli --run --keywords "python"  # keyword custom
  python -m jobbot.cli --list               # tampilkan job di DB
  python -m jobbot.cli --report             # report manual
  python -m jobbot.cli --setup-oauth        # setup Google OAuth
  python -m jobbot.cli --tick --interval 3600  # background ticker
"""
import argparse
import json

from . import db
from .models import get_all_jobs, get_progress, application_count
from .scraper import scrape_all, SCRAPERS
from .reporter import TelegramReporter, format_daily_summary


def cmd_run(args):
    """Scrapa + report sekali."""
    db.init_db()
    from .autopilot import DEFAULT_KEYWORDS, DEFAULT_PLATFORMS
    keywords = args.keywords.split(",") if args.keywords else DEFAULT_KEYWORDS
    platforms = args.platforms.split(",") if args.platforms else DEFAULT_PLATFORMS
    print(f"[cli] scraping {len(platforms)} platforms...")
    results = scrape_all(keywords, platforms, args.limit)
    total = sum(len(v) for v in results.values())
    print(f"[cli] found {total} jobs")
    for platform, jobs in results.items():
        print(f"[cli]   {platform}: {len(jobs)} jobs")

    # Report
    reporter = TelegramReporter()
    if reporter.token and reporter.channel_id:
        all_jobs = [j for v in results.values() for j in v]
        reporter.send_jobs_batch(all_jobs)
        reporter.send_message(format_daily_summary(all_jobs))
        print("[cli] reported to Telegram")
    else:
        print("[cli] Telegram belum diset, skip report")

    return results


def cmd_list(args):
    """Tampilkan job di DB."""
    db.init_db()
    conn = db.get_conn()
    try:
        jobs = get_all_jobs(conn)
        print(f"[cli] {len(jobs)} jobs in DB")
        for j in jobs[:args.limit]:
            print(f"  - {j['platform']}: {j['title']} ({j['company']})")
    finally:
        conn.close()


def cmd_report(args):
    """Report manual."""
    db.init_db()
    conn = db.get_conn()
    try:
        jobs = get_all_jobs(conn)
        reporter = TelegramReporter()
        if reporter.token and reporter.channel_id:
            reporter.send_jobs_batch(jobs)
            reporter.send_message(format_daily_summary(jobs))
            print(f"[cli] reported {len(jobs)} jobs to Telegram")
        else:
            print("[cli] Telegram belum diset")
    finally:
        conn.close()


def cmd_setup_oauth(args):
    """Setup Google OAuth."""
    from .google_drive import setup_oauth
    setup_oauth()


def cmd_tick(args):
    """Background ticker."""
    from .cron import tick
    tick(interval_seconds=args.interval, max_iterations=args.iterations)


def cmd_stats(args):
    """Tampilkan statistik progress."""
    db.init_db()
    conn = db.get_conn()
    try:
        progress = get_progress(conn)
        print(json.dumps(progress, indent=2, default=str))
    finally:
        conn.close()


def cmd_export(args):
    """Export jobs ke Google Sheets atau CSV."""
    import csv
    db.init_db()
    conn = db.get_conn()
    try:
        jobs = get_all_jobs(conn)
        if not jobs:
            print("[cli] tidak ada job di DB")
            return
        headers = ["platform", "title", "company", "location",
                   "rate_min", "rate_max", "rate_currency", "url",
                   "posted_at", "skills", "category", "job_type"]
        rows = [[str(j.get(h) or "") for h in headers] for j in jobs]

        if args.format == "csv":
            out = args.output or "jobbot/jobs_export.csv"
            with open(out, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(headers)
                w.writerows(rows)
            print(f"[cli] exported {len(rows)} jobs to {out}")
        elif args.format == "sheet":
            from .google_drive import create_google_sheet, append_google_sheet
            sheet_id, url = create_google_sheet(
                args.title or "Jobbot Jobs", headers=headers,
                folder_id=args.folder_id,
            )
            append_google_sheet(sheet_id, "A2", rows)
            print(f"[cli] exported {len(rows)} jobs to sheet {url}")
    finally:
        conn.close()


def cmd_gdrive(args):
    """Buat laporan harian lengkap ke Google Workspace (Sheet + Doc + Drive)."""
    import csv
    import io
    from datetime import datetime, timezone

    db.init_db()
    conn = db.get_conn()
    try:
        from .models import get_earnings_summary, get_earnings
        from .workflow import contract_summary
        from .google_drive import (
            create_drive_folder, create_google_sheet, append_google_sheet,
            create_google_doc, upload_file_to_drive,
        )

        jobs = get_all_jobs(conn)
        earnings = get_earnings_summary(conn)
        contracts = contract_summary(conn)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # 1. Folder harian
        folder_id = create_drive_folder(f"Jobbot Report {today}")

        # 2. Google Sheet ringkasan
        headers = ["date", "jobs_found", "applications", "earnings_today_usd",
                   "earnings_total_usd", "target_daily_usd", "today_pct",
                   "contracts_active", "contracts_completed"]
        row = [[
            today, len(jobs), application_count(conn),
            earnings["today_usd"], earnings["total_usd"],
            earnings["target_daily_usd"], earnings["today_pct"],
            contracts.get("active", 0), contracts.get("completed", 0),
        ]]
        sheet_id, sheet_url = create_google_sheet(
            f"Jobbot Daily {today}", headers=headers, folder_id=folder_id)
        append_google_sheet(sheet_id, "A2", row)

        # 3. CSV jobs -> upload ke Drive
        csv_buf = io.StringIO()
        w = csv.writer(csv_buf)
        w.writerow(["platform", "title", "company", "budget_min", "budget_max",
                    "url", "posted_at"])
        for j in jobs:
            w.writerow([j.get("platform"), j.get("title"), j.get("company"),
                        j.get("budget_min"), j.get("budget_max"),
                        j.get("url"), j.get("posted_at")])
        csv_path = f"/tmp/jobbot_jobs_{today}.csv"
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write(csv_buf.getvalue())
        upload_file_to_drive(csv_path, folder_id=folder_id,
                             filename=f"jobs_{today}.csv")

        # 4. Google Doc laporan naratif
        doc_content = (
            f"JOBOT DAILY REPORT — {today}\n\n"
            f"Jobs found: {len(jobs)}\n"
            f"Applications: {application_count(conn)}\n"
            f"Earnings today: ${earnings['today_usd']:.2f}\n"
            f"Earnings total: ${earnings['total_usd']:.2f}\n"
            f"Target daily: ${earnings['target_daily_usd']:.2f} "
            f"({earnings['today_pct']}%)\n\n"
            f"Contracts: {contracts.get('active', 0)} active, "
            f"{contracts.get('completed', 0)} completed, "
            f"{contracts.get('revision', 0)} in revision\n\n"
            f"Sheet: {sheet_url}\n"
        )
        create_google_doc(f"Jobbot Report {today}", doc_content,
                          folder_id=folder_id)

        print(f"[cli] Google Workspace report selesai. Folder: {folder_id}")
        print(f"[cli] Sheet: {sheet_url}")
    finally:
        conn.close()


def cmd_execute(args):
    """Produksi deliverable nyata untuk satu job/role (developer/designer/writer/web3)."""
    from .executor import execute_job
    from .models import Job

    db.init_db()
    conn = db.get_conn()
    try:
        job = None
        if args.job_id:
            from .models import get_all_jobs
            for j in get_all_jobs(conn):
                if j["job_id"] == args.job_id:
                    job = Job(
                        platform=j["platform"], job_id=j["job_id"],
                        title=j["title"], company=j["company"],
                        url=j.get("url"), description=j.get("description"),
                        skills=j.get("skills"), category=j.get("category"),
                    )
                    break
        if job is None:
            # Buat Job dari argumen CLI (untuk test manual)
            job = Job(
                platform=args.platform or "manual", job_id=args.job_id or "manual",
                title=args.title or "Project", company=args.company or "Client",
                url=args.url or "", description=args.description or "",
            )
        result = execute_job(job, role=args.role, publish_github=args.publish_github,
                             repo_name=args.repo_name, auto_merge=args.auto_merge,
                             framework=args.framework)
        print(f"[cli] deliverable produced: {result['summary']}")
        print(f"[cli] path: {result['path']}")
        print(f"[cli] files ({len(result['files'])}):")
        for f in result["files"]:
            print(f"  - {f}")
        if result.get("github"):
            g = result["github"]
            print(f"[cli] GitHub repo: {g['repo']}")
            print(f"[cli] PR #{g['pr_number']}: {g['pr_url']}")
            print(f"[cli] merged: {g['merged']}")
        elif result.get("github_error"):
            print(f"[cli] GitHub publish error: {result['github_error']}")
    finally:
        conn.close()


def cmd_autopilot(args):
    """Jalankan pipeline autonomous end-to-end (tanpa interaksi)."""
    from .autopilot import run_cycle, run_forever
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


def cmd_bot(args):
    """Bot Telegram dua arah (terima file & perintah)."""
    from .telegram_bot import run_bot
    run_bot(forever=args.forever, admin_id=args.admin_id)


def cmd_email(args):
    """Kirim laporan email via SMTP."""
    from .models import get_all_jobs, Job
    from .email_report import EmailReporter
    db.init_db()
    conn = db.get_conn()
    try:
        rows = get_all_jobs(conn)
        jobs = [
            Job(platform=j["platform"], job_id=j["job_id"],
                title=j["title"], company=j["company"],
                url=j.get("url"), rate_min=j.get("rate_min"),
                rate_max=j.get("rate_max"),
                budget_min=j.get("budget_min"),
                budget_max=j.get("budget_max"))
            for j in rows
        ]
        emailer = EmailReporter()
        if args.recipient:
            emailer.recipient = args.recipient
        ok = emailer.send(jobs, applied=args.applied, subject=args.subject)
        print(f"[cli] email sent: {ok}")
    finally:
        conn.close()


def cmd_inbox(args):
    """Cek email masuk (belum dibaca) via IMAP."""
    from .imap_inbox import ImapInbox
    imap = ImapInbox()
    emails = imap.list_unread(limit=args.limit)
    if not emails:
        print("[cli] tidak ada email masuk (belum dibaca)")
        return
    print(f"[cli] {len(emails)} email masuk (belum dibaca):")
    for e in emails:
        sender = e["from"].split("<")[0].strip() or e["from"]
        print(f"  #{e['num']} | {e['subject']} | dari: {sender} | {e['date'][:16]}")


def cmd_reply(args):
    """Balas email masuk via IMAP+SMTP (cerdas: deteksi intent)."""
    from .imap_inbox import ImapInbox
    from .auto_reply import generate_reply
    imap = ImapInbox()
    if args.num is None:
        # Balas semua email belum dibaca
        emails = imap.list_unread(limit=args.limit)
        if not emails:
            print("[cli] tidak ada email untuk dibalas")
            return
        for e in emails:
            body, intent = generate_reply(e)
            if args.body:
                body = args.body
                intent = "manual"
            ok = imap.reply_email(e["num"], body)
            print(f"[cli] balas #{e['num']} ({e['from']}) [{intent}]: {'OK' if ok else 'GAGAL'}")
    else:
        info = imap.read_email(args.num)
        if not info:
            print(f"[cli] email #{args.num} tidak ditemukan")
            return
        body, intent = generate_reply(info)
        if args.body:
            body = args.body
            intent = "manual"
        ok = imap.reply_email(args.num, body)
        print(f"[cli] balas #{args.num} ({info['from']}) [{intent}]: {'OK' if ok else 'GAGAL'}")


def cmd_watch(args):
    """Watch inbox realtime (polling) + auto-reply opsional."""
    from .imap_inbox import run_watch
    run_watch(interval=args.interval, reply_body=args.reply_body,
              max_iterations=args.iterations, smart=args.smart)


def cmd_apply(args):
    """Catat aplikasi lamaran ke DB."""
    from .models import add_application
    db.init_db()
    conn = db.get_conn()
    try:
        app = {
            "platform": args.platform,
            "job_id": args.job_id,
            "title": args.title,
            "url": args.url,
            "proposal_amount": args.amount,
            "status": "applied",
            "applied_at": args.date,
            "feedback": args.feedback,
        }
        add_application(conn, app)
        print(f"[cli] application recorded: {args.title}")
    finally:
        conn.close()


def cmd_earnings(args):
    """Catat & tampilkan pendapatan harian vs target $50."""
    from .models import add_earning, get_earnings, get_earnings_summary
    db.init_db()
    conn = db.get_conn()
    try:
        if args.add is not None:
            add_earning(conn, args.add, date=args.date,
                        source=args.source, note=args.note)
            print(f"[cli] recorded earning ${args.add} ({args.date or 'today'})")

        summary = get_earnings_summary(conn)
        print("\n=== EARNINGS SUMMARY ===")
        print(f"  Target harian : ${summary['target_daily_usd']:.0f}")
        print(f"  Hari ini      : ${summary['today_usd']:.2f} "
              f"({summary['today_pct']}%)")
        print(f"  Sisa target   : ${summary['remaining_today']:.2f}")
        print(f"  Total semua   : ${summary['total_usd']:.2f}")

        earnings = get_earnings(conn, date=args.date)
        if earnings:
            print(f"\n  Riwayat ({len(earnings)} entri):")
            for e in earnings:
                src = f" [{e['source']}]" if e['source'] else ""
                note = f" — {e['note']}" if e['note'] else ""
                print(f"    {e['date']}  ${e['amount']:.2f}{src}{note}")
    finally:
        conn.close()


def cmd_top(args):
    """Tampilkan job high-value (budget/rate tertinggi)."""
    from .models import get_high_value_jobs
    db.init_db()
    conn = db.get_conn()
    try:
        jobs = get_high_value_jobs(conn, min_budget=args.min_budget,
                                   min_rate=args.min_rate, limit=args.limit)
        if not jobs:
            print("[cli] tidak ada job yang cocok dengan filter")
            return
        print(f"[cli] {len(jobs)} high-value jobs:")
        for j in jobs:
            budget = j.get("budget_min") or j.get("budget_max")
            rate = j.get("rate_min") or j.get("rate_max")
            val = ""
            if budget:
                val = f"budget ${budget:,.0f}"
            elif rate:
                val = f"rate ${rate:,.0f}/hr"
            print(f"  - {val:20s} | {j['platform']:14s} | {j['title']} @ {j['company']}")
    finally:
        conn.close()


def cmd_proposal(args):
    """Generate proposal untuk job (satu atau batch)."""
    import json
    from .models import get_all_jobs, get_high_value_jobs
    from .proposal import generate_proposal
    from .models import Job

    db.init_db()
    conn = db.get_conn()
    try:
        # Ambil job target
        if args.job_id:
            jobs = [j for j in get_all_jobs(conn) if j["job_id"] == args.job_id]
        elif args.top:
            jobs = get_high_value_jobs(conn, min_budget=args.min_budget,
                                       min_rate=args.min_rate, limit=args.limit)
        else:
            jobs = get_all_jobs(conn)[:args.limit]

        if not jobs:
            print("[cli] tidak ada job untuk dibuatkan proposal")
            return

        profile = None
        if args.profile:
            try:
                profile = json.loads(args.profile)
            except json.JSONDecodeError:
                print("[cli] --profile harus JSON valid, abaikan")
                profile = None

        for j in jobs:
            job = Job(
                platform=j["platform"], job_id=j["job_id"],
                title=j["title"], company=j["company"],
                skills=j.get("skills"), category=j.get("category"),
                description=j.get("description"),
            )
            proposal = generate_proposal(job, profile)
            print(f"\n{'='*60}")
            print(f"PROPOSAL for: {j['title']} @ {j['company']}")
            print(f"Platform: {j['platform']} | URL: {j.get('url') or '-'}")
            print(f"{'='*60}")
            print(proposal)
    finally:
        conn.close()


def cmd_contract(args):
    """Kelola siklus hidup kontrak pekerjaan."""
    from .workflow import (
        create_contract, list_contracts, get_contract, set_status,
        add_deliverable, list_deliverables, add_revision, complete_contract,
        contract_summary, get_contract_by_job,
    )
    db.init_db()
    conn = db.get_conn()
    try:
        if args.action == "create":
            cid = create_contract(
                conn, args.platform, args.job_id, title=args.title,
                company=args.company, url=args.url, rate=args.rate,
                budget=args.budget, deadline=args.deadline, notes=args.notes,
            )
            print(f"[cli] contract #{cid} created (accepted)")
        elif args.action == "list":
            contracts = list_contracts(conn, status=args.status)
            if not contracts:
                print("[cli] tidak ada kontrak")
                return
            for c in contracts:
                print(f"  #{c['id']} [{c['status']:12s}] {c['title']} @ {c['company']} "
                      f"(deadline: {c['deadline'] or '-'})")
        elif args.action == "status":
            if args.id is None:
                print("[cli] --id wajib untuk action status")
                return
            set_status(conn, args.id, args.status, deadline=args.deadline,
                       notes=args.notes)
            c = get_contract(conn, args.id)
            print(f"[cli] contract #{args.id} -> {c['status']}")
        elif args.action == "deliver":
            if args.id is None:
                print("[cli] --id wajib untuk action deliver")
                return
            did = add_deliverable(conn, args.id, args.name, path=args.path,
                                  description=args.description)
            set_status(conn, args.id, "delivered")
            print(f"[cli] deliverable #{did} recorded, contract #{args.id} -> delivered")
        elif args.action == "deliverables":
            if args.id is None:
                print("[cli] --id wajib")
                return
            for d in list_deliverables(conn, args.id):
                print(f"  v{d['version']} [{d['status']}] {d['name']} ({d['path'] or '-'})")
                if d.get("feedback"):
                    print(f"      feedback: {d['feedback']}")
        elif args.action == "revise":
            if args.id is None:
                print("[cli] --id wajib")
                return
            add_revision(conn, args.id, args.feedback or "")
            print(f"[cli] contract #{args.id} -> revision (feedback tersimpan)")
        elif args.action == "complete":
            if args.id is None:
                print("[cli] --id wajib")
                return
            complete_contract(conn, args.id, amount=args.amount,
                              source=args.source, note=args.note)
            print(f"[cli] contract #{args.id} -> completed"
                  + (f" (earning ${args.amount})" if args.amount else ""))
        elif args.action == "summary":
            s = contract_summary(conn)
            print("[cli] contract pipeline:")
            for k, v in s.items():
                print(f"  {k:12s}: {v}")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(prog="jobbot", description="Jobbot CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Scrapa + report sekali")
    p_run.add_argument("--keywords", help="Keyword dipisah koma")
    p_run.add_argument("--platforms", help="Platform dipisah koma")
    p_run.add_argument("--limit", type=int, default=20)
    p_run.set_defaults(func=cmd_run)

    p_list = sub.add_parser("list", help="Tampilkan job di DB")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.set_defaults(func=cmd_list)

    p_report = sub.add_parser("report", help="Report manual")
    p_report.set_defaults(func=cmd_report)

    p_oauth = sub.add_parser("setup-oauth", help="Setup Google OAuth")
    p_oauth.set_defaults(func=cmd_setup_oauth)

    p_tick = sub.add_parser("tick", help="Background ticker")
    p_tick.add_argument("--interval", type=int, default=3600)
    p_tick.add_argument("--iterations", type=int, default=None)
    p_tick.set_defaults(func=cmd_tick)

    p_stats = sub.add_parser("stats", help="Tampilkan statistik")
    p_stats.set_defaults(func=cmd_stats)

    p_export = sub.add_parser("export", help="Export jobs ke CSV/Google Sheets")
    p_export.add_argument("--format", choices=["csv", "sheet"], default="csv")
    p_export.add_argument("--output", help="Path output CSV")
    p_export.add_argument("--title", help="Judul Google Sheet")
    p_export.add_argument("--folder-id", help="Folder ID Google Drive")
    p_export.set_defaults(func=cmd_export)

    p_gdrive = sub.add_parser("gdrive", help="Buat laporan harian lengkap ke Google Workspace")
    p_gdrive.set_defaults(func=cmd_gdrive)

    p_exec = sub.add_parser("execute", help="Produksi deliverable nyata (developer/designer/writer/web3)")
    p_exec.add_argument("--job-id", help="Job ID dari DB (opsional)")
    p_exec.add_argument("--role", choices=["developer", "designer", "writer", "web3", "data", "security"],
                        help="Role eksplisit (default: auto-detect)")
    p_exec.add_argument("--platform", help="Platform (untuk job manual)")
    p_exec.add_argument("--title", help="Judul pekerjaan (untuk job manual)")
    p_exec.add_argument("--company", help="Nama klien (untuk job manual)")
    p_exec.add_argument("--url", default="")
    p_exec.add_argument("--description", default="")
    p_exec.add_argument("--publish-github", action="store_true",
                        help="Push deliverable ke GitHub (buat repo + buka PR)")
    p_exec.add_argument("--repo-name", default=None, help="Nama repo GitHub (default = slug)")
    p_exec.add_argument("--auto-merge", action="store_true",
                        help="Otomatis review APPROVE + merge PR")
    p_exec.set_defaults(func=cmd_execute)

    p_auto = sub.add_parser("autopilot", help="Pipeline autonomous end-to-end (tanpa interaksi)")
    p_auto.add_argument("--interval", type=int, default=0,
                        help="Detik antar siklus (0 = sekali jalan)")
    p_auto.add_argument("--max-cycles", type=int, default=None,
                        help="Maksimal siklus (default infinite bila interval>0)")
    p_auto.add_argument("--max-deliverables", type=int, default=3,
                        help="Maksimal deliverable per siklus")
    p_auto.add_argument("--min-budget", type=float, default=0.0,
                        help="Filter minimal budget (USD)")
    p_auto.add_argument("--keywords", default=None, help="Keyword dipisah koma")
    p_auto.add_argument("--platforms", default=None, help="Platform dipisah koma")
    p_auto.add_argument("--report-google", action="store_true",
                        help="Juga buat laporan Google Workspace")
    p_auto.add_argument("--report-email", action="store_true",
                        help="Juga kirim laporan email via SMTP")
    p_auto.set_defaults(func=cmd_autopilot)

    p_bot = sub.add_parser("bot", help="Bot Telegram dua arah (terima file & perintah)")
    p_bot.add_argument("--forever", action="store_true",
                       help="Polling terus-menerus (long-running)")
    p_bot.add_argument("--admin-id", default=None,
                       help="Chat ID admin (opsional, untuk batasi akses)")
    p_bot.set_defaults(func=cmd_bot)

    p_email = sub.add_parser("email", help="Kirim laporan email via SMTP")
    p_email.add_argument("--recipient", default=None, help="Email tujuan (default JOB_EMAIL_RECIPIENT)")
    p_email.add_argument("--applied", type=int, default=0, help="Jumlah aplikasi terkirim")
    p_email.add_argument("--subject", default=None, help="Subjek email")
    p_email.set_defaults(func=cmd_email)

    p_inbox = sub.add_parser("inbox", help="Cek email masuk (belum dibaca) via IMAP")
    p_inbox.add_argument("--limit", type=int, default=20, help="Maksimal email ditampilkan")
    p_inbox.set_defaults(func=cmd_inbox)

    p_reply = sub.add_parser("reply", help="Balas email masuk via IMAP+SMTP")
    p_reply.add_argument("--num", default=None, help="Nomor email (kosongkan = balas semua unread)")
    p_reply.add_argument("--body", default=None, help="Isi balasan (default template otomatis)")
    p_reply.add_argument("--limit", type=int, default=20, help="Maksimal email dibalas bila --num kosong")
    p_reply.set_defaults(func=cmd_reply)

    p_watch = sub.add_parser("watch", help="Watch inbox realtime (polling) + auto-reply opsional")
    p_watch.add_argument("--interval", type=int, default=60, help="Detik antar polling")
    p_watch.add_argument("--iterations", type=int, default=None, help="Maksimal iterasi (default infinite)")
    p_watch.add_argument("--reply-body", default=None, help="Isi auto-reply (default: tidak balas, hanya log)")
    p_watch.add_argument("--smart", action="store_true", help="Auto-reply cerdas (deteksi intent + balas kontekstual)")
    p_watch.set_defaults(func=cmd_watch)

    p_apply = sub.add_parser("apply", help="Catat aplikasi lamaran")
    p_apply.add_argument("--platform", required=True)
    p_apply.add_argument("--job-id", required=True)
    p_apply.add_argument("--title", required=True)
    p_apply.add_argument("--url", default="")
    p_apply.add_argument("--amount", help="Proposal amount (USD)")
    p_apply.add_argument("--date", default=None)
    p_apply.add_argument("--feedback", default=None)
    p_apply.set_defaults(func=cmd_apply)

    p_earn = sub.add_parser("earnings", help="Catat & track pendapatan harian")
    p_earn.add_argument("--add", type=float, help="Tambahkan pendapatan (USD)")
    p_earn.add_argument("--date", default=None, help="Tanggal (YYYY-MM-DD), default hari ini")
    p_earn.add_argument("--source", default=None, help="Sumber (mis. upwork)")
    p_earn.add_argument("--note", default=None, help="Catatan")
    p_earn.set_defaults(func=cmd_earnings)

    p_top = sub.add_parser("top", help="Tampilkan job high-value (budget/rate tertinggi)")
    p_top.add_argument("--min-budget", type=float, default=0.0, help="Min total budget (USD)")
    p_top.add_argument("--min-rate", type=float, default=0.0, help="Min rate/jam (USD)")
    p_top.add_argument("--limit", type=int, default=20)
    p_top.set_defaults(func=cmd_top)

    p_prop = sub.add_parser("proposal", help="Generate proposal/cover letter")
    p_prop.add_argument("--job-id", help="Job ID spesifik")
    p_prop.add_argument("--top", action="store_true", help="Generate untuk job high-value")
    p_prop.add_argument("--min-budget", type=float, default=0.0)
    p_prop.add_argument("--min-rate", type=float, default=0.0)
    p_prop.add_argument("--limit", type=int, default=5)
    p_prop.add_argument("--profile", help="JSON override profil (mis. '{\"name\":\"John\"}')")
    p_prop.set_defaults(func=cmd_proposal)

    p_contract = sub.add_parser("contract", help="Kelola siklus hidup kontrak pekerjaan")
    p_contract.add_argument("action", choices=["create", "list", "status", "deliver",
                                               "deliverables", "revise", "complete", "summary"])
    p_contract.add_argument("--id", type=int, help="Contract ID")
    p_contract.add_argument("--platform", help="Platform")
    p_contract.add_argument("--job-id", help="Job ID")
    p_contract.add_argument("--title", help="Judul pekerjaan")
    p_contract.add_argument("--company", help="Nama klien/perusahaan")
    p_contract.add_argument("--url", default="")
    p_contract.add_argument("--rate", type=float, help="Rate USD/jam")
    p_contract.add_argument("--budget", type=float, help="Total budget USD")
    p_contract.add_argument("--deadline", help="Deadline (YYYY-MM-DD)")
    p_contract.add_argument("--notes", help="Catatan")
    p_contract.add_argument("--status", help="Status kontrak")
    p_contract.add_argument("--name", help="Nama deliverable")
    p_contract.add_argument("--path", help="Path file deliverable")
    p_contract.add_argument("--description", help="Deskripsi deliverable")
    p_contract.add_argument("--feedback", help="Feedback revisi")
    p_contract.add_argument("--amount", type=float, help="Jumlah pembayaran USD")
    p_contract.add_argument("--source", help="Sumber pembayaran")
    p_contract.add_argument("--note", help="Catatan pembayaran")
    p_contract.set_defaults(func=cmd_contract)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
