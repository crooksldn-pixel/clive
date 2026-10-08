# Browser gate, revived — and the one check that fails

**Date:** 2026-09-18/19
**Tree:** `claude/bridge-builder` at `e43aecd` (product source **unmodified** by the round that
found this)
**Environment:** Chromium 141.0.7390.37, Playwright build **1194**, Playwright 1.56.1

---

## What happened

The CROOKS browser gate had never run on this server: Playwright and Chromium were absent and the
builder had no `.venv`, so `experience.browser.available()` returned false and every browser check
reported itself *skipped*. Honest, but it proved nothing.

With the environment in `docs/DEV_ENVIRONMENT.md` in place, the gate runs. Two full runs:

| Run | Conditions | Total checks | Failed |
|---|---|---|---|
| 1 | under CPU contention (a scan running alongside) | 593 | 1 |
| 2 | quiet machine | 593 | 1 |

**Same count, same single failure, both times.** This is not a flake and not contention.

For reference, the baseline recorded in commit `721a31c` was *"592 checks, 4 failed, and all four
are the named-MISSING shots"*. These runs passed no output directory, so no screenshots were
written (`shots: 0`) and the four named-MISSING shot checks did not run — which accounts for the
different total. The four known failures are therefore **absent** here, and a different one is
present.

---

## The failure

```
PATH 4-split-two-halves-independent · step 2 · a 95ms press on Split lands

  "Split" had to be activated directly for the path to continue
  — it is wired, the touch did not reach it
```

The harness says precisely the right thing: the control **is** wired — activating it
programmatically works and the path continues — but a synthetic 95 ms press at its coordinates did
not reach it.

## Why this one matters more than an arbitrary failing check

This is the **same bug class** that produced the worst field defect in the product's history, and
on the same control.

From the layer-order commentary in `web/style.css` (and `DESIGN.md` §9.2): `#branch-bar` — Split,
Merge, Close — sat inside a stacking context while `#talk` was a sibling at `z-index: 3` with
`inset: 0`, i.e. a transparent, viewport-sized button painted over every branch control. **63 taps
in one evening, 26 of them in ten consecutive seconds, went to the speech recogniser instead.** The
owner reported it twice. The layer table exists because of it.

A check that says *a press on Split does not land* is exactly the alarm that table was installed
to trip.

## What is NOT claimed

- **Not a regression introduced by this round.** The round that found it changed no product
  source — its diff is `.gitignore`, `DESIGN.md`, `docs/`, and `scripts/dev_env.py`. The behaviour
  is in the tree as delivered.
- **Not yet attributed.** It has not been determined whether this is (a) a live defect on the
  device, (b) specific to Chromium 141 / this synthetic-press path, or (c) a pre-existing failure
  that earlier baselines did not surface. Two runs establish that it reproduces; they do not
  establish the cause.
- **No fix attempted.** The brief for this round forbade UI changes.

## Suggested next step

Reproduce narrowly and attribute, before anything is changed:

1. Run `scripts/browser/touch.js` and the split path alone, with a screenshot at the moment of the
   press.
2. At the press coordinates, ask the page `document.elementFromPoint(x, y)` — if the answer is
   `#talk` or any `.branch-zone` ancestor, it is the layer defect again and `DESIGN.md` §9.2 needs
   an entry, not just a fix.
3. Vary the press duration around 95 ms. If a longer press lands, this is the hold/tap threshold in
   `web/touch.js` rather than layering.
4. Only then decide whether it is a product defect or a harness artefact.
