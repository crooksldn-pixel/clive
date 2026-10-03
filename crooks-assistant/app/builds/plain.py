"""The loop's reasons, and a reviewer's findings, in plain words for George.

George's words (2 Oct 2026): "many of the review findings are incomprehensible to me". Two
translators, both rule-based and both built only from the record's own fields:

- `why_stopped(item)`: why a build stopped, from the reason the loop published with it. The loop
  writes its reasons from a handful of fixed sentences (the Dispatcher's convergence limit, the
  GitHub acceptance gate, the builder's own report, CLIVE's checks, the build server's workspace);
  each is recognised by its own opening and said again in one or two plain sentences, with who it
  now waits on. Anything not recognised is the loop's first sentence, cleaned, never a guess.
- `finding(record)`: a reviewer's finding (F-01 and its evidence, as app/orchestrator/reviewers/
  base.py `Finding` holds it) as "What's wrong · Why it matters · What fixes it". What's wrong is the
  finding's first sentence; why it matters is the finding's own sentence about the harm when it has
  one, else what its `material` flag means, and where it was found; what fixes it is the required
  repair's first sentence. The full technical text stays beside it, for the details.

What reaches the face is cleaned the same way everywhere: a test named by its id is said as its
name reads ("a planner exception never breaks a turn"), a path as its file name, and no commit SHA
or branch name is left in it. Every string is the loop's or the reviewer's own, redacted by the rule
engineering_status already applies to them (secrets, URL credentials, customer shapes) before it is
cut, so a cut never leaves half a secret behind.
"""

from __future__ import annotations

import re
from typing import Any

from app.tools.engineering_tools import _said

FACE_CHARS = 280          # one or two sentences on the face
TECHNICAL_CHARS = 1000    # the loop's or the reviewer's full words, behind the details

# Where on the road (Filed, Built, Reviewed, On the trunk, Live) a build stopped.
FILED, BUILT, REVIEWED, TRUNK, LIVE = range(5)

YOU, DIRECTOR = "you", "the Director"

_TEST_ID = re.compile(r"(?:[\w.-]+/)*(?P<file>test_\w+\.py)::(?P<name>test_\w+)(?:\[[^\]\s]*\])?")
_PATH = re.compile(r"^(?:[\w.-]+/)+(?P<base>[\w.-]+\.\w{1,5})(?::(?P<line>\d{1,6}))?$")
_CODE = re.compile(r"`([^`\n]{1,240})`")
_SHA = re.compile(r"\b(?=[0-9a-f]{7,40}\b)(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}\b")
_TRUNK = re.compile(r"\bclive/trunk\b")
_BRANCH = re.compile(r"\b(?:clive|claude|chatgpt)/[\w./-]+")
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]?\s+(?=[A-Z(\"'`“])")
_LABEL = re.compile(r"^\s*(?:BLOCKS|FOLLOW-UP|NOT A DEFECT|CANNOT TELL|MATERIAL|NON-MATERIAL)\s*(?:[:—–-]\s*)+", re.I)
_WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"]


def number_word(n: int, *, lower: bool = True) -> str:
    word = _WORDS[n] if 0 <= n < len(_WORDS) else str(n)
    return word.lower() if lower else word


# ------------------------------------------------------------------ cleaning words for the face


def test_name(ref: str) -> str:
    """A test as its name reads: tests/web/x.py::test_a_reconnect_never_opens_the_mic ->
    "a reconnect never opens the mic". Empty when `ref` is not a test id."""
    match = _TEST_ID.search(str(ref or ""))
    if not match:
        return ""
    return " ".join(match.group("name")[len("test_"):].split("_"))


def _code(span: str) -> str:
    named = test_name(span)
    if named and _TEST_ID.fullmatch(span.strip()):
        return f"“{named}”"
    path = _PATH.match(span.strip())
    if path:
        return path.group("base")
    return span


def face(text: Any, limit: int = FACE_CHARS) -> str:
    """Words fit for the face: redacted, code spans said plainly, no SHA, no branch name."""
    said = _said(text, TECHNICAL_CHARS)
    said = _CODE.sub(lambda m: _code(m.group(1)), said)
    said = _TEST_ID.sub(lambda m: f"“{test_name(m.group(0))}”", said)
    said = _TRUNK.sub("the trunk", said)
    said = _BRANCH.sub("its branch", said)
    said = _SHA.sub("", said)
    said = re.sub(r"\s+([,.;:)])", r"\1", re.sub(r"\(\s*\)", "", said))
    said = " ".join(said.split())
    return said if len(said) <= limit else said[: limit - 3].rstrip(" ,;:") + "..."


def sentences(text: Any) -> list[str]:
    words = " ".join(str(text or "").split())
    return [s.strip() for s in _SENTENCE_END.split(words) if s.strip()]


def first_sentence(text: Any, limit: int = FACE_CHARS) -> str:
    found = sentences(_LABEL.sub("", str(text or "")))
    return face(found[0], limit) if found else ""


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _stop(text: str) -> str:
    text = text.strip()
    return text if not text or text.endswith((".", "!", "?", "...")) else f"{text}."


# ------------------------------------------------------------------ why a build stopped

_REVIEW_LIMIT = re.compile(
    r"convergence limit: (?P<used>\d+) repair round\(s\) used of (?P<max>\d+); findings (?P<ids>[\w.-]+(?:, [\w.-]+)*)"
    r" on [0-9a-f]{40} remain")
_GITHUB_RED = re.compile(r"GitHub acceptance is red on [0-9a-f]{40}")
_FAILING_TEST = re.compile(r"failing: (?P<test>\S+::test_\w+)")
_REFUSED_CHECKS = re.compile(r"(?:worker results refused (?P<n>\d+) times?; last: )?result_refused: checks failed on [0-9a-f]{40}: "
                             r"(?P<check>[\w-]+) \(exit \d+\)")
_WORKSPACE = re.compile(r"^workspace: ")
_BUILDER = re.compile(r"^worker reported blocked: (?P<report>.*)$", re.S)
_OWNER_GATE = re.compile(r"^(?:owner_gate: )?worker reports an owner decision is required: (?P<report>.*)$", re.S)
_BASE_MISSING = re.compile(r"base ref does not resolve to the declared base sha")

# What a builder's own report says, recognised by its words, most specific first.
_BUILDER_SAYS = (
    (re.compile(r"doesn't say which gate failed|can't fetch the artifact", re.I),
     "it couldn't see why GitHub's tests failed"),
    (re.compile(r"fails on the untouched base|cannot pass in this environment at base|at base and here alike", re.I),
     "a required check already fails before any change, so it can't prove its work"),
    (re.compile(r"can't execute commands|cannot execute commands|can only be met by something that runs commands|"
                r"none of them can delete", re.I),
     "the job needs something its tools can't do"),
    (re.compile(r"conflicts with an existing suite|conflicts with two tests", re.I),
     "what it was asked to do conflicts with an existing test"),
    (re.compile(r"outside (?:the |my |this attempt's )?allowed paths|not in ALLOWED PATHS|can't be met inside the allowed paths|"
                r"cannot be met inside the allowed paths", re.I),
     "it can't finish without changing files it wasn't allowed to touch"),
)
_ASKS_TEST_CHANGE = re.compile(r"assertion|asserts|existing test|conflicts with .{0,60}tests?|test expects", re.I)


def _blocker(item: dict[str, Any]) -> str:
    return str(item.get("blocker") or item.get("stage_reason") or item.get("reason") or "")


def _runs(item: dict[str, Any]) -> list[str]:
    gate = item.get("github_acceptance")
    runs = gate.get("runs") if isinstance(gate, dict) else None
    return [str(r["id"]) for r in runs or [] if isinstance(r, dict) and isinstance(r.get("id"), int)
            and not isinstance(r.get("id"), bool)][:10]


def loop_said(text: Any, item: dict[str, Any], limit: int = TECHNICAL_CHARS) -> str:
    """The loop's own words, redacted as everywhere, except that the GitHub run ids the loop
    published for this request are kept: an eleven-digit run id reads to the customer-shape rule as
    a phone number, and "run [phone] failure" tells George nothing. Only ids from the record's own
    `github_acceptance.runs` are kept, each where it stands as a whole number."""
    words = str(text or "") if isinstance(text, (str, int, float)) else ""
    kept: dict[str, str] = {}
    for i, run in enumerate(_runs(item)):
        token = f"GHRUN{chr(65 + i)}KEPT"
        replaced = re.sub(rf"(?<![\w.-]){re.escape(run)}(?![\w.-])", token, words)
        if replaced != words:
            kept[token], words = run, replaced
    said = _said(words, limit)
    for token, run in kept.items():
        said = said.replace(token, run)
    return said


def _rounds(used: int) -> str:
    return {1: "its one repair round", 2: "both repair rounds"}.get(used, f"all {number_word(used)} repair rounds")


def why_stopped(item: dict[str, Any]) -> dict[str, Any]:
    """Why one request stopped, said plainly: `says` (one or two sentences for the face), `who` it
    waits on now (YOU or DIRECTOR), `kind`, where on the road it stopped (`at`), the open review
    finding ids, the failing test's name, and the loop's own words in full (`loop_words`)."""
    raw = _blocker(item)
    text = raw[len("blocked: "):] if raw.startswith("blocked: ") else raw
    out: dict[str, Any] = {"kind": "other", "who": DIRECTOR, "at": BUILT, "findings": [], "test": "",
                           "loop_words": loop_said(raw, item)}
    if str(item.get("outcome") or "") == "refused":
        out.update(kind="refused", at=FILED)
        out["says"] = ("The loop turned the request away: it named a starting point the build server didn't have."
                       if _BASE_MISSING.search(text) else
                       _stop(f"The loop turned the request away: {first_sentence(text) or 'it gave no reason'}"))
        return out
    review = _REVIEW_LIMIT.search(text)
    if review:
        ids = [i.strip() for i in review.group("ids").split(",") if i.strip()]
        used = int(review.group("used"))
        n = len(ids)
        out.update(kind="review_limit", who=YOU, at=REVIEWED, findings=ids)
        out["says"] = (f"The reviewer still found {number_word(n)} problem{'' if n == 1 else 's'} ({', '.join(ids)}) "
                       f"after {_rounds(used)}, "
                       "so the loop stopped and left the next step to you.")
        return out
    if _GITHUB_RED.search(text):
        failing = _FAILING_TEST.search(text)
        out.update(kind="github_red", at=REVIEWED, test=test_name(failing.group("test")) if failing else "")
        said = "GitHub's full test run failed on the finished build, so it never reached the reviewer."
        if out["test"]:
            said += f" The failing test: “{out['test']}”."
        if "repair round(s) are used" in text:
            said += " Its repair rounds were all used."
        out["says"] = said
        return out
    refused = _REFUSED_CHECKS.search(text)
    if refused:
        n = int(refused.group("n") or 1)
        out.update(kind="checks_failed", at=BUILT)
        out["says"] = (f"CLIVE's own {refused.group('check')} check failed on the builder's work "
                       f"{'once' if n == 1 else 'twice' if n == 2 else f'{number_word(n)} times'}, so the loop stopped trying.")
        return out
    if _WORKSPACE.match(text):
        out.update(kind="build_server", at=BUILT)
        out["says"] = ("The build server couldn't set up a place to build it, a problem on the server rather than in "
                       "the code. Nothing was built.")
        return out
    gate = _OWNER_GATE.match(text)
    if gate or item.get("stage") == "OWNER_GATE" or item.get("owner_gate") is True:
        report = gate.group("report") if gate else text
        out.update(kind="owner_gate", who=YOU, at=BUILT)
        out["says"] = ("The builder needs your say: what you asked for conflicts with an existing test, and changing "
                       "that test is yours to allow." if _ASKS_TEST_CHANGE.search(report) else
                       _stop(f"The builder needs your say: {first_sentence(report) or 'it gave no reason'}"))
        return out
    builder = _BUILDER.match(text)
    if builder:
        report = builder.group("report")
        out.update(kind="builder_stopped", at=BUILT)
        plain = next((words for pattern, words in _BUILDER_SAYS if pattern.search(report)), "")
        out["says"] = _stop(f"The builder stopped: {plain or first_sentence(report) or 'it gave no reason'}")
        return out
    out["says"] = _stop(f"The loop stopped it: {first_sentence(text) or 'it gave no reason'}") if text else \
        "The loop stopped it without saying why."
    return out


# ------------------------------------------------------------------ a reviewer's finding

# A sentence that says what goes wrong for someone: the finding's own reason it matters.
_HARM = re.compile(
    r"\b(leak|lose|loses|lost|loss|exploit|expos|breaks?|broken|crash|fails?|failing|wrong|refus|mislead|customer|"
    r"private|personal|secret|spend|money|charg|sends?|sent|unsafe|silently|data|owner|george)", re.I)
# The reviewer saying what it could not see: kept in the technical text, not put on the face.
_UNSURE = re.compile(r"^CANNOT TELL\b", re.I)
_EVIDENCE_PATH = re.compile(r"(?P<path>(?:[\w.-]+/)*[\w.-]+\.(?:py|js|css|html|md|json|ya?ml|txt))(?::(?P<line>\d{1,6}))?")


def _where(evidence: str) -> str:
    """Where the reviewer found it, in words: "Found in dispatch.py, line 120."."""
    if not evidence.strip():
        return ""
    found = _EVIDENCE_PATH.search(evidence)
    if found:
        name = found.group("path").rsplit("/", 1)[-1]
        return f"Found in {name}" + (f", line {found.group('line')}." if found.group("line") else ".")
    if re.search(r"packet", evidence, re.I):
        return "Found in what the reviewer was sent to review."
    return ""


def finding(record: dict[str, Any]) -> dict[str, Any]:
    """One reviewer finding as What's wrong, Why it matters and What fixes it, each from the record's
    own fields, with the technical text kept whole beside them. Takes the reviewer's shape
    (finding_id, material, finding, evidence_ref, required_repair) and the shorter one a published
    status may carry (id, severity, text)."""
    fid = _said(record.get("finding_id") or record.get("id"), 40) or "A finding"
    body = str(record.get("finding") or record.get("text") or "")
    evidence = str(record.get("evidence_ref") or record.get("evidence") or "")
    repair = str(record.get("required_repair") or record.get("repair") or "")
    material = record.get("material")
    labelled = bool(_LABEL.match(body))
    parts = [p for p in sentences(_LABEL.sub("", body)) if not _UNSURE.match(p)]
    if labelled and len(parts) >= 2:
        # A labelled finding ("BLOCKS — ...", "FOLLOW-UP — ...") opens with the reviewer's reason for
        # the label, which is why it matters; what is wrong follows it.
        harm, wrong = parts[0], face(parts[1])
    else:
        wrong = face(parts[0]) if parts else ""
        harm = next((s for s in parts[1:] if _HARM.search(s)), "")
    if harm:
        matters = face(harm)
    elif material is True:
        matters = "The reviewer marked it as something that must be fixed before the build can pass."
    elif material is False:
        matters = "The reviewer noted it, but it doesn't stop the build."
    else:
        severity = _said(record.get("severity"), 20)
        matters = f"The reviewer rated it {severity}." if severity else ""
    return {
        "id": fid,
        "wrong": _stop(_capital(wrong)) if wrong else "The reviewer gave no wording for it.",
        "matters": _stop(_capital(matters)) if matters else "",
        "where": _where(evidence),
        "fix": _stop(_capital(first_sentence(repair))) if repair.strip() else "The reviewer named no repair.",
        "material": material if isinstance(material, bool) else None,
        "technical": {"finding": _said(body, TECHNICAL_CHARS), "evidence": _said(evidence, 400),
                      "repair": _said(repair, TECHNICAL_CHARS)},
    }


def findings_of(item: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The findings a published status carries for a request, translated; None when it carries
    none (today's loop never publishes their text: app/remote_engineering/status.py)."""
    listed = item.get("findings")
    if not isinstance(listed, list):
        review = item.get("review")
        listed = review.get("findings") if isinstance(review, dict) else None
    if not isinstance(listed, list):
        return None
    return [finding(f) for f in listed[:10] if isinstance(f, dict)]
