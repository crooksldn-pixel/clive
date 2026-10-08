# CROOKS Mobile Experience V1 — what a phone was doing, and what it does now

**Date:** 2026-09-19
**Tree:** `claude/mobile-experience-v1`, from `claude/bridge-builder` at `9a27bc4`
**Environment:** Chromium 141.0.7390.37, Playwright 1.56.1 (build 1194), the builder worktree
only. No live Shopify, Gmail or ElevenLabs call was made; the whole of the evidence below is
the fixture world on loopback.

**Scope:** `crooks-assistant/web/` — one stylesheet, plus a new browser gate and its tests.
**Not** a redesign, not a separate mobile product, and not one line of backend, action,
proposal or speech semantics.

---

## 0. The one-sentence version

CROOKS had a phone viewport in its verification matrix (`DESIGN.md` §13) and **no gate that
had ever rendered a pixel at it**, so what the product did on a phone was an opinion. The
page's own collision engine, asked at 390 × 844 for the first time, reported **32 interactive
collisions across eight surfaces**; it now reports **0**, and a new gate keeps it there.

---

## 1. Method

The instruments are the ones that already existed. Nothing here is a new opinion about phones:

1. Read `PRODUCT_BRAIN.md`, `DECISIONS.md`, `PHASE_1_UX_BASELINE.md`, `DESIGN.md`,
   `ENGINEERING_LOOP.md`, `docs/DEV_ENVIRONMENT.md` and `docs/dev-environment/BROWSER_GATE_FINDING.md`
   before touching a rule.
2. Captured BEFORE evidence at five viewports against the real fixture backend.
3. Ran `window.CrooksCollide.scan()` — the page's own engine, the one `collision.js` runs at
   601 and 800 — at 390 × 844 and 375 × 667.
4. Implemented, re-measured, and wrote the measurements into the stylesheet beside the rules
   they justify.
5. Added `scripts/browser/mobile.js` to the default browser sweep so none of it can regress
   silently.

**Authority order was kept.** Where a general web convention conflicted with CROOKS intent, the
convention lost and the conflict is reported rather than resolved in silence — see §6.1.

---

## 2. What the phone was doing (BEFORE)

Measured on the unmodified tree. Screenshots: `docs/screens/mobile-v1/before-*`.

| Viewport | Interactive collisions (8 surfaces) | Elements off the viewport | Controls under 44px |
|---|---|---|---|
| 390 × 844 @3 | **32** | 75 | 0 |
| 375 × 667 @2 | **32** | 83 | 0 |
| 601 × 889 @1.33 | 0 | 6 | 0 |
| 800 × 1280 @1 | 0 | 0 | 0 |
| 1280 × 800 @1 | 0 | 0 | 0 |

The same instruments at the tablet's two sizes report zero. The phone was not a little worse
than the tablet; it was a screen the product had never been measured on.

### 2.1 Two of the four ways into the shop were half a control

The dock asked for **476px on a 390px screen**: four 52px areas, a 200px hold slot, four 10px
gaps, 28px of padding. Orders sat at **x = −29** and Products ended at **x = 419**.

The collision engine's own words, on every surface, twice:

```
control_clipped_by_container  button.dock-btn  "29px off the side — fixed furniture must fit the screen"
```

And it was not cosmetic. A 95 ms CDP press at the Orders icon's measured centre — x = −3 —
**posted nothing at all**. Two of the four business areas could not be reached with a thumb.

### 2.2 The voice layer was painted over the navigation layer

`--hold-w` narrowed to 200px in the phone media query. `.talk-label` did not: it kept
`min-width:240px`. So the pill was drawn **10px over the Inbox icon and 10px over the Sales
icon**:

```
button_over_navigation  span#talk-label  ×  button.dock-btn  w:10 h:56   (twice, every surface)
```

That is layer 5 over layer 3 in `DESIGN.md` §9.2 — **D-1's rule and D-1's shape**, on the same
kind of control, five rows apart in the table and touching anyway. The layer table is kept by
geometry, and on a phone the geometry did not hold.

### 2.3 The invitation to divide was off the screen

The navigation rail wanted 468px of chips in 354px of container. Split was reported **72px off
the side** and the open-set chip was entirely past the right edge. The rail scrolls, so nothing
was clipped in the document's terms — but `control_clipped_by_container` counts a navigation
chip as fixed furniture on purpose: *"nothing on the glass says a navigation strip continues
past the edge of the screen."*

### 2.4 The card header read across a screen that has no across

At 390 the identity column is ~250px of a 358px card, because the money and the state badges
hold the other 110px beside it. `Alexandra Featherstonehaugh-Wallingford` came out on **four
lines, broken mid-word twice**.

---

## 3. What changed, and why each one

Every change is in `web/style.css` and every one is scoped by a media query except the three
marked **all sizes**. The measurement that justifies each is written into the sheet beside it.

| # | Change | Why |
|---|---|---|
| 1 | **The dock band stacks on a phone** (`max-width:560px`, context mode): four areas on the upper row, the hold across the whole of the lower one. Same 112px. | The band cannot get wider, so the arrangement changes instead of the sizes. The NAVIGATION/VOICE separation §8 requires becomes **vertical** — bought with geometry exactly as before. Fixes §2.1 and §2.2 together. Labels come back with the space: a cube and a luggage tag are not self-evident. |
| 2 | **The hold pill is bought from its slot** (all sizes): `min-width:240px` → `min-width:0; width:100%; max-width:240px`. | A width taken from the slot cannot exceed the slot, whatever the slot becomes. At 601 and 800 the arithmetic is identical (`min(252, 240) = 240`). This is §2.2's mechanism removed, not just its symptom. |
| 3 | **Safe areas become tokens** (all sizes): `--safe-t/r/b/l`, and `.dock` / `.talk` carry the bottom inset in their height instead of subtracting it. | Two reasons, and the second matters more. `.app` reserved `--dock + inset` while `.dock` was `--dock` tall with the inset taken **out** of it: on a notched phone the band was 34px shorter than its own reservation. And **`env()` cannot be set from a test** — which is why nothing in this repo had ever checked a notch or a home indicator. A custom property can. |
| 4 | **The navigation rail wraps on a phone** instead of scrolling out of reach, and the "there is more this way" fade goes with the scroll. | §2.3. Wrapping is conditional by construction: a rail whose chips fit stays one row, and 601/800 never reach the block. |
| 5 | **The card header stacks on a phone.** | §2.4. The **order** of the answer is unchanged — who and which record, then how much and what state. Only the axis changes, because down is the direction a phone has room in. |
| 6 | **The keyboard, on a phone** (`max-width:560px and max-height:520px`): the four dock areas stand down, the rail stops wrapping and sheds Split and the trail chips, the orb's 44px dot goes. | 390 × 844 becomes 390 × ~508 with the keyboard up, where both small-screen blocks meet and their arithmetic does not survive it: a 76px band in two rows is 34px over 42px, and nothing here has ever been under 44px. **This is the change most in need of owner judgement — see §7.** |
| 7 | **`.deck{min-height:0}` when the keyboard is open** (`max-height:520px`, all widths). | A 72px floor the column cannot honour is not a short deck, it is a deck that **overflows** — painted out under the fixed band. Measured at 375 × 313: the compose card's subject field at y 232–278 with the band starting at 237, so `#talk-label` was drawn **27px across the field being typed into**. The deck scrolls; a short deck is an interaction and a card under the furniture is a defect. |
| 8 | **`.rail-more` 32px → 44px** (all sizes). | §6 says every control is at least `--tap` high and the collision gate enforces 44 with **no tolerance** — and had never seen this one, because its fixtures are rendered payloads and the disclosure only exists on a rail built from a real order. It costs no height: the control sits in a flex row beside 44px rail chips. |
| 9 | **`--ink-3` `#83827c` → `#8a8983`** (all sizes). | axe-core measured 4.26:1 against a raised tile at 10px; AA wants 4.5. `#8a8983` is 4.68:1 there and 5.74:1 on the ground. Moved on the **token**, per §3.2, because every metadata label on every raised tile failed the same way. |
| 10 | **`.rows.tight .row{padding:9px 0}` → explicit top/bottom** (all sizes). | The shorthand reset the 26px `.row.tappable` reserves for its chevron, so the chevron was drawn **9 × 18px into the row's own right-hand column** — "1h ago" read "1h ag›" on every tight list. Identical at 390, 375, 601 and 800: **not a phone defect**. |
| 11 | **`88vh` → `88dvh`, `26vh` → `26dvh`** (all sizes). | `vh` is the large viewport and ignores a collapsing address bar, so an 88vh sheet in a browser tab puts its Done button under the browser's own chrome. In the installed PWA the units are identical, so the tablet pays nothing. |
| 12 | **`scroll-padding-block:6px` on `.cards`.** | Where the browser puts a field it has just given focus to. 6px and not more: the padding comes off both ends, and the shortest deck behind a keyboard is 63px with a 48px field in it. |

**What was deliberately NOT changed:** no JS product source, no HTML, no backend, no renderer.
The candidate is `web/style.css` plus the new gate and its tests. One `web/app.js` change was
written and **reverted** — a `focusin` handler to re-centre the focused field, which measured
as a no-op (scrollTop unchanged at 154, twice). Dead code is worse than an honest gap; the room
was the problem and change 6 is what fixed it.

---

## 4. AFTER, measured

Screenshots: `docs/screens/mobile-v1/after-*`.

### 4.1 The audit, same eight surfaces, same five viewports

| Viewport | Collisions before → after | Off-viewport before → after | Controls <44px |
|---|---|---|---|
| 390 × 844 @3 | **32 → 0** | 75 → 9 | 0 → 0 |
| 375 × 667 @2 | **32 → 0** | 83 → 9 | 0 → 0 |
| 601 × 889 @1.33 | 0 → 0 | 6 → 6 | 0 → 0 |
| 800 × 1280 @1 | 0 → 0 | 0 → 0 | 0 → 0 |
| 1280 × 800 @1 | 0 → 0 | 0 → 0 | 0 → 0 |

No page errors at any viewport. The tablet and desktop columns are **unchanged**, which is the
non-regression claim stated as a number.

The nine remaining off-viewport elements at each phone size are the card's tab strip (§6.2) and
are the same behaviour the tablet has.

### 4.2 The new gate, `scripts/browser/mobile.js`

Run against both trees, same script, same machine:

| Tree | Checks | Failed |
|---|---|---|
| pre-change (`9a27bc4`) | 122 | **62** |
| this candidate | 122 | **0** |

Six of the 62 are checks that **cannot run** on the pre-change tree rather than defects: with
`env()` written inline there is no way to give the page an inset, so the three safe-area checks
report the absence of the instrument. The other 56 are the product.

The gate presses with CDP touch events at measured pixels, opens a real order from the real
fixture backend, divides the orb, sets an iPhone's notch and home indicator, opens the
keyboard, and emulates `prefers-reduced-motion`. It is in `run_checks`' default sweep and its
check names are guarded in `tests/test_browser.py`, so a run that quietly stops measuring a
viewport is a failure and not a smaller green number.

### 4.3 Accessibility (axe-core 4.11.1, WCAG 2.0/2.1 A + AA + best-practice)

Four viewports × three surfaces, before and after:

| | Before | After |
|---|---|---|
| Violation entries | 44 | **40** |
| `color-contrast` (serious) | 15 nodes | **0** |
| `aria-allowed-role` (minor) | 24 nodes | 24 nodes |
| `list` (serious) | 8 nodes | 8 nodes |
| `meta-viewport` (moderate) | 12 nodes | 12 nodes |
| `page-has-heading-one` (moderate) | 12 nodes | 12 nodes |

Every remaining finding is **identical at all four viewports**, so none is phone-specific and
none is a regression introduced here. They are carried in §6 with a proposed fix each.

---

## 5. Non-regression

| Gate | Before | After |
|---|---|---|
| Full browser sweep (`experience.browser.run_checks`) | 593 checks, 1 failed | **714 checks, 0 failed** |
| Python suite (`pytest`) | — | **2827 passed, 4 skipped, 0 failed** |
| Collision gate at 601 × 889 and 800 × 1280 | 0 interactive | 0 interactive |
| Touch gate | unchanged | unchanged |
| Density | unchanged | unchanged |

The sweep grew by 121 checks, which is `mobile.js` joining the default tuple, and the one
pre-existing failure — the Split press, §5.1 — **did not reproduce**.

### 5.0 One test this candidate broke, found on re-measure and fixed

`tests/test_compose.py::test_the_hold_surface_is_not_over_the_composer` asserted the band's
height as the literal string `height:var(--dock)`. Change 3 makes it
`height:calc(var(--dock) + var(--safe-b))`, so the assertion went stale and the suite was **red**.
The parallel assertion in `tests/test_touch.py` had been updated for the same change and this one
had not — an inconsistently-carried edit, not a second opinion about the layout.

The invariant it guards is intact and is now **tighter than it was**. What the test exists to
prove is that the hold surface is a band along the bottom and never over the composer. `.app`
reserves `calc(var(--dock) + var(--safe-b))` for that band; the band used to be `--dock` tall with
the inset taken *out* of it, so on a notched phone it was 34px **shorter** than its own
reservation and left a strip of dead ground. The two are now one number. Where there is no inset
— the tablet, the desktop, every viewport in §13 but the phone — `--safe-b` is `0px` and the
arithmetic is identical to the old rule.

The assertion was updated to match, and a second one added: that the band's height and `.app`'s
reservation are the same expression. A string equality that can drift silently was replaced with
the pairing that actually carries the safety property.

### 5.1 The Split-control finding: attributed, not a product defect

`docs/dev-environment/BROWSER_GATE_FINDING.md` recorded one deterministic failure:

```
PATH 4-split-two-halves-independent · step 2 · a 95ms press on Split lands
```

**It was reproduced, and it is a harness artefact under load, not a defect in the control.**

Evidence, in order:

1. **In isolation it lands, 5 times out of 5.** A narrow reproduction drives the exact hop —
   the Orders dock button, then a 95 ms CDP press at the Split chip's measured centre — and
   every attempt posts `/branches/fork` and takes the branch count from 1 to 2. Press durations
   of 95, 95, 140, 220 and 400 ms all land, so it is **not** a hold/tap threshold in
   `web/touch.js`.
2. **Nothing is painted over it.** `document.elementsFromPoint` at the press coordinates
   (407, 179) returns `button.chip → nav#context-nav → section#context → main#stage → div#app →
   body`. The top element **is the Split chip**. `#talk` is not in the chain, and no
   `.branch-zone` ancestor caps it. The page's own touch machine classifies a press there as
   `{control:true, voice:false, approval:false, scroll:false}`. **This is not D-1 returning.**
3. **The chip does not move between measurement and press.** Its rect is `[366,157 82×44]` at
   `locate()` and `[366,157 82×44]` 500 ms later; the rail's `scrollLeft` is 0 both times and
   `scrollWidth === clientWidth === 571`, so the rail is not scrolling under the press.
   `pointer-events` is `auto`, `scroll-behavior` is `auto`.
4. **`clickpath.js` alone passes: 38 checks, 0 failed.** The failure appears only in the full
   sweep, where twelve browser scripts run in sequence against one backend.
5. **On the verification run it did not reproduce at all** — not in isolation (38 checks, 0
   failed) and **not in the full sweep either** (714 checks, 0 failed), where it had previously
   been deterministic. `PATH 4-split-two-halves-independent · step 2 · Split → 2 halves`
   **passed**, along with all nine steps of the path.

   This is the strongest evidence in the list and it points the same way as the other four. A
   hit-target, layering or `pointer-events` defect is a property of the tree, and the tree did
   not change between the run that failed and the run that passed. A settle budget under CPU
   contention is a property of the **machine**, and that did change. A finding that survives one
   sweep and vanishes from the next was never deterministic; it was load-dependent, and
   `BROWSER_GATE_FINDING.md` recorded the load it was under rather than a defect.

**Conclusion.** The control is reachable, correctly layered and correctly classified. What
fails, when it fails, is `hop()`'s 4.3 s settle budget in `scripts/browser/clickpath.js` under
the CPU contention of the full sweep: the fork is posted and the redraw has not landed inside
the budget, so the harness reports UNREACHED and delivers the activation directly.

**It is therefore not fixed and not "fixed by this candidate" either** — nothing here touches
it, and the green above should not be read as a repair. The flake is still in the harness and
will return on a loaded machine.

**No fix is included, deliberately.** Widening the settle budget would change a harness
timeout, which is a change to what the gate measures and belongs in its own reviewed step — and
`BROWSER_GATE_FINDING.md` asks for attribution before anything is changed. The attribution is
above. The recommended next step is in the outbox.

---

## 6. Open, and not fixed here

### 6.1 `user-scalable=no` — a genuine conflict, decided for CROOKS

axe reports `meta-viewport` (moderate, WCAG 1.4.4) at every viewport: pinch-zoom is disabled.

**It is disabled on purpose and must stay disabled.** A two-finger spread on this product is
the gesture that **divides the orb**, and a pinch is the gesture that **merges the halves**
(`scripts/browser/tablet.js`, `DESIGN.md` §9.3). Enabling browser zoom would put the platform's
pinch in direct competition with the product's own, on the same surface, with a write-capable
workspace behind it.

This is exactly the case `DESIGN.md` §0 exists for: a general web convention sits below CROOKS
intent, and the conflict is reported rather than resolved in silence. **Owner decision, not an
agent's.** If zoom is wanted, it needs a different home for split/merge first.

### 6.2 The card's tab strip scrolls off with nothing to say so

At 390, three of five tabs are past the right edge; at 601, one is. The strip scrolls
(`overflow-x:auto`) but has no fade, unlike `.context-nav`, which sets `data-overflow="1"` from
`web/app.js` and masks its far edge.

Not fixed because the honest fix is to generalise that mechanism to any strip, which means
touching `web/ui.js`'s render paths and the tablet's behaviour — wider than this candidate, and
this is **pre-existing at the tablet's own size**, not a mobile regression.

**Proposed:** lift the `mark()` closure in `app.js` into a small shared overflow-watcher applied
to `.tabs` as well as `.context-nav`, with a `ResizeObserver`. One mechanism, two users.

### 6.3 `<li role="button">` — `aria-allowed-role` (24 nodes) and `list` (8 nodes)

Every tappable list row is `<li class="row tappable" role="button">` inside `<ul class="rows">`.
`button` is not an allowed role on `li`, and a `ul` whose children are not list items fails
`list`. Both are one root cause, at every viewport, on every list.

Not fixed because the correct shape changes the DOM of **every list row in the product**, and
the row shape is load-bearing for `web/touch.js`'s classification, `web/collide.js`'s selectors,
`clickpath.js`'s `[data-ref][data-kind]` finder and four files in `tests/web/`. That is a
behavioural change dressed as a markup change, and it belongs in its own pass with its own
gate run.

**Proposed:** `<ul role="list">` → `<div role="list">`, rows `<div role="listitem">` wrapping a
real `<button>`, with `.rows`/`.row` class selectors unchanged so no CSS moves.

### 6.4 `page-has-heading-one` (12 nodes)

The only `<h1>` is `#system-title` in the boot layer, which goes `visibility:hidden` once the
Mac answers. Best-practice, not a WCAG A/AA failure. **Proposed:** make the `.wordmark` an
`<h1>`; it is already the page's title in every sense but the tag.

### 6.5 `--ink-4` on a raised tile

`#7a7a74` measures **4.29:1** on the stat tile — under AA. axe did not flag it because nothing
currently puts `--ink-4` text on a raised surface, but nothing stops it. Recorded in
`DESIGN.md` §3.3 as a rule: `--ink-4` is metadata grey **on the ground**, and putting it on a
tile is a defect.

### 6.6 `web/sw.js` still carries the old `#83827c`

The offline page in the service worker is a self-contained HTML string on a flat dark ground,
where `#83827c` measures 5.22:1 and passes. Left alone rather than risk `tests/test_pwa.py` and
`tests/web/sw.test.js` for a value that is not failing. Worth aligning in a tidy-up.

---

## 7. What needs the owner's judgement

**The keyboard trade on a phone (change 6).** While the keyboard is open on a phone — and only
then — three things stand down: the four dock areas, the Split invitation, and the trail's
entity chips. Assistant, Back, Previous and Next stay; the hold stays, full width at 48px; the
Mac's last line stays. Everything returns the moment the keyboard stops needing the screen, and
nothing is disabled or made unreachable in the meantime.

The precedent is in the same media query and is the product's own: the halves' band already
does exactly this, with the reason written beside it — *"The owner is typing into a field; the
halves are not what he is doing... He can still divide with the gesture."* The same sentence
applies to all three. But it is still a decision about what the owner can reach while composing
on a phone, and it should be his.

The arithmetic that forces some version of it: 375 × 313 with the keyboard up is 244px of fixed
furniture on a 313px screen. Without the trade, the deck measured **20px**.

---

*Measured on the tree at `claude/mobile-experience-v1`. Production was not touched; writes stay
disabled; no live API was called and no secret was read.*
