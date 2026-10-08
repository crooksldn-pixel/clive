# Phase 4 screens

Thirty-one pictures of the build, taken by the browser gates themselves rather than by hand,
so every one of them is a screen a check has just driven and asserted on. The filenames are
the gates' own, unchanged, so a re-run puts each picture back where it was.

Two sizes throughout. **601 × 889 at DPR 1.33** is the physical Samsung Tab A the owner holds,
and it is the authoritative one: the Phase 3 live test found clipping and a swallowed dock
that the 800 × 1280 shots could not show. **800 × 1280** is kept because it is where the
experience gate has always run and a regression should not be able to hide by moving between
them.

On 8 October 2026, when the repository went public, every fixture name that read like a real
person's was swapped for an obviously invented one. Where one of the old names was drawn in a
picture — here, in `../phase5-before/`, `../phase5-after/` and `docs/phase6/evidence/screens/` —
it has been painted out with the card's own background, so a row or a sentence in those
pictures has a gap where the name was.

| # | File | Size | What it shows |
|---|------|------|----------------|
| 01 | `tab-01-idle.png` | 601×889 | The orb at rest. Nothing is said until the dock is held. |
| 02 | `accept-01-ready.png` | 800×1280 | READY, with the wordmark and the dock's four landings. |
| 03 | `tab-02-dock-orders.png` | 601×889 | The Orders landing, reached by a tap and not a sentence. |
| 04 | `08-assistant-landing.png` | 800×1280 | Home: a PLACE with cards on it, twice running, never a stale record (D-10). |
| 05 | `03-order-list.png` | 800×1280 | A list that folds: five rows, where it is, and one control for the rest. |
| 06 | `02-order-detail.png` | 800×1280 | The order. What it NEEDS is above the tabs and above the rail (D-12). |
| 07 | `07-email-thread.png` | 800×1280 | Newest message first, history behind one control, Reply above the fold. |
| 08 | `05-list-walk.png` | 800×1280 | Next over a set: "3 of 10" as numbers, not parsed out of prose. |
| 09 | `01-home.png` | 800×1280 | Back to the branch landing. |
| 10 | `04-capabilities.png` | 800×1280 | What the system says it can do, including how to type (D-6). |
| 11 | `accept-05-action-armed.png` | 800×1280 | ARMED. The gesture is the authorisation; the model never gave one. |
| 12 | `action-01-applying.png` | 800×1280 | EXECUTING, with the watchdog running. The state the owner watched get stuck (D-1). |
| 13 | `accept-05-action-verified.png` | 800×1280 | VERIFIED, from a re-read, with its undo. Success means verified and nothing less. |
| 14 | `action-02-settled.png` | 800×1280 | A terminal card. No surface is left mid-flight. |
| 15 | `accept-06-action-blocked.png` | 800×1280 | Blocked, saying who is stopping it. It looks unavailable and cannot be tapped. |
| 16 | `accept-08-refused.png` | 800×1280 | A refusal with somewhere to go, not one unactionable sentence. |
| 17 | `action-03-merged.png` | 800×1280 | A merge that does not count an undo offer as a change still waiting (D-2). |
| 18 | `split-601x889-01-divided.png` | 601×889 | The orb divided, each half a chip that says what it is. |
| 19 | `split-601x889-02-second-half.png` | 601×889 | The second half: its own screen, not its parent's cards (D-3). |
| 20 | `split-601x889-03-both-halves.png` | 601×889 | Two halves on two questions, two headlines, two sets of cards. |
| 21 | `split-601x889-04-ready-retrieved.png` | 601×889 | A half that finished says READY on its chip; nothing was thrown over the other. |
| 22 | `split-800x1280-01-divided.png` | 800×1280 | The same division at the other size. |
| 23 | `tab-05-reloaded.png` | 601×889 | A divided orb after a reload: both halves come back. |
| 24 | `e02-reply-composer.png` | 800×1280 | Reply OPENS a reply: who it is to, what it is about, and a box to type in. |
| 25 | `e03-typed.png` | 800×1280 | Characters typed by a real keyboard, surviving a redraw with the caret kept. |
| 26 | `e08-address.png` | 800×1280 | The address workspace — a postcode is the worst thing in the shop to dictate. |
| 27 | `e07-order-rail.png` | 800×1280 | The order's rail: two chips that lead, the rest behind one control, each disabled one saying why. |
| 28 | `collide-601-cards.png` | 601×889 | The geometry check's own view: the deck ends where the dock begins. |
| 29 | `collide-601-keyboard.png` | 601×889 | A focused field with the keyboard up, and nothing on top of anything. |
| 30 | `density-04-worst-order.png` | 601×889 | The worst order this build can draw: 633 px against a 699 px first screen. |
| 31 | `accept-07-offline.png` | 800×1280 | The Mac unreachable, said plainly, with the cards the owner was reading left alone. |

## Taking them again

    .venv/bin/python -c "import asyncio; from pathlib import Path; \
      from experience.browser import capture_screens; \
      asyncio.run(capture_screens(None, out=Path('docs/screens/phase4')))"

That drives every gate and writes **96** pictures, of which the thirty-one above are the ones
kept in the repository. The rest are the fixture gallery (`accept-04-fixture-*`, one per card
type), the per-state orb (`accept-02-state-*`), the density measurements and the 800 × 1280
halves of the split and collision runs. They are worth looking at when a specific card type is
in question; they are not worth carrying in git.
