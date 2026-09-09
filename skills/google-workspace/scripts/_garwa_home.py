"""Resolve GARWA_HOME for standalone skill scripts.

Skill scripts (google-workspace) may run outside the Garwa process (e.g.
system Python, cron, CI) where ``garwa.constants`` is not importable.  This
module provides the same ``get_garwa_home()`` and ``display_garwa_home()``
contracts without requiring Garwa on ``sys.path``.

The Google OAuth token, client secret, and pending-auth state for the
google-workspace skill are stored under GARWA_HOME so they stay isolated
from any runtime DB Garwa uses.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from garwa.constants import display_garwa_home as display_garwa_home
    from garwa.constants import get_garwa_home as get_garwa_home
except (ModuleNotFoundError, ImportError):

    def get_garwa_home() -> Path:
        """Return the Garwa home directory (default: ~/.garwa)."""
        val = os.environ.get("GARWA_HOME", "").strip()
        return Path(val) if val else Path.home() / ".garwa"

    def display_garwa_home() -> str:
        """Return a user-friendly ``~/``-shortened display string."""
        home = get_garwa_home()
        try:
            return "~/" + home.relative_to(Path.home()).as_posix()
        except ValueError:
            return str(home)
