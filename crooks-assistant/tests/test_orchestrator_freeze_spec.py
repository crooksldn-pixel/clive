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

    api = read(STATE_API)
    assert "CREATED | `task.cancel` / `integration.cancel`" in api
    assert "STARTING | `task.cancel` / `integration.cancel`" in api
    assert "STARTING | cancellation/fencing event where a preflight process group cannot be proven stopped" in api


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
# Regression guards for the previously validated N-series repairs.
# --------------------------------------------------------------------------------------------


def test_traceability_dispositions_every_reviewed_finding() -> None:
    """Silence is not a disposition: N-01..N-04 and B-01..B-05 each carry an explicit row."""
    text = read(TRACEABILITY)
    assert "Silence is not a disposition." in text
    for finding in ("N-01", "N-02", "N-03", "N-04", "B-01", "B-02", "B-03", "B-04", "B-05", "R-01", "R-02", "R-03", "F-01", "F-02", "F-03", "G-01", "G-02", "G-03"):
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
