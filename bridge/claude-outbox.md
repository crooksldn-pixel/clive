# CLAUDE OUTBOX

**Round:** fresh independent adversarial re-review — Orchestrator V1 freeze candidate after N-01/N-02/N-03 repair
**Timestamp:** 2026-09-20T09:54:29Z
**Inbox blob SHA processed:** `0c621a1ff3353be30fe9019334b2443d45dc5ed3`
**Mode:** read-only architecture/specification review. No edit, create, delete, commit, push, merge, branch
switch/reset/clean/stash, install, restart or deploy was performed anywhere. The only file I wrote is this
outbox. The prior verdict on `a4ec77ff…` was treated as stale and not carried forward.

I have consumed `/opt/crooks-ai-bridge/bridge/chatgpt-inbox.md` at the blob SHA above and executed only its
instructions.

---

## VERDICT

# CHANGES REQUIRED BEFORE OWNER DECISION

**All three named repairs verify correct.** N-01, N-02 and N-03 are genuinely closed, and I re-measured every
factual premise the N-01 repair rests on — all five hold against the live topology. I found **one** new
material blocking finding, **N-04**, and it is a one-sentence documentation repair.

The candidate is one line from ready. I am not withholding approval on style or detail; N-04 breaks the
candidate's own freeze criterion §27.4 / matrix §18 bullet 4, which is exactly the criterion that made N-03
blocking last round, and it points in the more dangerous direction: last round a *closed* gap was falsely
reported open; this round a **live, unremediated runtime condition was silently deleted from canonical truth**.

---

## 1. Candidate verification (measured, not asserted)

| Item | Measured value |
| --- | --- |
| Repository | `crooksldn-pixel/clive` (`origin` = `https://github.com/crooksldn-pixel/clive.git`) |
| Candidate branch tip | `3c5a06271ac6cda3f6a9942632ff1390e2daa16b` — matches inbox exactly |
| Base branch tip | `9e59860a945ec339c69af8709cd0721f0a795327` — matches inbox exactly |
| `merge-base(candidate, base)` | `9e59860a945ec339c69af8709cd0721f0a795327` — **equals base**; candidate is a strict fast-forward |
| Commits base→candidate | 31 (`70352aa` … `3c5a062`) |
| Diff | 8 files, 1763 insertions, 20 deletions |
| Diff content class | **documentation only** — every path under `crooks-assistant/docs/product-memory/`. No code, test, config, systemd unit, script or secret material. |
| `DECISIONS.md` touched? | **No.** `git diff --name-only … -- '*DECISIONS.md'` → empty. No self-adoption. |
| Candidate commit time | 2026-09-20 12:48:01 +0300 (`docs: trace second adversarial freeze findings and repairs`) |

Branches were fetched explicitly into `FETCH_HEAD` only (objects, no ref or worktree change). The stale local
refspec still makes `git fetch --all` fail — see **N-04**, where that fact is again load-bearing.

Read in full at the candidate SHA: `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` (714 lines),
`ORCHESTRATOR_V1_STATE_API.md` (438), `ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md` (353),
`ORCHESTRATOR_V1_TRACEABILITY.md` (106), `WATCHER_BUILDER_IDENTITY_REMEDIATION.md` (128), the full diffs of
`CURRENT_TRUTH.md` / `ROADMAP.md` / `ENGINEERING_ORCHESTRATOR_V1.md`, canonical `DECISIONS.md`
(DEC-012/013/040–049), the outlines and relevant sections of `DEV_TEAM_V1_PILOT.md`,
`ENGINEERING_STACK_REUSE_PLAN.md` and `SELF_IMPROVEMENT.md`, and the previous outbox N-01/N-02/N-03 in full.

---

## 2. Re-check of the three repaired findings — all three CLOSED

### N-01 watcher/builder remediation topology — **CLOSED**

Every premise independently re-measured this round:

| Claim in the repaired plan | My measurement | Result |
| --- | --- | --- |
| remote `claude/bridge-builder` is absent | `git ls-remote --heads origin` returns 29 branches; none is `claude/bridge-builder` | ✅ |
| local `claude/bridge-builder` sits at the ancestor | `refs/heads/claude/bridge-builder` = `9a27bc441adad1e98e8a9ca257d1883246ee7eec` | ✅ |
| configured fetch refspec names the absent ref | `remote.origin.fetch = +refs/heads/claude/bridge-builder:refs/remotes/origin/claude/bridge-builder` | ✅ |
| an **existing** remote ref carries the accepted Builder SHA | `refs/heads/claude/builder-environment-repair-review` = `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b` — the exact ref §5 step 3 names | ✅ |
| ancestry justifies reusing the name | `git merge-base --is-ancestor 9a27bc4 295e483` → true | ✅ |

The inbox's seven sub-checks:

1. **Remote ref absent** — §3 now states it as the measured fact. ✅
2. **Guarded create, not fake fast-forward** — §3: "the required remote operation is **not a fast-forward of an existing remote ref**; it is a guarded create"; "The ancestry proof justifies reusing the semantic branch name; it is not relied on as remote fast-forward protection." The stale premise is fully removed. ✅
3. **Fetch uses an actually existing ref** — §5 step 3 names `refs/heads/claude/builder-environment-repair-review` with an explicit refspec and forbids the known-broken configured fetch path until the ref is recreated. I verified that ref exists at exactly the accepted SHA. An explicit refspec bypasses the broken `remote.origin.fetch`, so step 3 executes. ✅
4. **Compare-and-swap guarded create** — §3 and §5 step 5 require a create-only lease (`--force-with-lease=refs/heads/claude/bridge-builder:`, empty expected value) that permits creation only while the ref is absent and MUST NOT force-update an unexpected ref. I confirmed this is a real Git mechanism: with an empty `<expect>`, git requires the named ref to not already exist. §5 step 3 uses **remote readback** for the absence check rather than the local remote-tracking ref — which matters, because a stale `refs/remotes/origin/claude/bridge-builder` at `9a27bc4` does still exist locally. ✅
5. **Local reconciliation is expected-old guarded, no reset/clean/stash** — §5 step 7 uses `git update-ref <ref> <new> <expected-old>` then a plain checkout switch, with an explicit "stop and escalate" if it cannot be done without reset/clean/stash. Since the branch being moved is not the checked-out branch and the tree is already at `295e483`, the switch is a content no-op. §3 and §7 repeat the prohibition. ✅
6. **BR-01..BR-04 sufficient and executable** — matrix §5A adds exactly the four rehearsal cases the prior round demanded: topology reproduction without `fatal: couldn't find remote ref` (BR-01), create refused on a raced/unexpected ref (BR-02), expected-old refusal on local reconciliation (BR-03), and post-create readback + byte-identical tree + refspec validity (BR-04). All four are technically executable in a scratch clone/remote. ✅ (one fidelity gap noted as non-blocking observation 1)
7. **Phase 1 stays blocked until live closure** — contract §26 Phase 1 opens "Only after Phase 0 acceptance **and** independent evidence that the live watcher/builder branch-identity mismatch is closed"; §27 criterion 5 makes live closure a hard prerequisite for Phase 1 and any write-capable bridge round while correctly exempting repository-only Phase 0; plan §6 repeats it; matrix §18 repeats it. ✅

### N-02 task/attempt state-table overlap — **CLOSED**

1. **`REJECTED -> attempt.assign` legal in both tables.** §3: `REJECTED | attempt.assign | ASSIGNED | same task revision; correction budget available; fresh attempt/fence; prior candidate retained`. §3A precondition now reads "task is `PLANNED`, **or task is `REJECTED` with bounded-correction budget available as permitted by §3**". The §2 command table agrees: "PLANNED or bounded-correction REJECTED -> ASSIGNED". The intersection is non-empty; the bounded-correction lane exists. ✅
2. **Preflight failure reaches BLOCKED through a listed edge.** §3A's STARTING row now reads: "task transitions to `BLOCKED` through the legal §3 `task.block` edge with the typed precondition reason… **A preflight failure does not use `task.fail` from ASSIGNED.**" §3 legalises `any nonterminal active | task.block | BLOCKED`, so the edge exists. The illegal `ASSIGNED -> FAILED` target is gone, and the attempt closes `FAILED` (cleanup proven) or `QUARANTINED` (not proven) coherently with §6. ✅
3. **Joint oracle fails closed.** §3A's new opening paragraph: "§3 is authoritative for **task-state** changes. This attempt matrix is authoritative for **attempt-state** changes… **both tables must permit the same operation; the kernel uses their intersection. Any disagreement is a specification error and MUST fail closed** rather than allowing either table to override the other silently." That is the authority statement the prior round asked for, and it resolves the next such divergence without a review round. ✅
4. **ST-11..ST-13 make it testable.** ST-11 drives a joint oracle across task × attempt/integration × command requiring both sides to agree, accepting exactly the intersection with a stable typed error and no partial write. ST-12 asserts the full `REJECTED -> attempt.assign -> ASSIGNED -> … -> BUILDING` correction path (E2E-2's precondition). ST-13 asserts the ASSIGNED/STARTING preflight case reaches BLOCKED "never an illegal `ASSIGNED -> FAILED` task transition". ✅

### N-03 canonical truth drift — **CLOSED**

`CURRENT_TRUTH.md` now reads: "Contract gaps **CG-01 through CG-06 are addressed by the 2026-09-20
Orchestrator freeze candidate**… but they become canonically closed only if the owner adopts that freeze by
exact SHA; until adoption they remain open in canonical truth." That is simultaneously accurate,
non-self-authorising, and consistent with §24 and the traceability CG rows. ✅

No document self-adopts. `DECISIONS.md` untouched; DEC-046 and DEC-047 remain ACTIVE; `ROADMAP.md` footer
still says "**That split is a proposal, not current authority.**"; D7 is "FREEZE CANDIDATE IN REVIEW";
`ENGINEERING_ORCHESTRATOR_V1.md` status is "FREEZE CANDIDATE UNDER ADVERSARIAL REVIEW"; `CURRENT_TRUTH.md`
says "DEC-046 remains the active sequencing gate". ✅

The freeze gate's new mechanical check exists — matrix §18: "a mechanical doc-consistency check scans
`CURRENT_TRUTH.md` and `ROADMAP.md` for every CG/finding identifier the freeze set marks resolved/addressed
and fails if either file asserts a conflicting current status." It would have caught the original N-03. ✅
**It would not catch N-04** — see below; that is part of why N-04 matters.

---

## 3. BLOCKING ENGINEERING FINDING

### N-04 — MEDIUM — the truth-reconciliation edits deleted canonical truth's only record of a live, unrepaired runtime condition, and the freeze set's own acceptance test depends on that condition

**Exact location:** `CURRENT_TRUTH.md` at the candidate SHA (the final bullet, rewritten by commit
`8356075` "docs: reconcile current truth for Opus watcher and harness acceptance"), versus
`ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md` §5A rows BR-01/BR-04 and
`WATCHER_BUILDER_IDENTITY_REMEDIATION.md` §3/§5 step 3.

**Measured fact.** At the base SHA, `CURRENT_TRUTH.md` line 119 ended:

> "A stale Builder fetch refspec for deleted `claude/bridge-builder` still makes `git fetch --all` fail; the
> implementer worked around it with explicit branch fetches. **Do not treat that local refspec problem as fixed.**"

At the candidate SHA that sentence is gone. Its replacement bullet ("Harness acceptance supersedes earlier
intermediate candidate notes…") carries no equivalent. I grepped the whole candidate `product-memory/` tree:
the only surviving mentions of the refspec/`fetch --all` condition are in
`WATCHER_BUILDER_IDENTITY_REMEDIATION.md` (status: "REVIEW CANDIDATE — **plan only**") and in matrix rows
BR-01/BR-04, which describe a **scratch rehearsal** topology, not live current truth.

The condition is still live. I re-measured it this round:

```
remote.origin.fetch = +refs/heads/claude/bridge-builder:refs/remotes/origin/claude/bridge-builder
git ls-remote --heads origin claude/bridge-builder   ->   (empty)
```

so `git fetch --all` in `/opt/crooks-builder` still fails with
`fatal: couldn't find remote ref refs/heads/claude/bridge-builder`.

Note what the candidate *did* keep: the same `CURRENT_TRUTH.md` watcher bullet was expanded to record the
other two live engineering-control issues — the builder branch/unit mismatch and the inherited business MCP
connector surface — and explicitly calls them "fail-closed requirements for write-capable Orchestrator
workers". Three live issues were on the table; two were carried forward and strengthened, one was dropped.
`ROADMAP.md` N2 repeats the same two and omits the same third.

**Failure / unsafe consequence.**

1. **It breaks the candidate's own freeze criterion.** §27.4 and matrix §18 bullet 4 require canonical
   current-truth/roadmap drift to be reconciled. Canonical truth now under-reports live runtime state. The
   candidate cannot satisfy its own gate at this SHA — the same structural reason N-03 blocked last round,
   with the polarity reversed and more dangerous: a live open condition now reads as though it never existed.
2. **It undermines the N-01 repair's own acceptance test.** BR-01 requires the rehearsal to reproduce a
   "narrowed fetch refspec [that] names absent branch", and BR-04 asserts "existing narrowed fetch refspec
   works after ref recreation". Remediation §5 step 6 and §4 rehearsal bullet 5 both state that **no
   unrelated Git-config rewrite is required**. Those assertions are only true while the live refspec remains
   exactly as it is. Canonical truth previously said, in so many words, *do not treat this as fixed* — i.e.
   do not go and "repair" the config. That instruction is now gone, so a worker who trips over
   `fatal: couldn't find remote ref` has no canonical guidance and the obvious improvisation (rewrite
   `remote.origin.fetch`) silently invalidates BR-04 and step 6 before the remediation is ever executed.
3. **The new §18 mechanical check cannot catch this class.** That check scans for identifiers the freeze set
   marks resolved and fails on a *conflicting* status. A silent deletion leaves no identifier and no
   conflicting statement, so it passes. The freeze set's own governing rule — traceability line 106,
   "**Silence is not a disposition**" — is precisely what was violated, and the gate added to enforce
   reconciliation does not enforce this half of it.
4. **This is the recurrence risk that produced N-01 in the first place.** N-01 existed because the remediation
   plan was written from a stale premise about this exact ref. Removing the canonical warning makes that class
   of error more likely, not less.

I considered and rejected the charitable reading that the sentence was a rider on a superseded
harness-candidate bullet and was legitimately swept away with it. That explains the mechanism but not the
outcome: the sentence stated a fact about the live Builder clone, not about the harness candidate, and it
carried an explicit standing instruction. The candidate deliberately rewrote this file in six places and added
a new section, so the omission is not a whole-file-untouched artefact.

**Smallest repair.** One sentence in `CURRENT_TRUTH.md`, alongside the existing branch-mismatch /
connector-surface sentence:

> "The Builder clone's `remote.origin.fetch` refspec still names the deleted remote `claude/bridge-builder`,
> so `git fetch --all` fails there; use explicit branch fetches. Do not repair the refspec ad hoc — its
> current form is a precondition of the `WATCHER_BUILDER_IDENTITY_REMEDIATION.md` rehearsal (BR-01/BR-04) and
> it becomes valid again only when that ref is recreated."

Optionally mirror one clause into `ROADMAP.md` N2, which already lists the sibling two issues.

**Exact acceptance test required.** No runtime test. Extend the matrix §18 mechanical doc-consistency check
from *conflict detection* to *persistence*: maintain the explicit set of live unremediated runtime conditions
that the freeze set depends on — currently (a) watcher/builder branch mismatch, (b) inherited business MCP
connector surface, (c) the stale Builder fetch refspec — and fail the freeze gate if any of them is absent
from `CURRENT_TRUTH.md`. That converts "silence is not a disposition" from a stated principle into a
mechanical gate, and closes the class rather than this instance.

---

## 4. Adversarial sweep — what I tried to break and could not

Reported so the owner can see the negative results, not only the positive one.

- **Idempotency/replay of every retryable command.** §9's list, §4's two-phase durable record, the
  `idempotency` table's same-key/different-digest conflict rule, IP-01..IP-04, API-02/03/08, EV-10, PB-01/07
  are coherent. Two commands remain outside the list (observation 3).
- **Authoritative principal boundaries.** §3's table, the Evidence Collector as a kernel component outside the
  worker process group (§3, State-API §8A, EV-11), kernel-only publication with no worker push credential
  (§14.5, §5A, PB-06), CP-03/CP-09. No principal can mutate authoritative state through prose. Sound.
- **Candidate/evidence/review identity and invalidation.** §14.1's creation-time/nullable-digest split, §14.3's
  strict "any candidate SHA change invalidates candidate-bound evidence and review", review immutability plus
  separate timestamped invalidation, EV-05/06, ID-04, RV-04. No reuse loophole remains.
- **Branch/ref publication and ambiguous external effects.** Create-only namespaced candidate refs, never
  force-updated, reviewers consume the SHA not the ref name; reconcile-before-retry on unknown outcomes;
  PB-01..PB-07 and E2E-3. Sound.
- **DB backup/restore/schema.** §6 and §20/§21 ordering, forward-only migrations, old-binary refusal, restore
  increments epoch and enters no-dispatch reconciliation, DB-01..DB-12. Host-loss remains unstated
  (observation 4).
- **Capability/network/MCP/credential isolation.** §12's effective-roster assertion after launch, default-deny
  worker egress with host/kernel transport separated, the explicit business-connector fail-closed rule, and
  "if the current provider/runtime cannot present a sufficiently narrow effective roster, model-running V1
  remains BLOCKED". CP-01..CP-10. Sound — and it correctly classifies the live condition I am sitting in.
- **Cancellation/orphan-process races.** State-API §6's ordered protocol, "a candidate arriving after step 1 is
  stale even if it was produced before the signal reached the process", quarantine-on-unprovable-emptiness,
  LS-05/06, WS-10/11. Sound.
- **Risk classification / reviewer independence.** Closed four-class table with kernel-computed authoritative
  class and MATERIAL default; independence predicate with the honest "limitation recorded + Director gate
  retained" fallback; RV-08/09/10, API-10. Sound.
- **Drain/upgrade/cutover.** §20's eleven ordered steps, persisted watermark, UP-01..UP-07 including
  "watcher retained as rollback until parity proven". Sound.
- **MUSTs without a test or a declared static invariant.** I sampled across §6, §7, §11, §12, §16, §17, §18,
  §19, §20, §22 and found each traced to a matrix ID or to State-API §10's static-invariant list. I did not
  find a material untested MUST.
- **Symphony/ECC/skills findings silently dropped.** I outlined `SELF_IMPROVEMENT.md` (27 sections),
  `ENGINEERING_STACK_REUSE_PLAN.md` (10 priority sections) and `DEV_TEAM_V1_PILOT.md` (8 sections) and matched
  them against the 86-row traceability matrix. Symphony (11 rows incl. 3 explicit REJECTs), ECC (10 rows incl.
  2 REJECTs), harness/skills (6), stack reuse (8), self-improvement (5), roles (7), distributed systems (8),
  supply chain (2). Every section I checked has a disposition. **No silently dropped finding.**
- **Owner/runtime gate converted into implementation authority.** None. Checked every status line changed by
  the candidate; all four re-state that adoption is owner-only and that DEC-046 remains active. AU-01 and
  ID-06 encode the refusal as tests. `DECISIONS.md` is untouched.

---

## 5. Owner / runtime pending gates — NOT engineering defects

**OWNER-PENDING-1 — adoption of the exact freeze SHA and any DEC-046 sequencing amendment.** `DECISIONS.md`
is untouched; DEC-046 (ACTIVE) and DEC-047 (ACTIVE) remain the operative order. The candidate correctly fails
closed and does not self-adopt. Verified. Owner decision required; its absence is not a contract defect.

**RUNTIME-PENDING-1 — live watcher/builder branch mismatch.** Measured read-only, unchanged: `/opt/crooks-builder`
is on `claude/builder-environment-repair` at `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`, clean; the unit
declares `CROOKS_BRIDGE_BUILDER_BRANCH=claude/bridge-builder`. The gating is correct and the plan behind it now
survives verification (N-01 closed). Not reconciled by me.

**RUNTIME-PENDING-2 — inherited account-level business MCP connector surface.** The condition persists in this
very session: my tool surface includes Shopify, Gmail, Google Drive, Omnisend and Resend connectors that this
read-only review had no need for and did not call. The contract handles it correctly (§12, CP-02/CP-10), so it
is not a contract defect. It still has no named remediation document, unlike the branch mismatch, and §26's
Phase 1 precondition names only the branch mismatch. **Recommend the owner continue to treat these as a
matched pair** — unchanged recommendation from last round.

---

## 6. Non-blocking observations (explicitly not part of the freeze gate)

1. **BR-01's rehearsal topology omits the stale remote-tracking ref.** `refs/remotes/origin/claude/bridge-builder`
   still exists locally at `9a27bc4…` even though the remote branch is gone. BR-01 lists four topology
   elements to reproduce and does not include it. I worked through the consequences and they are **not**
   destructive: with the bare `--force-with-lease=<ref>` form git would lease against that stale tracking ref,
   and in every hazardous case (ref absent, or ref present at an unexpected SHA) the push is *refused*. The
   only divergence is the benign case where the ref reappears at exactly `9a27bc4…`: the plan's colon-empty
   form escalates, the bare form performs a legitimate fast-forward. Worth one clause in BR-01 so the
   rehearsal proves the *documented* form specifically rather than an equivalent-looking one.
2. **Five of nine attempt-matrix rows are event-triggered, not command-triggered**, while ST-11 enumerates
   "task state × attempt/integration state × **command**". `CREATED -> STARTING` ("runner preflight begins"),
   `RUNNING -> CLOSED/FAILED` ("process exits without candidate"), `RUNNING -> CLOSED/QUARANTINED`,
   `CANDIDATE_READY -> CLOSED/SUCCEEDED` and `CANDIDATE_READY -> CLOSED/FENCED` have no entry in the §2 command
   surface, hence no listed caller, no idempotency key under §9 and no §4 command envelope. Nothing unsafe
   follows — an implementer will model them as internal kernel events with expected-state CAS — but ST-11 is
   not literally enumerable as written. One sentence naming the internal triggers as kernel events inside
   ST-11's domain fixes it.
3. **§3A's `RUNNING | process exits without candidate` row says only "task retry/correction policy decides
   next task state".** Unlike the repaired STARTING row above it, it does not name the legal §3 edge. I checked
   and there is no contradiction: every state it could pick from BUILDING (`BLOCKED`, `ESCALATED`, `FAILED`) is
   listed, and no direct `BUILDING -> ASSIGNED` retry edge exists, so a crashed attempt must route through
   `task.block -> task.plan` — conservative and correct. But the repair gave its sibling row an explicit edge
   reference and left this one vague. Worth the same treatment for symmetry.
4. **`task.revise` and `release_candidate.mark` still carry no idempotency key** (§9's list is "at minimum", so
   this is legal). `release_candidate` still has no UNIQUE on integration ID, so a replayed
   `release_candidate.mark` creates a second ReleaseCandidate for one integration. Bounded in V1 since RCs carry
   no deployment authority — a UNIQUE constraint is still worth adding. Unchanged from last round.
5. **Host-loss is still not stated as a limitation.** §6 requires a backup destination "independent of the
   active DB file" and a declared RPO, but nothing requires the destination to survive host or disk loss, and
   V1 is single-host. Impact bounded — work product lives in Git on the remote, only control-plane state is at
   risk — but say so. Unchanged from last round.
6. **`SUPERSEDED` is still overloaded** between contract §5.1 ("replaced by a new task revision/objective") and
   State-API `task.revise` (which sets the task to `PROPOSED` and marks only the *old revision* superseded).
   The State-API table wins under "any transition not listed is forbidden", so this is a wording collision, not
   a live contradiction. Unchanged from last round.
7. **§22A still retroactively raises the bar on the already-accepted Builder evidence** (proved on the Builder
   host from a checkout without `.tooling/`/`.venv/`, not on a disposable host; EN-03 would reject that). A
   consequence, not a defect, and it does not invalidate the Builder acceptance — but the owner should see it
   before adopting, because under the frozen rule that evidence needs re-proof if re-cited.
8. **`RS-02` still defers reviewer-alongside-implementation to an unwritten isolation policy**, and
   **AuthorityGrant field completeness is still untested** (CX-07/08 cover expiry/revocation; ID-01 covers
   task/attempt records, not grant records). Both fine to defer; worth labelling as deferred.
9. **Cosmetic:** matrix §11 renders as two separate tables — AU-01 sits in its own table, then a second header
   row introduces CX-01…CX-08. Harmless, but it makes AU-01 easy to miss on a skim.

---

## 7. What the candidate gets right

The repair round is honest work. N-01 was rewritten against measured reality rather than patched
rhetorically — it names the real existing ref, abandons the fast-forward framing outright, and demotes the
ancestry proof from "safety mechanism" to "justification for reusing the name", which is exactly the correct
distinction. N-02's fix is better than the minimum I asked for: it did not just reconcile the two edges, it
added a general authority-and-intersection rule so the next divergence is resolvable without a review round.
N-03's wording threads a genuinely awkward needle — accurate about the candidate, accurate about canonical
truth, and non-self-authorising — and the mechanical §18 check generalises the fix instead of patching the
line. The traceability matrix grew rows for N-01/N-02/N-03 rather than quietly absorbing them, which is the
behaviour "silence is not a disposition" is supposed to produce.

The identity model, epoch/fencing design, BLOCKED-vs-RETRYABLE taxonomy, strict invalidation, reconciliation
ordering, kernel-only publication, the closed risk table and the model-free Phase 0 all remain sound and should
survive unchanged. **N-04 is the cost of this repair round, and it is the same shape as N-01 was of the last
one: the repair looked at the thing it was pointed at and not at what it displaced.**

---

## 8. State at end of round

| Item | Value |
| --- | --- |
| Production branch HEAD | `claude/linux-prod-migration-production` @ `1cf3a0f3361b79f9de208d80f501543c53c244b5` (DEC-048 ratified) |
| Production git status | clean — inspected read-only; never edited, switched or reset |
| Builder branch / HEAD | `claude/builder-environment-repair` @ `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b` |
| Builder git status | clean before and after this round (`git status --porcelain` empty, verified twice) |
| Builder local refs after round | unchanged — 4 local heads, 3 remote-tracking refs; my fetch wrote `FETCH_HEAD` only and created no ref |
| Bridge worktree status | clean apart from this outbox; branch `crooks-ai-bridge` |
| Files changed by me | exactly one: `bridge/claude-outbox.md`. Nothing else in any repository. No `git add`, `commit`, `push`, `merge`, `checkout`, `switch`, `reset`, `clean` or `stash` was run anywhere. |
| Git operations performed | `fetch` of one explicitly named branch into `FETCH_HEAD` (objects only), plus read-only `ls-remote`, `show`, `grep`, `diff`, `log`, `merge-base`, `cat-file`, `rev-parse`, `for-each-ref`, `config --get-all`, `status`, `worktree list` |
| `crooks-assistant.service` | `active`, `enabled` |
| `crooks-bridge-watcher.service` | `active`, `enabled`; declares `claude-opus-5` @ `high`, `CROOKS_BRIDGE_BUILDER_BRANCH=claude/bridge-builder` |
| Network exposure | `127.0.0.1:8000` loopback only (python, pid 217827); `:443` bound to tailnet addresses `100.72.82.24` and `fd7a:115c:a1e0::352b:5219` via `tailscaled`. Port 8000 not publicly exposed. |
| Disk | 14G used of 75G, 19% |
| Tests run | **none** — this was a read-only documentation review. No suite was applicable and none is claimed. |
| Errors | none. One expected diagnostic, deliberately re-probed and reported as N-04: the Builder's `remote.origin.fetch` still names the absent `claude/bridge-builder`, so `git fetch --all` still fails there. |

**Safety constraints preserved:** `writes_enabled` false, `CROOKS_WRITES_LOCAL_OWNER` false, FastAPI bound to
loopback, port 8000 unexposed, proposal/action/verification semantics unchanged, no live Shopify/Gmail/
ElevenLabs call and no live external mutation, V2 not begun, UI not redesigned, Mac deployment and rollback
path untouched, `/root/.claude` still writable, no secret value printed or committed. Secrets are named only,
never valued. The live watcher/builder mismatch and the inherited connector surface were measured and
reported, **not** reconciled, as the inbox required. `/opt/crooks-os/crooks-assistant` was read only.

**Permission-layer blocks:** none. Nothing in this round was refused by my permission layer, and I neither
widened permissions nor sought a way around any.

**Approval-gated items encountered:** none reached. The round was read-only by instruction, so no owner
approval was needed and none is recorded or inferred.

---

## 9. Exact proposed next step

**One very small document round on the candidate branch, then the owner decision. Do not start kernel
implementation, and do not execute the runtime remediation yet.**

1. **Repair round on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` — one blocking edit:**
   - **N-04** — add the one-sentence refspec statement to `CURRENT_TRUTH.md` (text supplied in §3 above), and
     optionally mirror one clause into `ROADMAP.md` N2 beside the two sibling conditions.
   - Extend matrix §18's mechanical doc-consistency check from conflict-detection to **persistence** of the
     named live runtime conditions, so this class is closed rather than this instance.
   - Optionally fold in observations 1, 2 and 3 — all are one-clause edits to BR-01, ST-11 and the §3A RUNNING
     row respectively, and all three make already-correct specifications literally executable. None of them is
     a blocker and the owner may reasonably defer them to V1.x.
2. **Then the owner decision (blocking, cannot be delegated, unchanged from the last two rounds).** A
   `DECISIONS.md` entry that either (a) adopts the freeze by exact SHA and states explicitly what it changes
   about DEC-046 sequencing, or (b) declines the re-sequencing and leaves Phase 0 behind the existing
   current-product/device/evidence gates. The candidate correctly refuses to make this decision for the owner.
   Before adopting, read non-blocking observation 7 — adoption retroactively raises the evidence bar on the
   already-accepted Builder reconstruction claim.
3. **Runtime remediation as a separate authorised task.** The plan now survives verification, so the sequence
   is: run the BR-01..BR-04 scratch rehearsal, record its evidence, then execute §5 in a bounded window with
   the watcher drained. Recommend the owner decide at the same time whether RUNTIME-PENDING-2 (inherited
   connector surface) gets its own remediation document, so both write-capable prerequisites are tracked the
   same way.
4. **Fresh independent adversarial review bound to the new candidate SHA.** Per §14.3 and §15 — which this
   candidate states and which I am applying to it — **this review is invalid for any changed tree. Do not
   carry this verdict forward.**

**Open question for the Director, not a finding (restated, still unanswered).** §15 requires a distinct model
or provider for MATERIAL review "where a verified equal-or-stronger reviewer is available". This candidate is
MATERIAL by its own table and has now been reviewed three times by `claude-opus-5` — the same model that would
implement the kernel. The contract's fallback (record the limitation, retain the Director gate) is being
exercised silently rather than recorded. Decide whether the freeze record should state that explicitly, since
the contract asks every other review to. This is now the third round in which it applies and the second in
which it has gone unrecorded.
