"""The shipping provider, as a capability the owner can see the state of (§20).

DISCONNECTED, and the detail says exactly what is missing: the credential, by the name of the
environment variable a future integration would read, and the client, which is not written. The
state is PROBED rather than declared — it asks app/shipping which provider is installed — so
this row cannot go stale against reality: install a provider that is genuinely connected (the
fixture one, in a scenario) and the row says READY, without this file changing.

No tools and no operations. That is not an oversight:

* No tools, because a family that is not READY has its tools withheld from the model
  (`runtime.withheld_by_family`), and a shipping tool that is never offered is prompt weight
  for nothing. The shipping context reaches the tablet through the anticipation layer's
  internal read instead (app/anticipation/internal.py), which carries `checked=false` and says
  so on the card.
* No operations, because buying a label is a WRITE and will go through the action engine when
  it exists, not through a provider adapter.
"""

from __future__ import annotations

from typing import Any

from app.capabilities.families import CapabilityFamily, register


async def _probe(_runtime: Any) -> dict[str, Any]:
    """Which shipping provider is installed, and whether it can actually be asked."""
    from app.shipping import current as provider_current

    provider = provider_current()
    if provider is None:
        from app.shipping.easyship import CLIENT, TOKEN_ENV

        return {
            "state": "DISCONNECTED",
            "detail": f"no shipping provider is connected: {TOKEN_ENV} is unset and {CLIENT}",
        }
    if not provider.connected():
        return {
            "state": "DISCONNECTED",
            "detail": f"{getattr(provider, 'name', 'the shipping provider')} is not connected: "
                      f"{', '.join(provider.missing()) or 'no credentials'}",
        }
    return {"state": "READY", "detail": f"{getattr(provider, 'name', 'a provider')} is answering"}


FAMILY = register(CapabilityFamily(
    key="shipping_provider", label="Shipping labels and tracking", area="shipping",
    what="whether a label exists for an order, which carrier has it, the tracking number, its "
         "latest status, and any shipping exception",
    operations=(), tools=(),
    # A provider needs credentials, not a Shopify scope, so there is no scope to name here —
    # the detail names the credential instead.
    scopes=(),
    state="DISCONNECTED",
    detail="Easyship is not integrated in this build: no credentials and no client",
    probe=_probe,
))


# What this Mac cannot know, in the one table that reaches /health, the manifest and the model's
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
DELIVERY = register(CapabilityFamily(
    key="delivery_tracking", label="Delivery status", area="shipping",
    what="whether a parcel has actually arrived",
    state="DISCONNECTED",
    detail="no carrier is connected, so whether a parcel arrived is not a fact CLIVE holds — "
           "only fulfilled/unfulfilled, and whether a tracking number exists",
))
