"""The CI workflow is configuration, and configuration drifts silently.

The properties tested here are the ones whose loss would not make CI red — it
would make CI *wrong*: a run that tests the branch tip instead of the commit it
was triggered for, a scanner installed at "latest", a token with write
permissions, or a workflow that has stopped invoking the provenance script at
all. Each of those would keep passing while proving less.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
ACCEPTANCE = WORKFLOWS / "acceptance.yml"


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(ACCEPTANCE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def steps(workflow: dict) -> list[dict]:
    return workflow["jobs"]["acceptance"]["steps"]


def step_named(steps: list[dict], fragment: str) -> dict:
    for step in steps:
        if fragment.lower() in (step.get("name") or "").lower():
            return step
    raise AssertionError(f"no step whose name contains {fragment!r}")


def test_the_workflow_exists_and_parses(workflow: dict) -> None:
    assert ACCEPTANCE.is_file()
    assert list(workflow["jobs"]) == ["acceptance"]


def test_the_checkout_is_pinned_to_the_triggering_commit(steps: list[dict]) -> None:
    """Without an explicit ref, ``actions/checkout`` takes the branch tip — so
    the evidence would describe whatever landed most recently, not the commit
    the run claims to be about."""

    checkout = step_named(steps, "check out")
    assert checkout["uses"].startswith("actions/checkout@")

    ref = checkout["with"]["ref"]
    assert "github.event.pull_request.head.sha" in ref
    assert "github.sha" in ref
    assert "github.ref" not in ref
    assert "head_ref" not in ref


def test_the_checkout_keeps_enough_history_to_scan_a_range(steps: list[dict]) -> None:
    assert step_named(steps, "check out")["with"]["fetch-depth"] == 0


def test_the_run_verifies_the_checkout_against_the_candidate(steps: list[dict]) -> None:
    """A belt-and-braces check inside CI itself, before any gate runs."""

    verify = step_named(steps, "verify the candidate")
    assert "git rev-parse HEAD" in verify["run"]
    assert "exit 1" in verify["run"]
    assert verify.get("id") == "candidate"


def test_the_gates_step_hands_the_candidate_sha_to_the_provenance_script(
    steps: list[dict],
) -> None:
    gates = step_named(steps, "acceptance gates")
    assert "scripts/acceptance_provenance.py" in gates["run"]
    assert "--candidate-sha" in gates["run"]
    assert "steps.candidate.outputs.sha" in gates["run"]


def test_the_secret_scanner_is_pinned_to_a_version(workflow: dict, steps: list[dict]) -> None:
    assert workflow["env"]["GITLEAKS_VERSION"]
    scanner = step_named(steps, "secret scanner")
    assert "GITLEAKS_VERSION" in scanner["run"]
    assert "latest" not in scanner["run"]


def test_the_workflow_token_is_read_only(workflow: dict) -> None:
    assert workflow["permissions"] == {"contents": "read"}


def test_the_workflow_never_reads_a_secret(workflow: dict) -> None:
    """Acceptance is offline. Nothing here needs a credential, and a workflow
    that asked for one would be able to reach the live world."""

    rendered = ACCEPTANCE.read_text(encoding="utf-8")
    assert "secrets." not in rendered
    assert "${{ secrets" not in rendered


def test_the_workflow_makes_no_live_or_outward_call(workflow: dict) -> None:
    rendered = ACCEPTANCE.read_text(encoding="utf-8").lower()
    for forbidden in ("shopify", "gmail", "elevenlabs", "deploy", "myshopify", "-m live"):
        assert forbidden not in rendered, forbidden


def test_every_run_step_fails_closed_on_the_first_error(steps: list[dict]) -> None:
    """``bash`` without ``-e`` would let a failed gate be followed by a
    successful ``echo`` and report the job green."""

    assert yaml.safe_load(ACCEPTANCE.read_text(encoding="utf-8"))["defaults"]["run"]["shell"] == "bash"
    for step in steps:
        script = step.get("run")
        if script and "\n" in script.strip():
            assert "set -euo pipefail" in script, step.get("name")


def test_the_evidence_is_published_even_when_a_gate_fails(steps: list[dict]) -> None:
    upload = step_named(steps, "publish the provenance")
    assert upload["if"] == "always()"
    assert "steps.candidate.outputs.sha" in upload["with"]["name"]


def test_the_summary_says_this_is_not_acceptance(steps: list[dict]) -> None:
    summary = step_named(steps, "summarise")["run"].lower()
    assert "not accepted" in summary
    assert "independent" in summary
