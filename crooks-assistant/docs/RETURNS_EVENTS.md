# CROOKS Returns rings CLIVE: `/hooks/returns`

The owner's ruling 20 of 8 October ([DEC-071](product-memory/DECISIONS.md)): CROOKS Returns posts its
events to CLIVE through the public hooks door, `hooks.crooksldn.com`. What was built is
[DEC-077](product-memory/DECISIONS.md).

**The post is a doorbell, not the record.** It says which return changed and how. CLIVE then reads
that return through the service's API with its own read key, and everything George sees comes from
that read.

## What happens

1. Something changes a return in the service: a customer asks, staff approve, a label fails, Shopify
   doesn't move the money, the timer flags a label overdue. Each event the return records gets one
   row in the service's outbox, written in the same transaction as the return
   (`crooks-returns/returns/store.py`).
2. The service's doorbell (`crooks-returns/returns/doorbell.py`), on its own thread, posts each row to
   `RETURNS_CLIVE_WEBHOOK_URL`. The body is exactly:

       {"id":"evt_…","type":"label_bought","return_id":"ret_…","at":"2026-10-08T12:00:00+00:00","sent_at":1791460800}

   There is no customer's name, email, address or order in it. It is signed
   `X-Crooks-Returns-Signature: sha256=<hex HMAC-SHA256 of the raw body>` with
   `RETURNS_CLIVE_WEBHOOK_SECRET`. A post that is not answered with a 2xx is tried again after 30 s,
   then 1, 2 and 4 minutes, and so on, at most an hour apart, for a day. It never blocks or fails the
   person acting.
3. CLIVE's door (`app/routes/returns_hook.py`, `app/returns/events.py`) checks it, in this order:
   - the body is at most 4 KB (it is refused before it is read whole);
   - the events secret is stored;
   - the signature matches, compared in constant time, before the body is decoded;
   - the body has exactly those five fields, in their shapes;
   - `sent_at` is within five minutes of CLIVE's clock;
   - the event id has not been seen before (the last 10,000).

   Anything else gets 403 with an empty body. A repeat gets 200 and is dropped. The door carries no
   authority: no tool runs from it.
4. An accepted event marks CLIVE's copy of the open returns stale and reads them again through the
   API, so the home's Needs you row and the next returns card are fresh.
5. Some events can make a return need George: one to approve, a parcel delivered back unchecked, a
   return received that needs a decision, a label overdue or failed, money that didn't move, an
   approval or cancel that failed. For those CLIVE also reads that return. If the read says it
   needs him for that reason, the home shows a notice that stays until he dismisses it, for example:
   - "Note · Return on #2131: waiting for your approval."
   - "Failed · Return on #2132: Shopify didn't move the money."

   Each notice is shown once on each device. It names the order, never the customer. It goes away
   once the open returns no longer say so.

Without the events secret, or before the service is set up, nothing changes from before: CLIVE asks
the service at most once a minute while someone is using it.

## Settings

**CROOKS Returns** (`/opt/clive/crooks-returns/.env`, then `docker compose up -d` in that folder):

    RETURNS_CLIVE_WEBHOOK_URL=https://hooks.crooksldn.com/hooks/returns
    RETURNS_CLIVE_WEBHOOK_SECRET=<openssl rand -hex 32>

**CLIVE**: on the Connections screen, open CROOKS Returns and paste the same secret as the "Events
secret". Get it with `grep CLIVE /opt/clive/crooks-returns/.env`; a whole `RETURNS_CLIVE_WEBHOOK_SECRET=…`
line is accepted as it is. It is stored like the read and write keys, as `crooks_returns_hook_secret`,
and it can also be provisioned with `scripts/provision_secrets.py` (`docs/DEPLOY_LINUX.md`). The
card's Test then says whether the service is sending its events, and whether CLIVE has the secret to
check them with.

**The public address**: `hooks.crooksldn.com` must forward `/hooks/returns` to CLIVE (127.0.0.1:8000)
as it forwards the other doors. With Caddy, add one line to the site in `docs/WECOM.md` section 4:

    hooks.crooksldn.com {
        handle /hooks/wecom { reverse_proxy 127.0.0.1:8000 }
        handle /hooks/whatsapp { reverse_proxy 127.0.0.1:8000 }
        handle /hooks/instagram { reverse_proxy 127.0.0.1:8000 }
        handle /hooks/returns { reverse_proxy 127.0.0.1:8000 }
        handle { respond 404 }
    }

The returns service runs in a container on the same host and posts to that public name. If the
hooks site is served by the Caddy inside the returns compose project, that Caddy cannot reach the
host's 127.0.0.1 (`docs/WECOM.md` section 4 says the same). Run the hooks site in a proxy on the host,
or decide how the app is reached before turning this on.

## Deploy order

1. **CLIVE first**, with this change, and the events secret stored on Connections. Until the
   service posts, nothing changes.
2. **The public address**: add `/hooks/returns` to the `hooks.crooksldn.com` site. Check from outside
   the tailnet: `curl -si -X POST https://hooks.crooksldn.com/hooks/returns` answers `403` with an
   empty body.
3. **CROOKS Returns last**, with branch `claude/n3-service-events` and the two settings above. Every
   event recorded from then on is posted. Events recorded before the URL was set are not sent,
   because CLIVE reads those itself as before.
4. **Check it**: `docker compose exec returns returns-ctl doorbell` shows how many events are
   waiting, delivered and given up, and the last answer CLIVE gave. A 403 there means the two
   secrets differ or the clocks are more than five minutes apart. A 404 or 502 means the address is
   not forwarding `/hooks/returns`. Then bump `tests/returns_service.py` `SERVICE_SHA` to the deployed
   commit, so `tests/test_returns_events_contract.py` runs the service's own doorbell against CLIVE's
   door in acceptance.

Rollback: unset `RETURNS_CLIVE_WEBHOOK_URL` and restart the service. Nothing is posted, and CLIVE goes
back to asking.
