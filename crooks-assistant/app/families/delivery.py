"""Whether a parcel has actually arrived, as a capability the owner — and the model — can see the
state of.

This lived in app/families/shipping.py beside the parked Easyship row ("shipping_provider"),
which was deleted on the owner's ruling of 8 October (DEC-071, ruling 24) now CLIVE Shipping
(app/tools/shipping_tools.py, its own two families) carries labels and tracking for international
orders. This family is Ship24's, and stays.
"""

from __future__ import annotations

from typing import Any

from app.capabilities.families import CapabilityFamily, register


# What CLIVE cannot know, in the one table that reaches /health, the manifest and the model's
# own context (app/capabilities/families.py, app/routes/turn.py:_family_lines). Registered as a
# family precisely so the model is TOLD once, at the top of the turn, rather than discovering it
# a refused query at a time — which is what cost the tablet 45 s on one question. (It lived
# beside the word-matching families of app/families/query_language.py until those were removed
# on 28 September 2026; the model still needs to be told.)
#
# DISCONNECTED rather than NOT_SUPPORTED_BY_STORE: the shop can be told a tracking number, and
# often is. What is missing is anything that reports back, and that is a provider nobody has
# connected. `detail` carries no full stop: `families.words()` adds one, and the line the model
# reads is short because it is paid on every model-path turn.
#
# Ship24 is that provider, one parcel at a time (app/tools/ship24_tools.py, track_parcel), so the
# state is PROBED from its key: with one stored, whether a parcel arrived IS a fact CLIVE can
# look up, and telling the model otherwise at the top of every turn would stop it asking. Without
# one, the reason is the Ship24 family's own, word for word, so the two share one line of the
# model's prompt (`families.words()` groups by state and reason) instead of paying for two.
async def _delivery_probe(_runtime: Any) -> dict[str, Any]:
    from app.clients import ship24

    if ship24.api_key():
        return {"state": "READY", "detail": "Ship24 is connected: track_parcel reads one parcel's carrier scans"}
    return {"state": "DISCONNECTED", "detail": ship24.NOT_CONNECTED}


DELIVERY = register(CapabilityFamily(
    key="delivery_tracking", label="Delivery status", area="shipping",
    what="whether a parcel has actually arrived",
    state="DISCONNECTED",
    detail="no carrier is connected, so whether a parcel arrived is not a fact CLIVE holds — "
           "only fulfilled/unfulfilled, and whether a tracking number exists",
    probe=_delivery_probe,
))
