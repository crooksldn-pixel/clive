# Remote Engineering Control V1 — activation run report

**Outcome: NOT ACTIVATED. Stopped at RUNBOOK §9.**

Stop condition, exactly as §9 states it: *"Two failed rounds ... STOP."* Two successor
repairs of `$SHA` were authored and gated; the independent GPT exact-SHA review returned
`CHANGES_REQUIRED` for the original candidate and for both successors. No third successor
was authored. Sections 5, 6 and 7 of the runbook were never entered: nothing was
withdrawn, nothing was blocked, no unit was installed, no loop was started and no proof
objective was queued.

Run window: 2026-09-24 11:31Z – 12:38Z. Host `crooks-os-prod-1`.

---

## 1. Discovery (§1)

| Fact | Value |
|---|---|
| `$TRUSTED` (`/srv/clive-engineering/src`) HEAD | `c566a955903a3a02e4a9ec97f0bab5a62e703fcd` |
| Worktree clean | yes (`git status --porcelain` empty) |
| `$TA` | `/srv/clive-engineering/src/crooks-assistant` |
| Reviewer code vs pinned baseline `c566a955` | identical (`git diff --quiet … reviewers` exit 0) |
| `$PY` / `$VENV` | `/home/user/clive/crooks-assistant/.venv/bin/python` (Python 3.12.3) present |
| Dispatcher / remote-engineering processes running | none (`pgrep` matched only this session's own shell) |
| `clive*` systemd units | none present, none installed |
| `/srv/clive-engineering/remote-control` | did not exist; still does not |
| Receipts (`$STORE/remote_engineering/receipts/`) | did not exist; still does not |
| Package integrity | all six `SHA256SUMS` entries verified OK |

No dispatcher `run` was active, so the §1 STOP condition did not apply and no 30-minute
wait was needed.

### Objective stages at discovery (and unchanged at the end of the run)

| Objective | Stage |
|---|---|
| `derived-truth-attention-v1` | COMPLETE |
| `engineering-team-activation-v1` | COMPLETE |
| `mobile-dogfood-voice-v1` | COMPLETE |
| `remote-engineering-control-v1-repair-1` | OWNER_GATE (`blocker_class: owner_only`) |
| `remote-engineering-control-v1-repair-2` | COMPLETE |
| `remote-engineering-control-v1` | BLOCKED (`deterministic`: worker results refused twice; last `result_refused: checks failed on f496bf61… : remote (exit 1)`) |

Every objective was COMPLETE, BLOCKED or OWNER_GATE, so the §6 precondition would have
been satisfied had the gates passed. The OWNER_GATE and BLOCKED items were left exactly
as found: neither was resumed, lifted or altered.

### Last proven dispatcher invocation (§1.2)

Recovered from `/root/.bash_history` (19 `run` invocations, all with the same flag set;
the three most recent are identical):

```
/home/user/clive/crooks-assistant/.venv/bin/python \
  /srv/clive-engineering/src/crooks-assistant/scripts/engineering_dispatcher.py \
  --store /srv/clive-engineering/state/engineering \
  --repo /srv/clive-engineering/repo \
  --runtime-root /srv/clive-engineering/runtime \
  --workspace-root /srv/clive-engineering/workers \
  --operator "clive-team-controller@$(hostname)" \
  --max-concurrent 1 --publish-remote origin \
  --gpt-api-key-file /root/.config/clive-engineering/openai_api_key \
  --worker-token-file /root/.config/clive-engineering/claude_oauth_token \
  --check-ro-path /home/user/clive/crooks-assistant/.venv \
  --check-ro-path /opt/node22 \
  run --interval 15
```

Differences from `clive-remote-engineering.service.template`, and which the runbook says
to prefer:

- **`--check-ro-path`**: the template carries one (`__VENV__`); every proven run carried
  **two**, adding `/opt/node22`. The proven pair would have been used at §6.2 and the
  deviation recorded there. (This is recorded here rather than applied, since §6 was
  never reached.)
- **worker model / effort**: never passed explicitly in any proven invocation. The
  observed worker roster shows the default `claude-sonnet-5`. The template also passes
  them implicitly (it sets neither), so there is no conflict.
- **`--worker-cli`**: never passed explicitly; the template pins `/usr/local/bin/claude`,
  which exists and resolves to the packaged `claude.exe` binary. No conflict.

### Production baseline (§1.6)

`touch /tmp/clive-activation.marker` at `2026-09-24T11:35:34Z`. Units at baseline:

```
crooks-assistant.service      active
crooks-bridge-watcher.service active
```

---

## 2. Publication of the candidate (§2)

The branch was reported as possibly already existing with its acceptance run done. **It
did not exist.** `git ls-remote origin refs/heads/claude/remote-engineering-control-v1-activation-successor-2026-09-24`
returned nothing and `GET /repos/crooksldn-pixel/clive/commits/c23f1935…` returned HTTP
422, so §2 and §3 were executed for real rather than skipped.

- `git bundle verify` → OK; contains exactly `c23f1935…`, requires parent `abaefa5228880c266e52f35f009527be7344c05e`.
- Fetched from the bundle; local branch resolved to exactly `$SHA`.
- Pushed `c23f1935…:refs/heads/claude/remote-engineering-control-v1-activation-successor-2026-09-24` — new branch, fast-forward, nothing rewritten, no force.

Diff `abaefa52..c23f1935` touched 9 files, all within `crooks-assistant/app/remote_engineering/`,
`scripts/remote_engineering.py`, `tests/test_remote_engineering.py` and the
`REMOTE_ENGINEERING_CONTROL_V1.md` product-memory doc.

---

## 3. SHAs, CI runs and gate outcomes

| # | SHA | Parent | Acceptance run | Conclusion | `mechanical_evidence` | `eligible` | Gate A | Gate B (GPT exact-SHA) |
|---|---|---|---|---|---|---|---|---|
| candidate | `c23f193520b0a25e73df5ce91d7845f77584d971` | `abaefa52` | [35994015937](https://github.com/crooksldn-pixel/clive/actions/runs/35994015937) | success | complete | true | **PASS** | **CHANGES_REQUIRED** (4 material) |
| successor 1 | `05fe80463f75dce4bc6349ce471e4113f0b6a6b1` | `c23f1935` | [35996970816](https://github.com/crooksldn-pixel/clive/actions/runs/35996970816) | success | complete | true | **PASS** | **CHANGES_REQUIRED** (4 material) |
| successor 2 | `62f6e7e51f72d87c3f7caae2552f0cc5eea66e85` | `05fe8046` | [35999394632](https://github.com/crooksldn-pixel/clive/actions/runs/35999394632) | success | complete | true | **PASS** | **CHANGES_REQUIRED** (5 material) |

Reviewed base for all three reviews: `6c300c5f9a349bf2da397ecd2ac7a263849dbc60`
(kept constant per §9). Reviewer principal `gpt`, mechanism
`openai-responses:gpt-5.6-sol`, effort `high`, `courier: false`, one run each — no
transient API failure, so no `--run 2`/`--run 3` was needed.

No CI rerun was required: every acceptance run passed first time, all five gates
(`ruff`, `pytest_control_plane`, `product_memory_structure`, `pytest_offline_full`,
`secret_scan`) with `unsatisfied_gates: []` and `malformed_gates: []`. Offline suite size
grew `3234 → 3250 → 3266` as regression tests were added; `secret_scan` reported
"no leaks found" on all three.

`build_review_job.py` reported `protected_hits: []` for all three SHAs — no protected
path was touched at any point.

---

## 4. Gate B findings

### Round 0 — `c23f1935` (CHANGES_REQUIRED, 4 material)

| ID | Finding |
|---|---|
| F-01 | A mixed snapshot could admit a new objective before reporting an immutable-ID violation; intake was not atomic. |
| F-02 | Raw transport text (git output, which names the remote; an authenticated URL carries a credential) reached `intake_error`/`publish_error` and the process log. |
| F-03 | Malformed inbox records were never represented in the GitHub-visible projection. |
| F-04 | `--interval`/`--status-heartbeat-s` accepted arbitrary floats (NaN/inf/0/negative). |

### Round 1 — successor `05fe8046` (CHANGES_REQUIRED, 4 material)

Repairs to the four above were accepted as present, and four new material findings were
raised:

| ID | Finding |
|---|---|
| F-01 | `base_ref` was not bounded as a git ref: URLs, option-like strings and revision expressions reached `git rev-parse`, and the raw value was echoed into a published refusal. |
| F-02 | `redact_validation_error` copied pydantic `loc` segments verbatim; for a forbidden extra field that segment *is* the requester's key name, so a credential in a key **name** survived. |
| F-03 | `source`/`refusal_id` copied an unvalidated git tree path; a credential-shaped filename under `requests/` reached the public status branch. |
| F-04 | `_validate_name`/`_validate_remote` echoed the rejected value, so one-shot `poll` printed a mistyped authenticated URL. |

### Round 2 — successor `62f6e7e5` (CHANGES_REQUIRED, 5 material) — **terminal**

Repairs to the four above were accepted as present ("repairs the four previously listed
cases"), and five new material findings were raised:

| ID | Finding |
|---|---|
| F-01 | No aggregate work bound on an inbox snapshot: record count, listing bytes, blob bytes, aggregate bytes and total intake-cycle time are unbounded, so a large snapshot can starve the long-lived loop and stall supervision of existing objectives. |
| F-02 | `_NAME_RE` uses an unbounded `+` and `_validate_name` has no maximum length; noncanonical git identifiers (`.` components, `.lock` endings) are admitted and left for git to reject. |
| F-03 | A credential-*shaped* value that passes the permissive remote/branch syntax (e.g. `ghp_…`) is still embedded in `TransportError` and printed verbatim by one-shot `poll`. The round-1 test only covered values rejected *before* git. |
| F-04 | `git fetch <remote> <branch>` omits `--no-tags`, so git may auto-follow tags into local refs outside the dedicated inbox ref — and those tags can then become resolvable `base_ref` values. |
| F-05 | `_validate_status_path` has no character allowlist and accepts tab/newline; the value is interpolated into newline-delimited `git mktree` input, so a crafted `--status-path` can inject a second tree record and break the single-file projection invariant. |

The full typed results are committed beside this report.

---

## 5. Successor repairs authored (§9)

Two successors, the maximum §9 allows. Both are **new commits on `$BRANCH`** — nothing
was amended, no SHA was rewritten, no force-push was used. Every changed path in both
commits was inside the §9 allowlist (verified mechanically before each commit):
`crooks-assistant/app/remote_engineering/`, `crooks-assistant/scripts/remote_engineering.py`,
`crooks-assistant/tests/test_remote_engineering.py`,
`crooks-assistant/docs/product-memory/REMOTE_ENGINEERING_CONTROL_V1.md`.

- **`05fe8046` — "Make remote intake atomic and every loop bound explicit"** (11 files,
  +405/−47): snapshot preflight before any write; bounded `TransportError`; `refused_records`
  projection keyed by source+digest; finite/range-checked `--interval` and
  `--status-heartbeat-s`.
- **`62f6e7e5` — "Echo nothing a requester or a mistyped flag supplied"** (7 files,
  +269/−29): schema-level bounded `base_ref`; `loc` filtered through a host-defined label
  allowlist; `source` reduced to `<directory>/<request_id>.json` or an opaque
  `<directory>/#<sha256>` locator; rejected remote/branch/path values no longer printed.

No test assertion was weakened. Two existing assertions were **strengthened** because
round 0's F-02 explicitly required it ("Update the regression test to prove the token-like
value is absent from both the projection and all CLI output/result fields"):

- `test_an_intake_transport_failure_never_projects_raw_git_output`: the assertion
  `"SYNTHETIC-NOT-A-TOKEN" in result["intake_error"]` (which asserted the *presence* of
  raw transport text) became an assertion of its absence from the entire result.
- `test_a_publish_failure_is_reported_and_the_cycle_completes`: `"push rejected" in
  result["publish_error"]` became an assertion of the bounded code plus the absence of the
  raw text.

One test helper was made more capable (`commit_request` now creates parent directories,
so a nested-path regression test can exist). No behaviour of existing tests changed.

---

## 6. What was NOT done

| Runbook section | Status |
|---|---|
| §5 Neutralise the superseded inbox request | **Not reached.** `origin/clive/control/owner-inbox` is untouched at `cc9ab83887cc1850c75a2e9403dc8db9f5a9d7b1`; `requests/remote-engineering-control-v1-activation-readiness.json` is still present. It has **no receipt** (the receipts store does not exist), so had the gates passed, the first §5 branch would have applied: `git rm` on a fresh worktree, fast-forward push. Nothing was withdrawn and no `block` was issued. |
| §6 Activate | **Not reached.** No `$E/remote-control/$SHA` pin was cloned, no smoke cycle was run, no unit file was written, `systemctl daemon-reload`/`enable`/`start` were never invoked. There is no installed unit text to report: `/etc/systemd/system/` contains no `clive*` unit. |
| §7 Prove the no-courier path | **Not reached.** No proof request was committed to the inbox, no objective `remote-loop-dispatcher-timing-parity` exists, and there is no status.json item or candidate CI conclusion to report. |

`origin/clive/control/status` does not exist — the loop never ran, so no projection was
ever published.

---

## 7. Production-untouched proof

Taken after the run, against the `2026-09-24T11:35:34Z` marker:

```
$ find /opt/crooks-interactive /opt/crooks-os -newer /tmp/clive-activation.marker
(no output)

$ systemctl is-active crooks-assistant.service crooks-bridge-watcher.service
active
active            # identical to the recorded baseline

$ ls /etc/systemd/system/ | grep -i clive
(no output)
```

`/opt/crooks-interactive`, `/opt/crooks-os`, their units and every production checkout
were never written, and no production service was started, stopped or reloaded. The
engineering store was only ever read (`engineering_dispatcher.py … status --json`); no
kernel verb that mutates it was invoked, and its six objectives are in exactly the stages
recorded at discovery. No credential value was read, printed, copied or committed at any
point: key files were referred to by path only, and the reviewer read the OpenAI key
itself.

---

## 8. Deviations from the runbook, with reasons

1. **Sandboxed pre-flight of candidate checks before each push.** Before committing each
   successor I ran `ruff` and the candidate test suites inside the project's own
   `NamespaceSandbox` (linux namespaces — mount/net/pid/ipc/uts — chroot, uid 65534, no
   capabilities; canary held), on a disposable copy of the tree.
   *Reason:* §0 forbids running candidate tests **unsandboxed** on the host, and requires
   that mechanical evidence come from GitHub CI only. Both conditions are honoured: the
   runs were sandboxed, and every gate outcome reported above comes from GitHub. The
   pre-flight was justified by the §9 budget of only two successors — it caught two real
   defects in my drafts (a negative outcome filter that swept up an unrelated stub, and a
   filename-bounding rule that a credential-shaped but syntactically valid filename
   defeated) that would otherwise have consumed a repair round.
   Under the sandbox the full offline suite showed 10 failures
   (`test_gpt_reviewer.py` ×7, `test_launch.py::test_port_open_sees_a_real_listener`,
   `test_web_js.py::test_the_service_worker_under_node`,
   `test_acceptance_provenance.py::test_cli_refuses_with_exit_two_and_still_emits_readable_json`).
   A control run of the **unmodified** candidate `c23f1935` in the same sandbox produced
   the identical 10 failures, so they are artifacts of the sandbox's network isolation and
   chroot, not of any change made here. GitHub CI passed all of them for all three SHAs.

2. **Extra evidence files.** §8 names `$SHA.review.json` and `ci-$SHA.json`. Because two
   successors were authored, the equivalent files for `05fe8046` and `62f6e7e5` are
   committed as well, so that "every SHA and run id" in §8 is fully covered.

3. **The premise in the activation instruction was incorrect** (branch already pushed and
   accepted). It was verified rather than assumed, found false, and §2/§3 were executed in
   full. Recorded here because it changed what the run had to do.

No other deviation. No protected path, frozen kernel, test assertion, secret-scanning
rule, CI workflow or acceptance machinery was weakened at any point. No force-push, no
amended commit, no rewritten SHA.

---

## 9. Where this leaves the work

`$BRANCH` = `claude/remote-engineering-control-v1-activation-successor-2026-09-24` is at
`62f6e7e5`, which has full GitHub acceptance for its exact SHA and carries the repairs for
the eight material findings of rounds 0 and 1. It is **not** activation-approved: the
round-2 review raised five further material findings, listed in §4 above and typed in
`62f6e7e51f72d87c3f7caae2552f0cc5eea66e85.review.json`.

§9's limit is reached, so the next step is an owner decision, not another autonomous
repair round.

---

# Round 3 — gate `ca047b89` (RUNBOOK_ROUND3.md)

**Outcome: NOT ACTIVATED. Stopped at RUNBOOK_ROUND3 §4.**

Stop condition, exactly as §4 states it: *"`CHANGES_REQUIRED`: STOP. Do not author a repair;
publish (section 7 below) and end."* The independent GPT exact-SHA review of
`ca047b8963bcbf7124f71037a2fa14fc4853ab8d` returned `CHANGES_REQUIRED` with two material
findings, judged against the owner's own frozen materiality standard. No repair was
authored. Sections 5 (activate) and 6 (operational-alpha proof) were never entered.

Run window: 2026-09-24 13:18Z – 13:31Z. Host `crooks-os-prod-1`.

## R3.1 Package check (§1)

| Fact | Value |
|---|---|
| Source ref | `origin/clive/evidence/activation-round-3` |
| Files fetched | `RUNBOOK_ROUND3.md`, `build_review_job.py`, `round3.patch`, `proof-request-operational-alpha.json`, `SHA256SUMS` |
| `sha256sum -c SHA256SUMS` | all 4 entries OK |
| Prior findings extracted from published `62f6e7e5.review.json` | **5** (F-01…F-05), so the §1 STOP threshold ("fewer than five") did not apply |

## R3.2 Verification of the new `--materiality` flag

This flag shapes the independent review gate, and RUNBOOK §0 forbids weakening the
acceptance machinery, so it was checked before use rather than taken on trust.

- `build_review_job.py` differs from the round-1 builder only by a `block()` extractor and
  an optional section. It changes nothing about protected-path checking, the candidate
  SHA/base checks, the packet's criteria, or the reviewer invocation.
- Both quoted blocks are real and were read independently from git at
  `origin/chatgpt/product-memory-reconcile-2026-09-23` (`95227cc27729bf7a5ecba8de09e493666342c89e`):
  `DECISIONS.md` line 832 `## DEC-057 — Verification must reduce subject uncertainty, not
  justify itself` (dated 2026-09-21, ACTIVE ENGINEERING DIRECTION), and
  `RECONCILIATION_2026-09-23.md` line 302 `### Self-referential convergence rule`.
- The generated `packet.md` was inspected: both blocks appear complete and unaltered, with
  no truncation or paraphrase.
- The standard does **not** soften the gate in the direction that mattered in rounds 0–2.
  The framing keeps material: any failure of an acceptance criterion, **and** "any
  credential or secret value reaching a receipt, log, output or the public projection".
  DEC-057 itself closes with "This does not weaken independent review, safety gates or
  owner-only authority." What it makes non-blocking is only *newly invented* hardening
  beyond the frozen criteria, recorded as `material=false` backlog.

Conclusion recorded for the owner: `--materiality` is the owner's own documented doctrine
applied to the situation it was written for, not a tilted gate. Its effect is visible in
the result — the reviewer returned two findings and marked **both** material, so the
standard did not prevent a block.

## R3.3 Candidate reproduction and publication (§2)

```
git am --committer-date-is-author-date round3.patch  onto 62f6e7e5
HEAD = ca047b8963bcbf7124f71037a2fa14fc4853ab8d   (exact match, no fallback needed)
HEAD^ = 62f6e7e51f72d87c3f7caae2552f0cc5eea66e85   (declared PARENT)
push: 62f6e7e5..ca047b89 -> claude/remote-engineering-control-v1-activation-successor-2026-09-24
```

Fast-forward from `$PARENT`; nothing amended, no SHA rewritten, no force. The patch touched
5 files (+304/−65), all inside the section 9 allowlist (verified mechanically):
`app/remote_engineering/{errors,inbox,publisher,runner}.py` and
`tests/test_remote_engineering.py`. `build_review_job.py` reported `protected_hits: []`.

## R3.4 Gate A (§3) — PASS

| Field | Value |
|---|---|
| Run | [36004882143](https://github.com/crooksldn-pixel/clive/actions/runs/36004882143) |
| Head SHA | `ca047b8963bcbf7124f71037a2fa14fc4853ab8d` (exact) |
| Conclusion | success (first attempt; no rerun needed) |
| `mechanical_evidence` | complete |
| `eligible_for_acceptance_decision` | true |
| `unsatisfied_gates` / `malformed_gates` | `[]` / `[]` |
| Gates | ruff pass · pytest_control_plane 44 passed · product_memory_structure pass · pytest_offline_full **3296 passed**, 14 skipped · secret_scan "no leaks found" |

Offline suite growth across the whole activation effort: 3234 → 3250 → 3266 → **3296**.

## R3.5 Gate B (§4) — CHANGES_REQUIRED (terminal)

Reviewer principal `gpt`, kind `model`, `read_only: true`, mechanism
`openai-responses:gpt-5.6-sol`, effort `high`, `courier: false`, one run (no transient
failure, so no `--run 2`/`--run 3`). Result validates as `clive.review_result.v1` with
`candidate_sha == ca047b89…`.

The reviewer accepted that the five findings of the `62f6e7e5` round are "substantially
addressed", and raised two new findings, **both marked material**:

| ID | Material | Finding |
|---|---|---|
| F-01 | true | A bounded malformed JSON record can terminate the long-lived process before the Dispatcher advances. `parse_request` converts only `UnicodeDecodeError` and `JSONDecodeError`; Python's decoder can also raise `RecursionError` on deeply nested JSON and `ValueError` on an over-limit integer, neither caught around `poll_once`. A sub-64 KiB record can therefore stop supervision of existing objectives. |
| F-02 | true | The operator-supplied `--directory` is neither bounded nor redacted and is copied verbatim into `Receipt.source` and the projection's `source`/locator fields, so a credential-shaped directory reaches printed outcomes, a durable receipt and the public status projection. |

Both sit squarely inside what the frozen standard preserves as material: F-01 is a failure
of the "malformed schema fails closed" criterion *and* of the requirement that the loop keep
advancing the existing Dispatcher; F-02 is precisely "a credential or secret value reaching
a receipt, log, output or the public projection". The materiality standard was therefore
applied and still blocked — it was not a route to READY.

## R3.6 Gate outcomes across all four exact SHAs

| # | SHA | Acceptance run | Gate A | Gate B |
|---|---|---|---|---|
| candidate | `c23f1935` | 35994015937 | pass | CHANGES_REQUIRED (4 material) |
| successor 1 | `05fe8046` | 35996970816 | pass | CHANGES_REQUIRED (4 material) |
| successor 2 | `62f6e7e5` | 35999394632 | pass | CHANGES_REQUIRED (5 material) |
| round 3 | `ca047b89` | 36004882143 | pass | CHANGES_REQUIRED (2 material) |

Reviewed base held constant at `6c300c5f9a349bf2da397ecd2ac7a263849dbc60` for all four.
Fifteen material findings raised, thirteen repaired and confirmed repaired by the next
review. Every SHA passed full GitHub acceptance; the gate that has never passed is the
independent review.

## R3.7 What was NOT done

| Section | Status |
|---|---|
| §5 Activate (RUNBOOK §§5–6 with `ca047b89`) | **Not reached.** No pin directory `$E/remote-control/ca047b89…` was cloned, no smoke cycle was run, no unit file was written, `systemctl daemon-reload`/`enable --now` were never invoked. There is no installed unit text to report. The proven flag set (adding `--check-ro-path /opt/node22` beside the venv path) was therefore never applied. The owner-inbox is untouched at `cc9ab83887cc1850c75a2e9403dc8db9f5a9d7b1`; the superseded readiness request is still present and still has no receipt. |
| §6 Operational-alpha proof | **Not reached.** `proof-request-operational-alpha.json` was **not** committed to the inbox. No objective `operational-alpha-acceptance-repair` exists, no candidate was produced for `f7be86f7`, and there is no status.json item or candidate CI conclusion to report. |

`origin/clive/control/status` still does not exist — the loop has never run, so no
projection has ever been published. The engineering store has no `remote_engineering/`
directory: nothing has ever been admitted through remote ingress.

## R3.8 Production and store state

The engineering store was read-only throughout round 3 (`engineering_dispatcher.py … status
--json` only). Its six objectives are unchanged from the first run's discovery:
`derived-truth-attention-v1` COMPLETE, `engineering-team-activation-v1` COMPLETE,
`mobile-dogfood-voice-v1` COMPLETE, `remote-engineering-control-v1-repair-1` OWNER_GATE,
`remote-engineering-control-v1-repair-2` COMPLETE, `remote-engineering-control-v1` BLOCKED.
The OWNER_GATE and BLOCKED items were not resumed, lifted or altered. No credential value
was read, printed, copied or committed; key files were referred to by path only.

`systemctl is-active` for `crooks-assistant.service` and `crooks-bridge-watcher.service` is
`active` for both — identical to the baseline recorded at `2026-09-24T11:35:34Z`. No
`clive*` unit exists in `/etc/systemd/system/`.

**Correction to the first report's production check, stated precisely.** The first report
recorded `find /opt/crooks-interactive /opt/crooks-os -newer /tmp/clive-activation.marker`
as empty; that was true when taken at 12:38Z. Re-run at 13:31Z it is **no longer empty**:

```
/opt/crooks-os/crooks-assistant/logs{,/assistant.log,/turns.jsonl,/anticipation,/anticipation/transitions.json}
/opt/crooks-os/crooks-assistant/.cache/media{,/<two cached images and their .type files>}
/opt/crooks-os/crooks-assistant/kb/.catalogue-cache.txt
```

Every one of these is a runtime artifact that the **live production assistant writes for
itself**: `crooks-assistant.service` has been running continuously since
`2026-09-24T06:59:48Z` (MainPID 3740098, cwd `/opt/crooks-os/crooks-assistant`) and the
timestamps fall at 12:44–12:51Z, inside its own activity. No source, configuration, unit or
service path changed, and nothing in this run wrote to `/opt` at any point — round 3 issued
no command that writes there.

This is recorded rather than glossed because it matters operationally: **RUNBOOK §6.4's
literal test ("`find …` is empty and every production unit's `is-active` equals the
baseline") would now produce a false positive on this host**, since a healthy production
assistant dirties its own log and cache directories within minutes. Had activation
proceeded, §6.4 would have demanded stopping the new unit for a benign reason. A future
runbook should scope that check to exclude the service's own `logs/`, `.cache/` and
`kb/.catalogue-cache.txt`, or compare a manifest of tracked source/config paths instead.

## R3.9 Deviations from RUNBOOK_ROUND3.md

1. **The `--materiality` flag was verified before use** (R3.2) rather than applied on
   trust: the two quoted blocks were read independently from git and the generated packet
   was inspected for faithful, untruncated inclusion. *Reason:* RUNBOOK §0 forbids
   weakening the acceptance machinery, and a flag that reshapes the review gate is exactly
   the kind of change that rule exists for. No change was made to the flag or its output;
   this is an added check, not a departure from the instructions.
2. **No sandboxed pre-flight was run this round.** The first run pre-flighted its own
   authored code in the project's `NamespaceSandbox`; round 3 authored nothing, and §4
   forbids authoring a repair, so there was nothing to pre-flight. Gate A supplied all
   mechanical evidence, as RUNBOOK §0 requires.
3. **The production-untouched check result changed and is reported as it actually is**
   (R3.8), including the false-positive risk in §6.4, rather than being reported as empty.

No other deviation. No protected path, frozen kernel, test assertion, secret-scanning rule,
CI workflow or acceptance machinery was weakened. No force-push, no amended commit, no
rewritten SHA, no repair authored.

## R3.10 Where this leaves the work

`claude/remote-engineering-control-v1-activation-successor-2026-09-24` is at `ca047b89`,
which holds full GitHub acceptance for its exact SHA and the repairs for thirteen of the
fifteen material findings raised across four reviews. It is **not** activation-approved:
two material findings remain, typed in
`ca047b8963bcbf7124f71037a2fa14fc4853ab8d.review.json`.

Both remaining findings are small and well-specified — a decoder-exception widening in
`parse_request` plus loop-level containment, and either fixing the inbox directory or
refusing to serialize the supplied text. Neither needs a protected path. But §4 of this
round's runbook forbids authoring that repair, so the next step is an owner decision, not
another autonomous round.

---

# Round 4 — gate `11ab9070` (RUNBOOK_ROUND4.md)

**Outcome: NOT ACTIVATED. Stopped at RUNBOOK_ROUND4 §4.**

Stop condition, exactly as §4 states it: *"`CHANGES_REQUIRED`: STOP, publish (section 7)
and end."* The independent GPT exact-SHA review of
`11ab9070650abd12a7f8f990e462d5d328f2fbd9` returned `CHANGES_REQUIRED` with one material
finding, judged against the same frozen materiality standard as round 3. No repair was
authored. Sections 5 (activate) and 6 (operational-alpha proof) were never entered.

Run window: 2026-09-24 13:49Z – 14:03Z. Host `crooks-os-prod-1`.

## R4.1 Package check (§1)

| Fact | Value |
|---|---|
| Round-4 files from `origin/clive/evidence/activation-round-4` | `RUNBOOK_ROUND4.md`, `round4.patch`, `SHA256SUMS` |
| Round-3 files reused from `origin/clive/evidence/activation-round-3` | `build_review_job.py`, `proof-request-operational-alpha.json` |
| `sha256sum -c SHA256SUMS` | all 4 entries OK |
| Reused files vs. the copies audited in round 3 | `cmp` byte-identical for both |
| Prior findings extracted from published `ca047b89.review.json` | **2** (F-01, F-02), so the §1 STOP threshold ("fewer than two") did not apply |

The runbook states the review builder is "round 3's, unchanged and already verified by
you". That was confirmed rather than assumed: both reused files were compared byte-for-byte
against the round-3 copies this session had audited, so round 3's `--materiality`
verification (R3.2) carries over unchanged. The generated packet was re-checked and again
contains the DEC-057 and self-referential-convergence blocks in full.

## R4.2 Candidate reproduction and publication (§2)

```
git am --committer-date-is-author-date round4.patch  onto ca047b89
HEAD = 11ab9070650abd12a7f8f990e462d5d328f2fbd9   (exact match)
HEAD^ = ca047b8963bcbf7124f71037a2fa14fc4853ab8d   (declared PARENT)
push: ca047b89..11ab9070 -> claude/remote-engineering-control-v1-activation-successor-2026-09-24
```

Fast-forward from `$PARENT`; nothing amended, no SHA rewritten, no force. The patch touched
7 files (+214/−26), all inside the section 9 allowlist (verified mechanically):
`app/remote_engineering/{controller,errors,inbox,requests,runner}.py`,
`scripts/remote_engineering.py` and `tests/test_remote_engineering.py`.
`build_review_job.py` reported `protected_hits: []`.

Notable surface change: the candidate **removes** the `--directory` CLI flag, so the inbox
directory is no longer operator input at all. That is a reduction in configurability, not a
weakening of a gate, and it is the reviewer's own preferred repair for `ca047b89` F-02
("Prefer a fixed inbox directory").

## R4.3 Gate A (§3) — PASS

| Field | Value |
|---|---|
| Run | [36008900056](https://github.com/crooksldn-pixel/clive/actions/runs/36008900056) |
| Head SHA | `11ab9070650abd12a7f8f990e462d5d328f2fbd9` (exact) |
| Conclusion | success (first attempt; no rerun needed) |
| `mechanical_evidence` | complete |
| `eligible_for_acceptance_decision` | true |
| `unsatisfied_gates` / `malformed_gates` | `[]` / `[]` |
| Gates | ruff pass · pytest_control_plane 44 passed · product_memory_structure pass · pytest_offline_full **3313 passed**, 14 skipped · secret_scan "no leaks found" |

Offline suite growth across the whole effort: 3234 → 3250 → 3266 → 3296 → **3313**.

## R4.4 Gate B (§4) — CHANGES_REQUIRED (terminal for this round)

Reviewer principal `gpt`, kind `model`, `read_only: true`, `context_fresh: true`, mechanism
`openai-responses:gpt-5.6-sol`, effort `high`, `courier: false`, one run (no transient
failure, so no `--run 2`/`--run 3`). Result validates as `clive.review_result.v1` with
`candidate_sha == 11ab9070…`.

The reviewer recorded that the two `ca047b89` findings "appear addressed" and raised one
new finding, marked material:

| ID | Material | Finding |
|---|---|---|
| F-01 | true | Authoritative intake and exact-byte provenance are not committed crash-safely. `intake()` writes the Objective/task **before** the acceptance receipt carrying `request_sha256` is persisted. A crash or receipt-write failure in that window leaves an admitted objective with no durable request digest; on restart, byte-different JSON that parses to the same request model is indistinguishable from the original until after intake, so the adapter can neither replay the original bytes idempotently nor reliably refuse the changed bytes. |

Required repair (recorded for the owner, not performed): persist an atomic immutable claim
binding `request_id` to `request_sha256` *before* any lifecycle write — without that claim
being lifecycle authority — resume or finalise only the claimed digest on restart, refuse
every different digest, and add fault-injection tests that interrupt after intake but
before the receipt.

This is a genuine failure of a frozen acceptance criterion ("restart and re-poll remain
idempotent and do not duplicate objectives, attempts, reviews or integrations", and
immutable-request replay safety), so `material: true` is correctly assigned under the
standard rather than being new hardening that the convergence rule would make backlog.

## R4.5 Gate outcomes across all five exact SHAs

| # | SHA | Acceptance run | Gate A | Gate B |
|---|---|---|---|---|
| candidate | `c23f1935` | 35994015937 | pass | CHANGES_REQUIRED (4 material) |
| successor 1 | `05fe8046` | 35996970816 | pass | CHANGES_REQUIRED (4 material) |
| successor 2 | `62f6e7e5` | 35999394632 | pass | CHANGES_REQUIRED (5 material) |
| round 3 | `ca047b89` | 36004882143 | pass | CHANGES_REQUIRED (2 material) |
| round 4 | `11ab9070` | 36008900056 | pass | CHANGES_REQUIRED (1 material) |

Reviewed base held constant at `6c300c5f9a349bf2da397ecd2ac7a263849dbc60` for all five.
Sixteen material findings raised; fifteen repaired and confirmed repaired by the next
review. Every SHA passed full GitHub acceptance on its first attempt; the gate that has
never passed is the independent review.

The per-round material count is falling (4, 4, 5, 2, 1) and each round's findings have been
confirmed fixed by the next, so the line is converging rather than churning. It has not yet
converged to zero.

## R4.6 What was NOT done

| Section | Status |
|---|---|
| §5 Activate | **Not reached.** No pin directory `$E/remote-control/11ab9070…` was cloned, no smoke cycle was run, no unit file was written, `systemctl daemon-reload`/`enable --now` were never invoked. There is no installed unit text to report. The proven flag set (adding `--check-ro-path /opt/node22`) was never applied. **`prod-before.txt` was not taken** and is therefore not among the published files: §5 specifies taking it "immediately before installing the unit", and no unit was ever installed. |
| §6 Operational-alpha proof | **Not reached.** `proof-request-operational-alpha.json` was **not** committed to the inbox. No objective `operational-alpha-acceptance-repair` exists, no `clive/objective/operational-alpha-acceptance-repair` ref exists, no candidate was produced for `f7be86f7`, and there is no status.json item or candidate CI conclusion to report. |

`origin/clive/control/status` still does not exist. The owner-inbox is untouched at
`cc9ab83887cc1850c75a2e9403dc8db9f5a9d7b1`; the superseded readiness request is still
present and still has no receipt. The engineering store still has no `remote_engineering/`
directory: nothing has ever been admitted through remote ingress.

## R4.7 Production and store state

The engineering store was read-only throughout round 4 (`engineering_dispatcher.py … status
--json` only). Its six objectives are unchanged from the original discovery:
`derived-truth-attention-v1` COMPLETE, `engineering-team-activation-v1` COMPLETE,
`mobile-dogfood-voice-v1` COMPLETE, `remote-engineering-control-v1-repair-1` OWNER_GATE,
`remote-engineering-control-v1-repair-2` COMPLETE, `remote-engineering-control-v1` BLOCKED.
The OWNER_GATE and BLOCKED items were not resumed, lifted or altered. No credential value
was read, printed, copied or committed; key files were referred to by path only.

**The replacement production check from §5 works.** Although §5 was not reached, its
`prod_state` function was exercised read-only to confirm it is sound before relying on it:

- Both `/opt/crooks-os` and `/opt/crooks-interactive` take the **git branch** of the
  function (both are git repositories); the manifest branch was not used for either.
- `/opt/crooks-os` `ca388ceeedb54cfd495fb2b5205ec2184db9ccae`, `/opt/crooks-interactive`
  `31fb755360ae40959c14d608de0035815c41cc40`, and both report a tracked-file dirty hash of
  `e3b0c44298fc1c14` — the sha256 of empty input, i.e. no modified tracked file.
- Sampled twice 20 s apart, the whole `prod_state` output was byte-identical, and both
  production units are `active`, matching the original baseline.

This confirms the round-3 report's R3.8 concern is resolved: the new check is stable where
the old `find … -newer` test now false-positives on the live assistant's own logs and
caches. Recorded here so a future round can rely on it.

## R4.8 Deviations from RUNBOOK_ROUND4.md

1. **The reused round-3 artifacts were re-verified rather than trusted.** §1 states the
   builder and proof request are "unchanged and already verified by you"; both were
   compared byte-for-byte (`cmp`) against the round-3 copies, and the generated packet was
   re-inspected for the complete materiality blocks. *Reason:* the `--materiality` flag
   shapes the review gate, and RUNBOOK §0 forbids weakening the acceptance machinery. No
   change was made; this is an added check.
2. **`prod_state` was exercised read-only before §5 would have needed it** (R4.7), to
   establish which branch each directory takes and that its output is stable. *Reason:* the
   check exists because round 3 found the previous one unreliable; confirming the
   replacement is sound is cheap and was worth doing even though activation did not follow.
   No baseline file was written, since §5 was never entered.
3. **The builder's cosmetic prior-findings heading was left alone**, as §4 instructs ("the
   builder's prior-findings heading still names `abaefa52`; the findings listed are the
   `ca047b89` review's. Cosmetic; do not edit the builder."). Recorded so the wording in
   the published packet is not mistaken for a wrong-SHA provenance error.

No other deviation. No protected path, frozen kernel, test assertion, secret-scanning rule,
CI workflow or acceptance machinery was weakened. No force-push, no amended commit, no
rewritten SHA, no repair authored.

## R4.9 Where this leaves the work

`claude/remote-engineering-control-v1-activation-successor-2026-09-24` is at `11ab9070`,
which holds full GitHub acceptance for its exact SHA and the repairs for fifteen of the
sixteen material findings raised across five reviews. It is **not** activation-approved: one
material finding remains, typed in
`11ab9070650abd12a7f8f990e462d5d328f2fbd9.review.json`.

The remaining defect is a crash window between `intake()` and the acceptance receipt. It is
narrow and the required repair is specified precisely, and it needs no protected path. But
§4 of this round's runbook forbids authoring that repair, so the next step is an owner
decision, not another autonomous round.

---

# Round 4 (revised runbook) — autonomous repair loop, `71c4ed6a`

**Outcome: NOT ACTIVATED. The loop is not live. Stopped at RUNBOOK_ROUND4 §4b.**

The round-4 runbook was revised after the first round-4 run (branch tip `f077cf23`,
"Round 4: the server repairs and re-gates on its own until READY"). The revision replaced
the previous §4 STOP-on-`CHANGES_REQUIRED` with §4b, authorising this session to author
successors and re-gate without asking, up to six successor rounds, subject to explicit
stop conditions.

Stop condition reached, exactly as §4b states it: *"STOP only if: a repair needs any other
path, a protected path, a credential, production or an owner decision …"*. One of the three
material findings of the review of `71c4ed6a` cannot be repaired inside the §4b path
allowlist — its required repair reaches two protected paths and changes the remote
protocol's identifier contract, which is an owner decision. No further successor was
authored. Sections 5 (activate) and 6 (operational-alpha proof) were never entered.

Run window: 2026-09-24 14:04Z – 14:30Z. Host `crooks-os-prod-1`.

## R4b.1 What the revision changed, and what was re-verified

The runbook body changed; `round4.patch` did not (`cmp` byte-identical to the copy already
applied, so `11ab9070` was not re-created). `build_review_job.py` and
`proof-request-operational-alpha.json` are still fetched from the round-3 branch and were
again confirmed byte-identical to the copies audited in round 3, so that audit carries over.
`sha256sum -c SHA256SUMS` passed for all four files.

**The Gate B review of `11ab9070` was deliberately not re-run.** That SHA already has a
valid, current exact-SHA review (`CHANGES_REQUIRED`, 1 material). Re-rolling a stochastic
reviewer against unchanged bytes in the hope of a different verdict is gate-shopping, and it
is exactly what "exact-SHA evidence never transfers" exists to prevent. The existing verdict
was taken as §4's result and §4b entered from there.

## R4b.2 Successor round 1 — `71c4ed6a`

Repairing the single material finding of the `11ab9070` review (crash window between
`intake()` and the acceptance receipt).

**The defect was reproduced before it was repaired.** A throwaway probe was run against a
pristine `11ab9070` tree in the sandbox, and the real behaviour is worse than the review
described:

- a receipt log that raises on the acceptance receipt simulates a crash in the window;
- the objective and task are admitted and live;
- on restart, replaying **the original, unmodified bytes** with a clock that has moved
  rebuilds an `Objective` whose `created_at` differs, so `ObjectiveStore.put` refuses its own
  record — *"objective … is already recorded differently"* — and the adapter durably writes a
  **`refused` receipt for a request that was in fact admitted**.

The consequence is not a missing digest but an actively false public record: the projection
would report the request refused while the kernel holds a live `READY` task the dispatcher
will work. The probe is a scratch artifact and is not part of the commit.

**Repair** (commit `71c4ed6a`, "Bind a request id to its bytes before the first lifecycle
write", 5 files, +303/−10, all inside the §4b allowlist, `protected_hits: []`):

- a write-once **claim** (`claims/<request_id>.json`, `clive.remote_engineering_claim.v1`)
  binds the id to the exact bytes before the first lifecycle write; like a receipt it is
  adapter provenance and admits nothing;
- the claim pins `created_at`, which is what makes recovery byte-identical and therefore
  possible at all — `ObjectiveStore.put` and `create_task` are idempotent only for identical
  bytes;
- on restart only the claimed digest resumes; other bytes for that id — including
  formatting-only differences that parse to the same request — are refused;
- same class, one step out: a claimed-but-unreceipted id joins the snapshot preflight, so an
  interrupted admission refuses its whole cycle before any write; and claims and receipts
  fsync the containing directory, not only the file.

Six regression tests were added. Pre-flight in the project's `NamespaceSandbox`: ruff clean,
`tests/test_remote_engineering.py` 132 passed, control-plane 44 passed.

**Gate A — PASS.** Run [36011018742](https://github.com/crooksldn-pixel/clive/actions/runs/36011018742),
head `71c4ed6a` exact, conclusion success first attempt, `mechanical_evidence: complete`,
`eligible: true`, no unsatisfied or malformed gate, **3319 offline tests passed**,
secret_scan "no leaks found".

**Gate B — CHANGES_REQUIRED, 3 material.** Reviewer `gpt`, `read_only: true`, mechanism
`openai-responses:gpt-5.6-sol`, effort high, one run, same frozen materiality standard.

| ID | Material | Finding |
|---|---|---|
| F-01 | true | A requester-controlled `request_id` is schema-valid while being credential-shaped, and is copied verbatim into claims, receipts, objective/task identifiers, refusal messages, host output, source locators and the public projection. |
| F-02 | true | The claim is not fully crash-durable on **first** use: `_durable_write` fsyncs `claims/` after the rename, but not the parents that made the newly created `remote_engineering/` and `claims/` directories reachable, so a crash can lose the claims directory while lifecycle writes survive. |
| F-03 | true | `ClaimLog.put` is check-then-write with no exclusive create, lock or compare-and-swap, so two overlapping controllers can both observe no claim, write different claims and race lifecycle intake. |

## R4b.3 Why the loop stopped here rather than continuing

**F-02 and F-03 are mine, are real, and are in scope.** They are defects in the claim
mechanism this round introduced — the repair was incomplete, not wrong. Both are narrow and
fixable entirely inside `app/remote_engineering/`: fsync each newly created directory's
parent as the chain is built (F-02), and make the claim an atomic `O_CREAT|O_EXCL` create
whose loser reloads the winner and continues only for the same digest (F-03). They are
recorded here unfixed only because a successor must repair *every* material finding, and
F-01 cannot be repaired here.

**F-01 is the stop.** Its required repair is "use that value for claim/receipt keys **and
objective/task correlation**", and that cannot be done inside the allowlist:

- `task_id = objective.objective_id` is assigned in
  `crooks-assistant/app/orchestrator/objectives.py:248` — a **protected path**;
- the sibling requester-chosen `target_branch` is published as a real git ref by
  `crooks-assistant/app/orchestrator/dispatcher.py` — a **protected path**. Making
  `objective_id` opaque in `controller.py` alone would leave `target_branch` published
  verbatim, so the finding's class would stay open;
- replacing the Director's own request identifier with a derived opaque one changes the
  documented remote protocol: the spec's "Outbound visibility" section requires a Director
  polling GitHub to determine "request accepted/refused; objective/task id" for **its**
  request. That is an owner decision about the protocol, not an implementation detail.

Both of §4b's listed reasons therefore apply: the repair needs a protected path, and it needs
an owner decision.

**A fact the owner should weigh when deciding.** F-01's threat model does not appear to hold
on this deployment. `crooksldn-pixel/clive` is **public** (`"private": false`, verified
unauthenticated), and an inbox request only becomes visible to the adapter by being committed
to `clive/control/owner-inbox` — where its `request_id` is the filename. The request file is
readable unauthenticated at
`https://raw.githubusercontent.com/crooksldn-pixel/clive/clive/control/owner-inbox/requests/<request_id>.json`
(verified: HTTP 200). A credential placed in a `request_id` is therefore already public,
published by the Director that authored the request, before the adapter ever reads it.
Redacting it from the status projection would not un-publish it. This is offered as evidence
for the decision, not as a reason to dismiss the finding: the adapter does copy the value
into durable records, and whether that is acceptable is the owner's call.

## R4b.4 Convergence signal

Material findings per exact-SHA review across the whole effort:

| SHA | Acceptance run | Gate A | Material findings |
|---|---|---|---|
| `c23f1935` | 35994015937 | pass | 4 |
| `05fe8046` | 35996970816 | pass | 4 |
| `62f6e7e5` | 35999394632 | pass | 5 |
| `ca047b89` | 36004882143 | pass | 2 |
| `11ab9070` | 36008900056 | pass | 1 |
| `71c4ed6a` | 36011018742 | pass | **3** |

This is the first round in which the count **rose**. §4b's convergence stop is "the
material-finding count fails to fall across two consecutive rounds", and only one
non-falling round has occurred, so that condition was **not** reached; the stop above is the
protected-path/owner-decision one. The rise is recorded because it is the signal DEC-057
asks to watch, and because two of the three new findings are defects in the repair itself —
the pattern DEC-057 calls verification improving its own subject.

Twenty material findings have now been raised across six reviews and seventeen repaired and
confirmed repaired by the following review. One successor round was authored in this run, of
the six §4b allows.

## R4b.5 What was NOT done

| Section | Status |
|---|---|
| §5 Activate | **Not reached.** No pin directory, no smoke cycle, no unit file, no `daemon-reload`/`enable --now`. There is no installed unit text to report. **`prod-before.txt` was not taken** and is not among the published files: §5 takes it "immediately before installing the unit", and no unit was installed. |
| §6 Operational-alpha proof | **Not reached.** `proof-request-operational-alpha.json` was **not** committed to the inbox. No `operational-alpha-acceptance-repair` objective or `clive/objective/…` ref exists, no candidate was produced for `f7be86f7`, and there is no status.json item or candidate CI conclusion to report. |

`origin/clive/control/status` still does not exist; the loop has never run. The owner-inbox
is untouched at `cc9ab83887cc1850c75a2e9403dc8db9f5a9d7b1` and the superseded readiness
request is still present with no receipt. The engineering store still has no
`remote_engineering/` directory: nothing has ever been admitted through remote ingress.

## R4b.6 Production and store state

The engineering store was read-only throughout (`engineering_dispatcher.py … status --json`
only). Its six objectives are unchanged from the original discovery:
`derived-truth-attention-v1` COMPLETE, `engineering-team-activation-v1` COMPLETE,
`mobile-dogfood-voice-v1` COMPLETE, `remote-engineering-control-v1-repair-1` OWNER_GATE,
`remote-engineering-control-v1-repair-2` COMPLETE, `remote-engineering-control-v1` BLOCKED.
The OWNER_GATE and BLOCKED items were not resumed, lifted or altered. No credential value was
read, printed, copied or committed; key files were referred to by path only.

Using §5's own `prod_state` definition: `/opt/crooks-os` at
`ca388ceeedb54cfd495fb2b5205ec2184db9ccae`, `/opt/crooks-interactive` at
`31fb755360ae40959c14d608de0035815c41cc40`, both with tracked-file dirty hash
`e3b0c44298fc1c14` (sha256 of empty input — no modified tracked file), both taking the **git**
branch of the function, and both production units `active`. Identical to the values recorded
in round 4's first run.

## R4b.7 Deviations from RUNBOOK_ROUND4.md (revised)

1. **Gate B was not re-run on `11ab9070`** (R4b.1). §§2–4 were already complete for that SHA
   from the first round-4 run, and re-reviewing unchanged bytes to seek a better verdict is
   gate-shopping. Its existing `CHANGES_REQUIRED` was used as §4's result.
2. **The reused round-3 artifacts were re-verified byte-for-byte** rather than trusted, as in
   the first round-4 run, because `--materiality` shapes the review gate.
3. **The `11ab9070` defect was reproduced with a throwaway probe** against a pristine tree in
   the sandbox before being repaired (R4b.2). §4b does not ask for this; it was done because
   a repair authored against a description rather than an observed failure is a guess, and it
   materially changed the fix (it is what revealed that `created_at` must be pinned, and that
   the real symptom is a false `refused` receipt rather than a missing digest).
4. **F-02 and F-03 are left unrepaired** (R4b.3), because §4b requires a successor to repair
   every material finding and F-01 cannot be repaired within the allowlist.

No other deviation. No protected path, frozen kernel, test assertion, secret-scanning rule,
CI workflow or acceptance machinery was weakened. No force-push, no amended commit, no
rewritten SHA.

## R4b.8 Where this leaves the work

`claude/remote-engineering-control-v1-activation-successor-2026-09-24` is at **`71c4ed6a`**,
with full GitHub acceptance for that exact SHA. **The loop is not live.**

Three material findings stand. Two (F-02, F-03) are in-scope defects of this round's own
repair with the fixes already identified above, and would take one more successor round. The
third (F-01) needs an owner decision on whether the remote protocol keeps the Director's own
`request_id` as the public correlation handle — and, if not, a change to two protected paths
that this run is not permitted to make.

---

# Round 4 - owner override: ACTIVATED on `4c32bb3d`, proof objective FAILED

**The loop is live.** `clive-remote-engineering.service` is active, enabled, pinned to
`4c32bb3d5f4935402c9cdc897914370950f7f206`, 0 restarts, production untouched.

**The no-courier proof did not succeed.** Both queued requests were **refused** by the
running loop for the same reason, and no worker ever ran. Root cause in R4o.6.

## R4o.1 The owner decision, verbatim

From `round-4/OVERRIDE.md` (`d54c9107…`, verified against `SHA256SUMS`):

> **Decision (George, owner):** activate the remote engineering loop at
> `71c4ed6af13d37d8c9d16179a553201c1e2de695`. Basis: full GitHub acceptance on that exact SHA
> (run 36011018742, 3319 passed, secret scan clean); 17 of 20 material review findings repaired and
> confirmed repaired across six reviews; the three open findings on `71c4ed6a` (credential-shaped
> request ids, first-use claim durability, two overlapping controllers) do not arise when one unit
> runs and only the owner and his Director write the inbox. They become the loop's second job.

> It overrides one gate only: Gate B READY for the loop's own code. Everything the loop builds
> afterwards is still gated by CI and the independent exact-SHA review as normal.

Superseded in the same session by owner direction: re-take the `prod_state` baseline; activate
on the newest successor (`4c32bb3d`) rather than `71c4ed6a` since it already repairs F-01 to
F-03; treat `request-open-findings.json` as superseded and do not submit it; run Gate B once for
the record only and activate regardless; write any remaining material findings as one new inbox
request based on the activated SHA and submit it alongside the operational-alpha proof request;
author no further repairs.

## R4o.2 A stop that was raised and then resolved by the owner

Before activating, this session stopped. `/opt/crooks-interactive/.gitleaks-baseline.json` — a
secret-scanning baseline in a production checkout — was modified at 14:42:46Z, adding a
suppression for `…/HumanisingTests.swift:generic-api-key:127`: exactly the finding the
operational-alpha request forbids fixing that way, for a file not even present at that
checkout's HEAD. 54 `.pyc` files showed pytest had run inside production in the same minute, and
the edit was reverted at 14:53:25Z. The `prod_state` baseline taken at 14:47Z consequently
already differed from live state through no action of this session, which is what made the
production-untouched gate unable to produce evidence.

The owner identified it as his own work in another window, confirmed it was reverted and never
needed, and undertook not to touch `/opt` again during activation. The baseline was re-taken at
15:02Z against a clean, stable state, and only diffs after that baseline are treated as evidence.
Recorded because the first baseline is published beside this report and does not match.

## R4o.3 A regression this session introduced, and repaired

`c6b63e10` (successor 6, the CONTINUE.md repairs) **failed its acceptance run**
([36015482301](https://github.com/crooksldn-pixel/clive/actions/runs/36015482301)) on two gates
with one cause: the new F-01 tests needed credential-shaped ids and they were written as
literals, so `secret_scan` reported "leaks found: 1", and
`test_acceptance_provenance::test_a_new_secret_still_fails_the_gate` failed with it because its
control assertion needs a clean tree. That is precisely the coupling the operational-alpha
request describes, and the fix it prescribes: `4c32bb3d` assembles the values at runtime from a
bare prefix and a repeating body, so no credential-shaped literal exists in source. `ci-c6b63e10…json`
is published beside this report so the failure is on the record, not just its repair.

## R4o.4 The activated SHA

| Field | Value |
|---|---|
| Activated SHA | `4c32bb3d5f4935402c9cdc897914370950f7f206` |
| Gate A | [36016500843](https://github.com/crooksldn-pixel/clive/actions/runs/36016500843) — success, `mechanical_evidence: complete`, `eligible: true`, no unsatisfied or malformed gate, **3341 passed**, secret_scan "no leaks found" |
| Gate B | **CHANGES_REQUIRED**, 3 material — run for the record only, activation proceeded under the override |
| Protected paths touched | none (`protected_hits: []`) |

Gate B findings on the activated SHA, all material, all now queued as the loop's own second job
(`request-review-findings.json`, published beside this report):

| ID | Finding |
|---|---|
| F-01 | A valid slug can still *be* a secret (`prod-password-hunter2`), and `request_id` is still persisted and published verbatim. The earlier required opaque-id repair remains unimplemented. |
| F-02 | The slug pattern admits ids up to 135 characters while `Claim.request_id` and `Receipt.request_id` cap at 120, and the claim is built outside the guarded intake block — so a 121–135 character request fails repeatedly without ever earning a durable decision, and one-shot `poll` can echo the supplied id through a raw `ValidationError`. Introduced by this session in `c6b63e10`. |
| F-03 | The atomic claim keeps a concurrent window: the winner may be descheduled after `os.link` but before the directory fsync, and the loser returns from `_write_once` without fsyncing, then may enter lifecycle intake. |

## R4o.5 Activation sequence, as executed

1. `prod_state` baseline re-taken 15:02Z; both `/opt` checkouts on the git branch of the
   function and clean; stable across samples.
2. RUNBOOK §6 precondition re-checked: all six objectives COMPLETE / OWNER_GATE / BLOCKED, so
   none would be advanced by the loop starting. No dispatcher running.
3. RUNBOOK §5, no-receipt branch (the receipts store did not exist): the superseded
   `requests/remote-engineering-control-v1-activation-readiness.json` was `git rm`'d on a fresh
   worktree of the inbox branch and pushed fast-forward, `cc9ab838..4cc17f84`.
4. Pinned `$E/remote-control/4c32bb3d…`, HEAD exact, worktree clean; fetched
   `origin/claude/product-memory-truth-2026-09-23` (`07459b85`).
5. **Smoke cycle**, `--max-cycles 1`, foreground: exit 0, `projection_commit`
   `a540ae355fce0ee1cbdb748dc03c88ea72a957ea`, `intake_error` null, `publish_error` null, and
   `origin/clive/control/status:status.json` created and publicly readable (HTTP 200). No
   `DispatcherBusy`. Production diff empty.
6. Unit installed from the template with `__SHA__`, `__PYTHON__`, `__VENV__` filled and the
   proven flag set — `--check-ro-path /opt/node22` beside the venv, as the first report's §1.2
   recorded from 19 prior dispatcher runs. `daemon-reload`, `enable --now`.
7. Verified: active, enabled, **2+ cycles** in `journalctl`, `NRestarts=0`, production diff empty.

The installed unit text is published beside this report as
`clive-remote-engineering.service`.

## R4o.6 The proof objective failed, and why

Both requests were committed to `origin/clive/control/owner-inbox` in one fast-forward commit
(`4cc17f84..52b86313`) and both were validated against the running code's own schema before
submission. `request-open-findings.json` was **not** submitted: superseded, per owner direction.

Watching only `clive/control/status:status.json`, the loop picked both up within two cycles and
**refused both**:

```
operational-alpha-acceptance-repair  -> refused   objective: null   task: null
remote-engineering-review-findings   -> refused   objective: null   task: null
```

> "the store has uncommitted changes (engineering/remote_engineering/claims/operational-alpha-acceptance-repair.json);
> a verb would sweep them into its journal commit as its own: commit or discard them first; nothing was written"

**Root cause.** The engineering store is journalled (`/srv/clive-engineering/state/.git`), and
`journal_preconditions` refuses any journalled verb when anything under the store is modified or
untracked. The claim introduced in `71c4ed6a` is written *into the store* at
`engineering/remote_engineering/claims/<id>.json` **before** `intake()` — which is exactly what
the round-4 review required ("persist an atomic immutable claim … before any lifecycle write").
That untracked claim therefore makes `intake()` fail its own precondition; the controller catches
the refusal and writes a **refused receipt**, which is immutable. The request id is then burned:
a replay of the same bytes returns the stored refusal for ever.

So the claim-before-intake repair, as specified by the review and implemented across
`71c4ed6a`…`4c32bb3d`, is **incompatible with a journalled store**. Nothing caught it: every
unit test constructs the kernel with `journal=False`, and CI runs the same tests, so six exact-SHA
reviews and 3341 passing tests never exercised this path. The first real objective did, within
two minutes of activation. That is the dogfood working exactly as intended — it is the one
failure mode none of the machinery could find by inspection.

**Consequences, as they stand:**

- the loop is live and stable (it re-reads the stored receipts and writes nothing further), but
  **it cannot admit any work** in this configuration;
- both request ids are spent; resubmitting the same bytes replays the refusal, so the work needs
  new request ids once the cause is fixed;
- the store now holds untracked adapter files (`engineering/remote_engineering/`), which will
  refuse **any** journalled kernel verb — including the canonical dispatcher run by hand — until
  they are committed or removed.

Nothing was done about any of this: the store was not edited by hand (§0 forbids it), no repair
was authored (owner direction), and the unit was left running (the owner's decision to activate).
Candidate CI conclusions for the two objectives: **none exist** — no worker ran, no candidate SHA
was produced, and no `clive/objective/…` ref was created.

## R4o.7 Production and store state

Final `prod_state` diff against the 15:02Z baseline: **empty**. `/opt/crooks-os`
`ca388ceeedb54cfd495fb2b5205ec2184db9ccae`, `/opt/crooks-interactive`
`31fb755360ae40959c14d608de0035815c41cc40`, both with tracked-file dirty hash
`e3b0c44298fc1c14` (no modified tracked file), both units `active`, unit-file hash unchanged.
The six pre-existing objectives are in exactly the stages recorded at first discovery; the
OWNER_GATE and BLOCKED items were not resumed, lifted or altered. No credential value was read,
printed, copied or committed.

## R4o.8 Deviations

1. **Activated `4c32bb3d`, not `71c4ed6a`** — owner direction superseding the SHA in OVERRIDE.md.
2. **`request-open-findings.json` was not submitted** — superseded by owner direction, because the
   activated SHA already repairs its three findings; its replacement
   `request-review-findings.json` carries the activated SHA's own open findings instead.
3. **Gate B was run once and ignored for the activation decision**, per owner direction; its
   three material findings were queued rather than repaired.
4. **A repair was authored after the STOP** (`4c32bb3d`) — but only to undo this session's own
   `c6b63e10` regression that had left the shared branch failing `secret_scan`. It advanced no
   gate and was not a review repair.
5. **The run stopped once before activating** (R4o.2) and resumed only on owner direction.

No protected path, frozen kernel, test assertion, secret-scanning rule, CI workflow or acceptance
machinery was weakened. No force-push, no amended commit, no rewritten SHA. The engineering store
was never edited by hand.

## R4o.9 Where this leaves the work

The loop is live on `4c32bb3d`, with full GitHub acceptance for that exact SHA and three open
material findings queued as its own second job. It cannot admit that job, or any other, until
claim-before-intake is reconciled with the journalled store — for example by placing claims
outside the journalled store, exempting the adapter's own directory in the precondition (a
protected path), or running the loop with `--no-journal`. That decision is the owner's; it is
also the first thing the loop would need in order to do any work at all.
