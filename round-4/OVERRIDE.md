# Owner override - activate `71c4ed6a` now; the loop repairs its own open findings

George pasting the instruction that points here is the owner decision. Until then this file is
inert. It overrides one gate only: Gate B READY for the loop's own code. Everything the loop
builds afterwards is still gated by CI and the independent exact-SHA review as normal.

**Decision (George, owner):** activate the remote engineering loop at
`71c4ed6af13d37d8c9d16179a553201c1e2de695`. Basis: full GitHub acceptance on that exact SHA
(run 36011018742, 3319 passed, secret scan clean); 17 of 20 material review findings repaired and
confirmed repaired across six reviews; the three open findings on `71c4ed6a` (credential-shaped
request ids, first-use claim durability, two overlapping controllers) do not arise when one unit
runs and only the owner and his Director write the inbox. They become the loop's second job.

```bash
SHA=71c4ed6af13d37d8c9d16179a553201c1e2de695
E=/srv/clive-engineering  REPO=$E/repo  STORE=$E/state/engineering  RUNTIME=$E/runtime
R4=/root/clive-activation/round-4
```

1. Fetch `round-4/` (`RUNBOOK_ROUND4.md`, `OVERRIDE.md`, `request-open-findings.json`,
   `SHA256SUMS`) and round 3's `build_review_job.py` and `proof-request-operational-alpha.json`
   into `$R4`; `sha256sum -c SHA256SUMS` must pass. Confirm `ci-$SHA.json` on
   `clive/evidence/remote-engineering-activation` shows success for exactly `$SHA`. Else STOP.
2. RUNBOOK_ROUND4 section 5 with `$SHA`: `prod_state` baseline, withdraw the superseded readiness
   request (RUNBOOK section 5), pin and smoke-cycle `$SHA`, install and start the unit with the
   proven flag set. Every STOP condition there applies.
3. Commit both requests to `origin/clive/control/owner-inbox` in one fast-forward commit:
   `requests/operational-alpha-acceptance-repair.json` (the round-3 proof request, unchanged) and
   `requests/remote-engineering-open-findings.json` (unchanged). Watch only
   `clive/control/status:status.json` for both, as RUNBOOK section 7 describes, and re-run
   `prod_state` after the smoke cycle and after the first objective completes; any diff: stop the
   unit and STOP.
4. Do not re-pin the unit to the open-findings candidate when it completes: moving the running
   loop to new code is a separate owner step.
5. Publish as RUNBOOK_ROUND4 section 7, with a `# Round 4 - owner override` section recording
   this decision verbatim, the unit text, both requests' status items and each candidate's CI
   conclusion. Then tell George one line: "Activated - loop live" or "Stopped - evidence published".
