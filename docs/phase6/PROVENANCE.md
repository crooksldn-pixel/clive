# Phase 6 provenance — what is actually here

Written before any code was changed, because the continuation brief describes a body of work
(the Codex Phase 6 implementation) that **this environment cannot see**, and every later claim
depends on being straight about that.

## What was looked for, and what was found

| asked about | result |
|---|---|
| Phase 5 donor `e43aecdb39b87b622f64b6ab434e428d216ef157` | **PRESENT.** `§38: the final gate, measured on the tree being delivered` |
| Tag `crooks-os-v1-phase5-candidate` | **DOES NOT EXIST** — not locally, and `git ls-remote --tags origin` returns nothing. The repository has no tags at all. |
| Codex Phase 6 SHA `663d2a1ccb71ba315830169dbdaf0678fe7437de` | **NOT REACHABLE.** `git cat-file` cannot resolve it; it is on no local or remote branch. |
| Codex checkout `/Users/mrcrooks/Documents/Codex/…` | **DOES NOT EXIST.** That is a macOS path. This session runs in a Linux container with its own fresh clone. |
| `origin/claude/crooks-assistant-mac-local` (the only remote branch that sounded Mac-related) | **Not Codex.** It is an ancestor of the Phase 5 donor — 0 commits ahead — and contains no Swift and no `mac/` tree. Already included. |

The brief itself said the Codex work was **PUSHED: NO**. That is consistent with all of the
above. It is not missing because something went wrong; it is on the owner's Mac and has never
left it.

### What follows from that

I **cannot** inspect the Codex tree, cherry-pick its commits, port its verified pieces, or
judge which of its changes are worth preserving. Any statement in this phase's documents about
Codex code would be repetition of the brief, not observation, so there are none.

The instruction "preserve verified infrastructure, do not preserve its UI as design precedent"
is therefore satisfied vacuously on the preservation half and substantively on the rejection
half: **the rejected visual design is described in §5 of the brief, and those specific faults
are what the redesign is being judged against.** A description of a bad UI is enough to avoid
building it again; it does not require the source.

## What IS here — the real starting point

Branch `claude/crooks-appliance-phase6`, based on exactly `e43aecd`, carrying four merged
workstreams built in this environment:

| | what it is | state |
|---|---|---|
| **A** | the Mac ops layer — `scripts/service.py` (launchd lifecycle), `control.py`, `update.py` | merged |
| **B** | the backend appliance surface — `POST /pad/heartbeat`, the `pad` block on `/health` | merged |
| **C** | **CROOKS Pad — the native Android shell** | merged |
| **D** | CROOKS Control — Swift, split into a Foundation-only core and a SwiftUI view layer | merged, **fixes incomplete** |

Two differences from the state the brief assumes are worth stating plainly:

1. **A CROOKS Pad implementation already exists here.** The brief says the Codex work "does NOT
   contain a CROOKS Pad implementation yet". This branch does: a hardened-WebView Android shell
   with a JVM-testable core, which assembles into a real APK.
2. **Workstream D's fix round never ran.** The previous session's agent run hit the account's
   weekly limit after three of seven agents, so D's four must-fix items and the document-version
   deadlock are open, and **none of the fix round was independently verified**.

## The Node discrepancy §31 asks about — measured, not reconciled on paper

Phase 5 reported **291/291**. Codex reported **139 subtests**.

Measured on this integrated tree, `node --test "tests/web/*.test.js"`:

```
# tests 291   # pass 291   # fail 0   # skipped 0
```

Per file:

| tests | file | | tests | file |
|---:|---|---|---:|---|
| 110 | `ui.test.js` | | 13 | `progressive.test.js` |
| 29 | `collide.test.js` | | 12 | `sw.test.js` |
| 26 | `notify.test.js` | | 10 | `workspaces.test.js` |
| 24 | `touch.test.js` | | 8 | `telemetry.test.js` |
| 24 | `email.test.js` | | 4 | `fold.test.js` |
| 16 | `tabs.test.js` | | | |
| 15 | `action-state.test.js` | | **291** | **total, 12 files** |

**110 + 29 = 139.** `ui.test.js` and `collide.test.js` are the two largest files and their sum
is exactly the Codex figure. So 139 is not a different counting unit and not nested subtests —
it is **a partial run of two files out of twelve**, leaving 152 tests in the other ten
unexecuted. Whatever glob or invocation produced it matched only those two.

That also means the Codex number and the Phase 5 number were never comparable, and a report
placing them side by side as though they measured the same thing was wrong to do so.

## The other number §31 asks about

Phase 5 reported **2 skipped**; Codex reported **8**. The skip list for the final tree is
produced by the final regression run with `-rs` and appears in `PHASE_6_APPLIANCE_REPORT.md`,
where each skip is named with its reason. It is not guessed here.

## One hard environmental limit, stated now rather than at the end

**This machine cannot compile CROOKS Control.** Verified directly: Swift 6.0.3 for Linux
answers `no such module 'SwiftUI'`. There is no macOS SDK and no `xcodebuild`. Therefore §16's
"compile it for real, launch it for real, capture real screenshots" **cannot be done here**, by
me, at all.

What is done instead is stated wherever a screenshot appears, and never described as the
compiled application. See `PRODUCT_DESIGN_SYSTEM.md`.
