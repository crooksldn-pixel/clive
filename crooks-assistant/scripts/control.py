#!/usr/bin/env python3
"""crooks-control — what CROOKS Control shows, and what its buttons run.

The Mac app is a renderer. Every decision it appears to make is made here, in Python, where
it can be tested; the app reads one JSON document per subcommand and draws it.

    crooks-control status      the colour, every row, the build ids     (no network, no fetch)
    crooks-control plan        what an update would do: current vs candidate SHA
    crooks-control apply --yes do it: update, tests, restart, verify, tablet, mark good
    crooks-control rollback --yes   go back to the last known-good build, where that is safe
    crooks-control mark-good   record the running build as the one to come back to
    crooks-control actions     the twelve buttons, with the command behind each
    crooks-control contract    what every field above means, for whoever writes the next client

Four colours, and nothing else, because a glance has room for one fact:

    GREEN   live and healthy
    BLUE    a test session is recording
    AMBER   live but read-only, or something non-essential is down, or the tablet has no route
    RED     nothing is answering, or one of the three the assistant cannot work without
            (hearing, Claude, Shopify) is down

RED beats BLUE beats AMBER beats GREEN: an issue is never hidden by a test session, and a
test session is what the owner most wants to know while one is on. The three essentials are
crooks-status's own verdict, one colour deeper — this command invents no second opinion about
whether the Mac is well.

What this command will not do:

  * update anything without --yes. A click is the click; nothing here runs on a timer, on a
    boot, or from inside CROOKS OS. `scripts/update.py` says the same thing about itself.
  * throw local work away. The update stops on a dirty tree (that is update.py's rule, and it
    is tested); a rollback refuses on a dirty tree for the same reason.
  * print a secret. Every document goes through redact() on the way out, and the test suite
    puts a real-looking token in the environment and in a health detail and asserts it is
    not in the output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

# The version of every document below. The app refuses a number it does not know rather than
# drawing a field that has moved under it.
CONTRACT = 1
LOG_DIR = ROOT / "logs"
# The build to come back to. Written by `crooks-control apply` when an update verifies, and by
# `crooks-control mark-good`; read by the rollback decision. Nothing else writes it, nothing
# in CROOKS OS reads it, and it is inside logs/ — which the updater never touches.
KNOWN_GOOD_FILE = "last_known_good.json"

COLOURS = ("GREEN", "BLUE", "AMBER", "RED")
# The three the assistant cannot work without. Straight from scripts/status.py's verdict.
ESSENTIAL = ("speech", "claude", "shopify")

STATE_OK, STATE_OFF, STATE_BAD = "ok", "off", "bad"


# --------------------------------------------------------------------------- git (read-only)


def git(*args: str, cwd: Path | None = None) -> str:
    """A git question. Every verb this function is ever given is a question — the one command
    that moves anything is `checkout`, below, and it has its own name so that a scan of this
    file can tell them apart."""
    out = subprocess.run(["git", *args], cwd=cwd or ROOT, capture_output=True, text=True, timeout=60)
    return (out.stdout or "").strip() if out.returncode == 0 else ""


def git_ok(*args: str, cwd: Path | None = None) -> bool:
    out = subprocess.run(["git", *args], cwd=cwd or ROOT, capture_output=True, text=True, timeout=60)
    return out.returncode == 0


def checkout(sha: str, cwd: Path | None = None) -> tuple[bool, str]:
    """The only git command here that moves anything, used by the rollback and nowhere else.
    A checkout of an existing commit cannot lose a commit; the rollback still refuses to run
    it while the tree is dirty, because carrying uncommitted work onto an older build is not
    what the owner asked for."""
    out = subprocess.run(["git", "checkout", sha], cwd=cwd or ROOT, capture_output=True, text=True, timeout=120)
    return out.returncode == 0, ((out.stderr or out.stdout) or "").strip()[:300]


# --------------------------------------------------------------------------- secrets


# A key whose NAME says the value is a credential. The value goes; the key stays, so the shape
# of the document does not change under the app.
SECRET_KEY_HINTS = ("token", "secret", "password", "passwd", "credential", "cookie", "authorization", "api_key", "apikey")
# What a credential looks like whatever it is called. Shopify, Anthropic, Google, GitHub, Slack.
SECRET_SHAPES = re.compile(
    r"(shpat_|shpca_|shpss_|shppa_|sk-ant-[A-Za-z0-9-]*|sk-|ghp_|gho_|github_pat_|xoxb-|xoxp-|ya29\.|AIza)[A-Za-z0-9_\-]{6,}"
)
MASK = "[redacted]"


def environment_secrets() -> list[str]:
    """The values in this process's environment that are named like credentials. They are
    never read from here for use — only so that a health detail which happens to quote one is
    caught before it reaches the screen."""
    found = []
    for name, value in os.environ.items():
        if len(value) >= 8 and any(hint in name.lower() for hint in ("token", "secret", "key", "password", "credential", "cookie")):
            found.append(value)
    return sorted(set(found), key=len, reverse=True)


def redact(value, secrets: list[str] | None = None):
    """Every document leaves through here. Nothing in CROOKS OS puts a secret in /health — the
    keychain wrapper exists so that it cannot — but "nothing does" is a promise and this is a
    test: a detail line quoting a token, a git remote with a token in the URL, an environment
    variable echoed by a subprocess. All of them come out masked."""
    secrets = environment_secrets() if secrets is None else secrets
    if isinstance(value, dict):
        out = {}
        for key, inner in value.items():
            if isinstance(inner, str) and any(hint in str(key).lower() for hint in SECRET_KEY_HINTS):
                out[key] = MASK if inner else inner
            else:
                out[key] = redact(inner, secrets)
        return out
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        text = value
        for secret in secrets:
            if secret and secret in text:
                text = text.replace(secret, MASK)
        return SECRET_SHAPES.sub(MASK, text)
    return value


# --------------------------------------------------------------------------- what is running


def port() -> int:
    from config.settings import get_settings

    return get_settings().port


def read_health(the_port: int, *, fresh: bool = False) -> dict | None:
    """/health, on loopback, or None when nothing is answering. Monkeypatched in the tests:
    every rule below is a function of this document, so the rules can be driven from it."""
    import launch_common as lc

    return lc.fetch_health(f"http://127.0.0.1:{the_port}/health" + ("?fresh=1" if fresh else ""))


def tablet_route(the_port: int) -> tuple[str | None, str]:
    """(host, note) — the ts.net address the tablet opens, from Tailscale itself."""
    import launch_common as lc

    return lc.serve_status(the_port)


def checks_of(health: dict) -> dict[str, dict]:
    """/health answers with a map of name -> {ok, detail}; older builds answered with a list.
    Both are read, as crooks-status reads them, so an old backend does not blank the app."""
    raw = health.get("checks")
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items() if isinstance(v, dict)}
    return {str(c.get("name") or ""): c for c in (raw or []) if isinstance(c, dict)}


def test_session_of(health: dict) -> dict:
    observed = health.get("observability") if isinstance(health.get("observability"), dict) else {}
    ident = observed.get("test_session")
    return {"active": bool(ident), "id": str(ident or ""), "name": str(observed.get("name") or "")}


# --------------------------------------------------------------------------- mutation readiness


# The family states that mean the write half of a family cannot run now. From
# app/capabilities/families.py, which is the one table that knows.
def mutation_readiness(health: dict) -> dict:
    """Whether this Mac could make a change, read off the capability families rather than from
    a second opinion of our own. `app/capabilities/families.py` states every family with the
    scope named; /health carries the table. Only "ready" is green.

    An older backend that carries `writes` but no `families` is read from `writes`, because a
    control app that goes blank against last month's build is worse than one that says less.
    """
    families = health.get("families") if isinstance(health.get("families"), dict) else {}
    writes = health.get("writes") if isinstance(health.get("writes"), dict) else {}
    rows = [f for f in families.values() if isinstance(f, dict) and f.get("operations")]
    named = lambda rs: [{"label": str(r.get("label") or r.get("key") or "?"), "scope": str(r.get("scope") or ""), "detail": str(r.get("detail") or "")[:120]} for rs_ in [rs] for r in rs_]  # noqa: E731
    if not rows:
        state = {"ready": "ready", "disabled": "read_only", "blocked": "blocked", "unknown": "unknown"}.get(str(writes.get("state") or ""), "unknown")
        return {
            "state": state, "detail": str(writes.get("detail") or "no capability table on this build")[:160],
            "source": "writes", "ready": [], "read_only": [], "missing_scope": [], "unavailable": [],
        }
    ready = [r for r in rows if r.get("state") == "READY"]
    read_only = [r for r in rows if r.get("state") == "READ_ONLY"]
    missing = [r for r in rows if r.get("state") == "MISSING_SCOPE"]
    unavailable = [r for r in rows if r.get("state") in ("DISCONNECTED", "TEMPORARILY_UNAVAILABLE", "NOT_SUPPORTED_BY_STORE")]
    if str(writes.get("state") or "") == "blocked":
        state, detail = "blocked", str(writes.get("detail") or "blocked")
    elif read_only:
        state = "read_only"
        detail = f"{len(read_only)} of {len(rows)} read-only — " + str(read_only[0].get("detail") or "changes are off")
    elif missing:
        scopes = sorted({str(r.get("scope") or "?") for r in missing})
        state, detail = "missing_scope", f"{len(missing)} of {len(rows)} need a scope the store has not granted: {', '.join(scopes)}"
    elif ready and len(ready) == len(rows):
        state, detail = "ready", f"all {len(rows)} changes ready"
    elif ready:
        state, detail = "partial", f"{len(ready)} of {len(rows)} ready"
    else:
        state, detail = "unknown", f"{len(rows)} families, none ready"
    return {
        "state": state, "detail": detail[:160], "source": "families",
        "ready": [str(r.get("label") or r.get("key")) for r in ready],
        "read_only": named(read_only), "missing_scope": named(missing), "unavailable": named(unavailable),
    }


# --------------------------------------------------------------------------- the one colour


def roll_up(health: dict | None, *, tablet_host: str | None, session: dict, mutation: dict, the_port: int) -> dict:
    """One colour, and the sentence under it. A pure function of what was read, so every
    colour can be driven from a document in a test."""
    if not health:
        return {
            "state": "RED", "headline": "CROOKS — Offline",
            "why": f"nothing is answering on 127.0.0.1:{the_port}. `make up`, or `make install` to have it start at login.",
            "issues": ["the assistant is not answering"], "degraded": [],
        }
    checks = checks_of(health)
    down = [name for name, check in checks.items() if not check.get("ok")]
    essential_down = [name for name in ESSENTIAL if name in down]
    if essential_down:
        return {
            "state": "RED", "headline": "CROOKS — Issue",
            "why": _sentence_for(checks, essential_down),
            "issues": essential_down, "degraded": [n for n in down if n not in essential_down],
        }
    if session.get("active"):
        return {
            "state": "BLUE", "headline": "CROOKS — Testing",
            "why": f"recording {session.get('id') or 'a test session'} — crooks-watch follows it",
            "issues": [], "degraded": down,
        }
    degraded = list(down)
    if mutation.get("state") != "ready":
        degraded.append("changes")
    if not tablet_host:
        degraded.append("tablet route")
    if degraded:
        read_only = mutation.get("state") in ("read_only", "blocked")
        return {
            "state": "AMBER",
            "headline": "CROOKS — Read only" if read_only and len(degraded) == 1 else "CROOKS — Degraded",
            "why": _sentence_for(checks, down, mutation=mutation if mutation.get("state") != "ready" else None,
                                 tablet=not tablet_host),
            "issues": [], "degraded": degraded,
        }
    return {"state": "GREEN", "headline": "CROOKS — Online", "why": "everything answering, changes ready, tablet routed",
            "issues": [], "degraded": []}


def _sentence_for(checks: dict[str, dict], down: list[str], *, mutation: dict | None = None, tablet: bool = False) -> str:
    parts = [f"{name}: {str(checks.get(name, {}).get('detail') or 'down')[:80]}" for name in down]
    if mutation is not None:
        parts.append(str(mutation.get("detail") or "changes are off"))
    if tablet:
        parts.append("Tailscale is not serving the tablet's address")
    return " · ".join(parts) or "everything answering"


# --------------------------------------------------------------------------- the build ids


def current_build(health: dict | None = None) -> dict:
    """What is checked out here, and what the running backend calls itself. Two different
    identifiers, and the difference is the point: a build id that has not moved after an
    update means the restart did not happen."""
    sha = git("rev-parse", "HEAD")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    subject = git("log", "-1", "--format=%s")
    when = git("log", "-1", "--format=%cI")
    return {
        "sha": sha, "short": sha[:10], "branch": branch if branch != "HEAD" else "",
        "detached": branch == "HEAD", "subject": subject[:120], "committed_at": when,
        "build": str((health or {}).get("build") or ""),
        "version": str((health or {}).get("version") or ""),
    }


def known_good_path() -> Path:
    return Path(LOG_DIR) / KNOWN_GOOD_FILE


def read_known_good() -> dict | None:
    try:
        data = json.loads(known_good_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("sha") else None


def write_known_good(record: dict) -> Path:
    """Written whole and renamed into place, 0600 in a 0700 directory — the same way the test
    session's own files are written (app/observability/session.py). Inside logs/, which
    NEVER_TOUCH keeps the updater away from."""
    path = known_good_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.parent.stat().st_mode & 0o077:
            path.parent.chmod(0o700)
    except OSError:
        pass
    tmp = path.with_suffix(".tmp")
    handle = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(handle, (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    finally:
        os.close(handle)
    os.replace(tmp, path)
    return path


def rollback_decision(*, current: dict, good: dict | None, blocking: list[str], repo: Path | None = None) -> dict:
    """Can this Mac go back, and is going back safe? Never a guess: the commit has to be in
    this checkout, it has to be a different one, and the tree has to be clean."""
    out = {
        "available": False, "safe": False, "sha": "", "short": "", "recorded_at": None,
        "build": "", "reason": "", "commands": [], "note": "",
    }
    if not good:
        out["reason"] = ("No known-good build has been recorded on this Mac yet, so there is nothing to go back to. "
                         "`crooks-control mark-good` records the build that is running now.")
        return out
    sha = str(good.get("sha") or "")
    out.update({"sha": sha, "short": sha[:10], "recorded_at": good.get("recorded_at"), "build": str(good.get("build") or "")})
    if sha == str(current.get("sha") or ""):
        out["reason"] = "The build running here IS the last known-good one. There is nothing to go back to."
        return out
    if not git_ok("cat-file", "-e", f"{sha}^{{commit}}", cwd=repo):
        out["reason"] = (f"The last known-good commit ({sha[:10]}) is not in this checkout, so it cannot be gone back to. "
                         "`git fetch origin` may bring it back.")
        return out
    out["available"] = True
    out["commands"] = [["git", "checkout", sha], ["make", "restart"]]
    out["note"] = (f"`git checkout {sha[:10]}` leaves this checkout on a detached HEAD, which is deliberate: nothing is "
                   f"moved and nothing is lost. `git checkout {current.get('branch') or '<branch>'}` comes forward again.")
    if blocking:
        listed = ", ".join(blocking[:5])
        out["reason"] = (f"There are local changes here ({listed}). Going back would carry them onto an older build; "
                         "commit or stash them first. Nothing has been thrown away.")
        return out
    out["safe"] = True
    out["reason"] = f"Go back to {sha[:10]}" + (f" ({good.get('build')})" if good.get("build") else "") + ", then restart."
    return out


# --------------------------------------------------------------------------- rows


def _row(key: str, label: str, state: str, value: str, detail: str = "") -> dict:
    return {"key": key, "label": label, "state": state, "value": value[:160], "detail": detail[:200]}


def rows_for(health: dict | None, *, build: dict, good: dict | None, tablet: tuple[str | None, str],
             session: dict, mutation: dict, the_port: int) -> list[dict]:
    """Every line the brief asks the app to show, in the order it asks for them. One shape, so
    the app draws a list and nothing more."""
    host, note = tablet
    rows = []
    if not health:
        rows.append(_row("online", "Online", STATE_BAD, f"nothing answering on 127.0.0.1:{the_port}",
                         "`make up` to run it in a window, or `make install` to have it start at login"))
    else:
        rows.append(_row("online", "Online", STATE_OK, f"answering on 127.0.0.1:{the_port}",
                         f"{health.get('status', '?')} · up {_hours(health.get('uptime_s'))} · {health.get('sessions', 0)} session(s)"))
    checks = checks_of(health or {})
    rows.append(_row("build", "Build", STATE_OK if health else STATE_OFF,
                     str((health or {}).get("build") or "?"),
                     f"version {(health or {}).get('version') or '?'}"))
    rows.append(_row("backend", "Assistant", STATE_OK if health else STATE_BAD,
                     "running" if health else "not running",
                     str((health or {}).get("manifest", {}) and _manifest(health) or "")))
    speech = (health or {}).get("speech") if isinstance((health or {}).get("speech"), dict) else {}
    for key, label, name in (("speech", "Voice/STT", "speech"), ("speaks", "Speaks", "tts"),
                             ("claude", "Claude", "claude"), ("shopify", "Shopify", "shopify"),
                             ("gmail", "Gmail", "gmail")):
        check = checks.get(name)
        if check is None:
            rows.append(_row(key, label, STATE_OFF, "unknown", "this build does not report it"))
            continue
        value = str(check.get("detail") or "")
        if key == "speech" and speech:
            value = f"{speech.get('effective') or '?'} · {value}"
        rows.append(_row(key, label, STATE_OK if check.get("ok") else STATE_BAD, value))
    cache = (health or {}).get("orders_cache") if isinstance((health or {}).get("orders_cache"), dict) else None
    if cache:
        held, age = cache.get("orders", 0), cache.get("age_s")
        rows.append(_row("orders", "Order cache", STATE_OK if held else STATE_OFF,
                         f"{held} held" + (f", read {age}s ago" if age is not None else ""),
                         f"{cache.get('days', '?')} day(s)" if cache.get("days") is not None else ""))
    else:
        rows.append(_row("orders", "Order cache", STATE_OFF, "cold", "the first question about orders will read the store"))
    rows.append(_row("tablet", "Tablet", STATE_OK if host else STATE_OFF,
                     f"https://{host}/" if host else "no route", note))
    rows.append(_row("mutation", "Changes", STATE_OK if mutation.get("state") == "ready" else STATE_OFF,
                     str(mutation.get("state") or "unknown").replace("_", " "), str(mutation.get("detail") or "")))
    rows.append(_row("session", "Test session", STATE_OK if session.get("active") else STATE_OFF,
                     session.get("id") or "none", session.get("name") or ""))
    rows.append(_row("branch", "Branch", STATE_OFF if build.get("detached") else STATE_OK,
                     (build.get("branch") or "detached HEAD") + f" · {build.get('short') or '?'}",
                     str(build.get("subject") or "")))
    if good:
        rows.append(_row("known_good", "Known good", STATE_OK, str(good.get("short") or "")
                         + (f" · {good.get('build')}" if good.get("build") else ""),
                         f"recorded {_ago(good.get('recorded_at'))}" + (f" by {good.get('recorded_by')}" if good.get("recorded_by") else "")))
    else:
        rows.append(_row("known_good", "Known good", STATE_OFF, "none recorded",
                         "crooks-control mark-good records the running build as the one to come back to"))
    return rows


def _manifest(health: dict) -> str:
    manifest = health.get("manifest") if isinstance(health.get("manifest"), dict) else None
    if not manifest:
        return ""
    return f"{manifest.get('reads', 0)} reads, {manifest.get('writes', 0)} changes, {manifest.get('batches', 0)} bulk ({str(manifest.get('fingerprint') or '')[:8]})"


def _hours(seconds) -> str:
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "?"
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m"
    return f"{seconds / 3600:.1f}h"


def _ago(when) -> str:
    try:
        delta = time.time() - float(when)
    except (TypeError, ValueError):
        return "at an unknown time"
    return _hours(delta) + " ago"


# --------------------------------------------------------------------------- the documents


def envelope(command: str, **fields) -> dict:
    doc = {"contract": CONTRACT, "command": command, "ok": True, "at": round(time.time(), 3)}
    doc.update(fields)
    return doc


def status_document(*, fresh: bool = False) -> dict:
    """One read of /health, one read of Tailscale, one read of git, no fetch. This is what the
    menu bar polls, so it costs nothing the Mac would notice."""
    the_port = port()
    health = read_health(the_port, fresh=fresh)
    tablet = tablet_route(the_port)
    session = test_session_of(health or {})
    mutation = mutation_readiness(health or {})
    build = current_build(health)
    good = read_known_good()
    state = roll_up(health, tablet_host=tablet[0], session=session, mutation=mutation, the_port=the_port)
    dirty = _dirty()
    return envelope(
        "status", ok=state["state"] != "RED", **state,
        rows=rows_for(health, build=build, good=good, tablet=tablet, session=session, mutation=mutation, the_port=the_port),
        build={"current": build, "candidate": None, "last_known_good": good,
               "note": "the candidate build is read by `plan`, which fetches; status never touches the network"},
        tablet={"host": tablet[0] or "", "url": f"https://{tablet[0]}/" if tablet[0] else "", "note": tablet[1],
                "local": f"http://127.0.0.1:{the_port}/"},
        test_session=session, mutation=mutation,
        local_work={"dirty": dirty, "blocking": update_module().blocking_changes(dirty), "stops": bool(update_module().blocking_changes(dirty))},
        rollback=rollback_decision(current=build, good=good, blocking=update_module().blocking_changes(dirty)),
        port=the_port,
    )


def update_module():
    from scripts import update as _update

    # The updater is the same file `crooks-update` is, pointed at the same checkout, so a
    # button and a typed command cannot take different paths through it.
    _update.ROOT = ROOT
    return _update


def _dirty() -> list[str]:
    try:
        return update_module().dirty_paths()
    except Exception:  # noqa: BLE001 — not a git checkout, or git is not installed
        return []


def plan_document(branch: str = "") -> dict:
    """What an update would do. This one fetches — it is the "Check for update" button — and
    changes nothing else."""
    upd = update_module()
    code, doc = upd.run(check=True, branch=branch, quiet=True)
    good = read_known_good()
    build = current_build(read_health(port()))
    return envelope(
        "plan", ok=code == 0, update=doc,
        build={"current": {**build, **(doc.get("current") or {})}, "candidate": doc.get("candidate"), "last_known_good": good},
        local_work=doc.get("local_work"),
        rollback=rollback_decision(current=build, good=good, blocking=(doc.get("local_work") or {}).get("blocking") or []),
        next=doc.get("next"),
        click={"label": "Update now", "command": ["crooks-control", "apply", "--yes"],
               "enabled": bool(code == 0 and doc.get("behind") and doc.get("fast_forward"))},
    )


def apply_document(*, yes: bool, branch: str = "", run_tests: bool = True) -> dict:
    """The update, end to end, in the brief's order: inspect, fetch, show both SHAs, require a
    click, fast-forward only, dependencies, tests, restart, verify /health, verify the tablet
    route, mark successful. The first six and the restart and the health read are update.py's
    (one implementation, one set of refusals); the last three are here."""
    upd = update_module()
    if not yes:
        plan = plan_document(branch)
        plan["command"] = "apply"
        plan["ok"] = False
        plan["stop"] = {"stage": "click", "reason": "An update applies on a click. `crooks-control apply --yes`, or the app's Update button."}
        plan["next"] = "click_to_apply"
        return plan
    the_port = port()
    stages: list[dict] = []
    code, doc = upd.run(check=False, branch=branch, test=run_tests, quiet=True)
    build_before = doc.get("current") or {}
    good = read_known_good()
    if code != 0:
        build = current_build(read_health(the_port))
        decision = rollback_decision(current=build, good=good, blocking=(doc.get("local_work") or {}).get("blocking") or [])
        return envelope(
            "apply", ok=False, update=doc, stages=stages, tablet=None, marked_good=None,
            build={"current": build, "candidate": doc.get("candidate"), "last_known_good": good},
            rollback=decision,
            next=("rollback" if doc.get("moved") and decision.get("safe") else "blocked"),
            stop=doc.get("stop"),
        )
    if not doc.get("moved"):
        stages.append({"stage": "tablet", "state": "skip", "detail": "nothing moved, so nothing to verify"})
        return envelope("apply", ok=True, update=doc, stages=stages, tablet=None, marked_good=None,
                        build={"current": current_build(read_health(the_port)), "candidate": doc.get("candidate"), "last_known_good": good},
                        rollback=rollback_decision(current=current_build(None), good=good, blocking=[]),
                        next="up_to_date")
    # Step 10: the tablet's route. A missing route does NOT roll the update back — the Mac is
    # well and only the tablet's door is shut — but it is why the colour is AMBER afterwards.
    host, note = tablet_route(the_port)
    stages.append({"stage": "tablet", "state": "ok" if host else "warn",
                   "detail": f"https://{host}/" if host else note})
    health = read_health(the_port, fresh=True)
    build = current_build(health)
    # Step 11: mark successful. This is the only thing that writes logs/last_known_good.json
    # besides `mark-good`, and it happens after /health was read back, never before.
    marked = None
    if doc.get("verified") and health:
        marked = _mark(build, health, why="apply")
        stages.append({"stage": "mark", "state": "ok", "detail": f"{build['short']} recorded as known good"})
    else:
        stages.append({"stage": "mark", "state": "skip", "detail": "the backend did not read back healthy, so nothing was marked"})
    return envelope(
        "apply", ok=True, update=doc, stages=stages,
        tablet={"host": host or "", "url": f"https://{host}/" if host else "", "note": note},
        marked_good=marked,
        build={"current": build, "was": build_before, "candidate": doc.get("candidate"), "last_known_good": marked or good},
        rollback=rollback_decision(current=build, good=marked or good, blocking=[]),
        next="done" if marked else "verify_by_hand",
    )


def _mark(build: dict, health: dict, *, why: str) -> dict:
    record = {
        "version": 1, "sha": build.get("sha", ""), "short": build.get("short", ""),
        "branch": build.get("branch", ""), "subject": build.get("subject", ""),
        "build": str(health.get("build") or ""), "status": str(health.get("status") or ""),
        "recorded_at": round(time.time(), 3), "recorded_by": f"crooks-control {why}",
    }
    write_known_good(record)
    return record


def mark_good_document() -> dict:
    """Record the running build as the one to come back to. Refuses a build that is not
    answering, or one whose essentials are down: a "known good" that was never good is worse
    than none, because it is what a rollback would choose."""
    the_port = port()
    health = read_health(the_port, fresh=True)
    build = current_build(health)
    if not health:
        return envelope("mark-good", ok=False, marked_good=None, build={"current": build},
                        stop={"stage": "health", "reason": f"Nothing is answering on 127.0.0.1:{the_port}, so this build is not known to be good."})
    down = [name for name in ESSENTIAL if not (checks_of(health).get(name) or {}).get("ok", False)]
    if down:
        return envelope("mark-good", ok=False, marked_good=None, build={"current": build},
                        stop={"stage": "health", "reason": f"Not marked: {', '.join(down)} " + ("is" if len(down) == 1 else "are") + " down on this build."})
    if build.get("detached"):
        # Deliberate: after a rollback the checkout is detached, and marking THAT as good
        # would make the rollback target the build the owner just came back from.
        return envelope("mark-good", ok=False, marked_good=None, build={"current": build},
                        stop={"stage": "branch", "reason": "This checkout is on a detached HEAD (a rollback leaves it that way). `git checkout <branch>` first."})
    return envelope("mark-good", ok=True, marked_good=_mark(build, health, why="mark-good"), build={"current": build},
                    next="done")


def rollback_document(*, yes: bool) -> dict:
    """Go back to the last known-good build, where that is safe. Never a reset, never a clean:
    a checkout of a commit that is already here, and then the restart the owner would type."""
    the_port = port()
    dirty = _dirty()
    blocking = update_module().blocking_changes(dirty)
    build = current_build(read_health(the_port))
    good = read_known_good()
    decision = rollback_decision(current=build, good=good, blocking=blocking)
    if not decision["safe"]:
        return envelope("rollback", ok=False, rollback=decision, build={"current": build, "last_known_good": good},
                        stages=[], stop={"stage": "decide", "reason": decision["reason"]}, next="blocked")
    if not yes:
        return envelope("rollback", ok=False, rollback=decision, build={"current": build, "last_known_good": good},
                        stages=[], stop={"stage": "click", "reason": "A rollback moves the build. `crooks-control rollback --yes`, or the app's button."},
                        next="click_to_apply")
    stages = []
    moved, detail = checkout(decision["sha"])
    stages.append({"stage": "checkout", "state": "ok" if moved else "fail", "detail": detail or decision["short"]})
    if not moved:
        return envelope("rollback", ok=False, rollback=decision, build={"current": current_build(None), "last_known_good": good},
                        stages=stages, stop={"stage": "checkout", "reason": detail or "git refused the checkout"}, next="blocked")
    try:
        upd = update_module()
        upd.stage_restart(check_only=False, port=the_port)
        import launch_common as lc

        stages.append({"stage": "restart", "state": "ok",
                       "detail": f"{' and '.join(lc.service_labels())} restarted"})
    except Exception as exc:  # noqa: BLE001 — a refused launchctl is a state, not a crash
        stages.append({"stage": "restart", "state": "fail", "detail": str(exc)[:300]})
        return envelope("rollback", ok=False, rollback=decision, build={"current": current_build(None), "last_known_good": good},
                        stages=stages, stop={"stage": "restart", "reason": str(exc)[:300]}, next="restart_by_hand")
    health = read_health(the_port, fresh=True)
    stages.append({"stage": "verify", "state": "ok" if health else "fail",
                   "detail": str((health or {}).get("build") or "the backend did not answer")})
    return envelope("rollback", ok=bool(health), rollback=decision, stages=stages,
                    build={"current": current_build(health), "last_known_good": good},
                    next="done" if health else "verify_by_hand")


# --------------------------------------------------------------------------- the buttons


def actions_document() -> dict:
    """The twelve buttons, and the command behind each. The app draws this list; it hard-codes
    no command of its own, so a command that changes here changes there.

    kind:  "control"  run this same script and render the JSON it prints
           "shell"    run it and show the output as it arrives
           "open_url" hand it to the browser
           "open_path" reveal it in the Finder
    """
    import launch_common as lc

    the_port = port()
    host, _note = tablet_route(the_port)
    py = str(ROOT / ".venv" / "bin" / "python")
    control_py = str(HERE / "control.py")
    # launchd on the Mac, systemd on the server. The button is the same button; only the
    # command behind it and the words on the confirmation differ.
    installer = str(lc.installer_script())
    supervised = " and ".join(lc.service_labels())
    return envelope("actions", actions=[
        {"id": "open", "label": "Open CROOKS OS", "kind": "open_url", "group": "use",
         "url": f"https://{host}/" if host else f"http://127.0.0.1:{the_port}/", "confirm": False,
         "why": "the tablet's own page, on this Mac's browser"},
        {"id": "restart", "label": "Restart", "kind": "shell", "group": "use",
         "command": [py, installer, "--restart"], "cwd": str(ROOT), "confirm": True,
         "confirm_text": f"Restart {supervised}? Anything mid-sentence on the tablet will stop.",
         "why": f"{supervised}, restarted — the same as `make restart`"},
        {"id": "check", "label": "Check for update", "kind": "control", "group": "update",
         "command": [py, control_py, "plan"], "cwd": str(ROOT), "confirm": False,
         "why": "fetches, shows both SHAs, changes nothing"},
        {"id": "update", "label": "Update", "kind": "control", "group": "update",
         "command": [py, control_py, "apply", "--yes"], "cwd": str(ROOT), "confirm": True,
         "confirm_text": "Fast-forward to the candidate build, run the offline suite, restart and verify?",
         "why": "the whole update; it stops rather than move a dirty tree", "needs_plan": True},
        {"id": "rollback", "label": "Roll back", "kind": "control", "group": "update",
         "command": [py, control_py, "rollback", "--yes"], "cwd": str(ROOT), "confirm": True,
         "confirm_text": "Go back to the last known-good build and restart?",
         "why": "only offered when a known-good build is recorded and the tree is clean"},
        {"id": "tests", "label": "Run tests", "kind": "shell", "group": "test",
         "command": [str(ROOT / ".venv" / "bin" / "pytest"), "-q", "-m", "not live"], "cwd": str(ROOT), "confirm": False,
         "why": "the offline suite — the same as `make test`"},
        {"id": "tests_ui", "label": "Run UI tests", "kind": "shell", "group": "test",
         "command": [py, str(HERE / "experience.py"), "--ui"], "cwd": str(ROOT), "confirm": False,
         "why": "the golden scenarios, and the page driven in Chromium — the same as crooks-test-ui"},
        {"id": "session_start", "label": "Start live recording", "kind": "shell", "group": "test",
         "command": [py, str(HERE / "test_session.py"), "start", "--name", "from the Control app"], "cwd": str(ROOT), "confirm": False,
         "why": "begins a test session; nothing restarts and the tablet joins within a poll"},
        {"id": "session_stop", "label": "Stop recording", "kind": "shell", "group": "test",
         "command": [py, str(HERE / "test_session.py"), "stop"], "cwd": str(ROOT), "confirm": False,
         "why": "ends it"},
        {"id": "report", "label": "Generate report", "kind": "shell", "group": "test",
         "command": [py, str(HERE / "test_session.py"), "report"], "cwd": str(ROOT), "confirm": False,
         "why": "writes reports/<session>.md from the timeline"},
        {"id": "report_open", "label": "Open latest report", "kind": "open_path", "group": "test",
         "path": str(ROOT / "reports"), "confirm": False,
         "why": "the newest file in reports/ — the app opens it, or the folder when there is none"},
        {"id": "logs", "label": "Open logs", "kind": "open_path", "group": "look",
         "path": str(ROOT / "logs"), "confirm": False, "why": "assistant.out.log and its neighbours"},
        {"id": "folder", "label": "Open project folder", "kind": "open_path", "group": "look",
         "path": str(ROOT), "confirm": False, "why": "the checkout itself"},
    ])


def contract_document() -> dict:
    """What every field means. Written down here rather than in a comment on the Swift side,
    so there is one description and the test suite can check the app renders what it names."""
    return envelope("contract", version=CONTRACT, envelope_keys=["contract", "command", "ok", "at"], documents={
        "status": {
            "state": f"one of {', '.join(COLOURS)} — RED beats BLUE beats AMBER beats GREEN",
            "headline": "the one line for the menu bar, e.g. 'CROOKS — Online'",
            "why": "the sentence under it: what is down, or read-only, or recording",
            "issues": "the essential subsystems that are down — the reason for RED",
            "degraded": "what is down, off or unrouted without being essential — the reason for AMBER",
            "rows": "[{key,label,state:ok|off|bad,value,detail}] in the order the app draws them",
            "build": "{current:{sha,short,branch,detached,subject,build,version}, candidate:null, last_known_good, note}",
            "tablet": "{host,url,note,local}", "mutation": "the capability families' verdict, from /health",
            "test_session": "{active,id,name}", "local_work": "{dirty[],blocking[],stops}",
            "rollback": "{available,safe,sha,short,recorded_at,build,reason,commands,note}", "port": "the loopback port",
        },
        "plan": {"update": "the whole `crooks-update --json` document", "click": "{label,command,enabled}",
                 "build": "{current,candidate,last_known_good}", "local_work": "{dirty[],blocking[],stops}",
                 "rollback": "the decision as it stands now", "next": "click_to_apply | up_to_date | blocked",
                 "stop": "on `apply` without --yes: why nothing moved"},
        "apply": {"update": "as above, with moved/tested/restarted/verified", "stages": "[{stage,state,detail}] — tablet, mark",
                  "tablet": "{host,url,note} — the route verified after the restart, or null",
                  "marked_good": "what was written to logs/last_known_good.json, or null",
                  "build": "{current,was,candidate,last_known_good}", "local_work": "as above, when it stopped on one",
                  "rollback": "the decision, which is what to do when this failed", "click": "as `plan`, when the click is missing",
                  "stop": "{stage,reason} when it stopped", "next": "done | up_to_date | rollback | blocked | verify_by_hand | click_to_apply"},
        "rollback": {"rollback": "the decision, whether or not it ran", "stages": "checkout, restart, verify",
                     "build": "{current,last_known_good}", "stop": "{stage,reason} when it refused",
                     "next": "done | blocked | click_to_apply | restart_by_hand | verify_by_hand"},
        "mark-good": {"marked_good": "the record written, or null", "build": "{current}",
                      "stop": "{stage,reason} why it refused", "next": "done"},
        "actions": {"actions": "[{id,label,kind,group,command|url|path,confirm,confirm_text,why}]"},
        "contract": {"version": "the number every document above carries", "envelope_keys": "on every document",
                     "documents": "this", "states": "what each colour means"},
    }, states={
        "GREEN": "live and healthy", "BLUE": "a test session is recording",
        "AMBER": "live but read-only, or something non-essential is down, or no tablet route",
        "RED": f"nothing answering, or one of {', '.join(ESSENTIAL)} is down",
    })


# --------------------------------------------------------------------------- the command


def build_document(args) -> tuple[int, dict]:
    if args.what == "status":
        doc = status_document(fresh=args.fresh)
    elif args.what == "plan":
        doc = plan_document(args.branch)
    elif args.what == "apply":
        doc = apply_document(yes=args.yes, branch=args.branch, run_tests=not args.no_tests)
    elif args.what == "rollback":
        doc = rollback_document(yes=args.yes)
    elif args.what == "mark-good":
        doc = mark_good_document()
    elif args.what == "actions":
        doc = actions_document()
    else:
        doc = contract_document()
    return (0 if doc.get("ok") else 1), doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["status", "plan", "apply", "rollback", "mark-good", "actions", "contract"],
                        nargs="?", default="status")
    parser.add_argument("--yes", action="store_true", help="apply / rollback: the click. Without it, nothing moves.")
    parser.add_argument("--branch", default="", help="the branch this checkout should be on")
    parser.add_argument("--fresh", action="store_true", help="status: skip /health's cache")
    parser.add_argument("--no-tests", action="store_true", help="apply: skip the offline suite (not recommended)")
    args = parser.parse_args(argv)
    try:
        code, doc = build_document(args)
    except Exception as exc:  # noqa: BLE001 — the app gets a document whatever happens
        code, doc = 1, envelope(args.what, ok=False, stop={"stage": "control", "reason": f"{type(exc).__name__}: {exc}"})
    print(json.dumps(redact(doc), indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
