"""The digest report: one DigestResult as Markdown, for the owner to read.

    render(result) -> str

What it says, in order: where the artifact came from and how it is pinned; whether it was
digested or blocked, and by which adapters; the kinds it was found to be, with detect's
evidence and the census; the findings, most severe first; and the Units, counted by kind,
with the first few of each kind by place and whatever the adapters could not read.

The same result gives the same text, byte for byte: nothing here reads the clock, the machine
or the tree. Everything taken from the artifact — its origin, paths, evidence, titles — is
shown as text and never as markup: characters that do not print (a direction override, a
zero-width space) are written as escapes, as the scanner writes them, and Markdown's
punctuation is escaped, so a title cannot hide words in an HTML comment or rearrange the
report around it. Paths are shown as the scanner shows them, with anything shaped like a
credential replaced by its kind. Findings never quote what they found, and the title of a Unit
read from a line where the scanner found a credential is withheld, so no secret value reaches
the report. Every list is bounded."""

from __future__ import annotations

import re
from collections import Counter

from app.digest import scan
from app.digest.model import SEVERITIES, UNIT_KINDS, Finding, Location, Unit
from app.digest.pipeline import DigestResult, normalise_kind

MAX_SAMPLES = 5            # Units shown for each kind
MAX_FINDINGS = 50          # findings shown for each severity
MAX_EVIDENCE = 5           # pieces of evidence shown for each detection
MAX_UNREAD = 10            # 'unparsed' Units shown
MAX_EXTENSIONS = 8         # extensions named in the census line
MAX_TEXT = 200             # characters of any one piece of the artifact's text

_UNPARSED = "unparsed"
_MARKDOWN = re.compile(r"([\\`*_\[\]<>|~&!#])")
_SECRET = "secret."        # pipeline._from_scan starts each explanation with the scan rule


def render(result: DigestResult) -> str:
    artifact = result.artifact
    lines = [f"# Digest of {_text(artifact.source.origin)}", ""]
    lines += _source(result)
    lines += _outcome(result)
    lines += _kinds(result)
    lines += _findings(result.findings)
    lines += _units(artifact.units, result.findings)
    return "\n".join(lines).rstrip("\n") + "\n"


# --- sections -------------------------------------------------------------------------------


def _source(result: DigestResult) -> list[str]:
    source = result.artifact.source
    return [
        "## Source",
        "",
        f"- Artifact: {_code(result.artifact.id)}",
        f"- Origin: {_text(source.origin)} ({source.origin_kind})",
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
    return ["## Outcome", "", text, ""]


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
    extensions = ", ".join(
        f"{_text(ext)} {count}" for ext, count in list(census.by_extension.items())[:MAX_EXTENSIONS]
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


def _units(units: tuple[Unit, ...], findings: tuple[Finding, ...]) -> list[str]:
    lines = ["## Units", ""]
    if not units:
        return [*lines, "None.", ""]
    counts = Counter(unit.kind for unit in units)
    lines += ["| Kind | Units |", "|---|---:|"]
    lines += [f"| {kind} | {counts[kind]} |" for kind in UNIT_KINDS if counts[kind]]
    lines += [f"| total | {len(units)} |", ""]
    secrets = _secret_places(findings)
    unread = [unit for unit in units if _UNPARSED in unit.tags]
    for kind in UNIT_KINDS:
        read = [unit for unit in units if unit.kind == kind and _UNPARSED not in unit.tags]
        if not read:
            continue
        lines += [f"### {kind} ({len(read)})", ""]
        for unit in read[:MAX_SAMPLES]:
            lines.append(f"- {_title(unit, secrets)} at {_where(unit.location)}{_tags(unit)}")
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


# --- the artifact's text, shown as text -------------------------------------------------------


def _secret_places(findings: tuple[Finding, ...]) -> dict[str, set[int | None]]:
    places: dict[str, set[int | None]] = {}
    for finding in findings:
        if finding.category == "safety" and finding.explanation.startswith(_SECRET):
            places.setdefault(finding.location.path, set()).add(finding.location.line_start)
    return places


def _title(unit: Unit, secrets: dict[str, set[int | None]]) -> str:
    lines = secrets.get(unit.location.path)
    if lines:
        start, end = unit.location.line_start, unit.location.line_end
        if start is None or any(line is None or start <= line <= end for line in lines):
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


def _text(text: str, limit: int | None = MAX_TEXT) -> str:
    """Plain text in Markdown: one line, printable, every piece of Markdown punctuation escaped."""
    return _MARKDOWN.sub(r"\\\1", _clip(_printable(text), limit))


def _code(text: str, limit: int | None = MAX_TEXT) -> str:
    """A code span that holds the text whatever backticks it contains (CommonMark's rule)."""
    shown = _clip(_printable(text), limit)
    longest = max((len(run) for run in re.findall(r"`+", shown)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if shown.startswith(("`", " ")) or shown.endswith(("`", " ")) else ""
    return f"{fence}{pad}{shown}{pad}{fence}"
