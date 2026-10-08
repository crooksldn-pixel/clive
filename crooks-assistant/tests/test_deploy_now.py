"""Deploy now (DEC-072; the owner's rulings 6, 7 and 8 of 8 October 2026): his hold and passkey on the
Builds screen approve exactly one version, the release service is started at once and checks the
approval itself, and CLIVE follows the deploy to the end, keeping it once his phone gets through.

What these hold it to:
- no card unless the trunk's head is ahead of what runs and acceptance is green on exactly that SHA;
  when his hold cannot deploy it, the card says why instead of offering it;
- the team never see it or use it: every route is the owner's;
- an approval for SHA A can deploy nothing but A; a challenge is good once and expires in minutes, on
  CLIVE's side and again on the release service's, which also spends an approval before it deploys;
- the trigger starts a tick at once (the path unit, checked by systemd's own verifier where it is
  installed), and an approval that arrives while a tick runs is deployed by that tick;
- the status says each stage as it is reached, a rollback with why, a refusal with why, a dry run as
  a dry run; CLIVE's progress says the same; and "kept" only once the journal holds his phone's line,
  on the new build.

The release service runs on the fake server of tests/test_release_service.py; CLIVE's routes run in the
real app with real passkey signatures (tests/fake_passkey.py) and the trunk read from a stand-in.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.connections import passkeys
from app.orchestrator.github_acceptance import GateResult, GateState, RunFact
from app.release import approve, authority, offer, state, status
from app.release.offer import Trunk
from app.release.settings import ReleaseSettings
from app.routes import release as release_route
from app.tools import engineering_tools
from tests.test_actions_routes import PROXIED, client  # noqa: F401 - `client` is a fixture
from tests.test_connections_routes import (  # noqa: F401 - `world` is a fixture
    HEADERS,
    register,
    world,
)
from tests.test_release_service import (  # noqa: F401 - `server` is a fixture
    ISSUED,
    LIVE,
    MUTATING,
    OTHER,
    TOKEN,
    TRUNK,
    FakeHost,
    Gate,
    _passkey_waiver,
    _register,
    _status,
    _tick,
    server,
)
from tests.test_team import AS_MIA, let_mia_in, team  # noqa: F401 - `team` is a fixture

ROOT = Path(__file__).resolve().parents[1]
TITLE = "Days left count London's day"
GREEN = GateResult(TRUNK, GateState.GREEN, "acceptance run(s) 77 completed with success",
                   (RunFact(77, "completed", "success"),))


class Recording(FakeHost):
    """The fake server, keeping every status the service wrote, in order."""

    def __init__(self, fake, on_status=None) -> None:
        super().__init__(fake)
        self.statuses: list[dict] = []
        self.on_status = on_status

    def write(self, path, data, mode):
        super().write(path, data, mode)
        if Path(path).name == "status.json":
            self.statuses.append(json.loads(data))
            if self.on_status:
                self.on_status(len(self.statuses))


def _stages(found: dict) -> list[str]:
    return [stage for stage, _at in (found.get("deploy") or {}).get("steps") or []]


# ------------------------------------------------------------------ the release service's half


def test_a_deploy_says_each_stage_on_the_status_as_it_is_reached(server, tmp_path):  # noqa: F811 - fixtures imported from the suite they belong to
    settings, fake, _host = server
    host = Recording(fake)
    approval = _passkey_waiver(settings, _register(tmp_path))
    code, printed = _tick(settings, host)
    assert code == 0, printed
    seen = [_stages(s) for s in host.statuses]
    assert seen == [["started"], ["started", "checks"], ["started", "checks", "installing"],
                    ["started", "checks", "installing", "health"],
                    ["started", "checks", "installing", "health", "done"]], seen
    assert [s["state"] for s in host.statuses] == ["would_deploy"] * 4 + ["deployed"]
    last = host.statuses[-1]
    assert last["deploy"]["approval"] == approval and last["deploy"]["end"] == "done"
    assert last["deploy"]["title"] == "Days left count London's day (PR #99)" and last["rule"] == "owner_waiver"
    # What CLIVE reads of it, checked for shape: the stages in order, each with when.
    read = status.read(settings.state_dir)["deploy"]
    assert [s["stage"] for s in read["steps"]] == ["started", "checks", "installing", "health", "done"]
    assert all(re.fullmatch(r"2026-10-08T01:\d\d:\d\dZ", s["at"]) for s in read["steps"])


def test_a_rollback_is_shown_with_why(server, tmp_path):  # noqa: F811 - fixtures imported from the suite they belong to
    settings, fake, _host = server
    host = Recording(fake)
    approval = _passkey_waiver(settings, _register(tmp_path))
    fake.health["health_after"] = None
    code, _ = _tick(settings, host)
    assert code == 1 and fake.head == LIVE
    deploy = status.read(settings.state_dir)["deploy"]
    why = "/health after is not well: claude, proxy_identity, shopify went down"
    assert deploy["end"] == "rolled_back" and deploy["reason"] == why
    assert [s["stage"] for s in deploy["steps"]] == ["started", "checks", "installing", "health", "rolled_back"]
    shown = offer.progress(_approval(approval), status.read(settings.state_dir), kept=None, process_sha=LIVE,
                           now=_epoch("2026-10-08T01:05:00Z"))
    assert shown["end"] == "rolled_back" and shown["final"] is True
    assert shown["line"] == f"Rolled back: {why}. Production is back on the version it ran before."
    assert [s["state"] for s in shown["stages"]] == ["lit", "lit", "lit", "stop", "dim", "dim"]


def test_a_refusal_before_the_change_is_shown_with_why_and_the_approval_is_spent(server, tmp_path):  # noqa: F811 - fixtures imported from the suite they belong to
    settings, fake, _host = server
    host = Recording(fake)
    _passkey_waiver(settings, _register(tmp_path))
    fake.fail.add("doctor")
    code, _ = _tick(settings, host)
    assert code == 1 and [s for s in host.steps if s in MUTATING] == []
    deploy = status.read(settings.state_dir)["deploy"]
    assert (deploy["end"], deploy["reason"]) == ("refused", "make doctor: exit 1")
    # The same approval cannot start another: one hold, one deploy at most.
    fake.fail.clear()
    host.calls.clear()
    _tick(settings, host)
    assert [s for s in host.steps if s in MUTATING] == []
    assert "this approval was already used" in _status(settings)["line"]


def test_an_approval_starts_one_deploy_at_most(server, tmp_path):  # noqa: F811 - fixtures imported from the suite they belong to
    settings, fake, host = server
    _passkey_waiver(settings, _register(tmp_path))
    assert _tick(settings, host)[0] == 0 and fake.head == TRUNK
    fake.head = LIVE                       # production put back by hand; the same approval is still there
    host.calls.clear()
    _tick(settings, host)
    assert [s for s in host.steps if s in MUTATING] == []
    assert "this approval was already used" in _status(settings)["line"]


@pytest.mark.parametrize("how,said", [
    ("expired", "the approval expired at 01:09 UTC"),
    ("too long a life", "does not have the life CLIVE gives one"),
    ("issued in the future", "does not have the life CLIVE gives one"),
    ("no expiry (before DEC-072)", "no challenge CLIVE issued with an expiry"),
])
def test_an_approval_out_of_its_life_deploys_nothing(server, tmp_path, how, said):  # noqa: F811 - fixtures imported from the suite they belong to
    settings, fake, host = server
    device = _register(tmp_path)
    if how == "expired":
        _passkey_waiver(settings, device, issued=ISSUED - authority.APPROVAL_TTL_S)
        said = f"the approval expired at {datetime.fromtimestamp(ISSUED, UTC):%H:%M} UTC"
    elif how == "too long a life":
        _passkey_waiver(settings, device, life=24 * 3600)
    elif how == "issued in the future":
        _passkey_waiver(settings, device, issued=ISSUED + 3600)
    else:
        _passkey_waiver(settings, device)
        path = settings.passkey_waivers_dir / f"{TRUNK}.json"
        record = json.loads(path.read_text())
        del record["passkey"]["issued_at"], record["passkey"]["expires_at"]
        path.write_text(json.dumps(record))
    _tick(settings, host)
    assert [s for s in host.steps if s in MUTATING] == [] and fake.head == LIVE
    assert said in _status(settings)["line"], _status(settings)["line"]


def test_an_approval_for_one_sha_deploys_no_other(server, tmp_path):  # noqa: F811 - fixtures imported from the suite they belong to
    """Signed for A, the file renamed and rewritten to say B: the signature is over A's challenge."""
    settings, fake, host = server
    device = _register(tmp_path)
    _passkey_waiver(settings, device, sha=OTHER, signed_for=OTHER)
    record = json.loads((settings.passkey_waivers_dir / f"{OTHER}.json").read_text())
    record["sha"] = TRUNK
    (settings.passkey_waivers_dir / f"{TRUNK}.json").write_text(json.dumps(record))
    _tick(settings, host)
    assert [s for s in host.steps if s in MUTATING] == [] and fake.head == LIVE
    assert "other than deploying this exact SHA" in _status(settings)["line"]


def test_ready_for_names_the_sha_only_when_his_approval_is_all_it_lacks(server):  # noqa: F811 - fixtures imported from the suite they belong to
    settings, fake, host = server
    _tick(settings, host)
    assert _status(settings)["ready_for"] == TRUNK and _status(settings)["state"] == "waiting"
    for change in ("acceptance pending", "the installer", "dirty"):
        fake.changed = ["crooks-assistant/app/x.py"]
        fake.dirty = ""
        gate = Gate()
        if change == "acceptance pending":
            gate = Gate(GateState.PENDING)
        elif change == "the installer":
            fake.changed.append("crooks-assistant/deploy/systemd/crooks-assistant.service")
        else:
            fake.dirty = " M crooks-assistant/app/main.py\n"
        _tick(settings, host, gate=gate)
        assert _status(settings)["ready_for"] == "", change
    settings.rule = "exact_sha_review"
    fake.dirty = ""
    fake.changed = ["crooks-assistant/app/x.py"]
    _tick(settings, host)
    assert _status(settings)["ready_for"] == "", "only his approval's rule"


def test_dry_run_answers_his_hold_and_changes_nothing(server, tmp_path):  # noqa: F811 - fixtures imported from the suite they belong to
    settings, fake, host = server
    settings.dry_run = True
    approval = _passkey_waiver(settings, _register(tmp_path))
    _tick(settings, host)
    assert [s for s in host.steps if s in MUTATING] == [] and fake.head == LIVE
    now = _status(settings)
    assert now["state"] == "would_deploy" and now["mode"] == "dry_run"
    assert now["deploy"]["end"] == "dry_run" and now["deploy"]["approval"] == approval
    # Review note 1 (8 Oct): a dry run spends the approval, recorded as a dry run, so it never deploys later.
    assert state.approval_used(host, settings.state_dir, approval)["mode"] == "dry_run"
    shown = offer.progress(_approval(approval), status.read(settings.state_dir), kept=None, process_sha=LIVE,
                           now=_epoch("2026-10-08T01:01:00Z"))
    assert shown["line"] == ("Dry run: the release service checked everything and would deploy it now. Nothing "
                             "was changed.")


def test_a_hold_answered_in_dry_run_deploys_nothing_once_dry_run_is_switched_off(server, tmp_path):  # noqa: F811 - fixtures imported from the suite they belong to
    """Review note 1: he holds "Hold to try it (dry run)"; root switches dry run off within the approval's
    ten minutes; the next tick must not deploy on an approval he gave only to try it."""
    settings, fake, host = server
    settings.dry_run = True
    approval = _passkey_waiver(settings, _register(tmp_path))
    _tick(settings, host)
    assert _status(settings)["deploy"]["end"] == "dry_run"
    settings.dry_run = False                     # "looks good, turn dry run off", inside the ten minutes
    assert host.clock.timestamp() < ISSUED + authority.APPROVAL_TTL_S
    host.calls.clear()
    code, printed = _tick(settings, host)
    assert [s for s in host.steps if s in MUTATING] == [] and fake.head == LIVE, printed
    now = _status(settings)
    assert now["state"] == "waiting" and now["mode"] == "live"
    assert "this approval was used for a dry run" in now["line"], now["line"]
    assert now["deploy"]["end"] == "dry_run" and now["deploy"]["approval"] == approval, "the dry run is still shown"
    assert now["ready_for"] == TRUNK, "his hold is offered again, to deploy for real"


def test_a_dry_run_that_cannot_spend_the_approval_says_so_and_does_not_count_it(server, tmp_path, monkeypatch):  # noqa: F811 - fixtures imported from the suite they belong to
    settings, fake, host = server
    settings.dry_run = True
    approval = _passkey_waiver(settings, _register(tmp_path))
    monkeypatch.setattr(state, "spend_approval", lambda *a, **k: False)
    _tick(settings, host)
    deploy = _status(settings)["deploy"]
    assert [s for s in host.steps if s in MUTATING] == [] and fake.head == LIVE
    assert (deploy["end"], deploy["approval"]) == ("refused", approval)
    assert deploy["reason"] == "the approval could not be marked as used, so it was not used"


def test_the_deploy_stays_on_the_status_after_the_next_tick(server, tmp_path):  # noqa: F811 - fixtures imported from the suite they belong to
    settings, _world, host = server
    _passkey_waiver(settings, _register(tmp_path))
    _tick(settings, host)
    _tick(settings, host)                                   # production now runs the trunk's head
    now = _status(settings)
    assert now["state"] == "up_to_date" and now["deploy"]["end"] == "done"


def test_a_deploy_stopped_part_way_ends_halted_on_the_status(server, tmp_path):  # noqa: F811 - fixtures imported from the suite they belong to
    settings, fake, host = server
    _passkey_waiver(settings, _register(tmp_path))

    def killed():
        raise SystemExit("the service was stopped")

    fake.on_step["gap_check"] = killed
    with pytest.raises(SystemExit):
        _tick(settings, host)
    assert _stages(_status(settings)) == ["started", "checks", "installing"]
    fake.on_step.clear()
    _tick(settings, host)
    deploy = status.read(settings.state_dir)["deploy"]
    assert deploy["end"] == "halted" and "stopped part way" in deploy["reason"]
    assert _status(settings)["state"] == "halted"


def _within(seconds: float, run, fifos: list[Path]):
    """`run()` in a thread, failed (not hung) if it is still going after `seconds`; any reader still
    waiting on one of `fifos` is then let go (a writer opened and closed), so the suite never hangs."""
    import threading

    out: dict = {}
    worker = threading.Thread(target=lambda: out.setdefault("result", run()), daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        for fifo in fifos:
            try:
                os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
            except OSError:
                pass
        worker.join(10)
        pytest.fail(f"still waiting after {seconds} s: a pipe held the tick (and its deploy lock)")
    return out.get("result")


def test_the_service_reads_clives_folder_as_plain_files_only(tmp_path):
    from app.release.host import SystemHost

    host = SystemHost()
    plain = tmp_path / "plain.json"
    plain.write_bytes(b"{}")
    assert host.read_plain(plain, 64) == (b"{}", "")
    assert host.read_plain(tmp_path / "missing.json", 64) == (None, "")
    (tmp_path / "link.json").symlink_to(plain)
    assert host.read_plain(tmp_path / "link.json", 64) == (None, "it is a link, or it cannot be opened")
    os.mkfifo(tmp_path / "pipe.json")
    assert _within(10, lambda: host.read_plain(tmp_path / "pipe.json", 64), [tmp_path / "pipe.json"]) == \
        (None, "it is not a plain file")
    (tmp_path / "big.json").write_bytes(b" " * 65)
    assert host.read_plain(tmp_path / "big.json", 64) == (None, "it is larger than 64 bytes")


def test_a_link_in_clives_folder_is_never_followed(server, tmp_path):  # noqa: F811 - fixtures imported from the suite they belong to
    """Review note 4: a valid approval kept elsewhere and linked into CLIVE's folder deploys nothing."""
    settings, fake, host = server
    _passkey_waiver(settings, _register(tmp_path))
    elsewhere = tmp_path / "elsewhere.json"
    (settings.passkey_waivers_dir / f"{TRUNK}.json").rename(elsewhere)
    (settings.passkey_waivers_dir / f"{TRUNK}.json").symlink_to(elsewhere)
    _tick(settings, host)
    assert [s for s in host.steps if s in MUTATING] == [] and fake.head == LIVE
    assert "the approval in CLIVE's folder was not read: it is a link" in _status(settings)["line"]
    # The registered passkeys, linked in from elsewhere, are not read either.
    (settings.passkey_waivers_dir / f"{TRUNK}.json").unlink()
    elsewhere.rename(settings.passkey_waivers_dir / f"{TRUNK}.json")
    keys = tmp_path / "keys-elsewhere.json"
    settings.passkeys_file.rename(keys)
    settings.passkeys_file.symlink_to(keys)
    host.calls.clear()
    _tick(settings, host)
    assert [s for s in host.steps if s in MUTATING] == [] and fake.head == LIVE
    assert "the registered passkeys were not read: it is a link" in _status(settings)["line"]


def test_a_pipe_in_clives_folder_never_holds_the_tick(server, tmp_path):  # noqa: F811 - fixtures imported from the suite they belong to
    """Review note 4: a FIFO where an approval should be would hang the root tick while it holds the
    deploy lock (up to four hours). Under the trunk's name, or any other: read as not a plain file."""
    settings, fake, host = server
    settings.passkey_waivers_dir.mkdir()
    named, other = settings.passkey_waivers_dir / f"{TRUNK}.json", settings.passkey_waivers_dir / "other.json"
    os.mkfifo(named)
    os.mkfifo(other)
    _within(20, lambda: _tick(settings, host), [named, other])
    assert [s for s in host.steps if s in MUTATING] == [] and fake.head == LIVE
    assert "the approval in CLIVE's folder was not read: it is not a plain file" in _status(settings)["line"]
    # A real approval beside a pipe still deploys: the pipe is counted by name, never waited on.
    named.unlink()
    _passkey_waiver(settings, _register(tmp_path))
    code, printed = _within(20, lambda: _tick(settings, host), [other])
    assert code == 0 and fake.head == TRUNK, printed


# ------------------------------------------------------------------ the trigger


def test_the_path_unit_starts_a_tick_when_clive_writes_an_approval():
    unit = (ROOT / "deploy" / "release" / "clive-release-now.path").read_text()
    watched = re.search(r"^PathChanged=(.+)$", unit, re.M)
    assert watched and watched[1] == str(ReleaseSettings.model_fields["passkey_waivers_dir"].default)
    assert watched[1].endswith("/" + approve.WAIVERS), "the folder CLIVE writes approvals into"
    assert re.search(r"^Unit=clive-release\.service$", unit, re.M)
    assert re.search(r"^ConditionPathExists=/etc/crooks-os/release\.env$", unit, re.M)
    assert re.search(r"^WantedBy=paths\.target$", unit, re.M)
    assert "Timer" not in re.sub(r"#.*", "", unit), "no timer in the way"


def test_systemd_itself_reads_the_path_unit(tmp_path):
    analyze = shutil.which("systemd-analyze")
    if analyze is None:
        pytest.skip("systemd-analyze is not installed here")
    root = ROOT / "deploy" / "release"
    shutil.copy(root / "clive-release-now.path", tmp_path / "clive-release-now.path")
    # The service it starts, with a command this machine has: systemd checks Unit= names a real unit.
    service = (root / "clive-release.service").read_text()
    (tmp_path / "clive-release.service").write_text(re.sub(r"^ExecStart=.*$", "ExecStart=/bin/true", service,
                                                           flags=re.M))
    done = subprocess.run([analyze, "verify", "--man=no", str(tmp_path / "clive-release-now.path")],
                          capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    # And the verifier is not just quiet: a misspelt watch is refused.
    (tmp_path / "broken.path").write_text((tmp_path / "clive-release-now.path").read_text()
                                          .replace("PathChanged=", "PathChnaged="))
    done = subprocess.run([analyze, "verify", "--man=no", str(tmp_path / "broken.path")],
                          capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode != 0 and "lacks path setting" in done.stderr


def test_an_approval_that_arrives_while_a_tick_runs_is_deployed_by_that_tick(server, tmp_path):  # noqa: F811 - fixtures imported from the suite they belong to
    """systemd folds the trigger's start into a tick already running: that tick looks once more."""
    settings, fake, _host = server
    device = _register(tmp_path)
    host = Recording(fake, on_status=lambda n: _passkey_waiver(settings, device) if n == 1 else None)
    code, printed = _tick(settings, host)
    assert code == 0 and fake.head == TRUNK, printed
    assert "An approval arrived while this tick ran; looking again." in printed
    assert host.statuses[0]["state"] == "waiting" and _status(settings)["state"] == "deployed"


def test_the_second_look_fits_in_the_units_time_limit(server, tmp_path):  # noqa: F811 - fixtures imported from the suite they belong to
    """The longest tick with a second look: a look that deploys nothing, then a deploy that goes all the way
    to the journal and rolls back in full, its record pushed onto a branch already there."""
    from app.orchestrator import github_acceptance

    settings, fake, _host = server
    settings.settle_s = ReleaseSettings.model_fields["settle_s"].default
    device = _register(tmp_path)
    host = Recording(fake, on_status=lambda n: _passkey_waiver(settings, device) if n == 1 else None)
    fake.record_exists = True
    fake.fail.add("journal")
    code, printed = _tick(settings, host, token=TOKEN)
    assert code == 1 and _status(settings)["state"] == "rolled_back", printed
    assert host.steps.count("fetch_trunk") == 2 and {"rollback_install", "record_fetch", "record_push"} <= set(host.steps)
    acceptance = 2 * 10 * 4 * github_acceptance.TIMEOUT_S          # two looks, each as the first tick test allows
    budget = sum(host.timeouts) + settings.settle_s + acceptance
    unit = (ROOT / "deploy" / "release" / "clive-release.service").read_text()
    limit = re.search(r"^TimeoutStartSec=(\d+)(h|min|s)?$", unit, re.M)
    seconds = int(limit[1]) * {"h": 3600, "min": 60, "s": 1, None: 1}[limit[2]]
    assert seconds > budget, (seconds, budget)


# ------------------------------------------------------------------ CLIVE's half: the card, pure


def _epoch(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def _approval(approval_id: str, given: str = "2026-10-08T01:00:00Z") -> dict:
    return {"sha": TRUNK, "title": TITLE, "approval": approval_id, "given_at": given, "given": _epoch(given),
            "expires_at": "", "expires": _epoch(given) + authority.APPROVAL_TTL_S}


def _trunk(**change) -> Trunk:
    found = Trunk(sha=TRUNK, title=TITLE, ahead=True, changes=[TITLE, "Seven fixes from the review"], count=2,
                  files=["crooks-assistant/app/objectives/store.py"], acceptance=GREEN)
    for key, value in change.items():
        setattr(found, key, value)
    return found


READY = {"installed": True, "state": "waiting", "line": "Not deploying “X”: George has not waived the review for "
         "this SHA.", "at": "2026-10-08T00:55:00Z", "mode": "live", "rule": "owner_waiver", "ready_for": TRUNK,
         "sha": TRUNK, "title": TITLE, "deploy": None}


@pytest.mark.parametrize("change", [
    {"sha": LIVE}, {"ahead": False}, {"ahead": None}, {"sha": ""},
    {"acceptance": None},
    {"acceptance": GateResult(TRUNK, GateState.PENDING, "1 of 1 acceptance run(s) not completed", ())},
    {"acceptance": GateResult(TRUNK, GateState.RED, "1 of 1 acceptance run(s) not successful", ())},
    {"acceptance": GateResult(TRUNK, GateState.MISSING, "no run", ())},
    {"acceptance": GateResult(TRUNK, GateState.UNAVAILABLE, "GitHub could not be reached", ())},
    {"acceptance": GateResult(OTHER, GateState.GREEN, "green, but for another commit", ())},
])
def test_no_card_unless_the_trunk_is_ahead_and_green_on_that_exact_sha(change):
    assert offer.offer(_trunk(**change), live=LIVE, release=READY) is None
    assert offer.offer(_trunk(), live="", release=READY) is None
    card = offer.offer(_trunk(), live=LIVE, release=READY)
    assert card["sha"] == TRUNK and card["title"] == TITLE and card["hold"]["can"] is True
    assert card["hold"]["label"] == "Hold to deploy" and card["acceptance"] == {"green": True, "runs": [77]}


@pytest.mark.parametrize("release,said", [
    ({"installed": False, "state": ""}, "isn't installed on this server yet"),
    ({"state": "off"}, "switched off (CLIVE_RELEASE_ENABLED)"),
    ({"state": "no_rule", "rule": ""}, "isn't owner_waiver"),
    ({"rule": "exact_sha_review"}, "isn't owner_waiver"),
    ({"state": "halted", "line": "The release service has stopped until a person looks: a rollback failed."},
     "has stopped until a person looks"),
    ({"ready_for": "", "line": "Not deploying “X”: production's checkout has local changes."},
     "production's checkout has local changes"),
    ({"state": "", "line": status.UNREADABLE}, status.UNREADABLE),
])
def test_the_hold_says_why_when_it_cannot_deploy_now(release, said):
    card = offer.offer(_trunk(), live=LIVE, release={**READY, **release})
    assert card["hold"]["can"] is False and said in card["hold"]["why_not"], card["hold"]


def test_the_hold_refuses_a_change_that_stays_a_hand_deploy_and_one_too_large_to_check():
    guarded = _trunk(files=["crooks-assistant/app/x.py", "crooks-assistant/deploy/systemd/crooks-assistant.service"])
    hold = offer.offer(guarded, live=LIVE, release={**READY, "sha": OTHER, "ready_for": ""})["hold"]
    assert not hold["can"] and "crooks-assistant/deploy/systemd/crooks-assistant.service" in hold["why_not"]
    unknown = offer.offer(_trunk(files=None), live=LIVE, release={**READY, "sha": OTHER, "ready_for": ""})["hold"]
    assert not unknown["can"] and "too large" in unknown["why_not"]
    # The service has already looked at it and says only his approval is missing: that settles it.
    assert offer.offer(_trunk(files=None), live=LIVE, release=READY)["hold"]["can"] is True
    # Not looked at yet, and nothing it touches stays a hand deploy: he may hold; the service checks it all.
    fresh = offer.offer(_trunk(), live=LIVE, release={**READY, "sha": OTHER, "ready_for": ""})["hold"]
    assert fresh["can"] and fresh["note"] == "The release service checks everything again the moment you hold."


def test_dry_run_is_said_on_the_hold():
    hold = offer.offer(_trunk(), live=LIVE, release={**READY, "mode": "dry_run"})["hold"]
    assert hold["can"] and hold["dry_run"] and hold["label"] == "Hold to try it (dry run)"


def test_a_deploy_under_way_is_not_offered_again():
    hold = offer.offer(_trunk(), live=LIVE, release={**READY, "state": "would_deploy", "ready_for": "",
                                                     "line": "Deploying “X”."})["hold"]
    assert not hold["can"] and hold["why_not"] == "A deploy is under way now. Deploying “X”."


async def test_github_is_read_without_the_token_when_it_refuses_it():
    """The repository is public: a token GitHub refuses for a read (no Actions: read, say) is not the end."""
    import httpx

    asked: list[tuple[str, bool]] = []
    body = {"status": "ahead", "ahead_by": 1, "files": [{"filename": "crooks-assistant/app/a.py"}],
            "commits": [{"sha": TRUNK, "commit": {"message": f"{TITLE} (PR #99)"}, "parents": [{"sha": LIVE}]}]}

    def answer(request: httpx.Request) -> httpx.Response:
        authed = "authorization" in request.headers
        asked.append((request.url.path, authed))
        if authed:
            return httpx.Response(403, json={"message": "Resource not accessible by personal access token"})
        if request.url.path.endswith("/git/ref/heads/clive/trunk"):
            return httpx.Response(200, json={"object": {"sha": TRUNK}})
        if "/compare/" in request.url.path:
            return httpx.Response(200, json=body)
        if request.url.path.endswith("/runs"):
            return httpx.Response(200, json={"total_count": 1, "workflow_runs": [
                {"id": 77, "path": ".github/workflows/acceptance.yml", "head_sha": TRUNK, "status": "completed",
                 "conclusion": "success"}]})
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json={"total_count": 1, "jobs": [
                {"id": 9, "run_id": 77, "name": "acceptance", "head_sha": TRUNK, "status": "completed",
                 "conclusion": "success"}]})
        return httpx.Response(404, json={})

    reader = offer.GitHubTrunk("crooksldn-pixel/clive", token_source=lambda: "a-token-github-refuses",
                               transport=httpx.MockTransport(answer), sync_transport=httpx.MockTransport(answer))
    found = await reader.read(LIVE)
    assert found.sha == TRUNK and found.ahead and found.title == TITLE and not found.problem
    assert found.acceptance is not None and found.acceptance.green, found.acceptance
    assert offer.offer(found, live=LIVE, release=READY)["hold"]["can"]
    assert ("/repos/crooksldn-pixel/clive/git/ref/heads/clive/trunk", True) in asked
    assert ("/repos/crooksldn-pixel/clive/git/ref/heads/clive/trunk", False) in asked
    assert any(path.endswith("/runs") and not authed for path, authed in asked), "acceptance asked without it too"


def test_a_word_from_a_tick_that_began_before_his_approval_does_not_end_the_following():
    release = {**READY, "at": "2026-10-08T01:00:03Z"}
    mine = _approval("a" * 32)
    early = offer.progress(mine, release, kept=None, process_sha=LIVE, now=_epoch("2026-10-08T01:00:05Z"))
    assert early["end"] == "not_started" and early["final"] is False, "the page keeps asking: a second look follows"
    late = offer.progress(mine, release, kept=None, process_sha=LIVE, now=_epoch("2026-10-08T01:01:30Z"))
    assert late["final"] is True and "George has not waived" in late["line"]


def test_the_comparison_reads_as_pull_request_titles_newest_first():
    found = Trunk(sha="c" * 40)

    def commit(sha, message, *parents):
        return {"sha": sha, "commit": {"message": message}, "parents": [{"sha": p} for p in parents]}

    offer.compare(found, {"status": "ahead", "ahead_by": 4, "files": [{"filename": "crooks-assistant/app/a.py"}],
                          "commits": [
                              commit("a" * 40, "Seven fixes from the review (PR #95)\n\nbody", LIVE),
                              commit("e" * 40, f"Merge clive/trunk {'f' * 40} into clive/objective/x at {'a' * 40} "
                                                "(loop)\n\nThe loop's refresh before landing", "a" * 40, "f" * 40),
                              commit("b" * 40, "The card George holds is always on top (PR #111)", "e" * 40),
                              commit("c" * 40, "Deploy now on the Builds screen (PR #112)", "b" * 40)]})
    assert found.ahead is True and found.count == 4 and found.title == "Deploy now on the Builds screen"
    assert found.changes == ["Deploy now on the Builds screen", "The card George holds is always on top",
                             "Seven fixes from the review"]
    assert found.files == ["crooks-assistant/app/a.py"]
    behind = Trunk(sha="c" * 40)
    offer.compare(behind, {"status": "behind", "commits": []})
    assert behind.ahead is False


def test_only_the_loops_own_refresh_merge_is_left_out_of_the_list_he_approves_from():
    """Review note 2: a commit pushed straight onto the trunk with a merge-like title is listed; only the
    loop's exact refresh merge, with exactly the parents its title names, is plumbing."""
    def commit(sha, message, *parents):
        return {"sha": sha, "commit": {"message": message}, "parents": [{"sha": p} for p in parents]}

    loop = f"Merge clive/trunk {'f' * 40} into clive/objective/x-y at {'a' * 40} (loop)"
    pushed = [
        commit("1" * 40, "Merge branch 'quick-fix' into clive/trunk", LIVE),
        commit("2" * 40, "Merge remote-tracking branch 'origin/clive/trunk' into clive/trunk", "1" * 40, "9" * 40),
        commit("3" * 40, "Merge clive/trunk 1234 into clive/objective/x (loop)", "2" * 40, "8" * 40),
        commit("4" * 40, loop, "3" * 40, "f" * 40),                 # the loop's words, other parents
        commit("5" * 40, loop + " and more", "4" * 40, "f" * 40),
        commit("a" * 40, "Seven fixes from the review (PR #95)", "5" * 40),
        commit("6" * 40, loop, "a" * 40, "f" * 40),                 # the loop's own: hidden
        commit("c" * 40, "Deploy now on the Builds screen (PR #112)", "6" * 40)]
    found = Trunk(sha="c" * 40)
    offer.compare(found, {"status": "ahead", "ahead_by": 8, "commits": pushed})
    assert found.changes == ["Deploy now on the Builds screen", "Seven fixes from the review",
                             loop + " and more", loop, "Merge clive/trunk 1234 into clive/objective/x (loop)",
                             "Merge remote-tracking branch 'origin/clive/trunk' into clive/trunk",
                             "Merge branch 'quick-fix' into clive/trunk"]
    assert found.count == 8
    # The shape matched is the one the loop writes (app/orchestrator/dispatcher.py, its refresh merge).
    source = (ROOT / "app" / "orchestrator" / "dispatcher.py").read_text()
    assert 'f"Merge {TRUNK_BRANCH} {task.base_sha} into {task.target_branch} at {source} (loop)' in source
    assert '"-p", source, "-p", task.base_sha' in source


def test_the_card_lists_every_commit_the_deploy_brings_in_on_a_range_like_the_real_one():
    """The re-review's finding B, on a range shaped like b33ccbc2..6f844183: objectives land as the loop's
    refresh merges, fast-forward, and the pull requests merged meanwhile come in through those merges'
    second parents, off the first-parent line. Every one is listed; only the exact refresh merges are not,
    and the headline and "and N more" count the list."""
    def commit(sha, message, *parents):
        return {"sha": sha, "commit": {"message": message}, "parents": [{"sha": p} for p in parents]}

    def refresh(sha, trunk, objective, source):
        return commit(sha, f"Merge clive/trunk {trunk} into clive/objective/{objective} at {source} (loop)\n\nThe "
                           "loop's refresh before landing", source, trunk)

    sha = {name: (str(i) * 40 if i < 10 else chr(87 + i) * 40) for i, name in enumerate(
        ["pr100a", "t100", "obj1", "r1", "pr101a", "pr101b", "t101", "obj2a", "obj2b", "r2", "pr110a", "t110"], start=1)}
    # GitHub's comparison lists them oldest first.
    commits = [
        commit(sha["pr100a"], "This repository is CLIVE only: the theme moves out", LIVE),
        commit(sha["t100"], "This repository is CLIVE only (PR #100)", LIVE, sha["pr100a"]),
        commit(sha["obj1"], "Deflake the reply turn's enrichment", LIVE),
        refresh(sha["r1"], sha["t100"], "deflake-reply-turn-enrichment", sha["obj1"]),
        commit(sha["pr101a"], "The release service, off and in dry run", sha["t100"]),
        commit(sha["pr101b"], "Seven fixes from the review", sha["pr101a"]),
        commit(sha["t101"], "The release service (PR #101)", sha["t100"], sha["pr101b"]),
        commit(sha["obj2a"], "Days left count London's day", sha["obj1"]),
        commit(sha["obj2b"], "Days left: the test for midnight", sha["obj2a"]),
        refresh(sha["r2"], sha["t101"], "days-left-london", sha["obj2b"]),
        commit(sha["pr110a"], "Research on the Builds screen", sha["r2"]),
        commit(sha["t110"], "Give CLIVE research (PR #110)", sha["r2"], sha["pr110a"]),
    ]
    green = GateResult(sha["t110"], GateState.GREEN, "acceptance run(s) 77 completed with success",
                       (RunFact(77, "completed", "success"),))
    found = Trunk(sha=sha["t110"], ahead=True, acceptance=green)
    offer.compare(found, {"status": "ahead", "ahead_by": len(commits), "files": [{"filename": "crooks-assistant/a.py"}],
                          "commits": commits})
    assert found.changes == ["Give CLIVE research", "Research on the Builds screen", "Days left: the test for midnight",
                             "Days left count London's day", "The release service", "Seven fixes from the review",
                             "The release service, off and in dry run", "Deflake the reply turn's enrichment",
                             "This repository is CLIVE only", "This repository is CLIVE only: the theme moves out"]
    assert (found.count, found.hidden, found.unlisted) == (12, 2, 0)
    assert len(found.changes) + found.hidden == found.count, "every commit is listed or counted as a refresh merge"
    assert found.title == "Give CLIVE research"
    card = offer.offer(found, live=LIVE, release=READY)
    assert card["changes"] == found.changes[:8] and (card["count"], card["more"], card["hidden"]) == (10, 2, 2)
    # The head itself a refresh merge (an objective that landed last): titled by the newest change, not the merge.
    landed = Trunk(sha=sha["r2"], ahead=True)
    offer.compare(landed, {"status": "ahead", "ahead_by": 10, "commits": commits[:10]})
    assert landed.title == "Days left: the test for midnight" and "The release service" in landed.changes
    # GitHub listed only part (it stops at 250): the rest is counted, never dropped from the headline.
    part = Trunk(sha=sha["t110"], ahead=True, acceptance=green)
    offer.compare(part, {"status": "ahead", "ahead_by": 14, "commits": commits})
    shown = offer.offer(part, live=LIVE, release=READY)
    assert (part.unlisted, shown["count"], shown["more"], shown["unlisted"]) == (2, 12, 4, 2)


def test_progress_follows_his_approval_stage_by_stage_then_kept():
    release = {**READY, "deploy": None}
    mine = _approval("a" * 32)
    waiting = offer.progress(mine, release, kept=None, process_sha=LIVE, now=_epoch("2026-10-08T01:00:05Z"))
    assert waiting["line"] == "Approved. Starting the release service…" and not waiting["final"]
    slow = offer.progress(mine, release, kept=None, process_sha=LIVE, now=_epoch("2026-10-08T01:02:00Z"))
    assert "within five minutes" in slow["line"]
    gone = offer.progress(mine, release, kept=None, process_sha=LIVE, now=_epoch("2026-10-08T01:11:00Z"))
    assert gone["end"] == "expired" and gone["final"] and "Nothing was deployed" in gone["line"]
    steps = [("started", "2026-10-08T01:00:10Z"), ("checks", "2026-10-08T01:00:11Z")]
    record = status.deploy_of(state.deploy_record(sha=TRUNK, title=TITLE, approval="a" * 32, steps=steps))
    running = offer.progress(mine, {**release, "deploy": record}, kept=None, process_sha=LIVE,
                             now=_epoch("2026-10-08T01:00:20Z"))
    assert [s["state"] for s in running["stages"]] == ["lit", "now", "dim", "dim", "dim", "dim"]
    assert running["line"] == "Checking production before anything changes…"
    steps += [("installing", "2026-10-08T01:00:30Z"), ("health", "2026-10-08T01:01:30Z"),
              ("done", "2026-10-08T01:02:00Z")]
    record = status.deploy_of(state.deploy_record(sha=TRUNK, title=TITLE, approval="a" * 32, steps=steps, end="done"))
    old = offer.progress(mine, {**release, "deploy": record}, kept=None, process_sha=LIVE, now=_epoch("2026-10-08T01:03:00Z"))
    assert old["line"] == "Deployed. CLIVE is restarting onto the new build…" and not old["keep_check"]
    new = offer.progress(mine, {**release, "deploy": record}, kept=None, process_sha=TRUNK, now=_epoch("2026-10-08T01:03:00Z"))
    assert new["keep_check"] and [s["state"] for s in new["stages"]][-2:] == ["lit", "now"]
    kept = offer.progress(mine, {**release, "deploy": record},
                          kept={"kept_at": "2026-10-08T01:03:10Z", "approval": "a" * 32},
                          process_sha=TRUNK, now=_epoch("2026-10-08T01:04:00Z"))
    assert kept["final"] and kept["line"] == "Deployed and kept: your phone got through on the new build."
    assert [s["state"] for s in kept["stages"]] == ["lit"] * 6
    # Someone else's deploy on the status is not his approval's progress.
    other = offer.progress(_approval("b" * 32), {**release, "deploy": record}, kept=None, process_sha=TRUNK,
                           now=_epoch("2026-10-08T01:00:05Z"))
    assert other["line"] == "Approved. Starting the release service…"


def test_kept_is_this_deploys_never_an_earlier_deploy_of_the_same_version(monkeypatch, tmp_path):
    """Review note 3: approval A deployed and kept TRUNK; production went back by hand; approval B
    deployed TRUNK again. A's kept record must not make B's deploy "Deployed and kept"."""
    steps = [("started", "2026-10-08T02:00:10Z"), ("checks", "2026-10-08T02:00:11Z"),
             ("installing", "2026-10-08T02:00:30Z"), ("health", "2026-10-08T02:01:30Z"), ("done", "2026-10-08T02:02:00Z")]
    record = status.deploy_of(state.deploy_record(sha=TRUNK, title=TITLE, approval="b" * 32, steps=steps, end="done"))
    release = {**READY, "state": "deployed", "deploy": record}
    earlier = {"sha": TRUNK, "approval": "a" * 32, "kept_at": "2026-10-08T01:03:10Z", "check": "ab12cd34"}
    shown = offer.progress(_approval("b" * 32, "2026-10-08T02:00:00Z"), release, kept=earlier, process_sha=TRUNK,
                           now=_epoch("2026-10-08T02:03:00Z"))
    assert shown["final"] is False and shown["keep_check"] is True and shown["kept_at"] == ""
    assert shown["line"] == "Deployed. Checking that your phone gets through on the new build…"
    assert [s["state"] for s in shown["stages"]][-1] == "now"
    # His phone's check after THIS deploy is recorded with B, and that keeps it.
    monkeypatch.setattr(approve, "journal_has", lambda line, since: since == _epoch("2026-10-08T02:02:00Z"))
    kept = approve.keep(TRUNK, "cd34ab12", process_sha=TRUNK, release=release, folder=tmp_path, now=_epoch(
        "2026-10-08T02:03:05Z"))
    assert kept["approval"] == "b" * 32 and approve.kept_record(tmp_path, TRUNK)["approval"] == "b" * 32
    shown = offer.progress(_approval("b" * 32, "2026-10-08T02:00:00Z"), release,
                           kept=approve.kept_record(tmp_path, TRUNK), process_sha=TRUNK, now=_epoch("2026-10-08T02:04:00Z"))
    assert shown["final"] and shown["line"] == "Deployed and kept: your phone got through on the new build."


@pytest.mark.parametrize("deploy,process,said,end", [
    (("", "done", "2026-10-08T01:20:00Z"), LIVE,
     "Your approval has expired. The release service's record shows this version deployed at 01:20 UTC, not on this "
     "approval.", "lapsed"),
    (("", "rolled_back", "2026-10-08T01:20:00Z"), LIVE,
     "Your approval has expired. The release service's record shows this version tried at 01:20 UTC and rolled back "
     "(/health after is not well), not on this approval.", "lapsed"),
    ((OTHER, "done", "2026-10-08T01:20:00Z"), LIVE,
     "Your approval has expired. The release service's latest record is of another version, 33333333: deployed at "
     "01:20 UTC.", "lapsed"),
    (None, TRUNK, "Your approval expired before the release service started it (an approval lasts ten "
     "minutes). CLIVE runs this version now all the same: it was deployed another way.", "lapsed"),
    (("", "done", "2026-10-08T00:30:00Z"), LIVE, "Your approval expired before the release service started it "
     "(an approval lasts ten minutes). Nothing was deployed.", "expired"),
    (None, LIVE, "Your approval expired before the release service started it (an approval lasts ten "
     "minutes). Nothing was deployed.", "expired"),
])
def test_an_expired_approval_says_what_the_services_record_shows(deploy, process, said, end):
    """Review note 3: a host waiver may deploy the version after his approval expired; the card then says
    what the release service's record shows, never "Nothing was deployed"."""
    release = {**READY, "state": "waiting", "at": "2026-10-08T00:55:00Z"}
    if deploy is not None:
        sha, how, at = deploy
        steps = [("started", at), ("checks", at), ("installing", at), ("health", at), (how, at)]
        release = {**release, "state": "deployed" if how == "done" else "rolled_back", "sha": sha or TRUNK,
                   "deploy": status.deploy_of(state.deploy_record(
                       sha=sha or TRUNK, title=TITLE, approval="", steps=steps, end=how,
                       reason="" if how == "done" else "/health after is not well"))}
    shown = offer.progress(_approval("a" * 32), release, kept=None, process_sha=process,
                           now=_epoch("2026-10-08T01:30:00Z"))
    assert (shown["end"], shown["line"], shown["final"]) == (end, said, True)
    assert ("Nothing was deployed" in shown["line"]) is (end == "expired")
    # The service's status unreadable: no record to go on, so no "Nothing was deployed" either.
    unread = offer.progress(_approval("a" * 32), {**READY, "state": "", "line": status.UNREADABLE, "deploy": None},
                            kept=None, process_sha=LIVE, now=_epoch("2026-10-08T01:30:00Z"))
    assert (unread["end"], unread["line"]) == ("lapsed", f"{offer.EXPIRED} {status.UNREADABLE}")


# ------------------------------------------------------------------ CLIVE's half: the routes


class Reader:
    def __init__(self, found: Trunk) -> None:
        self.found = found
        self.asked = 0

    async def read(self, live):
        self.asked += 1
        return self.found


@pytest.fixture
def deploy_world(world, tmp_path, monkeypatch):  # noqa: F811 - fixtures imported from the suite they belong to
    """The owner's CLIVE on LIVE, the trunk's head ahead and green, the release service installed, on,
    under owner_waiver and waiting only for his approval."""
    world.runtime.settings = world.runtime.settings.model_copy(update={"objectives_dir": tmp_path / "objectives"})
    monkeypatch.setattr(engineering_tools, "running_sha", lambda root=None: LIVE)
    monkeypatch.setattr(release_route, "PROCESS_SHA", LIVE)
    monkeypatch.setenv("CLIVE_RELEASE_STATE_DIR", str(tmp_path / "release"))
    reader = Reader(_trunk())
    offer.bind(reader)
    approve.reset()
    _write_status(tmp_path / "release", READY)
    world.reader = reader
    world.waivers = tmp_path / "objectives" / approve.WAIVERS
    world.kept = tmp_path / "objectives" / approve.KEPT
    world.release = tmp_path / "release"
    yield world
    offer.bind(None)
    approve.reset()


def _write_status(folder: Path, release: dict, deploy: dict | None = None) -> None:
    from app.release.host import SystemHost

    state.write_status(SystemHost(), folder, state=release["state"] or "waiting", line=release["line"],
                       at=release["at"], mode=release["mode"] or "live", sha=release["sha"], title=release["title"],
                       rule=release["rule"], ready_for=release["ready_for"], deploy=deploy)


async def _approve(http, sha=TRUNK, mode="live"):
    """His hold, as the page sends it: the version, and the mode its button said (web/deploy.js)."""
    asked = await http.post("/release/deploy/challenge", json={"sha": sha, "mode": mode}, headers=HEADERS)
    assert asked.status_code == 200, asked.text
    answer = http.device.get(asked.json()["publicKey"])
    return asked.json(), answer


async def test_the_owner_approves_with_his_passkey_and_the_release_service_deploys_exactly_that(
        deploy_world, server, tmp_path):  # noqa: F811 - fixtures imported from the suite they belong to
    http = deploy_world
    await register(http)
    shown = await http.get("/release/deploy", headers=PROXIED)
    assert shown.status_code == 200 and shown.headers["cache-control"] == "no-store"
    card = shown.json()["offer"]
    assert card["sha"] == TRUNK and card["hold"]["can"] and card["changes"][0] == TITLE
    asked, answer = await _approve(http)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", asked["expires_at"])
    done = await http.post("/release/deploy", json={"sha": TRUNK, "ticket": asked["ticket"], "approval": answer},
                           headers=HEADERS)
    assert done.status_code == 200, done.text
    assert done.json()["progress"]["line"] == "Approved. Starting the release service…"
    waiver = json.loads((http.waivers / f"{TRUNK}.json").read_text())
    assert waiver["given_by"] == "the owner" and waiver["words"] == "" and "owner@example.com" not in json.dumps(waiver)
    assert os.stat(http.waivers / f"{TRUNK}.json").st_mode & 0o077 == 0
    # The release service, on its own, believes exactly that approval for exactly that SHA.
    settings, fake, host = server
    settings.passkey_waivers_dir = http.waivers
    settings.passkeys_file = passkeys._path()
    host.clock = datetime.now(UTC)
    code, printed = _tick(settings, host)
    assert code == 0 and fake.head == TRUNK, printed
    assert _status(settings)["deploy"]["approval"] == done.json()["approved"]["approval"]
    # Copied to another SHA's name and rewritten to say it: deploys nothing.
    fake.head, fake.trunk = LIVE, OTHER
    fake.titles[OTHER] = "Another version"
    forged = {**waiver, "sha": OTHER}
    (http.waivers / f"{OTHER}.json").write_text(json.dumps(forged))
    host.calls.clear()
    _tick(settings, host)
    assert [s for s in host.steps if s in MUTATING] == [] and fake.head == LIVE
    assert "other than deploying this exact SHA" in _status(settings)["line"]


async def test_a_hold_given_to_try_it_in_dry_run_is_signed_so_and_never_deploys_for_real(
        deploy_world, server, tmp_path):  # noqa: F811 - fixtures imported from the suite they belong to
    """Review note 1, the mode bound into the challenge: the card said "Hold to try it (dry run)"; root
    switches dry run off before any tick has answered it (so nothing has marked it used): it deploys nothing."""
    http = deploy_world
    await register(http)
    _write_status(http.release, {**READY, "mode": "dry_run"})
    shown = (await http.get("/release/deploy", headers=PROXIED)).json()["offer"]["hold"]
    assert shown["label"] == "Hold to try it (dry run)" and shown["can"]
    asked, answer = await _approve(http, mode="dry_run")
    done = await http.post("/release/deploy", json={"sha": TRUNK, "ticket": asked["ticket"], "approval": answer},
                           headers=HEADERS)
    assert done.status_code == 200, done.text
    assert json.loads((http.waivers / f"{TRUNK}.json").read_text())["passkey"]["mode"] == "dry_run"
    settings, fake, host = server
    settings.passkey_waivers_dir = http.waivers
    settings.passkeys_file = passkeys._path()
    host.clock = datetime.now(UTC)
    settings.dry_run = False                                  # switched off before any tick answered it
    code, printed = _tick(settings, host)
    assert [s for s in host.steps if s in MUTATING] == [] and fake.head == LIVE, printed
    assert "it was given only to try it in dry run" in _status(settings)["line"], _status(settings)["line"]
    # Rewritten after the tap to say it was given to deploy: the signature is over the dry-run challenge.
    path = http.waivers / f"{TRUNK}.json"
    forged = json.loads(path.read_text())
    forged["passkey"]["mode"] = "live"
    path.write_text(json.dumps(forged))
    host.calls.clear()
    _tick(settings, host)
    assert [s for s in host.steps if s in MUTATING] == [] and fake.head == LIVE
    assert "other than deploying this exact SHA" in _status(settings)["line"]
    # In dry run, the same hold is answered as what it was: tried, nothing changed, and spent.
    forged["passkey"]["mode"] = "dry_run"
    path.write_text(json.dumps(forged))
    settings.dry_run = True
    host.calls.clear()
    _tick(settings, host)
    assert [s for s in host.steps if s in MUTATING] == [] and _status(settings)["deploy"]["end"] == "dry_run"


def test_a_waiver_that_does_not_say_its_mode_deploys_nothing(server, tmp_path):  # noqa: F811 - fixtures imported from the suite they belong to
    settings, fake, host = server
    _passkey_waiver(settings, _register(tmp_path))
    path = settings.passkey_waivers_dir / f"{TRUNK}.json"
    record = json.loads(path.read_text())
    del record["passkey"]["mode"]
    path.write_text(json.dumps(record))
    _tick(settings, host)
    assert [s for s in host.steps if s in MUTATING] == [] and fake.head == LIVE
    assert "whether it was given to deploy or only to try it" in _status(settings)["line"]


async def test_a_stale_dry_run_button_is_never_signed_as_a_deploy(deploy_world, server, tmp_path):  # noqa: F811 - fixtures imported from the suite they belong to
    """The re-review's finding A, its sequence through the routes: his card says "Hold to try it (dry run)";
    dry run is switched off and a tick writes mode live; he holds the card he still sees. Nothing is asked
    for, nothing is written, nothing deploys; the card read again says "Hold to deploy"."""
    http = deploy_world
    await register(http)
    _write_status(http.release, {**READY, "mode": "dry_run"})
    seen = (await http.get("/release/deploy", headers=PROXIED)).json()["offer"]["hold"]
    assert seen["label"] == "Hold to try it (dry run)"
    _write_status(http.release, {**READY, "mode": "live"})          # dry run off, and a tick has said so
    held = await http.post("/release/deploy/challenge", json={"sha": TRUNK, "mode": "dry_run"}, headers=HEADERS)
    assert held.status_code == 409 and held.json()["code"] == "mode_changed", held.text
    assert held.json()["detail"] == release_route.MODE_CHANGED["live"]
    assert "publicKey" not in held.json() and "ticket" not in held.json()
    # A page that says nothing of its mode is not taken at its word either.
    unsaid = await http.post("/release/deploy/challenge", json={"sha": TRUNK}, headers=HEADERS)
    assert unsaid.status_code == 409 and unsaid.json()["code"] == "mode_changed"
    assert not http.waivers.exists() or not list(http.waivers.iterdir()), "nothing written"
    settings, fake, host = server
    settings.passkey_waivers_dir = http.waivers
    settings.passkeys_file = passkeys._path()
    host.clock = datetime.now(UTC)
    _tick(settings, host)
    assert [s for s in host.steps if s in MUTATING] == [] and fake.head == LIVE
    # The card read again says what his hold does now; held as shown, it is signed as shown.
    again = (await http.get("/release/deploy", headers=PROXIED)).json()["offer"]["hold"]
    assert again["label"] == "Hold to deploy" and again["dry_run"] is False
    asked, answer = await _approve(http, mode="live")
    done = await http.post("/release/deploy", json={"sha": TRUNK, "ticket": asked["ticket"], "approval": answer},
                           headers=HEADERS)
    assert done.status_code == 200
    assert json.loads((http.waivers / f"{TRUNK}.json").read_text())["passkey"]["mode"] == "live"
    # And the other way: dry run switched on under a "Hold to deploy" button.
    _write_status(http.release, {**READY, "mode": "dry_run"})
    flipped = await http.post("/release/deploy/challenge", json={"sha": TRUNK, "mode": "live"}, headers=HEADERS)
    assert flipped.status_code == 409 and flipped.json()["detail"] == release_route.MODE_CHANGED["dry_run"]


async def test_a_used_expired_or_other_challenge_is_refused_and_writes_nothing(deploy_world, monkeypatch):
    http = deploy_world
    await register(http)
    asked, answer = await _approve(http)
    done = await http.post("/release/deploy", json={"sha": TRUNK, "ticket": asked["ticket"], "approval": answer},
                           headers=HEADERS)
    assert done.status_code == 200
    (http.waivers / f"{TRUNK}.json").unlink()
    again = await http.post("/release/deploy", json={"sha": TRUNK, "ticket": asked["ticket"], "approval": answer},
                            headers=HEADERS)
    assert again.status_code == 409 and again.json()["code"] == "approval_stale"
    # Asked for TRUNK, answered as if for OTHER.
    asked, answer = await _approve(http)
    other = await http.post("/release/deploy", json={"sha": OTHER, "ticket": asked["ticket"], "approval": answer},
                            headers=HEADERS)
    assert other.status_code == 409 and other.json()["code"] == "approval_other"
    # Asked, then left past its life.
    asked, answer = await _approve(http)
    import time as clock

    later = clock.time() + authority.APPROVAL_TTL_S + 5
    monkeypatch.setattr(release_route.time, "time", lambda: later)
    late = await http.post("/release/deploy", json={"sha": TRUNK, "ticket": asked["ticket"], "approval": answer},
                           headers=HEADERS)
    assert late.status_code == 409 and late.json()["code"] == "approval_expired"
    assert not (http.waivers / f"{TRUNK}.json").exists(), "nothing written for a refused approval"


async def test_his_hold_is_refused_when_it_cannot_deploy_or_the_trunk_moved_on(deploy_world):
    http = deploy_world
    await register(http)
    moved = await http.post("/release/deploy/challenge", json={"sha": OTHER}, headers=HEADERS)
    assert moved.status_code == 409 and moved.json()["code"] == "moved_on"
    _write_status(http.release, {**READY, "state": "off", "line": "The release service is off."})
    off = await http.post("/release/deploy/challenge", json={"sha": TRUNK}, headers=HEADERS)
    assert off.status_code == 409 and "switched off" in off.json()["detail"]
    shutil.rmtree(http.release)
    gone = await http.post("/release/deploy/challenge", json={"sha": TRUNK}, headers=HEADERS)
    assert gone.status_code == 409 and "isn't installed" in gone.json()["detail"]
    assert http.reader.asked >= 3, "each hold reads the trunk again"
    # From the server itself, or from another site, nothing is asked for.
    assert (await http.post("/release/deploy/challenge", json={"sha": TRUNK})).status_code == 403
    wrong = {**HEADERS, "Origin": "https://evil.example"}
    assert (await http.post("/release/deploy/challenge", json={"sha": TRUNK}, headers=wrong)).status_code == 403


async def test_kept_only_once_his_phones_line_is_in_the_journal_on_the_new_build(deploy_world, monkeypatch):
    http = deploy_world
    await register(http)
    asked, answer = await _approve(http)
    done = await http.post("/release/deploy", json={"sha": TRUNK, "ticket": asked["ticket"], "approval": answer},
                           headers=HEADERS)
    approval = done.json()["approved"]["approval"]
    steps = [("started", "2026-10-08T01:00:10Z"), ("checks", "2026-10-08T01:00:11Z"),
             ("installing", "2026-10-08T01:00:30Z"), ("health", "2026-10-08T01:01:30Z"), ("done", "2026-10-08T01:02:00Z")]
    _write_status(http.release, {**READY, "state": "deployed", "line": "Deployed “X”. Open /whoami on your phone to "
                                 "keep it.", "ready_for": ""},
                  deploy=state.deploy_record(sha=TRUNK, title=TITLE, approval=approval, steps=steps, end="done"))
    asked_journal: list[tuple[str, float]] = []
    seen = {"line": False}

    def journal(line, since):
        asked_journal.append((line, since))
        return seen["line"]

    monkeypatch.setattr(approve, "journal_has", journal)
    old = await http.post("/release/kept", json={"sha": TRUNK, "check": "ab12cd34"}, headers=HEADERS)
    assert old.status_code == 409 and old.json()["code"] == "not_this_build", "the build it replaced cannot keep it"
    monkeypatch.setattr(release_route, "PROCESS_SHA", TRUNK)
    asked_github = http.reader.asked
    shown = (await http.get("/release/deploy?progress=1", headers=PROXIED)).json()
    assert shown["progress"]["keep_check"] is True and shown["offer"] is None
    assert http.reader.asked == asked_github, "while a deploy runs, the page's asks never reach GitHub"
    early = await http.post("/release/kept", json={"sha": TRUNK, "check": "ab12cd34"}, headers=HEADERS)
    assert early.status_code == 409 and early.json()["code"] == "not_in_journal"
    assert asked_journal[-1] == ("whoami: id=ab12cd34 through=tailscale owner=true refusal=none",
                                 _epoch("2026-10-08T01:02:00Z"))
    seen["line"] = True
    kept = await http.post("/release/kept", json={"sha": TRUNK, "check": "ab12cd34"}, headers=HEADERS)
    assert kept.status_code == 200, kept.text
    assert kept.json()["progress"]["line"] == "Deployed and kept: your phone got through on the new build."
    assert json.loads((http.kept / f"{TRUNK}.json").read_text())["check"] == "ab12cd34"
    bad = await http.post("/release/kept", json={"sha": TRUNK, "check": "not-a-check"}, headers=HEADERS)
    assert bad.status_code == 400


def test_the_journal_line_must_be_exactly_the_procedures(monkeypatch):
    class Done:
        returncode = 0
        stdout = ("INFO crooks.identity whoami: id=ab12cd34 through=tailscale owner=true refusal=none_x\n"
                  "INFO crooks.identity whoami: id=ab12cd34 through=this_host owner=false refusal=not_authorised_local\n")

    monkeypatch.setattr(approve.subprocess, "run", lambda *a, **k: Done())
    assert approve.journal_has(approve.whoami_line("ab12cd34"), 0) is False
    Done.stdout += "INFO crooks.identity whoami: id=ab12cd34 through=tailscale owner=true refusal=none\n"
    assert approve.journal_has(approve.whoami_line("ab12cd34"), 0) is True
    Done.returncode = 1
    assert approve.journal_has(approve.whoami_line("ab12cd34"), 0) is None, "unreadable is never a yes"


async def test_the_team_never_see_or_use_deploy_now(team):  # noqa: F811 - fixtures imported from the suite they belong to
    let_mia_in()
    assert (await team.get("/today/state", headers=AS_MIA)).status_code == 200, "she is let in"
    for method, path in (("GET", "/release/deploy"), ("GET", "/release/deploy?progress=1"),
                         ("POST", "/release/deploy/challenge"), ("POST", "/release/deploy"), ("POST", "/release/kept")):
        response = await team.request(method, path, headers=AS_MIA, json={"sha": TRUNK})
        assert response.status_code == 403, (method, path, response.status_code)
        assert TRUNK not in response.text


def test_the_server_and_its_new_files_hold_no_secret_and_no_login():
    for name in ("clive-release-now.path",):
        text = (ROOT / "deploy" / "release" / name).read_text()
        assert "github_pat_" not in text and "@" not in text
    source = (ROOT / "app" / "release" / "approve.py").read_text()
    assert 'GIVEN_BY = "the owner"' in source


def test_the_card_under_node():
    """web/deploy.js with the page's own code (tests/web/deploy.test.js)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed here")
    result = subprocess.run([node, "--test", str(ROOT / "tests" / "web" / "deploy.test.js")], capture_output=True,
                            text=True, timeout=120, cwd=ROOT)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout and "# skipped 0" in result.stdout


@pytest.fixture(autouse=True)
def _fresh_challenges():
    approve.reset()
    yield
    approve.reset()
