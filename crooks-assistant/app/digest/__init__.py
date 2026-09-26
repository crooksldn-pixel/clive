"""The Knowledge Digester: how CLIVE takes in an external artifact — a repository, a skill, a
document, a specification, a dataset — and turns it into provenance-tagged, reversible
knowledge. Standard library only, no network, and nothing it reads is ever executed:
digesting is reading. See SOURCE_ASSIMILATION_V1.md in product memory."""

from app.digest.model import (
    ABSORPTION_TARGETS,
    ADDING_TARGETS,
    ADDITION_KINDS,
    ARTIFACT_KINDS,
    DECIDER,
    FINDING_CATEGORIES,
    ORIGIN_KINDS,
    PROPOSER,
    SEVERITIES,
    UNIT_KINDS,
    Absorption,
    Addition,
    Artifact,
    Finding,
    Location,
    RemovalHandle,
    Source,
    Unit,
    content_digest,
    utc_now,
)
from app.digest.schema import SCHEMAS, schema_for
from app.digest.store import ArtifactConflict, DigestStore

__all__ = [
    "ABSORPTION_TARGETS",
    "ADDING_TARGETS",
    "ADDITION_KINDS",
    "ARTIFACT_KINDS",
    "DECIDER",
    "FINDING_CATEGORIES",
    "ORIGIN_KINDS",
    "PROPOSER",
    "SCHEMAS",
    "SEVERITIES",
    "UNIT_KINDS",
    "Absorption",
    "Addition",
    "Artifact",
    "ArtifactConflict",
    "DigestStore",
    "Finding",
    "Location",
    "RemovalHandle",
    "Source",
    "Unit",
    "content_digest",
    "schema_for",
    "utc_now",
]
