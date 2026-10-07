# The release service

**What it is.** A small program on the production host (`crooks-os-prod-1`) that deploys CLIVE the
way the Termius Claude does today: `docs/DEPLOY_LINUX.md`, "Deploying a new build", step by step,
with the same checks and the same record. It runs every five minutes from a systemd timer.

**Why.** George, 7 Oct 2026, wants deploys "to just happen (or fix themselves) without him relaying
commands between Claude and the Termius Claude". He approved exactly: "Release service. I build it
tonight, switched off. It only deploys once you've said who holds deploy authority." (DEC-067).

**Where it stands.** Built and tested in the repository (`app/release/`, `deploy/release/`).
**Not installed** on the server, and **off** by default twice over: `CLIVE_RELEASE_ENABLED` is off,
and `CLIVE_RELEASE_RULE` is `off` until George names who holds deploy authority. Production keeps
being deployed by hand until both are set and the unit is installed.

---

## What it does on each tick

1. **Off, or no rule named:** it writes one status line ("The release service is off…") and stops.
   It does not read GitHub or touch the checkout.
2. **Halted** (an earlier rollback failed): it says so and stops, until a person removes
   `/var/lib/clive-release/HALT`.
3. **One at a time:** it takes `/var/lib/clive-release/deploy.lock`. A tick that finds it held does nothing.
4. **Reads the facts, changing nothing on production** (`app/release/facts.py`):
   - `clive/trunk`'s head, fetched into the service's own copy of the repository
     (`/var/lib/clive-release/repo.git`), never into production's checkout;
   - what production runs, from git in `/opt/crooks-os` (never from a document), and whether that
     checkout has local changes;
   - that production is behind the trunk's head on the trunk (a forward move only), and which paths
     the change touches;
   - GitHub `acceptance` on exactly that SHA, by the gate the build loop already uses
     (`app/orchestrator/github_acceptance.py`): every acceptance run for the SHA completed with
     success, and its acceptance job ran on that SHA;
   - the authorisation George's rule asks for (below).
5. **Decides** (`app/release/decide.py`). It deploys only when every one of these holds; each that
   does not is a sentence in the status line and the journal:
   - switched on, a rule named, not halted, running from its pinned copy, the lock free;
   - every fact read; the SHA is `clive/trunk`'s head; production is behind it on the trunk;
   - production's checkout is clean;
   - the change does not touch how CLIVE is installed: `deploy/`, the `Makefile`,
     `scripts/install_systemd.py`, `scripts/launch_common.py`, `pyproject.toml` or any `.env` file.
     Those stay hand deploys, because `make install` installs no dependency and a program cannot
     judge, as a person can, whether a change to the installer is harmless;
   - the SHA was not tried and rolled back before;
   - acceptance green on the exact SHA, and the authorisation.
6. **Dry run** (`CLIVE_RELEASE_DRY_RUN=true`): it says "Dry run: it would deploy “…” now. Nothing
   was changed." and stops.
7. **Deploys** (`app/release/deploy.py`), the hand procedure as code:

   | Stage | What it does | On failure |
   |---|---|---|
   | Before anything changes | production still on the SHA it read, checkout clean; the checkout and the unit folder writable; `make doctor`; `tailnet_self_check()`; `/health` well (read as the server's own reader, `scripts/healthcheck.py --json`); the live unit saved to `/var/lib/clive-release/deploys/<sha8>/unit-before.service`; `.env`'s and the drop-ins' fingerprints taken; the unit `make install` would write (`scripts/install_systemd.py --print`) byte-identical to the live one, as the `b33ccbc2` deploy checked by hand; the target's objects fetched into the checkout | refuses; nothing changed; tried again next tick |
   | The change | `git checkout --detach <sha>`; the new build's `scripts/gap_clean_check.py`; `make install`, run with the `HOME` and `PATH` the live unit was rendered with, so the re-rendered unit comes out the same | rolls back |
   | After | wait 20 s; `/health` well with no check that was ok before now not ok; the service `active (running)` with no restart; `.env` and the drop-ins untouched; the journal since the restart free of tracebacks, `ERROR`/`CRITICAL`, `withheld`, `not confirmed on disk` and the process exiting | rolls back |

   **Rollback:** the previous SHA checked out again; when `make install` ran, the saved unit put
   back, `systemctl daemon-reload` and `make install` on the previous SHA; then `/health` read
   again. The SHA is marked in `/var/lib/clive-release/failed/` and is not tried again on its own.
   **A rollback step that fails** writes `/var/lib/clive-release/HALT`, and the service does nothing
   more until a person has looked at production and removed that file.
8. **Records** (`app/release/record.py`): the deploy record, in the shape of
   `reports/deploy-<sha8>.md` (rollback target, authority, every check, the installer's own status
   lines, verification, what is outstanding, the trunk commits it carries). It is kept in
   `/var/lib/clive-release/deploys/<sha8>/` and pushed as one commit on top of the SHA to the branch
   **`claude/deploy-<sha8>-record`**, ready to merge like the hand records. A rollback's record is
   `deploy-<sha8>-rolled-back.md`, a name `scripts/map.py` never takes for production. The record
   holds no journal line, no `/health` detail and nothing a customer wrote: the repository is public.
9. **Tells George** (below).

**Still outstanding after every deploy: his phone `/whoami`**, exactly as in DEPLOY_LINUX.md. The
deploy is kept once that line appears; the status line says so.

## What it never does

- Deploy anything but `clive/trunk`'s head, or move production backwards or sideways.
- Change `.env`, a credential, the CLIVE loop's unit, the door, or the procedure in DEPLOY_LINUX.md.
- Run from the checkout it deploys. It runs from its own pinned copy (`/srv/clive-release/pin`); a
  deploy can never change the program that decides the next one. Its code refuses to deploy if it
  finds itself inside `/opt/crooks-os`. Moving the pin is a person's act, after review.
- Push anything but a `claude/deploy-<sha8>-record` branch (`app/release/github.py`
  `record_refspec`, the one way it pushes).
- Print, record or push its token. The token reaches git through an environment variable read by a
  credential helper, never an argument; every printed or recorded text is scrubbed of it.
- Give the model anything. No tool and no route reach it; CLIVE only reads its status file.

---

## The decision George must make: who holds deploy authority

`CLIVE_RELEASE_RULE` in `/etc/crooks-os/release.env`. Until it names one of these, nothing deploys.
Under either, acceptance must be green on the exact SHA, and only the trunk's head, forward, is
deployed.

### `exact_sha_review`: an independent review of exactly that SHA

What `DEPLOY_LINUX.md` still says every deploy needs. The service deploys when a reviewer's record
for that exact SHA says **SHIP** with nothing blocking, measured against what production runs (or a
SHA behind it). The record is a file on a branch:

- branch `claude/review-<sha8>-record`, file `crooks-assistant/reports/review-<sha8>.json`:

```json
{"schema": "clive.release.review.v1",
 "sha": "<40 hex: the trunk SHA to deploy>",
 "base_sha": "<40 hex: what production ran when it was reviewed>",
 "verdict": "SHIP", "blocking": [],
 "reviewer": "<who reviewed>", "reviewed_at": "2026-10-08T09:00:00Z",
 "rule": "regression-only (OWNER_DECISIONS_2026-09-30)", "summary": "<one line>"}
```

**What this hands over:** deploy authority goes to whoever can push a branch to the repository:
the Director's review sessions today, and anything else holding a push credential. The trunk is
unprotected, so a push credential can already change the trunk; under this rule it can also put
that change on production, without George. No tap from him per deploy.

### `owner_waiver`: George's own waiver of the review, for exactly that SHA

How the last three deploys were made (`66d3e05d`, `cac1a9e7`, `b33ccbc2`). The service deploys when
George has waived the review for that exact SHA, in one of two forms:

- **Today, on the server.** At his word, the Termius Claude runs one line (below). The file goes into
  a root-only folder, and is believed only from there.
- **Next, with his passkey, in CLIVE** ("deploy the latest", below). The waiver carries his passkey's
  own signature over a challenge bound to this repository and this exact SHA; the service checks
  that signature itself against his registered public key, so a tap for one SHA cannot deploy another.

**What this keeps:** nothing reaches production without a gesture of his. One gesture per deploy.

**Recommendation:** `owner_waiver`. It is the rule the last three deploys actually followed, it keeps
the standing rule that nothing changes without his gesture, and the passkey step turns the relay into
one tap on his phone. `exact_sha_review` suits a day when reviews are routine and he trusts every
push credential with production.

---

## How George turns it on

Two halves: the Termius Claude installs it (off), and George sets the switches.

### 1. Install, switched off (the Termius Claude, as root on `crooks-os-prod-1`)

Once this branch is merged, `SHA` is the trunk SHA that carries `app/release/`. The unit names the
token, so it cannot start without it: if George has not made the token yet (step 2), stop after the
pinned copy and come back.

```bash
SHA=<the 40-character clive/trunk SHA that carries app/release>
cd /opt/crooks-os && git fetch origin clive/trunk
git merge-base --is-ancestor "$SHA" origin/clive/trunk && echo "on the trunk"

# The pinned copy of the service's own code: an exact SHA, unpacked, never a checkout.
install -d -m 0755 "/srv/clive-release/$SHA"
git -C /opt/crooks-os archive "$SHA" | tar -x -C "/srv/clive-release/$SHA"
ln -sfn "/srv/clive-release/$SHA" /srv/clive-release/pin

# Its own GitHub token (step 2 makes it), encrypted for this host, apart from CLIVE's credentials.
install -d -m 0700 /etc/crooks-os/release /etc/crooks-os/release/waivers
read -rs TOKEN && printf %s "$TOKEN" | systemd-creds encrypt --name=clive_release_github_token - \
  /etc/crooks-os/release/clive_release_github_token.cred && unset TOKEN
chmod 0600 /etc/crooks-os/release/clive_release_github_token.cred

# The switches, exactly as shipped: off, no rule, dry run.
install -m 0600 /srv/clive-release/pin/crooks-assistant/deploy/release/release.env.example /etc/crooks-os/release.env

# The unit and its timer.
install -m 0644 /srv/clive-release/pin/crooks-assistant/deploy/release/clive-release.service /etc/systemd/system/
install -m 0644 /srv/clive-release/pin/crooks-assistant/deploy/release/clive-release.timer /etc/systemd/system/
systemctl daemon-reload

# One tick by hand: it must say it is off, and nothing else.
systemctl start clive-release.service
journalctl -u clive-release.service -n 5 --no-pager        # "The release service is off. Deploys are done by hand."
cat /var/lib/clive-release/status.json                      # "state": "off"

# What it would do now, if it were on: changes nothing on production, pushes nothing, writes no
# status; it only refreshes its own copy of the repository in /var/lib/clive-release/repo.git.
cd /srv/clive-release/pin/crooks-assistant && \
  /opt/crooks-os/crooks-assistant/.venv/bin/python -m app.release --env /etc/crooks-os/release.env plan

systemctl enable --now clive-release.timer
```

CLIVE's Builds screen then reads "The release service is off. Deploys are done by hand." Before the
install it reads "The release service is not installed on this server, so deploys are done by hand."

### 2. The token (George, on github.com)

Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate:
resource owner **crooksldn-pixel**; **Only select repositories: clive**; repository permissions
**Actions: Read-only**, **Contents: Read and write** (Metadata: Read-only comes with it); nothing else;
an expiry he will notice (90 days). He pastes it at the `read -rs TOKEN` prompt above.

GitHub cannot limit "Contents: write" to some branches for a token. The narrowing to
`claude/deploy-*-record` is the service's own code (`record_refspec`), tested. Without the token the
service still reads the public repository, but cannot push its records (each stays in
`/var/lib/clive-release/deploys/`), and the unit will not start, because it names the credential.

### 3. The switches (George)

In `/etc/crooks-os/release.env`:

```
CLIVE_RELEASE_ENABLED=true
CLIVE_RELEASE_RULE=owner_waiver          # or exact_sha_review: his decision, above
CLIVE_RELEASE_DRY_RUN=true               # for the first days: compare its plan with a hand deploy
```

Then, when its dry-run lines have matched what a hand deploy would have done, `CLIVE_RELEASE_DRY_RUN=false`.
The next tick reads the file; nothing restarts.

### Giving a waiver today

At George's word, on the server:

```bash
cd /srv/clive-release/pin/crooks-assistant && /opt/crooks-os/crooks-assistant/.venv/bin/python \
  -m app.release waive <the 40-character SHA> --by George --words "<what he said>"
```

The next tick (at most five minutes) deploys it if everything else holds.

### Turning it off

`CLIVE_RELEASE_ENABLED=false` in `/etc/crooks-os/release.env` (the next tick stops), or
`systemctl disable --now clive-release.timer`. To remove it: also
`rm /etc/systemd/system/clive-release.{service,timer} && systemctl daemon-reload`.

### After a halt

Look at production (`make status`, `scripts/healthcheck.py -v`, `git -C /opt/crooks-os rev-parse HEAD`),
put it right by hand with the record's rollback lines (`/var/lib/clive-release/deploys/<sha8>/`), then
`rm /var/lib/clive-release/HALT`. A SHA that rolled back is retried only after
`rm /var/lib/clive-release/failed/<sha>.json`.

### Moving the pin

A new version of the service is a new pinned copy: the same three `SHA=…`, `archive` and `ln -sfn`
lines with the new SHA, after its own review. Nothing else changes.

---

## How George is told

- **CLIVE's Builds screen**, under the heading: the service's own line, how long ago, and a dot
  (blue: deploying, waiting, or deployed and waiting for his phone check; steel: production runs the
  trunk's latest; red: rolled back or halted; a ring: off, no rule, or not installed). Read from
  `/var/lib/clive-release/status.json` (`app/release/status.py`, `app/builds/read.py`,
  `web/builds.js`). Read-only: nothing on the screen can start or stop a deploy.
- **The record branch** `claude/deploy-<sha8>-record` on GitHub, and `journalctl -u clive-release`.
- **Not yet: a push to his phone.** CLIVE has no push channel: `web/notify.js` decides where a message
  sits on a page that is open, and the service worker (`web/sw.js`) has no push handler. When the
  messaging work (WeCom, and later WhatsApp) lands, one message per deploy outcome is the natural next
  step; the line it would send is the status line, as written.
- **Screens:** after a deploy, every open CLIVE page reloads itself onto the new build at rest
  (`X-Clive-Build`, DEPLOY_LINUX.md), so the new build is on his phone without his doing anything.

## How it ties to CLIVE: "deploy the latest", with his passkey

The next build, on CLIVE's side only; nothing more on the server:

1. George says "deploy the latest" (or taps the Builds line). Every sentence is a model turn, and the
   model has no deploy tool and gets none. CLIVE draws a card from what it can read: the trunk head's
   title, the commits since production, GitHub acceptance on that exact SHA. **Hold to deploy.**
2. His hold opens the passkey prompt from an owner-only route (for example `POST /release/waive`),
   not a tool. The route asks `app/connections/passkeys.py` for an approval whose challenge is
   `app/release/authority.py` `waiver_challenge(repository, sha, nonce)`; that needs one small change
   there, an approval that takes the caller's challenge instead of a random one.
3. On Face ID, the route verifies the approval as every Connections change is verified, and writes
   the waiver, with the assertion inside it, to
   `/var/lib/crooks-assistant/objectives/release-waivers/<sha>.json`: CLIVE's own state folder, which
   it can already write, so no unit changes.
4. Within five minutes the service reads it, verifies the signature itself against his registered
   public key (`/etc/crooks-os/secrets/app/passkeys.json`), and deploys. The Builds line follows it,
   and ends with "Open /whoami on your phone to keep it."

The waiver format and the service's verification are built and tested now
(`tests/test_release_service.py`, the passkey cases); only steps 1 to 3 remain.

---

## Files

| File | What it is |
|---|---|
| `app/release/` | the service (its `__init__.py` lists each module) |
| `scripts/release.py` | the same command line as `python -m app.release` |
| `deploy/release/clive-release.service`, `.timer` | the unit and its timer, installed only by the steps above |
| `deploy/release/release.env.example` | the switches as shipped: off, no rule, dry run |
| `/etc/crooks-os/release.env` | the switches on the server (George's) |
| `/etc/crooks-os/release/` | the encrypted token and the root-only `waivers/` folder |
| `/srv/clive-release/pin` | the pinned copy the unit runs |
| `/var/lib/clive-release/` | its state: `status.json`, `deploy.lock`, `repo.git`, `deploys/<sha8>/`, `failed/`, `HALT` |
| `tests/test_release_service.py`, `tests/test_release_service_git.py` | every condition, failure point and rollback on a fake server; the git it runs, on real git |

The unit runs as root (it runs `make install`, which writes the crooks-assistant unit and restarts
it), under `ProtectSystem=strict` with only `/opt/crooks-os`, `/etc/systemd/system` and its own state
writable, `ProtectHome=read-only`, `NoNewPrivileges` and `PrivateTmp`. Before changing anything, each
deploy checks it can write what it must (`access(2)` sees a read-only mount), so a confinement too
narrow is a refusal with nothing changed, never a half-made deploy.
