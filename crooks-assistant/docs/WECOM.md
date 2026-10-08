# WeCom: how CLIVE reads and answers WeChat

CROOKS talks to its manufacturer and its freight forwarder on WeChat. WeCom (企业微信) is the
official way an app reaches WeChat, and George has built his own WeCom app. This page is what he
sets up in the WeCom admin console, what each way of reaching people can and cannot do, and what
CLIVE does with every message. The code is `app/clients/wecom.py` (every call), `app/messaging/`
(the channel-neutral core and the WeCom adapter), `app/routes/hooks.py` (the one public door) and
`app/tools/messaging_tools.py` (what the model can ask for).

The rules George approved on 7 October, and where each is kept:

| Rule | Where |
|---|---|
| Every outgoing message needs his hold. | `message_reply` is a write registered at RED: staged, never sent when called; its card is hold-to-arm (`app/actions/grammar.py`). |
| Inbound Chinese is shown in English, the original one tap away. | Translated when it arrives (`app/messaging/translate.py`), labelled machine translation; the card hides the original behind one tap (`web/messages.js`). |
| Outbound messages are drafted in both English and Chinese. | `message_reply` takes both; the card prints both; both are sent, Chinese first. |
| Inbound arrives at one public, signature-checked address; only that path is public. | `/hooks/wecom` (`app/routes/hooks.py`, `app/main.py`); everything else stays behind the door. |

## 1. The six values, and where each is in the admin console

The first five go in **Connections → WeCom** on CLIVE (or `python scripts/provision_secrets.py <key>`
on the server). Test asks WeCom what the app can do and says, route by route, what is ready and what
to switch on. CLIVE's WeCom tools are switched off until those five are stored. The sixth is
optional and rare, so the Connections screen does not ask for it: it is stored on the server only
(`python scripts/provision_secrets.py wecom_kf_secret`), and only if the company already used
微信客服's own Secret before 1 December 2023.

| Field on CLIVE | Secret store key | Where it is |
|---|---|---|
| CorpID | `wecom_corp_id` | work.weixin.qq.com → 我的企业 (My Company) → bottom of the page; starts `ww`. |
| AgentID | `wecom_agent_id` | 应用管理 (App Management) → your self-built app → AgentId. |
| App Secret | `wecom_app_secret` | Same page → Secret → 查看 (View); WeCom sends it to your WeCom app. |
| Callback Token | `wecom_callback_token` | Same page → 接收消息 (Receive Messages) → 设置API接收 (Set API Receive) → Token. |
| EncodingAESKey | `wecom_encoding_aes_key` | Same place → EncodingAESKey (43 letters and digits). |
| Customer service Secret (optional, server only) | `wecom_kf_secret` | Only if 微信客服 → API shows a Secret of its own. Since 1 Dec 2023 WeCom takes the self-built app's own Secret for 微信客服 calls (companies already using the old one are not cut off), so this is normally left empty. |

## 2. What to switch on in the WeCom admin console

In this order; Test on CLIVE's Connections screen says which step is still missing.

1. **The app's visible range (可见范围).** On the app's page, include everyone CLIVE should message
   inside the company (George, the team), and the customer-service account's agents (接待人员):
   WeCom refuses 微信客服 calls for an account whose agents the app cannot see (document 94677).
   Messages to people outside the range are refused (60011).
2. **Receive messages (接收消息 → 设置API接收).**
   - URL: the public hooks address of section 4, ending `/hooks/wecom`.
   - Token and EncodingAESKey: press 随机获取 (generate) for each, then store both on CLIVE **before**
     pressing Save, because Save makes WeCom send a signed check to the URL and CLIVE can only
     answer it with the same two values.
   - Format: XML (the default). CLIVE also reads JSON.
   - Events: none are needed beyond messages; customer-service events arrive regardless.
3. **Trusted IPs (企业可信IP)**, on the app's page: add the production server's public IPv4 (the
   address CLIVE calls `qyapi.weixin.qq.com` from). Without it WeCom refuses CLIVE's calls with
   60020, and Test names the address it saw. WeCom only lets the trusted IP be set once the app has
   a callback URL or a trusted domain, which step 2 gives it.
4. **WeChat customer service (微信客服)**: how the manufacturer and the forwarder reach CROOKS from
   their own WeChat.
   - Create the CROOKS customer-service account (or use the one you have).
   - 微信客服 → API → **可调用接口的应用** (apps that can call the API): add this app.
   - 微信客服 → API → **通过API管理微信客服账号** (manage accounts through the API): choose the CROOKS
     account, so its conversations come to the app rather than to a person.
   - Copy the account's link (客服链接) and send it to Jessica and the forwarder. They open it in
     WeChat and send one message; from then on CLIVE sees what they send.
5. **Customer contact (客户联系)** is not needed: see the routes below.

## 3. What each route can and can't do

| Route | State in CLIVE | What it does | Limits |
|---|---|---|---|
| **WeChat contacts, through customer service** (微信客服: `kf/sync_msg`, `kf/send_msg`) | Used | Reads what someone sends the CROOKS customer-service account from their own WeChat, and answers them. | A reply only within **48 hours** of their last message, **five replies** at most until they write again (95001, 95002), and only while the conversation is with the app (状态 0 or 1), not a person in WeCom (95018). WeCom keeps messages for sync for three days. A send WeCom accepted can still fail later; CLIVE marks it failed when WeCom says so (`msg_send_fail`). |
| **Your team, as app messages** (`message/send`, and messages to the app in the callback) | Used | People in the company message the app; CLIVE reads it and answers as the app. | Only people in the app's visible range. WeCom limits each member to 30 app messages a minute. |
| **Your own WeChat contacts** (客户联系: `externalcontact/add_msg_template`) | Not used | — | WeCom lets an app only *queue* a message to a contact; the member must then confirm and send it in the WeCom app, and it counts against the contact's monthly group-message limit. CLIVE would not be the one sending, and could not prove a send, so it doesn't use it. |
| **Conversation archive** (会话内容存档) | Not used | — | A paid add-on that needs Tencent's own C library on the server, an RSA key pair, the members' and each external contact's consent, and its own IP list. Not used. |
| **Group chats made by the app** (`appchat`) | Not used | — | Members of the company only, the app's visible range must be the root department, and WeCom confirms a group message with no message id, so CLIVE couldn't prove a send. |

## 4. The public address (server side)

WeCom calls CLIVE from the internet, so `/hooks/wecom` must be reachable publicly, and nothing else.
The app keeps binding 127.0.0.1 and the unit is unchanged; only something in front of it is added,
and it forwards that one path. CLIVE itself also refuses every other path to anyone not signed in
through Tailscale, so a proxy that forwarded more would still meet the door.

Two ways; choose one on the production host (`crooks-os-prod-1`):

- **A. A subdomain of crooksldn.com on the host's public address** (no Tailscale in the path).
  1. DNS: an `A` record `hooks.crooksldn.com` → the server's public IPv4.
  2. Find what already answers on ports 80 and 443 for `returns.crooksldn.com`:
     `ss -ltnp | grep -E ':(80|443) '`. If it is Caddy on the host, add a site:

         hooks.crooksldn.com {
             handle /hooks/wecom {
                 reverse_proxy 127.0.0.1:8000
             }
             handle {
                 respond 404
             }
         }

     then `caddy validate` and reload it. If the proxy runs inside a container, it cannot reach the
     host's 127.0.0.1: run this site in a proxy on the host instead, or ask before changing how
     the app binds.
  3. The URL for WeCom: `https://hooks.crooksldn.com/hooks/wecom`.
- **B. Tailscale Funnel on port 8443, for the one path.**
  1. In the Tailscale admin console, allow Funnel for this machine (Access controls: a `nodeAttrs`
     entry giving it the `funnel` attribute) and keep HTTPS certificates on.
  2. `tailscale funnel --bg --https=8443 --set-path=/hooks/wecom http://127.0.0.1:8000/hooks/wecom`
     (port 443 stays the tailnet-only `tailscale serve`; `tailscale funnel status` shows both).
  3. The URL for WeCom: `https://<the server's ts.net name>:8443/hooks/wecom`. If WeCom will not
     save a URL with a port, or cannot reach it, use A.

Either way, before saving the URL in WeCom, check from a machine outside the tailnet:
`curl -si https://<the URL>` answers `403` with an empty body (CLIVE's door: unsigned), and
`curl -si https://<the host>/connections` is a 404 from the proxy (A) or refused (B). Then
store the five values on Connections, then press Save in WeCom (section 2): CLIVE answers its
signed check. The service's log names a refused request by its kind (signature, stale, repeat),
never what any request carried.

## 5. What CLIVE does with each message

1. **At the door** (`app/routes/hooks.py`): a body over 64 KB is refused before it is read; the
   signature (SHA-1 of the sorted token, timestamp, nonce and ciphertext) is checked before
   anything else is done with it; then the timestamp must be within five minutes and the request
   new (`app/messaging/guard.py`); then it is decrypted (AES-256-CBC, the scheme of
   document/path/90968) and must be for this CorpID. A body is read only if it is UTF-8 and starts
   `<xml` or `{`, as everything WeCom sends does, so no other encoding or document type reaches a
   parser; the path checked is the routed one, never one the Host header could shape. Anything
   refused, or that cannot be read at all, gets **403 with an empty body**, never an error. A
   message gets **200 with an empty body at once**, because WeCom wants an answer within five
   seconds and retries otherwise; a team member's message, which is in the callback itself, is
   stored before that answer however busy CLIVE is; a repeat of one already taken is answered and
   dropped.
2. **After the door** (`app/messaging/ingest.py`, no tool authority, no turn): for customer
   service, CLIVE reads the messages with `kf/sync_msg` using the callback's token and the stored
   read position, saving the position after every page. Each message is stored once (by WeCom's
   msgid). At most four of these run at once; past that, customer-service messages are read by the
   next callback, and a team member's message (already stored at the door) is translated by a run
   already going.
3. **Translated** by Claude on the Max plan through the Agent SDK, with no tools at all
   (`MaxAgentSDKProvider.complete`), one at a time, told the text is a quotation and never an
   instruction. Stored beside the original, labelled machine translation. If it fails, the
   original stays and the message says its translation is missing; it is not tried again. One a
   restart cut off reads as missing 15 minutes after it arrived, and is kept so at the next start.
4. **Named**: the WeChat nickname (`kf/customer/batchget`), until George says who it is
   ("that's Jessica, our manufacturer"), which links the conversation to Jessica's card
   (`message_contact`, `app/people/store.py` `channels`).
5. **Read** by the model with `messages_recent` and `message_thread`: English first, the original
   beside it, and how long WeChat will still take a reply. Both are AMBER, like every read that
   shows people's names and words, so the model reads the name back.
6. **Answered** with `message_reply`: the model writes the English and the Chinese; CLIVE checks the
   48-hour window, the five-reply limit, the conversation's state and WeChat's 2,048-byte limit,
   and stages a card printing the exact message, with WeChat's own name for the contact beside the
   person it is linked to ("Jessica (WeChat name: …)"), so a conversation linked to the wrong
   person shows before the hold. Only his hold sends it. The send is proved by
   WeCom's errcode 0 and msgid, recorded in the thread and on the action ledger; anything else is
   said as a failure in plain words, and a send whose answer never came back is "couldn't
   confirm", never "sent" and never "not sent".

## 6. What is kept, and for how long

`.state/messaging/` beside CLIVE's other records: one file per conversation and the read
positions, folder 0700, files 0600, written atomically. Messages are kept **90 days**, at most 400
per conversation, and pruned on every write and at start. Access tokens are held in memory only.
No message text, name, contact id, Secret or token is written to a log line or to telemetry; the
query string of `/hooks/*` is kept off the access log, and WeCom addresses lose their query in
httpx's log lines.

## 7. When the generic message card lands

Tonight's reply follows the email writes (`app/tools/gmail_writes.py`): a write tool with its own
`present`, drawn as the action engine's confirmation card, hold to arm, then tap. The flow
workstream's one-hold message card (branch `claude/n2-flow`, DEC-067, `app/families/message.py`)
draws any write whose `present()` returns a `message` block. When it lands on the trunk, one thing
switches here: `message_reply`'s `_present` also returns

    "message": {"channel": "wecom", "kind": "reply", "to": <who>, "subject": "",
                "body": <the Chinese, a blank line, the English: exactly what is sent>,
                "sign_off": "", "editable": [], "args": {}, "other": None, "sending": True}

and drops its own `body`. `editable` stays empty at first: an edit of the English on the card
would leave the Chinese saying something else, so changing the words is a new sentence to CLIVE,
which drafts both again. The WriteSpec, the gate, the hold, the proof (WeCom's msgid read back
from the thread) and the ledger stay exactly as they are.

## 8. Doc pages relied on (developer.work.weixin.qq.com/document/path/…)

- 90968 加解密方案说明 — the signature, the AES scheme and the worked example (its token, key, CorpID and POST are the vectors in `tests/test_wecom_crypto.py`).
- 90307 加解密库下载与返回码 — the official sample libraries (github.com/sbzhu/weworkapi_*), source of the URL-check vector.
- 90930 回调配置 and 90238 接收消息与事件 概述 — the GET check, the POST, answer in 1 s / 5 s, retries, dedupe by msgid.
- 90239 消息格式, 90240 事件格式 — message and event fields.
- 91039 获取access_token — 7,200 s, cache it, it can be invalidated early.
- 90313 全局错误码 — every errcode CLIVE puts in words.
- 94670 微信客服 接收消息和事件 — `kf_msg_or_event`, `kf/sync_msg`, cursor, token, event types, `msg_send_fail`.
- 94677 微信客服 发送消息 — `kf/send_msg`, 48 hours, five messages, msgid, 2,048 bytes.
- 94669 会话分配与消息收发 / 分配客服会话 — `service_state` 0–4.
- 94661 获取客服账号列表 — `manage_privilege`.
- 94665 获取客服账号链接 — the link contacts open in WeChat.
- 95159 获取客户基础信息 — nicknames.
- 90236 发送应用消息 — `message/send`, `invaliduser`, duplicate check, 2,048 bytes.
- 90227 获取应用 — `agent/get`, the app's name and whether it is switched off.
- 90245 创建群聊会话, 90248 应用推送消息 — `appchat` (not used).
- 92135 创建企业群发 — `add_msg_template` needs the member to confirm (not used).
- 92571 获取配置了客户联系功能的成员列表 — customer contact permission.
- 91360, 91361, 91774 会话内容存档 — the archive (not used).
