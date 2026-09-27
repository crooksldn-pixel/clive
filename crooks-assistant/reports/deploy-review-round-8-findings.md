# Deploy review, round 8 — findings for the Director

**Candidate reviewed:** `6a29e31013b0b9e543d90434e14ed65deea1ce30` — `clive/trunk` head, PR #50's merge commit.
**Its code:** `aeda0dd8cecef5fa89f6ad06313ed857bb3430d9` (PR #49's merge commit). PR #50 changed four documentation files and no code.
**Currently deployed:** `3e77f2157a35a23ba69014c1b0161a9351accd48` (PR #42), unchanged.
**Previous review:** round 7 of `1d7a934a` — all four parts CHANGES_REQUIRED, 19 material findings, published at `5b6e67bb`. PR #49 claimed to close all 19.

**Outcome: all four parts returned CHANGES_REQUIRED. Nothing was deployed.** No `.env` line, no
service file, no systemd state and no checkout changed. The service is still running its original
process — same `MainPID` 2135565, same `ActiveEnterTimestamp` of 01:07:04 UTC, `NRestarts=0`.
`CROOKS_SCREEN_SNAPSHOTS` stayed `false`, `CROOKS_LOCAL_OWNER` unset, `CROOKS_WRITES_LOCAL_OWNER`
`false`, `CROOKS_ENGINEERING_HOST` unset, `CROOKS_TAILSCALE_VERIFY` unset, and the engineering
credential stayed parked and unopened.

**The owner was not called.** Because the gate never opened, neither phone check ran: no staging
copy was started, no second HTTPS port was published, and `tailscale serve` was never touched.

| Part | Scope | Verdict | Findings |
|---|---|---|---|
| A1 | proxy identity, the access boundary, the local CLI | **CHANGES_REQUIRED** | 4 (4 material) |
| A2 | the tool boundary and the pad routes | **CHANGES_REQUIRED** | 4 (3 material) |
| A3 | the gap record, report handling, observability accounting | **CHANGES_REQUIRED** | 7 (7 material) |
| B | the screens feature | **CHANGES_REQUIRED** | 9 (7 material) |

**24 findings, 21 material.** Three of round 7's findings closed: **F-NEW-TOOLS-PATH** is repaired,
and **B-06** and **B-07** show no regression. Three findings are new: **F-A2-FIXTURE**,
**NEW-B-CAP** and **NEW-B-LOCAL-SLIP**.

This is the sixth consecutive round in which F-04, F-05 and F-07 have come back partly repaired.
Real work landed in PR #49 — the list of genuine repairs below is the longest of any round — but in
every case a narrower version of the same defect survived, and two of the three new findings are
defects that PR #49 introduced while repairing something else.

## Read this first

Three findings are more urgent than their ordering suggests.

**A2/F-A2-FIXTURE means the test suite is not measuring the system being deployed.**
`tests/conftest.py` is a protected file and was changed by hand. Its new autouse fixture is:

```python
@pytest.fixture(autouse=True)
def _the_owner_is_asking(request):
    if request.node.get_closest_marker("live"):
        yield
        return
    from app.tools import authority
    token = authority.TOOL_AUTHORITY.set(authority.for_owner("owner@example.com"))
    yield
    authority.TOOL_AUTHORITY.reset(token)
```

Every offline test now runs with a full owner authority already stamped. Production's default is
`None`. So the default condition the whole F-NEW-TOOLS repair exists to establish — that absent
authority refuses — is switched off for the entire suite, and there is no ordinary opt-out; a test
must override with `acting_as(None)`. The reviewer names the specific tests in
`tests/test_provider.py` that would no longer reach their asserted behaviour without the grant. The
boundary tests themselves do use the door or `acting_as(None)` and are sound, but part of the suite
has been made to pass by widening the default it is meant to assess. I read this one straight out of
the file and confirmed it.

**A3/F-04-REPORT-LOSS is still a destructive action at start-up, in a new form.** The
`float("inf")` fallback round 7 put in front of the Director is genuinely gone, and a report that
cannot be moved is now never deleted whatever its age. But `_remove_if_older` still decides a report
*directory's* expiry from the directory's own mtime and then deletes everything inside it:

```python
if path.stat().st_mtime >= cutoff: return 0
if path.is_dir(): shutil.rmtree(path, ignore_errors=True)
```

An old `ts-…-screens/` directory holding a freshly modified, non-expired report is removed whole, at
start-up, before permission checks. Separately, withheld paths are given UUID prefixes while the
pruning pass selects only `ts-*`, so withheld reports never expire at all. Confirmed by reading.

**B/NEW-B-CAP silently destroys a live customer slip.** At `MAX_SCREENS = 20`, registering a new
screen name runs:

```python
if len(self._data["screens"]) >= MAX_SCREENS:
    oldest = min(self._data["screens"].values(), key=lambda s: s.get("last_seen") or "")
    del self._data["screens"][oldest["id"]]
```

The evicted screen's key and whatever it was `showing` — a customer's name, address, phone, note and
items — go with it, with no owner confirmation. This bypasses the explicit owner `/forget` recovery
that PR #49 added for exactly this purpose, and it frees the evicted screen's name for another
device to claim, which re-opens B-02 and B-05 through a different door. Round 7 never named this;
it is new, and it has its own test asserting the behaviour is intended
(`test_the_oldest_screen_makes_way_when_there_are_too_many`). Confirmed by reading.

## What PR #49 did close

Credit where the code earns it. These are repairs I or a reviewer confirmed at this SHA:

- **F-NEW-TOOLS-PATH — repaired.** With `app/routes/turn.py`, `app/providers/max_agent_sdk.py` and
  `app/tools/registry.py` finally in the packet, A2 traced the real path: `POST /turn` → provider
  `_options` → `registry.build_mcp_server` callbacks → provider `_dispatch`, which checks the
  conversation's active authority and installs it around a fail-closed `dispatch` before any handler
  runs. The `PreToolUse` hook is now redundant rather than load-bearing, so a missing or permissive
  hook does not bypass the check. This was my evidence gap from round 7 and it is closed.
- **The fail-open tool default — repaired.** `TOOL_AUTHORITY` now defaults to `None` and `dispatch`
  refuses when `current()` is `None`. The `is False` guard is gone. The door revokes its owner
  authority after the response, so a detached task is refused.
- **The 600-second own-address cache — gone.** `local_addresses` reads `/proc/net/fib_trie` and
  `/proc/net/if_inet6` fresh on every request, with no positive set remembered and no `tailscale ip`
  subprocess. An address the host gains is in on the very next request.
- **The pidfd — added, and correctly ordered.** A1 confirms the pidfd is opened *before* the cgroup,
  executable and fd reads and checked for exit afterwards, that the executable is attested against
  an approved path rather than a basename, and that the root-only cgroup check matches this host.
- **Screen-name takeover after a restart — repaired.** `register` now requires the existing key;
  `_seen` no longer decides ownership, so neither a restart nor a stale flag transfers a name. An
  owner-principal `/forget` clears the record, credential and showing before reuse.
- **Fail-closed start-up on exposed reports — added.** When `tidy_reports` sets
  `tidy_contained=False`, `lifespan` raises before serving and uvicorn fails to start. Traversal
  errors are now distinguishable from an empty directory.
- **Pre-replacement fsync failures — now propagate.** In `gaps.py` a failed backup-directory fsync
  raises before replacement, retries recognise a byte-identical private existing backup instead of
  proliferating them, and the successful path makes exactly one.
- **The runtime-close overlap — repaired.** `lifespan` consumes `Housekeeper.stop`'s result and does
  not call `runtime.aclose()` while a pass holds the lock.
- **The pad and observability blocks — withheld, without cache poisoning.** `_guarded` removes both
  on every `/health` return path including both cached branches, and they are added after the shared
  result is cached, so neither caller's version is ever served to the other.
- **The issued-ID gate — enforced.** `_ID_KIND` checks the `obj_` kind and membership in the
  session's issued IDs, which `dispatch` populates from tool results via `_harvest_ids`. A
  model-supplied string alone does not satisfy it.
- **`done` row privacy — improved.** `done_summary` replaces list and objective titles with their
  kind and keeps only patterned order or objective references. `_write` now fsyncs the parent, and
  pre-replace failures roll back and surface as 503.
- **Housekeeping wiring — supplied and verified.** `lifespan` runs a first pass and starts
  `Housekeeper`, whose 15-minute passes call `displays().sweep()` even with no screen registered,
  and the timer restarts after an unexpected end. This closes round 7's B-03 evidence gap.
- **B-06 and B-07 — no regression.** The worker's shell list still excludes `/display`, the screen
  assets and `/displays/*`; the changed display page's `/static/display.js` and `/static/display.css`
  were not added to the shell, and its new `/seen` and `/forget` POSTs are not intercepted.

## Standing facts, unchanged

**`clive/trunk` has no branch protection.** Re-checked at this preflight:
`GET /branches/clive%2Ftrunk` returns `"protected": false`. Branch protection and rulesets both
return HTTP 403 on this plan. A SHA's position on trunk and a green acceptance run carry zero review
weight, and refused SHAs have landed on this branch before. All four reviewers were told this.

**The engineering bridge stayed out of this deploy.**
`github_engineering_inbox_token.cred` remained parked in `/etc/crooks-os/credentials-parked/` —
directory 0700, file 0600, 292 bytes, uid 0, original mtime — and was never opened or decrypted.
`/etc/crooks-os/credentials/` held exactly three `.cred` files; `/etc/crooks-os/secrets/` held only
`gmail_token` and `media_signing_key`, so there is no second copy that would make the bridge live.
The unit rendered at the candidate carries `LoadCredentialEncrypted` lines byte-identical to the
three installed ones. F-ENG stays deferred and was not gated on.

## How this review was run

The same four-part split as round 7, for the same reason: the reviewer harness appends full files
for whatever appears in the packet's diff, in packet order, against a 300 KB budget, and silently
replaces the rest with `omitted` lines. The budget was simulated per packet before sending, and
every packet was leak-checked against every production secret value.

**Auto-supplied bytes per part: A1 154,593; A2 227,304; A3 224,965; B 237,186 — zero omissions in
all four.** Packet sizes: A1 145,119; A2 246,344; A3 172,618; B 250,073 bytes.

**Eleven files unchanged in the range were supplied explicitly**, because the harness would never
have supplied them. This is what closed round 7's two evidence gaps:

- A1: `deploy/systemd/crooks-assistant.service`, `scripts/install_systemd.py`
- A2: `app/routes/turn.py` (89 KB), `app/tools/registry.py`, `app/routes/pad.py`
- A3: `tests/rollback/gaps_3e77f215.py`
- B: `app/tools/display_tools.py`, `app/tools/gate.py`, `web/sw.js`, `web/startup.css`,
  `tests/web/sw.test.js`

A2 fitted without the A2a/A2b split: its auto-file total of 227,304 bytes is inside the budget even
with `turn.py` supplied in full as packet text.

Each reviewer was `gpt-6-sol` at high effort, told it was one of four parts and not to approve what
it could not see, and given the full round-7 findings document and the full PR #49 body as a claim
sheet to check rather than trust. The four documentation files PR #50 changed went to no part;
preflight 1.1 verified them instead.

**One correction was carried into A1.** Round 7's F-05B-AVAIL-PREFLIGHT asked for
"`app/routes/environment.py`'s `/whoami` implementation". That was wrong: `/whoami` is in
`app/routes/admin.py` and `environment.py` contains no `/whoami`. A1 was told so and given the real
file, and ruled on the actual implementation.

## Preflight, all read-only, all passed

**1.1 SHA provenance.**
- `6a29e310` is `origin/clive/trunk`'s head and PR #50's merge commit (`merge_commit_sha` confirmed
  via the API; `merged: true`, base `clive/trunk`).
- `git diff --name-only aeda0dd8 6a29e310` lists **exactly four files**: `README.md`,
  `crooks-assistant/deploy/env.production.example`, `crooks-assistant/docs/DEPLOY_LINUX.md`,
  `crooks-assistant/docs/product-memory/CURRENT_TRUTH.md`. 124 insertions, 11 deletions, no code.
- `aeda0dd8^{tree}` = `9e6f75c8^{tree}` = `6e0c98b885ff5351976a30fc175d9c5c32d90bca`. **Byte-identical.**
- `1d7a934a` and `3e77f215` are both ancestors of the candidate. So are `aeda0dd8` and `9e6f75c8`.
- The range `1d7a934a..6a29e310` is 36 files, 2348 insertions, 448 deletions, in four commits.
- Acceptance run **36340233782** on exactly `6a29e310`: `completed` / `success`, `head_sha` matches,
  `event=push` on `clive/trunk`. The other five runs named in the request were all
  completed/success with matching head SHAs.

**1.2 Switches.** `CROOKS_SCREEN_SNAPSHOTS=false`; `CROOKS_LOCAL_OWNER` unset;
`CROOKS_WRITES_LOCAL_OWNER=false`; `CROOKS_ENGINEERING_HOST` unset; `CROOKS_TAILSCALE_VERIFY` unset
(code default true); `CROOKS_ALLOWED_LOGINS` non-empty. 40 keys, no duplicates. No value printed.

**1.3 Unit.** Rendered at the candidate with `install_systemd.py --print`, which returns before any
Linux or install path, then normalised from the review checkout's path to `/opt/crooks-os`. The diff
against the installed unit is **exactly the three differences rounds 6 and 7 accepted**:
`--no-proxy-headers` with its two comment lines, the `/opt/crooks-os/crooks-assistant/.venv/bin`
PATH entry, and one trailing blank line. `LoadCredentialEncrypted` lines identical. No `User=`, no
sandboxing change, no `ReadWritePaths` change, no `Restart=` change.

**1.4 Tailscale.** All pass.
- `systemctl show -p MainPID --value tailscaled` → 1655; `readlink /proc/1655/exe` →
  `/usr/sbin/tailscaled` exactly; `/proc/1655/cgroup` → `0::/system.slice/tailscaled.service` exactly.
- `stat -c '%u %a %n'`: `0 755 /usr/sbin/tailscaled`,
  `0 755 /sys/fs/cgroup/system.slice/tailscaled.service`,
  `0 644 /sys/fs/cgroup/system.slice/tailscaled.service/cgroup.procs`. All uid 0, no group-write, no
  other-write.
- `/opt/crooks-os/crooks-assistant/.venv/bin/python` is CPython 3.12.3 and
  `os.close(os.pidfd_open(1))` succeeds.
- `tailscale ip -4` → `100.72.82.24`, present in `/proc/net/fib_trie` as `/32 host LOCAL`.
  IPv6 is enabled (`disable_ipv6=0`); `tailscale ip -6` → `fd7a:115c:a1e0::352b:5219`, present in
  `/proc/net/if_inet6` as `fd7a115ca1e0000000000000352b5219 03 80 00 80 tailscale0`.

**1.5 Reports.** `CROOKS_REPORTS_DIR` is not set, so the production reports_dir is
`/opt/crooks-os/crooks-assistant/reports`. **`find <dir> -perm /077 | wc -l` = 2** — the directory
itself at 0755 and `.gitkeep` at 0644. No `.withheld/`. Both are root-owned and ordinarily
chmod-fixable, so the first pass would have tightened two paths and withheld none. Nothing was
changed. A2's F-04-STARTUP ruling notes that changing `.gitkeep` from 0644 to 0600 alters no
Git-tracked executable bit, so it need not appear in `git status`, and a checkout that rematerialises
it can restore its original permissions.

**1.6 Gap record.** `tests/rollback/gaps_3e77f215.py` from line 6 onward is **byte-identical** to
`git show 3e77f215:crooks-assistant/app/objectives/gaps.py` — both sha256
`b6bfba90973a1647659e4d3e24e61a006d8aaffbb03e52236ddc992c9f24c26f`, 16,831 bytes.
`/var/lib/crooks-assistant/objectives/gaps.json` **exists: 4,663 bytes**, mode 0600, uid 0, mtime
2026-09-27 01:07:06 UTC, sha256 `90591f14…`. Its keys: `version=1`, `gaps` (8 entries), `builds`
(empty), `misjudged` (empty), `seeded="2026-09-27T01:07:06+00:00"`. Unchanged after the review.

# Part A1 — proxy identity, the access boundary, the local CLI

**Verdict: CHANGES_REQUIRED** — model `gpt-6-sol`, effort high.

> A1 is not ready. F-05A is partially repaired; F-05B retains an unverified malformed-row failure path; F-05B-AVAIL remains unsafe on incomplete kernel tables and does not establish availability on lookup failure; F-05B-AVAIL-PREFLIGHT lacks the required executable and real-device evidence. The other review parts and deferred F-ENG are not judged here.
> 
> [model gpt-6-sol, effort high, usage {"input_tokens": 75043, "input_tokens_details": {"cache_write_tokens": 75040, "cached_tokens": 0}, "output_tokens": 6841, "output_tokens_details": {"reasoning_tokens": 5538}, "total_tokens": 81884}]

## A1 · F-05A

**Severity:** MATERIAL

**What it found**

STILL PRESENT in the presence rule and required test. The door refuses a verified proxied owner carrying a nonempty key, and admits that owner without it; neither principal_verdict nor caller_check reads the key. But local_cli.presented treats an empty X-Crooks-Local-Key header as absent, so refusal depends on the header’s value rather than its presence. The claimed verified-device test substitutes mocked peer, locality and whois answers, rather than exercising a genuinely verified owner-device request.

**Evidence it cites**

`crooks-assistant/app/local_cli.py:presented, admits; crooks-assistant/app/main.py:guard_and_freshness; crooks-assistant/app/routes/actions.py:principal_verdict, caller_check; crooks-assistant/tests/test_local_cli.py:test_a_verified_owner_device_carrying_the_key_is_refused_and_without_it_is_admitted`

**Required repair**

Detect header presence, including an empty value, and refuse it wherever the key does not apply. Test correct, wrong and empty keys through the proxy on all three CLI routes; supply a real verified owner-device check carrying the correct key, while confirming the same device is admitted without it.

**Verification note (mine, not the reviewer's)**

Confirmed, and the residual is narrower than round 7's but real. The substance round 7
asked for is done: a verified proxied owner carrying a non-empty key is now refused, the same owner
without it is admitted, and neither `principal_verdict` nor `caller_check` reads the key. What
survives is a presence-versus-value distinction — `local_cli.presented` treats an empty
`X-Crooks-Local-Key:` header as absent, so a caller who sends the header with no value is not
refused where the key does not apply. I did not construct that request. The reviewer also notes the
new "verified owner device" test substitutes mocked peer, locality and whois answers, so the
genuinely-verified-device requirement is still met by a mock rather than a device. That half is what
my step-3 staging phone check was built to answer, and it did not run.

---

## A1 · F-05B

**Severity:** MATERIAL

**What it found**

STILL PRESENT for the specified malformed-row failure path. The pidfd is opened before the cgroup, executable and fd reads, checked for exit afterward, and the approved executable path and root-only cgroup match the supplied host preconditions. However, unit_pids silently discards malformed cgroup.procs words while trusting other entries, and socket_inode can accept a matching TCP row with a numeric inode without validating the rest of that row. The tests do not establish fail-closed handling of malformed rows at either gate.

**Evidence it cites**

`crooks-assistant/app/identity.py:unit_pids, socket_inode, _proc_peer_check; crooks-assistant/tests/test_proxy_identity.py:test_at_both_gates_a_process_that_exits_during_the_check_is_not_believed; REVIEW PACKET — PACKET FACTS`

**Required repair**

Reject malformed cgroup listings and TCP records rather than treating a partially parsed listing or row as authenticated provenance. Exercise malformed inputs through both principal_verdict and caller_check. Preserve the pidfd, approved-path and root-only checks.

**Verification note (mine, not the reviewer's)**

Confirmed as substantially repaired, with a narrower residual than round 7's. The TOCTOU
round 7 named is genuinely closed: A1 confirms the pidfd is opened before the cgroup, executable and
fd reads and checked for exit afterwards, the executable is attested against an approved path rather
than a basename, and the root-only cgroup requirement matches the host evidence I supplied. I
verified `os.pidfd_open` works in the production interpreter and that the cgroup directory and
`cgroup.procs` are uid 0 with no group or other write bit. The residual is input validation rather
than racing: `unit_pids` silently discards malformed `cgroup.procs` words while trusting the rest of
the listing, and `socket_inode` can accept a TCP row on a numeric inode without validating the rest
of the row. I did not build a malformed `/proc` to drive either path.

---

## A1 · F-05B-AVAIL

**Severity:** MATERIAL

**What it found**

STILL PRESENT in failure handling, despite removal of the stale address cache and tailscale ip subprocess. local_addresses reads the kernel tables afresh, so a correctly parsed added address is seen on the next request. But it treats a missing if_inet6 table as proof that IPv6 is off, without checking whether IPv6 is actually disabled; the packet says IPv6 is enabled on this host. It also silently skips malformed address entries. Either condition can omit this host’s own address from a non-None set. A host-originated request through tailscale serve could then be classified TAILSCALE and pass both gates under the host’s owner login despite writes_local_owner=false. Conversely, an unreadable table returns None and refuses all owner devices; the required availability behavior under a lookup failure is not demonstrated.

**Evidence it cites**

`crooks-assistant/app/identity.py:local_addresses, is_this_host; crooks-assistant/app/routes/actions.py:proxy_state, principal_verdict, caller_check; crooks-assistant/tests/test_proxy_identity.py:test_this_servers_own_addresses_are_the_kernels_read_fresh_every_time; REVIEW PACKET — PACKET FACTS`

**Required repair**

Distinguish verified IPv6-disabled state from a missing or renamed table, and fail closed on incomplete or malformed address data. Test an address addition, missing and malformed tables, and lookup failures through both gates with production flags. Provide an availability-preserving response to routine lookup failures without admitting uncertain host locality.

**Verification note (mine, not the reviewer's)**

Confirmed, and I read the mechanism myself. The round-7 defect is properly fixed:
`SELF_CACHE_S` and the `tailscale ip` subprocess are gone, and `local_addresses` reads
`/proc/net/fib_trie` and `/proc/net/if_inet6` fresh on every request, so an address the host gains
is in on the next request. What remains is in the same function:

    try:
        inet6 = (root / "net" / "if_inet6").read_text(...)
    except FileNotFoundError:
        inet6 = ""          # IPv6 switched off on this host: it owns no IPv6 address
    except OSError:
        return None

A missing or renamed `if_inet6` is taken as proof that IPv6 is off, without checking whether it is.
I verified IPv6 **is** enabled on this host (`net.ipv6.conf.all.disable_ipv6 = 0`, and the table
holds `fd7a115ca1e0000000000000352b5219 … tailscale0`). If that table were ever absent while IPv6 was
live, this host's own IPv6 address would be missing from a non-`None` set, `is_this_host` would say
no, `proxy_state` would call a host-originated request TAILSCALE, and both gates would admit it under
this host's owner login despite `CROOKS_WRITES_LOCAL_OWNER=false`. Malformed entries are also skipped
with `continue` rather than failing closed. The availability half is unanswered in the other
direction: an unreadable `fib_trie` returns `None` and refuses every owner device.

---

## A1 · F-05B-AVAIL-PREFLIGHT

**Severity:** MATERIAL

**What it found**

STILL UNVERIFIED as a deployment gate. admin.whoami obtains through and owner_refusal from proxy_state and principal_verdict, logs no login, and does not return the allow-list; for the stated production uvicorn command, served_without_proxy_headers detects a missing flag. But no successful real-phone request against this SHA is evidenced yet. The described abort-and-rollback operation is a plan, not a supplied or executed gate: the supplied install_systemd.install accepts any non-None health response and performs no running-argv or real-device assertion. app/routes/health.py’s check implementation is absent, so its expected detail and behavior cannot be verified here. The journal line has no request correlation, and the locality defect above could let a host-originated IPv6 request emit the same tailscale/owner=true line.

**Evidence it cites**

`crooks-assistant/app/routes/admin.py:whoami; crooks-assistant/app/identity.py:served_without_proxy_headers; crooks-assistant/scripts/install_systemd.py:install; REVIEW PACKET — F-05B-AVAIL-PREFLIGHT, WHAT I AM DOING ABOUT THE OPERATOR HALF, and CANDIDATE FILES (app/routes/health.py::_guarded not supplied)`

**Required repair**

Supply the health-check implementation and the enforceable deployment gate, then record a successful real-phone /whoami against this exact SHA under the rendered unit before installation. Require and evidence the running argv, expected health detail, and a second correlated production phone check, with abort or rollback on failure. Make the journal signal distinguishable from an unrelated request, and close the host-local misclassification before relying on it.

**Verification note (mine, not the reviewer's)**

Confirmed, and most of what remains is evidence I was going to produce
in steps 3 and 4 and never did, because the gate did not open. I should be precise about which parts
are the code's and which are mine.

The code half is better than round 7: I read `admin.whoami` and it takes `through` and
`owner_refusal` from `proxy_state` and `principal_verdict` — the same rule the owner routes enforce —
logs no login, and does not return the allow-list. Its journal line is exactly the one an operator
can gate on:

    logging.getLogger("crooks.identity").info(
        "whoami: through=%s owner=%s refusal=%s", route, "true" if not code else "false", code or "none")

A1 makes two points I accept. First, `scripts/install_systemd.py:install` still accepts any non-`None`
health response and asserts nothing about the running argv or a real device, so the *shipped*
deployment path still does not fail on a missing flag — my `round-8/deploy.sh` does, but that is an
operator script, not the product. Second, the journal line carries no request correlation, so it
cannot be tied to a particular device; and while the F-05B-AVAIL locality defect stands, a
host-originated IPv6 request could in principle emit the same `through=tailscale owner=true` line
that the deploy gate reads. That makes the gate weaker than I claimed when I described it to the
reviewer, and it is the right catch.

A1 also correctly refused to rule on `app/routes/health.py`'s check implementation, which went to A2
rather than A1. That is a fourth round of me splitting a finding's evidence across parts. Both
`/whoami` and the `checks.proxy_identity` implementation belong in A1 next time.

---


# Part A2 — the tool boundary and the pad routes

**Verdict: CHANGES_REQUIRED** — model `gpt-6-sol`, effort high.

> A2 is not ready. The SDK callback path now has a fail-closed owner check, and the pad and observability blocks are withheld without cache poisoning. Public /health still exposes other detailed owner status, service authority is not limited to service reads, and the autouse fixture makes offline tests authoritative by default. This verdict rules only on A2, not the other review parts.
> 
> [model gpt-6-sol, effort high, usage {"input_tokens": 114242, "input_tokens_details": {"cache_write_tokens": 114239, "cached_tokens": 0}, "output_tokens": 6784, "output_tokens_details": {"reasoning_tokens": 5366}, "total_tokens": 121026}]

## A2 · F-NEW-PAD

**Severity:** MATERIAL

**What it found**

STILL PRESENT in part. `_guarded` removes `pad` and `observability` on every /health return path, including both cached branches. Those blocks are added after the shared result is cached, so neither an owner's block nor a withheld version is cached for the other caller; `withheld` names the blocks without exposing their contents. But a refused caller still receives the rest of `_health`'s owner-facing payload: session count, write state and detail, capability and family states, orders-cache status, and detailed check results, including exception text. Public /health is therefore not limited to non-sensitive liveness. The new headerless production-switch test covers /health and /pad, but not these remaining fields or both cache directions.

**Evidence it cites**

`CANDIDATE FILES — app/routes/health.py: health, _guarded, _health; tests/test_pad.py: test_the_public_health_check_keeps_the_pads_status_and_the_session_to_the_owner`

**Required repair**

Return only non-sensitive liveness fields to callers failing the owner rule; keep detailed status for the owner. Test headerless production-settings requests before and after owner requests, including cached responses.

**Verification note (mine, not the reviewer's)**

Confirmed, and the boundary moved further than round 7's but still not to
non-sensitive liveness. The specific leak round 7 found is closed: `_guarded` removes `pad` and
`observability` on every `/health` return path including both cached branches, and because the blocks
are added *after* the shared result is cached, neither an owner's block nor a withheld one can be
served to the other caller — the cache-poisoning direction I would have worried about is genuinely
covered, and `withheld` names the blocks without exposing their contents.

What A2 found is that the rest of the payload is still owner-facing: session count, write state and
detail, capability and family states, orders-cache status, and detailed check results including
exception text. I confirmed against my own baseline capture that production `/health` is 15,527 bytes
with ten checks carrying detail strings that name the Gmail mailbox, the Shopify store and the voice
configuration. `/health` is public, reached over the tailnet through `tailscale serve`, and
`clive-worker-01` is on the tailnet and not on the allow-list. Round 7 asked for "non-sensitive
liveness only, or withhold from callers failing the owner rule"; two blocks were withheld and the
rest was left.

---

## A2 · F-NEW-TOOLS

**Severity:** MATERIAL

**What it found**

STILL PRESENT in the service-authority restriction, although absent authority now refuses: `TOOL_AUTHORITY` defaults to None and `dispatch` refuses when `current()` is None. The door revokes its shared owner object after the response, so the tested detached owner task is refused. However, `Authority.active` treats every unexpired SERVICE authority as sufficient for every tool. `Prefetcher.start` grants one to an arbitrary factory without enforcing its `readable()` list at that boundary; the test demonstrates a screen tool running after the owner authority is revoked. Neither `dispatch` nor `_dispatch` restricts a service authority to the named prefetch reads. A tool without its own principal check, including a screen tool, is therefore not unconditionally safe behind this boundary.

**Evidence it cites**

`CANDIDATE FILES — app/tools/authority.py: Authority.active, derive; app/tools/dispatch.py: dispatch; app/memory/prefetch.py: Prefetcher.start, readable; tests/test_tool_boundary.py: test_bounded_service_work_holds_its_own_derived_authority`

**Required repair**

Enforce the service authority's named, read-only tool scope at the shared invocation boundary, and revoke it when its bounded work finishes. Test that screen and write tools are refused under service authority, including after the owner response.

**Verification note (mine, not the reviewer's)**

Confirmed, and the shape of the finding has changed in an important way: the
fail-open default is gone, and what replaced it is an unscoped capability. I verified both halves.

`app/tools/context.py`'s `OWNER_REQUEST` is replaced by `app/tools/authority.py`'s
`TOOL_AUTHORITY: ContextVar[Authority | None] = ContextVar(..., default=None)`, and `dispatch`
refuses when `current()` is `None`. The `is False` guard is gone. That is round 7's headline defect
closed.

But `Authority.active` is:

    return not self.revoked and self.kind in (OWNER, SERVICE) and time.monotonic() < self.expires_at

`derive` records a `purpose` and a TTL capped at `MAX_SERVICE_S = 120`, and nothing at the invocation
boundary ever reads that purpose. So any unexpired SERVICE authority is sufficient for **every**
tool. A2 reports `Prefetcher.start` granting one to an arbitrary factory without enforcing its
`readable()` list, and a supplied test demonstrating a *screen* tool running under service authority
after the owner authority was revoked. A read-only prefetch grant therefore reaches the screen tools
and, on the same reasoning, the write tools. This is why B-01 cannot be closed either.

---

## A2 · F-NEW-TOOLS-PATH

**Severity:** not material

**What it found**

REPAIRED for model-initiated SDK tool calls. POST /turn reaches the provider; `_options` exposes registered tools through `registry.build_mcp_server`, whose callbacks call provider `_dispatch`. That callback checks the conversation's active authority, then installs it around fail-closed `dispatch` before a handler can run. `_turn_locked` captures the request authority for SDK tasks; revocation remains visible through that shared object. The PreToolUse hook also checks it, but is redundant for this owner check: a missing, failed, or unexpectedly permissive hook does not bypass `_dispatch`. Newly registered tools receive the same callback when included in a newly built server. The CLI subprocess does not stamp authority from model output. `registry.invoke` and decorated handlers remain directly callable by application Python code, so `dispatch` is not literally the only Python route to a handler; the shown SDK configuration does not expose those direct routes to the model. This finding does not clear the unrestricted service authority identified above.

**Evidence it cites**

`FULL FILES — app/routes/turn.py: turn, _provider_turn; CANDIDATE FILES — app/providers/max_agent_sdk.py: _options, _turn_locked, _dispatch; FULL FILES — app/tools/registry.py: build_mcp_server, invoke, tool; tests/test_tool_boundary.py: CallbackClient and provider callback tests`

**Required repair**

None for the model-initiated SDK path; repair the service-authority scope under F-NEW-TOOLS.

**Verification note (mine, not the reviewer's)**

Agreed — repaired, and this one was my evidence gap, so I want to be clear
that supplying the files is what closed it rather than any change in the code. With
`app/routes/turn.py`, `app/providers/max_agent_sdk.py` and `app/tools/registry.py` in the packet, A2
traced `POST /turn` → `_options` → `registry.build_mcp_server` → provider `_dispatch`, which checks
the conversation's active authority and installs it around fail-closed `dispatch` before a handler
runs. The `PreToolUse` hook is redundant for this check rather than load-bearing, which is the right
property: a missing, failing or permissive hook does not open a bypass. The CLI subprocess does not
stamp authority from model output.

A2 is careful about one limit and I record it: `registry.invoke` and the decorated handlers remain
directly callable from application Python, so `dispatch` is not literally the only route to a handler
— it is the only one the shown SDK configuration exposes to the model. That is a fair description and
not, on its own, material. This finding does not clear F-NEW-TOOLS.

---

## A2 · F-A2-FIXTURE

**Severity:** MATERIAL

**What it found**

The protected autouse fixture grants a fresh owner authority to every offline test by default, unlike production's None default. Boundary tests in test_tool_boundary.py explicitly use `acting_as(None)` or the HTTP door and do not need that grant; the no-authority dispatch test tests an override, not an unstamped call. The production-switch pad test likewise uses the door. But test_provider.py's `test_the_other_halfs_instruction_does_not_refuse_this_halfs_tool_calls` and `test_a_tool_call_carries_its_own_half_into_the_engine` rely on `_live_conversation` copying the fixture's authority and would no longer reach their asserted dispatch behavior without it. `test_a_tool_call_from_a_turn_the_owner_has_left_is_refused` would no longer demonstrate its asserted 'moved on' reason. Tests can override the context with `acting_as(None)`; there is no ordinary offline-test opt-out from the fixture itself. Thus part of the suite has been made to pass by widening the default it is meant to assess.

**Evidence it cites**

`CANDIDATE FILES — tests/conftest.py: _the_owner_is_asking; tests/test_provider.py: _live_conversation and named tests; tests/test_tool_boundary.py: test_with_no_authority_or_a_dead_one_no_handler_is_reached`

**Required repair**

Remove the global authority grant. Give tests that intentionally represent an admitted owner explicit, scoped authority, and add a dispatch test with no authority stamp at all. Keep boundary tests under the same deny-by-default condition as production.

**Verification note (mine, not the reviewer's)**

Confirmed, and I read it straight out of the file — see **Read this first**. Of
the three new findings this is the one I would put in front of the Director first, because it changes
how much any other test result in this candidate is worth.

`tests/conftest.py` is a protected path changed by hand. Its autouse `_the_owner_is_asking` fixture
sets `TOOL_AUTHORITY` to `authority.for_owner("owner@example.com")` for every test that is not marked
`live`. Production's default is `None`. The fixture's own docstring argues the case — "the offline
world is the owner's server with the owner asking" — so this is a deliberate decision rather than an
accident, which is why it needs the Director's ruling rather than a patch.

A2 is fair about the blast radius, and I agree with its narrowing: the boundary tests in
`tests/test_tool_boundary.py` do use `acting_as(None)` or the real door, so they are sound, and the
production-switch pad test uses the door too. The tests that actually depend on the grant are in
`tests/test_provider.py`. But there is no ordinary opt-out from the fixture, and the suite therefore
runs by default in a state production never has.

---


# Part A3 — the gap record, report handling, observability accounting

**Verdict: CHANGES_REQUIRED** — model `gpt-6-sol`, effort high.

> A3 is not ready. The candidate repairs important parts of all seven assigned findings, but each retains a material failure or an uncovered destructive, fail-open, or misleading path. The stated live reports directory appears ordinarily fixable; that does not close the general-case defects.
> 
> [model gpt-6-sol, effort high, usage {"input_tokens": 100707, "input_tokens_details": {"cache_write_tokens": 100704, "cached_tokens": 0}, "output_tokens": 12423, "output_tokens_details": {"reasoning_tokens": 9790}, "total_tokens": 113130}]

## A3 · F-07-VALUES

**Severity:** MATERIAL

**What it found**

STILL PRESENT in part. The startup rewrite validates many known fields, including seeded and version, but `_count` accepts a string whenever `isdigit()` is true and then calls `int()`; a known count containing `²` raises ValueError. `_strict_iso` can likewise raise OverflowError while converting a valid ISO timestamp near year 0001 with a positive offset to UTC. `install` catches the failed repair and leaves the legacy file; subsequent `report()` calls `load()` and fails on the same value. The added test covers an email, an invalid word and a huge integer, not these hostile known-field values.

**Evidence it cites**

`REVIEW PACKET — CANDIDATE FILES: crooks-assistant/app/objectives/gaps.py (`_count`, `_strict_iso`, `GapLedger.install`, `GapLedger.load`); tests/test_capability_gaps.py (`test_every_kept_value_is_what_its_field_says_it_is`)`

**Required repair**

Make count parsing and timestamp normalization total over JSON values: reject unsupported numeral strings and catch conversion overflow, dropping or replacing invalid values without aborting repair or report. Test those values, booleans and nested values in known fields through both paths.

**Verification note (mine, not the reviewer's)**

Confirmed, and I reproduced the mechanism. Most of what round 7 asked for is done:
the rewrite validates known fields including `seeded` and `version`, and the added test drives an
email, an invalid word and a huge integer through both paths.

`_count` is:

    if isinstance(value, str) and value.isdigit() and len(value) <= 8:
        return int(value)

`str.isdigit()` is true for Unicode digit characters that `int()` will not parse. I checked:
`'²'.isdigit()` is `True` and `int('²')` raises `ValueError`. So a known `count` field holding `²`
raises inside the repair. A3 reports the same class of failure in `_strict_iso`, which can raise
`OverflowError` normalising a valid ISO timestamp near year 0001 with a positive offset. `install`
catches the failed repair and leaves the legacy file in place, and a later `report()` calls `load()`
and fails on the same value — so the failure is persistent rather than transient. On this host
`builds` and `misjudged` are both empty, so the production record would not have exercised it on the
first pass; the record is the owner's and will accumulate both.

---

## A3 · F-07-LINKS

**Severity:** MATERIAL

**What it found**

STILL PRESENT in part. The new pass checks reciprocal links after remapping, and the test exercises mismatched surviving links. But `_only_known_gap` silently discards requests beyond `_MAX_READ=1000` and older seen entries beyond 1000; `_only_known_build` cuts gap keys at `MAX_GAPS=200`. None of those losses increments `not_kept` or makes `hits_after_fix_exact` false. Even below those limits, `_keep_requests` retains the last 20 equally ranked live builds, potentially dropping the *earliest* live fix; `report` can then report zero recurrence and call it exact when hits occurred after that omitted fix. The collision test exceeds `MAX_LINKS=20` and `_KEEP_SEEN=50` (30 requests and 80 seen entries), but not the 1000- or 200-entry input limits, and has only one live build.

**Evidence it cites**

`REVIEW PACKET — CANDIDATE FILES: crooks-assistant/app/objectives/gaps.py (`_only_known_gap`, `_only_known_build`, `_keep_requests`, `GapLedger.report`); tests/test_capability_gaps.py (`test_two_gaps_that_are_one_past_every_limit_keep_their_stage_and_say_what_they_could_not_keep`)`

**Required repair**

Account for losses at every input limit and preserve the earliest relevant live-fix time, or explicitly mark stage and recurrence uncertain when a relevant link is lost. Test reciprocal collisions with 21 live builds, more than 1000 requests/seen times, and a build with more than 200 gap keys.

**Verification note (mine, not the reviewer's)**

Not independently verified beyond reading the limits, and A3 went considerably
deeper than round 7 did. Reciprocity — the thing round 7 asked for — is genuinely added, and the test
does exercise mismatched surviving links. What A3 found is that the accounting round 7 also asked for
is incomplete at the *input* limits rather than the output ones: `_only_known_gap` discards requests
beyond `_MAX_READ=1000` and older `seen` entries beyond 1000, and `_only_known_build` cuts gap keys
at `MAX_GAPS=200`, and none of those losses increments `not_kept` or clears `hits_after_fix_exact`.
A3 adds a case below the limits too: `_keep_requests` retains the last 20 equally ranked live builds
and can drop the *earliest* live fix, after which `report` can say zero recurrence and call it exact.
The new collision test does exceed `MAX_LINKS=20` and `_KEEP_SEEN=50` — 30 requests and 80 seen
entries — but not the 1000- or 200-entry limits, and uses only one live build. I confirmed the
constants and the test's shape; I did not build a record past the 1000-entry limit.

---

## A3 · F-07-DURABILITY

**Severity:** MATERIAL

**What it found**

STILL PRESENT in part. A failed fsync of the backup directory now propagates before replacement; retries find a byte-identical, private existing backup, and the successful path makes one. But `_save` calls `os.replace` *before* its directory fsync. If that second fsync fails, startup logs that the record was 'left exactly as it was' although the live file has already changed; later saves similarly log 'not updated' after changing it. The failure test makes every `_fsync_dir` call fail, so it exercises only the pre-replacement failure. An unsupported directory fsync does not itself prevent service startup, but leaves repair and later bookkeeping unable to complete.

**Evidence it cites**

`REVIEW PACKET — CANDIDATE FILES: crooks-assistant/app/objectives/gaps.py (`GapLedger._save`, `_repair_locked`, `_change`, `install`); tests/test_capability_gaps.py (`test_a_copy_whose_folder_could_not_be_flushed_leaves_the_live_record_untouched`)`

**Required repair**

Handle a post-replacement directory-fsync failure as an uncertain or failed write without claiming the live file is untouched; provide a verified recovery of the prior contents where that guarantee is required. Test failure specifically on the second fsync during startup and on a later save.

**Verification note (mine, not the reviewer's)**

Confirmed, and the defect has moved from before the replacement to after it. I
read both halves.

The pre-replacement path is properly repaired: a failed backup-directory fsync now raises before the
live file is touched, retries recognise a byte-identical private existing backup instead of making
another, and the successful path makes exactly one. `_fsync_dir` no longer swallows everything.

But `_save` is:

    os.replace(tmp, self.path)
    _fsync_dir(folder)

The replacement happens first. If that second fsync fails, the live file has already changed while
start-up logs that the record was "left exactly as it was", and later saves log "not updated" after
updating. So the failure mode is no longer silent data loss but a false statement about what is on
disk — which, for a record whose whole purpose is to be recoverable, is close to the same problem.
A3 notes the supplied failure test makes *every* `_fsync_dir` call fail, so it only ever reaches the
pre-replacement branch and never the post-replacement one.

---

## A3 · F-04-STARTUP

**Severity:** MATERIAL

**What it found**

STILL PRESENT on a skipped-check path. When `tidy_reports` sets `tidy_contained=False`, `lifespan` raises before serving and uvicorn fails startup; traversal errors reported by `os.walk` are now distinguishable from an empty directory. But `housekeep_once` calls `tests.active()` before `tidy_reports()` and catches an exception from either as only a health problem. For example, a valid active-session JSON object with a nonnumeric `started_at` makes `TestSession.from_dict` raise ValueError; no report check runs, `tidy_contained` retains its initial True, and `lifespan` serves despite exposed reports. `tidy_reports` also treats a reports path for which `is_dir()` returns false as contained without establishing whether it is absent or unreadable. Tests cover an unfixable folder and a traversal callback, not these bypasses. A transient traversal error can conversely prevent boot; the deploy rollback limits that outage. The currently described root-owned folder and `.gitkeep` are ordinarily chmod-fixable. Changing `.gitkeep` from 0644 to 0600 changes no Git-tracked executable bit, so it need not appear in `git status`; a checkout that rematerializes it can restore its checkout permissions.

**Evidence it cites**

`REVIEW PACKET — CANDIDATE FILES: crooks-assistant/app/main.py (`housekeep_once`, `lifespan`); crooks-assistant/app/observability/session.py (`TestSession.from_dict`, `TestSessions.active`, `TestSessions.tidy_reports`); PACKET FACTS — THE REPORTS DIRECTORY`

**Required repair**

Make the startup report inspection mandatory independently of session-roll or other housekeeping failures. Treat an unreadable configured reports path as unchecked, not contained; test exceptions before `tidy_reports` and an unreadable reports path, with bounded retry for transient inspection errors.

**Verification note (mine, not the reviewer's)**

Confirmed, and I read the bypass. The fail-closed start round 7 asked for is
really there: when `tidy_reports` sets `tidy_contained=False`, `lifespan` raises before serving and
uvicorn fails startup, and traversal errors are now distinguishable from an empty directory.

The bypass is the ordering in `housekeep_once`:

    try:
        tests.active()
        tests.prune()
        tests.tidy_reports()
        ...
    except Exception as exc:
        problems.append(f"test-mode housekeeping did not complete ({type(exc).__name__})")

All three calls share one `try`. An exception from `active()` or `prune()` skips `tidy_reports()`
entirely and is caught as a health string, so `tidy_contained` keeps its initial `True` and
`lifespan` serves with reports never inspected. A3's example is concrete: an active-session record
with a non-numeric `started_at` makes `TestSession.from_dict` raise `ValueError`. A3 adds that
`tidy_reports` treats a reports path whose `is_dir()` is false as contained without distinguishing
absent from unreadable. The reverse risk is also named — a transient traversal error preventing
boot — and my deploy script's 30-second up-check and rollback would have caught that, which is the
one place my operator script does cover a code gap.

---

## A3 · F-04-REPORT-LOSS

**Severity:** MATERIAL

**What it found**

STILL PRESENT in a different destructive case. The permission-repair fallback no longer calls removal with infinity; move failure leaves both a fresh file and a directory intact. `_remove_if_older` is now called by `prune_reports` using the named-session age and by `TestSessions._prune` using the applicable session age, while `_close` unlinks the stopped session's active marker. However, `_remove_if_older` decides a report *directory's* expiry solely from the directory mtime and then calls `shutil.rmtree` on everything inside it. An old `ts-…-screens` directory containing a recently modified, non-expired report is deleted at startup before permission checks. Also, withheld paths acquire UUID prefixes, whereas pruning `.withheld` selects only `ts-*`, so withheld reports never expire by that pass. The destination is checked private before `os.rename`, not after; a symlink destination is refused and the nested rename has no copy-then-delete fallback, but post-move privacy is not verified.

**Evidence it cites**

`REVIEW PACKET — CANDIDATE FILES: crooks-assistant/app/observability/session.py (`_remove_if_older`, `prune_reports`, `withhold`, `TestSessions.tidy_reports`, `TestSessions._prune`, `_close`); tests/test_screen_privacy.py (`test_a_report_that_cannot_be_moved_is_never_deleted_whatever_its_age`)`

**Required repair**

Do not recursively delete a directory containing non-expired reports: check descendants or retain the directory until its contents expire. Give withheld items an effective bounded retention policy, verify containment after a move, and test a fresh descendant in an old directory as well as move failure.

**Verification note (mine, not the reviewer's)**

Confirmed, and it is still the finding I would act on first among the A3 set.
See **Read this first**. Round 7's exact defect is closed — the `float("inf")` fallback is gone and a
report that cannot be moved is never deleted whatever its age, with a test to that effect. But
`_remove_if_older` still reads a single mtime and then removes a whole tree:

    if path.stat().st_mtime >= cutoff: return 0
    if path.is_dir(): shutil.rmtree(path, ignore_errors=True)
    else: path.unlink()

It is now reached from `prune_reports` with the named-session age and from `TestSessions._prune` with
the applicable session age rather than from the permission fallback, so the trigger is ordinary
ageing rather than a failed chmod. The consequence is unchanged for a directory: an old
`ts-…-screens/` directory containing a recently modified, non-expired report is deleted whole, at
start-up, before permission checks. A3 adds a retention hole in the other direction — withheld paths
get UUID prefixes while the pruning pass selects only `ts-*`, so nothing in `.withheld` ever expires
— and notes the move destination is checked private before `os.rename` but not after. A symlink
destination is refused, which is right.

On this host there are no report directories yet, so nothing would have been deleted on the first
pass. That is luck, not a property of the code.

---

## A3 · F-04-SHUTDOWN

**Severity:** MATERIAL

**What it found**

STILL PRESENT as an unsafe timeout policy, although the specific runtime-close overlap is repaired. `lifespan` consumes the stop result and does not call `runtime.aclose()` while a pass holds the lock. At 20 seconds it instead abandons runtime closure permanently, even if the pass finishes a moment later; the new test asserts exactly that. A running pass has no cooperative interruption check once it begins. On a real stop the unit's 30-second TimeoutStopSec can therefore end in SIGKILL for a pass that stays stuck, with neither a completed pass nor runtime cleanup. The test outlasts the shortened wait but finishes before the unit deadline; it does not establish safe shutdown beyond that deadline.

**Evidence it cites**

`REVIEW PACKET — CANDIDATE FILES: crooks-assistant/app/main.py (`lifespan`, `Housekeeper.run_pass`, `Housekeeper.stop`, `SHUTDOWN_WAIT_S`); tests/test_screen_privacy.py (`test_shutdown_never_closes_the_runtime_under_a_pass_that_outlasts_the_wait`); PACKET FACTS — THE UNIT'S SHUTDOWN CONTRACT`

**Required repair**

Provide a shutdown path that can stop or cooperatively end an overlong pass within the unit deadline and close the runtime once the pass has ended, without closing it underneath the pass. Test completion just after the first wait and a pass exceeding the actual unit deadline.

**Verification note (mine, not the reviewer's)**

Confirmed, and the policy question round 7 asked to be handled explicitly has
been answered in a way that trades one unsafe outcome for another. The overlap is genuinely closed:
`lifespan` consumes `keeper.stop`'s result and does not call `runtime.aclose()` while a pass holds
the lock.

What it does instead, at `SHUTDOWN_WAIT_S = 20.0`, is abandon runtime closure permanently — even if
the pass finishes a moment later — and the new test asserts exactly that. I checked the arithmetic
against the unit, because it decides what actually happens on a real `systemctl stop`:
`KillSignal=SIGINT`, `TimeoutStopSec=30`, and the code waits 20. So a pass that stays stuck gets
10 more seconds and then `SIGKILL`, with neither a completed pass nor runtime cleanup. A running pass
has no cooperative interruption check once it begins. The test outlasts the 20-second wait but
finishes inside the 30-second unit deadline, so the case that matters is untested.

---

## A3 · F-10

**Severity:** MATERIAL

**What it found**

STILL PRESENT in the Control-app fallback. The stop route now carries `stop_settled`, and both scripts use it with settled counts for a *received backend answer*. `Timeline.counts` still reads the file outside its lock, comparing snapshots; that alone need not make the new backend-answer claim false. But `session_ops.call` returns None on a timeout as well as when no backend exists. `stop_and_analyse` then stops the session file locally, sets `final=True` unconditionally, and can say 'Recorded N event(s)' after `_settle` sees two unchanged counts while a live backend writer is held. The session-ops test supplies mocked answers, not a held writer or a timeout through this path; the CLI test does hold a writer, and the route test substitutes a false flush result. For a received answer whose flush failed but whose pending count has since reached zero, Control also says '0 were still being written', rather than giving the actual unsettled reason.

**Evidence it cites**

`REVIEW PACKET — CANDIDATE FILES: crooks-assistant/scripts/session_ops.py (`call`, `_settle`, `stop_and_analyse`); crooks-assistant/app/observability/timeline.py (`Timeline.counts`, `stop_is_final`); tests/test_screen_privacy.py (`test_the_control_apps_stop_never_calls_a_snapshot_recorded`, `test_a_stop_that_did_not_settle_never_presents_its_count_as_final`, `test_the_stop_route_says_whether_its_flush_settled`)`

**Required repair**

Distinguish verified backend absence from a failed or timed-out call. Without authoritative flush and pending state, label the file count an on-disk snapshot, not final; explain a failed flush separately from a pending count. Test an actually held writer through both owner-facing stop paths, including a backend-call timeout.

**Verification note (mine, not the reviewer's)**

Confirmed in part, and A3 found a path through the Control app that neither round 7 nor I
had looked at. The route half round 7 required is done: the stop route now carries `stop_settled`,
and both owner-facing scripts use it together with settled counts when they have a real backend
answer.

The residual is that `session_ops.call` returns `None` for a timeout and for "no backend exists"
alike. `stop_and_analyse` then stops the session file locally, sets `final=True` unconditionally, and
can tell the owner "Recorded N event(s)" after `_settle` sees two unchanged counts while a live
backend writer is held — which is the original F-10 sentence, reached by a different route. A3 also
notes that for a received answer whose flush failed but whose pending count has since reached zero,
Control says "0 were still being written" rather than naming the failed flush. The session-ops test
supplies mocked answers rather than a held writer or a timeout; the CLI test does hold a writer.
`Timeline.counts` still reads outside the lock, which A3 fairly says need not by itself falsify the
new claim. I did not drive a held writer through either path.

---


# Part B — the screens feature

**Verdict: CHANGES_REQUIRED** — model `gpt-6-sol`, effort high.

> Part B is not ready. Key-based registration and much of the storage work improve the feature, but packing acknowledgements remain forgeable, privacy deletion can be reported successful without restart-safe durability, first pairing and automatic eviction undermine destination binding, and an open screen can retain a slip after access is lost. The production screen-tool invocation path also remains unverified in this packet. F-ENG remains deferred.
> 
> [model gpt-6-sol, effort high, usage {"input_tokens": 127235, "input_tokens_details": {"cache_write_tokens": 127232, "cached_tokens": 0}, "output_tokens": 6489, "output_tokens_details": {"reasoning_tokens": 4142}, "total_tokens": 133724}]

## B · B-01

**Severity:** MATERIAL

**What it found**

STILL UNVERIFIED. Neither screen tool checks the principal itself. `dispatch` now refuses missing or inactive authority, and the middleware creates authority after the owner rule passes. But the supplied HTTP refused-caller test stops before its substitute provider calls either tool; the SDK tests start a provider turn without an HTTP request. The production turn-to-SDK-to-tool path cannot be established from this Part B packet.

**Evidence it cites**

`app/tools/display_tools.py:screen_list,screen_show; app/tools/dispatch.py:dispatch; app/main.py:guard_and_freshness; tests/test_tool_boundary.py:test_a_turn_from_anyone_but_the_owner_never_reaches_the_model_or_a_tool,test_the_real_provider_refuses_every_tool_without_authority`

**Required repair**

Supply app/routes/turn.py, app/providers/max_agent_sdk.py and app/tools/registry.py for review, and demonstrate refused HTTP callers cannot reach either screen handler on the production invocation path; alternatively enforce verified principal authority at both tools.

**Verification note (mine, not the reviewer's)**

Confirmed as still unverified, and the cause is the same compounding as round 7: the
screen tools have no check of their own, so they inherit whatever the shared boundary gives them, and
A2 has found that boundary admits any unexpired service authority for any tool. `dispatch` does now
refuse missing or inactive authority, which is real progress.

Part B could not close it for a second reason that is mine: I put `app/routes/turn.py`,
`app/providers/max_agent_sdk.py` and `app/tools/registry.py` in A2 and not in B, so B could see the
boundary but not the production path to it, and B correctly declined to approve what it could not
see. A2 did trace that path and found it sound for model-initiated calls. Between the two parts the
invocation path is established; what is not established is that a *service* authority cannot reach
`screen_show`, and A2 reports a test demonstrating that it can.

---

## B · B-02

**Severity:** MATERIAL

**What it found**

PARTLY REPAIRED. An existing name is no longer transferred merely because a screen went quiet or the service restarted: registration requires its existing key. `_seen` remains memory-only, but no longer decides ownership, so a stale persisted online flag cannot lock out key-based registration. Owner-principal `/forget` removes the old record, credential and showing before reuse. First registration, however, has no reservation or device-pairing step: any caller admitted as the owner can claim a guessed intended name first and receive its key. A tailnet caller refused by the owner rule cannot do so; an admitted but unintended device can. Automatic eviction also frees names without `/forget` (NEW-B-CAP). The restart test exercises the blocked takeover, not that eviction or the initial pairing race.

**Evidence it cites**

`app/displays/store.py:DisplayStore.register,forget,online; app/routes/displays.py:router,forget; tests/test_displays.py:test_a_name_is_one_screen_however_it_is_typed_and_never_passes_to_another_device`

**Required repair**

Bind first pairing of an intended name to an explicit owner-approved device/pairing operation, and prevent name reuse through automatic eviction. Test a competing first registration and an attempted claim across a restart and at capacity.

**Verification note (mine, not the reviewer's)**

Confirmed as partly repaired, and the restart hole round 7 called the worst part is
genuinely shut. `register` now requires the existing key, `_seen` no longer decides ownership, and an
owner-principal `/forget` clears the record, credential and showing before a name is reused. A stale
persisted online flag cannot lock out key-based registration either, which is the availability mirror
answered correctly.

Two ways in remain. First registration has no reservation or pairing step, so any caller the owner
rule admits can claim a guessed intended name first and receive its key; a tailnet caller the owner
rule refuses cannot, which bounds it to admitted-but-unintended devices. And NEW-B-CAP frees an
existing name without `/forget` at all. The restart test exercises the blocked takeover, not the
eviction path or the first-registration race.

---

## B · B-03

**Severity:** MATERIAL

**What it found**

PARTLY REPAIRED. `done_summary` replaces list/objective titles with their kind and keeps only patterned order or objective references; done rows still have a 90-day cutoff. `_write` now fsyncs the parent, and pre-replace failures roll back changes and reach the routes as 503. Expiry failures are reported and retried. But a parent-fsync failure *after* replacement makes `_write` return success: a privacy-deleting `mark_done` can answer successfully while `unsaved` exists only in memory. If power fails before the retry, the old file can survive; on restart `_load` can restore the unexpired customer slip, `unsaved` resets to false, and the startup sweep need not remove it. This does not fail closed for a deletion reported as successful. Housekeeping is wired: `lifespan` runs a first pass and starts `Housekeeper`, whose 15-minute passes call `displays().sweep()` even with no registered screen; `housekeep_once` reports a returned problem, and the timer restarts after an unexpected end. These mechanisms do not close the crash window.

**Evidence it cites**

`app/displays/store.py:done_summary,_write,_commit,_load,sweep,mark_done; app/main.py:lifespan,housekeep_once,Housekeeper._loop,Housekeeper._ended; app/routes/displays.py:done`

**Required repair**

Do not acknowledge a privacy deletion as durable after parent-fsync failure. Preserve a recoverable deletion obligation across restart or fail closed until it is durable; test a post-replace fsync failure followed by a restart before the retry.

**Verification note (mine, not the reviewer's)**

Confirmed as partly repaired, and the durability residual is the same shape as
F-07-DURABILITY in a different file — which is worth saying plainly, because it is the second time
this pattern has survived a round in two places at once.

The privacy work is real: `done_summary` replaces list and objective titles with their kind and keeps
only patterned order or objective references, `_write` now fsyncs the parent, pre-replace failures
roll back and surface as 503, and expiry failures are reported and retried. The housekeeping wiring I
failed to supply in round 7 is in this packet and B traced it: `lifespan` runs a first pass and starts
`Housekeeper`, whose 15-minute passes call `displays().sweep()` even with no screen registered, and
the timer restarts after an unexpected end. That closes round 7's unattended-expiry evidence gap.

The residual is that a parent-fsync failure *after* replacement makes `_write` return success, so a
privacy-deleting `mark_done` can answer the caller successfully while the obligation exists only in
memory as `unsaved`. If power fails before the retry, `_load` can restore the unexpired customer slip
on restart, `unsaved` resets to false, and the start-up sweep need not remove it. A deletion reported
as done does not fail closed.

---

## B · B-04

**Severity:** MATERIAL

**What it found**

STILL PRESENT in the packing attestation. The server holds per-version acknowledged item indices, resets them on a new showing, and loses them on restart—requiring re-acknowledgement rather than reopening the old count bypass. A direct done POST claiming `items_seen` without acknowledgements is tested and refused. Nevertheless `/seen` accepts arbitrary client-supplied ranges with the screen key and current version. A client that never renders a page can POST successive ranges of at most 12 items and then POST `/done`; there is no page issuance, nonce, timing or packer interaction for the server to verify. The done row therefore still rests on client assertions rather than evidence that the complete order was displayed or packed.

**Evidence it cites**

`app/displays/store.py:DisplayStore.acknowledge,mark_done; app/routes/displays.py:SeenBody,seen,done; tests/test_displays.py:test_an_order_is_marked_packed_only_once_every_item_was_acknowledged_on_the_screen`

**Required repair**

Make the confirmation protocol establish more than arbitrary range POSTs—for example, bind acknowledgements to separately issued pages for the current showing and an explicit packer confirmation—and test direct `/seen` calls followed by `/done` without displaying pages.

**Verification note (mine, not the reviewer's)**

Confirmed, and the control has been rebuilt rather than patched — which makes it much
better and still not enforceable. The server now holds per-version acknowledged item indices, resets
them on a new showing, and a direct `/done` POST claiming `items_seen` without acknowledgements is
tested and refused. Losing them on restart requires re-acknowledgement rather than reopening the old
count bypass, which is the right direction.

But `/seen` accepts arbitrary client-supplied ranges given the screen key and current version, so a
client that never renders a page can POST successive ranges of at most 12 items and then POST
`/done`. There is no page issuance, nonce, timing or packer interaction the server can check. The
done row still rests on client assertions. Round 7 asked for complete-order confirmation to be
enforceable; what exists is a longer client-side protocol. Combined with B-02's first-pairing gap and
NEW-B-CAP, the key that makes the assertion is still obtainable without the owner's involvement.

---

## B · B-05

**Severity:** MATERIAL

**What it found**

PARTLY REPAIRED. The gate lists `objective_id` among `screen_show`'s issued-ID arguments, checks the `obj_` kind and membership in the session's issued IDs; `dispatch` populates those IDs from tool results through `_harvest_ids`. A model-supplied string alone does not satisfy this gate. `screen_show` also requires an exact name. The physical destination guarantee remains incomplete because first pairing is unbound and capacity eviction can release an existing name for another device (B-02 and NEW-B-CAP). Actual production enforcement of the gate still depends on the missing invocation-path files noted in B-01.

**Evidence it cites**

`app/tools/gate.py:_ISSUED_ID_ARGS,_ID_KIND,_check_issued_ids,classify; app/tools/dispatch.py:dispatch,_harvest_ids; app/tools/display_tools.py:screen_show; app/displays/store.py:DisplayStore.register,find`

**Required repair**

Close the pairing and eviction paths so an exact registered name remains bound to the intended physical device, and supply the production tool invocation wiring for verification of gate enforcement.

**Verification note (mine, not the reviewer's)**

Confirmed as partly repaired, and the half round 7 could not see is now closed. With
`app/tools/gate.py` in Part B's packet, B ruled on `_ID_KIND` directly: the gate lists `objective_id`
among `screen_show`'s issued-ID arguments, checks the `obj_` kind and checks membership in the
session's issued IDs, which `dispatch` populates from tool results through `_harvest_ids`. A
model-supplied string alone does not satisfy it. `screen_show` also still requires an exact name and
rejects oversized input before finding a screen.

The destination guarantee still does not hold, for the reasons B-02 and NEW-B-CAP give: an exact
registered name is not bound to the intended physical device while first pairing is unbound and
capacity eviction can release a name. So a sensitive objective can still be routed to a screen that
is not the intended one. B also notes production enforcement of the gate depends on the invocation
path it was not given.

---

## B · B-06

**Severity:** not material

**What it found**

NO REGRESSION SHOWN. The packet states `web/startup.js` is unchanged in this range; the supplied `startup.css` retains its independent give-way animation, and the supplied test asserts timer-before-engine-before-is-live ordering. Because startup.js itself is not supplied, its implementation cannot be independently re-examined in this part.

**Evidence it cites**

`REVIEW PACKET — FULL FILES THAT ARE UNCHANGED IN THIS RANGE; web/startup.css:.startup,.startup.is-live; tests/test_displays.py:test_the_start_up_is_taken_away_whatever_fails`

**Required repair**

None for a regression in this range; supply web/startup.js if independent re-verification of its implementation is required.

**Verification note (mine, not the reviewer's)**

Agreed — no regression, and the limit is mine to note. `web/startup.js` is unchanged in
this range, so nothing could have regressed in it, and the supplied `startup.css` retains the
independent give-way animation. But I did not put `startup.js` itself in Part B, so B could not
re-examine the implementation round 7 verified, only confirm that this range did not touch it. That
is the right answer to the question I asked; if independent re-verification is ever wanted,
`startup.js` has to be in the packet.

---

## B · B-07

**Severity:** not material

**What it found**

NO REGRESSION SHOWN in the worker: its shell list still excludes `/display`, screen assets and `/displays/*`; only shell paths are intercepted and cached, older build caches are deleted, and a 403 passes through. The changed display page loads `/static/display.js` and `/static/display.css`, neither of which was added to the worker shell; its new `/seen` and `/forget` POSTs are not intercepted.

**Evidence it cites**

`web/sw.js:SHELL,activate,fetch,networkFirst; web/display.html:script,stylesheet; web/display.js:ackPage,replaceBtn; tests/web/sw.test.js:screen and change-of-login tests`

**Required repair**

None for B-07.

**Verification note (mine, not the reviewer's)**

Agreed — no regression, and B checked the thing I most wanted checked. `web/sw.js` is
unchanged in this range, and its shell list still excludes `/display`, the screen assets and
`/displays/*`; only shell paths are intercepted and cached, older build caches are deleted on
activation, and a 403 passes through uncached. Because `web/display.js`, `display.html` and
`display.css` *did* change, I asked B specifically whether those changes introduced a resource the
worker would now intercept. They did not: the page loads `/static/display.js` and
`/static/display.css`, neither of which was added to the shell, and the new `/seen` and `/forget`
POSTs are not intercepted.

---

## B · NEW-B-CAP

**Severity:** MATERIAL

**What it found**

At 20 screens, registering a new name silently deletes the screen with the oldest `last_seen`, including its key and any live customer slip. This bypasses the explicit owner `/forget` recovery policy, can lose a packing slip without confirmation, and makes the evicted physical destination's name available for registration by another admitted device.

**Evidence it cites**

`app/displays/store.py:DisplayStore.register (create branch at MAX_SCREENS); tests/test_displays.py:test_the_oldest_screen_makes_way_when_there_are_too_many`

**Required repair**

Refuse a new registration at capacity until the owner explicitly removes a selected screen; do not silently evict one with a showing. Test capacity with a live slip and subsequent attempts to reclaim its name.

**Verification note (mine, not the reviewer's)**

Confirmed by reading, and new — see **Read this first**. Round 7 never saw this
because `MAX_SCREENS` was not a path any finding pointed at. The `create` branch of `register` is:

    if len(self._data["screens"]) >= MAX_SCREENS:
        oldest = min(self._data["screens"].values(), key=lambda s: s.get("last_seen") or "")
        del self._data["screens"][oldest["id"]]
        self._acks.pop(oldest["id"], None)

`MAX_SCREENS = 20`. The evicted record's key and its `showing` — a customer's name, address, phone,
note and items — are deleted with no owner confirmation and nothing retained. That is a destructive
action at request time, it bypasses the explicit owner `/forget` recovery PR #49 added for this exact
purpose, and it frees the evicted name for another admitted device, which is how it re-opens B-02 and
B-05. It has a test asserting the behaviour is intended
(`test_the_oldest_screen_makes_way_when_there_are_too_many`), so like F-A2-FIXTURE it is a decision
to be reversed rather than a bug to be patched.

---

## B · NEW-B-LOCAL-SLIP

**Severity:** MATERIAL

**What it found**

An already-open screen retains and displays its customer slip indefinitely when polling loses access. On HTTP 403 or a network error, `poll()` only changes the online indicator and schedules another attempt; `S.showing`, `S.drawnView` and the visible UI are not cleared. `wanted()` applies a local timeout only to a done slip. Thus server-side expiry, clearing, or removal of an allowed login cannot take customer details off a disconnected or refused screen that stays open.

**Evidence it cites**

`web/display.js:poll,receive,wanted,reconcile; app/displays/store.py:SHOWING_KEEP_S,DisplayStore._expire_locked`

**Required repair**

Give the screen a local maximum lifetime for customer details and clear the DOM and retained view on expiry and access refusal; define fail-closed behavior for prolonged disconnection. Test an open screen past server expiry and after polling begins returning 403.

**Verification note (mine, not the reviewer's)**

Confirmed by reading, and new. This is the customer-privacy hole that survives
every server-side control in the feature, because it lives entirely in the page. In `poll()`:

    if (response.status === 403) {
      if (S.online !== false || !S.refused) setOnline(false, true);
      pollTimer = setTimeout(poll, REFUSED_MS);
      return;
    }
    ...
    } catch (e) {
      if (S.online !== false || S.refused) setOnline(false);
      ...
    }

Only a 404 reaches `forgetScreen()`. A 403 or a network error changes the online indicator and
reschedules; `S.showing`, `S.drawnView` and the visible DOM are untouched. `wanted()` applies a local
timeout only to a slip already marked done. So a screen that is already open keeps displaying the
customer's details indefinitely once polling loses access — and the case that matters most is the
owner removing that device's login from `CROOKS_ALLOWED_LOGINS`, which produces exactly a 403. Server
expiry, clearing and de-authorisation all become unenforceable against a screen left open on a wall.
I did not open a screen to watch it.

---
## What I verified, and what I did not

Every claim I checked held, and I checked more of them this round because several turn on a single
line. Confirmed directly in the code at this SHA:

- `tests/conftest.py`'s autouse `_the_owner_is_asking` fixture setting `TOOL_AUTHORITY` to a full
  owner authority for every non-`live` test, against production's `None` default;
- `Authority.active` returning true for any unexpired `SERVICE` authority, with `derive`'s `purpose`
  read nowhere at the invocation boundary;
- `TOOL_AUTHORITY`'s new `None` default and `dispatch`'s refusal on it — the round-7 fail-open
  default is genuinely gone;
- `_count`'s `value.isdigit()` then `int(value)`, and separately that `'²'.isdigit()` is `True`
  while `int('²')` raises `ValueError`;
- `_remove_if_older` deciding a directory's fate from one mtime and then calling
  `shutil.rmtree(path, ignore_errors=True)`;
- `_save` calling `os.replace` *before* `_fsync_dir`, so a post-replacement fsync failure follows a
  live change that is then reported as "left exactly as it was";
- `housekeep_once` sharing one `try` across `tests.active()`, `tests.prune()` and
  `tests.tidy_reports()`, so an exception in the first two skips the report inspection entirely;
- `SHUTDOWN_WAIT_S = 20.0` against the unit's `TimeoutStopSec=30` and `KillSignal=SIGINT`;
- `local_addresses` treating a `FileNotFoundError` on `/proc/net/if_inet6` as proof IPv6 is off, and
  that IPv6 is in fact enabled on this host;
- `register`'s capacity branch deleting the oldest screen, its key and its `showing`;
- `display.js`'s `poll()` clearing nothing on 403 or a network error, with only 404 reaching
  `forgetScreen()`;
- `admin.whoami` taking `through` and `owner_refusal` from `proxy_state` and `principal_verdict`,
  logging no login, and emitting exactly
  `whoami: through=%s owner=%s refusal=%s`;
- `deploy/systemd/crooks-assistant.service`'s template diff being only the `--no-proxy-headers`
  lines, and `launch_common.py` and `install_systemd.py` being unchanged in this range;
- the rollback fixture's byte-identity to `3e77f215:app/objectives/gaps.py` from line 6
  (sha256 `b6bfba90…`, 16,831 bytes).

Not independently verified: F-07-LINKS' input-limit accounting beyond confirming the constants and
the test's shape (I did not build a record past the 1000-entry limit); F-05B's malformed `/proc`
rows; F-05A's empty-header request; F-10's held writer through either owner-facing path;
F-07-VALUES' `_strict_iso` overflow near year 0001; and B-04's `/seen` range sequence. I did not
attempt any of these against a live service, and none of them needed constructing to establish that
the gate stays shut.

One evidence gap is mine again and I should name it: I put `app/routes/health.py` in A2 and `/whoami`
in A1, so A1 could rule on `/whoami` but not on the `checks.proxy_identity` implementation it feeds.
That is the fourth consecutive round in which a finding's evidence was split across two parts. For
F-05B-AVAIL-PREFLIGHT, `app/routes/admin.py`, `app/identity.py` **and** `app/routes/health.py` all
belong in A1 together.

## The two phone checks, which did not happen

Both were prepared and neither ran, because the rules make them conditional on four READY verdicts.
Recording exactly how far preparation went, since the request asked for pass or fail:

**Phone check 1 (staging, step 3): not run.** No staging clone was made, no `stage.env` was written,
no transient unit was started, port 8799 was never bound (`ss -ltn` shows no listener), and
`tailscale serve` was never modified — it still shows only the single original mapping
`https://crooks-os-prod-1.taildfb357.ts.net → 127.0.0.1:8000`, and no second HTTPS port exists. No
`serve-before.json` was needed because nothing was changed.

**Phone check 2 (production, step 4): not run.** `round-8/deploy.sh` was written, adapted from
round 7's, and syntax-checked. It was never executed. It asserts the running uvicorn's argv contains
`--no-proxy-headers`; that the service is active with the same `MainPID` for 30 seconds; that
`/health` shows `checks.proxy_identity.ok` true with the detail
`uvicorn started with --no-proxy-headers` and `checks.housekeeping.ok` true; waits up to 10 minutes
for `whoami: through=tailscale owner=true refusal=none` in the journal since the restart; requires
the host's own request to log `through=this_host owner=false`; and re-asserts the switches, the
`.env` sha256 and the parked credential's fingerprint. Its `ERR` trap restores the `3e77f215`
checkout and the saved `installed.service`, reloads systemd and restarts.

**The owner was never contacted.** Neither phone check was requested of him, so he has spent no time
on this round.

## The state the server was left in

Verified after the reviews returned, against the preflight baseline:

| | baseline | after |
|---|---|---|
| `/opt/crooks-os` HEAD | `3e77f215…` | `3e77f215…`, 0 dirty entries |
| service | active/enabled, MainPID 2135565 | active/enabled, **MainPID 2135565** |
| ActiveEnterTimestamp | 2026-09-27 01:07:04 UTC | 2026-09-27 01:07:04 UTC |
| NRestarts | 0 | **0** |
| running argv | no `--no-proxy-headers` | unchanged |
| installed unit sha256 | `e099b167…` | `e099b167…` |
| `.env` sha256 | `0021c07d…` | `0021c07d…`, mode 0600 |
| `credentials/*.cred` | 3 | 3 |
| parked credential | uid 0, 0600, 292 B, mtime 1790474150 | identical, never opened |
| `secrets/` | `gmail_token`, `media_signing_key` | unchanged |
| reports `-perm /077` | 2 | **2**, no `.withheld/` |
| `gaps.json` | 4,663 B, 0600, sha256 `90591f14…` | identical, **0 backups** |
| `tailscale serve` | one mapping, `/ → 127.0.0.1:8000` | unchanged |

The service never restarted, so none of the start-up code in this candidate ran: the gap record was
not rewritten, no backup was made, no report permission was changed, and `displays.json` still does
not exist.

## What the Director has to decide

Two of the 21 material findings are decisions rather than bugs, because each has a test asserting the
current behaviour is intended:

1. **F-A2-FIXTURE** — whether the offline suite may run with owner authority granted by default. If
   it may, then every boundary result in this candidate needs re-reading under that assumption, and
   F-NEW-TOOLS cannot be closed by any offline test. I would remove the grant.
2. **NEW-B-CAP** — whether a twenty-first screen may evict the least recently seen one, destroying its
   key and any live customer slip without confirmation. I would refuse the registration instead.

The remaining nineteen are ordinary repairs, and eleven of them are one-line or few-line changes to
code that is otherwise now correct: the empty-header check in `local_cli.presented`; malformed-row
rejection in `unit_pids` and `socket_inode`; distinguishing a missing `if_inet6` from IPv6 being off;
restricting `/health` to liveness for refused callers; scoping service authority to its declared
purpose; making `_count` and `_strict_iso` total over JSON values; ordering `_save`'s fsync before
its replace, or reporting an uncertain write; separating `tidy_reports` from the session calls in
`housekeep_once`; checking a directory's descendants before `rmtree`; giving `.withheld` a retention
pass that matches its UUID prefixes; distinguishing a `session_ops.call` timeout from no backend;
and clearing the screen's DOM on 403.

## Artefacts

Held on the deploy host under `/root/clive-activation/round-8/`, not committed here: the four
`.review.json` verdicts, the four dispatch packets and job files, the packet builder with its budget
simulation and leak check, the rendered and installed unit files and their diff, the
`LoadCredentialEncrypted` comparison, the env-switch record and `.env` sha256, the pre-deploy
baseline and `/health` baseline, the Tailscale and proxy-identity preconditions, the reports
preflight, the rollback-fixture check, the gap-record key listing, the six acceptance-run records,
the PR #49 and PR #50 metadata and the PR #49 body, the range diffstat, and the post-review state
check. The unrun deploy script is there as `deploy.sh`.

The review checkout at the candidate is at `round-8/review/`. No `round-8/stage*` exists, because
step 3 never ran.

---

# Addendum — the deploy, under George's waiver, 27 September 2026

The round-8 review above refused this SHA in all four parts. George waived that refusal and the
deploy went ahead the same night. **Production now runs
`6a29e31013b0b9e543d90434e14ed65deea1ce30`.** Everything the review found is still true; nothing
below repairs any of it. The 21 material findings are to be fixed after this deploy, in a normal PR,
and reviewed in round 9.

## The waiver, word for word

George's decision, 27 Sep 2026, 21:41:

> sure - lets waive review - go, we can work on fixing once its deployed go

What he waived, and nothing else:

- the rule that every review part must be READY before a deploy, **for this one deploy of
  `6a29e310`**;
- the 21 material findings published at `b55a573a` on `claude/deploy-review-round-8-findings`.

Everything else was kept and run in full: the preflight, both phone checks against a real device,
the one-operation deploy with automatic rollback, the switches, and the parked credential. The
four-part review was **not** re-run: round 8 had already reviewed this exact SHA.

## Step 1 — re-check before touching anything (read-only, all passed)

| Check | Result |
|---|---|
| `origin/clive/trunk` | still `6a29e31013b0b9e543d90434e14ed65deea1ce30` |
| production HEAD / dirty | `3e77f215…`, 0 entries |
| MainPID / NRestarts | **2135565**, unchanged from the round-8 baseline; `NRestarts=0`; up since 01:07:04 UTC |
| `CROOKS_SCREEN_SNAPSHOTS` | `false` |
| `CROOKS_LOCAL_OWNER` | unset |
| `CROOKS_WRITES_LOCAL_OWNER` | `false` |
| `CROOKS_ENGINEERING_HOST` | unset |
| `CROOKS_TAILSCALE_VERIFY` | unset |
| `CROOKS_ALLOWED_LOGINS` | non-empty (value never printed) |
| `.env` sha256 | `0021c07d…` — matches the round-8 baseline |
| installed unit sha256 | `e099b167…` — matches the round-8 baseline |
| rendered candidate unit | `3808af03…`, carries `--no-proxy-headers` |
| tailscaled exe | `/usr/sbin/tailscaled` exactly; cgroup `0::/system.slice/tailscaled.service` |
| cgroup + `cgroup.procs` | uid 0, no group-write, no other-write (`0 755`, `0 644`) |
| IPv4 in `fib_trie` | `100.72.82.24` present as `/32 host LOCAL` |
| `if_inet6` | exists, holds `fd7a115ca1e0000000000000352b5219 … tailscale0` |
| reports `-perm /077` | 2, no `.withheld/` |
| `gaps.json` | `90591f14…`, 4,663 bytes, 0600, 0 backups |
| parked credential | uid 0, 0600, 292 B, mtime 1790474150 — never opened |
| port 8799 | free |

## Step 2 — phone check 1, against a staging copy: **PASS**

A staging clone of `6a29e310` was cloned **from the review checkout**, never as a worktree of
`/opt/crooks-os` (`git -C /opt/crooks-os worktree list` confirmed production was untouched
throughout). Its tree matched the candidate's `1dedf34d…` with 0 dirty entries.

**Isolation.** `stage-state/{home,secrets}` created 0700 and empty; `stage.env` 0600 holding only
`CROOKS_ALLOWED_LOGINS` (copied from production without being printed), `CROOKS_WRITES_ENABLED=false`,
`CROOKS_WRITES_LOCAL_OWNER=false`, `CROOKS_SCREEN_SNAPSHOTS=false` and the three isolated
`CROOKS_LOG_DIR` / `CROOKS_OBJECTIVES_DIR` / `CROOKS_REPORTS_DIR` paths. No production data path
appears in it.

**No credentials reached it.** The transient unit `crooks-stage-r8` ran the production venv
interpreter on `127.0.0.1:8799` with `--no-proxy-headers`. Its process environment contained **no
`CREDENTIALS_DIRECTORY`**, and no `/run/credentials/crooks-stage-r8.service` was created. The staging
HOME acquired only a Claude CLI settings scaffold (`.claude.json` and one backup) and **no credential
file**, so the staging CLI had no login and could not race production's OAuth refresh;
production's `/root/.claude/.credentials.json` kept its 20:03:43 mtime throughout.

**It was the candidate's code.** `readlink /proc/<pid>/cwd` was the staging path, and
`import app` from that directory resolved to
`/root/clive-activation/round-8/stage/crooks-assistant/app/__init__.py` — so the staging copy beat
the venv's editable install of production.

**Staging `/health`:** `checks.proxy_identity.ok` true with detail
`uvicorn started with --no-proxy-headers`; `checks.housekeeping.ok` true;
`withheld: ['pad', 'observability']` with neither key present in the body. Top-level **`degraded`**,
correctly — `claude`, `gmail`, `shopify`, `scribe`, `speech`, `tts` and `whisper` all failed precisely
because the copy had no credentials.

**Serve.** `serve-before.json` saved (sha256 `075b5bcb…`); `tailscale serve --bg --https=8443
http://127.0.0.1:8799` added; the existing `:443 → 127.0.0.1:8000` handler was **byte-identical**
before and after.

**George's phone, 20:59:24 and 20:59:54 UTC.** Both halves of the gate held:

```
whoami: through=tailscale owner=true refusal=none
whoami: through=tailscale owner=true refusal=none
```

and his phone showed `"owner": true`, `"proxied": true`, `through` `tailscale`. His login is not
recorded here: the `/whoami` journal line deliberately carries no login, and the value he read back
is redacted.

**The three negative checks.** Two behaved exactly as specified; the third behaved *better* than
specified, and that is worth stating rather than glossing.

1. The host's own request through serve → `whoami: through=this_host owner=false
   refusal=not_authorised_local`. **PASS.**
2. A request carrying the local command key on `/objectives` → `403`, body code
   `local_key_misused`, logged as
   `refused a request carrying the local command key where it does not apply (path=/objectives)`.
   **PASS.**
3. Forged forwarding headers (`X-Forwarded-For` + `Tailscale-User-Login`) straight to `:8799`. The
   step expected a logged `through=forged owner=false`. **That line cannot occur**, because
   `guard_and_freshness` classifies the request `FORGED` via `proxy_state` and refuses it with
   `403 {"error":"not allowed","who":"unverified proxy"}` **before any route sees it**, logging
   `refused a request that claimed to come through Tailscale and did not: the connection was opened
   by something other than tailscaled (path=/whoami)`. The property under test — a forged
   forwarding header is not treated as the owner — holds, in the stronger form of refusal at the
   door rather than a route reporting `owner=false`. **PASS on substance**, with the expectation
   itself corrected.

**A new observation from the live run, which no reviewer saw.** George also registered a screen on a
second device (`scr_dce077a78139`), which came up and sat on its idle clock — the first time the
screens feature has run against a real device. Its polls returned `200` then seven `204`s, and then
its **final** poll, as the page went away, was refused `403` with *"the connection was opened by
something other than tailscaled"*. That is the provenance check failing **closed** on a connection
being torn down while a request is still in flight. A burst of 20 requests through serve immediately
afterwards returned 20/20 clean with zero forged refusals, so the check is stable rather than
flapping. Operationally: expect occasional `403`s in the journal when a screen is closed or a device
sleeps, and the page retries. It belongs with F-05B-AVAIL in round 9; it is the safe direction, but it
is a real availability wrinkle in the screens path that only a real device exposed.

**Tear-down.** `tailscale serve --https=8443 off`; `tailscale serve status --json` **byte-identical**
to `serve-before.json` (both sha256 `075b5bcb…`); `crooks-stage-r8` stopped, port 8799 free. The
staging screen's `displays.json` was written to the isolated `stage-state/objectives/` (378 bytes)
and **not** to production, which still had no `displays.json` afterwards. `round-8/stage`,
`round-8/stage-state` and `round-8/stage.env` are kept as evidence.

## Step 3 — the deploy: **DEPLOYED_OK**

`round-8/deploy.sh` was run as written and previously syntax-checked, in one operation, at
21:18:43 UTC. Full output:

```
### round 8 deploy  3e77f2157a35a23ba69014c1b0161a9351accd48 -> 6a29e31013b0b9e543d90434e14ed65deea1ce30  2026-09-27T21:18:43Z
[21:18:43] STEP 0: identity of the pieces this script will install
  .env sha256 matches preflight; parked credential fingerprint recorded (never opened)
[21:18:43] fetching candidate into /opt/crooks-os
  candidate object present
  journal marker: 2026-09-27 21:18:45
[21:18:46] STEP 4.1a: stop the service
  service now: inactive
[21:18:48] STEP 4.1b: checkout 6a29e31013b0b9e543d90434e14ed65deea1ce30
  HEAD: 6a29e31013b0b9e543d90434e14ed65deea1ce30
[21:18:48] STEP 4.1c: dependencies, only if the lock changed
  no dependency file changed between 3e77f215... and 6a29e310... -> nothing to install
[21:18:48] STEP 4.1d: install the re-rendered unit and daemon-reload
  installed ExecStart: ... -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
[21:18:49] STEP 4.1e: restart
  service now: active
[21:18:49] STEP 4.1f: wait for /health to answer
  /health answered after ~8s
[21:18:56] STEP 4.2: the running uvicorn's args carry --no-proxy-headers
  pid 3068091 args: ... -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
  OK
[21:18:56] STEP 4.3: active, and stayed up for 30 seconds
  active for 30s, same MainPID 3068091, NRestarts=0
[21:19:27] STEP 4.4: /health proxy_identity and housekeeping
  proxy_identity ok=True detail='uvicorn started with --no-proxy-headers'
  housekeeping   ok=True detail='last pass 33s ago · 1 pass(es)'
  top-level status: 'ok'   withheld: ['pad', 'observability']
  OK
[21:19:27] STEP 4.5: GEORGE, PHONE CHECK 2 — https://.../whoami on his phone
  waiting up to 600s for the service journal since 2026-09-27 21:18:45 to show:
    whoami: through=tailscale owner=true refusal=none
  FOUND after ~365s
    21:25:38 INFO crooks.identity  whoami: through=tailscale owner=true refusal=none
[21:25:39] STEP 4.6: the host's own request through serve is this_host, not the owner
  OK: 'whoami: through=this_host owner=false' present
[21:25:41] STEP 4.7: the switches, the .env and the parked credential are exactly as found
  .env sha256 unchanged: 0021c07d...
  CROOKS_SCREEN_SNAPSHOTS      = 'false'    OK
  CROOKS_LOCAL_OWNER           = <unset>    OK
  CROOKS_WRITES_LOCAL_OWNER    = 'false'    OK
  CROOKS_ENGINEERING_HOST      = <unset>    OK
  CROOKS_TAILSCALE_VERIFY      = <unset>    OK
  CROOKS_ALLOWED_LOGINS        = non-empty:True (value not printed) OK
  parked credential unchanged (uid mode size mtime identical; never opened or decrypted)
  /etc/crooks-os/credentials/ still holds exactly 3 .cred files
  installed unit's LoadCredentialEncrypted lines identical to the saved ones

RESULT: DEPLOYED_OK  HEAD=6a29e31013b0b9e543d90434e14ed65deea1ce30  unit=3808af03...
```

**Phone check 2: PASS.** The owner's phone got through production at 21:25:38 UTC, 365 s into the
600 s window. Production journal lines since the restart (no logins recorded):

```
whoami: through=tailscale owner=true refusal=none      <- George's phone, 21:25:38
whoami: through=this_host owner=false refusal=not_authorised_local   <- step 4.6, the host itself
```

**The start-up refusal that F-04-STARTUP is about did not fire.** `NRestarts=0` and the same
`MainPID 3068091` held for the full 30 seconds, so the reports folder was made private without the
fail-closed path being reached. Had it fired, step 4.3 would have rolled back rather than logged.

## Post-deploy facts

**1. The gap record's start-up rewrite made exactly one backup.**

```
-rw------- root:root 4663  gaps.json.20260927T211850Z.before-clean
-rw------- root:root 4662  gaps.json
```

One backup, 0600, and its sha256 is
`90591f143f4eccfc18b01343e877cc350641215b6254149a71b707bfb4c35b60` — **byte-identical to the
pre-deploy record**. So the F-07-DURABILITY repair's one-backup property held on the owner's live
record, and the rollback target is recoverable.

The rewrite itself was conservative: all five top-level keys unchanged (`version=1`,
`seeded="2026-09-27T01:07:06+00:00"`, `builds` and `misjudged` still empty), **all 8 gap keys
preserved**, no field added or removed on any row, and exactly one row's `label` normalised — which
is the one-byte size difference.

**2. The vendored `3e77f215` reader still reads the rewritten file.**
`tests/rollback/gaps_3e77f215.py` was loaded from the deployed checkout and run against the live
rewritten record: `load()` returned all five keys with 8 gaps, 0 builds, 0 misjudged and the original
`seeded`; `report()` (run against a byte-identical copy) returned `gaps` (8), `misjudged` (0) and an
11-field `summary`. The live file's sha256 was identical before and after, so the reader wrote
nothing. A rollback to `3e77f215` would read this record.

**3. Report paths: 2 tightened, 0 withheld** — exactly as expected.

| path | before | after |
|---|---|---|
| `reports/` | `0755` | **`0700`** |
| `reports/.gitkeep` | `0644` | **`0600`** |

`find reports -perm /077 | wc -l` went from 2 to **0**. No `.withheld/` was created, so nothing was
moved and nothing was deleted. A3's F-04-STARTUP note is confirmed: `git status --porcelain` on
`/opt/crooks-os` is **empty**, so chmodding the tracked `.gitkeep` to 0600 does not show up as a
modification.

**4. `/health` top-level status: `ok`** — 12 checks, all true (`claude`, `gmail`, `knowledge_base`,
`scribe`, `shopify`, `speech`, `terminology`, `tts`, `whisper`, `writes`, plus the two new
`proxy_identity` and `housekeeping`), with `withheld: ['pad', 'observability']`.

## What is still true

Every one of the 21 material findings above is unrepaired and now running in production. The two
that are decisions rather than bugs are live: the offline test suite still grants owner authority by
default (**F-A2-FIXTURE**), and a twenty-first screen will still evict the least recently seen one
along with its key and any live customer slip (**NEW-B-CAP**). The screens feature is enabled for the
first time, so **B-02**, **B-03**, **B-04**, **NEW-B-CAP** and **NEW-B-LOCAL-SLIP** are all live
paths rather than latent ones. `CROOKS_SCREEN_SNAPSHOTS` stays `false`, so F-02 remains latent.

Rollback remains available and tested in shape: `git -C /opt/crooks-os checkout --detach 3e77f215`
plus `cp round-8/installed.service /etc/systemd/system/crooks-assistant.service`, `daemon-reload`,
restart. The gap record's one backup makes that safe for the record too.

Round 9 should review the repairs for all 21, plus the two new observations this run produced: the
teardown-race `403` on the screens poll path, and the corrected expectation that a forged forwarding
header is refused at the door rather than logged by `/whoami`.
