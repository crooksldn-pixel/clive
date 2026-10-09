"""A made-up world for the research synthesis tests (DEC-078): invented notes and a scripted model.

Everything here is invented for CLIVE's tests (tests/fixtures/research/synthesis/test-note-*.md); none
of it is George's research. `Scripted` answers each step of the synthesis from the tables below, keyed
on the step's system prompt and on what the prompt holds (the document's name, a claim's title, an
idea's name), so a test can run the real pipeline end to end and change one answer to exercise one rule.

`build_world` runs the whole story the screen's contract example shows: three notes read the old way,
a full synthesis, a fourth note read before it is applied, applying it, George's answers, a fifth note
read into the live ideas, a file that couldn't be read, and one still being read. Run this module to
write the contract example from it:

    python -m tests.research_synthesis_fixture      (in crooks-assistant/)
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import re
from pathlib import Path
from typing import Any

from app.research.review import SYSTEM as REVIEW_SYSTEM
from app.research.synthesis.consolidate import CONSOLIDATE_SYSTEM
from app.research.synthesis.extract import EXTRACT_SYSTEM, REPAIR_SYSTEM
from app.research.synthesis.judge import JUDGE_SYSTEM, OWNER_VIEW_SYSTEM
from app.research.synthesis.match import MATCH_SYSTEM
from app.research.synthesis.summary import SUMMARY_SYSTEM

HERE = Path(__file__).resolve().parent
NOTES = HERE / "fixtures" / "research" / "synthesis"
EXAMPLE = HERE / "fixtures" / "research" / "ideas-payload.json"
OWNER_LOGIN = "team@crooksldn.com"


def note(name: str) -> bytes:
    return (NOTES / name).read_bytes()


def claim(title, says, quote, section, idea, *, kind="build", stance="supports", centrality="central"):
    return {"title": title, "says": says, "quote": quote, "section": section, "kind": kind, "idea": idea,
            "stance": stance, "centrality": centrality}


# Each note's recommendations as the scripted model reads them; `idea` is the idea it belongs to (by name).
CLAIMS: dict[str, list[dict[str, Any]]] = {
    "test-note-alpha.md": [
        claim("Keep jobs alive across restarts", "Every job CLIVE starts carries on after a restart.",
              "Every job CLIVE starts should carry on after the server restarts", "TEST SECTION: Restarts and jobs",
              "Work survives a restart", kind="principle"),
        claim("Use TestQueue for jobs", "Use an outside workflow engine to keep jobs alive.",
              "An outside workflow engine such as the invented TestQueue could keep these jobs alive",
              "TEST SECTION: Restarts and jobs", "Adopt a workflow engine for it", centrality="supporting"),
        claim("Apply small refunds automatically", "Refunds under five pounds go out without his approval.",
              "Refunds under five pounds should be applied automatically without his approval",
              "TEST SECTION: Small refunds", "Send small refunds without a hold"),
        claim("Show when each key was checked", "Each Connections card says when its key was last checked.",
              "Each card on the Connections screen should show when its key was last checked",
              "TEST SECTION: Connections cards", "Each key shows when it was checked"),
        # A list number inside the quote's line, where the note starts a line with it.
        claim("Update the stock page hourly", "The stock page is updated every hour.",
              "as soon as possible. 10. update the stock page every hour", "TEST SECTION: Order of work",
              "Stock page updates every hour", centrality="passing"),
        # A word broken at a line end, quoted with the space kept.
        claim("One source of truth for orders", "CLIVE keeps the one record of orders itself.",
              "CLIVE needs a single source-of- truth for orders", "TEST SECTION: Order of work",
              "CLIVE keeps one record of orders", kind="principle", centrality="supporting"),
        # Curly quotes in the note, straight in the quote.
        claim("Done only after reading back", "CLIVE says a change is done only once it has read it back.",
              "CLIVE should say \"it's done\" only after it reads the change back", "TEST SECTION: Order of work",
              "Done only after reading it back", kind="principle", centrality="passing"),
        # Paraphrased: found by the repair call.
        claim("Make stale keys obvious", "A stale key is obvious at a glance.", "stale keys must stand out at a glance",
              "TEST SECTION: Connections cards", "Each key shows when it was checked", centrality="supporting"),
        # Paraphrased, and the research never says it: unplaced, with why.
        claim("Send invoices by carrier pigeon", "Invoices go by carrier pigeon.", "pigeons carry every invoice to the bank",
              "TEST SECTION: Order of work", "Invoices by pigeon"),
    ],
    "test-note-beta.md": [
        claim("Finish jobs after a restart", "A half-done job finishes after a restart.",
              "A job that is halfway done when the server restarts should finish afterwards", "TEST SECTION: Keeping work",
              "Work survives a restart", centrality="supporting"),
        claim("Supplier messages in one thread", "The manufacturer's messages land in one thread CLIVE reads.",
              "Messages from the manufacturer should land in one thread that CLIVE reads and sums up",
              "TEST SECTION: Supplier threads", "Supplier messages in one thread"),
        claim("No approval for small refunds", "Small refunds need no approval.", "Refunds under five pounds need no approval at all",
              "TEST SECTION: Refund speed", "Send small refunds without a hold"),
        claim("A weekly learning note", "CLIVE writes a short weekly note of what it learned.",
              "CLIVE should write a short weekly note of what it learned about the business",
              "TEST SECTION: Learning notes", "A weekly note of what CLIVE learned", kind="process", centrality="passing"),
    ],
    "test-note-gamma.md": [
        claim("Stay on the flat plan", "CLIVE stays on the flat monthly plan, never a metered key.",
              "CLIVE should stay on the flat monthly plan and never use a metered key", "TEST SECTION: Monthly costs",
              "Answers stay on the Max plan", kind="principle"),
        claim("Tiny refunds go out by themselves", "Tiny refunds go out without the owner's approval.",
              "Let tiny refunds go out automatically without the owner's approval", "TEST SECTION: Tiny refunds",
              "Send small refunds without a hold", centrality="supporting"),
        claim("Never lose work on a restart", "A restart never loses work.", "A restart should never lose work that CLIVE was doing",
              "TEST SECTION: Reliability notes", "Work survives a restart", centrality="passing"),
        # Matched to an idea of its own, which consolidate then joins to the one it repeats.
        claim("Last-checked time on every key", "Every key shows a last-checked time.",
              "Show a last-checked time on every key so nobody trusts a dead one", "TEST SECTION: Key freshness",
              "Keys show a last-checked time"),
    ],
    "test-note-delta.md": [
        claim("Pick up unfinished jobs", "CLIVE picks up unfinished jobs by itself after a restart.",
              "When the server comes back, CLIVE should pick up its unfinished jobs by itself", "TEST SECTION: After a restart",
              "Work survives a restart"),
    ],
    "test-note-epsilon.md": [
        claim("Tell the owner what changed", "Once a week CLIVE tells the owner what it now thinks differently.",
              "Once a week CLIVE should tell the owner, in a few lines, what it now thinks differently",
              "TEST SECTION: What CLIVE learned", "A weekly note of what CLIVE learned", kind="process"),
    ],
}
STANCES = {"test-note-beta.md": [{"says": "Don't add an outside service just to keep jobs alive.",
                                  "quote": "Do not add a new outside service just to keep jobs alive",
                                  "idea": "Adopt a workflow engine for it"}]}
REPAIRS = {"Make stale keys obvious": "so a stale key is obvious", "Send invoices by carrier pigeon": None}

IDEAS = {
    "Work survives a restart": ("CLIVE's jobs survive a server restart and finish afterwards.", "foundational"),
    "Adopt a workflow engine for it": ("Use an outside workflow engine to keep CLIVE's jobs alive.", "tooling-choice"),
    "Send small refunds without a hold": ("Refunds under a few pounds go out without the owner's hold.", "safety"),
    "Each key shows when it was checked": ("Every key on the Connections screen says when CLIVE last checked it.", "capability"),
    "Stock page updates every hour": ("The stock page is brought up to date every hour.", "capability"),
    "CLIVE keeps one record of orders": ("CLIVE keeps the one record of orders that everything else reads.", "foundational"),
    "Done only after reading it back": ("CLIVE says a change is done only after reading it back.", "safety"),
    "Supplier messages in one thread": ("Everything the manufacturer sends lands in one thread CLIVE reads and sums up.", "capability"),
    "A weekly note of what CLIVE learned": ("Once a week CLIVE writes a few lines on what it now thinks differently.", "process"),
    "Answers stay on the Max plan": ("CLIVE keeps answering through the owner's flat plan, never a metered key.", "foundational"),
    "Keys show a last-checked time": ("Every key shows when it was last checked.", "capability"),
    "Invoices by pigeon": ("Invoices go by pigeon.", "capability"),
}
MERGES = {"Keys show a last-checked time": ("Each key shows when it was checked", "Both say every key shows when it was checked.")}


def view(means, today, after="", example="", before_after="", why_care=(), notice=""):
    return {"means": means, "today": today, "after": after, "example": example, "before_after": before_after,
            "why_care": list(why_care), "notice": notice}


def judgment(j, r, t, c, i, k, *, why="", when="", keys=(), basis=(), held=(), today=None, needs=None, effects=(),
             touches=(), done=(), differ="", revisit="", owner_view=None):
    return {"answers": {"judgment": j, "relationship": r, "timing": t, "confidence": c, "importance": i, "knowledge": k},
            "reasons": {"judgment": why, "timing": when}, "keys": [{"key": a, "how": b} for a, b in keys],
            "basis": list(basis), "timing_held_by": list(held), "today": today or {"level": "none", "says": "", "where": []},
            "needs_you": needs, "effects": list(effects), "touches": list(touches), "done_when": list(done),
            "how_they_differ": differ, "revisit": revisit, "owner_view": owner_view}


JUDGE: dict[str, dict[str, Any]] = {
    "Work survives a restart": judgment(
        "ADOPT", "EXTENDS_EXISTING", "NOW", "high", "FOUNDATIONAL", "STRENGTHENED",
        why="Every test note that mentions it agrees, and it serves DEC-005: a change is only done once it is read back.",
        when="It makes everything after it safer, so it comes first.",
        keys=[("DEC-005", "serves"), ("FEAT-010", "builds on")], basis=["DEC-005"],
        today={"level": "partial", "says": "Proposals are kept on disk; work in progress is not.",
               "where": ["app/actions/engine.py", "FEAT-010", "app/no_such_part/keeper.py"]},
        needs={"trigger": "opportunity", "question": "Do you want CLIVE to keep its work across restarts, starting with returns checks?"},
        effects=["HIGHER RELIABILITY", "LESS HUMAN ATTENTION"], touches=["app/work", "web/jobs.js", "app/actions"],
        done=["A job running when the server restarts finishes afterwards.", "Nothing is done twice after a restart."],
        differ="Alpha wants every job kept; beta only the half-done ones.", revisit="If restarts became so rare nothing is ever caught halfway.",
        owner_view=view("If the server restarts while CLIVE is doing something for you, it carries on afterwards.",
                        "A long job in progress starts again from nothing after a restart.",
                        "A restart in the middle of a returns check finishes the check instead of dropping it.",
                        "You ask CLIVE to check every open return while the server updates; today you ask again, after this it carries on.",
                        "Before: ask again after a restart. After: it finishes by itself.",
                        ["HIGHER RELIABILITY", "LESS HUMAN ATTENTION"], "The first time the server restarts while CLIVE is busy.")),
    "Adopt a workflow engine for it": judgment(
        "INVESTIGATE", "NEW", "UNSCHEDULED", "low", "USEFUL", "CHALLENGED",
        why="It is one way to reach the restart idea, not the goal itself, and it would be a new outside service.",
        when="Only once the goal is approved.", keys=[("RULE-1", "related")],
        today={"level": "none", "says": "CLIVE has no workflow engine.", "where": []},
        needs={"trigger": "uncertainty", "question": "Should CLIVE look into an outside engine, or keep this in its own code?"},
        effects=["HIGHER RELIABILITY"], differ="Alpha suggests an engine; beta argues against adding any outside service.",
        revisit="If keeping jobs in CLIVE's own code proves fragile.",
        owner_view=view("Running CLIVE's jobs through a separate engine made for keeping work alive.", "Nothing like it is in CLIVE.")),
    "Send small refunds without a hold": judgment(
        "ADOPT", "NEW", "NEXT", "high", "HIGH_LEVERAGE", "CHALLENGED",
        why="It would save the owner time on small refunds.", when="Soon.",
        keys=[("DEC-006", "related")], today={"level": "none", "says": "Every refund waits for his hold.", "where": ["app/actions/grammar.py"]},
        needs={"trigger": "clash", "question": "Your rule says nothing outward goes without your hold. Do you want to keep it for small refunds too?"},
        effects=["LESS HUMAN ATTENTION", "MAKES / PROTECTS MONEY"], touches=["app/families"],
        done=["Refunds under five pounds are sent automatically without his hold."],
        revisit="Only the owner's own change to rule 2.",
        owner_view=view("CLIVE would refund small amounts by itself, without you holding the card.", "Every refund waits for your hold.",
                        "A four-pound refund for a late parcel goes out at once.",
                        "A customer's tee arrives a day late and they ask for four pounds back; today it waits for you.",
                        "Before: every refund waits for you. After: small ones go by themselves.",
                        ["LESS HUMAN ATTENTION", "MAKES / PROTECTS MONEY"], "The next small refund.")),
    "Each key shows when it was checked": judgment(
        "ADOPT", "NEW", "NEXT", "high", "USEFUL", "NEW",
        why="Small and clear, and it serves the owner's keys from the app (DEC-065).", when="After the restart work.",
        keys=[("DEC-065", "serves")], today={"level": "none", "says": "The cards say whether a key is stored, not when it was checked.",
                                             "where": ["web/connections.js"]},
        needs={"trigger": "clash", "question": "Is a last-checked line worth it?"},   # not a clash: dropped by code
        effects=["LOWER RISK"], touches=["web/connections.js"],
        done=["Each Connections card says when its key was last checked."], revisit="If keys were checked so often a time added nothing.",
        owner_view=view("Each key on the Connections screen says how long ago CLIVE checked it.",
                        "You can't tell a stale key from a good one.")),
    "Stock page updates every hour": judgment(
        "ADOPT", "EXTENDS_EXISTING", "LATER", "medium", "OPTIMISATION", "NEW",
        why="Fresher stock counts help, but nothing is wrong today.", when="After the finish list.",
        keys=[("FEAT-003", "builds on")], today={"level": "partial", "says": "Stock is read when asked.", "where": ["FEAT-003"]},
        effects=["FASTER EXECUTION"], revisit="If stock mistakes started costing sales.",
        owner_view=view("The stock page is kept up to date every hour.", "It is read when someone asks.")),
    "CLIVE keeps one record of orders": judgment(
        "ADOPT_PARTLY", "PARTIALLY_SATISFIED", "LATER", "medium", "USEFUL", "MODIFIED",
        why="Right that Shopify stays the record; CLIVE keeping its own copy is not.", when="Later.",
        keys=[("DEC-004", "serves")], basis=["DEC-004"],
        today={"level": "substantial", "says": "Shopify is the record; CLIVE reads it.", "where": ["FEAT-003"]},
        effects=["HIGHER RELIABILITY"], revisit="If Shopify's record proved unreliable.",
        owner_view=view("One place that holds every order.", "Shopify holds them; CLIVE reads Shopify.")),
    "Done only after reading it back": judgment(
        "REJECT", "NEW", "UNSCHEDULED", "high", "FOUNDATIONAL", "VALIDATED",
        why="Already in CLIVE: FEAT-007 reads every change back.", when="Nothing to build.",
        keys=[("FEAT-007", "contradicts"), ("RULE-1", "serves")], basis=["FEAT-007"],
        today={"level": "complete", "says": "Every change is read back before it is called done.", "where": ["app/actions/engine.py"]},
        effects=["LOWER RISK"], revisit="Nothing the research could say.",
        owner_view=view("CLIVE says a change is done only once it has checked it.", "It already does this for every change.",
                        "Nothing changes: this confirms what CLIVE does.", "When it changes a price on your shop, it reads the price back first.",
                        "Before and after: the same.", ["LOWER RISK"], "You won't: it stays as it is.")),
    "Supplier messages in one thread": judgment(
        "INVESTIGATE", "EXTENDS_EXISTING", "NOW", "medium", "HIGH_LEVERAGE", "STRENGTHENED",
        why="Parked: DEC-018 says finish the current product first.", when="Not now.",
        keys=[("DEC-018", "contradicts"), ("IDEA-001", "builds on")], basis=["DEC-018"],
        today={"level": "partial", "says": "CLIVE keeps 90 days of messages from the channels it has.", "where": ["app/messaging/store.py"]},
        effects=["LESS HUMAN ATTENTION", "ENABLES NEW CAPABILITY"], touches=["app/messaging"],
        done=["The manufacturer's messages from email and chat show in one thread."], revisit="When DEC-018's finish list is clear.",
        owner_view=view("Everything your manufacturer sends lands in one place CLIVE reads and sums up.",
                        "Supplier messages are spread over email and chat.", "You ask CLIVE where the sample is and it answers from the thread.",
                        "", "Before: two places to look. After: one answer.", ["LESS HUMAN ATTENTION"], "The next sample round.")),
    "A weekly note of what CLIVE learned": judgment(
        "ADOPT_PARTLY", "NEW", "LATER", "medium", "HIGH_LEVERAGE", "NEW",
        why="A short weekly note is right; a long report is not.", when="After the finish list.",
        keys=[("DEC-018", "holds timing")], held=["DEC-018"], today={"level": "none", "says": "No weekly note exists.", "where": []},
        effects=["MOSTLY INTERNAL"], touches=["app/anticipation"], revisit="If you would read it.",
        owner_view=view("A short weekly note of what CLIVE now thinks differently.", "Nothing like it.")),
    "Answers stay on the Max plan": judgment(
        "ADOPT", "ALREADY_SATISFIED", "UNSCHEDULED", "high", "FOUNDATIONAL", "VALIDATED",
        why="Already CLIVE's rule 5; the research agrees.", when="Nothing to build.",
        keys=[("RULE-5", "already does it")], today={"level": "complete", "says": "The app refuses to start with an API key.",
                                                     "where": ["app/providers/max_agent_sdk.py"]},
        effects=["MAKES / PROTECTS MONEY"], revisit="Only the owner's own decision.",
        owner_view=view("CLIVE costs the same each month however much you use it.", "It already refuses a metered key.",
                        "Nothing changes: this confirms the rule.", "A busy drop day costs no more than a quiet Monday.",
                        "Before and after: the same plan.", ["MAKES / PROTECTS MONEY"], "You won't: it stays as it is.")),
}
OWNER_VIEWS = {
    "Supplier messages in one thread": view(
        "Everything your manufacturer sends lands in one place CLIVE reads and sums up.", "Supplier messages are spread over email and chat.",
        "You ask CLIVE where the sample is and it answers from the thread.",
        "Your manufacturer sends a sample photo on chat and the invoice by email; CLIVE puts both in one thread.",
        "Before: two places to look. After: one answer.", ["LESS HUMAN ATTENTION", "ENABLES NEW CAPABILITY"], "The next sample round."),
}
SUMMARY = {"points": ["TEST RESEARCH NOTE — invented for CLIVE's tests: CLIVE's work should survive a restart.",
                      "Keep every outward change behind your hold; the test notes disagree only on small refunds.",
                      "Each key should say when it was last checked.",
                      "Bring the manufacturer's messages into one thread, once the finish list is clear."],
           "before": "CLIVE loses work in progress when the server restarts",
           "after": "CLIVE carries its work through a restart and says how fresh each key is"}

# The old screen (DEC-070): what each note's proposals were, before ideas.
OLD = {
    "test-note-alpha.md": [
        {"title": "Show when each key was last checked", "says": "Each Connections card says when its key was last checked.",
         "quote": "Each card on the Connections screen should show when its key was last checked", "verdict": "adopt",
         "reason": "Serves keys from the app (DEC-065).", "cites": ["DEC-065"], "touches": ["web/connections.js"], "same_as": [],
         "done_when": ["Each Connections card says when its key was last checked."]},
        {"title": "Use TestQueue to keep jobs alive", "says": "Use an outside workflow engine.",
         "quote": "An outside workflow engine such as the invented TestQueue could keep these jobs alive", "verdict": "park",
         "reason": "Finishing current work comes first (DEC-018).", "cites": ["DEC-018"], "touches": ["app/work"], "same_as": [],
         "done_when": []},
        {"title": "Apply small refunds automatically", "says": "Small refunds go out without approval.",
         "quote": "Refunds under five pounds should be applied automatically without his approval", "verdict": "park",
         "reason": "Needs his say.", "cites": ["DEC-008"], "touches": ["app/families"], "same_as": [], "done_when": []},
    ],
    "test-note-beta.md": [
        {"title": "Supplier messages in one thread", "says": "The manufacturer's messages in one thread.",
         "quote": "Messages from the manufacturer should land in one thread that CLIVE reads and sums up", "verdict": "park",
         "reason": "Finishing current work comes first (DEC-018).", "cites": ["DEC-018"], "touches": ["app/messaging"], "same_as": ["IDEA-001"],
         "done_when": []},
    ],
    "test-note-gamma.md": [
        {"title": "Stay on the flat plan", "says": "CLIVE stays on the flat monthly plan.",
         "quote": "CLIVE should stay on the flat monthly plan and never use a metered key", "verdict": "reject",
         "reason": "Already live: the Max plan (FEAT-002).", "cites": ["FEAT-002"], "touches": ["app/providers"], "same_as": [],
         "done_when": []},
    ],
    "test-note-delta.md": [],
    "test-note-epsilon.md": [],
}


# ------------------------------------------------------------------ the scripted model


def _attr(prompt: str, key: str) -> str:
    match = re.search(rf'<research [^>]*{key}=("(?:[^"\\]|\\.)*")', prompt)
    return json.loads(match.group(1)) if match else ""


def _slug(name: str) -> str:
    return "new:" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class Scripted:
    """The model, answering from the tables above. `judge`, `owner_views`, `claims` and the rest are
    copies a test may change; every prompt is kept, by step."""

    name = "scripted"

    def __init__(self) -> None:
        self.claims = copy.deepcopy(CLAIMS)
        self.stances = copy.deepcopy(STANCES)
        self.repairs = dict(REPAIRS)
        self.ideas = dict(IDEAS)
        self.merges = dict(MERGES)
        self.judge = copy.deepcopy(JUDGE)
        self.owner_views = copy.deepcopy(OWNER_VIEWS)
        self.old = copy.deepcopy(OLD)
        self.summary = copy.deepcopy(SUMMARY)
        self.prompts: list[tuple[str, str]] = []
        self.fail_at: str = ""        # a step's name: that step's next call fails, once

    def step(self, system: str) -> str:
        return {EXTRACT_SYSTEM: "extract", REPAIR_SYSTEM: "repair", MATCH_SYSTEM: "match", CONSOLIDATE_SYSTEM: "consolidate",
                JUDGE_SYSTEM: "judge", OWNER_VIEW_SYSTEM: "owner_view", SUMMARY_SYSTEM: "summary",
                REVIEW_SYSTEM: "review"}.get(system, "unknown")

    def asked(self, step: str) -> list[str]:
        return [p for s, p in self.prompts if self.step(s) == step]

    async def ask(self, system: str, prompt: str) -> str:
        from app.research.model import ModelError

        self.prompts.append((system, prompt))
        step = self.step(system)
        if self.fail_at == step:
            self.fail_at = ""
            raise ModelError("The scripted model was told to fail here.")
        return json.dumps(getattr(self, f"_{step}")(prompt))

    def _document(self, prompt: str) -> str:
        return _attr(prompt, "name")

    def _review(self, prompt: str) -> dict[str, Any]:
        return {"recommendations": self.old.get(self._document(prompt), [])}

    def _extract(self, prompt: str) -> dict[str, Any]:
        name = self._document(prompt)
        return {"thesis": f"TEST: {name} is an invented note.", "concepts": [{"term": "job", "means": "work CLIVE does for the owner"}],
                "stances_against": [{"says": s["says"], "quote": s["quote"]} for s in self.stances.get(name, [])],
                "sequence": [], "claims": [{k: c[k] for k in ("title", "says", "quote", "section", "kind")} | {"priority_in_doc": n}
                                           for n, c in enumerate(self.claims.get(name, []), 1)]}

    def _repair(self, prompt: str) -> dict[str, Any]:
        out = []
        for n, title in re.findall(r"(?m)^(\d+)\. ([^:\n]+):", prompt):
            out.append({"n": int(n), "quote": self.repairs.get(title)})
        return {"quotes": out}

    def _known(self, prompt: str) -> dict[str, str]:
        block = prompt.split("</research>", 1)[0]
        return {name.strip(): idea_id for idea_id, name in re.findall(r"(?m)^(idea-\d{4,6}): (.+?) — ", block)}

    def _claim(self, title: str) -> dict[str, Any] | None:
        return next((c for claims in self.claims.values() for c in claims if c["title"] == title), None)

    def _match(self, prompt: str) -> dict[str, Any]:
        known = self._known(prompt)
        placed, new = [], {}
        for n, title in re.findall(r"(?m)^C(\d+): (.+?)\. ", prompt):
            found = self._claim(title)
            if found is None:
                continue
            idea = found["idea"]
            ref = known.get(idea) or _slug(idea)
            if ref.startswith("new:"):
                statement, kind = self.ideas[idea]
                new[ref] = {"key": ref, "name": idea, "statement": statement, "kind": kind}
            placed.append({"c": f"C{n}", "idea": ref, "stance": found["stance"], "centrality": found["centrality"]})
        stances = []
        for n, says in re.findall(r"(?m)^S(\d+): (.+)$", prompt):
            target = next((s["idea"] for ss in self.stances.values() for s in ss if s["says"] == says.strip()), None)
            stances.append({"s": f"S{n}", "idea": known.get(target) if target else None})
        return {"claims": placed, "new": list(new.values()), "stances": stances}

    def _consolidate(self, prompt: str) -> dict[str, Any]:
        known = {name: idea_id for idea_id, name in re.findall(r"(?m)^(idea-\d{4,6}): (.+?) — ", prompt)}
        merges = []
        for other, (keep, why) in self.merges.items():
            if other in known and keep in known:
                merges.append({"keep": known[keep], "merge": [known[other]], "why": why})
        return {"merges": merges}

    def _judge(self, prompt: str) -> dict[str, Any]:
        body = prompt.split("</clive_design>", 1)[1]
        out = []
        for idea_id, name in re.findall(r"(?m)^(idea-\d{4,6}): (.+)$", body):
            answer = self.judge.get(name.strip())
            if answer is not None:
                out.append(dict(copy.deepcopy(answer), id=idea_id))
        return {"ideas": out}

    def _owner_view(self, prompt: str) -> dict[str, Any]:
        name = re.search(r"(?m)^idea-\d{4,6}: (.+)$", prompt).group(1).strip()
        return {"owner_view": self.owner_views.get(name) or (self.judge.get(name) or {}).get("owner_view") or {}}

    def _summary(self, prompt: str) -> dict[str, Any]:
        return copy.deepcopy(self.summary)

    def _unknown(self, prompt: str) -> dict[str, Any]:
        raise AssertionError("a prompt this model doesn't know")


# ------------------------------------------------------------------ the story


async def read_old_way(store, model, *names: str) -> list[dict[str, Any]]:
    """Notes given and read as DEC-070 reads them, before any synthesis is live."""
    from app.research import flow

    for name in names:
        flow.receive(store, name, note(name), via="screen")
    return await flow.run_pending(store, model=model)


@contextlib.contextmanager
def isolated(root: Path):
    """A research store and an owner's ledger of their own under `root`, installed for the duration."""
    from app.builds import decisions
    from app.objectives import store as objectives_store
    from app.research import store as research_store

    before = (objectives_store._STORE, decisions._LEDGER)
    objectives_store._STORE = objectives_store.ObjectiveStore(root / "objectives")
    decisions._LEDGER = None
    store = research_store.install(root / "research")
    try:
        yield store, decisions.ledger()
    finally:
        objectives_store._STORE, decisions._LEDGER = before
        research_store.install(None)


async def build_world(store, ledger, *, the_map=None, prepared_request: str = "research-idea-test-0001") -> dict[str, Any]:
    """The whole story, in `store` (the installed research store) with `ledger` (the installed owner's
    ledger). Returns {"store", "model", "gen", "ledger"}."""
    from app.builds import decisions
    from app.research import flow
    from app.research.rules import read_map
    from app.research.synthesis import answers as idea_answers
    from app.research.synthesis.apply import apply
    from app.research.synthesis.run import synthesise
    from app.research.synthesis.store import synthesis_store

    the_map = the_map or read_map()
    model = Scripted()
    await read_old_way(store, model, "test-note-alpha.md", "test-note-beta.md", "test-note-gamma.md")
    gen = await synthesise(store, model=model, the_map=the_map)
    await read_old_way(store, model, "test-note-delta.md")
    await apply(store, gen, model=model, the_map=the_map)
    synth = synthesis_store(store)
    ideas = {i["name"]: i for i in synth.ideas(gen).values() if i.get("status") == "active"}
    keys = ideas["Each key shows when it was checked"]
    decisions.decide(ledger, idea_answers.question(keys), "go", principal=OWNER_LOGIN, session_id="fixture")
    synth.event(gen, "owner_answered", idea=keys["id"], answer="go", said="You chose Approve the work.")
    synth.note_prepared(keys["id"], prepared_request)
    synth.event(gen, "prepared", idea=keys["id"], request_id=prepared_request,
                said="Its build request was prepared on a card, waiting for your hold.")
    weekly = ideas["A weekly note of what CLIVE learned"]
    decisions.decide(ledger, idea_answers.question(weekly), "later", principal=OWNER_LOGIN, session_id="fixture")
    synth.event(gen, "owner_answered", idea=weekly["id"], answer="later", said="You chose Not now.")
    flow.receive(store, "test-note-epsilon.md", note("test-note-epsilon.md"), via="folder")
    await flow.run_pending(store, model=model, the_map=the_map)
    store.refused_document("test-note-zeta.pdf", "No text could be read from it.", via="folder")
    flow.receive(store, "test-note-eta.md", b"# TEST RESEARCH NOTE - invented for CLIVE's tests (eta)\n\nStill being read.\n",
                 via="screen")
    return {"store": store, "model": model, "gen": gen, "ledger": ledger}


async def payload(store, ledger) -> dict[str, Any]:
    """The section exactly as GET /objectives/research builds it for the story, with the build loop's
    answers made up: the approved idea's request is prepared and not filed yet."""
    from app.builds import research as section
    from app.builds import research_ideas

    world = await build_world(store, ledger)
    previous = section._filed
    section._filed_cache.clear()

    async def not_filed(_request_id: str) -> str:
        return "no"

    section._filed = not_filed
    try:
        return await research_ideas.current(world["store"], world["ledger"])
    finally:
        section._filed = previous


def write_example() -> Path:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="ideas-example-") as folder:
        try:
            with isolated(Path(folder)) as (store, ledger):
                found = asyncio.run(payload(store, ledger))
        finally:
            _open_up(Path(folder))
    EXAMPLE.write_text(json.dumps(found, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return EXAMPLE


def _open_up(folder: Path) -> None:
    """The quarantine is read-only by design; open it up so the folder can be removed."""
    import os

    for base, dirs, files in os.walk(folder):
        for name in dirs + files:
            try:
                os.chmod(os.path.join(base, name), 0o700, follow_symlinks=False)
            except (OSError, NotImplementedError):
                pass


if __name__ == "__main__":
    print(write_example())
