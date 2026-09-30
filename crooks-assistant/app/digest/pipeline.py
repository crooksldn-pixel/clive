"""The Knowledge Digester in one call: from a quarantined directory to a stored digest and,
given CLIVE's self-model, to what CLIVE proposes to take from it.

    result = digest(root, source, store, self_model=build_self_model(repo_root))

runs the library stages of KNOWLEDGE_DIGESTER_V1.md section 3 in order, on a copy that is
already in quarantine and already pinned by its Source:

1. Recognise: detect.detect_kinds names every kind the tree is, with evidence and a census.
   A recogniser that failed becomes a quality finding.
2. Scan: scan.scan_tree reads the tree for what it would do to us. Each of its findings
   becomes a model Finding in the "safety" category, its severity mapped by SCAN_SEVERITY.
   A block-severity finding stops the artifact here, before decomposition: the Artifact is
   returned (and stored) with its findings and no Units — unless it holds only part of it.
   A licence that forbids reuse (SCOPED_BLOCKS), declared by a licence file or manifest below
   the top of the artifact, covers only its own folder, so that folder is left out (the
   finding says so, at SCOPED_SEVERITY) and the rest is digested. Any other block, in a file
   the scanner read as it is written, holds only the nearest skill folder above that file —
   a folder with a SKILL.md the scanner read — or, outside every skill folder of an artifact
   that has one, only that file (the owner's decision of 30 September 2026: skills are scanned
   per skill, not per collection). What is held is left out whole, the finding says so at
   SCOPED_SEVERITY, and the result's `holds` carry each finding with its flagged line quoted
   from the quarantined copy, credentials redacted, for the owner (never a credential rule's
   line). Still stopping everything: a licence that forbids reuse at the top; the rules in
   WHOLE_ARTIFACT_BLOCKS (characters that make what a reviewer sees differ from what a machine
   reads, which say the author set out to deceive); a finding whose path the scanner escaped,
   redacted or did not read as text; more credentials than the scanner keeps; any block in an
   artifact with no skill folder, or in a skill at its very top. Only what the scanner read
   reaches an adapter, and nothing left out does, so no adapter reads across into what is held.
3. Decompose: every adapter in the app.digest.adapters namespace whose HANDLES meet the
   detected kinds reads the tree into Units — but only what the scanner read. The adapters
   are given a private view of the tree holding exactly the files the scanner read and
   scanned as text, byte for byte as it read them (scan.Reading), outside any folder or file
   left out or held: a file it skipped (binary, too large, hard-linked, unreadable, past its
   limits) or that changed after it was scanned is never read by an adapter, since what could
   not be scanned is never passed as clean. Adapters are discovered with pkgutil.iter_modules at
   every call, never from a list kept here, so a module dropped into the namespace is used
   from the next digest on. An adapter that raises, or returns something that is not its
   artifact's Units, is contained: a quality finding names it and the others carry on.
   Every Unit's title, body, tags and path then have every credential the scanner found in
   the artifact, and every credential of a shape it knows, replaced by '[redacted …]'
   (scan.redact) and the Unit is tagged 'redacted' — so no credential is stored, related,
   proposed or shown, wherever an adapter quoted it from; detect's evidence is redacted the
   same way. Units are de-duplicated by id and sorted by place.
4. Relate, when a self-model is given (selfmodel.build_self_model): relate.relate gives each
   Unit its relation to what CLIVE already is — overlap, extends, gap or reference — with the
   entries it rests on and the digest of the self-model it was made against.
5. Propose, with the relations: propose.proposals gives CLIVE's absorption proposals — one
   per skill, per file of procedures or per other Unit, licensed, ranked best first and bounded
   by a budget per target, the rest held back in `held` — each proposed by CLIVE and decided
   by no one, with its target, reasoning, hypothesis, measure and removal handle. With
   purpose="self" (CLIVE digesting its own repository) nothing is proposed: relate.relate_self
   traces every Unit to the product memory instead, into `trace`. With a store the proposals
   go into the artifact's ledger through store.add_proposals, which appends only what the
   ledger does not already hold: the same
   digest against the same self-model again appends nothing, and the result carries the
   records as the ledger holds them, each with the time it was first proposed.
   Self mode, like every digest, relates only the Units decomposed from what the scanner read,
   redacted; each folder's licence is read from the same scanned view.
   A blocked artifact has no Units, so nothing is related or proposed; without a self-model
   the digest stops after decomposition, as it always could.

Digesting is reading. Nothing here, and nothing it calls, executes, imports or installs what
the artifact holds; there is no network; the same tree, Source and self-model give the same
result, and the same proposals once their `recorded_at` is given (or held by the store).

Why a result object and not a bare Artifact: the model's Artifact is the Source, the kinds and
the Units, and the store keeps findings and the ledger beside it rather than in it. What a
caller (the report, the command line, the next stages) also needs from one digest — its
findings, detect's evidence and census, which adapters ran, whether it was blocked, and the
relations and proposals — is gathered in DigestResult, whose ``artifact`` is exactly what the
store holds.

tree_digest(root) is the content digest a Source records for a directory: stable across
machines, walk order and time, symbolic links named and never followed, and bounded in
entries, bytes and depth.
"""

from __future__ import annotations

import hashlib
import importlib
import os
import pkgutil
import posixpath
import re
import shutil
import stat
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from app.digest import detect, scan
from app.digest.model import (
    ARTIFACT_KINDS,
    FINDING_CATEGORIES,
    MAX_BODY,
    MAX_EXPLANATION,
    MAX_TAG,
    MAX_TITLE,
    SEVERITIES,
    Absorption,
    Artifact,
    Finding,
    Location,
    Source,
    Unit,
    utc_now,
)
from app.digest.propose import proposals as propose_ranked
from app.digest.relate import Relation, SelfTrace, relate, relate_self
from app.digest.selfmodel import SelfModel
from app.digest.store import DigestStore

ADAPTERS_PACKAGE = "app.digest.adapters"
PURPOSES = ("absorb", "self")

# --- the one kind table -------------------------------------------------------------------
#
# detect.py names kinds in its own words (agent_skill, openapi_spec, shopify_theme, ...), and
# each adapter's HANDLES mixes those words, plain words ("skill collection") and the model's
# ARTIFACT_KINDS. Every word from either side is canonicalised (lower case, runs of spaces and
# hyphens to one underscore) and looked up here; a word the table does not know is "other".
# The model's own kinds map to themselves, so a kind added to ARTIFACT_KINDS is known at once.
KIND_TABLE: dict[str, str] = {
    **{kind: kind for kind in ARTIFACT_KINDS},
    # agent skills, harness configuration and prompt libraries
    "agent_skill": "skill_collection",
    "skill": "skill_collection",
    "prompt_library": "skill_collection",
    "agent_config": "configuration",
    "agent_configuration": "configuration",
    "harness_configuration": "configuration",
    # code
    "git_repository": "source_code",
    "swift_project": "source_code",
    "go_project": "source_code",
    "rust_project": "source_code",
    "java_project": "source_code",
    "jupyter_notebooks": "source_code",
    # interface and tool specifications
    "openapi": "api_spec",
    "openapi_spec": "api_spec",
    "swagger": "api_spec",
    "graphql": "api_spec",
    "graphql_schema": "api_spec",
    "json_schema": "api_spec",
    "json_schema_set": "api_spec",
    "mcp": "tool_spec",
    "mcp_server": "tool_spec",
    # documents
    "documentation_set": "document",
    "office_documents": "document",
    "markdown": "document",
    "restructuredtext": "document",
    "text": "document",
    "html": "document",
    # web, themes and design systems
    "website": "web_app",
    "shopify_theme": "theme",
    "design_system": "theme",
    "design_tokens": "theme",
    # applications
    "browser_extension": "application",
    "mobile_app": "application",
    # media
    "images": "media",
    "audio": "media",
    "video": "media",
    # configuration of machines and builds
    "infrastructure": "configuration",
    "ci_workflows": "configuration",
    # nothing recognised
    detect.UNKNOWN: "other",
}

# Scan severities onto the model's SEVERITIES. A severity scan.py does not document is taken
# as block: the quarantine fails closed.
SCAN_SEVERITY: dict[str, str] = {
    scan.INFO: "info",
    scan.WARN: "medium",
    scan.BLOCK: "critical",
}
ADAPTER_FAILURE_SEVERITY = "medium"      # part of the artifact is not digested
RECOGNISER_FAILURE_SEVERITY = "low"      # one kind may have been missed

# Scan rules whose block covers only the folder of the file that says it (see stage 2), and
# the severity such a block is recorded at once that folder is left out.
SCOPED_BLOCKS = frozenset({"licence.forbids_reuse"})
SCOPED_SEVERITY = "high"
# Scan rules whose block stops the whole artifact even inside a skill collection, where any
# other block holds only its skill folder or its file (see _held_place). Each is a technique
# for making what a person reviews differ from what a machine reads: a direction override
# reorders the line on screen, tag characters and runs of variation selectors spell out text
# nobody sees, and a file name with them displays as another name. Unlike a phrase aimed at an
# agent — which documentation about agents quotes, advises against or uses in plain prose, and
# which per-skill holding exists to recover from — none has an innocent use in a skill (none of
# the 34 block findings measured on five public collections was one). Each is invisible in the
# raw source too, in every editor and on GitHub, where no escape is written for the reviewer as
# the report writes one; so each shows an author working to deceive whoever reviews the
# collection, and nothing else of theirs can be vouched for by the patterns this one got past.
# A path the scanner had to escape or redact is never held either (it is not in reading.text),
# so most deceptive file names stop everything twice over; the rule covers the rest (a Hangul
# filler prints, so its path is shown as it is).
WHOLE_ARTIFACT_BLOCKS = frozenset({
    "deceptive.bidi", "deceptive.tag", "deceptive.variation", "deceptive.filename",
})
SKILL_FILE = "skill.md"                  # a skill folder's file, named in any case (as the adapter)
CREDENTIAL_RULES = "secret."             # a held credential's line is never quoted
MAX_QUOTE = 240                          # characters of a flagged line quoted for the owner
REDACTED_TAG = "redacted"
# The scan rules that mean a file was not read as text, so not decomposed.
UNSCANNED_RULES = frozenset({
    "scan.binary", "scan.too_large", "scan.hardlink", "scan.unreadable", "scan.limit",
    "scan.special",
})
VIEW_PREFIX = "clive-digest-view-"

# Bounds on tree_digest: past either, the tree cannot be pinned and is refused.
MAX_TREE_ENTRIES = 50_000                # files, directories, links and the rest, as detect
MAX_TREE_BYTES = 1 << 30                 # file content hashed, in all
MAX_TREE_DEPTH = 256                     # folders inside folders
_TREE_DIGEST_VERSION = b"clive-tree-digest-v1\x00"
_CHUNK = 1 << 20

_WORD_BREAK = re.compile(r"[\s\-]+")


def canonical_word(word: str) -> str:
    return _WORD_BREAK.sub("_", word.strip().lower())


def normalise_kind(word: str) -> str:
    """The model's ARTIFACT_KINDS name for a kind word from detect.py or an adapter's HANDLES:
    through KIND_TABLE, and "other" for a word it does not know."""
    return KIND_TABLE.get(canonical_word(word), "other")


# --- adapters -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Adapter:
    """One module of the adapters namespace that keeps the adapter contract: HANDLES, a tuple
    of kind words, and decompose(root, artifact_id) -> list[Unit]; NAME defaults to the module's."""

    module: str
    name: str
    handles: tuple[str, ...]
    decompose: Callable[[Path, str], list[Unit]]

    def handles_any(self, detected: Iterable[str]) -> bool:
        """Whether this adapter reads an artifact detected as these kinds. The words meet
        through KIND_TABLE; a word the table does not know meets only the same word, never
        another unknown one by way of "other"."""
        detected = [canonical_word(word) for word in detected]
        found = {KIND_TABLE[word] for word in detected if word in KIND_TABLE}
        wanted = {canonical_word(word) for word in self.handles}
        known = {KIND_TABLE[word] for word in wanted if word in KIND_TABLE}
        return bool(known & found) or bool(wanted & set(detected))


def discover_adapters() -> tuple[tuple[Adapter, ...], tuple[tuple[str, str], ...]]:
    """Every adapter in the namespace, in module-name order, and every module that could not
    be imported or does not keep the contract, as (module, reason). Modules whose names start
    with an underscore are helpers, and a module without HANDLES or decompose is not an adapter;
    both are passed over."""
    importlib.invalidate_caches()        # a module written since the last digest is seen
    package = importlib.import_module(ADAPTERS_PACKAGE)
    adapters: list[Adapter] = []
    broken: list[tuple[str, str]] = []
    for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda found: found.name):
        if info.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"{ADAPTERS_PACKAGE}.{info.name}")
        except Exception as error:
            broken.append((info.name, f"could not be imported ({type(error).__name__})"))
            continue
        handles = getattr(module, "HANDLES", None)
        decompose = getattr(module, "decompose", None)
        if handles is None or decompose is None:
            continue
        if (
            not callable(decompose) or not isinstance(handles, (tuple, list, frozenset, set))
            or not all(isinstance(word, str) for word in handles)
        ):
            broken.append((info.name, "does not keep the adapter contract (HANDLES words and decompose)"))
            continue
        name = getattr(module, "NAME", None)
        adapters.append(Adapter(
            module=info.name,
            name=name if isinstance(name, str) and name.strip() else info.name,
            handles=tuple(sorted(handles)) if isinstance(handles, (set, frozenset)) else tuple(handles),
            decompose=decompose,
        ))
    return tuple(adapters), tuple(broken)


# --- the result -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Hold:
    """One block-severity finding that holds only its skill folder or its file for the owner,
    rather than stopping the artifact (stage 2). `place` is what is left out — the skill folder
    ("skill") or the file ("file") — and `path`, `line`, `rule` and `message` are the scanner's.
    `quote` is the flagged line as it stands in the quarantined copy, at most MAX_QUOTE
    characters, with every credential the scanner found replaced by '[redacted]', every shape of
    one by '[redacted <kind>]' and every invisible or direction-changing character written as an
    escape; None, with `unquoted` saying why, for a credential rule, a finding about a file as a
    whole, a line where a credential was found, or a copy that changed after it was scanned."""

    place: str
    scope: str                               # "skill" or "file"
    rule: str
    path: str
    line: int
    message: str
    quote: str | None = None
    unquoted: str = ""


@dataclass(frozen=True)
class DigestResult:
    """One digest: the Artifact as the store keeps it, what was found on the way, and — when
    it was related to CLIVE's self-model — each Unit's relation and CLIVE's proposals."""

    artifact: Artifact
    findings: tuple[Finding, ...]            # most severe first, then by place
    detections: tuple[detect.Detection, ...]  # detect's own, most confident first
    census: detect.Census
    adapters: tuple[str, ...]                # the adapters that ran, by NAME, in the order run
    blocked: bool                            # stopped before decomposition by a block finding
    relations: tuple[Relation, ...] = ()     # one per Unit, in the Units' order
    proposals: tuple[Absorption, ...] = ()   # best first, within the budget, as recorded
    self_model: str | None = None            # the digest of the self-model related against
    purpose: str = "absorb"                  # PURPOSES: absorb from it, or understand CLIVE
    held: tuple[tuple[str, tuple[str, ...]], ...] = ()  # (target, unit ids) past the budget
    trace: SelfTrace | None = None           # self mode: the why-index and drift
    excluded: tuple[str, ...] = ()           # folders left out under their own licence
    withheld: tuple[tuple[str, str], ...] = ()  # (path, why) the intake did not copy
    notes: tuple[str, ...] = ()              # what the intake said about the copy
    holds: tuple[Hold, ...] = ()             # block findings holding only a skill folder or file

    @property
    def units(self) -> tuple[Unit, ...]:
        return self.artifact.units

    @property
    def held_places(self) -> tuple[tuple[str, str], ...]:
        """Each skill folder or file held for the owner, as (place, scope), once, in order."""
        return tuple(dict.fromkeys((hold.place, hold.scope) for hold in self.holds))

    @property
    def related(self) -> bool:
        """Whether the Units were related to a self-model (and so proposed for)."""
        return self.self_model is not None


def digest(root: str | os.PathLike[str], source: Source,
           store: DigestStore | None = None, *, self_model: SelfModel | None = None,
           recorded_at: str | None = None, purpose: str = "absorb",
           withheld: Iterable[tuple[str, str]] = (), notes: Iterable[str] = (),
           curated: bool = False) -> DigestResult:
    """Recognise, scan and decompose the quarantined directory at root, as the artifact source
    names, and write the source, artifact, units and findings to store when one is given.
    Given CLIVE's self_model, and unless the artifact was blocked, relate every Unit to it and
    propose what to take from each; with a store the proposals go into the ledger, once.

    source.content_digest is the caller's pin and is not recomputed here (tree_digest gives it
    for a directory). A Source whose origin carries a credential is refused with ValueError:
    it would be stored and shown. A root that is not a directory, or is a symbolic link, is
    refused with NotADirectoryError. Writing an artifact whose id the store already holds as a
    different record raises store.ArtifactConflict; the same record again changes nothing.
    `recorded_at` is when new proposals are recorded (default: now); pass it to make them
    exactly repeatable without a store. `purpose` is "absorb" (what CLIVE might take from it) or
    "self" (CLIVE digesting its own repository: traced to the product memory, nothing proposed);
    either way the Units are only what the scanner read, redacted. `withheld` ((path, why)
    pairs) and `notes` are what the intake said about the copy (intake.Intake), carried into
    the result and the report. `curated` says the owner listed this artifact's skills himself,
    and is passed to proposing (propose.proposals)."""
    if not isinstance(source, Source):
        raise ValueError("a digest needs the artifact's Source")
    if scan.redact(source.origin) != source.origin:
        raise ValueError("the Source's origin carries a credential; give the origin without it")
    withheld = _pairs(withheld)
    notes = _texts(notes)
    if store is not None and not isinstance(store, DigestStore):
        raise ValueError("store must be a DigestStore")
    if self_model is not None and not isinstance(self_model, SelfModel):
        raise ValueError("self_model must be a SelfModel (selfmodel.build_self_model)")
    # purpose "self" is CLIVE digesting its own repository: relate everything, trace it to the
    # product memory (relate.relate_self), and propose nothing — CLIVE does not absorb itself.
    if purpose not in PURPOSES:
        raise ValueError(f"purpose must be one of {PURPOSES}, not {purpose!r}")
    if purpose == "self" and self_model is None:
        raise ValueError("digesting CLIVE itself needs its self-model")
    base = Path(root)
    if os.path.islink(base) or not base.is_dir():
        raise NotADirectoryError(f"{base} is not a directory: digest reads a quarantined copy")
    artifact_id = source.artifact_id
    findings: dict[str, Finding] = {}

    def keep(finding: Finding) -> None:
        findings.setdefault(finding.id, finding)

    # 1. recognise
    detection = detect.detect_kinds(base)
    detected = [found.kind for found in detection.kinds]
    for kind, failure in sorted(detection.failures.items()):
        keep(Finding(
            artifact_id, "quality", RECOGNISER_FAILURE_SEVERITY, Location("."),
            f"digest.recogniser: the '{_clean(kind)}' recogniser failed "
            f"({_error_type(failure)}), so whether the artifact is also that kind is unknown.",
        ))
    found_kinds = {normalise_kind(word) for word in detected}
    kinds = tuple(kind for kind in ARTIFACT_KINDS if kind in found_kinds)

    # 2. scan
    reading = scan.Reading()
    blocked = False
    excluded: set[str] = set()
    unscanned = 0
    scanned = scan.scan_tree(base, reading=reading)
    skills = _skill_folders(reading)
    holding: list[tuple[scan.Finding, str, str]] = []   # (finding, place, scope)
    for found in scanned:
        unscanned += found.rule in UNSCANNED_RULES
        if found.severity in (scan.INFO, scan.WARN):
            keep(_from_scan(artifact_id, found))
            continue
        folder = _scoped_folder(found, reading)
        if folder is not None:
            excluded.add(folder)
            keep(_from_scan(
                artifact_id, found, SCOPED_SEVERITY,
                f" Only {folder}/ is under this licence, so only it is left out: nothing in it is "
                "decomposed, and the rest of the artifact is digested.",
            ))
            continue
        held = _held_place(found, reading, skills)
        if held is None:
            blocked = True
            keep(_from_scan(artifact_id, found))
        else:
            holding.append((found, *held))
    if reading.overflowed:
        blocked = True
        keep(Finding(
            artifact_id, "safety", "critical", Location("."),
            "digest.withheld: more credential values were found than the scanner keeps, so no "
            "Unit could be vouched free of them: nothing is decomposed.",
        ))
    secrets = reading.secrets
    # A finding that would hold only its skill folder or file holds it only when nothing stops
    # the artifact; when something does, it is one more reason the artifact stopped.
    holds: tuple[Hold, ...] = ()
    for found, place, scope in holding:
        keep(_from_scan(artifact_id, found) if blocked else _from_scan(
            artifact_id, found, SCOPED_SEVERITY, _held_note(found, place, scope, secrets)))
    if holding and not blocked:
        holds = _holds(base, reading, holding, scanned)
    detections = tuple(_redacted_detection(found, secrets) for found in detection.kinds)

    # 3. decompose, unless blocked: only what the scanner read, and never a credential
    units: dict[str, Unit] = {}
    ran: list[str] = []
    licences: dict[str, tuple[str, str]] = {}
    if not blocked:
        view, changed = _scanned_view(base, reading, excluded | {hold.place for hold in holds})
        try:
            adapters, broken = discover_adapters()
            for module, reason in broken:
                keep(Finding(
                    artifact_id, "quality", ADAPTER_FAILURE_SEVERITY, Location("."),
                    f"digest.adapter: the adapter module '{_clean(module)}' {reason}, so it did not run.",
                ))
            for adapter in adapters:
                if not adapter.handles_any(detected):
                    continue
                ran.append(adapter.name)
                made, problem = _run(adapter, view, artifact_id)
                for unit in made:
                    unit = _redacted_unit(unit, secrets)
                    units.setdefault(unit.id, unit)
                if problem:
                    keep(Finding(
                        artifact_id, "quality", ADAPTER_FAILURE_SEVERITY, Location("."),
                        f"digest.adapter: the '{_clean(adapter.name)}' adapter {problem}",
                    ))
            if self_model is not None and purpose != "self":
                # each folder's own licence, for the proposals: read from the view, so only
                # from licence files the scanner read, and redacted as the Units' paths are
                licences = {
                    scan.redact(folder, secrets): (scan.redact(expression, secrets), scan.redact(where, secrets))
                    for folder, (expression, where) in scan.licence_map(view).items()
                }
        finally:
            shutil.rmtree(view.parent, ignore_errors=True)
        for rel in changed:
            location, where = _location(scan.redact(rel, secrets), 0)
            keep(Finding(
                artifact_id, "safety", "high", location,
                f"digest.changed: {where}this file's bytes are not the ones the scanner read, so it "
                "was not decomposed: the quarantined copy changed after it was scanned.",
            ))
        if unscanned:
            keep(Finding(
                artifact_id, "quality", "info", Location("."),
                f"digest.unscanned: only what the scanner read as text is decomposed; {unscanned} "
                "file(s) or part(s) of the tree it did not read (binary, too large, hard-linked, "
                "unreadable, special or past its limits: see the scan findings) were read by no adapter.",
            ))
        redacted = sum(1 for unit in units.values() if REDACTED_TAG in unit.tags)
        if redacted:
            keep(Finding(
                artifact_id, "safety", "info", Location("."),
                f"digest.redacted: {redacted} Unit(s) quoted text shaped like a credential, or one "
                "the scanner found in the artifact; it was replaced by '[redacted …]' before any "
                "Unit was kept, related or shown.",
            ))

    artifact = Artifact(source=source, kinds=kinds, units=tuple(sorted(units.values(), key=_unit_order)))
    ordered = tuple(sorted(findings.values(), key=finding_order))

    # 4. relate and 5. propose, given the self-model and something to relate
    relations: tuple[Relation, ...] = ()
    proposals: tuple[Absorption, ...] = ()
    related_to = None
    held: tuple[tuple[str, tuple[str, ...]], ...] = ()
    trace = None
    if self_model is not None and not blocked:
        related_to = self_model.digest
        if purpose == "self":
            found, trace = relate_self(artifact.units, self_model)
            relations = tuple(found)
        else:
            relations = tuple(relate(artifact.units, self_model))
            made = propose_ranked(
                artifact.id, artifact.units, relations, recorded_at=recorded_at or utc_now(),
                licence=source.licence, licences=licences, findings=ordered,
                self_model=self_model, curated=curated,
            )
            proposals, held = made.kept, made.held

    if store is not None:
        store.put(artifact)
        store.add_findings(ordered)
        if proposals:
            proposals, _appended = store.add_proposals(proposals)
    return DigestResult(
        artifact=artifact, findings=ordered, detections=detections,
        census=detection.census, adapters=tuple(ran), blocked=blocked,
        relations=relations, proposals=proposals, self_model=related_to, purpose=purpose,
        held=held, trace=trace, excluded=tuple(sorted(excluded)),
        withheld=tuple((scan.redact(path, secrets), scan.redact(why, secrets)) for path, why in withheld),
        notes=tuple(scan.redact(note, secrets) for note in notes), holds=holds,
    )


def _pairs(items: Iterable[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    out = []
    for item in items:
        if (not isinstance(item, (tuple, list)) or len(item) != 2
                or not all(isinstance(part, str) for part in item)):
            raise ValueError("withheld must be (path, why) pairs of text")
        out.append((_clean(item[0]), _clean(item[1])))
    return tuple(out)


def _texts(items: Iterable[str]) -> tuple[str, ...]:
    out = []
    for item in items:
        if not isinstance(item, str):
            raise ValueError("notes must be text")
        out.append(_clean(item))
    return tuple(out)


# --- only what the scanner read ---------------------------------------------------------------


def _scoped_folder(found: scan.Finding, reading: scan.Reading) -> str | None:
    """The folder a block covers when it covers only a folder (SCOPED_BLOCKS, from a file the
    scanner read below the top of the artifact); None when it stops the whole artifact —
    including when its path is not one the scanner read as it is written (redacted or escaped),
    so the folder cannot be told exactly."""
    if found.rule not in SCOPED_BLOCKS or found.path not in reading.text:
        return None
    return posixpath.dirname(found.path) or None


# --- held for the owner -------------------------------------------------------------------------
#
# The owner's decision of 30 September 2026 (OWNER_DECISIONS_2026-09-30.md): skills are scanned
# per skill, not per collection, and a held skill is shown to the owner with the exact flagged
# line. Measured on five public collections, 94% of 353 skills were lost to whole-collection
# blocks, 27 of the 34 block findings were false positives, and the 7 real ones sat outside every
# skill folder (hooks, MCP configuration, agent settings). So a block finding in a file the
# scanner read as written holds only the nearest skill folder above it — or, outside every skill
# folder of an artifact that has one, only that file — and the rest is digested. Nothing held is
# decomposed, related or proposed. What still stops the artifact: a licence that forbids reuse at
# its top (SCOPED_BLOCKS keeps its own rule), a rule in WHOLE_ARTIFACT_BLOCKS, a finding whose
# path the scanner escaped, redacted or did not read as text (so where it is cannot be told
# exactly), more credentials than the scanner keeps, any block in an artifact with no skill
# folder, and any block inside a skill at the top of the artifact, which is the whole of it.


def _skill_folders(reading: scan.Reading) -> frozenset[str]:
    """Every folder holding a SKILL.md (in any case) that the scanner read as text; "" is the
    top of the artifact."""
    return frozenset(
        posixpath.dirname(rel) for rel in reading.text if posixpath.basename(rel).lower() == SKILL_FILE
    )


def _held_place(found: scan.Finding, reading: scan.Reading,
                skills: frozenset[str]) -> tuple[str, str] | None:
    """What a block finding holds, as (place, scope): the nearest skill folder above its file
    ("skill"), or, in an artifact with skill folders, the file alone when none is above it
    ("file"). None when it stops the whole artifact (see above)."""
    if found.rule in SCOPED_BLOCKS or found.rule in WHOLE_ARTIFACT_BLOCKS or found.path not in reading.text:
        return None
    folder = posixpath.dirname(found.path)
    while True:
        if folder in skills:
            return (folder, "skill") if folder else None
        if not folder:
            break
        folder = posixpath.dirname(folder)
    return (found.path, "file") if skills else None


def _held_note(found: scan.Finding, place: str, scope: str, secrets: Iterable[str]) -> str:
    shown = scan.redact(place, secrets)
    what = (f"Only the skill folder {shown}/ is held and left out" if scope == "skill"
            else "Only this file is held and left out")
    sees = ("where it is (a credential's line is never quoted)" if found.rule.startswith(CREDENTIAL_RULES)
            else "the flagged line")
    return (f" {what}: nothing in it is decomposed, the rest of the artifact is digested, and the "
            f"owner sees {sees}.")


def _holds(base: Path, reading: scan.Reading, holding: list[tuple[scan.Finding, str, str]],
           scanned: Iterable[scan.Finding]) -> tuple[Hold, ...]:
    """Each held finding with its flagged line quoted from the quarantined copy, as Hold
    describes. Each file is read once, bounded as the scanner read it, and only if its bytes are
    still the ones scanned."""
    credited: dict[str, set[int]] = {}      # lines where a credential was found; 0: the file
    for found in scanned:
        if found.rule.startswith(CREDENTIAL_RULES):
            credited.setdefault(found.path, set()).add(found.line)
        elif found.rule == "scan.truncated" and f"'{CREDENTIAL_RULES}" in found.message:
            credited.setdefault(found.path, set()).add(0)   # the lines not listed are unknown
    secrets = sorted({value for value in reading.secrets if value}, key=lambda value: (-len(value), value))
    texts: dict[str, list[str] | None] = {}
    holds: list[Hold] = []
    for found, place, scope in holding:
        quote, unquoted = None, ""
        lines = credited.get(found.path, set())
        if found.rule.startswith(CREDENTIAL_RULES):
            unquoted = "a credential's line is never quoted"
        elif found.line < 1:
            unquoted = "the finding is about the file as a whole, not one line"
        elif found.line in lines or 0 in lines:
            unquoted = "a credential was found on this line or past the scanner's count in this file"
        else:
            if found.path not in texts:
                data = _read_scanned(base, found.path)
                texts[found.path] = (
                    scan._decode(data).split("\n")
                    if data is not None and hashlib.sha256(data).hexdigest() == reading.text[found.path]
                    else None
                )
            text = texts[found.path]
            if text is None:
                unquoted = "the quarantined copy changed after it was scanned"
            elif found.line > len(text):
                unquoted = "the file has no such line"
            else:
                quote = _quotable(text[found.line - 1], secrets)
        holds.append(Hold(place, scope, found.rule, found.path, found.line, _clean(found.message),
                          quote, unquoted))
    return tuple(sorted(holds, key=lambda hold: (hold.place, hold.path, hold.line, hold.rule, hold.message)))


def _quotable(line: str, secrets: list[str]) -> str:
    """A line of the artifact as it can be shown to the owner: every credential value found
    replaced by '[redacted]' (longest first, however short), every credential shape by
    '[redacted <kind>]', every character that does not print or that hides or reorders text
    written as an escape, and at most MAX_QUOTE characters."""
    line = line.rstrip("\r")
    for value in secrets:
        if value in line:
            line = line.replace(value, scan.REDACTED)
    line = scan.redact(line)
    shown = "".join(scan._escape(ch) if _hides(ch) else ch for ch in line)
    return shown if len(shown) <= MAX_QUOTE else shown[:MAX_QUOTE - 1] + "…"


def _hides(ch: str) -> bool:
    """Whether a character does not print, or can hide or reorder text on screen (the zero-width
    and filler characters, direction controls, tag characters, variation selectors)."""
    return not ch.isprintable() or scan._is_hidden_char(ch) or scan._is_variation(ord(ch)) or bool(
        scan._INVISIBLE.fullmatch(ch))


def _scanned_view(base: Path, reading: scan.Reading,
                  excluded: Iterable[str]) -> tuple[Path, list[str]]:
    """A private directory holding exactly the files the scanner read as text, byte for byte as
    it read them, outside the excluded folders and files: what the adapters decompose. It has
    the tree's own name, inside a private temporary directory the caller removes. A file whose
    bytes are no longer the ones scanned is left out, and returned."""
    excluded = tuple(sorted(excluded))
    holder = Path(tempfile.mkdtemp(prefix=VIEW_PREFIX))
    view = holder / (base.resolve().name or "artifact")
    changed: list[str] = []
    try:
        view.mkdir()
        for rel in sorted(reading.text):
            if any(rel == folder or rel.startswith(folder + "/") for folder in excluded):
                continue
            data = _read_scanned(base, rel)
            if data is None or hashlib.sha256(data).hexdigest() != reading.text[rel]:
                changed.append(rel)
                continue
            target = view / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    except BaseException:
        shutil.rmtree(holder, ignore_errors=True)
        raise
    return view, changed


def _read_scanned(base: Path, rel: str) -> bytes | None:
    """The bytes of the file at rel under base, reached one folder at a time without following
    a link, and only if it is still a regular file with no other name; None otherwise."""
    parts = rel.split("/")
    try:
        fd = os.open(base, _DIR_FLAGS)
    except OSError:
        return None
    try:
        for part in parts[:-1]:
            inner = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = inner
        handle = os.open(parts[-1], _FILE_FLAGS, dir_fd=fd)
    except OSError:
        os.close(fd)
        return None
    os.close(fd)
    try:
        info = os.fstat(handle)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1 or info.st_size > scan.MAX_FILE_BYTES:
            return None
        chunks = []
        size = 0
        while chunk := os.read(handle, _CHUNK):
            size += len(chunk)
            if size > scan.MAX_FILE_BYTES:
                return None
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError:
        return None
    finally:
        os.close(handle)


def _fit(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _redacted_unit(unit: Unit, secrets: Iterable[str]) -> Unit:
    """The Unit with every credential in its text or path replaced (scan.redact), tagged
    'redacted'; the Unit itself when there was none."""
    title = _fit(scan.redact(unit.title, secrets), MAX_TITLE)
    body = _fit(scan.redact(unit.body, secrets), MAX_BODY)
    tags = tuple(dict.fromkeys(_fit(scan.redact(tag, secrets), MAX_TAG) for tag in unit.tags))
    path = scan.redact(unit.location.path, secrets)
    if (title, body, tags, path) == (unit.title, unit.body, unit.tags, unit.location.path):
        return unit
    try:
        location = Location(path, unit.location.line_start, unit.location.line_end)
    except ValueError:
        location = Location(".")
    return Unit(unit.artifact_id, unit.kind, title, body, location,
                tuple(dict.fromkeys((*tags, REDACTED_TAG))))


def _redacted_detection(found: detect.Detection, secrets: Iterable[str]) -> detect.Detection:
    """detect's evidence with every credential replaced: it quotes files — .git/HEAD, say — that
    the scanner never reads."""
    return replace(found, label=scan.redact(found.label, secrets), evidence=tuple(
        replace(item, path=scan.redact(item.path, secrets), signal=scan.redact(item.signal, secrets))
        for item in found.evidence
    ))


def _run(adapter: Adapter, base: Path, artifact_id: str) -> tuple[list[Unit], str | None]:
    """The adapter's Units, and what went wrong if anything did. The exception's message is
    never kept: it may quote the artifact, and a finding never does."""
    try:
        made = adapter.decompose(base, artifact_id)
    except Exception as error:
        return [], (
            f"stopped with {type(error).__name__}, and none of its Units were kept: what it "
            "reads in this artifact is not digested."
        )
    if not isinstance(made, (list, tuple)):
        return [], (
            f"returned {type(made).__name__} rather than a list of Units, and none of it was "
            "kept: what it reads in this artifact is not digested."
        )
    good = [unit for unit in made if isinstance(unit, Unit) and unit.artifact_id == artifact_id]
    if len(good) == len(made):
        return good, None
    return good, (
        f"returned {len(made) - len(good)} item(s) that are not Units of this artifact; they "
        f"were dropped and its other {len(good)} Unit(s) kept."
    )


def _from_scan(artifact_id: str, found: scan.Finding, severity: str | None = None,
               note: str = "") -> Finding:
    severity = severity or SCAN_SEVERITY.get(found.severity, "critical")
    location, where = _location(found.path, found.line)
    explanation = _clean(f"{found.rule}: {where}{found.message}{note}")
    return Finding(artifact_id, "safety", severity, location, explanation[:MAX_EXPLANATION])


def _location(path: str, line: int) -> tuple[Location, str]:
    """The scan's place as a model Location; one the model cannot hold (a withheld or escaped
    path it refuses) becomes the artifact as a whole, and the explanation says so."""
    lines = (line, line) if isinstance(line, int) and line >= 1 else (None, None)
    try:
        return Location(path, *lines), ""
    except ValueError:
        return Location("."), "(at a path that cannot be recorded) "


def _clean(text: str) -> str:
    """Text as the model can store it: anything UTF-8 cannot hold becomes '?'."""
    return text.encode("utf-8", "replace").decode("utf-8")


def _error_type(failure: str) -> str:
    return _clean(failure.partition(":")[0].strip() or "an error")


def finding_order(finding: Finding) -> tuple:
    """Most severe first, then safety before quality (the model's order of categories), then
    by place."""
    return (
        -SEVERITIES.index(finding.severity), FINDING_CATEGORIES.index(finding.category),
        *_place(finding.location), finding.explanation, finding.id,
    )


def _place(location: Location) -> tuple:
    return (location.path, location.line_start or 0, location.line_end or 0)


def _unit_order(unit: Unit) -> tuple:
    return (*_place(unit.location), unit.kind, unit.title, unit.id)


# --- the content digest of a directory --------------------------------------------------------


class TreeTooLarge(ValueError):
    """The tree is past the bounds tree_digest reads, so it cannot be pinned."""


def tree_digest(root: str | os.PathLike[str], *, max_entries: int = MAX_TREE_ENTRIES,
                max_bytes: int = MAX_TREE_BYTES, max_depth: int = MAX_TREE_DEPTH) -> str:
    """The content digest of the directory at root, as "sha256:<hex>": every entry in order of
    its relative path's bytes, each framed with its type — a file by the SHA-256 of its bytes,
    a symbolic link by its target (never followed), a directory and anything else by its name
    alone (file modes are not part of it: intake pins a copy before it seals its modes). Nothing
    about the machine, the clock or where the tree is goes in, so the same tree gives the same
    digest anywhere. Past max_entries entries, max_bytes bytes of content or max_depth folders
    inside folders it raises TreeTooLarge; a file that cannot be read, or a folder or file that
    is no longer the one listed, raises OSError: a digest never stands for content it did not
    read.

    Each folder is opened relative to the descriptor of the folder it was listed in, and checked
    to be the very one listed, and each file and link relative to its folder's, so no path is
    resolved twice and none is longer than one name: a tree deeper than the system's longest
    path is read like any other, up to max_depth. Where the platform cannot list by descriptor,
    paths from the root are used, with the same checks."""
    base = os.fsencode(os.fspath(root))
    if os.path.islink(base) or not os.path.isdir(base):
        raise NotADirectoryError(os.fsdecode(base))
    walk = _TreeWalk(base, max_entries, max_bytes, max_depth)
    if _FD_WALK:
        fd = os.open(base, _DIR_FLAGS)
        try:
            walk.folder(fd, b"", 0)
        finally:
            os.close(fd)
    else:
        walk.folder(None, b"", 0)
    whole = hashlib.sha256(_TREE_DIGEST_VERSION)
    for rel, kind, held in sorted(walk.records):
        whole.update(kind + len(rel).to_bytes(8, "big") + rel + held)
    return "sha256:" + whole.hexdigest()


class _TreeWalk:
    """The records of one tree_digest: (relative path, type, what it holds)."""

    def __init__(self, base: bytes, max_entries: int, max_bytes: int, max_depth: int) -> None:
        self.base = base
        self.max_entries, self.max_bytes, self.max_depth = max_entries, max_bytes, max_depth
        self.records: list[tuple[bytes, bytes, bytes]] = []
        self.spent = 0

    def folder(self, fd: int | None, rel_dir: bytes, depth: int) -> None:
        path = os.path.join(self.base, rel_dir) if rel_dir else self.base
        with os.scandir(fd if fd is not None else path) as listing:
            entries = list(listing)
        for entry in entries:
            if len(self.records) >= self.max_entries:
                raise TreeTooLarge(f"more than {self.max_entries} entries: too large to pin")
            name = os.fsencode(entry.name)
            rel = rel_dir + b"/" + name if rel_dir else name
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                target = (os.readlink(name, dir_fd=fd) if fd is not None
                          else os.readlink(os.path.join(path, name)))
                self.records.append((rel, b"L", len(target).to_bytes(8, "big") + target))
            elif stat.S_ISDIR(info.st_mode):
                self.records.append((rel, b"D", b""))
                if depth + 1 > self.max_depth:
                    raise TreeTooLarge(f"folders more than {self.max_depth} deep: too deep to pin")
                self.child(fd, path, name, rel, _ident(info), depth + 1)
            elif stat.S_ISREG(info.st_mode):
                content, size = _file_digest(name, fd, path, self.max_bytes - self.spent,
                                             self.max_bytes, _ident(info))
                self.spent += size
                self.records.append((rel, b"F", content))
            else:
                self.records.append((rel, b"O", b""))

    def child(self, fd: int | None, path: bytes, name: bytes, rel: bytes,
              ident: tuple[int, int], depth: int) -> None:
        if fd is None:
            inner_path = os.path.join(path, name)
            if _ident(os.lstat(inner_path)) != ident:
                raise OSError("a folder changed while the tree was being read")
            self.folder(None, rel, depth)
            return
        inner = os.open(name, _DIR_FLAGS, dir_fd=fd)
        try:
            if _ident(os.fstat(inner)) != ident:
                raise OSError("a folder changed while the tree was being read")
            self.folder(inner, rel, depth)
        finally:
            os.close(inner)


_FD_WALK = (
    os.scandir in os.supports_fd and os.open in os.supports_dir_fd
    and os.readlink in os.supports_dir_fd and hasattr(os, "O_DIRECTORY")
)
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)


def _ident(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _file_digest(name: bytes, dir_fd: int | None, folder: bytes, allowance: int,
                 limit: int, ident: tuple[int, int] | None = None) -> tuple[bytes, int]:
    if dir_fd is not None:
        fd = os.open(name, _FILE_FLAGS, dir_fd=dir_fd)
    else:
        fd = os.open(os.path.join(folder, name), _FILE_FLAGS)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (ident is not None and _ident(info) != ident):
            raise OSError(f"{os.fsdecode(name)} is no longer the file that was listed")
        content = hashlib.sha256()
        size = 0
        while chunk := os.read(fd, _CHUNK):
            size += len(chunk)
            if size > allowance:
                raise TreeTooLarge(f"more than {limit} bytes of content: too large to pin")
            content.update(chunk)
        return content.digest(), size
    finally:
        os.close(fd)
