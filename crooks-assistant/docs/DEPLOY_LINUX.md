# CROOKS OS on Linux

The Mac is still the Mac. This describes the Ubuntu server that runs the same code as a
service, so the assistant is up when the Mac is not, and says plainly which parts of the
macOS deployment do not exist here and why that is deliberate.

Everything below is the *production* host `crooks-os-prod-1`. Nothing here changes the Mac,
and the Mac remains the rollback path: it has its own checkout, its own launchd agents, its
own Keychain and its own Tailscale address, and none of them are touched by any of this.

---

## What is different from the Mac, and why

| | Mac | This server |
|---|---|---|
| Supervision | launchd LaunchAgents (`launchd/`) | systemd unit (`deploy/systemd/`) |
| Starts at | login | boot |
| Secrets | login Keychain | systemd encrypted credentials + a root-only 0600 directory |
| Logs | `logs/*.log` + launchd's own files | `journalctl -u crooks-assistant` + the same `logs/assistant.log` |
| Local speech fallback | whisper.cpp with Core ML | **not deployed** — see below |
| Menu-bar app | CROOKS Control | not applicable; `crooks-control` on the command line still works |

Both are reached through the same `make` targets. The Makefile picks by platform.

---

## Speech: there is no local fallback here, on purpose

On the Mac, ElevenLabs Scribe hears you and whisper.cpp is the automatic fallback when Scribe
is slow, rate-limited or down. This server has no whisper.cpp: building it needs a toolchain
and a model, and the Apple Neural Engine it was tuned for does not exist on this hardware.

So the server is configured with `CROOKS_WHISPER_ENABLED=false`, and that setting does one
thing: it tells the truth about the arrangement.

* `/health` reports whisper as **disabled**, not failed — the distinction matters, because a
  check that is permanently red is a check nobody reads.
* It does **not** make the top-level status `degraded`. A machine that was never given a
  fallback is not a broken machine.
* It does **not** suppress a real failure. `checks["speech"]` still tells the truth: Scribe
  working is healthy, and **Scribe down with no fallback is unhealthy** — on the Mac that
  same outage would be a slower assistant, here it is a deaf one, and `/health` says so.
* The Core ML probe is skipped, because there is nothing to probe.

`checks["speech"]` carries `redundancy: "none"` on this host and `"whisper"` on the Mac, so
the absence of a fallback is a visible fact about the deployment rather than something you
have to know.

If local speech is ever wanted here, build whisper.cpp, set `CROOKS_WHISPER_ENABLED=true`,
and the behaviour returns to the Mac's exactly.

---

## Secrets

There is no Keychain. `app/secrets/keychain.py` keeps the same public surface — `get`,
`get_optional`, `set_secret`, `delete`, `present` — and dispatches on the platform, so no
calling code knows the difference. Underneath, on Linux, there are two tiers, and which tier
a secret belongs in is decided by one question: **does the running application ever write
it?**

### Static — encrypted credentials

`elevenlabs_api_key`, `shopify_client_id`, `shopify_client_secret`, `shopify_static_token`,
`claude_oauth_token`.

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
* writes to the store and the inbox stay off (`CROOKS_WRITES_ENABLED=false`).

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

`crooks-update` runs the same eight stages it runs on the Mac; only stage 7 differs, and it
restarts the systemd unit instead of kicking the launchd agents. It is still fast-forward
only, still refuses on a dirty tree, and still has no `--force`.

## Health

```bash
python scripts/healthcheck.py        # exit 0 healthy, 1 not; one line either way
python scripts/healthcheck.py -v     # every check
```

`/ping` is the cheap one — no external call, never cached — and `/health` is the real one.

## Rolling back to the Mac

Nothing to undo here, but if the server is to stop answering:

```bash
make uninstall           # stop, disable, remove the unit
tailscale serve reset    # drop the HTTPS route
```

The Mac's own deployment was never touched: its checkout, its launchd agents, its Keychain
and its Tailscale address are exactly as they were.
