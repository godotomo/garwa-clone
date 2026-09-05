"""jobbot/scraper.py - Core multi-platform job scraper.

Mengadopsi pola hermes product-price-monitor: foreground collection sekali,
tapi di sini kita jalankan berkala (via cron) untuk mengumpulkan lowongan
baru dari banyak platform freelance luar (bayar USD).

Platform yang didukung (endpoint publik, tanpa auth):
  - Upwork          (scraping halaman search)
  - Freelancer.com  (scraping)
  - Indeed          (scraping)
  - GitHub Jobs     (via GitHub Search API)
  - Remote OK       (public JSON API)
  - We Work Remotely  (RSS feed)
  - Remotive        (public JSON API)

Setiap scraper mengembalikan list[Job]. Dedup & storage ditangani di models.py.
"""
import time
from typing import Optional

import requests

from .models import Job, upsert_job
from . import db


class ScraperError(Exception):
    pass


class BaseScraper:
    platform = "base"
    base_url = ""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def fetch(self, url: str, params: Optional[dict] = None) -> requests.Response:
        try:
            resp = requests.get(
                url, headers=self.headers, params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            raise ScraperError(f"{self.platform}: fetch {url} failed -- {e}")


class UpworkScraper(BaseScraper):
    """Scrapa halaman search Upwork (tanpa auth). Endpoint API v2 butuh token."""
    platform = "upwork"
    base_url = "https://www.upwork.com/api/v2/jobs/search"
    search_page = "https://www.upwork.com/search/"

    def search(self, keywords: list[str], limit: int = 20) -> list[Job]:
        jobs = []
        for kw in keywords:
            try:
                resp = self.fetch(self.search_page, params={"q": kw})
                jobs.extend(self._parse_html(resp.text, limit))
            except ScraperError:
                continue
            time.sleep(1)
            if len(jobs) >= limit:
                break
        return jobs[:limit]

    def _parse_html(self, html: str, limit: int = 20) -> list[Job]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        # Upwork me-load job via JSON-LD di <script type="application/ld+json">
        scripts = soup.find_all("script", {"type": "application/ld+json"})
        for script in scripts:
            try:
                data = __import__("json").loads(script.string or "")
            except Exception:
                continue
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "JobPosting":
                        jobs.append(self._parse_jobposting(item))
            elif isinstance(data, dict) and data.get("@type") == "JobPosting":
                jobs.append(self._parse_jobposting(data))
        return jobs

    def _parse_jobposting(self, item: dict) -> Job:
        jobref = item.get("jobRef") or item.get("id")
        url = item.get("url") or item.get("alternateUrl")
        return Job(
            platform=self.platform,
            job_id=str(jobref),
            title=item.get("title"),
            company=item.get("hiringOrganization", {}).get("name")
            if isinstance(item.get("hiringOrganization"), dict) else None,
            location=item.get("workplaceLocation", {}).get("address", {}).get("addressLocality")
            if isinstance(item.get("workplaceLocation"), dict) else None,
            description=(item.get("description") or "")[:5000],
            url=url,
            posted_at=item.get("datePosted"),
        )


class FreelancerScraper(BaseScraper):
    platform = "freelancer"
    search_page = "https://www.freelancer.com/jobs/"

    def search(self, keywords: list[str], limit: int = 20) -> list[Job]:
        from bs4 import BeautifulSoup
        jobs = []
        for kw in keywords:
            try:
                resp = self.fetch(self.search_page, params={"query": kw})
                soup = BeautifulSoup(resp.text, "html.parser")
                for card in soup.select("div.job-card, div.JobsSearchCard")[:limit]:
                    title_el = card.select_one("a.job-card-title, h2")
                    link_el = card.select_one("a[href*='/jobs/']")
                    if not title_el or not link_el:
                        continue
                    href = link_el.get("href", "")
                    job_id = href.split("/")[-1] if href else None
                    jobs.append(Job(
                        platform=self.platform,
                        job_id=str(job_id),
                        title=title_el.get_text(strip=True),
                        company=card.select_one(".job-card-client").get_text(strip=True)
                        if card.select_one(".job-card-client") else None,
                        url=f"https://www.freelancer.com{href}" if href.startswith("/") else href,
                    ))
            except ScraperError:
                continue
            time.sleep(1)
            if len(jobs) >= limit:
                break
        return jobs[:limit]


class IndeedScraper(BaseScraper):
    platform = "indeed"
    base_url = "https://us.indeed.com/jobs"

    def search(self, keywords: list[str], limit: int = 20) -> list[Job]:
        from bs4 import BeautifulSoup
        jobs = []
        for kw in keywords:
            try:
                resp = self.fetch(
                    f"{self.base_url}/",
                    params={"q": kw, "limit": 30, "fromage": "day", "vfl": 3},
                )
                soup = BeautifulSoup(resp.text, "html.parser")
                for row in soup.select("div[data-jk]")[:limit]:
                    job_id = row.get("data-jk")
                    title_el = row.select_one("h2 a, span.jobtitle")
                    company_el = row.select_one("div.companyName")
                    desc_el = row.select_one("div.description")
                    jobs.append(Job(
                        platform=self.platform,
                        job_id=str(job_id),
                        title=title_el.get_text(strip=True) if title_el else None,
                        company=company_el.get_text(strip=True) if company_el else None,
                        description=desc_el.get_text(strip=True) if desc_el else None,
                        url=f"https://us.indeed.com/viewjob?jk={job_id}",
                    ))
            except ScraperError:
                continue
            time.sleep(1)
            if len(jobs) >= limit:
                break
        return jobs[:limit]


class GitHubJobsScraper(BaseScraper):
    platform = "github-jobs"
    base_url = "https://api.github.com/search/jobs"

    def search(self, keywords: list[str], limit: int = 20) -> list[Job]:
        jobs = []
        token = db.get_env("GITHUB_TOKEN")
        for kw in keywords:
            try:
                resp = requests.get(
                    f"{self.base_url}",
                    headers={
                        **self.headers,
                        "Authorization": f"Bearer {token}" if token else "",
                    },
                    params={"q": kw, "per_page": limit},
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("items", []):
                    jobs.append(self._parse(item))
            except requests.RequestException:
                continue
            time.sleep(1)
            if len(jobs) >= limit:
                break
        return jobs[:limit]

    def _parse(self, item: dict) -> Job:
        return Job(
            platform=self.platform,
            job_id=str(item.get("id")),
            title=item.get("title"),
            company=item.get("company", {}).get("name") if item.get("company") else None,
            location=item.get("location"),
            description=item.get("description"),
            url=item.get("html_url"),
            posted_at=item.get("created_at"),
            skills=[s["name"] for s in item.get("skills", [])],
            is_remote=1 if item.get("remote") else 0,
        )


class RemoteOKScraper(BaseScraper):
    platform = "remote-ok"
    base_url = "https://remoteok.com/api"

    def search(self, keywords: list[str], limit: int = 20) -> list[Job]:
        jobs = []
        try:
            resp = self.fetch(self.base_url)
            data = resp.json()
            # RemoteOK API: item pertama adalah metadata (bukan job), skip.
            for item in data[1:]:
                if not item.get("id") or not item.get("position"):
                    continue
                jobs.append(self._parse(item))
                if len(jobs) >= limit:
                    break
        except ScraperError:
            pass
        return jobs

    def _parse(self, item: dict) -> Job:
        return Job(
            platform=self.platform,
            job_id=str(item.get("id")),
            title=item.get("position"),
            company=item.get("company"),
            location=item.get("location"),
            budget_min=item.get("salary_min"),
            budget_max=item.get("salary_max"),
            rate_currency="USD",
            description=item.get("description"),
            url=item.get("url"),
            posted_at=item.get("dateUTC"),
            category=item.get("tag") if isinstance(item.get("tag"), str) else None,
            job_type=item.get("type"),
            is_remote=1,
        )


class WeWorkRemotelyScraper(BaseScraper):
    platform = "we-work-remotely"
    base_url = "https://weworkremotely.com/feeds/jobs.rss"

    def search(self, keywords: list[str], limit: int = 20) -> list[Job]:
        from bs4 import BeautifulSoup
        jobs = []
        try:
            resp = self.fetch(self.base_url)
            soup = BeautifulSoup(resp.text, "xml")
            for el in soup.find_all("item")[:limit]:
                jobs.append(self._parse(el))
        except ScraperError:
            pass
        return jobs

    def _parse(self, el) -> Job:
        guid = el.find("guid")
        return Job(
            platform=self.platform,
            job_id=str(guid.text.strip()) if guid is not None else None,
            title=el.find("title").text.strip(),
            company=el.find("company").text.strip(),
            location=el.find("location").text.strip(),
            description=(el.find("description").text.strip() or "")[:5000],
            url=el.find("link").text.strip(),
            posted_at=el.find("pubDate").text.strip(),
            category=el.find("category").text.strip() if el.find("category") else None,
            is_remote=1,
        )


class RemotiveScraper(BaseScraper):
    platform = "remotive"
    base_url = "https://remotive.com/api/remote-jobs"

    def search(self, keywords: list[str], limit: int = 20) -> list[Job]:
        jobs = []
        try:
            resp = self.fetch(self.base_url)
            data = resp.json()
            for item in data.get("jobs", [])[:limit]:
                jobs.append(self._parse(item))
        except ScraperError:
            pass
        return jobs

    def _parse(self, item: dict) -> Job:
        return Job(
            platform=self.platform,
            job_id=str(item.get("id")),
            title=item.get("title"),
            company=item.get("company_name"),
            location=item.get("country"),
            description=item.get("description"),
            url=item.get("url"),
            posted_at=item.get("published_at"),
            category=item.get("category"),
            job_type=item.get("job_type"),
            is_remote=1,
        )


class WorkingNomadsScraper(BaseScraper):
    """Working Nomads — agregator remote job (API publik keyless, terverifikasi)."""
    platform = "working-nomads"
    base_url = "https://www.workingnomads.com/api/exposed_jobs/"

    def search(self, keywords: list[str], limit: int = 20) -> list[Job]:
        jobs = []
        try:
            resp = self.fetch(self.base_url)
            data = resp.json()
            for item in data:
                jobs.append(self._parse(item))
                if len(jobs) >= limit:
                    break
        except ScraperError:
            pass
        return jobs

    def _parse(self, item: dict) -> Job:
        tags = item.get("tags")
        if isinstance(tags, list):
            tags = ",".join(tags)
        return Job(
            platform=self.platform,
            job_id=item.get("url") or item.get("title"),
            title=item.get("title"),
            company=item.get("company_name"),
            location=item.get("location"),
            description=(item.get("description") or "")[:5000],
            url=item.get("url"),
            posted_at=item.get("pub_date"),
            category=item.get("category_name"),
            skills=tags,
            is_remote=1,
        )


class JobicyScraper(BaseScraper):
    """Jobicy — remote job board (API publik keyless, field lengkap + salary)."""
    platform = "jobicy"
    base_url = "https://jobicy.com/api/v2/remote-jobs"

    def search(self, keywords: list[str], limit: int = 20) -> list[Job]:
        jobs = []
        try:
            resp = self.fetch(self.base_url, params={"count": limit})
            data = resp.json()
            for item in data.get("jobs", []):
                jobs.append(self._parse(item))
        except ScraperError:
            pass
        return jobs

    def _parse(self, item: dict) -> Job:
        industries = item.get("jobIndustry") or []
        job_types = item.get("jobType") or []
        # Jobicy salaryMin/salaryMax = gaji TAHUNAN (annual), bukan rate/jam.
        return Job(
            platform=self.platform,
            job_id=str(item.get("id")),
            title=item.get("jobTitle"),
            company=item.get("companyName"),
            location=item.get("jobGeo"),
            budget_min=item.get("salaryMin"),
            budget_max=item.get("salaryMax"),
            rate_currency=item.get("salaryCurrency") or "USD",
            description=(item.get("jobDescription") or item.get("jobExcerpt") or "")[:5000],
            url=item.get("url"),
            posted_at=item.get("pubDate"),
            category=",".join(industries) if industries else None,
            job_type=",".join(job_types) if job_types else None,
            is_remote=1,
        )


class ArbeitnowScraper(BaseScraper):
    """Arbeitnow — job board Eropa (API publik keyless, 175+ jobs)."""
    platform = "arbeitnow"
    base_url = "https://www.arbeitnow.com/api/job-board-api"

    def search(self, keywords: list[str], limit: int = 20) -> list[Job]:
        jobs = []
        try:
            resp = self.fetch(self.base_url)
            data = resp.json()
            for item in data.get("data", []):
                jobs.append(self._parse(item))
                if len(jobs) >= limit:
                    break
        except ScraperError:
            pass
        return jobs

    def _parse(self, item: dict) -> Job:
        tags = item.get("tags")
        if isinstance(tags, list):
            tags = ",".join(tags)
        job_types = item.get("job_types")
        if isinstance(job_types, list):
            job_types = ",".join(job_types)
        return Job(
            platform=self.platform,
            job_id=item.get("slug") or item.get("url"),
            title=item.get("title"),
            company=item.get("company_name"),
            location=item.get("location"),
            description=(item.get("description") or "")[:5000],
            url=item.get("url"),
            posted_at=item.get("created_at"),
            skills=tags,
            job_type=job_types,
            is_remote=1 if item.get("remote") else 0,
        )


class JobsColliderScraper(BaseScraper):
    """JobsCollider — agregator remote job (API publik keyless, salary tahunan).

    Endpoint: https://jobscollider.com/api/search-jobs
    - query (optional): kata kunci judul
    - category (optional): salah satu dari 16 kategori (software_development,
      data, design, devops, cybersecurity, writing, marketing, dll.)
    Catatan: hasil delayed 24 jam, update hourly, max 2000 jobs.
    """
    platform = "jobscollider"
    base_url = "https://jobscollider.com/api/search-jobs"

    CATEGORIES = [
        "software_development", "cybersecurity", "customer_service", "design",
        "marketing", "sales", "product", "business", "data", "devops",
        "finance_legal", "human_resources", "qa", "writing",
        "project_management", "all_others",
    ]

    def search(self, keywords: list[str], limit: int = 20) -> list[Job]:
        jobs = []
        # Coba query per keyword; kalau tidak ada keyword, ambil kategori umum.
        queries = keywords or [None]
        for q in queries:
            params = {"category": "software_development"}
            if q:
                params["query"] = q
            try:
                resp = self.fetch(self.base_url, params=params)
                data = resp.json()
                for item in data.get("jobs", []):
                    jobs.append(self._parse(item))
                    if len(jobs) >= limit:
                        break
            except (ScraperError, ValueError):
                pass
            if len(jobs) >= limit:
                break
            time.sleep(1)
        return jobs[:limit]

    def _parse(self, item: dict) -> Job:
        locations = item.get("locations") or []
        if isinstance(locations, list):
            location = ",".join(str(l) for l in locations)
        else:
            location = str(locations) if locations else None
        return Job(
            platform=self.platform,
            job_id=str(item.get("id")),
            title=item.get("title"),
            company=item.get("company_name"),
            location=location,
            budget_min=item.get("salary_min"),
            budget_max=item.get("salary_max"),
            rate_currency="USD",
            description=(item.get("description") or "")[:5000],
            url=item.get("url"),
            posted_at=item.get("published_at"),
            category=item.get("category"),
            job_type=item.get("seniority"),
            is_remote=1,
        )


class HackerOneScraper(BaseScraper):
    """HackerOne — directory program bug bounty (API publik, tanpa auth).

    Endpoint: https://hackerone.com/programs/search?query=<keyword>
    Mengembalikan program bounty (bukan lowongan kerja biasa). Setiap program
    punya meta.submission_state (open/closed), resolved_report_count, dll.
    Query keyword seperti "web", "crypto", "blockchain", "smart contract".
    """
    platform = "hackerone"
    base_url = "https://hackerone.com/programs/search"
    # HackerOne menolak Accept header default BaseScraper (406), butuh JSON murni.
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def search(self, keywords: list[str], limit: int = 20) -> list[Job]:
        jobs = []
        queries = keywords or ["web"]
        for q in queries:
            try:
                resp = self.fetch(self.base_url, params={"query": q})
                data = resp.json()
                for item in data.get("results", []):
                    jobs.append(self._parse(item))
                    if len(jobs) >= limit:
                        break
            except (ScraperError, ValueError):
                pass
            if len(jobs) >= limit:
                break
            time.sleep(1)
        return jobs[:limit]

    def _parse(self, item: dict) -> Job:
        meta = item.get("meta") or {}
        bounty_min = None
        bounty_max = None
        # HackerOne meta kadang berisi reward info (bila program punya bounty).
        if meta.get("bounty_min"):
            bounty_min = meta["bounty_min"]
        if meta.get("bounty_max"):
            bounty_max = meta["bounty_max"]
        url = item.get("url")
        if url and url.startswith("/"):
            url = "https://hackerone.com" + url
        return Job(
            platform=self.platform,
            job_id=str(item.get("id")),
            title=item.get("name"),
            company=item.get("handle") or item.get("name"),
            description=(item.get("stripped_policy") or item.get("about") or "")[:5000],
            url=url,
            budget_min=bounty_min,
            budget_max=bounty_max,
            rate_currency="USD",
            category="bug-bounty",
            job_type=meta.get("submission_state"),
            is_remote=1,
        )


class YesWeHackScraper(BaseScraper):
    """YesWeHack — directory program bug bounty (API publik, tanpa auth).

    Endpoint: https://api.yeswehack.com/programs
    Field lengkap: bounty_reward_min/max, scopes_count, reports_count,
    activity_area, type (bug-bounty/vdp), status.
    """
    platform = "yeswehack"
    base_url = "https://api.yeswehack.com/programs"

    def search(self, keywords: list[str], limit: int = 20) -> list[Job]:
        jobs = []
        try:
            resp = self.fetch(self.base_url)
            data = resp.json()
            for item in data.get("items", []):
                jobs.append(self._parse(item))
                if len(jobs) >= limit:
                    break
        except (ScraperError, ValueError):
            pass
        return jobs[:limit]

    def _parse(self, item: dict) -> Job:
        bu = item.get("business_unit") or {}
        title = item.get("title") or bu.get("name")
        return Job(
            platform=self.platform,
            job_id=str(item.get("slug") or item.get("pid") or title),
            title=title,
            company=bu.get("name") or title,
            location=item.get("country"),
            description=(bu.get("description") or "")[:5000],
            url=f"https://yeswehack.com/programs/{item.get('slug')}" if item.get("slug") else None,
            budget_min=item.get("bounty_reward_min"),
            budget_max=item.get("bounty_reward_max"),
            rate_currency=(bu.get("currency") or "USD"),
            category="bug-bounty",
            job_type=item.get("type"),
            is_remote=1,
            skills=f"scopes:{item.get('scopes_count')},reports:{item.get('reports_count')}",
        )


SCRAPERS = {
    "upwork": UpworkScraper,
    "freelancer": FreelancerScraper,
    "indeed": IndeedScraper,
    "github-jobs": GitHubJobsScraper,
    "remote-ok": RemoteOKScraper,
    "we-work-remotely": WeWorkRemotelyScraper,
    "remotive": RemotiveScraper,
    "working-nomads": WorkingNomadsScraper,
    "jobicy": JobicyScraper,
    "arbeitnow": ArbeitnowScraper,
    "jobscollider": JobsColliderScraper,
    "hackerone": HackerOneScraper,
    "yeswehack": YesWeHackScraper,
}


def get_scraper(platform: str) -> BaseScraper:
    if platform not in SCRAPERS:
        raise ScraperError(f"Unknown platform: {platform}")
    return SCRAPERS[platform]()


def scrape_platform(platform: str, keywords: list[str], limit: int = 20,
                    conn=None) -> list[Job]:
    """Scrapa satu platform, simpan ke DB. Return list[Job]."""
    if conn is None:
        conn = db.get_conn()
    scraper = get_scraper(platform)
    try:
        jobs = scraper.search(keywords, limit)
    except ScraperError as e:
        print(f"[scraper] {e}")
        jobs = []
    for job in jobs:
        upsert_job(conn, job)
    return jobs


def scrape_all(keywords: list[str], platforms: list[str] = None,
               limit: int = 20, conn=None) -> dict[str, list[Job]]:
    """Scrapa semua platform. Return dict {platform: [Job]}."""
    if conn is None:
        conn = db.get_conn()
    if platforms is None:
        platforms = list(SCRAPERS.keys())
    results = {}
    for platform in platforms:
        jobs = scrape_platform(platform, keywords, limit, conn=conn)
        if jobs:
            results[platform] = jobs
    return results