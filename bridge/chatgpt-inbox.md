# CHATGPT INBOX

## P0 recovery task — resume useful engineering immediately

Fresh owner direction: resume useful CLIVE engineering now. Do not spend this round merely re-reporting the existing reviewer-routing blocker.

Resolve fresh remote Git truth first. The last observed facts are:
- control-plane candidate `e8830c44bcae917b7c711b081a8adf003832bc9d` is still UNACCEPTED because no eligible independent principal has reviewed it;
- progress branch `22b8afe356decf61f19fbc5d94170f17a5139db0` must remain unreconciled until that acceptance exists;
- capability-registry candidate `6a522f8f42bf8664fc966152e3f0ea61aa241c81` and V0.5 `33968c92660032104ed75a49dd96df8e63b29a07` are separate streams and must not be overwritten.

This round is IMPLEMENTATION, repo-only, isolated, and must advance an unblocked P0 item.

### Primary objective: repository CI + provenance acceptance machinery

Create a fresh isolated branch/worktree for a bounded CI/provenance candidate. Do not modify the existing e8830c44 branch in place and do not imply that candidate is accepted.

Implement the smallest useful repository CI/acceptance layer that is missing today:

1. Add GitHub Actions workflow(s) under `.github/workflows/` for the CLIVE repo.
2. Bind every acceptance run to the exact commit SHA being tested and surface that SHA in machine-readable evidence.
3. Run the existing applicable gates rather than inventing prose parsers:
   - Ruff/static checks;
   - targeted control-plane tests;
   - appropriate bounded/full offline pytest evidence;
   - pinned secret scan/gitleaks where already supported;
   - structural product-memory consistency checks, including a guard against literal escaped-newline corruption in canonical Markdown;
   - existing targeted mutation/regression checks for allowed_paths, owner_gate and blocker_class where practical.
4. Add or isolate the already-disclosed missing single-signal regression for `TaskRuntimeState.status` if it can be done cleanly without altering policy semantics.
5. Ensure CI fails closed on test failure, scan failure, malformed evidence, or candidate-SHA mismatch.
6. Produce a concise machine-readable provenance/acceptance artifact or script output that records at minimum: candidate SHA, workflow/run identity if available, test/static/scan results, and acceptance eligibility state. Do not encode human approval into ActionStatus.

### Secondary objective if primary completes cleanly in this same round

If and only if the CI/provenance candidate is committed, pushed, and its local/offline evidence is green, continue with a bounded repository-only reviewer-routing skeleton on the SAME isolated candidate branch:
- represent author principal and reviewer principal separately;
- represent fresh session/context and workspace identity;
- exact candidate SHA binding;
- reviewer candidate must be read-only from the acceptance path;
- same-principal self-review and same-principal fresh-session review must be structurally ineligible for final acceptance;
- cognitive diversity is separate metadata, not a substitute for operational independence;
- add focused tests that kill author==reviewer and candidate-SHA drift.

Do not attempt to obtain an independent acceptance from this same Claude principal. The goal here is to build the routing/provenance machinery that will make that possible later.

### Continuation rule

A blocker on one sub-item is NOT a reason to stop the whole round. Park only the blocked sub-item and continue every other safe repo-only item above. Do not return an outbox whose substantive result is only "still blocked" if any unblocked work remains.

### Required completion evidence

Before reporting:
- push the isolated candidate branch;
- report exact branch + SHA;
- report files changed;
- report exact commands and pass/fail counts;
- report any known pre-existing failures separately;
- report what remains blocked and the next unblocked repo-only action.

### Hard boundaries

No production deploy/promotion. No systemd/watcher/runtime modification. No business writes. No secrets/credential reads. No account/global Claude changes. No connector/MCP permission changes. No privilege expansion. No public exposure. No external spend. No destructive cleanup. No production merge. No owner-only adoption/authority change.

Preserve the parked prose-freeze/parser loop. Do not restart it.
