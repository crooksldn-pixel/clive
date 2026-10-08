# ENV-REPRO-001 — the first Dev Team contract trial, run by hand

**Task:** repair BE-01 to BE-04 in the rejected Builder Environment candidate.
**Base:** `9a27bc441adad1e98e8a9ca257d1883246ee7eec` (the rejected candidate, unchanged).
**Branch:** `claude/builder-environment-repair`, published for review at
`claude/builder-environment-repair-review`.
**Run by:** a single worker through the existing bridge. **No orchestrator exists.**

`DEV_TEAM_V1_PILOT.md` (on `claude/product-memory-foundation`) proposes the Dev Team V1 record,
review and recovery contracts, and names this repair as the first thing to exercise them against.
This file is the record of that trial: which contract clauses were actually exercised, which were
only simulated, which could not be exercised at all, and what the trial found wrong with the
contract itself.

**This trial does not demonstrate that Dev Team V1 exists.** Every mechanism below was carried out
manually by one worker. What it demonstrates is whether the *clauses* survive contact with a real
rejected-then-repaired candidate — which is cheaper to learn now than after the kernel is built.

---

## 1. What each clause did when it was used

### 1.1 False-success handling — EXERCISED, and it mattered

The rejected candidate's own outbox reported a working environment. Three of the four findings
reproduce against its committed code in under a second, with no network and no missing tool:
`bootstrap` raises `TypeError` on the manifest beside it; `doctor` returns 0 with every tool
present and every version wrong; `env` executes a command substitution found in the checkout path.

**The clause holds, and the ordering inside it is the whole point.** Prose claiming success was
not evidence, and reproduction was not attempted *because* the prose was doubted — it was
attempted because reproduction is what the contract asks for regardless. A pipeline that
reproduces only when a result looks suspicious tests the reviewer's suspicion, not the candidate.

The pilot doc asks for at least one deliberate false green. It did not need to be manufactured:
`doctor` exit 0 with mismatched tooling was the real BE-02, and it is now a permanent fixture —
`test_be02_doctor_fails_closed_when_tools_are_present_but_wrong` asserts the rejection, and
`test_be02_doctor_passes_the_same_fixture_when_everything_matches` asserts that the rejection is
discriminating rather than unconditional.

### 1.2 Exact candidate identity binding — EXERCISED, with one structural limit

Every claim in the round's handoff is bound to a commit SHA and a review branch, and the base is
named so the diff is exactly attributable.

**A candidate cannot contain its own identity.** This file is inside the candidate, so it can
record its base but not its own SHA; the binding has to live in the handoff, which is written
after the commit exists. That is not a defect to fix, it is a property to design around: the
Candidate record in `DEV_TEAM_V1_PILOT.md` §2 must be created *by the collector from the committed
tree*, never assembled by the implementer inside it.

Evidence identity has the same shape, and the trial found a real gap — see §2.1.

### 1.3 Review invalidation on candidate change — EXERCISED

The suite and the environment proofs were run, then the lint gate found four findings in the new
test file, then the test file was edited. The prior run was discarded and re-run rather than
carried forward: it described a tree that no longer existed.

**The clause holds and is cheap to honour when evidence is fast.** It becomes expensive exactly
where evidence is slow — the full offline suite is eight minutes serial — which is where a
dependency-aware reuse rule will be argued for, and where it will be wrong most often. §2.2.

### 1.4 Publication retry without rebuilding — NOT EXERCISED

Publication of this candidate did not fail, so nothing was retried. **No claim is made that retry
works.** What can be said is structural: the candidate is a commit, publication is a push of that
commit to a named branch, and a retried push of an unchanged SHA is idempotent by construction. A
retry path that *rebuilds* would produce a different SHA and silently invalidate the evidence
bound to the first one, which is the failure the clause exists to prevent.

The four facts `DEV_TEAM_V1_PILOT.md` §6 asks to distinguish — process exited, candidate persisted,
evidence validated, result published — are distinguishable here only because a human is reading
them. Nothing in the bridge records them separately. §2.3.

### 1.5 Obsolete, late and duplicate results — EXERCISED as analysis, not as a run

The Mobile Experience V1 incident is the real instance and it is worth stating plainly, because it
is not the failure it first looks like.

At 2026-09-19T06:38:39Z the review recorded: the mobile inbox published at 02:18:32Z, the outbox
still acknowledging the *preceding* Builder inbox, and no mobile review branch. Four hours of Git
silence. The reviewer's disposition was to obtain watcher status and reconcile before dispatching
anything, and explicitly **not** to overwrite the inbox or launch a duplicate on the strength of
silence alone.

That disposition was correct. The work existed: `claude/mobile-experience-v1-review` is published
at `564ef3430d58b34de582f5548d7fe201c4cfe04b`. **The candidate had been built; only the outbox had
not been published.** A duplicate dispatch would have re-run completed work, and — because the
second attempt would have produced a different SHA — invalidated evidence that was already valid.

**What this proves about the contract:** an absent result is not an absent candidate, and Git
silence on one branch is not evidence about another. The delivery state must be read before the
work state is inferred, which is precisely `DEV_TEAM_V1_PILOT.md` §6's "process exited / candidate
persisted / evidence validated / result published" distinction. It survived a real incident.

**What it does not prove:** no stale token was rejected here, because there are no tokens. Fencing,
attempt IDs and idempotency keys remain entirely unimplemented and untested.

### 1.6 Reviewer gating — EXERCISED, by refusal

This worker implemented the repair. It therefore does not certify it. The handoff publishes the
candidate and the evidence and stops; acceptance is not claimed, and "Builder says green" is
exactly the claim the candidate was rejected for last time.

The pilot doc's clause that a reviewer who supplies an implementation patch does not independently
certify that patch was not tested, because no reviewer supplied one.

### 1.7 Integration re-verification — NOT APPLICABLE this round

Nothing was integrated. The candidate is published to a dedicated review branch and merged
nowhere. Semantic-conflict detection between two accepted candidates (§6.6 of the pilot doc) needs
two candidates and has none.

---

## 2. What the trial found wrong with the contract

These are gaps in the *specification*, found by using it. They are not worked around in this
candidate and none of them is fixed here.

> **§1 and §2 record the first round, 2026-09-19, and are left as written.** The task was
> continued later the same day under an owner approval that did not exist when they were written,
> so their present-tense statements about what is blocked describe that round. §4 is the
> continuation, and it says which of these gaps changed — CG-01 to CG-05 all remain open.

### 2.1 CG-01 — the evidence manifest has no defined identity

`DEV_TEAM_V1_PILOT.md` §2 requires a Candidate to carry an "evidence manifest digest", and §3 says
raw artifacts must be digest-bound and independently addressable. This round produced test
summaries, doctor transcripts and reconstruction output as **terminal text inside a handoff**.
Nothing is addressable and nothing is digested, so a reviewer must trust the transcription.

The review of `9a27bc4` raised the same thing and it is still true. Until an evidence manifest has
a defined location, format and digest, "candidate-bound evidence" means "evidence a worker said
was produced from that candidate".

### 2.2 CG-02 — invalidation has no stated granularity

"A candidate change invalidates candidate-bound reviews" is unambiguous and, taken literally,
expensive: a typo fix in a comment discards an eight-minute suite run. The doc gestures at "an
explicit dependency-aware reuse rule" without defining one, which means each worker invents one
under time pressure — and the reuse rule is exactly where a false green gets in, because reusing
evidence is indistinguishable from fabricating it unless the dependency is machine-checked.

Proposed shape, not adopted here: reuse is permitted only when the changed paths are provably
outside the evidence's input closure, and the closure is recorded with the evidence rather than
asserted afterwards.

### 2.3 CG-03 — the bridge cannot represent a candidate without a result

The Mobile V1 incident (§1.5) is this gap. The bridge has one inbox blob and one outbox blob. A
finished candidate whose outbox has not been published is indistinguishable from a worker that
never started, because the only channel that could say otherwise is the one that failed.

The Director's correct instinct — reconcile before dispatching — depended on a human choosing to
check the branch list. A kernel needs candidate persistence to be readable independently of result
delivery, or it will duplicate-dispatch exactly the work that succeeded.

### 2.4 CG-04 — BLOCKED has no defined granularity either

`DEV_TEAM_V1_PILOT.md` §3 says unavailable approved access produces BLOCKED rather than permission
to bypass a boundary. That is right, and this round hit it: full reconstruction needs an approved
package-fetch policy and does not have one.

But BLOCKED is specified as a whole-task verdict, and this task is not wholly blocked. Three of
four findings are repaired and proved; the fourth is repaired in three of its four parts with one
part blocked on an owner decision. Reporting the task as BLOCKED would hide four real repairs;
reporting it as complete would hide the blocker. The contract needs per-finding disposition with
its own state, not one verdict per task.

### 2.5 CG-05 — "prove a clean isolated reconstruction" understates what it needs

The acceptance case reads as one line of work. It is not: it needs a network egress policy, a
package-fetch allow-list, release-tag and asset-URL pins that do not currently exist in the
manifest, and a disposable host. Written as a checkbox, the pressure is to satisfy it with
something that looks like a reconstruction — a unit test, or a rerun on the machine that already
has the environment.

`DEV_TEAM_V1_PILOT.md` §4 already says network rebuild evidence is a separate class from offline
unit tests and that unit tests cannot prove a server can be recreated. That sentence is the load
-bearing one and it should be attached to the acceptance case, not held two sections away.

---

## 3. Standing

Nothing in this file is a decision. The contract gaps belong in
`DEV_TEAM_V1_PILOT.md` on `claude/product-memory-foundation`, which is the canonical product
memory and is deliberately not edited from here — a repair candidate forking canonical memory
would create two versions of the record that says which version is canonical.

The exact proposed edits are carried in this round's handoff for the Director to apply or reject.

---

## 4. Continuation, 2026-09-19 — what the second round of this same task exercised

The owner approved bounded read-only package fetching, and the remaining BE-04 work was carried
out under it: release tags and asset URLs pinned, step 4 made executable with integrity gates, the
plan executed twice from a disposable checkout, and the SkillSpector provenance gap closed.

This section exists because a continuation is not a new trial, and reporting it as one would
double-count the same clauses. Below is only what *this* round actually put through the contract.

### 4.1 Clause dispositions for the continuation

| Clause | This round | What happened |
|---|---|---|
| **False-success handling** | **EXERCISED** | The previous round's own carefully hedged claim — "these digests are observed, not upstream-attested" — was checked rather than accepted. All eight assets were fetched from their pinned upstreams and all nine extracted digests compared with the committed file. Had one differed, the environment's identity record would have been wrong. The habit is the point: the hedge was honest *and* it was still verified. |
| **False-success handling, second instance** | **EXERCISED** | Making the SkillSpector pin verifiable caused the **builder's own environment to fail its own `doctor`**, because the builder's SkillSpector was installed the old way. That result was reported, not softened, and not worked around by leaving the check advisory. A check that cannot fail the machine that wrote it is not a check. |
| **Exact candidate identity binding** | **EXERCISED**, same structural limit | The candidate changed, so it has a new SHA and this file still cannot contain it. §1.2 is unchanged and the collector-builds-the-record consequence stands. |
| **Review invalidation on candidate change** | **EXERCISED, and this time it was the instruction** | The dispatching inbox stated that prior candidate-bound review evidence is invalid for the changed tree and required the gates to be re-run against the exact final candidate. That is CG-02's question asked in the sharpest possible form — and it was answered by re-running rather than by arguing about closure, because the tree changed under `scripts/`, `tests/` and `docs/dev-environment/`, which is the input closure of every environment proof this candidate makes. |
| **Publication retry without rebuilding** | **NOT EXERCISED** | Publication was not retried and no claim is made that retry works. §1.4 stands unchanged. |
| **Obsolete / late / duplicate results, fencing** | **NOT EXERCISED** | No stale result arrived, no attempt was fenced, no duplicate was dispatched. There are still no tokens, attempt IDs or idempotency keys. §1.5's analysis of the Mobile V1 incident is not re-exercised by this round and is not re-counted. |
| **Reviewer gating** | **EXERCISED, by refusal, again** | This worker implemented the continuation and does not certify it. |
| **Integration re-verification** | **NOT APPLICABLE** | Nothing was integrated, merged or deployed. |

### 4.2 What the continuation did to the contract gaps

**CG-01 (evidence identity) — unchanged and now larger.** This round's central evidence is an
end-to-end reconstruction: a ~2.9 GB tree, 89 `.deb`s, eight release assets, two `doctor`
transcripts. All of it is still terminal text inside a handoff. Nothing is addressable, nothing is
digested, and the reviewer is asked to trust a transcription of a run that takes ten minutes to
repeat. The gap did not change; the cost of it did.

**CG-02 (invalidation granularity) — unchanged, and see §4.1.** The literal rule was applied and
was correct here. That is not evidence that the literal rule is right in general; it is evidence
that it is right when the change lands inside the evidence's input closure, which is the
distinction the contract still does not make.

**CG-03 (a candidate without a result) — unchanged.** Untouched by this round.

**CG-04 (BLOCKED granularity) — unchanged, and this round is the other half of the argument.**
Last round BE-04 was partial: three parts repaired, one blocked. This round completed it. The
contract has no state for "partially repaired, continued under a later approval", so the only way
to describe the two rounds together is prose. Per-finding disposition with its own state is still
the fix.

**CG-05 ("prove a clean isolated reconstruction") — satisfied for this environment; the
specification defect is unchanged.** The reconstruction was performed, twice, from a checkout with
no `.tooling/` and no `.venv/`. That is an instance, not a repair of the clause: the acceptance
case still reads as one checkbox while requiring an egress policy, a fetch allow-list, pinned
release assets and a disposable host, and a later worker reading the checkbox alone will still be
tempted to satisfy it with a rerun on a machine that already has the environment.

### 4.3 CG-06 — an approval expressed only as prose cannot be enforced

New, and found by this round.

The owner's approval arrived as a paragraph: read-only, declared dependencies only, authoritative
upstreams only, integrity enforced, fail closed. Every one of those is checkable, and as prose
none of them was checked by anything — the boundary would have been held by whoever remembered
reading it, which for an automated worker is nobody.

So the boundary was compiled instead. `fetch_spec()` requires each asset URL to be exactly
`<upstream>/releases/download/<release_tag>/<asset>` built from that tool's own manifest entry,
and refuses to emit a fetch step otherwise; the download gate runs before extraction and the
install gate after; `test_be04_an_asset_url_outside_the_tools_own_upstream_is_refused` covers a
mirror, another project, another tag, another asset and a non-release path.

**The contract gap is that nothing asked for this.** An approval is currently a fact about a
conversation. It should be a fact about the candidate: the granted boundary should be recorded in
a form the candidate can be checked against, so a reviewer can ask "does this tree stay inside
what was approved?" and get an answer from the tree rather than from the worker's account of it.
