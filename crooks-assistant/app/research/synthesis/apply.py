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

from app.research.model import ModelError
from app.research.review import normalise
from app.research.synthesis.ask import SynthesisError
from app.research.synthesis.ideas import evidence_hash, finish
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


def _renamed_words(to: str, was: str, previous: str, old_ids: set[str]) -> str:
    if to in old_ids:
        return f"Continues {to} from {previous}, so your answer to it stays with it."
    return f"Now {to}: {was} was an id an earlier generation used."


def finish_renames(synth: SynthesisStore, gen: str, previous: str) -> list[str]:
    """[second review N2] A rename stopped between writing an idea under its new id and removing its old
    file leaves the idea on disk twice. Finish it: the old file (the same evidence, under an id the other
    idea was) goes, and the rename is said once. Returns the ids removed."""
    ideas = synth.ideas(gen)
    said = {(e.get("idea"), e.get("was_id")) for e in synth.events(gen) if e.get("type") == "renumbered"}
    old_ids = set(synth.ideas(previous)) if previous else set()
    dropped: list[str] = []
    for idea in ideas.values():
        for was in idea.get("was") or []:
            stale = ideas.get(was)
            if was == idea["id"] or was in dropped or stale is None or evidence_hash(stale) != evidence_hash(idea):
                continue
            synth.remove_idea(gen, was)
            dropped.append(was)
            if (idea["id"], was) not in said:
                synth.event(gen, "renumbered", idea=idea["id"], was_id=was,
                            said=_renamed_words(idea["id"], was, previous, old_ids))
    return dropped


def renumber(synth: SynthesisStore, gen: str, mapping: dict[str, str], previous: str) -> dict[str, str]:
    """Give the generation's ideas their final ids: the old ids `mapping` names, and a fresh id for any
    other id an earlier generation used. Returns every change made, {was: now}. A rename an earlier try
    stopped halfway through is finished first (`finish_renames`), and an idea that already has its final
    id is left as it is."""
    finish_renames(synth, gen, previous)
    ideas = synth.ideas(gen)
    taken = synth.used_ids(but=gen)
    final: dict[str, str] = {}
    for idea_id in ideas:
        if idea_id in mapping:
            if mapping[idea_id] != idea_id:
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


async def apply(research_store, gen: str, *, model, the_map, say=lambda _t: None,
                accept_unmatched: bool = False) -> dict[str, Any]:
    """Make `gen` live. Returns what was done; raises SynthesisError with why it wasn't. [review 9] It refuses
    when an answer of his wouldn't stay with its idea (`unmatched`), unless `accept_unmatched`."""
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
        finish_renames(synth, gen, previous)       # [second review N2] before anything reads its ideas
        calls = run_module.Calls(model)
        work = run_module.Work(synth, gen, calls, the_map, say=say)
        taken_in, missing = [], []
        failed = run.get("failed") or {}
        for record in run_module.documents_done(research_store):
            if work.has_document(record):
                continue
            say(f"Taking in {record.get('name')}, read since the run")
            text = run_module.document_text(research_store, record)
            if record["id"] in failed:
                # [review 15] One the run couldn't read gets one more try; still unreadable, it stays out, said.
                try:
                    await run_module.extract_twice(work, record, text)
                except (SynthesisError, ModelError) as exc:
                    missing.append({"name": record.get("name") or "", "why": f"what it recommends couldn't be read ({exc})"})
                    say(f"  {record.get('name')}: still couldn't be read; it isn't in it")
                    continue
            touched = await run_module.absorb(work, record, text)
            await run_module.judge(work, touched)
            taken_in.append(record.get("name"))
        if missing:
            run["missing_at_apply"] = missing
            synth.save_run(gen, run)
        if taken_in:
            # Their old proposals, if they were read the old way, join their ideas' history too.
            run_module.link_old_proposals(research_store, work, run)
            await run_module.summarise(work)
            run["calls"] = int(run.get("calls") or 0) + calls.made
            run["taken_in_at_apply"] = [*run.get("taken_in_at_apply", []), *taken_in]
            for record in run_module.documents_done(research_store):
                if record.get("name") in taken_in:
                    (run.get("failed") or {}).pop(record["id"], None)
            synth.save_run(gen, run)
        mapping = reuse(synth.ideas(previous), synth.ideas(gen)) if previous else {}
        lost = unmatched(synth.ideas(previous), synth.ideas(gen), mapping, his_answers()) if previous else []
        run["unmatched"] = lost
        synth.save_run(gen, run)
        if lost and not accept_unmatched:
            raise SynthesisError(f"{gen} was not made live: {len(lost)} of your answers wouldn't stay with their idea. "
                                 + " ".join(p["said"] for p in lost)
                                 + " Run it again with --accept-unmatched to make it live anyway.")
        changed = renumber(synth, gen, mapping, previous)
        carried = carry_history(synth, gen, previous, mapping)
        synth.set_live(gen)
        if previous:
            synth.event(previous, "superseded", said=f"Superseded by {gen}, made live.", by=gen)
        synth.event(gen, "applied", said=f"Made live{', replacing ' + previous if previous else ''}.", replaced=previous,
                    unmatched=[p["idea"] for p in lost])
    return {"generation": gen, "previous": previous, "taken_in": taken_in, "kept_ids": len(mapping),
            "renumbered": changed, "calls": calls.made, "unmatched": lost, "history_carried": carried, "missing": missing}


# ------------------------------------------------------------------ his answers across generations (review 9)


def his_answers() -> dict[str, str]:
    """His newest answer (go, later, no) to each idea id, from the owner judgment ledger."""
    from app.builds import decisions
    from app.research.synthesis import answers as idea_answers

    try:
        return idea_answers.keys(decisions.ledger().effective())
    except decisions.DecisionError as exc:
        raise SynthesisError(f"Your answers couldn't be read, so nothing was made live: {exc}") from None


def _home(idea: dict[str, Any], new: dict[str, dict[str, Any]]) -> str:
    """The new idea that holds most of an old idea's evidence (by quote), or ""."""
    mine = _quotes(idea)
    best, most = "", 0
    for new_id, other in new.items():
        if other.get("status") != "active":
            continue
        n = sum(1 for q in mine if _same(q, _quotes(other)))
        if n > most:
            best, most = new_id, n
    return best


def unmatched(old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]], mapping: dict[str, str],
              answered: dict[str, str]) -> list[dict[str, Any]]:
    """Answers of his that wouldn't stay with their idea: an idea he answered that no new idea carries on,
    and ideas he answered differently whose evidence lands in one new idea. `home` is the new idea's id in
    the run, before applying gives it its final one; the words name it."""
    words = {"go": "Approve the work", "later": "Not now", "no": "Not for CLIVE"}
    carried = set(mapping.values())
    mine = {i: k for i, k in answered.items() if (old.get(i) or {}).get("status") == "active"}
    out, homes = [], {}
    for old_id, key in sorted(mine.items()):
        home = _home(old[old_id], new)
        homes.setdefault(home, []).append((old_id, key))
        if old_id not in carried:
            where = f"; most of its evidence is now in the idea “{new[home].get('name')}”" if home else "; none of its evidence is in it"
            out.append({"idea": old_id, "answer": key, "home": home,
                        "said": f"{old_id} ({old[old_id].get('name')}), which you answered {words.get(key, key)}, isn't carried on"
                                f"{where}."})
    for home, olds in homes.items():
        if home and len({k for _i, k in olds}) > 1:
            each = ", ".join(f"{i} ({old[i].get('name')}: {words.get(k, k)})" for i, k in olds)
            out.append({"idea": home, "answer": "", "home": home, "answered": [i for i, _k in olds],
                        "said": f"{each} are one idea now, “{new[home].get('name')}”, and you answered them differently."})
    return out


def carried_answers(synth: SynthesisStore) -> list[tuple[str, str]]:
    """(quote, his answer) for every quote behind an idea he answered in the live generation: a full
    re-synthesis never merges two ideas whose evidence carries different answers of his."""
    live = synth.live()
    if not live:
        return []
    answered = his_answers()
    return [(q, answered[i]) for i, idea in synth.ideas(live).items()
            if idea.get("status") == "active" and i in answered for q in _quotes(idea)]


def answers_carried(idea: dict[str, Any], carried: list[tuple[str, str]]) -> str:
    """The answer an idea's evidence carries from the live generation: "" for none, the key for one, and
    "mixed:…" for several, which never matches a single answer."""
    mine = _quotes(idea)
    keys = sorted({k for q, k in carried if _same(q, mine)})
    return "" if not keys else keys[0] if len(keys) == 1 else "mixed:" + "+".join(keys)


CARRIED_TYPES = ("owner_answered", "prepared", "old_screen", "earlier")


def carry_history(synth: SynthesisStore, gen: str, previous: str, mapping: dict[str, str]) -> int:
    """Each idea carried on from the generation live before brings its history with it, as events in the
    new one: his answers, its prepared builds, the old screen's lines (unless linked here already), and how
    CLIVE last judged it ("Earlier view …"). Written once, however often this runs."""
    if not previous or not mapping:
        return 0
    old_ideas, new_ideas = synth.ideas(previous), synth.ideas(gen)
    events = synth.events(previous)
    mine = synth.events(gen)
    have = {(e.get("idea"), e.get("source")) for e in mine if e.get("type") == "earlier"}
    written = 0
    for old_id in mapping.values():
        here = {old_id, *((new_ideas.get(old_id) or {}).get("was") or [])}
        linked = {e.get("proposal_id") for e in mine if e.get("type") == "old_screen" and e.get("idea") in here}
        ids = {old_id, *((old_ideas.get(old_id) or {}).get("was") or [])}
        theirs = [e for e in events if e.get("idea") in ids]
        judged_ = [e for e in theirs if e.get("type") == "judged"][-1:]
        for e in [*(x for x in theirs if x.get("type") in CARRIED_TYPES), *judged_]:
            kind = e.get("was_type") or e.get("type")
            if kind == "old_screen" and e.get("proposal_id") in linked:
                continue
            source = f"{e.get('from_generation') or previous}:{e.get('source') or e.get('at')}:{e.get('type')}"
            if (old_id, source) in have:
                continue
            said = f"Earlier view ({previous}): {e.get('said')}" if kind == "judged" else str(e.get("said") or "")
            extra = {k: e[k] for k in ("proposal_id", "old_at", "answer", "request_id") if e.get(k)}
            synth.event(gen, "earlier", idea=old_id, said=said, at=str(e.get("at") or ""), was_type=kind,
                        from_generation=e.get("from_generation") or previous, source=source, **extra)
            have.add((old_id, source))
            written += 1
    return written


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
