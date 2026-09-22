"""What the acceptance artifact is allowed to claim, and when it must refuse.

The gates themselves are tested where they live. What is tested here is the
binding: that a run which cannot honestly name the commit it tested produces no
artifact at all, and that an artifact which does name one never quietly turns
mechanical green into permission.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import acceptance_provenance as provenance  # noqa: E402

from app.actions.models import ActionStatus  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "acceptance_provenance.py"


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return completed.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A clean one-commit repository standing in for the real one."""

    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Test")
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "first")
    monkeypatch.setattr(provenance, "REPO", root)
    return root


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").lower()


def passing_gate(name: str) -> provenance.GateResult:
    return provenance.GateResult(name, required=True, status=provenance.PASS, exit_code=0)


@pytest.fixture
def all_gates_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provenance, "gate_static", lambda: passing_gate("ruff"))
    monkeypatch.setattr(
        provenance, "gate_control_plane_tests", lambda: passing_gate("pytest_control_plane")
    )
    monkeypatch.setattr(
        provenance,
        "gate_product_memory_structure",
        lambda: passing_gate("product_memory_structure"),
    )
    monkeypatch.setattr(
        provenance, "gate_offline_suite", lambda scope: passing_gate("pytest_offline_bounded")
    )
    monkeypatch.setattr(
        provenance, "gate_secret_scan", lambda base: passing_gate("secret_scan")
    )


# --- the binding -----------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["", "abc", "g" * 40, "a" * 39, "a" * 41, " " + "a" * 40 + "x", "a" * 39 + "/"],
)
def test_only_an_exact_forty_character_sha_is_a_candidate(value: str) -> None:
    with pytest.raises(provenance.EvidenceError):
        provenance.validate_sha(value)


def test_an_uppercase_sha_is_accepted_and_normalised_down() -> None:
    """Git SHAs are case-insensitive, so this is normalisation, not laxity —
    and everything downstream then compares lowercase against lowercase."""

    assert provenance.validate_sha("A" * 39 + "B") == "a" * 39 + "b"
    assert provenance.validate_sha("  " + "a" * 40 + "  ") == "a" * 40


def test_candidate_sha_mismatch_refuses_before_any_gate_runs(repo: Path) -> None:
    """The whole point: evidence that names the wrong commit is not evidence."""

    with pytest.raises(provenance.EvidenceError, match="candidate SHA mismatch"):
        provenance.resolve_repository_identity("d" * 40)


def test_a_sha_this_repository_does_not_contain_refuses(repo: Path, monkeypatch) -> None:
    # Force HEAD to agree so the mismatch check passes and the existence check
    # is the one under test.
    absent = "d" * 40
    real = provenance._git

    def fake(*args: str) -> str:
        if args[:2] == ("rev-parse", "HEAD"):
            return absent
        return real(*args)

    monkeypatch.setattr(provenance, "_git", fake)
    with pytest.raises(provenance.EvidenceError):
        provenance.resolve_repository_identity(absent)


def test_a_dirty_worktree_refuses(repo: Path) -> None:
    (repo / "scratch.txt").write_text("uncommitted\n", encoding="utf-8")

    with pytest.raises(provenance.EvidenceError, match="worktree is not clean"):
        provenance.resolve_repository_identity(head(repo))

    # Load-bearing control: commit it and the same call succeeds.
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "second")
    assert provenance.resolve_repository_identity(head(repo))["clean_worktree"] is True


def test_a_clean_repository_reports_the_identity_it_was_bound_to(repo: Path) -> None:
    identity = provenance.resolve_repository_identity(head(repo))

    assert identity["candidate_sha"] == head(repo)
    assert identity["head_sha"] == head(repo)
    assert identity["branch"] == "main"
    assert identity["clean_worktree"] is True
    assert identity["parents"] == []


# --- what the artifact may claim -------------------------------------------


def test_all_gates_green_is_eligible_for_review_and_nothing_more(
    repo: Path, all_gates_pass: None
) -> None:
    artifact = provenance.build_artifact(head(repo))
    acceptance = artifact["acceptance"]

    assert acceptance["mechanical_evidence"] == "complete"
    assert acceptance["eligible_for_acceptance_decision"] is True

    # Green gates never become permission.
    assert acceptance["independent_review"] == "required"
    assert acceptance["human_approval_recorded"] is False
    assert acceptance["accepted"] is False


def test_the_artifact_carries_the_exact_candidate_sha(repo: Path, all_gates_pass: None) -> None:
    artifact = provenance.build_artifact(head(repo))
    assert artifact["repository"]["candidate_sha"] == head(repo)
    assert artifact["schema"] == provenance.SCHEMA


def test_a_failing_gate_is_named_and_makes_the_run_ineligible(
    repo: Path, all_gates_pass: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        provenance,
        "gate_control_plane_tests",
        lambda: provenance.GateResult(
            "pytest_control_plane", required=True, status=provenance.FAIL, exit_code=1
        ),
    )
    acceptance = provenance.build_artifact(head(repo))["acceptance"]

    assert acceptance["eligible_for_acceptance_decision"] is False
    assert acceptance["unsatisfied_gates"] == ["pytest_control_plane"]
    assert acceptance["mechanical_evidence"] == "incomplete"


def test_malformed_gate_evidence_fails_closed(
    repo: Path, all_gates_pass: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A verdict that cannot be read is not a passing verdict."""

    monkeypatch.setattr(
        provenance,
        "gate_product_memory_structure",
        lambda: provenance.GateResult(
            "product_memory_structure",
            required=True,
            status=provenance.ERROR,
            exit_code=0,
            detail="gate did not emit parseable JSON",
        ),
    )
    acceptance = provenance.build_artifact(head(repo))["acceptance"]

    assert acceptance["eligible_for_acceptance_decision"] is False
    assert acceptance["malformed_gates"] == ["product_memory_structure"]


def test_a_skipped_gate_is_not_a_passed_gate(repo: Path, all_gates_pass: None) -> None:
    acceptance = provenance.build_artifact(head(repo), skip=frozenset({"secret_scan"}))["acceptance"]

    assert acceptance["eligible_for_acceptance_decision"] is False
    assert "secret_scan" in acceptance["unsatisfied_gates"]
    assert "secret_scan" in acceptance["malformed_gates"]


def test_an_absent_secret_scanner_is_an_error_not_a_pass(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(provenance, "_VENDORED_GITLEAKS", repo / "nothing-here")
    monkeypatch.setattr(provenance, "SECRET_BASELINE", repo / "no-baseline.json")
    monkeypatch.setenv("PATH", str(repo))  # no gitleaks on it

    result = provenance.gate_secret_scan(None)
    assert result.status == provenance.ERROR
    assert result.satisfied is False


# --- the secret-scan baseline ----------------------------------------------


def test_the_committed_baseline_holds_no_secret_value() -> None:
    """The baseline is committed, so it must be readable by anyone without
    handing them anything. Every value in it is the literal 'REDACTED'."""

    findings = provenance.read_baseline()
    assert findings, "the baseline should record the known pre-existing findings"

    for finding in findings:
        assert finding["Secret"] == "REDACTED"
        assert "REDACTED" in finding["Match"]
        assert finding["Fingerprint"]


def test_every_baselined_finding_is_a_test_fixture() -> None:
    """Nothing outside the test suite may be excused by the baseline.

    A baseline is a promise that these findings are not secrets. That promise
    is only defensible for strings that exist to be redacted in a test; the
    moment application code appears here, the promise is doing work it should
    not be doing.
    """

    for finding in provenance.read_baseline():
        assert "/tests/" in finding["File"], finding["File"]


def test_a_corrupt_baseline_fails_closed(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    corrupt = repo / "baseline.json"
    corrupt.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(provenance, "SECRET_BASELINE", corrupt)

    result = provenance.gate_secret_scan(None)
    assert result.status == provenance.ERROR
    assert "baseline" in result.detail


def test_a_baseline_that_is_not_a_list_fails_closed(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrong = repo / "baseline.json"
    wrong.write_text('{"findings": []}', encoding="utf-8")
    monkeypatch.setattr(provenance, "SECRET_BASELINE", wrong)

    with pytest.raises(provenance.EvidenceError, match="JSON array"):
        provenance.read_baseline()


def test_the_artifact_discloses_how_much_the_baseline_suppressed(
    repo: Path, all_gates_pass: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """"No leaks found" must not be able to hide how it got there."""

    monkeypatch.undo()  # restore the real gate_secret_scan
    real = provenance.gate_secret_scan(None)

    assert real.data is not None
    assert real.data["mode"] == "tree"
    assert real.data["baseline_suppressed_findings"] == len(provenance.read_baseline())
    assert real.data["baseline_path"] == ".gitleaks-baseline.json"


def test_a_commit_range_scan_does_not_use_the_baseline(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A range scan only sees what the candidate introduced, so there is
    nothing pre-existing for a baseline to excuse."""

    captured: list[list[str]] = []

    def fake_run_gate(name, command, **kwargs):
        captured.append(command)
        return provenance.GateResult(name, True, provenance.PASS, 0)

    monkeypatch.setattr(provenance, "_run_gate", fake_run_gate)
    result = provenance.gate_secret_scan("a" * 40)

    assert result.data["mode"] == "range"
    assert result.data["baseline_suppressed_findings"] == 0
    assert "--baseline-path" not in captured[0]
    assert f"--log-opts={'a' * 40}..HEAD" in captured[0]


# --- the boundary the inbox names ------------------------------------------


def test_acceptance_vocabulary_is_disjoint_from_action_status(
    repo: Path, all_gates_pass: None
) -> None:
    """Human approval must not be encoded into ActionStatus.

    ActionStatus is the business-write safety machine — PENDING waits for the
    owner's tap on a Shopify mutation. Repository acceptance is a different
    question with different authority, and borrowing that vocabulary would
    quietly make one look like the other.
    """

    artifact = provenance.build_artifact(head(repo))
    rendered = json.dumps(artifact)
    action_states = {status.value for status in ActionStatus}

    assert not action_states & set(str(value) for value in artifact["acceptance"].values())
    for state in action_states:
        assert state not in rendered

    source = SCRIPT.read_text(encoding="utf-8")
    assert "ActionStatus" not in source
    assert "app.actions" not in source


def test_no_environment_variable_can_claim_approval(
    repo: Path, all_gates_pass: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("CROOKS_ACCEPTED", "ACCEPTED", "OWNER_APPROVED", "CI_APPROVED"):
        monkeypatch.setenv(name, "true")

    acceptance = provenance.build_artifact(head(repo))["acceptance"]
    assert acceptance["accepted"] is False
    assert acceptance["human_approval_recorded"] is False
    assert acceptance["independent_review"] == "required"


# --- run identity ----------------------------------------------------------


def test_run_identity_is_recorded_when_the_runner_offers_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "crooksldn-pixel/clive")
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.setenv("GITHUB_WORKFLOW", "acceptance")

    identity = provenance.resolve_run_identity()
    assert identity["provider"] == "github-actions"
    assert identity["run_url"] == "https://github.com/crooksldn-pixel/clive/actions/runs/12345"
    assert identity["run_attempt"] == "2"


def test_run_identity_records_absence_rather_than_inventing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID",
                 "GITHUB_RUN_ATTEMPT", "GITHUB_WORKFLOW", "GITHUB_JOB"):
        monkeypatch.delenv(name, raising=False)

    identity = provenance.resolve_run_identity()
    assert identity["provider"] == "local"
    assert identity["run_url"] is None
    assert identity["run_id"] is None


# --- the command line ------------------------------------------------------


def test_cli_refuses_with_exit_two_and_still_emits_readable_json(tmp_path: Path) -> None:
    out = tmp_path / "evidence.json"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--candidate-sha", "d" * 40, "--out", str(out)],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2

    refusal = json.loads(completed.stdout)
    assert refusal["acceptance"]["mechanical_evidence"] == "unbound"
    assert refusal["acceptance"]["eligible_for_acceptance_decision"] is False
    assert refusal["acceptance"]["accepted"] is False
    assert "candidate SHA mismatch" in refusal["acceptance"]["refusal"]
    assert json.loads(out.read_text())["acceptance"]["accepted"] is False


def test_cli_rejects_a_malformed_candidate_sha() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--candidate-sha", "not-a-sha"],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert "40 lowercase hex" in json.loads(completed.stdout)["acceptance"]["refusal"]
