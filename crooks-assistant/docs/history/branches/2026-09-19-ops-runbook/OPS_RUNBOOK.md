# CROOKS OS — Operator / Bridge Recovery Runbook

**Status:** ACTIVE operational guidance  
**Created:** 2026-09-19  
**Purpose:** preserve repeatable operator shortcuts and hard-won recovery lessons without turning one incident into permanent architecture.

This file is for server-side engineering operations, bridge recovery, builder-environment diagnosis, and mobile SSH workflows. It is not a deployment approval and does not supersede `CURRENT_TRUTH.md`, `PRODUCT_BRAIN.md`, `EVOLUTION_POLICY.md`, or active safety decisions.

## 1. Non-negotiable workspace rule

Never run two mutable engineering agents in the same checkout.

- Production checkout is not an autonomous worker checkout.
- Normal bridge builder: `/opt/crooks-builder`.
- One worker = one task = one isolated mutable workspace = one branch = one result.
- A held bridge lock is evidence that a run is already active. Do not start another Claude in that builder tree.
- A dirty builder tree is treated as an anomaly until inspected. Do not reset, stash, commit, or bypass the guard casually.

## 2. Recovery lesson: useful build + failed publication

Observed real failure mode on 2026-09-19:

1. Claude did substantial Mobile Experience V1 work.
2. Worker exited before a valid bridge outbox was published.
3. Candidate remained as uncommitted work in `/opt/crooks-builder`.
4. Watcher correctly refused subsequent runs because the tree was dirty.
5. The correct recovery objective was to preserve and resume the exact candidate, not rebuild it from scratch.

This is a required Engineering Orchestrator V1 acceptance case:

> successful or valuable worker output + failed publication must be recoverable without destructive reset or unnecessary rebuild.

Future orchestrator behaviour should include candidate identity, persistent task state, heartbeat/lease, resumable publication, evidence preservation, stale-worker detection, and explicit recovery transitions.

## 3. Bridge status shortcuts

Canonical bridge status:

```bash
/opt/crooks-bridge-watcher/bin/crooks-bridge-watcher status
```

Useful interpretations:

- `pending YES` + `lock HELD` = a run is currently in progress.
- `pending YES` + `lock free` = work is waiting but no active run owns the lock.
- `last run failed` can describe the preceding run while a newer run is still active; do not infer current failure from that line alone.

Who holds the lock:

```bash
fuser -v /run/crooks-bridge/watcher.lock
```

Inspect a known Claude process:

```bash
ps -o pid,etime,stat,%cpu,%mem,wchan:32,cmd -p <PID>
pstree -ap <PID>
```

Check whether Claude has already written the bridge handoff:

```bash
git -C /opt/crooks-ai-bridge status --short -- bridge/claude-outbox.md
```

## 4. Dirty-tree recovery rule

The watcher has an explicit escape hatch:

`CROOKS_BRIDGE_ALLOW_DIRTY=1`

It must remain OFF by default.

Use it only after a person/director has inspected the exact dirty candidate, confirmed the work is the intended stranded task, confirmed no competing Claude is in the checkout, and deliberately chosen resume/finalise over reset/rebuild.

When resuming a task-specific branch, also set `CROOKS_BRIDGE_BUILDER_BRANCH` to the actual preserved branch so the watcher prompt does not describe the wrong branch.

Do not turn the dirty-tree override into normal operation. The underlying orchestrator should eventually model recovery explicitly instead.

## 5. Builder browser environment: verified paths

The Builder tooling currently uses project-local Node/Playwright and browser assets rather than the old global defaults.

Verified Node module path:

```bash
/opt/crooks-builder/.tooling/node/node_modules
```

Verified Chromium path:

```bash
/opt/crooks-builder/.tooling/browsers/chromium-1194/chrome-linux/chrome
```

For manual verification shells, the relevant environment is:

```bash
NODE_PATH=/opt/crooks-builder/.tooling/node/node_modules
CROOKS_CHROMIUM=/opt/crooks-builder/.tooling/browsers/chromium-1194/chrome-linux/chrome
```

Do not assume a fresh login shell has those exports.

This incident exposed a Builder Environment defect: the environment could contain Playwright and Chromium while `experience.browser.available()` still failed because the exports were absent.

## 6. Chromium host dependencies

A fresh Linux host may have the browser binary but still be unable to launch it because runtime libraries are missing.

Observed missing dependencies included NSS/NSPR, ATK/AT-SPI, CUPS, Xdamage, Cairo, Pango and ALSA libraries.

The Playwright-supported host dependency install used successfully was:

```bash
/opt/crooks-builder/.tooling/node/node_modules/.bin/playwright install-deps chromium
```

This should become part of a correct, idempotent Builder bootstrap/doctor path rather than a recurring manual repair.

A minimal Playwright launch test is more useful than rerunning the entire browser suite when diagnosing browser startup.

## 7. Mobile candidate verification incident

After the correct Builder environment was reconstructed, the full browser gate executed rather than skipping:

- 715 checks ran.
- 714 passed.
- 1 failed.
- The remaining failure was the previously known `Split` 95 ms touch-path check.

This did not by itself establish product acceptance. The owner has separately decided the Split feature should be retired in the later mobile cleanup, so stale Split-specific tests must not become a permanent constraint on the redesigned product.

**Updated 2026-09-19T10:33Z — do not carry the "1 failed" figure forward as current.** On the published candidate `564ef34` the sweep is 714 checks with 0 failures, and the Split check has now passed in three independent sweeps, including the exact step originally recorded as deterministic. The failure is attributed to `hop()`'s fixed 4.3s settle budget in `scripts/browser/clickpath.js` under CPU contention — a property of the machine, not of the tree — and is deliberately **not** fixed, because widening a harness timeout changes what the gate measures and belongs in its own reviewed step. While it remains, a full-sweep result from a loaded machine is ambiguous. The count also changed for a benign reason: `mobile.js` joined the default sweep tuple, so the total moved from 593 to 714.

The incident is valuable mainly because it proved the environment/recovery path and exposed the publication failure mode.

## 8. tmux + Termius operating pattern

A persistent tmux session is preferred for phone-based server work because it survives mobile disconnects and app restarts.

Current convention:

```bash
tmux new -s crooks-dev
tmux attach -t crooks-dev
```

Detach from tmux:

- press `Ctrl+B`,
- release,
- press `D`.

Do not type the words `ctrl b` into the shell.

Recommended persistent monitor window:

```bash
tmux rename-window monitor
watch -n 5 /opt/crooks-bridge-watcher/bin/crooks-bridge-watcher status
```

Use a second SSH session or a separate tmux window for inspection commands; leave the monitor running.

## 9. Termius AI Coding Mode

Preferred CROOKS Builder project folder:

```text
/opt/crooks-builder
```

AI Coding Mode is a launch/convenience layer. It does not replace the CROOKS Engineering Orchestrator or its isolation/review/recovery responsibilities.

Never launch an interactive Claude Code session through Termius AI Coding Mode while:

- bridge status says `lock HELD`, or
- another Claude process is already working in `/opt/crooks-builder`.

Preferred long-term use: AI Coding Mode opens the right project and agent quickly; tmux preserves interactive sessions; the Engineering Orchestrator should eventually eliminate routine owner terminal babysitting entirely.

## 10. One-step operator discipline

During live server/deployment/recovery work, give the owner exactly one command/action at a time unless the owner explicitly asks for the full sequence.

For each step:

1. state the exact command/action,
2. state what success looks like,
3. stop and inspect the result before proceeding.

This reduced the risk of destructive actions while diagnosing the stranded mobile candidate.

## 11. What not to preserve as doctrine

Do not fossilise:

- a specific PID,
- a temporary retry count,
- a transient branch SHA,
- the current Split implementation,
- a manual workaround that the Builder bootstrap/orchestrator should subsume.

Preserve the failure mode, recovery contract, verified environment facts, useful shortcuts, and safety boundaries.
