"""Who is allowed to review whom, and about which exact commit.

This is the machinery that a later round needs in order to route a candidate
to a reviewer honestly. It decides eligibility and nothing else: it dispatches
nothing, writes nothing, and cannot accept anything.

The distinction it exists to hold is between *operational* independence and
*cognitive* diversity. A different model family reading the same diff from the
same principal in the same workspace is not an independent review — it is the
same hand marking its own work with a different pen. Cognitive diversity is
recorded here because it is genuinely useful information, and it is recorded
as metadata that eligibility never consults.

Five rounds of this project's own review history were mis-routed back to their
author, so the rules fail closed: anything unresolved is ineligible, and no
combination of otherwise-good signals can overturn a structural refusal.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator

from .contracts import ExactSha, StrictRecord, validate_exact_sha


class PrincipalKind(StrEnum):
    MODEL = "model"
    HUMAN = "human"
    AUTOMATION = "automation"


class Ineligibility(StrEnum):
    """Every reason a review cannot count towards final acceptance."""

    SAME_PRINCIPAL = "same_principal"
    SAME_SESSION = "same_session"
    SAME_WORKSPACE = "same_workspace"
    STALE_CONTEXT = "stale_context"
    CANDIDATE_SHA_DRIFT = "candidate_sha_drift"
    REVIEWER_WORKSPACE_IS_WRITABLE = "reviewer_workspace_is_writable"
    REVIEWER_WORKSPACE_IS_DIRTY = "reviewer_workspace_is_dirty"
    REVIEWER_NOT_AT_CANDIDATE = "reviewer_not_at_candidate"


class Principal(StrictRecord):
    """A durable identity that can be held responsible for a judgement.

    ``model_family`` is descriptive only. Two principals sharing a family are
    still two principals; one principal wearing two families is still one.
    """

    principal_id: str = Field(min_length=1, max_length=200)
    kind: PrincipalKind
    model_family: str | None = Field(default=None, max_length=120)
    operator: str | None = Field(default=None, max_length=200)


class SessionContext(StrictRecord):
    """One continuous run of a principal's attention.

    ``context_is_fresh`` says the reviewer did not inherit the author's
    working context. It is necessary and nowhere near sufficient: a fresh
    session belonging to the same principal is still that principal.
    """

    session_id: str = Field(min_length=1, max_length=200)
    context_is_fresh: bool
    started_at: datetime

    @field_validator("started_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class Workspace(StrictRecord):
    """A checkout. Two principals sharing one are not working independently.

    ``read_only`` is the reviewer's side of the contract: a reviewer who can
    edit the candidate can repair what they were asked to judge, and their
    verdict then describes a tree nobody else has seen.
    """

    workspace_id: str = Field(min_length=1, max_length=200)
    branch: str = Field(min_length=1, max_length=300)
    head_sha: ExactSha
    read_only: bool = False
    clean: bool = True

    @field_validator("head_sha")
    @classmethod
    def validate_head(cls, value: str) -> str:
        return validate_exact_sha(value)


class Party(StrictRecord):
    """A principal, in a session, in a workspace — the three that must differ."""

    principal: Principal
    session: SessionContext
    workspace: Workspace


class ReviewAssignment(StrictRecord):
    """A proposal to have ``reviewer`` judge ``candidate_sha``, authored by ``author``."""

    schema_version: str = "clive.review_assignment.v1"
    candidate_sha: ExactSha
    author: Party
    reviewer: Party
    # Recorded, never consulted by eligibility. See the module docstring.
    cognitive_diversity_note: str | None = None

    @field_validator("candidate_sha")
    @classmethod
    def validate_candidate(cls, value: str) -> str:
        return validate_exact_sha(value)


class ReviewEligibility(StrictRecord):
    eligible: bool
    reasons: tuple[Ineligibility, ...] = ()
    detail: str = ""


def _same(left: str, right: str) -> bool:
    return left.strip().casefold() == right.strip().casefold()


def evaluate_review_eligibility(
    assignment: ReviewAssignment,
    *,
    observed_candidate_sha: str,
) -> ReviewEligibility:
    """Decide whether this review could count towards final acceptance.

    ``observed_candidate_sha`` is the SHA resolved fresh at decision time, not
    the one the assignment was written with. If they disagree the candidate
    moved underneath the assignment, and the review would be of a commit
    nobody asked about.

    Returns every reason it found rather than the first, so a caller fixing a
    routing mistake learns all of it at once.
    """

    reasons: list[Ineligibility] = []

    author, reviewer = assignment.author, assignment.reviewer

    # Operational independence: three separate questions, none of which the
    # others can answer on its behalf.
    if _same(author.principal.principal_id, reviewer.principal.principal_id):
        reasons.append(Ineligibility.SAME_PRINCIPAL)
    if _same(author.session.session_id, reviewer.session.session_id):
        reasons.append(Ineligibility.SAME_SESSION)
    if _same(author.workspace.workspace_id, reviewer.workspace.workspace_id):
        reasons.append(Ineligibility.SAME_WORKSPACE)
    if not reviewer.session.context_is_fresh:
        reasons.append(Ineligibility.STALE_CONTEXT)

    # Exact-SHA binding.
    try:
        observed = validate_exact_sha(observed_candidate_sha)
    except ValueError:
        observed = None
    if observed is None or observed != assignment.candidate_sha:
        reasons.append(Ineligibility.CANDIDATE_SHA_DRIFT)
    elif reviewer.workspace.head_sha != assignment.candidate_sha:
        # The reviewer is looking at something else entirely.
        reasons.append(Ineligibility.REVIEWER_NOT_AT_CANDIDATE)

    # The reviewer's workspace must be read-only from the acceptance path.
    if not reviewer.workspace.read_only:
        reasons.append(Ineligibility.REVIEWER_WORKSPACE_IS_WRITABLE)
    if not reviewer.workspace.clean:
        reasons.append(Ineligibility.REVIEWER_WORKSPACE_IS_DIRTY)

    if reasons:
        return ReviewEligibility(
            eligible=False,
            reasons=tuple(reasons),
            detail="; ".join(reason.value for reason in reasons),
        )

    return ReviewEligibility(
        eligible=True,
        detail="reviewer is operationally independent of the author at this exact candidate",
    )


def select_eligible_reviewer(
    *,
    author: Party,
    candidate_sha: str,
    observed_candidate_sha: str,
    reviewers: tuple[Party, ...],
    cognitive_diversity_note: str | None = None,
) -> ReviewAssignment | None:
    """Return the first reviewer that is eligible, or ``None``.

    ``None`` means nobody may review this yet. That is a correct and common
    answer, and it is emphatically not permission to let the author proceed.
    """

    for reviewer in reviewers:
        assignment = ReviewAssignment(
            candidate_sha=validate_exact_sha(candidate_sha),
            author=author,
            reviewer=reviewer,
            cognitive_diversity_note=cognitive_diversity_note,
        )
        if evaluate_review_eligibility(
            assignment, observed_candidate_sha=observed_candidate_sha
        ).eligible:
            return assignment
    return None
