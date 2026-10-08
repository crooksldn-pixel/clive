"""What can be connected from the Connections screen, the fields each one takes, and what CLIVE
does with it. The screen is drawn from this list; a key that is not here cannot be stored from
the app, whatever a request says.

A field is a key in the secret store (app/secrets/keychain.py KNOWN_KEYS). A secret field is never
shown again once stored, not even to the owner; an ID field (`secret=False`) is shown, because an
app ID is not a secret and seeing it is how the owner checks the right one is in.

What a connection lets CLIVE do is said three ways, all of them true of this build:
  what      one plain line, the row's own ("Reads and edits your orders, customers and stock.")
  unlocks   the capability families it powers (app/capabilities/families.py), by key: the screen
            names each by its registered label and live state, so nothing is said that the
            registry does not hold (tests/test_connections_page.py checks every key is registered)
  abilities for a connection no family describes (the voice, video search), the same in words
  without   what stops working when it is not connected, from what the code does without it
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    hint: str = ""
    secret: bool = True
    # The server setting the value is copied from, when it is one (CROOKS Returns' keys are read
    # with grep from its .env): a whole line pasted as it was printed, NAME=value, is taken as its
    # value, and of a comma-separated list the first (app/connections/service.py `_cleaned`).
    env: str = ""


@dataclass(frozen=True)
class Connection:
    name: str
    label: str
    what: str
    fields: tuple[Field, ...]
    # The keys it cannot work without: absent, it is "not connected"; these are what Disconnect
    # takes away (an app's own ID and secret stay, so signing in again is one tap).
    requires: tuple[str, ...]
    family: str = ""           # the capability family whose live state the card shows
    sign_in: str = ""          # a "Sign in with …" button: "instagram"
    note: str = ""
    unlocks: tuple[str, ...] = ()
    abilities: tuple[str, ...] = ()
    without: str = ""
    # Connected somewhere other than this screen, for now: "server" (Gmail's `make gmail`).
    set_up_at: str = ""


# The order the screen keeps within each of its groups: the shop and the inbox first, because
# most of what CLIVE does stands on them.
CONNECTIONS: tuple[Connection, ...] = (
    Connection(
        name="shopify", label="Shopify",
        what="Reads and edits your orders, customers and stock.",
        fields=(
            Field("shopify_client_id", "Client ID", secret=False,
                  hint="Shopify Dev Dashboard → the CLIVE app → Settings → Client ID."),
            Field("shopify_client_secret", "Client secret", hint="Same page: Client secret."),
        ),
        requires=("shopify_client_id", "shopify_client_secret"), family="order_reads",
        unlocks=("order_reads", "customer_reads", "product_reads", "analytics", "summary_surfaces",
                 "abandoned_checkouts", "order_fulfil", "order_notes", "order_address", "order_refund",
                 "order_cancel", "order_edit", "order_create", "inventory_set", "discount_create", "store_credit"),
        without="Without it CLIVE can't see or change anything in the shop.",
    ),
    Connection(
        name="gmail", label="Gmail",
        what="Reads your email, and drafts and sends the replies you approve.",
        fields=(), requires=("gmail_token",), family="email_reads",
        note="Set up at the server for now (make gmail). Sign in with Google comes next.",
        unlocks=("email_reads", "email_drafts", "email_sends", "email_compose", "email_archive"),
        without="Without it CLIVE can't read or answer your email.",
        set_up_at="server",
    ),
    Connection(
        name="elevenlabs", label="ElevenLabs",
        what="Hears you and speaks as CLIVE.",
        fields=(Field("elevenlabs_api_key", "API key", hint="ElevenLabs → your profile → API keys."),),
        requires=("elevenlabs_api_key",),
        abilities=("Hearing what you say", "Speaking its answers in the voice you choose"),
        # Said by the service from the settings in use (app/connections/service.py, _without):
        # whether the server has its own recogniser decides what listening falls back to.
        without="Without it CLIVE speaks in each device's own built-in voice.",
    ),
    Connection(
        name="instagram", label="Instagram",
        what="Reads your Instagram messages and the comments on your posts.",
        fields=(
            Field("instagram_app_id", "Instagram app ID", secret=False,
                  hint="Meta for Developers → the CLIVE app → Instagram → API setup with Instagram login."),
            Field("instagram_app_secret", "Instagram app secret",
                  hint="Same page. Sign in with Instagram needs it, once."),
            Field("instagram_access_token", "Access token (only if you made one there)",
                  hint="Not needed if you sign in: signing in makes one, and CLIVE renews it."),
        ),
        requires=("instagram_access_token",), family="instagram", sign_in="instagram",
        unlocks=("instagram",),
        without="Without it CLIVE can't read your Instagram messages or comments.",
    ),
    Connection(
        name="ship24", label="Ship24",
        what="Says where a parcel is, from the carrier's own scans.",
        fields=(Field("ship24_api_key", "API key",
                      hint="Ship24 dashboard → API keys (dashboard.ship24.com/integrations/api-keys): the "
                           "Default key, made when you chose a plan. It starts apik_."),),
        requires=("ship24_api_key",), family="parcel_tracking",
        unlocks=("parcel_tracking", "delivery_tracking"),
        without="Without it CLIVE can say an order has shipped, but not where the parcel is.",
    ),
    Connection(
        name="returns", label="CROOKS Returns",
        what="Your returns and exchanges: what needs you, where a return is, and the actions you approve.",
        fields=(
            Field("crooks_returns_read_key", "Read key", env="RETURNS_CLIVE_READ_KEYS",
                  hint="On the server, run grep CLIVE /opt/clive/crooks-returns/.env and paste what follows "
                       "RETURNS_CLIVE_READ_KEYS= (one key, if there are several)."),
            Field("crooks_returns_write_key", "Write key", env="RETURNS_CLIVE_WRITE_KEYS",
                  hint="Same command: paste what follows RETURNS_CLIVE_WRITE_KEYS=. CLIVE uses it only for an "
                       "action you approve on its card."),
        ),
        requires=("crooks_returns_read_key", "crooks_returns_write_key"), family="returns_reads",
        unlocks=("returns_reads", "returns_actions"),
        without="Without it CLIVE can't see your returns, and approving or receiving one is done in Shopify admin "
                "(Apps, CROOKS Returns).",
    ),
    # [messaging] George's own WeCom app: how CLIVE reads and answers the manufacturer and the forwarder
    # on WeChat (app/clients/wecom.py, docs/WECOM.md). Off until its keys are stored; Test asks WeCom
    # what the app can do, route by route, and says what to switch on.
    Connection(
        name="wecom", label="WeCom",
        what="Reads WeChat messages from your manufacturer and forwarder, and sends the replies you hold.",
        fields=(
            Field("wecom_corp_id", "CorpID", secret=False,
                  hint="WeCom admin console (work.weixin.qq.com) → My Company (我的企业): the CorpID at the bottom. "
                       "It starts ww."),
            Field("wecom_agent_id", "AgentID", secret=False,
                  hint="App Management (应用管理) → your self-built app: AgentId."),
            Field("wecom_app_secret", "App Secret", hint="Same page: Secret → View (查看). WeCom sends it to your WeCom app."),
            Field("wecom_callback_token", "Callback Token",
                  hint="Same page → Receive Messages (接收消息) → Set API Receive: the Token."),
            Field("wecom_encoding_aes_key", "EncodingAESKey",
                  hint="Same place: the EncodingAESKey, 43 letters and digits."),
            Field("wecom_kf_secret", "Customer service Secret (only if it has its own)",
                  hint="Leave empty unless 微信客服 → API shows a Secret of its own; the app's Secret is used otherwise."),
        ),
        requires=("wecom_corp_id", "wecom_agent_id", "wecom_app_secret", "wecom_callback_token",
                  "wecom_encoding_aes_key"),
        family="messaging_reads",
        unlocks=("messaging_reads", "messaging_replies"),
        without="Without it CLIVE can't see or answer WeChat messages from your manufacturer and forwarder.",
    ),
    # [shipping] CLIVE Shipping, the owner's international shipping service (app/clients/crooks_shipping.py).
    Connection(
        name="shipping", label="CLIVE Shipping",
        what="Your international orders: what each needs, buying the label at the price checked, and printing it.",
        fields=(
            Field("crooks_shipping_read_key", "Read key", env="SHIPPING_CLIVE_READ_KEYS",
                  hint="On the server, run grep CLIVE /opt/clive/clive-shipping/.env and paste what follows "
                       "SHIPPING_CLIVE_READ_KEYS= (one key, if there are several)."),
            Field("crooks_shipping_write_key", "Write key", env="SHIPPING_CLIVE_WRITE_KEYS",
                  hint="Same command: paste what follows SHIPPING_CLIVE_WRITE_KEYS=. CLIVE uses it only for a label "
                       "you approve on its card."),
        ),
        requires=("crooks_shipping_read_key", "crooks_shipping_write_key"), family="shipping_reads",
        unlocks=("shipping_reads", "shipping_labels"),
        without="Without it CLIVE can't see your international orders, and labels are bought and printed in Shopify "
                "admin (Apps, then the CROOKS app's Shipping).",
    ),
    Connection(
        name="youtube", label="YouTube",
        what="Finds videos to play on your screens.",
        fields=(Field("youtube_api_key", "API key",
                      hint="Google Cloud console → APIs & Services → Credentials: an API key restricted "
                           "to the YouTube Data API v3."),),
        requires=("youtube_api_key",),
        abilities=("Searching YouTube for a video by name",),
        without="Without it a YouTube link you give still plays; CLIVE can't search for one.",
    ),
    Connection(
        name="github", label="GitHub",
        what="Files build requests for CLIVE's own engineering.",
        fields=(Field("github_engineering_inbox_token", "Fine-grained token",
                      hint="GitHub → Settings → Developer settings → Fine-grained tokens: the clive "
                           "repository only, Contents read and write."),),
        requires=("github_engineering_inbox_token",), family="engineering",
        unlocks=("engineering",),
        without="Without it CLIVE can't file build requests or say how they are going.",
    ),
)

BY_NAME = {connection.name: connection for connection in CONNECTIONS}


def get(name: str) -> Connection | None:
    return BY_NAME.get(str(name or ""))


def field(connection: Connection, key: str) -> Field | None:
    return next((f for f in connection.fields if f.key == key), None)
