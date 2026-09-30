# Owner Decisions - 2026-09-30

Recorded from the owner's explicit answers in the Opus 5.5 engineering session, after two research reports:

- where Jev fits in CLIVE;
- what skills and agents need, where CLIVE denies them, and what has slowed building.

## The ship rule is regression-only, with one exception

This answers decision 5 of [the self-shipping plan](../plans/2026-09-29-clive-ships-its-own-fixes.md) and the regression-only rule proposed on 28 September.

The owner, verbatim:

> regression only ship rule is good for now "My advice is regression-only with one exception: anything shown to leak customer data, or to write to the shop or send an email you didn't confirm, blocks whether it's new or old. Everything else old goes into the next build. [...]" with this

**Why.** Until now a deploy was blocked by any finding that could be exploited, lose data or leak data, including findings in code that production was already running. Every deploy review re-found problems in live code, and a newer version that fixed things could not ship until those older problems were fixed too.

In the round-12 review, 62 findings were labelled blocking. When the code was read:

- 19 were not defects;
- 15 were real but not blockers under the rule's own text;
- 4 were not blockers under its configuration.

The rounds from 6 to 13 spent an estimated three-quarters of their time in review-and-fix loops.

**Decided.** Every deploy review, and the release service when it is built, applies this rule word for word:

> A material finding BLOCKS the deploy only when either:
>
> 1. **this change makes production worse:** the defect is in code this change adds or alters, or this change makes an existing defect reachable or worse, measured against the SHA production runs now; or
> 2. **it is shown to leak customer data, or to write to the shop or send an email the owner did not confirm,** whether it is new with this change or already in production. "Shown" means the reviewer demonstrates it from the code, on production as it is actually configured; a finding that only says it cannot tell is not shown.
>
> Every other material finding is a FOLLOW-UP and goes into the next build. That includes anything already in production that is not in (2).
>
> Where the deploy owner cannot tell whether a finding is new with this change, it is treated as new.
>
> "As configured" means Tailscale-only access, the owner's login on the allow-list, the switches as they stand, and writes as they are.

It supersedes the rule applied in rounds 9, 10 and 12 ("it can be exploited; it would lose data; it would leak data"). The owner said "for now": the rule stands until he changes it.

**What stays.**

- The exact-SHA review.
- Green GitHub acceptance on the exact head.
- Merging only with the expected head SHA.
- The owner's hold on every shop or email write.
- The rule never to weaken the kernel, test assertions, secret scanning or acceptance machinery.

Follow-ups are not dropped: each one is filed as work for the next build.

## Acceptance moves to a self-hosted runner on clive-worker-01

The owner, verbatim: "Self hosted runner definetely".

**Why.** The repository is private on GitHub Free. From 22 to 29 September acceptance used about 1,773 hosted minutes, against a free allowance of 2,000 a month, so at that pace the minutes run out early in each month.

Hosted runs take about 7 minutes for the gates step, and every PR head runs twice. On clive-worker-01, with the suite in memory and run in parallel, a full run is estimated at 1.5–3 minutes; that estimate is unverified until it runs there. GitHub does not charge for self-hosted runners today. It announced a per-minute fee on 16 December 2025 and postponed it two days later.

**Decided.** GitHub acceptance runs on a self-hosted runner on clive-worker-01, under these conditions:

- The runner is isolated in its own VM or its own user.
- It holds no production credential and not the engineering token.
- It is registered to this repository only.

**How it takes effect.** `.github` and `crooks-assistant/pyproject.toml` are protected paths, so the workflow change arrives as a reviewed PR like any other. The runner registration token is the owner's to create.

**Recommended, not yet decided:** keep a payment method on the GitHub account with a small spending cap, so that acceptance can fall back to hosted runners when the server is down.

## The owner's curated skill list is the owner's decision

The owner answered "Yes" to: "Does your own skill list count as your approval? That skips the per-skill sign-off and the cap of 5."

**Why.** CLIVE's digester was run on five public collections holding 353 skills. It adopted none of them:

- 94% were lost to whole-collection blocks. Most of those blocks were false positives, and the real findings sat in hooks and connector settings outside the skill folders.
- Blocking per skill alone would not have rescued them. The per-source budget of five builder skills (`app/digest/propose.py`), ranked by word overlap, would still hold back about 93% of the valid candidates.
- Every builder skill also waits on the owner (`propose.py`).

SOURCE_ASSIMILATION_V1.md §3 already puts an ordinary skill through the normal loop and reserves only executables, MCP servers, keys, new data vendors and spend for the owner. The code went further than the policy.

**Decided.** A skill on a list the owner supplies needs no further owner sign-off and does not count against a proposal budget.

**What still applies to every skill.**

- It is pinned to a commit and scanned per skill, not per collection.
- Its licence is checked.
- It is installed with its provenance and can be removed.
- A skill held by a finding is shown to the owner with the exact flagged line.
- Anything a skill brings that runs on its own — a hook, an MCP server, an executable, a key, a new data vendor, spend — stays the owner's to approve, as SOURCE_ASSIMILATION_V1.md §3 says.

## Builder capacity: one Max plan for now

The owner, verbatim: "Just max currently if we need more i can get another max plan".

**Decided.** Builders run on the owner's current Max plan. A second Max plan is added when usage, not hardware, becomes the limit.

**The risk the owner accepted.** Anthropic's consumer terms assume ordinary, individual use, and they allow enforcement without notice against automated access that is not explicitly permitted. Headless Claude Code under a subscription is documented and supported, but a large builder fleet on consumer plans carries that risk. If it bites, the fallback is a Team plan or the API.

Builders share the plan's 5-hour and weekly allowances with the owner's own use of Claude. The dispatcher should therefore pause launches before the allowance runs out rather than fail mid-task.

## Still open

- **Jev access.** Jev is reachable today through Vercel AI Gateway, because TypeSafe's direct signups were paused on 22 September. Zero data retention there needs Vercel Pro. The recommendation is to decide when the Jev step is reached: after the skills work, and once a labelled test set exists to prove it against. Nothing is paid for now.
- A written data policy for what business text may leave the host.
- The reviewer's monthly budget (decision 4 of the self-shipping plan).
- Decisions 1–3 and 6 of the self-shipping plan.
