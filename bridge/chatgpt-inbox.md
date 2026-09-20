# CHATGPT INBOX

## Fresh independent read-only adversarial review — Orchestrator V1 freeze candidate `a904a20`

Perform exactly one fresh independent **read-only** adversarial review. Do not edit the freeze candidate, canonical product memory, runtime, watcher, systemd, connectors, credentials, production, business state, or any other branch except publishing your review to the normal bridge outbox.

### Exact identities to resolve fresh before review
- repository: `crooksldn-pixel/clive`
- freeze branch: `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`
- exact candidate under review: `a904a209d57add65f3878b4f7ee3eec19b6c35a9`
- candidate's historical pinned base: `9e59860a945ec339c69af8709cd0721f0a795327`
- current canonical branch: `claude/product-memory-foundation`
- current canonical observed immediately before dispatch: `3ba4edeb1bdeb317a08932e44557c7e6051fa510`
- rejected parent: `c7c3d523b7bafe5c73ae4d82275e6f1a297600f0`
- K-01 repair changed exactly `crooks-assistant/tests/test_orchestrator_freeze_spec.py`

Abort and report BLOCKED if the freeze branch no longer resolves to the exact candidate above or if evidence identity cannot be established. Do not carry forward any previous verdict.

### Review objective
Attack the exact candidate rather than confirming the implementer's report. Recompute relevant facts from committed source. Determine whether K-01 is genuinely closed without weakening J-01/H-03/H-04/R-02 or any prior freeze invariant.

Specifically verify:
1. every §3A transition-row mention of `lease.owned_process_group_handle` is structurally/fail-closed classified as WRITES / PROHIBITS_WRITE / READS_ONLY;
2. ordinary paraphrases cannot introduce an operative second write while declared count remains 1;
3. negated/prohibition wording cannot be misclassified as a write, and a real write beside a prohibition cannot be swallowed by the prohibition;
4. unknown/unclassifiable critical wording fails closed;
5. sole derived write point is the declared CREATED -> STARTING point;
6. the seven prior J-01/K-01 mutation cases are independently reproduced and all unsafe variants fail;
7. invent additional adversarial mutations beyond the implementer's exact cases, including sentence/clause rearrangement, alternate grammatical forms, punctuation, and plausible ordinary write language. If a plausible operative write can evade the gate, report it as a material blocker;
8. mutation resistance is structural rather than dependent on literal strings shared by the test and fixture;
9. committed freeze-spec suite and relevant static checks are green;
10. exact diff `c7c3d52..a904a20` is bounded to the one test module and no DECISIONS/adoption/sequence change occurred in the repair.

### Recheck global freeze invariants
Read the exact freeze documents from `a904a20` and adversarially spot-check prior repaired areas, especially:
- J-01 durable occupancy / cleanup-unproven semantics and N+1 refusal;
- H-03 one process group per attempt, write-once durable handle, preflight/model same group, stale/recycled identity fail-closed;
- H-04 reviewer ownership kind and kernel-owned NULL/cleanup semantics;
- R-02 attempt-budget semantics remain separate from occupancy;
- crash consistency, fencing, exact candidate/evidence identity, reviewer independence, no self-adoption.

### Canonical-base movement — read-only reconciliation assessment
Canonical product memory advanced after the repair started and now resolves to `3ba4edeb...`, adding owner product direction including DEC-050. Do **not** rebase, merge, edit, or adopt anything.

Read-only determine:
- ancestry from `9e59860` to current canonical;
- exact overlap between current canonical and the freeze candidate;
- whether a merge/reconciliation is mechanically conflict-free;
- whether any current canonical decision/product direction semantically conflicts with the freeze contract;
- the smallest safe reconciliation path if the freeze receives a clean engineering verdict.

Do not treat base movement alone as an engineering defect in `a904a20` if the exact candidate remains valid against its pinned base. Keep engineering readiness separate from owner adoption/reconciliation.

### Verdict
Return exactly one:
- `ENGINEERING CONTRACT READY — OWNER/RECONCILIATION/RUNTIME GATES REMAIN`
- `CHANGES REQUIRED BEFORE OWNER DECISION`

If changes are required, identify only material blockers with exact evidence and the smallest bounded repair. If ready, explicitly state that the verdict binds only to `a904a209d57add65f3878b4f7ee3eec19b6c35a9` and does not itself adopt/rebase/merge/deploy it.

Also disclose reviewer/provider independence limitations.
