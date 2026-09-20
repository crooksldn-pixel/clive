# CLAUDE OUTBOX — latest handoff only

## 2026-09-20T09:06:02Z — Independent adversarial review, Orchestrator V1 freeze candidate

## VERDICT: `CHANGES REQUIRED BEFORE V1 FREEZE`

**Inbox consumed:** yes. Blob SHA processed:
`49bdf596f804e9789571a6d13f869d3fe9c8f3b3` (`bridge/chatgpt-inbox.md`, heading "Independent
adversarial review — Orchestrator V1 freeze candidate"). These instructions are now recorded as
executed and must not be run again.

**This was a READ-ONLY REVIEW round.** Nothing was edited, created or deleted anywhere except
this outbox file. No commit, push, merge, branch switch, reset, clean, stash, install, restart or
deploy. No change to production, `/opt/crooks-os/crooks-assistant`, the builder checkout, the
watcher, its systemd unit, account/global Claude or MCP configuration, connectors, credentials,
privileges or Git configuration. No live external call, no business write. The candidate was read
from the remote by exact SHA. The builder checkout was measured, not reconciled, as the inbox
instructed.

---

### What was asked

Attempt to prove the Orchestrator V1 freeze candidate is **not** ready to freeze; return exactly
one of `ACCEPT FOR V1 FREEZE` / `CHANGES REQUIRED BEFORE V1 FREEZE`; list only material blocking
findings with ID, severity, exact location, why it can cause an incorrect or unsafe
implementation, the smallest contract change, and the acceptance test that must be added or
changed; list non-blocking V1.x/V2 suggestions separately.

### Candidate identity — verified

| Item | Value | How verified |
| --- | --- | --- |
| Repository | `crooksldn-pixel/clive` | `git remote -v` on the builder clone |
| Candidate branch | `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` | `git ls-remote` |
| Candidate SHA | `f1c808eff1f0a6cafcb50cbb624cd2c913e2a6b1` | branch tip **equals** the stated SHA |
| Base | `claude/product-memory-foundation@9e59860a945ec339c69af8709cd0721f0a795327` | is the exact `git merge-base` of the two |
| Author / date | `crooksldn-pixel`, 2026-09-20T12:01:42+03:00 | `git log -1` |

Branches were fetched explicitly (the stale `claude/bridge-builder` refspec still makes
`git fetch --all` fail; unchanged, not fixed by me).

Diff `9e59860 → f1c808e` is six files, 1051 insertions / 14 deletions, six commits
(`70352aa`, `21b65a3`, `a3664ba`, `d4b253f`, `8356075`, `f1c808e`). Documentation only; no code,
no test, no config, no systemd, no secret material. I read all three new documents in full, both
modified documents' diffs in full, plus `DEV_TEAM_V1_PILOT.md`, `DECISIONS.md` (DEC-012/013/043/
044/046/047), `MIGRATION_HANDOFF.md` §134, the accepted contract-trial record
`295e483…:crooks-assistant/docs/dev-environment/CONTRACT_TRIAL_ENV_REPRO_001.md`, and the
previous bridge outbox.

---

## BLOCKING FINDINGS

### F-01 — CRITICAL — the candidate re-sequences an owner gate and self-grants freeze authority

**Where:** `ROADMAP.md` sequencing footer (lines ~709–717 of the new file) and
`ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §27; the commit does **not** touch `DECISIONS.md`
(`git diff --name-only` lists six files; `DECISIONS.md` is not among them).

**What it does.** The footer replaces the DEC-046 ordering item "10. implement Engineering
Orchestrator / Dev Team V1" with a split that lets the repository-only deterministic kernel
proceed **after freeze** rather than after the preceding current-product/device/evidence gates,
and says "This resolves the earlier ambiguity". `ROADMAP.md` D7 and `ENGINEERING_ORCHESTRATOR_V1.md`
are restatused to match.

**Why this is unsafe.** DEC-047 (ACTIVE) reads: "Implementation may begin once the preceding
DEC-046 … gates are satisfied, **unless the owner explicitly changes that ordering in canonical
Git**." No such owner change exists in this diff or anywhere in `DECISIONS.md`. DEC-046's
Consequences clause is more specific still: the V1 spec's "task-store choice, retry counts,
concurrency limits and other new mechanics are **not silently promoted to approved decisions**."
The freeze contract normatively fixes exactly those three — SQLite (§6), 5 attempts / 15-minute
retry ceiling (§10.2), concurrency = 1 (§19) — by Director document alone. DEC-047 also
explicitly does not "silently approve unresolved mechanism choices that the V1 specification
marks for architecture/engineering review."

The candidate therefore violates its own authority model in the same commit that asserts it:
§3 says the GPT Director MUST NOT "self-authorise owner gates", and §13 says a model "cannot
convert conversational prose into broader authority on its own". A Director-authored canonical
document that re-orders an owner gate and promotes mechanism choices to normative is precisely
the prose-to-authority conversion §13 exists to forbid. Accepting the freeze on this commit would
make the first act of the V1 contract a breach of it — and would let kernel implementation begin
ahead of gates the owner set.

**Smallest contract change.** (a) Revert the `ROADMAP.md` footer to the DEC-046 ordering and mark
the split as a **proposal requiring an owner decision**, not as resolved. (b) Add to §27 a
criterion 0: "This contract becomes normative only when a `DECISIONS.md` entry recorded by the
owner adopts it by exact SHA and states any sequencing change." (c) Restate D7 and
`ENGINEERING_ORCHESTRATOR_V1.md` as candidate-pending-owner-adoption.

**Acceptance test.** New **AU-01**: a canonical document asserting a re-sequencing, freeze status
or mechanism promotion with no corresponding owner `DECISIONS.md` entry MUST leave the kernel's
gate state unchanged and raise a typed authority finding. Extends CX-06 from conversational prose
to canonical-document prose, which is the larger hole.

---

### F-02 — HIGH — the task state machine has no legal transition table

**Where:** §5.1 (and §5.2 for attempts); matrix ST-03/ST-04.

**What is missing.** §5.1 gives one linear happy path
(`PROPOSED → … → RELEASE_CANDIDATE`) and then a bullet list of six side states — `BLOCKED`,
`ESCALATED`, `REJECTED`, `FAILED`, `CANCELLED`, `SUPERSEDED`. **No edges into or out of any side
state are defined anywhere.** In particular there is no re-entry edge implementing §10.3's
bounded correction: after `REJECTED`, nothing says whether the task returns to `ASSIGNED`,
`BUILDING`, or a new revision, nor which states may legally enter `BLOCKED`, nor how `BLOCKED`
is cleared, nor whether `ESCALATED` can return to the main path.

**Why this is unsafe.** ST-04 tests that illegal transitions are rejected "with a stable typed
error" against a legal set that the contract never enumerates — the test cannot be written, and
the implementer must invent the core table of the control plane under time pressure. Divergent
guesses produce either a stuck machine (no exit from `BLOCKED`) or a permissive one (a rejected
candidate silently re-entering `REVIEWING` without a new revision, defeating §14.3/§15).

**Smallest contract change.** Add to §5.1 an explicit edge table: for every source state, the
permitted targets, the actor permitted to make the transition, and the required precondition —
including the `REJECTED →` correction edge, `BLOCKED →` clearance edge and `ESCALATED →` return
edge. Same for §5.2, which as written has no `RUNNING → CLOSED` edge for an attempt that fails
before producing a candidate.

**Acceptance test.** ST-04 must cite that table as its oracle; add **ST-11**: property test
enumerating the full state × state matrix, asserting exactly the tabled edges are accepted and
all others rejected with a typed error and no partial write.

---

### F-03 — HIGH — §14.1 contradicts the CG-03 resolution it claims to deliver

**Where:** §14.1 vs §14.4, matrix DB-07 and EV-09.

**The contradiction.** §14.1: "A Candidate record is created by the collector **after** a commit
exists. It binds: … **evidence-manifest digest**." If the manifest digest is a required binding
field at creation, then a commit whose evidence collection or evidence-storage write fails
produces **no Candidate record at all**. But DB-07 asserts "evidence storage write fails →
candidate cannot reach `EVIDENCE_READY`", which presumes the candidate record exists. §14.4 only
separates the candidate from **delivery**, not from **evidence**.

**Why this is unsafe.** CG-03 exists because of the Mobile V1 incident: a finished candidate that
is invisible because the channel that would report it failed is indistinguishable from a worker
that never started, and the kernel duplicate-dispatches the work that actually succeeded
(`CONTRACT_TRIAL_ENV_REPRO_001.md` §2.3). Closing CG-03 only against delivery failure while
leaving evidence failure able to erase the candidate reintroduces the same incident through the
adjacent door. An implementer reading §14.1 literally will make the digest NOT NULL.

**Smallest contract change.** In §14.1, split the binding into creation-time fields (task
revision, attempt, base SHA, candidate SHA, changed-file set, diff digest, workspace/environment
identity) and a later-populated `evidence_manifest_digest` set at the `EVIDENCE_READY`
transition, with an explicit statement that the Candidate record MUST be durable before evidence
collection begins.

**Acceptance test.** Amend **DB-07** and **EV-09** to assert positively that the Candidate record
exists and is discoverable with a null manifest digest after an evidence-storage failure, and
that reconciliation does **not** re-dispatch the attempt.

---

### F-04 — HIGH — CG-05 is recorded as resolved but has no normative requirement and no test

**Where:** §24 bullet CG-05 (single line, contract line 581); `ORCHESTRATOR_V1_TRACEABILITY.md`
row "DEV_TEAM trial CG-05 … **V1 MUST — resolved**".

**Measured fact.** The strings `reconstruct`, `egress`, `allow-list` and `pinned` appear in the
entire freeze contract **only** on that one summary line in §24, and **not once** in the
acceptance matrix. There is no §-level requirement for an egress policy, a package-fetch
allow-list, asset pinning, integrity verification, a disposable host, or fresh reconstruction
evidence, and no test ID covers any of them.

**Why this is unsafe.** The contract-trial record is explicit that CG-05's defect is the checkbox
itself: "the acceptance case still reads as one checkbox while requiring an egress policy, a
fetch allow-list, pinned release assets and a disposable host, and a later worker reading the
checkbox alone will still be tempted to satisfy it with a rerun on a machine that already has the
environment." §24 restates the gap's *contents* as if listing them were the repair. It is a
narrower checkbox, in a document whose §27.2 and matrix §18 both require every MUST to have a
test. Marking a known false-green vector closed is worse than leaving it open, because the
traceability matrix then reports no outstanding item.

**Smallest contract change.** Either (a) add a normative section — "clean reconstruction MUST be
performed on a host with no pre-existing toolchain, under an approved egress allow-list, against
pinned release tags/asset digests, with pre-extraction and post-install integrity checks, and
produce a fingerprint equal to the declared environment" — or (b) change the §24 and traceability
rows to **OPEN / DEFERRED V1.x**, with the consequence that no acceptance may cite reconstruction
evidence until it is closed. (b) is the smaller and more honest change; the inbox's own
instruction is to prefer a smaller rigorous V1.

**Acceptance test.** If (a): new **EN-01..EN-03** — fetch outside the allow-list is denied;
asset digest mismatch fails closed; reconstruction on a host that already has the toolchain is
rejected as non-evidence. If (b): no test, but the traceability row must read OPEN.

---

### F-05 — HIGH — "risk-based" gates the two central safety controls and risk is never defined

**Where:** §15 "Required review is risk-based, not agent-count-based"; §22 "Required
CI/reverification policy is task-risk based"; §16 "Relevant tests/replay/reviews MUST be rerun";
matrix PR-06 "according to task risk policy", IN-06 "requiring relevant review".

**What is missing.** No risk taxonomy, no classification rule, and no default. The words `risk`
and `relevant` carry the decision of **whether independent review and independent CI are required
at all**, and whether an integration must be re-verified.

**Why this is unsafe.** This is the single highest-leverage undefined term in the contract. An
implementer — or worse, a model asked to classify its own task — decides that a change is
low-risk and the independent review gate (DEC-013, §15) and the exact-SHA CI gate (§22) simply do
not apply. Every other control in the contract is downstream of those two. Undefined plus
no-default resolves, under delivery pressure, to permissive.

**Smallest contract change.** Add to §15 a short closed risk table (e.g. `MATERIAL` — any change
to code, tests, config, policy, guards or dependencies; `DOCUMENTARY` — repository-only prose)
with an explicit **default-deny rule**: a task not classified by a listed rule is `MATERIAL`, and
classification is a kernel function, never a model assertion. Define "relevant" in §16 as "every
check whose input closure intersects the integration's changed paths; unknown closure means all".

**Acceptance test.** New **RV-08**: an unclassified or model-asserted-low-risk task MUST still
require independent review and independent CI. New **IN-09**: an integration whose input closure
cannot be computed MUST rerun the full check set.

---

### F-06 — MEDIUM-HIGH — the "collector" creates authoritative records but is not a principal

**Where:** §14.1 and §14.2 ("the collector"); §3 authority table; matrix EV-01.

**What is missing.** The collector builds the Candidate record and the evidence manifest — both
authoritative — yet it does not appear in the §3 authority table, and nothing states where it
runs or under whose privileges. §14.2 says the manifest is created "outside candidate-controlled
source", which constrains the *output location* but not the *executing principal*.

**Why this is unsafe.** The obvious implementation is to run the collector inside the attempt
workspace, as the worker, because that is where the repository and the test output are. That
makes the worker the author of its own candidate identity and its own evidence — exactly what
§14.1's own closing sentence forbids ("A candidate cannot authoritatively define its own
identity") and what the trial record flagged as the collector-builds-the-record consequence.
EV-01 tests the *content* ("built from measured SHA, not worker prose") but not the *principal*,
so a worker-side collector passes EV-01.

**Smallest contract change.** Add the collector to §3 as a kernel component: "the collector
executes with kernel authority, outside the attempt's writable boundary and outside the worker's
process group; it measures the workspace read-only and MUST NOT execute candidate-controlled
code to determine identity."

**Acceptance test.** New **EV-11**: a collector invoked with worker privileges, or from inside
the attempt process group/workspace, MUST be rejected and the candidate not admitted.

---

### F-07 — MEDIUM-HIGH — nobody is authorised to publish the candidate to the remote

**Where:** §9 (idempotency list includes "Git publication"); §11 (standalone clone); §12
(workers MUST NOT receive "unrestricted repository push authority"); matrix PB-01/PB-03/PB-04.

**What is missing.** §11 puts the attempt in an isolated standalone clone created from a
builder-owned local mirror. §12 denies the worker unrestricted push and defines no narrow push.
§9 and PB-01 assume a publication step exists and is idempotent. **No section says who performs
it or by what mechanism.**

**Why this is unsafe.** Two implementations are equally consistent with the text: give the worker
a push credential (re-opening the exact credential surface §12 and PB-03 exist to close), or have
the kernel fetch from the attempt clone and push (safe, but unspecified, so the readback
reconciliation of PB-01/PB-04 has no defined subject). Publication is also the one step that
touches shared mutable remote state, so leaving it undefined puts the ambiguous-external-effect
machinery of §9 on a foundation that does not exist.

**Smallest contract change.** Add to §11 or §14: "Publication is a kernel operation. The kernel
fetches the candidate commit from the attempt workspace by exact SHA and publishes it to a
namespaced candidate ref under its own credential. Attempt workspaces receive no remote push
credential." Add the candidate ref namespace and the rule that it is never a branch the
integrator or production consumes by name.

**Acceptance test.** New **PB-06**: an attempt workspace has no usable push credential (negative
test), and a worker-initiated push fails at the credential layer; **PB-07**: kernel publication
is idempotent under a lost response, reconciled by ref readback against the exact SHA.

---

### F-08 — MEDIUM — the environment/toolchain manifest digest is a MUST-bind field with zero tests

**Where:** §4 bullet "environment/toolchain manifest digest"; §11 pre-launch checklist; matrix
sections 5 and 6.

**Measured fact.** The string `toolchain` does not appear in the acceptance matrix at all. §11's
pre-launch list verifies HEAD, branch metadata, cleanliness, common-dir, foreign processes and
the tool/network/credential roster — but **not** that the workspace's measured toolchain matches
the digest bound to the record.

**Why this is unsafe.** This is the concrete false-green that `DEV_TEAM_V1_PILOT.md` §5 requires
the pilot to inject — "for example doctor exit 0 with mismatched tooling" — and the accepted
Builder Environment already produces the environment fingerprint that makes the check cheap
(BE-04, `295e483`). Binding a digest that nothing ever compares is decoration; evidence would be
attributed to an environment that did not produce it.

**Smallest contract change.** Add to §11's pre-launch checklist: "measured environment fingerprint
equals the bound environment/toolchain manifest digest; mismatch is BLOCKED."

**Acceptance test.** New **WS-13**: workspace toolchain differing from the bound digest blocks
launch before any model starts; **WS-14**: a `doctor`-style exit 0 with mismatched tooling is
rejected, satisfying the PILOT §5 false-green requirement.

---

### F-09 — MEDIUM — AuthorityGrant expiry and revocation are required fields with no negative test

**Where:** §13 (grant binds "expiry/revocation condition"); matrix CX-05, CX-06.

**What is missing.** CX-05 covers creating a grant, CX-06 covers acting without one. Nothing
tests an **expired** or **revoked** grant, and §13 states no behaviour for one.

**Why this is unsafe.** Under the matrix's own rule ("one deterministic test proves the positive
path and one negative/fault path where applicable"), an untested expiry field is a field that
gets implemented as advisory. A grant that never effectively expires is a standing privilege —
the failure mode §13 was written to prevent, and it degrades silently rather than failing closed.

**Smallest contract change.** Add to §13: "An expired or revoked grant is equivalent to no grant.
The kernel re-evaluates grant validity at each authority-bearing transition, not only at
admission."

**Acceptance test.** New **CX-07**: an attempt holding an expired grant is BLOCKED at the next
authority-bearing transition; **CX-08**: revocation mid-attempt fences the attempt.

---

### F-10 — MEDIUM — freeze criterion §27.4 is not met, and I measured it directly

**Where:** §27 criterion 4 and matrix §18 bullet 2 — freeze requires that "the existing bridge
branch/checkout identity defect has a reviewed remediation path".

**Measured now, read-only, not reconciled (as the inbox instructed):**

- builder checkout `/opt/crooks-builder` is on branch **`claude/builder-environment-repair`** at
  `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`, working tree clean;
- `systemctl cat crooks-bridge-watcher.service` still declares
  `Environment=CROOKS_BRIDGE_BUILDER_BRANCH=claude/bridge-builder`.

The mismatch is live and unchanged. Searching the candidate's product memory for a remediation
path finds only two descriptive records — `CURRENT_TRUTH.md` line 32 (reports the defect) and
`MIGRATION_HANDOFF.md` line 134 ("a standing discrepancy, not current truth"). **Describing a
defect is not a reviewed remediation path.**

**Consequence.** The contract cannot satisfy its own criterion 4 at this SHA regardless of the
other findings. This is a gate-not-met, not a document defect — but it independently forecloses
`ACCEPT`.

**Smallest change.** Produce the remediation as a separate reviewed bounded task (reconcile the
unit's declared branch with the accepted builder branch, or vice versa, with the decision
recorded), then cite its exact SHA in §27.4. Do not reconcile it inside the freeze commit.

**Acceptance test.** WS-02 already covers the invariant; what is missing is the **evidence** that
the live system satisfies it. Add to §18 the requirement that the freeze record cite the exact
remediation commit SHA.

---

### F-11 — MEDIUM — a frozen contract containing undefined escape hatches

**Where:** §6 "The authoritative store MUST be SQLite **unless an architecture review explicitly
replaces it before freeze implementation**"; §14.3 "any candidate SHA change invalidates
candidate-bound evidence and review **by default**".

**Why this is unsafe.** `ENGINEERING_ORCHESTRATOR_V1.md`'s new overlay note claims the overlay
"resolve[s] the previously open mechanism choices". These two clauses leave them open while
appearing resolved. "By default" implies a documented override for evidence invalidation; none
exists anywhere, so an implementer may infer discretion to reuse evidence — the precise
false-green path CG-02 and §14.3 exist to close. "Unless an architecture review" names no
authority and no record.

**Smallest contract change.** Delete "unless an architecture review explicitly replaces it before
freeze implementation" (a store change after freeze is a new revision of this contract, by §27's
own binding rule). Delete "by default" from §14.3, making invalidation unconditional in V1, which
is what §14.3's next sentence already says.

**Acceptance test.** EV-05/EV-06 already assert unconditional invalidation; they currently
contradict the "by default" hedge. Removing the hedge makes the contract match its own tests.

---

### F-12 — MEDIUM — "independent reviewer" is required everywhere and defined nowhere

**Where:** §3, §15, §22; matrix RV-01, RV-02; DEC-013.

**What is missing.** §4 requires records to bind "reviewer identity", and RV-01 rejects a review
whose author is the implementer. But no section defines what makes a reviewer *independent*:
different session, different workspace, different model, different provider account, different
credential? In this deployment implementer and reviewer would both be `claude-opus-5` launched by
the same controller under the same account.

**Why this is unsafe.** RV-01 as written is satisfied by a different attempt ID. DEC-013 asks for
"adversarial verification, not agreement"; an undefined predicate lets the weakest reading — a
fresh session of the same model with the same context — count as independence, which is exactly
the correlated-failure case adversarial review exists to break. This is not hypothetical: the
harness acceptance at `2c2b0cc` earned its trust from **six** genuinely separate rounds, and the
contract does not encode what made those rounds separate.

**Smallest contract change.** Add to §15 a minimum independence predicate: distinct session and
distinct workspace, no access to the implementer's reasoning or conversation, review input
limited to the §15 list, and — for `MATERIAL` risk per F-05 — a distinct model or distinct
provider where available, with the actual reviewer identity recorded and any unmet dimension
recorded as a stated limitation rather than silently met.

**Acceptance test.** Amend **RV-01** to assert each dimension separately; new **RV-09**: a review
produced in the implementer's session or workspace is rejected even under a different attempt ID.

---

## NON-BLOCKING — V1.x / V2 SUGGESTIONS (explicitly NOT part of the freeze gate)

1. **DEC-012 supersession is silent.** DEC-012 (ACTIVE) says "every autonomous worker gets its own
   **worktree**"; §11 now requires a standalone clone and forbids a linked worktree of production.
   That is a correct strengthening driven by the 2026-09-19 incident, but the contract states
   "Product safety decisions in `DECISIONS.md` remain superior" and then silently narrows one.
   Add a traceability row recording the disposition.
2. **§5.2 attempt lifecycle** has no `RUNNING → CLOSED` edge for an attempt that fails before
   producing a candidate (folds into F-02's table if done there).
3. **DB-07 names `EVIDENCE_READY`**, a *task* state, as though it were a candidate state. Naming
   only; worth fixing while F-03 is addressed.
4. **Backup substrate is unspecified** (§6, DB-04/DB-05): no location, retention, integrity
   verification of the backup itself, or restore rehearsal. A backup never verified is not a
   recovery path.
5. **Mirror staleness** (§11, WS-12): WS-12 covers the mirror being *unavailable*, not the mirror
   being *stale* such that the exact base SHA is absent. Add a fetch-then-verify rule.
6. **No observability for authority** (§18): the mandatory metric list has no counter for
   AuthorityGrant denials or expiries, which is the control plane's most security-relevant
   rejection class.
7. **`RS-02`** defers reviewer-alongside-implementation to a "resource/tool/workspace isolation
   policy" that is not written down. Fine to defer, but say it is deferred.
8. **Phase 5 / GPT Director automation** is the right thing to defer; no change requested.

## WHAT THE CANDIDATE GETS RIGHT (so the rework is targeted, not wholesale)

The identity model (§4, "branches are labels, SHAs are authority"), the epoch + monotonic fencing
design (§7) with its "stale token rejected even if the output would otherwise pass tests" rule,
the refusal to claim exactly-once (§9), the deterministic BLOCKED-vs-RETRYABLE taxonomy (§10)
which correctly encodes the eight-retry incident, lease-expiry-is-not-death with quarantine (§8),
strict full invalidation over a reuse optimisation (§14.3), the restart reconciliation ordering
(§21), and the Phase 0 repository-only kernel with no model launch (§26) are all sound and should
survive unchanged. The traceability matrix is genuinely thorough and its four-disposition rule
("silence is not a disposition") is the right mechanism. **The findings above are about what the
contract leaves to be invented, not about its direction.** F-01 is the exception: it is about
authority, not engineering, and it must be resolved by the owner rather than by a better document.

---

### State at end of round

| Item | Value |
| --- | --- |
| Production branch HEAD | `claude/linux-prod-migration-production` @ `1cf3a0f3361b79f9de208d80f501543c53c244b5` (DEC-048 ratified) |
| Production git status | clean — inspected read-only, never switched or reset |
| Builder branch/HEAD | `claude/builder-environment-repair` @ `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b` |
| Builder git status | clean, no modified or untracked files, before and after this round |
| Files changed by me | exactly one: `bridge/claude-outbox.md` (this file). Nothing else in any repository. |
| `crooks-assistant.service` | `active`, `enabled`, listening `127.0.0.1:8000` only |
| `crooks-bridge-watcher.service` | `active`, `enabled` |
| Network exposure | `127.0.0.1:8000` loopback only; `:443` bound to tailnet addresses (`100.72.82.24`, `fd7a:115c:a1e0::352b:5219`) via `tailscaled`. Port 8000 not publicly exposed. |
| Disk `/opt` | 14G used of 75G, 19% |
| Tests run | none — this was a documentation review; no suite was applicable and none is claimed |
| Errors | none |

**Safety constraints preserved:** `writes_enabled` false, `CROOKS_WRITES_LOCAL_OWNER` false,
FastAPI bound to loopback, port 8000 unexposed, proposal/action/verification semantics unchanged,
no live Shopify/Gmail/ElevenLabs call and no live external mutation, V2 not begun, UI not
redesigned, Mac deployment and rollback path untouched, `/root/.claude` still writable, no secret
value printed or committed. No secret is named with a value anywhere above.

**Permission-layer blocks:** none. Nothing in this round was refused by my permission layer.

**Approval-gated items encountered:** none reached — this round was read-only by instruction, so
no approval was needed and none is recorded.

### Exact proposed next step

**One decision by the owner, then one bounded document round. Do not start kernel implementation.**

1. **Owner decision on F-01 (blocking, cannot be delegated).** Record a `DECISIONS.md` entry
   (DEC-050) that either (a) adopts the freeze contract by exact SHA and explicitly states the
   DEC-046 sequencing change it makes, or (b) declines the re-sequencing, leaving the kernel
   behind the existing current-product/device/evidence gates. Everything else waits on this,
   because (b) makes most of the freeze urgency moot.
2. **Then one repair round on the candidate branch** addressing F-02 through F-09, F-11 and F-12 —
   all are document edits: a transition table, a field-ordering split, a risk table, a collector
   principal, a publication rule, an independence predicate, two deleted escape clauses, and the
   matrix rows AU-01, ST-11, EV-11, WS-13/14, CX-07/08, RV-08/09, IN-09, PB-06/07. F-04 should be
   taken as option (b) — reclassify CG-05 as OPEN — which is smaller and truthful.
3. **F-10 as a separate bounded task**, not folded into the freeze commit: decide and record
   whether the watcher unit's declared builder branch or the builder's actual branch changes, then
   cite that commit in §27.4.
4. **Fresh independent adversarial review bound to the new candidate SHA.** Per §14.3 and §15 —
   which this candidate states and which I am applying to it — this review is invalid for any
   changed tree. Do not carry this verdict forward.

**Open question for the Director, not a finding.** §27.6 requires the freeze commit SHA to be
recorded in canonical product memory, but the recording commit necessarily comes after the commit
it records. Decide now whether the freeze SHA is recorded in a separate follow-up commit (simple,
and the pattern already used for `HARNESS_ACCEPTANCE_2C2B0CC.md`) or via an annotated tag. Left
unstated, it will be improvised at the worst moment.
