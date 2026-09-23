"""The typed review result and the replaceable reviewer-driver seam.

The dispatcher consumes exactly one kind of reviewer output: a ``ReviewResult``
JSON object. Its decision is an enum (``READY`` or ``CHANGES_REQUIRED``); every
material finding is a structured record with an id, the evidence it rests on and
the bounded repair it requires. Explanation for humans may ride along in
``summary`` and is never read to decide anything. There is no prose parser.

The reviewer's own facts (principal, session, workspace, read-only, clean, at the
candidate) are declared in the result and handed to the kernel, which re-runs the
eligibility rule on them at the exact SHA; as the kernel documents, it cannot
inspect a reviewer's machine, so these are declared facts, bound to one verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field, field_validator, model_validator

from ..contracts import ExactSha, StrictRecord, validate_exact_sha
from ..review_acceptance import ReviewVerdict
from ..routing import Party, Principal, PrincipalKind, SessionContext, Workspace

__all__ = [
    "Finding",
    "ReviewContext",
    "ReviewResult",
    "ReviewerDriver",
    "ReviewerFacts",
    "REVIEW_RESULT_SCHEMA",
]


class Finding(StrictRecord):
    finding_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
    material: bool
    finding: str = Field(min_length=1, max_length=4000)
    evidence_ref: str = Field(min_length=1, max_length=1000)
    required_repair: str = Field(min_length=1, max_length=4000)


class ReviewerFacts(StrictRecord):
    principal_id: str = Field(min_length=1, max_length=200)
    principal_kind: PrincipalKind = PrincipalKind.MODEL
    session_id: str = Field(min_length=1, max_length=200)
    session_started_at: datetime
    context_fresh: bool
    workspace_id: str = Field(min_length=1, max_length=300)
    workspace_branch: str = Field(min_length=1, max_length=300)
    workspace_head: ExactSha
    read_only: bool
    clean: bool

    @field_validator("workspace_head")
    @classmethod
    def exact_sha(cls, value: str) -> str:
        return validate_exact_sha(value)

    def party(self) -> Party:
        return Party(
            principal=Principal(principal_id=self.principal_id, kind=self.principal_kind),
            session=SessionContext(session_id=self.session_id, context_is_fresh=self.context_fresh,
                                   started_at=self.session_started_at),
            workspace=Workspace(workspace_id=self.workspace_id, branch=self.workspace_branch,
                                head_sha=self.workspace_head, read_only=self.read_only, clean=self.clean),
        )


class ReviewResult(StrictRecord):
    schema_version: Literal["clive.review_result.v1"] = "clive.review_result.v1"
    task_id: str = Field(min_length=1, max_length=120)
    task_revision: int = Field(ge=1)
    attempt_id: str = Field(min_length=1, max_length=120)
    candidate_sha: ExactSha
    verdict: Literal["READY", "CHANGES_REQUIRED"]
    findings: tuple[Finding, ...] = ()
    reviewer: ReviewerFacts
    summary: str = Field(default="", max_length=20000)

    @field_validator("candidate_sha")
    @classmethod
    def exact_sha(cls, value: str) -> str:
        return validate_exact_sha(value)

    @model_validator(mode="after")
    def decision_matches_findings(self) -> ReviewResult:
        material = [f for f in self.findings if f.material]
        if self.verdict == "READY" and material:
            raise ValueError("READY cannot carry a material finding")
        if self.verdict == "CHANGES_REQUIRED" and not material:
            raise ValueError("CHANGES_REQUIRED needs at least one material finding")
        ids = [f.finding_id for f in self.findings]
        if len(ids) != len(set(ids)):
            raise ValueError("finding ids must be unique")
        return self

    @property
    def kernel_verdict(self) -> ReviewVerdict:
        return ReviewVerdict.READY if self.verdict == "READY" else ReviewVerdict.REPAIR_REQUIRED

    @property
    def material_findings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.material)


REVIEW_RESULT_SCHEMA = ReviewResult.model_json_schema()


@dataclass(frozen=True)
class ReviewContext:
    task_id: str
    task_revision: int
    attempt_id: str
    dispatch_seq: int
    candidate_sha: str
    packet_path: Path


class ReviewerDriver(Protocol):
    """Launches or relays one review and returns the typed result when there is one.

    ``availability`` must be honest: a driver that cannot actually reach its
    reviewer returns (False, the exact gap), and the dispatcher blocks instead of
    dispatching a review nobody will perform.
    """

    principal_id: str
    mechanism: str
    courier: bool

    def availability(self) -> tuple[bool, str]: ...

    def start(self, ctx: ReviewContext) -> None: ...

    def poll(self, ctx: ReviewContext) -> list[bytes]:
        """Every result submitted for this dispatch, oldest first; the dispatcher skips those it consumed."""
        ...
