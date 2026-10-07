# Watcher / Builder Identity Remediation Plan

**Status:** REVIEW CANDIDATE — plan only; no runtime mutation authorised by this document  
**Date:** 2026-09-20  
**Observed live mismatch:** watcher unit declares `claude/bridge-builder`; actual clean builder checkout is `claude/builder-environment-repair@295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`.

## 1. Objective

Eliminate the condition where the bridge prompt states one builder branch while the process actually executes in another checkout identity.

This is a prerequisite for any future **write-capable** unattended worker. Read-only review rounds may continue only when they independently measure and report actual checkout identity.

## 2. Desired steady state

The existing semantic role of `claude/bridge-builder` is retained as the canonical single-worker bridge branch.

Desired identities:

- accepted Builder content: `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`;
- canonical bridge builder branch: `claude/bridge-builder`;
- `/opt/crooks-builder`: clean standalone clone checked out on `claude/bridge-builder` at that same SHA before the next write-capable bridge task;
- watcher unit: continues to declare `CROOKS_BRIDGE_BUILDER_BRANCH=claude/bridge-builder`;
- watcher source: fails closed if actual checked-out branch differs from the declared builder branch or is detached.

This preserves the existing named bridge branch rather than changing systemd configuration to a repair-topic branch.

## 3. Measured remote topology and safe ref recreation

The accepted Builder SHA `295e483...` descends from the former local `claude/bridge-builder` state `9a27bc4...`. Independent read-only review re-proved that ancestry.

The important measured fact is that **`refs/heads/claude/bridge-builder` is currently absent on origin**. The local builder clone still has a local `claude/bridge-builder` ref at `9a27bc4...`, and its configured fetch refspec still names the now-absent remote ref. Therefore the required remote operation is **not a fast-forward of an existing remote ref**; it is a guarded create of that ref at the already accepted Builder SHA.

The safe intent is:

`remote absent -> guarded create refs/heads/claude/bridge-builder at 295e483...`

The ancestry proof justifies reusing the semantic branch name; it is not relied on as remote fast-forward protection.

The create MUST be compare-and-swap guarded so it fails if the remote ref appears between observation and publication. A suitable shape is a create-only lease such as `--force-with-lease=refs/heads/claude/bridge-builder:` (empty expected remote value) or an equivalent API conditional-create. This permits creation only while the ref is still absent; it MUST NOT force-update an existing unexpected remote ref.

No merge commit, reset, clean, stash, discarded work, production checkout mutation or blind ref overwrite is part of this plan.

If fresh verification finds the remote ref already exists, the local old ref is not the expected `9a27bc4...`, ancestry no longer holds, or any compare-and-swap guard cannot be established, stop and escalate rather than improvising.

## 4. Source hardening required before runtime reconciliation

The watcher source must gain a deterministic preflight in `target_is_safe()`:

1. measure actual branch with `git symbolic-ref --quiet --short HEAD`;
2. fail closed on detached HEAD;
3. compare actual branch exactly to `$BUILDER_BRANCH`;
4. fail closed on mismatch and report both values;
5. measure actual HEAD and include it in launch/status evidence;
6. preserve all existing production-path, linked-worktree, foreign-process and dirty-tree guards.

A branch name remains routing metadata, not proof of code identity. Each task/review still measures actual HEAD independently.

### Required watcher regression tests

- expected branch + clean standalone builder -> allowed;
- different branch at same SHA -> refused;
- different branch at descendant SHA -> refused;
- detached HEAD -> refused;
- branch check does not weaken production-path/linked-worktree/dirty-tree/foreign-Claude guards;
- installer/verify source-runtime equality remains green.

### Required remediation rehearsal before live execution

Before the live maintenance window, rehearse the Git-ref procedure against a scratch remote and scratch clone that reproduce the current topology:

- remote `claude/bridge-builder` absent;
- local `claude/bridge-builder` present at the ancestor SHA;
- accepted Builder SHA available through an existing remote ref;
- configured fetch refspec narrowed to the absent `claude/bridge-builder` ref.

The rehearsal MUST prove:

1. the documented sequence completes without `fatal: couldn't find remote ref`;
2. the guarded create is rejected if the remote ref appears at any unexpected SHA before publication;
3. no remote force-update, reset, clean or stash is used;
4. the checked-out Builder tree at `295e483...` is byte-identical before and after local branch reconciliation;
5. after the remote ref is created, the existing narrowed fetch refspec becomes valid without an unrelated Git-config rewrite.

Rehearsal evidence is required before this plan may be cited as executable runtime-remediation evidence.

## 5. Runtime reconciliation procedure — separately authorised execution

Only when no bridge task is in flight and the watcher is drained/stopped for the bounded maintenance window:

1. verify lock free / no active worker / no pending in-progress result;
2. verify `/opt/crooks-builder` clean and exactly at `295e483...`;
3. verify by remote readback that `refs/heads/claude/bridge-builder` is still absent; fetch the **existing** accepted Builder ref explicitly (for example `refs/heads/claude/builder-environment-repair-review`) with an explicit refspec, and do not invoke the known-broken configured fetch path before the missing ref is recreated;
4. re-prove the local `claude/bridge-builder@9a27bc4...` is the expected old semantic ref and that `9a27bc4...` is an ancestor of accepted `295e483...`;
5. create remote `refs/heads/claude/bridge-builder` at `295e483...` with a create-only compare-and-swap guard that requires the remote ref to still be absent; if the ref has appeared, stop and escalate rather than overwriting it;
6. explicitly fetch the newly created `claude/bridge-builder` ref and verify remote readback equals exactly `295e483...`; at this point the builder clone's existing narrowed fetch refspec is valid again and no unrelated Git-config rewrite is required;
7. move the **local ref only** from `9a27bc4...` to `295e483...` with an expected-old compare-and-swap (for example `git update-ref <ref> <new> <expected-old>`), then switch the clean checkout from `claude/builder-environment-repair` to `claude/bridge-builder`; verify the working-tree bytes and HEAD remain exactly `295e483...`; if this cannot be done without reset/clean/stash or an unguarded ref rewrite, stop and escalate;
8. install only the independently reviewed watcher-source hardening candidate;
9. run watcher tests and `install.sh verify`;
10. restart only `crooks-bridge-watcher.service`;
11. verify service healthy, actual branch equals declared branch, actual HEAD equals expected accepted Builder SHA, lock free/pending state coherent;
12. run a read-only verification inbox before permitting any write-capable task.

No production application, secrets, account/global Claude config, connectors, privileges or business state changes are in scope.

## 6. Freeze relationship

The V1 **specification** may describe this remediation before the live repair is executed, but:

- no V1 Phase 1 model worker may launch until the live mismatch is corrected and independently verified;
- no existing bridge write-capable implementation round should be dispatched while the mismatch persists;
- the exact reviewed watcher hardening candidate SHA and the later runtime-verification evidence must be recorded before this prerequisite is marked closed.

Phase 0 repository-only deterministic-kernel work does not depend on the existing watcher branch identity.

## 7. Acceptance evidence

Closure requires all of:

- watcher-source candidate exact SHA;
- focused watcher tests pass;
- full watcher suite remains green;
- source/runtime installer verification green;
- remote `claude/bridge-builder` was absent immediately before the guarded create, and exact post-create readback = `295e483...` or a later independently accepted Builder successor;
- actual `/opt/crooks-builder` branch = declared unit branch;
- actual builder HEAD = the accepted SHA expected for that round;
- read-only bridge smoke verifies measured branch/HEAD and intended model;
- scratch rehearsal evidence proves absent-ref handling, guarded-create refusal on a raced/unexpected ref, and byte-identical local reconciliation;
- no production/global/account/connector/credential/business mutation.
