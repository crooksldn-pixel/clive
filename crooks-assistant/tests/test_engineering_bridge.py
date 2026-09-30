"""CLIVE files an engineering objective into the remote engineering loop and says how it is
going. GitHub is faked in memory (httpx.MockTransport); nothing here touches the network."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import UTC, datetime

import httpx
import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.ledger import NullLedger
from app.actions.models import ActionStatus
from app.engineering_bridge import github
from app.engineering_bridge.github import (
    INBOX_BRANCH,
    Created,
    EngineeringInbox,
    GitHubError,
    NotConnected,
    Refused,
)
from app.engineering_bridge.requests import RequestRefused, build_request
from app.orchestrator.objectives import PROTECTED_PATHS, Objective, OwnerEntry
from app.reads import dedupe
from app.remote_engineering.requests import parse_request
from app.secrets import keychain
from app.session.models import Session
from app.tools import engineering_tools, registry
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from app.tools.registry import ToolError
from tests.fake_credentials import github_token

TOKEN = github_token("engineering-bridge")
REPO = "crooksldn-pixel/clive"
HEAD = "1" * 40
BASE_SHA = "a" * 40
MARK = "SECRETMARK9"
STATUS_TOOL = "engineering_status"
SUBMIT_TOOL = "submit_engineering_request"
PATH = "requests/bridge-demo-one.json"


def ask(**overrides) -> dict:
    """What the model may say: never a base and never checks (the 2026-09-26 deploy review,
    F-06). Those are the Mac's own."""
    out = {k: v for k, v in fields(**overrides).items() if k not in ("base_ref", "base_sha", "checks")}
    return out


def served(request_id: str = "bridge-demo-one"):
    """The exact request the tool files for ask(request_id=…): the trunk's head as its base, and
    the checks the tool builds itself."""
    a = ask(request_id=request_id)
    paths, checks, added = engineering_tools.default_checks(
        [engineering_tools.repo_path(p) for p in a["allowed_paths"]], request_id)
    return build_request(
        request_id=request_id, title=a["title"], requested_outcome=a["requested_outcome"], base_ref=BASE_SHA,
        base_sha=BASE_SHA, allowed_paths=paths, checks=checks, max_repair_rounds=a["max_repair_rounds"],
        acceptance_criteria=[*a["acceptance_criteria"], f"The change is proven by tests in {added}, and they pass."],
    )


def fields(**overrides) -> dict:
    base = {
        "request_id": "bridge-demo-one",
        "title": "Say which engineering requests are waiting",
        "requested_outcome": "The status card lists every request that is waiting, in plain words.",
        "base_ref": "main",
        "base_sha": BASE_SHA,
        # An ordinary part of CLIVE: the bridge itself is protected (F-ENG), so no request names it.
        "allowed_paths": ["crooks-assistant/app/objectives"],
        "acceptance_criteria": ["the status card lists waiting requests"],
        "checks": [{"name": "bridge", "argv": ["python", "-m", "pytest", "-q"], "cwd": "crooks-assistant"}],
        "max_repair_rounds": 2,
    }
    base.update(overrides)
    return base


class FakeGitHub:
    """The loop's two branches, in memory, behind the REST contents API's shape."""

    def __init__(self) -> None:
        self.head: str | None = HEAD
        self.status: dict | None = {"generated_at": "2026-09-25T10:00:00+00:00", "adapter": {"intake_error": None}, "requests": []}
        self.files: dict[str, bytes] = {}
        self.calls: list[httpx.Request] = []
        self.puts: list[dict] = []
        self.race: bytes | None = None       # a file that lands between the look and the write
        self.fail_with: int | None = None    # every call answers with this status
        self.commits = 0

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def commit(self) -> str:
        self.commits += 1
        self.head = hashlib.sha1(f"commit {self.commits}".encode()).hexdigest()
        return self.head

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.fail_with is not None:
            # GitHub's own words may say anything, the token included; none of it may travel.
            return httpx.Response(self.fail_with, json={"message": f"no: {TOKEN}"})
        prefix = f"/repos/{REPO}"
        assert request.url.path.startswith(prefix), request.url.path
        path = request.url.path[len(prefix):]
        ref = request.url.params.get("ref")
        if request.method == "GET" and path == "/git/ref/heads/clive/trunk":
            return httpx.Response(200, json={"ref": "refs/heads/clive/trunk", "object": {"type": "commit", "sha": BASE_SHA}})
        if request.method == "GET" and path == f"/git/ref/heads/{INBOX_BRANCH}":
            if self.head is None:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={"ref": f"refs/heads/{INBOX_BRANCH}", "object": {"type": "commit", "sha": self.head}})
        if path.startswith("/contents/"):
            name = path[len("/contents/"):]
            if request.method == "GET":
                if name == "status.json" and ref == "clive/control/status" and self.status is not None:
                    return self._file(name, json.dumps(self.status).encode())
                if ref == INBOX_BRANCH and name in self.files:
                    return self._file(name, self.files[name])
                return httpx.Response(404, json={"message": "Not Found"})
            if request.method == "PUT":
                body = json.loads(request.content)
                self.puts.append(body)
                if self.race is not None:
                    self.files[name] = self.race
                    self.commit()
                    return httpx.Response(409, json={"message": "conflict"})
                if name in self.files or "sha" in body or body.get("branch") != INBOX_BRANCH:
                    return httpx.Response(422, json={"message": "sha wasn't supplied"})
                self.files[name] = base64.b64decode(body["content"])
                sha = self.commit()
                return httpx.Response(201, json={"content": {"path": name}, "commit": {"sha": sha}})
        return httpx.Response(404, json={"message": "Not Found"})

    @staticmethod
    def _file(name: str, content: bytes) -> httpx.Response:
        return httpx.Response(200, json={
            "type": "file", "encoding": "base64", "path": name,
            "content": base64.encodebytes(content).decode("ascii"),
        })


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def fake() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture()
def inbox(fake) -> EngineeringInbox:
    return EngineeringInbox(REPO, token_source=lambda: TOKEN, transport=fake.transport())


@pytest.fixture()
def bound(inbox, monkeypatch) -> EngineeringInbox:
    monkeypatch.setattr(engineering_tools, "_inbox", inbox)
    return inbox


@pytest.fixture()
def clock() -> Clock:
    return Clock()


@pytest.fixture()
def engine(monkeypatch, clock) -> ActionEngine:
    fresh = ActionEngine(ledger=NullLedger(), clock=clock)
    monkeypatch.setattr(engine_module, "_engine", fresh)
    return fresh


async def _staged(session: Session) -> str:
    await dispatch(STATUS_TOOL, {}, session=session, timeout_s=5)
    return await dispatch(SUBMIT_TOOL, {"inbox_id": HEAD, **ask()}, session=session, timeout_s=5)


async def _authorise(engine: ActionEngine, clock: Clock, session: Session, proposal):
    armed, code = engine.arm(proposal.proposal_id, session.session_id)
    assert code == "", code
    clock.advance(1.0)   # the owner's hold
    return await engine.commit(
        proposal.proposal_id, session.session_id, caller="owner", spec_lookup=registry.get, nonce=armed.arm_nonce,
    )


# ------------------------------------------------------------------ the request


def test_a_built_request_passes_the_loops_own_intake():
    request = build_request(**fields())
    parsed = parse_request(request.content)
    assert parsed.request_id == "bridge-demo-one" and parsed.target_branch == "clive/objective/bridge-demo-one"
    assert request.path == PATH and request.content.endswith(b"\n")
    assert list(json.loads(request.content)) == [
        "schema_version", "request_id", "title", "requested_outcome", "base_ref", "base_sha",
        "allowed_paths", "acceptance_criteria", "checks", "target_branch", "max_repair_rounds",
    ]
    # And the objective door the loop then puts it through, PROTECTED_PATHS and all.
    Objective(
        objective_id=parsed.request_id, title=parsed.title, requested_outcome=parsed.requested_outcome,
        acceptance_criteria=parsed.acceptance_criteria, checks=parsed.checks, repository=REPO,
        base_ref=parsed.base_ref, base_sha=parsed.base_sha, target_branch=parsed.target_branch,
        product_memory_sha="b" * 40, allowed_paths=parsed.allowed_paths,
        max_repair_rounds=parsed.max_repair_rounds, owner=OwnerEntry(os_user="owner", host="mac"),
        created_at=datetime.now(UTC),
    )


def _rejected(value) -> list[str]:
    if isinstance(value, str):
        return [value] if len(value) >= 8 else []
    if isinstance(value, dict):
        return [s for v in value.values() for s in _rejected(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _rejected(v)]
    return []


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"request_id": f"Bad_{MARK}"}, "request_id"),
        ({"request_id": f"x-{MARK.lower()}-{'a' * 20}"}, "request_id"),
        ({"title": ""}, "title"),
        ({"title": MARK * 30}, "title"),
        ({"requested_outcome": MARK + "x" * 20000}, "requested_outcome"),
        ({"base_ref": f"main..{MARK}"}, "base_ref"),
        ({"base_sha": MARK}, "base_sha"),
        ({"base_sha": BASE_SHA.upper()}, "base_sha"),
        ({"allowed_paths": [f"/etc/{MARK}"]}, "allowed_paths"),
        ({"allowed_paths": [f"src/../{MARK}"]}, "allowed_paths"),
        ({"allowed_paths": [PROTECTED_PATHS[0]]}, "allowed_paths"),
        ({"allowed_paths": [f"{PROTECTED_PATHS[-1]}/{MARK}"]}, "allowed_paths"),
        ({"allowed_paths": []}, "allowed_paths"),
        ({"acceptance_criteria": ["   "]}, "acceptance_criteria"),
        ({"checks": [{"name": f"Bad {MARK}", "argv": ["x"]}]}, "checks"),
        ({"checks": [{"name": "ok", "argv": ["x"], "env": MARK}]}, "checks"),
        ({"checks": [{"name": "ok", "argv": ["x"], "cwd": f"../{MARK}"}]}, "checks"),
        ({"checks": [{"name": "ok", "argv": ["x"]}, {"name": "ok", "argv": ["y"]}]}, "checks"),
        ({"max_repair_rounds": 6}, "max_repair_rounds"),
        ({"max_repair_rounds": True}, "max_repair_rounds"),
    ],
)
def test_invalid_fields_are_refused_without_echo(override, field):
    with pytest.raises(RequestRefused) as refused:
        build_request(**fields(**override))
    message = str(refused.value)
    assert field in message and "Nothing was filed" in message
    assert MARK not in message
    for value in _rejected(override):
        assert value not in message


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_tool_refuses_a_bad_field_without_echo(fake, bound):
    session = Session(session_id="eng-bad")
    await dispatch(STATUS_TOOL, {}, session=session, timeout_s=5)
    out = await dispatch(SUBMIT_TOOL, {"inbox_id": HEAD, **ask(request_id=MARK)}, session=session, timeout_s=5)
    assert out.startswith("ERROR: The request was refused") and "request_id" in out
    assert MARK not in out and session.proposals == [] and fake.puts == []


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_a_caller_can_name_neither_its_base_nor_its_checks(fake, bound):
    """F-06: a request that chose its own checks would choose the gate it is judged by."""
    session = Session(session_id="eng-own-gate")
    await dispatch(STATUS_TOOL, {}, session=session, timeout_s=5)
    for extra in ({"checks": [{"name": "ok", "argv": ["true"], "cwd": "."}]}, {"base_sha": "b" * 40}, {"base_ref": "main"}):
        out = await dispatch(SUBMIT_TOOL, {"inbox_id": HEAD, **ask(), **extra}, session=session, timeout_s=5)
        assert out.startswith("REFUSED") and "does not take an argument" in out, out
    with pytest.raises(TypeError):
        await engineering_tools.submit_engineering_request(inbox_id=HEAD, **ask(), checks=[])
    assert session.proposals == [] and fake.puts == []
    # And what the tool builds names only real test modules, through fixed commands.
    paths, checks, _ = engineering_tools.default_checks(
        ["crooks-assistant/tests/test_ok.py", "crooks-assistant/tests/../x.py", "crooks-assistant/tests/test_$(x).py",
         "crooks-assistant/tests/web/ui.test.js", "crooks-assistant/app/fastpath"], "bridge-demo-one", python="/p")
    regression = {"name": "regression", "argv": ["/p", "-m", "pytest", "-q", "-m", "not live", *engineering_tools.REGRESSION_TESTS],
                  "cwd": "crooks-assistant"}
    assert checks == [
        {"name": "tests", "argv": ["/p", "-m", "pytest", "-q", "tests/test_ok.py"], "cwd": "crooks-assistant"},
        regression,
        {"name": "ruff", "argv": ["/p", "-m", "ruff", "check", "app", "config", "scripts", "tests"], "cwd": "crooks-assistant"},
    ]
    # F-06, second round: the regression check does not depend on what the request names.
    _, other, _ = engineering_tools.default_checks(["crooks-assistant/web/alpha.js"], "bridge-demo-two", python="/p")
    assert other[1] == regression
    from app.orchestrator.objectives import PROTECTED_PATHS

    assert all(f"crooks-assistant/{t}" in PROTECTED_PATHS for t in engineering_tools.REGRESSION_TESTS), \
        "every regression module is protected, so no build can weaken what judges it"


# ------------------------------------------------------------------ not connected


async def test_with_no_token_every_call_is_not_connected_and_nothing_is_sent(fake):
    inbox = EngineeringInbox(REPO, token_source=lambda: None, transport=fake.transport())
    results = [
        await inbox.status(), await inbox.inbox_head(), await inbox.request_file("bridge-demo-one"),
        await inbox.create_request("bridge-demo-one", b"{}\n"),
    ]
    assert all(isinstance(result, NotConnected) for result in results)
    assert inbox.requests_made == 0 and fake.calls == []


def test_the_token_is_read_from_the_secret_store_at_call_time(monkeypatch):
    asked: list[str] = []
    monkeypatch.setattr(keychain, "get_optional", lambda key: asked.append(key))
    assert github.read_token() is None and asked == [github.TOKEN_KEY]
    monkeypatch.setattr(keychain, "get_optional", lambda key: TOKEN if key == github.TOKEN_KEY else None)
    assert github.read_token() == TOKEN

    def unknown(key):
        raise ValueError("unknown secret key")

    # Not yet a key the store knows: that is "not connected", not a crash.
    monkeypatch.setattr(keychain, "get_optional", unknown)
    assert github.read_token() is None


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_tools_say_not_connected_and_send_nothing(fake, monkeypatch):
    inbox = EngineeringInbox(REPO, transport=fake.transport())   # the real token reader; no token
    monkeypatch.setattr(engineering_tools, "_inbox", inbox)
    session = Session(session_id="eng-off")
    out = await dispatch(STATUS_TOOL, {}, session=session, timeout_s=5)
    assert '"connected": false' in out and "not connected" in out
    assert HEAD not in session.issued_ids
    with pytest.raises(ToolError, match="not connected"):
        await engineering_tools.submit_engineering_request(inbox_id=HEAD, **ask())
    assert fake.calls == [] and inbox.requests_made == 0


# ------------------------------------------------------------------ create, never overwrite


async def test_the_request_file_is_created_only_when_absent(fake, inbox):
    request = build_request(**fields())
    created = await inbox.create_request(request.request_id, request.content)
    assert isinstance(created, Created) and created.path == PATH and created.commit_sha == fake.head
    assert fake.files[PATH] == request.content
    (put,) = fake.puts
    assert put["branch"] == INBOX_BRANCH and "sha" not in put, "a create, never an update"
    again = await inbox.create_request(request.request_id, b'{"other": true}\n')
    assert isinstance(again, Refused) and "nothing was overwritten" in again.reason
    assert fake.files[PATH] == request.content and len(fake.puts) == 1, "refused before any write"


async def test_a_conflict_is_read_again_and_refused(fake, inbox):
    request = build_request(**fields())
    fake.race = b'{"someone": "else"}\n'
    refused = await inbox.create_request(request.request_id, request.content)
    assert isinstance(refused, Refused) and "nothing was overwritten" in refused.reason
    assert fake.files[PATH] == fake.race, "what landed first is left exactly as it was"
    assert len(fake.puts) == 1 and fake.calls[-1].method == "GET", "read again, never retried or forced"


async def test_github_failures_are_fixed_words(fake, inbox):
    for code in (500, 401):
        fake.fail_with = code
        with pytest.raises(GitHubError) as failed:
            await inbox.inbox_head()
        assert f"HTTP {code}" in str(failed.value)
        assert TOKEN not in str(failed.value) and "no:" not in str(failed.value)


# ------------------------------------------------------------------ status in plain words


async def test_engineering_status_reports_each_request_in_plain_words(fake, bound):
    fake.status["requests"] = [
        {"request_id": "one-queued", "outcome": "accepted", "stage": "READY"},
        {"request_id": "two-building", "outcome": "accepted", "stage": "RUNNING"},
        {"request_id": "three-review", "outcome": "accepted", "stage": "REVIEWING",
         "review": {"verdicts": [{"verdict": "changes_requested"}]}},
        {"request_id": "four-done", "outcome": "accepted", "stage": "COMPLETE", "candidate_sha": "c" * 40},
        {"request_id": "five-blocked", "outcome": "accepted", "stage": "BLOCKED", "blocker": "check ruff failed"},
        {"request_id": "six-owner", "outcome": "accepted", "stage": "OWNER_GATE", "owner_gate": True,
         "blocker": "needs a credential"},
        {"request_id": "seven-refused", "outcome": "refused", "reason": "base ref does not resolve"},
    ]
    result = await engineering_tools.engineering_status()
    rows = {row["request_id"]: row for row in result["requests"]}
    assert [row["progress"] for row in result["requests"]] == [
        "queued", "building", "in review", "done", "blocked", "needs the owner", "blocked",
    ]
    assert rows["one-queued"]["words"] == "one-queued is queued; no builder has started it yet."
    assert rows["two-building"]["words"] == "two-building is being built."
    assert rows["three-review"]["words"] == "three-review is in review; the last verdict was changes_requested."
    assert rows["four-done"]["words"] == f"four-done is done: candidate {'c' * 40}."
    assert rows["four-done"]["candidate_sha"] == "c" * 40
    assert rows["five-blocked"]["words"] == "five-blocked is blocked: check ruff failed."
    assert rows["six-owner"]["words"] == "six-owner needs the owner: needs a credential."
    assert rows["seven-refused"]["words"] == "seven-refused is blocked: the loop refused it (base ref does not resolve)."
    assert all("candidate_sha" not in row for rid, row in rows.items() if rid != "four-done")
    assert result["summary"] == (
        "7 engineering requests: 1 queued, 1 building, 1 in review, 1 done, 2 blocked, 1 needs the owner."
    )
    assert result["inbox"]["id"] == HEAD and result["connected"] is True


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_engineering_status_reports_every_request_however_many(fake, bound):
    stages = ["READY", "RUNNING", "REVIEWING", "COMPLETE", "BLOCKED"]
    fake.status["requests"] = [
        {"request_id": f"many-r{n}", "outcome": "accepted", "stage": stages[n % len(stages)], "blocker": "waiting"}
        for n in range(45)
    ]
    result = await engineering_tools.engineering_status()
    assert [row["request_id"] for row in result["requests"]] == [f"many-r{n}" for n in range(45)], "none is dropped"
    assert result["summary"] == (
        "45 engineering requests: 9 queued, 9 building, 9 in review, 9 done, 9 blocked."
    )
    # And the answer the model is handed carries every one of them.
    text = await dispatch(STATUS_TOOL, {}, session=Session(session_id="eng-many"), timeout_s=5)
    assert all(f'"many-r{n}"' in text for n in range(45))


async def test_engineering_status_says_what_the_loop_has_not_published(fake, bound):
    fake.status = None
    result = await engineering_tools.engineering_status()
    assert result["summary"] == "The engineering loop has not published a status yet."
    assert result["requests"] == [] and result["inbox"]["id"] == HEAD
    fake.status = {"adapter": {"intake_error": "inbox fetch failed"}, "requests": []}
    result = await engineering_tools.engineering_status()
    assert "could not read its inbox last time: inbox fetch failed" in result["summary"]


# ------------------------------------------------------------------ the gate and the owner


def test_the_two_tools_are_registered_as_a_read_and_a_reviewed_write():
    status, submit = registry.get(STATUS_TOOL), registry.get(SUBMIT_TOOL)
    assert status.write is None and status.batch is None and status.tier is Tier.GREEN
    assert classify(STATUS_TOOL).disposition is Disposition.EXECUTE_NOW
    write = submit.write
    assert write is not None and write.complete and submit.tier is Tier.RED
    assert submit.issued_id_args == ("inbox_id",) and write.entity_arg == "inbox_id"
    assert write.interaction == "tap_commit" and write.kind == "irreversible" and not write.reversible


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_inbox_id_is_issued_by_the_read_and_the_write_is_staged_for_the_owner(fake, bound, engine, clock):
    session = Session(session_id="eng")
    args = {"inbox_id": HEAD, **ask()}
    early = classify(SUBMIT_TOOL, args, session.issued_ids)
    assert early.disposition is Disposition.DENY and early.recoverable, "read the inbox first"
    await dispatch(STATUS_TOOL, {}, session=session, timeout_s=5)
    assert HEAD in session.issued_ids
    decision = classify(SUBMIT_TOOL, args, session.issued_ids)
    assert decision.disposition is Disposition.STAGE_FOR_OWNER and decision.tier is Tier.RED

    text = await dispatch(SUBMIT_TOOL, args, session=session, timeout_s=5)
    assert text.startswith("PROPOSED (") and "NOT happened" in text
    assert fake.puts == [] and fake.files == {}, "staging files nothing"
    (proposal,) = session.proposals
    assert proposal.status is ActionStatus.PENDING and proposal.operation == "engineering_request_file"
    assert proposal.interaction == "hold_to_arm" and proposal.reversible is False

    card = registry.get(SUBMIT_TOOL).write.present(proposal)
    facts = {fact["label"]: fact["value"] for fact in card["facts"]}
    assert facts["Title"] == "Say which engineering requests are waiting"
    # The paths asked for, and the test module the build must write, which its check runs.
    assert facts["May change"] == "crooks-assistant/app/objectives, crooks-assistant/tests/test_bridge_demo_one.py"
    py = engineering_tools._check_python
    assert facts["Checks"] == "; ".join(f"{c['name']}: {' '.join(c['argv'])} (in {c['cwd']})" for c in served().record["checks"])
    assert facts["Checks"].startswith(f"tests: {py} -m pytest -q tests/test_bridge_demo_one.py (in crooks-assistant); regression: ")
    assert facts["Checks"].endswith(f"ruff: {py} -m ruff check app config scripts tests (in crooks-assistant)")
    assert facts["Base"] == f"clive/trunk at {BASE_SHA[:12]}"

    result = await _authorise(engine, clock, session, proposal)
    assert result.code == "verified", result
    assert result.spoken == "Filed bridge-demo-one with the engineering loop."
    assert fake.files[PATH] == served().content and len(fake.puts) == 1


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_an_inbox_that_moved_before_the_tap_files_nothing(fake, bound, engine, clock):
    session = Session(session_id="eng-stale")
    await _staged(session)
    (proposal,) = session.proposals
    fake.files[PATH] = b"{}\n"   # somebody else filed under the same id meanwhile
    fake.commit()
    result = await _authorise(engine, clock, session, proposal)
    assert result.code == "stale" and proposal.status is ActionStatus.STALE
    assert fake.files[PATH] == b"{}\n" and fake.puts == []


@pytest.fixture()
async def owner_app(monkeypatch, fake):
    """The Mac as the owner's tablet reaches it: the real routes, preflight and engine, with
    GitHub faked and a token that a test can take away."""
    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.main import app
    from app.providers import max_agent_sdk
    from app.session.manager import SessionManager
    from app.tools import shopify_tools
    from tests.test_actions import FakeStore
    from tests.test_actions_routes import FakeProvider

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    async def fake_scribe_health(self):
        return True, "fake scribe"

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    monkeypatch.setattr(ScribeClient, "health", fake_scribe_health)
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))
    token = {"value": TOKEN}
    inbox = EngineeringInbox(REPO, token_source=lambda: token["value"], transport=fake.transport())

    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        runtime.provider = FakeProvider()
        store = FakeStore()
        runtime.shopify = store
        shopify_tools.bind(store)
        runtime.actions = ActionEngine(ledger=NullLedger())
        monkeypatch.setattr(engine_module, "_engine", runtime.actions)
        runtime.sessions = SessionManager()
        monkeypatch.setattr(engineering_tools, "_inbox", inbox)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            c.runtime = runtime
            c.inbox = inbox
            c.token = token
            yield c


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_owner_approval_path_admits_the_engineering_write(fake, owner_app):
    from tests.test_actions_routes import PROXIED, configure

    runtime = owner_app.runtime
    operation = "engineering_request_file"
    # The writes switch and the owner allow-list still come first.
    configure(owner_app, writes=False)
    assert (await runtime.write_status(operation)).code == "writes_disabled"
    configure(owner_app, logins="")
    assert (await runtime.write_status(operation)).code == "allow_list_missing"
    configure(owner_app)
    status = await runtime.write_status(operation)
    assert status.ready and status.state == "ready", status
    assert "not a change this Mac can make" not in status.detail

    # Two conversations, each with a request staged for the owner through the gate.
    proposals = {}
    for session_id, request_id in (("eng-yes", "bridge-demo-one"), ("eng-gone", "bridge-demo-two")):
        session = runtime.sessions.get_or_create(session_id)
        session.epoch = max(session.epoch, 1)
        await dispatch(STATUS_TOOL, {}, session=session, timeout_s=5)
        text = await dispatch(SUBMIT_TOOL, {"inbox_id": HEAD, **ask(request_id=request_id)}, session=session, timeout_s=5)
        assert text.startswith("PROPOSED ("), text
        (proposals[session_id],) = session.proposals
    assert fake.puts == []

    async def hold_and_commit(session_id):
        proposal = proposals[session_id]
        armed = await owner_app.post(f"/actions/{proposal.proposal_id}/arm", data={"session_id": session_id}, headers=PROXIED)
        assert armed.status_code == 200, armed.text   # the preflight admitted it
        proposal.armed_at -= 1.0   # the owner's hold
        return await owner_app.post(
            f"/actions/{proposal.proposal_id}/commit", data={"session_id": session_id},
            headers={**PROXIED, "X-Crooks-Arm": armed.json()["nonce"]},
        )

    # With the token: the owner's tap files the request, and the re-read proves it.
    done = await hold_and_commit("eng-yes")
    assert done.status_code == 200, done.text
    assert done.json()["code"] == "verified" and done.json()["status"] == "verified"
    assert fake.files[PATH] == served().content and len(fake.puts) == 1

    # The token goes before the second tap: not connected, and nothing is sent to GitHub.
    calls, sent = len(fake.calls), owner_app.inbox.requests_made
    owner_app.token["value"] = None
    gone = await hold_and_commit("eng-gone")
    assert gone.status_code == 200, gone.text
    assert gone.json()["code"] == "service_unavailable" and gone.json()["status"] == "failed"
    assert "not connected" in proposals["eng-gone"].reason
    assert len(fake.calls) == calls and owner_app.inbox.requests_made == sent
    assert len(fake.puts) == 1 and "requests/bridge-demo-two.json" not in fake.files
    for response in (done, gone):
        assert TOKEN not in response.text


async def test_preparing_refuses_a_moved_inbox_or_an_id_already_used(fake, bound):
    with pytest.raises(ToolError, match="moved since it was read"):
        await engineering_tools.submit_engineering_request(inbox_id="2" * 40, **ask())
    fake.files[PATH] = b"{}\n"
    with pytest.raises(ToolError, match="already on the engineering inbox"):
        await engineering_tools.submit_engineering_request(inbox_id=HEAD, **ask())
    assert fake.puts == []


# ------------------------------------------------------------------ the token


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_token_appears_in_no_log_error_result_or_card(fake, bound, engine, clock, caplog):
    caplog.set_level(logging.DEBUG)
    session = Session(session_id="eng-token")
    outputs = [await _staged(session)]
    (proposal,) = session.proposals
    outputs.append(json.dumps(registry.get(SUBMIT_TOOL).write.present(proposal)))
    outputs.append(json.dumps(proposal.public()))
    outputs.append(json.dumps(proposal.summary, default=str))
    outputs.append(json.dumps(dict(proposal.execution), default=str))
    result = await _authorise(engine, clock, session, proposal)
    assert result.code == "verified"
    outputs.append(result.spoken)

    fake.fail_with = 401
    dedupe.current().reset()
    outputs.append(await dispatch(STATUS_TOOL, {}, session=session, timeout_s=5))
    assert outputs[-1].startswith("ERROR: GitHub refused the engineering inbox token")
    with pytest.raises(GitHubError) as failed:
        await bound.inbox_head()
    outputs.append(str(failed.value))
    with pytest.raises(ToolError) as refused:
        await engineering_tools.submit_engineering_request(inbox_id=HEAD, **ask(request_id="bridge-demo-two"))
    outputs.append(str(refused.value))

    # The token did go to GitHub, as a header and nowhere else, so its absence below means something.
    assert fake.calls and all(call.headers["authorization"] == f"Bearer {TOKEN}" for call in fake.calls)
    assert all(TOKEN not in str(call.url) for call in fake.calls)
    for text in [*outputs, caplog.text]:
        assert TOKEN not in text


# ------------------------------------------------------------------ what happened to each build (2026-09-30)
#
# Asked whether it repairs failed builds or whether the loop retries, CLIVE said it could not see whether
# the loop retries and could only file a fresh request; the owner filed each failed build twice more, and
# each failed the same way. The loop does retry and repair within a request. Each line now says what the
# build went through (`history`) and whether the loop will try again by itself (`next_step`): a blocked
# build needs the Director, and filing the same request again fails the same way unless the cause differs.

LANDED_SHA = "abc1234" + "0" * 33
BUILD_EMAIL = "mia.kowalski@example.com"
BUILD_PHONE = "07700 900123"


def _history(attempts: int, *revisions: tuple[str, int], changes: int = 0, limit: int = 2) -> dict:
    """``build_history`` as the loop derives it from the kernel's records."""
    return {"attempts": attempts,
            "revisions": [{"revision": n, "kind": kind, "attempts": tries, "transient": 0, "refused": 0}
                          for n, (kind, tries) in enumerate(revisions, start=1)],
            "review_changes_requested": changes, "max_repair_rounds": limit}


def _status_rows(result: dict) -> dict[str, dict]:
    return {row["request_id"]: row for row in result["requests"]}


async def test_a_building_build_says_how_often_it_was_built_what_the_review_asked_and_what_it_waits_for(fake, bound):
    fake.status["requests"] = [{
        "request_id": "tried-thrice", "outcome": "accepted", "stage": "EVIDENCE_READY",
        "github_acceptance": {"state": "pending"},
        "build_history": _history(3, ("build", 1), ("repair", 1), ("repair", 1), changes=2, limit=3),
    }]
    row = _status_rows(await engineering_tools.engineering_status())["tried-thrice"]

    assert row["words"] == "tried-thrice is in review."          # the headline reads as it always did
    assert row["history"] == "Built 3 times; the review asked for changes twice; now waiting for GitHub."
    assert row["next_step"] == ("The loop will try again by itself if CLIVE's checks or the review fail: "
                                "1 repair round left. Nothing needs filing again.")


async def test_a_build_being_repaired_says_the_loop_retries_by_itself_and_how_many_rounds_are_left(fake, bound):
    fake.status["requests"] = [{
        "request_id": "being-repaired", "outcome": "accepted", "stage": "RUNNING", "revision": 2,
        "attempts": [
            {"attempt_id": "being-repaired-a1", "revision": 1, "outcome": "cancelled", "reason": "transient: timeout"},
            {"attempt_id": "being-repaired-a2", "revision": 1, "outcome": "candidate", "reason": None},
            {"attempt_id": "being-repaired-a3", "revision": 2, "outcome": "launched", "reason": None},
        ],
        "repairs": {"review": 0, "ci": 1, "max": 3},
    }]
    row = _status_rows(await engineering_tools.engineering_status())["being-repaired"]

    assert row["progress"] == "building"
    assert row["history"] == ("Built 3 times; the loop retried it by itself once (1 attempt cancelled); "
                              "GitHub's tests failed once; now building.")
    assert row["next_step"] == ("The loop will try again by itself if CLIVE's checks, GitHub's tests or the review "
                                "fail: 2 repair rounds left. Nothing needs filing again.")


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_a_blocked_build_needs_the_director_and_filing_it_again_fails_the_same_way(fake, bound):
    """The answer the owner needed on 30 Sep: the loop will not retry it by itself, and a re-filing fails alike."""
    fake.status["requests"] = [
        {"request_id": "blocked-build", "outcome": "accepted", "stage": "BLOCKED",
         "blocker": "GitHub's tests failed — tests/test_x.py::test_y",
         "build_history": _history(3, ("build", 1), ("repair", 1), ("repair", 1), changes=1),
         "repairs": {"review": 1, "ci": 1, "max": 2}},
        {"request_id": "blocked-long", "outcome": "accepted", "stage": "BLOCKED",
         "blocker": "convergence limit: " + "finding F-07 remains on the candidate; " * 80,
         "build_history": _history(1, ("build", 1))},
    ]
    rows = _status_rows(await engineering_tools.engineering_status())

    blocked = rows["blocked-build"]
    assert blocked["progress"] == "blocked"
    assert blocked["history"] == ("Built 3 times; the review asked for changes once; GitHub's tests failed once; "
                                  "blocked after 2 repair rounds: GitHub's tests failed — tests/test_x.py::test_y.")
    assert blocked["next_step"] == (
        "The loop will not try again by itself: a blocked build needs the Director. "
        "Filing the same request again will fail the same way unless the cause is different."
    )
    # the blocker in full, up to its bound, where the headline stops at the usual one
    long = rows["blocked-long"]
    assert long["history"].startswith("Built once; blocked: convergence limit: finding F-07 remains")
    assert len(long["history"]) <= engineering_tools.MAX_HISTORY_CHARS
    assert long["history"].count("F-07") > long["words"].count("F-07") > 1
    assert "will not try again by itself" in long["next_step"]
    # and it is what the model is handed
    text = await dispatch(STATUS_TOOL, {}, session=Session(session_id="eng-blocked"), timeout_s=5)
    assert "a blocked build needs the Director" in text and "will fail the same way unless the cause" in text


async def test_a_landed_build_says_where_it_landed_and_a_refused_landing_needs_the_director(fake, bound):
    fake.status["requests"] = [
        {"request_id": "landed-build", "outcome": "accepted", "stage": "COMPLETE", "candidate_sha": "c" * 40,
         "build_history": _history(1, ("build", 1)),
         "landing": {"state": "landed", "sha": LANDED_SHA, "at": "2026-09-30T14:05:00+00:00", "reason": None}},
        {"request_id": "landing-waits", "outcome": "accepted", "stage": "COMPLETE", "candidate_sha": "d" * 40,
         "landing": {"state": "waiting", "sha": None, "at": None, "reason": "GitHub has not finished on the trunk"}},
        {"request_id": "landing-refused", "outcome": "accepted", "stage": "COMPLETE", "candidate_sha": "e" * 40,
         "landing": {"state": "refused", "sha": None, "at": None, "reason": "the trunk moved and the merge conflicts"}},
        {"request_id": "landing-off", "outcome": "accepted", "stage": "COMPLETE", "candidate_sha": "f" * 40,
         "landing": {"state": "off", "sha": None, "at": None, "reason": None}},
    ]
    rows = _status_rows(await engineering_tools.engineering_status())

    landed = rows["landed-build"]
    assert landed["words"] == f"landed-build is done: candidate {'c' * 40}."
    assert landed["history"] == "Built once; landed on the trunk as abc1234."
    assert "next_step" not in landed
    assert rows["landing-waits"]["history"] == "Now waiting to land on the trunk: GitHub has not finished on the trunk."
    assert rows["landing-waits"]["next_step"] == "The loop lands it on the trunk by itself; nothing needs filing again."
    assert rows["landing-refused"]["history"] == ("The loop would not land it on the trunk: the trunk moved and the "
                                                  "merge conflicts.")
    assert rows["landing-refused"]["next_step"].startswith("The loop will not land it by itself: it needs the Director.")
    assert rows["landing-off"]["history"] == ("Landing is switched off on the loop, so the owner merges it into the "
                                              "trunk.")


async def test_a_request_waiting_for_its_base_is_waiting_not_refused_and_needs_no_refiling(fake, bound, monkeypatch):
    monkeypatch.setattr(engineering_tools, "_progress_cache", {})
    fake.status["waiting_requests"] = [{
        "request_id": "fresh-after-merge", "source": "requests/fresh-after-merge.json", "request_sha256": "1" * 64,
        "outcome": "waiting", "reason": "waiting for the engineering repo to fetch the base commit it names",
        "waiting_since": "2026-09-30T12:00:00+00:00", "refuse_after": "2026-09-30T13:00:00+00:00",
    }]
    fake.status["adapter"] = {"intake_error": None, "trunk_fetch_error": "the trunk could not be fetched this cycle; "
                              "a request whose base commit is missing stays waiting"}

    result = await engineering_tools.engineering_status()

    assert _status_rows(result)["fresh-after-merge"] == {
        "request_id": "fresh-after-merge", "progress": "queued",
        "words": "fresh-after-merge is waiting for its base commit to reach the build server; the loop takes it in "
                 "by itself as soon as it arrives, and refuses it if it has not arrived by 2026-09-30 13:00 UTC.",
        "next_step": "Nothing needs filing again: the loop takes it in by itself once the build server has its base "
                     "commit.",
    }
    assert result["summary"] == (
        "1 engineering request: 1 queued. The loop could not fetch the trunk last time: the trunk could not be "
        "fetched this cycle; a request whose base commit is missing stays waiting."
    )
    # the owner's build card reads the same row, not "the loop has not picked it up yet"
    card = await engineering_tools.build_progress(["fresh-after-merge"])
    assert card["fresh-after-merge"]["words"].startswith("fresh-after-merge is waiting for its base commit")


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_nothing_secret_or_customer_shaped_reaches_what_clive_says_about_a_build(fake, bound):
    """The loop redacts what it publishes; the tool holds to it for whatever a status carries."""
    from tests.fake_credentials import credential_url, openai_key

    key = openai_key("engineering-bridge-status", kind="")
    url = credential_url(github_token("engineering-bridge-status-url", kind="s"))
    leak = f"push to {url} failed; {TOKEN} api_key={key}; the fixture mailed {BUILD_EMAIL} on {BUILD_PHONE}"
    fake.status["requests"] = [
        {"request_id": "leaky-blocked", "outcome": "accepted", "stage": "BLOCKED", "blocker": leak,
         "build_history": _history(2, ("build", 2)),
         "attempts": [{"attempt_id": "leaky-a1", "revision": 1, "outcome": "refused", "reason": leak}],
         "generated": [f"docs/{BUILD_EMAIL}.md"], "landing": {"state": "refused", "reason": leak}},
        {"request_id": "leaky-refused", "outcome": "refused", "reason": leak},
    ]
    fake.status["adapter"] = {"intake_error": leak, "trunk_fetch_error": leak}

    text = await dispatch(STATUS_TOOL, {}, session=Session(session_id="eng-leaky"), timeout_s=5)

    rows = _status_rows(json.loads(text))
    assert "blocked: push to https://[redacted]@" in rows["leaky-blocked"]["history"]
    assert "[email]" in rows["leaky-blocked"]["words"] and "[phone]" in rows["leaky-refused"]["words"]
    for leaked in (TOKEN, key, url, BUILD_EMAIL, BUILD_PHONE, "mia.kowalski", "900123"):
        assert leaked not in text, leaked
