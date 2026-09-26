# Owner Decisions - 2026-09-26

Recorded from the owner's explicit answers in the Opus 5.5 engineering session.

## GPT reviewer cost

Why: the exact-SHA GPT reviews were burning through OpenAI API tokens. The owner first asked to move from `gpt-5.6-sol` to `gpt-5.6-luna`. The Director pointed out that GPT-6 had been released on 2026-09-22 and changed the options:

| Model | Input per 1M tokens | Output per 1M tokens |
|---|---|---|
| `gpt-5.6-sol` | $4.00 | $20.00 |
| `gpt-6-sol` | $2.00 | $10.00 |
| `gpt-6-luna` | $0.10 | $0.50 |

These are OpenAI's list prices on 2026-09-26. On those prices `gpt-6-luna` beats `gpt-5.6-luna` on both cost and quality.

Decided:

- **The loop's routine exact-SHA reviews run on `gpt-6-luna` at medium effort.** These are the reviews of builder candidates in the remote engineering loop and the engineering dispatcher. Code defaults: `app/orchestrator/reviewers/gpt.py` `DEFAULT_MODEL` / `DEFAULT_EFFORT`, which the `--gpt-model` / `--gpt-effort` defaults of both loop scripts follow.
- **The production deploy review runs on `gpt-6-sol` at medium effort** (`DEPLOY_REVIEW_MODEL`). This is the exact-SHA review the production host runs before it deploys a trunk SHA. It is rare and it is the last gate before the live system, so it keeps the stronger model.

The risk the owner accepted: OpenAI positions the Luna models for routine extraction and summarisation, not code review. A weaker reviewer can pass a defect, or raise a finding that isn't real and costs a repair round of builder time.

What still sits behind it:

- green GitHub acceptance on the exact SHA, once the loop update is in force;
- the Director's landing;
- the `gpt-6-sol` deploy review.

The engineering measures (review rounds, false findings, defects found after acceptance) are how this choice is judged. If Luna's review quality shows up there, move the loop back to `gpt-6-sol`.

How it takes effect:

1. **Now, on each loop host:** the loop service's `--gpt-model gpt-6-luna --gpt-effort medium` flags, applied when the service restarts. The host first confirms, with one small request, that the API key can use `gpt-6-luna` with a strict JSON schema at medium effort.
2. **In code:** the defaults above, so a later re-pin keeps the choice without flags.

## Loop update follow-ups

The owner left the choice to the Director, and the Director ran both:

- **The manual kernel CLI is gated.** `scripts/engineering_kernel.py` `verdict` and `integrate` need the same green GitHub acceptance gate as the loop.
- **The tests that hold the protected code are protected too.** A builder that cannot change the safety core cannot weaken the tests that prove it either.

Both are part of loop update part 2 and, like the rest of it, are in force only through the owner-gated re-pin.
