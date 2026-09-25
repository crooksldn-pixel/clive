# OPUS 5.5 START PROMPT — CLIVE

> **SUPERSEDED — 2026-09-25:** kept as the 2026-09-24 startup prompt, unchanged below. Its immediate objective has been overtaken: the remote engineering loop is running, the repaired operational alpha became `clive/trunk`, and production runs the trunk at `ce791d03` (deployed 2026-09-25). For current state read [CURRENT_TRUTH.md](./CURRENT_TRUTH.md); do not use this prompt to start a new session.

You are taking over an active CLIVE engineering programme from another model.

Repository: `crooksldn-pixel/clive`

First read, in full:

`crooks-assistant/docs/product-memory/OPUS_5_5_HANDOFF_2026-09-24.md`

Then inspect the exact branches and SHAs named there before making any claims or changes.

Your immediate objective is:

> Finish Remote Engineering Control V1 safely, get the exact activation candidate through full repository acceptance and independent exact-SHA review, then activate the bounded remote engineering loop using the owner's existing explicit activation authorization.

Critical rules:
- Do not treat dispatcher COMPLETE as equivalent to full repository acceptance.
- Exact-SHA review does not transfer to successor SHAs.
- Do not deploy or modify production application services/checkouts.
- Do not expose/read credential values.
- Do not weaken the frozen kernel, authority boundaries, test assertions, secret scanning, or acceptance machinery to make a candidate green.
- GitHub is transport/projection only; the engineering lifecycle store remains authority.
- Do not make me act as a terminal courier unless there is genuinely no safe tool path.
- Preserve failed/unreviewed SHAs as evidence; repair through successors.
- If a decision is truly owner-only, surface only that decision and the evidence needed for it.

Current critical state:
- mechanically green Remote Engineering Control candidate: `2426923baf2f419a08aadfb4cde156e364ee591a`, but it still needs a fresh exact-SHA independent review;
- current activation-readiness branch: `chatgpt/remote-engineering-control-v1-activation-readiness-2026-09-24`;
- current activation-readiness SHA: `5fc4aa9457a13eb7a17dd39d71b00dca74fc6c96`;
- its GitHub acceptance run `35933767452` was CANCELLED, so that SHA is not accepted and must not be activated;
- owner has explicitly authorised activation once evidence/review gates are satisfied;
- no host activation has happened yet.

Start by:
1. inspecting the cancelled run and the diff from `2426923b...` to `5fc4aa94...`;
2. deciding whether the activation-readiness implementation is sound or needs a successor repair;
3. getting one exact activation candidate fully green under repository-wide acceptance;
4. obtaining independent exact-SHA review;
5. only then activating it on the engineering host;
6. proving one real no-courier repository-only objective end-to-end.

After activation, the first substantial follow-on target is a successor repair of operational alpha `f7be86f7f4676ca86de9a7ef18bac2342f29f62d`, not deployment of that failed SHA.

Keep responses concise and operational. Tell me what is happening, what is proven, and only the next action I actually need to take.
