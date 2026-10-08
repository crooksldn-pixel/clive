"""What a research recommendation is checked against: the map's rules, what is parked, every
decision, the ideas and features already written down, and what is live.

Why this exists: George's research (docs/RESEARCH.md) is weighed against CLIVE's own design, not
against the model's taste. That design is in the repository, so it is read from there every time,
never copied: MAP.md's rules that never bend and its Parked table, DECISIONS.md, IDEAS.md and
FEATURES.md (through the digester's self-model, app/digest/selfmodel.py), and CURRENT_TRUTH.md.

What it promises:
- Every citation a proposal may carry is a key read here — RULE-n, PARKED-n, DEC-nnn, IDEA-nnn,
  FEAT-nnn, or TRUTH — and `label` says it in words. A key the map does not hold is not a citation.
- The rules that never bend are also checked without the model (`vetoes`): a recommendation whose
  own words ask for what a rule forbids (an Anthropic API key, a change without his hold, words
  matched in front of the model, customer details in logs ...) is recommended for rejection with
  that rule cited, whatever the model said. The check only ever moves a recommendation towards
  "reject"; George's answer is still his.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]          # crooks-assistant/
MAP_FILE = "MAP.md"
TRUTH_FILE = Path("docs") / "product-memory" / "CURRENT_TRUTH.md"
MAX_TRUTH_CHARS = 14_000

_RULE = re.compile(r"^(\d{1,2})\.\s+\*\*(.+?)\*\*\s*(.*)$")
_MARKS = re.compile(r"[*`]")


@dataclass(frozen=True)
class Entry:
    """One thing a proposal may cite: its key, its kind, what it is called, and its status."""

    key: str
    kind: str        # rule, parked, decision, idea, feature, truth
    title: str
    status: str = ""
    detail: str = ""

    def label(self) -> str:
        if self.kind == "rule":
            return f"Rule {self.key.split('-')[1]}: {self.title}"
        if self.kind == "parked":
            return f"Parked: {self.title}"
        if self.kind == "truth":
            return "What is live now (CURRENT_TRUTH)"
        return f"{self.key} {self.title}"


@dataclass(frozen=True)
class Map:
    """The design a recommendation is weighed against, read from the repository."""

    entries: dict[str, Entry]
    truth: str
    digest: str
    self_model: object = None

    def get(self, key: str) -> Entry | None:
        return self.entries.get(str(key or "").strip().upper())

    def of(self, kind: str) -> list[Entry]:
        return [e for e in self.entries.values() if e.kind == kind]


# ------------------------------------------------------------------ reading the map


def read_map(root: Path | None = None, *, self_model=None) -> Map:
    """The map as it stands in the checkout at `root` (crooks-assistant/). The self-model gives
    the decisions, ideas and features; built here when not given."""
    root = Path(root or APP_ROOT)
    if self_model is None:
        from app.digest.selfmodel import build_self_model

        self_model = build_self_model(root)
    entries: dict[str, Entry] = {}
    map_text = _read(root / MAP_FILE)
    for entry in [*_rules(map_text), *_parked(map_text), *_memory(self_model)]:
        entries.setdefault(entry.key, entry)
    truth = _read(root / TRUTH_FILE)[:MAX_TRUTH_CHARS]
    entries["TRUTH"] = Entry("TRUTH", "truth", "CURRENT_TRUTH.md")
    digest = hashlib.sha256((map_text + truth + str(getattr(self_model, "digest", ""))).encode("utf-8")).hexdigest()
    return Map(entries=entries, truth=truth, digest=digest, self_model=self_model)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _section(text: str, heading: str) -> list[str]:
    lines = text.split("\n")
    out: list[str] = []
    inside = False
    for line in lines:
        if line.startswith("## "):
            inside = line[3:].strip().lower() == heading.lower()
            continue
        if inside:
            out.append(line)
    return out


def _rules(text: str) -> list[Entry]:
    found = []
    for line in _section(text, "The rules that never bend"):
        match = _RULE.match(line.strip())
        if match:
            number, title, rest = match.groups()
            found.append(Entry(f"RULE-{int(number)}", "rule", _plain(title).rstrip("."), detail=_plain(rest)))
    return found


def _parked(text: str) -> list[Entry]:
    found = []
    for line in _section(text, "Parked"):
        if not line.startswith("| ") or line.startswith("| What") or set(line) <= set("|- "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        what = _plain(cells[0])
        name = what.split(":", 1)[0].strip() or what[:60]
        found.append(Entry(f"PARKED-{len(found) + 1}", "parked", name[:80],
                           status=_plain(cells[3]) if len(cells) > 3 else "",
                           detail=f"{what}. Why: {_plain(cells[1])}. Decision: {_plain(cells[2])}"))
    return found


def _memory(self_model) -> list[Entry]:
    found = []
    kinds = {"decision": "decision", "idea": "idea", "feature": "feature"}
    for entry in getattr(self_model, "entries", ()) or ():
        kind = kinds.get(getattr(entry, "kind", ""))
        if kind is None:
            continue
        key = entry.key.split(":", 1)[1]
        found.append(Entry(key, kind, entry.name, status=entry.status or ""))
    return found


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", _MARKS.sub("", str(text or ""))).strip()


# ------------------------------------------------------------------ the rules, checked without a model


@dataclass(frozen=True)
class Veto:
    rule: str
    pattern: re.Pattern[str]
    words: str           # what the recommendation asks for, as "it ..." finishes it
    also: tuple[str, ...] = ()


def _p(text: str) -> re.Pattern[str]:
    return re.compile(text, re.IGNORECASE)


VETOES: tuple[Veto, ...] = (
    Veto("RULE-5", _p(r"\b(?:pay[- ]as[- ]you[- ]go|per[- ]token (?:billing|pricing)|anthropic[_ ]api(?:[_ ]key)?|claude api key"
                      r"|api[- ]key (?:for|from) (?:anthropic|claude))\b"),
         "asks for pay-as-you-go billing (an Anthropic API key) instead of the Max plan"),
    Veto("RULE-2", _p(r"\b(?:auto(?:matically)?[- ]?(?:send|reply|replies|refund|publish|approve|charge|pay|email|message)\w*"
                      r"|(?:send|sent|reply|replies|refund|publish|approv|charg|email|messag)\w*\b[^.;]{0,48}\bautomatically"
                      r"|without (?:his |the owner's |the owner |george's |any )?(?:approval|confirmation|sign[- ]off|tap|hold)"
                      r"|(?:skip|bypass|remove|drop)\w* (?:the |his )?(?:hold|approval|confirmation|approval gate)"
                      r"|(?:spoken|voice) (?:yes|approval|confirmation))\b"),
         "lets something go out, spend or change the shop without his gesture on its card", ("DEC-006",)),
    Veto("RULE-7", _p(r"\b(?:keyword|phrase|regex|intent)[- ]?(?:match(?:ing|er|es)?|router|routing|shortcuts?)\b"
                      r"|\bfast[- ]?paths?\b|\b(?:bypass|skip)\w* the model\b|\bwithout (?:calling |asking )?the model\b"),
         "acts on words before the model reads them", ("DEC-063",)),
    Veto("RULE-4", _p(r"\bcustomers?(?:'s?)? (?:data|details|names?|emails?|addresses|phone numbers?|pii)\b[^.]{0,80}"
                      r"\b(?:logs?|logging|telemetry|analytics events?|urls?|query strings?|build requests?)\b"
                      r"|\b(?:log|logging|telemetry)\b[^.]{0,60}\bcustomers?(?:'s?)? (?:data|details|names?|emails?|addresses)\b"),
         "puts customer details where they must never go (logs, URLs, telemetry or build requests)"),
    Veto("RULE-8", _p(r"\b(?:weaken|loosen|relax|disable|delete|remove|skip|turn off)\w* (?:(?:the|a|an|some|existing|flaky|failing|slow|old|broken) ){0,3}"
                      r"(?:tests?|test assertions?|assertions?|gate|approvals?|secret scanning|acceptance(?: run)?|kernel)\b"),
         "weakens a test, an approval, the gate or the acceptance machinery", ("DEC-064",)),
    Veto("RULE-3", _p(r"\bfail(?:s|ing)? open\b|\bdefaults? to (?:allow|green|approved)\b|\ballow unknown (?:tools|writes)\b"),
         "lets an unknown tool or write through instead of failing closed", ("DEC-007",)),
    Veto("RULE-1", _p(r"\b(?:assume|treat (?:it )?as|report (?:it )?as) (?:it )?(?:succeeded|successful|success|done)\b"
                      r"|\bskip (?:the )?(?:verification|read[- ]?back)\b|\boptimistic(?:ally)? (?:success|updates?|confirm\w*)\b"),
         "reports a change as done without reading it back", ("DEC-005",)),
    Veto("RULE-6", _p(r"\bdeploy\w* (?:straight |directly )?from (?:a |the |his )?(?:feature )?(?:branch|laptop|local|mac)\b"
                      r"|\bskip\w* (?:the )?(?:ci|acceptance)\b|\bwithout (?:ci|acceptance)\b"),
         "ships something that is not on the trunk and green", ("DEC-058",)),
)


# Words just before a match that turn it around: "never use an API key" keeps the rule, it does not
# break it.
_NEGATED = re.compile(r"\b(?:never|not|no|don't|do not|avoid\w*|instead of|rather than|refus\w*|forbid\w*|without)\b[^.;:]{0,30}$",
                      re.IGNORECASE)


def vetoes(text: str) -> list[tuple[Veto, str]]:
    """Each rule that never bends which these words ask CLIVE to break, with the words that did.
    A match the sentence itself negates ("never ...", "instead of ...") is not one."""
    hits = []
    words = text or ""
    for veto in VETOES:
        for match in veto.pattern.finditer(words):
            if _NEGATED.search(words[max(0, match.start() - 60):match.start()]):
                continue
            hits.append((veto, match.group(0)))
            break
    return hits
