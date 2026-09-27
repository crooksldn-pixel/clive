"""What CLIVE's engineering bridge's own code can and cannot do (the 2026-09-27 deploy review,
F-ENG). One test per bound, each against the code as it is, and the rest of the evidence named
where it already lives. What these tests cannot show is what the token could do outside this
code: clive/trunk has no branch protection (the repository's plan does not offer it on a private
repository), so a Contents-write token could reach the trunk if it were used by anything else.
That is why the bridge stays out of production, its credential parked, until the token cannot
write to the repository the trunk lives in (round 6); nothing here claims otherwise.

- It cannot widen its own paths. A request naming anything the loop protects is refused here and
  again by the loop's own door; and the bridge's own code (what it may name, which checks it
  builds, which base it reads, where it writes) is itself protected, with its tests, so no build
  it files can loosen the rules the next one is held to.
- It cannot choose its checks or pick its base. The tool takes neither (test_engineering_bridge.py
  `test_a_caller_can_name_neither_its_base_nor_its_checks`); the checks are built from fixed
  commands and always include the protected regression modules; the base is the trunk's head
  read at preparation, by SHA.
- Its code sends one write only. The only write it makes is one new file, requests/<id>.json,
  on its inbox branch, create-only, after the owner's tap; everything else it sends is a read.
  The loop publishes the work to clive/objective/<id> and nowhere else, and production takes
  only an exact trunk SHA after review. It has no HTTP route of its own. (Not claimed: that the
  trunk itself refuses a direct push. It does not; see above.)
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.engineering_bridge import github
from app.engineering_bridge.requests import RequestRefused, build_request
from app.orchestrator.objectives import PROTECTED_PATHS, Objective, OwnerEntry, protected_paths_in
from app.remote_engineering.errors import RequestSchemaError
from app.remote_engineering.requests import parse_request
from app.session.models import Session
from app.tools import engineering_tools
from app.tools.dispatch import dispatch
from app.tools.gate import Tier
from app.tools.registry import get as spec_of
from tests.test_engineering_bridge import (  # noqa: F401 - fixtures
    BASE_SHA,
    HEAD,
    REPO,
    SUBMIT_TOOL,
    ask,
    bound,
    clock,
    engine,
    fake,
    fields,
    inbox,
)

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "crooks-assistant"
BRIDGE_FILES = ("crooks-assistant/app/engineering_bridge/__init__.py", "crooks-assistant/app/engineering_bridge/github.py",
                "crooks-assistant/app/engineering_bridge/requests.py", "crooks-assistant/app/tools/engineering_tools.py")


# ------------------------------------------------------------------ it cannot widen its own paths


def test_the_bridges_own_rules_and_their_tests_are_out_of_every_build():
    """A build CLIVE files may not change the code that decides what a build may change, how it
    is checked, where it starts, or where it is written: the bridge, the loop's door and schema,
    and the acceptance run. Nor the tests that hold them."""
    for path in (*BRIDGE_FILES, "crooks-assistant/app/orchestrator/objectives.py",
                 "crooks-assistant/app/remote_engineering/requests.py", "crooks-assistant/scripts/acceptance_provenance.py",
                 ".github/workflows", "crooks-assistant/tests/test_engineering_bridge.py",
                 "crooks-assistant/tests/test_build_from_clive.py", "crooks-assistant/tests/test_engineering_bridge_bounds.py"):
        assert (ROOT / path).exists(), path
        assert protected_paths_in([path]), f"{path} must be protected"
    assert not [a for a in engineering_tools.buildable_areas() if protected_paths_in([a])]
    assert not [a for a in engineering_tools.buildable_areas() if "engineering_bridge" in a or a.endswith("engineering_tools.py")]


@pytest.mark.parametrize("path", [*PROTECTED_PATHS, *[f"{p}/new_file.py" for p in PROTECTED_PATHS[:5]],
                                  "crooks-assistant/app/engineering_bridge/requests.py", "crooks-assistant/app/tools",
                                  "crooks-assistant/app", "crooks-assistant"])
def test_no_protected_path_nor_anything_holding_one_can_be_named(path):
    with pytest.raises(RequestRefused, match="overlaps a path the loop protects"):
        build_request(**fields(allowed_paths=["crooks-assistant/app/support", path]))


def test_the_loops_own_door_refuses_them_even_if_the_bridge_did_not():
    """Defence in depth: a record built by hand, past the bridge's own check, is refused by the
    objective door the loop puts every request through (protected code, pinned by the owner)."""
    record = json.loads(build_request(**fields(allowed_paths=["crooks-assistant/app/support"])).content)
    for path in ("crooks-assistant/app/engineering_bridge", "crooks-assistant/app/tools/engineering_tools.py",
                 "crooks-assistant/app/actions", ".github/workflows/acceptance.yml"):
        record["allowed_paths"] = ["crooks-assistant/app/support", path]
        parsed = parse_request((json.dumps(record, indent=2) + "\n").encode())
        with pytest.raises(ValueError, match="no objective may put in scope"):
            Objective(
                objective_id=parsed.request_id, title=parsed.title, requested_outcome=parsed.requested_outcome,
                acceptance_criteria=parsed.acceptance_criteria, checks=parsed.checks, repository=REPO,
                base_ref=parsed.base_ref, base_sha=parsed.base_sha, target_branch=parsed.target_branch,
                product_memory_sha="b" * 40, allowed_paths=parsed.allowed_paths,
                max_repair_rounds=parsed.max_repair_rounds, owner=OwnerEntry(os_user="owner", host="mac"),
                created_at="2026-09-27T12:00:00+00:00",
            )


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_through_the_tool_a_protected_path_prepares_nothing_and_sends_no_write(fake, bound):  # noqa: F811 - fixtures imported from the suite they belong to
    session = Session(session_id="eng-widen")
    await dispatch("engineering_status", {}, session=session, timeout_s=5)
    for path in ("app/engineering_bridge", "app/tools/engineering_tools.py", "app/orchestrator/objectives.py", "tests/conftest.py"):
        out = await dispatch(SUBMIT_TOOL, {"inbox_id": HEAD, **ask(allowed_paths=[path])}, session=session, timeout_s=5)
        assert out.startswith("ERROR: The request was refused") and "protects" in out, (path, out)
    assert session.proposals == [] and fake.puts == []


# ------------------------------------------------------------------ it cannot choose its checks or pick its base


def test_the_tool_has_no_argument_for_a_base_a_check_a_branch_or_a_repository():
    spec = spec_of(SUBMIT_TOOL)
    offered = set(spec.input_schema["properties"])
    assert offered == {"inbox_id", "title", "requested_outcome", "allowed_paths", "acceptance_criteria",
                       "objective_id", "request_id", "max_repair_rounds"}
    assert spec.tier is Tier.RED and spec.issued_id_args == ("inbox_id",) and spec.write is not None
    assert spec.write.interaction == "tap_commit" and spec.write.reversible is False


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_base_is_the_trunks_head_read_at_preparation_by_sha(fake, bound):  # noqa: F811 - fixtures imported from the suite they belong to
    session = Session(session_id="eng-base")
    await dispatch("engineering_status", {}, session=session, timeout_s=5)
    out = await dispatch(SUBMIT_TOOL, {"inbox_id": HEAD, **ask()}, session=session, timeout_s=5)
    assert out.startswith("PROPOSED"), out
    record = json.loads(session.proposals[-1].execution["content"])
    assert record["base_ref"] == record["base_sha"] == BASE_SHA, "the trunk's head, named by SHA"
    names = [c["name"] for c in record["checks"]]
    assert names == ["tests", "regression", "ruff"]
    regression = record["checks"][1]["argv"]
    assert all(t in regression for t in engineering_tools.REGRESSION_TESTS)


# ------------------------------------------------------------------ it cannot reach production


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_everything_the_bridge_sends_is_a_read_or_one_create_on_its_inbox(fake, bound, engine, clock):  # noqa: F811 - fixtures imported from the suite they belong to
    """Every HTTP request of a whole filing, from status to the owner's tap to the read-back:
    reads of the status, the inbox and trunk heads, and the request file; one PUT of a new
    requests/<id>.json on the inbox branch, with no blob sha (so it cannot replace a file).
    Never a ref update, a merge, a pull request, a workflow, a release or a deployment."""
    from tests.test_engineering_bridge import _authorise, _staged

    session = Session(session_id="eng-reach")
    await _staged(session)
    proposal = session.proposals[-1]
    result = await _authorise(engine, clock, session, proposal)
    assert str(getattr(result, "status", "")).endswith("VERIFIED") or fake.puts, result
    reads = {f"/repos/{REPO}/contents/status.json", f"/repos/{REPO}/git/ref/heads/{github.INBOX_BRANCH}",
             f"/repos/{REPO}/git/ref/heads/clive/trunk"}
    request_file = f"/repos/{REPO}/contents/{proposal.execution['path']}"
    for call in fake.calls:
        if call.method == "GET":
            assert call.url.path in reads or call.url.path.startswith(f"/repos/{REPO}/contents/requests/"), call.url.path
            if call.url.path.startswith(f"/repos/{REPO}/contents/"):
                assert call.url.params.get("ref") in (github.INBOX_BRANCH, github.STATUS_BRANCH)
        else:
            assert call.method == "PUT" and call.url.path == request_file, (call.method, call.url.path)
    assert len(fake.puts) == 1
    (put,) = fake.puts
    assert set(put) == {"message", "content", "branch"} and put["branch"] == github.INBOX_BRANCH
    filed = json.loads(fake.files[proposal.execution["path"]])
    assert filed["target_branch"] == f"clive/objective/{filed['request_id']}"


def test_the_loop_publishes_a_request_nowhere_but_its_own_objective_branch():
    record = json.loads(build_request(**fields()).content)
    for branch in ("clive/trunk", "main", "clive/control/owner-inbox", "clive/objective/something-else"):
        record["target_branch"] = branch
        with pytest.raises(RequestSchemaError):
            parse_request((json.dumps(record, indent=2) + "\n").encode())


def test_every_inbox_is_a_control_branch_and_never_the_trunk():
    assert github.branches_for(github.DEFAULT_HOST) == (github.INBOX_BRANCH, github.STATUS_BRANCH)
    for host in ("worker-01", "trunk", "main", "owner-2"):
        inbox_branch, status_branch = github.branches_for(host)
        assert inbox_branch == f"clive/control/{host}-inbox" and status_branch == f"clive/control/{host}-status"
    for bad in ("../trunk", "Clive", "a b", "x/y", "", "-x"):
        with pytest.raises(ValueError):
            github.branches_for(bad)


def test_the_client_can_only_send_get_and_put_and_follows_no_redirect():
    """Read from the source: the one place an HTTP request leaves the bridge, the methods it is
    ever given, and nowhere else it could go."""
    source = (APP / "app" / "engineering_bridge" / "github.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    methods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "_call" and len(node.args) >= 2:
            method = node.args[1]
            assert isinstance(method, ast.Constant), "every method is a literal"
            methods.add(method.value)
    assert methods == {"GET", "PUT"}
    assert source.count("client.request(") == 1 and "follow_redirects=False" in source
    assert github.API_URL == "https://api.github.com" and github.DEFAULT_REPOSITORY == "crooksldn-pixel/clive"
    for word in ("/merges", "/pulls", "/actions/", "/deployments", "/releases", "/git/refs", "/dispatches"):
        assert word not in source, word
    # The one write's body: a message, the content and the inbox branch; never a sha or a force.
    (put_body,) = [node for node in ast.walk(tree) if isinstance(node, ast.Dict)
                   and {getattr(k, "value", None) for k in node.keys} >= {"content", "branch"}]
    assert {k.value for k in put_body.keys} == {"message", "content", "branch"}


def test_the_bridge_has_no_route_and_nothing_else_writes_through_it():
    """Driven by in-process tools only: no HTTP route imports the client or files a request,
    and the only callers of create_request are the tool's own execute step."""
    callers = []
    for path in (APP / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "create_request(" in text:
            callers.append(path.relative_to(APP).as_posix())
    assert sorted(callers) == ["app/engineering_bridge/github.py", "app/tools/engineering_tools.py"]
    for route in (APP / "app" / "routes").glob("*.py"):
        text = route.read_text(encoding="utf-8")
        assert "EngineeringInbox" not in text and "create_request" not in text and "submit_engineering_request" not in text, route.name
