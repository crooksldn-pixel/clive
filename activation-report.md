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
