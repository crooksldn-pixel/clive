"""Build objectives, filed from CLIVE to a builder host's loop (app/tools/engineering_tools.py).

The model supplies only what the owner wants: a title, the outcome, what done looks like and the
parts of CLIVE the work may touch. The base (the trunk's head, by SHA), the id and the checks are
filled in; the request goes to the configured host's own inbox branch; once filed it is linked to
its objective, which becomes a build objective with the building on its ladder.
"""

from __future__ import annotations

import base64
import hashlib
import json

import httpx
import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.ledger import NullLedger
from app.engineering_bridge.github import EngineeringInbox, branches_for
from app.objectives import store as store_module
from app.orchestrator.objectives import PROTECTED_PATHS, _overlaps
from app.remote_engineering.requests import parse_request
from app.routes import objectives as objectives_route
from app.session.models import Session
from app.tools import engineering_tools, registry
from app.tools.dispatch import dispatch
from tests.fake_credentials import github_token

TOKEN = github_token("build-from-clive")
REPO = "crooksldn-pixel/clive"
HOST = "worker-01"
INBOX = "clive/control/worker-01-inbox"
STATUS = "clive/control/worker-01-status"
TRUNK = "clive/trunk"
HEAD = "1" * 40
TRUNK_SHA = "b" * 40
CHECK_PYTHON = "/srv/builders/.venv/bin/python"


class FakeGitHub:
    """One builder host's inbox and status branches and the trunk, behind the REST API's shape."""

    def __init__(self) -> None:
        self.heads = {INBOX: HEAD, TRUNK: TRUNK_SHA}
        self.status: dict | None = {"generated_at": "2026-09-26T22:00:00+00:00", "requests": []}
        self.files: dict[str, bytes] = {}
        self.puts: list[dict] = []
        self.status_reads = 0
        self.down = False
        self.commits = 0

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            return httpx.Response(503, json={"message": "unavailable"})
        path = request.url.path[len(f"/repos/{REPO}"):]
        ref = request.url.params.get("ref")
        if request.method == "GET" and path.startswith("/git/ref/heads/"):
            branch = path[len("/git/ref/heads/"):]
            if branch not in self.heads:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={"object": {"type": "commit", "sha": self.heads[branch]}})
        name = path[len("/contents/"):]
        if request.method == "GET":
            if name == "status.json" and ref == STATUS and self.status is not None:
                self.status_reads += 1
                return self._file(json.dumps(self.status).encode())
            if ref == INBOX and name in self.files:
                return self._file(self.files[name])
            return httpx.Response(404, json={"message": "Not Found"})
        body = json.loads(request.content)
        self.puts.append(body)
        if name in self.files or body.get("branch") != INBOX:
            return httpx.Response(422, json={"message": "no"})
        self.files[name] = base64.b64decode(body["content"])
        self.commits += 1
        self.heads[INBOX] = hashlib.sha1(f"c{self.commits}".encode()).hexdigest()
        return httpx.Response(201, json={"commit": {"sha": self.heads[INBOX]}})

    @staticmethod
    def _file(content: bytes) -> httpx.Response:
        return httpx.Response(200, json={"type": "file", "encoding": "base64",
                                         "content": base64.encodebytes(content).decode("ascii")})


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def fake() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture()
def bound(fake, monkeypatch) -> EngineeringInbox:
    inbox = EngineeringInbox(REPO, token_source=lambda: TOKEN, transport=fake.transport(), host=HOST)
    monkeypatch.setattr(engineering_tools, "_inbox", inbox)
    monkeypatch.setattr(engineering_tools, "_check_python", CHECK_PYTHON)
    monkeypatch.setattr(engineering_tools, "_progress_cache", {})
    return inbox


@pytest.fixture()
def objectives(tmp_path, monkeypatch) -> store_module.ObjectiveStore:
    fresh = store_module.ObjectiveStore(tmp_path / "objectives")
    monkeypatch.setattr(store_module, "_STORE", fresh)
    return fresh


@pytest.fixture()
def engine(monkeypatch) -> tuple[ActionEngine, Clock]:
    clock = Clock()
    fresh = ActionEngine(ledger=NullLedger(), clock=clock)
    monkeypatch.setattr(engine_module, "_engine", fresh)
    return fresh, clock


def ask(**overrides) -> dict:
    base = {
        "inbox_id": HEAD,
        "title": "Show a task expanded on the big screen",
        "requested_outcome": "When I ask to pull up the fulfilment slip for an order, show it large on the Mac's screen.",
        "allowed_paths": ["app/scenes", "web/alpha.js"],
        "acceptance_criteria": ["Asking for an order's fulfilment slip shows it full screen."],
    }
    base.update(overrides)
    return base


async def _prepare(session: Session, **overrides) -> str:
    await dispatch("engineering_status", {"areas": True}, session=session, timeout_s=5)
    return await dispatch("submit_engineering_request", ask(**overrides), session=session, timeout_s=5)


async def _file(engine, session: Session):
    engine_, clock = engine
    (proposal,) = session.proposals
    armed, code = engine_.arm(proposal.proposal_id, session.session_id)
    assert code == "", code
    clock.now += 1.0
    return proposal, await engine_.commit(proposal.proposal_id, session.session_id, caller="owner",
                                          spec_lookup=registry.get, nonce=armed.arm_nonce)


# ------------------------------------------------------------------ where requests go


def test_each_host_has_its_own_inbox_and_status_branch():
    assert branches_for("owner") == ("clive/control/owner-inbox", "clive/control/status")
    assert branches_for(HOST) == (INBOX, STATUS)
    for bad in ("", "Worker", "a/b", "../x", "x" * 40):
        with pytest.raises(ValueError):
            branches_for(bad)


def test_the_runtime_files_with_the_configured_host():
    from app import engineering_switch
    from config.settings import Settings

    # Unset is off, not worker-01 (the 2026-09-28 review, round 10, CFG-01): filing is named on.
    assert engineering_switch.filing_host(Settings(_env_file=None).engineering_host) is None
    settings = Settings(_env_file=None, engineering_host=HOST)
    assert engineering_switch.inbox_for(settings.engineering_host).inbox_branch == INBOX


async def test_status_names_the_host_the_base_and_the_parts_a_build_may_change(fake, bound):
    out = await engineering_tools.engineering_status(areas=True)
    assert out["connected"] and out["host"] == HOST
    assert out["inbox"] == {"id": HEAD, "branch": INBOX}
    assert out["base"] == {"ref": TRUNK, "sha": TRUNK_SHA}
    areas = out["areas"]
    assert "crooks-assistant/web" in areas and "crooks-assistant/app/objectives" in areas
    assert not [a for a in areas if any(_overlaps(a, p) for p in PROTECTED_PATHS)]
    assert "tests" in out
    quiet = await engineering_tools.engineering_status()
    assert "areas" not in quiet


# ------------------------------------------------------------------ what is filled in


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_model_gives_the_want_and_the_rest_is_filled_in(fake, bound, objectives, engine):
    obj = objectives.create(title="Expanded task display", request="Show a task large on the Mac")
    session = Session(session_id="build")
    text = await _prepare(session, objective_id=obj.id)
    assert text.startswith("PROPOSED ("), text
    assert fake.puts == [], "preparing files nothing"

    (proposal,) = session.proposals
    record = json.loads(proposal.execution["content"])
    parse_request(proposal.execution["content"].encode("utf-8"))  # the loop's own intake admits it
    assert record["request_id"] == "show-task-expanded-big-screen"
    assert record["target_branch"] == "clive/objective/show-task-expanded-big-screen"
    # The trunk's head, named by its SHA so a trunk that moves on cannot unresolve it.
    assert record["base_sha"] == TRUNK_SHA and record["base_ref"] == TRUNK_SHA
    added = "crooks-assistant/tests/test_show_task_expanded_big_screen.py"
    assert record["allowed_paths"] == ["crooks-assistant/app/scenes", "crooks-assistant/web/alpha.js", added]
    assert record["checks"] == [
        {"name": "tests", "argv": [CHECK_PYTHON, "-m", "pytest", "-q", "tests/test_show_task_expanded_big_screen.py",
                                   "tests/test_web.py"], "cwd": "crooks-assistant"},
        {"name": "regression", "argv": [CHECK_PYTHON, "-m", "pytest", "-q", "-m", "not live", *engineering_tools.REGRESSION_TESTS],
         "cwd": "crooks-assistant"},
        {"name": "ruff", "argv": [CHECK_PYTHON, "-m", "ruff", "check", "app", "config", "scripts", "tests"],
         "cwd": "crooks-assistant"},
    ]
    assert record["acceptance_criteria"][-1] == f"The change is proven by tests in {added}, and they pass."

    card = registry.get("submit_engineering_request").write.present(proposal)
    facts = {fact["label"]: fact["value"] for fact in card["facts"]}
    assert facts["Base"] == f"clive/trunk at {TRUNK_SHA[:12]}"
    assert facts["Filed as"] == f"requests/show-task-expanded-big-screen.json on {INBOX}"

    _, result = await _file(engine, session)
    assert result.code == "verified", result
    assert fake.files["requests/show-task-expanded-big-screen.json"] == proposal.execution["content"].encode()

    linked = objectives.get(obj.id)
    assert linked.kind == "build"
    assert [(e["request_id"], e["host"], e["target_branch"]) for e in linked.engineering] == [
        ("show-task-expanded-big-screen", HOST, "clive/objective/show-task-expanded-big-screen")]
    (item,) = linked.items
    assert item["state"] == "started" and item["engineering"] == "show-task-expanded-big-screen"
    assert linked.summary()["kind"] == "build"
    assert any(e["kind"] == "engineering" for e in linked.events)


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_named_tests_are_the_ones_run(fake, bound):
    session = Session(session_id="named")
    await _prepare(session, allowed_paths=["app/fastpath", "tests/test_fastpath.py"])
    (proposal,) = session.proposals
    record = json.loads(proposal.execution["content"])
    assert record["allowed_paths"] == ["crooks-assistant/app/fastpath", "crooks-assistant/tests/test_fastpath.py"]
    assert record["checks"][0]["argv"][-1] == "tests/test_fastpath.py"
    assert not any("proven by tests" in c for c in record["acceptance_criteria"])


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_a_title_asked_again_steps_to_the_next_id(fake, bound):
    fake.files["requests/show-task-expanded-big-screen.json"] = b"{}\n"
    session = Session(session_id="again")
    await _prepare(session)
    (proposal,) = session.proposals
    assert proposal.execution["request_id"] == "show-task-expanded-big-screen-2"


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_an_id_the_model_chose_is_used_once(fake, bound):
    fake.files["requests/big-screen-slips.json"] = b"{}\n"
    session = Session(session_id="taken")
    out = await _prepare(session, request_id="big-screen-slips")
    assert out.startswith("ERROR:") and "already on the engineering inbox" in out
    assert session.proposals == [] and fake.puts == []


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_an_unknown_objective_or_a_protected_path_prepares_nothing(fake, bound, objectives):
    session = Session(session_id="refused")
    out = await _prepare(session, objective_id="obj_00000000")
    assert out.startswith("ERROR:") and "objective_list" in out
    out = await dispatch("submit_engineering_request", ask(allowed_paths=["app/tools/gate.py"]), session=session, timeout_s=5)
    assert out.startswith("ERROR: The request was refused") and "protects" in out and "gate.py" not in out
    assert session.proposals == [] and fake.puts == []


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_a_failed_link_never_undoes_the_filing(fake, bound, objectives, engine, monkeypatch):
    obj = objectives.create(title="Expanded task display", request="Show a task large on the Mac")
    session = Session(session_id="link")
    await _prepare(session, objective_id=obj.id)

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(objectives, "link_engineering", broken)
    _, result = await _file(engine, session)
    assert result.code == "verified" and len(fake.files) == 1


# ------------------------------------------------------------------ progress on the owner's screen


async def test_build_progress_reads_the_loop_at_most_once_a_minute(fake, bound, monkeypatch):
    fake.status["requests"] = [{"request_id": "show-task-expanded-big-screen", "stage": "RUNNING"}]
    now = [100.0]
    monkeypatch.setattr(engineering_tools.time, "monotonic", lambda: now[0])
    rows = await engineering_tools.build_progress(["show-task-expanded-big-screen", "not-yet-seen"])
    assert rows["show-task-expanded-big-screen"]["progress"] == "building"
    assert rows["not-yet-seen"]["progress"] == "queued"
    await engineering_tools.build_progress(["show-task-expanded-big-screen"])
    assert fake.status_reads == 1
    now[0] += engineering_tools.PROGRESS_TTL_S + 1
    await engineering_tools.build_progress(["show-task-expanded-big-screen"])
    assert fake.status_reads == 2


async def test_build_progress_says_nothing_when_github_is_down(fake, bound):
    fake.down = True
    assert await engineering_tools.build_progress(["show-task-expanded-big-screen"]) == {}


async def test_the_builds_route_lists_each_build_objectives_requests(fake, bound, objectives):
    obj = objectives.create(title="Expanded task display", request="Show a task large on the Mac")
    objectives.create(title="T-shirt week", request="Launch fourteen designs")
    objectives.link_engineering(obj.id, request_id="show-task-expanded-big-screen", host=HOST,
                                target_branch="clive/objective/show-task-expanded-big-screen")
    fake.status["requests"] = [{"request_id": "show-task-expanded-big-screen", "stage": "REVIEWING"}]
    out = await objectives_route.builds()
    assert list(out["builds"]) == [obj.id]
    (row,) = out["builds"][obj.id]
    assert row["progress"] == "in review"


def test_the_prompt_tells_clive_how_to_file_a_build(tmp_path):
    from app.kb.loader import build_system_prompt, load

    prompt = build_system_prompt(load(tmp_path))
    assert "kind 'build'" in prompt and "submit_engineering_request" in prompt and "areas true" in prompt
    assert "You never write code" in prompt
