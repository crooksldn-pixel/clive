"""Research synthesis after the first full run on the server (DEC-078, status of 16 Oct 2026).

That run read six documents into 403 ideas where about 40 were expected, then stopped judging at idea 51
on one answer that wasn't readable JSON. Proved here, with the model scripted (tests/research_synthesis_
fixture.py) on notes invented for CLIVE's tests, never George's research:

- an unreadable answer is asked once more, at every step, counted as a call and as one asked again; two
  stop the run as before, and --resume carries on;
- at most 4 calls make one answer (a failed call and an unreadable answer each asked once more), and
  extraction is not asked a third time;
- ideas join in rounds until one joins nothing, at most ROUNDS; more than GROUP ideas are asked about
  by kind, then all by name only; the code's checks hold across calls and rounds; a kept idea may be
  renamed within the lengths, and one George answered never is;
- reading during a run, and a new document into the live ideas, make one round;
- more than `most_ideas` ideas stop the run before anything is judged, said in words, and --resume
  joins them again;
- a second full run over the same documents makes no extract or repair call, and extract.VERSION is
  what the server's cache holds;
- run.json's shape is right, and holds counts only;
- a claim that details an idea joins it as `refines`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.research import flow
from app.research.model import ModelError
from app.research.rules import read_map
from app.research.synthesis import consolidate, extract, match, shape
from app.research.synthesis import run as run_module
from app.research.synthesis.ask import REASK, Calls, Unreadable
from app.research.synthesis.consolidate import CONSOLIDATE_SYSTEM
from app.research.synthesis.ideas import documents_backing, new_idea
from app.research.synthesis.run import Stopped, Work, report_lines, status_lines, synthesise
from app.research.synthesis.store import SynthesisStore, synthesis_store
from tests import research_synthesis_fixture as fx

FIRST_THREE = ("test-note-alpha.md", "test-note-beta.md", "test-note-gamma.md")
BAD = '{"cut off": [1, 2}'                    # what an answer cut off part-way looks like
WHAT = {"extract": "list of recommendations", "repair": "list of exact passages", "match": "placing of claims",
        "consolidate": "list of merges", "judge": "judgment of ideas", "owner_view": "owner view", "summary": "summary"}


@pytest.fixture(scope="module")
def the_map():
    return read_map()


@pytest.fixture()
def place(tmp_path):
    with fx.isolated(tmp_path) as (store, ledger):
        yield store, ledger
    fx._open_up(tmp_path)


def _script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("research_script", Path(__file__).resolve().parent.parent / "scripts" / "research.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


class Garbles(fx.Scripted):
    """The scripted model, answering the next `garble[step]` calls of a step with JSON cut off part-way."""

    def __init__(self, **garble: int) -> None:
        super().__init__()
        self.garble = dict(garble)

    async def ask(self, system, prompt):
        step = self.step(system)
        if self.garble.get(step):
            self.garble[step] -= 1
            self.prompts.append((system, prompt))
            return BAD
        return await super().ask(system, prompt)


# ------------------------------------------------------------------ 1. an unreadable answer is asked again, once


@pytest.mark.parametrize("step", list(WHAT))
async def test_an_unreadable_answer_is_asked_once_more_and_the_run_carries_on(place, the_map, step):
    store, _ledger = place
    model = Garbles(**{step: 1})
    await fx.read_old_way(store, model, *FIRST_THREE)
    gen = await synthesise(store, model=model, the_map=the_map)
    synth = synthesis_store(store)
    run = synth.run(gen)
    assert run["stage"] == "done" and run["failed"] == {} and run["retries"] == 1
    asked = model.asked(step)
    garbled = asked[0]
    assert asked[1] == f"{garbled}\n\n{REASK}", "the same prompt, plus one line"
    assert REASK == "Your last answer wasn't readable JSON. Answer with the JSON object only."
    assert run["calls_by_stage"][step] == len(asked), "the second ask is a call of its stage"
    assert run["calls"] == len(model.prompts) - 3, "every call counted, the old reviews aside"
    assert status_lines(synth, gen)[2].endswith("; 1 asked again.")


@pytest.mark.parametrize(("step", "while_"), [("match", "reading documents"), ("consolidate", "reading documents"),
                                              ("judge", "judging")])
async def test_two_unreadable_answers_stop_the_run_as_before_and_it_resumes(place, the_map, step, while_):
    store, _ledger = place
    model = Garbles(**{step: 2})
    await fx.read_old_way(store, model, *FIRST_THREE)
    said = f"It stopped while {while_}: Claude's answer ({WHAT[step]}) wasn't readable JSON. Run it again with --resume."
    with pytest.raises(Stopped) as stopped:
        await synthesise(store, model=model, the_map=the_map)
    assert str(stopped.value) == said
    synth = synthesis_store(store)
    (gen,) = synth.generations()
    run = synth.run(gen)
    assert run["retries"] == 1 and run["errors"][-1]["said"] == f"Claude's answer ({WHAT[step]}) wasn't readable JSON."
    assert await synthesise(store, model=model, the_map=the_map, resume=True) == gen
    assert synth.run(gen)["stage"] == "done"


async def test_one_answer_takes_at_most_four_calls():
    """A failed call is asked once more (Calls.ask) and an unreadable answer is asked once more
    (Calls.ask_json): the most one answer can take is four calls, then it is said."""
    class Worst:
        name, retry_pause_s = "worst", 0.0

        def __init__(self):
            self.made = 0

        async def ask(self, system, prompt):
            self.made += 1
            if self.made % 2:
                raise ModelError("TEST: invented failure")
            return "TEST: prose, not JSON"

    model = Worst()
    calls = Calls(model)
    with pytest.raises(Unreadable, match=r"^Claude's answer wasn't the summary CLIVE asked for\.$"):
        await calls.ask_json("summary", "TEST system", "TEST prompt", "summary")
    assert model.made == calls.made == 4 and calls.by_stage == {"summary": 4} and calls.retries == 3


async def test_extraction_is_never_asked_a_third_time_and_a_readable_answer_without_a_list_is_read_once_more(place, the_map):
    """Unreadable twice: left out after two calls (ask_json asked again; extract_twice doesn't). Readable but
    with no list of recommendations: the whole document is read once more."""
    class NoList(fx.Scripted):
        async def ask(self, system, prompt):
            if self.step(system) == "extract" and "test-note-gamma.md" in prompt:
                self.prompts.append((system, prompt))
                return json.dumps({"thesis": "TEST: an invented answer with no list"})
            if self.step(system) == "extract" and "test-note-beta.md" in prompt:
                self.prompts.append((system, prompt))
                return BAD
            return await super().ask(system, prompt)

    store, _ledger = place
    model = NoList()
    await fx.read_old_way(store, model, *FIRST_THREE)
    gen = await synthesise(store, model=model, the_map=the_map)
    failed = {f["name"]: f["why"] for f in synthesis_store(store).run(gen)["failed"].values()}
    assert set(failed) == {"test-note-beta.md", "test-note-gamma.md"}
    assert "wasn't readable JSON" in failed["test-note-beta.md"] and "had no list" in failed["test-note-gamma.md"]
    assert len([p for p in model.asked("extract") if "test-note-beta.md" in p]) == 2, "asked once more, never a third time"
    assert len([p for p in model.asked("extract") if "test-note-gamma.md" in p]) == 2, "the document read once more"


# ------------------------------------------------------------------ 2. joining ideas, in rounds


class Rounds:
    """A model for consolidate only: each call is answered by the next of `answers` (a dict, or a function of
    the prompt), then by "no merges"; every prompt is kept."""

    name, retry_pause_s = "rounds", 0.0

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts: list[str] = []

    async def ask(self, system, prompt):
        assert system == CONSOLIDATE_SYSTEM
        self.prompts.append(prompt)
        answer = self.answers.pop(0) if self.answers else {"merges": []}
        return json.dumps(answer(prompt) if callable(answer) else answer)


def _work(root: Path, model, ideas: list[tuple[str, str]], *, answered: dict[str, str] | None = None) -> Work:
    """A generation holding invented ideas, one invented source each."""
    synth = SynthesisStore(root / "synthesis")
    gen = synth.new_generation()
    work = Work(synth, gen, Calls(model), None, answered=answered)
    for n, (name, kind) in enumerate(ideas, 1):
        idea = new_idea(synth.next_idea_id(gen), name=name, statement=f"TEST: {name}, invented for CLIVE's tests.", kind=kind,
                        at="2026-10-16T00:00:00+00:00")
        doc = f"doc-{n:020x}"
        idea["sources"] = [{"doc_id": doc, "claim_id": f"{doc}:1", "document": "test-note.md", "section": "", "quote": f"TEST {n}",
                            "says": name, "title": name, "stance": "supports", "centrality": "central"}]
        work.save(idea)
    return work


def _shown(prompt: str) -> list[str]:
    return re.findall(r"(?m)^(idea-\d{4,6}):", prompt)


def _pair(prompt: str) -> dict:
    ids = _shown(prompt)
    return {"merges": [{"keep": ids[0], "merge": [ids[1]], "why": "TEST: the same"}]} if len(ids) > 1 else {"merges": []}


def test_the_starting_sizes():
    assert consolidate.GROUP == 60 and consolidate.ROUNDS == 4 and run_module.MOST_IDEAS == 90


async def test_rounds_repeat_until_one_joins_nothing(tmp_path):
    model = Rounds({"merges": [{"keep": "idea-0001", "merge": ["idea-0002"], "why": "TEST: one"}]},
                   {"merges": [{"keep": "idea-0003", "merge": ["idea-0004"], "why": "TEST: two"}]})
    work = _work(tmp_path, model, [(f"TEST idea {n}", "capability") for n in range(1, 6)])
    touched = await run_module.consolidate(work, rounds=consolidate.ROUNDS)
    assert len(model.prompts) == 3, "two rounds that join, then one that joins nothing, and no more"
    assert touched == {"idea-0001", "idea-0003"}
    assert {i["id"] for i in work.active()} == {"idea-0001", "idea-0003", "idea-0005"}
    assert "idea-0002:" not in model.prompts[1] and "idea-0004:" not in model.prompts[2], "a merged idea is never offered again"
    assert work.calls.by_stage == {"consolidate": 3}


async def test_rounds_stop_at_rounds(tmp_path):
    model = Rounds(*[_pair] * 10)
    work = _work(tmp_path, model, [(f"TEST idea {n}", "capability") for n in range(1, 11)])
    await run_module.consolidate(work, rounds=consolidate.ROUNDS)
    assert len(model.prompts) == consolidate.ROUNDS == 4 and len(work.active()) == 6
    model = Rounds(*[_pair] * 10)
    work = _work(tmp_path / "once", model, [(f"TEST idea {n}", "capability") for n in range(1, 11)])
    await run_module.consolidate(work)
    assert len(model.prompts) == 1, "one round unless asked for more"


async def test_more_than_group_ideas_are_asked_about_by_kind_then_all_by_name_only(tmp_path, monkeypatch):
    monkeypatch.setattr(consolidate, "GROUP", 3)
    kinds = ["capability", "process", "capability", "safety", "capability", "process", "capability"]
    model = Rounds()
    work = _work(tmp_path, model, [(f"TEST {kind} idea {n}", kind) for n, kind in enumerate(kinds, 1)])
    assert consolidate.calls_of(work.active()) == [
        (["idea-0001", "idea-0003", "idea-0005"], False),       # capability, the first chunk of GROUP in id order
        (["idea-0002", "idea-0006"], False),                    # process (the capability left over, and safety, are one each)
        ([f"idea-000{n}" for n in range(1, 8)], True)]          # every idea, by name only
    await run_module.consolidate(work, rounds=consolidate.ROUNDS)
    first, second, every = model.prompts
    assert len(model.prompts) == 3, "one round: it joined nothing"
    assert _shown(first) == ["idea-0001", "idea-0003", "idea-0005"] and " — TEST: " in first
    assert _shown(second) == ["idea-0002", "idea-0006"]
    assert _shown(every) == [f"idea-000{n}" for n in range(1, 8)] and " — " not in every.split("</research>")[0]
    assert "idea-0007: TEST capability idea 7\n" in every


async def test_the_checks_hold_across_calls_and_rounds(tmp_path, monkeypatch):
    monkeypatch.setattr(consolidate, "GROUP", 3)
    kinds = ["capability", "capability", "capability", "process", "process"]
    model = Rounds(
        # round 1, capability: idea-0002 is proposed twice in one call, and merged once
        {"merges": [{"keep": "idea-0001", "merge": ["idea-0002"], "why": "TEST"},
                    {"keep": "idea-0003", "merge": ["idea-0002"], "why": "TEST"}]},
        # round 1, process: an idea into itself, and one that does not exist
        {"merges": [{"keep": "idea-0004", "merge": ["idea-0004", "idea-0099"], "why": "TEST"}]},
        # round 1, every idea by name: idea-0002, merged earlier in the round, is not there to merge
        {"merges": [{"keep": "idea-0004", "merge": ["idea-0002", "idea-0005"], "why": "TEST"}]},
        # round 2: idea-0002 (merged in round 1) is not there to keep; idea-0003 is still there to merge
        {"merges": [{"keep": "idea-0002", "merge": ["idea-0004"], "why": "TEST"},
                    {"keep": "idea-0001", "merge": ["idea-0003"], "why": "TEST"}]})
    work = _work(tmp_path, model, [(f"TEST idea {n}", kind) for n, kind in enumerate(kinds, 1)])
    await run_module.consolidate(work, rounds=consolidate.ROUNDS)
    ideas = work.ideas
    assert {i["id"] for i in work.active()} == {"idea-0001", "idea-0004"}
    assert [ideas[i]["merged_into"] for i in ("idea-0002", "idea-0003", "idea-0005")] == ["idea-0001", "idea-0001", "idea-0004"]
    assert [_shown(p) for p in model.prompts] == [
        ["idea-0001", "idea-0002", "idea-0003"], ["idea-0004", "idea-0005"], ["idea-0001", "idea-0003", "idea-0004", "idea-0005"],
        ["idea-0001", "idea-0003", "idea-0004"], ["idea-0001", "idea-0004"]], "a merged idea is never offered again"
    merged = [e for e in work.synth.events(work.gen) if e["type"] == "merged" and e.get("into")]
    assert sorted(e["idea"] for e in merged) == ["idea-0002", "idea-0003", "idea-0005"], "each merged once"
    assert all((work.synth.gen_dir(work.gen) / "ideas" / f"{i}.json").exists() for i in ideas), "merged ideas stay on disk"
    assert sorted(s["claim_id"] for s in ideas["idea-0001"]["sources"]) == [f"doc-{n:020x}:1" for n in (1, 2, 3)], "nothing split"
    assert ideas["idea-0003"]["sources"] == [ideas["idea-0001"]["sources"][2]], "the merged idea keeps its own evidence"


def _named(name: str, statement: str, **more) -> dict:
    return {"merges": [{"keep": "idea-0001", "merge": ["idea-0002"], "why": "TEST", "name": name, "statement": statement, **more}]}


@pytest.mark.parametrize(("name", "statement", "renamed"), [
    ("TEST broader idea in eight plain words here", "TEST: one sentence. TEST: two sentences.", True),
    ("TEST broader idea in nine plain words here now", "TEST: one sentence.", False),
    ("", "TEST: one sentence.", False),
    ("TEST broader idea", "", False),
    ("TEST broader idea", "TEST: one. TEST: two. TEST: three.", False),
    ("TEST broader idea", "T" * 301, False),
    ("TEST broader idea", "T" * 299 + ".", True),
])
def test_a_rename_is_kept_only_within_its_lengths(name, statement, renamed):
    active = [{"id": f"idea-000{n}", "name": "x", "statement": "y", "sources": []} for n in (1, 2)]
    (merge,) = consolidate.read(_named(name, statement), active, {})
    assert ("rename" in merge) is renamed
    if renamed:
        assert merge["rename"] == {"name": name, "statement": statement}
    (only_name,) = consolidate.read({"merges": [{"keep": "idea-0001", "merge": ["idea-0002"], "why": "TEST", "name": name}]},
                                    active, {})
    assert "rename" not in only_name, "both or neither"


def test_an_idea_he_answered_is_never_renamed():
    active = [{"id": f"idea-000{n}", "name": "x", "statement": "y", "sources": []} for n in (1, 2)]
    answer = _named("TEST broader idea", "TEST: one sentence.")
    assert "rename" not in consolidate.read(answer, active, {"idea-0001": "go"})[0]
    (kept,) = consolidate.read(answer, active, {"idea-0002": "later"})
    assert kept["keep"] == "idea-0002" and "rename" not in kept, "the one he answered is kept, in its own words"


async def test_a_kept_idea_is_renamed_said_in_plain_words_and_never_when_he_answered_it(tmp_path):
    answer = _named("TEST work survives anything", "TEST: CLIVE's jobs survive anything, invented for CLIVE's tests.")
    model = Rounds(answer)
    work = _work(tmp_path, model, [("TEST work survives a restart", "foundational"), ("TEST save each step", "foundational")])
    await run_module.consolidate(work)
    kept = work.ideas["idea-0001"]
    assert (kept["name"], kept["statement"]) == ("TEST work survives anything", "TEST: CLIVE's jobs survive anything, invented for CLIVE's tests.")
    (renamed,) = [e for e in work.synth.events(work.gen) if e["type"] == "renamed"]
    assert renamed["said"] == "Renamed when ideas joined it: TEST work survives a restart → TEST work survives anything"
    assert renamed["idea"] == "idea-0001" and renamed["was_name"] == "TEST work survives a restart"
    model = Rounds(answer)
    work = _work(tmp_path / "answered", model, [("TEST work survives a restart", "foundational"), ("TEST save each step", "foundational")],
                 answered={"idea-0001": "go"})
    await run_module.consolidate(work)
    assert work.ideas["idea-0001"]["name"] == "TEST work survives a restart" and work.ideas["idea-0002"]["status"] == "merged"
    assert not [e for e in work.synth.events(work.gen) if e["type"] == "renamed"]


async def test_the_names_only_call_never_renames(tmp_path, monkeypatch):
    """[review 2] The call that shows ideas by name only never saw their statements: its shape asks for no
    name or statement, and a rename it gives anyway changes nothing but the merge."""
    monkeypatch.setattr(consolidate, "GROUP", 2)
    model = Rounds(_named("TEST a name from names alone", "TEST: a statement written from names alone."))
    work = _work(tmp_path, model, [("TEST jobs survive a restart", "foundational"), ("TEST save each step", "process"),
                                   ("TEST a third idea", "safety")])
    assert consolidate.calls_of(work.active()) == [(["idea-0001", "idea-0002", "idea-0003"], True)], "one kind each: by name only"
    await run_module.consolidate(work)
    kept = work.ideas["idea-0001"]
    assert work.ideas["idea-0002"]["merged_into"] == "idea-0001", "the merge stands"
    assert (kept["name"], kept["statement"]) == ("TEST jobs survive a restart", "TEST: TEST jobs survive a restart, invented for CLIVE's tests.")
    assert not [e for e in work.synth.events(work.gen) if e["type"] == "renamed"]
    (prompt,) = model.prompts
    asked = prompt.split("</research>", 1)[1]
    assert "leave name and statement out" in asked and '"name"' not in asked and '"statement"' not in asked
    full = consolidate.prompt_for(work.active()).split("</research>", 1)[1]
    assert '"name": "only when renamed", "statement": "only when renamed"' in full, "a call that shows statements may rename"


async def test_reading_makes_one_round_a_document_and_the_stage_stops_when_a_round_joins_nothing(place, the_map):
    store, _ledger = place
    model = fx.Scripted()
    await fx.read_old_way(store, model, *FIRST_THREE)
    gen = await synthesise(store, model=model, the_map=the_map)
    # one round after each of three documents (gamma's joins an idea, and is still one call), one at the stage
    assert synthesis_store(store).run(gen)["calls_by_stage"]["consolidate"] == 4


async def test_a_new_document_into_the_live_ideas_makes_one_round(place, the_map):
    store, ledger = place
    world = await fx.build_world(store, ledger, the_map=the_map)
    model, gen = world["model"], world["gen"]
    await flow.run_pending(store, model=model, the_map=the_map)      # the note still waiting to be read
    model.claims["test-note-lambda.md"] = [fx.claim("Check keys on a schedule", "Keys are checked on a schedule.",
                                                    "every key should be checked on a schedule", "TEST SECTION: Keys",
                                                    "Keys checked on a schedule")]
    model.ideas["Keys checked on a schedule"] = ("CLIVE checks every key on a schedule.", "capability")
    model.merges["Keys checked on a schedule"] = ("Each key shows when it was checked", "TEST: a step towards it.")
    before = len(model.asked("consolidate"))
    flow.receive(store, "test-note-lambda.md", b"# TEST RESEARCH NOTE - invented for CLIVE's tests (lambda)\n\n"
                 b"## TEST SECTION: Keys\n\nEvery key should be checked on a schedule.\n", via="screen")
    (lam,) = await flow.run_pending(store, model=model, the_map=the_map)
    assert lam["state"] == "done", lam["why"]
    assert len(model.asked("consolidate")) == before + 1, "one round, though it joined an idea"
    names = {i["name"]: i for i in synthesis_store(store).ideas(gen).values()}
    assert names["Keys checked on a schedule"]["merged_into"] == names["Each key shows when it was checked"]["id"]


# ------------------------------------------------------------------ 3. too many ideas stops the run before judging


async def test_too_many_ideas_stop_the_run_before_judging_and_resume_joins_them_again(place, the_map, capsys):
    from app.research import model as model_module

    store, _ledger = place
    script = _script()
    model = fx.Scripted()
    await fx.read_old_way(store, model, *FIRST_THREE)
    base = dict(files=[], list=False, try_file=None, synthesise=True, resume=False, export_synthesis=None, generation="",
                apply=None, ideas=False, call_timeout=None, status=False)
    replaced = model_module.install(model)
    try:
        assert await script._main(script.argparse.Namespace(**base, most_ideas=9)) == 1
        said = ("It stopped after joining ideas: 10 ideas is more than 9, too many to judge well (the aim is 25–60). "
                "Nothing was judged. Tell the Director; --resume tries joining them again.")
        out = capsys.readouterr()
        assert f"research: {said}" in out.err
        assert "Ideas: 10 active, 1 merged" in out.out, "the shape says where they came from"
        assert model.asked("judge") == [] and model.asked("owner_view") == [] and model.asked("summary") == []
        synth = synthesis_store(store)
        (gen,) = synth.generations()
        run = synth.run(gen)
        assert run["stage"] == "consolidate" and run["errors"][-1] == {"at": run["errors"][-1]["at"], "stage": "consolidate", "said": said}
        assert "judge" not in run["calls_by_stage"] and not [e for e in synth.events(gen) if e["type"] in ("old_screen", "judged")]
        lines = status_lines(synth, gen)
        assert lines[0] == f"Synthesis {gen}: joining ideas that are the same (not live; none is live yet)."
        assert lines[1] == ("Held before judging: 10 ideas is more than 9, too many to judge well (the aim is 25–60). "
                            "Nothing was judged; --resume tries joining them again.")
        joined, extracted = len(model.asked("consolidate")), len(model.asked("extract"))
        assert await script._main(script.argparse.Namespace(**dict(base, resume=True), most_ideas=9)) == 1
        capsys.readouterr()
        assert len(model.asked("consolidate")) == joined + 1 and len(model.asked("extract")) == extracted, "joined again, nothing read again"
        assert model.asked("judge") == []
        assert await script._main(script.argparse.Namespace(**dict(base, resume=True), most_ideas=10)) == 0
        assert "2. Distinct ideas: 10" in capsys.readouterr().out, "at the ceiling, not above it: it completes"
        run = synth.run(gen)
        assert run["stage"] == "done" and "too_many" not in run and model.asked("judge")
        assert not any(line.startswith("Held before judging") for line in status_lines(synth, gen))
    finally:
        model_module.install(replaced)
    with pytest.raises(SystemExit):
        script.main(["--most-ideas", "5"])


async def test_resuming_a_run_that_stopped_while_judging_is_held_by_the_ceiling_too(place, the_map):
    """[review 1] The server's first run stopped while judging, with 403 ideas. Resumed with too many active
    ideas, a run judges nothing: it is held, said, and set back to joining them. The ceiling is kept in
    run.json from the run's start, and --resume holds to it unless it is given again."""
    store, _ledger = place
    model = fx.Scripted()
    model.judge["Keys show a last-checked time"] = model.judge["Each key shows when it was checked"]
    await fx.read_old_way(store, model, "test-note-gamma.md", "test-note-epsilon.md")
    model.fail_at = "judge"
    with pytest.raises(Stopped, match="^It stopped while judging: "):
        await synthesise(store, model=model, the_map=the_map)
    synth = synthesis_store(store)
    (gen,) = synth.generations()
    run = synth.run(gen)
    assert run["stage"] == "judge" and run["most_ideas"] == 90 and run["shape"]["ideas"]["active"] == 5
    asked = {step: len(model.asked(step)) for step in ("judge", "owner_view", "summary")}
    with pytest.raises(Stopped) as held:
        await synthesise(store, model=model, the_map=the_map, resume=True, most_ideas=3)
    assert str(held.value) == ("It stopped after joining ideas: 5 ideas is more than 3, too many to judge well (the aim is "
                               "25–60). Nothing was judged. Tell the Director; --resume tries joining them again.")
    assert {step: len(model.asked(step)) for step in asked} == asked, "no judge, owner view or summary call"
    run = synth.run(gen)
    assert run["stage"] == "consolidate" and run["too_many"] == {"ideas": 5, "most": 3} and run["most_ideas"] == 3
    assert run["errors"][-1]["stage"] == "judge" and run["errors"][-1]["said"] == str(held.value)
    assert status_lines(synth, gen)[1].startswith("Held before judging: 5 ideas is more than 3")
    with pytest.raises(Stopped, match="^It stopped after joining ideas: 5 ideas is more than 3,"):
        await synthesise(store, model=model, the_map=the_map, resume=True)
    assert {step: len(model.asked(step)) for step in asked} == asked, "--resume holds to the ceiling it was given"
    assert await synthesise(store, model=model, the_map=the_map, resume=True, most_ideas=5) == gen
    run = synth.run(gen)
    assert run["stage"] == "done" and run["most_ideas"] == 5 and "too_many" not in run
    assert len(model.asked("judge")) > asked["judge"]


def test_a_run_too_big_that_has_judged_some_says_so():
    assert run_module.too_many(403, 90, 51) == (
        "It stopped after joining ideas: 403 ideas is more than 90, too many to judge well (the aim is 25–60). "
        "Nothing more was judged (51 already were). Tell the Director; --resume tries joining them again.")


# ------------------------------------------------------------------ the cache: the re-run reads nothing again


def test_extract_version_is_the_one_the_servers_cache_holds():
    """The six documents on the server are cached under this key (production dc59047e). Changing the
    extraction prompts or EXTRACT_CHARS changes it, and the next run reads every document again."""
    assert extract.VERSION == "0447652169d538c7"


async def test_a_second_full_run_over_the_same_documents_makes_no_extract_or_repair_call(place, the_map):
    store, _ledger = place
    model = fx.Scripted()
    await fx.read_old_way(store, model, *FIRST_THREE)
    first = await synthesise(store, model=model, the_map=the_map)
    asked = {step: len(model.asked(step)) for step in ("extract", "repair")}
    assert asked["extract"] and asked["repair"]
    second = await synthesise(store, model=model, the_map=the_map)
    synth = synthesis_store(store)
    assert second != first and synth.run(second)["stage"] == "done"
    by = synth.run(second)["calls_by_stage"]
    assert "extract" not in by and "repair" not in by
    assert {step: len(model.asked(step)) for step in ("extract", "repair")} == asked
    assert by["match"] == synth.run(first)["calls_by_stage"]["match"]


# ------------------------------------------------------------------ 4. the shape of a run


async def test_the_shape_of_a_run_is_counted_right_and_is_counts_only(place, the_map, capsys):
    import shutil
    import tempfile

    store, _ledger = place
    model = fx.Scripted()
    await fx.read_old_way(store, model, *FIRST_THREE)
    gen = await synthesise(store, model=model, the_map=the_map)
    synth = synthesis_store(store)
    run = synth.run(gen)
    docs = [d["doc_id"] for d in run["shape"]["started"]]
    assert [synth.claims(gen)[d]["document"] for d in docs] == list(FIRST_THREE), "in the order read"
    assert run["shape"] == {
        "claims": {"total": 17, "placed": 16, "unplaced": 1,
                   "by_centrality": {"central": 7, "supporting": 5, "passing": 4},
                   "by_kind": {"build": 11, "principle": 4, "avoid": 0, "measure": 0, "sequence": 0, "process": 1}},
        "ideas": {"active": 10, "merged": 1,
                  "by_kind": {"foundational": 3, "capability": 3, "safety": 2, "tooling-choice": 1, "process": 1, "meta": 0},
                  "by_documents": {"0": 0, "1": 7, "2": 1, "3+": 2}, "by_claims": {"1": 7, "2-3": 3, "4+": 0},
                  "only_passing": 3},
        "started": [{"doc_id": d, "ideas": n} for d, n in zip(docs, (7, 2, 2), strict=True)],
    }
    assert run["report"]["shape"] == run["shape"]

    def leaves(value, path=()):
        if isinstance(value, dict):
            for key, inner in value.items():
                assert key in shape_words, (path, key)
                yield from leaves(inner, (*path, key))
        elif isinstance(value, list):
            for n, inner in enumerate(value):
                yield from leaves(inner, (*path, n))
        else:
            yield path, value

    shape_words = {"claims", "ideas", "started", "total", "placed", "unplaced", "by_centrality", "by_kind", "active", "merged",
                   "by_documents", "by_claims", "only_passing", "0", "1", "2", "3+", "2-3", "4+", "central", "supporting",
                   "passing", "build", "principle", "avoid", "measure", "sequence", "process", "foundational", "capability",
                   "safety", "tooling-choice", "meta", "doc_id"}
    for path, value in leaves(run["shape"]):
        if path[-1] == "doc_id":
            assert re.fullmatch(r"doc-[0-9a-f]{20}", value), "a document's id, never its name"
        else:
            assert isinstance(value, int) and not isinstance(value, bool), (path, "counts only")
    text = json.dumps(run["shape"])
    for idea in synth.ideas(gen).values():
        assert idea["name"] not in text
    for name in FIRST_THREE:
        assert name not in text and fx.note(name).decode()[60:100] not in text
    lines = shape.lines(run["shape"])
    assert lines == [
        "Shape: 17 recommendations, 16 placed in ideas, 1 couldn't be placed; by how central: central 7, supporting 5, "
        "passing 4; by kind: build 11, principle 4, process 1.",
        "Ideas: 10 active, 1 merged; by kind: foundational 3, capability 3, safety 2, tooling-choice 1, process 1; backed by "
        "one document 7, two 1, three or more 2; with one recommendation 7, two or three 3, four or more 0; 3 only from "
        "passing mentions.",
        "Ideas started in each document, in the order read: 7, 2, 2."]
    assert report_lines(run["report"])[-3:] == lines
    status = status_lines(synth, gen)
    assert status[-4:-1] == lines and status[-1].endswith("on this server now.")
    outside = Path(tempfile.mkdtemp(prefix="clive-export-test-"))
    try:
        assert _script()._export(store, str(outside / "x.tgz"), gen) == 0
    finally:
        shutil.rmtree(outside, ignore_errors=True)
    assert capsys.readouterr().out.splitlines()[-3:] == lines


# ------------------------------------------------------------------ 5. a detail joins the idea it details


def test_the_joining_rule_is_one_constant_in_the_match_prompt():
    rule = match.JOIN_RULE
    assert rule in match.MATCH_SYSTEM and match.MATCH_SYSTEM.count("accepting one means accepting the other") == 0
    assert "details it, narrows it, is a step towards it, or is a way of doing it: then its stance is refines" in rule
    assert "Start a new idea only for something George would decide on separately" in rule
    assert '"work must survive restarts" and "adopt Temporal for it" are two ideas' in rule
    system = consolidate.CONSOLIDATE_SYSTEM
    assert "When in doubt" not in system and "Merge when George would answer them as one question." in system
    assert "a part, a detail, a step or a narrower form of the other: keep the broader one" in system
    assert "Never merge a goal with a tool or vendor" in system and "Never merge ideas that only touch the same part" in system


async def test_a_claim_that_details_an_idea_joins_it_as_refines(place, the_map):
    store, _ledger = place
    model = fx.Scripted()
    model.claims["test-note-kappa.md"] = [fx.claim("Save each job's step every minute", "Each job saves the step it is on.",
                                                   "Each job should save the step it is on every minute", "TEST SECTION: Saving steps",
                                                   "Work survives a restart", stance="refines")]
    await fx.read_old_way(store, model, *FIRST_THREE)
    flow.receive(store, "test-note-kappa.md", b"# TEST RESEARCH NOTE - invented for CLIVE's tests (kappa)\n\n## TEST SECTION: Saving "
                 b"steps\n\nEach job should save the step it is on every minute, so a restart can pick it up there.\n", via="screen")
    await flow.run_pending(store, model=model)
    gen = await synthesise(store, model=model, the_map=the_map)
    synth = synthesis_store(store)
    kappa = next(d for d, c in synth.claims(gen).items() if c["document"] == "test-note-kappa.md")
    restart = next(i for i in synth.ideas(gen).values() if i["name"] == "Work survives a restart")
    (detail,) = [s for s in restart["sources"] if s["doc_id"] == kappa]
    assert detail["stance"] == "refines" and kappa in documents_backing(restart)
    assert len([i for i in synth.ideas(gen).values() if i["status"] == "active"]) == 10, "no new idea"
    assert synth.run(gen)["shape"]["started"][-1] == {"doc_id": kappa, "ideas": 0}, "read last, and started nothing"
