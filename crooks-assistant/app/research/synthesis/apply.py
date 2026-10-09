"""Making a generation live, and packing one up for the Director to compare.

Why this exists: a full synthesis run (app/research/synthesis/run.py) is never live by itself. The
Director compares it with the old screen first (`scripts/research.py --export-synthesis`), and only
then makes it live (`--apply GEN`).

What `apply` does, in order, holding the research store's lock:
1. takes in every document read since the run began (each `done` document not in it yet), as a new
   document would be once live: extract (from the cache when it was read while waiting), match,
   consolidate, judge what it touched, link its old proposals, sum up; its calls join run.json's;
2. keeps George's answers attached: a new idea takes an old idea's id when at least half of its
   sources (by claim quote) came from that old idea, in the generation live before. His answer then
   shows as "your answer to an earlier view" until he answers again. Any other id that an earlier
   generation used is given a fresh one, so an answer never lands on a different idea;
3. writes LIVE, and appends a `superseded` event to the generation that was live before. That
   generation stays on disk, as every generation does.

What `export` promises: a .tgz of one generation (claims, ideas, events, summary, run), written 0600,
and never inside the repository: the repository is public, and research stays on the server.
"""

from __future__ import annotations

import os
import tarfile
from pathlib import Path
from typing import Any

from app.research.review import normalise
from app.research.synthesis.ask import SynthesisError
from app.research.synthesis.ideas import finish
from app.research.synthesis.store import SynthesisStore, now, synthesis_store

REUSE_SHARE = 0.5
EXPORTED = ("claims", "ideas", "events.jsonl", "summary.json", "run.json")


def _quotes(idea: dict[str, Any]) -> list[str]:
    return [q for q in (normalise(s.get("quote") or "") for s in idea.get("sources") or []) if q]


def _same(quote: str, theirs: list[str]) -> bool:
    """The same passage: equal, or one holds the other (a scrap under 12 characters holds nothing)."""
    return any(quote == q or (min(len(quote), len(q)) >= 12 and (quote in q or q in quote)) for q in theirs)


def reuse(old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]]) -> dict[str, str]:
    """{new id: old id} for each new idea at least half of whose sources came from one old idea. Each
    old id is given to one new idea at most, the strongest overlap first."""
    olds = {i: _quotes(idea) for i, idea in old.items() if idea.get("status") == "active"}
    pairs = []
    for new_id, idea in new.items():
        mine = _quotes(idea)
        if idea.get("status") != "active" or not mine:
            continue
        for old_id, theirs in olds.items():
            share = sum(1 for q in mine if _same(q, theirs)) / len(mine)
            if share >= REUSE_SHARE:
                pairs.append((share, new_id, old_id))
    out: dict[str, str] = {}
    for _share, new_id, old_id in sorted(pairs, key=lambda p: (-p[0], p[1], p[2])):
        if new_id not in out and old_id not in out.values():
            out[new_id] = old_id
    return out


def renumber(synth: SynthesisStore, gen: str, mapping: dict[str, str], previous: str) -> dict[str, str]:
    """Give the generation's ideas their final ids: the old ids `mapping` names, and a fresh id for any
    other id an earlier generation used. Returns every change made, {was: now}."""
    ideas = synth.ideas(gen)
    taken = synth.used_ids(but=gen)
    final: dict[str, str] = {}
    for idea_id in ideas:
        if idea_id in mapping:
            final[idea_id] = mapping[idea_id]
        elif idea_id in taken or idea_id in mapping.values():
            final[idea_id] = synth.next_idea_id(gen)
    if not final:
        return {}
    moved = {}
    for was, to in final.items():
        idea = dict(ideas[was], id=to, was=[*ideas[was].get("was", []), was])
        moved[to] = idea
    for idea in [*moved.values(), *(i for k, i in ideas.items() if k not in final)]:
        if idea.get("merged_into") in final:
            idea["merged_into"] = final[idea["merged_into"]]
    # [review 8] Every idea is written under its new id first; only then do the old files go (never one
    # that is also a new id), so stopping halfway leaves each idea on disk under one id or both.
    for idea in [*moved.values(), *(i for k, i in ideas.items() if k not in final)]:
        synth.save_idea(gen, finish(idea, idea.get("updated_at") or now()) if idea.get("judged_with") is None
                        else _refinger(idea))
    for was in final:
        if was not in moved:
            synth.remove_idea(gen, was)
    for was, to in final.items():
        if was in mapping:
            said = f"Continues {to} from {previous}, so your answer to it stays with it."
        else:
            said = f"Now {to}: {was} was an id an earlier generation used."
        synth.event(gen, "renumbered", idea=to, was_id=was, said=said)
    return final


def _refinger(idea: dict[str, Any]) -> dict[str, Any]:
    """A renamed idea's fingerprint covers its new id; its judgment stands (the evidence is the same)."""
    with_ = dict(idea.get("judged_with") or {})
    finish(idea, idea.get("updated_at") or now())
    with_["evidence_hash"] = idea["evidence_hash"]
    idea["judged_with"] = with_
    return idea


async def apply(research_store, gen: str, *, model, the_map, say=lambda _t: None) -> dict[str, Any]:
    """Make `gen` live. Returns what was done; raises SynthesisError with why it wasn't."""
    from app.research.flow import _store_lock
    from app.research.synthesis import run as run_module

    synth = synthesis_store(research_store)
    if not synth.exists(gen):
        raise SynthesisError(f"There is no generation {gen}.")
    run = synth.run(gen) or {}
    if run.get("stage") != "done":
        raise SynthesisError(f"{gen} hasn't finished ({run_module.STAGE_WORDS.get(run.get('stage', ''), 'no run record')}); "
                             "resume it first.")
    previous = synth.live()
    if previous == gen:
        return {"generation": gen, "already": True}
    with _store_lock(research_store), run_module.run_lock(synth):
        calls = run_module.Calls(model)
        work = run_module.Work(synth, gen, calls, the_map, say=say)
        taken_in = []
        for record in run_module.documents_done(research_store):
            if work.has_document(record):
                continue
            say(f"Taking in {record.get('name')}, read since the run")
            touched = await run_module.absorb(work, record, run_module.document_text(research_store, record))
            await run_module.judge(work, touched)
            taken_in.append(record.get("name"))
        if taken_in:
            # Their old proposals, if they were read the old way, join their ideas' history too.
            run_module.link_old_proposals(research_store, work, run)
            await run_module.summarise(work)
            run["calls"] = int(run.get("calls") or 0) + calls.made
            run["taken_in_at_apply"] = [*run.get("taken_in_at_apply", []), *taken_in]
            synth.save_run(gen, run)
        mapping = reuse(synth.ideas(previous), synth.ideas(gen)) if previous else {}
        changed = renumber(synth, gen, mapping, previous)
        synth.set_live(gen)
        if previous:
            synth.event(previous, "superseded", said=f"Superseded by {gen}, made live.", by=gen)
        synth.event(gen, "applied", said=f"Made live{', replacing ' + previous if previous else ''}.", replaced=previous)
    return {"generation": gen, "previous": previous, "taken_in": taken_in, "kept_ids": len(mapping),
            "renumbered": changed, "calls": calls.made}


def export(research_store, gen: str, path: str | os.PathLike) -> Path:
    """One generation as a .tgz at `path` (never inside the repository), 0600."""
    from app.research.rules import APP_ROOT

    synth = synthesis_store(research_store)
    if not synth.exists(gen):
        raise SynthesisError(f"There is no generation {gen}.")
    target = Path(path).expanduser().resolve()
    repository = APP_ROOT.parent.resolve()
    if target == repository or repository in target.parents:
        raise SynthesisError(f"{target} is inside CLIVE's repository, which is public: research never goes there.")
    target.parent.mkdir(parents=True, exist_ok=True)
    folder = synth.gen_dir(gen)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "wb") as out, tarfile.open(fileobj=out, mode="w:gz") as tar:
        for name in EXPORTED:
            if (folder / name).exists():
                tar.add(folder / name, arcname=f"{gen}/{name}")
    return target
