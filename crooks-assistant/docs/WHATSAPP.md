# WhatsApp: how CLIVE reads and answers WhatsApp

George approved WhatsApp on 7 October, beside WeChat: ready to switch on when he stores its keys,
every outgoing message on his hold. He did not say who it is for or which number, so it is built
for either: a supplier or a customer who writes to the CROOKS WhatsApp number is a conversation in
CLIVE, in English with the original kept, and is answered on his hold. **Section 1 is what he has
to decide.** The rest is what he sets up at Meta, what it costs and what CLIVE does.

It runs on Meta's own **WhatsApp Business Cloud API** (graph.facebook.com), with no partner or
middleman. The code: `app/clients/whatsapp.py` (every call), `app/messaging/whatsapp.py` (the
channel), `app/messaging/meta.py` (Meta's webhook checks, shared with Instagram),
`app/routes/hooks.py` (the public door, `/hooks/whatsapp`) and `app/tools/messaging_tools.py`
(the same four tools WeChat uses).

| Rule (7 October) | Where it is kept |
|---|---|
| Every outgoing message needs his hold. | `message_reply` is a write at RED: staged, never sent when called; its card is hold-to-arm. |
| Non-English inbound is shown in English, the original one tap away. | Translated when it arrives (`app/messaging/translate.py`), labelled machine translation. |
| "Sent" only when WhatsApp confirms it. | Only WhatsApp's own message id (`wamid.…`) counts; delivered and read come later from WhatsApp itself. |
| Only one public address. | `/hooks/whatsapp`, signature-checked before anything is read; everything else stays behind the door. |

## 1. What George must decide

1. **Who the number is for.** Suppliers (the manufacturer, a mill, the forwarder), customers, or
   both. CLIVE works the same either way. A conversation is linked to a person's card when he
   says who it is ("that's Ana, the knitwear supplier"), and one card can hold the same person's
   WeChat and WhatsApp. If customers are to write here, say so on the site and in emails.
2. **Which number.** The Cloud API needs a number that is **not** signed in to the WhatsApp or
   WhatsApp Business app on a phone at the same time.
   - **A new number just for CROOKS on WhatsApp** (simplest). A SIM or a landline that can take
     one verification code by SMS or a call.
   - **The number CROOKS already uses in the WhatsApp Business app.** Either delete that account
     from the app first (its chat history stays on the phone, not in CLIVE), or keep using the
     app beside the API ("coexistence"), which Meta only offers through a registered Meta
     partner's sign-up flow, not to a business on its own. CLIVE already keeps what someone sends
     from the app on a coexistence number (the `smb_message_echoes` field), so either works if
     he goes that way.
3. **The name people see.** WhatsApp shows the number's display name ("CROOKS LDN") once Meta has
   approved it.
4. **Whether to ever start a conversation, or answer after 24 hours.** WhatsApp only allows that
   with an approved **template** message, and Meta charges for each one. CLIVE doesn't send
   templates; it says so and asks the person to write first. Adding templates would be a new
   decision, with a cost.

## 2. The five values, and where each is

Store them in **Connections → WhatsApp** on CLIVE (or `python scripts/provision_secrets.py <key>`
on the server). **Test** asks Meta what the number can do and says what to do next. The
WhatsApp tools stay switched off until all five are stored.

| Field on CLIVE | Secret store key | Where it is |
|---|---|---|
| Phone number ID | `whatsapp_phone_number_id` | developers.facebook.com → your app → WhatsApp → API Setup: the **Phone number ID** under the number (digits; not the number itself). |
| WhatsApp Business Account ID | `whatsapp_business_account_id` | Same page: **WhatsApp Business Account ID**. |
| Access token (permanent) | `whatsapp_access_token` | business.facebook.com → Business settings → Users → **System users** (section 3, step 4). |
| App secret | `whatsapp_app_secret` | developers.facebook.com → your app → App settings → Basic → **App secret** → Show (32 letters and digits). Meta signs every webhook with it. |
| Verify token | `whatsapp_verify_token` | **Any long random string you choose.** You type the same into Meta in section 3, step 7. |

## 3. Setting it up at Meta, in order

1. **A Meta app.** developers.facebook.com → My Apps → Create app → type **Business**, connected
   to the CROOKS business portfolio. Add the **WhatsApp** product (or the "Connect with customers
   through WhatsApp" use case; then the WhatsApp settings are under Use cases → Customize). The
   same app can be the one that already reads Instagram.
2. **The number.** WhatsApp → API Setup → **Add phone number**: the display name, the category,
   then the code Meta sends by SMS or call. (The test number Meta gives every app can only message
   five numbers you list; use it to try CLIVE, not for real people.)
3. **Register the number for the Cloud API.** Meta only does this by API. On the server, after the
   keys are stored: `python scripts/whatsapp.py register` and type the number's six-digit
   two-step PIN (if it has none yet, the six digits you type become its PIN). `python
   scripts/whatsapp.py check` should then say the status is **CONNECTED**.
4. **A permanent token.** business.facebook.com → Business settings → Users → **System users** →
   Add (an **Admin** system user, or an Employee one given this WhatsApp account) → **Assign
   assets**: the app (full control) and the WhatsApp account (full control) → **Generate token**:
   the app, expiry **Never**, permissions `whatsapp_business_messaging` and
   `whatsapp_business_management` (and `business_management`). It starts `EAA`. Store it at once;
   Meta shows it once.
5. **Store the five values** on Connections → WhatsApp and press **Test**.
6. **The public address** (section 5): `https://hooks.crooksldn.com/hooks/whatsapp`.
7. **Webhooks.** developers.facebook.com → your app → WhatsApp → **Configuration** → Webhook →
   Edit: Callback URL = the address of step 6, Verify token = the same string as on Connections.
   Verify and save (CLIVE answers Meta's check). Then under **Webhook fields**, subscribe
   **messages** (and **smb_message_echoes** only on a coexistence number).
8. **Send the account's webhooks to the app**: `python scripts/whatsapp.py subscribe` on the
   server. Test then says "messages arriving: ready".
9. **App mode: Live** (App settings, top of the dashboard). Meta does not send every webhook to an
   app in Development mode.
10. **Business verification** (Business settings → Security centre) raises how many people the
    number may *start* conversations with, which is about templates; CLIVE's replies don't need it.
    If Meta ever refuses a send over payment (131042), add a payment method in WhatsApp Manager →
    Payment settings; CLIVE says so in those words. Replies themselves are free (section 4).

Then message the number from a phone: the message appears in CLIVE in a few seconds ("any
WhatsApp messages?"), and Test on Connections says each part is ready.

## 4. Costs and limits

- **Replies are free.** Since 1 July 2025 Meta charges per message, and a non-template message
  sent while the 24-hour window is open costs nothing. CLIVE sends nothing else.
- **The 24-hour window.** A reply is possible only within 24 hours of the person's last message;
  each message they send opens it again. Outside it CLIVE refuses before making a card, checks
  again at his hold and refuses there, before anything goes, if it closed in between; WhatsApp's
  own refusal (131047) is said the same way.
- **Templates** (starting a conversation, or after 24 hours) are charged per message and need
  Meta's approval. Not used (section 1, point 4).
- **4,096 characters** per text. CLIVE's own limit (600 characters of English, 600 of their
  language) keeps every reply well under it.
- **Messaging limits** (how many people a number may *start* conversations with a day) and
  **quality rating** apply to templates and to how people react to the number; `scripts/whatsapp.py
  check` shows the quality Meta gives. Sending many messages to one person quickly is refused for a
  moment (131056), and CLIVE says so.
- The **permanent token does not expire**; if it is revoked, Test and every send say so in plain
  words ("Meta refused CLIVE's WhatsApp access token").

## 5. The public address (server side)

Exactly as for WeCom (docs/WECOM.md, section 4), with one more path. With Caddy on the host:

    hooks.crooksldn.com {
        handle /hooks/wecom {
            reverse_proxy 127.0.0.1:8000
        }
        handle /hooks/whatsapp {
            reverse_proxy 127.0.0.1:8000
        }
        handle /hooks/instagram {
            reverse_proxy 127.0.0.1:8000
        }
        handle {
            respond 404
        }
    }

Or Tailscale Funnel, one command per path:
`tailscale funnel --bg --https=8443 --set-path=/hooks/whatsapp http://127.0.0.1:8000/hooks/whatsapp`.
Meta needs a valid HTTPS certificate (not self-signed); both ways give one.

Check from outside the tailnet before saving the URL at Meta: `curl -si https://hooks.crooksldn.com/hooks/whatsapp`
answers **403 with an empty body** (no verify token), and any other path is a 404 from the proxy.

## 6. What CLIVE does with each message

1. **At the door** (`app/routes/hooks.py`, `app/messaging/meta.py`): a body over Meta's 3 MB is
   refused before it is read. Meta's URL check is answered with its challenge only for the stored
   verify token, compared in constant time. A POST is read only when its `X-Hub-Signature-256`
   is `sha256=` and the HMAC-SHA256 of the raw body under the app secret, compared in constant
   time, **before** the body is decoded or parsed; then it must be strict UTF-8 JSON, one object,
   `whatsapp_business_account`. Anything else gets **403 with an empty body**, never an error.
   Meta signs no timestamp and retries an unanswered delivery for up to 7 days, so old requests
   are not refused; the same body again within ten minutes is answered and dropped, and each
   message is stored once by its `wamid`, so a replay changes nothing. Only changes for the
   stored phone number id are kept.
2. **Stored at once**, before Meta gets its 200: each message, the name WhatsApp gives the person,
   and what became of each reply CLIVE sent: **delivered**, **read**, or **failed** with
   WhatsApp's reason in plain words (never Meta's own text). Statuses never go backwards.
3. **Translated** after the door has answered, as for WeChat: anything not in English (Chinese,
   or a Latin-script language such as Portuguese or Turkish, told apart by its words) by Claude on
   the Max plan with no tools, labelled machine translation, the original kept; a failure says the
   translation is missing. English that only looked foreign ("Café hoodie restock?": an accent, no
   listed English word) comes back from the translator unchanged, and from then on counts as
   English: no label, and a reply in English alone.
4. **Read** with `messages_recent` (`channel: whatsapp` for WhatsApp alone, `person` for one
   person's conversations on every app) and `message_thread`: AMBER, so the model reads the name
   back. Each conversation says how long WhatsApp will still take a reply ("open 20h more").
5. **Answered** with `message_reply`: English alone to someone who writes English; to someone who
   doesn't, their language first and the English after (`translated`). The card prints the exact
   message, who it goes to (with WhatsApp's own name for them beside the person it is linked to),
   and the window. Only his hold sends it. "Sent" only on WhatsApp's message id, recorded in the
   conversation and on the action ledger; a refusal is said in plain words with "nothing was
   changed"; a send whose answer never came back, or that Meta answered with any 5xx (whatever
   code it carries), is "couldn't confirm", never "sent" and never "nothing was changed".

Nothing a message said, no number, name, token or secret goes to a log line or telemetry; the
door's query string is kept off the access log.

## 7. Doc pages relied on (developers.facebook.com/documentation/business-messaging/whatsapp/…)

- webhooks/create-webhook-endpoint — the GET check (hub.mode, hub.verify_token, hub.challenge),
  `X-Hub-Signature-256` (HMAC-SHA256 of the payload with the app secret), TLS, retries for 7 days,
  deduplication.
- webhooks/overview — fields, permissions, 3 MB payloads, Live mode.
- webhooks/reference/messages, …/messages/text, …/messages/status — the message and status payloads.
- messages/text-messages — `POST /<phone number id>/messages`, 4,096 characters, the `wamid` answer.
- messages/send-messages — customer service windows (24 hours), templates outside them.
- pricing — per-message pricing from 1 July 2025; non-template messages free in the window.
- support/error-codes — every code CLIVE puts in words (131047, 131026, 131056, 190, …).
- access-tokens — system user tokens, "Never" expiry, the three permissions.
- business-phone-numbers/phone-numbers and …/registration — `status` (CONNECTED), registering with the PIN.
- solution-providers/manage-webhooks — `POST /<WABA id>/subscribed_apps`.
- RFC 4231 — the HMAC-SHA256 vectors in `tests/test_whatsapp.py` (Meta publishes none complete).
