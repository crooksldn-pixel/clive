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

## Step 3 — RP1, the re-pin (worker-01; step 2 found the expected path on 2026-10-15)

### How the actual script works (read on 2026-10-15; sha256 `ab569848…8bab`)

`/home/george/clive-review/repin/root-repin.sh` takes **no arguments**. `SHA` (the target) and `PIN`
(the current pin) are hard-coded from the 1 Oct re-pin: `SHA=718fbc41…`, `PIN=b577bc97…`.

**What it does, in order:**

1. fetches trunk with the loop's credential;
2. checks that `SHA` is on trunk and `PIN` is an ancestor;
3. asks the GitHub gate at `SHA`;
4. runs a gpt-6-luna smoke request;
5. runs an exact-SHA review of `PIN..SHA` on gpt-6-sol, with the old pin's reviewer;
6. **requires READY.** The 1 Oct owner waiver applies only to `SHA=718fbc41`;
7. re-asks the gate;
8. builds `/srv/clive-engineering/remote-control/$SHA`;
9. backs up the unit and **rewrites only the pin and the product-memory ref**;
10. runs `daemon-reload`;
11. restarts once no builder or review is running;
12. reports.

**So RP1 is the script with two variables changed, followed by a separate flag change.** The flag
change is needed because the script deliberately changes nothing else.

**What the new pin does differently** (verified against `ef204bc2`'s source):
- Every flag `718fbc41` accepts still exists, so the current `ExecStart` parses.
- With a flag omitted, the defaults change: the reviewer becomes `claude`, repair rounds become 2, and
  **builder skills come on**. On CLI 2.1.280 that would make every build launch refused, so
  `--no-builder-skills` is required.
- Placement:
  - `--reviewer`, `--max-concurrent` and `--no-builder-skills` go **before** `run`;
  - `--default-repair-rounds`, `--private-listen` and `--private-allow-node` go **after** `run`.
- Outside the loop, the code imports only `app.logging.turnlog`. The only new dependency, `pypdf`, is
  research-only, so the unpinned venv is not at risk.

### The procedure (root on worker-01; the exact commands are in the planning session's reply of 2026-10-15)

| Step | What | Detail |
|---|---|---|
| R0 | Read-only pre-checks | Pinned trees present; `packet-head.md` names no SHA or PR (if it does: stop and paste it); port 8765 free; worker-01's tailnet IPv4; tmux available. **Attempt 2:** `packet-head.md` is replaced first with the reviewed head (`repin/packet-head-718fbc41-ef204bc2.md`, verified by sha256 before and after install) |
| R1 | Copy the script | `root-repin-ef204bc2.sh` with exactly two lines changed: `SHA=ef204bc2…` and `PIN=718fbc41…`. The diff must show only those, and the original's checksum is unchanged |
| R2 | Run the copy | Run it in the foreground, inside tmux if present, logged with `tee`. **Any `== STOPPED`, `CHANGES_REQUIRED` or `== NOT RESTARTED` means stop and paste it.** On success the loop restarts on `ef204bc2` with its old flags. **Nothing may be filed until R3 and R4 are done (the handoff guard below).** R3 onward is given only after the REPORT proves the running cwd is the `ef204bc2` tree |
| R3 | Change the flags | A Python edit that asserts the unit is exactly as audited and at the new pin. It backs up the unit, then: `--max-concurrent 8` → `2`; adds `--reviewer claude` and `--no-builder-skills` (before `run`); adds `--default-repair-rounds 2`, `--private-listen <worker tailnet IPv4>:8765` and `--private-allow-node <production's full tailnet name>` (after `run`). Then `systemd-analyze verify` and `daemon-reload` |
| R4 | Probes from the new tree | `engineering_dispatcher.py … --no-builder-skills probe-launch` and `… --reviewer claude probe-review --turn`. Both must PASS |
| R5 | Restart when idle | The unit's cgroup holds only the main process; then `systemctl restart` |
| R6 | Verify | Active state; cwd is the new tree; the cmdline shows the new flags; the pinned tree's HEAD is `ef204bc2`; the first tick shows no intake, publish or private error; the private port is bound |
| R7 | Rollback rehearsal, after the smoke request | The old pin's `remote_engineering.py status` against a **copy** of the store. **Deviation:** `tick` is omitted. The store is idle, and a side-effect-free tick would need a copy of the 53 GB runtime; `status` parses every record the old code would read |

### Operational handoff guard (sequencing, not a safety waiver)

**The gap.** At `ef204bc2`, while the unit still has its existing arguments:

- the reviewer defaults to Claude;
- builder skills default to on;
- on Claude Code 2.1.280 those skills cannot be launched, so a builder launch fails closed before any
  process starts.

**Therefore, after RP1 ends with a successful `== REPORT` at `ef204bc2`, no new engineering request
may be filed until both of these are done:**

1. the reviewed Stage A configuration step (R3) has applied `--no-builder-skills` and the intended
   concurrency, reviewer and private-channel flags;
2. both probes (R4) pass.

This only sequences the steps. The fail-closed behaviour itself stays as it is, and must not be
weakened to close the gap.

**Rollback:**
- **The flags only:** restore `….service.bak-flags-<ts>`, then `daemon-reload` and restart.
- **The whole re-pin:** restore the script's `….service.bak-718fbc41…-<ts>`, then `daemon-reload` and
  restart. The old tree is kept.

**Not done:** no reboot, no installs, no SSH, Tailscale or firewall changes. If production cannot
reach the private channel (for example, a firewall), that row is marked deferred. The firewall is not
changed.

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
| 1 (A1) | 2026-10-15 16:31 | Run by George as root on worker-01 | His pasted output (kept in this conversation, not in the repository) |
| 2 | 2026-10-15 | **Expected path; no material drift.** Pin `718fbc41` (an ancestor of `ef204bc2` by 58 commits); unit active since 1 Oct 22:04, 0 restarts; `--max-concurrent 8`; GPT reviewer through `--gpt-api-key-file` (no `--reviewer` at that pin); CLI 2.1.280 (`--no-builder-skills` needed); no browser; no `--worker-bash-prefix`; `--check-ro-path` is the venv and `/opt/node22` only; branches `worker-01-inbox` and `worker-01-status`; repo and workers on a 52G tmpfs, the store and the 53G runtime on disk (3.4T free); 0 lease cancellations; 0 rate-limit lines; 0 stop reports. **Minor note:** the code records worker-01 on CLI 2.1.285 on 30 Sep; it is 2.1.280 now. Not material: skills are off, and the probes test the real binary | A1 output; `git merge-base --is-ancestor` |
| 3 (RP1), attempt 1 | 2026-10-15 16:50–16:52 | **STOPPED by the re-pin review. The worker was not re-pinned.** Details below the table | George's transcript; `out/review-ef204bc2….json` on worker-01 |
| 3 (RP1), attempt 2 | 2026-10-16 11:3x–11:35:48 | **Re-pinned.** The reviewed packet head was installed (sha256 `6827c821…8227`, verified `OK`; the packet contains its wording). The script reached `== REPORT`: the running cwd is `/srv/clive-engineering/remote-control/ef204bc2…/crooks-assistant`; the tree's HEAD is `ef204bc2`; the unit is active since 11:35:48 UTC with 0 restarts; first tick `intake_error None`, `publish_error None`, 0 events; the public heartbeat at 11:36:39 UTC shows 74 requests, none waiting. The verdict line scrolled off the pane; the script restarts this SHA only on READY (its waiver applies to `718fbc41` alone), and R3's first check prints it from the review record | George's pane; `/root/rp1-repin-ef204bc2-attempt2.log`; `out/review-ef204bc2….json` |
| 4 (smoke) | — | — | — |
| 5 | — | — | — |
| 6 | — | — | — |
| 7 | — | — | — |


### RP1 attempt 1, 2026-10-15: what happened

**R0.** The `packet-head.md` check printed matches, which was the stop point. The reviewer
instructions are still the 1 Oct ones:

- "Current pin (base): b577bc97…";
- "Candidate: 718fbc41… (PR #88)";
- the PR #87 and #88 answers.

**R1.** Correct: exactly two lines differ, and the original script's checksum is unchanged.

**R2.**
- Trunk head `ef204bc2`; `718fbc41` is an ancestor; gate GREEN (run 38638076616); gpt-6-luna smoke OK.
- The packet was 868,465 bytes covering 40 files.
- **The review returned CHANGES_REQUIRED** on gpt-6-sol, response `resp_0a856dcb…`. Its one finding,
  F-01, says the packet named `b577bc97` as the running pin but supplied only the `718fbc41..ef204bc2`
  diff.
- **This is a defect in the stale packet head, not in the candidate.** It is a verifier-apparatus
  defect in the sense of ENGINEERING_CONTROL_PLANE_VNEXT §8.1.
- The script stopped: "nothing the loop uses was changed".

**R3–R7 were run anyway, outside the runbook's order.**

- **R3:** the Python assertion refused ("unit is not at the new pin"), so the unit was not touched.
  The following `systemctl daemon-reload` reloaded unchanged unit files.
- **R4:** both probes failed with "No such file", because the new tree was never built.
- **R5: an unplanned restart of the *old* loop** at 16:51:52 UTC. It came back on the same pin and the
  same flags, and its first tick showed `intake_error: null`.
- **R6:** confirmed the old pin and `--max-concurrent 8`; nothing listens on 8765.
- **R7:** the old pin's `status` on a store copy exited 0. Not meaningful, since nothing new had been
  written. It left `/root/rp1-rehearsal` (a 20 MB copy of the state) to be removed.

**State after attempt 1:**

| Item | State |
|---|---|
| worker-01 | Active on `718fbc41`, flags as audited |
| Production-host loop | Still active (correct: the re-pin is not done) |
| Created on worker-01 | `root-repin-ef204bc2.sh` (the two-line copy); the script's mirror fetch, archive tree `/var/lib/clive-review/tree-ef204bc2…`, packet and review record; `/root/rp1-rehearsal` |

**Next:**

1. Write a correct packet head for `718fbc41 → ef204bc2`, from the old file's contract text with only
   the re-pin-specific facts replaced, and **shown to George before use**.
2. Re-run `root-repin-ef204bc2.sh`.
3. **Run R3 onwards only if R2 prints `== REPORT` with the pin at `ef204bc2`.**
