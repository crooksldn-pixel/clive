"""The engineering bridge: CLIVE files an engineering request into the remote loop's GitHub
inbox and reads back, in plain words, where each request stands.

GitHub is a fake behind an httpx MockTransport: nothing here reaches the network, and the
token is a made-up string whose only job is to be looked for in every output.
"""

from __future__ import annotations

import base64
import importlib
import json
import logging
from datetime import UTC, datetime

import httpx
import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.ledger import NullLedger
from app.actions.models import ActionStatus
from app.engineering_bridge.github import (
    Created,
    GitHubInbox,
    InboxHead,
    NotConnected,
    Refused,
    RequestFile,
    Status,
    Unavailable,
)
from app.engineering_bridge.requests import RequestRefused, build_request
from app.orchestrator.objectives import Objective, OwnerEntry
from app.remote_engineering.requests import parse_request
from app.session.models import Session
from app.tools import registry
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from app.tools.registry import ToolError

TOKEN = "ghs_madeUpTokenForTests0000000000000000"
MARKER = "ghp_LEAKED0value"
HEAD = "a" * 40
AFTER = "b" * 40
BASE = "631caa24d551e994e77c0a794780c97a533f0823"
REPO = "/repos/crooksldn-pixel/clive"
PATH = "requests/bridge-status-v1.json"
NAMES = ("engineering_status", "submit_engineering_request")

GOOD = {
    "request_id": "bridge-status-v1",
    "title": "Report engineering progress in plain words",
    "requested_outcome": "CLIVE says where each engineering request stands.",
    "base_ref": "main",
    "base_sha": BASE,
    "allowed_paths": ["crooks-assistant/app/engineering_bridge", "crooks-assistant/docs/bridge.md"],
    "acceptance_criteria": ["each request's progress is said in plain words"],
    "checks": [{"name": "bridge", "argv": ["python", "-m", "pytest", "-q"], "cwd": "crooks-assistant"}],
    "max_repair_rounds": 2,
}


class FakeGitHub:
    """The contents API for one repository: the status file, the inbox branch, and a record
    of every request that reached it."""

    def __init__(self) -> None:
        self.head = HEAD
        self.status: bytes | None = None
        self.files: dict[str, bytes] = {}
        self.calls: list[httpx.Request] = []
        self.race = False            # someone else's file lands just before our create
        self.answer: int | None = None   # answer every request with this status
        self.unreachable = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        if self.unreachable:
            raise httpx.ConnectError(f"refused while sending Authorization: Bearer {TOKEN}", request=request)
        if self.answer is not None:
            return httpx.Response(self.answer, json={"message": f"Bad credentials for {TOKEN}"})
        path, method = request.url.path, request.method
        if method == "GET" and path == f"{REPO}/git/ref/heads/clive/control/owner-inbox":
            return httpx.Response(200, json={"ref": "refs/heads/clive/control/owner-inbox", "object": {"sha": self.head, "type": "commit"}})
        if method == "GET" and path == f"{REPO}/contents/status.json":
            assert request.url.params["ref"] == "clive/control/status"
            return httpx.Response(200, content=self.status) if self.status is not None else httpx.Response(404, json={"message": "Not Found"})
        if path.startswith(f"{REPO}/contents/requests/"):
            name = path.removeprefix(f"{REPO}/contents/")
            if method == "GET":
                assert request.url.params["ref"] == "clive/control/owner-inbox"
                return httpx.Response(200, content=self.files[name]) if name in self.files else httpx.Response(404, json={"message": "Not Found"})
            if method == "PUT":
                body = json.loads(request.content)
                assert "sha" not in body, "a create never names a blob to replace"
                assert body["branch"] == "clive/control/owner-inbox"
                if self.race:
                    self.files[name] = b"someone else's request\n"
                if name in self.files:
                    return httpx.Response(422, json={"message": "Invalid request. \"sha\" wasn't supplied."})
                self.files[name] = base64.b64decode(body["content"])
                self.head = AFTER
                return httpx.Response(201, json={"content": {"path": name}, "commit": {"sha": AFTER}})
        raise AssertionError(f"unexpected request {method} {path}")

    def puts(self) -> list[httpx.Request]:
        return [c for c in self.calls if c.method == "PUT"]


def connected(fake: FakeGitHub | None = None) -> tuple[FakeGitHub, GitHubInbox]:
    fake = fake or FakeGitHub()
    return fake, GitHubInbox(token=lambda: TOKEN, transport=httpx.MockTransport(fake.handler))


@pytest.fixture()
def tools():
    """The two tools, registered for this test only, like the probes in test_gate.py: the
    registry-wide checks elsewhere in the suite keep seeing exactly what they list."""
    from app.tools import engineering_tools

    for name in NAMES:
        registry._REGISTRY.pop(name, None)
    module = importlib.reload(engineering_tools)
    try:
        yield module
    finally:
        for name in NAMES:
            registry._REGISTRY.pop(name, None)


@pytest.fixture()
def engine(monkeypatch):
    e = ActionEngine(ledger=NullLedger())
    monkeypatch.setattr(engine_module, "_engine", e)
    return e


def spec_lookup(name):
    try:
        return registry.get(name)
    except KeyError:
        return None


def submission(**overrides) -> dict:
    return {"inbox_id": HEAD, **GOOD, **overrides}


# --------------------------------------------------------------------------- the request


def test_a_built_request_passes_the_loops_own_intake():
    """The bytes the bridge files are parsed by the loop's own parser and become an Objective
    by the loop's own record, the same way the loop's controller makes one."""
    request = build_request(**GOOD)
    parsed = parse_request(request.to_bytes())
    assert parsed.request_id == "bridge-status-v1"
    assert parsed.target_branch == "clive/objective/bridge-status-v1"
    assert parsed.checks[0].argv == ("python", "-m", "pytest", "-q") and parsed.checks[0].cwd == "crooks-assistant"
    objective = Objective(
        objective_id=parsed.request_id, title=parsed.title, requested_outcome=parsed.requested_outcome,
        acceptance_criteria=parsed.acceptance_criteria, checks=parsed.checks, repository="crooksldn-pixel/clive",
        base_ref=parsed.base_ref, base_sha=parsed.base_sha, target_branch=parsed.target_branch,
        product_memory_sha="e" * 40, allowed_paths=parsed.allowed_paths, max_repair_rounds=parsed.max_repair_rounds,
        owner=OwnerEntry(os_user="owner", host="clive"), created_at=datetime(2026, 9, 25, tzinfo=UTC),
    )
    assert objective.allowed_paths == tuple(GOOD["allowed_paths"])
    assert json.loads(request.to_bytes())["schema_version"] == "clive.remote_engineering_request.v1"


def test_the_longest_request_id_the_loop_allows_is_accepted():
    longest = "-".join(["abcdefghijklmnop"] * 8)
    assert build_request(**{**GOOD, "request_id": longest}).target_branch == f"clive/objective/{longest}"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_id", MARKER),
        ("request_id", "single"),
        ("request_id", "-".join(["abc"] * 9)),
        ("target_branch", f"clive/objective/{MARKER}"),
        ("title", ""),
        ("title", None),
        ("title", MARKER * 20),
        ("requested_outcome", MARKER * 1300),
        ("base_ref", f"{MARKER}..x"),
        ("base_ref", f"-{MARKER}"),
        ("base_sha", MARKER),
        ("base_sha", "abc123"),
        ("allowed_paths", []),
        ("allowed_paths", MARKER),
        ("allowed_paths", [f"/{MARKER}"]),
        ("allowed_paths", [f"crooks-assistant/../{MARKER}"]),
        ("allowed_paths", ["crooks-assistant/app/orchestrator/lifecycle.py"]),
        ("allowed_paths", ["crooks-assistant/app/orchestrator"]),
        ("allowed_paths", [f"engineering/{MARKER}"]),
        ("acceptance_criteria", ["   "]),
        ("acceptance_criteria", [MARKER * 200]),
        ("checks", [{"name": MARKER, "argv": ["x"]}]),
        ("checks", [{"name": "ok", "argv": []}]),
        ("checks", [{"name": "ok", "argv": ["x"], "cwd": f"../{MARKER}"}]),
        ("checks", [{"name": "ok", "argv": ["x"], MARKER: 1}]),
        ("checks", [{"name": "ok", "argv": ["x"]}, {"name": "ok", "argv": ["y"]}]),
        ("max_repair_rounds", 6),
        ("max_repair_rounds", -1),
        ("max_repair_rounds", True),
        ("max_repair_rounds", "2"),
    ],
)
def test_an_invalid_field_is_refused_without_echoing_it(field, value):
    with pytest.raises(RequestRefused) as refused:
        build_request(**{**GOOD, field: value})
    words = str(refused.value)
    assert field in words, "the refusal names the field"
    assert MARKER not in words and "LEAKED" not in words
    assert "orchestrator" not in words and "lifecycle" not in words, "nor the protected path it hit"


# --------------------------------------------------------------------------- not connected


async def test_with_no_token_every_call_is_not_connected_and_nothing_is_sent():
    fake = FakeGitHub()
    for token in (lambda: None, lambda: "", lambda: "   "):
        client = GitHubInbox(token=token, transport=httpx.MockTransport(fake.handler))
        results = [
            await client.read_status(),
            await client.inbox_head(),
            await client.request_file("bridge-status-v1"),
            await client.create_request("bridge-status-v1", b"{}\n"),
        ]
        assert all(isinstance(r, NotConnected) for r in results), results
    assert fake.calls == [], "nothing was attempted"


async def test_the_token_is_read_from_the_secret_store_at_call_time(monkeypatch):
    from app.secrets import keychain

    fake = FakeGitHub()
    fake.status = b'{"requests": []}'
    client = GitHubInbox(transport=httpx.MockTransport(fake.handler))
    assert isinstance(await client.read_status(), NotConnected), "the suite's store holds nothing"
    # The store as shipped refuses a name it does not list yet: that reads as not connected.
    monkeypatch.setattr(keychain, "get_optional", lambda key: keychain._validate(key))
    assert isinstance(await client.inbox_head(), NotConnected)
    assert fake.calls == []
    asked: list[str] = []
    monkeypatch.setattr(keychain, "get_optional", lambda key: asked.append(key) or TOKEN)
    assert isinstance(await client.read_status(), Status)
    assert asked == ["github_engineering_inbox_token"]
    assert TOKEN not in repr(client) and not any(TOKEN in str(v) for v in vars(client).values())


async def test_the_tools_say_not_connected_and_attempt_nothing(tools, engine):
    fake = FakeGitHub()
    tools.bind(GitHubInbox(token=lambda: None, transport=httpx.MockTransport(fake.handler)))
    status = await tools.engineering_status()
    assert status["connected"] is False and "not connected" in status["summary"]
    assert "inbox" not in status, "no inbox id is issued when the inbox was not read"
    with pytest.raises(ToolError, match="not connected"):
        await tools.submit_engineering_request(**submission())
    session = Session(session_id="eng")
    session.issue(HEAD)
    text = await dispatch("submit_engineering_request", submission(), session=session, timeout_s=5)
    assert text.startswith("ERROR") and "not connected" in text and session.proposals == []
    assert fake.calls == []


# --------------------------------------------------------------------------- the create


async def test_a_request_is_created_once_when_absent_and_never_overwritten():
    fake, client = connected()
    request = build_request(**GOOD)
    created = await client.create_request(request.request_id, request.to_bytes())
    assert created == Created(request_id="bridge-status-v1", commit_sha=AFTER)
    assert fake.files[PATH] == request.to_bytes()
    assert len(fake.puts()) == 1
    again = await client.create_request(request.request_id, b'{"different": true}\n')
    assert isinstance(again, Refused) and again.exists
    assert len(fake.puts()) == 1, "a file that is there is never written to"
    assert fake.files[PATH] == request.to_bytes()
    found = await client.request_file(request.request_id)
    assert found == RequestFile(request_id="bridge-status-v1", exists=True, content=request.to_bytes())


async def test_a_conflict_is_re_read_and_refused_never_retried():
    fake, client = connected()
    fake.race = True
    request = build_request(**GOOD)
    result = await client.create_request(request.request_id, request.to_bytes())
    assert isinstance(result, Refused) and result.exists
    assert len(fake.puts()) == 1, "one attempt, then a re-read, and no second attempt"
    assert fake.calls[-1].method == "GET", "the conflict was re-read"
    assert fake.files[PATH] == b"someone else's request\n", "and the other file stands"


async def test_the_inbox_head_is_read():
    fake, client = connected()
    assert await client.inbox_head() == InboxHead(sha=HEAD)


# --------------------------------------------------------------------------- status words

STATUS = {
    "schema_version": "clive.remote_engineering_status.v1",
    "generated_at": "2026-09-25T10:00:00+00:00",
    "adapter": {"intake_error": "the inbox could not be fetched"},
    "requests": [
        {"request_id": "alpha-one", "outcome": "accepted", "stage": "READY"},
        {"request_id": "bravo-two", "outcome": "accepted", "stage": "RUNNING", "candidate_sha": None},
        {"request_id": "charlie-three", "outcome": "accepted", "stage": "REVIEWING", "review": {"verdicts": [{"verdict": "changes_requested"}]}},
        {"request_id": "delta-four", "outcome": "accepted", "stage": "COMPLETE", "candidate_sha": "c" * 40, "acceptance": {"sha": "c" * 40}},
        {"request_id": "echo-five", "outcome": "accepted", "stage": "BLOCKED", "blocker": "the ruff check failed twice", "stage_reason": "blocked"},
        {"request_id": "foxtrot-six", "outcome": "accepted", "stage": "OWNER_GATE", "owner_gate": "a credential only the owner can provide"},
        {"request_id": "golf-seven", "outcome": "refused", "reason": "request does not match clive.remote_engineering_request.v1"},
        {"request_id": "hotel-eight", "outcome": "accepted"},
    ],
    "refused_records": [],
}


async def test_the_status_is_said_in_plain_words_per_request(tools):
    fake, client = connected()
    fake.status = json.dumps(STATUS).encode()
    tools.bind(client)
    out = await tools.engineering_status()
    assert out["connected"] is True and out["inbox"] == {"id": HEAD}
    assert [r["progress"] for r in out["requests"]] == [
        "queued", "building", "in review", "done", "blocked", "needs the owner", "blocked", "queued",
    ]
    words = [r["words"] for r in out["requests"]]
    assert words == [
        "alpha-one: queued.",
        "bravo-two: building.",
        "charlie-three: in review (1 verdict so far).",
        f"delta-four: done — candidate {'c' * 40}.",
        "echo-five: blocked — the ruff check failed twice",
        "foxtrot-six: needs the owner — a credential only the owner can provide",
        "golf-seven: blocked — the loop refused it: request does not match clive.remote_engineering_request.v1",
        "hotel-eight: queued.",
    ]
    assert out["requests"][3]["candidate_sha"] == "c" * 40
    assert "candidate_sha" not in out["requests"][1], "a SHA is only given once it is done"
    assert out["summary"].startswith("The loop could not read the inbox on its last pass: the inbox could not be fetched")
    assert all(w in out["summary"] for w in words)


async def test_no_status_yet_is_said_and_the_inbox_id_is_still_given(tools):
    fake, client = connected()
    tools.bind(client)
    out = await tools.engineering_status()
    assert out["requests"] == [] and "not published a status yet" in out["summary"]
    assert out["inbox"] == {"id": HEAD}


async def test_the_status_read_issues_the_inbox_id_through_the_dispatcher(tools):
    """The same mechanism every read uses: an `id` in the result is issued to the
    conversation, and that is what lets the gate stage the submission."""
    fake, client = connected()
    fake.status = json.dumps(STATUS).encode()
    tools.bind(client)
    session = Session(session_id="eng")
    assert HEAD not in session.issued_ids
    text = await dispatch("engineering_status", {}, session=session, timeout_s=5)
    assert HEAD in session.issued_ids
    assert "delta-four: done" in text
    assert fake.puts() == []


# --------------------------------------------------------------------------- the gate and the tap


def test_the_submission_is_staged_for_the_owner_only_on_the_inbox_id_that_was_read(tools):
    decision = classify("submit_engineering_request", submission(), issued_ids={HEAD})
    assert decision.disposition is Disposition.STAGE_FOR_OWNER and decision.tier is Tier.AMBER
    unread = classify("submit_engineering_request", submission(), issued_ids=set())
    assert unread.disposition is Disposition.DENY and unread.recoverable
    missing = {k: v for k, v in submission().items() if k != "inbox_id"}
    assert classify("submit_engineering_request", missing, issued_ids={HEAD}).disposition is Disposition.DENY
    too_long = submission(requested_outcome="x" * 20_001)
    assert classify("submit_engineering_request", too_long, issued_ids={HEAD}).disposition is Disposition.DENY
    assert classify("submit_engineering_request", submission(max_repair_rounds=6), issued_ids={HEAD}).disposition is Disposition.DENY
    read = classify("engineering_status", {}, issued_ids=set())
    assert read.disposition is Disposition.EXECUTE_NOW and read.tier is Tier.GREEN
    spec = registry.get("submit_engineering_request")
    assert spec.write is not None and spec.write.complete
    assert spec.write.interaction == "tap_commit" and spec.write.kind == "irreversible" and not spec.write.reversible


async def test_staging_sends_nothing_and_the_card_says_what_will_be_filed(tools, engine):
    fake, client = connected()
    tools.bind(client)
    session = Session(session_id="eng")
    session.epoch = 1
    await dispatch("engineering_status", {}, session=session, timeout_s=5)
    text = await dispatch("submit_engineering_request", submission(), session=session, timeout_s=5)
    assert text.startswith("PROPOSED (prop_") and "NOT happened" in text
    assert "engineering request bridge-status-v1" in text
    assert fake.puts() == [] and fake.files == {}
    proposal = session.proposals[-1]
    assert proposal.status is ActionStatus.PENDING
    card = registry.get("submit_engineering_request").write.present(proposal)
    facts = {f["label"]: f["value"] for f in card["facts"]}
    assert card["summary"] == "Report engineering progress in plain words"
    assert facts["May change"] == "Only crooks-assistant/app/engineering_bridge, crooks-assistant/docs/bridge.md"
    assert facts["Checks"] == "bridge: runs python -m pytest -q in crooks-assistant"
    assert facts["Base"] == f"main at commit {BASE}"
    assert facts["Repairs"] == "Up to 2 repair rounds"


async def test_the_owners_tap_creates_the_file_once_and_proves_its_bytes(tools, engine):
    fake, client = connected()
    tools.bind(client)
    session = Session(session_id="eng")
    session.epoch = 1
    session.issue(HEAD)
    await dispatch("submit_engineering_request", submission(), session=session, timeout_s=5)
    proposal = session.proposals[-1]
    result = await engine.commit(proposal.proposal_id, "eng", caller="owner", spec_lookup=spec_lookup)
    assert result.code == "verified" and proposal.status is ActionStatus.VERIFIED
    assert result.spoken == "Engineering request bridge-status-v1 is filed."
    assert fake.files[PATH] == build_request(**GOOD).to_bytes()
    assert len(fake.puts()) == 1
    again = await engine.commit(proposal.proposal_id, "eng", caller="owner", spec_lookup=spec_lookup)
    assert again.code == "already_executed" and len(fake.puts()) == 1, "a second tap is not a second file"


async def test_an_inbox_that_moved_before_the_tap_files_nothing(tools, engine):
    fake, client = connected()
    tools.bind(client)
    session = Session(session_id="eng")
    session.epoch = 1
    session.issue(HEAD)
    await dispatch("submit_engineering_request", submission(), session=session, timeout_s=5)
    proposal = session.proposals[-1]
    fake.files[PATH] = b"filed from somewhere else\n"
    fake.head = "d" * 40
    result = await engine.commit(proposal.proposal_id, "eng", caller="owner", spec_lookup=spec_lookup)
    assert result.code == "stale" and fake.puts() == []
    assert fake.files[PATH] == b"filed from somewhere else\n"


async def test_a_file_that_appears_at_the_last_moment_is_refused_not_overwritten(tools, engine):
    fake, client = connected()
    tools.bind(client)
    session = Session(session_id="eng")
    session.epoch = 1
    session.issue(HEAD)
    await dispatch("submit_engineering_request", submission(), session=session, timeout_s=5)
    proposal = session.proposals[-1]
    fake.race = True
    result = await engine.commit(proposal.proposal_id, "eng", caller="owner", spec_lookup=spec_lookup)
    assert result.code == "stale" and proposal.status is ActionStatus.STALE
    assert fake.files[PATH] == b"someone else's request\n"


async def test_the_prepare_step_refuses_a_moved_inbox_an_existing_file_and_a_bad_field(tools, engine):
    fake, client = connected()
    tools.bind(client)
    with pytest.raises(ToolError, match="moved on"):
        await tools.submit_engineering_request(**submission(inbox_id="d" * 40))
    fake.files[PATH] = b"{}\n"
    with pytest.raises(ToolError, match="already in the engineering inbox"):
        await tools.submit_engineering_request(**submission())
    with pytest.raises(ToolError) as refused:
        await tools.submit_engineering_request(**submission(base_sha=MARKER))
    assert MARKER not in str(refused.value)
    assert fake.puts() == []


# --------------------------------------------------------------------------- the token


async def test_the_token_appears_in_no_result_error_log_or_card(tools, engine, caplog):
    caplog.set_level(logging.DEBUG)
    seen: list[str] = []

    fake, client = connected()
    fake.status = json.dumps(STATUS).encode()
    tools.bind(client)
    session = Session(session_id="eng")
    session.epoch = 1
    seen.append(await dispatch("engineering_status", {}, session=session, timeout_s=5))
    seen.append(await dispatch("submit_engineering_request", submission(), session=session, timeout_s=5))
    proposal = session.proposals[-1]
    seen.append(repr(registry.get("submit_engineering_request").write.present(proposal)))
    seen.append(repr(proposal.summary) + repr(dict(proposal.execution)) + repr(proposal.public()))
    result = await engine.commit(proposal.proposal_id, "eng", caller="owner", spec_lookup=spec_lookup)
    seen.append(result.spoken + result.detail + repr(proposal.after) + repr(proposal.sent))

    # GitHub refusing the token, and GitHub unreachable: both quote the token in what they
    # say, and neither reaches a result.
    for trouble in ("answer", "unreachable"):
        broken, broken_client = connected()
        if trouble == "answer":
            broken.answer = 401
        else:
            broken.unreachable = True
        results = [
            await broken_client.read_status(), await broken_client.inbox_head(),
            await broken_client.request_file("bridge-status-v1"),
            await broken_client.create_request("bridge-status-v1", b"{}\n"),
        ]
        assert all(isinstance(r, Unavailable) for r in results), results
        seen.extend(repr(r) for r in results)
        tools.bind(broken_client)
        seen.append(await dispatch("engineering_status", {}, session=session, timeout_s=5))
        seen.append(await dispatch("submit_engineering_request", submission(), session=session, timeout_s=5))

    assert result.code == "verified"
    assert "401" in " ".join(seen) and "ConnectError" in " ".join(seen), "the failures were reported"
    for text in [*seen, caplog.text]:
        assert TOKEN not in text
