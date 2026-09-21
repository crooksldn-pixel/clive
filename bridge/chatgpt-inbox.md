# CHATGPT INBOX

## Independent adversarial review — Engineering Control Plane VNext Phase 1

Review **exactly** `8588776455a1832da763810064cacb47d7192ef4` on `chatgpt/control-plane-vnext-phase1`.

Resolve the remote branch HEAD first. STOP without verdict if it is not exactly that SHA.

This is **review-only**. Do not patch the branch. This bridge Claude did not author the Phase 1 candidate, so it is eligible to review it; independently verify authorship rather than trusting this sentence.

### Purpose of the candidate

Repository-only Phase 1 foundation for replacing the single-slot/hourly bridge workflow with typed machine-readable control-plane records and policy-validated obvious continuation. It must **not** be treated as a deployed Orchestrator or watcher.

The candidate adds:
- strict task/result/next-action/runtime-state contracts;
- immutable JSON task/result publication for offline simulation;
- guarded mutable task-state transitions;
- generated active engineering state;
- deterministic obvious-continuation policy;
- reviewer-independence and fresh-branch-HEAD binding;
- a deterministic scheduler simulation that can route the obvious next eligible stage immediately, skip an unroutable stream, and provide explicit priority/fairness;
- adversarial tests.

### Review standard

Do not accept ordinary green counts as proof. Re-derive the properties from source and attack them.

At minimum:

1. **Identity / path safety**
   - attempt path traversal in task/result/runtime IDs;
   - malformed SHA, task revision mismatch, stale subject SHA;
   - branch movement after a result;
   - late result from an old task revision.

2. **Obvious continuation authority**
   - a model's `next_action` is suggestion/data, not authority;
   - invalid stage transitions fail closed;
   - owner gates, deterministic blockers, missing evidence, dirty result or out-of-scope edits cannot auto-continue;
   - no new scope/permission/deployment authority is created.

3. **Independent review**
   - repair/build author cannot satisfy an independent review;
   - role routing cannot accidentally select the author when another reviewer is required;
   - identify any gap between a string `worker_id` and a trustworthy controller-issued identity, and judge whether it is acceptable for this *repository simulation* or a material Phase 1 defect.

4. **State / publication**
   - immutable record replay is idempotent and conflicting identity reuse fails;
   - task contract is distinct from mutable runtime state;
   - stale state writers cannot overwrite newer state in the simulated store;
   - current branch truth and obsolete results are represented correctly;
   - inspect whether the JSON compare-and-swap has any misleading concurrency claim. The code should clearly remain an offline/single-process simulation, not claim production multi-process safety.

5. **Scheduler / starvation**
   - an eligible obvious continuation can route without hourly polling;
   - an unroutable/blocked stream does not prevent another eligible stream;
   - least-recently-dispatched fairness works at equal priority;
   - explicit priority behavior is deterministic;
   - no owner-gated or stale task becomes dispatchable through scheduler composition.

6. **Test quality**
   - run the exact targeted test module;
   - run static/lint checks available in the accepted repository environment for these files;
   - mutate or otherwise adversarially invalidate at least reviewer independence, branch-head binding, filesystem identity safety, stale state/CAS, and starvation/fairness, and prove the tests catch the break;
   - invent additional counterexamples beyond the committed test table.

### Known local Director evidence — do not trust without recomputation

A separate local reproduction reported passing behavioral tests and killed mutations for reviewer-self-certification, branch-head drift, scope escape, filesystem identity, stale active state, CAS and fairness. Treat this only as a claim to challenge.

### Verdict

Return exactly one candidate-bound engineering verdict:

- `ACCEPT FOR PHASE 1 REPOSITORY FOUNDATION` if no material repository-only defect remains; or
- `REJECT — REPAIR REQUIRED` with bounded reproducing defects; or
- `BLOCKED` only for a genuine inability to perform the review.

Acceptance means only that this repository-only Phase 1 foundation is sound enough for the next isolated phase. It does **not** authorise watcher/systemd/runtime installation, production deployment, new credentials/secrets, connector/MCP permission changes, privilege expansion, CROOKS/CLIVE business writes, destructive owner-work cleanup, external spend, production merge, freeze adoption, or DEC-046/047 sequencing amendment.
