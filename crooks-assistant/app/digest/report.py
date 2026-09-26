"""The digest report: one DigestResult as Markdown, for the owner to read.

    render(result) -> str

What it says, in order: where the artifact came from and how it is pinned; whether it was
digested or blocked, and by which adapters; the kinds it was found to be, with detect's
evidence and the census; the findings, most severe first; the Units, counted by kind, with the
first few of each kind by place — each with its relation to CLIVE when it was related — and
whatever the adapters could not read; the relations, counted, with every overlap and extension
up to a bound and the self-model entry it rests on; and CLIVE's proposals grouped by target,
each with its reasoning, what it would add (which is its removal handle), and whether it needs
the owner.

The same result gives the same text, byte for byte: nothing here reads the clock, the machine
or the tree. Everything taken from the artifact — its origin, paths, evidence, titles — is
shown as text and never as markup: characters that do not print (a direction override, a
zero-width space) are written as escapes, as the scanner writes them, and Markdown's
punctuation is escaped, so a title cannot hide words in an HTML comment or rearrange the
report around it; and nothing is left that GitHub's Markdown would turn into a live link (a
bare URL, a www. name, an e-mail address) — each is defanged: https[:]//, www[.], name[@]host.
Every piece of the artifact's text, wherever it comes from (its origin, detect's evidence, a
title, a path, the intake's notes), has anything shaped like a credential replaced by its kind
(scan.redact), on top of what the pipeline has already redacted — every credential the scanner
found, wherever a Unit quoted it. Paths are shown as the scanner shows them, and a file
extension only when it looks like one. Findings never quote what they found, and the title of
a Unit read from a line where the scanner found a credential is withheld (a file whose findings
were cut short is withheld whole) — and so are the reasoning of its proposal, which quotes the
title, and the names of what it would add, which are made from it. Every list is bounded."""

from __future__ import annotations

import re
from collections import Counter

from app.digest import scan
from app.digest.model import (
    ABSORPTION_TARGETS,
    SEVERITIES,
    UNIT_KINDS,
    Absorption,
    Finding,
    Location,
    Unit,
)
from app.digest.pipeline import DigestResult, normalise_kind
from app.digest.propose import NEEDS_OWNER, explain, needs_owner, usual_hypothesis
from app.digest.relate import RELATIONS, Match, Relation

MAX_SAMPLES = 5            # Units shown for each kind
MAX_FINDINGS = 50          # findings shown for each severity
MAX_EVIDENCE = 5           # pieces of evidence shown for each detection
MAX_UNREAD = 10            # 'unparsed' Units shown
MAX_EXTENSIONS = 8         # extensions named in the census line
MAX_TEXT = 200             # characters of any one piece of the artifact's text
MAX_RELATED = 25           # overlaps, and extensions, listed
MAX_PROPOSALS = 10         # proposals shown for each target
MAX_REASONING = 900        # characters of a proposal's reasoning
MAX_ADDITIONS = 5          # additions named for one proposal
MAX_INTAKE = 20            # withheld entries and notes shown from the intake

_UNPARSED = "unparsed"
_MARKDOWN = re.compile(r"([\\`*_\[\]<>|~&!#$])")   # $ too: GitHub renders $…$ as math
_SECRET = "secret."        # pipeline._from_scan starts each explanation with the scan rule
_TRUNCATED = "scan.truncated"
_EXTENSION = re.compile(r"\.[a-z0-9]{1,10}")
# What GitHub's Markdown links on its own: a scheme and "://", "www.", mailto: and xmpp:, and an
# e-mail address.
_SCHEME = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*)://")
_WWW = re.compile(r"(?i)\bwww\.")
_MAIL_SCHEME = re.compile(r"(?i)\b(mailto|xmpp):")
_EMAIL_AT = re.compile(r"(?<=[A-Za-z0-9._+-])@(?=[A-Za-z0-9-]+\.)")


def render(result: DigestResult) -> str:
    artifact = result.artifact
    lines = [f"# Digest of {_code(artifact.source.origin)}", ""]
    secrets = _secret_places(result.findings)
    relations = {relation.unit_id: relation for relation in result.relations}
    lines += _source(result)
    lines += _intake(result)
    lines += _outcome(result)
    lines += _kinds(result)
    lines += _findings(result.findings)
    lines += _units(artifact.units, secrets, relations)
    lines += _relations(result, secrets)
    lines += _proposals(result, secrets, relations)
    return "\n".join(lines).rstrip("\n") + "\n"


# --- sections -------------------------------------------------------------------------------


def _source(result: DigestResult) -> list[str]:
    source = result.artifact.source
    return [
        "## Source",
        "",
        f"- Artifact: {_code(result.artifact.id)}",
        f"- Origin: {_code(source.origin)} ({source.origin_kind})",
        f"- Pinned reference: {_code(source.pinned_ref)}",
        f"- Content digest: {_code(source.content_digest)}",
        f"- Licence: {_text(source.licence) if source.licence else 'none recorded'}",
        f"- Taken at: {_text(source.taken_at)}",
        "",
    ]


def _outcome(result: DigestResult) -> list[str]:
    units = len(result.artifact.units)
    if result.blocked:
        stopping = sum(1 for f in result.findings if f.category == "safety" and f.severity == "critical")
        text = (
            f"**Blocked before decomposition.** {stopping} block-severity safety finding(s) "
            "stopped the artifact in quarantine: no adapter ran and no Units were read."
        )
    elif result.adapters:
        text = (
            f"Digested into {units} Unit(s) by the adapter(s) {', '.join(_text(n) for n in result.adapters)}."
        )
    else:
        text = "No adapter reads the kinds found, so no Units were read."
    if result.excluded and not result.blocked:
        text += (
            f" Left out under their own licence, which forbids reuse: "
            f"{', '.join(_path(folder + '/') for folder in result.excluded)} — nothing in "
            f"{'it' if len(result.excluded) == 1 else 'them'} was decomposed."
        )
    if result.related:
        text += (
            f" Related to CLIVE's self-model, with {len(result.proposals)} proposal(s), of which "
            f"{sum(1 for p in result.proposals if needs_owner(p))} need the owner."
        )
    return ["## Outcome", "", text, ""]


def _intake(result: DigestResult) -> list[str]:
    """What the intake said about the copy: entries it withheld, with why, and its notes."""
    if not result.withheld and not result.notes:
        return []
    lines = ["## Intake", ""]
    if result.withheld:
        lines.append(f"Withheld from the copy ({len(result.withheld)}): not in quarantine, so not digested.")
        lines.append("")
        for path, why in result.withheld[:MAX_INTAKE]:
            lines.append(f"- {_path(path)}: {_text(why)}")
        if len(result.withheld) > MAX_INTAKE:
            lines.append(f"- and {len(result.withheld) - MAX_INTAKE} more")
        lines.append("")
    if result.notes:
        lines += ["Notes:", ""]
        lines += [f"- {_text(note)}" for note in result.notes[:MAX_INTAKE]]
        if len(result.notes) > MAX_INTAKE:
            lines.append(f"- and {len(result.notes) - MAX_INTAKE} more")
        lines.append("")
    return lines


def _kinds(result: DigestResult) -> list[str]:
    lines = ["## Kinds", ""]
    for kind in result.artifact.kinds:
        detections = [d for d in result.detections if normalise_kind(d.kind) == kind]
        named = ", ".join(f"{_text(d.label)} ({d.confidence:.2f})" for d in detections)
        lines.append(f"- **{kind}**, recognised as {named}")
        for detection in detections:
            for evidence in detection.evidence[:MAX_EVIDENCE]:
                lines.append(
                    f"  - {_path(evidence.path)}: {_text(evidence.signal)} ({evidence.weight:.2f})"
                )
            more = len(detection.evidence) - MAX_EVIDENCE + detection.more_evidence
            if more > 0:
                lines.append(f"  - and {more} more piece(s) of evidence for {_text(detection.label)}")
    census = result.census
    # A name's last dot can start anything, a credential included: only what looks like an
    # extension is named, and the rest is counted.
    named = [(ext, count) for ext, count in census.by_extension.items() if _EXTENSION.fullmatch(ext)]
    others = sum(count for ext, count in census.by_extension.items() if not _EXTENSION.fullmatch(ext))
    extensions = ", ".join(
        [f"{_text(ext)} {count}" for ext, count in named[:MAX_EXTENSIONS]]
        + ([f"other {others}"] if others else [])
    )
    notes = []
    if census.truncated:
        notes.append("the walk stopped at its limit, so the tree is larger than this")
    if census.skipped:
        notes.append(f"{len(census.skipped)} folder(s) not walked (version control, dependencies, caches)")
    if census.unreadable:
        notes.append(f"{census.unreadable} entry(ies) could not be read")
    lines += [
        "",
        f"Census: {census.files} file(s), {census.dirs} folder(s), {census.symlinks} symbolic link(s)"
        + (f"; by extension {extensions}" if extensions else "")
        + (f"; {'; '.join(notes)}" if notes else "") + ".",
        "",
    ]
    return lines


def _findings(findings: tuple[Finding, ...]) -> list[str]:
    lines = ["## Findings", ""]
    if not findings:
        return [*lines, "None.", ""]
    by_severity: dict[str, list[Finding]] = {}
    for finding in findings:
        by_severity.setdefault(finding.severity, []).append(finding)
    for severity in reversed(SEVERITIES):
        group = by_severity.get(severity)
        if not group:
            continue
        lines += [f"### {severity} ({len(group)})", ""]
        for finding in group[:MAX_FINDINGS]:
            lines.append(
                f"- {_where(finding.location)} [{finding.category}] "
                f"{_text(finding.explanation, limit=None)}"
            )
        if len(group) > MAX_FINDINGS:
            lines.append(f"- and {len(group) - MAX_FINDINGS} more {severity} finding(s)")
        lines.append("")
    return lines


def _units(units: tuple[Unit, ...], secrets: dict[str, set[int | None]],
           relations: dict[str, Relation]) -> list[str]:
    lines = ["## Units", ""]
    if not units:
        return [*lines, "None.", ""]
    counts = Counter(unit.kind for unit in units)
    lines += ["| Kind | Units |", "|---|---:|"]
    lines += [f"| {kind} | {counts[kind]} |" for kind in UNIT_KINDS if counts[kind]]
    lines += [f"| total | {len(units)} |", ""]
    unread = [unit for unit in units if _UNPARSED in unit.tags]
    for kind in UNIT_KINDS:
        read = [unit for unit in units if unit.kind == kind and _UNPARSED not in unit.tags]
        if not read:
            continue
        lines += [f"### {kind} ({len(read)})", ""]
        for unit in read[:MAX_SAMPLES]:
            relation = relations.get(unit.id)
            related = f" — {_relation(relation)}" if relation is not None else ""
            lines.append(f"- {_title(unit, secrets)} at {_where(unit.location)}{_tags(unit)}{related}")
        if len(read) > MAX_SAMPLES:
            lines.append(f"- and {len(read) - MAX_SAMPLES} more")
        lines.append("")
    if unread:
        lines += [f"### Not read ({len(unread)})", ""]
        for unit in unread[:MAX_UNREAD]:
            lines.append(f"- {_where(unit.location)}: {_text(unit.body, limit=160)}")
        if len(unread) > MAX_UNREAD:
            lines.append(f"- and {len(unread) - MAX_UNREAD} more")
        lines.append("")
    return lines


def _relations(result: DigestResult, secrets: dict[str, set[int | None]]) -> list[str]:
    lines = ["## Relations", ""]
    if not result.related:
        why = ("the artifact was blocked before decomposition" if result.blocked
               else "it was digested without CLIVE's self-model")
        return [*lines, f"Not related to CLIVE: {why}.", ""]
    counts = Counter(relation.relation for relation in result.relations)
    by_relation = ", ".join(f"{name} {counts[name]}" for name in RELATIONS)
    lines += [
        f"Related to CLIVE's self-model {_code(result.self_model or '')}: {by_relation}. An overlap "
        "is something CLIVE already has; an extension adds to something CLIVE has, plans or has "
        "thought of; a gap is something CLIVE lacks; a reference is only pointed at.",
        "",
    ]
    units = {unit.id: unit for unit in result.units}
    place = {relation.unit_id: index for index, relation in enumerate(result.relations)}
    for name, heading in (("overlap", "Overlaps"), ("extends", "Extensions")):
        # the strongest first, then by place: the bound keeps what says most
        chosen = sorted((r for r in result.relations if r.relation == name),
                        key=lambda r: (-r.score, place[r.unit_id]))
        if not chosen:
            continue
        lines += [f"### {heading} ({len(chosen)}, strongest first)", ""]
        for relation in chosen[:MAX_RELATED]:
            unit = units[relation.unit_id]
            lines.append(f"- {_title(unit, secrets)} at {_where(unit.location)} — {_relation(relation)}")
        if len(chosen) > MAX_RELATED:
            lines.append(f"- and {len(chosen) - MAX_RELATED} more")
        lines.append("")
    return lines


def _proposals(result: DigestResult, secrets: dict[str, set[int | None]],
               relations: dict[str, Relation]) -> list[str]:
    lines = ["## Proposals", ""]
    if not result.related:
        return [*lines, "None: nothing was related to CLIVE, so nothing is proposed.", ""]
    if not result.proposals:
        return [*lines, "None: there were no Units to propose for.", ""]
    owner = [p for p in result.proposals if needs_owner(p)]
    lines += [
        f"{len(result.proposals)} proposal(s) made against the self-model above, each proposed "
        f"by CLIVE and decided by no one: the owner decides. {len(owner)} say they need the "
        "owner. What a proposal would add is its removal handle: taking exactly that out again "
        "undoes it.",
        "",
        "| Target | Proposals | Need the owner |",
        "|---|---:|---:|",
    ]
    by_target: dict[str, list[Absorption]] = {}
    for proposal in result.proposals:
        by_target.setdefault(proposal.target, []).append(proposal)
    for target in ABSORPTION_TARGETS:
        if target in by_target:
            group = by_target[target]
            lines.append(f"| {target} | {len(group)} | {sum(1 for p in group if needs_owner(p))} |")
    lines.append("")
    units = {unit.id: unit for unit in result.units}
    for target in ABSORPTION_TARGETS:
        group = by_target.get(target)
        if not group:
            continue
        # the ones that need the owner first, then in reading order
        group = sorted(group, key=lambda p: not needs_owner(p))
        waiting = sum(1 for p in group if needs_owner(p))
        lines += [f"### {target} ({len(group)}" + (f"; {waiting} need the owner" if waiting else "") + ")", ""]
        usual = usual_hypothesis(target)
        if all(usual):
            lines += [f"Hypothesis, unless a proposal says otherwise: {_text(usual[0], limit=None)} "
                      f"Measure: {_text(usual[1], limit=None)}", ""]
        for proposal in group[:MAX_PROPOSALS]:
            lines += _proposal(proposal, units[proposal.unit_id], relations.get(proposal.unit_id),
                               secrets, usual)
        if len(group) > MAX_PROPOSALS:
            lines.append(f"- and {len(group) - MAX_PROPOSALS} more {target} proposal(s)")
        lines.append("")
    return lines


def _proposal(proposal: Absorption, unit: Unit, relation: Relation | None,
              secrets: dict[str, set[int | None]], usual: tuple[str, str]) -> list[str]:
    withheld = _withheld(unit, secrets)
    parts = explain(proposal)
    head = f"- {_title(unit, secrets)} at {_where(unit.location)}"
    if relation is not None:
        head += f" — {relation.relation}"
    if parts.needs_owner:
        head += " — **Needs the owner**"
    if withheld:
        why = "*(withheld: the reasoning quotes a title read where a credential was found)*"
    else:
        why = _text(parts.why, limit=MAX_REASONING)
    lines = [head, f"  - Why: {why}"]
    if parts.needs_owner:
        lines.append(f"  - {NEEDS_OWNER}: {_text(parts.needs_owner, limit=MAX_REASONING)}.")
    if (parts.hypothesis, parts.measure) != usual and parts.hypothesis:
        lines.append(f"  - Hypothesis: {_text(parts.hypothesis, limit=MAX_REASONING)} "
                     f"Measure: {_text(parts.measure, limit=MAX_REASONING)}")
    additions = proposal.removal.additions
    if not additions:
        adds = "Adds nothing, so its removal handle is empty."
    else:
        named = [
            addition.kind if withheld else f"{addition.kind} {_code(addition.ref)}"
            for addition in additions[:MAX_ADDITIONS]
        ]
        more = len(additions) - MAX_ADDITIONS
        adds = "Would add, and so its removal handle: " + "; ".join(named) + (
            f"; and {more} more" if more > 0 else "") + (
            " *(names withheld: they are made from the title)*" if withheld else "") + "."
    return [*lines, f"  - {adds}"]


def _relation(relation: Relation) -> str:
    """A relation in a few words: what it is and the self-model entry it rests on."""
    basis = next((m for m in relation.matches if m.key == relation.basis), None)
    if basis is not None:
        verb = "overlaps" if relation.relation == "overlap" else "extends"
        planned = "" if basis.present or relation.relation == "overlap" else ", planned or an idea"
        return f"{verb} {_entry(basis)}{planned}"
    if relation.relation == "gap":
        return "gap: nothing in CLIVE is close"
    return "reference: only pointed at"


def _entry(match: Match) -> str:
    named = "named; " if match.named else ""
    terms = f"; shared: {', '.join(_text(term) for term in match.terms)}" if match.terms else ""
    return f"{_code(match.key)} {_text(match.name, limit=80)} ({named}{match.score:.2f}{terms})"


# --- the artifact's text, shown as text -------------------------------------------------------


def _secret_places(findings: tuple[Finding, ...]) -> dict[str, set[int | None]]:
    """Where the scanner found credentials, by the path as the scanner shows it: each line, or
    None for the whole file — as for a file whose credential findings were cut short, where the
    lines not listed are unknown."""
    places: dict[str, set[int | None]] = {}
    for finding in findings:
        if finding.category != "safety":
            continue
        if finding.explanation.startswith(_SECRET):
            places.setdefault(finding.location.path, set()).add(finding.location.line_start)
        elif finding.explanation.startswith(_TRUNCATED) and f"'{_SECRET}" in finding.explanation:
            places.setdefault(finding.location.path, set()).add(None)
    return places


def _withheld(unit: Unit, secrets: dict[str, set[int | None]]) -> bool:
    """Whether the Unit was read from where the scanner found a credential. Its path is compared
    as the scanner shows paths (credential shapes redacted, anything unprintable escaped)."""
    lines = secrets.get(scan._display(unit.location.path)) or secrets.get(unit.location.path)
    if not lines:
        return False
    start, end = unit.location.line_start, unit.location.line_end
    return start is None or any(line is None or start <= line <= end for line in lines)


def _title(unit: Unit, secrets: dict[str, set[int | None]]) -> str:
    if _withheld(unit, secrets):
        return "*(title withheld: a credential was found here)*"
    return f"**{_text(unit.title)}**"


def _tags(unit: Unit) -> str:
    return f" ({', '.join(_text(tag) for tag in unit.tags)})" if unit.tags else ""


def _where(location: Location) -> str:
    if location.line_start is None:
        return _path(location.path)
    span = str(location.line_start)
    if location.line_end != location.line_start:
        span += f"-{location.line_end}"
    return _path(location.path, span)


def _path(path: str, span: str = "") -> str:
    shown = scan._display(path)
    return _code(f"{shown}:{span}" if span else shown)


def _printable(text: str) -> str:
    """Characters that do not print written as escapes, as scan.py writes them in paths."""
    if text.isprintable():
        return text
    return "".join(ch if ch.isprintable() else scan._escape(ch) for ch in text)


def _clip(text: str, limit: int | None) -> str:
    if limit is not None and len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _defang(text: str) -> str:
    """Text GitHub's Markdown will not turn into a link: https[:]//, www[.], mailto[:], a[@]b."""
    text = _SCHEME.sub(r"\1[:]//", text)
    text = _WWW.sub(lambda match: match.group(0)[:-1] + "[.]", text)
    text = _MAIL_SCHEME.sub(r"\1[:]", text)
    return _EMAIL_AT.sub("[@]", text)


def _text(text: str, limit: int | None = MAX_TEXT) -> str:
    """Plain text in Markdown: one line, printable, credentials redacted, links defanged, every
    piece of Markdown punctuation escaped."""
    return _MARKDOWN.sub(r"\\\1", _defang(_clip(_printable(scan.redact(text)), limit)))


def _code(text: str, limit: int | None = MAX_TEXT) -> str:
    """A code span that holds the text whatever backticks it contains (CommonMark's rule), with
    credentials redacted. GitHub links nothing inside a code span."""
    shown = _clip(_printable(scan.redact(text)), limit)
    longest = max((len(run) for run in re.findall(r"`+", shown)), default=0)
    fence = "`" * (longest + 1)
    # CommonMark strips one space from each end of a code span, unless it is all spaces
    edged = shown.startswith(("`", " ")) or shown.endswith(("`", " "))
    pad = " " if edged and shown.strip(" ") else ""
    return f"{fence}{pad}{shown}{pad}{fence}"
