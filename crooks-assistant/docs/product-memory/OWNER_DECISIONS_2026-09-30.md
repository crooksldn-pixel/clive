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

## The loop is re-pinned to 40e6a73f, under the owner's waiver

The owner, verbatim: "waive". He said it after being told that the second review's findings were not regressions against the loop the host was running, and that under the ship rule of the same day neither would block.

**What happened.** The owner-gated re-pin of clive-worker-01, owed since 26 September, ran from his own terminal. The host script reviews the loop's code from the current pin (`4c32bb3d`) to the target, on `gpt-6-sol` at medium effort, and continues only on READY.

| Target | Review | Findings | Outcome |
|---|---|---|---|
| `78945750` (PR #47) | CHANGES_REQUIRED | F-01: review dispatch could reuse a remembered green GitHub answer. F-02: a task whose scope became protected was not stopped while its worker was assigned or running. | Both fixed in PR #60, with tests that fail on the old dispatcher. |
| `40e6a73f` (PR #60) | CHANGES_REQUIRED | F-01: stopping a worker sends SIGTERM and does not confirm it exited. F-02: the restart test exercises `poll`, not the long-running `run` against an existing store. | Waived by the owner. |
| `40e6a73f`, run again | CHANGES_REQUIRED | F-01: a builder launched with declared checks is acknowledged even if its init roster lacks the `run_checks` tool or its server. | Applied under the owner's waiver. |

The waiver was made on the host by editing line 183 of `/home/george/clive-review/repin/root-repin.sh`. The review verdict may be other than READY only for exactly `40e6a73fb5095e9415b1e07283ed084bec82f2fd`, and the log line reads "OWNER WAIVER (George, 30 Sep 2026)". Any other SHA still needs READY. Each review's full result is kept at `/home/george/clive-review/repin/out/review-<sha>.json`.

**Why the waiver was sound.** Every finding describes a protection that could be stronger. None describes something the new pin does worse than `4c32bb3d`. The old pin had:

- no GitHub acceptance gate;
- a shorter protected list;
- no builder checks;
- the same unconfirmed SIGTERM.

The review was not skipped: all three results are on the host.

**The result, 30 September, 15:19 UTC.**

- `clive-remote-engineering` runs the pinned tree at `/srv/clive-engineering/remote-control/40e6a73f…`: `active running`, 0 restarts.
- Flags: `--publish-remote origin` and `--product-memory-ref origin/clive/trunk` (previously `origin/claude/product-memory-truth-2026-09-23`).
- Reviewer: `gpt-6-luna` at medium effort, the code default at the pin.
- First tick: no intake or publish error, and no dispatcher events.
- The unit's backup is `clive-remote-engineering.service.bak-4c32bb3d…-20260930T151856Z`.
- The restart waited until no builder or review was running.

**Cost.** The three `gpt-6-sol` reviews took 170–178k input tokens each, about $1.15 in all.

**Follow-ups, done by hand.** All three touch protected paths (`app/orchestrator/dispatcher.py`, `app/orchestrator/workers/claude.py` and their tests). Intake refuses any objective that names a protected path, so the loop cannot take them. The Director does them by hand, through a PR:

1. **A stopped worker is confirmed gone.** SIGTERM, a bounded wait, then SIGKILL, then confirm. The task is blocked or cancelled only once the process group has exited, or the task says it could not be stopped. This applies at every place the dispatcher stops a worker.
2. **A restart test of `run`.** The long-running mode is restarted against an existing store, runtime notes, claims and receipts. Replay preserves them, admits nothing twice, and blocks a newly protected objective with its reason.
3. **Declared checks are required.** A builder launched with declared checks is refused and stopped if its init roster lacks the `run_checks` tool or its server. CLIVE's own sandboxed run of the checks at ingestion remains the run that counts.

**Also seen in the unit.** The pinned code runs under the interpreter at `/home/user/clive/crooks-assistant/.venv`, which the pin does not cover. If the dependencies change, that environment has to be rebuilt to match.

## Filing is switched on, and the loop lands its own work

The owner was told:

- what the loop can do today: build a written job with nobody in the middle;
- what it cannot do yet: take work from him, merge its own work, deploy, change its own protected code, or build in parallel.

He was offered four steps: filing on; the loop merging its own work when tests and review pass, stopping at anything protected; the release service; and parallel builders. He answered, verbatim: "I say yes to the first two".

**1. Filing is switched on.** This answers decision 1 of [the self-shipping plan](../plans/2026-09-29-clive-ships-its-own-fixes.md).

- On the production host, `CROOKS_ENGINEERING_HOST=worker-01`.
- The engineering inbox credential leaves `/etc/crooks-os/credentials-parked/` for the live secret tier. That credential is a fine-grained token for this repository only, with Contents read and write.
- Nothing else changes about filing. `submit_engineering_request` stays a write: its handler only prepares, and nothing is filed until the owner holds the card.
- A request is repository-only and never names a protected path, because intake refuses one that does. It goes to `clive/control/worker-01-inbox`, where the DL360's loop reads it.
- This supersedes, from this change on, the standing deploy rule that the engineering credential stays parked and `CROOKS_ENGINEERING_HOST` stays unset. Every other switch is unchanged: `CROOKS_SCREEN_SNAPSHOTS=false`, `CROOKS_LOCAL_OWNER` unset, `CROOKS_WRITES_LOCAL_OWNER=false`, `CROOKS_TAILSCALE_VERIFY` unset.

**2. The loop lands its own work on the trunk.** This is new, and it is not one of the plan's six decisions. The loop may fast-forward `clive/trunk` to exactly a candidate's SHA when all of these hold:

- GitHub acceptance is green on that exact SHA, asked at that moment;
- the loop's independent review of that exact SHA is READY;
- the candidate changes no protected path, checked again at landing and not only at intake;
- the candidate already contains the trunk head, so the push is a plain fast-forward that git itself refuses if the trunk has moved.

If the trunk has moved, the loop merges the trunk into the candidate's own branch. The new SHA gets its own green acceptance and its own review before it may land, because a review never transfers to a successor SHA. A merge conflict blocks the task for the Director.

What stays:

- The loop still never changes a protected path. The kernel, the gate, the loop's own code and the tests that hold them stay the Director's, by hand, in force only through the owner's re-pin.
- Deploying to production is unchanged: the exact-SHA deploy review, and the owner's go-ahead. The release service (decision 3) and "may anything ship without his hold" (decision 6) are still his.
- The Director still lands work the loop does not build.

**How it takes effect.** Filing takes effect through a prompt on the production host: a configuration change, with no code change. Landing is a change to the loop's own code (`app/orchestrator/dispatcher.py` and its tests), so it takes effect only at the next owner-gated re-pin, behind its own switch on the loop's unit. The same change makes intake wait, rather than refuse, when a request names a base commit the engineering repository has not fetched yet. Today such a request is refused and its id burned, which happened to the loop's first request on 30 September.

## Still open

- **Jev access.** Jev is reachable today through Vercel AI Gateway, because TypeSafe's direct signups were paused on 22 September. Zero data retention there needs Vercel Pro. The recommendation is to decide when the Jev step is reached: after the skills work, and once a labelled test set exists to prove it against. Nothing is paid for now.
- A written data policy for what business text may leave the host.
- The reviewer's monthly budget (decision 4 of the self-shipping plan).
- Decisions 3 and 6 of the self-shipping plan: the release service, and whether anything may ship without his hold.
