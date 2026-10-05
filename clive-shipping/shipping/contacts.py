"""Who the carrier contacts about a parcel. Booking data only: never written back to Shopify.

Shopify doesn't require customers to give a phone (or, for some orders, an email), but carriers
and Easyship require both. The rule is deterministic: the customer's own detail when there is
one, otherwise the shop's ship-from detail from Setup.
"""

from __future__ import annotations

from shipping.models import Address


def recipient(destination: Address, origin: Address | None) -> tuple[Address, list[str]]:
    """The destination as given to the carrier, and which details came from the shop."""
    o = origin or Address()
    phone, email = destination.phone.strip(), destination.email.strip()
    used = []
    if not phone and o.phone.strip():
        phone = o.phone.strip()
        used.append("phone")
    if not email and o.email.strip():
        email = o.email.strip()
        used.append("email")
    return destination.model_copy(update={"phone": phone, "email": email}), used


def note(used: list[str]) -> str:
    """The merchant-facing note, or "" when the customer's own details are used."""
    if not used:
        return ""
    what = " and ".join(f"store {u}" for u in used)
    which = " or ".join(used)
    return f"Carrier contact: {what} used because the customer supplied no {which}"
