# Stage A runbook: A1, RP1, and retiring the production-host loop

**Authorised by George on 2026-10-15** (DECISIONS.md, "Stage A authorisation"). Stage A only.

## Why this runbook exists

The planning session runs on `crooks-os-prod-1`. It **has no route to clive-worker-01**:

- worker-01 is online on the tailnet but offers no Tailscale SSH;
- this host has no SSH key or agent for it.

That was checked on 2026-10-15. So the worker-side steps are run by George over Termius, or by a
Claude session he opens on worker-01. Each step says what to paste back. The planning session
compares the result with revision 4 and does only the production-side steps itself.

## Readiness, checked from production (2026-10-15)

| Fact | Value |
|---|---|
| **The re-pin target** | trunk head `ef204bc29d7e6c6d8e518f62f01c9574a160e23b` (DEC-079, PR #125) |
| **Its CI** | `acceptance.yml` run `38638076616`: **success** on that exact SHA (14 Oct 21:09 UTC) |
| **worker-01's loop** | Alive and idle: heartbeat `2026-10-15T16:09Z`, 74 requests, none waiting, no new request since 8 Oct |
| **Production** | `dc59047e`. The production-host loop is still active and enabled |

**If trunk moves before RP1, re-check:** the new head is the target only once its own `acceptance.yml`
is green on that exact SHA.

---

## Step 1 — A1, the read-only audit (worker-01)

1. Run the script in [WORKER01_AUDIT.md](WORKER01_AUDIT.md) as root, on clive-worker-01.
2. **Paste the whole output back**, unedited apart from any redaction.

It writes nothing and sets `GIT_OPTIONAL_LOCKS=0` first.

## Step 2 — the comparison (done by the planning session)

### What the expected migration path looks like

| Check | Expected (revision 4) | Material drift: stop and report |
|---|---|---|
| Unit | `clive-remote-engineering.service` active and enabled; `ExecStart` runs `scripts/remote_engineering.py run` from a pinned tree | No such unit, a different program, or a second engineering loop on worker-01 |
| Pin | A clean pinned tree whose SHA is **an ancestor of trunk `ef204bc2`** (one of the loop's past re-pin targets) | Not an ancestor of trunk; a dirty tree; or no pin can be identified |
| Reviewer | `--reviewer gpt`, or GPT through `--gpt-api-key-file` (all 44 verdicts were GPT) | `--reviewer claude` already set, which would contradict 0 Claude verdicts |
| Concurrency | Any value (≥4 observed) | — (recorded; RP1 sets 2) |
| Builders' shell | No `--worker-bash-prefix` | Any `--worker-bash-prefix` |
| `--check-ro-path` | Venv and node paths only | `/`, `/etc` or a credentials directory |
| Inbox and status | `--branch clive/control/worker-01-inbox`, `--status-branch clive/control/worker-01-status` | Anything else |
| Claude CLI | Recorded. 2.1.285 or 2.1.293 means builder skills on; any other version means `--no-builder-skills` | — |
| Disk | At least 20% free where the store, runtime and workspaces live | Less than 20% free |
| Lease cancellations, rate-limit lines | Recorded | — |

**If anything is material drift, Stage A stops here, before the worker is changed.**

---

## Step 3 — RP1, the re-pin (worker-01; only after step 2 says "expected path")

Run as root on worker-01. `<…>` placeholders come from the A1 output.

1. **Run the re-pin review.**
   - Command: `sudo bash /home/george/clive-review/repin/root-repin.sh`, targeting `ef204bc2`.
   - The script reviews the loop's code from the current pin to the target, and continues only on
     READY. Its result is kept at `/home/george/clive-review/repin/out/review-<sha>.json`.
   - **If it returns CHANGES_REQUIRED: stop and paste the findings back.** No waiver is assumed.
2. **Set the unit flags** with `systemctl edit --full clive-remote-engineering`, then
   `systemctl daemon-reload`:
   - **Keep everything else as it is.** That includes the inbox and status branches,
     `--publish-remote`, the store, runtime and token-file paths, and `--gpt-api-key-file` (it is
     harmless while GPT is collect-only, and useful for a rollback).
   - **`--reviewer claude`.**
   - **`--max-concurrent 2`.** This is an engineering setting under DEC-079 ruling 4. It is not
     raised during Stage A.
   - **`--default-repair-rounds 2`.**
   - **The private channel (DEC-068):**
     - `--private-listen <worker-01's tailnet address>:<port>`;
     - `--private-allow-node <production's full tailnet name>`.

     Production is the only node allowed. The supervisor's own read access comes at RP2 through the
     read group (O-2).
   - **`--sandbox-browsers <path>` and `--sandbox-node-path <path>`**, only if A1 found Chromium and
     node.
   - **The workspace root on the same filesystem as the repository (`--repo`).** This is the EXDEV
     fix.
   - **`--no-builder-skills`**, unless the CLI is 2.1.285 or 2.1.293.
3. **Run the probes.** Run them as the unit's user, with the same global flags as the new `ExecStart`.
   Both must print PASS.
   - `<python> <pinned tree>/crooks-assistant/scripts/engineering_dispatcher.py <global flags> probe-launch`
   - `<python> <pinned tree>/crooks-assistant/scripts/engineering_dispatcher.py <global flags> probe-review --turn`
4. **Restart:** `systemctl restart clive-remote-engineering`. Then run
   `systemctl status clive-remote-engineering --no-pager | head -15`.
5. **Rollback rehearsal**, side effect free:
   - copy the store to a scratch folder;
   - run the **old** pin's `remote_engineering.py status` against the copy;
   - run the old pin's `engineering_dispatcher.py tick --no-land` against the copy, with:
     - a scratch `--runtime-root` and `--workspace-root`;
     - `--publish-remote` pointing at a throwaway local bare repository;
     - `--worker-cli /bin/false`;
     - no network needed.

   Both must run without refusing a record. Delete the scratch folder afterwards. If either refuses,
   record the refusal; the rollback target then becomes the oldest pin that passes.

### Paste back
- the re-pin script's verdict line;
- `systemctl cat clive-remote-engineering`, with credential paths redacted and the private-listen
  address replaced by "present";
- the two probe verdicts;
- `systemctl status` (the first 15 lines);
- the rehearsal result.

## Step 4 — the smoke request (George, in CLIVE)

1. **File one docs-only request from CLIVE, with his hold:** "CURRENT_TRUTH: production is `dc59047e`
   since 14 Oct; the trunk adds DEC-079". The allowed path is
   `crooks-assistant/docs/product-memory/CURRENT_TRUTH.md`. Every filing still waits for his hold.
2. **The planning session then reads worker-01's public status** until the request reaches COMPLETE:
   - the review must be by **`claude-reviewer`**;
   - the landing must be by the loop.

## Step 5 — the verification checklist (planning session, from the status and the pasted evidence)

| DEC | Behaviour | Proof |
|---|---|---|
| DEC-076 | Claude reviewer | The smoke request's verdict is by `claude-reviewer` |
| — | Loop landing still works | The smoke request is landed by the loop, and its SHA is on `clive/trunk` |
| — | Heartbeat | Fresh, about every 10 min |
| DEC-068 | Stop reports kept and served to production only | A `GET` from production to the private channel answers. An empty list is fine |
| DEC-068 | Findings reach the repair; `earlier_try`; repair rounds 0–5 | **Marked "pending first repair or re-file"** if the smoke request needs none: never assumed |
| DEC-068 | Skills | Ticked only on a gated CLI; otherwise "not applicable on this host" |
| DEC-068 | Browser in checks | Ticked only if bound; otherwise "not applicable" |

**Healthy means all of these:**
- the probes PASS;
- the unit is active;
- the heartbeat is fresh;
- the smoke request is reviewed by `claude-reviewer` and landed;
- the private channel answers production.

## Step 6 — retire the production-host loop (planning session, on `crooks-os-prod-1`, only after step 5 is healthy)

1. `systemctl disable --now clive-remote-engineering`. Keep `/srv/clive-engineering/{state,runtime,workers,repo}`; delete nothing.
2. **Verify:**
   - `systemctl is-active` gives `inactive` and `systemctl is-enabled` gives `disabled`;
   - no `remote_engineering.py` process remains;
   - `origin/clive/control/status` gains no new heartbeat commit for 20 minutes.
3. **Rollback, if ever needed:** `systemctl enable --now clive-remote-engineering`.

**Not done:** the revision-4 drill that commits a test request to `owner-inbox`. It would be a GitHub
write that Stage A does not need. A stopped unit cannot poll, and that is evidence enough.

## Step 7 — one canonical loop
- worker-01's unit is active with the new pin;
- the production host's unit is inactive and disabled;
- only `worker-01-status` heartbeats.

---

## Record of execution

| Step | When (UTC) | Result | Evidence |
|---|---|---|---|
| Readiness | 2026-10-15 16:10 | Target `ef204bc2` green; worker-01 alive; no route from production | This page, "Readiness" |
| 1 (A1) | — | **Waiting for George's run on worker-01** | — |
| 2 | — | — | — |
| 3 (RP1) | — | — | — |
| 4 (smoke) | — | — | — |
| 5 | — | — | — |
| 6 | — | — | — |
| 7 | — | — | — |
