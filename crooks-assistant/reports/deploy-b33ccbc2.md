# Deploy record — `b33ccbc2` on `crooks-os-prod-1`

**Deployed:** 2026-10-03, install 17:48:12–17:48:17 UTC (about 5 s of downtime).
**Host:** `crooks-os-prod-1`, checkout `/opt/crooks-os`.
**Procedure:** `crooks-assistant/docs/DEPLOY_LINUX.md`, "Deploying a new build".

| | |
|---|---|
| **Deployed SHA** | `b33ccbc29fd48de998abbd7b5bee967d232a0828` (PR #95, `clive/trunk` head) |
| **Previous SHA** | `cac1a9e7dede7fecd5d9deaf3d408d2184e75336` (PR #94) |
| **Build id now live** | `83524b275b07` (was `fdf72e24cc1e`) |
| **Outcome** | Installed, running, `/health` 200 and every check `ok`. One step outstanding: the owner's own phone `/whoami`. |

## Rollback target

Both halves were captured **before anything changed**:

| What | Where |
|---|---|
| Code | `git -C /opt/crooks-os checkout --detach cac1a9e7dede7fecd5d9deaf3d408d2184e75336` |
| Unit — **the copy to restore** | `/root/crooks-unit-before-b33ccbc2.main.service` (0600, 92 lines, main unit only) |
| Unit — full capture, for the record only | `/root/crooks-unit-before-b33ccbc2.service` (0600, 119 lines, `systemctl cat`) |

The main-unit-only copy is a byte-exact copy of `/etc/systemd/system/crooks-assistant.service`
taken straight from the file, not a slice of `systemctl cat` — so it carries no
`# /etc/...` header line and no trailing blank. **Restore that one.** The 119-line capture
concatenates the main unit with `10-state-writable.conf`, `objectives.conf` and `scenes.conf`;
restoring it whole would fold the drop-ins into the main unit while they also still exist in
`crooks-assistant.service.d/`, applying them twice, silently. The drop-in directory was not
touched by this deploy and must not be touched by a rollback.

Rollback, if it is ever wanted:

```bash
git -C /opt/crooks-os checkout --detach cac1a9e7dede7fecd5d9deaf3d408d2184e75336
install -m 0644 /root/crooks-unit-before-b33ccbc2.main.service \
  /etc/systemd/system/crooks-assistant.service
cd /opt/crooks-os/crooks-assistant && make install
```

`make install` rolls back the *unit* itself if any of its own gates fail, but by its own
docstring the **code in the checkout is not its to roll back** — that is the line above.

Nothing else needs undoing: the gap record was already clean and was not rewritten (below), and
`cac1a9e7`'s code reads the record as it stands.

## What was checked before anything changed

| Check | Result |
|---|---|
| Live SHA read from git, not from `CURRENT_TRUTH.md` | `cac1a9e7` — matches the stated rollback target |
| Target SHA present and on `clive/trunk` | yes; it **is** the trunk head |
| Shape of the change | single commit, sole parent `cac1a9e7` — a plain fast-forward, no merge |
| PR #95 | `MERGED` into `clive/trunk`, merge commit `b33ccbc2`, head was `d37a5f81` |
| **Acceptance on the exact deployed SHA** | **run `37128652668`, `completed` / `success`**, 9 m 55 s, `headSha` `b33ccbc29fd4…`, single `acceptance` job `success`, artifact `acceptance-b33ccbc29fd48de998abbd7b5bee967d232a0828` |
| No `.env`, unit, `deploy/` or `Makefile` paths in the diff | confirmed — none |
| `make doctor` | exit 0, "All prerequisites present. 8 warning(s)." |
| `tailnet_self_check()` (read-only, `app/identity.py`) | ok — "this host's own tailnet IPv4 and IPv6 addresses are on `tailscale0` and in its address tables" |
| tailscaled trust preconditions | `/usr/sbin/tailscaled`, root:root 755, `/proc/817/exe` resolves to it, cgroup `system.slice/tailscaled.service`, that folder and its `cgroup.procs` root-owned |
| `scripts/gap_clean_check.py` on the live record | **"VERDICT: nothing lost"** — 13 rows before, 13 after, all "kept as it was", *file unchanged*, rollback code (`3e77f215`) reads the result: yes |
| Baseline `/health` before the deploy | exit 0, all 12 checks `ok`, build `fdf72e24cc1e` |

The acceptance run named in the commit message (`37127824377`) is the one on the branch head
`d37a5f81`. The run recorded above is a **separate** run on the merge commit actually deployed,
which is what the acceptance condition for this deploy asked for.

### The re-rendered unit is byte-identical to the live one

The new build's `rendered_unit()` was rendered and diffed against
`/etc/systemd/system/crooks-assistant.service` *before* installing: **identical, no differences.**
So "code and unit together" held trivially here, and the unit half of the rollback is a no-op.

## The install

`make install` → exit 0. Its own gates, in order, all passed:

```
ok     unit → /etc/systemd/system/crooks-assistant.service
ok     crooks-assistant.service enabled (starts at boot)
ok     crooks-assistant.service started
https  https://crooks-os-prod-1.taildfb357.ts.net/  (already configured)
health all good · offline hearing, Claude, Shopify, ElevenLabs hearing, Gmail, instagram,
       the voice, hearing, the knowledge base, writes, proxy_identity, housekeeping
ok     running with --no-proxy-headers, and /health says it can tell who opened each connection
```

That last line is `running_problems()`, which checks three things after the restart and rolls the
unit back if any fail: the **running process's own command line** has `--no-proxy-headers`,
`/health checks.proxy_identity` is `ok`, and `tailnet_self_check()` still holds. All three passed
on the running build.

The live command line, read back from the running process:

```
/opt/crooks-os/crooks-assistant/.venv/bin/python -m uvicorn app.main:app \
  --host 127.0.0.1 --port 8000 --timeout-graceful-shutdown 10 --no-proxy-headers
```

`--timeout-graceful-shutdown 10` before `--no-proxy-headers`, as round 11 requires.

## Verification after the install

| Check | Result |
|---|---|
| `GET /health` | **HTTP 200**, `"status":"ok"`, build `83524b275b07` |
| `GET /ping` | HTTP 200, `{"ok":true}` |
| `scripts/healthcheck.py -v` | exit 0, **all 12 checks `ok`** — the same set, with the same verdicts, as the pre-deploy baseline |
| Service state | `active (running)`, `NRestarts=0`, one `MainPID` 94587, uptime climbing — no restart loop |
| `.env` | sha256 unchanged (`e81225c5…`) |
| Main unit | sha256 unchanged (`e9a8ed50…`), still byte-identical to the saved rollback copy |
| Drop-ins | sha256 of all three unchanged (`dba66649…`) |
| Switches | untouched — no `.env` line and no credential was written |
| Reports privacy | `reports/` is `drwx------`, `.withheld/` holds 0 entries; the service started, which it refuses to do if it cannot keep reports private |
| Gap record | no `gap record cleaned at startup` line in the journal, and `gaps.json` mtime is still 2026-10-02 21:47 — nothing written to an already-clean record, as round 9 specifies |
| Journal since restart | 53 lines, and **no** error, traceback, refusal, failure, `withheld` or `not confirmed on disk` line among them |

Startup was clean: graceful shutdown of PID 914, clean start of PID 94587, Shopify token minted,
Claude provider ready on `auth=cli`, screens resumed polling.

### The `/whoami` journal line works

A request the server made to itself over the HTTPS tailnet route answered HTTP 200 with
`"check":"d13ab2a1"`, `"through":"this_host"`, `"owner":false`, and the journal carried the
matching line:

```
17:49:38 INFO crooks.identity whoami: id=d13ab2a1 through=this_host owner=false refusal=not_authorised_local
```

Exactly what the procedure says a server-to-self request should look like. This confirms the route
is up and the token-matching mechanism works — it is **not** the owner-device check, which only a
real phone can give.

## Outstanding

- **The owner's phone `/whoami`.** Open `https://crooks-os-prod-1.taildfb357.ts.net/whoami` on the
  owner's phone; it must answer `"owner": true`, and
  `journalctl -u crooks-assistant.service | grep 'whoami: id=<the check it showed>'` must show
  `through=tailscale owner=true refusal=none` with that same eight-character token. Per the
  procedure the deploy is **kept** only once that line appears with the phone's own token.
- No screen reload is needed. The one-time `/display` reload belongs to the first deploy carrying
  round 10 (the move of the screen key into an HttpOnly cookie); that is long past, and the screens
  kept polling across this restart without being re-named.

## One thing to note about the procedure

`DEPLOY_LINUX.md` says a production deploy "happens only after an independent exact-SHA review of
that SHA", and the exact-SHA review is one of the things
`OWNER_DECISIONS_2026-09-30.md` explicitly did *not* relax. **The owner waived it for this SHA**,
on the grounds that every change in it was tested and that it follows a completed post-deploy
review of `cac1a9e7`. That is his call and it is recorded here rather than argued; it is noted only
so that the record does not read as though the review happened. What stands behind this build
instead is the green acceptance run on the exact deployed SHA, the twenty-two tests the change adds (eleven Python, eleven JavaScript),
and the post-deploy review of `cac1a9e7` that produced it.

`CURRENT_TRUTH.md` was not updated by this deploy. Its "Where the deploy is" table is badly stale —
it still names `3e77f215` as production and round 7 as the last review — so it was read as intent
and history, and the live SHA was taken from git.

## What this build changes

Seven fixes from the post-deploy review of `cac1a9e7` — six notes plus one found on the way — each
with a test that fails without it. 25 files, +1141/−188; no production code path outside the
Connections voice panel and the packing board.

**A voice's settings are never invented.** `app/clients/elevenlabs_tts.py`,
`app/routes/connections.py`, and a new `web/connections-voice.js` panel: a voice's own settings are
what ElevenLabs reports and nothing is made up; a saved voice is named by ElevenLabs, never by the
page; a voice ElevenLabs cannot name is not saved; going back to a voice's own settings needs a
passkey for exactly that; and ElevenLabs refusing the list or a preview is said in words rather
than crashing. `/health` names the record on the Connections screen when that is where the voice
came from.

**Shipped orders stay off the packing board.** `app/work/found.py`: an older order merely *changed*
today is not a box to pack; a refunded or cancelled order is no box to pack; a parcel the carrier
already has, or a fulfilment that was undone, is no box to pack; and a label is named only when
Shopify says one was bought.

Added Python tests:

```
test_a_voices_own_settings_are_what_elevenlabs_reports_and_nothing_is_made_up
test_the_voice_goes_back_to_its_own_settings_only_with_a_passkey_for_exactly_that
test_a_saved_voice_is_named_by_elevenlabs_never_by_the_page
test_a_voice_elevenlabs_cannot_name_is_not_saved
test_elevenlabs_refusing_the_list_or_a_preview_is_said_in_words_not_a_crash
test_health_names_the_record_on_the_connections_screen_when_that_is_where_the_voice_came_from
test_the_voice_panel_under_node
test_an_older_order_changed_today_does_not_come_back_as_a_box_to_pack
test_a_refunded_or_cancelled_order_is_no_box_to_pack
test_a_label_is_named_only_when_shopify_says_one_was_bought
test_a_parcel_the_carrier_has_or_a_fulfilment_undone_is_no_box_to_pack
```

And eleven JavaScript cases in `tests/web/connections-voice.test.js` (new) and
`tests/web/today-waiting.test.js`.
