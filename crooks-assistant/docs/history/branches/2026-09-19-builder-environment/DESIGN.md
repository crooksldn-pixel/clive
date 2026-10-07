# CROOKS — DESIGN.md

**Status:** PROPOSED. Not yet ratified by the owner.
**Scope:** the CROOKS operational product UI (`crooks-assistant/web/`).
**Method:** repository mode, following the `create-design-md` evidence pipeline
(`role → value → source → scope → recurrence → confidence`). Every value below was read out of
the shipped source, the UX baseline, or a Phase report. Nothing here is invented, and nothing
here proposes a new aesthetic.

---

## 0. What this document is, and what outranks it

This records the design language CROOKS **already has**. It exists so that a future agent — or a
third-party design skill — cannot quietly replace a deliberate decision with a generic one.

**Authority order for all future UI work:**

1. Owner request
2. `docs/product-memory/PRODUCT_BRAIN.md`, `docs/product-memory/DECISIONS.md`, and the UX
   invariants in `PHASE_1_UX_BASELINE.md`
3. **This document**
4. Existing functional and safety behaviour (the proposal/action/verification semantics)
5. Specialist design skills (`frontend-design`, `impeccable`, `web-interface-guidelines`, …)

A third-party design skill sits at rank 5. It may *propose*; it never silently overrides ranks
1–4. If a skill's house style conflicts with anything above, the skill loses and the conflict is
reported rather than resolved in silence.

**Sources of evidence used:** `web/style.css`, `web/index.html`, `web/ui.js`, `web/app.js`,
`web/collide.js`, `web/touch.js`, `PHASE_1_UX_BASELINE.md`, `PHASE_2_FABLE_UX_REPORT.md`,
`PHASE_3_ULTRACODE_REPORT.md`, `docs/phase5/*`, and the product-memory branch.

---

## 1. The two principles that generate everything else

### 1.1 Maximum capability, minimum visible UI

From `PRODUCT_BRAIN.md` §2.1 and `DEC-002`. The system may be sophisticated underneath; the
screen should not show it. The ideal turn produces one answer, one card, one action — or nothing.

Consequences that are already enforced in the source, and must stay enforced:

- No dashboards. No settings surfaces. No agent controls, model pickers, prompt boxes or
  workflow builders.
- A control exists because a real turn needs it, not because a capability exists.
- Internal vocabulary (proposal, capability manifest, branch, lane) does not appear on screen.

### 1.2 Speech and screen answer different questions

From `PHASE_1_UX_BASELINE.md`, the rule that governs every surface.

- **Spoken:** what a person would say across a workshop. One or two sentences.
- **Screen:** what you would hand them if they walked over.

The spoken answer never reads the card aloud; the card is never a transcript of the speech.
A turn that answers in words and draws nothing is a **failure** however good the words are —
this is what `prose_only` exists to catch. Do not "improve" a surface by moving detail into
speech, and do not fix a thin card by making the sentence longer.

---

## 2. Visual hierarchy

The screen is a near-black ground with lit glass panels on it. Hierarchy is carried by **light
level**, not by colour, weight or rules.

Order of prominence, strongest first:

1. The **armed / selected** surface — `--glass-control-active` plus `--shadow-active`
2. The **open** record or expanded row — `--glass-surface-strong`
3. An ordinary **card or panel** — `--glass-surface`
4. A **control at rest** — `--glass-control`
5. **Dividers and rows** — `--border-subtle` only, no fill

Because every state is a step on one white ladder, "selected", "pressed" and "armed" all read as
*more of the same light* rather than as a different material. Introducing a second material — a
tint, a gradient, an accent fill — breaks the system. Don't.

---

## 3. Colour, near-black and the glass system

### 3.1 Ground

| Token | Value | Role |
|---|---|---|
| `--bg-0` | `#07070a` | the page |
| `--bg-1` | `#0d0d10` | |
| `--bg-2` | `#131317` | |
| `--bg-3` | `#191a1f` | |

The ground is near-black and **warm**. This is why the glass steps are half the intensity of the
reference system they were borrowed from: on a warm near-black, white at `.10` already reads as a
lit panel. The **ratio** between steps is what was borrowed, not the values.

### 3.2 Glass — one white, five steps

| Token | Value |
|---|---|
| `--glass` | `rgba(255,255,255,.05)` |
| `--glass-2` | `rgba(255,255,255,.075)` |
| `--glass-3` | `rgba(255,255,255,.12)` |
| `--glass-4` | `rgba(255,255,255,.16)` |

Borders: `--line` `.10` → `--line-2` `.18` → `--hi` `.26` → `--line-3` `.34`.

**Never write a raw `rgba(255,255,255,…)` into a component.** Use the role aliases —
`--glass-surface`, `--glass-surface-strong`, `--glass-control`, `--glass-control-active`,
`--glass-overlay`, `--border-subtle`, `--border-rest`, `--border-active`. A change to the ladder
must be able to move every card, chip, tab, row and dock together.

### 3.3 Ink

`--ink` `#ebe8e0` (warm off-white) → `--ink-2` `#b9b6ae` → `--ink-3` `#83827c` → `--ink-4`
`#7a7a74` (metadata grey). Secondary text uses `--opacity-secondary: .6`; disabled uses
`--opacity-disabled: .32`.

### 3.4 Semantic colour is rare and never alone

`--ok` `#79c996`, `--warn` `#dcb266`, `--bad` `#dc7f6c`, each with a `-dim` fill at `.16`.

These are **rare, and always accompanied by a word or a mark**. Colour alone never carries
meaning — that is both a product rule and the accessibility rule (§11). A red chip with no word
on it is a defect.

### 3.5 Blur

`--blur-surface: 12px` is for **the nav glass and the dock pill, and nothing else**.
`--blur-overlay: 16px` is for the sheet. Blur is expensive on the target device (§12); adding a
third blurred surface is a performance decision, not a visual one.

---

## 4. Typography

- `--font`: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial,
  sans-serif` — the platform stack. **No web font is loaded.** The tablet is on a workbench and
  often on poor connectivity; a font that must be fetched is a blank card.
- `--mono`: `ui-monospace, SFMono-Regular, Menlo, "Roboto Mono", monospace` — for identifiers,
  tracking numbers, SKUs and money where digit alignment matters.

Type is sized per surface rather than from a global scale; controls sit at ~15px so that a label
stays legible at arm's length on an 8-inch panel. Sentence case throughout. No uppercase
transforms on controls (`text-transform:none` is set explicitly where a reset would otherwise
introduce one).

---

## 5. Spacing and density

`--sp-1` 4 · `--sp-2` 8 · `--sp-3` 12 · `--sp-4` 16 · `--sp-5` 20 · `--sp-6` 28 · `--sp-7` 40.

Radii: `--r-1` 8 · `--r-2` 14 · `--r-3` 20 · `--r-4` 28 · `--r-pill` 999, with two role aliases —
`--radius-panel` 20px (cards, nav container, dock) and `--radius-control` 14px (chips, tabs, rail
chips, nested tiles).

**Density is a hard constraint, not a preference.** The order card is ~7,500px of content against
~655px of usable screen. That is why detail lives in **tabs** rather than in one long scroll, and
why the order list is built so four or five rows fit without scrolling. Any change that adds
vertical space to a repeated element is spending the owner's screen and must be justified against
the collision gate (§12).

---

## 6. Controls

- Every control is at least `--tap` (48px) high. The pattern in source is
  `min-height:var(--tap)`, applied to chips, tabs, rows, rail chips, buttons, checkboxes and
  list rows. Circular controls are `width:var(--tap); height:var(--tap)`.
- `--tap-lg` (64px) is for primary list rows.
- The dock band is `--dock` (112px); the voice pill's slot is `--hold-w` (252px), and that one
  token is used by **both** `.dock-gap` and `.talk` so the hold region and the hole the dock
  leaves for it cannot drift apart.

### 6.1 The action rail

From the UX baseline, and this is product intent rather than styling:

> An action that the store has not granted is shown **disabled with the reason**, not hidden.

A rail that only shows what is possible teaches nothing; one that shows what is not, and why,
answers the question before it is asked. Refund on a nothing-to-refund order reads
"nothing to refund" and is inert.

**Nothing on the rail applies anything.** A tap stages a proposal; a separate gesture commits it.

### 6.2 Touch-then-voice binding

Tapping a control such as **Rewrite** binds what the following sentence will apply to, shows what
it is listening for, and starts listening. Three properties, all about *not* applying:

- It belongs to **one half of the orb**. A binding armed on the left never catches a sentence
  spoken to the right.
- It lasts **one sentence**. Taken or abandoned, it is released.
- It **expires** after two minutes.

A sentence that is an instruction in its own right ("go back", "next", "what can you do")
**releases** the binding rather than being captured by it.

---

## 7. Selected and armed states

- **Selected:** `--glass-control-active` fill + `--border-active` border.
- **Armed:** the action surface is dim and inert while arming — a thin line fills across it —
  then lit. Pressed compresses. Applying pulses. Settled states go quiet.
- Confirmation tiers tint the **border only**: `.tier-amber` `rgba(220,178,102,.28)`,
  `.tier-red` `rgba(220,127,108,.32)`. The fill stays on the white ladder.
- `--shadow-active` is `0 0 0 1px rgba(255,255,255,.22), 0 0 18px rgba(255,255,255,.12)` — a ring
  plus a glow, both white.

The arming animation is load-bearing: it is the visible gap in which a mistaken tap can be
abandoned. Do not shorten it to feel snappier.

---

##8. Cards and nested surfaces

- A card is `--glass-surface` on `--radius-panel`, with `--inset-hi`
  (`inset 0 1px 0 rgba(255,255,255,.06)`) as the top highlight and `--shadow-1`/`--shadow-2`
  beneath.
- A nested tile inside a card drops to `--radius-control` and does **not** get its own blur.
  Nesting is expressed by radius and border, not by stacking another blurred pane.
- Tabs inside a card are **state, not DOM**. "Show me the shipping" and a tap on Shipping are the
  same operation, and the selected tab is branch state, so it survives a reload, a Back, and
  putting the half aside.

---

## 9. Navigation and layering

### 9.1 Behaviour

- **Back** is deterministic and free: it moves the branch cursor and redraws from what is already
  held. No model, no read, no reconstruction. At the end of the trail it says so.
- **Next / Previous** move one member of the open set. At the ends they say "that is the last
  one" / "that is the first one" — a cursor that runs off the end and repeats the last member is
  worse than one that stops.
- **Linked entities** carry their kind and id on the card, so a tap opens the record without
  asking the model to find it again.
- Saying it and tapping it reach the same code. There is one implementation of each.

### 9.2 The layer order — do not change without reading why

Bottom to top:

| # | Layer | Owns |
|---|---|---|
| 1 | content | `.orb-zone` (**no z-index**), `.deck` |
| 2 | actions | `.context`, `.context-nav`, `.armed` |
| 3 | navigation | `.top`, `.bottom`, `.dock` |
| 4 | branch | `.branch-zone` — Split / halves / Merge / Close |
| 5 | voice | `.talk` — the hold-to-speak target |
| 20 | emergency | `.sheet`, `.system`, `.dev-banner` |

This exists because of a real, twice-reported field defect: `#branch-bar` was a child of a
`position:relative; z-index:1` stacking context while `#talk` was its sibling at `z-index:3` with
`inset:0` — a transparent, viewport-sized button painted over every branch control. **63 taps in
one evening, 26 of them in ten consecutive seconds, went to the speech recogniser.** No z-index on
a child can escape its parent's cap.

`.orb-zone` deliberately has **no z-index at all** — it is the content layer by document position.
Giving it a number is what created the cap. The same bug class had already been found one element
away (`.bottom`). Treat this table as a safety invariant.

### 9.3 The split orb

Two halves, each with its own current record, set, workflow, cursor, navigation stack, tab,
expanded rows, voice binding and proposals. A half put aside works quietly and says "ready" on its
own chip rather than taking the screen. **Read caches are shared because they are immutable;
nothing else is.**

---

## 10. Motion

Two naming families exist in source and both are live. Prefer the **role-named** set in new work:

| Role token | Value | Use |
|---|---|---|
| `--motion-press` | 120ms | touch-down feedback |
| `--motion-switch` | 260ms | a tab, chip or dock item changing state |
| `--motion-enter` | 380ms | a card or band arriving |

Generic: `--t-1` 120ms · `--t-2` 240ms · `--t-3` 380ms.
Easing: `--ease-standard` `cubic-bezier(.4,0,.2,1)`, `--ease-out` `cubic-bezier(.2,.7,.2,1)`,
`--ease-spring` `cubic-bezier(.3,1.35,.45,1)`, `--ease-inout` `cubic-bezier(.65,0,.25,1)`.

Motion is feedback, never decoration. Nothing moves that is not telling the owner a state changed.

**`prefers-reduced-motion: reduce` is honoured globally** — all transitions and animations drop to
1ms, `.card` animation is removed, and the armed dot and system pulse stop. There are eight
reduced-motion blocks in the stylesheet; any new animation must add its own.

---

## 11. Accessibility

- **48px minimum touch target**, enforced by `--tap` and checked by the touch harness.
- **Colour is never the only signal** (§3.4).
- **Reduced motion is honoured** (§10).
- Contrast: `--ink` `#ebe8e0` on `--bg-0` `#07070a` is a very high ratio; the constraint to watch
  is `--ink-3`/`--ink-4` metadata grey and anything at `--opacity-secondary`. New secondary text
  must be checked, not assumed.
- Hit-testing is a first-class check, not an audit afterthought: the layer table (§9.2) exists
  because a control can be perfectly contrasted and still unreachable.
- Automated axe-core auditing is now available in the builder (see `docs/DEV_ENVIRONMENT.md`) and
  should be run at the §13 viewports. It **supplements** the collision and touch harnesses; it
  does not replace them, because axe cannot see two boxes that are each the right size and in the
  same place.

---

## 12. Samsung performance constraints

The target device is a **Galaxy Tab A 8.0, 601 × 889 CSS px at DPR 1.33**, held in portrait, on a
workbench, operated by someone with their other hand full. Everything in this document follows
from that.

- Blur is restricted to two surfaces (§3.5). A third is a performance regression.
- No web fonts (§4).
- Density is bounded by 655px of usable height against a ~7,500px card (§5).
- The collision gate renders the worst data a real shop can produce and reads **every**
  `getBoundingClientRect()` for overlapping pairs, at **both** 601×889 DPR 1.33 and 800×1280 DPR 1.
  It exists because a live session reported `clipped=0` on every render while the owner was
  looking at overlapping text. A single subtraction on one card cannot see two boxes that are each
  the right size and in the same place.

Breakpoints in source: `max-width: 520px`, `max-width: 560px`, `max-height: 520px`,
`max-height: 640px`, and `(orientation: landscape) and (max-height: 820px)`.

---

## 13. Responsive / device behaviour and the visual verification matrix

Every UI change is verified at, at minimum:

| Viewport | DPR | Why |
|---|---|---|
| 601 × 889 | 1.33 | the physical Galaxy Tab A 8.0 — the device that exists |
| 800 × 1280 | 1 | the portrait gate |
| 390 × 844 | 3 | representative iPhone / CROOKS Phone |
| 1280 × 800 | 1 | desktop / CROOKS Control reference |

A defect is a defect at the size the tablet actually is. The 800×1280 gate alone has already
missed defects the 601×889 session found.

---

## 14. Loading, error and empty states

### 14.1 Loading — the honest position

**No section is currently drawn as `LOADING`, and that is recorded rather than papered over.**

`present(pending=…)` is accepted by the composition and honoured by every section renderer, but it
has **no live caller**: `progressive.observe()` passes no session on purpose, so early staging
cannot put a record on the context stack the owner never saw, and the turn's own `present()` runs
when the turn is over, by which point `in_flight` is empty by construction.

So a section still reading is **not drawn as loading; it is simply not drawn yet.** That is honest
but incomplete. The remaining gap is the call site, not the vocabulary. **Do not add the call at
the named site as a cosmetic fix** — it would be a no-op that *looks* done, which is worse than
the gap.

What *is* required today: the order does not wait for Gmail, and **regions that are still coming
say so**.

### 14.2 Partial and empty

- `.partial` — used where coverage is incomplete. Analytics states the period **and its
  completeness**; a partial total is never presented as a total.
- `.empty-line` / `.pending-line` — an empty screen is an invitation to act, not a mood.

### 14.3 Errors

Errors explain **what went wrong and how to fix it**, in the interface's voice. They do not
apologise and are never vague. A failure is a moment for direction.

### 14.4 The screen never lies

From the UX baseline's "what never happens" list — these are the loading/error invariants:

- A card never claims something was done that was not verified by reading it back.
- The screen never shows a value no tool returned.
- A question about a record is never answered with a paragraph and an empty screen.

---

## 15. What never happens

Reproduced from `PHASE_1_UX_BASELINE.md` because it is the shortest complete statement of the
product's UI contract:

- A change applied without the gesture on the card.
- A spoken "yes" authorising anything.
- A card claiming something was done that was not verified by reading it back.
- An action offered that the store has not granted — it is shown disabled, with the reason.
- An action offered to someone who could not apply it if they tapped it.
- The screen showing a value no tool returned.
- A question about a record answered with a paragraph and an empty screen.
- A record shown to a conversation that was never shown it.
- One half of the orb answering with the other half's list.
- A question that names a person or an order number answered from whichever record happens to be
  open.

---

## 16. Working notes for agents

- **Do not bulk-reformat** `web/*.css` or `web/*.js`. Biome is advisory and check-only here; see
  `docs/DEV_ENVIRONMENT.md`.
- **Do not introduce a component library or a CSS framework.** The product is one hand-written
  stylesheet with a documented token ladder.
- **Do not create a second product-intent document.** `PRODUCT_BRAIN.md` and `DECISIONS.md` are
  canonical. If a design skill expects its own `PRODUCT.md`, point it at product memory rather
  than forking the source of truth.
- Before/after screenshots at the §13 viewports, plus the collision and touch harnesses, are the
  evidence that a UI change is safe. A visual critique is not evidence.

---

*Proposed from the tree at `claude/bridge-builder`. Values read from source on 2026-09-18.
Supersedes nothing. Ratification is an owner decision.*
