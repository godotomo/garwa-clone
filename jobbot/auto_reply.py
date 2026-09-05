"""jobbot/auto_reply.py - Auto-reply email cerdas (pahami isi lalu balas kontekstual).

Tanpa API key eksternal, modul ini menganalisis isi email masuk secara
heuristik (deteksi intent + ekstraksi informasi) lalu menghasilkan balasan
yang relevan dengan konteks. Ini cukup untuk keperluan freelance.

Jika Anda menyediakan LLM API key (opsional), set env:
  JOB_LLM_API_KEY   -> key API (OpenAI-compatible)
  JOB_LLM_BASE_URL  -> base URL (default https://api.openai.com/v1)
  JOB_LLM_MODEL     -> model (default gpt-4o-mini)
maka generate_reply() akan memakai LLM untuk balasan yang lebih natural.

Deteksi intent yang didukung:
  - job_offer      : tawaran pekerjaan / undangan interview
  - payment        : pembayaran / invoice / tagihan
  - question       : pertanyaan umum
  - greeting       : sapaan / perkenalan
  - feedback       : revisi / feedback / komplain
  - follow_up      : follow-up / tindak lanjut
  - unknown        : tidak terdeteksi (fallback sopan)
"""
import json
import os
import re
from typing import Optional

from . import db  # memicu _load_dotenv() agar .env terbaca


# --------------------------------------------------------------------------- #
# Intent detection (heuristik keyword matching)
# --------------------------------------------------------------------------- #
INTENT_RULES = [
    ("job_offer", [
        "job", "position", "role", "hire", "hiring", "interview",
        "offer", "contract", "freelance", "project", "opportunity",
        "gig", "opening", "recruit", "vacancy", "apply",
    ]),
    ("payment", [
        "payment", "invoice", "paid", "pay", "salary", "compensation",
        "rate", "budget", "escrow", "milestone", "deposit", "transfer",
        "paypal", "wire", "bank", "amount", "fee",
    ]),
    ("feedback", [
        "revision", "revise", "feedback", "change", "edit", "fix",
        "issue", "bug", "error", "wrong", "update", "modify", "adjust",
        "complaint", "not working", "doesn't work", "broken",
    ]),
    ("question", [
        "question", "?", "how", "what", "when", "where", "why", "could you",
        "can you", "would you", "please explain", "clarify", "wondering",
    ]),
    ("follow_up", [
        "follow up", "follow-up", "following up", "checking in", "status",
        "update", "any news", "any progress", "just checking",
    ]),
    ("greeting", [
        "hello", "hi ", "hey", "good morning", "good afternoon",
        "good evening", "nice to meet", "introduce", "my name is",
        "greetings",
    ]),
]


def detect_intent(subject: str, body: str) -> str:
    """Deteksi intent email berdasarkan subject + body."""
    text = f"{subject} {body}".lower()
    # Prioritas: cek urutan rule (job_offer > payment > feedback > ...)
    for intent, keywords in INTENT_RULES:
        for kw in keywords:
            if kw in text:
                return intent
    return "unknown"


def extract_sender_name(from_addr: str) -> str:
    """Ekstrak nama dari 'Nama <email@x.com>' -> 'Nama' (fallback email)."""
    from_addr = from_addr.strip()
    m = re.match(r"^(.*?)\s*<([^>]+)>$", from_addr)
    if m:
        name = m.group(1).strip().strip('"')
        if name:
            return name
        return m.group(2)
    return from_addr


def extract_email(from_addr: str) -> str:
    """Ekstrak alamat email murni dari 'Nama <email@x.com>'."""
    m = re.search(r"<([^>]+)>", from_addr)
    if m:
        return m.group(1)
    return from_addr


# --------------------------------------------------------------------------- #
# Reply generation (template kontekstual, tanpa LLM)
# --------------------------------------------------------------------------- #
REPLY_TEMPLATES = {
    "job_offer": (
        "Hi {name},\n\n"
        "Thank you for reaching out regarding this opportunity. "
        "I'm very interested and would be glad to discuss the details further.\n\n"
        "Could you share more about the scope, timeline, and budget so I can "
        "confirm availability and prepare a proposal?\n\n"
        "Looking forward to hearing from you.\n\n"
        "Best regards,\n"
        "Garwa Coder"
    ),
    "payment": (
        "Hi {name},\n\n"
        "Thank you for your message regarding payment. I've noted the details "
        "and will review them promptly.\n\n"
        "If there's any specific action needed from my side (invoice, bank "
        "details, or confirmation), please let me know and I'll take care of "
        "it right away.\n\n"
        "Best regards,\n"
        "Garwa Coder"
    ),
    "feedback": (
        "Hi {name},\n\n"
        "Thank you for the feedback. I understand the points you raised and "
        "will address them promptly.\n\n"
        "I'll review the requested changes and get back to you with an updated "
        "version as soon as possible.\n\n"
        "Best regards,\n"
        "Garwa Coder"
    ),
    "question": (
        "Hi {name},\n\n"
        "Thank you for your question. I'd be happy to help.\n\n"
        "Could you provide a bit more context so I can give you the most "
        "accurate answer?\n\n"
        "Best regards,\n"
        "Garwa Coder"
    ),
    "follow_up": (
        "Hi {name},\n\n"
        "Thank you for following up. I appreciate your patience.\n\n"
        "I'm on it and will share an update with you shortly.\n\n"
        "Best regards,\n"
        "Garwa Coder"
    ),
    "greeting": (
        "Hi {name},\n\n"
        "Thank you for your message. It's great to connect with you.\n\n"
        "How can I help you today?\n\n"
        "Best regards,\n"
        "Garwa Coder"
    ),
    "unknown": (
        "Hi {name},\n\n"
        "Thank you for your email. I've received it and will review the "
        "details carefully.\n\n"
        "I'll get back to you shortly.\n\n"
        "Best regards,\n"
        "Garwa Coder"
    ),
}


def _topic_from_subject(subject: str) -> str:
    """Ambil topik singkat dari subject untuk dipakai di template."""
    subject = subject.strip()
    # Hapus prefix umum
    subject = re.sub(r"^(re|fwd?)\s*:\s*", "", subject, flags=re.IGNORECASE)
    if not subject:
        return "your project"
    # Batasi panjang & lowercase kata pertama
    return subject[:60]


def generate_reply_heuristic(info: dict) -> tuple:
    """Generate balasan heuristik. Return (body, intent)."""
    subject = info.get("subject", "")
    body = info.get("body", "")
    from_addr = info.get("from", "")
    intent = detect_intent(subject, body)
    name = extract_sender_name(from_addr)
    topic = _topic_from_subject(subject)
    template = REPLY_TEMPLATES.get(intent, REPLY_TEMPLATES["unknown"])
    reply = template.format(name=name, topic=topic)
    return reply, intent


# --------------------------------------------------------------------------- #
# LLM-backed reply (opsional, butuh JOB_LLM_API_KEY)
# --------------------------------------------------------------------------- #
def _llm_available() -> bool:
    return bool(os.environ.get("JOB_LLM_API_KEY"))


def generate_reply_llm(info: dict) -> Optional[str]:
    """Generate balasan via LLM (OpenAI-compatible). Return None jika gagal."""
    import requests
    api_key = os.environ.get("JOB_LLM_API_KEY")
    base_url = os.environ.get("JOB_LLM_BASE_URL") or "https://api.openai.com/v1"
    model = os.environ.get("JOB_LLM_MODEL") or "gpt-4o-mini"
    url = f"{base_url.rstrip('/')}/chat/completions"

    subject = info.get("subject", "")
    body = info.get("body", "")[:2000]
    from_addr = info.get("from", "")

    system = (
        "You are Garwa Coder, a professional freelance developer, designer, "
        "writer, and web3 developer. Write a concise, polite, professional "
        "email reply to the incoming message. Keep it under 150 words. "
        "Sign as 'Garwa Coder'."
    )
    user_msg = f"From: {from_addr}\nSubject: {subject}\n\nMessage:\n{body}"

    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.7,
                "max_tokens": 400,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[auto_reply] LLM gagal, fallback heuristik -- {e}")
        return None


def generate_reply(info: dict) -> tuple:
    """Generate balasan cerdas. Return (body, intent).

    Pakai LLM jika JOB_LLM_API_KEY tersedia, else heuristik.
    """
    intent = detect_intent(info.get("subject", ""), info.get("body", ""))
    if _llm_available():
        llm_reply = generate_reply_llm(info)
        if llm_reply:
            return llm_reply, intent
    body, intent = generate_reply_heuristic(info)
    return body, intent


# --------------------------------------------------------------------------- #
# Integration helper untuk imap_inbox.watch()
# --------------------------------------------------------------------------- #
def make_auto_reply_callback(imap, notify=None):
    """Buat callback untuk imap.watch() yang membalas cerdas tiap email masuk.

    notify: fungsi opsional untuk notifikasi (mis. kirim ke Telegram).
    """
    def callback(info: dict):
        body, intent = generate_reply(info)
        print(f"[auto_reply] '{info['subject']}' -> intent={intent}, "
              f"membalas ke {info['from']}")
        ok = imap.reply_email(info["num"], body)
        print(f"[auto_reply] balas {'OK' if ok else 'GAGAL'}")
        if notify:
            try:
                notify(f"📧 Balas email [{intent}]: {info['subject']} -> "
                       f"{'OK' if ok else 'GAGAL'}")
            except Exception as e:
                print(f"[auto_reply] notify gagal -- {e}")
    return callback


if __name__ == "__main__":
    # Smoke test
    samples = [
        {"from": "Client A <client@acme.com>",
         "subject": "Freelance project opportunity",
         "body": "Hi, we have a freelance project for a web developer. Are you available?"},
        {"from": "Billing <billing@acme.com>",
         "subject": "Invoice payment",
         "body": "Your invoice has been paid. Please confirm receipt."},
        {"from": "Boss <boss@acme.com>",
         "subject": "Revision needed",
         "body": "Please fix the bug in the login page."},
    ]
    for s in samples:
        body, intent = generate_reply(s)
        print(f"\n=== intent={intent} | {s['subject']} ===")
        print(body)
