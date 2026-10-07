"""The skill installer: the digester's approved skills, adopted whole (OWNER_DECISIONS_2026-09-30,
"The owner's curated skill list is the owner's decision"; SOURCE_ASSIMILATION_V1.md section 3).

    outcomes = install(store, quarantine_root, artifact_id, skills_dir)

reads the artifact's records in the digest store (never writing them) and installs each approved
skill from its quarantined copy into skills_dir:

    <skills_dir>/<name>/skill/...        the skill folder, byte for byte (files 0444, folders 0555)
    <skills_dir>/<name>/licence/...      the licence file, and a NOTICE beside it, when it lies
                                         outside the skill folder
    <skills_dir>/<name>/provenance.json  where it came from, what it is, who approved it

What is approved, per skill (one SKILL.md knowledge unit tagged skill:<name>): the last owner
decision in the ledger for its unit wins — builder_skill approves it (approved_by "owner"), any
other target withholds it. With no decision, CLIVE's latest proposal for it approves it
(approved_by "curated") only when it is a builder_skill proposal in propose's own shape whose
curated sentence (propose.CURATED) ends CLIVE's why, read forwards from its one
" Target builder_skill: " to the first label propose writes after it, and which does not say it
needs the owner: the artifact's own words (its title before that marker, the paths it chose
after the why) can never make a skill curated.

For each approved skill, in order: the quarantined copy is verified against the stored content
digest (or nothing of the artifact is installed); the skill is refused as held when the artifact
was blocked or a high or critical finding lies in its folder; refused as the owner's when
anything in it would run on its own or brings a key (OWNER_RULES, a hooks key in its front
matter, allowed-tools granting a shell tool, a !`command` line, a link, special or hard-linked
file, a licence that forbids reuse); deferred when it carries scripts, which wait for a sandboxed
script route; and otherwise copied into a private staging folder, scanned again, checked byte
for byte against the quarantined folder, given its licence and provenance.json, and renamed
into place in one step that never replaces anything (renameat2 with RENAME_NOREPLACE; held
where that is not available), so a reader never sees half an install. The same skill again
writes nothing; another skill under an installed name is a conflict, and nothing is
overwritten.

Nothing from a skill is executed, imported or installed anywhere else, and there is no network.
No third-party skill content may go into git: a skills_dir inside the repository is refused
unless it is under crooks-assistant/.state/, which .gitignore ignores."""

from __future__ import annotations

import contextlib
import ctypes
import errno
import hashlib
import json
import os
import posixpath
import re
import stat
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any

from app.digest import propose, scan
from app.digest.adapters.skills import SCRIPT_SUFFIXES
from app.digest.adapters.skills import _front_matter as _skill_front_matter
from app.digest.intake import remove_tree
from app.digest.model import DECIDER, Absorption, Artifact, Finding, Source, Unit, utc_now
from app.digest.pipeline import tree_digest
from app.digest.store import DigestStore

APP_ROOT = Path(__file__).resolve().parents[2]      # crooks-assistant
REPOSITORY = APP_ROOT.parent
STATE_DIR = APP_ROOT / ".state"                      # ignored by crooks-assistant/.gitignore
DEFAULT_SKILLS_DIR = STATE_DIR / "skills"

SCHEMA = "clive.skill_install.v1"
ROUTE = "instructions"
NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"
PROVENANCE_FILE = "provenance.json"
SKILL_DIR = "skill"
LICENCE_DIR = "licence"
NOTICE_FILES = ("NOTICE", "NOTICE.txt", "NOTICE.md")
SKILL_FILE = "SKILL.md"
STAGING_PREFIX = ".staging-"
TRASH_PREFIX = ".trash-"

MAX_FILES = 1_000                  # files in one skill
MAX_BYTES = 50 * 1024 * 1024       # bytes in one skill
MAX_DEPTH = 64                     # folders inside folders in one skill
MAX_FIELD = 1_024                  # characters of description and allowed_tools kept
MAX_NAMED = 5                      # files named when a skill is deferred
MAX_PROVENANCE = 4 * 1024 * 1024   # bytes of provenance.json read back

TARGET = "builder_skill"
MARKER = f" Target {TARGET}: "
# The labels propose._reasoning writes after a proposal's why, in this order when present; the
# first of them after the marker ends the why. A builder skill's why is CLIVE's own fixed words
# (and propose.CURATED, when curated); what follows it can quote the artifact: the Licence clause
# names the file that declares the licence, a path the artifact chose.
NEEDS_OWNER_LABEL = f" {propose.NEEDS_OWNER}: "
AFTER_WHY = (NEEDS_OWNER_LABEL, " Licence: ", " Hypothesis: ")
HOLDING = frozenset(("high", "critical"))
CREDENTIAL_RULES = "secret."
# Stored findings that make a skill the owner's: something in it would run on its own.
OWNER_RULES = frozenset((
    "execute.git_hook", "execute.git_config", "execute.install_script", "execute.build",
    "execute.startup", "execute.agent_settings", "execute.agent_hook", "execute.mcp",
    "execute.devcontainer", "execute.editor_task", "execute.ci", "execute.binary",
    "execute.agent_permissions",
))
# Stored findings that say a skill carries scripts: it waits for a sandboxed script route.
SCRIPT_RULES = frozenset((
    "execute.script", "execute.notebook", "execute.notebook_script", "execute.makefile",
))
_HOOKS_KEY = re.compile(r"""[ \t]*["']?hooks["']?[ \t]*:""", re.I)
_COMMAND = "!`"                    # Claude Code runs !`command` before the model reads the skill
# allowed-tools (or allowed_tools, in any case), and what follows it on its line.
_ALLOWED_TOOLS_KEY = re.compile(r"""[ \t]*["']?allowed[-_]tools["']?[ \t]*:(.*)""", re.I)
# The move that never replaces: Linux's renameat2 with RENAME_NOREPLACE (glibc 2.28 or later).
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1

# Outcomes, and why a skill was refused or deferred.
INSTALLED = "installed"
ALREADY = "already installed"
REFUSED = "refused"
DEFERRED = "deferred"
NOT_APPROVED = "not approved"
HELD = "held"
OWNER = "owner"
CONFLICT = "conflict"
NAME = "name"
SCRIPTS = "scripts"
# Why every skill of a blocked artifact is held.
BLOCKED = "the artifact was blocked in quarantine"

_DIR_FLAGS = (os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
              | getattr(os, "O_CLOEXEC", 0))
_FILE_FLAGS = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
               | getattr(os, "O_CLOEXEC", 0))
_WRITE_FLAGS = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0))
_CHUNK = 1 << 20


# --- failures and outcomes ----------------------------------------------------------------------


class InstallError(Exception):
    """The install could not run: no such artifact, or nowhere it may write."""


class SkillsDirRefused(InstallError):
    """The skills directory is inside the repository but outside crooks-assistant/.state/."""


class CopyMismatch(InstallError):
    """The quarantined copy is missing, a link, or no longer the stored content digest."""


class UninstallRefused(Exception):
    """What is under the name is not an install: a link, or a folder without provenance.json."""


class _Refused(Exception):
    def __init__(self, kind: str, reason: str) -> None:
        super().__init__(reason)
        self.kind = kind
        self.reason = reason


@dataclass(frozen=True)
class Outcome:
    """What install did with one skill. `name` and `reason` may quote the artifact: show them
    through intake.shown and scan.redact. `kind` says why it was refused (held, owner, conflict
    or name) or deferred (scripts); `files` names up to MAX_NAMED files of a deferred skill."""

    name: str
    status: str
    reason: str = ""
    kind: str = ""
    files: tuple[str, ...] = ()
    approved_by: str | None = None       # "owner", "curated", or None when not approved
    unit_id: str = ""
    path: Path | None = None             # skills_dir/<name>, once installed

    @property
    def approved(self) -> bool:
        return self.approved_by is not None


@dataclass(frozen=True)
class Removal:
    """What uninstall did: whether anything was removed, and whether its bytes still matched
    its provenance (None when nothing was installed under the name)."""

    name: str
    removed: bool
    matched: bool | None


@dataclass(frozen=True)
class Approval:
    """One skill of the artifact and whether it is approved: by whom, on which records."""

    unit: Unit
    name: str
    approved_by: str | None
    proposal_id: str | None
    decision_id: str | None
    reason: str = ""


# --- what is approved ---------------------------------------------------------------------------


def skill_name(unit: Unit) -> str | None:
    """The skill a unit is, when it is a skill's SKILL.md knowledge unit tagged skill:<name>."""
    if unit.kind != "knowledge" or "unparsed" in unit.tags:
        return None
    if PurePosixPath(unit.location.path).name != SKILL_FILE:
        return None
    return next((tag[len(propose.SKILL_TAG):] for tag in unit.tags
                 if tag.startswith(propose.SKILL_TAG)), None)


def is_curated(proposal: Absorption) -> bool:
    """Whether a proposal is CLIVE's curated builder skill: its reasoning holds " Target
    builder_skill: " exactly once; CLIVE's why, from there to the first of AFTER_WHY, ends with
    propose.CURATED; that first label is not "Needs the owner"; and propose.explain finds its
    Hypothesis, Measure and Removal, with nothing saying it needs the owner.

    Read forwards from the one marker, because the artifact's words stand on both sides of
    CLIVE's: its title before the marker, and paths it chose after the why. Read backwards, as
    propose.explain reads, a skill folder called "x Needs the owner:  Licence: <CURATED>" or
    "x Target builder_skill: <CURATED> Hypothesis: a Measure: b Removal: c" made a proposal that
    needs the owner read as curated."""
    if proposal.is_decision or proposal.target != TARGET:
        return False
    text = proposal.reasoning
    if text.count(MARKER) != 1:
        return False
    after = text[text.index(MARKER) + len(MARKER):]
    ends = [at for at in (after.find(label) for label in AFTER_WHY) if at >= 0]
    if not ends:
        return False
    why_ends = min(ends)
    if not after[:why_ends].endswith(propose.CURATED) or after.startswith(NEEDS_OWNER_LABEL, why_ends):
        return False
    parts = propose.explain(proposal)
    return bool(parts.hypothesis and parts.measure and parts.removal) and not propose.needs_owner(proposal)


def approvals(artifact: Artifact, ledger: Iterable[Absorption]) -> list[Approval]:
    """Each skill of the artifact, in the order of its units, and whether it is approved."""
    ledger = tuple(ledger)
    out: list[Approval] = []
    for unit in artifact.units:
        name = skill_name(unit)
        if name is None:
            continue
        records = [record for record in ledger if record.unit_id == unit.id]
        decisions = [record for record in records if record.decided_by == DECIDER]
        proposals = [record for record in records if not record.is_decision]
        proposal = next((p for p in reversed(proposals) if p.target == TARGET), None)
        proposal_id = proposal.id if proposal is not None else None
        if decisions:
            last = decisions[-1]
            if last.target == TARGET:
                out.append(Approval(unit, name, DECIDER, proposal_id, last.id))
            else:
                out.append(Approval(unit, name, None, proposal_id, last.id,
                                    f"the owner decided {last.target}"))
            continue
        latest = proposals[-1] if proposals else None
        if latest is None:
            reason = "nothing is proposed or decided for it"
        elif latest.target != TARGET:
            reason = f"CLIVE proposes {latest.target}, not a builder skill"
        elif not is_curated(latest):
            reason = "its builder_skill proposal is not curated, and the owner has not decided it"
        else:
            out.append(Approval(unit, name, "curated", latest.id, None))
            continue
        out.append(Approval(unit, name, None, proposal_id, None, reason))
    return out


# --- where skills go ----------------------------------------------------------------------------


def check_skills_dir(skills_dir: str | os.PathLike[str]) -> Path:
    """The skills directory, refused (SkillsDirRefused) when it is inside the repository but not
    under crooks-assistant/.state/: no third-party skill content may ever go into git. A .state
    that is a link (or reached through one) is not the git-ignored folder, so it allows nothing:
    pointed into a tracked folder, it would put skills where they could be committed."""
    resolved = Path(skills_dir).resolve()
    repository = REPOSITORY.resolve()
    state = STATE_DIR.resolve()
    inside = resolved == repository or repository in resolved.parents
    if inside and (STATE_DIR.is_symlink() or state != STATE_DIR.absolute()):
        raise SkillsDirRefused(
            f"the skills directory {resolved} is inside the repository and {STATE_DIR} is a link, "
            "not the real git-ignored folder, so no third-party skill can be put there"
        )
    if inside and state not in resolved.parents:
        raise SkillsDirRefused(
            f"the skills directory {resolved} is inside the repository; put it under {STATE_DIR} "
            "(git-ignored) or outside the repository, so no third-party skill can be committed"
        )
    return Path(skills_dir)


# --- install ------------------------------------------------------------------------------------


def install(store: DigestStore | str | os.PathLike[str], quarantine_root: str | os.PathLike[str],
            artifact_id: str, skills_dir: str | os.PathLike[str] = DEFAULT_SKILLS_DIR,
            only: Iterable[str] | None = None, *,
            on_outcome: Callable[[Outcome], None] | None = None) -> list[Outcome]:
    """Install the artifact's approved skills (only those named, when `only` is given) into
    skills_dir, one Outcome per skill (see the module's docstring). Raises SkillsDirRefused
    before anything is written, InstallError when the store has no such artifact, and
    CopyMismatch when its quarantined copy is not the one the store pinned.

    A blocked artifact is never decomposed, so it has no skills to name: it is one Outcome,
    refused as held (one per name asked for, when `only` is given), never an empty list that
    reads as nothing to do. on_outcome, when given, is told each Outcome as it is settled, so a
    failure part way (a disk that fills) still leaves what was already installed said."""
    skills_dir = check_skills_dir(skills_dir)
    store = store if isinstance(store, DigestStore) else DigestStore(store)
    try:
        artifact = store.load(artifact_id)
        findings = store.findings(artifact_id)
        ledger = store.absorptions(artifact_id)
    except (FileNotFoundError, ValueError) as error:
        raise InstallError(str(error)) from None
    copy = _verified_copy(Path(quarantine_root), artifact)
    wanted = None if only is None else list(dict.fromkeys(only))
    found = approvals(artifact, ledger)
    # The pipeline records every block as a critical finding, and decomposes nothing after one.
    blocked = any(finding.severity == "critical" for finding in findings)
    outcomes: list[Outcome] = []

    def settled(outcome: Outcome) -> None:
        outcomes.append(outcome)
        if on_outcome is not None:
            on_outcome(outcome)

    if blocked and not found:
        for name in wanted or [artifact.id]:
            settled(Outcome(name, REFUSED, f"{BLOCKED}: nothing of it was decomposed, so none of "
                                           "its skills can be installed", kind=HELD))
        return outcomes
    licences: dict[str, tuple[str, str]] | None = None
    for approval in found:
        if wanted is not None and approval.name not in wanted:
            continue
        if approval.approved_by is None:
            settled(Outcome(approval.name, NOT_APPROVED, approval.reason, unit_id=approval.unit.id))
            continue
        if licences is None:
            licences = scan.licence_map(copy)
        settled(_install_skill(copy, artifact, findings, blocked, licences, approval, skills_dir))
    for name in wanted or ():
        if not any(approval.name == name for approval in found):
            settled(Outcome(name, NOT_APPROVED, "the artifact has no skill by that name"))
    return outcomes


def _verified_copy(quarantine_root: Path, artifact: Artifact) -> Path:
    copy = quarantine_root / artifact.id
    if os.path.islink(copy) or not copy.is_dir():
        raise CopyMismatch(f"there is no quarantined copy of {artifact.id} at {copy} (or it is a "
                           "link): nothing of the artifact is installed")
    try:
        digest = tree_digest(copy)
    except (OSError, ValueError) as error:
        raise CopyMismatch(f"the quarantined copy of {artifact.id} could not be read "
                           f"({type(error).__name__}): nothing of the artifact is installed") from None
    if digest != artifact.source.content_digest:
        raise CopyMismatch(f"the quarantined copy of {artifact.id} is {digest}, not the stored "
                           f"{artifact.source.content_digest}: nothing of the artifact is installed")
    return copy


def _install_skill(copy: Path, artifact: Artifact, findings: tuple[Finding, ...], blocked: bool,
                   licences: dict[str, tuple[str, str]], approval: Approval,
                   skills_dir: Path) -> Outcome:
    outcome = Outcome(approval.name, REFUSED, approved_by=approval.approved_by,
                      unit_id=approval.unit.id)
    try:
        return _install_checked(copy, artifact, findings, blocked, licences, approval,
                                skills_dir, outcome)
    except _Refused as refused:
        return replace(outcome, status=REFUSED, kind=refused.kind, reason=refused.reason)


def _install_checked(copy: Path, artifact: Artifact, findings: tuple[Finding, ...], blocked: bool,
                     licences: dict[str, tuple[str, str]], approval: Approval, skills_dir: Path,
                     outcome: Outcome) -> Outcome:
    name = approval.name
    if not re.fullmatch(NAME_PATTERN, name):
        raise _Refused(NAME, f"its name '{name}' is not one a skill folder may have "
                             f"({NAME_PATTERN})")
    skill_md = approval.unit.location.path
    folder = posixpath.dirname(skill_md)
    inside = [finding for finding in findings if _finding_in(finding, folder)]

    # held: a hold, a licence that forbids reuse, a changed file
    if blocked:
        raise _Refused(HELD, BLOCKED)
    for finding in inside:
        if finding.severity in HOLDING:
            raise _Refused(HELD, f"a {finding.severity} finding in its folder "
                                 f"({_rule(finding)} at {finding.location.path})")

    # the owner's: anything that would run on its own, or brings a key
    for finding in inside:
        rule = _rule(finding)
        if rule.startswith(CREDENTIAL_RULES) or rule in OWNER_RULES:
            raise _Refused(OWNER, f"{rule} at {finding.location.path}")
    survey = _survey(copy, folder)
    for found, what in ((survey.links, "a symbolic link"), (survey.specials, "a special file"),
                        (survey.hardlinked, "a hard-linked file")):
        if found:
            raise _Refused(OWNER, f"{what} in its folder: {_in_artifact(folder, found[0])}")
    if survey.unnamed:
        raise _Refused(OWNER, "a file name in its folder is not UTF-8")
    for rel, data in survey.files.items():
        if posixpath.basename(rel).lower() != SKILL_FILE.lower():
            continue
        lines = _text_lines(data)
        if any(_HOOKS_KEY.match(line) for line in _front_matter_lines(lines)):
            raise _Refused(OWNER, f"a hooks key in the front matter of {_in_artifact(folder, rel)}")
        shell = _shell_grants(_front_matter_lines(lines))
        if shell:
            raise _Refused(OWNER, f"allowed-tools granting {', '.join(shell)} in the front matter of "
                                  f"{_in_artifact(folder, rel)}, which lets every builder that loads "
                                  "it run commands without asking")
        number = next((n for n, line in enumerate(lines, 1) if _COMMAND in line), 0)
        if number:
            raise _Refused(OWNER, f"a !`command` on line {number} of {_in_artifact(folder, rel)}, "
                                  "which Claude Code would run before the model reads the skill")
    expression, declared_in = _licence(licences, skill_md, artifact.source)
    if scan.licence_rank(expression) == 2:
        raise _Refused(OWNER, f"its licence ({expression}) forbids reuse")

    # deferred: scripts wait for a sandboxed script route
    scripts = {finding.location.path for finding in inside if _rule(finding) in SCRIPT_RULES}
    for rel, data in survey.files.items():
        if (PurePosixPath(rel).suffix.lower() in SCRIPT_SUFFIXES or data.startswith(b"#!")
                or survey.modes[rel] & 0o111):
            scripts.add(_in_artifact(folder, rel))
    if scripts:
        return replace(outcome, status=DEFERRED, kind=SCRIPTS, files=tuple(sorted(scripts)[:MAX_NAMED]),
                       reason="it carries scripts, which wait for a sandboxed script route")

    try:
        digest = tree_digest(copy / folder if folder else copy)
    except (OSError, ValueError) as error:
        raise _Refused(HELD, f"its quarantined folder could not be read ({type(error).__name__})") from None
    final = skills_dir / name
    if os.path.lexists(final):
        if _same_install(final, name, digest, artifact.id, approval.unit.id):
            return replace(outcome, status=ALREADY, path=final)
        raise _Refused(CONFLICT, f"{final} already holds something else; nothing is overwritten")

    copies = _licence_copies(copy, declared_in, folder)
    description, allowed_tools = _front_matter_fields(survey.files.get(posixpath.basename(skill_md)))
    record = {
        "schema": SCHEMA,
        "name": name,
        "description": description,
        "route": ROUTE,
        "installed_at": "",
        "source": {
            "origin": artifact.source.origin,
            "origin_kind": artifact.source.origin_kind,
            "pinned_ref": artifact.source.pinned_ref,
            "content_digest": artifact.source.content_digest,
            "taken_at": artifact.source.taken_at,
        },
        "skill": {"path_in_artifact": folder or ".", "digest": digest, "files": []},
        "licence": {"expression": expression, "declared_in": declared_in, "copied": []},
        "digest_record": {
            "artifact_id": artifact.id,
            "unit_id": approval.unit.id,
            "proposal_id": approval.proposal_id,
            "decision_id": approval.decision_id,
            "approved_by": approval.approved_by,
        },
        "allowed_tools": allowed_tools,
    }
    _stage(skills_dir, final, survey, digest, copies, record)
    return replace(outcome, status=INSTALLED, path=final)


def _rule(finding: Finding) -> str:
    """The scan rule a finding records: its explanation's text before the first ':'."""
    return finding.explanation.split(":", 1)[0].strip()


def _inside(path: str, folder: str) -> bool:
    return not folder or path == folder or path.startswith(folder + "/")


def _finding_in(finding: Finding, folder: str) -> bool:
    """Whether a finding lies in the folder. One about the artifact as a whole ("."), which
    may be at a path that could not be recorded, lies in every folder."""
    return finding.location.path == "." or _inside(finding.location.path, folder)


def _in_artifact(folder: str, rel: str) -> str:
    return f"{folder}/{rel}" if folder else rel


def _text_lines(data: bytes) -> list[str]:
    text = data.decode("utf-8", "replace").removeprefix("﻿")
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _front_matter_lines(lines: list[str]) -> list[str]:
    """The lines of a SKILL.md's front matter, as far as the first closing "---"; all of the file
    when it is opened and never closed. A "..." line does not end it here, though YAML and the
    adapter end a document there: a reader that closes front matter only on "---" takes the lines
    after it as front matter too, so a hooks key placed after a "..." is still a hooks key. Where
    two readers could disagree, the one that sees more is the one that counts."""
    if not lines or lines[0].strip() != "---":
        return []
    for end in range(1, len(lines)):
        if lines[end].strip() == "---":
            return lines[1:end]
    return lines[1:]


def _shell_grants(front_matter: list[str]) -> list[str]:
    """The shell tools an allowed-tools key in the front matter grants (scan._SHELL_TOOL's
    shapes: Bash, Shell, PowerShell or Terminal, bare or with a pattern, in any case), its value
    written inline, as a flow list or as a block list below the key. scan reads only the inline
    form; here every line below the key that is indented or a list item is its value too."""
    grants: list[str] = []
    for at, line in enumerate(front_matter):
        key = _ALLOWED_TOOLS_KEY.match(line)
        if key is None:
            continue
        value = [key.group(1)]
        for below in front_matter[at + 1:]:
            if below and below[0] not in " \t-":
                break
            value.append(below)
        grants += scan._SHELL_TOOL.findall("\n".join(value))
    return list(dict.fromkeys(grants))


def _front_matter_fields(data: bytes | None) -> tuple[str | None, str | None]:
    """The description and allowed-tools of SKILL.md's front matter, credentials redacted, at
    most MAX_FIELD characters; None when absent."""
    if data is None:
        return None, None
    lines = _text_lines(data)
    if lines and lines[-1] == "":
        lines.pop()
    fields, _taken, problem = _skill_front_matter(lines)
    if not fields or problem:
        return None, None
    return _field(fields.get("description")), _field(
        fields.get("allowed-tools") or fields.get("allowed_tools"))


def _field(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    return scan.redact(value.strip())[:MAX_FIELD]


def _licence(licences: dict[str, tuple[str, str]], skill_md: str,
             source: Source) -> tuple[str | None, str | None]:
    """(expression, declaring file): the folder licence covering SKILL.md, or the Source's
    licence, declared nowhere in particular."""
    found = scan.licence_for(skill_md, licences)
    if found is not None:
        return found
    return source.licence, None


def _licence_copies(copy: Path, declared_in: str | None, folder: str) -> list[tuple[str, bytes]]:
    """The licence file, and any NOTICE beside it, as (artifact path, bytes), when it lies
    outside the skill folder; nothing when it is inside it, or there is none."""
    if declared_in is None or _inside(declared_in, folder):
        return []
    data = _read_file(copy, declared_in, scan.MAX_FILE_BYTES)
    if data is None:
        raise _Refused(OWNER, f"its licence file {declared_in} could not be copied: not a regular "
                              "file of its own, or too large")
    out = [(declared_in, data)]
    where = posixpath.dirname(declared_in)
    for notice in NOTICE_FILES:
        rel = _in_artifact(where, notice)
        if rel != declared_in:
            found = _read_file(copy, rel, scan.MAX_FILE_BYTES)
            if found is not None:
                out.append((rel, found))
    return out


# --- reading the quarantined folder, never through a link -------------------------------------


@dataclass
class _Survey:
    """A skill folder as it stands in quarantine: every regular file's bytes and mode, every
    folder, and what is not a regular file of its own."""

    files: dict[str, bytes] = field(default_factory=dict)
    modes: dict[str, int] = field(default_factory=dict)
    dirs: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    specials: list[str] = field(default_factory=list)
    hardlinked: list[str] = field(default_factory=list)
    unnamed: int = 0
    total: int = 0

    def read(self, fd: int, rel: str, depth: int) -> None:
        with os.scandir(fd) as listing:
            entries = sorted(listing, key=lambda entry: entry.name)
        for entry in entries:
            path = f"{rel}/{entry.name}" if rel else entry.name
            try:
                path.encode("utf-8")
            except UnicodeEncodeError:
                self.unnamed += 1
                continue
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                self.links.append(path)
            elif stat.S_ISDIR(info.st_mode):
                if depth + 1 > MAX_DEPTH:
                    raise _Refused(OWNER, f"its folders are more than {MAX_DEPTH} deep")
                self.dirs.append(path)
                inner = os.open(entry.name, _DIR_FLAGS, dir_fd=fd)
                try:
                    if _ident(os.fstat(inner)) != _ident(info):
                        raise _Refused(HELD, f"{path} changed while it was read")
                    self.read(inner, path, depth + 1)
                finally:
                    os.close(inner)
            elif not stat.S_ISREG(info.st_mode):
                self.specials.append(path)
            elif info.st_nlink > 1:
                self.hardlinked.append(path)
            else:
                if len(self.files) >= MAX_FILES:
                    raise _Refused(OWNER, f"it has more than {MAX_FILES} files, more than an install takes")
                data = _read_at(fd, entry.name, _ident(info), MAX_BYTES - self.total)
                if data is None:
                    raise _Refused(OWNER, f"it is larger than an install takes ({MAX_BYTES} bytes), "
                                          f"or {path} could not be read as the file listed")
                self.total += len(data)
                self.files[path] = data
                self.modes[path] = info.st_mode


def _survey(copy: Path, folder: str) -> _Survey:
    survey = _Survey()
    try:
        fd = _open_folder(copy, folder)
    except OSError:
        raise _Refused(OWNER, f"its folder {folder or '.'} could not be opened without following "
                              "a link") from None
    try:
        survey.read(fd, "", 0)
    except OSError as error:
        raise _Refused(HELD, f"its folder could not be read ({type(error).__name__})") from None
    finally:
        os.close(fd)
    return survey


def _ident(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _open_folder(root: Path, rel: str) -> int:
    """A descriptor of the folder at rel under root, reached one folder at a time without
    following a link (as pipeline._read_scanned reaches a file)."""
    fd = os.open(root, _DIR_FLAGS)
    try:
        for part in rel.split("/") if rel else ():
            inner = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = inner
    except OSError:
        os.close(fd)
        raise
    return fd


def _read_at(dir_fd: int, name: str, ident: tuple[int, int] | None, limit: int) -> bytes | None:
    """The bytes of the regular file `name` in the folder, opened without following a link, only
    if it is still the file listed, has no other name, and holds at most limit bytes."""
    try:
        handle = os.open(name, _FILE_FLAGS, dir_fd=dir_fd)
    except OSError:
        return None
    try:
        info = os.fstat(handle)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink > 1
                or (ident is not None and _ident(info) != ident) or info.st_size > limit):
            return None
        chunks, size = [], 0
        while chunk := os.read(handle, _CHUNK):
            size += len(chunk)
            if size > limit:
                return None
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError:
        return None
    finally:
        os.close(handle)


def _read_file(root: Path, rel: str, limit: int) -> bytes | None:
    try:
        fd = _open_folder(root, posixpath.dirname(rel))
    except OSError:
        return None
    try:
        return _read_at(fd, posixpath.basename(rel), None, limit)
    finally:
        os.close(fd)


# --- staging and settling -----------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _write_new(path: Path, data: bytes) -> None:
    fd = os.open(path, _WRITE_FLAGS, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(data)


def _write_provenance(staging: Path, record: dict[str, Any]) -> None:
    text = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    _write_new(staging / PROVENANCE_FILE, text.encode("utf-8"))


def _stage(skills_dir: Path, final: Path, survey: _Survey, digest: str,
           copies: list[tuple[str, bytes]], record: dict[str, Any]) -> None:
    """Copy, check and record the skill in a private staging folder under skills_dir, then
    rename it to final in one step. Whatever stops it, the staging folder is removed and
    nothing is left at final."""
    skills_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix=f"{STAGING_PREFIX}{final.name}-", dir=skills_dir))
    try:
        skill = staging / SKILL_DIR
        skill.mkdir()
        for rel in survey.dirs:                       # listed parents first
            (skill / rel).mkdir()
        files = []
        for rel in sorted(survey.files):
            data = survey.files[rel]
            _write_new(skill / rel, data)
            files.append({"path": rel, "sha256": _sha256(data), "bytes": len(data)})

        # the copy, scanned again
        for found in scan.scan_tree(skill):
            if found.rule.startswith(CREDENTIAL_RULES):
                raise _Refused(OWNER, f"the copy scanned again: {found.rule} at {found.path}")
            if found.severity == scan.BLOCK:
                raise _Refused(HELD, f"the copy scanned again: {found.rule} at {found.path}")
        # and byte for byte the quarantined folder
        if tree_digest(skill) != digest:
            raise _Refused(HELD, "the copy is not the quarantined folder (their tree digests differ)")
        for item in files:
            if _sha256(_read_file(skill, item["path"], MAX_BYTES) or b"") != item["sha256"]:
                raise _Refused(HELD, f"the copy of {item['path']} is not the quarantined file")

        copied = []
        if copies:
            (staging / LICENCE_DIR).mkdir()
            for rel, data in copies:
                at = f"{LICENCE_DIR}/{posixpath.basename(rel)}"
                _write_new(staging / at, data)
                copied.append({"path": at, "from": rel, "sha256": _sha256(data), "bytes": len(data)})

        record = {**record, "installed_at": utc_now(),
                  "skill": {**record["skill"], "files": files},
                  "licence": {**record["licence"], "copied": copied}}
        _write_provenance(staging, record)
        _seal(staging)
        if os.path.lexists(final):
            raise _Refused(CONFLICT, f"{final} appeared while the skill was staged; nothing is overwritten")
        _move_noreplace(staging, final)
    finally:
        remove_tree(staging)


def _renameat2() -> Callable[..., int] | None:
    """libc's renameat2, or None when it has none (glibc before 2.28, or not Linux)."""
    try:
        function = ctypes.CDLL(None, use_errno=True).renameat2
    except (OSError, AttributeError):
        return None
    function.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    function.restype = ctypes.c_int
    return function


def _move_noreplace(staging: Path, final: Path) -> None:
    """Rename staging to final in one step that never replaces anything at final: a folder
    that appeared there, even an empty one that os.rename would replace silently, is a
    conflict and is left as it is. Where that move is not available, nothing is installed
    (held): there is no falling back to os.rename. Any other failure is raised."""
    renameat2 = _renameat2()
    unavailable = _Refused(HELD, "the move that never replaces (renameat2 with RENAME_NOREPLACE) is "
                                 f"not available here, so nothing is installed at {final}")
    if renameat2 is None:
        raise unavailable
    if renameat2(_AT_FDCWD, os.fsencode(staging), _AT_FDCWD, os.fsencode(final),
                 _RENAME_NOREPLACE) == 0:
        return
    code = ctypes.get_errno()
    if code == errno.EEXIST:
        raise _Refused(CONFLICT, f"{final} appeared while the skill was staged; nothing is overwritten")
    if code in (errno.ENOSYS, errno.EINVAL):
        raise unavailable
    raise OSError(code, os.strerror(code), str(staging), None, str(final))


def _seal(staging: Path) -> None:
    """Files 0444 and folders 0555, deepest first; the install's own folder stays the
    installer's, so uninstall can move it aside."""
    for folder, dirs, files in os.walk(staging, topdown=False, followlinks=False):
        for name in files:
            os.chmod(os.path.join(folder, name), 0o444)
        for name in dirs:
            os.chmod(os.path.join(folder, name), 0o555)
    os.chmod(staging, 0o755)


# --- what is installed --------------------------------------------------------------------------


def read_provenance(folder: Path) -> dict[str, Any] | None:
    """An install's provenance.json, read without following a link; None when it is not there,
    not a regular file, or not an install's record."""
    data = _read_file(folder, PROVENANCE_FILE, MAX_PROVENANCE)
    if data is None:
        return None
    try:
        record = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        return None
    return record


def _same_install(final: Path, name: str, digest: str, artifact_id: str, unit_id: str) -> bool:
    if os.path.islink(final) or not final.is_dir():
        return False
    record = read_provenance(final)
    if record is None:
        return False
    with contextlib.suppress(AttributeError, KeyError, TypeError):
        return (record["name"] == name and record["skill"]["digest"] == digest
                and record["digest_record"]["artifact_id"] == artifact_id
                and record["digest_record"]["unit_id"] == unit_id)
    return False


def installed(skills_dir: str | os.PathLike[str] = DEFAULT_SKILLS_DIR) -> list[dict[str, Any]]:
    """Every install's provenance, by name. A staging folder (a name starting ".") is never an
    install, nor is a link or a folder without provenance.json."""
    base = Path(skills_dir)
    if os.path.islink(base) or not base.is_dir():
        return []
    out = []
    with os.scandir(base) as listing:
        entries = sorted(listing, key=lambda entry: entry.name)
    for entry in entries:
        if entry.name.startswith(".") or not re.fullmatch(NAME_PATTERN, entry.name):
            continue
        if not entry.is_dir(follow_symlinks=False):
            continue
        record = read_provenance(Path(entry.path))
        if record is not None and record.get("name") == entry.name:
            out.append(record)
    return out


def _still_matches(final: Path, record: dict[str, Any]) -> bool:
    """Whether an install's bytes are still the ones its provenance records."""
    try:
        skill = final / SKILL_DIR
        if os.path.islink(skill) or not skill.is_dir():
            return False
        if tree_digest(skill) != record["skill"]["digest"]:
            return False
        if not _only_recorded_entries(final, record):
            return False
        for base, items in ((skill, record["skill"]["files"]), (final, record["licence"]["copied"])):
            for item in items:
                data = _read_file(base, item["path"], MAX_BYTES)
                if data is None or _sha256(data) != item["sha256"]:
                    return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def _only_recorded_entries(final: Path, record: dict[str, Any]) -> bool:
    """Whether the install folder holds exactly skill/, provenance.json and, when the provenance
    records licence copies, licence/ with exactly those files: nothing more, and no link. The
    skill folder's own entries are its tree digest's to check."""
    copied = [item["path"] for item in record["licence"]["copied"]]
    names = {posixpath.basename(path) for path in copied}
    if any(path != f"{LICENCE_DIR}/{posixpath.basename(path)}" for path in copied):
        return False
    expected = {SKILL_DIR: True, PROVENANCE_FILE: False}
    if copied:
        expected[LICENCE_DIR] = True
    for folder, wanted in ((final, expected), (final / LICENCE_DIR, dict.fromkeys(names, False))):
        if not wanted:
            continue
        with os.scandir(folder) as listing:
            entries = {entry.name: entry for entry in listing}
        if set(entries) != set(wanted):
            return False
        for entry_name, is_dir in wanted.items():
            entry = entries[entry_name]
            if entry.is_symlink():
                return False
            if is_dir and not entry.is_dir(follow_symlinks=False):
                return False
            if not is_dir and not entry.is_file(follow_symlinks=False):
                return False
    return True


def uninstall(skills_dir: str | os.PathLike[str], name: str) -> Removal:
    """Remove skills_dir/<name> wholly — only a real folder holding a provenance.json, never
    following a link — and say whether its bytes still matched. A name not installed changes
    nothing and succeeds. UninstallRefused for a link or a folder that is not an install."""
    if not isinstance(name, str) or not re.fullmatch(NAME_PATTERN, name):
        raise ValueError(f"not a skill name: {name!r}")
    base = Path(skills_dir)
    final = base / name
    if not os.path.lexists(final):
        return Removal(name, removed=False, matched=None)
    if os.path.islink(final):
        raise UninstallRefused(f"{final} is a symbolic link: it is not followed, and not removed")
    if not final.is_dir():
        raise UninstallRefused(f"{final} is not a folder: it is not an install, and is not removed")
    record = read_provenance(final)
    if record is None:
        raise UninstallRefused(f"{final} holds no provenance.json: it is not an install, and is "
                               "not removed")
    matched = _still_matches(final, record)
    trash = Path(tempfile.mkdtemp(prefix=f"{TRASH_PREFIX}{name}-", dir=base))
    try:
        os.chmod(final, 0o700)
        os.rename(final, trash / name)          # gone from its name in one step
    finally:
        remove_tree(trash)
    if os.path.lexists(final) or os.path.lexists(trash):
        raise OSError(f"{final} could not be removed wholly")
    return Removal(name, removed=True, matched=matched)
