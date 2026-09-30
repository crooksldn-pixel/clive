# Instagram (read-only)

CLIVE can read the CROOKS Instagram account's direct messages and the comments on its recent
posts. It cannot send, reply, hide or delete anything there.

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
- when the owner asks CLIVE to reply, it says it can read Instagram but not answer there yet.

## What it deliberately does not do (yet)

- **No sending or replying.** A reply would be a write, and writes go through the gate, the owner's hold and a verification step. Instagram also allows a business to answer a DM through the API only within 24 hours of the customer's last message. That is a follow-up decision, not part of this change.
- **No webhooks.** Real-time delivery needs a public HTTPS endpoint, which the private-first runtime (IDEA-046) avoids. CLIVE asks Instagram when the owner asks CLIVE.
- **Nothing kept.** Messages and comments are read when asked for and not stored. The only thing written to disk is `instagram.json` beside the objectives, which holds times and kinds for the token's life and never the token.

## Setting it up on the server

1. **In the Meta app** (Instagram → *API setup with Instagram login*):
   - add the `crooksldn` professional account;
   - make sure it has the permissions `instagram_business_basic`, `instagram_business_manage_messages` and `instagram_business_manage_comments`;
   - generate its access token (long-lived, 60 days).
2. **In the Instagram app on the phone:** if messages are refused while comments work, turn on *Allow access to messages*. It is in the message settings, under connected tools.
3. **Store the token** (hidden as you paste it):

   ```
   python scripts/provision_secrets.py instagram_access_token
   ```

   Optionally store `instagram_app_id` and `instagram_app_secret` too. Only `scripts/instagram.py exchange` needs the secret.
4. **Check it** (prints counts and the account's own handle, never a customer's words):

   ```
   python scripts/instagram.py check
   ```

The token is read from the secret store at every call, so no restart is needed after storing it. The new code does need deploying.

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
  - `python scripts/instagram.py exchange` turns a new short-lived token into a long-lived one and stores it.

## Code

- `app/clients/instagram.py`: the client. GET requests only, to graph.instagram.com (API version `CROOKS_INSTAGRAM_API_VERSION`, default `v25.0`). The token goes in the Authorization header. Errors are named kinds and never quote Meta.
- `app/tools/instagram_tools.py`: the three tools. They are on the gate's allow-list in `app/tools/gate.py`.
- `tests/test_instagram.py`: everything against a fake Graph API; no call reaches Meta.
