"""DEPLOY_LINUX.md "Deploying a new build", as code: check, change, verify, and roll back on any failure.

Why it exists: today every deploy is a prompt pasted into a Claude session on the server, which
reads the live SHA from git, saves the unit, runs the pre-checks, checks out the exact SHA, runs
`make install`, reads /health and the journal, and writes what it saw (reports/deploy-*.md). This is
the same procedure, step by step, with the same checks, so the record it writes reads like theirs.

    checked before anything changes   production is still where the facts said, its checkout clean;
                                       the checkout and the unit's folder writable; `make doctor`;
                                       the tailnet self-check; /health well; the unit, .env's and the
                                       drop-ins' fingerprints saved; the live build, run with the live
                                       unit's HOME and PATH, still renders the live unit byte for byte;
                                       the target's objects fetched; the started marker written
    the change                         git checkout --detach <sha>; the new build's gap_clean_check;
                                       the NEW build's unit rendered and byte-identical to the live one
                                       (as the b33ccbc2 deploy checked by hand), before make install;
                                       make install, with the PATH and HOME the live unit was made with
    verified after                     /health well and no check that was ok before now not ok; the
                                       service active with no restart; .env and the drop-ins untouched;
                                       the new process's journal free of tracebacks and errors; the
                                       unit make install wrote byte-identical to the saved copy

Each stage is reported as it is reached (`progress`: checks, installing, health), so the status CLIVE
reads follows the deploy as it happens (DEC-072). A failure before the change refuses with nothing changed. A failure at or after the checkout rolls
back: the previous SHA checked out; when `make install` ran, the saved unit put back, systemd
reloaded and `make install` run on the previous SHA; then /health read again. A rollback step that
fails leaves the outcome "halted", and the service then does nothing until a person has looked. A
deploy stopped part way (the process killed) leaves its started marker, and the next tick halts.

Nothing from the journal, /health's details or the commands' own output is kept beyond counts, check
names and the installer's own status lines: the record is pushed to a public repository.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.release import facts as facts_module
from app.release import state
from app.release.facts import Facts
from app.release.settings import TRUNK, ReleaseSettings

SERVICE = "crooks-assistant.service"
HEALTH_TIMEOUT_S = 60
INSTALL_TIMEOUT_S = 600
MAX_INSTALL_LINES = 30
_INSTALL_LINE = re.compile(r"^\s{1,4}(ok|FAIL|https|health|wait|undone|note)\b")
_UNIT_ENV = re.compile(r"^Environment=(HOME|PATH)=(.*)$")
JOURNAL_FAILURES = (
    ("a traceback", re.compile(r"Traceback \(most recent call last\)")),
    ("an ERROR or CRITICAL line", re.compile(r"\b(ERROR|CRITICAL)\b")),
    ("a report withheld", re.compile(r"\bwithheld\b")),
    ("a record not confirmed on disk", re.compile(r"not confirmed on disk")),
    ("the process exiting", re.compile(r"Main process exited|Failed with result")),
)
_REFUSAL = re.compile(r"refusal=(?!none\b)\w+")


@dataclass
class Step:
    name: str
    ok: bool
    said: str


@dataclass
class Outcome:
    sha: str
    previous: str
    result: str = "refused"            # refused, deployed, rolled_back, halted
    reason: str = ""
    steps: list[Step] = field(default_factory=list)
    rollback: list[Step] = field(default_factory=list)
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    install_lines: list[str] = field(default_factory=list)
    started_at: str = ""
    install_started_at: str = ""
    install_finished_at: str = ""
    finished_at: str = ""

    def said(self, name: str, ok: bool, words: str) -> bool:
        self.steps.append(Step(name, ok, words))
        if not ok and not self.reason:
            self.reason = words
        return ok


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256(data: bytes | None) -> str:
    return hashlib.sha256(data).hexdigest() if data is not None else ""


def _python(settings: ReleaseSettings) -> str:
    return str(settings.assistant / ".venv" / "bin" / "python")


def _dropins(host, settings: ReleaseSettings) -> dict[str, str]:
    folder = settings.unit_path.with_name(settings.unit_path.name + ".d")
    return {path.name: _sha256(host.read(path)) for path in host.files(folder, "*.conf")}


def _unit_env(unit: bytes) -> dict[str, str]:
    """HOME and PATH as the live unit has them, so `make install` renders the unit the same way."""
    found = {}
    for line in unit.decode("utf-8", "replace").splitlines():
        match = _UNIT_ENV.match(line.strip())
        if match:
            found[match[1]] = match[2]
    return found


def health(host, settings: ReleaseSettings, step: str) -> tuple[bool, dict[str, Any] | None]:
    """/health as the server's own reader gets it (scripts/healthcheck.py --json, the local key):
    well only when it exits 0 with the whole document, not the liveness anyone gets."""
    out = host.run(step, [_python(settings), "scripts/healthcheck.py", "--json"], cwd=settings.assistant,
                   timeout=HEALTH_TIMEOUT_S)
    try:
        doc = json.loads(out.out) if out.out.strip() else None
    except ValueError:
        doc = None
    if not isinstance(doc, dict) or doc.get("limited") is True or not checks(doc):
        return False, None
    return out.ok, doc


def checks(doc: dict[str, Any] | None) -> dict[str, bool]:
    raw = (doc or {}).get("checks")
    if isinstance(raw, dict):
        return {str(k): v.get("ok") is True for k, v in raw.items() if isinstance(v, dict)}
    if isinstance(raw, list):
        return {str(c.get("name")): c.get("ok") is True for c in raw if isinstance(c, dict) and c.get("name")}
    return {}


def _service(host) -> dict[str, str]:
    out = host.run("service_show", ["systemctl", "show", SERVICE, "-p", "ActiveState", "-p", "SubState",
                                    "-p", "NRestarts", "-p", "MainPID", "-p", "InvocationID"], timeout=30)
    pairs = (line.split("=", 1) for line in out.out.splitlines() if "=" in line)
    return {key.strip(): value.strip() for key, value in pairs} if out.ok else {}


def scan_journal(text: str) -> tuple[dict[str, int], int]:
    """How many lines of each failing kind, and how many refusal lines; never the lines themselves."""
    found: dict[str, int] = {}
    refusals = 0
    for line in text.splitlines():
        for name, pattern in JOURNAL_FAILURES:
            if pattern.search(line):
                found[name] = found.get(name, 0) + 1
        if _REFUSAL.search(line):
            refusals += 1
    return found, refusals


# ------------------------------------------------------------------ before anything changes


def precheck(host, settings: ReleaseSettings, facts: Facts, o: Outcome) -> bool:
    head = facts_module.git_checkout(host, settings, "precheck_head", "rev-parse", "--verify", "HEAD^{commit}")
    if not o.said("precheck_head", head.out.strip() == facts.live,
                  f"production still runs {facts.live[:8]}" if head.out.strip() == facts.live
                  else "production's SHA changed while the deploy was being worked out"):
        return False
    tree = facts_module.git_checkout(host, settings, "precheck_tree", "status", "--porcelain")
    if not o.said("precheck_tree", tree.ok and not tree.out.strip(),
                  "the checkout is clean" if tree.ok and not tree.out.strip()
                  else "the checkout has local changes, or git could not say"):
        return False
    places = (settings.checkout / ".git", settings.assistant, settings.unit_path.parent)
    shut = [str(place) for place in places if not host.writable(place)]
    if not o.said("writable", not shut, "the checkout and the unit's folder can be written" if not shut
                  else f"this service cannot write {', '.join(shut)} (its unit's ReadWritePaths)"):
        return False
    doctor = host.run("doctor", ["make", "doctor"], cwd=settings.assistant, timeout=120)
    if not o.said("doctor", doctor.ok, "make doctor: exit 0" if doctor.ok else f"make doctor: exit {doctor.code}"):
        return False
    tailnet = host.run("tailnet", [_python(settings), "-c",
                                   "import sys; from app import identity; ok, _ = identity.tailnet_self_check(); "
                                   "sys.exit(0 if ok else 1)"], cwd=settings.assistant, timeout=60)
    if not o.said("tailnet", tailnet.ok, "tailnet self-check: ok, this host can tell its own requests from a device's"
                  if tailnet.ok else "tailnet self-check failed: every request from his devices would be refused"):
        return False
    well, doc = health(host, settings, "health_before")
    o.before["health"] = checks(doc)
    o.before["build"] = str((doc or {}).get("build") or "")
    if not o.said("health_before", well, f"/health before: well, {len(o.before['health'])} checks, build "
                  f"{o.before['build'] or 'not said'}" if well
                  else "/health before the deploy is not well, so a deploy could not tell what it broke"):
        return False
    return capture(host, settings, facts, o)


def capture(host, settings: ReleaseSettings, facts: Facts, o: Outcome) -> bool:
    """The rollback target, both halves, saved before anything changes; then the target's objects."""
    unit = host.read(settings.unit_path)
    if not o.said("capture_unit", unit is not None, f"the live unit read ({len(unit or b'')} bytes, sha256 "
                  f"{_sha256(unit)[:8]})" if unit is not None else f"there is no unit at {settings.unit_path}"):
        return False
    saved = state.deploy_dir(settings.state_dir, facts.trunk) / "unit-before.service"
    try:
        host.write(saved, unit, 0o600)
        kept = host.read(saved) == unit
    except OSError:
        kept = False
    if not o.said("capture_saved", kept, f"the unit's copy is at {saved}" if kept
                  else "the unit could not be saved for a rollback"):
        return False
    o.before.update(unit_sha256=_sha256(unit), unit_saved=str(saved), unit_env=_unit_env(unit),
                    env_sha256=_sha256(host.read(settings.assistant / ".env")), dropins=_dropins(host, settings),
                    service=_service(host))
    # The LIVE build's installer (scripts/install_systemd.py --print), run with the HOME and PATH the live
    # unit was made with, must still render the live unit byte for byte: otherwise this service's
    # environment, or a credential provisioned since, would change the unit whatever the new build is, and
    # a person must look first. The new build's own unit is rendered after the checkout (render_new).
    same, rendered_ok = _renders_live_unit(host, settings, o, "render", unit)
    if not o.said("render", same, "the live build still renders the live unit, byte for byte" if same
                  else ("the unit could not be rendered" if not rendered_ok else
                        "the unit make install would write differs from the live one: a person must look first")):
        return False
    fetched = facts_module.git_checkout(host, settings, "fetch_into_checkout", "fetch", "--quiet", "--no-tags",
                                        str(facts_module.cache(settings)), f"refs/heads/{TRUNK}")
    present = fetched.ok and facts_module.git_checkout(host, settings, "target_present", "cat-file", "-e",
                                                       f"{facts.trunk}^{{commit}}").ok
    return o.said("fetch_into_checkout", present, f"{facts.trunk[:8]} is in production's checkout" if present
                  else f"{facts.trunk[:8]} could not be brought into production's checkout")


def _renders_live_unit(host, settings: ReleaseSettings, o: Outcome, step: str, unit: bytes) -> tuple[bool, bool]:
    """(the checkout's installer renders exactly `unit`, it rendered at all), with the live unit's HOME/PATH."""
    render = host.run(step, [_python(settings), "scripts/install_systemd.py", "--print"], cwd=settings.assistant,
                      env=o.before.get("unit_env") or {}, timeout=120)
    rendered = render.out[:-1] if render.out.endswith("\n") else render.out
    return render.ok and rendered.encode("utf-8") == unit, render.ok


def begin(host, settings: ReleaseSettings, facts: Facts, o: Outcome) -> bool:
    """The started marker, written and read back before the checkout: a deploy stopped from here on
    (killed, rebooted, timed out) is found by the next tick and halts the service, instead of its
    half-changed production being read as "up to date"."""
    written = state.start(host, settings.state_dir, facts.trunk, previous=facts.live, at=o.started_at)
    return o.said("started", written, "the started marker is written: an interruption from here on halts the service"
                  if written else "the started marker could not be written, so an interruption could not be noticed")


# ------------------------------------------------------------------ the change, and after


def change(host, settings: ReleaseSettings, facts: Facts, o: Outcome,
           progress: Callable[[str], None] = lambda _stage: None) -> str | None:
    """Make the change and verify it. None when it held; otherwise which rollback it needs."""
    moved = facts_module.git_checkout(host, settings, "checkout", "checkout", "--quiet", "--detach", facts.trunk)
    head = facts_module.git_checkout(host, settings, "checkout_head", "rev-parse", "--verify", "HEAD^{commit}")
    if not o.said("checkout", moved.ok and head.out.strip() == facts.trunk,
                  f"checked out {facts.trunk[:8]}" if moved.ok else f"git checkout failed (exit {moved.code})"):
        return "code"
    gap = host.run("gap_check", [_python(settings), "scripts/gap_clean_check.py"], cwd=settings.assistant,
                   timeout=300)
    if not o.said("gap_check", gap.ok, "gap_clean_check on the new build: nothing lost" if gap.ok
                  else f"gap_clean_check on the new build: exit {gap.code}, something would be lost"):
        return "code"
    # The unit the NEW build's installer would write, before it writes it (as the b33ccbc2 deploy checked
    # by hand): code outside the guarded paths feeds it (config/settings.py's host and port, the secrets
    # folder, the known keys behind the credentials block), so any difference is a person's to look at.
    saved = host.read(Path(o.before.get("unit_saved") or "/nonexistent"))
    same, rendered_ok = _renders_live_unit(host, settings, o, "render_new", saved) if saved else (False, False)
    if not o.said("render_new", same, "the new build's unit, rendered before make install, is the live unit "
                  "byte for byte" if same else ("the new build's unit could not be rendered" if not rendered_ok
                  else "the new build would install a different unit from the live one: a person must look first")):
        return "code"
    o.install_started_at = _iso(host.now())
    installed = host.run("install", ["make", "install"], cwd=settings.assistant, env=o.before.get("unit_env") or {},
                         timeout=INSTALL_TIMEOUT_S)
    o.install_lines = [line.rstrip()[:200] for line in installed.out.splitlines()
                       if _INSTALL_LINE.match(line)][:MAX_INSTALL_LINES]
    if not o.said("install", installed.ok, "make install: exit 0" if installed.ok
                  else f"make install: exit {installed.code} (it rolls its own unit back)"):
        return "full"
    progress("health")
    host.sleep(settings.settle_s)
    return verify(host, settings, o)


def verify(host, settings: ReleaseSettings, o: Outcome) -> str | None:
    well, doc = health(host, settings, "health_after")
    o.install_finished_at = _iso(host.now())
    after = checks(doc)
    o.after.update(health=after, build=str((doc or {}).get("build") or ""))
    worse = sorted(name for name, ok in o.before.get("health", {}).items() if ok and not after.get(name))
    if not o.said("health_after", well and not worse, f"/health after: well, all {len(after)} checks as before"
                  if well and not worse else f"/health after is not well{': ' + ', '.join(worse) + ' went down' if worse else ''}"):
        return "full"
    service = _service(host)
    o.after["service"] = service
    steady = (service.get("ActiveState") == "active" and service.get("SubState") == "running"
              and service.get("NRestarts") == "0")
    if not o.said("service_after", steady, f"{SERVICE} active (running), no restart" if steady
                  else f"{SERVICE} is not steady: {service.get('ActiveState') or '?'}/{service.get('SubState') or '?'}, "
                       f"{service.get('NRestarts') or '?'} restart(s)"):
        return "full"
    env_same = _sha256(host.read(settings.assistant / ".env")) == o.before.get("env_sha256")
    dropins_same = _dropins(host, settings) == o.before.get("dropins")
    if not o.said("switches_after", env_same and dropins_same, ".env and the drop-ins are as they were"
                  if env_same and dropins_same else f"{'.env' if not env_same else 'a drop-in'} changed during the deploy"):
        return "full"
    journal = host.run("journal", journal_argv(o, service), timeout=60)
    failures, refusals = scan_journal(journal.out)
    o.after.update(journal_lines=len(journal.out.splitlines()), journal_failures=failures, journal_refusals=refusals)
    clean = journal.ok and not failures
    if not o.said("journal", clean, f"journal since the restart: {len(journal.out.splitlines())} lines, no traceback, "
                  "error, withheld or not-confirmed line" if clean else
                  ("the journal could not be read" if not journal.ok
                   else "journal since the restart has " + ", ".join(f"{n} × {k}" for k, n in failures.items()))):
        return "full"
    unit = host.read(settings.unit_path)
    same = unit is not None and _sha256(unit) == o.before.get("unit_sha256")
    o.after.update(unit_sha256=_sha256(unit), unit_identical=same)
    if not o.said("unit_after", same, "byte-identical to the saved copy" if same else
                  "the unit make install wrote differs from the saved copy (sha256 "
                  f"{_sha256(unit)[:8] or 'none'}): a person must look first"):
        return "full"
    return None


_INVOCATION = re.compile(r"^[0-9a-f]{32}$")


def journal_argv(o: Outcome, service: dict[str, str]) -> list[str]:
    """The journal of the process `make install` started, not the old one's shutdown: entries since the
    install began AND from the service's new invocation (its processes' lines, and systemd's own lines
    about it). When the new invocation cannot be told from the old one, every line since the install
    began is read, as before: stricter, never looser."""
    since = int(datetime.fromisoformat(o.install_started_at.replace("Z", "+00:00")).timestamp())
    argv = ["journalctl", "--since", f"@{since}", "--no-pager", "-o", "cat"]
    new = service.get("InvocationID", "")
    old = (o.before.get("service") or {}).get("InvocationID", "")
    if _INVOCATION.fullmatch(new) and new != old:
        return argv + [f"_SYSTEMD_INVOCATION_ID={new}", "+", f"INVOCATION_ID={new}"]
    return argv + ["-u", SERVICE]


def roll_back(host, settings: ReleaseSettings, facts: Facts, o: Outcome, kind: str) -> None:
    """Back to the SHA (and, after `make install`, the unit) production ran before; halted if it fails."""
    def step(name: str, ok: bool, words: str) -> bool:
        o.rollback.append(Step(name, ok, words))
        return ok

    moved = facts_module.git_checkout(host, settings, "rollback_checkout", "checkout", "--quiet", "--detach",
                                      facts.live)
    head = facts_module.git_checkout(host, settings, "rollback_head", "rev-parse", "--verify", "HEAD^{commit}")
    fine = step("rollback_checkout", moved.ok and head.out.strip() == facts.live,
                f"checked out {facts.live[:8]} again" if moved.ok and head.out.strip() == facts.live
                else f"could not check out {facts.live[:8]} again")
    if kind == "full":
        saved = host.read(Path(o.before.get("unit_saved") or "/nonexistent"))
        try:
            if saved is None:
                raise OSError("the saved unit is gone")
            host.write(settings.unit_path, saved, 0o644)
            put = True
        except OSError:
            put = False
        fine &= step("rollback_unit", put, "the saved unit put back" if put else "the saved unit could not be put back")
        reload = host.run("rollback_reload", ["systemctl", "daemon-reload"], timeout=60)
        fine &= step("rollback_reload", reload.ok, "systemd reloaded" if reload.ok else "systemctl daemon-reload failed")
        again = host.run("rollback_install", ["make", "install"], cwd=settings.assistant,
                         env=o.before.get("unit_env") or {}, timeout=INSTALL_TIMEOUT_S)
        fine &= step("rollback_install", again.ok, f"make install on {facts.live[:8]}: exit 0" if again.ok
                     else f"make install on {facts.live[:8]}: exit {again.code}")
    well, doc = health(host, settings, "rollback_health")
    fine &= step("rollback_health", well, f"/health after the rollback: well, build {(doc or {}).get('build') or '?'}"
                 if well else "/health after the rollback is not well")
    o.result = "rolled_back" if fine else "halted"


def run(host, settings: ReleaseSettings, facts: Facts,
        progress: Callable[[str], None] = lambda _stage: None) -> Outcome:
    """One deploy of facts.trunk over facts.live: the whole procedure, and its outcome. `progress` is
    told each stage as it begins: checks, then installing once the started marker is down, then
    health once make install has finished."""
    o = Outcome(sha=facts.trunk, previous=facts.live, started_at=_iso(host.now()))
    progress("checks")
    if precheck(host, settings, facts, o) and begin(host, settings, facts, o):
        progress("installing")
        rollback = change(host, settings, facts, o, progress)
        if rollback is None:
            o.result = "deployed"
        else:
            roll_back(host, settings, facts, o, rollback)
    o.finished_at = _iso(host.now())
    return o
