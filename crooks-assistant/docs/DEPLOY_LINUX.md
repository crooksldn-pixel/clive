# CROOKS OS on Linux

This is the Ubuntu server that runs CLIVE as a service: the *production* host
`crooks-os-prod-1`, and the only host. The Mac is not a production or rollback host (DEC-058).
Its runtime (`mac/`, the CROOKS Control menu-bar app, `launchd/`, `install_launchd.py`) and the
local Whisper client were deleted on the owner's rulings of 8 October (DEC-071, rulings 38 and
39). The repository's history keeps them.

| | This server |
|---|---|
| Supervision | systemd unit (`deploy/systemd/`), through the `make` targets |
| Starts at | boot |
| Secrets | systemd encrypted credentials + a root-only 0600 directory |
| Logs | `journalctl -u crooks-assistant` + `logs/assistant.log` |
| Speech | ElevenLabs Scribe, with no local fallback (below) |

---

## Speech: there is no local fallback, on purpose

ElevenLabs Scribe is the one recogniser (DEC-022: no local speech fallback on the server). The
whisper.cpp client that used to stand behind it on the Mac was deleted with its settings on 8
October (DEC-071, ruling 39). `CROOKS_WHISPER_ENABLED` and `CROOKS_STT_PRIMARY`, if a server's
`.env` still has them, are ignored, as every unknown key is.

* `/health` has no whisper check, and the absence of a fallback does **not** make the
  top-level status `degraded`. A machine that was never given a fallback is not a broken
  machine.
* It does **not** hide a real failure. `checks["speech"]` tells the truth: Scribe working is
  healthy, and **Scribe down is unhealthy**, because with nothing behind it the assistant is
  deaf, and `/health` says so.

`checks["speech"]` carries `redundancy: "none"`, so the absence of a fallback is a visible fact
about the deployment rather than something you have to know.

---

## Secrets

There is no Keychain. `app/secrets/keychain.py` keeps the same public surface — `get`,
`get_optional`, `set_secret`, `delete`, `present` — and dispatches on the platform, so no
calling code knows the difference. Underneath, on Linux, there are two tiers, and which tier
a secret belongs in is decided by one question: **does the running application ever write
it?**

### Static — encrypted credentials

`elevenlabs_api_key`, `shopify_client_id`, `shopify_client_secret`, `shopify_static_token`,
`claude_oauth_token`, `youtube_api_key`, `ship24_api_key`, `crooks_returns_read_key`, `crooks_returns_write_key`,
`crooks_returns_hook_secret`, `crooks_shipping_read_key`, `crooks_shipping_write_key`.

`youtube_api_key` is optional. It is a YouTube Data API v3 key that CLIVE uses to search YouTube
when the owner asks for a video on a screen ("play the Heat trailer on the TV"). Without it, a
YouTube link still plays; only search needs the key (app/clients/youtube.py).

`ship24_api_key` is optional, and normally pasted on the Connections screen rather than stored
here. It is a Ship24 Tracking API key that CLIVE uses to say where a parcel is from the carrier's
own scans (app/clients/ship24.py); without it, parcel tracking reads as not connected.

`crooks_returns_read_key` and `crooks_returns_write_key` are optional, and normally pasted on the
Connections screen rather than stored here. They are the keys CROOKS Returns, the owner's own
returns service, lists for CLIVE (`grep CLIVE /opt/clive/crooks-returns/.env`:
`RETURNS_CLIVE_READ_KEYS` and `RETURNS_CLIVE_WRITE_KEYS`). CLIVE reads returns with the first and
sends the second only with an action the owner approved on its card (app/clients/crooks_returns.py);
without them, returns read as not connected. Where the service answers is the setting
`CROOKS_RETURNS_BASE_URL` (default `https://returns.crooksldn.com`).
`crooks_returns_hook_secret` is optional too: the value of the service's
`RETURNS_CLIVE_WEBHOOK_SECRET`, with which CLIVE checks the events the service posts to
`/hooks/returns` ([`RETURNS_EVENTS.md`](RETURNS_EVENTS.md), DEC-077). Without it, CLIVE asks the
service as before.

`crooks_shipping_read_key` and `crooks_shipping_write_key` are optional too, and normally pasted on
the Connections screen. They are the keys CLIVE Shipping, the owner's own international shipping
service, lists for CLIVE (`grep CLIVE /opt/clive/clive-shipping/.env`: `SHIPPING_CLIVE_READ_KEYS`
and `SHIPPING_CLIVE_WRITE_KEYS`). CLIVE reads orders, prices and tracking with the first and sends
the second only with a label bought or printed on a card the owner approved
(app/clients/crooks_shipping.py); without them, shipping reads as not connected. CLIVE holds no
PrintNode key: labels print through the service's own `PRINTNODE_API_KEY` and
`PRINTNODE_PRINTER_ID`. Where the service answers is the setting `CROOKS_SHIPPING_BASE_URL`
(default `https://returns.crooksldn.com/shipping`).

Read at runtime and never written. Encrypted with `systemd-creds encrypt`, which binds the
blob to this host, and mounted read-only into the service's own private tmpfs by
`LoadCredentialEncrypted=` in the unit. A copy taken off the disk — a snapshot, a backup — is
inert. Nothing else on the machine can read the decrypted value.

```
python scripts/provision_secrets.py elevenlabs_api_key
make install      # regenerates the unit's LoadCredentialEncrypted= lines and restarts
```

A static secret reaches the service on its next restart, never before.

### Mutable — a root-only directory

`gmail_token`, `media_signing_key`. Stored in `/etc/crooks-os/secrets/`, directory `0700`,
files `0600`, root-owned, written atomically.

* **`gmail_token`** — `app/clients/gmail.py` rewrites it after every OAuth refresh, about
  once an hour. It cannot live in a read-only credential. It is kept out of the checkout
  (where `token.json` would sit) so that a git operation can never see it; `token.json`
  remains the automatic fallback and is untouched.
* **`media_signing_key`** — signs the image paths the tablet is given. It is **generated once,
  here, at installation** and then kept. It must never be regenerated: every regeneration
  invalidates every signed path the tablet has cached.

  > This key was previously absent from `KNOWN_KEYS`, so every lookup raised "unknown key",
  > every store was swallowed, and a fresh key was made at every boot — on the Mac too. That
  > is fixed; the Mac now also keeps its key, which is what `app/media.py` always said it did.

### The one contract difference

A write to a key that systemd provisions read-only raises `SecretShadowed` rather than writing
somewhere the next read would ignore. It names the key and what to do. It is a refusal, never
a silence, and nothing in the running application writes a static key — only the installer
does.

### Claude Max

Not in either tier. The `claude` CLI holds its own login in `/root/.claude/.credentials.json`
and the provider uses it (`auth=cli`). The unit therefore sets `HOME` and keeps it writable,
because the CLI rewrites that file when the token refreshes. A read-only home turns a refresh
into an authentication failure days later, with nothing in the log to connect the two.

---

## Running as root — temporary

The service runs as root. This is a deliberate, time-limited compromise: the Claude Max login
this machine already holds is under `/root`, and moving it means a second authentication
migration at the same time as the first. The decision was to get production working, then
harden.

What contains it in the meantime:

* the app binds **127.0.0.1** and is never exposed publicly — `getUserMedia` needs a trusted
  HTTPS origin, and `tailscale serve` supplies one; binding `0.0.0.0` looks like it works and
  then fails on the browser API that actually matters;
* access is over Tailscale only, on a private tailnet;
* `ProtectSystem=strict` makes the whole filesystem read-only except three named paths, plus
  `NoNewPrivileges`, `PrivateTmp`, and the kernel protections in the unit;
* only the owner, and the members of the team he has let in, ask: every route but the public
  ones (liveness, `/whoami`, the page shells) needs a login on `CROOKS_ALLOWED_LOGINS`, or a
  staff member's login whose grant the owner approved with his passkey
  (`app/people/access.py`, `app/people/door.py`), confirmed by Tailscale either way
  (`CROOKS_TAILSCALE_VERIFY`, left unset so it stays on). A staff member reaches only the
  team's routes — the chat, its cards and the Today screen (`app/people/staff.py`) — and with an
  empty allow-list nobody gets in at all.

Writes are not one of the things that contain it. Production runs with writes to the store and
the inbox on, by the owner's choice: `deploy/env.production.example` ships
`CROOKS_WRITES_ENABLED=false`, and writes are on only once he sets it to `true` in the server's
`.env`. CLIVE only prepares a change, and nothing is sent until someone confirms its card on
their own device: the owner, for any change (a hold, or for a small undoable change a tap), or a
staff member, for only the five changes the owner let the team make without him — fulfilling an
order, setting its tracking number, drafting and sending an email reply, and adjusting stock
(`app/people/staff.py` `WRITES`) — and the undo of each. A commit is checked against who is
confirming it, Tailscale's identity and the scope the store granted, every time. The switches
that stay off are the ones that would let the host itself act as the owner or keep what the
screens showed:

* `CROOKS_WRITES_LOCAL_OWNER=false` — nothing on the server can apply a business write;
* `CROOKS_LOCAL_OWNER` unset — a request made on the server is not the owner's;
* `CROOKS_SCREEN_SNAPSHOTS=false` — no copy is kept of what a screen showed.

**Hardening item, once production is proven:** migrate to a dedicated `crooks` service user —
re-authenticate the Claude CLI as that user, chown the checkout, the secret directory and the
logs, and drop `ProtectHome=no`.

---

## Install

```bash
make venv                                     # once
python scripts/provision_secrets.py --all     # Shopify, ElevenLabs, and the media key
make doctor                                   # everything this host needs
make install                                  # unit, enable, start, Tailscale route, /health
make status                                   # is it up, what does /health say, what address
```

## Day to day

```bash
make status        # one screen
make logs          # journalctl -u crooks-assistant -f
make restart       # after a git pull
crooks-status      # the same screen, from anywhere on the PATH
crooks-update      # fetch, fast-forward, install what changed, restart, verify
```

`crooks-update` runs eight stages; stage 7 restarts the systemd unit and reads `/health` back.
It is fast-forward only, refuses on a dirty tree, and has no `--force`.

`crooks-control`, the menu-bar app's command, went with the app on 8 October (DEC-071, ruling
38). Each of its jobs has a home here: the state is `make status` or `crooks-status`; a restart
that reads `/health` back is `make restart`; a new build on production is a deploy (below), which
the release service ([RELEASE_SERVICE.md](RELEASE_SERVICE.md)) makes by itself once it is switched
on; and the previous build goes back as "Putting the previous build back" says. A
`~/.local/bin/crooks-control` left by an earlier `make commands` is taken off by running
`make commands` again.

## Health

```bash
python scripts/healthcheck.py        # exit 0 healthy, 1 not; one line either way
python scripts/healthcheck.py -v     # every check
```

`/ping` is the cheap one — no external call, never cached — and `/health` is the real one.

## Deploying a new build

A production deploy is an exact `clive/trunk` SHA. Since the owner's ruling of 8 October 2026
([DEC-071](product-memory/DECISIONS.md), ruling 6; how it works: DEC-072) an independent review of
that exact SHA is **no longer required before a deploy**. What a deploy needs instead, all three:

- **GitHub acceptance green on the exact SHA** (every `acceptance` run for that commit completed with
  success, its acceptance job on that commit);
- **the pull requests it carries were each independently reviewed before they merged.** This is the
  process, not a lock: merges come only through reviewed PRs or the loop's reviewed landings. The trunk
  has no branch protection, so nothing on GitHub stops a push that skipped review, and neither the
  release service nor CLIVE checks reviews. The Deploy now card lists every commit the deploy would
  bring in, in its own title: every commit in GitHub's comparison of production's SHA with the trunk's
  head, newest first, whichever line it came in on (a pull request a refresh merge carried in is
  listed like any other); eight are shown, and the headline and "and N more" count the same list. Only
  the loop's own refresh merges are left out, matched by their exact title and parents, and the card's
  technical details count them. That match is metadata: anyone who can push can make a commit in that
  shape, and its own content is then not on the card (the commits it merges still are). So the card
  shows him what is coming; it does not prove any of it was reviewed;
- **the owner's approval of that exact SHA** (ruling 7): given in CLIVE, on the Builds screen's
  "Deploy now" card, with his hold and his passkey; or, for a hand deploy, his word to the Termius
  Claude, recorded in the deploy record as his waiver.

His approval in CLIVE starts the deploy at once, through the release service
([`RELEASE_SERVICE.md`](RELEASE_SERVICE.md)), which runs this same procedure as code and rolls back on
any failure after the change. A change to how CLIVE is installed or checked (`deploy/`, the Makefile,
the installer, the dependencies, `.github/`) stays a hand deploy by this section. While the release
service is installed, a hand deploy first stops it (RELEASE_SERVICE.md, "Deploying by hand while the
service is installed"). Where the pipeline stands now is in
[CURRENT_TRUTH.md](product-memory/CURRENT_TRUTH.md), "Where the deploy is".

What every deploy must hold:

- **Code and unit together.** The checkout and the re-rendered unit are installed in one
  operation, with a rollback to the previous SHA and the saved unit if any step fails. The unit
  must start uvicorn with `--no-proxy-headers`: the app judges who opened each connection
  itself, and uvicorn's own handling would replace that address first. `/health`
  `checks.proxy_identity` says whether the running process has the flag. `make install` checks
  both after the restart — the running process's own command line
  (`/proc/<MainPID>/cmdline`) and that check — and exits non-zero, saying which, if either fails.
  Since round 11 the unit also bounds uvicorn's graceful drain (`--timeout-graceful-shutdown 10`,
  before `--no-proxy-headers`), inside the `TimeoutStopSec=30` a stop has always had: 10 s for
  requests still running, then at most 13 s of the app's own shutdown (housekeeping stopped, the
  runtime closed, the timeline's accepted events written — `app/main.py`, the SHUTDOWN_* budget),
  and the rest for the process to exit. The deploy's re-rendered unit is what carries the flag.
  Also since round 11, a forwarded request is admitted only while the host's address tables hold
  the Tailscale interface's own tailnet address (IPv6 as well, when IPv6 is on): a reading
  without it cannot tell the server's own requests from a device's (S1T-01). `make install`
  asks the same of the host after the restart (`app/identity.py` `tailnet_self_check`) and rolls
  itself back if it is not so — which a host running tailscaled in userspace mode, or with IPv6
  on and no tailnet IPv6 address on `tailscale0`, would be. The deploy prompt runs that check
  read-only before anything changes.
- **The switches stay as they are.** The table is in CURRENT_TRUTH. A deploy changes no `.env`
  line and no credential.
- **Tailscale is what the proxy check trusts.** These must all hold, or every owner device is
  refused:
  - tailscaled runs as `/usr/sbin/tailscaled`, owned by root;
  - it runs in `system.slice/tailscaled.service`;
  - that cgroup's folder and its `cgroup.procs` are root's alone;
  - this server's tailnet address is in the kernel's own tables (`/proc/net/fib_trie`, and
    `/proc/net/if_inet6` for IPv6), each read whole or not believed at all. A missing
    `if_inet6` counts as "no IPv6" only when `net.ipv6.conf.all.disable_ipv6` reads `1`;
    otherwise every forwarded request is refused. Since round 9 a reading is believed only when
    two taken one after the other agree (up to four, with a wait of at most 70 ms in all, and
    only when one went wrong); the IPv6 table must list `::1` unless IPv6 is switched off; and
    a reading without this server's own tailnet address of the forwarded family refuses every
    request of that family. The journal's refusal says which of these failed.
- **Reports must be private, or it will not start.** At start-up every report is set to 0600
  and every folder to 0700. Anything that cannot be fixed is moved into `reports/.withheld/`;
  nothing is deleted to get it private. What is in `.withheld/` ages out like any report, by its
  own time, after `test_session_keep_named_days`; a report folder goes only once everything in
  it has. If the reports folder itself cannot be made private, looked at or read, or a report
  in it cannot be withheld, the service checks three times, half a second apart, and then
  refuses to start. A rollback, not a retry, is the answer to that.
- **A real phone gets through.** Opening `/whoami` on the owner's phone writes one line to the
  service's journal, without the login:
  `whoami: id=<check> through=tailscale owner=true refusal=none`, where `<check>` is the
  eight-character token that same answer shows as `"check"` — so the line is matched to the
  phone that asked, and to no other request. The deploy is kept only once that line appears
  with the phone's own token. A request the server makes to itself through `tailscale serve`
  logs `through=this_host owner=false`.
- **`/health` is liveness to anyone but the owner.** A caller the owner rule refuses gets the
  overall status, the build, the uptime and two verdicts (`proxy_identity` with its detail,
  `housekeeping` without), marked `"limited": true`. The server's own status readers
  (`make health`, `crooks-status`, `make install`) read the whole document on loopback with the
  server's local key, sent only on a connection the kernel says `crooks-assistant.service` itself
  took, and never on a redirect (round 9: whatever held the port during a restart was otherwise
  sent the key). Run as a user who cannot read that key, or with the port held by anything else,
  they say the detail is the owner's and exit 1; so does `make status`.

- **Screens left open reload themselves — from round 10 on.** Every answer to a screen's ask
  says which build answered (`X-Clive-Build`), and a screen whose page is from an older build
  reloads itself once it is resting on its clock (never mid-slip, never mid-video).
  **The first deploy that carries round 10 is the exception** (round 10 was reviewed but not
  deployed, so this is round 11's deploy or whichever ships first): the pages already open on
  the TVs are from before this, and their key moves from the page's storage into an HttpOnly
  cookie (B2-01). An old page still sending its key as a header is answered 403 `reload` and
  shows "not allowed" until someone reloads it. So, once, after that deploy: reload `/display`
  on every screen (or restart the TV's browser), over the https tailnet address, since the
  cookie is Secure. It keeps its name and its approval: the new page takes the old key out of
  its storage the moment it reads it (round 11), hands it back once, gets the cookie, and the
  old key stops working. Reload each TV while CLIVE is up: a page reloaded AGAIN before that
  hand-back has succeeded no longer has the key anywhere, and the screen is named again (a new
  code for the owner to approve), as a new screen would be.

## The capability-gap record, cleaned at start-up

The first start of a build with the current gap rule (deploy review rounds 6 and 7) rewrites
`/var/lib/crooks-assistant/objectives/gaps.json` to that rule: every key and label redacted,
only known fields kept, every kept value validated, and links kept only when both sides agree.
It keeps the exact original first as
`gaps.json.<UTC time>.before-clean` beside it (0600, never overwritten). The code before it
(3e77f215) reads the cleaned file as it is — `tests/test_capability_gaps.py` runs that code
against it — so rolling the code back needs nothing else. To put the original back as well:

```
systemctl stop crooks-assistant
cd /var/lib/crooks-assistant/objectives
cp -p gaps.json "gaps.json.$(date -u +%Y%m%dT%H%M%SZ).after-clean"   # keep the cleaned one
install -m 0600 gaps.json.<time>.before-clean gaps.json
systemctl start crooks-assistant
```

A newer build started afterwards cleans it again, keeping a fresh copy first.

Before a deploy, `python scripts/gap_clean_check.py` (as root, on the server) runs the new build's
start-up on a private copy of the live record and says, row by row — by number and cleaned key,
never a label — what it would keep, merge or change, how many copies it keeps, and whether the
rollback code reads the result. The live record is only read. Start-up forgets no gap, and writes
nothing to a record that is already clean (round 9).

If the journal says `gap record cleaned at startup: the clean record has replaced the original,
but is not confirmed on disk`, the folder could not be flushed after the replace: `gaps.json`
holds the cleaned record, and the original named in that line was flushed before it. The steps
above put it back. A later `gap record updated, but not confirmed on disk` means the same of an
ordinary update; `gap record not updated` means the file was not replaced.

## Putting the previous build back

When a new build will not run, the answer is a rollback, not a retry. What goes back depends on how
the build arrived:

- **A deploy, by hand or by the release service.** Its record, `reports/deploy-<sha8>.md`, names
  the rollback target, captured before anything changed: the previous SHA and the unit as it was.
  It also carries the lines that put both back. The release service runs them itself when its own
  checks fail. A rollback it could not finish leaves `HALT` behind
  ([RELEASE_SERVICE.md](RELEASE_SERVICE.md), "After a halt").
- **`crooks-update`.** It moves the code and never the unit. When its restart fails it says so,
  and names the build it started from ("The build before this update: …"). Check that build out
  again and restart; `make restart` reads `/health` back:

  ```bash
  git checkout --detach <the SHA crooks-update named>
  make restart
  ```

  The next `crooks-update --branch <branch>` comes forward from there by itself.

## Taking the server down

There is no other host to fall back to (DEC-058). If the server is to stop answering:

```bash
make uninstall           # stop, disable, remove the unit
tailscale serve reset    # drop the HTTPS route
```
