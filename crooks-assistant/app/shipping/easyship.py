"""The Easyship adapter, in the only honest state it can be in here: not connected.

Easyship is not integrated. There is no API key on this machine, no HTTP client for it in this
repository, and no account to read. So this adapter exists to hold the SHAPE — it implements
`ShippingProvider`, it names exactly what is missing, and it refuses to answer — and the day
the credentials and the client exist, `shipment_for` is the one method that changes.

`connected()` returns False unconditionally, and that is not a placeholder to be flipped by an
environment variable: a token alone would not make this work, because the client that would use
it has not been written. Reporting "connected" on the strength of a secret being present would
be the exact pretence §20 forbids — the tablet would show a shipping card that never fills in.
So both things are named in `missing()`, and a test holds that no configuration of this process
can make this adapter claim to have checked anything.
"""

from __future__ import annotations

import os

from app.shipping.provider import ShippingContext, ShippingNotConnected

# The environment variable a future integration would read the key from, named here so the
# owner (and /health) can be told precisely what to set. It is not a key this build's Keychain
# knows: adding it there would be a claim that the integration exists.
TOKEN_ENV = "CROOKS_EASYSHIP_TOKEN"
# The second half of what is missing, and the half a credential cannot fix.
CLIENT = "the Easyship HTTP client (not written in this build)"


class EasyshipProvider:
    """Easyship, as far as this build goes: an interface and an honest refusal."""

    name = "Easyship"

    def __init__(self, *, token_env: str = TOKEN_ENV) -> None:
        self.token_env = token_env

    def token_present(self) -> bool:
        """Whether the credential a future integration would need is on this Mac. Reported for
        the owner's benefit; it is not what `connected()` turns on."""
        return bool(os.environ.get(self.token_env))

    def connected(self) -> bool:
        return False

    def missing(self) -> tuple[str, ...]:
        out: list[str] = []
        if not self.token_present():
            out.append(f"{self.token_env} (no Easyship credentials on this server)")
        out.append(CLIENT)
        return tuple(out)

    async def shipment_for(self, order_ref: str) -> ShippingContext:  # noqa: ARG002 — nothing to look up
        raise ShippingNotConnected(self.name, self.missing())

    async def document(self, reference: str) -> bytes | None:  # noqa: ARG002 — nothing to fetch
        raise ShippingNotConnected(self.name, self.missing())
