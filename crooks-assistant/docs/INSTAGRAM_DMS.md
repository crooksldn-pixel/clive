# Instagram direct messages: how CLIVE reads and answers them

CLIVE already reads the CROOKS Instagram account (docs/INSTAGRAM.md: the inbox, one conversation,
unanswered comments). George approved answering on 7 October, ready when its keys are stored, every
message on his hold. This adds Instagram's direct messages to the same messaging core as WeChat and
WhatsApp: they arrive at one public address as they are sent, are kept in English with the original,
and are answered on his hold. **Section 1 is what he has to decide.**

It reuses the client and the token CLIVE already has (Instagram API with Instagram Login,
graph.instagram.com; `app/clients/instagram.py`). The code: `app/messaging/instagram.py` (the
channel), `app/messaging/meta.py` (Meta's webhook checks, shared with WhatsApp),
`app/routes/hooks.py` (the public door, `/hooks/instagram`) and `app/tools/messaging_tools.py`.
Comments are never answered from CLIVE.

## 1. What George must decide

1. **App Review for Advanced Access.** When CLIVE asked Instagram for the account's conversations
   and comments, Meta's API has returned nothing from other people. Meta's documentation says why
   that is expected: an app with only **Standard Access** gets the data of accounts that have a
   role on the app; other people's messages and comments come back only once the app has
   **Advanced Access** to `instagram_business_manage_messages` (and `_comments`), which needs App
   Review and Business Verification. Until then:
   - a message **sent while the webhook is on** may still arrive, because webhooks are what Meta
     documents for receiving messages (but Meta's own rule for Messenger-platform apps is the same
     Advanced Access, so it may not);
   - Test on Connections → Instagram says exactly what the API returned ("Instagram's API returned
     0 conversations"), and never pretends.
   Apply in the Meta app → App Review → Permissions and Features → request Advanced Access for
   `instagram_business_basic`, `instagram_business_manage_messages` (and
   `instagram_business_manage_comments` for comments), with a screencast of CLIVE reading and
   answering a test message. **This is the decision that makes Instagram work for customers.**
2. **The human-agent tag (seven days).** Instagram takes a reply only within **24 hours** of the
   person's last message. Its `HUMAN_AGENT` tag allows seven days, but it needs its own App Review
   ("Human Agent" feature) and Meta allows it only for a person answering by hand, not an automated
   reply. CLIVE drafts and George holds, which is a judgement Meta would make; **CLIVE doesn't use
   the tag** and refuses after 24 hours, saying why. Applying for it is his decision.
3. **Whether to switch the webhook on** (section 3), which needs the public address of section 4.

## 2. The keys

All on **Connections → Instagram** (the card that already exists):

| Field | Secret store key | What for |
|---|---|---|
| Instagram app ID, app secret | `instagram_app_id`, `instagram_app_secret` | Sign in with Instagram, as before. The secret also checks every webhook's signature. |
| Access token | `instagram_access_token` | As before: made by signing in, renewed by CLIVE (it lasts 60 days; Instagram has no non-expiring user token, so CLIVE renews it weekly and /health warns a week before it runs out). Replies are sent with it. |
| Webhook verify token (new) | `instagram_webhook_verify_token` | **Any long random string you choose**, typed the same into the Meta app (section 3, step 2). |

The token must carry `instagram_business_basic` and `instagram_business_manage_messages`; Sign in
with Instagram already asks for both.

## 3. Setting it up at Meta, in order

1. **The public address** (section 4): `https://hooks.crooksldn.com/hooks/instagram`.
2. developers.facebook.com → the CLIVE app → Instagram → **API setup with Instagram login** →
   **Configure webhooks**: Callback URL = that address, Verify token = the one on Connections →
   Verify and save (CLIVE answers Meta's check). Subscribe the fields **messages** and
   **messaging_seen**.
3. **Switch on the account's events**: `python scripts/instagram.py subscribe` on the server (Meta's
   `POST /me/subscribed_apps` with the stored token). It prints what Instagram now sends.
4. **App mode: Live.** Meta sends webhooks only to a live app.
5. In the **Instagram app** on the phone: turn on **Allow access to messages** (the message settings,
   under connected tools).
6. **Test** on Connections → Instagram: replies, conversations (what the API returned) and messages
   arriving, each in plain words.

## 4. The public address (server side)

The same as for WeCom and WhatsApp (docs/WHATSAPP.md, section 5): one more `handle /hooks/instagram`
in the Caddy site, or `tailscale funnel --bg --https=8443 --set-path=/hooks/instagram
http://127.0.0.1:8000/hooks/instagram`. From outside the tailnet `curl -si <the URL>` answers
**403 with an empty body**.

## 5. What CLIVE does

1. **At the door** (`app/messaging/meta.py`): Meta's URL check answered only for the stored verify
   token; a POST read only when its `X-Hub-Signature-256` is the HMAC-SHA256 of the raw body under
   the Instagram app's secret (`instagram_app_secret`, and only it: the WhatsApp app's secret is
   never tried here, even when both products sit on one Meta app), compared in constant time
   before anything is parsed; then strict UTF-8 JSON for the
   `instagram` object, under 3 MB. Anything else: **403 with an empty body**. The same body again
   within ten minutes is dropped; every message is stored once by Instagram's own id.
2. **Stored at once**: each message (Instagram's millisecond times read as seconds), a message the
   account sent from the Instagram app kept as "the Instagram app" (Instagram echoes them), and
   "seen" marking CLIVE's replies read. After the door has answered, each new person's @handle is
   asked of Instagram once, and anything not in English is translated, labelled machine
   translation.
3. **Read** with `messages_recent` (`channel: instagram` also reads Instagram's conversations API
   again, keeps anything new, and says exactly how many conversations the API returned, nought
   included, or why it could not be read) and `message_thread`. That read takes at most 6 seconds,
   four conversations at a time, inside the tool's own 10; a slower Instagram is said beside the
   conversations CLIVE already had, never a failed tool.
4. **Answered** with `message_reply`, within 24 hours of their last message (checked when the card
   is made and again at his hold, before anything goes), at most 1,000 bytes
   (Instagram's limit): English alone to someone who writes English, theirs first otherwise. Only
   his hold sends it. "Sent" only on Instagram's `message_id`. Instagram echoes every message the
   account sends, CLIVE's included; when that echo reaches the door before the send's own answer,
   it becomes CLIVE's record, so the send is still proved once. Instagram saying the window has
   closed (code 10, subcode 2534022) is said as its refusal, with "nothing was changed". Any 5xx,
   whatever code it carries, is "couldn't confirm": a gateway's 502 doesn't prove nothing went.
5. The three read-only Instagram tools are unchanged and still make GET requests only; their note
   now says a direct message is answered through `message_reply`, and a comment not at all. The
   system prompt's one Instagram sentence says the same (it said CLIVE could not answer there).

## 6. Costs and limits

Instagram messaging costs nothing. A reply only within 24 hours; text up to 1,000 bytes; Meta
rate-limits calls and CLIVE says so when it does. Messages in the Requests folder untouched for 30
days are not returned by the API.

## 7. Doc pages relied on (developers.facebook.com/documentation/…)

- instagram-platform/webhooks — the GET check, `X-Hub-Signature-256` with the app secret, `POST
  /me/subscribed_apps`, the fields and their permissions, Live mode, Advanced Access, retries for
  36 hours.
- instagram-platform/instagram-api-with-instagram-login/messaging-api — `POST /me/messages`,
  `recipient.id` (the Instagram-scoped id from the webhook), 1,000 bytes, 24 hours, the answer's
  `message_id`, Standard and Advanced Access, human agents.
- business-messaging/instagram-messaging/webhooks — the `messaging` payload: `mid`, `text`,
  `is_echo`, `is_deleted`, `read`, millisecond timestamps; webhooks for people without a role on
  the app only after App Review.
- business-messaging/messenger-platform/send-messages and …/policy — the 24-hour standard window,
  message tags, the Human Agent tag's seven days.
- docs/features-reference/human-agent — the Human Agent feature: App Review and Business
  Verification, for human agent support only.
