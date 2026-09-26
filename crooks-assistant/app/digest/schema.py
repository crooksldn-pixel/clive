"""JSON Schema (draft 2020-12) for the digester's serialised forms: what to_dict writes, and
what the store keeps on disk. The vocabularies, bounds and id patterns are read from model.py,
so a kind added there is a kind the schema accepts.

The schema is structural. The rules that relate one field to another — a unit's id is derived
from its content, a target that adds something must say what — are the model's to enforce."""

from __future__ import annotations

from app.digest import model

DIALECT = "https://json-schema.org/draft/2020-12/schema"


def _string(max_length: int | None = None, *, min_length: int = 1, pattern: str | None = None,
            nullable: bool = False) -> dict:
    schema: dict = {"type": ["string", "null"] if nullable else "string", "minLength": min_length}
    if max_length is not None:
        schema["maxLength"] = max_length
    if pattern is not None:
        schema["pattern"] = pattern
    return schema


def _object(properties: dict) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _list(items: dict) -> dict:
    return {"type": "array", "items": items, "uniqueItems": True}


def _ref(name: str) -> dict:
    return {"$ref": f"#/$defs/{name}"}


_TIMESTAMP = {"type": "string", "minLength": 1, "format": "date-time"}
_LINE = {"type": ["integer", "null"], "minimum": 1}

DEFS: dict[str, dict] = {
    "location": _object({
        "path": _string(),
        "line_start": _LINE,
        "line_end": _LINE,
    }),
    "source": _object({
        "origin": _string(),
        "origin_kind": {"enum": list(model.ORIGIN_KINDS)},
        "pinned_ref": _string(),
        "licence": _string(model.MAX_LICENCE, nullable=True),
        "taken_at": _TIMESTAMP,
        "content_digest": _string(pattern=model.CONTENT_DIGEST_PATTERN),
    }),
    "unit": _object({
        "id": _string(pattern=model.UNIT_ID_PATTERN),
        "artifact_id": _string(pattern=model.ARTIFACT_ID_PATTERN),
        "kind": {"enum": list(model.UNIT_KINDS)},
        "title": _string(model.MAX_TITLE),
        "body": _string(model.MAX_BODY, min_length=0),
        "location": _ref("location"),
        "tags": _list(_string(model.MAX_TAG)),
    }),
    "artifact": _object({
        "id": _string(pattern=model.ARTIFACT_ID_PATTERN),
        "source": _ref("source"),
        "kinds": _list({"enum": list(model.ARTIFACT_KINDS)}),
        "units": _list(_ref("unit")),
    }),
    # artifact.json in the store: the artifact without its source and units, which are kept
    # beside it in source.json and units.jsonl.
    "artifact_record": _object({
        "id": _string(pattern=model.ARTIFACT_ID_PATTERN),
        "content_digest": _string(pattern=model.CONTENT_DIGEST_PATTERN),
        "kinds": _list({"enum": list(model.ARTIFACT_KINDS)}),
        "unit_ids": _list(_string(pattern=model.UNIT_ID_PATTERN)),
    }),
    "finding": _object({
        "id": _string(pattern=model.FINDING_ID_PATTERN),
        "artifact_id": _string(pattern=model.ARTIFACT_ID_PATTERN),
        "category": {"enum": list(model.FINDING_CATEGORIES)},
        "severity": {"enum": list(model.SEVERITIES)},
        "location": _ref("location"),
        "explanation": _string(model.MAX_EXPLANATION),
        "unit_id": _string(pattern=model.UNIT_ID_PATTERN, nullable=True),
    }),
    "addition": _object({
        "kind": {"enum": list(model.ADDITION_KINDS)},
        "ref": _string(),
        "digest": _string(pattern=model.CONTENT_DIGEST_PATTERN, nullable=True),
    }),
    "removal_handle": _object({
        "additions": _list(_ref("addition")),
    }),
    "absorption": _object({
        "id": _string(pattern=model.ABSORPTION_ID_PATTERN),
        "artifact_id": _string(pattern=model.ARTIFACT_ID_PATTERN),
        "unit_id": _string(pattern=model.UNIT_ID_PATTERN),
        "target": {"enum": list(model.ABSORPTION_TARGETS)},
        "reasoning": _string(model.MAX_REASONING),
        "removal": _ref("removal_handle"),
        "recorded_at": _TIMESTAMP,
        "proposed_by": {"enum": [model.PROPOSER]},
        "decided_by": {"enum": [model.DECIDER, None]},
    }),
}


def schema_for(name: str) -> dict:
    """A standalone schema document for one serialised form."""
    if name not in DEFS:
        raise KeyError(name)
    return {
        "$schema": DIALECT,
        "$id": f"urn:clive:digest:{name}",
        "$defs": DEFS,
        "$ref": f"#/$defs/{name}",
    }


SCHEMAS: dict[str, dict] = {
    name: schema_for(name)
    for name in ("source", "unit", "artifact", "artifact_record", "finding", "absorption")
}
