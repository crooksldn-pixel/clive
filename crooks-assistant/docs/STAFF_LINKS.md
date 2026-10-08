# Staff links: the team joins with a link and a code

Ruling 35 of DEC-071 ("Staff join with a link and a code instead of Tailscale? Y"), built as DEC-075.
George, before it: staff should "just get a link (e.g. 'send this person a staff link') with a code to
sign up, no app installs". The team are teenagers and low-skill workers on their own phones.

## What George does

1. **Team › People.** Someone new: *Add someone to the team* with their name and what they do (no
   Tailscale login needed). Someone already there: their row.
2. **Make a staff link**, beside their name, and confirm with his passkey. The screen shows, once:
   - the link, `https://team.crooksldn.com/join#…`, with **Share** (the phone's share sheet: WhatsApp,
     Messages) and **Copy**;
   - a six-digit **code**, in big type, and when the link stops working (12 hours).
   Neither is ever shown again: the server keeps only their hashes. Lost it? Make another; the old one
   stops working at once.
3. **He sends the link and tells them the code himself**, out loud or in another message. The two
   apart is the point: a link forwarded or seen over a shoulder is no use without the code.
4. They open the link, type the code, and are on Today, as themselves, with exactly the team's tools.

Asking CLIVE ("send Emily a staff link") gets the same answer in words: the link is made on Team ›
People with his passkey. CLIVE never makes one in a conversation, because the link and the code
would then pass through the model and its records.

**Taking it back.** On People, *Sign out* beside a phone signs that phone out at the next request.
*Take access away* (his passkey) signs out all of that person's phones, cancels a waiting link, and
closes their Tailscale access too. Taking someone off the list (`person_note` active false) or making
them a contact closes the door the same way. A phone unused for 14 days is signed out by itself, and
every phone needs a new link after 90 days.

## How it works

| Part | Where |
|---|---|
| The links and phones, kept as hashes | `app/people/links.py` → `staff-links.json` beside `access.json` and the passkeys (root-only, 0600) |
| The public door | `app/people/team_door.py`, called first by `app/main.py`'s middleware |
| The join and the owner's link routes | `app/routes/staff_links.py` |
| The join page | `web/join.html`, `web/join.js` |
| George's side | `web/today-owner.js` (People) |
| Who a request is, everywhere else | `app/routes/actions.py` `proxy_state` → `TEAM_DOOR` |

- **The link** is `https://<team host>/join#<token>`: 32 random bytes. The token is after `#`, so no
  browser ever sends it to a server: not to Caddy, not to CLIVE's request log, not in a `Referer`.
  The page reads it and posts it with the code, then goes to Today in its place.
- **The code** is six random digits. The invite is single-use, for one person's card, open for 12
  hours, and locked after 5 wrong codes.
- **The phone's sign-in** is a cookie, `__Host-clive_team`: `HttpOnly; Secure; SameSite=Strict;
  Path=/`, no `Domain` (the `__Host-` prefix makes the browser enforce the last three). Its value is a
  phone id and a 32-byte secret; the server keeps the secret's hash. It is handed out again every hour
  of use (rotation); the one it replaced works for two more minutes (requests already on their way),
  and after that, its use means a copy exists, so that phone is signed out.
- **The door.** A request is the team door's when Caddy marked it (`X-Clive-Door: team`) or it is
  addressed to `CROOKS_TEAM_HOST`. Either is enough, and both only ever narrow what it may reach. The
  door takes Tailscale's headers and CLIVE's local command key off it, so nothing behind can read an
  identity claim from the internet. It answers exactly the routes in `team_door.ROUTES` and 404s
  everything else. Without a signed-in phone it serves only the page shells, their files and the
  join; with one, the request carries the staff authority `for_staff(person, "team:<person>")`
  (`app/tools/authority.py`, unchanged), so the phone gets exactly the team's tools.
- **Tailscale is unchanged.** George's devices and staff already on Tailscale go through the same
  rules as before. A team cookie means nothing on the tailnet address, and a request through the
  team door is never the owner and never "made on the server itself".

## Threat model

What is protected: George's shop, inbox and money (the owner's tools and routes), the customers'
details CLIVE reads, the owner's conversations, and the team's own work list.

Who might attack: anyone on the internet (team.crooksldn.com is public); someone who sees or is
forwarded a staff link; someone who gets hold of a team member's phone or its cookie; a team member
trying to do more than the team may; a web page trying to act through a signed-in phone; a process on
the server.

| Threat | What stops it | Tested in `tests/test_staff_links.py` |
|---|---|---|
| Reaching an owner route (Connections, objectives, Builds, bench, release, admin, the TVs, the hooks, `/whoami`, `/health`) from the internet | The door's exact allow-list: anything else is 404 before any route runs, signed in or not. Caddy's site forwards only the team's paths as a second fence | every route the app serves is walked through the door, with and without a phone |
| Using the team's own owner-only steps (hand out, people, access, links) | Not on the door's list (404); on the tailnet the existing `_owner_only` refusal stands | as above |
| Pretending to be George through the door (a forged `Tailscale-User-Login`, the local key, an `X-Forwarded-For`) | The door strips those headers and marks the request `TEAM_DOOR`, which the owner rule, the write boundary and session binding all refuse as the owner and never treat as local | forged headers through the door |
| Guessing a link | 256-bit tokens; every refusal looks the same (used, expired, cancelled, unknown) | replay, expiry |
| Guessing the code of a real link | 5 wrong codes lock the invite for good; at most 10 failed joins per address per 15 minutes and 200 in all, then joining waits | brute force |
| Using a link twice, or after it is cancelled or expired, or after the person is taken off | Single-use; cancelled when a new one is made or access is taken away; refused if the card is no longer active staff | lifecycle |
| A link and code reaching someone else | The code is never in the message with the link; joining with a new link signs out the person's other phone; George sees every phone and when it was last used, and signs it out | revocation |
| A stolen cookie | `HttpOnly` (no script can read it); rotated hourly; a replaced cookie used after two minutes signs the phone out; 14 days idle and 90 days in all | rotation and replay |
| Another site making a signed-in phone act (CSRF) | `SameSite=Strict`; every POST through the door must carry an `Origin` of the door's own host, and a `Sec-Fetch-Site` other than same-origin is refused | CSRF |
| The link in logs, URLs or referrers | Token in the `#fragment`; the code only in a POST body; nothing of either, nor the cookie, is ever logged; the server stores hashes | logs checked after a whole join |
| A team member doing more than the team may | The phone carries the same staff authority as a Tailscale team member: `app/people/staff.py`'s tools and writes, the commit route's `staff_refusal`, their own assistant | the staff tool set, unchanged |
| A team member reading George's conversation | Sessions bind to `team:<person>`, never to "local" or an owner login | session binding |
| The file of links being read | Root-only directory, 0600; it holds only hashes: no link, code or cookie can be rebuilt from it | — |

### Risks that remain, in plain words

1. **Whoever has the link and the code first gets in.** If George sends both in the same message and
   someone else reads it before his staff member does, they join as that person. Mitigation: send them
   apart; George sees the new phone on People (with "iPhone" or "Android" and when it joined) and can
   sign it out; the real person's join would then fail, and they would ask him.
2. **A phone that is signed in is the person.** Anyone holding an unlocked, signed-in phone can do what
   that team member can, until George signs the phone out. Team members' phones should have a lock.
3. **The team's reach is the team's reach.** Through this door a team member can do exactly what they
   could on Tailscale: read orders, customers' details and the inbox, fulfil, reply to email and
   adjust stock on their own confirmation. This door does not narrow that; DEC-062's rules do.
4. **A cookie stolen and used before the real phone next opens CLIVE** works until the next rotation
   meets the real phone (at most an hour of use), then both are signed out and George sees it.
5. **Being online is the point.** The door is on the public internet: denial of service (flooding
   joins so real ones wait 15 minutes, or load on the server) is possible, as for any public site.
   Caddy and the per-address limit absorb the casual kind.
6. **The rate limits live in memory.** A restart clears the per-address and overall counts (the
   per-link lockout is on disk and survives).
7. **Caddy is trusted** to set `X-Clive-Door` and pass the right `Host`. If the site were edited to
   forward without both, a request from the internet would look like one made on the server itself:
   still refused every owner route unless `CROOKS_LOCAL_OWNER` is on, which production does not set.
   Keep the site block as written below.
8. **The link stays in that phone's browser history**, as any opened link does (no page of CLIVE's
   rewrites the address bar). Once used, locked or run out it is worth nothing.
9. **Phones change cookie jars.** On an iPhone, a link opened inside Instagram's or Facebook's own
   browser, or a home-screen icon added after joining, keeps its own cookies, so the phone shows as not
   signed in there. The join page says to open the link in Safari or Chrome; otherwise George makes a
   new link.

## Server steps (once, on crooks-os-prod-1)

1. **DNS:** an `A` record `team.crooksldn.com` → the server's public IPv4 (the same address as
   `returns.crooksldn.com` and `hooks.crooksldn.com`).
2. **Caddy on the host** (the one that serves `hooks.crooksldn.com`; `ss -ltnp | grep -E ':(80|443) '`
   shows it): add this site beside the hooks one, then `caddy validate --config <its Caddyfile>` and
   `systemctl reload caddy`:

       team.crooksldn.com {
           header Strict-Transport-Security "max-age=31536000"
           request_body {
               max_size 1MB
           }
           @team path / /join /today /today/* /turn /actions/* /static/*
           handle @team {
               reverse_proxy 127.0.0.1:8000 {
                   header_up X-Clive-Door team
                   header_up -Tailscale-User-Login
                   header_up -Tailscale-User-Name
                   header_up -Tailscale-User-Profile-Pic
                   header_up -X-Crooks-Local-Key
               }
           }
           handle {
               respond 404
           }
       }

   The paths are a coarse fence; CLIVE's door holds the exact list. If the only Caddy is the one inside
   the CROOKS Returns container, it cannot reach the host's 127.0.0.1: put this site where the hooks
   site went, and do not change how CLIVE binds.
3. **CLIVE's `.env`:** add `CROOKS_TEAM_HOST=team.crooksldn.com`, then `systemctl restart
   crooks-assistant`. Without it, CLIVE refuses to make a link ("the team's address is not set").
4. **Check from outside the tailnet** (mobile data):
   - `curl -si https://team.crooksldn.com/today` → `200` and the page;
   - `curl -si https://team.crooksldn.com/today/state` → `401` `signed_out`;
   - `curl -si https://team.crooksldn.com/connections` → `404`; `curl -si https://team.crooksldn.com/health` → `404`;
   - `curl -si -H 'Tailscale-User-Login: <George's login>' https://team.crooksldn.com/objectives` → `404`.
5. **Then a real join:** George makes a link for himself as a test person on People, opens it on a
   phone on mobile data, enters the code, sees Today, and signs that phone out on People.
