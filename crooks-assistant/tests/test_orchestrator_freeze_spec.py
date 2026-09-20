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


def numbered_section_text(path: Path, section: str) -> str:
    """The body of one numbered `##` section, up to the next `##` heading."""
    lines = read(path).splitlines()
    heading_re = re.compile(r"^##\s+" + re.escape(section) + r"(?:\.|\s)")
    out: list[str] = []
    in_section = False
    for line in lines:
        if heading_re.match(line):
            in_section = True
            continue
        if in_section and re.match(r"^##\s", line):
            break
        if in_section:
            out.append(line)
    assert in_section, f"{path.name} has no section {section}"
    return "\n".join(out)


def table_rows_under_header(path: Path, header: str) -> list[list[str]]:
    """Rows of the one markdown table whose header row is exactly `header`.

    Several documents now carry more than one table inside a single numbered section, so
    `table_rows_in_numbered_section` is too coarse to address them individually.
    """
    rows: list[list[str]] = []
    collecting = False
    for line in read(path).splitlines():
        if line.strip() == header.strip():
            collecting = True
            continue
        if not collecting:
            continue
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if not cells or set("".join(cells)) <= {"-", " "}:
            continue
        rows.append(cells)
    assert rows, f"{path.name}: no table found under header {header!r}"
    return rows


def declared_execution_bearing_states(text: str) -> dict[str, frozenset[str]]:
    """Parse the `TASK`/`INTEGRATION` execution-bearing state claims out of a normative passage.

    Both `ORCHESTRATOR_V1_STATE_API.md` §1A and `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §21 restate
    the same derived set in the same shape, which is what lets this be compared as a set rather
    than matched as a substring.
    """
    parsed: dict[str, frozenset[str]] = {}
    for kind in ("TASK", "INTEGRATION"):
        match = re.search(
            rf"`{kind}` subject states ((?:`[A-Z_]+`(?:, )?)+)", text
        )
        assert match is not None, f"no `{kind}` execution-bearing state list in the passage"
        parsed[kind] = frozenset(re.findall(r"`([A-Z_]+)`", match.group(1)))
    return parsed


def table_rows_in_numbered_section(path: Path, section: str) -> list[list[str]]:
    """Return non-header markdown table rows from one numbered section."""
    rows: list[list[str]] = []
    in_section = False
    heading_re = re.compile(r"^##\s+" + re.escape(section) + r"(?:\.|\s)")
    for line in read(path).splitlines():
        if heading_re.match(line):
            in_section = True
            continue
        if in_section and re.match(r"^##\s", line):
            break
        if not in_section or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if not cells or cells[0] in {"From", "---"}:
            continue
        rows.append(cells)
    return rows


# --------------------------------------------------------------------------------------------
# B-03 — no normative document may cite an acceptance case that does not exist.
# --------------------------------------------------------------------------------------------


def test_matrix_defines_the_acceptance_cases_the_freeze_gate_assumes() -> None:
    """Sanity floor: the families the repaired freeze set depends on are actually present."""
    ids = matrix_row_ids()
    assert len(ids) > 100, f"matrix looks truncated: only {len(ids)} rows parsed"
    for required in ("EN-01", "EN-02", "EN-03", "EN-04"):
        assert required in ids, f"{required} missing; CG-05 would again cite a phantom family"
    for required in ("RV-11", "RV-12", "RV-13", "PR-09", "PR-10", "IN-11", "IN-12", "IN-13", "IN-15", "IN-16", "IN-17", "IN-18", "ST-14", "ST-15", "ST-16", "ID-07", "DL-01", "DL-02", "DL-03", "DL-04", "DL-05", "DL-06"):
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
    assert re.search(r"at most \d+ execution attempts per task revision", text), (
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
    """F-01: subject and attempt matrices agree on the exact integration-start sequence."""
    api = read(STATE_API)
    assert "| `integration.begin` | integrator coordinator | CREATED -> INTEGRATING" in api
    begin_line = next(line for line in api.splitlines() if line.startswith("| `integration.begin` |"))
    assert "no model/toolchain preflight" in begin_line
    assert "| `integration.start` | runner adapter |" in api

    subject_rows = table_rows_in_numbered_section(STATE_API, "3")
    attempt_rows = table_rows_in_numbered_section(STATE_API, "3A")

    subject_start = [row for row in subject_rows if len(row) >= 3 and row[1] == "integration.start"]
    assert len(subject_start) == 1, subject_start
    assert subject_start[0][0] == "integration INTEGRATING"
    assert "attempt CREATED/STARTING" not in subject_start[0][0]

    created_edges = [
        row for row in attempt_rows
        if len(row) >= 3 and row[0] == "CREATED" and "integration.start" in row[1] and row[2] == "STARTING"
    ]
    running_edges = [
        row for row in attempt_rows
        if len(row) >= 3 and row[0] == "STARTING" and "integration.start" in row[1] and row[2] == "RUNNING"
    ]
    assert len(created_edges) == 1, created_edges
    assert len(running_edges) == 1, running_edges


def test_every_nonterminal_attempt_state_has_a_terminal_fencing_or_cleanup_edge() -> None:
    """F-03: allocation/preflight races cannot strand an authoritative lease forever."""
    rows = table_rows_in_numbered_section(STATE_API, "3A")
    for state in ("CREATED", "STARTING", "RUNNING", "CANDIDATE_READY"):
        terminal = [row for row in rows if len(row) >= 3 and row[0] == state and "CLOSED" in row[2]]
        assert terminal, f"{state} has no terminal attempt edge"

    # F-03's substance, taken from the matrix rather than from three fixed substrings: the two
    # pre-RUNNING states must each carry a *command-triggered* terminal edge — not merely an
    # abstract "fencing event" — and STARTING must additionally carry the unproven-cleanup edge.
    for state in ("CREATED", "STARTING"):
        commanded = [
            row for row in rows
            if len(row) >= 3
            and row[0] == state
            and "CLOSED" in row[2]
            and "`task.cancel`" in row[1]
            and "`integration.cancel`" in row[1]
        ]
        assert commanded, f"{state} has no command-triggered terminal cancellation edge"

    quarantine = [
        row for row in rows
        if len(row) >= 3
        and row[0] == "STARTING"
        and "QUARANTINED" in row[2]
        and "cannot be proven stopped" in row[1]
    ]
    assert len(quarantine) == 1, quarantine


def test_attempt_ceiling_is_a_transition_guard_not_only_prose() -> None:
    """R-02: the fourth attempt is impossible because every TASK allocation path checks the ceiling."""
    api = read(STATE_API)
    contract = read(FREEZE_CONTRACT)
    subject_rows = table_rows_in_numbered_section(STATE_API, "3")
    assign_rows = [
        row for row in subject_rows
        if len(row) >= 4 and row[1] == "attempt.assign" and row[0] in {"PLANNED", "REJECTED"}
    ]
    assert {row[0] for row in assign_rows} == {"PLANNED", "REJECTED"}
    assert all("per-revision attempt ceiling not exhausted" in row[3] for row in assign_rows)
    assert "both TASK branches the per-revision attempt ceiling must not be exhausted" in api
    assert "computed authoritatively from durable `attempt` rows" in api
    assert "BLOCKED` to **`ESCALATED`**" in contract
    assert "no further `attempt.assign` is admissible" in contract


def test_delivery_has_its_own_authority_and_complete_state_machine() -> None:
    """F-02: delivery authority and every declared delivery state have normative transitions."""
    api = read(STATE_API)
    contract = read(FREEZE_CONTRACT)
    assert "TASK|INTEGRATION|CANDIDATE|REVIEW|DELIVERY" in api
    assert "controller epoch of the last authoritative delivery mutation" in api
    assert "or NULL for a `DELIVERY` subject" in api
    assert "Delivery updates are not execution-record admissions" in contract
    assert "delivery idempotency key" in contract
    assert "idempotency-key/request-digest conflict" in contract

    delivery_record = api.split("### `delivery`", 1)[1].split("### `idempotency`", 1)[0]
    state_line = next(line for line in delivery_record.splitlines() if "state `" in line)
    match = re.search(r"state `([^`]+)`", state_line)
    assert match is not None
    declared = set(match.group(1).split("|"))

    rows = table_rows_in_numbered_section(STATE_API, "3C")
    assert rows, "§3C delivery transition matrix missing"
    to_states: set[str] = set()
    for row in rows:
        if len(row) < 3:
            continue
        for state in declared:
            if re.search(rf"\b{re.escape(state)}\b", row[2]):
                to_states.add(state)
    assert declared <= to_states, f"delivery states with no incoming normative edge: {sorted(declared - to_states)}"

    section2 = table_rows_in_numbered_section(STATE_API, "2")
    delivery_commands = {
        row[0].strip("`") for row in section2
        if row and row[0].startswith("`delivery.")
    }
    matrix_commands = " ".join(row[1] for row in rows if len(row) >= 2)
    for command in delivery_commands:
        assert command in matrix_commands, f"{command} has no §3C transition row"

# --------------------------------------------------------------------------------------------
# G-01 / G-02 / G-03 — stranded ASSIGNED subjects, ceiling accounting, delivery crash window.
# --------------------------------------------------------------------------------------------


ATTEMPT_BINDING_HEADER = "| Non-terminal attempt state | TASK subject state | INTEGRATION subject state |"
CEILING_HEADER = "| Attempt row | Consumes the ceiling? | Why |"


def attempt_subject_binding() -> dict[str, dict[str, str]]:
    """§3A.1 as `{"CREATED": {"TASK": "ASSIGNED", "INTEGRATION": "INTEGRATING"}}`."""
    binding: dict[str, dict[str, str]] = {}
    for row in table_rows_under_header(STATE_API, ATTEMPT_BINDING_HEADER):
        match = re.fullmatch(r"`attempt` ([A-Z_]+)", row[0])
        assert match is not None, f"unparseable §3A.1 row: {row[0]!r}"
        binding[match.group(1)] = {
            "TASK": row[1].strip("`"),
            "INTEGRATION": row[2].strip("`"),
        }
    return binding


def derived_execution_bearing_states() -> dict[str, frozenset[str]]:
    """Recompute §1A's execution-bearing set from §3A.1 and §3B rather than trusting either.

    This is the whole point of the G-01 repair: the set is a *derivation* of the transition
    matrices, so adding an attempt or dispatch edge under a new subject state must move this
    value and therefore fail every document that still claims the old one.
    """
    derived: dict[str, set[str]] = {"TASK": set(), "INTEGRATION": set()}
    for states in attempt_subject_binding().values():
        for kind, subject_state in states.items():
            derived[kind].add(subject_state)

    # §3B contributes the review-dispatch execution record, stated in the singular there.
    dispatch = numbered_section_text(STATE_API, "3B")
    for kind in ("TASK", "INTEGRATION"):
        match = re.search(rf"`{kind}` subject state `([A-Z_]+)`", dispatch)
        assert match is not None, f"§3B states no {kind} subject binding for `DISPATCHED`"
        derived[kind].add(match.group(1))

    return {kind: frozenset(states) for kind, states in derived.items()}


def test_attempt_matrix_binds_every_nonterminal_state_to_a_subject_state() -> None:
    """§3A.1 must cover exactly the non-terminal attempt states §3A actually defines."""
    binding = attempt_subject_binding()
    assert set(binding) == {"CREATED", "STARTING", "RUNNING", "CANDIDATE_READY"}, sorted(binding)

    # Every bound subject state must be a state the §3 subject matrix really uses, so the
    # binding cannot drift into naming something that does not exist.
    subject_rows = table_rows_in_numbered_section(STATE_API, "3")
    subject_states = set()
    for row in subject_rows:
        if len(row) >= 3:
            subject_states.update(re.findall(r"\b([A-Z][A-Z_]{3,})\b", f"{row[0]} {row[2]}"))
    for state, kinds in binding.items():
        for kind, subject_state in kinds.items():
            assert subject_state in subject_states, (
                f"§3A.1 binds attempt {state} ({kind}) to unknown subject state {subject_state}"
            )


def test_execution_bearing_states_are_derived_and_agree_across_documents() -> None:
    """G-01: `ASSIGNED` was missing from a hand-written list, so a fenced task was stranded.

    The repair replaces the list with a derivation. This test performs that derivation from
    §3A.1/§3B and asserts set equality against §1A and freeze contract §21 — not substring
    presence, so a document that keeps a stale enumeration fails even though every individual
    word it names still appears somewhere.
    """
    derived = derived_execution_bearing_states()

    # The specific hole G-01 named. Stated explicitly so a future edit that silently drops the
    # ASSIGNED binding from §3A.1 fails here rather than quietly shrinking the derived set.
    assert "ASSIGNED" in derived["TASK"], (
        "a TASK attempt in CREATED/STARTING is held under ASSIGNED; the derivation lost it"
    )
    assert derived["TASK"] == frozenset({"ASSIGNED", "BUILDING", "REVIEWING"}), derived["TASK"]
    assert derived["INTEGRATION"] == frozenset({"INTEGRATING", "REVIEWING"}), derived["INTEGRATION"]

    for label, text in (
        ("state API §1A", numbered_section_text(STATE_API, "1A")),
        ("freeze contract §21", numbered_section_text(FREEZE_CONTRACT, "21")),
    ):
        claimed = declared_execution_bearing_states(text)
        for kind in ("TASK", "INTEGRATION"):
            assert claimed[kind] == derived[kind], (
                f"{label} claims {kind} execution-bearing states {sorted(claimed[kind])}, "
                f"but §3A.1/§3B derive {sorted(derived[kind])}"
            )


def test_stranded_execution_bearing_subject_blocks_through_a_listed_edge() -> None:
    """Reconciliation must surface the stranded subject, with a typed reason and no redispatch."""
    api = read(STATE_API)
    contract = read(FREEZE_CONTRACT)

    assert dict(reason_code_table()).get("EXECUTION_RECORD_MISSING") == "BLOCKED", (
        "the stranded-subject reason code is missing or not fail-closed"
    )
    for text, name in ((api, "state API"), (contract, "freeze contract")):
        assert "EXECUTION_RECORD_MISSING" in text, f"{name} names no typed reason for the strand"

    # The block edge must already exist in §3; the repair may not invent a new transition.
    subject_rows = table_rows_in_numbered_section(STATE_API, "3")
    block_edges = [
        row for row in subject_rows
        if len(row) >= 3 and row[1] in {"task.block", "integration.block"} and row[2].endswith("BLOCKED")
    ]
    assert {row[1] for row in block_edges} == {"task.block", "integration.block"}, block_edges
    task_block = next(row for row in block_edges if row[1] == "task.block")
    assert "EXECUTION_RECORD_MISSING" in task_block[3], (
        "the §3 task.block row does not carry the reconciliation case"
    )
    assert "ASSIGNED" in task_block[3]

    one_a = numbered_section_text(STATE_API, "1A")
    assert "MUST NOT be resolved by blind re-dispatch" in one_a


def test_pre_running_fencing_does_not_consume_the_execution_attempt_ceiling() -> None:
    """G-02: restart fencing burned real execution budget, so restarts could starve a task."""
    rows = table_rows_under_header(STATE_API, CEILING_HEADER)
    verdicts = {row[0]: row[1].lower() for row in rows}
    assert set(verdicts.values()) <= {"yes", "no", "**no**"}, verdicts

    def verdict_for(fragment: str) -> str:
        matches = [value for key, value in verdicts.items() if fragment in key]
        assert len(matches) == 1, f"{fragment!r} matches {len(matches)} ceiling rows"
        return matches[0].strip("*")

    assert verdict_for("non-terminal") == "yes"
    assert verdict_for("`CLOSED / SUCCEEDED`") == "yes"
    assert verdict_for("`CLOSED / FAILED`") == "yes"
    assert verdict_for("`CLOSED / QUARANTINED`") == "yes"
    assert verdict_for("**that reached `RUNNING`**") == "yes"
    assert verdict_for("**that never reached `RUNNING`**") == "no"

    # Totality: every terminal disposition the schema declares is classified exactly once.
    attempt_block = read(STATE_API).split("### `attempt`", 1)[1].split("### `lease`", 1)[0]
    match = re.search(r"terminal disposition nullable `([^`]+)`", attempt_block)
    assert match is not None
    dispositions = set(match.group(1).split("|"))
    classified = {
        disposition
        for disposition in dispositions
        if any(disposition in key for key in verdicts)
    }
    assert classified == dispositions, (
        f"dispositions with no ceiling classification: {sorted(dispositions - classified)}"
    )

    api = read(STATE_API)
    contract = read(FREEZE_CONTRACT)
    # Reaching RUNNING must be decidable from the committed row, without a new column.
    assert "NULL until the attempt commits `RUNNING`" in api
    # R-02 must not be weakened: the guard stays on every assignment path.
    assert "The ceiling guard on every `attempt.assign` path in §3 and in this matrix is unchanged" in api
    # Deterministic preflight failure must stay budget-consuming.
    assert "never `CANCELLED`/`FENCED`" in contract
    # The contract must defer to one definition rather than keeping the old count-everything rule.
    assert "counting every attempt whatever its disposition" not in contract
    assert "MUST NOT restate it differently" in contract


def test_delivery_cannot_blindly_replay_an_initiated_external_effect() -> None:
    """G-03: a crash between the external effect and outcome persistence must not duplicate it."""
    rows = table_rows_in_numbered_section(STATE_API, "3C")
    section = numbered_section_text(STATE_API, "3C")

    def from_states(cell: str) -> set[str]:
        return set(re.findall(r"\b(PENDING|UNKNOWN|PUBLISHED|FAILED|BLOCKED|none)\b", cell))

    publish_rows = [row for row in rows if len(row) >= 4 and "delivery.publish" in row[1]]
    assert publish_rows, "§3C lists no `delivery.publish` edge at all"

    # Every state an external effect can be initiated from, taken from the matrix rather than
    # asserted by prose.
    initiating = set()
    for row in publish_rows:
        initiating |= from_states(row[0]) - {"none"}
    assert initiating == {"PENDING"}, (
        f"`delivery.publish` is admissible from {sorted(initiating)}; only PENDING may arm an effect"
    )

    # Each publish row must be gated on the durable initiation marker, in From or preconditions.
    for row in publish_rows:
        assert "attempt count" in f"{row[0]} {row[2]} {row[3]}", (
            f"§3C publish row has no `attempt count` gate: {row[0]!r} / {row[1]!r}"
        )

    # The arming row must commit the marker before the effect.
    arming = [row for row in publish_rows if "arms the external effect" in row[1]]
    assert len(arming) == 1, arming
    assert "attempt count = 0" in arming[0][0]
    assert "attempt count >= 1" in arming[0][2]
    assert "committed **before** the external publication effect is initiated" in arming[0][3]

    # Restart with the marker set must reconcile to UNKNOWN before any further external effect.
    restart_rows = [
        row for row in rows
        if len(row) >= 4 and "restart" in row[1] and "attempt count >= 1" in row[0]
    ]
    assert len(restart_rows) == 1, restart_rows
    assert restart_rows[0][2] == "UNKNOWN", restart_rows[0]
    assert "before any further external effect" in restart_rows[0][3]

    # Every state that can initiate an effect must be terminal or carry an explicit
    # reconciliation rule out of the ambiguity it can produce.
    reconcile_targets: set[str] = set()
    for row in rows:
        if len(row) >= 3 and ("delivery.reconcile" in row[1] or "restart" in row[1]):
            reconcile_targets |= from_states(row[0])
    terminal = {"PUBLISHED", "BLOCKED"}
    for state in initiating | {"UNKNOWN"}:
        assert state in terminal or state in reconcile_targets, (
            f"§3C state {state} can hold an initiated effect with no reconciliation rule"
        )

    # Replay out of ambiguity is refused, and reconciliation is the only exit.
    assert not [row for row in publish_rows if "UNKNOWN" in from_states(row[0])], (
        "§3C admits `delivery.publish` directly from UNKNOWN"
    )
    assert "MUST be refused for a record in `UNKNOWN`, with reason code `REMOTE_EFFECT_UNKNOWN`" in section
    assert "is the **only** path out of `UNKNOWN`" in section
    assert "MUST NOT be satisfied by replaying the publication" in section
    assert "Any delivery transition not listed above is forbidden" in section

    contract = read(FREEZE_CONTRACT)
    assert "MUST be committed *before* the effect is initiated, never after it" in contract
    assert "MUST NOT infer from a `PENDING` record alone that no effect has occurred" in contract
    assert "before any further external effect" in numbered_section_text(FREEZE_CONTRACT, "21")


# --------------------------------------------------------------------------------------------
# H-01 — no §3 subject transition may strand a live execution record.
# --------------------------------------------------------------------------------------------


SUBJECT_MATRIX_HEADER = "| From | Command | To | Mandatory preconditions |"
PROCESS_FACT_HEADER = "| Durable fact | Field | Written | Read by |"

ANY_NONTERMINAL = "any nonterminal active"
DISPATCH_TERMINAL = frozenset({"COMPLETED", "CANCELLED", "FENCED", "EXPIRED"})


def subject_states_in(cell: str) -> frozenset[str]:
    """Subject-state names in a §3 `From`/`To` cell.

    `ReleaseCandidate record` deliberately yields nothing: it is not a subject state, and the
    `release_candidate.mark` row must not be mistaken for an exit from the execution-bearing set.
    """
    return frozenset(re.findall(r"\b([A-Z][A-Z_]{2,})\b", cell))


def subject_matrix() -> list[dict[str, object]]:
    """§3 rows as structured records, with subject kind and command resolved per row."""
    derived = derived_execution_bearing_states()
    parsed: list[dict[str, object]] = []
    for row in table_rows_under_header(STATE_API, SUBJECT_MATRIX_HEADER):
        assert len(row) == 4, f"unparseable §3 row: {row}"
        source, command_cell, target, preconditions = row
        command_match = re.match(r"([a-z_]+\.[a-z_]+)", command_cell)
        assert command_match is not None, f"§3 row names no command: {command_cell!r}"
        command = command_match.group(1)
        kind = (
            "INTEGRATION"
            if "integration" in f"{source} {command} {target}"
            else "TASK"
        )
        bearing = derived[kind]
        if ANY_NONTERMINAL in source:
            # "any nonterminal active" is every non-terminal subject state, which necessarily
            # includes every execution-bearing one.
            from_states: frozenset[str] = bearing
        else:
            from_states = subject_states_in(source)
        parsed.append(
            {
                "from": from_states,
                "command": command,
                "to": subject_states_in(target),
                "preconditions": preconditions,
                "kind": kind,
                "bearing": bearing,
            }
        )
    assert len(parsed) > 25, f"§3 matrix looks truncated: {len(parsed)} rows"
    return parsed


def rows_leaving_the_execution_bearing_set() -> list[dict[str, object]]:
    """Exactly the §3 rows that carry a subject out of its execution-bearing set."""
    leaving = []
    for row in subject_matrix():
        held = row["from"] & row["bearing"]
        if not held:
            continue
        if not row["to"]:
            # No subject state is entered (`release_candidate.mark` creates a record instead).
            continue
        if row["to"] & row["bearing"]:
            continue
        leaving.append(row)
    return leaving


def test_every_subject_transition_leaving_execution_disposes_of_its_records() -> None:
    """H-01: `candidate.reject` could strand live reviewers, and `task.block` fenced only
    "when continuation unsafe".

    This is derived from the §3 rows themselves. It recomputes which rows leave the
    execution-bearing set — using the same §3A.1/§3B derivation §1A depends on — and requires each
    one to carry an explicit, normative disposal obligation. A prose restatement elsewhere cannot
    satisfy it, which is the point: two documents agreeing with each other is exactly how the
    contradiction survived the previous round.
    """
    leaving = rows_leaving_the_execution_bearing_set()

    # The specific edges the review named, stated so a future edit that quietly removes one from
    # the matrix cannot shrink this check into vacuous truth.
    commands = {row["command"] for row in leaving}
    for required in (
        "candidate.reject",
        "integration.reject",
        "integration.block",
        "task.escalate",
        "task.fail",
        "task.block",
    ):
        assert required in commands, f"{required} no longer appears as an edge leaving execution"

    problems: list[str] = []
    for row in leaving:
        cell = row["preconditions"]
        fence = "[EXEC-FENCE]" in cell
        atomic = "[EXEC-ATOMIC-CLOSE:" in cell
        if fence == atomic:
            problems.append(
                f"{row['command']} ({row['kind']}) leaves {sorted(row['from'] & row['bearing'])} "
                f"for {sorted(row['to'])} carrying "
                + ("both tokens" if fence else "neither [EXEC-FENCE] nor [EXEC-ATOMIC-CLOSE]")
            )
    assert not problems, "; ".join(problems)

    # `task.block` fences unconditionally now; the conditional qualifier was the defect.
    task_block = [row for row in leaving if row["command"] == "task.block"]
    assert len(task_block) == 1, task_block
    assert "when continuation unsafe" not in task_block[0]["preconditions"], (
        "task.block still fences only when continuation is judged unsafe"
    )
    assert "unconditionally" in task_block[0]["preconditions"]

    section = numbered_section_text(STATE_API, "3")
    assert "### 3.1 Execution-record fencing on subject transitions" in section
    assert "before the subject transition commits" in section


def test_atomic_close_rows_name_a_real_terminal_attempt_edge() -> None:
    """The `[EXEC-ATOMIC-CLOSE]` escape may only cite an edge that exists and is terminal."""
    attempt_rows = table_rows_in_numbered_section(STATE_API, "3A")
    atomic = [
        row for row in rows_leaving_the_execution_bearing_set()
        if "[EXEC-ATOMIC-CLOSE:" in row["preconditions"]
    ]
    assert {row["command"] for row in atomic} == {"evidence.register", "integration.register"}, (
        sorted(row["command"] for row in atomic)
    )
    for row in atomic:
        named = re.search(r"\[EXEC-ATOMIC-CLOSE: §3A ([A-Z_]+) -> (CLOSED) / ([A-Z]+)\]", row["preconditions"])
        assert named is not None, f"{row['command']} names no parseable §3A edge"
        source, _, disposition = named.groups()
        matching = [
            edge for edge in attempt_rows
            if len(edge) >= 3 and edge[0] == source and "CLOSED" in edge[2] and disposition in edge[2]
        ]
        assert matching, f"{row['command']} cites §3A {source} -> CLOSED / {disposition}, which does not exist"


def test_attempt_and_dispatch_matrices_carry_the_fencing_triggers_section_3_needs() -> None:
    """H-01's "matrices must agree" half, derived rather than restated.

    For every `[EXEC-FENCE]` row, §3A.1 says which non-terminal attempt states the states it
    leaves can actually hold, and §3B says whether those states can hold a dispatch. Each such
    command must then appear as a trigger on the corresponding terminal edge. Adding a §3 edge
    without teaching §3A/§3B about it fails here.
    """
    binding = attempt_subject_binding()
    dispatch_section = numbered_section_text(STATE_API, "3B")
    dispatch_bearing = {
        kind: re.search(rf"`{kind}` subject state `([A-Z_]+)`", dispatch_section).group(1)
        for kind in ("TASK", "INTEGRATION")
    }

    attempt_rows = table_rows_in_numbered_section(STATE_API, "3A")
    terminal_attempt_edges: dict[str, list[str]] = {}
    for row in attempt_rows:
        if len(row) >= 3 and row[0] in binding and "CLOSED" in row[2]:
            terminal_attempt_edges.setdefault(row[0], []).append(row[1])

    terminal_dispatch_triggers = " ".join(
        row[1] for row in table_rows_in_numbered_section(STATE_API, "3B")
        if len(row) >= 3 and row[0] == "DISPATCHED" and row[2] in DISPATCH_TERMINAL
    )

    # The requirement is derived from *which rows leave the set*, not from which rows carry the
    # token. Driving it off the token would make this test vacuously green on a matrix that has
    # no tokens at all — precisely the false-green shape this repair exists to remove.
    missing: list[str] = []
    checked = 0
    for row in rows_leaving_the_execution_bearing_set():
        if "[EXEC-ATOMIC-CLOSE:" in row["preconditions"]:
            # Closed through the named paired edge instead; covered by its own test.
            continue
        command, kind = row["command"], row["kind"]
        held = row["from"] & row["bearing"]

        for attempt_state, kinds in binding.items():
            if kinds[kind] not in held:
                continue
            checked += 1
            triggers = terminal_attempt_edges.get(attempt_state, [])
            if not any(f"`{command}`" in trigger for trigger in triggers):
                missing.append(f"§3A {attempt_state} has no `{command}` terminal trigger")

        if dispatch_bearing[kind] in held:
            checked += 1
            if f"`{command}`" not in terminal_dispatch_triggers:
                missing.append(f"§3B DISPATCHED has no `{command}` terminal trigger")

    assert checked > 20, f"only {checked} matrix agreements derived; the derivation went vacuous"
    assert not missing, "; ".join(sorted(set(missing)))


def test_fencing_frees_the_slot_and_stops_the_process_group_before_the_commit() -> None:
    """The two consequences H-01 requires beyond mere record termination."""
    fencing = numbered_section_text(STATE_API, "3")
    cancellation = numbered_section_text(STATE_API, "6")

    assert "MUST be stopped through §6 before that commit" in fencing
    assert "MUST be reusable as soon as the subject transition commits" in fencing
    assert "MUST NOT continue to occupy a slot, a lease or a concurrency unit" in fencing

    # §6 must actually cover review dispatches, not attempts alone, and must order itself
    # before the subject transition.
    assert "review dispatches" in cancellation
    assert "before the subject transition commits" in cancellation
    assert "MUST NOT continue to occupy a slot, a lease or a concurrency unit" in cancellation

    # §3B must forbid the strand explicitly and point at the mechanism that prevents it.
    dispatch = numbered_section_text(STATE_API, "3B")
    assert "MUST NOT exist under any other subject state" in dispatch
    assert "MUST fence those siblings rather than abandon them" in dispatch


# --------------------------------------------------------------------------------------------
# H-02 — the pre-RUNNING cleanup handle and the ceiling discriminator are separate facts.
# --------------------------------------------------------------------------------------------


CLEANUP_HANDLE = "lease.owned_process_group_handle"
CEILING_DISCRIMINATOR = "attempt.running_process_group_identity"


def test_pre_running_cleanup_handle_and_ceiling_discriminator_are_distinct_facts() -> None:
    """H-02: one `process-group identity` field answered both "what do I kill?" and "did this
    attempt ever run?", and those two questions have different answers during STARTING.

    The repair is schema-free — an existing lease field and the existing committed-RUNNING fact
    take one role each — so this test's job is to prove the roles really are separate: two named
    fields, two population times, one reader each, and no document naming one where the other is
    meant.
    """
    api = read(STATE_API)

    facts = table_rows_under_header(STATE_API, PROCESS_FACT_HEADER)
    assert len(facts) == 2, facts
    fields = [row[1].strip("`") for row in facts]
    assert fields == [CLEANUP_HANDLE, CEILING_DISCRIMINATOR], fields
    assert len(set(fields)) == 2, "the two durable facts collapsed onto one field"

    cleanup, ceiling = facts
    # Population timing is normative and opposite: the handle is written *before* the fork, the
    # discriminator only at the RUNNING commit.
    assert "**before** the attempt's single owned process group is created" in cleanup[2]
    assert "CREATED -> STARTING" in cleanup[2]
    # H-03: the handle has exactly ONE population time. It must not also be written at the
    # RUNNING commit — that handover is the defect, not a second legitimate timing.
    assert "STARTING -> RUNNING" not in cleanup[2], (
        "the cleanup handle is written at STARTING -> RUNNING too, which is the H-03 handover"
    )
    assert "never written again" in cleanup[2]
    assert "exactly once" in ceiling[2] and "STARTING -> RUNNING" in ceiling[2]
    assert "NULL at every other time" in ceiling[2]

    # One reader each, and neither is the other's reader.
    assert "§6" in cleanup[3] and "§21" in cleanup[3]
    assert ceiling[3].strip().startswith("§3A.2")
    assert "§3A.2" not in cleanup[3]
    assert "§6" not in ceiling[3]

    # The schema declares each field on exactly one record.
    attempt_block = api.split("### `attempt`", 1)[1].split("### `lease`", 1)[0]
    lease_block = api.split("### `lease`", 1)[1].split("### `review_dispatch`", 1)[0]
    assert "`running_process_group_identity`" in attempt_block
    assert "`owned_process_group_handle`" in lease_block
    assert "- `owned_process_group_handle`" not in attempt_block
    assert "- `running_process_group_identity`" not in lease_block


def test_the_four_sections_agree_on_which_fact_they_use() -> None:
    """§1A, §3A, §3A.2 and §6 must each name the field whose role they actually need."""
    ceiling = numbered_section_text(STATE_API, "3A")
    # §3A.2 lives inside §3A; address the ceiling subsection precisely through its own table.
    assert CEILING_DISCRIMINATOR in ceiling.split("### 3A.2", 1)[1].split("### 3A.3", 1)[0], (
        "§3A.2 does not name the ceiling discriminator"
    )

    one_a = numbered_section_text(STATE_API, "1A")
    assert "two different fields with two different population times" in one_a
    assert "MUST NOT be inferred from the other" in one_a

    cancellation = numbered_section_text(STATE_API, "6")
    assert f"`{CLEANUP_HANDLE}`" in cancellation, "§6 identifies no durable cleanup handle"
    assert CEILING_DISCRIMINATOR not in cancellation, (
        "§6 reaches for the ceiling discriminator, which is NULL exactly when cleanup matters most"
    )

    # The pre-RUNNING attempt edges must populate and read the right one.
    rows = table_rows_in_numbered_section(STATE_API, "3A")
    to_starting = [row for row in rows if len(row) >= 3 and row[0] == "CREATED" and row[2] == "STARTING"]
    assert len(to_starting) == 1, to_starting
    assert f"`{CLEANUP_HANDLE}` is committed **before**" in to_starting[0][3]
    assert "`attempt.running_process_group_identity` stays NULL" in to_starting[0][3]

    to_running = [row for row in rows if len(row) >= 3 and row[0] == "STARTING" and row[2] == "RUNNING"]
    assert len(to_running) == 1, to_running
    assert "`attempt.running_process_group_identity` is written in this same commit" in to_running[0][3]


def test_crash_during_starting_is_cleaned_up_without_quarantine_or_budget_loss() -> None:
    """The STARTING crash window resolves deterministically, in all three of its outcomes."""
    three_a_three = numbered_section_text(STATE_API, "3A").split("### 3A.3", 1)[1]

    # A missing handle is proof of no group, not an unknown — that is what removes the ambiguity.
    assert "positive proof that no owned group exists" in three_a_three
    assert "MUST close `FENCED`/`CANCELLED`" in three_a_three
    # A live group is identified, stopped and closed FENCED without charging the ceiling.
    assert "stopping the named group through §6" in three_a_three
    assert "cannot consume execution budget" in three_a_three
    # QUARANTINED is reserved for genuinely unprovable cleanup.
    assert "MUST NOT be used merely because no durable identity was recorded" in three_a_three
    # R-02 survives: deterministic preflight failure is still budget-consuming.
    assert "remains budget-consuming and R-02 is not weakened" in three_a_three

    rows = table_rows_in_numbered_section(STATE_API, "3A")
    quarantine = [
        row for row in rows
        if len(row) >= 3
        and row[0] == "STARTING"
        and "QUARANTINED" in row[2]
        and "cannot be proven stopped" in row[1]
    ]
    assert len(quarantine) == 1, quarantine
    assert CLEANUP_HANDLE in quarantine[0][1], (
        "the STARTING quarantine edge does not say which group could not be proven stopped"
    )
    assert "a NULL or absent handle is proof of no group" in quarantine[0][3]

    # Restart reconciliation must use the same fact under the same rule.
    step_five = numbered_section_text(FREEZE_CONTRACT, "21")
    assert "`owned_process_group_handle`" in step_five
    assert "An attempt found in `STARTING` is reconciled here" in step_five
    assert "does not consume the §10.3.1 ceiling" in step_five


# --------------------------------------------------------------------------------------------
# H-03 — one owned process group per attempt, and a write-once cleanup handle.
# --------------------------------------------------------------------------------------------

# The exact wording the rejected tree used to hand the handle from a preflight group to a model
# group. Scanning for it is what makes this guard fail `9fbe4a9` rather than merely describe the
# repair: the defect was a *positive* claim, so its absence is checkable.
HANDOVER_WORDINGS = (
    "updated to the model process group",
    "and then for the model process group on `STARTING -> RUNNING`",
    "first for the preflight group on `CREATED -> STARTING`",
    "the durable identity of whatever process group this attempt currently owns",
    "the durable identity of whatever process group the attempt currently owns",
    "preflight group on `CREATED -> STARTING`, model group on `STARTING -> RUNNING`",
)


@pytest.mark.parametrize("path", FREEZE_SET, ids=lambda p: p.name)
def test_no_freeze_document_retains_the_two_group_handover_wording(path: Path) -> None:
    """H-03: the handle must not be described as moving from one group to another.

    Between overwriting the handle and proving the first group empty, a surviving preflight
    descendant is owned by nothing the database can name. Freeze contract §11's "no reuse until
    emptiness is verified" then passes vacuously over the model group alone.
    """
    text = read(path)
    for wording in HANDOVER_WORDINGS:
        assert wording not in text, (
            f"{path.name} still hands the cleanup handle over to a second group: {wording!r}"
        )


def test_the_running_commit_must_not_replace_the_cleanup_handle() -> None:
    """The `STARTING -> RUNNING` row carries an explicit prohibition, not merely silence.

    Silence would leave two conformant kernels free to disagree, which is exactly how the
    handover survived the H-02 repair.
    """
    rows = table_rows_in_numbered_section(STATE_API, "3A")
    to_running = [
        row for row in rows if len(row) >= 3 and row[0] == "STARTING" and row[2] == "RUNNING"
    ]
    assert len(to_running) == 1, to_running
    cell = to_running[0][3]

    assert "MUST NOT update, replace or clear" in cell, (
        "the RUNNING edge does not forbid replacing the cleanup handle"
    )
    assert CLEANUP_HANDLE in cell
    # The model process joins the group that already exists rather than getting a new one.
    assert "inside the attempt's existing owned process group" in cell
    assert "no second group is created" in cell
    # And the ceiling discriminator is not quietly promoted into the vacated cleanup role.
    assert "MUST NOT be used as the cleanup handle" in cell

    # The one edge that *may* write the handle is the earlier one, and it says so exclusively.
    to_starting = [
        row for row in rows if len(row) >= 3 and row[0] == "CREATED" and row[2] == "STARTING"
    ]
    assert len(to_starting) == 1, to_starting
    assert "only edge that may write" in to_starting[0][3]


def test_one_group_per_attempt_agrees_across_the_contract_and_the_state_api() -> None:
    """FC §11 and SA §3A.3 must agree on one group with a write-once lifetime owner.

    The rejected tree had §11 giving each attempt one cgroup covering the "complete attempt
    process tree" while §3A.3 gave it two with a handover — a direct contradiction between two
    normative documents, which the freeze gate is supposed to make impossible.
    """
    workspace = numbered_section_text(FREEZE_CONTRACT, "11")
    assert "**exactly one** per attempt" in workspace
    assert "never handed over to a second group while the attempt is live" in workspace
    # Emptiness is proved over the whole group, so a narrower proof cannot satisfy the rule.
    assert "verified empty" in workspace and "that whole group" in workspace
    assert "an emptiness proof over any narrower group does not satisfy this rule" in workspace

    three_a_three = numbered_section_text(STATE_API, "3A").split("### 3A.3", 1)[1]
    assert "**exactly one** controller-created process group" in three_a_three
    assert "both preflight and model execution run inside it" in three_a_three
    assert "the cleanup handle is therefore **write-once**" in three_a_three.lower()
    assert "A two-group handover" in three_a_three and "is **forbidden**" in three_a_three
    # The consequence that closes the finding: the surviving child stays visible.
    assert "cannot become invisible" in three_a_three

    # §6 must prove emptiness over the entire group, not over whatever the handle last named.
    cancellation = numbered_section_text(STATE_API, "6")
    assert "verify the **entire** owned process group is empty" in cancellation
    assert "surviving preflight descendants are included" in cancellation


def test_cleanup_handles_are_controller_allocated_and_reuse_fails_closed() -> None:
    """A handle that outlives a crash must not resolve onto a recycled unrelated group."""
    three_a_three = numbered_section_text(STATE_API, "3A").split("### 3A.3", 1)[1]

    assert "controller-allocated, attempt-bound (or dispatch-bound) identity" in three_a_three
    assert "MUST NOT be a bare recyclable OS process-group/process number" in three_a_three
    # Ownership is re-verified before a signal is sent, and a failed check fails closed.
    assert "before signalling, §6 MUST verify" in three_a_three
    assert "the controller MUST NOT signal it" in three_a_three
    assert "fails closed" in three_a_three

    cancellation = numbered_section_text(STATE_API, "6")
    assert "verify that the group the handle resolves to is still the one this record created" in (
        cancellation
    )
    assert "A handle that fails the ownership check is never signalled" in cancellation


# --------------------------------------------------------------------------------------------
# H-04 — a kernel-owned reviewer is write-ahead too, and ownership is read from the principal.
# --------------------------------------------------------------------------------------------


def review_dispatch_block() -> str:
    """The `review_dispatch` schema block, addressed as a record rather than as prose."""
    api = read(STATE_API)
    return api.split("### `review_dispatch`", 1)[1].split("### `authority_grant`", 1)[0]


def test_review_dispatch_records_a_durable_reviewer_ownership_kind() -> None:
    """H-04: external-vs-kernel-owned must be a committed fact, not an inference from NULL."""
    block = review_dispatch_block()

    assert "`KERNEL_OWNED|EXTERNAL`" in block, (
        "the dispatch records no durable execution-ownership kind for its reviewer principal"
    )
    # It must be durable before any reviewer process exists, or the crash window reopens.
    assert "committed durably in the same transaction that creates the `DISPATCHED` row" in block
    assert "immutable thereafter" in block
    assert "before any reviewer process exists" in block
    assert "the **only** authoritative answer" in block


def test_kernel_owned_reviewer_handle_is_write_ahead_and_null_is_not_externality() -> None:
    """The dispatch's process-group identity obeys the attempt's write-ahead rule.

    The rejected tree read NULL as "external principal, do not signal". A crash between reviewer
    fork and identity persistence is indistinguishable from that, so §6 skipped a live
    kernel-owned reviewer and released its slot.
    """
    block = review_dispatch_block()

    assert "same §3A.3 write-ahead, write-once, controller-allocated rule" in block
    assert "committed **before** the reviewer process group is created" in block
    assert "positive proof that no owned reviewer group exists" in block
    assert "**not** a signal that the reviewer is external" in block, (
        "NULL on the dispatch handle is still overloaded as externality"
    )
    # External dispatches keep fencing-only semantics, and that limitation stays recorded.
    assert "For an `EXTERNAL` dispatch it is always NULL" in block
    assert "cancellation relies on fencing alone" in block
    assert "that limitation is recorded" in block


def test_section_six_branches_on_reviewer_ownership_before_it_signals() -> None:
    """§6 step 3 must decide ownership from the principal first, then signal."""
    cancellation = numbered_section_text(STATE_API, "6")
    step_three = cancellation.split("3. ", 1)[1].split("\n4. ", 1)[0]

    assert "ownership first" in step_three
    assert "from durable principal/role identity, never from a NULL handle" in step_three
    # The kernel-owned branch covers attempts and kernel-owned dispatches identically.
    assert "execution-ownership kind `KERNEL_OWNED`" in step_three
    assert "it does **not** mean the process belongs to someone else" in step_three
    # Fencing-only is reachable only through an EXTERNAL principal.
    assert "only for a `review_dispatch` whose reviewer principal carries execution-ownership" in (
        step_three
    )

    # Resources are released at the proof of emptiness, never at the unprovable-cleanup step.
    assert "at step 6 **and never at step 7**" in cancellation
    assert "no replacement reviewer can be admitted while that orphan may still be alive" in (
        cancellation
    )


def test_restart_reconciliation_treats_a_forkless_kernel_reviewer_as_kernel_owned() -> None:
    """Freeze contract §21 step 8 must reconcile on ownership, not on a NULL identity."""
    step_eight = numbered_section_text(FREEZE_CONTRACT, "21")
    step_eight = step_eight.split("8. reconcile", 1)[1].split("\n9. ", 1)[0]

    assert "never the process-group identity" in step_eight
    assert "write-once handle committed before the reviewer was forked" in step_eight
    assert "a NULL handle proves no group was created" in step_eight
    # The exact crash the finding describes, named and resolved.
    assert (
        "A crash between the reviewer-handle commit and the reviewer fork is therefore "
        "reconciled as a kernel-owned dispatch with no group, not as an external reviewer"
    ) in step_eight
    # The slot and the concurrency unit stay held while the orphan may exist.
    assert "still held" in step_eight


def test_the_substrate_rules_really_do_apply_to_all_three_execution_records() -> None:
    """§1A claims uniformity over all three records; §3A.3 must actually deliver it."""
    one_a = numbered_section_text(STATE_API, "1A")
    assert "The following rules apply uniformly to all three" in one_a
    assert "implementation attempt, integration attempt and review dispatch alike" in one_a
    assert "**at most one** controller-created process group" in one_a
    assert "MUST NOT hand its cleanup handle over from one group to another" in one_a
    assert "never from a NULL cleanup handle" in one_a

    three_a_three = numbered_section_text(STATE_API, "3A").split("### 3A.3", 1)[1]
    assert "normative for **all three** execution records" in three_a_three
    assert "not for attempts alone" in three_a_three


def test_acceptance_arms_exist_for_both_repaired_findings() -> None:
    """ST-16 and ST-17 must carry the arms that would catch a regression of H-03/H-04."""
    rows = {row[0]: row for row in table_rows_under_header(
        ACCEPTANCE_MATRIX, "| ID | Scenario | Expected invariant / result |"
    ) if row}

    st16 = " ".join(rows["ST-16"])
    assert "Surviving-preflight-child arm" in st16
    assert "neither updated nor replaced it" in st16
    assert "rather than over a model-only group" in st16
    # R-02's budget semantics are explicitly preserved by the new arm.
    assert "R-02's attempt-budget semantics are preserved" in st16

    st17 = " ".join(rows["ST-17"])
    assert "Kernel-owned reviewer crash arm" in st17
    assert "around reviewer process creation" in st17
    assert "before `REJECTED` commits" in st17
    assert "are **not** released" in st17
    assert "External-principal negative arm" in st17
    assert "fencing-only path is reachable *only* through the external principal kind" in st17


# --------------------------------------------------------------------------------------------
# Regression guards for the previously validated N-series repairs.
# --------------------------------------------------------------------------------------------


def test_traceability_dispositions_every_reviewed_finding() -> None:
    """Silence is not a disposition: N-01..N-04 and B-01..B-05 each carry an explicit row."""
    text = read(TRACEABILITY)
    assert "Silence is not a disposition." in text
    for finding in ("N-01", "N-02", "N-03", "N-04", "B-01", "B-02", "B-03", "B-04", "B-05", "R-01", "R-02", "R-03", "F-01", "F-02", "F-03", "G-01", "G-02", "G-03", "H-01", "H-02", "H-03", "H-04"):
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
