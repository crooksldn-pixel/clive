"""CLIVE learns from research instead of piling it up (DEC-078, app/research/synthesis).

Proved here, on notes invented for these tests (tests/fixtures/research/synthesis/), with the model
scripted and keyed on each prompt (tests/research_synthesis_fixture.py) and the map read from this
repository:

- every recommendation is kept, with no cap, pinned to the research's own words: a list number, a
  word broken at a line end and curly quotes all match; a paraphrase is repaired by one more call, or
  is unplaced with why;
- every claim lands in exactly one idea; a repeat raises support and makes no new idea; an argument
  against an idea is kept and shows as disagreement;
- the history is append-only; reading the same document again asks nothing and records nothing;
- the axes are enforced in code, whatever the model said: already done is never a reason to reject,
  DEC-018 only holds timing, a rule that never bends makes CONFLICT at three documents and REJECT
  below, a false "needs you" is dropped, a place in the code that isn't there is removed, and an owner
  view that is incomplete is asked for again and never shown as complete;
- the old screen's proposals become history on the right ideas, and their records stay byte for byte;
- applying a generation keeps ids by overlap and keeps the one it replaces on disk;
- his answers bind to what he saw; approving prepares a card whose request carries none of the
  research's own words, and nothing is filed; the old answers say "superseded" once ideas are live;
- the model is still asked with no tools and no settings, and research only ever sits inside
  <research> tags;
- the route gives exactly the payload contract, and the contract example is the real code's output.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.builds import decisions, research_ideas
from app.builds import research as section
from app.research import flow
from app.research.rules import read_map
from app.research.synthesis import answers as idea_answers
from app.research.synthesis import consolidate, judge
from app.research.synthesis.apply import apply, export, reuse
from app.research.synthesis.ask import Calls, data
from app.research.synthesis.extract import extract
from app.research.synthesis.ideas import documents_backing, new_idea
from app.research.synthesis.quotes import FOUND, FOUND_LETTERS, MISSING, find_quote, passage
from app.research.synthesis.run import Stopped, Work, absorb, synthesise
from app.research.synthesis.store import synthesis_store
from app.research.synthesis.words import AXES, CHOICES, EFFECTS, KINDS, TRIGGERS, WORDS
from tests import research_synthesis_fixture as fx

OWNER = {"Tailscale-User-Login": fx.OWNER_LOGIN, "X-Forwarded-For": "100.64.0.9"}
FIRST_THREE = ("test-note-alpha.md", "test-note-beta.md", "test-note-gamma.md")


@pytest.fixture(scope="module")
def the_map():
    return read_map()


@pytest.fixture()
def place(tmp_path):
    """A research store and an owner's ledger of their own, installed for the test."""
    with fx.isolated(tmp_path) as (store, ledger):
        yield store, ledger
    fx._open_up(tmp_path)


async def _synthesised(store, the_map, model=None, *names):
    model = model or fx.Scripted()
    await fx.read_old_way(store, model, *(names or FIRST_THREE))
    gen = await synthesise(store, model=model, the_map=the_map)
    return model, gen


def _active(store, gen) -> dict[str, dict]:
    return {i["name"]: i for i in synthesis_store(store).ideas(gen).values() if i.get("status") == "active"}


def _events(store, gen) -> list[dict]:
    return synthesis_store(store).events(gen)


# ------------------------------------------------------------------ quotes: the research's own words


DOC = """## Plan

It should be done as soon as possible.
10. update the inventory page every hour so stock is right.

We need a single source-of-
truth for orders across every channel.

CLIVE should say “it’s done” only after it reads the change back.
"""


@pytest.mark.parametrize(("quote", "how"), [
    ("possible. 10. update the inventory page every hour", FOUND),           # a list number inside the line
    ("We need a single source-of- truth for orders", FOUND),                 # a broken word, the space kept
    ("We need a single source-of-truth for orders", FOUND_LETTERS),          # a broken word, mended
    ('CLIVE should say "it\'s done" only after it reads the change back', FOUND),   # straight for curly
])
def test_a_quote_is_found_as_the_research_wrote_it(quote, how):
    span, why = find_quote(DOC, quote)
    assert why == how and span is not None
    kept = passage(DOC, span)
    assert kept.split()[0] in DOC and kept.split()[-1].rstrip(".") in DOC
    assert DOC[span[0]:span[1]].startswith(kept.split()[0]), "the span is the document's own text"


def test_a_near_quote_is_found_and_an_invented_one_is_not():
    near = "CLIVE should say it is done only after it has read the change back"
    span, why = find_quote(DOC, near)
    assert span is not None and why.startswith("found")
    assert find_quote(DOC, "nothing like this is anywhere in the research at all") == (None, MISSING)
    assert find_quote(DOC, "short")[0] is None


async def test_every_recommendation_is_kept_with_no_cap():
    """A document with 40 recommendations keeps 40 (DEC-070 kept 25)."""
    text = "\n\n".join(f"## TEST SECTION: Part {n}\n\nCLIVE should do invented thing number {n} for the test owner every day."
                       for n in range(1, 41))
    model = fx.Scripted()
    model.claims["forty.md"] = [fx.claim(f"Invented thing {n}", f"Do invented thing {n}.",
                                         f"CLIVE should do invented thing number {n} for the test owner",
                                         f"TEST SECTION: Part {n}", f"Idea {n}") for n in range(1, 41)]
    found = await extract(name="forty.md", text=text, calls=Calls(model))
    assert len(found["claims"]) == 40 and found["unplaced"] == []
    assert [c["n"] for c in found["claims"]] == list(range(1, 41))


async def test_quotes_are_the_documents_own_words_and_a_paraphrase_is_repaired_or_unplaced():
    name = "test-note-alpha.md"
    text = fx.note(name).decode()
    model = fx.Scripted()
    calls = Calls(model)
    found = await extract(name=name, text=text, calls=calls)
    by = {c["title"]: c for c in found["claims"]}
    assert by["Update the stock page hourly"]["quote"].startswith("as soon as possible. 10. update the stock page")
    assert by["One source of truth for orders"]["quote"] == "CLIVE needs a single source-of- truth for orders"
    assert "“it’s done”" in by["Done only after reading back"]["quote"], "the note's curly quotes, not the model's straight ones"
    assert by["Make stale keys obvious"]["quote"] == "so a stale key is obvious."
    assert by["Make stale keys obvious"]["found"].endswith("after CLIVE asked again for the exact passage")
    (unplaced,) = found["unplaced"]
    assert unplaced["title"] == "Send invoices by carrier pigeon"
    assert "asked again for the exact passage" in unplaced["why"]
    assert calls.by_stage == {"extract": 1, "repair": 1}, "one repair call for both paraphrases"


async def test_two_claims_over_one_passage_are_one_claim():
    text = "## TEST SECTION: One\n\nEvery job CLIVE starts should carry on after the server restarts, instead of being lost.\n"
    model = fx.Scripted()
    model.claims["one.md"] = [fx.claim("Keep jobs", "Jobs carry on.", "Every job CLIVE starts should carry on", "TEST SECTION: One", "x"),
                              fx.claim("Do not lose jobs", "Jobs are not lost.", "after the server restarts, instead of being lost",
                                       "TEST SECTION: One", "x")]
    model.claims["one.md"][1]["quote"] = "CLIVE starts should carry on after the server restarts"
    found = await extract(name="one.md", text=text, calls=Calls(model))
    (only,) = found["claims"]
    assert only["title"] == "Keep jobs" and only["also"] == ["Do not lose jobs"]


# ------------------------------------------------------------------ ideas: every claim once, repeats, disagreement


async def test_every_claim_lands_in_exactly_one_idea_and_a_repeat_makes_no_new_idea(place, the_map):
    store, _ledger = place
    model, gen = await _synthesised(store, the_map)
    synth = synthesis_store(store)
    claims = [c["id"] for doc in synth.claims(gen).values() for c in doc["claims"]]
    landed = [s["claim_id"] for i in synth.ideas(gen).values() if i["status"] == "active" for s in i["sources"]]
    assert sorted(landed) == sorted(claims) and len(set(landed)) == len(landed)
    ideas = _active(store, gen)
    restart = ideas["Work survives a restart"]
    assert len(documents_backing(restart)) == 3, "alpha, beta and gamma back it"
    assert [n for n in ideas if "restart" in n.lower()] == ["Work survives a restart"]
    assert "Keys show a last-checked time" not in ideas, "consolidate joined it to the idea it repeats"
    merged = [i for i in synth.ideas(gen).values() if i["status"] == "merged"]
    assert [i["name"] for i in merged] == ["Keys show a last-checked time"]
    assert merged[0]["merged_into"] == ideas["Each key shows when it was checked"]["id"]


async def test_an_argument_against_an_idea_is_kept_and_shows_as_disagreement(place, the_map):
    store, ledger = place
    model, gen = await _synthesised(store, the_map)
    synth = synthesis_store(store)
    synth.set_live(gen)
    engine = _active(store, gen)["Adopt a workflow engine for it"]
    (against,) = engine["against"]
    assert against["claim_id"].startswith("stance:doc-") and against["why"].startswith("Don't add an outside service")
    assert engine["answers"]["knowledge"] == "CHALLENGED"
    payload = await research_ideas.current(store, ledger)
    row = next(r for g in payload["groups"] for r in g["ideas"] if r["id"] == engine["id"])
    assert row["against"] == [{"document": "test-note-beta.md", "says": against["why"]}]
    assert payload["synthesis"]["counts"]["disagreements"] >= 1


async def test_a_claim_put_in_an_idea_that_does_not_exist_is_asked_again_then_starts_its_own(place, the_map):
    store, _ledger = place
    model = fx.Scripted()
    real = model._match

    def stubborn(prompt):
        out = real(prompt)
        for placed in out["claims"]:
            if placed["c"] == "C1":
                placed["idea"] = "idea-9999"
        return out

    model._match = stubborn
    await fx.read_old_way(store, model, "test-note-delta.md")
    synth = synthesis_store(store)
    gen = synth.new_generation()
    work = Work(synth, gen, Calls(model), the_map)
    (record,) = store.documents()
    await absorb(work, record, flow.document_text(_units(store, record)))
    (idea,) = work.active()
    assert idea["name"] == "Pick up unfinished jobs", "its own idea, named from the claim"
    assert len(model.asked("match")) == 2


def _units(store, record):
    from app.digest.store import DigestStore

    return DigestStore(store.digests).load(record["artifact_id"]).units


# ------------------------------------------------------------------ the history, and reading twice


async def test_the_history_is_append_only_and_reading_the_same_document_again_changes_nothing(place, the_map):
    store, ledger = place
    model, gen = await _synthesised(store, the_map)
    path = synthesis_store(store).gen_dir(gen) / "events.jsonl"
    before = path.read_bytes()
    assert os.stat(path).st_mode & 0o777 == 0o600
    synth = synthesis_store(store)
    work = Work(synth, gen, Calls(model), the_map)
    asked = len(model.prompts)
    for record in store.documents():
        assert await absorb(work, record, "ignored: it is already in") == set()
    assert len(model.prompts) == asked and path.read_bytes() == before, "no model call, no event"
    await fx.read_old_way(store, model, "test-note-delta.md")
    await apply(store, gen, model=model, the_map=the_map)
    after = path.read_bytes()
    assert len(after) > len(before) and after.startswith(before), "earlier lines are never rewritten"


async def test_the_same_file_given_again_once_live_asks_nothing(place, the_map):
    store, ledger = place
    world = await fx.build_world(store, ledger, the_map=the_map)
    model = world["model"]
    await flow.run_pending(store, model=model, the_map=the_map)      # the note still waiting to be read
    asked = len(model.prompts)
    events = _events(store, world["gen"])
    flow.receive(store, "copy-of-epsilon.md", fx.note("test-note-epsilon.md"), via="screen")
    ended = [r for r in await flow.run_pending(store, model=model, the_map=the_map) if r["name"] == "copy-of-epsilon.md"]
    assert ended[0]["repeat_of"] and "what it says is in CLIVE's ideas" in ended[0]["why"]
    assert len(model.prompts) == asked and _events(store, world["gen"]) == events


# ------------------------------------------------------------------ the axes, enforced in code


def _idea(statement="An invented idea for CLIVE's tests.", docs=1):
    idea = new_idea("idea-0001", name="Invented idea", statement=statement, kind="capability", at="2026-10-09T00:00:00+00:00")
    idea["sources"] = [{"doc_id": f"doc-{n:020d}", "claim_id": f"doc-{n:020d}:1", "document": f"test-{n}.md", "section": "",
                        "quote": "q", "says": statement, "title": "t", "stance": "supports", "centrality": "central"}
                       for n in range(docs)]
    return idea


def _raw(j="ADOPT", r="NEW", t="NEXT", *, keys=(), basis=(), held=(), where=(), level="partial", needs=None, importance="USEFUL",
         owner_view=None, why=""):
    return {"answers": {"judgment": j, "relationship": r, "timing": t, "confidence": "high", "importance": importance,
                        "knowledge": "NEW"}, "reasons": {"judgment": why, "timing": ""},
            "keys": [{"key": k, "how": h} for k, h in keys], "basis": list(basis), "timing_held_by": list(held),
            "today": {"level": level, "says": "x", "where": list(where)}, "needs_you": needs, "effects": [], "touches": [],
            "done_when": [], "owner_view": owner_view}


def test_already_done_is_never_a_reason_to_reject(the_map):
    idea = _idea()
    notes = judge.enforce(idea, _raw("REJECT", "NEW", keys=[("FEAT-007", "contradicts")], basis=["FEAT-007"],
                                     why="FEAT-007 already exists."), the_map=the_map, previous=None)
    assert (idea["answers"]["judgment"], idea["answers"]["relationship"]) == ("ADOPT", "ALREADY_SATISFIED")
    assert idea["keys"] == [{"key": "FEAT-007", "how": "already does it"}] and idea["checked_by"] == "rule"
    assert notes and notes[0].startswith("Already done is not a reason to reject")
    nothing = _idea()
    judge.enforce(nothing, _raw("REJECT", "NEW"), the_map=the_map, previous=None)
    assert nothing["answers"]["judgment"] == "INVESTIGATE", "no rule or decision named: not rejected"
    ruled = _idea()
    judge.enforce(ruled, _raw("REJECT", "NEW", keys=[("DEC-063", "contradicts")]), the_map=the_map, previous=None)
    assert ruled["answers"]["judgment"] == "REJECT" and ruled["basis"] == ["DEC-063"]


def test_dec_018_moves_timing_only(the_map):
    idea = _idea()
    judge.enforce(idea, _raw("INVESTIGATE", "EXTENDS_EXISTING", "NOW", keys=[("DEC-018", "contradicts"), ("IDEA-001", "builds on")],
                             basis=["DEC-018"], why="Parked: DEC-018 says finish first."), the_map=the_map, previous=None)
    assert idea["answers"]["judgment"] == "ADOPT"
    assert idea["timing_held_by"] == ["DEC-018"] and idea["answers"]["timing"] == "LATER"
    assert "DEC-018" not in [k["key"] for k in idea["keys"]] and "DEC-018" not in idea["basis"]
    rejected = _idea()
    judge.enforce(rejected, _raw("REJECT", "NEW", keys=[("DEC-018", "contradicts")]), the_map=the_map, previous=None)
    assert rejected["answers"]["judgment"] == "ADOPT" and rejected["timing_held_by"] == ["DEC-018"]
    both = _idea()
    judge.enforce(both, _raw("REJECT", "NEW", keys=[("RULE-5", "contradicts"), ("DEC-018", "contradicts")]), the_map=the_map,
                  previous=None)
    assert both["answers"]["judgment"] == "REJECT" and both["basis"] == ["RULE-5"] and both["timing_held_by"] == ["DEC-018"]


@pytest.mark.parametrize(("documents", "judged"), [(1, "REJECT"), (2, "REJECT"), (3, "CONFLICT"), (4, "CONFLICT")])
def test_a_rule_that_never_bends_makes_conflict_at_three_documents_and_reject_below(the_map, documents, judged):
    idea = _idea("Refunds under five pounds go out automatically without his approval.", docs=documents)
    judge.enforce(idea, _raw("ADOPT", "NEW"), the_map=the_map, previous=None)
    assert idea["answers"]["judgment"] == judged and idea["checked_by"] == "rule"
    assert {"key": "RULE-2", "how": "contradicts"} in idea["keys"] and "RULE-2" in idea["basis"]
    assert idea["reasons"]["judgment"].startswith("Breaks rule 2 (Anything outward waits for a gesture on its card)")


def test_a_needs_you_that_isnt_true_is_dropped(the_map):
    idea = _idea()
    notes = judge.enforce(idea, _raw(importance="USEFUL", needs={"trigger": "opportunity", "question": "Shall we?"}),
                          the_map=the_map, previous=None)
    assert idea["needs_you"] is None and any(n.startswith("Dropped “needs you” (opportunity)") for n in notes)
    for trigger in ("whim", "clash", "uncertainty", "direction", "authority"):
        other = _idea()
        judge.enforce(other, _raw(needs={"trigger": trigger, "question": "?"}), the_map=the_map, previous=None)
        assert other["needs_you"] is None, trigger
    kept = _idea()
    judge.enforce(kept, _raw(importance="FOUNDATIONAL", needs={"trigger": "opportunity", "question": "Shall we?"}),
                  the_map=the_map, previous=None)
    assert kept["needs_you"] == {"trigger": "opportunity", "question": "Shall we?"}
    flipped = _idea()
    judge.enforce(flipped, _raw("REJECT", keys=[("RULE-5", "contradicts")], needs={"trigger": "direction", "question": "?"}),
                  the_map=the_map, previous={"answers": {"judgment": "ADOPT"}})
    assert flipped["needs_you"]["trigger"] == "direction"


def test_a_place_in_the_code_that_isnt_there_is_removed(the_map):
    idea = _idea()
    notes = judge.enforce(idea, _raw(where=["app/actions/engine.py", "crooks-assistant/web/connections.js", "app/nope/never.py",
                                            "FEAT-010", "FEAT-999", "../../etc/passwd"]), the_map=the_map, previous=None)
    assert idea["today"]["where"] == ["app/actions/engine.py", "web/connections.js", "FEAT-010"] and idea["today"]["verified"]
    assert any("app/nope/never.py" in n for n in notes)
    none_left = _idea()
    judge.enforce(none_left, _raw(where=["app/nope/never.py"]), the_map=the_map, previous=None)
    assert none_left["today"]["where"] == [] and none_left["today"]["verified"] is False


def test_every_value_is_in_its_enum(the_map):
    idea = _idea()
    notes = judge.enforce(idea, _raw("MAYBE", "SORT OF", "SOON"), the_map=the_map, previous=None)
    assert (idea["answers"]["judgment"], idea["answers"]["relationship"], idea["answers"]["timing"],
            idea["answers"]["confidence"]) == ("INVESTIGATE", "NEW", "UNSCHEDULED", "low")
    assert len(notes) == 3
    keys = _idea()
    judge.enforce(keys, _raw(keys=[("DEC-9999", "serves"), ("RULE-2", "nonsense"), ("not a key", "serves")]), the_map=the_map,
                  previous=None)
    assert keys["keys"] == [{"key": "RULE-2", "how": "related"}]


async def test_a_foundational_idea_without_a_whole_owner_view_is_asked_again_then_marked_incomplete(place, the_map):
    store, ledger = place
    model = fx.Scripted()
    model.judge["Answers stay on the Max plan"]["owner_view"]["example"] = ""
    model, gen = await _synthesised(store, the_map, model)
    ideas = _active(store, gen)
    plan = ideas["Answers stay on the Max plan"]
    assert plan["owner_view_complete"] is False and plan["owner_view"]["example"] == ""
    asked = [p for p in model.asked("owner_view") if "Answers stay on the Max plan" in p]
    assert len(asked) == 1, "asked once more, then marked"
    said = [e["said"] for e in _events(store, gen) if e.get("idea") == plan["id"]]
    assert any(s.startswith("Its plain-English view is incomplete") for s in said)
    supplier = ideas["Supplier messages in one thread"]
    assert supplier["owner_view_complete"] is True and supplier["owner_view"]["example"].startswith("Your manufacturer")
    synthesis_store(store).set_live(gen)
    payload = await research_ideas.current(store, ledger)
    row = next(r for g in payload["groups"] for r in g["ideas"] if r["id"] == plan["id"])
    assert row["owner_view"]["example"] == "", "shown as it is, never filled in"


async def test_the_pipeline_holds_the_model_to_the_rules(place, the_map):
    store, _ledger = place
    model, gen = await _synthesised(store, the_map)
    ideas = _active(store, gen)
    done = ideas["Done only after reading it back"]
    assert (done["answers"]["judgment"], done["answers"]["relationship"]) == ("ADOPT", "ALREADY_SATISFIED")
    supplier = ideas["Supplier messages in one thread"]
    assert supplier["answers"]["judgment"] == "ADOPT" and supplier["timing_held_by"] == ["DEC-018"]
    refunds = ideas["Send small refunds without a hold"]
    assert refunds["answers"]["judgment"] == "CONFLICT" and len(documents_backing(refunds)) == 3
    keys = ideas["Each key shows when it was checked"]
    assert keys["needs_you"] is None
    assert any(e["type"] == "needs_you_dropped" and e["idea"] == keys["id"] for e in _events(store, gen))
    restart = ideas["Work survives a restart"]
    assert restart["today"]["where"] == ["app/actions/engine.py", "FEAT-010"]
    judged = [e for e in _events(store, gen) if e["type"] == "judged"]
    assert {e["idea"] for e in judged} == {i["id"] for i in ideas.values()}
    assert all(set(e["now"]) == set(AXES) - {"execution"} for e in judged)


# ------------------------------------------------------------------ the old screen, and making a generation live


async def test_old_proposals_become_history_on_the_right_ideas_and_their_records_stay_as_they_were(place, the_map):
    store, ledger = place
    model = fx.Scripted()
    model.old["test-note-beta.md"].append(
        {"title": "Avoid more services", "says": "Do not take on more to look after.", "quote": "it is more to look after than the problem",
         "verdict": "park", "reason": "Too vague.", "cites": ["DEC-017"], "touches": ["app/work"], "same_as": [], "done_when": []})
    await fx.read_old_way(store, model, *FIRST_THREE)
    (alpha,) = [r for r in store.documents() if r["name"] == "test-note-alpha.md"]
    decisions.decide(ledger, section.question(alpha, alpha["proposals"][0]), "park", principal=fx.OWNER_LOGIN, session_id="s1")
    folder = store.root / "documents"
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    gen = await synthesise(store, model=model, the_map=the_map)
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before, "the old records are byte for byte as they were"
    ideas = {i["id"]: i["name"] for i in synthesis_store(store).ideas(gen).values()}
    old = {e["title"]: (ideas[e["idea"]], e["said"]) for e in _events(store, gen) if e["type"] == "old_screen"}
    assert old["Show when each key was last checked"][0] == "Each key shows when it was checked"
    assert re.match(r"\d{1,2} \w{3}, old screen: Adopt, DEC-065 \(", old["Show when each key was last checked"][1])
    assert "; you answered Park on " in old["Show when each key was last checked"][1]
    assert old["Supplier messages in one thread"][0] == "Supplier messages in one thread"
    assert ", old screen: Park, DEC-018 (Finishing current work comes first" in old["Supplier messages in one thread"][1]
    assert old["Stay on the flat plan"][0] == "Answers stay on the Max plan"
    run = synthesis_store(store).run(gen)
    assert [u["title"] for u in run["unlinked"]] == ["Avoid more services"]
    rep = run["report"]
    assert rep["8 DEC-018"]["old_proposals_citing_it"] == 2 and rep["8 DEC-018"]["of_those_called_right"] >= 1
    assert rep["7 how they re-sort"]["held only by DEC-018 though the direction is right"] == 1


async def test_a_synthesis_is_not_live_until_applied_and_applying_takes_in_what_was_read_since(place, the_map):
    store, ledger = place
    model, gen = await _synthesised(store, the_map)
    synth = synthesis_store(store)
    assert synth.live() == ""
    payload = await _get(store, ledger)
    assert payload["mode"] == "proposals" and payload["synthesis"]["state"] == "not_live"
    assert payload["synthesis"]["run"]["stage"] == "done" and payload["synthesis"]["run"]["calls"] > 0
    assert payload["groups"][0]["key"] == "waiting", "the old section, exactly as before"
    await fx.read_old_way(store, model, "test-note-delta.md")
    (delta,) = [r for r in store.documents() if r["name"] == "test-note-delta.md"]
    assert delta["proposals"] == [] and any("waiting for the first synthesis" in n for n in delta["notes"])
    extracted = len([p for p in model.asked("extract") if "test-note-delta.md" in p])
    done = await apply(store, gen, model=model, the_map=the_map)
    assert done["taken_in"] == ["test-note-delta.md"] and synth.live() == gen
    assert len([p for p in model.asked("extract") if "test-note-delta.md" in p]) == extracted == 1, "read once, by its digest"
    assert len(documents_backing(_active(store, gen)["Work survives a restart"])) == 4


async def test_applying_a_new_generation_keeps_ids_by_overlap_and_keeps_the_old_one(place, the_map):
    store, ledger = place
    model, first = await _synthesised(store, the_map)
    await apply(store, first, model=model, the_map=the_map)
    old_ids = {name: i["id"] for name, i in _active(store, first).items()}
    keys = _active(store, first)["Each key shows when it was checked"]
    decisions.decide(ledger, idea_answers.question(keys), "go", principal=fx.OWNER_LOGIN, session_id="s1")
    await fx.read_old_way(store, model, "test-note-delta.md")
    second = await synthesise(store, model=model, the_map=the_map)
    fresh = {name: i["id"] for name, i in _active(store, second).items()}
    assert not set(fresh.values()) & set(old_ids.values()), "a new run never reuses an id by itself"
    await apply(store, second, model=model, the_map=the_map)
    synth = synthesis_store(store)
    assert synth.live() == second and synth.exists(first)
    kept = {name: i["id"] for name, i in _active(store, second).items()}
    assert kept == old_ids, "every idea backed by the same quotes kept its id"
    assert any(e["type"] == "superseded" and e["by"] == second for e in _events(store, first))
    restart = _active(store, second)["Work survives a restart"]
    assert restart["was"] and any(e["type"] == "renumbered" and e["idea"] == restart["id"] for e in _events(store, second))
    payload = await research_ideas.current(store, ledger)
    row = next(r for g in payload["groups"] for r in g["ideas"] if r["id"] == keys["id"])
    assert row["owner_answer"]["key"] == "go", "his answer stayed with the idea"


def test_reuse_needs_half_the_sources():
    def idea(*quotes):
        return {"status": "active", "sources": [{"quote": q} for q in quotes]}

    one, two, three = ("Every job CLIVE starts should carry on", "A restart should never lose work",
                       "Show a last-checked time on every key")
    old = {"idea-0001": idea(one, two), "idea-0002": idea(three)}
    new = {"idea-0010": idea(one + " after the server restarts", "Something else entirely, said here"),
           "idea-0011": idea(three, "A second quote that is new", "A third quote that is new"),
           "idea-0012": idea("Nothing the old ideas said at all")}
    assert reuse(old, new) == {"idea-0010": "idea-0001"}, "half or more, by quote (one containing the other counts)"
    assert reuse(old, {"idea-0013": idea("a", "e")}) == {}, "a scrap of a word is not a quote"


def test_consolidate_never_merges_ideas_he_answered_differently():
    active = [{"id": f"idea-000{n}", "name": "x", "statement": "y", "sources": []} for n in (1, 2, 3)]
    answer = json.dumps({"merges": [{"keep": "idea-0001", "merge": ["idea-0002", "idea-0003", "idea-0001", "idea-0099"], "why": "same"}]})
    assert consolidate.read(answer, active, {"idea-0001": "go", "idea-0002": "no"}) == [
        {"keep": "idea-0001", "merge": ["idea-0003"], "why": "same"}]
    assert consolidate.read(answer, active, {}) == [{"keep": "idea-0001", "merge": ["idea-0002", "idea-0003"], "why": "same"}]


async def test_a_run_that_stops_is_said_and_resumes_where_it_stopped(place, the_map):
    store, _ledger = place
    model = fx.Scripted()
    await fx.read_old_way(store, model, *FIRST_THREE)
    model.fail_at = "judge"
    with pytest.raises(Stopped, match="It stopped while judging: The scripted model was told to fail here. Run it again with --resume"):
        await synthesise(store, model=model, the_map=the_map)
    synth = synthesis_store(store)
    (gen,) = synth.generations()
    run = synth.run(gen)
    assert run["stage"] == "judge" and run["errors"][0]["stage"] == "judge" and run["calls"] > 0
    extracts = len(model.asked("extract"))
    again = await synthesise(store, model=model, the_map=the_map, resume=True)
    assert again == gen and synth.run(gen)["stage"] == "done"
    assert len(model.asked("extract")) == extracts, "nothing read again"
    assert synth.run(gen)["calls"] == len(model.prompts) - 3, "every call counted, the old reviews aside"
    with pytest.raises(Stopped, match="no synthesis run to resume"):
        await synthesise(store, model=model, the_map=the_map, resume=True)


async def test_an_export_is_one_generation_and_never_inside_the_repository(place, the_map):
    import shutil
    import tempfile

    from app.research.synthesis.ask import SynthesisError

    store, _ledger = place
    _model, gen = await _synthesised(store, the_map)
    inside = Path(__file__).resolve().parent / "clive-synthesis-export.tgz"
    with pytest.raises(SynthesisError, match="inside CLIVE's repository"):
        export(store, gen, inside)
    assert not inside.exists()
    outside = Path(tempfile.mkdtemp(prefix="clive-export-test-"))
    if Path(__file__).resolve().parents[2] in outside.resolve().parents:
        pytest.skip("this machine's temporary folder is inside the repository")
    try:
        _export_lands(store, gen, outside)
    finally:
        shutil.rmtree(outside, ignore_errors=True)


def _export_lands(store, gen, outside: Path) -> None:
    written = export(store, gen, outside / "out" / "clive-synthesis-export.tgz")
    assert os.stat(written).st_mode & 0o777 == 0o600
    with tarfile.open(written) as tar:
        names = tar.getnames()
    assert f"{gen}/events.jsonl" in names and f"{gen}/run.json" in names and f"{gen}/summary.json" in names
    assert any(n.startswith(f"{gen}/ideas/idea-") for n in names) and any(n.startswith(f"{gen}/claims/doc-") for n in names)


# ------------------------------------------------------------------ the routes: his answers, the payload


def _client(runtime=None) -> TestClient:
    from app.routes import objectives as objectives_route

    app = FastAPI()
    app.include_router(objectives_route.router)
    settings = SimpleNamespace(writes_local_owner=False, tailscale_verify=False, tailscale_cli="")
    app.state.runtime = runtime or SimpleNamespace(allowed_logins=(fx.OWNER_LOGIN,), settings=settings)
    return TestClient(app)


async def _get(store, ledger) -> dict:
    ideas = await research_ideas.current(store, ledger)
    if ideas is not None:
        return ideas
    return {**await section.current(store, ledger), **research_ideas.not_live(store)}


@pytest.fixture()
def live(place, the_map, monkeypatch):
    store, ledger = place
    world = asyncio.run(fx.build_world(store, ledger, the_map=the_map))
    monkeypatch.setattr(flow, "kick", lambda store: False)

    async def not_filed(_rid):
        return "no"

    monkeypatch.setattr(section, "_filed", not_filed)
    return world


def test_the_route_gives_the_payload_contract(live):
    client = _client()
    assert client.get("/objectives/research").status_code == 403
    assert client.post("/objectives/research/idea/answer", json={}).status_code == 403
    payload = client.get("/objectives/research", headers=OWNER).json()
    check_contract(payload)
    assert payload["summary"] == "10 ideas from 5 documents; 3 wait on you; 1 being read."
    assert [g["key"] for g in payload["groups"]] == ["now", "next", "later", "unscheduled"]
    later = next(g for g in payload["groups"] if g["key"] == "later")["ideas"]
    assert later[0]["answers"]["importance"]["key"] == "HIGH_LEVERAGE" and later[0]["backed_by"]["count"] == 2
    states = {d["name"]: d["synthesis_state"] for d in payload["documents"]}
    assert states == {"test-note-alpha.md": "absorbed", "test-note-beta.md": "absorbed", "test-note-gamma.md": "absorbed",
                      "test-note-delta.md": "absorbed", "test-note-epsilon.md": "absorbed", "test-note-zeta.pdf": "failed",
                      "test-note-eta.md": "reading"}
    brief = client.get("/objectives/research?brief=1", headers=OWNER).json()
    assert brief == {"waiting": 3, "reading": 1, "summary": payload["summary"]}


def test_his_answer_binds_to_what_he_saw_and_the_old_answers_are_superseded(live):
    client = _client()
    payload = client.get("/objectives/research", headers=OWNER).json()
    engine = next(r for r in payload["needs_you"] if r["name"] == "Adopt a workflow engine for it")
    body = {"idea_id": engine["id"], "fingerprint": engine["fingerprint"], "answer": "later", "session_id": "a1b2c3d4"}
    stale = client.post("/objectives/research/idea/answer", headers=OWNER, json={**body, "fingerprint": "0" * 64})
    assert stale.status_code == 409 and stale.json()["code"] == "moved_on" and stale.json()["section"]["mode"] == "ideas"
    assert client.post("/objectives/research/idea/answer", headers=OWNER, json={**body, "answer": "adopt"}).status_code == 400
    gone = client.post("/objectives/research/idea/answer", headers=OWNER, json={**body, "idea_id": "idea-9999"})
    assert gone.status_code == 409 and gone.json()["code"] == "gone"
    done = client.post("/objectives/research/idea/answer", headers=OWNER, json=body).json()
    assert done["recorded"] is True and done["chosen"]["label"] == "Not now" and done["staged"] is None
    assert engine["id"] not in [r["id"] for r in done["section"]["needs_you"]], "answered: off his list"
    row = next(r for g in done["section"]["groups"] for r in g["ideas"] if r["id"] == engine["id"])
    assert row["owner_answer"]["key"] == "later" and row["owner_answer"]["current"] is True
    assert row["history"][-1]["said"] == "You chose Not now."
    judged = live["ledger"].effective()[idea_answers.proposal_id(engine["id"], engine["fingerprint"])]
    assert judged.action_id.startswith("research-idea-decision:research-idea:") and decisions.answer_of(judged).key == "later"
    assert judged.provenance.principal_id == fx.OWNER_LOGIN and judged.decision.value == "DEFERRED"
    merged = next(i for i in synthesis_store(live["store"]).ideas(live["gen"]).values() if i["status"] == "merged")
    said = client.post("/objectives/research/idea/answer", headers=OWNER, json={**body, "idea_id": merged["id"]})
    assert said.status_code == 409 and said.json()["code"] == "merged"
    for path, old in (("/objectives/research/answer", {"proposal_id": "research:x", "fingerprint": "0" * 64, "answer": "park"}),
                      ("/objectives/research/prepare", {"proposal_id": "research:x"})):
        refused = client.post(path, headers=OWNER, json=old)
        assert refused.status_code == 409 and refused.json()["code"] == "superseded"
    not_approved = client.post("/objectives/research/idea/prepare", headers=OWNER, json={"idea_id": engine["id"]})
    assert not_approved.status_code == 409 and not_approved.json()["code"] == "not_approved"


def test_approving_prepares_a_card_in_clives_words_only(live, monkeypatch, the_map):
    prepared = []

    async def fake_prepare(request, record, p, *, session_id, args_for=None):
        prepared.append((p, args_for("inbox-head", the_map)))
        return {"ok": True, "request_id": "research-idea-approved-1", "proposal_id": "prop-1"}

    monkeypatch.setattr(section, "prepare", fake_prepare)
    client = _client()
    payload = client.get("/objectives/research", headers=OWNER).json()
    restart = next(r for r in payload["needs_you"] if r["name"] == "Work survives a restart")
    done = client.post("/objectives/research/idea/answer", headers=OWNER, json={
        "idea_id": restart["id"], "fingerprint": restart["fingerprint"], "answer": "go", "session_id": "a1b2c3d4"}).json()
    assert done["staged"]["ok"] and done["chosen"]["label"] == "Approve the work"
    ((p, args),) = prepared
    assert p == {"touches": ["app/work", "web/jobs.js"]}, "a part only George may change is never a build's to touch"
    assert args["title"] == "Work survives a restart" and args["allowed_paths"] == ["app/work", "web/jobs.js"]
    assert args["acceptance_criteria"] == ["A job running when the server restarts finishes afterwards.",
                                           "Nothing is done twice after a restart."]
    _never_the_research(args, live)
    row = next(r for g in done["section"]["groups"] for r in g["ideas"] if r["id"] == restart["id"])
    assert row["answers"]["execution"]["key"] == "READY" and row["build"]["state"] == "waiting"
    assert row["build"]["request_id"] == "research-idea-approved-1"
    again = client.post("/objectives/research/idea/prepare", headers=OWNER, json={"idea_id": restart["id"], "session_id": "a1b2c3d4"})
    assert again.status_code == 200 and len(prepared) == 2


def _never_the_research(args: dict, world) -> None:
    """The request carries none of the research's own words: no quote, no document name, no section title."""
    text = json.dumps(args)
    for name in os.listdir(fx.NOTES):
        body = (fx.NOTES / name).read_text()
        assert name not in text and name.rsplit(".", 1)[0] not in text
        for heading in re.findall(r"(?m)^## (.+)$", body):
            assert heading not in text
        for sentence in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", body)):
            words = sentence.split()
            for i in range(max(0, len(words) - 8)):
                assert " ".join(words[i:i + 8]) not in text, sentence
    for record in world["store"].documents():
        assert record["name"] not in text


def test_a_line_that_would_carry_the_research_is_left_out(live, the_map):
    idea = dict(next(i for i in synthesis_store(live["store"]).ideas(live["gen"]).values() if i["name"] == "Work survives a restart"))
    idea["statement"] = "Every job CLIVE starts should carry on after the server restarts, says test-note-alpha.md."
    idea["owner_view"] = dict(idea["owner_view"], after="As TEST SECTION: Restarts and jobs puts it, nothing is lost.")
    idea["name"] = "test-note-alpha.md restarts"
    args = research_ideas.filing_args(idea, "head", gen=live["gen"], names=["test-note-alpha.md"], the_map=the_map)
    _never_the_research(args, live)
    assert args["title"] == f"Research idea {idea['id']}"
    assert "left out because it repeated the research's own words" in args["requested_outcome"]
    echo = dict(idea, statement="CLIVE's jobs carry on after the server restarts, instead of being lost at all.")
    text = (fx.NOTES / "test-note-alpha.md").read_text()
    loose = research_ideas.filing_args(echo, "head", gen=live["gen"], names=[], the_map=the_map)
    assert "instead of being lost" in loose["requested_outcome"], "eight words of the note, but not of any quote"
    held = research_ideas.filing_args(echo, "head", gen=live["gen"], names=[], texts=[text], the_map=the_map)
    assert "instead of being lost" not in held["requested_outcome"], "the note's own text holds them back too"


@pytest.mark.usefixtures("owner_asking")
async def test_an_approved_ideas_request_is_filed_only_when_he_holds_its_card(live, monkeypatch, the_map):
    from app.actions import engine as engine_module
    from app.actions.engine import ActionEngine
    from app.actions.ledger import NullLedger
    from app.engineering_bridge.github import EngineeringInbox
    from app.remote_engineering.requests import parse_request
    from app.session.models import Session
    from app.tools import engineering_tools, registry
    from app.tools.dispatch import dispatch
    from tests.test_build_from_clive import HEAD, HOST, REPO, TOKEN, Clock, FakeGitHub

    fake = FakeGitHub()
    monkeypatch.setattr(engineering_tools, "_inbox", EngineeringInbox(REPO, token_source=lambda: TOKEN, transport=fake.transport(), host=HOST))
    monkeypatch.setattr(engineering_tools, "_progress_cache", {})
    clock = Clock()
    engine = ActionEngine(ledger=NullLedger(), clock=clock)
    monkeypatch.setattr(engine_module, "_engine", engine)
    idea = next(i for i in synthesis_store(live["store"]).ideas(live["gen"]).values() if i["name"] == "Work survives a restart")
    records = live["store"].documents()
    names = [r["name"] for r in records]
    texts = research_ideas.source_texts(live["store"], idea, records)
    assert len(texts) == 4 and all("TEST SECTION" in t for t in texts)
    session = Session(session_id="research-idea")
    await dispatch("engineering_status", {"areas": True}, session=session, timeout_s=5)
    args = research_ideas.filing_args(idea, HEAD, gen=live["gen"], names=names, texts=texts, the_map=the_map)
    said = await dispatch("submit_engineering_request", args, session=session, timeout_s=5)
    assert said.startswith("PROPOSED ("), said
    assert fake.puts == [], "approving prepares; nothing is filed before his hold"
    (proposal,) = session.proposals
    content = proposal.execution["content"]
    parse_request(content.encode("utf-8"))
    request = json.loads(content)
    assert request["allowed_paths"][:2] == ["crooks-assistant/app/work", "crooks-assistant/web/jobs.js"]
    assert f"idea {idea['id']}, {live['gen']}" in request["requested_outcome"]
    _never_the_research(request, live)
    armed, code = engine.arm(proposal.proposal_id, session.session_id)
    assert code == ""
    clock.now += 1.0
    result = await engine.commit(proposal.proposal_id, session.session_id, caller="owner", spec_lookup=registry.get, nonce=armed.arm_nonce)
    assert result.code == "verified", result
    assert fake.files[f"requests/{proposal.execution['request_id']}.json"] == content.encode()


async def test_execution_follows_his_answer_and_the_build(monkeypatch):
    owner = {"key": "go", "label": "Approve the work", "at": "", "current": True}
    assert research_ideas.execution(None, None) == "NOT_AUTHORISED"
    assert research_ideas.execution(dict(owner, current=False), None) == "NOT_AUTHORISED"
    assert research_ideas.execution(owner, {"state": "waiting"}) == "READY"
    for progress, state, execution in (("building", "filed", "IN_PROGRESS"), ("done", "done", "IMPLEMENTED"),
                                       ("blocked", "blocked", "BLOCKED"), ("needs the owner", "blocked", "BLOCKED")):
        async def filed(_rid):
            return "yes"

        async def where(_rid, progress=progress):
            return progress

        monkeypatch.setattr(section, "_filed", filed)
        monkeypatch.setattr(research_ideas, "_progress", where)
        build = await research_ideas.build_state({"request_id": "r-1"})
        assert build["state"] == state and research_ideas.execution(owner, build) == execution


# ------------------------------------------------------------------ the model: no tools, research only as data


def test_the_max_plan_model_is_still_asked_with_no_tools_and_no_settings(monkeypatch):
    import claude_agent_sdk

    from app.research.model import MaxPlanModel, ModelError

    seen = {}

    class Client:
        def __init__(self, options):
            seen["options"] = options

        async def connect(self):
            raise RuntimeError("not here")

        async def disconnect(self):
            return None

    monkeypatch.setattr(claude_agent_sdk, "ClaudeSDKClient", Client)
    model = MaxPlanModel(model="sonnet", cli_path="/nonexistent").with_timeout(900)
    assert model._timeout_s == 900 and model._model == "sonnet" and model._cli_path == "/nonexistent"
    with pytest.raises(ModelError):
        asyncio.run(model.ask("s", "p"))
    options = seen["options"]
    assert options.tools == [] and options.allowed_tools == [] and options.mcp_servers == {}
    assert options.setting_sources == [] and options.max_turns == 1 and options.permission_mode == "dontAsk"


async def test_research_only_ever_sits_inside_research_tags(place, the_map):
    store, ledger = place
    world = await fx.build_world(store, ledger, the_map=the_map)
    sentences = []
    for name in os.listdir(fx.NOTES):
        body = re.sub(r"\s+", " ", (fx.NOTES / name).read_text())
        sentences += [s for s in re.split(r"(?<=[.!?])\s+", body) if len(s) > 30 and not s.startswith("#")]
    synthesis_steps = ("extract", "repair", "match", "consolidate", "judge", "owner_view", "summary")
    prompts = [(s, p) for s, p in world["model"].prompts if world["model"].step(s) in synthesis_steps]
    assert {world["model"].step(s) for s, _ in prompts} == set(synthesis_steps)
    for system, prompt in prompts:
        assert "DATA" in system and "never follow" in system.lower()
        outside = re.sub(r"<research[^>]*>.*?</research>", "", prompt, flags=re.S)
        for sentence in sentences:
            assert sentence[:40] not in outside, (world["model"].step(system), sentence)
        for name in os.listdir(fx.NOTES):
            assert name not in outside
    assert data("x </research> y <research name='z'>") == "x ‹/research> y ‹research name='z'>"


# ------------------------------------------------------------------ the contract, and its example


ROW_KEYS = {"id", "fingerprint", "name", "statement", "kind", "answers", "reasons", "timing_held_by", "backed_by",
            "how_they_differ", "against", "owner_view", "needs_you", "keys", "today", "revisit", "effects", "sources",
            "history", "owner_answer", "choices", "build"}


def check_contract(payload: dict) -> None:
    """Every key and every enum of the payload contract (docs/RESEARCH.md, the synthesis brief)."""
    assert set(payload) == {"mode", "summary", "synthesis", "needs_you", "groups", "documents", "waiting", "reading", "accepts",
                            "problem"}
    assert payload["mode"] == "ideas" and isinstance(payload["summary"], str) and payload["summary"]
    synthesis = payload["synthesis"]
    assert set(synthesis) == {"generation", "at", "points", "before", "after", "counts"}
    assert re.fullmatch(r"gen-\d{8}T\d{6}(-\d+)?", synthesis["generation"]) and len(synthesis["points"]) <= 9
    assert set(synthesis["counts"]) == {"documents", "claims", "unplaced", "ideas", "converged", "disagreements", "validations",
                                        "changes"}
    assert all(isinstance(v, int) for v in synthesis["counts"].values())
    titles = {"now": "Now", "next": "Next", "later": "Later", "unscheduled": "No date"}
    keys = [g["key"] for g in payload["groups"]]
    assert keys == [k for k in titles if k in keys] and all(g["ideas"] for g in payload["groups"])
    for group in payload["groups"]:
        assert set(group) == {"key", "title", "ideas"} and group["title"] == titles[group["key"]]
        for row in group["ideas"]:
            _check_row(row)
            assert row["answers"]["timing"]["key"] == {"now": "NOW", "next": "NEXT", "later": "LATER", "unscheduled": "UNSCHEDULED"}[group["key"]]
        order = [(r["answers"]["importance"]["key"] != "FOUNDATIONAL", -r["backed_by"]["count"]) for r in group["ideas"]]
        assert order == sorted(order), "FOUNDATIONAL first, then by support"
    for row in payload["needs_you"]:
        _check_row(row)
        assert row["needs_you"] and not (row["owner_answer"] and row["owner_answer"]["current"])
    assert payload["waiting"] == len(payload["needs_you"]) and isinstance(payload["reading"], int)
    for doc in payload["documents"]:
        assert set(doc) == {"id", "name", "state", "state_words", "why", "received_at", "via", "claims", "unplaced",
                            "synthesis_state", "notes"}
        assert doc["synthesis_state"] in ("absorbed", "waiting", "reading", "failed") and isinstance(doc["claims"], int)
        assert all(set(u) == {"title", "why"} for u in doc["unplaced"])


def _check_row(row: dict) -> None:
    assert set(row) == ROW_KEYS
    assert re.fullmatch(r"idea-\d{4,6}", row["id"]) and re.fullmatch(r"[0-9a-f]{64}", row["fingerprint"])
    assert row["kind"] in KINDS and 0 < len(row["name"].split()) <= 8
    assert set(row["answers"]) == set(AXES)
    for axis, said in row["answers"].items():
        assert set(said) == {"key", "words"} and said["key"] in AXES[axis] and said["words"] == WORDS[axis][said["key"]]
    assert set(row["reasons"]) == {"judgment", "timing"}
    assert all(set(h) == {"key", "label"} for h in row["timing_held_by"])
    backed = row["backed_by"]
    assert set(backed) == {"count", "of", "documents"} and backed["count"] == len(backed["documents"]) <= backed["of"]
    assert all(d["centrality"] in ("central", "supporting", "passing") for d in backed["documents"])
    assert all(set(a) == {"document", "says"} for a in row["against"])
    if row["owner_view"] is not None:
        assert set(row["owner_view"]) == {"means", "today", "after", "example", "before_after", "why_care", "notice"}
        assert all(e in EFFECTS for e in row["owner_view"]["why_care"])
    if row["needs_you"] is not None:
        assert set(row["needs_you"]) == {"trigger", "trigger_words", "question"} and row["needs_you"]["trigger"] in TRIGGERS
        assert row["needs_you"]["trigger_words"] == WORDS["trigger"][row["needs_you"]["trigger"]]
    assert all(set(k) == {"key", "label", "how"} for k in row["keys"])
    assert set(row["today"]) == {"level", "says", "where", "verified"} and row["today"]["level"] in ("none", "partial", "substantial", "complete")
    assert all(e in EFFECTS for e in row["effects"])
    assert all(set(s) == {"document", "section", "quote", "stance", "centrality"} and s["stance"] in ("supports", "opposes", "refines")
               for s in row["sources"])
    assert all(set(h) == {"at", "said"} for h in row["history"]) and row["history"] == sorted(row["history"], key=lambda h: h["at"])
    if row["owner_answer"] is not None:
        assert set(row["owner_answer"]) == {"key", "label", "at", "current"} and row["owner_answer"]["key"] in ("go", "later", "no")
    assert [(c["key"], c["label"], c["then"]) for c in row["choices"]] == list(CHOICES)
    if row["build"] is not None:
        assert set(row["build"]) == {"state", "words", "request_id"}


def test_the_contract_example_is_the_real_codes_output_and_invented(tmp_path):
    example = json.loads(fx.EXAMPLE.read_text())
    check_contract(example)
    with fx.isolated(tmp_path) as (store, ledger):
        made = asyncio.run(fx.payload(store, ledger))
    fx._open_up(tmp_path)
    check_contract(made)

    def shape(value):
        if isinstance(value, dict):
            return {k: shape(v) for k, v in value.items()}
        if isinstance(value, list):
            return [shape(v) for v in value]
        return type(value).__name__

    for payload in (example, made):     # documents given in the same second come in either order
        payload["documents"].sort(key=lambda d: d["name"])
    assert shape(example) == shape(made), "regenerate it: python -m tests.research_synthesis_fixture"
    rows = [r for g in example["groups"] for r in g["ideas"]]
    assert {r["name"] for r in rows} == {r["name"] for g in made["groups"] for r in g["ideas"]}
    assert {r["answers"]["judgment"]["key"] for r in rows} == {"ADOPT", "ADOPT_PARTLY", "INVESTIGATE", "CONFLICT"}
    assert any(r["owner_answer"] and not r["owner_answer"]["current"] for r in rows), "an answer to an earlier view"
    assert any(r["build"] for r in rows) and any(r["timing_held_by"] for r in rows) and any(r["against"] for r in rows)
    assert all(d["name"].startswith("test-note-") for d in example["documents"])
    text = json.dumps(example, ensure_ascii=False)
    assert "TEST RESEARCH NOTE — invented for CLIVE's tests" in text and "@" not in text
