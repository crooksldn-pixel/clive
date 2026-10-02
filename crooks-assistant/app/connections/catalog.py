"""What can be connected from the Connections screen, the fields each one takes, and what CLIVE
does with it. The screen is drawn from this list; a key that is not here cannot be stored from
the app, whatever a request says.

A field is a key in the secret store (app/secrets/keychain.py KNOWN_KEYS). A secret field is never
shown again once stored, not even to the owner; an ID field (`secret=False`) is shown, because an
app ID is not a secret and seeing it is how the owner checks the right one is in.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    hint: str = ""
    secret: bool = True


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


CONNECTIONS: tuple[Connection, ...] = (
    Connection(
        name="instagram", label="Instagram",
        what="Reads the CROOKS Instagram messages and the comments on its posts.",
        fields=(
            Field("instagram_app_id", "Instagram app ID", secret=False,
                  hint="Meta for Developers → the CLIVE app → Instagram → API setup with Instagram login."),
            Field("instagram_app_secret", "Instagram app secret",
                  hint="Same page. Sign in with Instagram needs it, once."),
            Field("instagram_access_token", "Access token (only if you made one there)",
                  hint="Not needed if you sign in: signing in makes one, and CLIVE renews it."),
        ),
        requires=("instagram_access_token",), family="instagram", sign_in="instagram",
    ),
    Connection(
        name="elevenlabs", label="ElevenLabs",
        what="Hears you and speaks as CLIVE.",
        fields=(Field("elevenlabs_api_key", "API key", hint="ElevenLabs → your profile → API keys."),),
        requires=("elevenlabs_api_key",),
    ),
    Connection(
        name="shopify", label="Shopify",
        what="Reads the shop, and changes it only when you approve.",
        fields=(
            Field("shopify_client_id", "Client ID", secret=False,
                  hint="Shopify Dev Dashboard → the CLIVE app → Settings → Client ID."),
            Field("shopify_client_secret", "Client secret", hint="Same page: Client secret."),
        ),
        requires=("shopify_client_id", "shopify_client_secret"), family="order_reads",
    ),
    Connection(
        name="youtube", label="YouTube",
        what="Finds videos to play on your screens.",
        fields=(Field("youtube_api_key", "API key",
                      hint="Google Cloud console → APIs & Services → Credentials: an API key restricted "
                           "to the YouTube Data API v3."),),
        requires=("youtube_api_key",),
    ),
    Connection(
        name="ship24", label="Ship24",
        what="Tracks parcels with the carrier's own scans, so CLIVE can say where an order is.",
        fields=(Field("ship24_api_key", "API key",
                      hint="Ship24 dashboard → API keys (dashboard.ship24.com/integrations/api-keys): the "
                           "Default key, made when you chose a plan. It starts apik_."),),
        requires=("ship24_api_key",), family="parcel_tracking",
    ),
    Connection(
        name="github", label="GitHub",
        what="Lets CLIVE file build requests for its own engineering.",
        fields=(Field("github_engineering_inbox_token", "Fine-grained token",
                      hint="GitHub → Settings → Developer settings → Fine-grained tokens: the clive "
                           "repository only, Contents read and write."),),
        requires=("github_engineering_inbox_token",), family="engineering",
    ),
    Connection(
        name="gmail", label="Gmail",
        what="Reads your email, and drafts and sends only when you approve.",
        fields=(), requires=("gmail_token",), family="email_reads",
        note="Set up at the server for now (make gmail). Sign in with Google comes next.",
    ),
)

BY_NAME = {connection.name: connection for connection in CONNECTIONS}


def get(name: str) -> Connection | None:
    return BY_NAME.get(str(name or ""))


def field(connection: Connection, key: str) -> Field | None:
    return next((f for f in connection.fields if f.key == key), None)
