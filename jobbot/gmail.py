"""jobbot/gmail.py - Kirim & balas email via Gmail API (Service Account).

Menggunakan Service Account + Domain-Wide Delegation (impersonation ke
JOB_GOOGLE_SUBJECT) agar bisa mengirim email atas nama akun Workspace.

Fungsi:
  - send_email()          : kirim email baru
  - reply_email()         : balas thread email tertentu
  - list_unread()         : daftar email belum dibaca (untuk auto-reply)
  - mark_read()           : tandai email sudah dibaca

Setup:
  - Enable Gmail API di Google Cloud Console
  - Service Account + Domain-Wide Delegation dengan scope gmail.send/gmail.modify
  - Set JOB_GOOGLE_SUBJECT = email Workspace user (mis. bot@domain-anda.com)
"""
import base64
import os
from email.mime.text import MIMEText

from .google_auth import get_credentials, SCOPES


def _gmail_service():
    from googleapiclient.discovery import build
    creds = get_credentials(SCOPES)
    return build("gmail", "v1", credentials=creds)


def _encode_message(msg) -> str:
    """Encode email message ke base64url untuk Gmail API."""
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return raw


def send_email(to, subject, body, cc=None, bcc=None, from_email=None) -> dict:
    """Kirim email baru. Return dict hasil Gmail API."""
    service = _gmail_service()
    msg = MIMEText(body, "plain", "utf-8")
    msg["to"] = to
    msg["subject"] = subject
    if cc:
        msg["cc"] = cc
    if bcc:
        msg["bcc"] = bcc
    if from_email:
        msg["from"] = from_email
    raw = _encode_message(msg)
    result = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
    print(f"[gmail] Sent to {to}: {result.get('id')}")
    return result


def reply_email(message_id, body, to=None, subject=None) -> dict:
    """Balas email (reply) ke message_id tertentu.

    message_id = ID pesan Gmail (dari list_unread). body = teks balasan.
    """
    service = _gmail_service()
    # Ambil pesan asli untuk header In-Reply-To / References / subject.
    original = service.users().messages().get(
        userId="me", id=message_id, format="metadata",
        metadataHeaders=["Subject", "From", "Message-ID", "References"],
    ).execute()
    headers = {h["name"]: h["value"] for h in original.get("payload", {}).get("headers", [])}

    msg = MIMEText(body, "plain", "utf-8")
    if subject is None:
        subj = headers.get("Subject", "")
        if not subj.lower().startswith("re:"):
            subj = "Re: " + subj
        subject = subj
    msg["subject"] = subject
    msg["to"] = to or headers.get("From", "")
    msg["In-Reply-To"] = headers.get("Message-ID", "")
    refs = headers.get("References", "")
    if refs:
        msg["References"] = refs + " " + headers.get("Message-ID", "")
    else:
        msg["References"] = headers.get("Message-ID", "")

    raw = _encode_message(msg)
    result = service.users().messages().send(
        userId="me", body={"raw": raw, "threadId": original.get("threadId")}
    ).execute()
    print(f"[gmail] Replied to {message_id}: {result.get('id')}")
    return result


def list_unread(max_results=20, query=None) -> list:
    """Daftar email belum dibaca. Return list dict {id, threadId, subject, from, snippet}."""
    service = _gmail_service()
    q = query or "is:unread"
    res = service.users().messages().list(
        userId="me", q=q, maxResults=max_results
    ).execute()
    out = []
    for m in res.get("messages", []):
        msg = service.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["Subject", "From"],
        ).execute()
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        out.append({
            "id": msg["id"],
            "threadId": msg.get("threadId"),
            "subject": headers.get("Subject", ""),
            "from": headers.get("From", ""),
            "snippet": msg.get("snippet", ""),
        })
    return out


def mark_read(message_id) -> dict:
    """Tandai email sudah dibaca (hapus label UNREAD)."""
    service = _gmail_service()
    return service.users().messages().modify(
        userId="me", id=message_id,
        body={"removeLabelIds": ["UNREAD"]},
    ).execute()
