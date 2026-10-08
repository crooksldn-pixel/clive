"""The release service's status, read-only, for CLIVE's Builds screen.

Why it exists: George is told what the release service did on the screen where he already reads
what is being built (app/builds/read.py adds it to the board; web/builds.js draws it as one line).
CLIVE only reads the file the service writes (app/release/state.py); it has no way to start,
stop or steer a deploy, and the model has no tool that reaches this.

What it promises: the line shown is the service's own words, checked for shape and bounded; a
missing file says plainly that the service is not installed on this server; a file that cannot be
read says that. Nothing here raises.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.release.state import STATES, STATUS_FILE, STATUS_SCHEMA

NOT_INSTALLED = "The release service is not installed on this server, so deploys are done by hand."
UNREADABLE = "The release service's status could not be read."
MAX_LINE = 400


def read(state_dir: Path | None = None) -> dict[str, Any]:
    """{"installed", "state", "line", "at", "mode"}: what the Builds screen says about deploys."""
    if state_dir is None:
        from app.release.settings import ReleaseSettings

        state_dir = ReleaseSettings().state_dir
    path = Path(state_dir) / STATUS_FILE
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {"installed": False, "state": "", "line": NOT_INSTALLED, "at": "", "mode": ""}
    except OSError:
        return {"installed": True, "state": "", "line": UNREADABLE, "at": "", "mode": ""}
    try:
        data = json.loads(raw.decode("utf-8")) if len(raw) <= 64 * 1024 else None
    except (UnicodeDecodeError, ValueError):
        data = None
    if not isinstance(data, dict) or data.get("schema") != STATUS_SCHEMA or data.get("state") not in STATES:
        return {"installed": True, "state": "", "line": UNREADABLE, "at": "", "mode": ""}
    line = data.get("line")
    at = data.get("at")
    return {"installed": True, "state": data["state"],
            "line": " ".join(line.split())[:MAX_LINE] if isinstance(line, str) and line.strip() else UNREADABLE,
            "at": at if isinstance(at, str) and len(at) <= 40 else "",
            "mode": data.get("mode") if data.get("mode") in ("live", "dry_run") else ""}
