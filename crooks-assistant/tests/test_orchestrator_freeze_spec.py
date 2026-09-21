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


def table_rows_under_header_in(text: str, header: str) -> list[list[str]]:
    """Rows of the one markdown table whose header row is exactly `header`, over a document held
    in memory rather than on disk.

    The K-01 mutation harness has to parse a *mutated* copy of the state API, so every parser the
    handle-write gate depends on is reachable from a string as well as from a path.
    """
    rows: list[list[str]] = []
    collecting = False
    for line in text.splitlines():
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
    return rows


def table_rows_under_header(path: Path, header: str) -> list[list[str]]:
    """Rows of the one markdown table whose header row is exactly `header`.

    Several documents now carry more than one table inside a single numbered section, so
    `table_rows_in_numbered_section` is too coarse to address them individually.
    """
    rows = table_rows_under_header_in(read(path), header)
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
DISPATCH_TERMINAL = frozenset({"COMPLETED", "CANCELLED", "FENCED", "EXPIRED", "QUARANTINED"})


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
    # J-01: the release is conditioned on the cleanup proof, not on the fencing. The clean path
    # still frees at the subject commit; the unproven path keeps its occupancy.
    assert "MUST be reusable as soon as the subject transition commits" in fencing
    assert "**Terminality alone MUST NOT release a resource**" in fencing
    assert "MUST keep it occupying its slot, its concurrency unit and its lease" in fencing

    # §6 must actually cover review dispatches, not attempts alone, and must order itself
    # before the subject transition.
    assert "review dispatches" in cancellation
    assert "before the subject transition commits" in cancellation
    assert (
        "MUST continue to occupy the slot, the lease and the concurrency unit it held"
    ) in cancellation

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
# H-03 follow-up — the one-group invariant proved by a declared count, not by a phrase blacklist.
# --------------------------------------------------------------------------------------------


GROUP_CARDINALITY_HEADER = "| Record kind | Owned process groups over the lifetime | Handle write points |"


def declared_group_cardinality_in(api_text: str) -> dict[str, tuple[str, str]]:
    """§3A.3's cardinality table as `{record kind: (group count, write points)}`."""
    rows = table_rows_under_header_in(api_text, GROUP_CARDINALITY_HEADER)
    assert rows, f"no table found under header {GROUP_CARDINALITY_HEADER!r}"
    return {row[0]: (row[1], row[2]) for row in rows}


def declared_group_cardinality() -> dict[str, tuple[str, str]]:
    """§3A.3's cardinality table, read from the committed state API."""
    return declared_group_cardinality_in(read(STATE_API))


# --------------------------------------------------------------------------------------------
# K-01 — every §3A mention of the cleanup handle is *classified*, not scanned for one verb.
#
# The previous detector was `f"`{CLEANUP_HANDLE}` is committed" in row[3]`: a single verbatim
# verb. An operative second write phrased "is written", "is rewritten", "is updated to",
# "is replaced with" or "is set to" was therefore invisible, the derived write count stayed 1,
# matched the declared 1, and the freeze gate went green on a restored H-03 handover. What
# follows replaces that with a closed-marker classifier that assigns every mention exactly one
# of WRITES / PROHIBITS_WRITE / READS_ONLY and fails closed on anything it cannot classify.
# --------------------------------------------------------------------------------------------

ATTEMPT_TRANSITION_HEADER = "| From | Trigger/command | To | Preconditions / result |"

# Match the *field*, not the English phrase "cleanup handle". §3A's `STARTING -> RUNNING` row also
# says the ceiling discriminator "MUST NOT be used as the cleanup handle", which is a statement
# about `attempt.running_process_group_identity` and must not be dragged into this classification.
HANDLE_MENTION_RE = re.compile(r"`(?:lease\.)?owned_process_group_handle`")

WRITES = "WRITES"
PROHIBITS_WRITE = "PROHIBITS_WRITE"
READS_ONLY = "READS_ONLY"
UNCLASSIFIED = "UNCLASSIFIED"

# Closed marker set: verbs that put a value *into* the handle, with the grammatical variants the
# freeze set actually uses. Nothing outside this set counts as a write, and a mention carrying no
# marker at all is a gate failure rather than a pass — see `classify_handle_mention`.
WRITE_VERBS = frozenset({
    "commit", "commits", "committing", "committed",
    "write", "writes", "writing", "written",
    "rewrite", "rewrites", "rewriting", "rewritten",
    "overwrite", "overwrites", "overwriting", "overwritten",
    "update", "updates", "updating", "updated",
    "replace", "replaces", "replacing", "replaced",
    "clear", "clears", "clearing", "cleared",
    "set", "sets", "setting",
    "record", "records", "recording", "recorded",
    "populate", "populates", "populating", "populated",
    "assign", "assigns", "assigning", "assigned",
    "supersede", "supersedes", "superseding", "superseded",
    "retire", "retires", "retiring", "retired",
})

# Retirement is the one write §3A.3 places in a *different* commit from the edge that mentions it:
# the handle is "durably retired in — and only in — the later commit that proves that whole group
# empty", which §3D uses as an attempt's release record. A §3A row may therefore refer to it as a
# future condition ("... until the handle is durably retired") without that row writing anything.
RETIREMENT_VERBS = frozenset({"retire", "retires", "retiring", "retired"})

# Fillers a prohibition may legitimately put between its negation and the verbs it governs.
NEGATED_SPAN_FILLERS = frozenset({
    "be", "been", "being", "ever", "again", "also", "then", "later",
    "silently", "durably", "subsequently", "further", "otherwise",
})

READ_MARKERS = (
    "identified from", "read from", "read by", "MUST NOT be read", "named by", "proven by",
    "resolves to", "against", "being NULL", "is NULL", "stays NULL", "MUST NOT be used as",
    # Absence/evidence predicates. §3A.3 makes a NULL handle *positive proof* that no group
    # exists, so §3A states that fact on the cancellation edges. These are copular predicates:
    # they assert what a handle value means and can commit nothing. They are consulted only when
    # the clause carries no operative write verb, so they cannot mask a write.
    "is proof of", "is positive proof", "means no",
)

# A deferral conjunction before the mention, with the write verb after it, marks a clause that
# talks about a *later* commit rather than about this edge.
DEFERRAL_RE = re.compile(r"(?<![\w-])(?:until|once|after)(?![\w-])", re.IGNORECASE)


# --------------------------------------------------------------------------------------------
# L-01 — co-reference. The K-01 classifier above only ever *looked at* clauses that repeated the
# backticked field name, so an operative second write whose subject was a pronoun or an ordinary
# English alias was not misclassified — it was never examined, and therefore could not even be
# reported as unclassifiable. Four such writes appended to the real `STARTING -> RUNNING` cell
# left the whole suite green.
#
# The repair makes the unit of inspection the *cell*, not the matching clause. Once a cell has
# established cleanup-handle context, every following clause is inspected, and every un-negated
# write verb in it must be attributed to a referent: the handle (literal, alias or anaphor), an
# explicitly different backticked `record.field`, or a closed, individually asserted carve-out
# for a legitimate non-handle subject. A write verb that resolves to none of those is
# UNCLASSIFIED and fails the gate, so ambiguity stops the freeze instead of passing it.
# --------------------------------------------------------------------------------------------

WRITES_OTHER_FIELD = "WRITES_OTHER_FIELD"
NEUTRAL = "NEUTRAL"

# Referent kinds a write verb can be attributed to.
_HANDLE = "handle"
_OTHER_FIELD = "other-field"

# Backticked `record.field` / `field` tokens. Field names in these documents are lower-case with
# underscores; state and disposition literals (`STARTING`, `QUARANTINED`) are upper-case, so the
# leading lower-case requirement separates a field reference from a state reference without a
# hand-maintained list of either.
FIELD_MENTION_RE = re.compile(r"`[a-z][a-z_]*(?:\.[a-z_]+)*`")

# English noun phrases that *name* the cleanup handle without backticks. These are self-
# establishing: they identify the field on their own, wherever they appear in the cell.
HANDLE_ALIAS_RE = re.compile(
    r"(?<![\w-])(?:"
    r"cleanup[\s-]handle"
    r"|owned[\s-]process[\s-]group[\s-]handle"
    r"|process[\s-]group[\s-]handle"
    r"|process[\s-]group[\s-]cleanup[\s-]identity"
    r")(?![\w-])",
    re.IGNORECASE,
)

# Co-referential continuations. These denote the handle only *after* the cell has established it,
# which is why `classified_handle_mentions` tracks establishment clause by clause. `it` is the
# bare pronoun the review used; the determiner+noun forms cover "this field", "that value",
# "the same handle", "a NULL or absent handle" and the like without enumerating phrasings.
HANDLE_ANAPHOR_RE = re.compile(
    r"(?<![\w-])(?:"
    r"it"
    r"|(?:the|this|that|a|an|its|each|any|such|no)\s+(?:[\w'*-]+\s+){0,3}?"
    r"(?:handle|field|value|identifier|column)"
    r")(?![\w-])",
    re.IGNORECASE,
)

# Closed, explicit carve-outs: write verbs whose grammatical subject is a legitimately *different*
# thing that carries no backticked name of its own. Each entry is asserted against the committed
# matrix by `test_every_non_handle_write_carve_out_is_live_and_narrow`, so a carve-out cannot be
# added speculatively and cannot quietly outlive the prose it was written for.
NON_HANDLE_WRITE_SUBJECTS = (
    # §3A `CREATED -> CLOSED / CANCELLED or FENCED`: "the lease is released/retired". The *lease*
    # is retired here, not the handle — the clause immediately before proves the handle NULL.
    re.compile(r"(?<![\w-])the lease is (?:released/)?retired(?![\w-])", re.IGNORECASE),
)

# Requirement 6 — defence in depth. §3A.3 declares how many process groups an attempt owns over
# its lifetime; that number is derivable from §3A independently of any wording about the handle,
# by counting the edges that assert a group is created. An unsafe second controller-created group
# therefore fails on a second, disjoint dimension even if the handle prose is rephrased.
# M-05 — the noun must be recognised in the plural too. `process groups`, `cgroups` and `groups`
# matched *nothing* here, so a creation phrased in the plural ("two further process groups are
# created") produced no group noun in the verb's segment and was therefore not a creation at all:
# a second group could be added to any §3A row and the derived count never moved. Plurality is also
# the signal `_asserted_group_count` needs, so the `s` is captured rather than merely tolerated.
GROUP_NOUN_RE = re.compile(
    r"(?<![\w-])(?:process[\s-]groups?|cgroups?|groups?)(?![\w-])", re.IGNORECASE
)
# M-02 — the derivation was past-participle-only and noun-before-verb-only, so present-tense
# "the controller creates a second process group", ordinary creation synonyms (`instantiated`,
# `provisioned`, `opened`) and object-after-verb phrasing ("placed into a newly created group")
# all slipped past it. The inflections are enumerated rather than stemmed so the set stays closed
# and readable; the hyphen lookbehind still keeps compound adjectives such as
# `controller-allocated` from being read as verbs.
GROUP_CREATION_RE = re.compile(
    r"(?<![\w-])(?:"
    r"creat(?:e|es|ing|ed)"
    r"|allocat(?:e|es|ing|ed)"
    r"|instantiat(?:e|es|ing|ed)"
    r"|establish(?:|es|ing|ed)"
    r"|provision(?:|s|ing|ed)"
    r"|spawn(?:|s|ing|ed)"
    r"|fork(?:|s|ing|ed)"
    r"|open(?:|s|ing|ed)"
    r")(?![\w-])",
    re.IGNORECASE,
)
# M-04 — negation must *govern* the creation it suppresses.
#
# The previous rule was "a negator anywhere in the creation verb's own comma-delimited segment
# makes the segment a denial". Presence in the segment is not government: an unrelated negator
# belonging to a different predication defused a real creation, so
# `if cleanup cannot be proven a second process group is created` — where `cannot` negates
# *proven* — read as a denial and left the gate green. Widening the window (either side of the
# verb) widened the defusal identically; narrowing it to "before the verb" still lost that case
# and would have broken `without a new process group`, which negates from *after*.
#
# The rule below is positional but constituent-aware rather than a phrase list. A negator counts
# only when it lies inside one of the two constituents a denial can attach to:
#
#   * the creation verb's own predication — its auxiliary chain and the subject noun phrase that
#     chain belongs to: `MUST NOT create`, `is never created`, `no second group is created`;
#   * the noun phrase of the group being created — its determiner, or a negating preposition one
#     step outside that determiner: `no owned process group`, `without a new process group`.
#
# Anything else is a negator speaking about something else in the same segment, and the creation
# stands. That is the fail-closed direction: an ungoverned negator can no longer buy silence.
_CREATION_NEGATORS = frozenset({"no", "not", "never", "nor", "cannot", "neither", "none"})
# The only preposition in this prose that negates a noun phrase from outside its determiner.
_NEGATING_PREPOSITIONS = frozenset({"without"})
# Auxiliaries, modals and adverbs may stand between a negator and the verb it governs without
# breaking that government: "no group *was ever* created", "*MUST NOT* create". Adverbs are an
# open class, so `-ly` forms are admitted by shape (`_is_transparent_to_government`) and only the
# irregular ones are enumerated.
_PREDICATION_AUXILIARIES = frozenset({
    "is", "are", "was", "were", "be", "been", "being", "am",
    "has", "have", "had", "having", "do", "does", "did",
    "will", "would", "shall", "should", "may", "might", "must", "can", "could",
    "ever", "also", "only", "still", "already", "yet", "again",
})  # fmt: skip
# Determiners head a noun phrase. A leftward walk stops when it reaches one, because everything
# further left belongs to a different constituent — which is exactly what keeps `cannot` in
# "if cleanup cannot be proven a second process group is created" away from `created`.
_NP_DETERMINERS = frozenset({
    "a", "an", "the", "this", "that", "these", "those", "its", "their", "his", "her", "our",
    "your", "each", "every", "any", "some", "no", "one", "another", "both", "same",
})  # fmt: skip
# Words that end a constituent outright, so a walk that meets one has left the phrase it started
# in. Needed for bare plurals ("process groups are created"), which carry no determiner to stop on.
_CONSTITUENT_BOUNDARIES = frozenset({
    "and", "or", "but", "if", "when", "while", "unless", "until", "because", "so", "then",
    "which", "who", "whom", "whose", "where", "after", "before", "once", "though", "although",
    "into", "in", "to", "for", "of", "on", "at", "by", "with", "from", "as", "than", "under",
    "over", "upon", "through", "during", "against", "between", "within",
})  # fmt: skip
# A leftward walk that has not met a determiner or a boundary by this many words has left the
# constituent it started in, whatever the punctuation says.
_GOVERNMENT_WORD_LIMIT = 8
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_SEGMENT_BOUNDARY_RE = re.compile(r"[,:;]")


def _alternation(words: frozenset[str]) -> str:
    return "|".join(sorted(words, key=len, reverse=True))


# `(?<![\w-])` / `(?![\w-])` keep the hyphenated adjectives the spec really uses — `write-once`,
# `write-ahead` — from being read as verbs.
WRITE_VERB_RE = re.compile(rf"(?<![\w-])({_alternation(WRITE_VERBS)})(?![\w-])")

NEGATION_RE = re.compile(
    r"(?<![\w-])(?:MUST NOT|MUST never|must not|shall not|can never|cannot|may not"
    r"|does not|do not|is not|are not|never)(?![\w-])"
)

_SPAN_TOKEN_RE = re.compile(rf"\s*(?:{_alternation(WRITE_VERBS | NEGATED_SPAN_FILLERS)})(?![\w-])")
_SPAN_JOIN_RE = re.compile(r"(?:\s*,\s*|\s+(?:or|and|nor)\s+)")

# Clause boundaries: a semicolon, or a full stop that ends a sentence. The lookahead demands
# whitespace then a capital or a backtick, so `§3A.3`, `§10.3.1` and `lease.owned_...` survive.
_CLAUSE_BOUNDARY_RE = re.compile(r";|(?<=[\w)`*])\.\s+(?=[A-Z`*])")


def attempt_transition_rows(api_text: str) -> list[list[str]]:
    """The rows of §3A's *transition matrix* alone.

    `table_rows_in_numbered_section(STATE_API, "3A")` also returns §3A.1's subject bindings,
    §3A.2's ceiling classification and §3A.3's cardinality and durable-fact tables — and the
    durable-fact table has four columns and names the handle, so a width filter cannot separate
    them. Addressing the matrix by its own header keeps the gate pointed at real edges. The
    header is shared with two §3B tables, so the scan is also bounded to §3A.
    """
    rows: list[list[str]] = []
    in_section = False
    in_table = False
    for line in api_text.splitlines():
        if re.match(r"^##\s+3A(?:\.|\s)", line):
            in_section = True
            continue
        if in_section and re.match(r"^##\s", line):
            break
        if not in_section:
            continue
        if line.strip() == ATTEMPT_TRANSITION_HEADER:
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith("|"):
            in_table = False
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if not cells or set("".join(cells)) <= {"-", " "}:
            continue
        rows.append(cells)
    assert rows, "§3A carries no attempt transition matrix"
    return rows


def _negated_spans(clause: str) -> list[tuple[int, int]]:
    """Character spans governed by a negation, as `MUST NOT update, replace or clear`.

    The span is the coordinated verb list the negation actually governs, not the rest of the
    clause. That distinction is what stops a prohibition sentence from cloaking an operative
    write appended after it in the same clause.
    """
    spans: list[tuple[int, int]] = []
    for negation in NEGATION_RE.finditer(clause):
        pos = end = negation.end()
        while True:
            join = _SPAN_JOIN_RE.match(clause, pos)
            token = _SPAN_TOKEN_RE.match(clause, join.end() if join else pos)
            if token is None:
                break
            pos = end = token.end()
        if end > negation.end():
            spans.append((negation.end(), end))
    return spans


def _carved_out_write_spans(clause: str) -> list[tuple[int, int]]:
    """Spans of `NON_HANDLE_WRITE_SUBJECTS` matches, i.e. asserted non-handle subjects."""
    return [
        (found.start(), found.end())
        for pattern in NON_HANDLE_WRITE_SUBJECTS
        for found in pattern.finditer(clause)
    ]


def _referents(clause: str, established: bool) -> list[tuple[int, int, str]]:
    """Ordered `(start, end, kind)` markers a write verb in this clause can be attributed to.

    Literal backticked handle mentions and English aliases denote the handle on their own.
    Anaphors only count once the cell has established what they refer back to — that is the whole
    of L-01: `it` means nothing until something has been named, and means the handle once it has.
    Any other backticked field is a competing referent, which is how a legitimate write to a
    different field is told apart from a write to the handle.
    """
    marks: list[tuple[int, int, str]] = []

    def add(start: int, stop: int, kind: str) -> None:
        if not any(held_start <= start < held_stop for held_start, held_stop, _ in marks):
            marks.append((start, stop, kind))

    for found in HANDLE_MENTION_RE.finditer(clause):
        add(found.start(), found.end(), _HANDLE)
    for found in FIELD_MENTION_RE.finditer(clause):
        if HANDLE_MENTION_RE.fullmatch(found.group(0)):
            continue
        add(found.start(), found.end(), _OTHER_FIELD)
    for found in HANDLE_ALIAS_RE.finditer(clause):
        add(found.start(), found.end(), _HANDLE)
    if established:
        for found in HANDLE_ANAPHOR_RE.finditer(clause):
            add(found.start(), found.end(), _HANDLE)

    marks.sort()
    return marks


def _resolve_write_target(
    verb_start: int, marks: list[tuple[int, int, str]]
) -> tuple[str, tuple[int, int, str]] | tuple[None, None]:
    """Attribute a write verb to its nearest referent — to the left first, then to the right.

    Nearest-to-the-left covers the ordinary subject-verb order of every phrasing in these
    documents ("the cleanup handle is rewritten", "it is set to"). The right-hand fallback covers
    the active voice, where the verb precedes its object ("the controller rewrites the handle").
    A verb with no referent on either side is unattributable, and unattributable is fatal.
    """
    before = [mark for mark in marks if mark[1] <= verb_start]
    if before:
        return before[-1][2], before[-1]
    after = [mark for mark in marks if mark[0] >= verb_start]
    if after:
        return after[0][2], after[0]
    return None, None


# --------------------------------------------------------------------------------------------
# M-01 — a decoy field must not be allowed to absorb a write the cleanup handle could have taken.
#
# `_resolve_write_target` attributes a write verb to its *nearest* referent, left first. That is
# sound when the clause offers one candidate, but it is exactly the wrong bias when it offers two:
# putting a backticked non-handle `record.field` nearer the verb than the handle referent made the
# clause classify `WRITES_OTHER_FIELD`, and `WRITES_OTHER_FIELD` is (a) not counted by
# `attempt_rows_writing_the_cleanup_handle`, which only counts `WRITES`, and (b) returned *before*
# the fail-closed arm at the foot of `classify_handle_clause`, so the decoy also bought the whole
# clause an exemption from failing closed. Six mutations appended to the real `STARTING -> RUNNING`
# row — an operative second write to the handle, sitting beside the surviving prohibition and the
# declared count of `1` — left the entire suite green.
#
# The repair is a rule about what the gate is entitled to conclude, not a longer list of phrasings:
# charging a write to another field is a *positive* claim that the handle did not receive it, and
# that claim is only available when no live cleanup-handle referent shares the clause. A referent is
# live unless the clause itself defuses it by making it the object of a read — a READ_MARKERS phrase
# ending immediately in front of it, which is how the committed `STARTING -> RUNNING` cell says the
# ceiling discriminator "MUST NOT be used as the cleanup handle". A read marker *behind* the
# referent is deliberately not enough: "... is written into `attempt.running_process_group_identity`
# and into the cleanup handle, which is read from the lease" would otherwise dress an operative
# second write as a read. A contested clause is UNCLASSIFIED, and UNCLASSIFIED fails the freeze.
# --------------------------------------------------------------------------------------------

# How close in front of a handle referent a read marker must sit to be read as governing it. The
# committed case is " the " — five characters — between "MUST NOT be used as" and "cleanup handle";
# the window is kept tight so that a marker belonging to some other part of the clause cannot reach
# across and defuse a referent it never spoke about.
READ_MARKER_BINDING_CHARS = 12


def _read_marker_spans(clause: str) -> list[tuple[int, int]]:
    """Character spans of every `READ_MARKERS` phrase occurring in the clause."""
    spans: list[tuple[int, int]] = []
    for marker in READ_MARKERS:
        start = clause.find(marker)
        while start != -1:
            spans.append((start, start + len(marker)))
            start = clause.find(marker, start + 1)
    return spans


def _live_handle_referents(
    clause: str, marks: list[tuple[int, int, str]]
) -> list[tuple[int, int, str]]:
    """Handle referents in this clause that the clause has not itself defused as reads.

    Anything left over is a referent the prose still offers as a possible target of a write. Its
    presence is what makes a "this write went to some other field" verdict unprovable.
    """
    read_marked = _read_marker_spans(clause)
    return [
        mark
        for mark in marks
        if mark[2] == _HANDLE
        and not any(
            0 <= mark[0] - marker_stop <= READ_MARKER_BINDING_CHARS
            for _marker_start, marker_stop in read_marked
        )
    ]


# M-03 — how many writes one clause asserts.
#
# A `WRITES` verdict says the clause writes the handle; it does not say how often, and the
# declared cardinality in §3A.3 is a count of write *points*. Counting every operative verb
# over-counts two ways that the committed matrix itself demonstrates: `may write` states a
# permission, not a second write event, and `in this same commit` is the *noun* `commit`, which
# is in `WRITE_VERBS` because the verb is. Both are recognised structurally — a permission modal
# immediately governing the verb, and a determiner heading the phrase the token sits in — so a
# clause asserting one write counts one, and a clause asserting two counts two.
_PERMISSION_MODALS = frozenset({"may", "can", "might", "could"})


def _is_an_independent_write_assertion(clause: str, verb_start: int) -> bool:
    """Does the write verb at `verb_start` assert a write event of its own?"""
    words = _words_before(clause, verb_start)[-3:]
    if not words:
        return True
    # A noun in a noun phrase — `this same commit`, `a record` — is not a write event.
    tail = words[-2:]
    if any(word in _NP_DETERMINERS for word in tail) and not any(
        _is_transparent_to_government(word) for word in tail
    ):
        return False
    # `the only edge that may write the cleanup handle` grants permission for the write the rest
    # of the clause then states; it is the same event, not a second one.
    for word in reversed(words):
        if word in _PERMISSION_MODALS:
            return False
        if not _is_transparent_to_government(word):
            break
    return True


def _classify_handle_clause(clause: str, established: bool) -> tuple[str, int]:
    """Classify one clause of a handle-bearing cell, and count the writes it asserts.

    Fail-closed ordering: an operative handle write anywhere in the clause outranks a prohibition
    in the same clause (the dangerous edit is a write added *beside* a surviving prohibition), and
    an unattributable — or contested — write verb outranks every benign class, `WRITES_OTHER_FIELD`
    included. That last ordering is M-01: a decoy field no longer buys the clause an exemption.

    The count is zero unless the verdict is `WRITES`, and never less than one when it is: a clause
    the classifier calls a write asserts at least one write even if every verb in it is discounted
    by `_is_an_independent_write_assertion`.

    M-05: each surviving verb contributes the number of write events it actually asserts, not one.
    A verb that asserts repetition without naming a number leaves the count unknown, and an
    unknown write count is `UNCLASSIFIED` — the same answer this classifier already gives to any
    other handle wording it cannot resolve.
    """
    marks = _referents(clause, established)
    negated = _negated_spans(clause)
    carved = _carved_out_write_spans(clause)
    deferrals = [found.start() for found in DEFERRAL_RE.finditer(clause)]
    live_handles = _live_handle_referents(clause, marks)

    prohibited = deferred_retirement = other_field = unattributable = False
    contested = False
    operative: list[re.Match[str]] = []
    for verb in WRITE_VERB_RE.finditer(clause):
        if any(start <= verb.start() < stop for start, stop in negated):
            prohibited = True
            continue
        if any(start <= verb.start() < stop for start, stop in carved):
            continue
        target, mark = _resolve_write_target(verb.start(), marks)
        if target is None:
            unattributable = True
        elif target == _OTHER_FIELD:
            # M-01: nearest-referent attribution is only evidence of exclusivity when there is
            # nothing else in the clause the write could have landed on.
            if live_handles:
                contested = True
            else:
                other_field = True
        elif (
            verb.group(1) in RETIREMENT_VERBS
            and mark is not None
            and verb.start() > mark[1]
            and any(deferral < mark[0] for deferral in deferrals)
        ):
            deferred_retirement = True
        else:
            operative.append(verb)

    if operative:
        asserted = 0
        for verb in operative:
            if not _is_an_independent_write_assertion(clause, verb.start()):
                continue
            start, stop = _segment_bounds(clause, verb.start(), verb.end())
            repetitions = _asserted_write_repetitions(
                clause[start:stop], verb.start() - start, verb.end() - start
            )
            if repetitions is None:
                # The clause says the handle is written more than once but not how many times.
                return UNCLASSIFIED, 0
            asserted += repetitions
        return WRITES, max(1, asserted)
    if unattributable or contested:
        return UNCLASSIFIED, 0
    if prohibited:
        return PROHIBITS_WRITE, 0
    if other_field:
        return WRITES_OTHER_FIELD, 0
    if deferred_retirement or any(marker in clause for marker in READ_MARKERS):
        return READS_ONLY, 0
    if any(kind == _HANDLE for _start, _stop, kind in marks):
        # The clause speaks about the handle in wording that carries no marker from any set.
        # That is not evidence the edge is harmless; it is evidence the gate cannot say.
        return UNCLASSIFIED, 0
    return NEUTRAL, 0


def classify_handle_clause(clause: str, established: bool) -> str:
    """The semantic class of one clause of a handle-bearing cell. See `_classify_handle_clause`."""
    return _classify_handle_clause(clause, established)[0]


def classified_handle_clauses(api_text: str) -> list[tuple[list[str], str, str, int]]:
    """Every classified clause of every §3A transition cell that establishes handle context.

    Scope is the point of L-01. A row's cells are read in order and split into clauses; from the
    first clause that *names* the handle (backticked field or English alias) onward, every clause
    is classified, whether or not it repeats the name. Establishment carries across cells because
    a transition row is one piece of prose — the `STARTING -> CLOSED / QUARANTINED` row names the
    handle in its trigger and then co-refers to it as "that handle" in its preconditions. Clauses
    before the naming point have nothing to co-refer to and are left alone, which is what keeps
    the ordinary preconditions prose out of the gate.

    The fourth element is how many writes the clause asserts (M-03), zero unless it is a `WRITES`.
    """
    clauses: list[tuple[list[str], str, str, int]] = []
    for row in attempt_transition_rows(api_text):
        established = False
        for cell in row:
            for clause in _CLAUSE_BOUNDARY_RE.split(cell):
                names_it = bool(HANDLE_MENTION_RE.search(clause) or HANDLE_ALIAS_RE.search(clause))
                if not (established or names_it):
                    continue
                established = True
                verdict, writes = _classify_handle_clause(clause, established=True)
                if verdict != NEUTRAL:
                    clauses.append((row, verdict, clause.strip(), writes))
    return clauses


def classified_handle_mentions(api_text: str) -> list[tuple[list[str], str, str]]:
    """`classified_handle_clauses` without the write count, which is how the gate reads it."""
    return [(row, verdict, clause) for row, verdict, clause, _ in classified_handle_clauses(api_text)]


def cleanup_handle_write_assertions(api_text: str) -> list[str]:
    """Every asserted write of the cleanup handle in §3A, one entry each, as `EDGE: clause`.

    M-03: `attempt_rows_writing_the_cleanup_handle` deduplicates by transition row, so the one row
    that legitimately writes the handle could absorb a second, unsafe write and still be counted
    once. §3A.3 declares a number of write *points*, so the authoritative comparison has to be
    against the assertions themselves; the row-level derivation is kept for its diagnostics and
    for the write-point identity check, both of which speak about rows.
    """
    assertions: list[str] = []
    for row, verdict, clause, writes in classified_handle_clauses(api_text):
        if verdict == WRITES:
            assertions.extend([f"{row[0]} -> {row[2]}: {clause}"] * writes)
    return assertions


def attempt_rows_writing_the_cleanup_handle(api_text: str) -> list[list[str]]:
    """§3A transition rows that operatively write the cleanup handle.

    Fails closed first: any mention this classifier cannot place is a gate failure, so unknown
    wording can never be silently dropped from the derived count.
    """
    mentions = classified_handle_mentions(api_text)
    assert mentions, "§3A's transition matrix mentions the cleanup handle nowhere"

    unclassified = [
        f"{row[0]} -> {row[2]}: {clause}"
        for row, verdict, clause in mentions
        if verdict == UNCLASSIFIED
    ]
    assert not unclassified, (
        "§3A mentions the cleanup handle in wording this gate cannot classify as WRITES, "
        "PROHIBITS_WRITE or READS_ONLY; the freeze gate fails closed rather than assuming it is "
        "harmless:\n  " + "\n  ".join(unclassified)
    )

    writing: list[list[str]] = []
    for row, verdict, _clause in mentions:
        if verdict == WRITES and row not in writing:
            writing.append(row)
    return writing


def assert_declared_write_point_matches_the_matrix(api_text: str) -> None:
    """§3A.3's declared handle cardinality must equal what §3A's edges actually do.

    Split out of the test body so the mutation harness below can run the identical gate against a
    mutated document and require it to fail.
    """
    attempt_kind = "`attempt` (TASK or INTEGRATION)"
    cardinality = declared_group_cardinality_in(api_text)
    assert attempt_kind in cardinality, sorted(cardinality)
    groups, write_points = cardinality[attempt_kind]

    writing = attempt_rows_writing_the_cleanup_handle(api_text)
    assert len(writing) == int(groups), (
        f"{len(writing)} §3A edges write the cleanup handle; §3A.3 declares {groups}: "
        + "; ".join(f"{row[0]} -> {row[2]}" for row in writing)
    )
    assert f"`{writing[0][0]} -> {writing[0][2]}`" == write_points, (
        f"§3A writes the handle on {writing[0][0]} -> {writing[0][2]}, "
        f"but §3A.3 declares the write point as {write_points}"
    )

    # M-03 — the two checks above both speak about rows, and a row is not the declared unit. A
    # second write added *inside* the row that legitimately writes the handle leaves both of them
    # satisfied, so the count that decides the gate is the count of assertions. Deliberately last:
    # every mutation the earlier rounds pinned still fails on its own message.
    asserted = cleanup_handle_write_assertions(api_text)
    assert len(asserted) == int(groups), (
        f"§3A asserts {len(asserted)} writes of the cleanup handle; §3A.3 declares {groups}:\n  "
        + "\n  ".join(asserted)
    )


def _segment_bounds(clause: str, start: int, stop: int) -> tuple[int, int]:
    """The comma/colon/semicolon-delimited segment of `clause` containing `[start, stop)`."""
    left, right = 0, len(clause)
    for found in _SEGMENT_BOUNDARY_RE.finditer(clause):
        if found.end() <= start:
            left = found.end()
        elif found.start() >= stop:
            right = found.start()
            break
    return left, right


def _words_before(text: str, index: int) -> list[str]:
    """The lower-cased words of `text` that end at or before `index`, in reading order."""
    return [found.group().lower() for found in _WORD_RE.finditer(text[:index])]


def _is_transparent_to_government(word: str) -> bool:
    """May this word stand between a negator and the verb it negates?

    Auxiliaries, modals and adverbs may; a content word may not, because reaching one means the
    walk has left the verb's own auxiliary chain and entered its subject.
    """
    return word in _PREDICATION_AUXILIARIES or (word.endswith("ly") and len(word) > 3)


def _negation_governs_the_predication(segment: str, verb_offset: int) -> bool:
    """Is the verb at `verb_offset` negated by a negator that actually governs *it*?

    The walk runs leftward from the verb through its own auxiliary chain and then into the
    subject noun phrase that chain belongs to, stopping at that phrase's determiner. A negator
    met on the way is the verb's own: `MUST NOT create`, `the controller never creates`,
    `no second group is created`, `no group was ever created`. A negator met after the walk has
    stopped belongs to a different predication and is ignored — M-04's
    `if cleanup cannot be proven a second process group is created`, where the walk halts at the
    determiner `a` and never reaches `cannot`.
    """
    words = _words_before(segment, verb_offset)[-_GOVERNMENT_WORD_LIMIT:]
    in_auxiliary_chain = True
    for word in reversed(words):
        if word in _CREATION_NEGATORS:
            return True
        if in_auxiliary_chain and _is_transparent_to_government(word):
            continue
        in_auxiliary_chain = False
        if word in _NP_DETERMINERS or word in _CONSTITUENT_BOUNDARIES:
            return False
    return False


def _negation_governs_the_noun_phrase(segment: str, noun_offset: int) -> bool:
    """Is the group noun phrase headed at `noun_offset` itself denied?

    `no second group` and `without a new process group` both say the group does not come into
    existence, so a creation verb sharing their segment creates nothing. The walk runs leftward
    through the phrase's own modifiers to its determiner and is then allowed exactly one further
    step, onto a negating preposition — the only way English negates such a phrase from outside
    its determiner. `a second process group is created ... without delay` is precisely the case
    this must *not* defuse: there `without` governs `delay`, a phrase of its own.
    """
    words = _words_before(segment, noun_offset)[-_GOVERNMENT_WORD_LIMIT:]
    for steps, word in enumerate(reversed(words)):
        if word in _CREATION_NEGATORS or word in _NEGATING_PREPOSITIONS:
            return True
        if word in _NP_DETERMINERS:
            outside = words[: len(words) - steps - 1]
            return bool(outside) and outside[-1] in _NEGATING_PREPOSITIONS
        if word in _CONSTITUENT_BOUNDARIES:
            return False
    return False


# --------------------------------------------------------------------------------------------
# M-05 — semantic cardinality is not verb cardinality.
#
# The M-03 repair counted one write assertion per operative write verb and one group creation per
# creation verb. That is a count of *predicates*, and the freeze set declares a count of *events*
# and of *entities*. One predication can explicitly assert more than one of either:
#
#   * "two process groups are created" / "creates two process groups" — one verb, two groups;
#   * "`lease.owned_process_group_handle` is written twice" / "is committed two times" — one verb,
#     two writes.
#
# Both left §3A.3's declared `1` satisfied. The repair reads the number the prose actually states:
# a quantifier heading the created noun phrase, and a repetition adverbial governing the write
# verb. Where the prose asserts more than one without saying how many — a bare plural, "written
# repeatedly", "more than once" — the count is unknown, and an unknown count on a critical
# cardinality is a red gate rather than an assumed 1.
# --------------------------------------------------------------------------------------------

_CARDINAL_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "both": 2,
}  # fmt: skip
# Quantifiers that pin a noun phrase at exactly one. Ordinals are here because "a second process
# group" is one group, not two — the ordinal says *which*, the cardinality is still singular.
_SINGULAR_QUANTIFIERS = frozenset({
    "single", "sole", "lone", "only", "first", "second", "third", "fourth", "fifth", "sixth",
    "next", "last", "another",
})  # fmt: skip
# M-06 — `new`, `existing` and `same` are not quantifiers, and treating them as ones that pin the
# phrase at one was a false green. They are ordinary noun modifiers: they say *which* groups are
# meant, never how many. `a new process group` is one because of `a`; `two new process groups` is
# two, and the leftward walk used to stop dead on `new` and report one without ever reading `two`.
# So they are skipped exactly like any other adjective, and the number is taken from whatever
# quantifier or determiner really heads the phrase — or, for a bare plural, from nothing, which is
# the unknown count the gate already fails closed on. (`same` is also an `_NP_DETERMINERS` member,
# so `the same group` still resolves to one there, while `the same groups` becomes unknown.)
_NON_QUANTIFYING_MODIFIERS = frozenset({"new", "existing", "same"})
# Quantifiers that assert *more than one* without naming a number. Unknown critical cardinality.
_INDEFINITE_PLURAL_QUANTIFIERS = frozenset({
    "several", "many", "multiple", "various", "numerous", "additional", "further", "more",
    "other", "few", "fewer", "most",
})  # fmt: skip
# Repetition adverbials on the write dimension: how many times one verb happens.
_REPETITION_ADVERBS = {"once": 1, "twice": 2, "thrice": 3}
_REPETITION_NOUNS = frozenset({"time", "times", "occasion", "occasions"})
_INDEFINITE_REPETITION = frozenset({
    "repeatedly", "again", "anew", "afresh", "multiple", "several", "many", "numerous",
    "various", "additional", "further", "more",
})  # fmt: skip
# A repetition adverbial belongs to its verb's own predication, not to anything else in the
# segment — M-04's lesson applied to counting. The walk is bounded and stops at a boundary word.
_REPETITION_WORD_LIMIT = 6
# Digits count as quantifiers: `2 process groups`, `committed 2 times`. `_WORD_RE` is letters only.
_QUANTIFIER_TOKEN_RE = re.compile(r"\d+|[A-Za-z][A-Za-z'’-]*")


def _quantifier_tokens_before(text: str, index: int) -> list[str]:
    """The lower-cased words *and numerals* of `text` ending at or before `index`, in order."""
    return [found.group().lower() for found in _QUANTIFIER_TOKEN_RE.finditer(text[:index])]


def _quantifier_tokens_after(text: str, index: int) -> list[str]:
    """Tokens from `index` onward, stopping at the first boundary word or the walk limit.

    One boundary word is crossed rather than obeyed: a preposition immediately followed by a bare
    repetition phrase — "committed **on two occasions**" — heads an adverbial of the verb rather
    than ending its predication. The lookahead is deliberately exact (a number, then a repetition
    noun) so the committed `is committed **before** the attempt's single owned process group` still
    stops dead on `before`, where what follows is a determiner and a noun phrase.
    """
    pending = [found.group().lower() for found in _QUANTIFIER_TOKEN_RE.finditer(text, index)]
    tokens: list[str] = []
    for position, token in enumerate(pending):
        if token in _CONSTITUENT_BOUNDARIES:
            follows = pending[position + 1 : position + 3]
            if not (
                len(follows) == 2
                and _as_cardinal(follows[0]) is not None
                and follows[1] in _REPETITION_NOUNS
            ):
                break
            continue
        tokens.append(token)
        if len(tokens) >= _REPETITION_WORD_LIMIT:
            break
    return tokens


def _as_cardinal(token: str) -> int | None:
    """The number this token states, if it states one."""
    if token.isdigit():
        return int(token)
    return _CARDINAL_WORDS.get(token)


def _heads_a_different_noun_phrase(token: str) -> bool:
    """Has the leftward walk left the premodifier run of the phrase it started in?

    M-06's other half. Reached only after every quantifier, determiner and boundary vocabulary has
    been consulted, so what is left is an ordinary word of this prose. English premodifiers are
    adjectives, participles and *singular* noun modifiers — `owned`, `controller-allocated`,
    `preflight`, `process`, and possessives such as `the attempt's`. A bare plural word is not one:
    meeting it means the walk has crossed out of this noun phrase and into the subject or object
    phrase next door, so `two attempts create new process groups` must not read `two` as the number
    of groups. Possessives keep the walk alive — they modify a head, they do not head one.

    Stopping here is the fail-closed direction for the case that matters: a plural head that finds
    no quantifier of its own yields `None`, the unknown count the gate already refuses.
    """
    return token.endswith("s") and "'" not in token and "’" not in token


def _asserted_group_count(segment: str, noun: re.Match[str]) -> int | None:
    """How many groups the noun phrase headed at `noun` asserts, or `None` if it does not say.

    The walk is the one `_negation_governs_the_noun_phrase` already uses: leftward from the noun
    head through its own modifiers to its determiner, bounded by the same word limit and stopped
    by the same boundary words, so a quantifier belonging to a neighbouring phrase is never read
    as this phrase's. A cardinal or numeral is the count; a singular quantifier or a determiner is
    one, *unless the noun is plural*, in which case the determiner says nothing about how many and
    the count is unknown.

    M-06 — no modifier may end the walk before an explicit cardinal in the same phrase is read.
    `new` and `existing` used to, so `two new process groups are created` reported one and the
    `two` beside it was never seen. Modifiers are now all transparent and only *record* what they
    mean, so a stated number always outranks them; the walk ends where the noun phrase itself
    ends — at its determiner, at a boundary word, at the word limit, or at a plural word that can
    only head a phrase of its own. The two modifier vocabularies stay distinct because they differ
    in what they say when no cardinal is found: a singular quantifier asserts one even with no
    determiner to lean on (`single process group`), while `new` asserts nothing at all, leaving a
    bare plural unknown.
    """
    plural = noun.group().lower().endswith("s")
    indefinite = False
    singular = False
    tokens = _quantifier_tokens_before(segment, noun.start())[-_GOVERNMENT_WORD_LIMIT:]

    def settled() -> int | None:
        return None if indefinite or (plural and not singular) else 1

    for token in reversed(tokens):
        number = _as_cardinal(token)
        if number is not None:
            # A stated number outranks a vague one in the same phrase: "two further process
            # groups" says two. The walk still stops at the phrase's edge, so "more **than** two
            # process groups" breaks on the boundary word and stays unquantified.
            return number
        if token in _INDEFINITE_PLURAL_QUANTIFIERS:
            indefinite = True
            continue
        if token in _SINGULAR_QUANTIFIERS:
            singular = True
            continue
        if token in _NON_QUANTIFYING_MODIFIERS:
            continue
        if token in _NP_DETERMINERS:
            return settled()
        if token in _CONSTITUENT_BOUNDARIES:
            break
        if _heads_a_different_noun_phrase(token):
            break
    return settled()


def _asserted_write_repetitions(segment: str, verb_start: int, verb_stop: int) -> int | None:
    """How many write events the verb at `[verb_start, verb_stop)` explicitly asserts.

    One unless the verb carries a repetition adverbial of its own — "written **twice**",
    "committed **two times**" — and `None` when the prose asserts repetition without naming a
    number. Government, not presence: the rightward walk stops at the first boundary word, so the
    committed `is committed **before** the attempt's single owned process group is created` sees
    `before`, stops, and counts one. The leftward look covers only the verb's auxiliary chain,
    which is where a preposed adverbial ("is twice committed") can sit.
    """
    following = _quantifier_tokens_after(segment, verb_stop)
    preceding = []
    for token in reversed(_quantifier_tokens_before(segment, verb_start)[-3:]):
        preceding.append(token)
        if not (_is_transparent_to_government(token) or token in _REPETITION_ADVERBS):
            break

    count = 1
    for tokens in (following, preceding):
        for index, token in enumerate(tokens):
            if token in _INDEFINITE_REPETITION:
                return None
            if token in _REPETITION_ADVERBS:
                count = max(count, _REPETITION_ADVERBS[token])
            number = _as_cardinal(token)
            if (
                number is not None
                and index + 1 < len(tokens)
                and tokens[index + 1] in _REPETITION_NOUNS
            ):
                count = max(count, number)
    return count


def group_creations(clause: str) -> list[tuple[re.Match[str], int | None]]:
    """`group_creation_assertions` with each verb's asserted group count beside it.

    `None` is "this clause asserts a creation but does not say how many groups", which
    `owned_process_group_creation_assertions` turns into a gate failure. When a segment holds
    several live group nouns the largest count wins: over-counting turns the gate red, and red is
    the direction a cardinality invariant is allowed to be wrong in.
    """
    creations: list[tuple[re.Match[str], int | None]] = []
    for verb in GROUP_CREATION_RE.finditer(clause):
        start, stop = _segment_bounds(clause, verb.start(), verb.end())
        segment = clause[start:stop]
        if _negation_governs_the_predication(segment, verb.start() - start):
            continue
        counts = [
            _asserted_group_count(segment, noun)
            for noun in GROUP_NOUN_RE.finditer(segment)
            if not _negation_governs_the_noun_phrase(segment, noun.start())
        ]
        if not counts:
            continue
        creations.append((verb, None if None in counts else max(counts)))
    return creations


def group_creation_assertions(clause: str) -> list[re.Match[str]]:
    """Every un-negated assertion in this clause that a process group comes into existence.

    Derived structurally: a creation verb sharing its own comma/colon/semicolon-delimited segment
    with a process-group noun. M-02 widened this from "nearest *preceding* noun" to "a noun
    anywhere in the verb's own segment", because English puts the created thing on either side of
    the verb — "the controller creates a second process group" and "placed into a newly created
    controller-allocated group" assert exactly what "a second process group is created" asserts.

    M-04 replaced "a negator somewhere in the segment" with government: the creation survives
    unless a negator governs its predication, or every group noun in the segment is itself denied.
    Requiring the group noun *and* bounding it to one segment is still what keeps the derivation
    from firing on unrelated prose; a creation verb with no group in its segment (a created
    workspace, an established lease) is not a group.

    One entry per verb, not per clause: M-03's lesson is that the declared cardinality is a count
    of creations, so two creations in one sentence must count as two. How many groups each verb
    creates is M-05's question and is answered separately, by `group_creations`; this function
    stays a list of verbs because that is what the row-level derivation and the `_asserts_a_group
    _creation` predicate need, and an unquantifiable creation is still a creation.
    """
    return [verb for verb, _count in group_creations(clause)]


def _asserts_a_group_creation(clause: str) -> bool:
    """Does this clause assert that a process group *is created*, un-negated?"""
    return bool(group_creation_assertions(clause))


def attempt_rows_creating_an_owned_process_group(api_text: str) -> list[list[str]]:
    """§3A transition rows that assert a controller-created process group comes into existence."""
    rows: list[list[str]] = []
    for row in attempt_transition_rows(api_text):
        for cell in row:
            for clause in _CLAUSE_BOUNDARY_RE.split(cell):
                if _asserts_a_group_creation(clause) and row not in rows:
                    rows.append(row)
    return rows


def owned_process_group_creation_assertions(api_text: str) -> list[str]:
    """Every §3A assertion that an owned process group comes into existence, one entry each.

    M-03: `attempt_rows_creating_an_owned_process_group` deduplicates by transition row, so the
    one row that legitimately creates the attempt's group could absorb a second creation and
    still be counted once. §3A.3 declares a number of *groups*, not a number of rows, so the
    authoritative comparison has to be against the assertions themselves.

    M-05: and a number of groups is not a number of verbs. A creation that explicitly quantifies
    what it creates contributes that many entries, and one that asserts a plurality without
    naming it contributes a gate failure — the same fail-closed rule the handle classifier uses
    for wording it cannot place.
    """
    assertions: list[str] = []
    unquantified: list[str] = []
    for row in attempt_transition_rows(api_text):
        for cell in row:
            for clause in _CLAUSE_BOUNDARY_RE.split(cell):
                for verb, count in group_creations(clause):
                    entry = f"{row[0]} -> {row[2]}: {verb.group()!r} in {clause.strip()}"
                    if count is None:
                        unquantified.append(entry)
                    else:
                        assertions.extend([entry] * count)
    assert not unquantified, (
        "§3A asserts that process groups are created without saying how many; a declared "
        "cardinality cannot be checked against an unstated one, so the freeze gate fails closed "
        "rather than reading it as one:\n  " + "\n  ".join(unquantified)
    )
    return assertions


def assert_declared_group_count_matches_the_matrix(api_text: str) -> None:
    """Requirement 6: the declared *group* count, derived from §3A without reading handle prose.

    This is deliberately disjoint from `assert_declared_write_point_matches_the_matrix`. That one
    reasons about who writes the handle; this one reasons only about how many groups §3A brings
    into existence. An unsafe second controller-created attempt process group therefore has to
    defeat two independent derivations, and rewording the handle sentence defeats neither.
    """
    attempt_kind = "`attempt` (TASK or INTEGRATION)"
    cardinality = declared_group_cardinality_in(api_text)
    assert attempt_kind in cardinality, sorted(cardinality)
    groups, write_points = cardinality[attempt_kind]

    creating = attempt_rows_creating_an_owned_process_group(api_text)
    assert len(creating) == int(groups), (
        f"{len(creating)} §3A edges create an owned process group; §3A.3 declares {groups}: "
        + "; ".join(f"{row[0]} -> {row[2]}" for row in creating)
    )
    assert f"`{creating[0][0]} -> {creating[0][2]}`" == write_points, (
        f"§3A creates the attempt's group on {creating[0][0]} -> {creating[0][2]}, but §3A.3 "
        f"declares the handle write point as {write_points}; the group must be created on the "
        f"edge that commits the handle naming it"
    )

    # M-03, the same defect on this dimension: the row that legitimately creates the attempt's
    # one group could absorb a second creation without changing the number of rows. §3A.3 declares
    # a number of groups. Deliberately last, for the same reason as on the write dimension.
    asserted = owned_process_group_creation_assertions(api_text)
    assert len(asserted) == int(groups), (
        f"§3A asserts {len(asserted)} owned process group creations; §3A.3 declares {groups}:\n  "
        + "\n  ".join(asserted)
    )


def test_one_owned_group_per_attempt_is_a_declared_count_not_a_missing_phrase() -> None:
    """The H-03 guard, restated positively.

    The first guard was `HANDOVER_WORDINGS`: a verbatim blacklist. Mutation testing showed a
    *paraphrased* two-group handover could be added while the prohibition sentence stayed, and the
    gate went green — prose-absence checks cannot see a contradicting addition. So the invariant is
    now carried by a number: §3A.3 declares how many groups a record owns over its lifetime and how
    many write points its handle has, and those declarations are cross-checked against the edges
    that actually write it.

    K-01: that cross-check was itself phrase-dependent — it recognised a write only from the
    literal ``` `lease.owned_process_group_handle` is committed ```, so a second write point
    spelled "is written" or "is rewritten" left the derived count at 1 and the gate green. The
    detection is now `attempt_rows_writing_the_cleanup_handle`, which classifies *every* §3A
    transition-row mention of the handle over a closed marker set and fails closed on wording it
    cannot classify. What this proves, precisely: a second write point on a real §3A edge fails
    whatever verb from that marker set introduces it, and an unrecognised verb fails too, because
    an unclassifiable mention is an error rather than a pass. What it does not prove is stated
    with the mutation harness below.
    """
    cardinality = declared_group_cardinality()

    attempt_kind = "`attempt` (TASK or INTEGRATION)"
    assert attempt_kind in cardinality, sorted(cardinality)
    groups, write_points = cardinality[attempt_kind]
    assert groups == "1", f"an attempt is declared to own {groups} process groups, not 1"
    assert write_points == "`CREATED -> STARTING`", write_points

    # A kernel-owned dispatch owns one group too; an external one owns none and never writes.
    assert cardinality["`review_dispatch` (`KERNEL_OWNED`)"][0] == "1"
    external_groups, external_writes = cardinality["`review_dispatch` (`EXTERNAL`)"]
    assert external_groups == "0", external_groups
    assert external_writes.startswith("none"), external_writes

    # The declaration must match the matrix: exactly one §3A edge writes the handle, and it is
    # the edge the table names. A handover adds a second such row and fails here.
    assert_declared_write_point_matches_the_matrix(read(STATE_API))
    # L-01 requirement 6: and the same table's *group* column is derived a second time, from
    # §3A's creation prose alone, so the invariant does not rest on handle wording only.
    assert_declared_group_count_matches_the_matrix(read(STATE_API))

    # The count is normative in its own right, not a summary of the prohibition.
    three_a_three = numbered_section_text(STATE_API, "3A").split("### 3A.3", 1)[1]
    assert "raises the owned-group count above the declared number" in three_a_three
    assert "satisfying only the prohibition MUST NOT be sufficient" in three_a_three

    # And freeze contract §11 must declare the same cardinality rather than merely agreeing in tone.
    assert "**exactly one** per attempt" in numbered_section_text(FREEZE_CONTRACT, "11")


def test_every_handle_mention_in_the_attempt_matrix_is_classified() -> None:
    """The fail-closed half of K-01, asserted directly rather than only as a side effect.

    If a future edit rewords a handle mention into something the marker set does not cover, the
    right outcome is a red gate, not a quietly smaller write count. This test pins the classes the
    committed matrix actually produces, so both a new unclassifiable mention and a silent
    reclassification of an existing one are visible.
    """
    mentions = classified_handle_mentions(read(STATE_API))
    assert not [m for m in mentions if m[1] == UNCLASSIFIED], [m[2] for m in mentions]

    by_edge: dict[str, set[str]] = {}
    for row, verdict, _clause in mentions:
        by_edge.setdefault(f"{row[0]} -> {row[2]}", set()).add(verdict)

    # The one write point, beside the read of the ceiling discriminator in the same cell.
    assert by_edge["CREATED -> STARTING"] == {WRITES, READS_ONLY}, by_edge
    # The prohibition that guards the edge which must not write — and, now that L-01 widened the
    # scope from "clauses repeating the field name" to "every clause of the row once the handle
    # has been named", the legitimate write to the *other* field in the same cell, which the
    # previous classifier never looked at. Distinguishing those two is requirement 3.
    assert by_edge["STARTING -> RUNNING"] == {PROHIBITS_WRITE, WRITES_OTHER_FIELD}, by_edge
    # Every other mention is a read: cancellation edges identify, name or prove a group from the
    # handle, and the quarantine edges refer to a *later* §3D retirement of it.
    for edge, verdicts in by_edge.items():
        if edge not in {"CREATED -> STARTING", "STARTING -> RUNNING"}:
            assert verdicts == {READS_ONLY}, (edge, verdicts)


# The `STARTING -> RUNNING` cell as the candidate commits it — the edge H-03 forbids to write the
# handle, and therefore the edge a restored handover would attack.
RUNNING_EDGE_MARKER = "`attempt.running_process_group_identity` is written in this same commit"

# Operative second writes, in the ordinary paraphrases the K-01 review proved invisible. Variants
# A and B of that review — "is durably rewritten to name" and "is written" — are the two that must
# flip from MISSED to CAUGHT, so both appear here explicitly.
SECOND_WRITE_PHRASINGS = (
    "is written to name",
    "is rewritten to name",
    "is durably rewritten to name",
    "is updated to name",
    "is replaced with",
    "is set to",
    "is recorded as",
    "is superseded by the identity of",
    "is committed for",
)


def state_api_with_a_second_handle_write(phrasing: str) -> str:
    """The committed state API, with one operative second write injected into a real §3A edge.

    The mutation is deliberately minimal and deliberately *survivable* by the other two gates:
    §3A.3's prohibition sentence and its declared count of `1` are both left exactly as they are,
    and the injection lands on the genuine `STARTING -> RUNNING` row rather than on a row invented
    for the test. That is the shape the review demonstrated, and the shape a careless freeze edit
    would take.
    """
    api = read(STATE_API)
    edge_lines = [
        line for line in api.splitlines()
        if line.startswith("| STARTING |") and RUNNING_EDGE_MARKER in line
    ]
    assert len(edge_lines) == 1, edge_lines
    original = edge_lines[0]

    injected = (
        f". A fresh controller-allocated process group is created for the model process "
        f"and `{CLEANUP_HANDLE}` {phrasing} that group"
    )
    mutated_line = original[: original.rindex("|")].rstrip() + injected + " |"
    mutated = api.replace(original, mutated_line)
    assert mutated != api

    # The mutant must leave the two independent gates satisfied, or it would prove nothing about
    # this one.
    assert "MUST NOT update, replace or clear `lease.owned_process_group_handle`" in mutated
    assert "| `attempt` (TASK or INTEGRATION) | 1 | `CREATED -> STARTING` |" in mutated
    return mutated


@pytest.mark.parametrize("phrasing", SECOND_WRITE_PHRASINGS)
def test_a_second_handle_write_is_caught_whatever_verb_introduces_it(phrasing: str) -> None:
    """K-01's required mutation proof: the gate must fail on each of these, not just on "committed".

    Each case restores the H-03 two-group handover as an operative write on the real
    `STARTING -> RUNNING` edge, in contradiction of the prohibition sitting in the same cell, and
    leaves §3A.3's prohibition and declared count of `1` untouched. Before this repair every
    phrasing but the last left the suite fully green.
    """
    mutated = state_api_with_a_second_handle_write(phrasing)

    writing = attempt_rows_writing_the_cleanup_handle(mutated)
    assert len(writing) == 2, (
        f"a second write phrased {phrasing!r} was not derived as a write: "
        + "; ".join(f"{row[0]} -> {row[2]}" for row in writing)
    )
    assert [f"{row[0]} -> {row[2]}" for row in writing] == [
        "CREATED -> STARTING",
        "STARTING -> RUNNING",
    ]

    with pytest.raises(AssertionError, match="§3A edges write the cleanup handle"):
        assert_declared_write_point_matches_the_matrix(mutated)


def test_the_gate_fails_closed_on_handle_wording_it_cannot_classify() -> None:
    """Requirement 5, proved rather than asserted: unknown wording is not silently ignored.

    A mention carrying no marker from any of the three sets is not evidence that the edge is
    harmless — it is evidence that this gate can no longer speak about the edge, which must stop
    the freeze rather than pass it.
    """
    api = read(STATE_API)
    edge_lines = [
        line for line in api.splitlines()
        if line.startswith("| STARTING |") and RUNNING_EDGE_MARKER in line
    ]
    original = edge_lines[0]
    mutated = api.replace(
        original,
        original[: original.rindex("|")].rstrip()
        + f". The model group thereafter enjoys `{CLEANUP_HANDLE}` |",
    )
    assert mutated != api

    with pytest.raises(AssertionError, match="cannot classify"):
        attempt_rows_writing_the_cleanup_handle(mutated)


def test_the_pristine_candidate_is_the_control_for_those_mutations() -> None:
    """The mutation cases above are only evidence if the unmutated document passes the same gate."""
    assert_declared_write_point_matches_the_matrix(read(STATE_API))
    assert_declared_group_count_matches_the_matrix(read(STATE_API))


# --------------------------------------------------------------------------------------------
# L-01 — co-referential second writes, and the two independent dimensions that must catch them.
#
# Every case below is appended to the *real* `STARTING -> RUNNING` cell and leaves §3A.3's
# prohibition sentence and its declared count of `1` exactly as committed, because that is the
# shape the review proved invisible and the shape a careless freeze edit would take. Each case is
# labelled with the grammatical device it exercises, so a reader can see the class is covered
# rather than a list of sentences.
# --------------------------------------------------------------------------------------------


def state_api_with_appended_running_edge_prose(tail: str) -> str:
    """The committed state API with `tail` appended to the genuine `STARTING -> RUNNING` cell."""
    api = read(STATE_API)
    edge_lines = [
        line for line in api.splitlines()
        if line.startswith("| STARTING |") and RUNNING_EDGE_MARKER in line
    ]
    assert len(edge_lines) == 1, edge_lines
    original = edge_lines[0]
    mutated = api.replace(original, original[: original.rindex("|")].rstrip() + tail + " |")
    assert mutated != api

    assert "MUST NOT update, replace or clear `lease.owned_process_group_handle`" in mutated
    assert "| `attempt` (TASK or INTEGRATION) | 1 | `CREATED -> STARTING` |" in mutated
    return mutated


# The four escapes the L-01 review demonstrated against `a904a20`, verbatim from the inbox.
REVIEW_CO_REFERENCE_ESCAPES = (
    (
        "pronoun 'it', semicolon boundary",
        "; a fresh controller-allocated process group is created for the model process"
        " and it is set to that group's identity",
    ),
    (
        "alias 'the cleanup handle', sentence boundary",
        ". A fresh controller-allocated process group is created for the model process"
        " and the cleanup handle is rewritten to name it",
    ),
    (
        "anaphor 'This field', own sentence",
        ". A fresh controller-allocated process group is created for the model process."
        " This field is then updated to name that group",
    ),
    (
        "noun-phrase alias 'The attempt's owned process group handle'",
        ". The attempt's owned process group handle is replaced with the identity of a fresh"
        " controller-allocated model process group",
    ),
)

# Escapes invented here rather than taken from the review, covering the rest of the class: bare
# pronoun, alias, demonstrative+noun, active voice, an em-dash aside, and a passive with an
# adverb between auxiliary and participle.
INVENTED_CO_REFERENCE_ESCAPES = (
    (
        "bare pronoun after a semicolon",
        "; it is then written to name a freshly created model process group",
    ),
    (
        "active voice — verb precedes its object",
        ". The controller rewrites the attempt's cleanup handle to the identity of the model"
        " process group",
    ),
    (
        "noun-phrase alias with a trailing qualifier",
        ". The owned process group handle for this attempt is assigned the identity of the"
        " model process group",
    ),
    (
        "demonstrative + generic noun ('this value')",
        "; this value is superseded by the model process group's identity",
    ),
    (
        "em-dash aside, and two coordinated verbs",
        ". The handle — write-once until now — is cleared and then set to the new group",
    ),
    (
        "passive with an adverb inside the verb phrase",
        ". That field is durably populated with the model group's controller-allocated identity",
    ),
)


@pytest.mark.parametrize(
    "device,tail",
    REVIEW_CO_REFERENCE_ESCAPES + INVENTED_CO_REFERENCE_ESCAPES,
    ids=lambda value: value.replace(" ", "-")[:40],
)
def test_a_co_referential_second_handle_write_is_derived_as_a_write(device: str, tail: str) -> None:
    """L-01's core proof: a second write that never repeats the field name is still counted.

    Before this repair `classified_handle_mentions` only *looked at* clauses matching the
    backticked identifier, so none of these were classified at all — not even as unclassifiable —
    and the derived write count stayed at 1. Each case must now derive two write points on two
    distinct edges and fail the declared-cardinality gate.
    """
    mutated = state_api_with_appended_running_edge_prose(tail)

    writing = attempt_rows_writing_the_cleanup_handle(mutated)
    assert [f"{row[0]} -> {row[2]}" for row in writing] == [
        "CREATED -> STARTING",
        "STARTING -> RUNNING",
    ], f"{device}: co-referential write not derived"

    with pytest.raises(AssertionError, match="§3A edges write the cleanup handle"):
        assert_declared_write_point_matches_the_matrix(mutated)


# Prose that refers to the handle in wording carrying no marker from any of the three closed sets.
# The right outcome is a red gate: the classifier can no longer speak about the edge, and silence
# is not a safety argument. Requirement 4's "unknown/ambiguous critical prose fails closed".
AMBIGUOUS_HANDLE_PROSE = (
    ("pronoun with an unknown predicate", ". It thereafter designates the model process group"),
    ("alias with an unknown predicate", ". The cleanup handle henceforth tracks the model group"),
    (
        "literal field with an unknown predicate",
        f". The model group thereafter enjoys `{CLEANUP_HANDLE}`",
    ),
)


@pytest.mark.parametrize(
    "device,tail", AMBIGUOUS_HANDLE_PROSE, ids=lambda value: value.replace(" ", "-")[:40]
)
def test_ambiguous_handle_prose_fails_closed_whether_or_not_it_names_the_field(
    device: str, tail: str
) -> None:
    """Ambiguity is fatal for a co-reference too, not only for a literal mention.

    This is the property that stops the L-01 repair from becoming a broad heuristic that produces
    false confidence: the classifier does not guess that an unrecognised predicate is harmless.
    """
    mutated = state_api_with_appended_running_edge_prose(tail)
    with pytest.raises(AssertionError, match="cannot classify"):
        attempt_rows_writing_the_cleanup_handle(mutated)


# Legitimate additions that must NOT turn the gate red, or the gate would merely be rejecting
# every write verb near the handle and would prove nothing.
LEGITIMATE_HANDLE_CONTEXT_PROSE = (
    (
        "write to an explicitly different backticked field",
        ". `attempt.running_process_group_identity` is recorded for the model process in this"
        " same commit",
    ),
    ("lease retirement, not handle retirement", ". The lease is retired once cleanup is proven"),
    (
        "an unambiguous read of the handle",
        f". The group named by `{CLEANUP_HANDLE}` is left exactly as it is",
    ),
)


@pytest.mark.parametrize(
    "device,tail", LEGITIMATE_HANDLE_CONTEXT_PROSE, ids=lambda value: value.replace(" ", "-")[:40]
)
def test_legitimate_prose_in_handle_context_keeps_the_gate_green(device: str, tail: str) -> None:
    """The negative controls. Requirement 3 and requirement 4's carve-outs, proved non-vacuous."""
    mutated = state_api_with_appended_running_edge_prose(tail)
    assert_declared_write_point_matches_the_matrix(mutated)
    assert_declared_group_count_matches_the_matrix(mutated)


def test_every_non_handle_write_carve_out_is_live_and_narrow() -> None:
    """Requirement 4: the carve-out set is closed, and every member of it is asserted.

    A carve-out is a hole in a fail-closed gate, so it may not be added speculatively and may not
    outlive the prose it was written for. Each pattern must match somewhere in the committed §3A
    matrix, and must not match the handle itself.
    """
    matrix = "\n".join(" | ".join(row) for row in attempt_transition_rows(read(STATE_API)))
    for pattern in NON_HANDLE_WRITE_SUBJECTS:
        found = pattern.search(matrix)
        assert found, f"carve-out {pattern.pattern!r} matches nothing in §3A and must be removed"
        assert not HANDLE_MENTION_RE.search(found.group(0)), found.group(0)
        assert not HANDLE_ALIAS_RE.search(found.group(0)), found.group(0)

    # And the carve-out must be doing real work: without it the pristine document fails closed,
    # which is what proves it is a deliberate, narrow exception rather than dead code.
    lease_clause = "the lease is released/retired and the old fencing token can never admit a result"
    assert classify_handle_clause(lease_clause, established=True) == NEUTRAL
    assert _carved_out_write_spans(lease_clause)


# --------------------------------------------------------------------------------------------
# L-01 requirement 6 — defence in depth. The declared group count, derived from §3A's own prose
# about group creation, with no reference to the cleanup handle at all.
# --------------------------------------------------------------------------------------------


def test_the_declared_group_count_is_derived_from_the_matrix_independently() -> None:
    """Exactly one §3A edge brings an owned process group into existence, and §3A.3 says 1."""
    api = read(STATE_API)
    creating = attempt_rows_creating_an_owned_process_group(api)
    assert [f"{row[0]} -> {row[2]}" for row in creating] == ["CREATED -> STARTING"], creating
    assert_declared_group_count_matches_the_matrix(api)


def test_group_creation_denials_in_the_matrix_are_not_read_as_creations() -> None:
    """The derivation is only sound if `no second group is created` counts as zero groups.

    These three denials are load-bearing prose in the committed matrix; misreading any one of
    them as a creation would make the count 2 or more and turn the invariant into noise.
    """
    for denial in (
        "so this edge MUST NOT update, replace or clear the handle and no second group is created",
        "no owned process group has been created, proven by the handle being NULL",
        "A NULL handle means no group was ever created and cleanup is therefore proven",
    ):
        assert not _asserts_a_group_creation(denial), denial

    assert _asserts_a_group_creation(
        "the attempt's single owned process group is created (§3A.3)"
    )


@pytest.mark.parametrize(
    "device,tail",
    [case for case in REVIEW_CO_REFERENCE_ESCAPES if "process group is created" in case[1]],
    ids=lambda value: value.replace(" ", "-")[:40],
)
def test_a_second_created_group_fails_on_the_cardinality_dimension_alone(
    device: str, tail: str
) -> None:
    """The reinforcement, proved to be genuinely independent of the handle wording.

    Three of the review's four escapes announce a second controller-created process group. Those
    fail here on group cardinality alone — no clause about the handle is consulted — so however
    the handle sentence is reworded, the unsafe second group still cannot pass.
    """
    mutated = state_api_with_appended_running_edge_prose(tail)

    creating = attempt_rows_creating_an_owned_process_group(mutated)
    assert [f"{row[0]} -> {row[2]}" for row in creating] == [
        "CREATED -> STARTING",
        "STARTING -> RUNNING",
    ], device

    with pytest.raises(AssertionError, match="§3A edges create an owned process group"):
        assert_declared_group_count_matches_the_matrix(mutated)


def test_the_group_cardinality_dimension_has_a_stated_blind_spot() -> None:
    """Honest scope: the fourth review escape creates no group *in prose*, so this gate is silent.

    It names an already-existing "fresh controller-allocated model process group" without
    asserting that §3A creates one. The handle-write dimension is what catches it. Recording the
    limit here keeps the two dimensions from being mistaken for one redundant gate — and pins the
    division of labour, so a future edit cannot quietly leave the escape covered by neither.
    """
    _device, tail = REVIEW_CO_REFERENCE_ESCAPES[3]
    mutated = state_api_with_appended_running_edge_prose(tail)

    assert_declared_group_count_matches_the_matrix(mutated)  # silent, by construction
    with pytest.raises(AssertionError, match="§3A edges write the cleanup handle"):
        assert_declared_write_point_matches_the_matrix(mutated)


# --------------------------------------------------------------------------------------------
# M-01 — the decoy-field false green, and the class of escapes it belongs to.
#
# Every mutation below appends an operative second write to the *real* `STARTING -> RUNNING` cell
# while leaving §3A.3's prohibition sentence and its declared count of `1` exactly as committed —
# the shape the independent review proved invisible. What they have in common is that a backticked
# non-handle `record.field` sits nearer the write verb than the handle referent does, so the L-01
# classifier charged the write to that field and returned `WRITES_OTHER_FIELD`, which is both
# uncounted and exempt from failing closed.
#
# Each case is labelled with the device it exercises so the *class* is visible rather than a list
# of sentences. The first six are the semantic equivalents of the review's M1/M2/M3/M4/M6/M7; the
# rest are adjacent variants invented here, covering the grammar the review did not walk.
# --------------------------------------------------------------------------------------------

# The review's demonstrated false greens, restated. M6 and M7 are complete two-group handovers —
# a creation *and* a rewrite — and were green on both dimensions at once, because their creation
# verbs were also outside the M-02 derivation.
REVIEW_DECOY_ESCAPES = (
    (
        "M1 — literal decoy field, literal handle, known verb",
        ". The identity of the new model group is written into"
        f" `attempt.running_process_group_identity` and into `{CLEANUP_HANDLE}`",
    ),
    (
        "M2 — literal decoy field, English alias for the handle",
        ". The identity of the new model group is recorded in"
        " `attempt.running_process_group_identity` and in the cleanup handle",
    ),
    (
        "M3 — decoy first, handle carried by an elliptical 'as is'",
        ". `attempt.running_process_group_identity` is set to that group, as is the cleanup handle",
    ),
    (
        "M4 — decoy absorbs the known verb, handle takes an unknown predicate",
        ". `attempt.running_process_group_identity` is written here, and the cleanup handle"
        " thereafter designates that same new group",
    ),
    (
        "M6 — two-group handover, present-tense creation plus a decoy-shielded rewrite",
        ". The controller creates a second process group for the model process."
        " The identity of that group is written into `attempt.running_process_group_identity`"
        " and into the cleanup handle",
    ),
    (
        "M7 — two-group handover, object-after-verb creation plus a decoy-shielded rewrite",
        ". The model process is placed into a newly instantiated controller-allocated group."
        " That group's identity is recorded in `attempt.running_process_group_identity` and in"
        " the attempt's owned process group handle",
    ),
)

# Adjacent variants the review did not demonstrate, one per grammatical device. Measured against
# the rejected gate, five of these seven were false greens exactly like M1–M4; the first two —
# active voice and the bare pronoun — were already caught there, because nearest-referent
# resolution happened to land on the handle. They are kept as regression controls rather than
# dropped: the M-01 rule must not lose a case the rejected gate already held.
INVENTED_DECOY_ESCAPES = (
    (
        "active voice — the controller as subject, verb before both objects",
        ". The controller updates `attempt.running_process_group_identity` and the cleanup handle"
        " in the same commit",
    ),
    (
        "co-reference — the second target is a bare pronoun",
        ". `attempt.running_process_group_identity` is written here, and it is populated with the"
        " same value",
    ),
    (
        "noun alias — 'the attempt's process group handle'",
        ". The new group's identity is recorded in `attempt.running_process_group_identity` and in"
        " the attempt's process group handle",
    ),
    (
        "clause reordering — the decoy is fronted so it is nearest the verb",
        ". Into the cleanup handle, and into `attempt.running_process_group_identity`, the new"
        " model group's identity is written",
    ),
    (
        "read-marker camouflage — the marker trails the handle instead of governing it",
        ". The identity of the new model group is written into"
        " `attempt.running_process_group_identity` and into the cleanup handle, which is read"
        " from the lease",
    ),
    (
        "unknown predicate on the handle, known verb on the decoy",
        ". `attempt.running_process_group_identity` is updated in this commit, and that field"
        " thereafter doubles as the cleanup identity of the model group",
    ),
    (
        "prohibition survives, decoy carries the operative write",
        ". This edge MUST NOT clear the cleanup handle, which"
        " `attempt.running_process_group_identity` is then written into",
    ),
)

DECOY_ESCAPES = REVIEW_DECOY_ESCAPES + INVENTED_DECOY_ESCAPES


@pytest.mark.parametrize(
    "device,tail", DECOY_ESCAPES, ids=lambda value: value.replace(" ", "-")[:44]
)
def test_a_decoy_field_cannot_absorb_a_write_to_the_cleanup_handle(device: str, tail: str) -> None:
    """M-01's core proof: the freeze gate rejects every one of these.

    The assertion is deliberately on the *gate*, not on a particular verdict, because two verdicts
    are both correct answers here: a write the classifier can attribute to the handle is a second
    write point and fails on cardinality, while a write it cannot prove went elsewhere is
    UNCLASSIFIED and fails closed. What must never happen again is the third outcome — silence.
    """
    mutated = state_api_with_appended_running_edge_prose(tail)

    with pytest.raises(AssertionError) as raised:
        assert_declared_write_point_matches_the_matrix(mutated)
    assert re.search(
        r"cannot classify|§3A edges write the cleanup handle", str(raised.value)
    ), f"{device}: gate failed for an unrelated reason: {raised.value}"


@pytest.mark.parametrize(
    "device,tail", DECOY_ESCAPES, ids=lambda value: value.replace(" ", "-")[:44]
)
def test_no_decoy_escape_is_ever_classified_as_a_write_to_another_field(
    device: str, tail: str
) -> None:
    """The precise M-01 property, asserted clause by clause rather than through the gate.

    `WRITES_OTHER_FIELD` is the verdict that made the gate go quiet, so it is the verdict none of
    these clauses may receive. Asserting it here — instead of only observing that the gate goes
    red — pins the mechanism, so a future edit cannot restore the false green while keeping these
    cases failing for some other, accidental reason.
    """
    injected = [clause for clause in _CLAUSE_BOUNDARY_RE.split(tail) if clause.strip()]
    assert injected, device

    verdicts = {classify_handle_clause(clause, established=True) for clause in injected}
    assert WRITES_OTHER_FIELD not in verdicts, f"{device}: decoy absorbed the write: {verdicts}"
    assert verdicts & {WRITES, UNCLASSIFIED}, f"{device}: no clause was found dangerous: {verdicts}"


# Prose that must stay green, or the repair would just be a ban on write verbs near the handle.
# The first two are the legitimate controls the repair is required to preserve: a real write to an
# unrelated field, and explicit read-only handle prose.
LEGITIMATE_DECOY_ADJACENT_PROSE = (
    (
        "a genuine write to an unrelated field, with no handle referent in the clause",
        ". `attempt.running_process_group_identity` is written for the model process in this same"
        " commit",
    ),
    (
        "a genuine write to an unrelated field beside a read-marked handle",
        f". The group named by `{CLEANUP_HANDLE}` is unchanged, and"
        " `attempt.running_process_group_identity` is written in this same commit",
    ),
    (
        "explicit read-only handle prose, no write anywhere",
        f". The preflight group is identified from `{CLEANUP_HANDLE}` and is left exactly as it is",
    ),
    (
        "the committed 'MUST NOT be used as the cleanup handle' shape, restated",
        ". `attempt.workspace_epoch` is written in this same commit as the workspace discriminator"
        " alone, and MUST NOT be used as the cleanup handle",
    ),
)


@pytest.mark.parametrize(
    "device,tail",
    LEGITIMATE_DECOY_ADJACENT_PROSE,
    ids=lambda value: value.replace(" ", "-")[:44],
)
def test_the_decoy_rule_leaves_legitimate_other_field_writes_and_reads_green(
    device: str, tail: str
) -> None:
    """The false-positive controls for M-01, through both dimensions of the gate."""
    mutated = state_api_with_appended_running_edge_prose(tail)
    assert_declared_write_point_matches_the_matrix(mutated)
    assert_declared_group_count_matches_the_matrix(mutated)


def test_the_committed_running_edge_still_charges_its_write_to_the_other_field() -> None:
    """The narrowest control of all: §3A's own ceiling-discriminator clause.

    This is the single committed clause in the whole matrix that classifies `WRITES_OTHER_FIELD`,
    and it does so only because "MUST NOT be used as" governs the handle referent beside it. If the
    M-01 rule ever stopped honouring a read marker that precedes its referent, this clause would
    fail closed and the pristine freeze document would be rejected by its own gate.
    """
    clause = (
        "`attempt.running_process_group_identity` is written in this same commit and only here, as"
        " the ceiling discriminator alone, and MUST NOT be used as the cleanup handle (§3A.3)"
    )
    assert clause in read(STATE_API)
    assert classify_handle_clause(clause, established=True) == WRITES_OTHER_FIELD
    assert not _live_handle_referents(clause, _referents(clause, established=True))

    # And the same sentence with the marker removed is contested, not silently charged elsewhere.
    without_marker = clause.replace("MUST NOT be used as the cleanup handle", "the cleanup handle")
    assert classify_handle_clause(without_marker, established=True) == UNCLASSIFIED


# --------------------------------------------------------------------------------------------
# M-02 — the group-creation derivation, widened to the forms the review demonstrated.
# --------------------------------------------------------------------------------------------

# Creation assertions the derivation missed at the rejected SHA: present tense, synonyms, and the
# created group named *after* its verb. Each is appended to the real `STARTING -> RUNNING` cell and
# says nothing whatever about the cleanup handle, so the group dimension has to catch it alone.
M02_CREATION_FORMS = (
    ("present tense, active voice", ". The controller creates a second process group for the model"),
    (
        "object after the verb, past participle",
        ". The model process is placed into a newly created controller-allocated group",
    ),
    ("synonym 'instantiated'", ". A second owned process group is instantiated for the model"),
    ("synonym 'provisioned'", ". The controller provisions a second process group for the model"),
    ("synonym 'opened', object after the verb", ". The controller opens a second process group"),
    ("present participle, object after the verb", ". The controller is creating a second cgroup"),
)


@pytest.mark.parametrize(
    "device,tail", M02_CREATION_FORMS, ids=lambda value: value.replace(" ", "-")[:44]
)
def test_the_group_derivation_covers_the_creation_forms_the_review_demonstrated(
    device: str, tail: str
) -> None:
    """M-02: a second group is a second group however the sentence is arranged."""
    mutated = state_api_with_appended_running_edge_prose(tail)

    creating = attempt_rows_creating_an_owned_process_group(mutated)
    assert [f"{row[0]} -> {row[2]}" for row in creating] == [
        "CREATED -> STARTING",
        "STARTING -> RUNNING",
    ], device

    with pytest.raises(AssertionError, match="§3A edges create an owned process group"):
        assert_declared_group_count_matches_the_matrix(mutated)


# Prose containing a creation verb that creates no *group*, or denies creating one. Requirement:
# widening the verb set must not turn broad harmless prose into an automatic failure.
M02_NON_CREATIONS = (
    "the workspace reservation established at admission is unchanged",
    "a new lease is created for the corrected attempt",
    "evidence for the model process is recorded in the same commit",
    "no second process group is created for the model process",
    "the controller never creates a second process group",
    "the model process is launched inside the attempt's existing owned process group",
    "a replacement workspace is provisioned without a new process group, reusing the existing one",
)


@pytest.mark.parametrize("clause", M02_NON_CREATIONS, ids=lambda value: value[:44])
def test_the_widened_group_derivation_does_not_fire_on_harmless_prose(clause: str) -> None:
    """The false-positive controls for M-02, at clause level.

    The last case is the load-bearing one: a creation verb and a group noun in the same clause but
    in different segments, with the group explicitly *not* created. Segment scoping, not distance,
    is what keeps the two apart.
    """
    assert not _asserts_a_group_creation(clause), clause


def test_the_group_derivation_still_requires_a_group_noun_in_the_verbs_own_segment() -> None:
    """Why the widening is safe: the verb alone never asserts a group.

    Without the noun requirement, every `created`/`established`/`opened` in §3A — of a lease, a
    workspace, an epoch — would be counted as a process group, and the cardinality invariant would
    be noise. The noun and the negator are both scoped to the verb's own segment, so neither can
    reach across a comma to a clause it never spoke about.
    """
    assert not _asserts_a_group_creation("a new fencing token is created")
    assert _asserts_a_group_creation("a new process group is created")
    assert _asserts_a_group_creation("the controller creates a new process group")
    # Reaching across a segment boundary in either direction must not manufacture a creation.
    assert not _asserts_a_group_creation(
        "a new fencing token is created, and the existing process group is reused"
    )
    # ... nor must a negator in a neighbouring segment suppress a real one.
    assert _asserts_a_group_creation(
        "no model process is launched yet, and a second process group is created here"
    )


def test_the_group_derivation_blind_spots_are_stated_rather_than_assumed_closed() -> None:
    """Honest scope for M-02, carried forward for the next review.

    The derivation reads assertions, not references: a clause that *mentions* an already-created
    group without asserting a new one is silent here by construction, and a back-reference to the
    legitimate `CREATED -> STARTING` creation is counted as a creation (over-strict, fail-closed).
    Both are recorded so a later reader cannot mistake the widened set for completeness.
    """
    # Silent: names a group, asserts no creation. The handle dimension is what catches this class.
    assert not _asserts_a_group_creation(
        "the identity of a fresh controller-allocated model process group"
    )
    # Over-strict, in the safe direction: a back-reference reads as a creation and turns it red.
    assert _asserts_a_group_creation(
        "the preflight group created on the earlier edge continues to hold the child"
    )


# --------------------------------------------------------------------------------------------
# M-03 — a row is not the declared unit.
#
# Both cardinality derivations deduplicated by transition row (`if row not in rows`), so the one
# row that legitimately writes the handle and creates the attempt's group could absorb a *second*
# write and a *second* creation and still be counted once. §3A.3's prohibition sentence and its
# declared count of `1` stayed intact, both dimensions stayed green, and the classifier was never
# fooled — it emitted the second `WRITES` and `_asserts_a_group_creation` returned True; the
# aggregation threw the evidence away. Every earlier handover mutation placed its second write on
# a *different* row, which is the only placement row-counting can see.
#
# Every mutation below is therefore confined to `CREATED -> STARTING`, the legitimate row.
# --------------------------------------------------------------------------------------------

# The `CREATED -> STARTING` cell as the candidate commits it: the one edge that may write the
# handle, and the one edge that creates the attempt's single owned process group.
CREATING_EDGE_MARKER = "is committed **before** the attempt's single owned process group is created"


def state_api_with_appended_prose(row_prefix: str, marker: str, tail: str) -> str:
    """The committed state API with `tail` appended to the §3A row identified by `marker`.

    The generalisation of `state_api_with_appended_running_edge_prose` to any edge. M-03 needs its
    mutations inside `CREATED -> STARTING`, and M-04 needs a row carrying no handle context at all,
    so that the group dimension is demonstrably the only thing standing between the document and
    an unsafe second group.
    """
    api = read(STATE_API)
    edge_lines = [
        line for line in api.splitlines() if line.startswith(row_prefix) and marker in line
    ]
    assert len(edge_lines) == 1, edge_lines
    original = edge_lines[0]
    mutated = api.replace(original, original[: original.rindex("|")].rstrip() + tail + " |")
    assert mutated != api

    # The mutant has to leave every other dimension of the gate satisfied, or it proves nothing.
    assert "MUST NOT update, replace or clear `lease.owned_process_group_handle`" in mutated
    assert "| `attempt` (TASK or INTEGRATION) | 1 | `CREATED -> STARTING` |" in mutated
    return mutated


def state_api_with_appended_creating_edge_prose(tail: str) -> str:
    """The committed state API with `tail` appended to the genuine `CREATED -> STARTING` cell."""
    return state_api_with_appended_prose("| CREATED |", CREATING_EDGE_MARKER, tail)


# Complete handovers — a second group created *and* the handle rewritten to name it — placed
# entirely inside the legitimate row. Each is labelled with the device it exercises. All six left
# the rejected gate green on the dimension named in the test; the row count never moved off 1.
SAME_ROW_HANDOVERS = (
    (
        "explicit backticked handle, second sentence in the same cell",
        ". A second controller-allocated process group is created for the model process, and"
        " `lease.owned_process_group_handle` is rewritten to name it",
    ),
    (
        "natural-language alias for the handle",
        ". A second controller-allocated process group is created for the model process, and the"
        " attempt's cleanup handle is then updated to name that group",
    ),
    (
        "decoy field beside the alias — M-01's device inside M-03's placement",
        ". A second controller-allocated process group is created for the model process. Its"
        " identity is written into `attempt.running_process_group_identity` and into the cleanup"
        " handle",
    ),
)


@pytest.mark.parametrize(
    "device,tail", SAME_ROW_HANDOVERS, ids=lambda value: value.replace(" ", "-")[:44]
)
def test_a_complete_handover_inside_the_legitimate_row_fails_both_dimensions(
    device: str, tail: str
) -> None:
    """M-03's core proof: the count that decides the gate is a count of assertions, not of rows.

    The row-level derivations are deliberately asserted to be *unchanged* here — one writing row,
    one creating row — because that is the whole point: they cannot see this mutation, and a
    repair that merely made them noisier would not have found the defect.
    """
    mutated = state_api_with_appended_creating_edge_prose(tail)

    assert [
        f"{row[0]} -> {row[2]}" for row in attempt_rows_creating_an_owned_process_group(mutated)
    ] == ["CREATED -> STARTING"], f"{device}: the mutation was not confined to one row"

    with pytest.raises(AssertionError, match="owned process group creations"):
        assert_declared_group_count_matches_the_matrix(mutated)

    with pytest.raises(AssertionError) as raised:
        assert_declared_write_point_matches_the_matrix(mutated)
    assert re.search(
        r"cannot classify|asserts \d+ writes of the cleanup handle", str(raised.value)
    ), f"{device}: the write dimension failed for an unrelated reason: {raised.value}"


def test_a_second_creation_inside_the_legitimate_row_fails_the_group_dimension_alone() -> None:
    """Half of the handover, so neither dimension can be credited with the other's catch.

    Nothing here says a word about the cleanup handle, so the write dimension is silent by
    construction and the group cardinality is the only guard — exactly the division of labour
    `test_the_group_cardinality_dimension_has_a_stated_blind_spot` pins from the other side.
    """
    mutated = state_api_with_appended_creating_edge_prose(
        ". A second controller-allocated process group is created for the model process"
    )

    assert_declared_write_point_matches_the_matrix(mutated)  # silent, by construction
    assert len(owned_process_group_creation_assertions(mutated)) == 2
    with pytest.raises(AssertionError, match="owned process group creations"):
        assert_declared_group_count_matches_the_matrix(mutated)


def test_a_second_write_inside_the_legitimate_row_fails_the_write_dimension_alone() -> None:
    """The other half: a second write to the handle that creates no group in prose."""
    mutated = state_api_with_appended_creating_edge_prose(
        ". `lease.owned_process_group_handle` is rewritten to name the model process group"
    )

    assert_declared_group_count_matches_the_matrix(mutated)  # silent, by construction
    assert [
        f"{row[0]} -> {row[2]}" for row in attempt_rows_writing_the_cleanup_handle(mutated)
    ] == ["CREATED -> STARTING"]
    with pytest.raises(AssertionError, match="asserts 2 writes of the cleanup handle"):
        assert_declared_write_point_matches_the_matrix(mutated)


def test_a_second_write_in_the_same_clause_is_counted_as_a_second_write() -> None:
    """The escape one step past M-03: same row *and* same clause, so clause-counting alone misses.

    The tail carries no sentence or semicolon boundary, so it joins the committed write clause
    rather than forming a new one. Counting `WRITES` clauses would still say 1; counting the write
    assertions inside them says 2.
    """
    mutated = state_api_with_appended_creating_edge_prose(
        " and `lease.owned_process_group_handle` is then set to the model group's identity"
    )

    pristine = classified_handle_mentions(read(STATE_API))
    assert len(classified_handle_mentions(mutated)) == len(pristine), "a new clause was created"
    with pytest.raises(AssertionError, match="asserts 2 writes of the cleanup handle"):
        assert_declared_write_point_matches_the_matrix(mutated)


def test_the_committed_matrix_asserts_exactly_one_write_and_exactly_one_creation() -> None:
    """The pristine control for M-03, and the measurement the counts are calibrated against.

    Both numbers are 1 for reasons worth pinning. The write clause contains *two* `WRITE_VERBS`
    tokens attributed to the handle — "the only edge that **may write** the cleanup handle" and
    "is **committed**" — which name one write event, not two; the permission modal is what
    separates them. The creating segment contains one creation verb. If either number moves, the
    counts have started measuring something other than what §3A.3 declares.
    """
    api = read(STATE_API)

    assert len(cleanup_handle_write_assertions(api)) == 1, cleanup_handle_write_assertions(api)
    assert len(owned_process_group_creation_assertions(api)) == 1, (
        owned_process_group_creation_assertions(api)
    )

    write_clause = (
        "This is the only edge that may write the cleanup handle:"
        " `lease.owned_process_group_handle` is committed **before** the attempt's single owned"
        " process group is created (§3A.3), and preflight runs inside that group"
    )
    assert write_clause in api
    assert _classify_handle_clause(write_clause, established=True) == (WRITES, 1)
    assert len(list(WRITE_VERB_RE.finditer(write_clause))) == 2


# Prose added to the legitimate row that is genuinely harmless. If any of these turned the gate
# red, the assertion counts would be a ban on writing about the row at all.
LEGITIMATE_PROSE_INSIDE_THE_CREATING_ROW = (
    (
        "a real write to an unrelated field, read-marked handle beside it",
        ". `attempt.workspace_epoch` is written in this same commit as the workspace discriminator"
        " alone, and MUST NOT be used as the cleanup handle",
    ),
    (
        "a read-only reference to the handle",
        f". The preflight group is identified from `{CLEANUP_HANDLE}` and is left exactly as it is",
    ),
    (
        "a creation of something that is not a process group",
        ". A new fencing token is created for the correction, and a new lease is established",
    ),
)


@pytest.mark.parametrize(
    "device,tail",
    LEGITIMATE_PROSE_INSIDE_THE_CREATING_ROW,
    ids=lambda value: value.replace(" ", "-")[:44],
)
def test_counting_assertions_leaves_legitimate_prose_in_the_creating_row_green(
    device: str, tail: str
) -> None:
    """The false-positive controls for M-03, through both dimensions of the gate."""
    mutated = state_api_with_appended_creating_edge_prose(tail)
    assert_declared_write_point_matches_the_matrix(mutated)
    assert_declared_group_count_matches_the_matrix(mutated)


# --------------------------------------------------------------------------------------------
# M-04 — a negator that governs nothing may not defuse a creation.
#
# The M-02 repair scoped negation to the creation verb's own comma-delimited segment and then
# accepted *any* negator found there. Presence is not government: an unrelated negator suppressed
# a real creation, so `a second process group is created for the model without delay` — where
# `without` governs `delay` — read as a denial and the gate went green. Widening the window
# widened the defusal identically.
#
# These mutations go on `RUNNING -> CANDIDATE_READY`: a §3A row that names the cleanup handle
# nowhere and carries no byte-level pin, so the write dimension is silent by construction and the
# group cardinality is provably the only thing that can catch them.
# --------------------------------------------------------------------------------------------

CANDIDATE_READY_EDGE_MARKER = "immutable commit identity independently measured"

# A real second group, accompanied by a negator that speaks about something else. Each left the
# rejected gate fully green.
UNGOVERNED_NEGATION_CREATIONS = (
    (
        "negating preposition after the verb, governing its own object",
        ". A second controller-allocated process group is created for the model without delay",
    ),
    (
        "coordinated negative adjunct after the verb",
        ". A second controller-allocated process group is created for the model and not for"
        " preflight",
    ),
    (
        "preceding unrelated condition — `cannot` governs `proven`, not `created`",
        ". If cleanup cannot be proven a second controller-allocated process group is created here",
    ),
    (
        "post-verb `never` governing a different verb",
        ". A second controller-allocated process group is created here and never reused afterwards",
    ),
    (
        "`no` governing an unrelated noun earlier in the segment",
        ". With no further approval a second controller-allocated process group is created",
    ),
)


@pytest.mark.parametrize(
    "device,tail", UNGOVERNED_NEGATION_CREATIONS, ids=lambda value: value.replace(" ", "-")[:44]
)
def test_an_ungoverned_negator_no_longer_defuses_a_real_group_creation(
    device: str, tail: str
) -> None:
    """M-04's core proof, on the one dimension that can see these at all."""
    mutated = state_api_with_appended_prose(
        "| RUNNING |", CANDIDATE_READY_EDGE_MARKER, tail
    )

    assert_declared_write_point_matches_the_matrix(mutated)  # silent, by construction
    assert [
        f"{row[0]} -> {row[2]}" for row in attempt_rows_creating_an_owned_process_group(mutated)
    ] == ["CREATED -> STARTING", "RUNNING -> CANDIDATE_READY"], device

    with pytest.raises(AssertionError, match="create an owned process group"):
        assert_declared_group_count_matches_the_matrix(mutated)


def test_ungoverned_negation_and_same_row_multiplicity_compose() -> None:
    """The two blockers crossed: M-04's device used at M-03's placement.

    A repair for either one alone leaves this green — row-counting cannot see the placement, and
    segment-presence negation cannot see the creation — so it is the combination that proves both
    halves are really fixed.
    """
    mutated = state_api_with_appended_creating_edge_prose(
        ". A second controller-allocated process group is created for the model without delay"
    )

    assert [
        f"{row[0]} -> {row[2]}" for row in attempt_rows_creating_an_owned_process_group(mutated)
    ] == ["CREATED -> STARTING"]
    assert len(owned_process_group_creation_assertions(mutated)) == 2
    with pytest.raises(AssertionError, match="owned process group creations"):
        assert_declared_group_count_matches_the_matrix(mutated)


# Genuine denials. The first three are the load-bearing prose of the committed matrix, restated
# here at clause level; the rest are the ordinary ways a freeze document would deny a creation and
# must keep working, or the M-04 rule would just be "negation no longer counts".
GENUINE_CREATION_DENIALS = (
    "so this edge MUST NOT update, replace or clear the handle and no second group is created",
    "no owned process group has been created, proven by the handle being NULL",
    "A NULL handle means no group was ever created and cleanup is therefore proven",
    "the controller MUST NOT create a second process group for the model",
    "the controller never creates a second process group",
    "a second owned process group is never created on this edge",
    "a replacement workspace is provisioned without a new process group, reusing the existing one",
    "no second process group is created for the model process",
)


@pytest.mark.parametrize("clause", GENUINE_CREATION_DENIALS, ids=lambda value: value[:44])
def test_negation_that_governs_the_creation_still_denies_it(clause: str) -> None:
    """The false-positive controls for M-04, at clause level.

    Two directions of government are covered and both are needed. The negator may sit in the
    creation verb's own predication — its auxiliary chain (`MUST NOT create`, `is never created`)
    or the subject noun phrase that chain belongs to (`no second group is created`) — or it may
    deny the created group's noun phrase from outside its determiner (`without a new process
    group`). A rule with only the first direction loses the last case; a rule with only the second
    loses `MUST NOT create`.
    """
    assert not _asserts_a_group_creation(clause), clause


def test_the_negation_rule_is_government_not_proximity() -> None:
    """The M-04 rule stated as a property, so a later edit cannot regress it into a phrase list.

    The same negator, the same segment and nearly the same distance decide opposite ways purely on
    what the negator governs. That is the distinction the rejected gate did not draw.
    """
    # `cannot` governs `proven` in one and `create` in the other.
    assert _asserts_a_group_creation("if cleanup cannot be proven a second process group is created")
    assert not _asserts_a_group_creation("the controller cannot create a second process group")

    # `without` governs `delay` in one and the group's own noun phrase in the other.
    assert _asserts_a_group_creation("a second process group is created for the model without delay")
    assert not _asserts_a_group_creation("the model is relaunched without a second process group")

    # `never` governs `released` in one and `created` in the other.
    assert _asserts_a_group_creation("a second process group is created here and never released")
    assert not _asserts_a_group_creation("a second process group is never created here")

    # And the two walks are individually load-bearing, at the exact offsets the gate uses.
    assert _negation_governs_the_predication("the controller MUST NOT create a group", 30)
    assert not _negation_governs_the_predication(
        "if cleanup cannot be proven a second process group is created", 51
    )
    assert _negation_governs_the_noun_phrase("relaunched without a second process group", 27)
    assert not _negation_governs_the_noun_phrase(
        "a second process group is created without delay", 2
    )


def test_ambiguous_creation_semantics_fail_closed_rather_than_silent() -> None:
    """Requirement: where government is unclear, the creation stands and the gate goes red.

    A negator the walks cannot bind to the creation is treated as speaking about something else,
    which counts the creation — the direction that stops a freeze rather than passing one. The
    cost is recorded honestly: a genuine denial phrased so that the negator reaches the creation
    through neither constituent is over-counted, turning the gate red on prose that meant no harm.
    """
    # Negation of the *placement* rather than of the creation: the group is still asserted to
    # exist, so it is counted. Over-strict in the safe direction.
    assert _asserts_a_group_creation(
        "the model process is not placed into a newly created controller-allocated group"
    )
    # A negator separated from the creation by a whole intervening predication never binds.
    assert _asserts_a_group_creation(
        "the handle is not read here and a second process group is created"
    )


# --------------------------------------------------------------------------------------------
# M-05 — one predication can assert more than one event.
#
# The M-03 repair made both dimensions count assertions instead of rows, but it counted one write
# per operative write verb and one group per creation verb. English does not oblige a second verb
# for a second event: "two process groups are created" and "the handle is written twice" each say
# two while offering one verb, so both declared `1`s stayed satisfied and the gate stayed green.
#
# The mutations below are the two families, at their most dangerous placement — *rewriting* the
# legitimate prose of the real `CREATED -> STARTING` edge rather than appending to it, so §3A.3's
# declared count, §3A's prohibition sentence, the write-point identity and the number of rows are
# all left exactly as committed and the assertion count is the only thing that can object.
# --------------------------------------------------------------------------------------------

# The committed creation and the committed write, verbatim, as the substitution anchors.
COMMITTED_CREATION_PROSE = "the attempt's single owned process group is created"
COMMITTED_WRITE_PROSE = f"`{CLEANUP_HANDLE}` is committed"


def state_api_with_rewritten_prose(original: str, replacement: str) -> str:
    """The committed state API with one phrase of the `CREATED -> STARTING` cell rewritten.

    Rewriting rather than appending is what makes these mutations sharp: nothing is added for a
    row count or a clause count to notice, and the document still contains exactly one creation
    predicate and exactly one write predicate. Only the *number they assert* has changed.

    The substitution is confined to the §3A transition row, which is the only text either
    derivation reads; §3A.3's durable-fact table restates the same phrase and is deliberately left
    as committed, so the mutation cannot be credited to a disagreement between the two.
    """
    api = read(STATE_API)
    edge_lines = [
        line for line in api.splitlines()
        if line.startswith("| CREATED |") and CREATING_EDGE_MARKER in line
    ]
    assert len(edge_lines) == 1, edge_lines
    assert edge_lines[0].count(original) == 1, original
    mutated = api.replace(edge_lines[0], edge_lines[0].replace(original, replacement))
    assert mutated != api

    # Every other dimension of the gate must survive the rewrite, or the mutation proves nothing.
    assert "MUST NOT update, replace or clear `lease.owned_process_group_handle`" in mutated
    assert "| `attempt` (TASK or INTEGRATION) | 1 | `CREATED -> STARTING` |" in mutated
    return mutated


# Explicitly quantified creations. Each states a number the committed table does not declare.
QUANTIFIED_GROUP_CREATIONS = (
    ("cardinal word, plural noun, passive", "two process groups are created", 2),
    ("cardinal word, plural noun, active", "the controller creates two process groups", 2),
    ("numeral, plural noun", "2 process groups are created", 2),
    ("possessive, cardinal, plural noun", "the attempt's two owned process groups are created", 2),
    ("cardinal with a singular head noun", "the attempt's two owned process group records are"
     " created", 2),
    ("`both`, plural noun", "both owned process groups are created", 2),
    ("numeral, plural `cgroups`", "3 owned cgroups are created", 3),
)


@pytest.mark.parametrize(
    "device,replacement,count",
    QUANTIFIED_GROUP_CREATIONS,
    ids=lambda value: str(value).replace(" ", "-")[:44],
)
def test_an_explicitly_quantified_creation_is_counted_as_the_number_it_states(
    device: str, replacement: str, count: int
) -> None:
    """M-05's first family: one creation verb, more than one group.

    The row-level derivation is asserted unchanged on purpose — one creating row, still the edge
    §3A.3 names — because that is precisely what these mutations leave intact. Only the count of
    groups moves, and that is the number §3A.3 actually declares.
    """
    mutated = state_api_with_rewritten_prose(COMMITTED_CREATION_PROSE, replacement)

    assert [
        f"{row[0]} -> {row[2]}" for row in attempt_rows_creating_an_owned_process_group(mutated)
    ] == ["CREATED -> STARTING"], f"{device}: the mutation was not confined to one row"
    assert len(owned_process_group_creation_assertions(mutated)) == count, device

    with pytest.raises(AssertionError, match="owned process group creations"):
        assert_declared_group_count_matches_the_matrix(mutated)


# Creations that assert a plurality without naming a number. The count is not derivable, so the
# gate must say so rather than read the prose as one.
UNQUANTIFIED_GROUP_CREATIONS = (
    ("bare plural, no quantifier at all", "process groups are created"),
    ("indefinite plural quantifier", "several owned process groups are created"),
    ("definite article with a plural noun", "the attempt's owned process groups are created"),
    ("indefinite quantifier, active voice", "the controller creates additional process groups"),
    # A partitive puts the number outside the noun phrase's own determiner, where the walk stops.
    # The count is therefore unknown rather than two — red either way, by the honest route.
    ("partitive, number outside the determiner",
     "both of the attempt's owned process groups are created"),
)


@pytest.mark.parametrize(
    "device,replacement", UNQUANTIFIED_GROUP_CREATIONS, ids=lambda value: value.replace(" ", "-")[:44]
)
def test_a_creation_that_will_not_say_how_many_fails_closed(device: str, replacement: str) -> None:
    """The fail-closed half of M-05's first family.

    A plural creation whose number is unstated is not evidence of one group; it is evidence the
    gate cannot count. Reading it as one is exactly the collapse M-05 is about, so the derivation
    refuses to produce a number and the freeze stops.
    """
    mutated = state_api_with_rewritten_prose(COMMITTED_CREATION_PROSE, replacement)

    with pytest.raises(AssertionError, match="without saying how many"):
        owned_process_group_creation_assertions(mutated)
    with pytest.raises(AssertionError, match="without saying how many"):
        assert_declared_group_count_matches_the_matrix(mutated)


# The same defect at the other placement: a *second* creation phrased in the plural. Before the
# repair `GROUP_NOUN_RE` matched no plural at all, so these added no creation whatever — the
# group dimension was blind to every plural second group, on every row.
PLURAL_SECOND_CREATIONS = (
    ("cardinal, plural noun", ". Two further controller-allocated process groups are created", 3),
    ("cardinal, plural noun, active", ". The controller creates two further process groups here", 3),
    ("cardinal, plural `cgroups`", ". Two further controller-allocated cgroups are created here", 3),
)


@pytest.mark.parametrize(
    "device,tail,count", PLURAL_SECOND_CREATIONS, ids=lambda value: str(value).replace(" ", "-")[:44]
)
def test_a_plural_second_creation_is_visible_to_the_group_dimension(
    device: str, tail: str, count: int
) -> None:
    """Placed on `RUNNING -> CANDIDATE_READY`, which names the handle nowhere.

    The write dimension is therefore silent by construction and the group cardinality is provably
    the only guard — the same division of labour M-04's mutations rely on.
    """
    mutated = state_api_with_appended_prose("| RUNNING |", CANDIDATE_READY_EDGE_MARKER, tail)

    assert_declared_write_point_matches_the_matrix(mutated)  # silent, by construction
    assert len(owned_process_group_creation_assertions(mutated)) == count, device
    with pytest.raises(AssertionError, match="create an owned process group"):
        assert_declared_group_count_matches_the_matrix(mutated)


def test_a_plural_group_noun_is_recognised_at_all() -> None:
    """The root of the blind spot, pinned directly so it cannot silently return.

    `process groups`, `cgroups` and `groups` matched nothing, which is why a plural creation was
    not merely miscounted — it was not a creation. Singular forms must keep matching unchanged.
    """
    for plural in ("process groups", "process-groups", "cgroups", "groups"):
        assert GROUP_NOUN_RE.findall(plural) == [plural], plural
    for singular in ("process group", "cgroup", "group"):
        assert GROUP_NOUN_RE.findall(singular) == [singular], singular

    assert _asserts_a_group_creation("two process groups are created")
    assert not _asserts_a_group_creation("no further process groups are created")


# --------------------------------------------------------------------------------------------
# M-06 — an ordinary adjective is not a quantifier.
#
# The M-05 walk stopped at the first `_SINGULAR_QUANTIFIERS` member it met and reported one. That
# set contained `new` and `existing`, which are not quantifiers at all: they say *which* groups,
# never how many. So `two new process groups are created` stopped on `new`, returned one, and
# never read the `two` sitting immediately beside it. Written over the one clause that legitimately
# creates the attempt's group, that keeps the number of creating *rows* at one and the declared
# cardinality at one, so the asserted count was the only guard — and it was wrong.
#
# These mutations rewrite the committed `CREATED -> STARTING` creation clause rather than appending
# a sentence, exactly so the row-counting dimension cannot answer for the count. All of them were
# GREEN at `7f92215`.
# --------------------------------------------------------------------------------------------
QUANTIFIED_MODIFIER_CREATIONS = (
    ("cardinal before `new`", "two new process groups are created", 2),
    ("cardinal before `existing`", "three existing process groups are created", 3),
    ("cardinal before `new`, bare noun", "two new groups are provisioned", 2),
    ("cardinal before `new`, `cgroups`", "two new cgroups are created", 2),
    ("numeral before `new`", "2 new process groups are created", 2),
    ("`both` before `new`", "both new process groups are created", 2),
    ("cardinal before two modifiers", "three new same process groups are created", 3),
)


@pytest.mark.parametrize(
    "device,replacement,count",
    QUANTIFIED_MODIFIER_CREATIONS,
    ids=lambda value: str(value).replace(" ", "-")[:44],
)
def test_an_explicit_cardinal_outranks_a_non_quantifying_modifier(
    device: str, replacement: str, count: int
) -> None:
    """M-06. The number the prose states is read even when an adjective stands between it and
    the noun it governs.

    The row dimension is asserted to be satisfied first, because it is: exactly one §3A edge still
    creates, and §3A.3 still declares one. The count is the whole of the guard here.
    """
    mutated = state_api_with_rewritten_prose(COMMITTED_CREATION_PROSE, replacement)

    creating = attempt_rows_creating_an_owned_process_group(mutated)
    assert [f"{row[0]} -> {row[2]}" for row in creating] == ["CREATED -> STARTING"], (
        f"{device}: the mutation was not confined to the one committed creating row"
    )
    assert len(owned_process_group_creation_assertions(mutated)) == count, device

    with pytest.raises(AssertionError, match=f"asserts {count} owned process group creations"):
        assert_declared_group_count_matches_the_matrix(mutated)


# The same family with the plurality asserted but unquantified. `new`/`existing` used to collapse
# these to one as well, which is worse than over-counting: an unknown critical cardinality must be
# a red gate, not an assumed one.
UNQUANTIFIED_MODIFIER_CREATIONS = (
    ("`several` before `new`", "several new process groups are created"),
    ("`multiple` before `existing`", "multiple existing process groups are created"),
    ("`the same` plus plural", "the same process groups are created"),
    ("bare plural behind `new`", "new process groups are created"),
    ("bare plural behind `existing`", "existing cgroups are created"),
)


@pytest.mark.parametrize(
    "device,replacement",
    UNQUANTIFIED_MODIFIER_CREATIONS,
    ids=lambda value: str(value).replace(" ", "-")[:44],
)
def test_a_modifier_cannot_collapse_an_unstated_plurality_to_one(
    device: str, replacement: str
) -> None:
    """The fail-closed half of M-06, on the same clause and the same row."""
    mutated = state_api_with_rewritten_prose(COMMITTED_CREATION_PROSE, replacement)

    with pytest.raises(AssertionError, match="without saying how many"):
        owned_process_group_creation_assertions(mutated)
    with pytest.raises(AssertionError, match="without saying how many"):
        assert_declared_group_count_matches_the_matrix(mutated)


# The direction that must not move. Every one of these genuinely asserts one group, and the freeze
# set has to keep passing on prose of exactly this shape.
SINGULAR_CREATIONS_THAT_MUST_STILL_PASS = (
    ("determiner plus `new`", "a new process group is created"),
    ("determiner plus `existing`", "the existing owned process group is created"),
    ("determiner plus ordinal", "a second owned process group is created"),
    ("`another` plus `new`", "another new process group is created"),
    ("cardinal `one` plus `new`", "one new process group is created"),
    ("`single` plus `new`", "the single new process group is created"),
    ("`the same` plus singular", "the same process group is created"),
    ("possessive plus `new`", "the attempt's new owned process group is created"),
)


@pytest.mark.parametrize(
    "device,replacement",
    SINGULAR_CREATIONS_THAT_MUST_STILL_PASS,
    ids=lambda value: str(value).replace(" ", "-")[:44],
)
def test_prose_that_genuinely_asserts_one_group_still_passes(device: str, replacement: str) -> None:
    """The false-positive control for M-06.

    A cardinality gate that reddens on ordinary singular prose is unmaintainable, and a repair
    that bought its catches that way would be traded straight back at the next freeze-doc edit.
    """
    mutated = state_api_with_rewritten_prose(COMMITTED_CREATION_PROSE, replacement)

    assert len(owned_process_group_creation_assertions(mutated)) == 1, device
    assert_declared_group_count_matches_the_matrix(mutated)
    assert_declared_write_point_matches_the_matrix(mutated)


def test_a_number_is_never_stolen_from_the_phrase_next_door() -> None:
    """The bound on M-06's repair: a cardinal counts only for the noun it premodifies.

    Letting the walk see past `new` is only safe while it still stops where the noun phrase does.
    A bare plural word cannot premodify a head in this prose, so meeting one means the walk has
    crossed into the subject phrase — and the number found there is not this phrase's number.
    Every case below therefore reads *unknown*, which is red, rather than a borrowed number.
    """
    for clause in (
        "two attempts create new process groups",
        "two attempts create process groups",
        "three leases provision existing cgroups",
        "after two failures new process groups are created",
    ):
        assert [count for _, count in group_creations(clause)] == [None], clause

    # The stop is on the plural word, not on distance: a possessive is a premodifier and the walk
    # survives it, while a determiner still ends the phrase and still answers one.
    assert group_creations("the attempt's two new owned process groups are created")[0][1] == 2
    assert group_creations("two leases each create a new process group")[0][1] == 1


def test_new_and_existing_are_not_treated_as_quantifiers() -> None:
    """M-06 stated as a property of the vocabulary, so a later edit cannot re-add them.

    The distinction is the whole repair: `_SINGULAR_QUANTIFIERS` members pin a phrase at one and
    may end the walk; `_NON_QUANTIFYING_MODIFIERS` members say nothing about number and may not.
    """
    assert not (_SINGULAR_QUANTIFIERS & _NON_QUANTIFYING_MODIFIERS)
    for modifier in ("new", "existing", "same"):
        assert modifier in _NON_QUANTIFYING_MODIFIERS
        assert modifier not in _SINGULAR_QUANTIFIERS, modifier
        assert _as_cardinal(modifier) is None, modifier

    # Both kinds of modifier are transparent to a stated number — that is M-06 — but they differ
    # where no number is stated: a singular quantifier still asserts one, `new` asserts nothing.
    assert group_creations("two new process groups are created")[0][1] == 2
    assert group_creations("two single process groups are created")[0][1] == 2
    assert group_creations("the single process group is created")[0][1] == 1
    assert group_creations("new process groups are created")[0][1] is None


# Explicitly repeated writes. One operative verb, more than one write event.
REPEATED_HANDLE_WRITES = (
    ("adverb `twice`", f"`{CLEANUP_HANDLE}` is written twice", 2),
    ("cardinal word plus `times`", f"`{CLEANUP_HANDLE}` is committed two times", 2),
    ("three times", f"`{CLEANUP_HANDLE}` is written three times", 3),
    ("numeral plus `times`", f"`{CLEANUP_HANDLE}` is committed 2 times", 2),
    ("preposed adverb", f"`{CLEANUP_HANDLE}` is twice committed", 2),
    ("prepositional repetition phrase", f"`{CLEANUP_HANDLE}` is committed on two occasions", 2),
)


@pytest.mark.parametrize(
    "device,replacement,count",
    REPEATED_HANDLE_WRITES,
    ids=lambda value: str(value).replace(" ", "-")[:44],
)
def test_an_explicitly_repeated_write_is_counted_as_the_number_it_states(
    device: str, replacement: str, count: int
) -> None:
    """M-05's second family: one write verb, more than one write point.

    §3A.3 declares a number of write *points*. A verb carrying its own repetition adverbial
    asserts that many, and the row, the clause and the verb all stay at one — which is why every
    earlier dimension of the gate is asserted here to still be satisfied.
    """
    mutated = state_api_with_rewritten_prose(COMMITTED_WRITE_PROSE, replacement)

    assert [
        f"{row[0]} -> {row[2]}" for row in attempt_rows_writing_the_cleanup_handle(mutated)
    ] == ["CREATED -> STARTING"], f"{device}: the mutation was not confined to one row"
    assert len(cleanup_handle_write_assertions(mutated)) == count, device

    with pytest.raises(AssertionError, match=f"asserts {count} writes of the cleanup handle"):
        assert_declared_write_point_matches_the_matrix(mutated)


# Repetition asserted without a number. Unknown cardinality on the write point is a red gate.
UNQUANTIFIED_HANDLE_WRITES = (
    ("bare `repeatedly`", f"`{CLEANUP_HANDLE}` is written repeatedly"),
    ("`more than once`", f"`{CLEANUP_HANDLE}` is written more than once"),
    ("`again` after the verb", f"`{CLEANUP_HANDLE}` is committed and then written again"),
    ("`several times`", f"`{CLEANUP_HANDLE}` is written several times"),
)


@pytest.mark.parametrize(
    "device,replacement", UNQUANTIFIED_HANDLE_WRITES, ids=lambda value: value.replace(" ", "-")[:44]
)
def test_a_repeated_write_that_will_not_say_how_many_fails_closed(
    device: str, replacement: str
) -> None:
    """The fail-closed half of M-05's second family.

    An unknown write count is handled the way this classifier already handles every other handle
    wording it cannot resolve: `UNCLASSIFIED`, and the gate stops rather than guessing one.
    """
    mutated = state_api_with_rewritten_prose(COMMITTED_WRITE_PROSE, replacement)

    with pytest.raises(AssertionError, match="cannot classify"):
        assert_declared_write_point_matches_the_matrix(mutated)


def test_semantic_cardinality_is_read_from_the_prose_not_from_the_verb_count() -> None:
    """M-05 stated as a property, so a later edit cannot regress it into a phrase list.

    Each pair holds the number of verbs constant and changes only the number the prose states.
    If a future gate went back to counting predicates, both halves of every pair would agree
    again — which is the failure this test exists to make loud.
    """
    # One creation verb, one group versus two.
    assert group_creations("the attempt's single owned process group is created")[0][1] == 1
    assert group_creations("two owned process groups are created")[0][1] == 2

    # One write verb, one write versus two.
    assert _classify_handle_clause(
        f"`{CLEANUP_HANDLE}` is committed here", established=True
    ) == (WRITES, 1)
    assert _classify_handle_clause(
        f"`{CLEANUP_HANDLE}` is committed twice here", established=True
    ) == (WRITES, 2)

    # Unknown is neither: it is a refusal, on both dimensions.
    assert group_creations("owned process groups are created")[0][1] is None
    assert _classify_handle_clause(
        f"`{CLEANUP_HANDLE}` is written repeatedly", established=True
    ) == (UNCLASSIFIED, 0)


# Prose that legitimately contains numbers, plurals or repetition words near the machinery M-05
# added. If any of these moved a count, the repair would have turned quantity into a tripwire.
LEGITIMATE_QUANTIFIED_PROSE = (
    (
        "plural creations of things that are not process groups",
        ". Two further fencing tokens are created and several leases are established",
    ),
    (
        "a plurality of groups explicitly denied",
        ". No further process groups are created on this edge",
    ),
    (
        "a back-reference to the one committed group",
        ". Preflight runs inside the attempt's single owned process group throughout",
    ),
    (
        "a number that counts commits rather than writes",
        ". `attempt.workspace_epoch` is written in this same commit as the workspace"
        " discriminator alone, and MUST NOT be used as the cleanup handle",
    ),
)


@pytest.mark.parametrize(
    "device,tail", LEGITIMATE_QUANTIFIED_PROSE, ids=lambda value: value.replace(" ", "-")[:44]
)
def test_counting_semantic_cardinality_leaves_legitimate_quantified_prose_green(
    device: str, tail: str
) -> None:
    """The false-positive controls for M-05, through both dimensions of the gate."""
    mutated = state_api_with_appended_prose("| RUNNING |", CANDIDATE_READY_EDGE_MARKER, tail)
    assert_declared_write_point_matches_the_matrix(mutated)
    assert_declared_group_count_matches_the_matrix(mutated)


def test_a_single_write_and_a_single_creation_still_read_as_one() -> None:
    """The pristine calibration for M-05, restated at clause level.

    The committed write clause is the case the repair had to leave alone: `is committed` is
    followed by `**before**`, which begins a *different* constituent, and the `single` two words
    later belongs to the group's noun phrase, not to the verb. A repetition rule based on presence
    in the segment rather than government would have read one of them and counted two.
    """
    api = read(STATE_API)
    assert len(cleanup_handle_write_assertions(api)) == 1
    assert len(owned_process_group_creation_assertions(api)) == 1

    write_clause = (
        "This is the only edge that may write the cleanup handle:"
        f" `{CLEANUP_HANDLE}` is committed **before** the attempt's single owned"
        " process group is created (§3A.3), and preflight runs inside that group"
    )
    assert write_clause in api
    assert _classify_handle_clause(write_clause, established=True) == (WRITES, 1)
    assert [count for _verb, count in group_creations(write_clause)] == [1]

    # `once` is a repetition adverbial too, and it states one.
    assert _classify_handle_clause(
        f"`{CLEANUP_HANDLE}` is committed once", established=True
    ) == (WRITES, 1)


def test_the_cardinality_blind_spots_are_stated_rather_than_assumed_closed() -> None:
    """Honest scope for M-05, carried forward for the next review.

    The repair reads the quantifiers and repetition adverbials English actually uses in this
    prose. It does not parse arithmetic, coordination or elision, and those limits are recorded
    here rather than left for a reviewer to rediscover.
    """
    # Coordination of two noun phrases under one verb is counted once, from the larger phrase.
    assert group_creations("a preflight group and a model group are created")[0][1] == 1
    # An elided second predicate ("as is ...") carries no verb of its own and is not counted.
    assert len(group_creations("the attempt's single owned process group is created, as is a"
                               " second process group")) == 1
    # Repetition nouns other than time/occasion are not read as repetition.
    assert _classify_handle_clause(
        f"`{CLEANUP_HANDLE}` is written in two batches", established=True
    ) == (WRITES, 1)
    # All three are under-counts, so each is a way for a future edit to be missed — not a way for
    # one to be wrongly rejected. None of them is reachable in the committed prose.


# --------------------------------------------------------------------------------------------
# J-01 — durable resource occupancy when cleanup is unproven.
# --------------------------------------------------------------------------------------------


OCCUPANCY_HEADER = "| Record | Occupies | While |"
RELEASE_HEADER = "| Cleanup-unproven record | Release transition | Precondition for the release |"

# The exact accounting rules that made a terminal record release its unit. These are positive
# claims in the rejected tree, so their absence is checkable — and unlike a prose blacklist each
# one is paired below with a derived check that fails if the rule returns in another wording.
RELEASE_BY_TERMINALITY = (
    "The reviewer-concurrency ceiling is enforced against non-terminal `review_dispatch` rows",
    "the implementation/integration concurrency ceilings against non-terminal `attempt` rows",
    "a terminal subject MUST NOT continue to occupy a slot, a lease or a concurrency unit",
    "the freed slot is immediately reusable",
    "so they are immediately reusable",
)


def occupancy_rules() -> dict[str, tuple[str, str]]:
    """§3D's occupancy table as `{record: (resources occupied, while-condition)}`."""
    return {row[0]: (row[1], row[2]) for row in table_rows_under_header(STATE_API, OCCUPANCY_HEADER)}


def release_rules() -> dict[str, tuple[str, str]]:
    """§3D's release table as `{cleanup-unproven record: (transition, precondition)}`."""
    return {row[0]: (row[1], row[2]) for row in table_rows_under_header(STATE_API, RELEASE_HEADER)}


def dispatch_state_enum() -> frozenset[str]:
    """The `review_dispatch.state` enum, read from the record schema rather than from prose."""
    block = review_dispatch_block()
    line = next(line for line in block.splitlines() if line.startswith("- state `"))
    return frozenset(line.split("`")[1].split("|"))


def test_a_cleanup_unproven_dispatch_cannot_be_represented_as_ordinary_fenced() -> None:
    """J-01's root cause: `FENCED` carried both the clean and the orphan outcome.

    §6 reaches a terminal dispatch on both paths, so if the enum offers one terminal state for
    both, committed durable state cannot answer "may a reviewer process still be alive?" — and
    every occupancy rule built on terminality is then unsound by construction.
    """
    enum = dispatch_state_enum()
    assert "QUARANTINED" in enum, (
        "`review_dispatch` has no cleanup-unproven terminal state; `FENCED` is overloaded again"
    )
    assert "FENCED" in enum and enum >= {"DISPATCHED", "COMPLETED", "CANCELLED", "EXPIRED"}, enum

    block = review_dispatch_block()
    assert "`FENCED` means authority is revoked **and** kernel-owned cleanup is proven" in block
    assert "cleanup is **not** proven" in block
    # An external reviewer is fencing-only by virtue of its principal; it must not be swept into
    # quarantine, or it would hold a reviewer unit for ever on cleanup grounds it can never meet.
    assert "An `EXTERNAL` dispatch never reaches `QUARANTINED`" in block

    # §3B must route the unprovable-cleanup outcome to QUARANTINED, not to FENCED.
    rows = table_rows_in_numbered_section(STATE_API, "3B")
    unproven = [
        row for row in rows
        if len(row) >= 3 and row[0] == "DISPATCHED" and "cannot be proven stopped" in row[1]
    ]
    assert len(unproven) == 1, unproven
    assert unproven[0][2].startswith("QUARANTINED"), (
        f"the unprovable-cleanup dispatch edge still lands on {unproven[0][2]!r}"
    )
    assert "a single state cannot carry both facts" in unproven[0][3]

    # And the clean FENCED edge must say it is the proven path, so the two cannot drift together.
    clean = [row for row in rows if len(row) >= 3 and row[0] == "DISPATCHED" and row[2] == "FENCED"]
    assert len(clean) == 1, clean
    assert "admissible only on the **cleanup-proven** path" in clean[0][3]


def test_durable_occupancy_counts_cleanup_unproven_terminal_records() -> None:
    """§3D must define occupancy over committed rows, including terminal quarantined ones."""
    occupancy = occupancy_rules()
    assert len(occupancy) == 3, sorted(occupancy)

    dispatch = occupancy["`review_dispatch`"]
    assert "reviewer-concurrency unit" in dispatch[0]
    assert "required-review slot" in dispatch[0]
    assert "**global**" in dispatch[0], "the reviewer ceiling is per-subject, so a sibling escapes it"
    assert "`DISPATCHED`" in dispatch[1] and "`QUARANTINED`" in dispatch[1], dispatch[1]

    for kind in ("TASK", "INTEGRATION"):
        occupies, while_ = occupancy[f"`attempt` with `subject_kind = {kind}`"]
        assert "concurrency unit" in occupies and "`lease`" in occupies
        assert "`CLOSED / QUARANTINED`" in while_, while_
        assert "has not yet been durably retired" in while_, while_
        for state in ("CREATED", "STARTING", "RUNNING", "CANDIDATE_READY"):
            assert f"`{state}`" in while_, f"{kind} occupancy omits non-terminal state {state}"

    section = numbered_section_text(STATE_API, "3D")
    assert "**Terminality MUST NOT imply release.**" in section
    assert "pure function of committed records" in section
    # Restart must not be able to release a unit, which is the whole point of durability here.
    assert "Controller restart, DB restore and controller-epoch change therefore cannot release" in (
        section
    )
    # Budget and occupancy stay separate in both directions (R-02 / §3A.2 preservation).
    assert "Neither MUST be derived from the other." in section


def test_the_release_transition_exists_and_requires_proven_emptiness() -> None:
    """Occupancy must end at a named transition gated on proof, never by decay or by terminality."""
    release = release_rules()
    assert len(release) == 2, sorted(release)

    dispatch_transition, dispatch_precondition = release["`review_dispatch` `QUARANTINED`"]
    assert "`QUARANTINED -> FENCED`" in dispatch_transition
    assert "proven empty" in dispatch_precondition
    assert "authority-terminal" in dispatch_precondition
    assert "`FENCE_STALE`" in dispatch_precondition, (
        "the release does not say stale verdicts stay inadmissible across it"
    )

    attempt_transition, attempt_precondition = release["`attempt` `CLOSED / QUARANTINED`"]
    assert f"`{CLEANUP_HANDLE}`" in attempt_transition
    assert "proven empty" in attempt_precondition
    assert "terminal disposition is **not** rewritten" in attempt_precondition, (
        "releasing occupancy rewrites the disposition, which would corrupt the §3A.2 budget"
    )
    assert "no relaunch" in attempt_precondition, "the release invents a relaunch path"

    section = numbered_section_text(STATE_API, "3D")
    assert "MUST NOT revive result authority" in section
    assert "MUST be committed **before or in the same transaction as** the release" in section

    # §3B must actually carry the dispatch release edge, and it must be the only edge out of a
    # terminal dispatch state.
    rows = table_rows_in_numbered_section(STATE_API, "3B")
    from_terminal = [row for row in rows if len(row) >= 3 and row[0] in DISPATCH_TERMINAL]
    assert len(from_terminal) == 1, from_terminal
    assert from_terminal[0][0] == "QUARANTINED" and from_terminal[0][2] == "FENCED", from_terminal
    assert "proves the owned reviewer process group empty" in from_terminal[0][1]
    assert "It restores nothing" in from_terminal[0][3]

    # `controller.reconcile` is the command that commits it, so the release has an owner.
    reconcile = next(
        line for line in read(STATE_API).splitlines() if line.startswith("| `controller.reconcile`")
    )
    assert "§3D release transition" in reconcile and "no relaunch" in reconcile


def test_freeze_contract_ceilings_count_exactly_the_occupying_rows() -> None:
    """FC §19 is where J-01 actually bit: it counted non-terminal rows, so step 7 released.

    This binds §19 to the §3D states rather than to a paraphrase, and it is the mutation case the
    review asked for: a §19 amended back to "non-terminal rows only", or amended to release at §6
    step 7, fails here.
    """
    section = numbered_section_text(FREEZE_CONTRACT, "19")

    assert "defined once, normatively, by `ORCHESTRATOR_V1_STATE_API.md` §3D" in section
    assert "MUST NOT restate it differently" in section
    assert "non-terminal execution records **plus cleanup-unproven terminal records**" in section

    # The reviewer bullet must name *exactly* the dispatch states §3D declares as occupying. This
    # is the derived form of the check: amending §19 back to "non-terminal rows" drops
    # `QUARANTINED` from the bullet, and set equality sees that without knowing the new wording.
    reviewer_bullet = next(
        line for line in section.splitlines()
        if line.startswith("- the **reviewer-concurrency** ceiling")
    )
    declared = frozenset(re.findall(r"`([A-Z_]+)`", occupancy_rules()["`review_dispatch`"][1]))
    assert declared == {"DISPATCHED", "QUARANTINED"}, declared
    assert frozenset(re.findall(r"`([A-Z_]+)`", reviewer_bullet)) == declared, (
        f"§19's reviewer ceiling counts {sorted(re.findall(r'`([A-Z_]+)`', reviewer_bullet))}, "
        f"but §3D declares {sorted(declared)} as occupying"
    )
    assert "global" in reviewer_bullet, "a per-subject reviewer ceiling lets a sibling exceed N"

    execution_bullet = next(
        line for line in section.splitlines()
        if line.startswith("- the **implementation-concurrency**")
    )
    assert "non-terminal" in execution_bullet
    assert "disposition `QUARANTINED` whose `lease.owned_process_group_handle`" in execution_bullet
    assert "has not yet been durably retired" in execution_bullet

    # No sentence of §19 may scope a ceiling to non-terminal rows on its own. A reintroduced
    # "enforced against non-terminal rows" fails here whatever else the section still says.
    for sentence in re.split(r"(?<=[.;])\s+", section):
        if "non-terminal" not in sentence:
            continue
        assert any(
            marker in sentence
            for marker in ("QUARANTINED", "specification error", "cleanup-unproven")
        ), f"§19 scopes a ceiling to non-terminal rows alone: {sentence.strip()[:120]!r}"

    # The two mutations the gate must catch, stated as prohibitions §19 itself carries.
    assert "Terminality MUST NOT be read as release." in section
    assert "enforcing any of these ceilings against non-terminal rows alone is a specification error" in (
        section
    )

    # §6 must still order release at step 6 and retention at step 7 — the other half of the mutation.
    cancellation = numbered_section_text(STATE_API, "6")
    assert "at step 6 **and never at step 7**" in cancellation
    step_seven = cancellation.split("\n7. ", 1)[1].split("\n\n", 1)[0]
    assert "QUARANTINED" in step_seven and "cleanup-unproven" in step_seven
    assert "FENCED" not in step_seven, (
        "§6 step 7 still produces the cleanup-proven representation for a dispatch"
    )


@pytest.mark.parametrize("path", FREEZE_SET, ids=lambda p: p.name)
def test_no_document_releases_a_resource_on_terminality_alone(path: Path) -> None:
    """No freeze document may keep a statement that contradicts quarantine occupancy."""
    text = read(path)
    for wording in RELEASE_BY_TERMINALITY:
        assert wording not in text, (
            f"{path.name} still releases a resource on terminality alone: {wording!r}"
        )


def test_per_slot_uniqueness_and_admission_treat_quarantine_as_occupied() -> None:
    """A replacement for a quarantined slot is the exact failure H-04 was reopened by."""
    block = review_dispatch_block()
    assert "restricted to the rows §3D counts as **occupying** that slot" in block
    assert "every `DISPATCHED` row and every `QUARANTINED` row" in block
    assert "Restricting it to non-terminal rows alone would admit a replacement" in block

    # The admission edge itself must refuse, rather than relying on the constraint alone.
    rows = table_rows_in_numbered_section(STATE_API, "3B")
    create = [row for row in rows if len(row) >= 3 and row[0] == "none" and row[2] == "DISPATCHED"]
    assert len(create) == 1, create
    cell = create[0][3]
    assert "no other dispatch occupies this required-review slot under §3D" in cell
    assert "a replacement for a quarantined slot is refused" in cell
    assert "past the freeze contract §19 ceiling" in cell, (
        "dispatch admission checks the slot but not the global reviewer ceiling"
    )

    section = numbered_section_text(STATE_API, "3D")
    assert "**per-slot uniqueness counts quarantine.**" in section
    assert "**global reviewer concurrency counts quarantine.**" in section
    assert "at most N-1 further reviewers may be admitted across all subjects" in section
    # §21 reconciliation must not be the back door that replaces a quarantined slot.
    step_eight = numbered_section_text(FREEZE_CONTRACT, "21")
    step_eight = step_eight.split("8. reconcile", 1)[1].split("\n9. ", 1)[0]
    assert "whose §3D occupancy has been released" in step_eight
    assert "gets neither a replacement nor a silent release" in step_eight


def test_attempt_occupancy_counts_quarantined_without_touching_the_budget() -> None:
    """The single implementation slot must not be handed on merely because the row is terminal."""
    section = numbered_section_text(STATE_API, "3D")
    assert "**the single implementation slot and the integration ceilings count quarantine.**" in (
        section
    )
    assert "no second task may start while that attempt's owned group may still exist" in section
    assert "MUST NOT take that capacity merely because the attempt row is terminal" in section

    # Both §3A quarantine edges must say the row keeps occupying, not just that it is terminal.
    rows = table_rows_in_numbered_section(STATE_API, "3A")
    quarantines = [
        row for row in rows
        if len(row) >= 4 and row[0] in {"STARTING", "RUNNING"} and row[2] == "CLOSED / QUARANTINED"
    ]
    assert {row[0] for row in quarantines} == {"STARTING", "RUNNING"}, [r[0] for r in quarantines]
    for row in quarantines:
        assert "§3D" in row[3], f"the {row[0]} quarantine edge says nothing about occupancy"
        assert "retired" in row[3], f"the {row[0]} quarantine edge names no release condition"

    # R-02: occupancy and budget stay separate, in both directions.
    ceiling = numbered_section_text(STATE_API, "3A").split("### 3A.2", 1)[1].split("### 3A.3", 1)[0]
    assert "**Budget consumption is not resource occupancy.**" in ceiling
    assert "Releasing occupancy under §3D MUST NOT decrement this ceiling" in ceiling
    assert "MUST NOT be taken as evidence that a resource was released" in ceiling


def acceptance_rows() -> dict[str, list[str]]:
    """Every acceptance row of the matrix, keyed by test ID.

    `table_rows_under_header` stops at the first table, and the matrix repeats the same header in
    every numbered section, so the resource-ceiling rows of §14B are unreachable through it.
    """
    rows: dict[str, list[str]] = {}
    for line in read(ACCEPTANCE_MATRIX).splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if cells and re.fullmatch(r"[A-Z]{2,4}-\d{2}", cells[0]):
            rows[cells[0]] = cells
    assert rows, "no acceptance rows parsed"
    return rows


def test_acceptance_covers_both_occupancy_ceilings_and_their_release() -> None:
    """RS-03/RS-04 must exercise the ceilings, the refusals and the release, not just assert prose."""
    rows = acceptance_rows()

    rs03 = " ".join(rows["RS-03"])
    assert "global reviewer-concurrency ceiling to N" in rs03
    assert "a reviewer for a **different** subject is refused" in rs03
    assert "same** required-review slot is refused" in rs03
    assert "`QUARANTINED -> FENCED` commits **before** the unit or the slot becomes usable" in rs03
    assert "**EXTERNAL arm:**" in rs03 and "never reaches `QUARANTINED`" in rs03
    assert "**Clean-path arm:**" in rs03

    rs04 = " ".join(rows["RS-04"])
    assert "one** implementation slot" in rs04
    assert "`CLOSED / QUARANTINED`" in rs04
    assert "admission for task B is refused" in rs04
    assert "terminality of the row is asserted not to be sufficient" in rs04
    assert "no result from task A's quarantined attempt regains authority" in rs04
    assert "§10.3.1 execution-attempt budget is unchanged by the release" in rs04

    # ST-13/ST-17 carry the same distinction at the points the review named.
    assert "keeps both occupied under" in " ".join(rows["ST-13"])
    st17 = " ".join(rows["ST-17"])
    assert "the same fresh-dispatch probe is asserted to be **refused**" in st17
    assert "a state distinct from `FENCED`" in st17


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
