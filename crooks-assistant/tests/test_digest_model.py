"""The Knowledge Digester's model and store: ids that follow from content, records that read
back exactly as written, serialised forms that meet their JSON Schema, a store that will not
overwrite one artifact with another, and an absorption ledger that is only ever appended to —
where nothing is absorbed without a way back."""

from __future__ import annotations

import json
import re

import pytest

from app.digest import (
    SCHEMAS,
    Absorption,
    Addition,
    Artifact,
    ArtifactConflict,
    DigestStore,
    Finding,
    Location,
    RemovalHandle,
    Source,
    Unit,
    content_digest,
)
from app.digest.model import MAX_BODY
from app.digest.schema import DEFS

TAKEN = "2026-09-26T10:00:00+00:00"


def _source(data: bytes = b"a skill collection", **overrides) -> Source:
    fields = {
        "origin": "https://example.invalid/skills.git",
        "origin_kind": "git",
        "pinned_ref": "0123456789abcdef0123456789abcdef01234567",
        "licence": "MIT",
        "taken_at": TAKEN,
        "content_digest": content_digest(data),
    }
    fields.update(overrides)
    return Source(**fields)


def _unit(artifact_id: str, **overrides) -> Unit:
    fields = {
        "artifact_id": artifact_id,
        "kind": "procedure",
        "title": "Release a package",
        "body": "1. Bump the version.\n2. Tag it.\n3. Publish.",
        "location": Location("skills/release/SKILL.md", 3, 9),
        "tags": ("release", "packaging"),
    }
    fields.update(overrides)
    return Unit(**fields)


def _artifact(source: Source | None = None) -> Artifact:
    source = source or _source()
    units = (
        _unit(source.artifact_id),
        _unit(source.artifact_id, kind="script", title="publish.sh", body="twine upload dist/*",
              location=Location("skills/release/publish.sh", 1, 1), tags=()),
        _unit(source.artifact_id, kind="knowledge", title="Licence", body="",
              location=Location("."), tags=("licence",)),
    )
    return Artifact(source=source, kinds=("skill_collection", "python_package"), units=units)


def _finding(artifact: Artifact) -> Finding:
    script = artifact.units[1]
    return Finding(
        artifact_id=artifact.id, category="safety", severity="medium",
        location=script.location, unit_id=script.id,
        explanation="Uploads to a package index if it is run. Recorded as a script, not run.",
    )


def _absorption(artifact: Artifact, **overrides) -> Absorption:
    fields = {
        "artifact_id": artifact.id,
        "unit_id": artifact.units[0].id,
        "target": "builder_skill",
        "reasoning": "A release procedure the builder can follow as written.",
        "removal": RemovalHandle((
            Addition("skill", "skills/release.md", content_digest(b"release skill")),
        )),
        "recorded_at": TAKEN,
    }
    fields.update(overrides)
    return Absorption(**fields)


# --- a structural JSON Schema checker: only the keywords schema.py uses ----------------------

_KNOWN = {
    "$schema", "$id", "$defs", "$ref", "type", "enum", "properties", "required",
    "additionalProperties", "items", "uniqueItems", "minLength", "maxLength", "pattern",
    "minimum", "format",
}
_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _errors(value, schema: dict) -> list[str]:
    errors: list[str] = []
    _check(value, schema, schema, "$", errors)
    return errors


def _check(value, schema: dict, root: dict, where: str, errors: list[str]) -> None:
    if "$ref" in schema:
        target = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        _check(value, target, root, where, errors)
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPES[name](value) for name in names):
            errors.append(f"{where}: not {names}")
            return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{where}: {value!r} not in enum")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{where}: too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{where}: too long")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{where}: does not match {schema['pattern']}")
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{where}: below minimum")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{where}: missing {key}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                _check(item, properties[key], root, f"{where}.{key}", errors)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{where}: unexpected {key}")
    if isinstance(value, list):
        if schema.get("uniqueItems"):
            seen = [json.dumps(item, sort_keys=True) for item in value]
            if len(set(seen)) != len(seen):
                errors.append(f"{where}: duplicate items")
        if "items" in schema:
            for index, item in enumerate(value):
                _check(item, schema["items"], root, f"{where}[{index}]", errors)


def _keywords(node, found: set[str], *, names: bool = False) -> None:
    """Every keyword the schema uses. Property names and $defs names are not keywords."""
    if isinstance(node, dict):
        for key, item in node.items():
            if not names:
                found.add(key)
            _keywords(item, found, names=key in ("properties", "$defs") and not names)
    elif isinstance(node, list):
        for item in node:
            _keywords(item, found)


# --- deterministic ids -------------------------------------------------------------------------


def test_ids_follow_from_content_and_nothing_else():
    one, two = _artifact(), _artifact()
    assert one.id == two.id
    assert re.fullmatch(r"art-[0-9a-f]{24}", one.id)
    assert [u.id for u in one.units] == [u.id for u in two.units]
    assert all(re.fullmatch(r"unit-[0-9a-f]{24}", u.id) for u in one.units)
    assert _finding(one).id == _finding(two).id
    assert re.fullmatch(r"find-[0-9a-f]{24}", _finding(one).id)
    assert _absorption(one).id == _absorption(two).id
    assert re.fullmatch(r"abs-[0-9a-f]{24}", _absorption(one).id)


def test_the_artifact_id_is_derived_from_the_source_digest():
    same_bytes_elsewhere = _source(origin="/tmp/upload.zip", origin_kind="upload", licence=None)
    assert same_bytes_elsewhere.artifact_id == _source().artifact_id
    assert _source(b"other bytes").artifact_id != _source().artifact_id


def test_a_unit_id_changes_with_what_the_unit_is():
    artifact_id = _source().artifact_id
    base = _unit(artifact_id)
    assert _unit(artifact_id, location=Location("skills/release/SKILL.md", 3, 10)).id != base.id
    assert _unit(artifact_id, kind="rule").id != base.id
    assert _unit(_source(b"other").artifact_id).id != base.id


# --- round-trips -------------------------------------------------------------------------------


def test_every_record_round_trips_exactly():
    artifact = _artifact()
    records = [
        (Source, artifact.source),
        (Unit, artifact.units[0]),
        (Artifact, artifact),
        (Finding, _finding(artifact)),
        (Absorption, _absorption(artifact)),
        (Absorption, _absorption(artifact, decided_by="owner", target="reference_only",
                                 removal=RemovalHandle())),
    ]
    for cls, record in records:
        data = record.to_dict()
        again = cls.from_dict(json.loads(json.dumps(data)))
        assert again == record
        assert again.to_dict() == data


def test_records_are_frozen():
    artifact = _artifact()
    with pytest.raises(AttributeError):
        artifact.kinds = ()  # type: ignore[misc]
    with pytest.raises(AttributeError):
        artifact.units[0].title = "changed"  # type: ignore[misc]


def test_a_record_whose_id_does_not_match_its_content_is_refused():
    data = _artifact().units[0].to_dict()
    data["title"] = "Something else"
    with pytest.raises(ValueError, match="id"):
        Unit.from_dict(data)
    data = _artifact().to_dict()
    data["id"] = "art-" + "0" * 24
    with pytest.raises(ValueError, match="id"):
        Artifact.from_dict(data)


def test_unknown_or_missing_fields_are_refused():
    data = _source().to_dict()
    data["extra"] = 1
    with pytest.raises(ValueError, match="unexpected"):
        Source.from_dict(data)
    data = _source().to_dict()
    del data["licence"]
    with pytest.raises(ValueError, match="missing"):
        Source.from_dict(data)


def test_vocabularies_and_bounds_are_enforced():
    artifact_id = _source().artifact_id
    with pytest.raises(ValueError):
        _unit(artifact_id, kind="spell")
    with pytest.raises(ValueError):
        _unit(artifact_id, body="x" * (MAX_BODY + 1))
    with pytest.raises(ValueError):
        _source(origin_kind="carrier_pigeon")
    with pytest.raises(ValueError):
        _source(taken_at="2026-09-26T10:00:00")          # no timezone
    for path in ("/etc/passwd", "../outside", "a/../b", "./a", ""):
        with pytest.raises(ValueError):
            Location(path)
    with pytest.raises(ValueError):
        Location("a.md", 5, 2)
    with pytest.raises(ValueError):
        Artifact(source=_source(), kinds=("skill_collection",),
                 units=(_unit(_source(b"other").artifact_id),))


def test_an_artifact_never_exists_without_its_source():
    with pytest.raises(ValueError, match="Source"):
        Artifact(source=None, kinds=("document",))  # type: ignore[arg-type]


# --- the removal handle ------------------------------------------------------------------------


def test_an_absorption_without_a_removal_handle_is_rejected():
    artifact = _artifact()
    with pytest.raises(ValueError, match="removal handle"):
        _absorption(artifact, removal=None)
    data = _absorption(artifact).to_dict()
    del data["removal"]
    with pytest.raises(ValueError, match="removal"):
        Absorption.from_dict(data)
    data = _absorption(artifact).to_dict()
    data["removal"] = None
    with pytest.raises(ValueError, match="removal handle"):
        Absorption.from_dict(data)


def test_an_absorption_that_adds_something_must_say_what():
    artifact = _artifact()
    with pytest.raises(ValueError, match="removal handle"):
        _absorption(artifact, removal=RemovalHandle())
    with pytest.raises(ValueError, match="removal handle"):
        _absorption(artifact, target="rejected")          # adds nothing, yet lists an addition
    assert _absorption(artifact, target="rejected", removal=RemovalHandle()).removal.additions == ()


def test_clive_proposes_and_the_owner_decides():
    artifact = _artifact()
    assert not _absorption(artifact).is_decision
    assert _absorption(artifact, decided_by="owner").is_decision
    with pytest.raises(ValueError):
        _absorption(artifact, decided_by="clive")
    with pytest.raises(ValueError):
        _absorption(artifact, proposed_by="someone")


# --- JSON Schema -------------------------------------------------------------------------------


def test_the_schema_uses_only_keywords_the_checker_understands():
    for schema in SCHEMAS.values():
        found: set[str] = set()
        _keywords(schema, found)
        assert found <= _KNOWN, found - _KNOWN
    assert set(DEFS) >= set(SCHEMAS)


def test_serialised_examples_meet_their_schema():
    artifact = _artifact()
    examples = {
        "source": artifact.source.to_dict(),
        "unit": artifact.units[0].to_dict(),
        "artifact": artifact.to_dict(),
        "finding": _finding(artifact).to_dict(),
        "absorption": _absorption(artifact).to_dict(),
    }
    for name, data in examples.items():
        assert _errors(data, SCHEMAS[name]) == [], name
    decision = _absorption(artifact, decided_by="owner", target="rejected", removal=RemovalHandle())
    assert _errors(decision.to_dict(), SCHEMAS["absorption"]) == []


def test_the_schema_refuses_what_the_model_refuses():
    artifact = _artifact()
    unit = artifact.units[0].to_dict()
    unit["kind"] = "spell"
    assert _errors(unit, SCHEMAS["unit"])
    absorption = _absorption(artifact).to_dict()
    del absorption["removal"]
    assert _errors(absorption, SCHEMAS["absorption"])
    source = artifact.source.to_dict()
    source["content_digest"] = "md5:abc"
    assert _errors(source, SCHEMAS["source"])


# --- the store ---------------------------------------------------------------------------------


def test_the_store_keeps_one_directory_per_artifact(tmp_path):
    store = DigestStore(tmp_path / "digest")
    artifact = _artifact()
    assert store.put(artifact) is True
    folder = tmp_path / "digest" / artifact.id
    assert sorted(p.name for p in folder.iterdir()) == [
        "absorptions.jsonl", "artifact.json", "findings.jsonl", "source.json", "units.jsonl",
    ]
    assert store.ids() == [artifact.id]
    assert store.load(artifact.id) == artifact
    assert [p.name for p in (tmp_path / "digest").iterdir()] == [artifact.id]   # no staging left

    assert _errors(json.loads((folder / "source.json").read_text()), SCHEMAS["source"]) == []
    assert _errors(json.loads((folder / "artifact.json").read_text()), SCHEMAS["artifact_record"]) == []
    lines = (folder / "units.jsonl").read_text().splitlines()
    assert len(lines) == len(artifact.units)
    for line in lines:
        assert _errors(json.loads(line), SCHEMAS["unit"]) == []


def test_the_store_refuses_to_overwrite_a_different_artifact(tmp_path):
    store = DigestStore(tmp_path)
    artifact = _artifact()
    store.put(artifact)
    folder = tmp_path / artifact.id
    before = {p.name: p.read_bytes() for p in folder.iterdir()}

    assert store.put(_artifact()) is False                       # the same artifact: no change
    retaken = _artifact(_source(taken_at="2026-09-27T09:00:00+00:00"))
    assert retaken.id == artifact.id
    with pytest.raises(ArtifactConflict):
        store.put(retaken)
    fewer_units = Artifact(source=artifact.source, kinds=artifact.kinds, units=artifact.units[:1])
    with pytest.raises(ArtifactConflict):
        store.put(fewer_units)

    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
    assert store.load(artifact.id) == artifact


def test_the_absorption_ledger_is_append_only(tmp_path):
    store = DigestStore(tmp_path)
    artifact = _artifact()
    store.put(artifact)
    ledger = tmp_path / artifact.id / "absorptions.jsonl"

    proposal = _absorption(artifact)
    assert store.add_absorption(proposal) is True
    after_first = ledger.read_bytes()
    decision = _absorption(artifact, decided_by="owner", recorded_at="2026-09-26T12:00:00+00:00")
    assert store.add_absorption(decision) is True
    after_second = ledger.read_bytes()
    assert after_second.startswith(after_first) and len(after_second) > len(after_first)

    assert store.add_absorption(proposal) is False               # already recorded: not again
    assert ledger.read_bytes() == after_second
    assert store.absorptions(artifact.id) == (proposal, decision)
    for line in ledger.read_text().splitlines():
        assert _errors(json.loads(line), SCHEMAS["absorption"]) == []

    stranger = _absorption(artifact, unit_id=_unit(_source(b"other").artifact_id).id)
    with pytest.raises(ValueError, match="does not have"):
        store.add_absorption(stranger)
    assert ledger.read_bytes() == after_second


def test_findings_are_appended_and_read_back(tmp_path):
    store = DigestStore(tmp_path)
    artifact = _artifact()
    store.put(artifact)
    finding = _finding(artifact)
    assert store.add_finding(finding) is True
    assert store.add_finding(finding) is False
    assert store.findings(artifact.id) == (finding,)
    line = (tmp_path / artifact.id / "findings.jsonl").read_text().strip()
    assert _errors(json.loads(line), SCHEMAS["finding"]) == []


def test_the_store_refuses_ids_that_are_not_artifact_ids(tmp_path):
    store = DigestStore(tmp_path)
    for bad in ("../escape", "art-xyz", ""):
        with pytest.raises(ValueError):
            store.path_for(bad)
    with pytest.raises(FileNotFoundError):
        store.load(_source().artifact_id)


def test_text_that_cannot_be_written_as_utf8_is_refused_as_a_value_error():
    """A lone surrogate (from a JSON or Python escape, or a file name that is not UTF-8)
    would make the unit's id and the store's write raise UnicodeEncodeError later. The
    model refuses it at construction, as the ValueError every other bad field raises."""
    from app.digest.model import Location, Unit

    lone = "before \ud800 after"
    with pytest.raises(ValueError, match="UTF-8"):
        Unit(artifact_id="art-" + "0" * 24, kind="knowledge", title=lone, body="b",
             location=Location(path="a.md"))
    with pytest.raises(ValueError, match="UTF-8"):
        Unit(artifact_id="art-" + "0" * 24, kind="knowledge", title="t", body=lone,
             location=Location(path="a.md"))
    with pytest.raises(ValueError, match="UTF-8"):
        Location(path=lone)
