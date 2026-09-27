# Deploy review, round 6 — findings for the Director

**Candidate reviewed:** `9a79dc1243c9d922079a4064a24435a98d39884a` (`clive/trunk` head at the time of review; PRs #45 and #46).
**Currently deployed:** `3e77f2157a35a23ba69014c1b0161a9351accd48` (PR #42).
**Last SHA a reviewer had judged before this:** `e4f8bb437f51e23c2f9cbbc233f7fccb2d9ea51c` (round 5, CHANGES_REQUIRED, 7 material findings, not deployed).

**Outcome: both parts returned CHANGES_REQUIRED. Nothing was deployed. No `.env` line, no service
file, no systemd state and no checkout was changed.** `CROOKS_SCREEN_SNAPSHOTS` stayed `false` and
`CROOKS_ENGINEERING_HOST` stayed unset throughout.

## How this review was run

The range `3e77f215..9a79dc12` is 64 files. The reviewer harness derives its own full-file block
from the `diff --git` headers in the packet and spends a 300 KB budget in git's alphabetical path
order. Sent as one request, that budget is exhausted on the first 19 paths and silently omits most
of the files the review depends on. So the review was split into two bounded dispatches, both
required to return READY:

| Part | Scope | Verdict | Findings |
|---|---|---|---|
| A | The seven round-5 findings and all server-side code (`app/`, `config/`, `deploy/`, `scripts/`, `launchd/` and four named test files) | **CHANGES_REQUIRED** | 10 (9 material) |
| B | PR #45's screens feature, never previously reviewed (`app/displays/`, `app/routes/displays.py`, `app/tools/display_tools.py`, `tests/test_displays.py`, `web/`) | **CHANGES_REQUIRED** | 7 (7 material) |

Both were reviewed by `gpt-6-sol` at high effort, each told it was one half of a split and not to
approve what it could not see.

## Two standing facts the Director should carry forward

**1. `clive/trunk` has no branch protection, and none can be configured.**
`GET /branches/clive%2Ftrunk/protection` and `GET /rulesets` both return HTTP 403
("Upgrade to GitHub Pro or make this repository public to enable this feature"), and
`GET /branches/clive%2Ftrunk` reports `"protected": false`. The repository is private under a free
personal account. There is no required review, no required status check and no push restriction:
anything that can push can land on trunk. A SHA's presence on trunk and a green acceptance run
therefore carry **zero** review weight. Both reviewers were told this and both weighted it.

**2. The engineering bridge was kept out of this deploy by parking its credential.**
`github_engineering_inbox_token.cred` was moved to `/etc/crooks-os/credentials-parked/` (directory
0700, file 0600, 292 bytes, original mtime preserved). It was moved, never opened, read or
decrypted, and it stays parked. Note that leaving `CROOKS_ENGINEERING_HOST` unset does **not** by
itself make the bridge inert — `settings.engineering_host` still defaults to `worker-01` — so the
parked credential is what makes it inert. F-ENG is deferred on that basis, not cleared.

---

# Part A — the round-5 findings and the server side

**Verdict: CHANGES_REQUIRED**

> Part A is not ready. F-02, F-04, F-05A, F-05B, F-07 and F-10 remain at least partly present; F-ENG is deferred while its credential is parked. The sender-folding issue W-01 remains under its waiver: the shown fastpath change adds repeat-answer caveats, not a sender-folding repair. Screens authorization, storage and display_tools cannot be cleared from Part A because their implementation is reserved for Part B. clive/trunk has no branch protection; its position and green CI carry zero review weight.
> 
> [model gpt-6-sol, effort high, usage {"input_tokens": 154126, "input_tokens_details": {"cache_write_tokens": 154123, "cached_tokens": 0}, "output_tokens": 8232, "output_tokens_details": {"reasoning_tokens": 5489}, "total_tokens": 162358}]

## F-02

**Severity:** MATERIAL

**What it found**

STILL PRESENT in part. In app/observability/screens.py, _Sanitiser._attrs now drops d and arbitrary aria- names, so the two demonstrated round-5 examples are repaired. Its src branch nevertheless retains base64 inline images without inspecting the image content. sanitise_metadata delegates to timeline.scrub, which preserves non-withheld dictionary keys, including credential-shaped keys; telemetry_screen persists that result. The attribute list is now fixed. Snapshots remain disabled in this deploy, so these are latent persistence defects, not active snapshot capture.

**Evidence it cites**

`DIFF — app/observability/screens.py (_Sanitiser._attrs, sanitise_metadata); app/observability/timeline.py (scrub); app/routes/observe.py (telemetry_screen); REVIEW PACKET — PRODUCTION STATE`

**Required repair**

Do not persist uninspected inline images; redact or reject sensitive metadata keys as well as values. Test the actual persistence route with snapshots enabled and adversarial image and metadata inputs.

**Verification note (mine, not the reviewer's)**

Confirmed, in both directions.

On the round-5 code (`e4f8bb43`) I reproduced both of the reviewer's examples against the
module's own regexes and both were real: `d="M 07700 900123"` passed `_DRAWING_VALUE` and evaded
`_LONG_NUMBER` (the phone number is written with a space, so no run of seven digits exists), and
`_ARIA_NAME = ^aria-[a-z]{2,20}$` accepted `aria-gregevans`.

At `9a79dc12` both are genuinely closed, by construction rather than by a tighter pattern:
`_FREEFORM_DRAWING = frozenset({"d", "points", "transform"})` is dropped outright, `_ARIA` is now
an explicit WAI-ARIA 1.2 frozenset with no regex, and `DATA_NAMES` is a fixed frozenset — the
runtime glob and its `lru_cache` are gone, which also closes the trust-boundary half of the
round-5 finding.

I did not independently test the two residuals the reviewer names (uninspected base64 in `src`,
and `scrub` preserving non-withheld dictionary keys). They are consistent with the code I read.

---

## F-04

**Severity:** MATERIAL

**What it found**

STILL PRESENT in part. app/main.py lifespan now awaits a housekeeping pass before serving, but housekeep_once and session.tighten swallow failures, so unsuccessful permission tightening does not prevent service. _housekeeping has no supervision or recovery if its task fails or is unexpectedly cancelled. Shutdown cancels the task without awaiting it; cancellation of asyncio.to_thread does not stop a pass already running in its thread, which can overlap runtime.aclose.

**Evidence it cites**

`DIFF — app/main.py (lifespan, housekeep_once, _housekeeping); app/observability/session.py (tighten)`

**Required repair**

Make startup tightening failures detectable and fail closed for exposed reports; supervise and restart periodic passes after failures; stop scheduling and await completion of any in-progress threaded pass before closing the runtime.

**Verification note (mine, not the reviewer's)**

Confirmed repaired in the part the reviewer credits, and I agree the rest stands.

`app/main.py` line 101 is `await asyncio.to_thread(housekeep_once, app.state.runtime)`, which
precedes the `create_task` on 102 and the `yield` on 104 — so one pass does complete before the
service accepts a request. That is the startup half of the round-5 required repair.

The other two parts remain visible in the same function: `_housekeeping` is a bare
`create_task` with no supervision or restart, and shutdown still calls `housekeeping.cancel()`
without awaiting it. I did not test whether a failed `tighten` is observable.

---

## F-05A

**Severity:** MATERIAL

**What it found**

STILL PRESENT in the local-control portion. app/routes/observe.py now applies principal_check to its controls and telemetry, repairing the headerless observe-router admission. But production's CROOKS_WRITES_LOCAL_OWNER=false makes the existing on-server test-session CLI receive 403, without a separate authenticated local-CLI mechanism. The owner can use an authorized proxied device, but not that CLI. Setting the shared flag to restore it would also authorize headerless host processes under actions.caller_check to apply business writes.

**Evidence it cites**

`DIFF — app/routes/observe.py (_refused, telemetry); app/routes/actions.py (principal_check, caller_check); REVIEW PACKET — F-05A operational point and PRODUCTION STATE`

**Required repair**

Provide an intentional, narrowly authenticated local CLI control that does not set CROOKS_WRITES_LOCAL_OWNER or widen the business-write gate; test it with the production flag values.

**Verification note (mine, not the reviewer's)**

Confirmed, including the operational consequence, which I raised in the packet.

All six observe routes now pass through `_refused()` / `principal_check` (`observe.py` lines 91,
109, 121, 140, 151 and 171, plus `/telemetry/screen` at 243). The headerless admission the
round-5 review found is closed.

The residual is a real operational problem, not a theoretical one. Production has
`CROOKS_WRITES_LOCAL_OWNER=false`, which I recorded read-only at preflight, so the owner's
on-server `make test-session-*` CLI now receives a 403. The trap the reviewer identifies is worth
stating plainly: the obvious operator fix — setting that flag true — would also authorise
headerless host processes to apply business writes, because `caller_check` reads the same flag.
That would be a much larger change than restoring a CLI.

---

## F-05B

**Severity:** MATERIAL

**What it found**

STILL PRESENT in the provenance check, despite the repaired empty-allow-list behavior. principal_check and caller_check use the same proxy_state decision, and both fail closed on a missing allow-list. But identity.pids_named authenticates a proxy solely by its process comm, which another local process can name tailscaled. More seriously, _proc_peer_check accepts an inode from _holdings without rechecking the process's current fds: socket-inode reuse, including after a tailscaled PID is recycled, can turn a non-tailscaled connection into an accepted one. A matching cached inode also bypasses a subsequent fd-read failure. A claimed owner's forwarded address can then pass identity.verify, which verifies the address holder rather than the sender. proc-table absence, unreadability, missing tailscaled, malformed rows and a rewritten client port generally refuse; that does not cure these false positives. _proc_forms uses the machine's word byte order and tries IPv4-mapped IPv6, as required by the supplied tests.

**Evidence it cites**

`DIFF — app/identity.py (pids_named, _proc_peer_check, _tailscaled_pids, _proc_forms); app/routes/actions.py (proxy_state, caller_check, principal_check); tests/test_proxy_identity.py`

**Required repair**

Authenticate the actual proxy process rather than comm alone, and verify current socket ownership for each request without a positive stale-inode cache. Exercise inode reuse, PID reuse, a renamed local process and fd-read failures against both owner-record and business-write gates.

**Verification note (mine, not the reviewer's)**

Confirmed. This is the most serious finding in either part, and I verified both
mechanisms directly.

1. The `comm` check is not an authentication. `identity.pids_named` matches a process by
   `/proc/<pid>/comm` alone. I confirmed that any process can set that freely: a single
   `prctl(PR_SET_NAME, "tailscaled")` call changed a Python process's `comm` from `python3` to
   `tailscaled`, after which `pids_named("tailscaled")` would return it.

   The consequence is worse than a naming collision. A local process that renames itself and
   then *opens the connection itself* genuinely holds that connection's client-end socket inode,
   so `socket_inode()` finds it and `socket_inodes(pid)` contains it. The check therefore returns
   `True, "opened by tailscaled"`. A forged `X-Forwarded-For` naming one of the owner's devices
   then passes `identity.verify`, because whois confirms who holds the *address*, not who sent the
   packet. That is a complete bypass of the F-05B repair by any process that can reach the port.

2. The inode cache short-circuits the check. In `_proc_peer_check`:
   `held = _holdings.get(pid)` / `if held is None or inode not in held: held = socket_inodes(pid)`
   / `if inode in held: return True`. When the cached set already contains the inode, the
   function returns `True` with no re-read of the process's current fds. Kernel socket inodes are
   reused, so a stale positive persists and also masks a later fd-read failure.

I verified the mechanisms only. I did not run the end-to-end bypass against the live service, and
no such request was sent.

I also confirm the reviewer's credit where due: `principal_check` and `caller_check` now share one
`proxy_state` decision and both fail closed on a missing allow-list, which closes that half of the
round-5 finding.

---

## F-05B-AVAIL

**Severity:** MATERIAL

**What it found**

STILL PRESENT as an owner lockout risk. identity.is_this_host treats a successful bind as proof that the forwarded address belongs to this host. Enabling net.ipv4.ip_nonlocal_bind, or an equivalent nonlocal-bind behavior, makes an owner's remote address appear local; proxy_state then chooses THIS_HOST and both gates refuse all three owner's proxied devices with the production local-owner flag false. The reported sysctls make this hazard not live today, but a host configuration change can activate it without changing code. The supplied tests mock the proxy decision; the packet does not demonstrate a successful owner request through the newly rendered production unit. --no-proxy-headers is load-bearing: without the unit re-render, uvicorn replaces the client address and the port-0 check refuses forwarded requests.

**Evidence it cites**

`DIFF — app/identity.py (is_this_host, _proc_peer_check); app/routes/actions.py (proxy_state); REVIEW PACKET — CHANGE C, F-05B(c–d), UNIT DIFF`

**Required repair**

Identify local addresses by interface ownership rather than bind success. Verify a real owner-device request using this SHA and the rendered --no-proxy-headers unit before deployment, and explicitly fail deployment when the unit was not updated.

**Verification note (mine, not the reviewer's)**

Confirmed as a latent risk, not a live one, and I checked the host myself.

`identity.is_this_host` infers that an address is local from a successful `socket.bind()`. On this
host the hazard is not active: `net.ipv4.ip_nonlocal_bind = 0` and `net.ipv6.ip_nonlocal_bind = 0`,
both read at preflight. If either were set to 1, every forwarded address would bind successfully,
`proxy_state` would answer `this_host`, and with `CROOKS_WRITES_LOCAL_OWNER=false` both gates would
refuse all three of the owner's devices at once. No code change would be involved.

The reviewer's point about the unit is independently important and I verified the preconditions:
`--no-proxy-headers` is load-bearing, because `_proc_peer_check` detects the overwritten case only
by a client port of 0. The installed unit does **not** currently carry the flag. So the code and
the re-rendered unit must land in one operation; deploying the code alone would refuse every
forwarded request.

Other preconditions I confirmed present on this host: tailscaled running as pid 1655 with `comm`
exactly `tailscaled`, its 26 fds readable by root, `/proc/net/tcp` readable, and `tailscale serve`
proxying the tailnet HTTPS name to `127.0.0.1:8000`.

---

## F-07

**Severity:** MATERIAL

**What it found**

STILL PRESENT in part. GapLedger.repair now runs at install(), creates a 0600 O_EXCL copy and fsyncs its file before saving a changed record; a copy failure leaves the original untouched. But _sanitise leaves arbitrary reportable legacy row fields untouched. In particular, a misjudged row's own capability overrides the cleaned key in report's {"capability": k, **v}; unknown customer names can likewise survive after restart. _merge truncates links and seen history, build-gap remapping does not validate surviving links, and the backup's parent directory is not fsynced. The rollback test checks json.loads of the backup, not whether the actual 3e77 reader can read the rewritten live file. That required rollback property cannot be verified from the supplied evidence.

**Evidence it cites**

`DIFF — app/objectives/gaps.py (_repair_locked, _keep_original, _sanitise, _merge); app/objectives/gaps.py (report); tests/test_capability_gaps.py (test_the_record_on_disk_is_cleaned_at_startup_and_the_original_kept_first); REVIEW PACKET — F-07`

**Required repair**

Sanitize or strictly reconstruct every reportable legacy field, including misjudged capability; validate remapped build links and collision accounting. Make the private original durable, and run a rollback compatibility test using the actual 3e77 reader against the cleaned file, with a documented restoration procedure for the original.

**Verification note (mine, not the reviewer's)**

Confirmed, and the specific override is real.

`report()` builds its misjudged rows as `[{"capability": k, **v} for k, v in ...]`. Because `**v`
is expanded after the literal key, a legacy row that itself carries a `capability` field
**overrides the cleaned key**. That is exactly the round-5 complaint surviving into this SHA.

I credit the repaired part: `repair()` does now run from `install()`, and the backup is made with
`O_EXCL` at 0600 and fsynced before any save, with a failed copy leaving the original untouched.

The rollback criterion is the one I would not sign off on. The test checks `json.loads` of the
backup, not that the `3e77f215` reader — the actual rollback target — can read the rewritten live
file. Nothing in this deploy demonstrates that property, and the rewrite would run against the
real record: `/var/lib/crooks-assistant/objectives/gaps.json`, 0600, 4663 bytes, 8 gap keys, 0
builds, 0 misjudged. I recorded SHA-256 prefixes of those 8 keys before any deploy so a future
clean can be checked by count and hash without reading contents.

---

## F-10

**Severity:** MATERIAL

**What it found**

STILL PRESENT in the stop report, although the named dequeue window is repaired. Timeline._pending remains counted while the writer holds a batch; the Condition loop waits under its lock without an evident lost wakeup, and counts reads the file outside that lock. Timeline.stop nevertheless ignores its timed flush result, and the supplied scripts/test_session.py change updates cmd_status but not cmd_stop. Thus the round-5 stop path is not shown to disclose a pending batch or possible later drops before presenting its file count as final. The claim that the file read is locked is inaccurate; counts instead compares snapshots on either side.

**Evidence it cites**

`DIFF — app/observability/timeline.py (_run, flush, counts); scripts/test_session.py (cmd_status-only count change); REVIEW PACKET — F-10`

**Required repair**

Have stop propagate whether flush settled, and make cmd_stop explicitly distinguish the current on-disk count from a final total whenever pending work remains or the flush timed out; test that presentation with a held writer.

**Verification note (mine, not the reviewer's)**

Confirmed, including that the round-5 window really is closed.

The dequeue window the round-5 review named is repaired. The stop path is not: `cmd_stop` in
`scripts/test_session.py` is untouched in this range and still prints
`"{written} events in {path}"` with no mention of pending work, and `Timeline.stop` calls
`self.flush()` and **discards the returned boolean**. So a timed-out flush is invisible and a file
count is still presented as a final total.

I did not test the Condition for a lost wakeup; the reviewer reports none is evident, and also
corrects PR #46's claim that `counts` reads the file under the lock — it compares snapshots on
either side instead.

---

## F-NEW-PAD

**Severity:** MATERIAL

**What it found**

A separate live observe door remains open to callers the write gate refuses. app/routes/pad.py heartbeat has no principal check: a headerless host process admitted by app/main.py can submit registry.record events and receive the recording state and pad status. GET /pad likewise accepts that process through made_on_this_server. Gating app/routes/observe.py does not protect these paths.

**Evidence it cites**

`app/routes/pad.py (heartbeat, pad, _local); app/main.py (guard_and_freshness); app/routes/actions.py (made_on_this_server, caller_check)`

**Required repair**

Apply an appropriate authenticated owner or device policy to pad telemetry and sensitive status; test headerless host callers with the production write-gate settings.

**Verification note (mine, not the reviewer's)**

Confirmed. A second observe door, missed because the repair was scoped to one
router.

In `app/routes/pad.py`, `POST /pad/heartbeat` (line 68) has no authorisation check of any kind.
Only `GET /pad` checks, at line 129, and it calls `_local`, which delegates to
`made_on_this_server` — a function that *admits* callers on the server. So gating `observe.py` did
not cover pad telemetry, and a headerless host process can still submit `registry.record` events
and read pad status.

---

## F-NEW-TOOLS

**Severity:** MATERIAL

**What it found**

The router dependencies do not establish the required authorization of in-process owner-data tools. app/main.py still admits headerless local requests to /turn, while runtime imports engineering_tools and display_tools and the prompt invites objective, engineering and screen tool calls. The supplied packet contains neither the /turn-to-dispatch authorization nor evidence that these tools apply principal_check. Consequently it cannot establish that someone refused by the write gate cannot reach objective, display or engineering data through a turn, irrespective of the protected HTTP routers.

**Evidence it cites**

`app/main.py (guard_and_freshness, include_router(turn.router)); DIFF — app/runtime.py (build tool imports), app/routes/objectives.py (router-only dependency); app/kb/loader.py (objective, engineering and screen tool guidance); REVIEW PACKET — PART A exclusions`

**Required repair**

Supply and test the /turn and tool-dispatch authorization path, and enforce the same owner boundary on every tool exposing these records, not only its HTTP router. Review display tools and routes in Part B before clearing the deploy.

**Verification note (mine, not the reviewer's)**

Confirmed as an evidence gap, and both reviewers reached it independently.

`app/main.py` registers `turn.router` and still admits headerless local requests to `/turn`, while
`runtime.build` imports `engineering_tools` and `display_tools` and the prompt invites objective,
engineering and screen tool calls. The authorisation applied in this range is at the **router**
level (`objectives.py` and `displays.py` take `Depends(require_principal)`), which does not reach a
tool invoked *through a turn*.

I did not trace the `/turn`-to-dispatch path myself, so I cannot say whether a caller the write
gate refuses can in fact reach objective, display or engineering records that way. That is the
point: neither can the reviewer, from what exists. Part B's B-01 is the same defect seen from the
screens side.

---

## F-ENG

**Severity:** not material

**What it found**

DEFERRED, not cleared. With the credential locations and rendered three-credential unit described in Change A, github.read_token has no identified token and EngineeringInbox._token prevents its GitHub calls; the supplied bridge code shows no other outbound GitHub call route. Its PROTECTED_PATHS refusal is active for requests it prepares. The loop's older pinned door can still accept a separately filed objective naming the newly protected paths until the owner re-pins it: bridge-side refusal protects only requests through this bridge, and parking its token prevents those filings for this deploy. Tests asserting that a PR and owner merge prevent production reach overstate the evidence: clive/trunk is unprotected and green CI supplies zero review assurance.

**Evidence it cites**

`REVIEW PACKET — CHANGES A, B and D; app/engineering_bridge/github.py (read_token, EngineeringInbox._token); app/engineering_bridge/requests.py (_paths); DIFF — app/orchestrator/objectives.py (PROTECTED_PATHS); tests/test_engineering_bridge_bounds.py`

**Required repair**

Keep the credential parked for this deploy. Before enabling the bridge, separately review its production bounds, owner-gated re-pin of the loop door, and the actual route by which work may reach unprotected trunk.

**Verification note (mine, not the reviewer's)**

Confirmed deferred, and the parking is what makes it so. I verified each precondition.

- `/etc/crooks-os/credentials/` holds exactly three `.cred` files: `elevenlabs_api_key`,
  `shopify_client_id`, `shopify_client_secret`.
- `github_engineering_inbox_token.cred` was **moved** to `/etc/crooks-os/credentials-parked/`
  (directory 0700) intact — 292 bytes, mode 0600, original mtime preserved. It was never opened,
  read or decrypted, and it stays parked.
- `/etc/crooks-os/secrets/` — the read-write tier that `app/secrets/linux_store.py` consults
  *after* the systemd credentials — holds only `gmail_token` and `media_signing_key`. I checked by
  name that the engineering token is not there, so there is no second copy that would make the
  bridge live regardless of the unit.
- The unit re-rendered at `9a79dc12` after the move carries `LoadCredentialEncrypted` lines
  identical to the three installed ones.

The reviewer's last sentence deserves the Director's attention: tests asserting that a PR and an
owner merge prevent production reach **overstate the evidence**, because `clive/trunk` has no
protection at all. That claim should be corrected in PR #46 rather than carried forward.

---

# Part B — the screens feature (PR #45)

**Verdict: CHANGES_REQUIRED**

> Part B is not ready. The direct screen API applies `principal_check`, whose production Tailscale verification depends on the re-rendered `--no-proxy-headers` unit; deploying code without that unit risks denying legitimate screens. The front end uses text nodes rather than server-supplied markup, and the added shell entries are static assets, but the defects above remain. `clive/trunk` is unprotected: its presence there and green CI carry no review weight. This decision covers the supplied screens-feature Part B, not a ruling on Part A's seven findings or the deferred engineering bridge.
> 
> [model gpt-6-sol, effort high, usage {"input_tokens": 152398, "input_tokens_details": {"cache_write_tokens": 152395, "cached_tokens": 0}, "output_tokens": 8182, "output_tokens_details": {"reasoning_tokens": 6720}, "total_tokens": 160580}]

## B-01

**Severity:** MATERIAL

**What it found**

The `/displays` routes correctly use `require_principal`, but the model-facing `screen_list` and `screen_show` handlers do not check a request principal. The supplied middleware permits direct local requests to `/turn`, although production's write gate refuses local callers. The packet does not show a turn/dispatch check that would prevent such a caller from invoking these tools. Thus the required authorization of the tool surface cannot be verified.

**Evidence it cites**

`Supplementary app/main.py, guard_and_freshness and router list; DIFF app/routes/displays.py router dependency and app/tools/display_tools.py screen_list/screen_show`

**Required repair**

Enforce the same verified principal rule at the model-tool boundary, including locally initiated turns, and supply end-to-end tests that a caller refused by the write gate cannot list or change screens.

**Verification note (mine, not the reviewer's)**

Same defect as Part A's F-NEW-TOOLS, seen from the screens side; two reviewers reached
it independently, which is worth weighing.

I confirmed the router half: `app/routes/displays.py` does take the router-level
`Depends(require_principal)`. What I cannot confirm — and neither could the reviewer — is the tool
half: `screen_list` and `screen_show` in `app/tools/display_tools.py` are reachable through a
turn, and `/turn` still admits headerless local callers while production's write gate refuses
them. The authorisation boundary is on the HTTP router, not on the tool.

---

## B-02

**Severity:** MATERIAL

**What it found**

A caller's screen name is treated as an existing screen's identity: `DisplayStore.register` returns the existing ID for a matching name. Moreover, any principal allowed to call `/displays` can list every ID, poll its full contents and post `done` for it. There is no binding between a registered physical device and the screen whose customer address it displays or whose packing it attests.

**Evidence it cites**

`DIFF app/displays/store.py, DisplayStore.register/poll/mark_done; app/routes/displays.py, screens/poll/done`

**Required repair**

Give each physical screen an unguessable registration credential, require it for that screen's poll and done operations, and do not transfer an existing registration merely because another device supplies its name. Test same-name registration and cross-screen reads and done posts.

**Verification note (mine, not the reviewer's)**

Confirmed by reading `DisplayStore.register`.

The function computes `key = name_key(clean_name(name))`, walks existing screens, and on a match
does `self._touch(screen["id"]); return dict(screen)` — handing back the **existing screen's id**
with no credential of any kind. Its own docstring states the intent: "The same name again is the
same screen." So any caller who supplies a matching name becomes that screen, and can then poll
its contents and post `done` for it. There is nothing binding a physical device to the screen
whose customer address it shows.

---

## B-03

**Severity:** MATERIAL

**What it found**

`displays.json` persists the current order slip—including customer name, shipping address, phone and note—under the objectives directory. `_save` creates a 0600 file in a 0700 directory, but neither marking the order done nor the browser's 45-second display timeout removes the slip from that file. The 20-screen and 500-done limits do not impose an age or serialized-byte limit; address lines and some copied order fields are also unbounded. Privileged host processes can read this indefinitely retained customer data.

**Evidence it cites**

`DIFF app/displays/store.py, _save/show/mark_done; app/displays/views.py, order_view; web/display.js, wanted and DONE_HOLD_MS`

**Required repair**

Set and enforce expiry for displayed personal data and done history, clear expired slips on disk independently of browser activity, bound every serialized field and total file size, and test restart and ageing with a real order slip.

**Verification note (mine, not the reviewer's)**

Confirmed, and this is the finding with live customer-data consequences.

`mark_done` sets `showing["done_at"]`, appends a `done` row and calls `_save()` — but it never
removes `showing`. The slip therefore stays in `displays.json`. `order_view` puts real personal
data in that slip: `customer` (address name or `customer_name`), `company`, `address` (the address
lines, city, province, zip, country), `phone`, and `note` up to 600 characters.

So marking an order packed does not clear the customer's name, address and phone from disk, and
neither does the browser's display timeout, which touches only the page. The file is 0600 in a
0700 directory, which bounds who can read it but not how long it is kept; the reviewer is right
that the 20-screen and 500-done caps impose no age or byte limit.

Note this is latent in the deploy we refused rather than live today: the feature is new and
`displays.json` does not yet exist on this host.

---

## B-04

**Severity:** MATERIAL

**What it found**

An order with more than six items in portrait or twelve in landscape displays only that many rows, yet retains an enabled “Mark packed” button. `DisplayStore.mark_done` then records the entire order as done. An owner can therefore attest that an order was packed without seeing all its items; `order_view` also truncates the slip at 60 items.

**Evidence it cites**

`DIFF web/display.js, renderOrder (`max`, `items.slice`, actionFoot); app/displays/views.py, order_view; app/displays/store.py, mark_done`

**Required repair**

Make all items to pack accessible and require an explicit complete-order confirmation before recording the order as packed; otherwise record only the portion shown. Test orders exceeding each display limit and 60 items.

**Verification note (mine, not the reviewer's)**

Confirmed by reading `renderOrder` in `web/display.js`.

Line 300 sets `const max = L.portrait ? 6 : 12`; line 303 iterates `items.slice(0, max)`; line 336
appends a `cs-more` note reading "+ N more on the order. Ask CLIVE for the rest." — and line 343
still appends `actionFoot(..., 'Mark packed')` unconditionally. `DisplayStore.mark_done` then
records the whole order as done.

So the count is disclosed but the attestation is not scoped: an owner can certify an order packed
having seen six of its items. `order_view` also truncates at 60 items, so beyond that the
remainder is not reachable from the screen at all.

---

## B-05

**Severity:** MATERIAL

**What it found**

The model-facing `screen_show` accepts any existing `objective_id` without the issued-ID restriction tested for `order_id`; it can put that objective on any screen matched by a caller-supplied name. Its `lines` schema has no item-count or string-length limits, and `list_view` processes the entire supplied array before retaining 40 lines. No arbitrary filesystem path is accepted by these functions, but objective selection, destination and input work are not adequately bounded.

**Evidence it cites**

`DIFF app/tools/display_tools.py, screen_show schema and objective_id branch; app/displays/views.py, list_view; tests/test_displays.py, test_the_gate_lets_a_slip_through_only_for_an_order_this_conversation_looked_up`

**Required repair**

Constrain objective IDs to records authorized for the conversation, require an explicit safe destination for sensitive objectives, and validate array count and element lengths before processing. Add adversarial tool-dispatch tests.

**Verification note (mine, not the reviewer's)**

Confirmed by reading the tool definition.

`screen_show` declares `issued_id_args=("order_id",)` — so `order_id` is restricted to ids this
conversation actually looked up, but `objective_id` is **not** in that tuple and gets no such
restriction. Any existing objective can therefore be put on any screen matched by a
caller-supplied name, which compounds B-02.

The bounds claim also holds: `title` has `maxLength: 120`, but `lines` is declared
`{"type": "array", "items": {"type": "string"}}` with no `maxItems` and no per-item `maxLength`.
`list_view` processes the whole array before keeping 40 lines.

---

## B-06

**Severity:** MATERIAL

**What it found**

Startup can permanently cover the main app if initialization throws. `startup.js` adds `is-live` before constructing the canvas engine, which can fail, and installs its 20-second `finish` timer only later. `startup.css` disables its 12-second give-way animation for `is-live`, leaving an opaque, input-blocking overlay with neither escape path. The script itself sends no customer data; this is a startup availability defect.

**Evidence it cites**

`DIFF web/startup.js, is-live/CliveDots.create/setTimeout(finish, 20000); web/startup.css, .startup and .startup.is-live`

**Required repair**

Keep an independent CSS or pre-initialization timeout escape, remove the overlay on initialization errors, and test a missing or failing Canvas 2D context.

**Verification note (mine, not the reviewer's)**

Confirmed by reading `web/startup.js` and `startup.css`.

Line 46 adds `is-live` to the overlay root; the canvas engine is constructed afterwards at line 60
(`window.CliveDots.create`); and the 20-second escape timer is not installed until line 212. Line
19 does guard the *absent* case (`if (!window.CliveDots) { root.remove(); return; }`), but a throw
inside `create()` — a missing or failing 2D context — happens after `is-live` is set and before
the timer exists. `startup.css` disables the give-way animation for `is-live`, so what remains is
an opaque, input-blocking overlay with no escape path.

This is an availability defect on the owner's own app, not a data one; the reviewer says the script
sends nothing sensitive and I saw nothing to contradict that.

---

## B-07

**Severity:** MATERIAL

**What it found**

The supplied `sw.js` evidence shows only three static assets added to `SHELL`, not the worker's install, cache-key or fetch handling. Those added assets contain no order data themselves, and `/display` is not among the shown additions, but the requested assurance that the worker cannot serve stale or cross-owner content cannot be established from this hunk.

**Evidence it cites**

`Packet section ‘DIFF ... web/sw.js’ (SHELL hunk only); CANDIDATE FILES web/sw.js omitted`

**Required repair**

Supply the complete worker at this SHA and tests covering build changes, `/display` and `/displays` fetches, offline responses, and a change of authorized login on the same browser.

**Verification note (mine, not the reviewer's)**

Confirmed as an evidence gap rather than a defect, and the gap is mine to own.

The Part B packet carried only the `SHELL` hunk of `web/sw.js` — three static assets added
(`dots.js`, `startup.js`, `startup.css`) — because I excluded the large web files from the diff to
keep the request inside the reviewer's file budget. The worker's `install`, cache-key and `fetch`
handling were therefore never supplied, so the assurance the packet asked for could not be given.

What the reviewer could establish: the added entries are static assets containing no order data,
and `/display` is not among them. A future packet should carry the complete worker at the
candidate SHA.

---

## What I verified, and what I did not

Every claim I checked held. Independently confirmed: the `comm` bypass and the inode-cache
short-circuit (F-05B), the `{"capability": k, **v}` override (F-07), `cmd_stop` unchanged and
`Timeline.stop` discarding its flush result (F-10), the unguarded `POST /pad/heartbeat`
(F-NEW-PAD), `register` returning an existing screen on a name match (B-02), `mark_done` leaving
the customer slip on disk (B-03), the truncated item list with an enabled *Mark packed* button
(B-04), `objective_id` outside `issued_id_args` and `lines` unbounded (B-05), and the `is-live`
ordering in `startup.js` (B-06). I also confirmed the genuinely repaired parts: F-02's two
demonstrated examples, F-04's startup pass, F-05A's six gated observe routes, and the shared
fail-closed `proxy_state`.

Not independently verified: the `/turn`-to-dispatch authorisation path (F-NEW-TOOLS, B-01) — that
is the evidence gap itself; F-02's uninspected-`src` and metadata-key residuals; and the timeline
Condition's wakeup behaviour.

For F-05B I verified the two mechanisms only. No bypass request was sent to the live service.

## Artefacts

Held on the deploy host under `/root/clive-activation/round-6/`, not committed here: both
`.review.json` verdicts, both dispatch packets and job files, the unit diff and rendered unit, the
installed-unit copy, the `LoadCredentialEncrypted` comparison, the credential before/after/parked
listings, the pre-deploy baseline, the branch-protection and acceptance records, and SHA-256
prefixes of the eight existing `gaps.json` keys (hashes only, so a future clean can be checked by
count and hash without reading contents).

