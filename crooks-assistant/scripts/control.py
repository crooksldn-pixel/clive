#!/usr/bin/env python3
"""crooks-control — what CROOKS Control shows, and what its buttons run.

The Mac app is a renderer. Every decision it appears to make is made here, in Python, where
it can be tested; the app reads one JSON document per subcommand and draws it.

    crooks-control status      the colour, every row, the build ids     (no network, no fetch)
    crooks-control start       start CROOKS OS, from stopped, from never-installed, from stuck
    crooks-control stop        stop it, and prove it stopped
    crooks-control restart     stop and start, and read /health back
    crooks-control plan        what an update would do: current vs candidate SHA
    crooks-control apply --yes do it: update, tests, restart, verify, tablet, mark good —
                               and, when the new build does not come up healthy, put it back
    crooks-control rollback --yes   go back to the last known-good build, where that is safe
    crooks-control mark-good   record the running build as the one to come back to
    crooks-control session-start [--label "first hour"]   begin an hour with the tablet
    crooks-control session-status                         elapsed, turns, owner feedback
    crooks-control session-stop                           stop, keep the raw timeline, analyse
    crooks-control actions     every button, with the command behind each
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

Until Phase 6 this command could describe the Mac and update it but could not TURN IT ON: the
RED state said, in as many words, "`make up`, or `make install` to have it start at login" —
an instruction to open a Terminal, which is the one thing the appliance exists to remove. The
lifecycle lives in `scripts/service.py` now and start/stop/restart are operations here, each
of which succeeds only when /health answers and never because a subprocess exited 0.

What this command will not do:

  * update anything without --yes. A click is the click; nothing here runs on a timer, on a
    boot, or from inside CROOKS OS. `scripts/update.py` says the same thing about itself.
    start, stop and restart need no --yes: none of them moves the build, and a Start that
    asks the owner to confirm that he meant to press Start is not a Start button.
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
#
# 2 (Phase 6): start, stop, restart, the three session documents, and two new fields on
# `status` — `lifecycle` and `pad`. PURELY ADDITIVE: every field version 1 printed is still
# printed, unchanged, which is why 1 is still listed in the contract's `compatible_clients`.
# A client built against 1 renders correctly against 2 if it is willing to accept the number;
# mac/CrooksControl compares for equality and so must be rebuilt. That is stated in the
# contract document rather than left to be discovered.
CONTRACT = 2
COMPATIBLE_CLIENTS = (1, 2)
LOG_DIR = ROOT / "logs"
# The build to come back to. Written by `crooks-control apply` when an update verifies, and by
# `crooks-control mark-good`; read by the rollback decision. Nothing else writes it, nothing
# in CROOKS OS reads it, and it is inside logs/ — which the updater never touches.
KNOWN_GOOD_FILE = "last_known_good.json"

COLOURS = ("GREEN", "BLUE", "AMBER", "RED")
# The three the assistant cannot work without. Straight from scripts/status.py's verdict.
ESSENTIAL = ("speech", "claude", "shopify")
# How long since CROOKS Pad last said anything before it stops counting as being there. Two
# minutes rather than thirty seconds because the tablet sleeps, and a tablet asleep beside the
# till is not a tablet that has gone away.
PAD_STALE_S = 120.0

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


# A commit id, and nothing else, may be put on git's command line as a revision. Anything
# beginning with '-' is read by git as an OPTION — and one of git's options names a program
# for it to execute (`--upload-pack`) — so the value that comes off disk in
# logs/known-good.json is checked against this before it is ever an argument.
#
# `--` does NOT solve this. `git checkout -- <sha>` tells git the argument is a PATHSPEC: it
# exits 1 with "pathspec did not match any file" and checks nothing out, so the rollback would
# quietly stop rolling back. The revision has to stay a revision; what makes it safe is that
# it cannot be anything but hexadecimal.
COMMIT_SHA = re.compile(r"[0-9a-f]{7,40}")
NOT_A_COMMIT = "is not a commit id, so nothing was checked out"


def is_commit_id(sha: str) -> bool:
    return bool(COMMIT_SHA.fullmatch(str(sha or "")))


def checkout(sha: str, cwd: Path | None = None) -> tuple[bool, str]:
    """The only git command here that moves anything, used by the rollback and nowhere else.
    A checkout of an existing commit cannot lose a commit; the rollback still refuses to run
    it while the tree is dirty, because carrying uncommitted work onto an older build is not
    what the owner asked for.

    `--detach` states the intent the rollback document already describes in words, and the
    trailing `--` says there is no pathspec — so the argument cannot be read as a file either.
    """
    if not is_commit_id(sha):
        return False, f"{str(sha)[:40]!r} {NOT_A_COMMIT}"
    out = subprocess.run(["git", "checkout", "--detach", sha, "--"], cwd=cwd or ROOT,
                         capture_output=True, text=True, timeout=120)
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


def essentials_down(health: dict | None) -> list[str]:
    """Which of the three the assistant cannot work without are not working. One definition,
    used by the colour and by the lifecycle sentence, so those two can never disagree.

    Nothing answering at all returns [] and not all three: "the Mac is not running" and "the
    Mac is running and Shopify is down" are different facts, and flattening them here would
    make a stopped Mac report three broken subsystems it has not been able to ask about.
    """
    if not health:
        return []
    checks = checks_of(health)
    return [name for name in ESSENTIAL if name in checks and not checks[name].get("ok")]


# --------------------------------------------------------------------------- is the tablet there


def _number(raw: dict, *keys: str) -> float | None:
    """The first of these keys that carries a number. Order is the point: the name the backend
    really prints comes first, and the rest are compatibility, not choice."""
    for key in keys:
        try:
            return float(raw[key])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _text(raw: dict, *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def pad_status(health: dict | None) -> dict:
    """Is CROOKS Pad actually alive? (§16.)

    The Tablet row below answers a different question: whether Tailscale is serving the
    address. That is the door being open, not anybody having come through it — a tablet that
    is off, asleep in a drawer, or showing a crashed page leaves the route exactly as it was.
    Only the tablet saying so answers it, and the backend is what hears it.

    THE LAYERING, which is the whole of CONTRACT 1 as it touches this file:

        the pad (Kotlin) -> the backend (POST /pad/heartbeat, PadRegistry)
                         -> GET /health, the `pad` block   <- read HERE, by ITS names
                         -> this function's own key names  <- read by CROOKS Control (Swift)

    The backend's block is the authoritative wire shape and its spellings come FIRST:
    `connected`, `last_seen_s`, `last_seen`, `app_version`, `stale_after_s`. The looser
    spellings below them are kept only because the two halves of Phase 6 were written at the
    same time and a Mac can be running a backend from either — they are fallbacks, not
    alternatives, and nothing new should be added to them.

    `app_version` is what fills `app`, and getting that wrong is not cosmetic: this layer read
    `app` and then `client`, and neither of those is in the settled shape at all — so the line
    naming which CROOKS Pad is on the other end comes out EMPTY against a backend that keeps
    to it, and an empty one is indistinguishable from a pad that has not said.

    `last_seen` is read as epoch seconds. If it ever arrives as a formatted instant instead it
    is ignored rather than misread, and `last_seen_s` — which is the primary — carries the age.

    An explicit `connected` outranks our arithmetic, and where the backend states its own
    `stale_after_s` that number wins over PAD_STALE_S too: the backend is the one holding the
    socket, and two sides keeping separate opinions about when a pad is stale is how the Mac
    and the app come to draw different colours over the same tablet.

    What this function prints is a FIXED set of eight keys — known, alive, age_s, app, version,
    build, source, detail — the same whatever the backend said and the same when it said
    nothing, because the Swift app decodes these and not the backend's.

    A build that reports none of it is reported as NOT KNOWN — never as a tablet that has gone
    away. An absent field is ignorance, and ignorance drawn as a red light is how a status
    screen teaches its owner to stop reading it.
    """
    raw, source = None, "absent"
    for key in ("pad", "tablet"):
        value = (health or {}).get(key)
        if isinstance(value, dict) and value:
            raw, source = value, key
            break
    if raw is None:
        return {"known": False, "alive": None, "age_s": None, "app": "", "version": "", "build": "",
                "source": source,
                "detail": "this build does not say whether the tablet has been heard from; the route being open is not a heartbeat"}
    # An AGE, in seconds. `last_seen_s` is the backend's name; the two after it are the older
    # spellings this side accepted before the shape was settled.
    age = _number(raw, "last_seen_s", "age_s", "seen_s_ago")
    if age is None:
        # An INSTANT, as epoch seconds. `last_seen` is the backend's; `last_seen_at` is older.
        for key in ("last_seen", "last_seen_at"):
            when = _number(raw, key)
            if when is not None:
                age = max(0.0, time.time() - when)
                break
    # The backend's own staleness window, where it states one. Its number, not ours.
    stale_after = _number(raw, "stale_after_s")
    if stale_after is None or stale_after <= 0:
        stale_after = PAD_STALE_S
    stated = raw.get("connected", raw.get("alive"))
    alive = bool(stated) if isinstance(stated, bool) else (None if age is None else age <= stale_after)
    if alive is None:
        detail = "the build reports the tablet but not when it was last heard from"
    elif alive:
        detail = f"last heard from {_hours(age)} ago" if age is not None else "the backend says it is connected"
    else:
        detail = f"not heard from for {_hours(age)}" if age is not None else "the backend says it is not connected"
    return {"known": True, "alive": alive, "age_s": (round(age, 1) if age is not None else None),
            # `app_version` first: it is the only one of these the backend actually prints.
            "app": _text(raw, "app_version", "app", "client")[:40],
            "version": _text(raw, "version", "app_version")[:40],
            "build": _text(raw, "build")[:60],
            "source": source, "detail": detail}


# --------------------------------------------------------------------------- the lifecycle seam


def service_module(machine=None):
    """The lifecycle layer for the platform in front of us: scripts/service.py talks to launchd
    on the Mac, scripts/service_linux.py to systemd on the server. Same envelope, same rule
    that only /health counts. When a Machine is given, ITS answer to "is this a Mac" decides,
    so a test that hands in a Mac gets the Mac's layer on any host."""
    import launch_common as lc

    on_mac = machine.is_macos() if machine is not None else lc.is_macos()
    if on_mac:
        from scripts import service as _service

        return _service
    from scripts import service_linux as _service

    return _service


def session_module():
    from scripts import session_ops as _session_ops

    return _session_ops


def machine_for(the_port: int):
    """The Mac, as the lifecycle layer talks to it. Built around THIS module's `read_health`
    rather than around a second reader of its own, so that a test which bends /health bends
    every question that depends on it — the colour, the rows and the lifecycle alike."""
    import launch_common as lc

    from scripts import service as svc

    return svc.Machine(
        runner=svc.Subprocesses(),
        read_health=lambda fresh=False: read_health(the_port, fresh=fresh),
        port_open=lambda: lc.port_open("127.0.0.1", the_port),
        ensure_route=lambda: lc.ensure_serve(the_port),
        log_dir=Path(LOG_DIR),
    )


def launchd_for(machine):
    """The supervisor for this machine: launchd on the Mac, systemd on the server. Named for
    the Mac's, which came first, and kept under that name because it is the seam tests
    replace."""
    return service_module(machine).supervisor(machine, root=ROOT)


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


def roll_up(health: dict | None, *, tablet_host: str | None, session: dict, mutation: dict, the_port: int,
            pad: dict | None = None) -> dict:
    """One colour, and the sentence under it. A pure function of what was read, so every
    colour can be driven from a document in a test."""
    pad = pad or {"known": False}
    if not health:
        return {
            "state": "RED", "headline": "CROOKS — Offline",
            # This sentence used to read "`make up`, or `make install` to have it start at
            # login". That was the defect §5.2 exists to remove: the normal recovery from a
            # stopped appliance cannot be an instruction to open a Terminal. It is a button,
            # and the button is `crooks-control start`, which works from here.
            "why": f"nothing is answering on 127.0.0.1:{the_port}. Press Start.",
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
    # "tablet route" is Tailscale; "tablet" is the tablet. A pad this build knows nothing
    # about is never degraded on that account — see pad_status() on why ignorance is not
    # evidence.
    pad_gone = bool(pad.get("known")) and pad.get("alive") is False
    if pad_gone:
        degraded.append("tablet")
    if degraded:
        read_only = mutation.get("state") in ("read_only", "blocked")
        return {
            "state": "AMBER",
            "headline": "CROOKS — Read only" if read_only and len(degraded) == 1 else "CROOKS — Degraded",
            "why": _sentence_for(checks, down, mutation=mutation if mutation.get("state") != "ready" else None,
                                 tablet=not tablet_host, pad=pad if pad_gone else None),
            "issues": [], "degraded": degraded,
        }
    return {"state": "GREEN", "headline": "CROOKS — Online", "why": "everything answering, changes ready, tablet routed",
            "issues": [], "degraded": []}


def _sentence_for(checks: dict[str, dict], down: list[str], *, mutation: dict | None = None, tablet: bool = False,
                  pad: dict | None = None) -> str:
    parts = [f"{name}: {str(checks.get(name, {}).get('detail') or 'down')[:80]}" for name in down]
    if mutation is not None:
        parts.append(str(mutation.get("detail") or "changes are off"))
    if tablet:
        parts.append("Tailscale is not serving the tablet's address")
    if pad is not None:
        parts.append(f"CROOKS Pad {str(pad.get('detail') or 'has not been heard from')}")
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
    if not is_commit_id(sha):
        # `git cat-file -e -x^{commit}` is read as a switch for exactly the reason the
        # checkout was, so the record is refused here too rather than handed to git.
        out["reason"] = (f"The recorded known-good build ({sha[:10]!r}) {NOT_A_COMMIT}. "
                         "`crooks-control mark-good` records the build that is running now.")
        return out
    if not git_ok("cat-file", "-e", f"{sha}^{{commit}}", cwd=repo):
        out["reason"] = (f"The last known-good commit ({sha[:10]}) is not in this checkout, so it cannot be gone back to. "
                         "Press Check for update, which fetches, and then try again.")
        return out
    out["available"] = True
    # What this document says is what this program actually runs — both of them. The second
    # used to read `make restart`: a Makefile target, in a field the app draws, describing a
    # step the rollback performs itself and has never asked the owner to perform. It is not
    # even the right command any more, because the restart stage is service.restart() now —
    # the same thing the app's Restart button is.
    out["commands"] = [["git", "checkout", "--detach", sha, "--"],
                       [str(ROOT / ".venv" / "bin" / "python"), str(HERE / "control.py"), "restart"]]
    out["note"] = (f"Rolling back leaves this checkout on a detached HEAD at build {sha[:10]}, which is "
                   f"deliberate: nothing is moved and nothing is lost. Pressing Update afterwards comes forward "
                   f"onto {current.get('branch') or 'the branch'} again.")
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
             session: dict, mutation: dict, the_port: int, pad: dict | None = None,
             life: dict | None = None) -> list[dict]:
    """Every line the brief asks the app to show, in the order it asks for them. One shape, so
    the app draws a list and nothing more."""
    host, note = tablet
    pad = pad or {"known": False, "detail": ""}
    rows = []
    if not health:
        # The detail used to be "`make up` … or `make install`". §5.2: the recovery from a
        # stopped appliance is a button, and the sentence under the button says what the
        # lifecycle layer actually found — stopped, never installed, or stuck.
        rows.append(_row("online", "Online", STATE_BAD, f"nothing answering on 127.0.0.1:{the_port}",
                         str((life or {}).get("human") or "Press Start.")))
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
    # The row above is the door; this one is whether anybody came through it. Unknown is its
    # own state — neither a tick nor a cross — because a build that cannot answer the question
    # must not be drawn as an answer.
    if not pad.get("known"):
        rows.append(_row("pad", "CROOKS Pad", STATE_OFF, "unknown", str(pad.get("detail") or "")))
    else:
        alive = pad.get("alive")
        rows.append(_row("pad", "CROOKS Pad",
                         STATE_OK if alive else (STATE_OFF if alive is None else STATE_BAD),
                         ("here" if alive else ("unknown" if alive is None else "not here"))
                         + (f" · {pad.get('app')}" if pad.get("app") else ""),
                         str(pad.get("detail") or "")))
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
    pad = pad_status(health)
    build = current_build(health)
    good = read_known_good()
    # The lifecycle is asked even when /health answers, because "it is running" and "it is
    # running as a login service" are different facts and only the second one survives the
    # window being closed. It costs two `launchctl print`s on a poll the app makes every few
    # seconds, which is the cheapest true answer available.
    machine = machine_for(the_port)
    life = service_module(machine).lifecycle(machine, launchd_for(machine), port=the_port, health=health,
                                      unwell=essentials_down(health))
    state = roll_up(health, tablet_host=tablet[0], session=session, mutation=mutation, the_port=the_port, pad=pad)
    dirty = _dirty()
    return envelope(
        "status", ok=state["state"] != "RED", **state,
        rows=rows_for(health, build=build, good=good, tablet=tablet, session=session, mutation=mutation,
                      the_port=the_port, pad=pad, life=life),
        build={"current": build, "candidate": None, "last_known_good": good,
               "note": "the candidate build is read by `plan`, which fetches; status never touches the network"},
        tablet={"host": tablet[0] or "", "url": f"https://{tablet[0]}/" if tablet[0] else "", "note": tablet[1],
                "local": f"http://127.0.0.1:{the_port}/"},
        pad=pad, lifecycle=life,
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


def apply_document(*, yes: bool, branch: str = "", run_tests: bool = True, recover: bool = True) -> dict:
    """The update, end to end, in the brief's order: inspect, fetch, show both SHAs, require a
    click, fast-forward only, dependencies, tests, restart, verify /health, verify the tablet
    route, mark successful. The first six and the restart and the health read are update.py's
    (one implementation, one set of refusals); the rest is here.

    §5.5, and it is a correctness requirement rather than a nicety: AN UPDATE IS NOT A SUCCESS
    BECAUSE GIT PULL EXITED 0. It is a success when the new build becomes healthy. When it
    does not, this attempts the rollback itself rather than printing the decision and leaving
    it — the owner has no Terminal, and a half-updated Mac that says "you could roll back" is
    a broken appliance with a suggestion attached.

    "Healthy" is measured against the build that was running BEFORE the update, not against
    perfection. A new build that comes up with Shopify down did not break Shopify; rolling
    back for an outage would be churn with an air of competence. What triggers the recovery is
    the backend not answering at all, or an essential that was working before this update and
    is not working now.
    """
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
    # Fresh, and deliberately: /health answers from a ninety-second cache, and this reading is
    # the one the whole rollback decision is measured against. A cached answer from eighty
    # seconds ago showing Shopify up, against a fresh one showing it down, reads as "this
    # update broke the store" and rolls back a perfectly good build over somebody else's
    # outage. Once per update, the real check is worth the few seconds it costs.
    before_health = read_health(the_port, fresh=True)
    code, doc = upd.run(check=False, branch=branch, test=run_tests, quiet=True)
    build_before = doc.get("current") or {}
    good = read_known_good()
    if code != 0:
        build = current_build(read_health(the_port))
        decision = rollback_decision(current=build, good=good, blocking=(doc.get("local_work") or {}).get("blocking") or [])
        recovery = None
        if recover and doc.get("moved") and decision.get("safe"):
            recovery = _recover(decision, the_port=the_port, stages=stages)
        return envelope(
            "apply", ok=False, update=doc, stages=stages, tablet=None, marked_good=None,
            build={"current": current_build(read_health(the_port)), "candidate": doc.get("candidate"), "last_known_good": good},
            rollback=decision, recovery=recovery,
            next=_after_recovery(recovery, doc, decision),
            stop=doc.get("stop"),
        )
    if not doc.get("moved"):
        stages.append({"stage": "tablet", "state": "skip", "detail": "nothing moved, so nothing to verify"})
        return envelope("apply", ok=True, update=doc, stages=stages, tablet=None, marked_good=None,
                        build={"current": current_build(read_health(the_port)), "candidate": doc.get("candidate"), "last_known_good": good},
                        rollback=rollback_decision(current=current_build(None), good=good, blocking=[]),
                        recovery=None, next="up_to_date")
    # Step 10: the tablet's route. A missing route does NOT roll the update back — the Mac is
    # well and only the tablet's door is shut — but it is why the colour is AMBER afterwards.
    host, note = tablet_route(the_port)
    stages.append({"stage": "tablet", "state": "ok" if host else "warn",
                   "detail": f"https://{host}/" if host else note})
    health = read_health(the_port, fresh=True)
    build = current_build(health)
    regressed = _regressed(before_health, health)
    healthy = bool(doc.get("verified")) and health is not None and not regressed
    stages.append({"stage": "healthy", "state": "ok" if healthy else "fail",
                   "detail": "the new build answers and nothing that worked before is down" if healthy
                   else ("the backend did not answer after the restart" if health is None
                         else f"this update broke: {', '.join(regressed)}")})
    if not healthy:
        decision = rollback_decision(current=build, good=good, blocking=[])
        recovery = _recover(decision, the_port=the_port, stages=stages) if recover and decision.get("safe") else None
        return envelope(
            "apply", ok=False, update=doc, stages=stages,
            tablet={"host": host or "", "url": f"https://{host}/" if host else "", "note": note},
            marked_good=None,
            build={"current": current_build(read_health(the_port)), "was": build_before,
                   "candidate": doc.get("candidate"), "last_known_good": good},
            rollback=decision, recovery=recovery,
            next=_after_recovery(recovery, doc, decision),
            stop={"stage": "healthy", "reason": stages[-1]["detail"] if recovery is None else recovery["human"]},
        )
    # Step 11: mark successful. This is the only thing that writes logs/last_known_good.json
    # besides `mark-good`, and it happens after /health was read back, never before.
    #
    # The bar here is higher than the bar for keeping the update. An essential that was
    # already down does not make the update a failure — it did not cause it — but it does
    # make this build a poor thing to come back TO, because a rollback target is chosen at
    # the moment everything is already going wrong. `mark-good` refuses that case too, and
    # the two now agree on the rule that matters: a build with an essential down is not a
    # thing to come back to.
    already = essentials_down(health)
    marked = None
    if already:
        stages.append({"stage": "mark", "state": "skip",
                       "detail": f"not recorded as known good: {', '.join(already)} " + ("is" if len(already) == 1 else "are")
                       + " down here, and was before this update too"})
    else:
        marked = _mark(build, health, why="apply")
        stages.append({"stage": "mark", "state": "ok", "detail": f"{build['short']} recorded as known good"})
    return envelope(
        "apply", ok=True, update=doc, stages=stages,
        tablet={"host": host or "", "url": f"https://{host}/" if host else "", "note": note},
        marked_good=marked,
        build={"current": build, "was": build_before, "candidate": doc.get("candidate"), "last_known_good": marked or good},
        rollback=rollback_decision(current=build, good=marked or good, blocking=[]),
        recovery=None, next="done",
    )


def _regressed(before: dict | None, after: dict | None) -> list[str]:
    """The essentials this update broke: down now, and not down before it ran. Something that
    was already down stays out of the list — the update did not do that, and undoing the
    update will not fix it."""
    if after is None:
        return list(ESSENTIAL)
    was_down = set(essentials_down(before)) if before else set()
    return [name for name in essentials_down(after) if name not in was_down]


def _recover(decision: dict, *, the_port: int, stages: list[dict]) -> dict | None:
    """Put the Mac back on the last build known to have worked, and say honestly whether that
    worked either. Never claims a restoration it did not verify.

    The virtualenv is deliberately not touched. If the update installed new dependencies they
    are still installed, and the older code runs against them — which is almost always fine,
    because the dependency that a build needs is the one it was released with or an earlier
    one. Reinstalling here would be a second thing that can fail while the Mac is already
    down, and a recovery that can fail twice is not a recovery.
    """
    if not decision.get("safe"):
        return None
    short = decision.get("short") or ""
    moved, detail = checkout(decision["sha"])
    stages.append({"stage": "restore", "state": "ok" if moved else "fail", "detail": detail or short})
    if not moved:
        return {"attempted": True, "ok": False, "sha": decision.get("sha", ""), "short": short, "restarted": False,
                "human": f"Update failed, and this Mac could not be put back to {short}. Nothing has been thrown away."}
    machine = machine_for(the_port)
    out = service_module(machine).restart(machine, launchd_for(machine), port=the_port)
    stages.append({"stage": "restore_restart", "state": "ok" if out["ok"] else "fail", "detail": out["human"]})
    if not out["ok"]:
        return {"attempted": True, "ok": False, "sha": decision.get("sha", ""), "short": short, "restarted": False,
                "human": f"Update failed. This Mac is back on {short}, but CROOKS OS did not come back up."}
    return {"attempted": True, "ok": True, "sha": decision.get("sha", ""), "short": short, "restarted": True,
            "human": f"Update failed. Restored {short}."}


def _after_recovery(recovery: dict | None, doc: dict, decision: dict) -> str:
    if recovery is not None:
        return "rolled_back" if recovery["ok"] else "recovery_failed"
    if doc.get("moved") and decision.get("safe"):
        return "rollback"
    return "blocked"


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
                        stop={"stage": "branch", "reason": "This checkout is on a detached HEAD (a rollback leaves it that way), and the build you came back to is already the one marked good. Press Update to come forward to the latest build."})
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

        # "kicked" was what this said when the restart was a kickstart and an exit code. The
        # stage it calls now registers the service where the supervisor does not have it and
        # reads /health back, and raises if that does not answer — so reaching this line means
        # the backend is up, and the detail says the fact rather than the verb.
        stages.append({"stage": "restart", "state": "ok",
                       "detail": f"{' and '.join(lc.service_labels())} restarted and answered"})
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


# ------------------------------------------------------------------ start, stop, restart


def _lifecycle_envelope(command: str, out: dict, *, the_port: int) -> dict:
    """One shape for all three, so the app draws one panel and not three. `human` is the
    sentence; `problem` is null or the owner's version of what went wrong with the developer's
    version folded inside it; `lifecycle` is what the Mac was found to be doing afterwards."""
    return envelope(command, ok=out["ok"], stages=out["stages"], problem=out["problem"],
                    lifecycle=out["lifecycle"], before=out.get("before"), human=out["human"],
                    note=out.get("note", ""), next=out["next"], port=the_port)


def start_document(*, wait_s: float = 0.0, machine=None) -> dict:
    """Start CROOKS OS. Works from stopped, from never-installed, and from stuck.

    There is no --yes. A press of Start is the whole of the owner's intent, and an appliance
    that asks whether you meant to turn it on is not one. Nothing here moves the build, so
    there is nothing a second thought would save.
    """
    the_port = port()
    mach = machine or machine_for(the_port)
    svc = service_module(mach)
    out = svc.start(mach, launchd_for(mach), port=the_port, wait_s=wait_s or svc.START_WAIT_S)
    return _lifecycle_envelope("start", out, the_port=the_port)


def stop_document(*, machine=None) -> dict:
    """Stop CROOKS OS, and prove it stopped. `bootout` exits 0 for a label that was never
    loaded and exits 0 the moment the signal is sent; neither is the fact being asked about."""
    the_port = port()
    mach = machine or machine_for(the_port)
    svc = service_module(mach)
    out = svc.stop(mach, launchd_for(mach), port=the_port)
    return _lifecycle_envelope("stop", out, the_port=the_port)


def restart_document(*, wait_s: float = 0.0, machine=None) -> dict:
    """Stop and start in one press, and read /health back — which `make restart` never did.
    It printed "kicked" and an exit code, and a service that died on its first import printed
    exactly the same thing."""
    the_port = port()
    mach = machine or machine_for(the_port)
    svc = service_module(mach)
    out = svc.restart(mach, launchd_for(mach), port=the_port, wait_s=wait_s or svc.START_WAIT_S)
    return _lifecycle_envelope("restart", out, the_port=the_port)


# ------------------------------------------------------------------ an hour with the tablet


def session_start_document(label: str = "") -> dict:
    out = session_module().start(port(), label=label)
    return envelope("session-start", ok=out["ok"], session=out, human=out["human"],
                    next="recording" if out["ok"] else "blocked")


def session_status_document() -> dict:
    out = session_module().status(port())
    return envelope("session-status", ok=out["ok"], session=out, human=out["human"],
                    next="recording" if out.get("active") else "idle")


def session_stop_document(*, analyse: bool = True) -> dict:
    """Stop, keep the raw timeline, and run the analysis that already exists. The paths come
    back so the app can open any of them: the report, the proposals, the raw JSONL, the
    folder they are all in."""
    out = session_module().stop_and_analyse(port(), analyse=analyse)
    return envelope("session-stop", ok=out["ok"], session=out, human=out["human"],
                    paths=out.get("paths") or {}, artefacts=out.get("artefacts") or [],
                    next="analysed" if out["ok"] else "blocked")


# --------------------------------------------------------------------------- the buttons


def actions_document() -> dict:
    """Every button, and the command behind each. The app draws this list; it hard-codes no
    command of its own, so a command that changes here changes there.

    kind:  "control"  run this same script and render the JSON it prints
           "shell"    run it and show the output as it arrives
           "open_url" hand it to the browser
           "open_path" reveal it in the Finder

    Start and Stop head the list because until Phase 6 they did not exist at all, and their
    absence is what made the RED state an instruction to open a Terminal. They are "control"
    and not "shell" for the same reason Restart now is: a shell button can only show text, and
    the one thing the owner needs to know afterwards — did it come back up — is a verdict,
    not a scroll of output.

    `ask` is a short free-text prompt the app puts up before running the command, appending
    the answer after `flag`. Exactly one action uses it (a session's label), it is optional,
    and it is the only place any text from the app reaches a command line. Everything else
    here is fixed argv: there is no shell, no string interpolation and nothing to escape.
    """
    import launch_common as lc

    the_port = port()
    host, _note = tablet_route(the_port)
    py = str(ROOT / ".venv" / "bin" / "python")
    control_py = str(HERE / "control.py")
    # launchd on the Mac, systemd on the server. The buttons are the same buttons and run the
    # same `crooks-control` commands; only the words naming what is supervised differ.
    supervised = " and ".join(lc.service_labels())
    return envelope("actions", actions=[
        {"id": "start", "label": "Start", "kind": "control", "group": "use",
         "command": [py, control_py, "start"], "cwd": str(ROOT), "confirm": False,
         "why": "starts CROOKS OS — and installs the login service first if this Mac has never had one"},
        {"id": "stop", "label": "Stop", "kind": "control", "group": "use",
         "command": [py, control_py, "stop"], "cwd": str(ROOT), "confirm": True,
         "confirm_text": "Stop CROOKS OS? The tablet stops working until it is started again.",
         "why": "stops the login service, and checks the address is actually free afterwards"},
        {"id": "open", "label": "Open CROOKS OS", "kind": "open_url", "group": "use",
         "url": f"https://{host}/" if host else f"http://127.0.0.1:{the_port}/", "confirm": False,
         "why": "the tablet's own page, on this Mac's browser"},
        {"id": "restart", "label": "Restart", "kind": "control", "group": "use",
         "command": [py, control_py, "restart"], "cwd": str(ROOT), "confirm": True,
         "confirm_text": f"Restart {supervised}? Anything mid-sentence on the tablet will stop.",
         "why": f"{supervised}, restarted and /health read back — the same as `make restart`"},
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
        {"id": "session_start", "label": "Start live recording", "kind": "control", "group": "test",
         "command": [py, control_py, "session-start"], "cwd": str(ROOT), "confirm": False,
         "ask": {"prompt": "Name this session", "flag": "--label", "placeholder": "first hour", "optional": True},
         "why": "begins a test session under a name you choose; nothing restarts and the tablet joins within a poll"},
        {"id": "session_status", "label": "Recording status", "kind": "control", "group": "test",
         "command": [py, control_py, "session-status"], "cwd": str(ROOT), "confirm": False,
         "why": "how long it has been running, how many turns, how much feedback — safe to poll"},
        {"id": "session_stop", "label": "Stop & analyse", "kind": "control", "group": "test",
         "command": [py, control_py, "session-stop"], "cwd": str(ROOT), "confirm": False,
         "why": "ends it, keeps the raw timeline, and runs the report and the proposals over it"},
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
    lifecycle_fields = {
        "stages": "[{stage,state:ok|warn|skip|fail,detail}] — check, clear, install, start/stop/restart, route, verify",
        "problem": "null, or {code,human,fix,developer}: `human` and `fix` are the owner's words and never carry an "
                   "exit status or a path; `developer` is the expansion field and is the only place they appear",
        "lifecycle": "{state,crooks_os,human,supervised,answering,healthy,agents[],port,window,logs}",
        "before": "the same, as it was before the press",
        "human": "the one sentence the app shows", "note": "what the owner should know afterwards, or ''",
        "next": "running | already_running | stopped | already_stopped | blocked",
        "port": "the loopback port",
    }
    return envelope("contract", version=CONTRACT, compatible_clients=list(COMPATIBLE_CLIENTS),
                    envelope_keys=["contract", "command", "ok", "at"], documents={
        "status": {
            "state": f"one of {', '.join(COLOURS)} — RED beats BLUE beats AMBER beats GREEN",
            "headline": "the one line for the menu bar, e.g. 'CROOKS — Online'",
            "why": "the sentence under it: what is down, or read-only, or recording",
            "issues": "the essential subsystems that are down — the reason for RED",
            "degraded": "what is down, off or unrouted without being essential — the reason for AMBER",
            "rows": "[{key,label,state:ok|off|bad,value,detail}] in the order the app draws them",
            "build": "{current:{sha,short,branch,detached,subject,build,version}, candidate:null, last_known_good, note}",
            "tablet": "{host,url,note,local} — the ROUTE, which is the door being open",
            "pad": "{known,alive,age_s,app,version,build,source,detail} — the TABLET, which is whether anybody came "
                   "through it. known:false means this build does not report a heartbeat, and is never drawn as absence",
            "lifecycle": "{state,crooks_os,human,supervised,answering,healthy,agents[],port,window,logs} — running as a "
                         "login service, running in a window, starting, stuck, stopped or never installed. Closing the "
                         "app's window changes none of it, and nothing here is read from the app",
            "mutation": "the capability families' verdict, from /health",
            "test_session": "{active,id,name}", "local_work": "{dirty[],blocking[],stops}",
            "rollback": "{available,safe,sha,short,recorded_at,build,reason,commands,note}", "port": "the loopback port",
        },
        "start": lifecycle_fields, "stop": lifecycle_fields, "restart": lifecycle_fields,
        "plan": {"update": "the whole `crooks-update --json` document", "click": "{label,command,enabled}",
                 "build": "{current,candidate,last_known_good}", "local_work": "{dirty[],blocking[],stops}",
                 "rollback": "the decision as it stands now", "next": "click_to_apply | up_to_date | blocked",
                 "stop": "on `apply` without --yes: why nothing moved"},
        "apply": {"update": "as above, with moved/tested/restarted/verified",
                  "stages": "[{stage,state,detail}] — tablet, healthy, then mark, or restore and restore_restart",
                  "tablet": "{host,url,note} — the route verified after the restart, or null",
                  "marked_good": "what was written to logs/last_known_good.json, or null",
                  "build": "{current,was,candidate,last_known_good}", "local_work": "as above, when it stopped on one",
                  "rollback": "the decision, which is what to do when this failed",
                  "recovery": "null, or {attempted,ok,sha,short,restarted,human} — what was done about a build that did "
                              "not come up healthy. `human` is 'Update failed. Restored <sha>.' and says so only when it was",
                  "click": "as `plan`, when the click is missing",
                  "stop": "{stage,reason} when it stopped",
                  "next": "done | up_to_date | rolled_back | recovery_failed | rollback | blocked | click_to_apply"},
        "rollback": {"rollback": "the decision, whether or not it ran", "stages": "checkout, restart, verify",
                     "build": "{current,last_known_good}", "stop": "{stage,reason} when it refused",
                     "next": "done | blocked | click_to_apply | restart_by_hand | verify_by_hand"},
        "mark-good": {"marked_good": "the record written, or null", "build": "{current}",
                      "stop": "{stage,reason} why it refused", "next": "done"},
        "session-start": {"session": "{ok,active,test_session_id,name,path,started_at,where,human}",
                          "human": "the sentence", "next": "recording | blocked"},
        "session-status": {"session": "{ok,active,test_session_id,name,path,where,events,progress,last,human} — progress is "
                                      "{elapsed_s,turns,owner_feedback,events,measured,why}, and measured:false with a "
                                      "reason is what a count too expensive to take looks like",
                           "human": "the sentence", "next": "recording | idle"},
        "session-stop": {"session": "the whole stop-and-analyse result", "paths": "{raw,folder,report,proposals}",
                         "artefacts": "[{name,ok,path,detail}] — a report that could not be written says so and the "
                                      "session is still saved", "human": "the sentence", "next": "analysed | blocked"},
        "actions": {"actions": "[{id,label,kind,group,command|url|path,confirm,confirm_text,why,ask?}]"},
        "contract": {"version": "the number every document above carries",
                     "compatible_clients": "the contract numbers a client may declare and still render these documents "
                                           "correctly. 2 is additive over 1: every field 1 printed is still printed",
                     "envelope_keys": "on every document",
                     "documents": "this", "states": "what each colour means"},
    }, states={
        "GREEN": "live and healthy", "BLUE": "a test session is recording",
        "AMBER": "live but read-only, or something non-essential is down, or no tablet route, or the tablet has gone quiet",
        "RED": f"nothing answering, or one of {', '.join(ESSENTIAL)} is down",
    })


# --------------------------------------------------------------------------- the command


WHAT = ["status", "start", "stop", "restart", "plan", "apply", "rollback", "mark-good",
        "session-start", "session-status", "session-stop", "actions", "contract"]


def build_document(args) -> tuple[int, dict]:
    if args.what == "status":
        doc = status_document(fresh=args.fresh)
    elif args.what == "start":
        doc = start_document(wait_s=args.wait)
    elif args.what == "stop":
        doc = stop_document()
    elif args.what == "restart":
        doc = restart_document(wait_s=args.wait)
    elif args.what == "plan":
        doc = plan_document(args.branch)
    elif args.what == "apply":
        doc = apply_document(yes=args.yes, branch=args.branch, run_tests=not args.no_tests,
                             recover=not args.no_recover)
    elif args.what == "rollback":
        doc = rollback_document(yes=args.yes)
    elif args.what == "mark-good":
        doc = mark_good_document()
    elif args.what == "session-start":
        doc = session_start_document(args.label)
    elif args.what == "session-status":
        doc = session_status_document()
    elif args.what == "session-stop":
        doc = session_stop_document(analyse=not args.no_analyse)
    elif args.what == "actions":
        doc = actions_document()
    else:
        doc = contract_document()
    return (0 if doc.get("ok") else 1), doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=WHAT, nargs="?", default="status")
    parser.add_argument("--yes", action="store_true", help="apply / rollback: the click. Without it, nothing moves.")
    parser.add_argument("--branch", default="", help="the branch this checkout should be on")
    parser.add_argument("--fresh", action="store_true", help="status: skip /health's cache")
    parser.add_argument("--no-tests", action="store_true", help="apply: skip the offline suite (not recommended)")
    parser.add_argument("--no-recover", action="store_true",
                        help="apply: do NOT put the Mac back when the new build fails to come up healthy (not recommended)")
    parser.add_argument("--wait", type=float, default=0.0, help="start / restart: seconds to wait for /health (default 90)")
    parser.add_argument("--label", default="", help="session-start: a short name for the session")
    parser.add_argument("--no-analyse", action="store_true", help="session-stop: stop, and do not write the report")
    args = parser.parse_args(argv)
    try:
        code, doc = build_document(args)
    except Exception as exc:  # noqa: BLE001 — the app gets a document whatever happens
        code, doc = 1, envelope(args.what, ok=False, stop={"stage": "control", "reason": f"{type(exc).__name__}: {exc}"})
    print(json.dumps(redact(doc), indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
