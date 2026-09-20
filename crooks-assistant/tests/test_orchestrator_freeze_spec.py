"""Mechanical specification checks for the Orchestrator V1 freeze set.

The freeze set is documentation, so it has no runtime behaviour to test. It does, however, make
claims *about itself* that can be checked mechanically, and the adversarial review that rejected
candidate `2bf240c` found that two of those claims were false: CG-05 was certified "resolved" by an
`EN-01..EN-0x` acceptance family that existed nowhere in the repository, and the normative failure
reason-code list mandated a top-level retry classification that the freeze set never supplied.

Both defects share a shape: a normative document asserting coverage that nothing verified. The §18
freeze gate previously scanned only for *status disagreement* between documents, which by
construction cannot catch a citation of something that does not exist. These tests are the missing
half of that gate, and they are deliberately structural rather than illustrative — they recompute
what the documents actually contain and compare it against what the documents claim, so a future
edit cannot reintroduce a phantom citation, an unmapped reason code or an undispositioned MUST
without turning this file red.

No orchestrator runtime is implemented or implied here. These are document invariants only.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs" / "product-memory"

FREEZE_CONTRACT = DOCS / "ORCHESTRATOR_V1_FREEZE_CONTRACT.md"
STATE_API = DOCS / "ORCHESTRATOR_V1_STATE_API.md"
ACCEPTANCE_MATRIX = DOCS / "ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md"
TRACEABILITY = DOCS / "ORCHESTRATOR_V1_TRACEABILITY.md"
CURRENT_TRUTH = DOCS / "CURRENT_TRUTH.md"

FREEZE_SET = (FREEZE_CONTRACT, STATE_API, ACCEPTANCE_MATRIX, TRACEABILITY)

# A test ID looks like `ST-01`. Two-to-four capitals, a hyphen, exactly two digits. The trailing
# boundary matters: it keeps `SHA-256` and `DEC-046` out without needing to special-case them.
TEST_ID = re.compile(r"\b([A-Z]{2,4}-\d{2})\b")

# Identifier families that share the test-ID shape but are not acceptance tests.
NOT_TEST_IDS = frozenset({"CG", "DEC", "BE"})

REASON_CLASSES = frozenset({"RETRYABLE", "BLOCKED", "REJECTED_FAILED", "ESCALATED"})


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def matrix_row_ids() -> set[str]:
    """Every acceptance case defined by the matrix, taken from the first cell of each table row."""
    ids = set()
    for line in read(ACCEPTANCE_MATRIX).splitlines():
        if not line.startswith("|"):
            continue
        first_cell = line.split("|")[1].strip()
        match = re.fullmatch(r"([A-Z]{2,4}-\d{2})", first_cell)
        if match:
            ids.add(match.group(1))
    return ids


def referenced_test_ids(text: str) -> set[str]:
    return {
        found
        for found in TEST_ID.findall(text)
        if found.split("-")[0] not in NOT_TEST_IDS
    }


def numbered_sections(path: Path) -> dict[str, str]:
    """Map `§<number>` to the heading line, for every numbered heading in a normative document.

    Handles `## 7.`, `## 22A.`, `### 5.3` and `#### 10.3.1` alike. Unnumbered headings — the
    per-record subsections of the state API's §1, for instance — are deliberately excluded,
    because the coverage index is keyed on numbered sections.
    """
    sections: dict[str, str] = {}
    for line in read(path).splitlines():
        match = re.match(r"^(#{2,4})\s+(\d+[A-Z]?(?:\.\d+)*)\.?\s+\S", line)
        if match:
            sections[f"§{match.group(2)}"] = line
    return sections


def must_bearing_sections(path: Path) -> set[str]:
    """Numbered sections of a document that contain at least one MUST or MUST NOT."""
    bearing: set[str] = set()
    current: str | None = None
    for line in read(path).splitlines():
        heading = re.match(r"^(#{2,4})\s+(\d+[A-Z]?(?:\.\d+)*)\.?\s+\S", line)
        if heading:
            current = f"§{heading.group(2)}"
            continue
        if re.match(r"^#{1,4}\s", line):
            # An unnumbered heading: MUSTs under it belong to no indexable section, and the
            # `review_dispatch` record proves that case is reachable, so stop attributing.
            current = None
            continue
        if current and "MUST" in line:
            bearing.add(current)
    return bearing


def reason_code_table() -> list[tuple[str, str]]:
    """The `(code, class)` pairs of the normative reason-code table in state API §7."""
    pairs: list[tuple[str, str]] = []
    in_section = False
    for line in read(STATE_API).splitlines():
        if re.match(r"^##\s+7\.", line):
            in_section = True
            continue
        if in_section and re.match(r"^##\s", line):
            break
        if not in_section or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if len(cells) < 2:
            continue
        code = cells[0].strip("`")
        if re.fullmatch(r"[A-Z][A-Z_]+", code):
            pairs.append((code, cells[1].strip()))
    return pairs


def coverage_index() -> dict[str, str]:
    """The §18A MUST-coverage index as `{"FC §7": "<coverage cell>"}`."""
    index: dict[str, str] = {}
    in_section = False
    for line in read(ACCEPTANCE_MATRIX).splitlines():
        if re.match(r"^##\s+18A\.", line):
            in_section = True
            continue
        if in_section and re.match(r"^##\s", line):
            break
        if not in_section or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if len(cells) != 3 or cells[0] not in {"FC", "SA"}:
            continue
        index[f"{cells[0]} {cells[1]}"] = cells[2]
    return index


# --------------------------------------------------------------------------------------------
# B-03 — no normative document may cite an acceptance case that does not exist.
# --------------------------------------------------------------------------------------------


def test_matrix_defines_the_acceptance_cases_the_freeze_gate_assumes() -> None:
    """Sanity floor: the families the repaired freeze set depends on are actually present."""
    ids = matrix_row_ids()
    assert len(ids) > 100, f"matrix looks truncated: only {len(ids)} rows parsed"
    for required in ("EN-01", "EN-02", "EN-03", "EN-04"):
        assert required in ids, f"{required} missing; CG-05 would again cite a phantom family"
    for required in ("RV-11", "RV-12", "RV-13", "PR-09", "PR-10", "IN-11", "IN-12", "IN-13"):
        assert required in ids, f"{required} missing from the acceptance matrix"


@pytest.mark.parametrize("doc", FREEZE_SET, ids=lambda p: p.name)
def test_every_referenced_test_id_resolves_to_a_real_matrix_row(doc: Path) -> None:
    """The check that would have caught B-03 automatically.

    CG-05 was certified resolved by `EN-01..EN-03` while the matrix defined no `EN` family at all,
    and the two citing documents disagreed about the size of the set they were citing. A freeze gate
    that only compares *status* between documents cannot see that; this one can.
    """
    defined = matrix_row_ids()
    referenced = referenced_test_ids(read(doc))
    dangling = sorted(referenced - defined)
    assert not dangling, f"{doc.name} references acceptance IDs that do not exist: {dangling}"


def test_cg05_citations_agree_on_one_range() -> None:
    """Both documents that certify CG-05 must name the same, real acceptance range."""
    contract_line = next(
        line for line in read(FREEZE_CONTRACT).splitlines() if "**CG-05:**" in line
    )
    trace_line = next(
        line for line in read(TRACEABILITY).splitlines() if "CG-05" in line and "|" in line
    )
    assert "EN-01" in contract_line and "EN-04" in contract_line, contract_line
    assert "EN-01" in trace_line and "EN-04" in trace_line, trace_line
    assert "EN-03" not in contract_line.replace("EN-01..EN-04", ""), (
        "freeze contract still cites the stale EN-01..EN-03 range"
    )


# --------------------------------------------------------------------------------------------
# B-02 — the reason-code table must be a total mapping that fails closed.
# --------------------------------------------------------------------------------------------


def test_every_reason_code_maps_to_exactly_one_top_level_class() -> None:
    """PR-09 as a document check: totality, no duplicates, no class invented on the spot."""
    pairs = reason_code_table()
    assert len(pairs) >= 28, f"reason-code table looks truncated: {len(pairs)} rows"

    codes = [code for code, _ in pairs]
    duplicates = sorted({code for code in codes if codes.count(code) > 1})
    assert not duplicates, f"reason codes mapped more than once: {duplicates}"

    unknown = sorted({cls for _, cls in pairs if cls not in REASON_CLASSES})
    assert not unknown, f"reason codes mapped to classes outside the normative four: {unknown}"


def test_process_failure_codes_are_not_retryable() -> None:
    """The specific hazard B-02 named: a stalled model attempt silently relaunched as transient."""
    mapping = dict(reason_code_table())
    for code in ("PROCESS_TIMEOUT", "PROCESS_STALLED", "PROCESS_ORPHANED"):
        assert code in mapping, f"{code} is absent from the normative reason-code table"
        assert mapping[code] == "BLOCKED", f"{code} is classified {mapping[code]}, not BLOCKED"


def test_unmapped_reason_codes_fail_closed_to_blocked() -> None:
    """An unknown code must default to BLOCKED, and the documents must say so, not imply it."""
    text = read(STATE_API)
    assert "no resolvable top-level mapping MUST be treated as BLOCKED" in text
    assert "MUST NOT be treated as RETRYABLE" in text


def test_non_rejection_attempt_relaunch_budget_is_finite_and_persistent() -> None:
    """§10.3's correction budget covered rejection only; stall/timeout had no budget at all."""
    text = read(FREEZE_CONTRACT)
    assert "Non-rejection attempt failure budget" in text
    assert "automatic relaunches after a non-rejection attempt failure: zero" in text
    assert re.search(r"at most \d+ attempts per task revision", text), (
        "no absolute per-revision attempt ceiling is stated"
    )
    assert "MUST survive controller restart" in text


# --------------------------------------------------------------------------------------------
# B-03 follow-on — every MUST is tested, explicitly static, or explicitly deferred.
# --------------------------------------------------------------------------------------------


def test_coverage_index_dispositions_every_must_bearing_section() -> None:
    """The gate that reports MUST-coverage gaps instead of papering over them.

    §22A was a MUST-bearing section with zero test coverage, and freeze contract §18/§19 were the
    same defect one step less severe. This recomputes the MUST-bearing set from the documents
    themselves, so adding a MUST anywhere in the freeze set without dispositioning it fails here.
    """
    index = coverage_index()
    assert index, "§18A MUST-coverage index is missing or unparseable"

    missing: list[str] = []
    for label, path in (("FC", FREEZE_CONTRACT), ("SA", STATE_API)):
        for section in sorted(must_bearing_sections(path)):
            if f"{label} {section}" not in index:
                missing.append(f"{label} {section}")
    assert not missing, f"MUST-bearing sections with no coverage disposition: {missing}"


@pytest.mark.parametrize("path", (FREEZE_CONTRACT, STATE_API), ids=lambda p: p.name)
def test_no_must_hides_in_an_unnumbered_subsection(path: Path) -> None:
    """The coverage index is keyed on numbered sections, so a MUST must not escape into an
    unnumbered one.

    Without this, the per-record subsections of state API §1 would be a blind spot: a normative
    requirement could be added under `### \\`review_dispatch\\`` and never receive a coverage
    disposition. Normative statements belong in numbered sections; record subsections describe
    schema and may point at the section that mandates the behaviour.
    """
    offenders: list[str] = []
    current: str | None = None
    for line in read(path).splitlines():
        heading = re.match(r"^(#{1,4})\s+(.*)$", line)
        if heading:
            numbered = re.match(r"^(#{2,4})\s+(\d+[A-Z]?(?:\.\d+)*)\.?\s+\S", line)
            # The H1 preamble defines the RFC-2119 keywords themselves; it states no requirement.
            is_preamble = len(heading.group(1)) == 1
            current = None if (numbered or is_preamble) else heading.group(2)
            continue
        if current and "MUST" in line:
            offenders.append(f"{current!r}: {line.strip()[:80]}")
    assert not offenders, f"{path.name} has MUSTs outside any numbered section: {offenders}"


def test_coverage_index_entries_name_real_sections_and_real_tests() -> None:
    """An index is only as good as its references: no phantom sections, no phantom tests."""
    defined = matrix_row_ids()
    sections = {
        "FC": numbered_sections(FREEZE_CONTRACT),
        "SA": numbered_sections(STATE_API),
    }
    problems: list[str] = []
    for key, coverage in coverage_index().items():
        label, section = key.split(" ", 1)
        if section not in sections[label]:
            problems.append(f"{key} names a section that does not exist")
        cited = referenced_test_ids(coverage)
        dangling = sorted(cited - defined)
        if dangling:
            problems.append(f"{key} cites non-existent tests {dangling}")
        if not cited and not coverage.startswith(("STATIC", "DEFERRED")):
            problems.append(f"{key} names no test and is not STATIC or DEFERRED")
    assert not problems, "; ".join(problems)


def test_static_dispositions_are_honest_about_being_static() -> None:
    """A `STATIC` entry must carry a reason, so it cannot be used as a silent coverage escape."""
    for key, coverage in coverage_index().items():
        if coverage.startswith("STATIC"):
            assert "—" in coverage or "-" in coverage, f"{key}: STATIC with no stated reason"


# --------------------------------------------------------------------------------------------
# B-01 / B-04 — reviewers and integrators have a real execution substrate.
# --------------------------------------------------------------------------------------------


def test_review_execution_has_a_durable_fenced_record() -> None:
    """B-01: an in-flight review must be visible in the database and fenceable."""
    api = read(STATE_API)
    contract = read(FREEZE_CONTRACT)

    assert "### `review_dispatch`" in api, "no reviewer execution record"
    assert "## 3B. Review dispatch transition matrix" in api, "no dispatch lifecycle"
    assert "review_dispatch_id" in api

    # Admission is fenced, and fenced on dispatch identity rather than on candidate mutation.
    assert "**review-result admission**" in contract, (
        "freeze contract §7 fencing rule still omits review result admission"
    )
    assert "even when the subject SHA has not changed" in contract
    assert "even when the subject SHA has not changed" in api

    # Restart reconciles in-flight reviews before dispatch is re-enabled.
    assert "in-flight review dispatches" in contract, "§21 has no review reconciliation step"


def test_integration_execution_reuses_the_attempt_and_lease_machinery() -> None:
    """B-04: `integration.cancel` must fence something the schema can actually represent."""
    api = read(STATE_API)
    contract = read(FREEZE_CONTRACT)

    assert "subject kind `TASK|INTEGRATION`" in api, "attempt is not subject-kind aware"
    assert "One authoritative lease per `(subject_kind, subject_id, subject_revision)`" in api
    assert "One authoritative lease per `(task_id, revision)`" not in api.replace(
        'previous "one authoritative lease per `(task_id, revision)`" rule', ""
    ), "the task-only lease key survives as a normative statement"

    assert "integration attempts" in contract, "§21 has no integration reconciliation step"
    assert "`subject_kind = INTEGRATION`" in contract


def test_findings_carry_an_explicit_subject_kind() -> None:
    """B-05: integration findings gate `integration.verify`, so they must be representable."""
    api = read(STATE_API)
    finding_block = api.split("### `finding`")[1].split("### `attempt`")[0]
    assert "subject kind `CANDIDATE|INTEGRATION`" in finding_block
    assert "task_id TEXT NULL" in finding_block, "task binding is still mandatory"
    assert "no blocking finding whose subject is this integration" in api
    assert "parent_integration_id" in api


def test_fence_stale_is_a_classified_reason_code() -> None:
    """Rejecting a stale verdict needs a typed reason, which the taxonomy previously lacked."""
    mapping = dict(reason_code_table())
    assert mapping.get("FENCE_STALE") == "REJECTED_FAILED", mapping.get("FENCE_STALE")



# --------------------------------------------------------------------------------------------
# R-01 / R-02 / R-03 — repair the integration launch, attempt ceiling and delivery authority.
# --------------------------------------------------------------------------------------------


def test_integration_launch_is_split_into_allocation_then_preflight() -> None:
    """R-01: integration allocation and preflight must be two legal, jointly representable phases."""
    api = read(STATE_API)
    assert "| `integration.begin` | integrator coordinator | CREATED -> INTEGRATING" in api
    begin_line = next(line for line in api.splitlines() if line.startswith("| `integration.begin` |"))
    assert "no model/toolchain preflight" in begin_line
    assert "| `integration.start` | runner adapter |" in api
    assert "`attempt.start` (TASK) / `integration.start` (INTEGRATION)" in api
    assert "integration INTEGRATING + attempt CREATED/STARTING | integration.start" in api


def test_attempt_ceiling_is_a_transition_guard_not_only_prose() -> None:
    """R-02: the fourth attempt is impossible because every TASK allocation path checks the ceiling."""
    api = read(STATE_API)
    contract = read(FREEZE_CONTRACT)
    assert api.count("per-revision attempt ceiling not exhausted") >= 2
    assert "both TASK branches the per-revision attempt ceiling must not be exhausted" in api
    assert "BLOCKED` to **`ESCALATED`**" in contract
    assert "no further `attempt.assign` is admissible" in contract


def test_delivery_has_its_own_authority_and_journal_subject() -> None:
    """R-03: delivery is journalled but is not forced through an execution-record fence it does not own."""
    api = read(STATE_API)
    contract = read(FREEZE_CONTRACT)
    assert "TASK|INTEGRATION|CANDIDATE|REVIEW|DELIVERY" in api
    assert "controller epoch of the last authoritative delivery mutation" in api
    assert "Delivery updates are not execution-record admissions" in contract
    assert "delivery idempotency key" in contract
    assert "idempotency-key/request-digest conflict" in contract

# --------------------------------------------------------------------------------------------
# Regression guards for the previously validated N-series repairs.
# --------------------------------------------------------------------------------------------


def test_traceability_dispositions_every_reviewed_finding() -> None:
    """Silence is not a disposition: N-01..N-04 and B-01..B-05 each carry an explicit row."""
    text = read(TRACEABILITY)
    assert "Silence is not a disposition." in text
    for finding in ("N-01", "N-02", "N-03", "N-04", "B-01", "B-02", "B-03", "B-04", "B-05", "R-01", "R-02", "R-03"):
        assert f"re-review {finding} " in text, f"{finding} has no traceability disposition"


def test_current_truth_retains_the_live_unremediated_runtime_conditions() -> None:
    """The N-04 repair, as a mechanical gate rather than a promise.

    §18 requires the freeze gate to *persist* an explicit set of live unremediated runtime
    conditions, so that a future truth reconciliation cannot silently delete a condition the
    remediation rehearsal depends on. This is that check.
    """
    truth = read(CURRENT_TRUTH)

    # (a) watcher/builder branch mismatch
    assert "claude/builder-environment-repair" in truth and "claude/bridge-builder" in truth
    # (b) inherited business MCP connector surface
    assert "business MCP connector tools" in truth or "business connector" in truth
    # (c) the stale Builder fetch refspec, with its no-ad-hoc-repair instruction
    assert "`remote.origin.fetch` refspec still names the deleted remote" in truth
    assert "git fetch --all` fails there" in truth
    assert "Do not repair the refspec ad hoc" in truth
    assert "BR-01/BR-04" in truth


def test_no_self_adoption_of_the_freeze() -> None:
    """A repair round must not promote the candidate to adopted authority."""
    decisions = DOCS / "DECISIONS.md"
    assert decisions.exists()
    text = read(decisions)
    assert "orchestrator-v1-freeze-candidate" not in text, (
        "the freeze candidate has written itself into owner decisions"
    )
    contract = read(FREEZE_CONTRACT)
    assert "This specification is a candidate until the Owner adopts an exact candidate SHA" in (
        contract
    )
