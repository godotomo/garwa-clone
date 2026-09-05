"""jobbot/google_auth.py - Autentikasi Google (Service Account + impersonation).

Mendukung dua mode:
  1. Service Account (rekomendasi untuk autonomous) — token tidak expire,
     tidak butuh browser. Untuk Gmail/Drive atas nama akun Workspace,
     gunakan Domain-Wide Delegation + impersonation (JOB_GOOGLE_SUBJECT).
  2. OAuth desktop (fallback) — butuh browser interaktif (token.json).

Konfigurasi env (.env):
  JOB_GOOGLE_SERVICE_ACCOUNT  = path file service_account.json (default: jobbot/service_account.json)
  JOB_GOOGLE_SUBJECT          = email Workspace user yang di-impersonate
                                (mis. bot@domain-anda.com). Wajib untuk Gmail
                                & Drive atas nama user Workspace.

Scopes:
  - drive.file, drive (upload/kelola file)
  - spreadsheets (Google Sheets)
  - documents (Google Docs)
  - gmail.send, gmail.modify (kirim/balas email)
"""
import os

# Scopes lengkap untuk seluruh fitur (Drive/Sheets/Docs/Gmail).
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

# Scopes lama (kompatibilitas) — subset Drive/Sheets/Docs.
SCOPES_BASIC = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
]

_DIR = os.path.dirname(__file__)


def _service_account_path() -> str:
    return (os.environ.get("JOB_GOOGLE_SERVICE_ACCOUNT")
            or os.path.join(_DIR, "service_account.json"))


def _subject() -> str:
    return (os.environ.get("JOB_GOOGLE_SUBJECT")
            or os.environ.get("GOOGLE_SUBJECT")
            or "")


def has_service_account() -> bool:
    return os.path.exists(_service_account_path())


def get_credentials(scopes=None):
    """Ambil Google credentials.

    Prioritas: Service Account (dengan impersonation bila JOB_GOOGLE_SUBJECT
    diset) -> OAuth desktop (token.json).
    """
    scopes = scopes or SCOPES
    if has_service_account():
        return _service_account_credentials(scopes)
    return _oauth_credentials(scopes)


def _service_account_credentials(scopes):
    from google.oauth2 import service_account

    path = _service_account_path()
    subject = _subject()
    creds = service_account.Credentials.from_service_account_file(
        path, scopes=scopes
    )
    if subject:
        # Domain-Wide Delegation: impersonate user Workspace.
        creds = creds.with_subject(subject)
    return creds


def _oauth_credentials(scopes):
    from google.oauth2.credentials import Credentials

    token_path = os.path.join(_DIR, "token.json")
    if not os.path.exists(token_path):
        raise FileNotFoundError(
            "token.json tidak ditemukan. Jalankan setup_oauth() dulu, "
            "atau sediakan service_account.json."
        )
    return Credentials.from_authorized_user_file(token_path, scopes)


def build_service(name, version, scopes=None):
    """Bangun Google API service (drive/sheets/docs/gmail)."""
    from googleapiclient.discovery import build

    creds = get_credentials(scopes)
    return build(name, version, credentials=creds)


def setup_oauth():
    """OAuth desktop flow (fallback). Jalankan sekali, buka browser."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(
        os.path.join(_DIR, "credentials.json"), SCOPES_BASIC
    )
    creds = flow.run_local_server(port=8080)
    creds.to_token_file(os.path.join(_DIR, "token.json"))
    print("[google] OAuth complete. token.json saved.")


def print_auth_info() -> None:
    """Tampilkan info mode auth yang aktif (untuk debugging)."""
    if has_service_account():
        subject = _subject()
        print(f"[google] mode: service_account"
              + (f" (impersonate {subject})" if subject else " (tanpa subject)"))
    else:
        print("[google] mode: oauth desktop")
