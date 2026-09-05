"""jobbot/google_drive.py - Integrasi Google Sheets/Drive/Docs.

Mendukung dua mode auth (lihat google_auth.py):
  - Service Account (autonomous, tanpa browser) — rekomendasi.
  - OAuth desktop (fallback).

Setup Service Account:
  1. Google Cloud Console -> enable Drive API + Sheets API + Docs API
  2. Buat Service Account -> download JSON -> simpan jobbot/service_account.json
  3. (Opsional) Domain-Wide Delegation + set JOB_GOOGLE_SUBJECT agar bisa
     mengakses file atas nama user Workspace.

Fungsi:
  - upload_file_to_drive()  : upload file (PDF/CSV/DOCX) ke Drive
  - append_google_sheet()   : append baris ke Google Sheet
  - create_google_doc()     : buat dokumen Google Docs
  - create_google_sheet()   : buat Google Sheet baru
  - create_drive_folder()   : buat folder di Drive
"""
import os

from .google_auth import get_credentials, SCOPES


def _get_creds():
    """Ambil credentials (service account atau oauth)."""
    return get_credentials(SCOPES)


def upload_file_to_drive(local_path, folder_id=None, filename=None):
    """Upload file ke Google Drive. Return metadata file."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = _get_creds()
    service = build("drive", "v3", credentials=creds)
    filename = filename or os.path.basename(local_path)
    file_metadata = {"name": filename}
    if folder_id:
        file_metadata["parents"] = [folder_id]
    media = MediaFileUpload(local_path, resumable=True)
    result = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, name, webContentUrl, webViewLink",
    ).execute()
    print(f"[google] Uploaded: {result.get('name')} ({result.get('id')})")
    return result


def append_google_sheet(sheet_id, range_name, rows):
    """Append baris lowongan ke Google Sheet. rows = list[list[str]]."""
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    creds = _get_creds()
    service = build("sheets", "v4", credentials=creds)
    body = {"values": rows}
    try:
        result = (
            service.sheets()
            .values()
            .append(
                spreadsheetId=sheet_id,
                range=range_name,
                valueInputOption="RAW",
                body=body,
            )
            .execute()
        )
        print(f"[google] Appended {result.get('updatedRows')} rows to sheet {sheet_id}")
        return result
    except HttpError as e:
        print(f"[google] Sheet append failed -- {e}")
        return {}


def create_google_doc(title, content, folder_id=None):
    """Buat dokumen laporan di Google Docs. Return metadata doc."""
    from googleapiclient.discovery import build

    creds = _get_creds()
    service = build("docs", "v1", credentials=creds)
    doc = service.docs().create(body={"title": title}).execute()
    doc_id = doc.get("docId")
    requests = [
        {"insertText": {"location": {"index": 1}, "text": content}}
    ]
    service.docs().batchUpdate(
        docId=doc_id, body={"requests": requests}
    ).execute()
    if folder_id:
        drive = build("drive", "v3", credentials=creds)
        drive.files().update(fileId=doc_id, addParents=folder_id).execute()
    print(f"[google] Created doc: {doc_id}")
    return doc


def create_google_sheet(title, headers=None, folder_id=None):
    """Buat Google Sheet baru. Return (sheet_id, spreadsheet_url)."""
    from googleapiclient.discovery import build

    creds = _get_creds()
    service = build("sheets", "v4", credentials=creds)
    body = {"properties": {"title": title}}
    sheet = service.spreadsheets().create(body=body).execute()
    sheet_id = sheet.get("spreadsheetId")
    if headers:
        append_google_sheet(sheet_id, "A1", [headers])
    if folder_id:
        drive = build("drive", "v3", credentials=creds)
        drive.files().update(fileId=sheet_id, addParents=folder_id).execute()
    print(f"[google] Created sheet: {sheet_id}")
    return sheet_id, sheet.get("spreadsheetUrl")


def create_drive_folder(name, parent_id=None):
    """Buat folder di Google Drive. Return folder_id."""
    from googleapiclient.discovery import build

    creds = _get_creds()
    service = build("drive", "v3", credentials=creds)
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]
    folder = service.files().create(body=metadata, fields="id").execute()
    print(f"[google] Created folder: {folder.get('id')}")
    return folder.get("id")
