"""The release service's status, read-only, for CLIVE's Builds screen.

Why it exists: George is told what the release service did on the screen where he already reads
what is being built (app/builds/read.py adds it to the board; web/builds.js draws it as one line).
CLIVE only reads the file the service writes (app/release/state.py); it has no way to start,
stop or steer a deploy, and the model has no tool that reaches this.

What it promises: the line shown is the service's own words, checked for shape and bounded; a
missing file says plainly that the service is not installed on this server; a file that cannot be
read says that. Nothing here raises.

Since 8 October (DEC-072) it also passes on, each checked for shape, what Deploy now needs: the rule
the service follows, the SHA it would deploy the moment George approves it (`ready_for`), the SHA and
title it last looked at, and the latest deploy, stage by stage (`deploy`: each stage reached and when,
how it ended and why), which app/release/offer.py turns into the progress CLIVE shows.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.release.state import ENDS, STAGES, STATES, STATUS_FILE, STATUS_SCHEMA

NOT_INSTALLED = "The release service is not installed on this server, so deploys are done by hand."
UNREADABLE = "The release service's status could not be read."
MAX_LINE = 400


_SHA = re.compile(r"^[0-9a-f]{40}$")
_APPROVAL = re.compile(r"^[0-9a-f]{32}$")
EMPTY = {"rule": "", "ready_for": "", "sha": "", "title": "", "deploy": None}


def _text(value: Any, limit: int) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def _at(value: Any) -> str:
    return value if isinstance(value, str) and len(value) <= 40 else ""


def _sha(value: Any) -> str:
    return value if isinstance(value, str) and _SHA.fullmatch(value) else ""


def deploy_of(raw: Any) -> dict[str, Any] | None:
    """The latest deploy as the service wrote it (app/release/state.py deploy_record), checked: stages
    only from the fixed list, in the order reached, each with when."""
    if not isinstance(raw, dict) or not _sha(raw.get("sha")):
        return None
    steps = []
    for step in raw.get("steps") if isinstance(raw.get("steps"), list) else []:
        if isinstance(step, list) and len(step) == 2 and step[0] in STAGES + ENDS:
            steps.append({"stage": step[0], "at": _at(step[1])})
    approval = raw.get("approval")
    return {"sha": raw["sha"], "title": _text(raw.get("title"), 160),
            "approval": approval if isinstance(approval, str) and _APPROVAL.fullmatch(approval) else "",
            "steps": steps[:12], "end": raw.get("end") if raw.get("end") in ENDS else "",
            "reason": _text(raw.get("reason"), 300)}


def read(state_dir: Path | None = None) -> dict[str, Any]:
    """{"installed", "state", "line", "at", "mode", "rule", "ready_for", "sha", "title", "deploy"}: what
    the Builds screen says about deploys, and what Deploy now is drawn from."""
    if state_dir is None:
        from app.release.settings import ReleaseSettings

        state_dir = ReleaseSettings().state_dir
    path = Path(state_dir) / STATUS_FILE
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {"installed": False, "state": "", "line": NOT_INSTALLED, "at": "", "mode": "", **EMPTY}
    except OSError:
        return {"installed": True, "state": "", "line": UNREADABLE, "at": "", "mode": "", **EMPTY}
    try:
        data = json.loads(raw.decode("utf-8")) if len(raw) <= 64 * 1024 else None
    except (UnicodeDecodeError, ValueError):
        data = None
    if not isinstance(data, dict) or data.get("schema") != STATUS_SCHEMA or data.get("state") not in STATES:
        return {"installed": True, "state": "", "line": UNREADABLE, "at": "", "mode": "", **EMPTY}
    line = data.get("line")
    return {"installed": True, "state": data["state"],
            "line": " ".join(line.split())[:MAX_LINE] if isinstance(line, str) and line.strip() else UNREADABLE,
            "at": _at(data.get("at")),
            "mode": data.get("mode") if data.get("mode") in ("live", "dry_run") else "",
            "rule": data.get("rule") if data.get("rule") in ("owner_waiver", "exact_sha_review") else "",
            "ready_for": _sha(data.get("ready_for")), "sha": _sha(data.get("sha")),
            "title": _text(data.get("title"), 160), "deploy": deploy_of(data.get("deploy"))}
