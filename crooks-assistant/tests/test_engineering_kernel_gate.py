"""The kernel CLI's verdict and integrate verbs hold the GitHub acceptance gate, as the dispatcher does.

A ``ready`` verdict records an acceptance and ``integrate`` records a landing; the owner's loop update
(OWNER_DECISIONS_2026-09-25.md) allows either only after a green GitHub acceptance run on the exact SHA,
whoever records it. The task is brought to review by the real dispatcher (tests/test_engineering_dispatcher.py's
World); the verbs then run through the real CLI against the same store, with a gate double for GitHub.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.orchestrator.contracts import TaskStatus
from app.orchestrator.dispatcher import runtime_lock
from app.orchestrator.github_acceptance import GateState
from app.orchestrator.lifecycle import VerdictOutcome, sha256_of
from scripts import engineering_kernel as kernel_cli
from tests.test_engineering_dispatcher import EDIT_HELLO, OBJ, FakeAcceptance, World, latest_attempt


def _reviewing(tmp_path: Path, monkeypatch, state: GateState) -> tuple[World, FakeAcceptance, str]:
    w = World(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))      # the dispatcher's own gate was green for dispatch
    gate = FakeAcceptance(state)
    monkeypatch.setattr(kernel_cli, "acceptance_gate", lambda args: gate)
    [result] = w.store.read_results()
    return w, gate, result.result_sha


def _cli(w: World, *verb: str) -> int:
    return kernel_cli.run(["--store", str(w.store.root), "--repo", str(w.repo), "--no-journal",
                           "--runtime-root", str(w.tmp / "runtime"), "--lock-timeout", "0.5", *verb])


def _verdict(w: World, sha: str, verdict: str = "ready") -> int:
    evidence = w.tmp / f"verdict-{verdict}.txt"
    evidence.write_text(f"{verdict}: reviewed {sha} by hand\n")
    attempt = latest_attempt(w)
    return _cli(w, "verdict", "--attempt-id", attempt.attempt_id, "--reviewer-principal", "gpt",
                "--reviewer-session", "gpt-manual-review", "--reviewer-workspace-id", "gpt-ro-checkout",
                "--reviewer-workspace-branch", "review", "--reviewer-workspace-head", sha, "--reviewer-read-only",
                "--verdict", verdict, "--observed-sha", sha, "--evidence", str(evidence), "--current-head", sha)


def _integrate(w: World, sha: str, *extra: str) -> int:
    return _cli(w, "integrate", "--task-id", OBJ, "--revision", "1", "--integration-sha", sha,
                "--target-base-sha", w.base, "--method", "fast_forward", "--integrated-by", "owner", *extra)


def _recorded(w: World) -> tuple[dict, dict]:
    attempt = latest_attempt(w)
    notes = json.loads((w.tmp / "runtime" / "attempts" / f"{attempt.attempt_id}.json").read_text())
    evidence = json.loads((w.tmp / "runtime" / "evidence" / attempt.attempt_id / "github-acceptance.json").read_text())
    return notes["github_acceptance"], evidence


@pytest.mark.parametrize("state", [GateState.RED, GateState.PENDING, GateState.MISSING, GateState.UNAVAILABLE])
def test_a_ready_verdict_by_hand_is_refused_until_the_exact_candidate_is_green(tmp_path, monkeypatch, capsys, state):
    w, gate, sha = _reviewing(tmp_path, monkeypatch, state)
    attempt = latest_attempt(w)

    rc = _verdict(w, sha)

    err = capsys.readouterr().err
    assert rc == 2
    assert f"REFUSED: GitHub acceptance is not green on {sha} ({state.value}: " in err
    assert "a READY verdict is admitted only after a green GitHub acceptance run on that exact SHA" in err
    assert "Nothing was written to the store" in err and "Next: " in err
    assert gate.asked == [("crooksldn-pixel/clive", sha)]
    assert not w.store.read_admissions(OBJ, attempt.attempt_id) and not w.store.read_acceptances(OBJ)
    assert w.store.read_task_state(OBJ, 1).status is TaskStatus.REVIEWING
    # recorded where the dispatcher records its own answers, so the status projection shows it
    notes, evidence = _recorded(w)
    assert notes == evidence and evidence["sha"] == sha and evidence["state"] == state.value


def test_a_ready_verdict_by_hand_on_a_green_candidate_records_the_acceptance(tmp_path, monkeypatch, capsys):
    w, _gate, sha = _reviewing(tmp_path, monkeypatch, GateState.GREEN)

    assert _verdict(w, sha) == 0

    out = json.loads(capsys.readouterr().out)
    assert out["record"]["outcome"] == VerdictOutcome.ACCEPTED.value
    assert [(g["sha"], g["state"]) for g in out["github_acceptance"]] == [(sha, "green")]
    assert w.store.read_acceptances(OBJ)[0].accepted_sha == sha
    assert _recorded(w)[1]["green"] is True


def test_a_rejection_by_hand_is_not_held_by_the_gate(tmp_path, monkeypatch):
    w, gate, sha = _reviewing(tmp_path, monkeypatch, GateState.RED)
    assert _verdict(w, sha, "repair_required") == 0
    attempt = latest_attempt(w)
    assert [a.outcome for a in w.store.read_admissions(OBJ, attempt.attempt_id)] == [VerdictOutcome.REJECTED_BY_VERDICT]
    assert gate.asked == []


def test_an_integration_by_hand_lands_only_a_green_sha_and_keeps_the_answer_as_its_gates_evidence(
        tmp_path, monkeypatch, capsys):
    w, gate, sha = _reviewing(tmp_path, monkeypatch, GateState.GREEN)
    assert _verdict(w, sha) == 0
    capsys.readouterr()

    gate.state = GateState.RED                              # e.g. a re-run of the same SHA went red
    assert _integrate(w, sha) == 2
    err = capsys.readouterr().err
    assert f"GitHub acceptance is not green on {sha} (red: " in err and "an integration lands only after" in err
    assert not w.store.read_integrations()
    assert w.store.read_task_state(OBJ, 1).status is TaskStatus.ACCEPTED

    gate.state = GateState.GREEN
    operator = w.tmp / "provenance.json"
    operator.write_text('{"acceptance": "the CI artifact the owner kept"}\n')
    assert _integrate(w, sha, "--gates-evidence", str(operator)) == 0
    [integration] = w.store.read_integrations()
    attempt = latest_attempt(w)
    kept = (w.tmp / "runtime" / "evidence" / attempt.attempt_id / "integration-gates.json").read_bytes()
    assert integration.gates_evidence_sha256 == sha256_of(kept)
    document = json.loads(kept)
    assert [(g["sha"], g["green"]) for g in document["github_acceptance"]] == [(sha, True)]
    assert document["operator_gates_evidence_sha256"] == sha256_of(operator.read_bytes())
    assert gate.asked[-1] == ("crooksldn-pixel/clive", sha)


def test_an_integration_by_hand_of_a_task_that_was_never_accepted_asks_nothing_and_writes_nothing(
        tmp_path, monkeypatch, capsys):
    w, gate, sha = _reviewing(tmp_path, monkeypatch, GateState.GREEN)
    w.kernel.cancel_attempt(latest_attempt(w).attempt_id, reason="test: back to READY")
    assert _integrate(w, sha) == 2
    assert "not ACCEPTED" in capsys.readouterr().err
    assert gate.asked == [] and not w.store.read_integrations()


def test_while_a_dispatcher_tick_holds_the_runtime_lock_the_cli_waits_then_refuses(tmp_path, monkeypatch, capsys):
    w, gate, sha = _reviewing(tmp_path, monkeypatch, GateState.GREEN)
    with runtime_lock(w.tmp / "runtime", 1.0):
        rc = _verdict(w, sha)
    assert rc == 4 and "BUSY: " in capsys.readouterr().err
    assert gate.asked == [] and not w.store.read_acceptances(OBJ)


def test_the_kernel_cli_offers_no_flag_round_the_gate():
    parser = kernel_cli.build_parser()
    [verbs] = [action for action in parser._actions if action.choices and "verdict" in action.choices]
    flags = [flag for p in (parser, verbs.choices["verdict"], verbs.choices["integrate"])
             for action in p._actions for flag in action.option_strings]
    assert "--gates-evidence" in flags                      # extra evidence, bound by digest; not a way round
    for word in ("bypass", "skip", "no-gate", "no-acceptance", "force", "unsafe", "ignore"):
        assert not [flag for flag in flags if word in flag]


def test_a_runtime_root_the_gate_cannot_record_into_refuses_before_the_store(tmp_path, monkeypatch, capsys):
    w, _gate, sha = _reviewing(tmp_path, monkeypatch, GateState.GREEN)
    blocked = w.tmp / "not-a-directory"
    blocked.write_text("a file where the runtime root should be\n")
    rc = kernel_cli.run(["--store", str(w.store.root), "--repo", str(w.repo), "--no-journal",
                         "--runtime-root", str(blocked), "verdict", "--attempt-id",
                         latest_attempt(w).attempt_id, "--reviewer-principal", "gpt",
                         "--reviewer-session", "s", "--reviewer-workspace-id", "ro", "--reviewer-workspace-branch",
                         "review", "--reviewer-workspace-head", sha, "--reviewer-read-only", "--verdict", "ready",
                         "--observed-sha", sha, "--evidence", str(blocked), "--current-head", sha])
    assert rc == 2 and "nothing was written to the store" in capsys.readouterr().err
    assert not w.store.read_acceptances(OBJ)
