"""The loop lands its own work on the trunk (OWNER_DECISIONS_2026-09-30, "Filing is switched on, and the loop
lands its own work").

The real dispatcher, kernel, git, builder process (the dispatcher tests' fake ``claude``) and integrator run
against a local bare repository standing in for GitHub: ``origin`` holds ``clive/trunk``, candidates are
published to it, and the landing pushes to it. GitHub acceptance is the dispatcher tests' fake gate. Nothing
here reaches GitHub.

The loop may fast-forward ``clive/trunk`` to exactly a candidate's SHA only when (a) GitHub acceptance is green
on it, asked at that moment; (b) its independent review was READY and the kernel accepted it; (c) the diff from
the trunk head to it touches no protected path; (d) it contains the trunk head, so a plain push fast-forwards.
If the trunk moved, the loop merges it into the objective's branch, and the merge lands only after its own green
run and READY review. A conflict blocks; refreshes are bounded; no push is ever forced; ``--no-land`` is the
loop as it was; a restart between the push and its record lands nothing twice.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.orchestrator import dispatcher as dispatcher_module
from app.orchestrator.contracts import TaskKind, TaskStatus
from app.orchestrator.dispatcher import Dispatcher
from app.orchestrator.github_acceptance import GateState
from tests.test_engineering_dispatcher import FINDING, OBJ, World, _git, review

TRUNK = "clive/trunk"
BRANCH = "clive/objective/demo"
EDIT_HELLO = {"edits": [["pkg/hello.txt", "hello\n"]]}
FORCE = ("--force", "-f", "--force-with-lease", "--force-if-includes", "--mirror", "--delete", "-d")


@pytest.fixture
def pushes(monkeypatch):
    """Every ``git push`` the dispatcher runs during the test, by argv; none may ever be forced. (The tests' own
    set-up pushes, which stand in for other people moving branches, are not the loop's and are not counted.)"""
    seen: list[list[str]] = []
    real = dispatcher_module.subprocess.run

    def run(argv, *args, **kwargs):
        caller = sys._getframe(1).f_globals.get("__name__")
        if caller == dispatcher_module.__name__ and isinstance(argv, list | tuple) and list(argv[:2]) == ["git", "push"]:
            seen.append(list(argv))
        return real(argv, *args, **kwargs)

    monkeypatch.setattr(dispatcher_module.subprocess, "run", run)
    yield seen
    for argv in seen:
        assert not any(word in FORCE or word.startswith(("+", "--force")) for word in argv[2:]), argv
        assert not any(":" in word and word.split(":", 1)[0].startswith("+") for word in argv), argv


def landing_world(tmp_path: Path, **kw) -> World:
    """A World whose dispatcher publishes to, and lands on, a bare ``origin`` whose trunk is the base."""
    w = World(tmp_path, publish_remote="origin", **kw)
    w.origin = tmp_path / "origin.git"
    _git(tmp_path, "clone", "-q", "--bare", str(w.repo), str(w.origin))
    _git(w.repo, "remote", "add", "origin", str(w.origin))
    _git(w.repo, "push", "-q", "origin", f"{w.base}:refs/heads/{TRUNK}")
    w.reviewer.answers.append(lambda ctx: review(ctx))       # every candidate is READY unless a test says otherwise
    return w


def trunk(w: World) -> str:
    return _git(w.origin, "rev-parse", f"refs/heads/{TRUNK}")


def move_trunk(w: World, rel: str, content: str, message: str = "the Director lands something else") -> str:
    """Someone else lands a commit on the trunk: on top of the current origin trunk, pushed there."""
    scratch = w.tmp / f"elsewhere-{len(list(w.tmp.glob('elsewhere-*')))}"
    _git(w.tmp, "clone", "-q", "--branch", TRUNK, str(w.origin), str(scratch))
    (scratch / rel).parent.mkdir(parents=True, exist_ok=True)
    (scratch / rel).write_text(content)
    _git(scratch, "add", "-A")
    _git(scratch, "-c", "user.name=d", "-c", "user.email=d@d", "commit", "-q", "-m", message)
    _git(scratch, "push", "-q", "origin", f"HEAD:refs/heads/{TRUNK}")
    return _git(scratch, "rev-parse", "HEAD")


def landing_record(w: World) -> dict:
    path = w.config.runtime_root / "landings" / f"{OBJ}.json"
    return json.loads(path.read_text()) if path.exists() else {}


def landed(w: World) -> bool:
    return landing_record(w).get("state") == "landed"


def before_landing(d: Dispatcher, hook) -> Dispatcher:
    """Run ``hook(sha)`` once, just before the dispatcher's first landing step looks at the objective."""
    original = d._land
    fired: list[bool] = []

    def land(obj, task, state):
        if not fired:
            integration = next(i for i in d.store.read_integrations()
                               if i.task_id == task.task_id and i.task_revision == task.revision)
            fired.append(True)
            hook(integration.integration_sha)
        return original(obj, task, state)

    d._land = land
    return d


# ---------------------------------------------------------------- a fast-forward lands

def test_a_candidate_that_contains_the_trunk_head_lands_by_a_plain_push_and_the_trunk_is_that_sha(tmp_path, pushes):
    w = landing_world(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(lambda: landed(w))
    [result] = w.store.read_results()
    sha = result.result_sha
    assert trunk(w) == sha and w.stage() == "COMPLETE"
    assert _git(w.origin, "rev-parse", f"refs/heads/{BRANCH}") == sha
    assert [argv for argv in pushes if argv[-1].endswith(f":refs/heads/{TRUNK}")] == \
        [["git", "push", "--quiet", "origin", f"{sha}:refs/heads/{TRUNK}"]]
    record = landing_record(w)
    assert record["sha"] == sha and record["pushing"] is None and record["eligible"] == [sha]
    evidence = json.loads(Path(record["evidence"]).read_text())
    assert evidence["trunk_before"] == w.base and evidence["trunk_after"] == sha
    assert evidence["how"] == "fast-forwarded by the loop with a plain push"
    assert evidence["github_acceptance"]["sha"] == sha and evidence["github_acceptance"]["green"] is True
    assert evidence["review"]["accepted_sha"] == sha and evidence["review"]["reviewer"] == "gpt"
    item = w.dispatcher().status()[0]
    assert item["landing"]["state"] == "landed" and item["landing"]["sha"] == sha and item["landing"]["at"]
    # asked GitHub afresh at landing: a fourth question about the SHA after dispatch, READY and integration
    assert w.acceptance.asked.count(("crooksldn-pixel/clive", sha)) >= 4
    # landed once: later ticks push nothing more
    count = len(pushes)
    for _ in range(3):
        w.dispatcher().tick()
    assert len(pushes) == count and trunk(w) == sha


@pytest.mark.parametrize("state", [GateState.PENDING, GateState.MISSING, GateState.UNAVAILABLE])
def test_a_pending_answer_at_landing_waits_without_pushing_and_lands_once_green(tmp_path, pushes, state):
    w = landing_world(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    d = before_landing(w.dispatcher(), lambda sha: setattr(w.acceptance, "state", state))
    w.run_until(lambda: landing_record(w).get("state") == "waiting" and "waits for a green" in
                landing_record(w).get("reason", ""), dispatcher=d)
    assert trunk(w) == w.base and not [p for p in pushes if TRUNK in p[-1]]
    assert w.dispatcher().status()[0]["landing"]["state"] == "waiting"
    w.acceptance.state = GateState.GREEN
    w.run_until(lambda: landed(w))
    assert trunk(w) == w.store.read_results()[0].result_sha


def test_a_red_answer_at_landing_refuses_it_and_the_trunk_never_moves(tmp_path, pushes):
    w = landing_world(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    d = before_landing(w.dispatcher(), lambda sha: setattr(w.acceptance, "state", GateState.RED))
    w.run_until(lambda: landing_record(w).get("state") == "refused", dispatcher=d)
    sha = w.store.read_results()[0].result_sha
    assert f"GitHub acceptance is red on {sha}" in landing_record(w)["reason"]
    w.acceptance.state = GateState.GREEN
    for _ in range(3):
        w.dispatcher().tick()
    assert trunk(w) == w.base and not [p for p in pushes if TRUNK in p[-1]]
    assert w.stage() == "COMPLETE" and w.dispatcher().status()[0]["landing"]["state"] == "refused"


def test_a_protected_path_anywhere_in_the_diff_from_the_trunk_refuses_the_landing(tmp_path, pushes):
    """(c): the builder cannot change a protected path, but the objective's base can carry one the trunk has not
    got (a Director's branch). Landing checks the whole diff from the trunk head, not only the builder's change."""
    w = landing_world(tmp_path)
    protected = "crooks-assistant/app/orchestrator/dispatcher.py"
    (w.repo / protected).parent.mkdir(parents=True)
    (w.repo / protected).write_text("# the Director's unlanded change to the loop\n")
    _git(w.repo, "add", "-A")
    _git(w.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "director work")
    w.base = _git(w.repo, "rev-parse", "HEAD")                    # the objective starts from it; the trunk has not
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(lambda: landing_record(w).get("state") == "refused")
    reason = landing_record(w)["reason"]
    assert "touches protected path(s)" in reason and protected in reason
    assert trunk(w) != w.store.read_results()[0].result_sha and not [p for p in pushes if TRUNK in p[-1]]


def test_a_base_ahead_of_the_trunk_refuses_the_landing_because_its_commits_were_never_reviewed(tmp_path, pushes):
    """The review packet shows base..candidate. A base ahead of the trunk (a Director's unlanded branch) carries
    commits no reviewer saw, protected or not, so the loop never lands them: only a base already on the trunk."""
    w = landing_world(tmp_path)
    (w.repo / "app_unreviewed.py").write_text("UNREVIEWED = True\n")
    _git(w.repo, "add", "-A")
    _git(w.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "someone's unreviewed work")
    w.base = _git(w.repo, "rev-parse", "HEAD")                    # a descendant of the trunk head, not on it
    before = trunk(w)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(lambda: landing_record(w).get("state") == "refused")
    reason = landing_record(w)["reason"]
    assert f"base {w.base} is not on {TRUNK}" in reason and "never in the loop's review packet" in reason
    assert trunk(w) == before and not [p for p in pushes if TRUNK in p[-1]]
    packets = "\n".join(p.read_text(errors="replace") for p in w.store.root.rglob("*packet*") if p.is_file())
    assert "pkg/hello.txt" in packets and "app_unreviewed.py" not in packets     # what the reviewer saw


# ---------------------------------------------------------------- the trunk moved: the loop's refresh

def test_a_moved_trunk_is_merged_in_and_the_merge_is_accepted_and_reviewed_on_its_own_before_it_lands(
        tmp_path, pushes):
    w = landing_world(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    moved: list[str] = []
    d = before_landing(w.dispatcher(), lambda sha: moved.append(move_trunk(w, "README", "the trunk moved on\n")))
    w.run_until(lambda: landed(w), dispatcher=d, timeout=60)
    first = next(r for r in w.store.read_results() if r.task_revision == 1).result_sha
    r1, r2 = sorted((t for t in w.store.read_tasks() if t.task_id == OBJ), key=lambda t: t.revision)
    assert r2.kind is TaskKind.INTEGRATION and r2.base_sha == moved[0] and r2.target_branch == BRANCH
    assert "refresh 1 of 3" in r2.objective
    merge = next(r for r in w.store.read_results() if r.task_revision == 2).result_sha
    # the merge of the trunk into the objective's branch, made by the loop's integrator, is what landed
    assert _git(w.repo, "rev-list", "--parents", "-n", "1", merge).split()[1:] == [first, moved[0]]
    assert trunk(w) == merge and _git(w.origin, "rev-parse", f"refs/heads/{BRANCH}") == merge
    assert _git(w.repo, "show", f"{merge}:README") == "the trunk moved on"
    assert _git(w.repo, "show", f"{merge}:pkg/hello.txt") == "hello"
    [refresh] = [a for a in w.store.read_attempts(OBJ) if a.task_revision == 2]
    assert refresh.worker.principal.principal_id == "clive-integrator" and w.invocations() == 1
    # its own green run and its own READY review, of exactly the merge SHA
    assert (w.acceptance.asked.count(("crooksldn-pixel/clive", merge))) >= 4
    [dispatch] = w.store.read_dispatches(OBJ, refresh.attempt_id)
    assert dispatch.candidate_sha == merge
    assert sorted(a.accepted_sha for a in w.store.read_acceptances(OBJ)) == sorted([first, merge])
    packet = (w.store.root / dispatch.packet_path).read_text()
    assert "## The loop's refresh before landing" in packet and f"`{TRUNK}` at `{moved[0]}`" in packet
    # the first SHA was never pushed to the trunk: only the merge, once
    assert [p[-1] for p in pushes if p[-1].endswith(f":refs/heads/{TRUNK}")] == [f"{merge}:refs/heads/{TRUNK}"]
    item = w.dispatcher().status()[0]
    assert item["landing"]["state"] == "landed" and item["landing"]["sha"] == merge and item["revision"] == 2


def test_a_refresh_whose_merge_review_asks_for_changes_still_reads_as_refreshing_while_it_is_repaired(
        tmp_path, pushes):
    """The repair of a refresh's merge is still the refresh: the status says so rather than nothing (the #70
    pre-review)."""
    w = landing_world(tmp_path)
    w.scenarios(EDIT_HELLO, {"edits": [["pkg/hello.txt", "hello, merged\n"]]})
    w.reviewer.answers.clear()
    w.reviewer.answers.append(lambda ctx: review(ctx, "CHANGES_REQUIRED", findings=[FINDING]) if ctx.task_revision == 2
                              else review(ctx))
    w.objective()
    d = before_landing(w.dispatcher(), lambda sha: move_trunk(w, "README", "the trunk moved on\n"))
    w.run_until(lambda: any(t.revision == 3 for t in w.store.read_tasks() if t.task_id == OBJ), dispatcher=d,
                timeout=60)
    assert w.store.read_task(OBJ, 2).kind is TaskKind.INTEGRATION and w.store.read_task(OBJ, 3).kind is TaskKind.REPAIR
    item = w.dispatcher().status()[0]
    assert item["revision"] == 3 and item["landing"]["state"] == "refreshing" and item["landing"]["by"] is None
    assert not landed(w) and not [p for p in pushes if TRUNK in p[-1]]


def test_a_refresh_that_conflicts_blocks_for_the_director_and_nothing_lands(tmp_path, pushes):
    w = landing_world(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    d = before_landing(w.dispatcher(), lambda sha: move_trunk(w, "pkg/hello.txt", "bonjour\n"))
    w.run_until(lambda: w.state_of().task_revision == 2 and w.state_of().status is TaskStatus.BLOCKED, dispatcher=d,
                timeout=40)
    reason = w.state_of().blocker_reason
    assert reason.startswith(f"merging the trunk into {BRANCH} conflicts in pkg/hello.txt; the Director resolves it")
    assert w.state_of().blocker_class.value == "deterministic" and not w.state_of().owner_gate
    assert _git(w.origin, "show", f"{TRUNK}:pkg/hello.txt") == "bonjour"
    assert not [p for p in pushes if p[-1].endswith(f":refs/heads/{TRUNK}")]
    landing = w.dispatcher().status()[0]["landing"]
    assert landing["state"] == "refused" and "conflicts in pkg/hello.txt" in landing["reason"]


def test_refreshes_are_bounded(tmp_path, pushes):
    w = landing_world(tmp_path, max_landing_refreshes=1)
    w.scenarios(EDIT_HELLO)
    w.objective()
    d = w.dispatcher()
    original = d._land
    moves: list[str] = []

    def land(obj, task, state):                     # the trunk moves before each landing the loop tries
        if len(moves) < task.revision:
            moves.append(move_trunk(w, f"notes/{task.revision}.txt", f"trunk move {task.revision}\n"))
        return original(obj, task, state)

    d._land = land
    w.run_until(lambda: landing_record(w).get("state") == "refused", dispatcher=d, timeout=60)
    reason = landing_record(w)["reason"]
    assert "the 1 refresh(es) allowed are used (max_landing_refreshes 1)" in reason
    assert [t.kind for t in sorted(w.store.read_tasks(), key=lambda t: t.revision)] == \
        [TaskKind.BUILD, TaskKind.INTEGRATION]
    assert trunk(w) == moves[-1] and not [p for p in pushes if p[-1].endswith(f":refs/heads/{TRUNK}")]


def test_a_generated_file_both_sides_changed_is_regenerated_from_the_merge_not_a_conflict(tmp_path, pushes):
    """The case that blocked six builds on 30 September, at landing: two builds that each add a test both change
    the generated file, so merging the trunk into either conflicts there, and only there. The generated file is the
    loop's: the merge takes the trunk's copy and the loop regenerates it from the merged tree."""
    from tests.test_loop_generated import (
        DECLARATION,
        GENERATOR,
        INDEX,
        INDEX_BASE,
        PKG_INDEX,
        declaration,
    )

    w = landing_world(tmp_path)
    for rel, content in {DECLARATION: declaration(PKG_INDEX), "tools/gen_index.py": GENERATOR, INDEX: INDEX_BASE}.items():
        (w.repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (w.repo / rel).write_text(content)
    _git(w.repo, "add", "-A")
    _git(w.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "declare the loop's generators")
    w.base = _git(w.repo, "rev-parse", "HEAD")
    _git(w.repo, "push", "-q", "origin", f"{w.base}:refs/heads/{TRUNK}")
    w.scenarios({"edits": [["pkg/a.txt", "from the objective\n"]]})
    w.objective()

    def director_lands_b(_sha):
        scratch = w.tmp / "director"
        _git(w.tmp, "clone", "-q", "--branch", TRUNK, str(w.origin), str(scratch))
        (scratch / "pkg" / "b.txt").write_text("from the trunk\n")
        (scratch / INDEX).write_text(INDEX_BASE + "- pkg/b.txt\n")
        _git(scratch, "add", "-A")
        _git(scratch, "-c", "user.name=d", "-c", "user.email=d@d", "commit", "-q", "-m", "b, index regenerated")
        _git(scratch, "push", "-q", "origin", f"HEAD:refs/heads/{TRUNK}")

    d = before_landing(w.dispatcher(), director_lands_b)
    w.run_until(lambda: landed(w) and w.state_of().task_revision >= 3, dispatcher=d, timeout=60)
    landed_sha = trunk(w)
    assert _git(w.repo, "show", f"{landed_sha}:{INDEX}") == "# pkg index\n- pkg/a.txt\n- pkg/b.txt\n- pkg/hello.txt"
    assert _git(w.repo, "log", "-1", "--format=%s", landed_sha) == "Regenerate generated files (loop)"
    merge = _git(w.repo, "rev-parse", f"{landed_sha}^")
    assert len(_git(w.repo, "rev-list", "--parents", "-n", "1", merge).split()) == 3     # the loop's merge commit
    assert "<<<<<<<" not in _git(w.repo, "show", f"{merge}:{INDEX}")
    assert w.dispatcher().status()[0]["generated"] == [INDEX]


# ---------------------------------------------------------------- the switch, restarts, the status contract

def test_no_land_is_the_loop_as_it_was(tmp_path, pushes):
    w = landing_world(tmp_path, land=False)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(lambda: w.stage() == "COMPLETE")
    for _ in range(3):
        w.dispatcher().tick()
    assert trunk(w) == w.base and not [p for p in pushes if TRUNK in p[-1]]
    assert not (w.config.runtime_root / "landings").exists()
    assert [t.revision for t in w.store.read_tasks()] == [1]
    item = w.dispatcher().status()[0]
    assert item["landing"]["state"] == "off" and item["stage"] == "COMPLETE"
    # and turning it on later does not land what was integrated while it was off: that is the Director's
    on = Dispatcher(w.kernel, w.objectives, w.worker(), w.reviewers, dispatcher_module.DispatcherConfig(
        **{**w.config.__dict__, "land": True}), checks=w.runner, acceptance=w.acceptance)
    on.tick()
    assert trunk(w) == w.base and on.status()[0]["landing"] is None


def test_the_no_land_flag_reaches_the_dispatcher_from_both_command_lines(tmp_path):
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / "scripts"))
    try:
        import engineering_dispatcher
        import remote_engineering
    finally:
        sys.path.remove(str(root / "scripts"))
    common = ["--store", str(tmp_path / "store"), "--repo", str(tmp_path), "--runtime-root", str(tmp_path / "rt"),
              "--workspace-root", str(tmp_path / "ws"), "--no-journal", "--publish-remote", "origin"]
    for verb in ("tick", "run"):
        for extra, land in (([], True), (["--no-land"], False)):
            args = engineering_dispatcher.build_parser().parse_args([*common, verb, *extra])
            assert engineering_dispatcher._parts(args)[2].config.land is land, (verb, extra)
    transport = ["--repository", "crooksldn-pixel/clive"]
    for extra, land in (([], True), (["--no-land"], False)):
        args = remote_engineering.build_parser().parse_args([*common, "run", *transport, *extra])
        _store, kernel, objectives, _receipts = remote_engineering._kernel_parts(args)
        assert remote_engineering._dispatcher(args, kernel, objectives).config.land is land
        assert remote_engineering.build_parser().parse_args([*common, "poll", *transport, *extra]).no_land == (not land)


def test_a_restart_between_the_push_and_its_record_lands_once_and_pushes_nothing_again(tmp_path, pushes):
    w = landing_world(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    d = w.dispatcher()

    def crash(*args, **kwargs):
        raise RuntimeError("the host lost power after the push")

    d._record_landed = crash
    with pytest.raises(RuntimeError, match="lost power"):
        w.run_until(lambda: False, dispatcher=d)
    sha = w.store.read_results()[0].result_sha
    assert trunk(w) == sha                                               # pushed...
    record = landing_record(w)
    assert record["state"] == "waiting" and record["pushing"]["sha"] == sha   # ...recorded as intent only
    assert len([p for p in pushes if TRUNK in p[-1]]) == 1
    w.run_until(lambda: landed(w))                                       # a fresh dispatcher: nothing in memory
    assert len([p for p in pushes if TRUNK in p[-1]]) == 1 and trunk(w) == sha
    assert "pushed by the loop before a restart; recorded now and not pushed again" in landing_record(w)["reason"]


def test_a_restart_after_the_intent_but_before_the_push_pushes_that_sha_once(tmp_path, pushes):
    w = landing_world(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    d = w.dispatcher()

    def crash(*args, **kwargs):
        raise RuntimeError("the host lost power before the push")

    d._push_trunk = crash
    with pytest.raises(RuntimeError, match="before the push"):
        w.run_until(lambda: False, dispatcher=d)
    assert trunk(w) == w.base and landing_record(w)["pushing"]["trunk_before"] == w.base
    w.run_until(lambda: landed(w))
    sha = w.store.read_results()[0].result_sha
    assert trunk(w) == sha and [p[-1] for p in pushes if TRUNK in p[-1]] == [f"{sha}:refs/heads/{TRUNK}"]


def _someone_else_puts_it_on_the_trunk(w: World):
    """Before the loop's landing step: another actor pushes the integrated SHA onto the trunk (not the loop)."""
    return lambda sha: _git(w.repo, "push", "-q", "origin", f"{sha}:refs/heads/{TRUNK}")


def test_a_sha_someone_else_put_on_the_trunk_is_never_recorded_as_landed_while_github_is_red(tmp_path, pushes):
    """The 2c8d2caf re-pin review, F-01: a SHA already on the trunk is recorded as landed only on a green answer
    asked at landing, and a trunk another actor advanced is never the loop's landing."""
    w = landing_world(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    put = _someone_else_puts_it_on_the_trunk(w)

    def red_and_put(sha):
        w.acceptance.state = GateState.RED
        put(sha)

    d = before_landing(w.dispatcher(), red_and_put)
    w.run_until(lambda: landing_record(w).get("state") == "refused", dispatcher=d)
    sha = w.store.read_results()[0].result_sha
    reason = landing_record(w)["reason"]
    assert trunk(w) == sha and not [p for p in pushes if TRUNK in p[-1]]
    assert f"{sha} is on {TRUNK} already (someone other than the loop put it there)" in reason
    assert "GitHub acceptance is red on it, asked at landing" in reason and "the loop records no landing" in reason
    assert not list((w.config.runtime_root / "evidence").glob("*/landing.json"))


@pytest.mark.parametrize("first", [GateState.GREEN, GateState.PENDING])
def test_a_sha_someone_else_put_on_the_trunk_is_recorded_on_a_fresh_green_answer_as_not_the_loops(
        tmp_path, pushes, first):
    w = landing_world(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    put = _someone_else_puts_it_on_the_trunk(w)

    def then(sha):
        w.acceptance.state = first
        put(sha)

    d = before_landing(w.dispatcher(), then)
    if first is GateState.PENDING:
        w.run_until(lambda: landing_record(w).get("state") == "waiting", dispatcher=d)
        assert "already (someone other than the loop put it there) and waits for a green" in landing_record(w)["reason"]
        assert not landed(w)
        w.acceptance.state = GateState.GREEN
    w.run_until(lambda: landed(w), dispatcher=d)
    sha = w.store.read_results()[0].result_sha
    record = landing_record(w)
    assert record["by"] == "other" and "put there by someone other than the loop; the loop pushed nothing" in record["reason"]
    assert trunk(w) == sha and not [p for p in pushes if TRUNK in p[-1]]
    [evidence] = list((w.config.runtime_root / "evidence").glob("*/landing.json"))
    answer = json.loads(evidence.read_text())
    assert answer["by"] == "other" and answer["github_acceptance"]["green"] is True and answer["push_argv"] is None


def test_the_loops_interrupted_push_is_recorded_only_on_a_fresh_green_answer(tmp_path, pushes):
    """A restart after the loop's push and before its record: the push stands (git cannot take it back), but the
    landing is recorded only once GitHub is green on it, asked again; red refuses it for the Director."""
    w = landing_world(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    d = w.dispatcher()

    def crash(*args, **kwargs):
        raise RuntimeError("the host lost power after the push")

    d._record_landed = crash
    with pytest.raises(RuntimeError, match="lost power"):
        w.run_until(lambda: False, dispatcher=d)
    sha = w.store.read_results()[0].result_sha
    assert trunk(w) == sha and landing_record(w)["pushing"]["sha"] == sha
    w.acceptance.state = GateState.RED
    w.run_until(lambda: landing_record(w).get("state") == "refused")
    reason = landing_record(w)["reason"]
    assert f"{sha} is on {TRUNK} already (the loop pushed it before a restart)" in reason and "red on it" in reason
    assert len([p for p in pushes if TRUNK in p[-1]]) == 1 and not landed(w)


def test_an_intent_the_loop_never_saw_pushed_is_not_claimed_when_someone_else_lands_that_sha(tmp_path, pushes):
    """The push intent is written before git runs, so it proves nothing about the push. The loop dies before
    pushing, the Director pushes the same SHA by hand: on a fresh green answer it is recorded, but as unconfirmed,
    never as the loop's own landing (the #70 pre-review). Only a push git accepted (``pushed_at``) is the loop's."""
    w = landing_world(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    d = w.dispatcher()

    def crash(*args, **kwargs):
        raise RuntimeError("the host lost power before the push")

    d._push_trunk = crash
    with pytest.raises(RuntimeError, match="before the push"):
        w.run_until(lambda: False, dispatcher=d)
    sha = w.store.read_results()[0].result_sha
    intent = landing_record(w)["pushing"]
    assert intent["sha"] == sha and "pushed_at" not in intent and trunk(w) == w.base
    _git(w.repo, "push", "-q", "origin", f"{sha}:refs/heads/{TRUNK}")          # the Director, by hand
    w.run_until(lambda: landed(w))
    record = landing_record(w)
    assert record["by"] == "unconfirmed" and "whether that push or someone else's put it there cannot be told" in (
        record["reason"])
    assert not [p for p in pushes if TRUNK in p[-1]]                            # the loop pushed nothing at all
    assert w.dispatcher().status()[0]["landing"]["by"] == "unconfirmed"


def test_a_push_git_accepted_is_marked_at_once_so_a_restart_knows_it_was_the_loops(tmp_path, pushes):
    w = landing_world(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    d = w.dispatcher()

    def crash(*args, **kwargs):
        raise RuntimeError("the host lost power after the push")

    d._trunk_after_push = crash                                                  # after git accepted it
    with pytest.raises(RuntimeError, match="after the push"):
        w.run_until(lambda: False, dispatcher=d)
    sha = w.store.read_results()[0].result_sha
    assert trunk(w) == sha and landing_record(w)["pushing"]["pushed_at"]
    w.run_until(lambda: landed(w))
    assert landing_record(w)["by"] == "loop" and len([p for p in pushes if TRUNK in p[-1]]) == 1


def test_a_trunk_moved_away_from_an_interrupted_push_is_never_pushed_to_again(tmp_path, pushes):
    w = landing_world(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    d = w.dispatcher()

    def crash(*args, **kwargs):
        raise RuntimeError("lost before the push")

    d._push_trunk = crash
    with pytest.raises(RuntimeError):
        w.run_until(lambda: False, dispatcher=d)
    moved = move_trunk(w, "README", "someone else's work\n")
    w.run_until(lambda: landing_record(w).get("state") == "refused")
    assert "the loop never pushes it again" in landing_record(w)["reason"]
    assert trunk(w) == moved and not [p for p in pushes if TRUNK in p[-1]]
    assert [t.revision for t in w.store.read_tasks()] == [1]                 # and no refresh either


def test_landing_never_builds_a_forced_push():
    from app.orchestrator.dispatcher import landing_push_argv

    sha = "a" * 40
    assert landing_push_argv("origin", sha) == ["git", "push", "--quiet", "origin", f"{sha}:refs/heads/{TRUNK}"]
    for remote, bad in (("+origin", sha), ("--force", sha), ("origin", "+" + sha[1:]), ("origin", "HEAD"),
                        (None, sha), ("origin", sha + ":refs/heads/main")):
        with pytest.raises(ValueError):
            landing_push_argv(remote, bad)


def test_the_status_rows_carry_attempts_repairs_generated_and_landing(tmp_path, pushes):
    w = landing_world(tmp_path)
    w.scenarios({"edits": [["README", "out of scope\n"]]}, EDIT_HELLO)       # one refused attempt, then a candidate
    before = w.dispatcher().status()
    assert before == []
    w.objective()
    item = w.dispatcher().status()[0]
    assert item["attempts"] == [] and item["repairs"] == {"review": 0, "ci": 0, "max": 2}
    assert item["generated"] == [] and item["landing"] is None
    w.run_until(lambda: landed(w))
    item = w.dispatcher().status()[0]
    first, second = item["attempts"]
    assert set(first) == {"attempt_id", "revision", "outcome", "reason", "at"}
    assert first["outcome"] == "refused" and "outside the objective's scope" in first["reason"]
    assert second["outcome"] == "candidate" and second["reason"] == f"candidate {w.store.read_results()[0].result_sha}"
    assert first["at"] < second["at"] and first["revision"] == second["revision"] == 1
    assert item["repairs"] == {"review": 0, "ci": 0, "max": 2} and item["generated"] == []
    assert set(item["landing"]) == {"state", "sha", "at", "reason", "by"} and item["landing"]["state"] == "landed"
    assert item["landing"]["by"] == "loop"                                   # the loop's own plain push
    # every key the status had before is still there
    for key in ("objective_id", "title", "task_id", "revision", "kind", "stage", "stage_reason", "attempt_id",
                "worker", "last_heartbeat", "last_progress", "lease", "candidate_sha", "review", "acceptance",
                "integration", "blocker", "blocker_class", "next_action", "process", "review_mechanism",
                "github_acceptance"):
        assert key in item, key
    json.dumps(item, default=str)


def test_a_waiting_landing_is_bounded(tmp_path, pushes):
    from datetime import timedelta

    w = landing_world(tmp_path, acceptance_timeout_s=600)
    w.scenarios(EDIT_HELLO)
    w.objective()
    d = before_landing(w.dispatcher(), lambda sha: setattr(w.acceptance, "state", GateState.PENDING))
    w.run_until(lambda: landing_record(w).get("state") == "waiting" and landing_record(w).get("waiting_since"),
                dispatcher=d)
    w.clock.offset += timedelta(seconds=601)
    w.dispatcher().tick()
    assert landing_record(w)["state"] == "refused" and "not landed within 600s" in landing_record(w)["reason"]
    assert trunk(w) == w.base


def test_the_trunk_as_a_builders_target_is_still_refused_with_landing_on(tmp_path):
    w = landing_world(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective(target_branch=TRUNK)
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    assert "never publishes a candidate onto" in w.state_of().blocker_reason and w.invocations() == 0
    assert trunk(w) == w.base and w.dispatcher().status()[0]["landing"] is None      # nothing to land


# ---------------------------------------------------------------- the long-lived `run`, restarted on existing state
#
# A restart proven on ``tick`` is not a restart of the long-lived mode (the strict reviewer's CHANGES_REQUIRED). Here
# a previous life of the loop leaves the store, runtime notes and landing record (the real dispatcher writes them,
# crashed at a monkeypatched point where the case needs it), and ``engineering_dispatcher.py run`` itself takes them
# up: its parser, its ``_parts`` and its termination rule. Three things the CLI builds are the world's instead: the
# GitHub gate (the fake: nothing reaches GitHub and no credential is asked for), the kernel's clock, and the sleep
# between ticks, which moves that clock by the interval rather than waiting it out (GitHub is asked about a SHA at
# most once per ``acceptance_poll_s``, 60s, which is not a CLI flag).


def _dispatcher_run(w: World, monkeypatch, on_sleep=lambda seconds: None, *, max_ticks: int = 8) -> int:
    """``engineering_dispatcher.py ... run`` as a host starts it, on the world's store, repository, runtime,
    workspaces and fake builder. ``on_sleep`` sees each sleep between ticks; the interval is 61s of world time."""
    from datetime import timedelta
    from functools import partial
    from types import SimpleNamespace

    from app.orchestrator.lifecycle import Kernel
    from scripts import engineering_dispatcher as cli

    def sleep(seconds: float) -> None:
        on_sleep(seconds)
        w.clock.offset += timedelta(seconds=seconds)

    monkeypatch.setattr(cli, "GitHubAcceptance", lambda _token: w.acceptance)
    monkeypatch.setattr(cli, "git_remote_token", lambda _repo, _remote: (lambda _repository: None))
    monkeypatch.setattr(cli, "Kernel", partial(Kernel, clock=w.clock))
    monkeypatch.setattr(cli, "time", SimpleNamespace(sleep=sleep))
    return cli.run(["--store", str(w.store.root), "--repo", str(w.repo), "--runtime-root", str(w.config.runtime_root),
                    "--workspace-root", str(w.config.workspace_root), "--no-journal", "--publish-remote", "origin",
                    "--worker-cli", str(w.cli), "run", "--interval", "61", "--max-ticks", str(max_ticks)])


def _trunk_pushes(pushes: list[list[str]]) -> list[str]:
    return [argv[-1] for argv in pushes if argv[-1].endswith(f":refs/heads/{TRUNK}")]


def test_run_restarted_on_a_completed_objective_still_waiting_to_land_ticks_on_and_exits_once_it_lands(
        tmp_path, pushes, monkeypatch, capsys):
    """``run`` stops once every objective is COMPLETE, BLOCKED or at OWNER_GATE, but a COMPLETE objective whose
    landing still waits (here for a green run on its integrated SHA) is not finished. Restarted on that store, ``run``
    keeps ticking through the wait, lands it once GitHub is green, and then stops by its own rule, not --max-ticks."""
    w = landing_world(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    d = before_landing(w.dispatcher(), lambda sha: setattr(w.acceptance, "state", GateState.PENDING))
    w.run_until(lambda: landing_record(w).get("state") == "waiting" and "waits for a green" in
                landing_record(w).get("reason", ""), dispatcher=d)
    sha = w.store.read_results()[0].result_sha
    assert w.stage() == "COMPLETE" and trunk(w) == w.base and not _trunk_pushes(pushes)
    assert w.dispatcher().status()[0]["landing"]["state"] == "waiting"
    capsys.readouterr()

    between: list[tuple[str, str, str]] = []

    def on_sleep(_seconds):
        between.append((w.stage(), landing_record(w)["state"], trunk(w)))
        if len(between) == 2:
            w.acceptance.state = GateState.GREEN                 # GitHub's run on the SHA finishes green

    assert _dispatcher_run(w, monkeypatch, on_sleep) == 0
    out = capsys.readouterr().out
    # it slept twice with the objective COMPLETE and its landing waiting, rather than stopping at COMPLETE...
    assert between == [("COMPLETE", "waiting", w.base)] * 2
    # ...landed on the third tick, with one plain push of exactly the SHA, and stopped there (well inside 8 ticks)
    assert landed(w) and landing_record(w)["by"] == "loop" and trunk(w) == sha
    assert _trunk_pushes(pushes) == [f"{sha}:refs/heads/{TRUNK}"]
    assert f"LANDED {sha} on {TRUNK} (fast-forwarded by the loop with a plain push); not deployed" in out
    assert out.rstrip().endswith(json.dumps({OBJ: "COMPLETE"}, indent=2))


def test_run_restarted_on_a_push_intent_from_before_a_crash_pushes_once_and_records_it_as_the_loops(
        tmp_path, pushes, monkeypatch, capsys):
    """The previous life recorded its intent to push and died before git ran: the trunk is unchanged and the intent
    has no ``pushed_at``. ``run`` restarted on that store asks GitHub again, waits through a pending answer with the
    intent still on record and nothing pushed, then pushes exactly once, records the landing as the loop's own and
    stops. Restarted once more, it pushes nothing and stops after one tick."""
    w = landing_world(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    d = w.dispatcher()

    def crash(*args, **kwargs):
        raise RuntimeError("the host lost power before the push")

    d._push_trunk = crash
    with pytest.raises(RuntimeError, match="before the push"):
        w.run_until(lambda: False, dispatcher=d)
    sha = w.store.read_results()[0].result_sha
    record = landing_record(w)
    assert record["state"] == "waiting" and record["pushing"]["sha"] == sha
    assert record["pushing"]["trunk_before"] == w.base and "pushed_at" not in record["pushing"]
    assert trunk(w) == w.base and w.stage() == "COMPLETE" and not _trunk_pushes(pushes)
    capsys.readouterr()

    w.acceptance.state = GateState.PENDING                        # asked afresh after the restart: a re-run is going
    between: list[tuple[str, str | None, str]] = []

    def on_sleep(_seconds):
        record = landing_record(w)
        between.append((record["state"], (record.get("pushing") or {}).get("sha"), trunk(w)))
        w.acceptance.state = GateState.GREEN

    assert _dispatcher_run(w, monkeypatch, on_sleep) == 0
    out = capsys.readouterr().out
    assert between == [("waiting", sha, w.base)]                   # one waiting tick: intent kept, nothing pushed
    assert _trunk_pushes(pushes) == [f"{sha}:refs/heads/{TRUNK}"] and trunk(w) == sha
    record = landing_record(w)
    assert record["state"] == "landed" and record["sha"] == sha and record["by"] == "loop" and record["pushing"] is None
    evidence = json.loads(Path(record["evidence"]).read_text())
    assert evidence["by"] == "loop" and evidence["how"] == "fast-forwarded by the loop with a plain push"
    assert evidence["trunk_before"] == w.base and evidence["trunk_after"] == sha
    assert evidence["push_argv"] == ["git", "push", "--quiet", "origin", f"{sha}:refs/heads/{TRUNK}"]
    assert w.dispatcher().status()[0]["landing"]["by"] == "loop"
    assert f"LANDED {sha} on {TRUNK}" in out and out.rstrip().endswith(json.dumps({OBJ: "COMPLETE"}, indent=2))

    def must_not_sleep(_seconds):
        raise AssertionError("with its one objective landed, run must stop after its first tick")

    assert _dispatcher_run(w, monkeypatch, must_not_sleep) == 0
    assert _trunk_pushes(pushes) == [f"{sha}:refs/heads/{TRUNK}"] and landing_record(w) == record
