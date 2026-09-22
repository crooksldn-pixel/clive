"""Reviewer routing: the refusals, each one isolated.

Every test that asserts a refusal follows it with a load-bearing control —
repair that one thing, change nothing else, and watch the same assignment
become eligible. Without the control a refusal proves only that something was
wrong, not that the rule under test is the thing that noticed.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.orchestrator.routing import (
    Ineligibility,
    Party,
    Principal,
    PrincipalKind,
    ReviewAssignment,
    SessionContext,
    Workspace,
    evaluate_review_eligibility,
    select_eligible_reviewer,
)

CANDIDATE = "a" * 40
OTHER_SHA = "b" * 40
NOW = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)


def party(
    principal_id: str,
    session_id: str,
    workspace_id: str,
    *,
    read_only: bool,
    model_family: str = "claude-opus-5",
    context_is_fresh: bool = True,
    head_sha: str = CANDIDATE,
    clean: bool = True,
) -> Party:
    return Party(
        principal=Principal(
            principal_id=principal_id, kind=PrincipalKind.MODEL, model_family=model_family
        ),
        session=SessionContext(
            session_id=session_id, context_is_fresh=context_is_fresh, started_at=NOW
        ),
        workspace=Workspace(
            workspace_id=workspace_id,
            branch="claude/candidate",
            head_sha=head_sha,
            read_only=read_only,
            clean=clean,
        ),
    )


def author(**overrides) -> Party:
    return party("claude-builder-1", "session-author", "worktree-builder",
                 read_only=False, **overrides)


def reviewer(**overrides) -> Party:
    return party("claude-reviewer-2", "session-reviewer", "worktree-review",
                 read_only=True, **overrides)


def assignment(**overrides) -> ReviewAssignment:
    data = {"candidate_sha": CANDIDATE, "author": author(), "reviewer": reviewer()}
    data.update(overrides)
    return ReviewAssignment(**data)


def refused(result) -> set[Ineligibility]:
    assert result.eligible is False
    return set(result.reasons)


def test_a_properly_routed_review_is_eligible() -> None:
    """The baseline every refusal below is measured against."""

    result = evaluate_review_eligibility(assignment(), observed_candidate_sha=CANDIDATE)
    assert result.eligible is True
    assert result.reasons == ()


# --- the author cannot review themselves -----------------------------------


def test_self_review_is_structurally_ineligible() -> None:
    same = author()
    result = evaluate_review_eligibility(
        assignment(reviewer=same), observed_candidate_sha=CANDIDATE
    )
    assert Ineligibility.SAME_PRINCIPAL in refused(result)


def test_a_fresh_session_does_not_launder_the_same_principal() -> None:
    """The failure this project actually kept hitting.

    A new session, a new workspace, a clean read-only checkout, a genuinely
    empty context — and still the same principal, which is the one thing that
    has to differ.
    """

    disguised = party(
        "claude-builder-1",          # the author's principal
        "session-completely-new",     # a different session
        "worktree-somewhere-else",    # a different workspace
        read_only=True,
        context_is_fresh=True,
    )
    result = evaluate_review_eligibility(
        assignment(reviewer=disguised), observed_candidate_sha=CANDIDATE
    )
    assert refused(result) == {Ineligibility.SAME_PRINCIPAL}

    # Load-bearing control: change the principal id and nothing else.
    renamed = disguised.model_copy(
        update={"principal": disguised.principal.model_copy(update={"principal_id": "other-1"})}
    )
    assert evaluate_review_eligibility(
        assignment(reviewer=renamed), observed_candidate_sha=CANDIDATE
    ).eligible


def test_principal_identity_is_compared_without_case_or_padding_tricks() -> None:
    """``Claude-Builder-1 `` is not a second principal."""

    for disguise in ("Claude-Builder-1", "  claude-builder-1", "CLAUDE-BUILDER-1  "):
        sneaky = party(disguise, "session-new", "worktree-new", read_only=True)
        result = evaluate_review_eligibility(
            assignment(reviewer=sneaky), observed_candidate_sha=CANDIDATE
        )
        assert Ineligibility.SAME_PRINCIPAL in refused(result), disguise


# --- cognitive diversity is not operational independence -------------------


def test_a_different_model_family_cannot_rescue_the_same_principal() -> None:
    """Cognitive diversity is metadata. Eligibility never reads it."""

    other_model = party(
        "claude-builder-1", "session-new", "worktree-new",
        read_only=True, model_family="some-entirely-different-family",
    )
    result = evaluate_review_eligibility(
        assignment(
            reviewer=other_model,
            cognitive_diversity_note="different family, different training, different everything",
        ),
        observed_candidate_sha=CANDIDATE,
    )
    assert refused(result) == {Ineligibility.SAME_PRINCIPAL}


def test_the_same_model_family_is_no_obstacle_to_two_real_principals() -> None:
    """The converse, so the rule is not accidentally about families at all."""

    twin = party("claude-reviewer-2", "session-reviewer", "worktree-review",
                 read_only=True, model_family="claude-opus-5")
    assert evaluate_review_eligibility(
        assignment(reviewer=twin), observed_candidate_sha=CANDIDATE
    ).eligible


# --- session and workspace -------------------------------------------------


def test_sharing_the_authors_session_is_ineligible() -> None:
    shared = party("claude-reviewer-2", "session-author", "worktree-review", read_only=True)
    result = evaluate_review_eligibility(
        assignment(reviewer=shared), observed_candidate_sha=CANDIDATE
    )
    assert refused(result) == {Ineligibility.SAME_SESSION}

    fixed = party("claude-reviewer-2", "session-elsewhere", "worktree-review", read_only=True)
    assert evaluate_review_eligibility(
        assignment(reviewer=fixed), observed_candidate_sha=CANDIDATE
    ).eligible


def test_sharing_the_authors_workspace_is_ineligible() -> None:
    shared = party("claude-reviewer-2", "session-reviewer", "worktree-builder", read_only=True)
    result = evaluate_review_eligibility(
        assignment(reviewer=shared), observed_candidate_sha=CANDIDATE
    )
    assert refused(result) == {Ineligibility.SAME_WORKSPACE}


def test_an_inherited_context_is_ineligible() -> None:
    stale = reviewer(context_is_fresh=False)
    result = evaluate_review_eligibility(
        assignment(reviewer=stale), observed_candidate_sha=CANDIDATE
    )
    assert refused(result) == {Ineligibility.STALE_CONTEXT}


# --- the reviewer is read-only from the acceptance path --------------------


def test_a_writable_reviewer_workspace_is_ineligible() -> None:
    """A reviewer who can edit the candidate can repair what they are judging,
    and their verdict then describes a tree nobody else has seen."""

    writable = party("claude-reviewer-2", "session-reviewer", "worktree-review", read_only=False)
    result = evaluate_review_eligibility(
        assignment(reviewer=writable), observed_candidate_sha=CANDIDATE
    )
    assert refused(result) == {Ineligibility.REVIEWER_WORKSPACE_IS_WRITABLE}

    made_read_only = writable.model_copy(
        update={"workspace": writable.workspace.model_copy(update={"read_only": True})}
    )
    assert evaluate_review_eligibility(
        assignment(reviewer=made_read_only), observed_candidate_sha=CANDIDATE
    ).eligible


def test_a_dirty_reviewer_workspace_is_ineligible() -> None:
    dirty = reviewer(clean=False)
    result = evaluate_review_eligibility(
        assignment(reviewer=dirty), observed_candidate_sha=CANDIDATE
    )
    assert refused(result) == {Ineligibility.REVIEWER_WORKSPACE_IS_DIRTY}


# --- exact candidate SHA binding -------------------------------------------


def test_candidate_sha_drift_is_ineligible() -> None:
    """The branch moved after the assignment was written, so the review would
    be of a commit nobody asked about."""

    result = evaluate_review_eligibility(assignment(), observed_candidate_sha=OTHER_SHA)
    assert refused(result) == {Ineligibility.CANDIDATE_SHA_DRIFT}

    # Load-bearing control: observe the SHA the assignment names.
    assert evaluate_review_eligibility(assignment(), observed_candidate_sha=CANDIDATE).eligible


@pytest.mark.parametrize("observed", ["", "abc", "a" * 39, "a" * 41, "z" * 40, "HEAD"])
def test_an_unresolvable_observed_sha_fails_closed(observed: str) -> None:
    """Anything that is not an exact SHA is drift, not a pass."""

    result = evaluate_review_eligibility(assignment(), observed_candidate_sha=observed)
    assert Ineligibility.CANDIDATE_SHA_DRIFT in refused(result)


def test_a_reviewer_sitting_on_a_different_commit_is_ineligible() -> None:
    elsewhere = reviewer(head_sha=OTHER_SHA)
    result = evaluate_review_eligibility(
        assignment(reviewer=elsewhere), observed_candidate_sha=CANDIDATE
    )
    assert refused(result) == {Ineligibility.REVIEWER_NOT_AT_CANDIDATE}


def test_an_assignment_cannot_be_built_from_an_inexact_sha() -> None:
    with pytest.raises(ValidationError):
        assignment(candidate_sha="HEAD")
    with pytest.raises(ValidationError):
        assignment(candidate_sha="a" * 39)


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        assignment(rubber_stamp=True)


# --- every reason is reported, not just the first --------------------------


def test_all_reasons_are_reported_together() -> None:
    hopeless = party("claude-builder-1", "session-author", "worktree-builder",
                     read_only=False, context_is_fresh=False, head_sha=OTHER_SHA)
    result = evaluate_review_eligibility(
        assignment(reviewer=hopeless), observed_candidate_sha=OTHER_SHA
    )
    assert refused(result) == {
        Ineligibility.SAME_PRINCIPAL,
        Ineligibility.SAME_SESSION,
        Ineligibility.SAME_WORKSPACE,
        Ineligibility.STALE_CONTEXT,
        Ineligibility.CANDIDATE_SHA_DRIFT,
        Ineligibility.REVIEWER_WORKSPACE_IS_WRITABLE,
    }
    for reason in result.reasons:
        assert reason.value in result.detail


# --- selection -------------------------------------------------------------


def test_selection_skips_the_author_and_finds_the_real_reviewer() -> None:
    chosen = select_eligible_reviewer(
        author=author(),
        candidate_sha=CANDIDATE,
        observed_candidate_sha=CANDIDATE,
        reviewers=(author(), reviewer()),
    )
    assert chosen is not None
    assert chosen.reviewer.principal.principal_id == "claude-reviewer-2"


def test_selection_returns_nothing_rather_than_settling() -> None:
    """No eligible reviewer is a correct answer, and not permission to proceed."""

    assert select_eligible_reviewer(
        author=author(),
        candidate_sha=CANDIDATE,
        observed_candidate_sha=CANDIDATE,
        reviewers=(author(), party("claude-builder-1", "s2", "w2", read_only=True)),
    ) is None


def test_selection_finds_nobody_when_the_candidate_has_drifted() -> None:
    assert select_eligible_reviewer(
        author=author(),
        candidate_sha=CANDIDATE,
        observed_candidate_sha=OTHER_SHA,
        reviewers=(reviewer(),),
    ) is None
