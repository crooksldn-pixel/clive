# Deploy review, round 7 — findings for the Director

**Candidate reviewed:** `1d7a934a838b962ffaa4231bd31ac35fd3f92971` — `clive/trunk` head, PR #48's merge commit.
**Currently deployed:** `3e77f2157a35a23ba69014c1b0161a9351accd48` (PR #42), unchanged.
**Previous review:** round 6 of `9a79dc12` — both halves CHANGES_REQUIRED, 17 material findings, published at `4e1da401`. PR #48 claimed to close all 17.

**Outcome: all four parts returned CHANGES_REQUIRED. Nothing was deployed.** No `.env` line, no
service file, no systemd state and no checkout changed. The service is still running its original
process. `CROOKS_SCREEN_SNAPSHOTS` stayed `false`, `CROOKS_LOCAL_OWNER` unset,
`CROOKS_WRITES_LOCAL_OWNER` `false`, `CROOKS_ENGINEERING_HOST` unset, and the engineering
credential stayed parked.

| Part | Scope | Verdict | Findings |
|---|---|---|---|
| A1 | proxy identity, the access boundary, the local CLI | **CHANGES_REQUIRED** | 4 (4 material) |
| A2 | the tool boundary and the pad routes | **CHANGES_REQUIRED** | 3 (3 material) |
| A3 | the gap record, screen copies, observability accounting | **CHANGES_REQUIRED** | 8 (7 material) |
| B | the screens feature | **CHANGES_REQUIRED** | 7 (5 material) |

**22 findings, 19 material.** Three of the 17 round-6 findings are closed: **F-02**, **B-06**
and **B-07**. Everything else survives in whole or in part, and five findings are new.

## Read this first

Two findings are more urgent than their ordering suggests.

**A3/F-04-REPORT-LOSS is a destructive action added at start-up.** `withhold()` in
`app/observability/session.py`, reached from `install()` on every boot and every housekeeping
pass, falls back to `_remove_if_older(path, float("inf"))`. Because the function spares a path
only when `st_mtime >= cutoff`, an infinite cutoff means the age test can never spare anything:
the report is always deleted, at any age, and a report *directory* goes by
`shutil.rmtree(..., ignore_errors=True)`. It was introduced while fixing F-04 and it runs against
the owner's live reports with no recoverable copy required first. It did not run here, because
nothing was deployed.

**A2/F-NEW-TOOLS means the tool boundary fails open.** `OWNER_REQUEST` is declared
`ContextVar(..., default=None)` and `dispatch` guards with `if OWNER_REQUEST.get() is False:`. Any
path reaching `dispatch` without the middleware having stamped the contextvar runs tools with no
owner decision at all. This is the choke point PR #48 nominates as the fix, and an added test
depends on the fail-open default, so the repair is a design change rather than a one-line edit.

## Standing facts, unchanged

**`clive/trunk` has no branch protection and none can be configured** — branch protection and
rulesets both return HTTP 403 on this plan, and the branch reports `"protected": false`. A SHA's
position on trunk and a green acceptance run carry zero review weight. All four reviewers were
told this. PR #48 states it removed a test docstring claiming otherwise; A2 confirms the gate
diff tightens only.

**The engineering bridge stayed out of this deploy.** `github_engineering_inbox_token.cred`
remained parked in `/etc/crooks-os/credentials-parked/` (0700 directory, 0600 file, 292 bytes,
original mtime), never opened or decrypted; `/etc/crooks-os/credentials/` held exactly three
`.cred` files; `/etc/crooks-os/secrets/` held no engineering token. F-ENG stays deferred, and was
not gated on.

## How this review was run

Round 6 lost evidence to the harness's 300 KB full-file budget: it appends files for whatever
appears in the packet's diff, in packet order, and silently replaces the rest with `omitted`
lines. The files these findings turn on total about 760 KB, so a single dispatch — or even two —
would have dropped its own evidence again.

The review was therefore split into **four** bounded dispatches, each sized so that nothing it
needs is dropped, with the budget simulated per packet before sending and every packet
leak-checked. All four were required to return READY. Auto-supplied bytes per part: A1 197,587;
A2 188,112; A3 289,277; B 186,599 — **zero omissions in all four**. Files unchanged in the range,
which the harness would never supply, were added explicitly: the unit template in A1, and
`web/sw.js`, `web/display.html` and `web/startup.css` in B. Supplying the complete `web/sw.js`
this way is what let B-07 finally be ruled on.

Each reviewer was `gpt-6-sol` at high effort, told it was one of four parts and not to approve
what it could not see, and given the full round-6 findings document and the full PR #48 body as a
claim sheet to check rather than trust.

## Preflight, all read-only, all passed

- `1d7a934a` is `origin/clive/trunk`'s head and PR #48's merge commit; `9a79dc12` and `3e77f215`
  are both ancestors.
- Its tree is **byte-identical** to PR head `a82b2e0a` (both `5642cd71`), which was green on runs
  36332001602 and 36332084312.
- Acceptance on `1d7a934a` itself: run **36332489040**, completed/success, `head_sha` matching,
  the only run on the SHA, every step green.
- `CROOKS_TAILSCALE_VERIFY` unset → code default true, so the proxy check would be active on
  deploy. `CROOKS_ALLOWED_LOGINS` non-empty. The four required switches were as specified.
- Unit rendered at the candidate without installing. `LoadCredentialEncrypted` identical to the
  installed three; `ExecStart` gains `--no-proxy-headers`. Two further differences — a
  `Environment=PATH` entry for the venv bin, and one trailing newline — are byte-identical to
  those accepted in round 6 and come from `service_path()` including the venv interpreter's own
  directory; PR #48 changed neither the unit template nor `install_systemd.py` nor
  `launch_common.py`. The owner accepted them before the review ran.
- Proxy identity preconditions: tailscaled is pid 1655, cgroup
  `0::/system.slice/tailscaled.service`, exe `/usr/sbin/tailscaled`, `tailscale ip` answers as
  root. (`comm` is also `tailscaled`, the value the old code trusted and this one no longer does.)
- `tests/rollback/gaps_3e77f215.py` — its body from line 6 is **byte-identical** to
  `git show 3e77f215:crooks-assistant/app/objectives/gaps.py`, both sha256
  `b6bfba90973a1647659e4d3e24e61a006d8aaffbb03e52236ddc992c9f24c26f`, 16831 bytes. The vendored
  rollback reader genuinely is the rollback target's code.

The deploy script for step 3 was written and syntax-checked — one operation for code and unit,
`set -euo pipefail` with an `ERR` trap restoring the `3e77f215` checkout and the saved unit, and
asserting both the running uvicorn args and `/health` `checks.proxy_identity` before declaring
success. It was never run.

---

# Part A1 — proxy identity, the access boundary, the local CLI

**Verdict: CHANGES_REQUIRED** — model `gpt-6-sol`, effort high.

> A1 is not ready. The local CLI and provenance changes repair substantial parts of F-05A and F-05B, but the specified proxied-key refusal and within-check PID assurance remain unproven or absent. F-05B-AVAIL remains material: stale own-address data can admit host-originated writes, and the required real-device and fail-deployment checks have not been demonstrated. F-ENG remains deferred; A2, A3 and B require their separate reviews.
> 
> [model gpt-6-sol, effort high, usage {"input_tokens": 88335, "input_tokens_details": {"cache_write_tokens": 88332, "cached_tokens": 0}, "output_tokens": 7665, "output_tokens_details": {"reasoning_tokens": 6401}, "total_tokens": 96000}]

## A1 · F-05A

**Severity:** MATERIAL

**What it found**

STILL PRESENT in one requested restriction. The new key is generated in the root-only secret tier, compared with hmac.compare_digest, and does not enter either business-write gate; missing keys refuse the CLI. But a valid owner request through Tailscale that carries X-Crooks-Local-Key is not refused on a test-session route: local_cli.admits returns false for a proxied request, then principal_verdict admits it as the owner. The tests cover a stranger and a forged proxy request, not this case. The key grants no extra privilege in that case, but the specified proxied-request refusal is absent.

**Evidence it cites**

`app/local_cli.py:admits; app/main.py:guard_and_freshness; app/routes/observe.py:_refused; tests/test_local_cli.py:test_the_key_is_for_the_server_itself_never_through_the_proxy`

**Required repair**

Reject a proxied request presenting the local key on the three CLI routes, while continuing to admit authenticated owner-device requests without it. Test a genuinely verified owner-proxied request carrying the correct key.

**Verification note (mine, not the reviewer's)**

Confirmed, and I agree with the reviewer's framing that the substance is repaired and a
specified restriction is not. The key is generated in the root-only Tier B store, compared with
`hmac.compare_digest`, and does not enter either business-write gate — which is what round 6 asked
for, and it closes the trap where the obvious operator fix would have widened the write gate.

What is missing is narrow: a genuinely verified owner request arriving through Tailscale that also
carries `X-Crooks-Local-Key` is not refused on the three test-session routes. `local_cli.admits`
returns false for a proxied request and `principal_verdict` then admits it as the owner anyway. The
reviewer is careful to say the key grants no extra privilege in that case, so this is a
specification gap rather than a privilege escalation. I did not construct that request.

---

## A1 · F-05B

**Severity:** MATERIAL

**What it found**

STILL PRESENT in the PID-reuse edge of provenance authentication. Removing the positive inode cache repairs the demonstrated stale-inode bypass, and cgroup membership defeats a process that merely renames its comm. However, _proc_peer_check checks a numeric PID's cgroup and executable, then separately reads that PID's fds without pinning the process. If the trusted process exits and its PID is reused between those operations, the check can combine the former process's identity with the latter's socket. The supplied PID-reuse test changes processes between requests; it does not exercise this within-check race. Executable identity is also checked only by the basename of the /proc link, not by inode or an approved real path; the claimed restriction on who can enter the service cgroup is not established by the supplied host evidence.

**Evidence it cites**

`app/identity.py:unit_pids, is_proxy_process, _proc_peer_check, socket_inodes; tests/test_proxy_identity.py:test_at_both_gates_a_reused_pid_is_not_the_proxy; REVIEW PACKET — PROXY IDENTITY PRECONDITIONS ON THIS HOST`

**Required repair**

Pin the process identity across cgroup, executable and fd inspection (for example with a pidfd), attest the executable against an approved binary identity rather than its basename alone, and establish the production cgroup's entry permissions. Exercise exit/reuse during one check at both gates.

**Verification note (mine, not the reviewer's)**

Confirmed as substantially repaired, with a real residual race that I could not
close by reading alone.

The two mechanisms I demonstrated in round 6 are gone. `comm` is no longer consulted: identity is
now cgroup membership plus the exe name. The positive `_holdings` inode cache is gone, so the
stale-inode bypass I reproduced is closed.

The residual the reviewer names is a genuine TOCTOU: `_proc_peer_check` establishes a numeric PID's
cgroup and executable, then separately reads that PID's fds, without pinning the process. If the
trusted process exits and the PID is reused between those two reads, the check can pair one
process's identity with another's socket. A pidfd would pin it. I did not attempt to win that race,
and I would not on a live service — the window is small but it is real, and the supplied PID-reuse
test changes processes between requests rather than inside one check.

The executable point also stands on reading: the check is on the basename of the `/proc/<pid>/exe`
link, not an inode or an approved real path.

---

## A1 · F-05B-AVAIL

**Severity:** MATERIAL

**What it found**

STILL PRESENT, with a business-write consequence. Bind-based locality is gone, but own_addresses caches the server's tailnet addresses for 600 seconds. If the server's tailnet IP changes during that interval, a request the server sends through its own tailscale serve has a new address that is not in the cache. proxy_state calls it TAILSCALE rather than THIS_HOST; because this host uses the owner's tailnet login, whois can then confirm it and both principal_verdict and caller_check admit it despite CROOKS_WRITES_LOCAL_OWNER=false. A failed or slow tailscale ip also refuses all owner devices; failure is safe against that false acceptance but not available, and a failed lookup is cached for 30 seconds.

**Evidence it cites**

`app/identity.py:SELF_CACHE_S, own_addresses, is_this_host; app/routes/actions.py:proxy_state, principal_verdict, caller_check; REVIEW PACKET — PRODUCTION STATE and F-05B-AVAIL`

**Required repair**

Identify current interface-owned addresses without a stale positive set, or invalidate and refresh the set on address changes before judging forwarded requests. Keep uncertain locality closed without a routine CLI outage locking out all owner devices. Test an address change and a CLI timeout/failure through both gates with production flags.

**Verification note (mine, not the reviewer's)**

Confirmed, and this one has a business-write consequence that deserves the
Director's attention.

The round-6 defect is genuinely fixed: `bind()` is gone, and `own_addresses` now asks
`tailscale ip`. I verified the preconditions on this host at preflight — tailscaled is pid 1655, its
cgroup is `0::/system.slice/tailscaled.service`, its exe is `/usr/sbin/tailscaled`, and
`tailscale ip` answers as root.

But I confirmed the cache: `SELF_CACHE_S = 600.0`, and `own_addresses` serves a positive answer from
that cache for ten minutes. The path the reviewer describes follows from that. If this server's own
tailnet address changes inside that window, a request it sends through its own `tailscale serve`
carries an address absent from the cached set, so `is_this_host` says no, `proxy_state` calls it
TAILSCALE rather than THIS_HOST, and because this host holds the owner's tailnet login `whois`
confirms it — so **both** `principal_verdict` and `caller_check` admit it despite
`CROOKS_WRITES_LOCAL_OWNER=false`. That is a host-originated business write getting through a gate
set to refuse exactly that.

The availability half is the mirror image: a slow or failed `tailscale ip` refuses every owner
device, and a failed lookup is cached for 30 seconds. Safe against the false accept, not available.

---

## A1 · F-05B-AVAIL-PREFLIGHT

**Severity:** MATERIAL

**What it found**

STILL PRESENT as a deployment-verification gap. The rendered unit contains --no-proxy-headers and served_without_proxy_headers can detect its absence for the stated uvicorn command, but /health merely reports degraded after startup; no supplied deployment step fails the deployment when the installed unit lacks the flag. Nor is there evidence of the required real owner-device request using this SHA and rendered unit before deployment. The /whoami test substitutes synthetic forwarding headers and mocked identity; the /whoami implementation itself is not supplied in A1.

**Evidence it cites**

`deploy/systemd/crooks-assistant.service:ExecStart; app/identity.py:served_without_proxy_headers; app/routes/health.py:_guarded; tests/test_proxy_identity.py:test_whoami_says_whether_the_request_is_the_owners; REVIEW PACKET — UNIT DIFF and F-05B-AVAIL required repair`

**Required repair**

Supply app/routes/environment.py's /whoami implementation and a predeployment, real owner-device request against this SHA under the rendered unit. Make deployment explicitly abort unless the installed running unit has the flag and that request succeeds. The phone's post-deploy /whoami should show through="tailscale", owner=true and owner_refusal=null; "this_host", a refusal or a false owner verdict would mean the access boundary or owner's availability is wrong.

**Verification note (mine, not the reviewer's)**

Confirmed, and I should own part of this one.

The reviewer is right that nothing in the code fails a DEPLOYMENT when the installed unit lacks the
flag — `/health` only reports degraded afterwards. My step-3 deploy script does close that gap from
the operator side: it asserts both that the running uvicorn process's args contain
`--no-proxy-headers` and that `/health` `checks.proxy_identity.ok` is true with the expected detail,
and it rolls back on either. That script is written and syntax-checked at
`round-7/deploy.sh` but was never run, because the gate did not open.

The rest of the finding is a genuine evidence gap of my own making: I did not put
`app/routes/environment.py` in any part, so `/whoami`'s implementation was never supplied to any
reviewer, and the round-6 requirement for a real owner-device request against this SHA under the
rendered unit could not be met before deployment — it was step 4f of the plan, which comes after
the deploy. If this candidate is revised, `/whoami` belongs in A1's file list.

---

# Part A2 — the tool boundary and the pad routes

**Verdict: CHANGES_REQUIRED** — model `gpt-6-sol`, effort high.

> A2 is not ready. The two pad route bodies are repaired, but public /health still exposes pad status. The /turn middleware blocks refused callers before the model in the shown code, yet dispatch fails open without a request stamp and the real provider-to-tool path is unverified. The gate.py diff adds the objective_id issued-ID restriction and shape check; no other gate behavior changed in the shown diff. Public paths are /health, /ping, /whoami, /, /display, /sw.js, /manifest.webmanifest, /favicon.ico and the /static/ prefix. Exact matching keeps trailing-slash and case variants non-public; the OpenAPI route walk cannot establish coverage of the static mount, redirects or routes excluded from the schema.
> 
> [model gpt-6-sol, effort high, usage {"input_tokens": 70321, "input_tokens_details": {"cache_write_tokens": 70318, "cached_tokens": 0}, "output_tokens": 5012, "output_tokens_details": {"reasoning_tokens": 4142}, "total_tokens": 75333}]

## A2 · F-NEW-PAD

**Severity:** MATERIAL

**What it found**

STILL PRESENT in part. Both pad route bodies now call _refused before reading the heartbeat or returning status, so a refused caller cannot write registry events through POST /pad/heartbeat or receive either pad route’s status. But /health remains public and returns the same live pad-status block that GET /pad protects. A headerless host caller can still observe that sensitive status through /health.

**Evidence it cites**

`app/main.py (PUBLIC_PATHS, guard_and_freshness); app/routes/pad.py (pad, heartbeat); tests/test_pad.py (test_the_pad_block_is_the_wire_shape_the_layers_above_read, test_the_pad_block_is_never_served_from_the_health_cache)`

**Required repair**

Keep public /health to non-sensitive liveness only, or withhold its pad block from callers failing the owner rule. Test the headerless production-settings request against both /health and /pad.

**Verification note (mine, not the reviewer's)**

Confirmed, and the residual is a clean example of a boundary moved but not
closed.

Both pad route bodies do now call `_refused` before reading the heartbeat or returning status, so
the door I verified open in round 6 (`POST /pad/heartbeat` with no check of any kind) is shut.

But I confirmed the leak the reviewer found: `PUBLIC_PATHS` in `app/main.py` contains `/health`, and
`app/routes/health.py` composes `"pad": _pad()` into **all three** of its return paths (the two
cached branches and the live one). So the same live pad-status block that `GET /pad` now protects is
served unauthenticated on `/health`. Gating the route did not gate the data.

---

## A2 · F-NEW-TOOLS

**Severity:** MATERIAL

**What it found**

STILL PRESENT in part. The middleware refuses a non-owner /turn before reaching the model, and dispatch checks OWNER_REQUEST at one choke point for every tool it handles. ContextVar values are task-local, so ordinary concurrent requests do not share the flag, and to_thread work receives a copied context. But dispatch refuses only when the value is exactly False: its default None permits tools to run without any owner decision, as an added test expressly demonstrates. A detached task spawned by an owner request can also retain True after that request finishes; resetting the parent task does not revoke the copy. The dispatcher is therefore not a fail-closed request-owner boundary.

**Evidence it cites**

`app/tools/context.py (OWNER_REQUEST default); app/tools/dispatch.py (dispatch, OWNER_REQUEST.get() is False); app/main.py (guard_and_freshness, set/reset); tests/test_tool_boundary.py (test_outside_any_request_the_services_own_work_still_runs_its_tools)`

**Required repair**

Make missing request authority refuse tools by default. Give genuinely trusted service work a separate, explicit authorization rather than treating None or an inherited, post-request True as authority; test unscoped dispatch, concurrent requests and a detached task after response.

**Verification note (mine, not the reviewer's)**

Confirmed, and this is the finding I would act on first. I read it straight
out of the code.

`app/tools/context.py`:
    OWNER_REQUEST: ContextVar[bool | None] = ContextVar("crooks_owner_request", default=None)

`app/tools/dispatch.py:117`:
    if OWNER_REQUEST.get() is False:

The default is `None` and the guard fires only on exactly `False`. So any path that reaches
`dispatch` without the middleware having stamped the contextvar runs tools **with no owner decision
at all**. That is fail-open at the one place PR #48 nominates as the choke point, and the module's
own docstring states the design as "dispatch refuses every tool when it is False" — so this is
intended behaviour, not an oversight in a branch.

The reviewer adds that an added test expressly demonstrates unscoped dispatch running tools
(`test_outside_any_request_the_services_own_work_still_runs_its_tools`), which means service work
currently depends on the fail-open default. That is why the repair is not a one-character change:
trusted service work needs its own explicit authority before the default can be made to refuse.

I credit what is repaired: the middleware does refuse a non-owner `/turn` before the model, and
ContextVar values are task-local, so ordinary concurrent requests do not share the flag.

---

## A2 · F-NEW-TOOLS-PATH

**Severity:** MATERIAL

**What it found**

The required real /turn-to-tool execution path cannot be verified. The supplied end-to-end test substitutes ToolingProvider, whose turn method explicitly calls dispatch; it does not establish how the production Agent SDK provider invokes tools. The supplied PreToolUse hook checks classify but not OWNER_REQUEST, so its behavior cannot substitute for proof that every real invocation passes through the guarded dispatcher. app/routes/turn.py, app/providers/max_agent_sdk.py and the invocation wiring are absent from this packet.

**Evidence it cites**

`tests/test_tool_boundary.py (ToolingProvider.turn); app/tools/dispatch.py (make_pretooluse_hook); REVIEW PACKET — CANDIDATE FILES`

**Required repair**

Supply the production /turn, provider and tool-invocation wiring at this SHA. Demonstrate and test that every real SDK tool invocation, including newly registered tools, passes a fail-closed owner check before its handler runs.

**Verification note (mine, not the reviewer's)**

Confirmed as an evidence gap, and it is mine.

`app/routes/turn.py`, `app/providers/max_agent_sdk.py` and the tool-invocation wiring are in none of
the four parts, so no reviewer could see how the production Agent SDK provider actually invokes
tools. The end-to-end test substitutes a `ToolingProvider` whose `turn` calls `dispatch` directly,
which proves the guard works when it is reached, not that every real invocation reaches it. The
`PreToolUse` hook checks `classify` but not `OWNER_REQUEST`.

Round 6's F-NEW-TOOLS required "Supply and test the /turn and tool-dispatch authorization path". I
supplied the dispatcher but not the path to it. Those three files belong in A2's list next time.

---

# Part A3 — the gap record, screen copies, observability accounting

**Verdict: CHANGES_REQUIRED** — model `gpt-6-sol`, effort high.

> A3 is not ready. F-02 is repaired but latent with snapshots disabled. F-04 remains present at startup, in report preservation and at shutdown, although timer supervision is repaired. F-07 remains present despite the repaired capability override and a genuine vendored-reader rollback test. F-10 remains present in timeout propagation and session_ops wording.
> 
> [model gpt-6-sol, effort high, usage {"input_tokens": 112074, "input_tokens_details": {"cache_write_tokens": 112071, "cached_tokens": 0}, "output_tokens": 6493, "output_tokens_details": {"reasoning_tokens": 4660}, "total_tokens": 118567}]

## A3 · F-02

**Severity:** not material

**What it found**

REPAIRED for A3. The sanitizer drops every src, and screen_metadata reconstructs trigger, viewport and body from fixed keys. The route test exercises persistence with snapshots enabled and hostile images and metadata. This remains a latent path in production because snapshots stay off.

**Evidence it cites**

`app/observability/screens.py::_Sanitiser._attrs, screen_metadata; app/routes/observe.py::telemetry_screen; tests/test_observability.py::test_a_screen_copy_keeps_no_image_and_only_the_metadata_the_page_means_to_send; REVIEW PACKET — PRODUCTION STATE`

**Required repair**

None for this finding.

**Verification note (mine, not the reviewer's)**

Agreed — repaired, and this is the first of the five long-running findings to close.

The fixed attribute lists from round 6 hold, every `src` is now dropped, and `screen_metadata`
rebuilds trigger, viewport and body from fixed keys rather than scrubbing them, which is the right
shape for the metadata-key half. I did not re-run the hostile-input test myself.

Worth keeping in view: `CROOKS_SCREEN_SNAPSHOTS` stays `false` in this deploy, so this remains a
latent path. It becomes live the moment that switch is turned on, and that switch should be treated
as its own reviewable change.

---

## A3 · F-07-VALUES

**Severity:** MATERIAL

**What it found**

STILL PRESENT. Whitelisting field names has not sanitized every retained value. _sanitise copies misjudged first_seen and last_seen verbatim; report returns them verbatim. For example, a legacy first_seen of greg@example.com with count 1 survives the startup rewrite and enters the report. seeded is also retained without validation. An invalid misjudged count can instead make report's int conversion fail. The capability-key override itself is repaired.

**Evidence it cites**

`app/objectives/gaps.py::_sanitise, _TOP_FIELDS, GapLedger.report; tests/test_capability_gaps.py::test_a_stored_row_cannot_stand_in_for_its_cleaned_key_or_carry_fields_of_its_own`

**Required repair**

Validate and reconstruct the values of every retained legacy field, including misjudged counts and timestamps and top-level seeded/version; test hostile values in known fields through the startup rewrite and report.

**Verification note (mine, not the reviewer's)**

Confirmed in mechanism. The capability-key override I demonstrated in round 6 —
`{"capability": k, **v}` letting a legacy row's own field overwrite the cleaned key — is genuinely
repaired.

What replaced it is a whitelist of field NAMES, not of values: `_MISJUDGED_FIELDS = ("count",
"first_seen", "last_seen")` and `_TOP_FIELDS = frozenset({"version", "gaps", "builds", "misjudged",
"seeded"})`. Name-whitelisting is not value-validation, which is exactly the reviewer's point: a
retained `first_seen` or `last_seen`, or top-level `seeded`, passes through with whatever it holds.
I confirmed the whitelists are by name and include those fields; I did not build a hostile record to
watch an email survive the rewrite, so the reviewer's specific example is unverified by me.

---

## A3 · F-07-LINKS

**Severity:** MATERIAL

**What it found**

STILL PRESENT. The new link pass checks only that each referenced record exists, not that a gap's request and that build's gaps agree. A gap can therefore report the stage of an unrelated surviving build. _merge still truncates merged requests, objectives and seen history; its summed hits do not preserve the lost links or the history needed for hits_after_fix. The supplied collision test uses fewer than the truncation limits.

**Evidence it cites**

`app/objectives/gaps.py::_sanitise, _merge, GapLedger.report; tests/test_capability_gaps.py::test_links_between_gaps_and_builds_point_only_at_what_is_still_there`

**Required repair**

Validate reciprocal relationships after remapping and preserve, or explicitly account for, collision history and links without silently making the stage or recurrence report inaccurate; test mismatched surviving links and collisions beyond the limits.

**Verification note (mine, not the reviewer's)**

Not independently verified. I read the new link pass and it does check that each
referenced record exists; I did not test reciprocity, nor construct a collision beyond the
truncation limits to see whether `_merge` loses links or mis-reports `hits_after_fix`. The claim is
consistent with the `_merge` behaviour round 6 already established (it truncates `requests`,
`objectives` and `seen`), which is unchanged here.

---

## A3 · F-07-DURABILITY

**Severity:** MATERIAL

**What it found**

STILL PRESENT. _keep_original uses O_EXCL, mode 0600 and file fsync, and the normal successful clean makes one backup. But _fsync_dir suppresses both directory-open and fsync errors, allowing the live file to be replaced even when the backup's directory entry was not durably committed. A failed save followed by a retry can also make another backup. The vendored-reader test does read, report and write the cleaned fixture, and the documented stopped-service restoration can restore the selected original, but neither cures the durability failure.

**Evidence it cites**

`app/objectives/gaps.py::_keep_original, _fsync_dir, _repair_locked, install; tests/test_capability_gaps.py::test_the_code_a_rollback_returns_to_reads_writes_and_reports_the_cleaned_record; docs/DEPLOY_LINUX.md — The capability-gap record`

**Required repair**

On this Linux deployment, propagate backup-directory fsync failures and leave the live file untouched; make retries recognize a verified existing original rather than proliferating backups. Test failed directory fsync and failed-save/retry paths.

**Verification note (mine, not the reviewer's)**

Confirmed. `_keep_original` does use `O_EXCL`, mode 0600 and an fsync of the
file, and a normal successful clean makes exactly one backup — all of which round 6 asked for.

But `_fsync_dir` suppresses everything:
    try: fd = os.open(folder, os.O_RDONLY)
    except OSError: return
    try: os.fsync(fd)
    except OSError: pass
So a failure to make the backup's directory entry durable is invisible, and the live file is then
replaced anyway. On a crash between those two events the backup can be absent while the cleaned file
is present — which is the one state the whole F-07 repair exists to prevent.

I also credit the part I checked hardest, because it was my round-6 objection:
`tests/rollback/gaps_3e77f215.py` is byte-identical to `git show
3e77f215:crooks-assistant/app/objectives/gaps.py` from line 6 onward — both sha256
b6bfba90973a1647659e4d3e24e61a006d8aaffbb03e52236ddc992c9f24c26f, 16831 bytes. The vendored reader
genuinely is the rollback target's code, and it is exercised against the cleaned file. That specific
round-6 gap is closed.

---

## A3 · F-04-STARTUP

**Severity:** MATERIAL

**What it found**

STILL PRESENT for startup fail-closed behavior. If the reports directory itself remains exposed, withhold leaves it in left; first_pass records an error and /health becomes degraded, but lifespan still starts serving. Reporting exposure on /health is detectable, not fail-closed. tighten also treats a failed traversal as an empty path list.

**Evidence it cites**

`app/observability/session.py::tighten, withhold, TestSessions.tidy_reports; app/main.py::housekeep_once, Housekeeper.first_pass, lifespan`

**Required repair**

Make incomplete permission checks or any exposure that cannot be contained block startup or otherwise prevent access to the exposed reports. Test an unfixable reports directory and a traversal failure.

**Verification note (mine, not the reviewer's)**

Confirmed as reported. `first_pass` records an error and `/health` goes
degraded, but `lifespan` still starts serving. Reporting an exposure is detection, not fail-closed,
and round 6 asked for fail-closed. I also confirmed `tighten` treats a failed traversal as an empty
path list, so "nothing exposed" and "could not look" are indistinguishable to its caller.

---

## A3 · F-04-REPORT-LOSS

**Severity:** MATERIAL

**What it found**

STILL PRESENT for safe startup handling of the owner's reports. When moving an exposed path fails, withhold calls _remove_if_older(path, infinity), which deletes even a fresh report or an entire report directory. This runs during startup and every later housekeeping pass, with no recoverable copy required. The test covers a successful move and an unsuccessful move/removal, not the destructive fallback.

**Evidence it cites**

`app/observability/session.py::withhold, _remove_if_older, TestSessions.tidy_reports; tests/test_screen_privacy.py::test_a_report_that_cannot_be_made_private_is_withheld_and_what_is_left_is_said`

**Required repair**

Do not delete non-expired owner reports as a permission-repair fallback. Retain them in verified private storage, or fail closed and surface the problem without destroying them; test move failure on a fresh report and directory.

**Verification note (mine, not the reviewer's)**

Confirmed, and of the 21 material findings this is the one I would put in
front of the Director first. It is a destructive action added at start-up in the course of fixing
F-04.

`app/observability/session.py::withhold` tries to move an exposed report into a private 0700 folder
and, if that fails, reaches its fallback:

    _remove_if_older(path, float("inf"))

and `_remove_if_older` is:

    if path.stat().st_mtime >= cutoff: return 0
    if path.is_dir(): shutil.rmtree(path, ignore_errors=True)
    else: path.unlink()

With `cutoff` of `+inf`, `st_mtime >= inf` is always False, so the age test can never spare
anything: the path is **always** deleted, whatever its age. If it is a directory — and screen
artefacts live in `ts-…-screens/` directories — it goes by `shutil.rmtree(..., ignore_errors=True)`.

This runs from `install()` at every start-up and on every housekeeping pass, against the owner's
live reports, with no recoverable copy required first. The docstring rationalises it ("a report is
drawn from a session and can be drawn again"), but the session it was drawn from may itself have
been pruned. The supplied test covers a successful move and an unsuccessful move, not this fallback.

This is squarely against the standing acceptance criterion that there be no destructive or
irreversible action at import, start-up or request time. Note it did not run here: nothing was
deployed.

---

## A3 · F-04-SHUTDOWN

**Severity:** MATERIAL

**What it found**

STILL PRESENT for awaited shutdown. Supervision and timer restart after an unexpected exception or cancellation are repaired. But Housekeeper.stop waits at most 60 seconds for the threaded pass, returns False if it is still running, and lifespan ignores that result and calls runtime.aclose. A long or stuck pass can therefore overlap runtime closure.

**Evidence it cites**

`app/main.py::Housekeeper._ended, Housekeeper.stop, lifespan; tests/test_screen_privacy.py::test_shutdown_waits_for_a_pass_already_running_before_the_runtime_is_closed`

**Required repair**

Do not close the runtime while a housekeeping pass still uses it. Handle the timeout explicitly with a safe shutdown policy, and test a pass that outlasts the timeout.

**Verification note (mine, not the reviewer's)**

Confirmed as reported. Timer supervision and restart after a failure are
genuinely repaired — that part of round 6 is closed. But `Housekeeper.stop` waits at most 60 seconds
for the threaded pass and returns False if it is still running, and `lifespan` ignores that return
value and calls `runtime.aclose()` regardless. So a long or stuck pass can still overlap runtime
closure, which is the specific overlap round 6 named.

---

## A3 · F-10

**Severity:** MATERIAL

**What it found**

STILL PRESENT in part. Timeline.stop now retains the flush result, and cmd_stop distinguishes unsettled on-disk counts; cmd_status calls its figure on-disk and shows pending work. But the stop route returns counts without stop_settled, so a timed-out flush that finishes before counts is read can be presented by cmd_stop as final without disclosing the timeout. Separately, scripts/session_ops.py still says 'Recorded N event(s)' after _settle sees two identical file counts; a stalled writer can produce those identical counts while events remain pending. Timeline.counts reads the file outside its lock, comparing locked snapshots on either side.

**Evidence it cites**

`app/observability/timeline.py::Timeline.stop, counts; app/routes/observe.py::stop; scripts/test_session.py::cmd_stop, stopped_line, cmd_status; scripts/session_ops.py::_settle, stop_and_analyse`

**Required repair**

Carry the stop flush outcome through the route and require it as well as settled counts before calling a stop total final. Have session_ops consume authoritative pending/flush state and describe its count as an on-disk snapshot when unsettled; test a held writer through both owner-facing stop paths.

**Verification note (mine, not the reviewer's)**

Confirmed in part, and the reviewer found a path I had not looked at.

The repaired half is real: `Timeline.stop` now retains the flush result and `cmd_stop`
distinguishes an unsettled on-disk count, which is what round 6 required of those two.

The residuals are two. The stop ROUTE returns counts without `stop_settled`, so a flush that timed
out but finished before counts were read can still be presented as final. And
`scripts/session_ops.py` — which I had not examined in any round — still says "Recorded N event(s)"
once `_settle` sees two identical file counts, and a stalled writer produces exactly that. So the
owner can still be handed a total that is a snapshot.

The reviewer also re-confirms what round 6 corrected: `counts` reads the file OUTSIDE the lock and
compares locked snapshots either side, whatever the comments say.

---

# Part B — the screens feature

**Verdict: CHANGES_REQUIRED** — model `gpt-6-sol`, effort high.

> Part B is not ready. B-06 and B-07 are repaired; the routes and several storage and UI controls improved. Screen-name takeover, client-asserted packing completion, privacy-deletion durability and the unverified screen-tool boundary remain material blockers.
> 
> [model gpt-6-sol, effort high, usage {"input_tokens": 101995, "input_tokens_details": {"cache_write_tokens": 101992, "cached_tokens": 0}, "output_tokens": 7176, "output_tokens_details": {"reasoning_tokens": 5696}, "total_tokens": 109171}]

## B · B-01

**Severity:** MATERIAL

**What it found**

STILL UNVERIFIED for the screen tools. The /displays router has require_principal, but screen_list and screen_show have no principal check. The supplied screen tests call the tools or dispatch with a session, not an HTTP turn from a caller refused by the write gate. The shared dispatch boundary is assigned to A2, but it is not shown here, so this part cannot establish that the screen tools sit behind it.

**Evidence it cites**

`app/routes/displays.py:router; app/tools/display_tools.py:screen_list, screen_show; tests/test_displays.py:test_an_objective_goes_up_only_once_this_conversation_was_shown_it; packet section THIS IS PART B`

**Required repair**

Establish the deny-by-default turn-to-dispatch boundary with code and end-to-end refused-caller tests covering both screen tools, or enforce the verified principal at those tools.

**Verification note (mine, not the reviewer's)**

Confirmed as still unverified, and the cause is the same as A2's F-NEW-TOOLS-PATH. The
`/displays` router does carry `require_principal`, but `screen_list` and `screen_show` have no
principal check of their own — they rely entirely on the shared `dispatch` choke point, which A2
found fails open on its `None` default. So the two halves of this finding compound: the screens
tools depend on a boundary that A2 has shown is not closed.

---

## B · B-02

**Severity:** MATERIAL

**What it found**

STILL PRESENT in the quiet-period case. Registration generates a strong 24-byte random key, stores its SHA-256 hash, and compares hashes with hmac.compare_digest; poll and done require it. But register replaces the key for anyone who supplies the matching name once online() is false, without the old key or an approved recovery. The new holder inherits the existing ID and showing, so can poll a customer's slip or mark it done. _seen is only in memory, making every existing screen appear offline immediately after a service restart. There are no pre-deploy screens to migrate, but first registration is likewise a race to claim an intended name.

**Evidence it cites**

`app/displays/store.py:DisplayStore.register, online, _holder, poll, mark_done; tests/test_displays.py:test_a_name_is_one_screen_however_it_is_typed_and_the_device_that_named_it_holds_it`

**Required repair**

Do not transfer a registration or its showing by name after inactivity or restart. Require the existing key or an explicit owner-approved recovery that clears the old showing and credential; address first-registration pairing.

**Verification note (mine, not the reviewer's)**

Confirmed by reading `DisplayStore.register`, and the restart case makes it worse than
it first looks.

The credential half is done properly: `secrets.token_urlsafe(24)`, only a SHA-256 hash stored,
`hmac.compare_digest` to compare, and both `poll` and `mark_done` require it.

But the name-match branch does not create a new screen. It takes the EXISTING record — its `id` and
whatever it is `showing` — and merely replaces `secret` and bumps `version`. Its only guard is
`self.online(screen["id"])`, and `online` reads `self._seen`, which `__init__` sets to an empty dict.
`_seen` is memory-only, so after any service restart every screen is offline and every screen name
is immediately claimable by any caller, who then inherits that screen's id and its slip. A restart
is not an unusual event — this deploy is one.

`register` documents the behaviour as intended ("a screen that has gone quiet can be named again
from another device"), so the fix is a policy decision, not a bug fix: quiet must not mean
transferable when a customer's slip is attached.

---

## B · B-03

**Severity:** MATERIAL

**What it found**

STILL PRESENT in part. mark_done strips the address, phone, note and items from showing; install() sweeps an expired slip on restart, and _expire_locked specifies 12-hour showing and 90-day done cutoffs. Views and the attempted file write have byte caps; new files use a 0600 temporary file in a 0700 directory. However, done rows and the stripped showing retain title and ref, which can themselves be customer text for lists or objectives, for up to 90 days. _save fsyncs the temporary file but not its parent after os.replace, and silently absorbs write failures. An expiry or done operation can therefore appear successful in memory while the prior customer slip remains on disk. The claimed independent housekeeping timer is not shown in this part. On a successful restart after expiry the slip is removed; after a failed save or crash durability failure, that removal is not assured.

**Evidence it cites**

`app/displays/store.py:_expire_locked, _save, mark_done, install; app/displays/views.py:list_view, objective_view; packet section B-03`

**Required repair**

Apply a privacy policy to title/ref in retained done rows; fsync the parent after replacement and surface failed privacy-deletion writes so they can be retried or fail closed. Supply the timer wiring needed to verify unattended expiry.

**Verification note (mine, not the reviewer's)**

Confirmed in part, and the privacy substance is much improved. `mark_done` does now
strip address, phone, note and items from `showing`; `install()` sweeps an expired slip on restart;
`_expire_locked` sets 12-hour showing and 90-day done cutoffs; views and the file write have byte
caps; and a new file is a 0600 temporary in a 0700 directory. Round 6's core complaint — that
marking done left the customer's name, address and phone on disk — is closed.

Two residuals, both real. `done` rows and the stripped `showing` keep `title` and `ref`, which for a
list or objective view can themselves be customer text, for up to 90 days. And `_save` fsyncs the
temporary file but not the parent after `os.replace`, while absorbing write failures silently — so a
privacy DELETION can appear to succeed in memory while the prior slip is still the durable content
on disk. That is the same class of defect as F-07-DURABILITY, in a different file.

I did not verify the housekeeping-timer wiring; it was not in Part B, which is why the reviewer
could not confirm unattended expiry.

---

## B · B-04

**Severity:** MATERIAL

**What it found**

STILL PRESENT in the server attestation. The page paginates orders, disables Mark packed until its page set is complete, and both page and server refuse a slip marked partial at the 60-item limit. But mark_done accepts any client-supplied items_seen greater than or equal to the number of items. A key holder can POST that count and the current version without opening any page; the server has no evidence of which pages were displayed. Thus the done row can still attest that an unseen order was packed.

**Evidence it cites**

`app/displays/store.py:_shown_count, DisplayStore.mark_done; app/routes/displays.py:DoneBody, done; web/display.js:itemsSeen, markDone`

**Required repair**

Make complete-order confirmation enforceable rather than trusting a client-asserted count—for example, track page-specific acknowledgements for the current version server-side—and test a direct done POST that claims all items without viewing them.

**Verification note (mine, not the reviewer's)**

Confirmed by reading the server side, and the conclusion is that the control is still
client-asserted.

`DoneBody.items_seen` is an ordinary client field (`int | None`, bounded 0..10000). `mark_done`'s
check is:
    shown = _shown_count(showing)
    if shown is not None and (items_seen is None or int(items_seen) < shown): raise
So any caller holding the screen key can POST `items_seen` equal to the item count together with the
current `version` and record the order as packed **without ever opening a page**. The server keeps no
record of which pages were displayed, so it cannot tell the difference.

The page-side work is real — pagination, the button disabled until the page set is complete, and a
60-item `partial` slip refused by both page and server. But a disabled button is not a control, and
round 6 asked for complete-order confirmation to be enforceable. Combined with B-02, the key that
makes this assertion is itself obtainable by name after a restart.

---

## B · B-05

**Severity:** MATERIAL

**What it found**

STILL PRESENT in the destination guarantee; the issued-ID portion is not fully verifiable here. screen_show now names a destination exactly and rejects oversized lines and elements before finding a screen or processing lines. It declares objective_id as an issued ID, but the gate's _ID_KIND implementation is not supplied. More importantly, an exact name does not establish a safe physical destination while B-02 permits another device to take that name and inherit its showing after inactivity or restart.

**Evidence it cites**

`app/tools/display_tools.py:screen_show; app/displays/store.py:DisplayStore.find, register; packet section PR #48 BODY — Protected paths changed by hand`

**Required repair**

Supply the gate implementation to establish objective-ID kind and issuance enforcement, and pair sensitive destinations with a registration that cannot be taken by name alone.

**Verification note (mine, not the reviewer's)**

Confirmed as reported, and the dependency on B-02 is the important part. `screen_show`
does now name a destination exactly and reject oversized `lines` and elements before finding a screen
or processing them, which is the ordering round 6 asked for. `objective_id` is declared as an issued
id, but `app/tools/gate.py`'s `_ID_KIND` went to A2 rather than B, so the reviewer could not confirm
enforcement from here — A2 reports the gate diff adds exactly that restriction and nothing else, so
between the two parts that half appears sound.

What remains is that an exact name is not a safe physical destination while B-02 lets another device
take that name and inherit the showing. A sensitive objective can therefore be routed to a screen
that is not the intended one.

---

## B · B-06

**Severity:** not material

**What it found**

REPAIRED for the reported initialization failure. The escape timer is installed before engine creation, creation and initialization are guarded, and is-live is set only after create returns. A failing Canvas context takes the guarded error path; the independent timer removes the overlay if progress stalls.

**Evidence it cites**

`web/startup.js:bail, initialization guard, CliveDots.create; web/startup.css:.startup.is-live; tests/web/startup.test.js`

**Required repair**

None for B-06.

**Verification note (mine, not the reviewer's)**

Agreed — repaired. I verified the ordering myself, which was the whole of round 6's
complaint: the escape timer is now installed before the engine is created, creation and
initialisation are guarded, and `is-live` is set only after `create` returns. A failing Canvas
context takes the guarded path, and the independent timer removes the overlay if progress stalls. The
round-6 sequence (is-live at line 46, create at 60, timer not until 212) is gone.

---

## B · B-07

**Severity:** not material

**What it found**

REPAIRED as an evidence gap. The complete worker and tests are supplied. Its shell list excludes /display, screen assets and /displays/*, so those requests are not intercepted. It keys shell caches by build and deletes older shell caches on activation; offline it can serve only the cached application shell, not screen or owner-record responses. An online 403 after a login change passes through and is not cached. The old shell can remain until the new worker activates, as designed.

**Evidence it cites**

`web/sw.js:SHELL, install, activate, fetch, networkFirst; tests/web/sw.test.js:screen, build, offline and change-of-login tests`

**Required repair**

None for B-07.

**Verification note (mine, not the reviewer's)**

Agreed — repaired, and this one closes an evidence gap that was mine. Round 6 could not
rule on the worker because I sent only its `SHELL` hunk to stay inside the harness's file budget. The
complete `web/sw.js` and its tests went to Part B this time, and the reviewer could rule: the shell
list excludes `/display`, the screen assets and `/displays/*`, so those are not intercepted; shell
caches are keyed by build with older ones deleted on activation; offline it can serve only the cached
application shell, not screen or owner-record responses; and an online 403 after a login change
passes through uncached.

PR #48 says `sw.js` itself is unchanged, so what closed here was the evidence, not the code.

---

## What I verified, and what I did not

Every claim I checked held. Confirmed directly in the code: the `OWNER_REQUEST` fail-open default
and `dispatch`'s `is False` guard; `withhold()`'s always-true deletion via `float("inf")` and its
`rmtree` of directories; `/health` being public while composing the pad block into all three of its
return paths; `own_addresses`' 600-second positive cache; `_fsync_dir` suppressing both open and
fsync errors; `register` reusing an existing screen's id and `showing` behind a memory-only
`_seen`; `mark_done` trusting a client-supplied `items_seen`; and the name-only whitelists
`_MISJUDGED_FIELDS` and `_TOP_FIELDS`. I also confirmed the repairs: F-02's dropped `src` and
rebuilt metadata, B-06's corrected start-up ordering, B-07's worker behaviour, and the vendored
rollback reader's byte-identity.

Not independently verified: F-07-LINKS' reciprocity and collision accounting; the F-05B PID-reuse
race, which I would not attempt against a live service; F-07-VALUES' specific example of an email
surviving in a timestamp field (I confirmed only that the whitelist is by name, not by value); and
the housekeeping-timer wiring behind B-03's unattended expiry.

Two evidence gaps are mine to own. `app/routes/environment.py` (`/whoami`) went to no part, so
A1 could not rule on it; and `app/routes/turn.py`, `app/providers/max_agent_sdk.py` and the
tool-invocation wiring went to no part, which is precisely why A2 could not verify the real
`/turn`-to-tool path. Those four files belong in the next round's lists.

## Artefacts

Held on the deploy host under `/root/clive-activation/round-7/`, not committed here: the four
`.review.json` verdicts, the four dispatch packets and job files, the packet builder with its
budget simulation, the rendered and installed unit files and their diff, the
`LoadCredentialEncrypted` comparison, the credential and secret name listings, the env-switch
record, the pre-deploy baseline and `/health` baseline, the proxy-identity preconditions, the
rollback-fixture check, the acceptance-run record, the range diffstat, the PR #48 body, and
sha256 prefixes of the eight `gaps.json` keys (hashes only, so a future clean can be checked by
count and hash without reading a key). The unrun deploy script is there as `deploy.sh`.

