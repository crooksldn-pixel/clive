# Connections

The owner adds, tests and removes CLIVE's keys and sign-ins from the app, at `/connections` on CLIVE's own address. He no longer needs a terminal for them.

The owner's decision of 1 October 2026, given in the review session:
- keys may be stored from the app, not only typed at a server prompt: "yes";
- every change asks for a passkey at that moment: "yes".

## What the screen shows

The screen is grouped by what you have to do, not by how each connection is built (redesigned 2 October 2026):

- **Needs you**: anything broken, running out or failing its test, each with the one thing that puts it right: a box for the key the service refused, *Sign in again* for an Instagram sign-in that is running out, or *Check again* when the service only did not answer.
- **Working**: one quiet row each, saying what it lets CLIVE do and "Connected · checked 2 min ago". No key box. Tap the row for its details: what it unlocks (the capability families' own names and states), what stops without it, the account, where the key is kept, the last check, and *Check now*, *Replace key* and *Disconnect*. ElevenLabs' details hold the voice: the picker, the sliders, Preview and Save.
- **Not connected**: what you could add. Its key box appears only when you tap *Connect*. Gmail says it connects at the server for now.
- **Passkeys** and **Recent changes** come last.

Opening the screen asks every connected service again with the same tests as *Check now* (`POST /connections/check`), at most once a minute for each however many devices open it. The tests read only and spend nothing (`app/connections/testers.py`); Gmail is asked as `/health` asks it.

## Using it

1. **Open the screen.** It is CLIVE's address followed by `/connections`, on your phone: `https://<your CLIVE>.<your tailnet>.ts.net/connections`. Add it to the home screen if you like.
2. **Set up your passkey** (Face ID, a fingerprint or the device PIN), once per device.
   - Set up the first one on **your own phone**, before anything else: until one exists, the screen lets the first device that opens it make one. Every later one is approved by a passkey you already have, and the server itself can never make one or approve a change.
   - **Not on a shared tablet.** A passkey on the shop tablet approves with that tablet's PIN, so anyone who knows it could change a key or let someone onto the team. Keep passkeys on devices only you unlock.
   - The iPhone and the iPad share passkeys through iCloud Keychain.
3. **Paste a key and tap Save.** A box is there only where one is needed: under a connection that needs you, after *Connect*, or after *Replace key* in a working one's details.
   - Your passkey is asked for.
   - CLIVE then tests the key with the service, and stores it only if it works.
   - It is live at once, with no restart.
   - A saved secret is never shown again; an app ID is shown, because it is not a secret.
4. **Check now** asks the service again with what is stored. It changes nothing, so it asks no passkey.
5. **Disconnect** asks your passkey. CLIVE stops using the key at once, even where the server still holds an older copy.
6. **Sign in with Instagram.**
   - Save the Instagram app ID and app secret on the card, once.
   - Add the address shown on the card to the Meta app: Instagram → API setup with Instagram login → Business login settings → OAuth redirect URIs.
   - Then tap *Sign in with Instagram*. Instagram's own page asks you to approve, and you come back connected; CLIVE renews the token itself.
7. **Recent changes** lists every change, made or refused, with the device it came from. If you see one you did not make, remove that passkey and disconnect what it touched.

CLIVE itself never takes a key. Its prompt sends you to this screen, and stops you if you start to say or paste one, because whatever reaches it is written down.

## What happens to a key

- **Encrypted on this machine.** It is kept in `/etc/crooks-os/secrets/app/<key>.cred`, encrypted with `systemd-creds`, the same machine-bound key systemd uses for the static secrets (`app/secrets/vault.py`).
  - The plain value is never on the disk, and never in a process's arguments: it goes in on stdin.
  - A copy of the file taken off the machine is useless.
- **The app's choice wins.** Reads ask the app tier first, then the systemd credentials, then the plain 0600 files (`app/secrets/linux_store.py`).
  - Storing a key at the server prompt (`scripts/provision_secrets.py`) clears the app tier first, so the latest choice wins whichever way it was made.
- **Renewals land where the next read looks.** A token CLIVE renews itself (Instagram's) is written back to the app tier.
- **An unreadable key is absent.** If this machine can no longer decrypt a key (a new TPM state, a restored disk), it reads as absent, never as an older key underneath it. The card says to save it again.
- **Never sent back, never logged.** The screen's answers, the record of changes and every log line carry key names, never values. The access log drops the query of every Connections route, so a sign-in's one-time code never reaches the journal.

## What protects a change

- **The door** (`app/main.py`): only the owner's own device on the tailnet reaches these routes.
- **A passkey for exactly that change** (`app/connections/passkeys.py`). Each approval must:
  - answer a challenge the server issued for that one action;
  - be used once, within three minutes;
  - come from CLIVE's own https Tailscale address;
  - be signed by a registered passkey, after Face ID, a fingerprint or the PIN (user verification is required).
  - A passkey's signature counter, when it keeps one, may only go up.
- **A test before a key replaces the one in use** (`app/connections/testers.py`). The key travels in a header or a body, never in an address, and no answer quotes it back.
- **The record** (`app/connections/ledger.py`): every change, shown on the screen.
- **No tool.** The model has no tool that reads or writes a key.
- **The protected list.** `app/secrets`, `app/connections`, the route, the server prompt and their tests are on PROTECTED_PATHS, so the loop's builders cannot weaken them.

## After deploying

- **Open `/connections`.** If it says "This server can't keep keys for the app yet: …", `systemd-creds` could not run inside the service. The reason shown is what to fix. Nothing is stored until then.
- **Using another name for CLIVE.** If you reach CLIVE at an address other than its `*.ts.net` name, set `CROOKS_PUBLIC_ORIGIN` to that address. A passkey is bound to the address it was made at.
- **Adding a new service.** Its keys are added to `app/secrets/keychain.py` (KNOWN_KEYS), and its card and test to `app/connections/catalog.py` and `testers.py`.

## Not yet

- **Sign in with Google.** The Gmail row says Gmail is set up at the server for now (`make gmail`). Google sign-in from the screen needs: the Google Cloud OAuth client's ID and secret stored as two new keys; this CLIVE's `https://<name>.ts.net/connections/google/callback` added to that client's authorised redirect URIs; and the consent screen published (an app left in Testing gets 7-day tokens). Then the same pattern as Instagram's sign-in: a passkey-approved start, the callback storing the authorised-user JSON as `gmail_token` in the app tier.
- **Install the Shopify app from the screen.** Shopify connects with the CLIVE app's client ID and secret (the client-credentials grant), which only work for an app released and installed in the shop's own organisation. An install button would need the app's OAuth redirect URL set to this CLIVE's `https://<name>.ts.net/connections/shopify/callback` in the Shopify Dev Dashboard, the scopes listed in `SHOPIFY_SCOPES.md` requested there, and a token-exchange callback; until then the screen asks for the ID and secret only when they are missing or refused.
- **A phone notification when a key changes.** CLIVE has no delivery channel yet; the record is on the screen.
- **On a Mac.** Keys stored from the app go to the login Keychain, which the system already encrypts.
- **Clients' own connections** (IDEA-038). Each client's CLIVE cannot be a sign-in return address for the providers, so that needs one public sign-in service.

## Code

| What | Where |
|---|---|
| The screen | `web/connections.html`, `connections.js` (asks and acts), `connections-view.js` (draws the rows), `connections.css` |
| Its routes | `app/routes/connections.py` |
| Store, test, disconnect, record | `app/connections/service.py`, `ledger.py` |
| What can be connected | `app/connections/catalog.py` |
| A key's live test | `app/connections/testers.py` |
| Passkeys | `app/connections/passkeys.py` |
| Sign in with Instagram | `app/connections/instagram.py` |
| The app tier of the secret store | `app/secrets/vault.py`, read through `linux_store.py` |
| Tests | `tests/test_connections_*.py` (the page's purpose: `test_connections_page.py`; in Chromium: `test_connections_browser.py` with `scripts/browser/connections.js` and `tests/connections_world.py`), `tests/web/connections.test.js`, `tests/test_secrets_vault.py`, `tests/fake_passkey.py` |
