# Quality harness plan

Quality is layered evidence, not a single test command. This document binds each layer to the
machinery that already exists (audit/REPO_AUDIT.md) and says exactly what V1 changes.

## Evidence layers as they really are

| # | Layer | What runs today | Where | Who decides | Fails closed? |
|---:|---|---|---|---|---|
| 1 | Scope and protected paths | `allowed_paths` scope check and the `PROTECTED_PATHS` refusal on every candidate | Dispatcher on worker-01 | Code | Yes |
| 2 | Static | ruff, as one of the request's declared checks (`default_checks`) and in CI | Sandbox and CI | Code | Yes |
| 3 | Focused unit and integration | The request's declared `checks`: pytest on the named test files plus a regression set, derived by `engineering_tools.default_checks(paths)`. Run in `NamespaceSandbox`, no network | Sandbox on worker-01 | Code | Yes |
| 4 | Browser | Every screen test in real Chromium, on every SHA (since PR #108). The workflow refuses to run without Chromium | `acceptance.yml`, exact SHA | Code | Yes |
| 5 | Bench | `python -m app.bench …`: personas through the real turn against the fake shop, judged. **Not wired to the loop.** It needs the model over the network, so it cannot run in the no-network sandbox | Operator CLI | Owner ratings | n/a |
| 6 | Exact-SHA acceptance | `acceptance.yml` → `acceptance_provenance.py`: ruff, control-plane pytest, product-memory structure, the full offline pytest including browser tests, gitleaks. **The same for every SHA** | GitHub Actions | Code | Yes. Asked fresh at dispatch, admission, integration and landing |
| 7 | Independent review | `clive.review_result.v1` from a principal that is never the author. In force today: GPT. At the re-pin: Claude in a sealed read-only room | worker-01 | Reviewer | Yes. An invalid verdict is an error, never a verdict |
| 8 | Post-landing | Deploy is a separate owner gesture (DEC-072); the phone `/whoami` check after a deploy | Production | Owner | — |

## Routing: work type → required evidence

Layers 1, 2, 3, 6 and 7 apply to **every** loop candidate and are never reduced. Routing adds evidence;
it never removes it.

| Work type (detected from `allowed_paths` by the preflight, PR 3) | Added evidence | Who adds it |
|---|---|---|
| docs and product-memory only | — | — |
| Backend (`app/**` outside the paths below) | The validator adds the paired test modules for the touched app modules to scope and checks. The acceptance criteria require a new or changed test that fails at base | Preflight, PR 3 |
| UI (`web/**`, `app/builds/**`, `app/presentation*`, `app/screen*`) | `tests/test_web.py` plus the matching browser test in declared checks (`default_checks` already adds `test_web.py` for `web/`). Browser evidence comes from layer 4. Design skills routed (PR 6) | Preflight, PR 3 |
| Assistant behaviour (`app/kb/**`, prompts, `app/tools/**` descriptions, `app/presentation.py`, `app/focus.py`, routing) | **A Bench report for the trunk head before deploy.** `clive-eng deploy-brief` marks it required and shows it if one exists. Bench is run by hand on worker-01 in V1 (an engineering choice), and is not a landing gate, because it cannot run in the sandbox | `deploy-brief`, PR 10a |
| External integration (`app/clients/**`, hooks; `app/connections/**` is protected) | A mocked failure-path test (auth failure, rate limit, timeout) named in the acceptance criteria. The `external-api-integration` skill is routed once curated (NEXT) | The plan item's criteria (PR 7); routing PR 6 |
| Security or permissions (protected paths: gate, actions, people, secrets, connections, engineering) | **The loop refuses these paths.** They are built by a Director as a PR, with targeted negative tests and an independent review recorded on the PR at its exact head SHA. They are merged by a non-author session, and take effect only at his deploy or re-pin | The existing rule, made explicit |
| The loop's own code | The above, plus the re-pin's own exact-SHA review (`root-repin.sh`) and the owner-gated re-pin | Existing rule; unchanged |
| Project acceptance (a plan of more than one item) | **Tests first.** The plan's root item writes acceptance tests for the project's criteria, marked `xfail(strict=False, reason="project <slug>")`. Its exact-SHA CI must report them **XFAIL, not XPASS**: that is the evidence they fail before the work. Strict xfail is *not* used, because intermediate members would make them pass early and turn their own CI red. A final member, which depends on all the others, removes the marks, and its CI proves they pass. Both go through layers 1–7 and independent review | A rule of the plan card (PR 7) |

## Repair: structured failure evidence (already built)

A failed gate already becomes evidence for the next revision, so George never relays it:

- the reviewer's findings, verbatim;
- a summary of the red CI log;
- the failed-check tails;
- the earlier try's stop report for a re-file (`dispatcher.py:1941-2208,2633-2698`).

V1 adds only:

- **Stop cause words and owner class (PR 6).** The supervisor and Builds route a stop without parsing
  prose.
- **A green trunk head, checked paths and the worker's toolchain at filing (PR 3).** Filing on a red head is refused as
  Director work. Building on an older green commit would only move the stop later, because landing
  needs the head. Paths are checked as areas, with paired tests. The effect on scope and environment
  stops is measured in V1-real, not assumed.

A base preflight inside the loop is NEXT, if environment stops persist.

## Fault injection (run F1, before calling the harness sufficient)

The harness (PR 12) works on prepared candidates derived from baseline tasks. Each candidate carries
one seeded defect and is pushed as a branch `fi/<n>`. `acceptance.yml` runs on every push, so layer 6
runs on its exact SHA. An operator-run script on worker-01 then does two things:

- it runs the task's declared checks in the same `NamespaceSandbox` (layers 1–3);
- it runs the Claude reviewer on a packet built by the dispatcher's own packet code, in a scratch
  store (layer 7).

The script never touches the kernel store, the inbox or trunk. The reviewer sees the original task's
outcome and criteria, not the seeded defect, so the review is blind. For each defect, record which
layer caught it first.

| Seeded defect | Expected first catch | If nothing catches it |
|---|---|---|
| Subtle regression in an existing behaviour | 3 or 6 | Gap in test selection: the preflight must add the covering (paired) tests |
| Missing edge case in new code | 7 | The review prompt or acceptance criteria are too weak |
| Wrong date or time assumption (UTC vs London) | 3 or 6 (the clock fixtures exist) | Add clock-change fixtures to the default checks |
| UI interaction bug | 4 | Browser coverage gap for that screen |
| Permission widening (a write path without its card) | 1 (protected) or 6 (gate tests) | Critical: stop V1 and escalate |
| False success state (says done, did nothing) | 3, 6 or 7 | Critical for rule 1 ("verified, or it is an error") |
| Hidden external dependency (network call in a test) | 3 (sandbox has no network) | — |
| Scope violation | 1 | Critical |
| Concurrency or race defect | 6 (repeat run), sometimes 7 | Record as a known limit |

**Pass bar (an engineering bar, reported to George):**

- Every critical row is caught.
- At least 7 of 9 rows are caught before landing.
- Each miss produces a recorded harness change, not just a note.

## Fast feedback vs the final gate

- **Fast:** the sandbox checks in the loop (focused) give minutes-scale feedback.
- **Final and authoritative:** exact-SHA `acceptance.yml`, identical for every SHA, asked fresh at
  every authorising step.
- **Not in V1:** impacted-test selection to shorten CI is LATER. Even then it may only shorten the
  *fast* layer; it can never replace or thin the final gate (DEC-064 and MAP rule 8).
