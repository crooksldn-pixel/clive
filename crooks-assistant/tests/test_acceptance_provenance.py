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
from tests.fake_credentials import aws_secret_access_key  # noqa: E402

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
    handing them anything. Every value in it is the literal 'REDACTED'.

    Since the owner's rule B (2026-09-25) the test suite's fake credentials are
    assembled at runtime by tests/fake_credentials.py instead of being baselined,
    so the committed baseline is empty; this still holds for anything a later
    decision puts in it."""

    for finding in provenance.read_baseline():
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
    baseline = provenance.read_baseline()
    assert real.data["baseline_suppressed_findings"] == len(baseline)
    assert real.data["baseline_path"] == (".gitleaks-baseline.json" if baseline else None)


def test_a_non_empty_baseline_is_handed_to_the_scanner_and_disclosed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The committed baseline is empty under rule B. The day it is not, what it
    suppresses must still reach the scanner and the artifact."""

    baseline = tmp_path / ".gitleaks-baseline.json"
    baseline.write_text(json.dumps([{
        "Fingerprint": "crooks-assistant/tests/x.py:generic-api-key:1",
        "Match": "REDACTED", "Secret": "REDACTED",
    }]), encoding="utf-8")
    monkeypatch.setattr(provenance, "SECRET_BASELINE", baseline)
    captured: list[list[str]] = []

    def fake_run_gate(name, command, **kwargs):
        captured.append(command)
        return provenance.GateResult(name, True, provenance.PASS, 0)

    monkeypatch.setattr(provenance, "_run_gate", fake_run_gate)
    result = provenance.gate_secret_scan(None)

    assert captured[0][-2:] == ["--baseline-path", ".gitleaks-baseline.json"]
    assert result.data["baseline_suppressed_findings"] == 1
    assert result.data["baseline_path"] and result.data["baseline_path"].endswith(".gitleaks-baseline.json")


def test_the_scan_command_uses_only_relative_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """The invariant whose loss is silent, and therefore the dangerous one.

    Given an absolute ``--source``, gitleaks reports absolute ``File`` paths.
    The baseline's fingerprints are relative, so nothing matches, every
    already-accounted-for finding comes back, and the gate goes red for
    reasons that look like a real leak. It cost a full acceptance run to
    notice; it costs one assertion to never repeat.
    """

    captured: list[list[str]] = []

    def fake_run_gate(name, command, **kwargs):
        captured.append(command)
        assert kwargs.get("cwd") == provenance.REPO, "the scan must run from the repository root"
        return provenance.GateResult(name, True, provenance.PASS, 0)

    monkeypatch.setattr(provenance, "_run_gate", fake_run_gate)
    provenance.gate_secret_scan(None)

    # The executable itself may be an absolute path; its arguments may not.
    for argument in captured[0][1:]:
        assert not argument.startswith("/"), argument


def test_the_scan_extends_the_default_rules_rather_than_replacing_them() -> None:
    config = provenance.CONFIG.read_text(encoding="utf-8")
    assert "useDefault = true" in config
    # No rule may be redefined or weakened here; only paths allowlisted.
    assert "[[rules]]" not in config


def test_the_allowlist_covers_only_generated_paths() -> None:
    """Allowlisting a source directory would hide a real leak forever."""

    config = provenance.CONFIG.read_text(encoding="utf-8")
    for source_dir in ("crooks-assistant/app", "crooks-assistant/config",
                       "crooks-assistant/scripts", "snippets", "sections", "templates"):
        assert source_dir not in config
    # tests/ in particular must stay in scope — its fake credentials are
    # assembled at runtime (rule B), so the scan reads the tests and finds none.
    assert "'''(^|/)tests/'''" not in config


def test_a_new_secret_still_fails_the_gate(tmp_path: Path, monkeypatch) -> None:
    """No rule is relaxed and no path hidden: a new secret anywhere fails the gate."""

    if not (provenance._VENDORED_GITLEAKS.is_file() or _on_path("gitleaks")):
        pytest.skip("the pinned scanner is not available on this host")

    probe = provenance.REPO / "scratch-leak-probe-test.txt"
    probe.write_text(
        'aws_secret_access_key = "' + aws_secret_access_key("gate-probe") + '"\n',
        encoding="utf-8",
    )
    try:
        assert provenance.gate_secret_scan(None).satisfied is False
    finally:
        probe.unlink()

    # Load-bearing control: with the probe gone the same gate passes.
    assert provenance.gate_secret_scan(None).satisfied is True


def _on_path(name: str) -> bool:
    from shutil import which

    return which(name) is not None


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


# ---------------------------------------------------------------- a red run says which test failed (1 Oct)

def _a_failing_test(tmp_path: Path) -> Path:
    test = tmp_path / "test_red.py"
    test.write_text(
        "def test_passes():\n    assert True\n\n\n"
        "def test_the_greeting_is_wrong():\n    greeting = 'bye'\n    assert greeting == 'hello'\n",
        encoding="utf-8",
    )
    return test


def test_a_failed_pytest_gate_keeps_the_failing_test_and_its_assertion(tmp_path: Path) -> None:
    """A red acceptance run must say which test failed, or nobody can repair it: the loop's builder was handed
    only the steps after the failure (1 Oct, clive-voice-uses-the-clock). The gate's own pytest output is kept as
    an excerpt: the short summary's FAILED line, the E lines and the totals, nothing else."""
    test = _a_failing_test(tmp_path)
    result = provenance._run_gate(
        "pytest_offline_full",
        [sys.executable, "-m", "pytest", str(test), "-q", "-p", "no:cacheprovider"],
        cwd=tmp_path, excerpt="pytest",
    )
    assert result.status == provenance.FAIL
    excerpt = result.failure_excerpt
    assert any(line.startswith("FAILED ") and "test_the_greeting_is_wrong" in line for line in excerpt), excerpt
    assert any(line.startswith("E ") and "assert 'bye' == 'hello'" in line for line in excerpt), excerpt
    assert "1 failed, 1 passed" in excerpt[-1]
    assert not any("def test_passes" in line for line in excerpt)            # only why, never the whole output
    assert result.as_dict()["failure_excerpt"] == excerpt


def test_a_passing_gate_and_the_secret_scan_never_carry_an_excerpt(tmp_path: Path) -> None:
    (tmp_path / "test_green.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    green = provenance._run_gate(
        "pytest_control_plane", [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_green.py"],
        cwd=tmp_path, excerpt="pytest",
    )
    assert green.status == provenance.PASS and green.failure_excerpt is None
    assert "failure_excerpt" not in green.as_dict()
    # No gate that scans for secrets is ever asked for one: its output could hold what it found.
    source = Path(provenance.__file__).read_text(encoding="utf-8")
    scan = source[source.index("def gate_secret_scan"):]
    scan = scan[:scan.index("\ndef ", 1)]
    assert "excerpt=" not in scan


def test_the_excerpt_is_bounded_however_much_fails() -> None:
    noisy = "\n".join([f"FAILED tests/test_x.py::test_{n} - AssertionError: {'x' * 500}" for n in range(500)]
                      + [f"E       assert {n} == 0" for n in range(500)] + ["===== 500 failed in 1.00s ====="])
    excerpt = provenance.failure_excerpt(noisy, "", kind="pytest")
    assert len(excerpt) <= provenance.EXCERPT_MAX_LINES
    assert all(len(line) <= provenance.EXCERPT_MAX_LINE for line in excerpt)
    assert sum(len(line) + 1 for line in excerpt) <= provenance.EXCERPT_MAX_CHARS + 1


def test_the_job_log_names_the_failing_test_ahead_of_the_artifact(
    repo: Path, all_gates_pass: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """What the loop's red-run summariser reads: pytest's own FAILED and E lines at the start of a log line."""
    real = provenance.gate_offline_suite

    def red(scope: str) -> provenance.GateResult:
        result = real(scope)
        return provenance.GateResult(
            result.name, True, provenance.FAIL, 1, 0.1, "1 failed, 6400 passed",
            failure_excerpt=["FAILED tests/test_x.py::test_y - AssertionError: nope", "E       assert 1 == 2",
                             "1 failed, 6400 passed in 400.00s"],
        )

    monkeypatch.setattr(provenance, "gate_offline_suite", red)
    code = provenance.main(["--candidate-sha", head(repo), "--suite", "bounded"])
    out = capsys.readouterr().out
    assert code == 1
    lines = out.splitlines()
    assert "== pytest_offline_bounded failed; what it said:" in lines
    assert "FAILED tests/test_x.py::test_y - AssertionError: nope" in lines
    assert "E       assert 1 == 2" in lines
    assert out.index("FAILED tests/test_x.py::test_y") < out.index('"schema"')
