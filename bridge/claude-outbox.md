# CLAUDE OUTBOX

**Round:** fresh independent adversarial re-review — Orchestrator V1 freeze candidate
**Timestamp:** 2026-09-20T09:26:16Z
**Inbox blob SHA processed:** `0f4004639f41620fcea488a1e3e0dafd76e38443`
**Mode:** read-only architecture/specification review. No edit, commit, push, merge, branch switch,
install, restart or deploy was performed anywhere. The only file I wrote is this outbox.

---

## VERDICT

# CHANGES REQUIRED BEFORE OWNER DECISION

Three material blocking engineering findings (N-01, N-02, N-03 below). All three are document
edits. **F-01 through F-12 from the previous review are now CLOSED, OWNER-PENDING or
RUNTIME-PENDING — none remain open as engineering defects.** The candidate has materially and
genuinely improved; the blockers below are new, and two of them were introduced or left behind by
the repairs themselves.

I did not approve on detail. I tried to break the contract and these are what broke.

---

## 1. Candidate verification (measured, not asserted)

| Item | Measured value |
| --- | --- |
| Repository | `crooksldn-pixel/clive` (`origin` = `https://github.com/crooksldn-pixel/clive.git`) |
| Candidate branch tip | `a4ec77ff953bd7af5117e5adb5756adddd942fdb` — matches inbox exactly |
| Base branch tip | `9e59860a945ec339c69af8709cd0721f0a795327` — matches inbox exactly |
| `merge-base(candidate, base)` | `9e59860a945ec339c69af8709cd0721f0a795327` — **equals base** |
| Base ahead of candidate | none — candidate is a strict fast-forward of base |
| Commits base→candidate | 26 (`70352aa` … `a4ec77f`) |
| Diff | 8 files, 1718 insertions, 19 deletions |
| Diff content class | **documentation only** — every path is under `crooks-assistant/docs/product-memory/`. No code, test, config, systemd unit, script or secret material. |
| `DECISIONS.md` touched? | **No.** Confirmed by `git diff --name-only … -- '*DECISIONS.md'` → empty. |

Branches were fetched explicitly. The stale local refspec still makes `git fetch --all` fail — see
N-01, where that same fact is now load-bearing.

Read in full at the candidate SHA: all four new normative documents, `WATCHER_BUILDER_IDENTITY_REMEDIATION.md`,
the full diffs of `CURRENT_TRUTH.md` / `ROADMAP.md` / `ENGINEERING_ORCHESTRATOR_V1.md`, plus
canonical `DECISIONS.md` (DEC-012/013/045/046/047/048/049), the accepted contract trial at
`295e483…:crooks-assistant/docs/dev-environment/CONTRACT_TRIAL_ENV_REPRO_001.md`, and the previous
outbox F-01…F-12 in full.

---

## 2. Disposition of prior blockers F-01 … F-12

| ID | Prior subject | Disposition | Evidence at `a4ec77f` |
| --- | --- | --- | --- |
| F-01 | Candidate re-sequenced an owner gate / self-granted freeze authority | **OWNER-PENDING** | Genuinely repaired. `ROADMAP.md` footer now reads "**That split is a proposal, not current authority.** It becomes active only if the owner records an explicit DECISIONS.md entry adopting the exact freeze SHA"; D7 restatused to "FREEZE CANDIDATE IN REVIEW … DEC-046 remains the active execution order". `CURRENT_TRUTH.md` matches. Freeze contract §27 opens "This specification is a candidate until the Owner adopts an exact candidate SHA in `DECISIONS.md`. A Director/authored document cannot re-sequence owner gates or promote itself to normative authority." Backed by tests **AU-01** (canonical prose asserting a sequencing change without an owner DECISIONS entry leaves kernel gate state unchanged + typed `AUTHORITY_STALE`) and **ID-06** (implementation started against a branch name rather than the owner-adopted exact frozen SHA is blocked). `DECISIONS.md` is untouched, so no self-adoption occurred. **It fails closed.** Per inbox handling this is an owner gate, not an engineering defect. |
| F-02 | No legal transition table | **CLOSED — but see N-02** | `ORCHESTRATOR_V1_STATE_API.md` §3 (task/integration matrix), §3A (attempt matrix), "Any transition not listed is forbidden", plus ST-11/API-01 property tests. The tables now exist and are mostly complete. Two edges where they contradict each other are raised as **N-02**. |
| F-03 | §14.1 contradicted the CG-03 resolution | **CLOSED** | §14.1 now splits creation-time fields from `evidence_manifest_digest`, explicitly "nullable at Candidate creation", "Candidate existence therefore survives evidence-storage, outbox or delivery failure". `candidate` table: "evidence-manifest digest NULL until evidence completes". DB-07/EV-09/EV-12 now assert durability positively and that reconciliation does not re-dispatch. |
| F-04 | CG-05 marked resolved with no requirement and no test | **CLOSED** | New normative §22A "Clean reconstruction claims" requires approved egress allow-list, immutable pins, pre-extraction and post-install integrity verification, fresh fingerprint, fingerprint equality, and proof that pre-existing tooling did not satisfy the test accidentally — plus "A rerun on the already-provisioned Builder is not reconstruction evidence." Tests EN-01…EN-04. Traceability row updated to cite §22A + EN-01..EN-04. The repair chose option (a) and did it properly. |
| F-05 | "risk-based" gated the two central controls, risk undefined | **CLOSED** | §15 now carries a closed four-class table (`DOCUMENTARY_NONNORMATIVE` / `MATERIAL` / `EXPERIENCE` / `SECURITY_CRITICAL`) with minimum gates, "Unclassified work is `MATERIAL`", and "Models may propose a class but the kernel/policy rules compute the authoritative class." Tests RV-08, IN-09. Self-consistency check passed: `MATERIAL` explicitly includes "normative policy/acceptance document", so this candidate classifies itself as MATERIAL, not documentary. |
| F-06 | Collector creates authoritative records but is not a principal | **CLOSED** | Evidence Collector is now a row in the §3 authority table as a kernel component with explicit MUST NOTs ("execute candidate-controlled code to determine identity; run inside worker process group; accept worker prose as identity"), plus State-API §8A. Test EV-11 rejects a collector running with worker authority or inside the worker process group. |
| F-07 | Nobody authorised to publish the candidate | **CLOSED** | New §14.5: publication is a kernel publication-adapter operation to a create-only namespaced ref `orchestrator/candidate/<task-id>/<candidate-id>`, never force-updated, reviewers consume the immutable SHA not the ref name; "Attempt workspaces MUST have no usable remote push credential." State-API §5A repeats it. Tests PB-06, PB-07. |
| F-08 | Environment/toolchain digest bound but never compared | **CLOSED** | §11 pre-launch now includes "measured environment/toolchain fingerprint equals the environment-manifest digest bound to the task revision; an exit-0 `doctor` or self-report cannot override a fingerprint mismatch." State-API §5B. Tests WS-13, WS-14 (the explicit `DEV_TEAM_V1_PILOT` §5 false-green injection). |
| F-09 | AuthorityGrant expiry/revocation untested | **CLOSED** | §13: "An expired or revoked grant is equivalent to no grant. Grant validity MUST be re-evaluated at every authority-bearing transition; revocation while an attempt is active immediately fences that attempt before any further authoritative result is admitted." Tests CX-07, CX-08, plus OB-07 for the observability gap. |
| F-10 | Freeze criterion §27.4 not met — live branch/checkout mismatch | **RUNTIME-PENDING, with a blocking defect in the plan itself (N-01)** | `WATCHER_BUILDER_IDENTITY_REMEDIATION.md` now exists, §27.5 requires it, §26 Phase 1 is explicitly gated on independent evidence of live closure, and matrix §18 repeats it. The *gating* is correct and I confirm Phase 1 cannot proceed. The *plan* does not survive verification — see N-01. |
| F-11 | Undefined escape hatches | **CLOSED** | §6 now: "The authoritative store MUST be SQLite for frozen V1. Replacing it requires a new reviewed revision of this contract; implementation may not substitute another store under an informal architecture exception." §14.3 now: "V1 uses a deliberately strict rule: **any candidate SHA change invalidates candidate-bound evidence and review.**" Both hedges ("unless an architecture review…", "by default") are gone. The contract now matches EV-05/EV-06. |
| F-12 | "Independent reviewer" undefined | **CLOSED** | §15 final paragraph plus State-API §9 give a minimum predicate: distinct reviewer session/principal, distinct review workspace/channel with no candidate write authority, immutable inputs, no access to the implementer's hidden reasoning. For MATERIAL+ a distinct model/provider where a verified equal-or-stronger one is available; if unavailable, the limitation is recorded and the Director gate stays mandatory. Tests RV-09, RV-10, API-10. |

The previous round's eight non-blocking V1.x suggestions were also addressed: DEC-012 supersession
now has a traceability row; the attempt `RUNNING → CLOSED` edge exists (§3A); DB-07's state naming
is fixed; backup substrate gained an independent destination, periodic cadence, rehearsal and
DB-11/DB-12; mirror staleness gained §5A and WS-15; authority observability gained OB-07; and the
open question about the recording commit is answered in §27 ("a separate follow-up canonical
product-memory commit, matching the existing harness-acceptance pattern").

---

## 3. BLOCKING ENGINEERING FINDINGS

### N-01 — MEDIUM-HIGH — the remediation plan's central remote operation cannot execute, because the ref it fast-forwards does not exist

**Exact location:** `WATCHER_BUILDER_IDENTITY_REMEDIATION.md` §3 ("Why fast-forward rather than
merge/reset"), §5 steps 3 and 5, and §7 acceptance bullet 5. Load-bearing because
`ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §27 criterion 5 and `ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md`
§18 bullet 3 both name this exact document as the required reviewed remediation path, and the
inbox conditions the `RUNTIME-PENDING` classification on the plan being "technically sound".

**What the plan asserts.** §3: "the intended remote ref change is a **fast-forward only**:
`claude/bridge-builder: 9a27bc4... -> 295e483...`". §5 step 3: "fetch only the explicit
`claude/bridge-builder` and accepted Builder refs; do not use the known-broken `git fetch --all`".
§5 step 5: "fast-forward remote `claude/bridge-builder` to `295e483...` without force". §7:
"remote `claude/bridge-builder` exact SHA = `295e483...`".

**Measured fact.** `claude/bridge-builder` **does not exist on `origin`**:

```
git ls-remote --heads origin claude/bridge-builder   ->   (empty)
```

The full `git ls-remote --heads origin` listing (24 branches) contains no `claude/bridge-builder`.
The branch exists only locally, at the old state `9a27bc441adad1e98e8a9ca257d1883246ee7eec`, and
the builder clone's fetch refspec is narrowed to exactly that one deleted ref:

```
remote.origin.fetch = +refs/heads/claude/bridge-builder:refs/remotes/origin/claude/bridge-builder
git fetch --all  ->  fatal: couldn't find remote ref refs/heads/claude/bridge-builder
```

The previous outbox already recorded the branch as deleted; the plan was written as though it were
merely stale.

**Failure / unsafe consequence.** An operator executing §5 inside the bounded maintenance window
hits a hard failure at **step 3**, before reaching any verification step — and the plan explicitly
forbids the one workaround it names (`git fetch --all`), which is itself broken by the same
refspec. Step 5 is then not a fast-forward at all but a **ref creation**
(`push origin 295e483:refs/heads/claude/bridge-builder`), which is a different operation with
different safety properties: a fast-forward push is protected by the remote's own ancestry check,
whereas a create has no such protection and the plan's §3 ancestry argument silently stops
applying. The plan's own escape clause ("if fresh ancestry verification does not prove a strict
fast-forward at execution time, stop and escalate") means the *correct* behaviour is to abort —
so the plan as written cannot close the gate it exists to close. Phase 1 and every write-capable
bridge round stay blocked on a procedure that aborts by construction. This is the freeze gate
resting on an unexecutable step.

**Smallest repair.** In §3, replace the fast-forward framing with the measured state: the remote
ref is absent; the operation is a **create** of `refs/heads/claude/bridge-builder` at
`295e483…`, and the ancestry proof (`9a27bc4…` is an ancestor of `295e483…` — I re-verified this
independently and it holds) is what justifies reusing the name rather than what makes it a
fast-forward. In §5, replace step 3's fetch of the non-existent ref with a fetch of the refs that
do exist (`claude/builder-environment-repair-review` carries `295e483…` on origin), add an
explicit step to repair or replace the stale `remote.origin.fetch` refspec, and change step 5 to a
non-force create with a `--force-with-lease=refs/heads/claude/bridge-builder:` (empty expected
value) or equivalent create-only guard. Update §7 accordingly. Keep every existing prohibition.

**Exact acceptance test required.** A dry-run rehearsal, in a scratch clone against a scratch
remote, that reproduces the current topology (ref absent on remote, present locally at the
ancestor SHA, narrowed refspec) and proves: (a) the documented step sequence completes without
`fatal: couldn't find remote ref`; (b) the create is refused if the remote ref has appeared at an
unexpected SHA in the meantime; (c) no force-update, reset, clean or stash is used; (d) the local
working tree at `295e483…` is byte-identical before and after. Record the rehearsal evidence
before the plan is cited as satisfying §27.5.

---

### N-02 — MEDIUM-HIGH — the two normative transition tables contradict each other on two edges, and the contract's own property test cannot be written

**Exact location:** `ORCHESTRATOR_V1_STATE_API.md` §3 (task transition matrix) versus §3A (attempt
transition matrix). Both are normative in the same freeze set; §3 states "Any transition not
listed is forbidden" and tests ST-11 / API-01 assert that "exactly the normative transition
tables are accepted" and that "only pairs listed in the normative transition matrix can mutate
state".

**Edge (i) — the bounded correction path is forbidden by the attempt table.**
§3 legalises `REJECTED | attempt.assign | ASSIGNED | same task revision; correction budget
available; fresh attempt/fence; prior candidate retained`.
§3A legalises `none | attempt.assign | CREATED` with the mandatory precondition **"task PLANNED"**.
A task in `REJECTED` is not `PLANNED`. The intersection of the two normative tables therefore
contains no legal way to create the correction attempt.

**Edge (ii) — a preflight failure is told to enter a state the task table forbids.**
§3A: `STARTING | preflight deterministic failure | CLOSED / FAILED or QUARANTINED | no model
launch; task becomes BLOCKED/**FAILED** according to typed cause`. At preflight the task is in
`ASSIGNED` (`attempt.start` has not succeeded, so `ASSIGNED → BUILDING` has not fired). But §3
legalises `task.fail` only from `BUILDING/REJECTED`. `ASSIGNED → FAILED` is not a listed
transition and is therefore forbidden.

**Failure / unsafe consequence.** Two divergent implementations are equally defensible and both
are wrong. An implementer who takes §3A's precondition literally gates `attempt.assign` on
`task.state == PLANNED` and **the entire bounded-correction lane silently ceases to exist** —
§10.3's one-bounded-correction rule, matrix RV-04 and gate **E2E-2** ("Intentionally reject a
candidate, perform exactly one bounded correction") all become unreachable, and every rejected
candidate escalates or fails instead. An implementer who instead follows §3 has an attempt table
whose stated precondition is false, so the property test ST-11 — which is the contract's own
mechanism for proving the state machine correct — has two mutually exclusive oracles and cannot be
written. Edge (ii) sends a deterministic preflight failure into a transition the kernel must
reject, so the typed-cause branch that is supposed to produce `FAILED` produces an illegal-
transition error instead, and the attempt is closed while the task is left in `ASSIGNED` with no
lease. That is precisely the stuck-machine class the transition tables were added to eliminate.

This is the direct answer to the inbox's requirement that "complete task/attempt/integration state
and command semantics are executable and non-contradictory". On these two edges they are not.

**Smallest repair.** (a) In §3A, change the `attempt.assign` precondition from "task PLANNED" to
"task `PLANNED`, or task `REJECTED` with correction budget available (§3)". (b) In §3A's STARTING
preflight-failure row, either restrict the task outcome to `BLOCKED` (which is already legal from
any nonterminal state), or add `ASSIGNED` to the `task.fail` from-list in §3. Choose one; do not
leave both documents free to disagree. (c) Add one sentence stating which table is authoritative
where they overlap, so the next such divergence is resolvable without a review round.

**Exact acceptance test required.** Extend **ST-11** so the property test is driven by a single
generated oracle derived from *both* tables jointly, and assert it is non-contradictory: for every
`(task state, attempt state, command)` triple, the task-side and attempt-side guards must agree on
accept/reject. Add a positive case asserting the full `REJECTED → attempt.assign → ASSIGNED →
attempt.start → BUILDING` correction path is legal end-to-end (this is E2E-2's precondition), and a
case asserting a deterministic preflight failure from `ASSIGNED` reaches its typed terminal state
through a listed transition with no partial write.

---

### N-03 — MEDIUM — the candidate fails its own freeze criterion §27.4: `CURRENT_TRUTH.md` still reports CG-01…CG-05 open while the freeze set reports all six resolved

**Exact location:** `CURRENT_TRUTH.md` line 44 at `a4ec77f` versus
`ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §24 and the `ORCHESTRATOR_V1_TRACEABILITY.md` CG rows.

**Measured fact.** `CURRENT_TRUTH.md` line 44, unmodified by this candidate, reads: "Contract gaps
**CG-01 through CG-05 remain open** and CG-06 was added by the continuation". §24 of the freeze
contract lists CG-01…CG-06 each as resolved, and the traceability matrix marks all six
"**V1 MUST — resolved**". The candidate edited `CURRENT_TRUTH.md` in five other places and added a
new "2026-09-20 Orchestrator freeze candidate" section, so the omission is not a
whole-file-untouched artefact.

**Failure / unsafe consequence.** `CURRENT_TRUTH.md` declares itself "compact active context for
GPT/Claude/Fable/engineering workers" and is the file a worker is told to read first. A worker
reading it concludes the reconstruction gap CG-05 is open and reconstruction evidence cannot be
cited; a worker reading the traceability matrix concludes the opposite. This is exactly the drift
that freeze criterion **§27.4** ("canonical current-truth/roadmap drift is reconciled") and matrix
§18 bullet 4 exist to forbid, so the candidate cannot satisfy its own gate at this SHA. It also
re-opens the F-04 failure mode in mirror image: last round a gap was falsely reported closed; this
round a closed gap is falsely reported open, and the traceability matrix's governing rule is
"silence is not a disposition".

I considered and rejected the charitable reading that "the CGs remain open until the freeze is
adopted". It is defensible in principle, but the line does not say that — it states the gaps are
open as current truth, with no reference to the candidate — and §27.4 requires the reconciliation
regardless.

**Smallest repair.** One sentence. Amend `CURRENT_TRUTH.md` line 44 to: "Contract gaps CG-01
through CG-06 are addressed by the 2026-09-20 Orchestrator freeze candidate (§24 and the
traceability matrix) and become canonically closed only when the owner adopts that freeze by exact
SHA; until adoption they remain open in canonical truth." That is simultaneously accurate,
non-self-authorising and consistent with both documents.

**Exact acceptance test required.** No runtime test. Add to the freeze gate (matrix §18) a
mechanical pre-freeze check: every contract-gap / finding identifier that the freeze set marks
resolved is grepped across `CURRENT_TRUTH.md` and `ROADMAP.md`, and any occurrence asserting a
conflicting status fails the gate. This is the same exact-SHA doc/link check `DOCUMENTARY_NONNORMATIVE`
already requires under §15 and would have caught this automatically.

---

## 4. Owner / runtime pending gates — NOT engineering defects

Listed separately, as instructed. Nothing here is a defect in the engineering contract.

**OWNER-PENDING-1 — the F-01 sequencing/adoption decision.** `DECISIONS.md` is untouched by this
candidate; no DEC entry adopts the freeze, and none asserts the Phase 0 sequencing amendment.
DEC-046 (ACTIVE) and DEC-047 (ACTIVE, "unless the owner explicitly changes that ordering in
canonical Git") remain the operative order. The candidate correctly fails closed: `ROADMAP.md`
states the split "is a proposal, not current authority", §27 makes owner adoption by exact SHA a
precondition of normativity, and AU-01/ID-06 make the kernel refuse to act on document prose
alone. **Verified: the candidate does not self-adopt.** The owner decision is required and cannot
be delegated, but its absence is not a contract defect.

**RUNTIME-PENDING-1 — live watcher/builder identity mismatch.** Measured read-only, not
reconciled: `/opt/crooks-builder` is on `claude/builder-environment-repair` at
`295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`, clean; the unit still declares
`Environment=CROOKS_BRIDGE_BUILDER_BRANCH=claude/bridge-builder`. The mismatch is live and
unchanged. The *gating* is now correct and I verified it: §26 Phase 1 begins "Only after Phase 0
acceptance **and** independent evidence that the live … mismatch is closed"; §27.5 makes live
closure a hard prerequisite for Phase 1 and any write-capable bridge round while correctly
exempting repository-only Phase 0. **The gate is sound; the plan behind it is not — see N-01.**

**RUNTIME-PENDING-2 — inherited account-level business MCP connector surface.** Recorded in
`CURRENT_TRUTH.md`: the unattended session "inherited account-level business MCP connector tools
beyond the six CLI `--allowed-tools`". I confirm the condition persists in this very session — my
own tool surface includes Shopify, Gmail, Google Drive, Omnisend and Resend connectors that this
read-only review has no need for and did not call. The contract handles it correctly (§12
effective-roster assertion, "If the current provider/runtime cannot present a sufficiently narrow
effective roster, model-running V1 remains BLOCKED", tests CP-02/CP-10), so it is not a contract
defect. But it has no named remediation document, unlike the branch mismatch, and §26's Phase 1
precondition names only the branch mismatch. **Recommend the owner treat these as a matched pair**:
both are fail-closed prerequisites for write-capable workers, and only one currently has a plan.

---

## 5. Non-blocking observations (explicitly not part of the freeze gate)

1. **§22A retroactively raises the bar on already-accepted Builder evidence.** §22A requires any
   reconstructibility claim to be proved "on a disposable environment with no pre-existing target
   toolchain state", and EN-03 rejects a host that already has the toolchain. The accepted Builder
   (BE-04, `295e483`) makes exactly that claim and was proved on the Builder host from a checkout
   without `.tooling/`/`.venv/` — not on a disposable host. This is a consequence, not a defect,
   and it does not invalidate the Builder acceptance, but the owner should see it before adopting:
   under the frozen rule that evidence would need re-proof if re-cited.
2. **`task.revise` and `release_candidate.mark` carry no idempotency key.** §9's list is "at
   minimum", so this is legal, but a replayed `task.revise` creates a second revision and a
   replayed `release_candidate.mark` creates a second ReleaseCandidate for one integration
   (`release_candidate` has no UNIQUE on integration ID). Bounded impact in V1 since RCs carry no
   deployment authority — worth a UNIQUE constraint anyway.
3. **`SUPERSEDED` is overloaded.** Freeze contract §5.1 defines it as "replaced by a new task
   revision/objective", but State-API `task.revise` sets the task to `PROPOSED` and marks only the
   *old revision* superseded, while `task.supersede` makes the *task* terminal. An implementer
   following §5.1's wording would set the task terminal on every revision. The State-API table is
   unambiguous and wins under "any transition not listed is forbidden", so this is a wording
   collision, not a live contradiction — but it is one word away from being one.
4. **A `BLOCKED` integration has no resume edge.** Task `BLOCKED` resumes via `task.plan`;
   integration `BLOCKED` can only be cancelled, forcing a new integration record. Fail-closed and
   recoverable, so acceptable — worth stating as deliberate.
5. **Host-loss is not stated as a limitation.** §6 requires a backup destination "independent of
   the active DB file" and a "declared recovery-point objective", but nothing requires the
   destination to survive host or disk loss, and V1 is single-host. The RPO claim is therefore
   unfalsifiable against the most likely total-loss scenario. Impact is bounded — work product
   lives in Git on the remote; only control-plane state is at risk — but say so.
6. **`RS-02`** still defers reviewer-alongside-implementation to a "resource/tool/workspace
   isolation policy" that is not written down. Unchanged from last round; fine to defer, worth
   labelling as deferred.
7. **AuthorityGrant field completeness is untested.** CX-07/CX-08 cover expiry and revocation;
   ID-01 covers task/attempt record completeness but not grant records.

## 6. What the candidate gets right

The repairs are real, not cosmetic. The authority fix (F-01) is the important one: the candidate
now argues against its own promotion and encodes that refusal as a test (AU-01), which is the
correct shape for a document that cannot be trusted to grade itself. §22A is a genuine normative
section rather than a restated checkbox. The Evidence Collector as a named kernel principal
outside the worker process group (§3, §8A, EV-11), kernel-only publication with no worker push
credential (§14.5, §5A, PB-06/07), the closed risk table with a MATERIAL default computed by the
kernel rather than asserted by a model (§15, RV-08), the candidate-durable-before-evidence split
(§14.1, DB-07/EV-09/EV-12), and the independence predicate with its honest "limitation recorded"
fallback (§15, RV-10) all close their findings properly. The identity model, epoch/fencing design,
BLOCKED-vs-RETRYABLE taxonomy, strict invalidation, reconciliation ordering and the model-free
Phase 0 remain sound and should survive unchanged. **N-01 and N-02 are the cost of the repair
round — a plan written from a stale premise, and a second transition table that was not
cross-checked against the first.** N-03 is a line that was not carried along. None of the three is
a direction problem.

---

## 7. State at end of round

| Item | Value |
| --- | --- |
| Production branch HEAD | `claude/linux-prod-migration-production` @ `1cf3a0f3361b79f9de208d80f501543c53c244b5` (DEC-048 ratified) |
| Production git status | clean — inspected read-only; never switched, reset or edited |
| Builder branch / HEAD | `claude/builder-environment-repair` @ `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b` |
| Builder git status | clean before and after this round (verified twice, `git status --porcelain` empty) |
| Bridge worktree status | clean apart from this outbox |
| Files changed by me | exactly one: `bridge/claude-outbox.md`. Nothing else in any repository. No `git add`, `commit`, `push`, `merge`, `checkout`, `reset`, `clean` or `stash` was run anywhere. |
| Git operations performed | `fetch` of two explicitly named branches into the builder clone (objects only, no ref/worktree change), plus read-only `ls-remote`, `show`, `diff`, `log`, `merge-base`, `cat-file`, `rev-parse`, `status` |
| `crooks-assistant.service` | `active`, `enabled` |
| `crooks-bridge-watcher.service` | `active`, `enabled`; declares `claude-opus-5` @ `high` |
| Network exposure | `127.0.0.1:8000` loopback only (python, pid 217827); `:443` bound to tailnet addresses `100.72.82.24` and `fd7a:115c:a1e0::352b:5219` via `tailscaled`. Port 8000 not publicly exposed. |
| Disk | 14G used of 75G, 19% |
| Tests run | none — this was a read-only documentation review. No suite was applicable and none is claimed. |
| Errors | none. One expected diagnostic, deliberately probed and reported as finding N-01: `git fetch --all` → `fatal: couldn't find remote ref refs/heads/claude/bridge-builder`. |

**Safety constraints preserved:** `writes_enabled` false, `CROOKS_WRITES_LOCAL_OWNER` false,
FastAPI bound to loopback, port 8000 unexposed, proposal/action/verification semantics unchanged,
no live Shopify/Gmail/ElevenLabs call and no live external mutation, V2 not begun, UI not
redesigned, Mac deployment and rollback path untouched, `/root/.claude` still writable, no secret
value printed or committed. Secrets are named only, never valued. The live watcher/builder
mismatch was measured and reported, **not** reconciled, as the inbox required.

**Permission-layer blocks:** none. Nothing in this round was refused by my permission layer, and I
neither widened permissions nor sought a way around any.

**Approval-gated items encountered:** none reached. The round was read-only by instruction, so no
owner approval was needed and none is recorded or inferred.

---

## 8. Exact proposed next step

**One bounded document round on the candidate branch, then the owner decision. Do not start
kernel implementation, and do not execute the runtime remediation yet.**

1. **Repair round on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, three edits:**
   - **N-01** — rewrite `WATCHER_BUILDER_IDENTITY_REMEDIATION.md` §3, §5 steps 3/5 and §7 against
     the measured topology: remote ref absent, local ref at the ancestor SHA, narrowed refspec.
     Add the refspec repair as an explicit step and make step 5 a guarded create.
   - **N-02** — reconcile `ORCHESTRATOR_V1_STATE_API.md` §3A with §3 on both edges and state which
     table is authoritative on overlap.
   - **N-03** — one-sentence amendment to `CURRENT_TRUTH.md` line 44.
   Add the corresponding matrix rows: the ST-11 joint-oracle extension, the `REJECTED →
   attempt.assign` positive case, the `ASSIGNED` preflight-failure case, and the §18 mechanical
   gap-status cross-check.
2. **Then the owner decision (blocking, cannot be delegated, unchanged from last round).** A
   `DECISIONS.md` entry that either (a) adopts the freeze by exact SHA and states explicitly what
   it changes about DEC-046 sequencing, or (b) declines the re-sequencing and leaves Phase 0
   behind the existing current-product/device/evidence gates. The candidate now correctly refuses
   to make this decision for the owner; nothing in it should be read as having made it.
3. **Runtime remediation as a separate authorised task, after the plan is corrected.** Execute
   only in a bounded window with the watcher drained, and only with the rehearsal evidence from
   N-01's acceptance test in hand. Recommend the owner decide at the same time whether
   RUNTIME-PENDING-2 (inherited connector surface) gets its own remediation document, so both
   write-capable prerequisites are tracked the same way.
4. **Fresh independent adversarial review bound to the new candidate SHA.** Per §14.3 and §15 —
   which this candidate states and which I am applying to it — **this review is invalid for any
   changed tree. Do not carry this verdict forward.**

**Open question for the Director, not a finding.** §15 requires a distinct model or provider for
MATERIAL review "where a verified equal-or-stronger reviewer is available". This candidate is
MATERIAL by its own table, and it has now been reviewed repeatedly by `claude-opus-5` — the same
model that would implement the kernel. The contract's fallback (record the limitation, retain the
Director gate) is being exercised silently rather than recorded. Decide whether the freeze record
should state that explicitly, since the contract asks every other review to.
