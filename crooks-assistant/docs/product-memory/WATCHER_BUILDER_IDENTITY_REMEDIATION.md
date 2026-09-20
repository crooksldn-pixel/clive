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

## 3. Why fast-forward rather than merge/reset

The accepted Builder SHA `295e483...` descends from the old `claude/bridge-builder` state `9a27bc4...`. The previous read-only verification proved that ancestry.

Therefore the intended remote ref change is a **fast-forward only**:

`claude/bridge-builder: 9a27bc4... -> 295e483...`

No merge commit, force push, reset, clean, stash, discarded work or production checkout mutation is part of this plan.

If fresh ancestry verification does not prove a strict fast-forward at execution time, stop and escalate rather than improvising.

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

## 5. Runtime reconciliation procedure — separately authorised execution

Only when no bridge task is in flight and the watcher is drained/stopped for the bounded maintenance window:

1. verify lock free / no active worker / no pending in-progress result;
2. verify `/opt/crooks-builder` clean and exactly at `295e483...`;
3. fetch only the explicit `claude/bridge-builder` and accepted Builder refs; do not use the known-broken `git fetch --all`;
4. re-prove `9a27bc4...` is an ancestor of `295e483...`;
5. fast-forward remote `claude/bridge-builder` to `295e483...` without force;
6. reconcile the local branch to `claude/bridge-builder` using a clean fast-forward-only path that preserves the exact working tree at `295e483...`; if local-ref topology makes that impossible without reset/force, stop and escalate;
7. install only the independently reviewed watcher-source hardening candidate;
8. run watcher tests and `install.sh verify`;
9. restart only `crooks-bridge-watcher.service`;
10. verify service healthy, actual branch equals declared branch, actual HEAD equals expected accepted Builder SHA, lock free/pending state coherent;
11. run a read-only verification inbox before permitting any write-capable task.

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
- remote `claude/bridge-builder` exact SHA = `295e483...` or a later independently accepted Builder successor;
- actual `/opt/crooks-builder` branch = declared unit branch;
- actual builder HEAD = the accepted SHA expected for that round;
- read-only bridge smoke verifies measured branch/HEAD and intended model;
- no production/global/account/connector/credential/business mutation.
