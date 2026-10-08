# Instagram (read-only)

CLIVE can read the CROOKS Instagram account's direct messages and the comments on its recent
posts with the three tools below, which cannot send, reply, hide or delete anything. Answering a
direct message, on the owner's hold, is the messaging core's: [INSTAGRAM_DMS.md](./INSTAGRAM_DMS.md).
A comment is never answered from CLIVE.

## What the owner can ask

| Ask | Tool |
|---|---|
| "Who's waiting on Instagram?" / "Any DMs?" | `instagram_inbox`: recent conversations, whoever has waited longest first |
| "What did @someone say?" | `instagram_thread`: one conversation's latest messages (Instagram gives at most 20). It needs a `conversation_id` from `instagram_inbox` in the same conversation |
| "Any comments we haven't answered?" | `instagram_comments`: comments on the 12 most recent posts with no reply from CROOKS, from the last 7 days by default |

All three are **AMBER** reads, because they surface people's handles and words:
- the model reads the identifying detail back before acting on it;
- the turn log scrubs the handles.

Everything a customer wrote is **untrusted**, exactly like an email:
- every result says so beside the text;
- the system prompt says it too (`app/kb/loader.py`);
- when the owner asks CLIVE to reply to a direct message, it stages `message_reply` for his hold
  ([INSTAGRAM_DMS.md](./INSTAGRAM_DMS.md)); a comment, it says it cannot answer.

## What it deliberately does not do (yet)

- **No sending or replying from these tools.** Since 8 October a direct message is answered through the messaging core instead: `message_reply`, staged at RED, sent only on the owner's hold, within Instagram's 24 hours, proved by Instagram's message id ([INSTAGRAM_DMS.md](./INSTAGRAM_DMS.md)). Comments are not answered.
- **No webhooks here.** Since 8 October the messaging core has one public door for Instagram's direct messages, `/hooks/instagram`, switched on only when George sets it up ([INSTAGRAM_DMS.md](./INSTAGRAM_DMS.md)). These tools still ask Instagram when the owner asks CLIVE.
- **Nothing kept by these tools.** Messages and comments are read when asked for and not stored. The only thing they write to disk is `instagram.json` beside the objectives, which holds times and kinds for the token's life and never the token. Direct messages that reach the messaging core are kept in its private store (90 days), like WeChat's.

## Setting it up

**The easy way: the Connections screen** (`/connections`, see [CONNECTIONS.md](./CONNECTIONS.md)).
1. **In the Meta app** (Instagram → *API setup with Instagram login*):
   - add the `crooksldn` professional account;
   - make sure it has the permissions `instagram_business_basic`, `instagram_business_manage_messages` and `instagram_business_manage_comments`.
2. **On the Instagram card, save the app ID and app secret.** Your passkey approves it.
3. **Register the sign-in's return address in the Meta app, once.** The card shows the address with a copy button. Add it under *Business login settings → OAuth redirect URIs*, exactly as shown.
4. **Tap *Sign in with Instagram*.** Instagram's own page asks you to approve. You come back connected, with a long-lived token CLIVE has tested, stored encrypted and renews itself.
5. **In the Instagram app on the phone:** if messages are refused while comments work, turn on *Allow access to messages*. It is in the message settings, under connected tools.

If you already have a token from the Meta app's *Generate token* button, you can paste it in the card's *Access token* field instead of signing in.

**At the server, still works** (hidden as you paste):

```
python scripts/provision_secrets.py instagram_access_token
python scripts/instagram.py check
```

`check` prints counts and the account's own handle, never a customer's words. A token stored there replaces one stored from the app, and the reverse: the latest choice wins.

## The token's life

- A long-lived token lasts **60 days**. CLIVE renews it itself:
  - a day after it was first used (Meta renews only tokens at least a day old);
  - then weekly;
  - it writes the new token back into the secret store, which is why the token is a *mutable* secret.
- `/health` shows `instagram`:
  - who it is connected as, and how many days the token has left;
  - it turns red when the token has under a week left, has expired, or its last call was refused.
- By hand:
  - `python scripts/instagram.py refresh` renews it now;
  - `python scripts/instagram.py exchange` turns a new short-lived token into a long-lived one and stores it;
  - or sign in again from the Connections screen.

## Code

- `app/connections/instagram.py`: Sign in with Instagram (the one POST, to Instagram's token endpoint, with the app secret in its body).
- `app/clients/instagram.py`: the client. GET requests only, to graph.instagram.com (API version `CROOKS_INSTAGRAM_API_VERSION`, default `v25.0`). The token goes in the Authorization header. Errors are named kinds and never quote Meta.
- `app/tools/instagram_tools.py`: the three tools. They are on the gate's allow-list in `app/tools/gate.py`.
- `tests/test_instagram.py`: everything against a fake Graph API; no call reaches Meta.
