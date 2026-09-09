"""Test kemampuan Calendar skill google-workspace (get/update/list-calendars).

Memakai mock build_service agar tidak butuh kredensial/network. Menangkap
stdout JSON yang dicetak oleh fungsi calendar_*.
"""
import io
import json
import os
import sys
import contextlib
import argparse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "skills", "google-workspace", "scripts"))

import google_api


class _FakeEvent:
    """Fake hasil service.events().get() / update() / list()."""

    def __init__(self, data):
        self._data = data

    def execute(self):
        return self._data


class _FakeEvents:
    def __init__(self, event_data, list_items=None):
        self._event = event_data
        self._items = list_items

    def get(self, calendarId=None, eventId=None):
        return _FakeEvent(self._event)

    def update(self, calendarId=None, eventId=None, body=None):
        merged = dict(self._event)
        merged.update(body)
        return _FakeEvent(merged)

    def list(self, **kwargs):
        return _FakeEvent({"items": self._items})

    def insert(self, calendarId=None, body=None):
        return _FakeEvent({"id": "new1", "summary": body.get("summary", "")})


class _FakeCalendarList:
    def list(self, maxResults=None):
        return _FakeEvent({"items": [
            {"id": "primary", "summary": "My Calendar", "accessRole": "owner",
             "primary": True, "timeZone": "Asia/Jakarta"},
        ]})


class _FakeService:
    def __init__(self, event_data, list_items=None):
        self.events = lambda: _FakeEvents(event_data, list_items)
        self.calendarList = lambda: _FakeCalendarList()


def _run(func, args):
    """Jalankan func(args) dan kembalikan dict hasil JSON dari stdout."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        func(args)
    return json.loads(buf.getvalue())


def _make_args(**kw):
    return argparse.Namespace(**kw)


def test_calendar_get():
    event = {
        "id": "evt1", "summary": "Rapat", "description": "Agenda",
        "location": "Zoom",
        "start": {"dateTime": "2026-03-01T10:00:00-06:00"},
        "end": {"dateTime": "2026-03-01T10:30:00-06:00"},
        "status": "confirmed", "htmlLink": "https://cal.google/1",
        "attendees": [{"email": "a@co.com"}],
        "creator": {"email": "me@co.com"},
    }
    google_api._gws_binary = lambda: None
    google_api.build_service = lambda api, v: _FakeService(event)
    out = _run(google_api.calendar_get,
               _make_args(event_id="evt1", calendar="primary"))
    assert out["id"] == "evt1"
    assert out["summary"] == "Rapat"
    assert out["attendees"] == ["a@co.com"]
    assert out["creator"] == "me@co.com"


def test_calendar_update_changes_fields():
    event = {
        "id": "evt1", "summary": "Lama", "location": "",
        "start": {"dateTime": "2026-03-01T10:00:00-06:00"},
        "end": {"dateTime": "2026-03-01T10:30:00-06:00"},
    }
    google_api._gws_binary = lambda: None
    google_api.build_service = lambda api, v: _FakeService(event)
    out = _run(google_api.calendar_update,
               _make_args(event_id="evt1", calendar="primary",
                          summary="Baru", location="Ruang 2",
                          start="2026-03-01T11:00:00-06:00",
                          end="2026-03-01T11:30:00-06:00",
                          description=None, attendees=None))
    assert out["status"] == "updated"
    assert out["summary"] == "Baru"
    assert out["start"] == "2026-03-01T11:00:00-06:00"


def test_calendar_list_calendars():
    google_api._gws_binary = lambda: None
    google_api.build_service = lambda api, v: _FakeService({})
    out = _run(google_api.calendar_list_calendars, _make_args(max=50))
    assert isinstance(out, list)
    assert out[0]["id"] == "primary"
    assert out[0]["primary"] is True
    assert out[0]["timeZone"] == "Asia/Jakarta"
