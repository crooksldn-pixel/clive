"""The release service (app/release/), on a fake server: every command a tick would run is answered by
a small world here, so each condition, each failure point and each rollback can be driven and the
exact commands read back.

What these hold it to: green and authorised is a plan, and a deploy by DEPLOY_LINUX.md's procedure;
each missing condition is no deploy, with its reason in words and no command that changes anything;
a failure at each point after a change rolls production back, and a rollback that fails halts the
service; a dry run changes nothing; only clive/trunk's head is deployed; one deploy at a time; the
token never appears in an argument, a line printed, the status or the record.
"""

from __future__ import annotations

import json
import os
import re
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.connections import passkeys
from app.orchestrator import github_acceptance
from app.orchestrator.github_acceptance import GateResult, GateState, RunFact
from app.release import authority, decide, github, service, state, status
from app.release import settings as settings_module
from app.release.facts import Facts
from app.release.host import Result, SystemHost
from app.release.settings import ReleaseSettings
from tests import fake_credentials
from tests.fake_passkey import Authenticator, b64url

TRUNK = "1" * 32 + "a1b2c3d4"
LIVE = "2" * 32 + "e5f6a7b8"
OTHER = "3" * 40
TOKEN = fake_credentials.github_fine_grained_token("release-service")   # assembled at runtime (rule B)
MUTATING = {"checkout", "gap_check", "install", "rollback_checkout", "rollback_reload", "rollback_install",
            "fetch_into_checkout", "record_push", "record_commit", "record_blob"}
DEPLOY_STEPS = ["cache_init", "fetch_trunk", "trunk_head", "live_head", "live_status", "live_known", "ancestry",
                "diff", "commits", "trunk_title", "live_title",
                "precheck_head", "precheck_tree", "doctor", "tailnet", "health_before", "service_show", "render",
                "fetch_into_checkout", "target_present", "checkout", "checkout_head", "gap_check", "render_new", "install",
                "health_after", "service_show", "journal",
                "record_blob", "record_listed", "record_tree_read", "record_tree_add", "record_tree",
                "record_commit", "record_push"]
UNIT = b"[Service]\nEnvironment=HOME=/root\nEnvironment=PATH=/root/.local/bin:/usr/bin:/bin\nExecStart=x\n"
HEALTHY = {"status": "ok", "build": "aaaa11112222",
           "checks": {"claude": {"ok": True}, "shopify": {"ok": True}, "proxy_identity": {"ok": True}}}


class World:
    """The server and GitHub as the fake answers them."""

    def __init__(self, settings: ReleaseSettings) -> None:
        self.settings = settings
        self.head = LIVE
        self.trunk = TRUNK
        self.dirty = ""
        self.ancestor = True
        self.live_known = True
        self.changed = ["crooks-assistant/app/objectives/store.py", "crooks-assistant/tests/test_x.py"]
        self.commits = ["Days left count London's day (PR #99)"]
        self.titles = {TRUNK: "Days left count London's day (PR #99)", LIVE: "Seven fixes from the review (PR #95)"}
        self.review: dict | None = None
        self.review_base_behind = True
        self.health = {"health_before": HEALTHY, "health_after": HEALTHY, "rollback_health": HEALTHY}
        self.service = "ActiveState=active\nSubState=running\nNRestarts=0\nMainPID=4242\n"
        self.journal = "12:00:01 INFO crooks.runtime ready\n12:00:02 INFO crooks.identity whoami: id=ab12cd34 " \
                       "through=this_host owner=false refusal=not_authorised_local\n"
        self.fail: set[str] = set()
        self.readonly = False
        self.echo_token = False
        self.on_step: dict[str, callable] = {}
        self.rendered: str | None = None
        self.rendered_new: str | None = None         # the new build's unit, after the checkout
        self.journal_old = ""                        # the old process's lines, from before the restart
        self.same_invocation = False                 # make install did not start a new invocation
        self.record_exists = False                   # a record branch is already on GitHub

    def answer(self, step: str, argv: list[str], env: dict, host) -> Result:
        if step in self.on_step:
            self.on_step[step]()
        if step in self.fail:
            return Result(1, "", f"{step} failed" + (f" {TOKEN}" if self.echo_token else ""))
        s = self.settings
        if step == "cache_init":
            host.write(s.state_dir / "repo.git" / "HEAD", b"ref: refs/heads/main\n", 0o644)
            return Result(0)
        out = {
            "trunk_head": self.trunk, "live_head": self.head, "precheck_head": self.head,
            "checkout_head": self.head, "rollback_head": self.head,
            "live_status": self.dirty, "precheck_tree": self.dirty,
            "diff": "\n".join(self.changed), "commits": "\n".join(self.commits),
            "trunk_title": self.titles.get(argv[-1], ""), "live_title": self.titles.get(argv[-1], ""),
            "review_listed": f"{OTHER}\trefs/heads/{github.review_branch(self.trunk)}\n" if self.review else "",
            "review_read": json.dumps(self.review) if self.review else "",
            "service_show": self.service + self.invocation(),
            "journal": self.journal if any(a.startswith("_SYSTEMD_INVOCATION_ID=") for a in argv)
            else self.journal_old + self.journal,
            "install": "  ok     unit → /etc/systemd/system/crooks-assistant.service\n  health all good · Claude\n"
                       "random chatter that is not kept\n",
            "record_blob": "b" * 40, "record_tree": "c" * 40, "record_commit": "d" * 40,
            "record_listed": f"{'e' * 40}\trefs/heads/{github.record_branch(self.trunk)}\n" if self.record_exists else "",
            "record_head": "e" * 40,
            "render": (self.rendered if self.rendered is not None else UNIT.decode()) + "\n",
            "render_new": (self.rendered_new if self.rendered_new is not None else UNIT.decode()) + "\n",
        }.get(step, "")
        if step in self.health:
            out = json.dumps(self.health[step]) if self.health[step] is not None else ""
        if step == "live_known" and not self.live_known:
            return Result(1)
        if step == "ancestry":
            return Result(0 if self.ancestor else 1)
        if step == "review_base":
            return Result(0 if self.review_base_behind else 1)
        if step == "review_read" and not self.review:
            return Result(128)
        if step in ("checkout", "rollback_checkout"):
            self.head = argv[-1]
        if self.echo_token and step == "install":
            out += f"  ok     remote said {TOKEN}\n"
        return Result(0, out, f"remote said {TOKEN}" if self.echo_token else "")

    def invocation(self) -> str:
        """systemd's InvocationID: a new one once make install has restarted the service on the new build."""
        new = self.head != LIVE and not self.same_invocation
        return f"InvocationID={('f' if new else '0') * 32}\n"


class FakeHost(SystemHost):
    def __init__(self, world: World) -> None:
        self.world = world
        self.calls: list[tuple[str, list[str], dict, str | None]] = []
        self.timeouts: list[float] = []
        self.slept: list[float] = []
        self.clock = datetime(2026, 10, 8, 1, 0, 0, tzinfo=UTC)

    def run(self, step, argv, *, cwd=None, env=None, input=None, timeout=600.0):
        self.calls.append((step, list(argv), dict(env or {}), input))
        self.timeouts.append(timeout)
        return self.world.answer(step, list(argv), dict(env or {}), self)

    def writable(self, path):
        return not self.world.readonly

    def stat(self, path):
        found = super().stat(path)
        if found is None:
            return None
        uid, mode = found
        return (0 if str(path).startswith(str(self.world.settings.waivers_dir)) else uid), mode

    def sleep(self, seconds):
        self.slept.append(seconds)

    def now(self):
        self.clock += timedelta(seconds=1)
        return self.clock

    def name(self):
        return "crooks-os-prod-1"

    @property
    def steps(self) -> list[str]:
        return [call[0] for call in self.calls]


class Gate:
    def __init__(self, state_: GateState = GateState.GREEN) -> None:
        self.state = state_
        self.asked: list[str] = []

    def check(self, repository: str, sha: str) -> GateResult:
        self.asked.append(sha)
        detail = {GateState.GREEN: "acceptance run(s) 77 completed with success",
                  GateState.PENDING: "1 of 1 acceptance run(s) not completed: run 77 in_progress",
                  GateState.RED: "1 of 1 acceptance run(s) not successful: run 77 failure",
                  GateState.MISSING: "no GitHub Actions acceptance run exists for this commit"}[self.state]
        runs = () if self.state is GateState.MISSING else (RunFact(77, "completed", "success"),)
        return GateResult(sha, self.state, detail, runs)


@pytest.fixture
def server(tmp_path):
    settings = ReleaseSettings(enabled=True, rule="owner_waiver", dry_run=False, checkout=tmp_path / "opt",
                               state_dir=tmp_path / "state", unit_path=tmp_path / "etc" / "crooks-assistant.service",
                               waivers_dir=tmp_path / "waivers", passkey_waivers_dir=tmp_path / "pkw",
                               passkeys_file=tmp_path / "secrets" / "passkeys.json", settle_s=0)
    (tmp_path / "opt" / "crooks-assistant").mkdir(parents=True)
    (tmp_path / "opt" / "crooks-assistant" / ".env").write_text("CROOKS_WRITES_ENABLED=true\n")
    (tmp_path / "etc" / "crooks-assistant.service.d").mkdir(parents=True)
    (tmp_path / "etc" / "crooks-assistant.service.d" / "10-state.conf").write_text("[Service]\n")
    settings.unit_path.write_bytes(UNIT)
    world = World(settings)
    host = FakeHost(world)
    return settings, world, host


def _waive(settings: ReleaseSettings, sha: str = TRUNK, **extra) -> None:
    """George's host waiver for `sha`, in the file the service looks in for the trunk's head."""
    settings.waivers_dir.mkdir(mode=0o700, exist_ok=True)
    record_ = {"schema": authority.WAIVER_SCHEMA, "sha": sha, "repository": settings.repository,
               "waives": "exact_sha_review", "given_by": "George", "given_at": "2026-10-08T00:30:00+00:00",
               "words": "waive", "source": "host", "passkey": None, **extra}
    path = settings.waivers_dir / f"{TRUNK}.json"
    path.write_text(json.dumps(record_))
    os.chmod(path, 0o600)


def _tick(settings, host, gate=None, token="", pinned=True):
    printed: list[str] = []
    code = service.tick(host, settings, token=github.Token(token), gate=gate or Gate(), pinned=pinned,
                        out=printed.append)
    return code, printed


def _status(settings) -> dict:
    return json.loads((settings.state_dir / "status.json").read_text())


def _changed_anything(host) -> list[str]:
    return [step for step in host.steps if step in MUTATING]


# ------------------------------------------------------------------ off, and no rule


def test_switched_off_it_runs_nothing_and_says_so(server):
    settings, _world, host = server
    settings.enabled = False
    _waive(settings)
    code, printed = _tick(settings, host)
    assert code == 0 and host.calls == []
    assert _status(settings)["state"] == "off" and printed == [service.LINES["off"]]


def test_with_no_rule_named_it_deploys_nothing(server):
    settings, _world, host = server
    settings.rule = "off"
    _waive(settings)
    code, _ = _tick(settings, host)
    assert code == 0 and host.calls == []
    assert (_status(settings)["state"], _status(settings)["line"]) == ("no_rule", service.LINES["no_rule"])


# ------------------------------------------------------------------ green and authorised


def test_green_and_authorised_is_a_plan_and_the_plan_changes_nothing(server):
    settings, _world, host = server
    _waive(settings)
    printed: list[str] = []
    code = service.plan(host, settings, token=github.Token(""), gate=Gate(), pinned=True, out=printed.append)
    assert code == 0
    text = "\n".join(printed)
    assert "WOULD DEPLOY" in text and "git checkout --detach a1b2c3d4" in text.replace(TRUNK[:8], "a1b2c3d4")
    assert "claude/deploy-11111111-record" in text
    assert _changed_anything(host) == []
    assert not (settings.state_dir / "status.json").exists() and not (settings.state_dir / "deploy.lock").exists()
    assert not (settings.state_dir / "deploys").exists()


def test_green_and_authorised_deploys_by_the_procedure_and_records_it(server):
    settings, world, host = server
    _waive(settings)
    code, printed = _tick(settings, host, token=TOKEN)
    assert code == 0, printed
    assert host.steps == DEPLOY_STEPS
    assert world.head == TRUNK
    install = next(call for call in host.calls if call[0] == "install")
    assert install[1] == ["make", "install"]
    assert install[2] == {"HOME": "/root", "PATH": "/root/.local/bin:/usr/bin:/bin"}, "rendered as the live unit was"
    push = next(call for call in host.calls if call[0] == "record_push")
    assert push[1][-1] == "d" * 40 + ":refs/heads/claude/deploy-11111111-record"
    now = _status(settings)
    assert now["state"] == "deployed" and now["record_branch"] == "claude/deploy-11111111-record"
    assert now["line"] == "Deployed “Days left count London's day (PR #99)”. Open /whoami on your phone to keep it."
    kept = (settings.state_dir / "deploys" / "11111111" / "deploy-11111111.md").read_text()
    for heading in ("# Deploy record — `11111111` on `crooks-os-prod-1`", "## Rollback target",
                    "## What was checked before anything changed", "## The install",
                    "## Verification after the install", "## Outstanding", "## What this build changes",
                    "## The authority for this deploy"):
        assert heading in kept
    assert "**Deployed:** 2026-10-08, install" in kept and "| Switches | untouched" in kept
    assert "waived by George (given on the server)" in kept and "His words" not in kept
    assert not (settings.state_dir / "deploys" / "11111111" / "started").exists(), "the outcome is on disk"
    assert "random chatter" not in kept, "only the installer's own status lines are kept"
    assert "ab12cd34" not in kept and "crooks.runtime ready" not in kept, "no journal line reaches the record"
    blob = next(call for call in host.calls if call[0] == "record_blob")
    assert blob[3] == kept
    saved = settings.state_dir / "deploys" / "11111111" / "unit-before.service"
    assert saved.read_bytes() == UNIT and stat.S_IMODE(saved.stat().st_mode) == 0o600


def test_the_record_is_named_so_map_reads_it_as_production(server):
    settings, _world, host = server
    _waive(settings)
    _tick(settings, host)
    import re

    name = "deploy-11111111.md"
    assert re.fullmatch(r"deploy-([0-9a-f]{8})\.md", name)
    text = (settings.state_dir / "deploys" / "11111111" / name).read_text()
    assert re.search(r"(\d{4})-(\d{2})-(\d{2})[^\n]*?\b(\d{2}):(\d{2})", text)
    assert re.search(r"(?i)switch[^\n]{0,60}untouched", text)


# ------------------------------------------------------------------ each missing condition


def _set(world, settings, what):
    if what == "acceptance pending":
        return Gate(GateState.PENDING), "GitHub acceptance on this SHA is pending"
    if what == "acceptance red":
        return Gate(GateState.RED), "GitHub acceptance on this SHA is red"
    if what == "acceptance missing":
        return Gate(GateState.MISSING), "GitHub acceptance on this SHA is missing"
    if what == "no waiver":
        settings.waivers_dir.joinpath(f"{TRUNK}.json").unlink()
        return None, "George has not waived the review for this SHA"
    if what == "waiver for another commit":
        _waive(settings, sha=OTHER)
        return None, "the waiver is for another commit"
    if what == "waiver for another repository":
        _waive(settings, repository="someone/else")
        return None, "the waiver is for another repository"
    if what == "dirty checkout":
        world.dirty = " M crooks-assistant/app/main.py\n"
        return None, "production's checkout has local changes"
    if what == "not forward":
        world.ancestor = False
        return None, "not behind the trunk's head on the trunk"
    if what == "production not on the trunk":
        world.live_known = False
        return None, "not behind the trunk's head on the trunk"
    if what == "the change touches the installer":
        world.changed.append("crooks-assistant/deploy/systemd/crooks-assistant.service")
        return None, "the change touches how CLIVE is installed (crooks-assistant/deploy/systemd"
    if what == "dependencies changed":
        world.changed.append("crooks-assistant/pyproject.toml")
        return None, "crooks-assistant/pyproject.toml"
    if what == "the change touches the acceptance workflow":
        world.changed.append(".github/workflows/acceptance.yml")
        return None, "the change touches how CLIVE is checked (.github/workflows/acceptance.yml)"
    if what == "the trunk cannot be fetched":
        world.fail.add("fetch_trunk")
        return None, "clive/trunk could not be fetched from GitHub"
    if what == "not pinned":
        return "unpinned", "it runs only from its own pinned copy"
    raise AssertionError(what)


@pytest.mark.parametrize("what", [
    "acceptance pending", "acceptance red", "acceptance missing", "no waiver", "waiver for another commit",
    "waiver for another repository", "dirty checkout", "not forward", "production not on the trunk",
    "the change touches the installer", "dependencies changed", "the trunk cannot be fetched", "not pinned",
    "the change touches the acceptance workflow",
])
def test_each_missing_condition_is_no_deploy_with_its_reason(server, what):
    settings, world, host = server
    _waive(settings)
    gate, reason = _set(world, settings, what)
    pinned = gate != "unpinned"
    code, printed = _tick(settings, host, gate=gate if isinstance(gate, Gate) else None, pinned=pinned)
    assert _changed_anything(host) == [], f"{what}: nothing may change"
    now = _status(settings)
    assert now["state"] == "waiting", now
    assert reason in "\n".join(printed), (what, printed)
    assert now["line"].startswith("Not deploying ")
    assert world.head == LIVE


def test_exact_sha_review_takes_a_ship_record_for_exactly_this_sha_and_nothing_less(server):
    settings, world, host = server
    settings.rule = "exact_sha_review"
    _waive(settings)                       # a waiver is not what this rule asks for
    code, printed = _tick(settings, host)
    assert _changed_anything(host) == [] and "no review record for this SHA (no branch claude/review-11111111-record)" \
        in printed[0]
    good = {"schema": authority.REVIEW_SCHEMA, "sha": TRUNK, "base_sha": LIVE, "verdict": "SHIP", "blocking": [],
            "reviewer": "Opus 5.5 review session", "reviewed_at": "2026-10-08T00:10:00Z",
            "rule": "regression-only (OWNER_DECISIONS_2026-09-30)", "summary": "No regression; nothing leaks."}
    for change, said in (({"verdict": "CHANGES_REQUIRED"}, "verdict is CHANGES_REQUIRED, not SHIP"),
                         ({"blocking": ["F-01"]}, "the review lists blocking findings"),
                         ({"sha": OTHER}, "the review record is about another commit"),
                         ({"reviewer": ""}, "does not say who reviewed it")):
        host.calls.clear()
        world.review = {**good, **change}
        _tick(settings, host)
        assert _changed_anything(host) == [] and said in _status(settings)["line"], change
    host.calls.clear()
    world.review, world.review_base_behind = {**good, "base_sha": OTHER}, False
    _tick(settings, host)
    assert _changed_anything(host) == [] and "did not cover this change" in _status(settings)["line"]
    host.calls.clear()
    world.review, world.review_base_behind = good, True
    code, printed = _tick(settings, host)
    assert code == 0 and _status(settings)["state"] == "deployed"
    kept = (settings.state_dir / "deploys" / "11111111" / "deploy-11111111.md").read_text()
    assert "SHIP by Opus 5.5 review session" in kept and "measured against `22222222`" in kept


def test_a_host_waiver_others_could_write_is_not_believed(server):
    settings, _world, host = server
    _waive(settings)
    os.chmod(settings.waivers_dir, 0o777)
    _tick(settings, host)
    assert _changed_anything(host) == [] and "not believed" in _status(settings)["line"]


# ------------------------------------------------------------------ the passkey waiver


def _register(tmp_path: Path) -> Authenticator:
    passkeys.configure(state_dir=tmp_path / "secrets")
    passkeys.reset()
    device = Authenticator()
    options = passkeys.begin_registration(login="owner@example.com", origin=device.origin, rp_id=device.rp_id,
                                          approved=False)
    passkeys.finish_registration(device.create(options), login="owner@example.com", origin=device.origin,
                                 label="his phone")
    return device


def _passkey_waiver(settings, device: Authenticator, *, sha: str = TRUNK, signed_for: str = TRUNK) -> None:
    nonce = os.urandom(16)
    challenge = b64url(authority.waiver_challenge(settings.repository, signed_for, nonce))
    got = device.get({"challenge": challenge}, count=device.counter + 1)
    settings.passkey_waivers_dir.mkdir(exist_ok=True)
    (settings.passkey_waivers_dir / f"{sha}.json").write_text(json.dumps({
        "schema": authority.WAIVER_SCHEMA, "sha": sha, "repository": settings.repository,
        "waives": "exact_sha_review", "given_by": "George", "given_at": "2026-10-08T00:40:00+00:00",
        "words": "deploy the latest", "source": "passkey",
        "passkey": {"credential_id": got["rawId"], "nonce": b64url(nonce),
                    "client_data_json": got["response"]["clientDataJSON"],
                    "authenticator_data": got["response"]["authenticatorData"],
                    "signature": got["response"]["signature"]}}))


def test_a_passkey_waiver_for_exactly_this_sha_deploys(server, tmp_path):
    settings, _world, host = server
    device = _register(tmp_path)
    _passkey_waiver(settings, device)
    code, printed = _tick(settings, host)
    assert code == 0 and _status(settings)["state"] == "deployed", printed
    kept = (settings.state_dir / "deploys" / "11111111" / "deploy-11111111.md").read_text()
    assert "waived by George (with his passkey)" in kept
    assert "deploy the latest" not in kept, "his words stay in the waiver"


@pytest.mark.parametrize("how,said", [
    ("signed for another SHA", "other than deploying this exact SHA"),
    ("another passkey", "not registered here"),
    ("not verified", "did not check it was you"),
    ("another site", "made for another site"),
])
def test_a_passkey_waiver_that_does_not_hold_deploys_nothing(server, tmp_path, how, said):
    settings, _world, host = server
    device = _register(tmp_path)
    if how == "signed for another SHA":
        _passkey_waiver(settings, device, signed_for=OTHER)
    elif how == "another passkey":
        _passkey_waiver(settings, Authenticator())
    elif how == "not verified":
        device.uv = False
        _passkey_waiver(settings, device)
    else:
        device.rp_id = "evil.example"
        _passkey_waiver(settings, device)
    _tick(settings, host)
    assert _changed_anything(host) == [] and said in _status(settings)["line"], _status(settings)


# ------------------------------------------------------------------ failures before the change


@pytest.mark.parametrize("step,said", [
    ("doctor", "make doctor: exit 1"),
    ("tailnet", "tailnet self-check failed"),
    ("health_before", "/health before the deploy is not well"),
    ("fetch_into_checkout", "could not be brought into production's checkout"),
    ("render", "the unit could not be rendered"),
])
def test_a_failed_check_before_the_change_refuses_with_nothing_changed(server, step, said):
    settings, world, host = server
    _waive(settings)
    world.fail.add(step)
    code, _ = _tick(settings, host)
    assert code == 1 and world.head == LIVE
    assert not {"checkout", "install", "rollback_checkout", "record_push"} & set(host.steps)
    assert said in _status(settings)["line"] and _status(settings)["state"] == "waiting"
    assert not (settings.state_dir / "failed").exists(), "a refusal is tried again next tick"


def test_a_unit_make_install_would_change_refuses_before_anything_changes(server):
    settings, world, host = server
    _waive(settings)
    world.rendered = UNIT.decode() + "LoadCredentialEncrypted=new_key:/etc/crooks-os/credentials/new_key.cred\n"
    code, _ = _tick(settings, host)
    assert code == 1 and world.head == LIVE and "checkout" not in host.steps
    assert "differs from the live one: a person must look first" in _status(settings)["line"]
    render = next(call for call in host.calls if call[0] == "render")
    assert render[1][1:] == ["scripts/install_systemd.py", "--print"] and render[2]["HOME"] == "/root"


def test_a_unit_folder_it_cannot_write_refuses_before_anything_changes(server):
    settings, world, host = server
    _waive(settings)
    world.readonly = True
    _tick(settings, host)
    assert world.head == LIVE and "cannot write" in _status(settings)["line"]


# ------------------------------------------------------------------ rollback at each failure point


def _not_well(world):
    world.health["health_after"] = None


def _worse(world):
    world.health["health_after"] = {**HEALTHY, "checks": {**HEALTHY["checks"], "shopify": {"ok": False}}}


def _restarting(world):
    world.service = "ActiveState=active\nSubState=running\nNRestarts=2\nMainPID=99\n"


def _env_moved(world):
    world.on_step["health_after"] = lambda: (world.settings.assistant / ".env").write_text("CHANGED=1\n")


def _journal_errors(world):
    world.journal += "12:00:03 ERROR crooks.runtime something broke\nTraceback (most recent call last):\n"


CODE_ONLY = ["rollback_checkout", "rollback_head", "rollback_health"]
FULL = ["rollback_checkout", "rollback_head", "rollback_reload", "rollback_install", "rollback_health"]


@pytest.mark.parametrize("point,arrange,expected,said", [
    ("checkout", lambda w: w.fail.add("checkout"), CODE_ONLY, "git checkout failed"),
    ("gap_check", lambda w: w.fail.add("gap_check"), CODE_ONLY, "something would be lost"),
    ("install", lambda w: w.fail.add("install"), FULL, "make install: exit 1"),
    ("health not well", _not_well, FULL, "/health after is not well"),
    ("health worse", _worse, FULL, "shopify went down"),
    ("service restarting", _restarting, FULL, "2 restart(s)"),
    (".env changed", _env_moved, FULL, ".env changed during the deploy"),
    ("journal errors", _journal_errors, FULL, "1 × a traceback"),
])
def test_a_failure_at_each_point_after_the_change_rolls_back(server, point, arrange, expected, said):
    settings, world, host = server
    _waive(settings)
    arrange(world)
    code, printed = _tick(settings, host, token=TOKEN)
    assert code == 1
    rollback = [step for step in host.steps if step.startswith("rollback_")]
    assert rollback == expected, point
    assert world.head == LIVE, "production is back on the SHA it ran"
    now = _status(settings)
    assert now["state"] == "rolled_back" and said in now["line"], now
    assert "Production is back on “Seven fixes from the review (PR #95)”" in now["line"]
    if "rollback_reload" in expected:
        assert settings.unit_path.read_bytes() == UNIT, "the saved unit was put back"
    kept = (settings.state_dir / "deploys" / "11111111" / "deploy-11111111-rolled-back.md").read_text()
    assert "## The rollback" in kept and "**rolled back**" in kept
    push = next(call for call in host.calls if call[0] == "record_push")
    assert push[1][-1].endswith(":refs/heads/claude/deploy-11111111-record")
    assert json.loads((settings.state_dir / "failed" / f"{TRUNK}.json").read_text())["reason"]
    # The same SHA is not tried again on its own.
    host.calls.clear()
    world.fail.clear()
    world.health["health_after"] = HEALTHY
    world.service = "ActiveState=active\nSubState=running\nNRestarts=0\nMainPID=4242\n"
    world.on_step.clear()
    _tick(settings, host)
    assert _changed_anything(host) == [] and "is not tried again on its own" in _status(settings)["line"]


def test_a_rollback_that_fails_halts_the_service_until_a_person_looks(server):
    settings, world, host = server
    _waive(settings)
    world.fail |= {"install", "rollback_install"}
    code, _ = _tick(settings, host)
    assert code == 1 and _status(settings)["state"] == "halted"
    assert json.loads((settings.state_dir / "HALT").read_text())["sha"] == TRUNK
    assert (settings.state_dir / "deploys" / "11111111" / "deploy-11111111-halted.md").exists()
    host.calls.clear()
    world.fail.clear()
    code, printed = _tick(settings, host)
    assert host.calls == [] and code == 1 and "stopped until a person looks" in printed[0]


# ------------------------------------------------------------------ dry run, the trunk only, the lock


def test_a_dry_run_tick_says_what_it_would_do_and_changes_nothing(server):
    settings, world, host = server
    settings.dry_run = True
    _waive(settings)
    code, printed = _tick(settings, host, token=TOKEN)
    assert code == 0 and _changed_anything(host) == [] and world.head == LIVE
    now = _status(settings)
    assert now["state"] == "would_deploy" and now["mode"] == "dry_run"
    assert now["line"] == "Dry run: it would deploy “Days left count London's day (PR #99)” now. Nothing was changed."
    assert not (settings.state_dir / "deploys").exists()


def test_only_the_trunks_head_is_deployed(server):
    settings, _world, host = server
    _waive(settings)
    printed: list[str] = []
    code = service.plan(host, settings, token=github.Token(""), requested=OTHER, gate=Gate(), pinned=True,
                        out=printed.append)
    assert code == 1 and any("333333333333 is not clive/trunk's head (11111111)" in line for line in printed)
    with pytest.raises(ValueError):
        github.record_refspec("d" * 40, "clive/trunk")
    with pytest.raises(ValueError):
        github.record_refspec("d" * 40, "clive/control/worker-01-status")
    with pytest.raises(ValueError):
        github.record_refspec("main", "claude/deploy-11111111-record")
    assert github.record_refspec("d" * 40, "claude/deploy-11111111-record").endswith("claude/deploy-11111111-record")


def test_while_another_deploy_holds_the_lock_nothing_happens(server):
    settings, _world, host = server
    _waive(settings)
    with state.Lock(settings.state_dir):
        code, printed = _tick(settings, host)
        assert code == 0 and host.calls == [] and printed == ["Another deploy holds the lock; this tick did nothing."]
        plan_lines: list[str] = []
        service.plan(host, settings, token=github.Token(""), gate=Gate(), pinned=True, out=plan_lines.append)
        assert any("another deploy holds the lock" in line for line in plan_lines)
        with pytest.raises(state.LockHeld):
            with state.Lock(settings.state_dir):
                pass
    assert not state.lock_held(settings.state_dir)


# ------------------------------------------------------------------ secrets


def test_the_token_is_never_an_argument_printed_or_recorded(server):
    settings, world, host = server
    _waive(settings)
    world.echo_token = True                         # every command "says" the token back
    world.fail.add("journal")                       # and a rollback, so every path writes something
    code, printed = _tick(settings, host, token=TOKEN)
    assert _status(settings)["state"] == "rolled_back"
    assert not any(TOKEN in arg for call in host.calls for arg in call[1]), "never an argument"
    with_token = {call[0] for call in host.calls if TOKEN in call[2].values()}
    assert with_token == {"fetch_trunk", "record_listed", "record_push"}, "only git's GitHub calls carry it"
    assert TOKEN not in "\n".join(printed)
    for path in settings.state_dir.rglob("*"):
        if path.is_file():
            assert TOKEN.encode() not in path.read_bytes(), path
    assert TOKEN not in repr(github.Token(TOKEN)) and TOKEN not in str(github.Token(TOKEN))


def test_the_token_is_read_from_systemds_credential_folder_only(tmp_path, monkeypatch):
    (tmp_path / "clive_release_github_token").write_text(TOKEN + "\n")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    token = github.read_token("clive_release_github_token")
    assert token.present and token.env() == {github.TOKEN_ENV: TOKEN}
    assert github.read_token("../etc/passwd").present is False
    monkeypatch.delenv("CREDENTIALS_DIRECTORY")
    assert github.read_token("clive_release_github_token").present is False


# ------------------------------------------------------------------ what CLIVE reads, and the files for the server


def test_clive_reads_the_status_and_says_plainly_when_there_is_none(tmp_path):
    assert status.read(tmp_path) == {"installed": False, "state": "", "line": status.NOT_INSTALLED, "at": "",
                                     "mode": ""}
    (tmp_path / "status.json").write_text("not json")
    assert status.read(tmp_path)["line"] == status.UNREADABLE
    host = SystemHost()
    state.write_status(host, tmp_path, state="deployed", line="Deployed “X”.  Open /whoami.", at="2026-10-08T01:00:00Z",
                       mode="live", sha=TRUNK)
    assert status.read(tmp_path) == {"installed": True, "state": "deployed", "line": "Deployed “X”. Open /whoami.",
                                     "at": "2026-10-08T01:00:00Z", "mode": "live"}


def test_decide_is_pure_and_names_every_reason():
    settings = ReleaseSettings(enabled=False, rule="maybe")
    facts = Facts(trunk=TRUNK, live=LIVE, forward=True, acceptance=Gate(GateState.RED).check("r", TRUNK))
    decision = decide.decide(settings, facts, lock_held=True, halted={"reason": "x"})
    assert decision.state == "off" and not decision.deploy
    text = " | ".join(decision.reasons)
    for said in ("switched off", "CLIVE_RELEASE_RULE is 'maybe'", "could not be rolled back", "holds the lock",
                 "acceptance on this SHA is red"):
        assert said in text


def test_the_server_files_are_off_by_default_and_hold_no_secret():
    root = Path(__file__).resolve().parents[1] / "deploy" / "release"
    unit = (root / "clive-release.service").read_text()
    timer = (root / "clive-release.timer").read_text()
    env = (root / "release.env.example").read_text()
    assert "ExecStart=/opt/crooks-os/crooks-assistant/.venv/bin/python -m app.release tick" in unit
    assert "WorkingDirectory=/srv/clive-release/pin/crooks-assistant" in unit
    assert "LoadCredentialEncrypted=clive_release_github_token:" in unit and "github_pat_" not in unit
    assert "EnvironmentFile=/etc/crooks-os/release.env" in unit and "Type=oneshot" in unit
    assert "OnUnitActiveSec=5min" in timer and "Unit=clive-release.service" in timer
    assert "CLIVE_RELEASE_ENABLED=false" in env and "CLIVE_RELEASE_RULE=off" in env
    assert "CLIVE_RELEASE_DRY_RUN=true" in env
    assert ReleaseSettings.model_fields["enabled"].default is False
    assert ReleaseSettings.model_fields["rule"].default == "off"


def test_a_refusal_before_the_change_leaves_no_record_and_pushes_nothing(server):
    settings, world, host = server
    _waive(settings)
    world.fail.add("doctor")
    _tick(settings, host, token=TOKEN)
    assert not list((settings.state_dir / "deploys" / "11111111").glob("deploy-*.md"))
    assert not {"record_blob", "record_push"} & set(host.steps)


def test_a_command_it_runs_inherits_neither_its_pin_nor_its_credentials(monkeypatch):
    from app.release.host import child_env

    monkeypatch.setenv("PYTHONPATH", "/srv/clive-release/pin/crooks-assistant")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", "/run/credentials/clive-release.service")
    monkeypatch.setenv("CLIVE_RELEASE_ENABLED", "true")
    env = child_env({"HOME": "/root", github.TOKEN_ENV: TOKEN})
    assert "PYTHONPATH" not in env and "CREDENTIALS_DIRECTORY" not in env and "CLIVE_RELEASE_ENABLED" not in env
    assert env["HOME"] == "/root" and env[github.TOKEN_ENV] == TOKEN, "only what the step is given"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


# ------------------------------------------------------------------ the review's notes (night of 7–8 Oct)


def test_a_deploy_stopped_part_way_halts_instead_of_reading_as_up_to_date(server):
    """Note 1: killed after the checkout (systemd's time limit, a reboot, systemctl stop), production is on
    the new SHA with nothing verified; the next tick must halt, not say "production runs the trunk's latest"."""
    settings, world, host = server
    _waive(settings)

    def killed():
        raise SystemExit("the service was stopped")

    world.on_step["gap_check"] = killed
    with pytest.raises(SystemExit):
        _tick(settings, host)
    marker = settings.state_dir / "deploys" / "11111111" / "started"
    assert world.head == TRUNK and json.loads(marker.read_text())["sha"] == TRUNK
    world.on_step.clear()
    printed: list[str] = []
    service.plan(host, settings, token=github.Token(""), gate=Gate(), pinned=True, out=printed.append)
    assert "WOULD NOT DEPLOY" in "\n".join(printed) and "stopped part way" in "\n".join(printed)
    host.calls.clear()
    code, printed = _tick(settings, host)
    assert code == 1 and host.calls == [], "nothing read, nothing changed"
    now = _status(settings)
    assert now["state"] == "halted" and "stopped part way" in now["line"] and "11111111" in now["line"], now
    assert json.loads((settings.state_dir / "HALT").read_text())["sha"] == TRUNK
    assert not marker.exists(), "HALT now says it"
    # A person puts production back and removes HALT: that SHA is not tried again on its own.
    world.head = LIVE
    (settings.state_dir / "HALT").unlink()
    host.calls.clear()
    _tick(settings, host)
    assert _changed_anything(host) == [] and "is not tried again on its own" in _status(settings)["line"]


def test_the_started_marker_is_written_before_the_checkout(server):
    settings, world, host = server
    _waive(settings)
    marker = settings.state_dir / "deploys" / "11111111" / "started"
    seen: list[bool] = []
    world.on_step["checkout"] = lambda: seen.append(marker.exists())
    _tick(settings, host)
    assert seen == [True] and not marker.exists()


def test_systemd_never_stops_a_tick_its_own_step_limits_would_still_allow(server):
    """Note 1: TimeoutStartSec above the sum of every limit the longest tick meets: exact_sha_review, a
    record branch already there, a deploy that goes all the way to the journal and rolls back in full."""
    settings, world, host = server
    settings.rule = "exact_sha_review"
    settings.settle_s = ReleaseSettings.model_fields["settle_s"].default
    world.review = {"schema": authority.REVIEW_SCHEMA, "sha": TRUNK, "base_sha": OTHER, "verdict": "SHIP",
                    "blocking": [], "reviewer": "review session", "reviewed_at": "2026-10-08T00:10:00Z"}
    world.record_exists = True
    world.fail.add("journal")
    code, _ = _tick(settings, host, token=TOKEN)
    assert code == 1 and _status(settings)["state"] == "rolled_back"
    assert {"review_base", "record_fetch", "rollback_install"} <= set(host.steps)
    # GitHub's acceptance: one ask for the runs and one per run, each bounded by the gate's own limit on
    # connect, write, read and pool alike; allowed here for nine runs on one SHA.
    acceptance = 10 * 4 * github_acceptance.TIMEOUT_S
    budget = sum(host.timeouts) + settings.settle_s + acceptance
    unit = (Path(__file__).resolve().parents[1] / "deploy" / "release" / "clive-release.service").read_text()
    limit = re.search(r"^TimeoutStartSec=(\d+)(h|min|s)?$", unit, re.M)
    assert limit, "a finite limit"
    seconds = int(limit[1]) * {"h": 3600, "min": 60, "s": 1, None: 1}[limit[2]]
    assert seconds > budget, (seconds, budget)


def test_a_sha_that_halted_is_not_tried_again_once_halt_is_removed(server):
    """Note 2."""
    settings, world, host = server
    _waive(settings)
    world.fail |= {"install", "rollback_install"}
    _tick(settings, host)
    assert _status(settings)["state"] == "halted"
    assert json.loads((settings.state_dir / "failed" / f"{TRUNK}.json").read_text())["reason"]
    (settings.state_dir / "HALT").unlink()
    world.fail.clear()
    host.calls.clear()
    _tick(settings, host)
    assert _changed_anything(host) == [] and "is not tried again on its own" in _status(settings)["line"]


def test_a_halt_written_after_the_ticks_first_look_still_stops_it(server):
    """Note 3: HALT is read again once the lock is held, just before anything could change."""
    settings, world, host = server
    _waive(settings)
    world.on_step["fetch_trunk"] = lambda: (settings.state_dir / "HALT").write_text('{"reason": "a person stopped it"}')
    code, _ = _tick(settings, host)
    assert code == 1 and _changed_anything(host) == [] and "precheck_head" not in host.steps
    now = _status(settings)
    assert now["state"] == "halted" and "a person stopped it" in now["line"] and world.head == LIVE


def test_the_new_builds_unit_is_rendered_before_make_install_and_a_difference_rolls_back(server):
    """Note 4: the unit rendered is the NEW build's (after the checkout), before make install writes it."""
    settings, world, host = server
    _waive(settings)
    world.rendered_new = UNIT.decode() + "LoadCredentialEncrypted=new_key:/etc/crooks-os/credentials/new_key.cred\n"
    code, _ = _tick(settings, host, token=TOKEN)
    assert code == 1 and "install" not in host.steps and world.head == LIVE
    assert host.steps.index("checkout") < host.steps.index("gap_check") < host.steps.index("render_new")
    assert [step for step in host.steps if step.startswith("rollback_")] == CODE_ONLY
    render = next(call for call in host.calls if call[0] == "render_new")
    assert render[1][1:] == ["scripts/install_systemd.py", "--print"] and render[2]["HOME"] == "/root"
    now = _status(settings)
    assert now["state"] == "rolled_back" and "would install a different unit from the live one" in now["line"]
    assert (settings.state_dir / "failed" / f"{TRUNK}.json").exists()


def test_a_unit_make_install_wrote_differently_rolls_back(server):
    """Note 4: and after make install, the unit read back; any difference from the saved copy rolls back."""
    settings, world, host = server
    _waive(settings)
    world.on_step["install"] = lambda: settings.unit_path.write_bytes(UNIT + b"Environment=EXTRA=1\n")
    code, _ = _tick(settings, host)
    assert code == 1 and [step for step in host.steps if step.startswith("rollback_")] == FULL
    assert settings.unit_path.read_bytes() == UNIT, "the saved unit was put back"
    assert "differs from the saved copy" in _status(settings)["line"]


def test_dry_run_is_on_unless_switched_off_in_so_many_words(tmp_path, monkeypatch):
    """Note 5: a release.env that lost its CLIVE_RELEASE_DRY_RUN line stays a dry run."""
    for name in ("CLIVE_RELEASE_ENABLED", "CLIVE_RELEASE_RULE", "CLIVE_RELEASE_DRY_RUN"):
        monkeypatch.delenv(name, raising=False)
    assert ReleaseSettings.model_fields["dry_run"].default is True
    env = tmp_path / "release.env"
    env.write_text("CLIVE_RELEASE_ENABLED=true\nCLIVE_RELEASE_RULE=owner_waiver\n")
    loaded = settings_module.load(env)
    assert loaded.enabled and loaded.rule_named() == "owner_waiver" and loaded.dry_run is True
    env.write_text(env.read_text() + "CLIVE_RELEASE_DRY_RUN=false\n")
    assert settings_module.load(env).dry_run is False


def test_decide_deploys_only_when_each_condition_is_known_to_hold():
    """Note 6: no recorded problem is not enough; forward, acceptance and authority must each be true."""
    settings = ReleaseSettings(enabled=True, rule="owner_waiver")
    green = Gate().check("r", TRUNK)
    granted = authority.Authority(True, "waived by George (given on the server)", kind="waiver")
    assert decide.decide(settings, Facts(trunk=TRUNK, live=LIVE, forward=True, acceptance=green,
                                         authority=granted)).deploy
    for facts, said in (
        (Facts(trunk=TRUNK, live=LIVE, forward=None), "not known that production is behind"),
        (Facts(trunk=TRUNK, live=LIVE, forward=None, acceptance=green, authority=granted),
         "not known that production is behind"),
        (Facts(trunk=TRUNK, live="", forward=True, acceptance=green, authority=granted),
         "the SHA production runs is not known"),
        (Facts(trunk="", live=LIVE, forward=True, acceptance=green, authority=granted), "head is not known"),
    ):
        decision = decide.decide(settings, facts)
        assert not decision.deploy and decision.state == "waiting", facts
        assert any(said in reason for reason in decision.reasons), (said, decision.reasons)


def test_georges_own_words_never_reach_the_record(server):
    """Note 12: the record is pushed to a public repository; his free-text words stay in the waiver."""
    settings, _world, host = server
    _waive(settings, words="ship it, Jane Doe can wait for her refund")
    code, _ = _tick(settings, host, token=TOKEN)
    assert code == 0
    kept = (settings.state_dir / "deploys" / "11111111" / "deploy-11111111.md").read_text()
    pushed = next(call for call in host.calls if call[0] == "record_blob")[3]
    for text in (kept, pushed):
        assert "Jane Doe" not in text and "refund" not in text
    assert "waived by George (given on the server)" in kept


def test_the_journal_read_is_the_new_processs_not_the_old_ones_shutdown(server):
    """Note 14: an ERROR the old process logged while stopping does not roll back a good deploy."""
    settings, world, host = server
    _waive(settings)
    world.journal_old = "12:00:00 ERROR crooks.runtime stopping: a report withheld\n"
    code, printed = _tick(settings, host)
    assert code == 0 and _status(settings)["state"] == "deployed", printed
    journal = next(call for call in host.calls if call[0] == "journal")[1]
    assert journal[journal.index("--since") + 1].startswith("@")
    assert journal[-3:] == [f"_SYSTEMD_INVOCATION_ID={'f' * 32}", "+", f"INVOCATION_ID={'f' * 32}"]


def test_when_the_new_process_cannot_be_told_apart_the_whole_journal_since_the_install_is_read(server):
    settings, world, host = server
    _waive(settings)
    world.journal_old = "12:00:00 ERROR crooks.runtime stopping\n"
    world.same_invocation = True
    code, _ = _tick(settings, host)
    assert code == 1 and _status(settings)["state"] == "rolled_back", "stricter, never looser"
    journal = next(call for call in host.calls if call[0] == "journal")[1]
    assert journal[-2:] == ["-u", "crooks-assistant.service"]
