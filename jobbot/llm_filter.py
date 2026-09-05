"""jobbot/llm_filter.py - Filter relevansi & deteksi role berbasis LLM.

Menggantikan filter regex murni dengan klasifikasi cerdas via LLM
(OpenAI-compatible). Bila LLM tidak tersedia atau gagal, otomatis fallback
ke heuristik regex yang sudah ada — sehingga pipeline TIDAK pernah gagal
hanya karena LLM mati.

Konfigurasi (satu sumber kebenaran = config Garwa, dengan override JOB_*):
  Prioritas tiap nilai: env JOB_LLM_*  >  config Garwa (garwa.config)  >  default.

  - API key : JOB_LLM_API_KEY  > LLAMA_API_KEY (garwa.config)  > "" (fallback heuristik)
  - URL     : JOB_LLM_BASE_URL > LLAMA_URL (garwa.config)      > https://api.openai.com/v1
  - Model   : JOB_LLM_MODEL    > LLAMA_MODEL (garwa.config)    > gpt-4o-mini

  Catatan: LLAMA_URL dari Garwa adalah FULL endpoint (.../chat/completions),
  sedangkan JOB_LLM_BASE_URL adalah base URL (tanpa /chat/completions). Keduanya
  dinormalisasi menjadi endpoint chat/completions yang valid.

Output klasifikasi (dict):
  {
    "relevant": bool,          # apakah PASTI bisa dikerjakan langsung
    "role": str,               # developer | designer | writer | web3 | data | security
    "subtype": str,            # sub-spesialisasi (web/mobile/api/devops/cloud/qa/ml/...)
    "reason": str,             # alasan singkat (untuk log/debug)
    "source": "llm" | "heuristic",
  }
"""
import json
import os
from typing import Optional

from .models import Job
from .proposal import _detect_role


def _heuristic_relevant(job: Job) -> bool:
    """Fallback relevansi heuristik (lazy import untuk hindari circular)."""
    from .autopilot import _is_relevant
    return _is_relevant(job)


# --------------------------------------------------------------------------- #
# LLM plumbing
# --------------------------------------------------------------------------- #
def _garwa_llm_config() -> tuple[str, str, str]:
    """Ambil konfigurasi LLM dari config Garwa (garwa.config) sebagai fallback.

    Return (api_key, url, model). url adalah FULL endpoint chat/completions.
    """
    try:
        from garwa import config as garwa_config
        return (
            getattr(garwa_config, "LLAMA_API_KEY", "") or "",
            getattr(garwa_config, "LLAMA_URL", "") or "",
            getattr(garwa_config, "LLAMA_MODEL", "") or "",
        )
    except Exception:
        return "", "", ""


def _llm_available() -> bool:
    api_key, _, _ = _llm_config()
    return bool(api_key)


def _llm_config() -> tuple[str, str, str]:
    """Return (api_key, url, model) dengan prioritas JOB_LLM_* > garwa.config > default.

    url yang dikembalikan adalah FULL endpoint chat/completions.
    """
    garwa_key, garwa_url, garwa_model = _garwa_llm_config()

    api_key = os.environ.get("JOB_LLM_API_KEY") or garwa_key or ""
    model = os.environ.get("JOB_LLM_MODEL") or garwa_model or "gpt-4o-mini"

    # URL: JOB_LLM_BASE_URL (base) menang; fallback ke LLAMA_URL (full endpoint);
    # terakhir default OpenAI.
    base_url = os.environ.get("JOB_LLM_BASE_URL")
    if base_url:
        url = _ensure_chat_completions(base_url)
    elif garwa_url:
        url = _ensure_chat_completions(garwa_url)
    else:
        url = "https://api.openai.com/v1/chat/completions"

    return api_key, url, model


def _ensure_chat_completions(url: str) -> str:
    """Normalisasi URL menjadi FULL endpoint chat/completions.

    - Jika sudah berakhir dengan /chat/completions -> pakai apa adanya.
    - Jika berakhir dengan /v1 (base URL) -> tambahkan /chat/completions.
    - Lainnya -> tambahkan /chat/completions bila belum ada.
    """
    url = (url or "").strip().rstrip("/")
    if not url:
        return "https://api.openai.com/v1/chat/completions"
    if url.endswith("/chat/completions"):
        return url
    return url + "/chat/completions"


# Role yang valid + deskripsi singkat untuk prompt
ROLE_SPEC = {
    "developer": "software/web/mobile/backend/frontend engineering",
    "designer": "UI/UX, graphic, brand, product, visual design",
    "writer": "content writing, copywriting, technical writing, editing",
    "web3": "solidity, smart contract, blockchain, DeFi, NFT",
    "data": "data science, ML engineering, data analysis, AI/LLM",
    "security": "security audit, pentest, bug bounty, appsec",
}

# Sub-spesialisasi developer yang dikenali executor
DEV_SUBTYPES = [
    "web",          # Next.js / Vite frontend
    "mobile",       # React Native / Expo
    "api",          # FastAPI backend
    "devops",       # Docker + K8s + CI
    "cloud",        # Terraform IaC (AWS/GCP/Azure)
    "qa",           # test suite
]

SYSTEM_PROMPT = """You are a job classification engine for a freelance developer/designer/writer/web3 specialist.

Classify a freelance job posting into whether it is a good fit to be DONE DIRECTLY as an individual contributor (not a managerial/executive/non-technical role), and which role + subtype it belongs to.

Rules:
- REJECT (relevant=false) any role that is managerial/executive (VP, Director, Manager, Head of, Team Lead, Principal, C-level), or non-technical (sales, marketing, HR, finance, accounting, recruiting, customer support, data entry, legal, compliance, virtual assistant, operations, product/project manager, community, growth).
- ACCEPT (relevant=true) only hands-on individual-contributor technical/creative roles.
- "Senior"/"Staff" in front of a hands-on role (e.g. Senior Software Engineer) is STILL acceptable (individual contributor).

Role must be exactly one of: developer, designer, writer, web3, data, security.

For developer, also pick a subtype from: web, mobile, api, devops, cloud, qa (default "web" if unclear).

Respond with JSON only, no markdown, in this exact shape:
{"relevant": true, "role": "developer", "subtype": "web", "reason": "hands-on senior engineer"}

For non-developer roles, set subtype to "".
"""


def _build_user_msg(job: Job) -> str:
    parts = [
        f"Title: {job.title or ''}",
        f"Company: {job.company or ''}",
        f"Skills: {job.skills or ''}",
        f"Category: {job.category or ''}",
        f"Description: {(job.description or '')[:600]}",
    ]
    return "\n".join(parts)


def _extract_json(content: str) -> dict:
    """Ekstrak objek JSON dari response LLM secara robust.

    Menangani markdown fence, teks sebelum/sesudah JSON, dan response terpotong
    (mencoba menutup brace yang belum selesai). Return dict atau raise ValueError.
    """
    content = (content or "").strip()
    # Hapus markdown fence ```json ... ```
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:]
        content = content.strip()

    # Cari blok JSON pertama (dari '{' pertama ke '}' terakhir).
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"tidak ada objek JSON: {content[:80]!r}")
    candidate = content[start:end + 1]

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # Coba perbaiki response terpotong: tutup string/brace yang belum selesai.
        repaired = _repair_truncated_json(candidate)
        return json.loads(repaired)


def _repair_truncated_json(s: str) -> str:
    """Perbaiki JSON terpotong dengan menutup string & brace yang belum selesai."""
    # Tutup string yang belum selesai (jumlah kutip ganjil).
    in_str = False
    escaped = False
    out = []
    for ch in s:
        out.append(ch)
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
        elif ch == '"':
            in_str = not in_str
    if in_str:
        out.append('"')
    s = "".join(out)

    # Tutup brace/kurung yang belum seimbang.
    open_braces = s.count("{") - s.count("}")
    if open_braces > 0:
        s += "}" * open_braces
    return s


def _classify_llm(job: Job) -> Optional[dict]:
    """Klasifikasi via LLM. Return dict atau None bila gagal/tidak tersedia."""
    if not _llm_available():
        return None
    import requests
    api_key, url, model = _llm_config()
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _build_user_msg(job)},
                ],
                "temperature": 0.0,
                "max_tokens": 200,
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        data = _extract_json(content)

        relevant = bool(data.get("relevant", False))
        role = str(data.get("role", "") or "").strip()
        subtype = str(data.get("subtype", "") or "").strip()

        # Validasi: job yang diterima WAJIB punya role valid; kalau tidak,
        # anggap response tidak valid -> fallback heuristik.
        if relevant and role not in ROLE_SPEC:
            raise ValueError(f"role tidak valid untuk job relevan: {role!r}")

        return {
            "relevant": relevant,
            "role": role,
            "subtype": subtype,
            "reason": str(data.get("reason", "")),
            "source": "llm",
        }
    except Exception as e:
        print(f"[llm_filter] LLM gagal, fallback heuristik -- {e}")
        return None


def _classify_heuristic(job: Job) -> dict:
    """Fallback heuristik (regex) — konsisten dengan _is_relevant + _detect_role."""
    relevant = _heuristic_relevant(job)
    # Untuk job yang ditolak, kosongkan role/subtype agar konsisten dengan output LLM.
    if not relevant:
        return {
            "relevant": False,
            "role": "",
            "subtype": "",
            "reason": "heuristic regex",
            "source": "heuristic",
        }
    role = _detect_role(job)
    subtype = _heuristic_subtype(job, role)
    return {
        "relevant": relevant,
        "role": role,
        "subtype": subtype,
        "reason": "heuristic regex",
        "source": "heuristic",
    }


def _heuristic_subtype(job: Job, role: str) -> str:
    """Tentukan sub-spesialisasi developer via keyword judul/skills/kategori."""
    if role != "developer":
        return ""
    text = " ".join(filter(None, [job.title or "", job.skills or "",
                                  job.category or ""])).lower()
    if any(k in text for k in ["mobile", "react native", "android", "ios",
                               "flutter", "swift", "kotlin"]):
        return "mobile"
    if any(k in text for k in ["aws", "gcp", "azure", "terraform", "cloud",
                               "cloudformation", "cloud engineer", "cloud architect"]):
        return "cloud"
    if any(k in text for k in ["devops", "sre", "kubernetes", "k8s", "docker",
                               "infrastructure", "ci/cd", "release", "platform",
                               "site reliability"]):
        return "devops"
    if any(k in text for k in ["qa", "test", "testing", "quality", "sdet"]):
        return "qa"
    if any(k in text for k in ["api", "backend", "back end", "back-end", "rest",
                               "microservice", "server", "django", "flask",
                               "golang", "rust", "node.js", "nodejs", "express"]):
        return "api"
    return "web"


def classify_job(job: Job) -> dict:
    """Klasifikasi satu job: coba LLM, fallback heuristik.

    Selalu mengembalikan dict dengan kunci: relevant, role, subtype, reason, source.
    """
    result = _classify_llm(job)
    if result is not None:
        return result
    return _classify_heuristic(job)


def classify_batch(jobs: list[Job]) -> list[dict]:
    """Klasifikasi banyak job (satu per satu; LLM dipakai bila tersedia)."""
    return [classify_job(j) for j in jobs]
