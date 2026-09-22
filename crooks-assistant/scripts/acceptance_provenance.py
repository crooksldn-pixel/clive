#!/usr/bin/env python3
"""Run the repository's acceptance gates and record what they prove, about what.

The thing this exists to prevent is evidence that floats free of the commit it
claims to be about. A green test run is worth nothing as provenance unless you
can say which exact 40-character SHA it ran against, that the tree was clean
while it ran, and that nobody has quietly substituted a different commit in
between. So the caller must state the candidate SHA up front, and this refuses
to produce an artifact at all if the repository disagrees with it.

What it emits is evidence, never permission. Mechanical gates can say the code
compiles, the tests pass and no secret is present; they cannot say a competent
independent principal looked at it. The artifact therefore always carries
``independent_review: "required"``, and there is no flag, no environment
variable and no gate result that turns it into "approved" — acceptance is a
decision recorded elsewhere, by someone else.

    python scripts/acceptance_provenance.py --candidate-sha <40-hex>
    python scripts/acceptance_provenance.py --candidate-sha <sha> --suite full \\
        --out evidence/acceptance.json

Exit status is 0 only when every required gate passed and the evidence is
well-formed and bound to the stated candidate.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = "clive.acceptance_provenance.v1"
ASSISTANT = Path(__file__).resolve().parents[1]
REPO = ASSISTANT.parent

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# Where the pinned scanner lives when the builder host provides it. In CI the
# workflow installs the same pinned version onto PATH instead.
_VENDORED_GITLEAKS = REPO / ".tooling" / "bin" / "gitleaks"

# Findings that predate this gate, recorded by fingerprint with every value
# redacted. See ``read_baseline``.
SECRET_BASELINE = REPO / ".gitleaks-baseline.json"

# Extends the scanner's default rules; relaxes none of them.
CONFIG = REPO / ".gitleaks.toml"

PASS = "pass"
FAIL = "fail"
ERROR = "error"


class EvidenceError(RuntimeError):
    """The evidence cannot be trusted, so no artifact may claim it."""


@dataclass
class GateResult:
    name: str
    required: bool
    status: str
    exit_code: int | None = None
    duration_s: float = 0.0
    detail: str = ""
    data: dict | None = None
    command: list[str] = field(default_factory=list)

    @property
    def satisfied(self) -> bool:
        return self.status == PASS

    def as_dict(self) -> dict:
        record = {
            "name": self.name,
            "required": self.required,
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_s": round(self.duration_s, 3),
            "detail": self.detail,
            "command": self.command,
        }
        if self.data is not None:
            record["data"] = self.data
        return record


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise EvidenceError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def validate_sha(value: str) -> str:
    """A candidate is an exact commit or it is not a candidate."""

    lowered = value.strip().lower()
    if not _SHA_RE.fullmatch(lowered):
        raise EvidenceError(f"candidate SHA must be exactly 40 lowercase hex characters: {value!r}")
    return lowered


def resolve_repository_identity(candidate_sha: str) -> dict:
    """Bind this run to one commit, or refuse.

    Three ways this can be a lie, and all three are refused here: the stated
    candidate is not what HEAD resolves to; the stated candidate is not a
    commit this repository contains; or the tree has uncommitted changes, in
    which case the gates below would be testing something the SHA does not
    describe.
    """

    candidate_sha = validate_sha(candidate_sha)

    head = _git("rev-parse", "HEAD").lower()
    if head != candidate_sha:
        raise EvidenceError(
            f"candidate SHA mismatch: caller stated {candidate_sha}, repository HEAD is {head}"
        )

    kind = _git("cat-file", "-t", candidate_sha)
    if kind != "commit":
        raise EvidenceError(f"candidate SHA is a {kind}, not a commit")

    dirty = _git("status", "--porcelain")
    if dirty:
        changed = [line[3:] for line in dirty.split("\n")]
        raise EvidenceError(
            "worktree is not clean, so no evidence can be bound to the candidate SHA: "
            + ", ".join(sorted(changed)[:10])
        )

    return {
        "candidate_sha": candidate_sha,
        "head_sha": head,
        "clean_worktree": True,
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "committed_at": _git("show", "-s", "--format=%cI", candidate_sha),
        "parents": _git("show", "-s", "--format=%P", candidate_sha).split() or [],
    }


def resolve_run_identity() -> dict:
    """Whatever the runner is willing to tell us about itself.

    Absent outside CI, and that absence is itself recorded rather than faked.
    """

    env = os.environ.get
    server = env("GITHUB_SERVER_URL")
    repository = env("GITHUB_REPOSITORY")
    run_id = env("GITHUB_RUN_ID")

    identity = {
        "provider": "github-actions" if run_id else "local",
        "workflow": env("GITHUB_WORKFLOW"),
        "job": env("GITHUB_JOB"),
        "run_id": run_id,
        "run_attempt": env("GITHUB_RUN_ATTEMPT"),
        "runner_os": env("RUNNER_OS"),
        "event": env("GITHUB_EVENT_NAME"),
        "run_url": None,
    }
    if server and repository and run_id:
        identity["run_url"] = f"{server}/{repository}/actions/runs/{run_id}"
    return identity


def _run_gate(
    name: str,
    command: list[str],
    *,
    required: bool = True,
    cwd: Path = ASSISTANT,
    parse_json: bool = False,
) -> GateResult:
    started = time.monotonic()
    try:
        completed = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True)
    except OSError as exc:
        return GateResult(
            name,
            required,
            ERROR,
            None,
            time.monotonic() - started,
            f"could not run gate: {exc}",
            command=command,
        )

    duration = time.monotonic() - started
    tail = (completed.stdout or completed.stderr or "").strip().split("\n")
    detail = tail[-1][:400] if tail else ""

    data = None
    if parse_json:
        try:
            data = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            # Malformed evidence is worse than a failed gate: it is a gate whose
            # verdict cannot be read at all.
            return GateResult(
                name,
                required,
                ERROR,
                completed.returncode,
                duration,
                f"gate did not emit parseable JSON: {exc}",
                command=command,
            )

    return GateResult(
        name,
        required,
        PASS if completed.returncode == 0 else FAIL,
        completed.returncode,
        duration,
        detail,
        data,
        command,
    )


def _python() -> str:
    return sys.executable


def gate_static() -> GateResult:
    return _run_gate("ruff", [_python(), "-m", "ruff", "check", "app", "config", "scripts", "tests"])


def gate_control_plane_tests() -> GateResult:
    return _run_gate(
        "pytest_control_plane",
        [_python(), "-m", "pytest", "tests/test_orchestrator_control_plane.py",
         "-q", "-p", "no:cacheprovider"],
    )


def gate_product_memory_structure() -> GateResult:
    return _run_gate(
        "product_memory_structure",
        [_python(), str(ASSISTANT / "scripts" / "product_memory_check.py"), "--json"],
        parse_json=True,
    )


def gate_offline_suite(scope: str) -> GateResult:
    """The offline pytest evidence: the whole suite, or the bounded subset."""

    if scope == "full":
        targets = ["tests"]
        name = "pytest_offline_full"
    else:
        # The acceptance-machinery modules, whichever of them this tree has.
        # A named module that does not exist yet is omitted rather than turned
        # into a collection error that reads like a real failure.
        targets = [
            candidate
            for candidate in (
                "tests/test_orchestrator_control_plane.py",
                "tests/test_product_memory_structure.py",
                "tests/test_acceptance_provenance.py",
                "tests/test_ci_workflow.py",
                "tests/test_review_routing.py",
            )
            if (ASSISTANT / candidate).is_file()
        ]
        name = "pytest_offline_bounded"
    return _run_gate(
        name,
        [_python(), "-m", "pytest", *targets, "-m", "not live", "-q", "-p", "no:cacheprovider"],
    )


def _display_path(path: Path) -> str:
    """Repository-relative when it can be, absolute when it cannot.

    Never an exception: a path that happens to sit outside the repository is a
    thing to report, not a reason for the gate to crash instead of returning a
    verdict.
    """

    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def read_baseline() -> list[dict]:
    """The pre-existing findings this repository has already accounted for.

    They are all redaction fixtures in test files — strings that exist
    precisely so the observability tests can prove a secret gets masked. The
    baseline records them by fingerprint, never by value, so the scanner stops
    reporting them without anybody having to weaken a rule or exclude a path.
    """

    if not SECRET_BASELINE.is_file():
        return []
    try:
        loaded = json.loads(SECRET_BASELINE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvidenceError(f"secret-scan baseline is not readable JSON: {exc}") from exc
    if not isinstance(loaded, list):
        raise EvidenceError("secret-scan baseline must be a JSON array of findings")
    return loaded


def gate_secret_scan(base_sha: str | None) -> GateResult:
    """The pinned secret scanner, over the candidate's tree or a commit range.

    An absent scanner is not a pass. It is recorded as an error, the gate is
    required, and the run therefore fails closed — a candidate nobody scanned
    is not a candidate that is clean.

    Whatever the baseline suppresses is reported in the artifact, so a reader
    can see how much was excused rather than having to take "no leaks found"
    on trust.
    """

    executable = "gitleaks"
    if _VENDORED_GITLEAKS.is_file():
        executable = str(_VENDORED_GITLEAKS)

    # Every path below is relative, and the scan runs with cwd=REPO. That is
    # load-bearing: given an absolute --source, gitleaks reports absolute File
    # paths, the fingerprints stop matching the baseline's relative ones, and
    # suppression fails silently — the gate goes red for findings it was
    # supposed to have already accounted for.
    common = ["--no-banner", "--redact", "--exit-code", "1", "--config", CONFIG.name]

    if base_sha:
        mode = "range"
        command = [executable, "git", *common, f"--log-opts={base_sha}..HEAD", "."]
    else:
        mode = "tree"
        command = [executable, "detect", *common, "--no-git", "--source", "."]

    try:
        baseline = read_baseline()
    except EvidenceError as exc:
        return GateResult("secret_scan", True, ERROR, None, 0.0, str(exc), command=command)

    if baseline and mode == "tree":
        command += ["--baseline-path", SECRET_BASELINE.name]

    result = _run_gate("secret_scan", command, cwd=REPO)
    result.data = {
        "mode": mode,
        "scanner": Path(executable).name,
        "baseline_path": _display_path(SECRET_BASELINE) if baseline else None,
        "baseline_suppressed_findings": len(baseline) if baseline and mode == "tree" else 0,
    }
    return result


def build_artifact(
    candidate_sha: str,
    *,
    scope: str = "bounded",
    base_sha: str | None = None,
    skip: frozenset[str] = frozenset(),
) -> dict:
    """Run the gates and return the provenance artifact.

    Raises ``EvidenceError`` before running anything if the run cannot honestly
    be bound to ``candidate_sha``.
    """

    repository = resolve_repository_identity(candidate_sha)

    planned: list[tuple[str, callable]] = [
        ("ruff", gate_static),
        ("pytest_control_plane", gate_control_plane_tests),
        ("product_memory_structure", gate_product_memory_structure),
        ("pytest_offline", lambda: gate_offline_suite(scope)),
        ("secret_scan", lambda: gate_secret_scan(base_sha)),
    ]

    gates: list[GateResult] = []
    for key, run_gate in planned:
        if key in skip:
            gates.append(
                GateResult(key, required=True, status=ERROR, detail="gate was skipped by request")
            )
            continue
        gates.append(run_gate())

    required = [gate for gate in gates if gate.required]
    unsatisfied = [gate.name for gate in required if not gate.satisfied]
    malformed = [gate.name for gate in gates if gate.status == ERROR]

    return {
        "schema": SCHEMA,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repository": repository,
        "run": resolve_run_identity(),
        "gates": [gate.as_dict() for gate in gates],
        "acceptance": {
            # Mechanical evidence is the only thing this program can speak to.
            "mechanical_evidence": "complete" if not unsatisfied else "incomplete",
            "unsatisfied_gates": sorted(unsatisfied),
            "malformed_gates": sorted(malformed),
            # And this is the part no gate result can ever change.
            "independent_review": "required",
            "human_approval_recorded": False,
            "eligible_for_acceptance_decision": not unsatisfied,
            "accepted": False,
            "note": (
                "Mechanical gates produce evidence, not permission. Eligibility means an "
                "independent principal may now review this exact SHA; it is not acceptance, "
                "and acceptance is never derived from this artifact alone."
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-sha", required=True, help="the exact 40-hex commit under test")
    parser.add_argument(
        "--suite",
        choices=("bounded", "full"),
        default="bounded",
        help="offline pytest scope: the bounded acceptance modules, or every test",
    )
    parser.add_argument("--base-sha", help="scan only base..HEAD for secrets rather than the tree")
    parser.add_argument("--skip", action="append", default=[], help="record a gate as unrun")
    parser.add_argument("--out", type=Path, help="also write the artifact here")
    args = parser.parse_args(argv)

    try:
        artifact = build_artifact(
            args.candidate_sha,
            scope=args.suite,
            base_sha=args.base_sha,
            skip=frozenset(args.skip),
        )
    except EvidenceError as exc:
        # Refusing is the correct output. Say why, in the same shape, so a
        # consumer never has to parse prose to learn there is no evidence.
        refusal = {
            "schema": SCHEMA,
            "acceptance": {
                "mechanical_evidence": "unbound",
                "independent_review": "required",
                "human_approval_recorded": False,
                "eligible_for_acceptance_decision": False,
                "accepted": False,
                "refusal": str(exc),
            },
        }
        print(json.dumps(refusal, indent=2, sort_keys=True))
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(refusal, indent=2, sort_keys=True), encoding="utf-8")
        return 2

    rendered = json.dumps(artifact, indent=2, sort_keys=True)
    print(rendered)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")

    return 0 if artifact["acceptance"]["eligible_for_acceptance_decision"] else 1


if __name__ == "__main__":
    sys.exit(main())
