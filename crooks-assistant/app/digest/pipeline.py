"""The Knowledge Digester in one call: from a quarantined directory to a stored digest.

    result = digest(root, source, store)

runs the library stages of KNOWLEDGE_DIGESTER_V1.md section 3 in order, on a copy that is
already in quarantine and already pinned by its Source:

1. Recognise: detect.detect_kinds names every kind the tree is, with evidence and a census.
   A recogniser that failed becomes a quality finding.
2. Scan: scan.scan_tree reads the tree for what it would do to us. Each of its findings
   becomes a model Finding in the "safety" category, its severity mapped by SCAN_SEVERITY.
   A block-severity finding stops the artifact here, before decomposition: the Artifact is
   returned (and stored) with its findings and no Units.
3. Decompose: every adapter in the app.digest.adapters namespace whose HANDLES meet the
   detected kinds reads the tree into Units. Adapters are discovered with
   pkgutil.iter_modules at every call, never from a list kept here, so a module dropped
   into the namespace is used from the next digest on. An adapter that raises, or returns
   something that is not its artifact's Units, is contained: a quality finding names it and
   the others carry on. Units are de-duplicated by id and sorted by place.

Digesting is reading. Nothing here, and nothing it calls, executes, imports or installs what
the artifact holds; there is no network; the same tree and Source give the same result.

Why a result object and not a bare Artifact: the model's Artifact is the Source, the kinds and
the Units, and the store keeps findings beside it rather than in it. What a caller (the report,
the command line, the next stages) also needs from one digest — its findings, detect's evidence
and census, which adapters ran, whether it was blocked — is gathered in DigestResult, whose
``artifact`` is exactly what the store holds.

tree_digest(root) is the content digest a Source records for a directory: stable across
machines, walk order and time, symbolic links named and never followed, and bounded.
"""

from __future__ import annotations

import hashlib
import importlib
import os
import pkgutil
import re
import stat
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from app.digest import detect, scan
from app.digest.model import (
    ARTIFACT_KINDS,
    MAX_EXPLANATION,
    SEVERITIES,
    Artifact,
    Finding,
    Location,
    Source,
    Unit,
)
from app.digest.store import DigestStore

ADAPTERS_PACKAGE = "app.digest.adapters"

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

# Bounds on tree_digest: past either, the tree cannot be pinned and is refused.
MAX_TREE_ENTRIES = 50_000                # files, directories, links and the rest, as detect
MAX_TREE_BYTES = 1 << 30                 # file content hashed, in all
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
class DigestResult:
    """One digest: the Artifact as the store keeps it, and what was found on the way."""

    artifact: Artifact
    findings: tuple[Finding, ...]            # most severe first, then by place
    detections: tuple[detect.Detection, ...]  # detect's own, most confident first
    census: detect.Census
    adapters: tuple[str, ...]                # the adapters that ran, by NAME, in the order run
    blocked: bool                            # stopped before decomposition by a block finding

    @property
    def units(self) -> tuple[Unit, ...]:
        return self.artifact.units


def digest(root: str | os.PathLike[str], source: Source,
           store: DigestStore | None = None) -> DigestResult:
    """Recognise, scan and decompose the quarantined directory at root, as the artifact source
    names, and write the source, artifact, units and findings to store when one is given.

    source.content_digest is the caller's pin and is not recomputed here (tree_digest gives it
    for a directory). A root that is not a directory, or is a symbolic link, is refused with
    NotADirectoryError. Writing an artifact whose id the store already holds as a different
    record raises store.ArtifactConflict; the same record again changes nothing."""
    if not isinstance(source, Source):
        raise ValueError("a digest needs the artifact's Source")
    if store is not None and not isinstance(store, DigestStore):
        raise ValueError("store must be a DigestStore")
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
    blocked = False
    for found in scan.scan_tree(base):
        blocked = blocked or found.severity not in (scan.INFO, scan.WARN)
        keep(_from_scan(artifact_id, found))

    # 3. decompose, unless blocked
    units: dict[str, Unit] = {}
    ran: list[str] = []
    if not blocked:
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
            made, problem = _run(adapter, base, artifact_id)
            for unit in made:
                units.setdefault(unit.id, unit)
            if problem:
                keep(Finding(
                    artifact_id, "quality", ADAPTER_FAILURE_SEVERITY, Location("."),
                    f"digest.adapter: the '{_clean(adapter.name)}' adapter {problem}",
                ))

    artifact = Artifact(source=source, kinds=kinds, units=tuple(sorted(units.values(), key=_unit_order)))
    ordered = tuple(sorted(findings.values(), key=finding_order))
    if store is not None:
        store.put(artifact)
        for finding in ordered:
            store.add_finding(finding)
    return DigestResult(
        artifact=artifact, findings=ordered, detections=detection.kinds,
        census=detection.census, adapters=tuple(ran), blocked=blocked,
    )


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


def _from_scan(artifact_id: str, found: scan.Finding) -> Finding:
    severity = SCAN_SEVERITY.get(found.severity, "critical")
    location, where = _location(found.path, found.line)
    explanation = _clean(f"{found.rule}: {where}{found.message}")
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
    """Most severe first, then safety before quality, then by place."""
    return (
        -SEVERITIES.index(finding.severity), finding.category, *_place(finding.location),
        finding.explanation, finding.id,
    )


def _place(location: Location) -> tuple:
    return (location.path, location.line_start or 0, location.line_end or 0)


def _unit_order(unit: Unit) -> tuple:
    return (*_place(unit.location), unit.kind, unit.title, unit.id)


# --- the content digest of a directory --------------------------------------------------------


class TreeTooLarge(ValueError):
    """The tree is past the bounds tree_digest reads, so it cannot be pinned."""


def tree_digest(root: str | os.PathLike[str], *, max_entries: int = MAX_TREE_ENTRIES,
                max_bytes: int = MAX_TREE_BYTES) -> str:
    """The content digest of the directory at root, as "sha256:<hex>": every entry in order of
    its relative path's bytes, each framed with its type — a file by the SHA-256 of its bytes,
    a symbolic link by its target (never followed), a directory and anything else by its name
    alone. Nothing about the machine, the clock or where the tree is goes in, so the same tree
    gives the same digest anywhere. Past max_entries entries or max_bytes bytes of content it
    raises TreeTooLarge; a file that cannot be read, or a directory that is no longer the one
    listed, raises OSError: a digest never stands for content it did not read.

    As in scan.py, directories are listed through descriptors checked to be the very ones that
    were listed, and files and links are opened relative to them, so no path is resolved twice."""
    base = os.fsencode(os.fspath(root))
    if os.path.islink(base) or not os.path.isdir(base):
        raise NotADirectoryError(os.fsdecode(base))
    records: list[tuple[bytes, bytes, bytes]] = []    # relative path, type, what it holds
    spent = 0
    pending: list[tuple[bytes, tuple[int, int] | None]] = [(b"", None)]
    while pending:
        rel_dir, ident = pending.pop()
        path = os.path.join(base, rel_dir) if rel_dir else base
        fd = _open_dir(path, ident)
        try:
            with os.scandir(fd if fd is not None else path) as listing:
                for entry in listing:
                    if len(records) >= max_entries:
                        raise TreeTooLarge(f"more than {max_entries} entries: too large to pin")
                    name = os.fsencode(entry.name)
                    rel = rel_dir + b"/" + name if rel_dir else name
                    if entry.is_symlink():
                        target = (os.readlink(name, dir_fd=fd) if fd is not None
                                  else os.readlink(os.path.join(path, name)))
                        records.append((rel, b"L", len(target).to_bytes(8, "big") + target))
                    elif entry.is_dir(follow_symlinks=False):
                        records.append((rel, b"D", b""))
                        pending.append((rel, _ident(entry.stat(follow_symlinks=False))))
                    elif entry.is_file(follow_symlinks=False):
                        content, size = _file_digest(name, fd, path, max_bytes - spent, max_bytes)
                        spent += size
                        records.append((rel, b"F", content))
                    else:
                        records.append((rel, b"O", b""))
        finally:
            if fd is not None:
                os.close(fd)
    whole = hashlib.sha256(_TREE_DIGEST_VERSION)
    for rel, kind, held in sorted(records):
        whole.update(kind + len(rel).to_bytes(8, "big") + rel + held)
    return "sha256:" + whole.hexdigest()


_FD_WALK = (
    os.scandir in os.supports_fd and os.open in os.supports_dir_fd
    and os.readlink in os.supports_dir_fd and hasattr(os, "O_DIRECTORY")
)
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)


def _ident(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _open_dir(path: bytes, ident: tuple[int, int] | None) -> int | None:
    """A descriptor for the directory, checked to be the one that was listed; None where the
    platform cannot list by descriptor, after the same check by path."""
    if not _FD_WALK:
        if ident is not None and _ident(os.lstat(path)) != ident:
            raise OSError(f"{os.fsdecode(path)} changed while the tree was being read")
        return None
    fd = os.open(path, _DIR_FLAGS)
    try:
        if ident is not None and _ident(os.fstat(fd)) != ident:
            raise OSError(f"{os.fsdecode(path)} changed while the tree was being read")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _file_digest(name: bytes, dir_fd: int | None, folder: bytes, allowance: int,
                 limit: int) -> tuple[bytes, int]:
    if dir_fd is not None:
        fd = os.open(name, _FILE_FLAGS, dir_fd=dir_fd)
    else:
        fd = os.open(os.path.join(folder, name), _FILE_FLAGS)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(f"{os.fsdecode(name)} is no longer a regular file")
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
