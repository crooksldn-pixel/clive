"""Running the synthesis: every document into a new generation, one new document into the live one,
making a generation live, and packing one up for the Director.

Why this exists: DEC-078. A full run (`scripts/research.py --synthesise`) reads every document that
was read (`done`) again from the digester's store, and takes each through extract, match and, when it
started an idea, consolidate; then consolidates once more, links the old screen's proposals, judges
every idea and sums up. Once a generation is live, each new document goes the same way into it
(app/research/flow.py), and only the ideas it touched are judged again.

What it promises:
- A full run is never live: `apply` makes it live, after taking in any document read since.
- A run is resumable after any model failure: run.json says the stage it reached, which documents
  are in, and every error in words; `--resume` carries on from there.
- What a file said is read by the model once: extraction is cached by the file's digest, so reading
  the same document again makes no model call and no event.
- Every call is counted in run.json, by stage.
- Only one full run at a time on a server (a lock file in the synthesis folder).
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
from collections.abc import Callable
from typing import Any

from app.research.model import ModelError
from app.research.synthesis import consolidate as consolidate_step
from app.research.synthesis import judge as judge_step
from app.research.synthesis import match as match_step
from app.research.synthesis import migrate
from app.research.synthesis import summary as summary_step
from app.research.synthesis.ask import Calls, SynthesisError
from app.research.synthesis.extract import VERSION, extract
from app.research.synthesis.ideas import evidence_hash, finish, has_claim, judged, new_idea
from app.research.synthesis.store import ReadProblem, SynthesisStore, now, synthesis_store

STAGES = ("documents", "consolidate", "migrate", "judge", "summary", "done")
# How far a run has got, as the screen says it ("judging, 31 of 42"); `done` and `of` count only in the
# stages that have something to count (documents, judging), and are 0 in the others.
STAGE_WORDS = {"documents": "reading documents", "consolidate": "joining ideas that are the same",
               "migrate": "linking the old proposals", "judge": "judging", "summary": "summing up",
               "done": "finished, waiting to be made live"}


class Stopped(Exception):
    """A run that stopped part-way, said in words; `--resume` carries on."""


def _say_nothing(_text: str) -> None:
    return None


# ------------------------------------------------------------------ one generation, in hand


class Work:
    """A generation being written: its ideas and claims in hand, every change saved as it is made."""

    def __init__(self, synth: SynthesisStore, gen: str, calls: Calls, the_map, *, answered: dict[str, str] | None = None,
                 say: Callable[[str], None] = _say_nothing) -> None:
        self.synth, self.gen, self.calls, self.the_map = synth, gen, calls, the_map
        self.ideas = synth.ideas(gen)
        self.claims = synth.claims(gen)
        self.answered = answered or {}
        self.changed = False
        self.say = say
        self.base: tuple[int, dict[str, int]] = (0, {})

    def active(self) -> list[dict[str, Any]]:
        return [i for i in self.ideas.values() if i.get("status") == "active"]

    def save(self, idea: dict[str, Any]) -> None:
        finish(idea, now())
        self.ideas[idea["id"]] = idea
        self.synth.save_idea(self.gen, idea)

    def event(self, kind: str, *, idea: str | None, said: str, **fields: Any) -> None:
        self.synth.event(self.gen, kind, idea=idea, said=said, **fields)

    def documents(self) -> dict[str, str]:
        return {doc_id: c.get("document") or "" for doc_id, c in self.claims.items()}

    def has_document(self, record: dict[str, Any]) -> bool:
        digest = record.get("file_digest") or ""
        return record["id"] in self.claims or bool(digest and any(
            c.get("file_digest") == digest for c in self.claims.values()))


# ------------------------------------------------------------------ steps 1-2: what a document says


def _cache_key(record: dict[str, Any]) -> str:
    digest = str(record.get("file_digest") or "")
    return hashlib.sha256(f"{digest}:{VERSION}".encode()).hexdigest() if digest else ""


async def read_claims(synth: SynthesisStore, record: dict[str, Any], text: str, calls: Calls) -> dict[str, Any]:
    """What the document says, from the cache when this file was read before."""
    key = _cache_key(record)
    cached = synth.cached(key) if key else None
    if cached and cached.get("version") == VERSION:
        return cached
    found = await extract(name=record.get("name") or "research", text=text, calls=calls)
    if key:
        synth.cache(key, found)
    return found


def claims_record(record: dict[str, Any], found: dict[str, Any]) -> dict[str, Any]:
    claims = [dict(c, id=f"{record['id']}:{c['n']}") for c in found.get("claims") or []]
    return {"doc_id": record["id"], "document": record.get("name") or "", "artifact_id": record.get("artifact_id") or "",
            "file_digest": record.get("file_digest") or "", "version": found.get("version"),
            "thesis": found.get("thesis") or "", "concepts": found.get("concepts") or [],
            "stances_against": found.get("stances_against") or [], "sequence": found.get("sequence") or [],
            "claims": claims, "unplaced": found.get("unplaced") or [], "parts": found.get("parts") or 1, "at": now()}


# ------------------------------------------------------------------ step 3: into ideas


async def absorb(work: Work, record: dict[str, Any], text: str) -> set[str]:
    """One document's claims into the generation's ideas. Returns the ideas it touched (empty when the
    document, or the same file, is already in: then nothing is asked and nothing is recorded)."""
    if work.has_document(record):
        return set()
    found = await read_claims(work.synth, record, text, work.calls)
    doc = claims_record(record, found)
    work.say(f"  {doc['document']}: {len(doc['claims'])} recommendations, {len(doc['unplaced'])} couldn't be placed")
    touched, created = await _match(work, doc)
    work.synth.write_json(work.synth.claims_path(work.gen, record["id"]), doc)
    work.claims[record["id"]] = doc
    if created:
        touched |= await consolidate(work)
    return {work_id for work_id in touched if work.ideas.get(work_id, {}).get("status") == "active"}


async def _match(work: Work, doc: dict[str, Any]) -> tuple[set[str], set[str]]:
    claims = [c for c in doc["claims"] if not any(has_claim(i, c["id"]) for i in work.ideas.values())]
    stances = [s for s in doc["stances_against"] if s.get("quote")]
    batches = [claims[i:i + match_step.BATCH] for i in range(0, len(claims), match_step.BATCH)] or ([[]] if stances else [])
    touched: set[str] = set()
    created: set[str] = set()
    joined: dict[str, int] = {}
    for n, batch in enumerate(batches):
        last = n == len(batches) - 1
        landing = await match_step.place(document=doc["document"], concepts=doc["concepts"],
                                         active=[{"id": i["id"], "name": i["name"], "statement": i["statement"]}
                                                 for i in work.active()],
                                         claims=batch, stances=stances if last else [], calls=work.calls)
        made = _new_ideas(work, landing, doc)
        created |= set(made.values())
        for claim in batch:
            ref, stance, centrality = landing.claims[claim["id"]]
            idea = work.ideas[made.get(ref, ref)]
            idea["sources"].append({"doc_id": doc["doc_id"], "claim_id": claim["id"], "document": doc["document"],
                                    "section": claim.get("section") or "", "quote": claim["quote"],
                                    "says": claim["says"], "title": claim["title"], "stance": stance,
                                    "centrality": centrality})
            if stance == "opposes":
                idea["against"].append({"claim_id": claim["id"], "why": claim["says"]})
            touched.add(idea["id"])
            if idea["id"] not in created:
                joined[idea["id"]] = joined.get(idea["id"], 0) + 1
        for stance_n, ref in landing.stances.items():
            idea = work.ideas.get(made.get(ref, ref))
            stance = next(s for s in stances if s["n"] == stance_n)
            if idea is not None:
                idea["against"].append({"claim_id": f"stance:{doc['doc_id']}:{stance_n}", "why": stance["says"]})
                touched.add(idea["id"])
                joined.setdefault(idea["id"], 0)
        for idea_id in touched:
            work.save(work.ideas[idea_id])
    for idea_id, count in joined.items():
        idea = work.ideas[idea_id]
        mine = [s for s in idea["sources"] if s["doc_id"] == doc["doc_id"]]
        stances_said = sorted({s["stance"] for s in mine}) or ["opposes"]
        work.event("source_joined", idea=idea_id, doc_id=doc["doc_id"],
                   said=f"{doc['document']} joined it: {_n(count, 'recommendation')} ({', '.join(stances_said)}).")
    return touched, created


def _new_ideas(work: Work, landing, doc: dict[str, Any]) -> dict[str, str]:
    made = {}
    for key, given in landing.new.items():
        # Only a claim starts an idea: a stance against something no claim proposes stays in the claims record.
        if not any(ref == key for ref, _s, _c in landing.claims.values()):
            continue
        idea = new_idea(work.synth.next_idea_id(work.gen), name=given.get("name") or "", statement=given.get("statement") or "",
                        kind=given.get("kind") or "", at=now())
        work.ideas[idea["id"]] = idea
        made[key] = idea["id"]
        work.event("created", idea=idea["id"], doc_id=doc["doc_id"], said=f"Created from {doc['document']}: {idea['name']}.")
    return made


def _n(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


# ------------------------------------------------------------------ step 4: the same proposition, once


async def consolidate(work: Work) -> set[str]:
    merges = await consolidate_step.propose(work.active(), work.answered, work.calls)
    touched = set()
    for merge in merges:
        keep = work.ideas[merge["keep"]]
        for other_id in merge["merge"]:
            other = work.ideas[other_id]
            consolidate_step.merge_into(keep, other)
            work.save(other)
            work.event("merged", idea=other_id, into=keep["id"], said=f"Joined {keep['id']} ({keep['name']}): {merge['why']}")
            work.event("merged", idea=keep["id"], merged=other_id, said=f"{other_id} ({other['name']}) joined it: {merge['why']}")
        work.save(keep)
        touched.add(keep["id"])
    return touched


# ------------------------------------------------------------------ step 5: the four answers


def needs_judging(idea: dict[str, Any], map_digest: str) -> bool:
    if not judged(idea):
        return True
    with_ = idea.get("judged_with") or {}
    return with_.get("evidence_hash") != idea.get("evidence_hash") or with_.get("map_digest") != map_digest


async def judge(work: Work, only: set[str] | None = None, *, progress: Callable[[int, int], None] | None = None) -> int:
    """Judge every active idea that needs it (of `only`, when given). Returns how many were judged."""
    for idea in work.active():
        finish(idea, idea.get("updated_at") or now())     # the evidence hash as the sources stand
    todo = [i for i in work.active() if (only is None or i["id"] in only) and needs_judging(i, work.the_map.digest)]
    if not todo:
        return 0
    the_design = judge_step.design(work.the_map)
    documents = work.documents()
    done = 0
    for start in range(0, len(todo), judge_step.BATCH):
        batch = todo[start:start + judge_step.BATCH]
        raw = await judge_step.ask(batch, the_design=the_design, documents=documents, calls=work.calls)
        for idea in batch:
            await _judge_one(work, idea, raw[idea["id"]], documents)
        done += len(batch)
        if progress:
            progress(done, len(todo))
    return done


async def _judge_one(work: Work, idea: dict[str, Any], raw: dict[str, Any], documents: dict[str, str]) -> None:
    before = {k: idea.get(k) for k in ("answers", "owner_view", "owner_view_complete")} if judged(idea) else None
    before_answers = dict((before or {}).get("answers") or {})
    notes = judge_step.enforce(idea, raw, the_map=work.the_map, previous=before)
    if not idea["owner_view_complete"]:
        view = judge_step.owner_view_from(await judge_step.ask_owner_view(idea, documents, work.calls))
        if judge_step.view_complete(view, idea["answers"]["importance"]):
            idea["owner_view"], idea["owner_view_complete"] = view, True
        else:
            idea["owner_view"] = idea["owner_view"] or view
            work.event("owner_view_incomplete", idea=idea["id"],
                       said="Its plain-English view is incomplete, even after CLIVE asked again; it is shown as it is.")
    for note in [n for n in notes if n.startswith("Dropped “needs you”")]:
        work.event("needs_you_dropped", idea=idea["id"], said=note)
    finish(idea, now())
    idea["judged_with"] = {"map_digest": work.the_map.digest, "evidence_hash": idea["evidence_hash"],
                           "model": work.calls.name, "at": now()}
    if any(before_answers.get(a) != idea["answers"].get(a) for a in ("judgment", "importance", "timing")):
        work.changed = True
    said = judge_step.judged_words(idea, before_answers or None)
    rule_notes = [n for n in notes if not n.startswith("Dropped “needs you”")]
    if rule_notes:
        said += " Checked by CLIVE's rules: " + " ".join(rule_notes)
    work.event("judged", idea=idea["id"], was=before_answers, now=dict(idea["answers"]), why=idea["reasons"],
               checked_by=idea["checked_by"], said=said)
    work.save(idea)


# ------------------------------------------------------------------ step 6: the summary


async def summarise(work: Work, *, force: bool = False) -> bool:
    """The summary written again when an answer that matters changed (or `force`); otherwise only its
    counts are brought up to date, which takes no model call. True when the model wrote it."""
    existing = work.synth.summary(work.gen)
    if not (work.changed or force or existing is None):
        work.synth.save_summary(work.gen, dict(existing, counts=summary_step.counts(work.ideas, work.claims)))
        return False
    if not [i for i in work.active() if judged(i)]:
        return False
    work.synth.save_summary(work.gen, await summary_step.write(work.ideas, work.claims, work.calls, now(), work.gen))
    return True


# ------------------------------------------------------------------ a full run


def documents_done(research_store) -> list[dict[str, Any]]:
    """Every document read whole (`done`), not a repeat of another, oldest first."""
    records = [r for r in research_store.documents() if r.get("state") == "done" and not r.get("repeat_of")
               and r.get("artifact_id")]
    return sorted(records, key=lambda r: (str(r.get("received_at") or ""), str(r.get("name") or ""), r["id"]))


def document_text(research_store, record: dict[str, Any]) -> str:
    """The research as the scanner read it, from the digester's store (the file as given is gone)."""
    from app.digest.store import DigestStore
    from app.research.flow import document_text as text_of

    artifact = DigestStore(research_store.digests).load(record["artifact_id"])
    return text_of(artifact.units)


@contextlib.contextmanager
def run_lock(synth: SynthesisStore):
    synth.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(synth.root / ".run.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Stopped("Another synthesis run is going on this server; let it finish first.") from None
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def unfinished(synth: SynthesisStore) -> str:
    """The newest generation whose run hasn't finished, or ""."""
    for gen in reversed(synth.generations()):
        run = synth.run(gen) or {}
        if run.get("mode") == "full" and run.get("stage") != "done":
            return gen
    return ""


async def synthesise(research_store, *, model, the_map, resume: bool = False, timeout_s: float | None = None,
                     say: Callable[[str], None] = _say_nothing) -> str:
    """Build a new generation from every document read, or carry on the one that stopped. Not live.
    Returns its name; raises Stopped with why when it stops part-way."""
    synth = synthesis_store(research_store)
    with run_lock(synth):
        gen = unfinished(synth) if resume else ""
        if resume and not gen:
            raise Stopped("There is no synthesis run to resume.")
        gen = gen or synth.new_generation()
        run = synth.run(gen) or {"generation": gen, "mode": "full", "stage": STAGES[0], "started_at": now(),
                                  "finished_at": "", "documents": {}, "done": 0, "of": 0, "calls": 0,
                                  "calls_by_stage": {}, "errors": [], "changed": False, "unlinked": [],
                                  "model": getattr(model, "name", "model"), "map_digest": the_map.digest}
        calls = Calls(model, timeout_s=timeout_s)
        work = Work(synth, gen, calls, the_map, say=say)
        work.changed = bool(run.get("changed"))
        work.base = (int(run.get("calls") or 0), dict(run.get("calls_by_stage") or {}))
        say(f"Synthesis {gen}: {'carrying on from ' + STAGE_WORDS[run['stage']] if resume else 'started'}.")
        try:
            await _stages(research_store, work, run, say)
        except (SynthesisError, ReadProblem, ModelError) as exc:
            _error(work, run, str(exc))
            raise Stopped(f"It stopped while {STAGE_WORDS[run['stage']]}: {exc} Run it again with --resume.") from None
        finally:
            _count(work, run)
            synth.save_run(gen, run)
        return gen


def _error(work: Work, run: dict[str, Any], said: str) -> None:
    run["errors"].append({"at": now(), "stage": run["stage"], "said": said[:400]})


def _count(work: Work, run: dict[str, Any]) -> None:
    """The calls made so far: those before this process (a resumed run) and this process's own."""
    before, by = work.base
    run["calls"] = before + work.calls.made
    run["calls_by_stage"] = {k: by.get(k, 0) + work.calls.by_stage.get(k, 0) for k in sorted({*by, *work.calls.by_stage})}
    run["changed"] = work.changed


async def _stages(research_store, work: Work, run: dict[str, Any], say) -> None:
    synth = work.synth

    def save() -> None:
        _count(work, run)
        synth.save_run(work.gen, run)

    if run["stage"] == "documents":
        records = documents_done(research_store)
        run["of"] = len(records)
        for record in records:
            if run["documents"].get(record["id"]) in ("in", "failed"):
                continue
            try:
                text = document_text(research_store, record)
            except (OSError, ValueError) as exc:
                run["documents"][record["id"]] = "failed"
                _error(work, run, f"{record.get('name')}: its sections couldn't be read from the digester's store ({exc}).")
                save()
                continue
            say(f"Reading {record.get('name')} ({len([v for v in run['documents'].values() if v == 'in']) + 1} of {len(records)})")
            await absorb(work, record, text)
            run["documents"][record["id"]] = "in"
            run["done"] = sum(1 for v in run["documents"].values() if v == "in")
            save()
        run["stage"], run["done"], run["of"] = "consolidate", 0, 0
        save()
    if run["stage"] == "consolidate":
        say("Joining ideas that are the same")
        await consolidate(work)
        run["stage"], run["done"], run["of"] = "migrate", 0, 0
        save()
    if run["stage"] == "migrate":
        say("Linking the old screen's proposals to their ideas")
        link_old_proposals(research_store, work, run)
        run["stage"], run["done"], run["of"] = "judge", 0, 0
        save()
    if run["stage"] == "judge":
        def progress(done: int, of: int) -> None:
            run["done"], run["of"] = done, of
            save()
            say(f"Judged {done} of {of}")
        await judge(work, progress=progress)
        run["stage"], run["done"], run["of"] = "summary", 0, 0
        save()
    if run["stage"] == "summary":
        say("Summing up")
        await summarise(work, force=True)
        run["stage"], run["done"], run["of"], run["finished_at"] = "done", 0, 0, now()
        run["report"] = report(work, run)
        save()


def link_old_proposals(research_store, work: Work, run: dict[str, Any]) -> None:
    from app.builds import decisions

    done = {e.get("proposal_id") for e in work.synth.events(work.gen) if e.get("type") == "old_screen"}
    try:
        effective = decisions.ledger().effective()
    except decisions.DecisionError as exc:
        effective = {}
        _error(work, run, f"The owner's answers couldn't be read, so the old screen's answers aren't in the history: {exc}")
    answers = {pid: decisions.chosen(record) for pid, record in effective.items()
               if pid.startswith(f"{decisions.RESEARCH}:")}
    answers = {pid: {"label": c["label"], "at": c["decided_at"]} for pid, c in answers.items() if c}
    links, unlinked = migrate.link(sorted(research_store.documents(), key=lambda r: str(r.get("received_at") or "")),
                                   work.claims, work.ideas, done, answers)
    for link in links:
        work.event("old_screen", idea=link["idea"], proposal_id=link["proposal_id"], verdict=link["verdict"],
                   cites=link["cites"], title=link["title"], duplicate_of=link["duplicate_of"], said=link["said"])
    run["links"] = int(run.get("links") or 0) + len(links)
    run["unlinked"] = unlinked


def report(work: Work, run: dict[str, Any]) -> dict[str, Any]:
    """The run's eight-item report."""
    counts = summary_step.counts(work.ideas, work.claims)
    links = [{"idea": e["idea"], "proposal_id": e.get("proposal_id"), "verdict": e.get("verdict", ""),
              "cites": e.get("cites") or [], "duplicate_of": e.get("duplicate_of") or "", "title": e.get("title") or ""}
             for e in work.synth.events(work.gen) if e.get("type") == "old_screen"]
    resorted = migrate.resort(links, run.get("unlinked") or [], work.ideas)
    return {
        "1 raw recommendations": counts["claims"] + counts["unplaced"],
        "2 distinct ideas": counts["ideas"],
        "3 converged": counts["converged"],
        "4 disagreements": counts["disagreements"],
        "5 validations of CLIVE's direction": counts["validations"],
        "6 changes to CLIVE's understanding": counts["changes"],
        "7 old parks and rejects": resorted["old_parks_and_rejects"], "7 how they re-sort": resorted["resorted"],
        "7 old proposals not linked": resorted["unlinked"],
        "8 DEC-018": resorted["dec_018"],
        "placed": counts["claims"], "unplaced": counts["unplaced"], "judgments": counts["judgments"],
        "relationships": counts["relationships"], "documents": counts["documents"],
    }


def report_lines(rep: dict[str, Any]) -> list[str]:
    """The eight-item report as the script prints it."""
    out = [f"1. Raw recommendations: {rep['1 raw recommendations']} ({rep['placed']} placed, {rep['unplaced']} couldn't be placed)",
           f"2. Distinct ideas: {rep['2 distinct ideas']}",
           f"3. Converged (two or more documents): {rep['3 converged']}",
           f"4. Disagreements: {rep['4 disagreements']}",
           f"5. Validations of CLIVE's existing direction: {rep['5 validations of CLIVE' + chr(39) + 's direction']}",
           f"6. Changes to CLIVE's understanding: {rep['6 changes to CLIVE' + chr(39) + 's understanding']}",
           "7. How the old parks and rejects re-sort:"]
    for row in rep["7 old parks and rejects"]:
        out.append(f"   - {row['was']} ({', '.join(row['cites']) or 'nothing cited'}) -> {row['idea']} {row['name']}: "
                   f"{row['judgment']}, {row['relationship']}, {row['timing']}")
    out += [f"   {name}: {n}" for name, n in rep["7 how they re-sort"].items()]
    out.append(f"   not linked to any idea: {rep['7 old proposals not linked']}")
    dec = rep["8 DEC-018"]
    out.append(f"8. DEC-018: the reason on {dec['old_proposals_citing_it']} old proposals; it holds {dec['ideas_it_holds']} "
               f"ideas now, and {dec['of_those_called_right']} of those are called the right direction.")
    finish = dec.get("on_its_finish_list") or []
    out.append(f"   not held, because CLIVE reads them as on DEC-018's own finish list: {len(finish)}")
    out += [f"   - {f['idea']} {f['name']} ({f['item'] if f['item'] != 'unnamed' else 'no item named'})" for f in finish]
    return out


# ------------------------------------------------------------------ one new document, once a generation is live


async def absorb_live(research_store, record: dict[str, Any], text: str, *, model, the_map) -> dict[str, Any]:
    """A new document into the live generation: extract, match, consolidate, judge what it touched,
    and sum up if an answer changed. The caller holds the research store's lock."""
    from app.builds import decisions
    from app.research.synthesis import answers as idea_answers

    synth = synthesis_store(research_store)
    gen = synth.live()
    if not gen:
        raise SynthesisError("No synthesis is live.")
    try:
        answered = idea_answers.keys(decisions.ledger().effective())
    except decisions.DecisionError:
        answered = {}
    calls = Calls(model)
    work = Work(synth, gen, calls, the_map, answered=answered)
    touched = await absorb(work, record, text)
    # Ideas an earlier document changed and couldn't see judged (its run stopped) are judged now too:
    # a document touched them. Ideas no document touched are never judged again here.
    touched |= {i["id"] for i in work.active()
                if judged(i) and evidence_hash(i) != (i.get("judged_with") or {}).get("evidence_hash")}
    if touched:
        await judge(work, touched)
        await summarise(work)
    digest = record.get("file_digest") or ""
    doc = work.claims.get(record["id"]) or next((c for c in work.claims.values() if digest and c.get("file_digest") == digest), {})
    return {"claims": len(doc.get("claims") or []), "unplaced": len(doc.get("unplaced") or []), "touched": sorted(touched),
            "calls": calls.made, "generation": gen}


async def keep_claims(research_store, record: dict[str, Any], text: str, *, model) -> int | None:
    """Before any generation is live, but once a synthesis exists: what a new document says is read
    and kept by its digest, so applying a generation can take it in. None when no synthesis exists yet."""
    synth = synthesis_store(research_store)
    if not synth.generations():
        return None
    found = await read_claims(synth, record, text, Calls(model))
    return len(found.get("claims") or [])
