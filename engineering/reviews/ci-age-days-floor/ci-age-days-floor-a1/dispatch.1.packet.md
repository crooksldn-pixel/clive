# EXACT-SHA GPT REVIEW PACKET 8 — the nightly golden-scenario failure (age_days rounding)

Generated 2026-09-22 22:30Z by the Claude engineering executor (session_014NGs3CS6XKQVhULWsHgqsi).
Reviewer principal: **gpt**. Claude-authored; GPT is eligible. Small, isolated, and the reason every full-suite run after 21:48 UTC failed tonight.

## Identity

| Field | Value |
| --- | --- |
| candidate_sha | `ef3d08ff9fc58d33ba96994bb2e3256010bda1f4` |
| branch (head == candidate when written) | `claude/ci-age-days-floor-2026-09-22` |
| parent | `84e12e77e712ed454f12a6300f6e5f5b54391252` (the truth-repairs candidate; this fix touches nothing that candidate touches) |
| author_principal | claude |
| review_state | NOT_REVIEWED |
| ci_state | PASS — run 35791618176, https://github.com/crooksldn-pixel/clive/actions/runs/35791618176, 2026-09-22T22:18:06Z to 22:21:48Z, all five gates green, run inside the failure window (the golden scenario now passes there) |
| local evidence | `scripts/acceptance_provenance.py --candidate-sha ef3d08ff… --suite full`, Python 3.12.3, gitleaks 8.30.1, clean tree, run inside the window: ruff pass; pytest_control_plane 44 passed in 0.23s; product_memory_structure pass; pytest_offline_full 3048 passed, 8 skipped, 2 deselected in 300.46s (0:05:00); secret_scan no leaks; eligible_for_acceptance_decision True |

## What failed, and why it had never failed before

`tests/test_experience.py::test_the_golden_scenarios[query_international_waiting]` asserts the answer names the fixture order and says it has waited 14 days. From 21:48 UTC tonight the answer read "waiting 15 days" on every branch, including candidates whose CI had been green an hour earlier (1958b327, 11060463). It reproduces locally at any minute between 21:48 and 23:00 UTC, on any checkout, and passes outside that window.

The fixture places the order 14 days ago at midnight shop-local (Europe/London) precisely to stay off the floor boundary, and `tests/test_fixture_wiring.py` walks the clock proving `int(elapsed)` is 14 at every hour. The engine, however, rounds `age_days` to one decimal (`round(elapsed_days, 1)`) before the presenters floor it (`int(age_days)` in `app/families/query_language.py:105`, `app/families/landings.py:122`, `app/fastpath/library.py:1020`). At 14 days 23 hours the elapsed time is 14.96 days, which rounds to 15.0, and `int(15.0)` is 15. The window is the last 72 minutes of each elapsed day: for this fixture (placed 23:00 UTC), 21:48 to 23:00 UTC. CI on this repository had never run inside it until tonight.

## The change

`git diff --stat 84e12e77..ef3d08ff`: 4 files, 57 insertions, 11 deletions.

- `app/analytics/engine.py`: `age_days_tenths(seconds)` truncates to a tenth (`floor(x * 10 + 1e-9) / 10`); used for order rows and for the bucket metric.
- `app/analytics/summarise.py`: the two `age_days` fields use the same function (clamped at zero as before).
- `tests/test_fixture_wiring.py`: the guard test walks minutes 0, 30 and 59 of every hour and passes the elapsed time through the engine's function; before the fix it fails at 22:30 and 23:30 shop-local.
- `tests/test_analytics.py`: a unit test sweeps three hundred tenths and asserts `int(age_days_tenths(x))` equals `floor(x)` for each, plus the exact cases 14.97 → 14.9, 20 → 20.0, 2.3 → 2.3.

Nothing else changes: the presenters keep `int()`, the table formatter (`present.py`) keeps rounding to whole days for display, and the analytics assertion at exactly 20.0 days still holds.

## Reviewer checklist

1. SHA resolves; parent 84e12e77; tree clean.
2. Between 21:48 and 23:00 UTC: `python -m pytest tests/test_experience.py -k query_international_waiting -q` fails at 84e12e77 and passes at ef3d08ff. Outside the window both pass; the new tests fail at 84e12e77 at any hour (`tests/test_fixture_wiring.py`, `tests/test_analytics.py::test_age_days_is_truncated_to_a_tenth_so_whole_days_are_the_floor`).
3. Decide whether truncation is the right rule for `age_days` in listing rows (a 0.1-day resolution field that a person reads as whole days). The alternative, computing whole days in each presenter from the timestamp, needs the engine's clock in three places and was judged wider.

## Known risks

1. Listing rows now say 14.9 where they said 15.0 for an order 14 days 23 hours old; the table formatter still shows "15" (it rounds for display). Anything that compared `age_days` to a rounded expectation would see a tenth less; the suite found none.
2. The other candidates under review (1958b327, 84e12e77, 119bb9b) do not carry this fix; their recorded CI runs are green because they ran before 21:48Z, and a re-run in the window would fail until they carry it. Nothing is rewritten; carrying it is a merge after review.

## After acceptance

Merge into the stream and into each live candidate branch after their own reviews; no deployment.
