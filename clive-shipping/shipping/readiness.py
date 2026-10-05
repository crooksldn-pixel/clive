"""Readiness: is everything needed to buy a label known? If not, the fewest questions.

Facts are resolved in this order, per line:
  1. Shopify's own record (InventoryItem HS code, country of origin, weight): the system of
     record, used as-is. If the merchant changes it in Shopify, the new value wins.
  2. What the merchant confirmed here before (kept if Shopify refused to store it).
  3. Otherwise: a question, asked once per product (all sizes share HS code and origin).

Suggestions come only from evidence in this shop (e.g. the HS code the merchant confirmed for
another product of the same type). Nothing is guessed into a shipment: a suggestion is shown
for confirmation and never used until confirmed.
"""

from __future__ import annotations

from shipping.models import Address, CustomsLine, Question
from shipping.shopify import FoSnapshot, ItemFacts
from shipping.store import Store

COUNTRY_NAMES = {
    "CN": "China",
    "PT": "Portugal",
    "TR": "Türkiye",
    "GB": "United Kingdom",
    "IN": "India",
    "BD": "Bangladesh",
    "PK": "Pakistan",
    "VN": "Vietnam",
    "IT": "Italy",
    "ES": "Spain",
}


# Places that don't use postcodes in addresses; everywhere else a missing postcode is a gap.
NO_POSTCODE = frozenset("AE AG AW BS BZ BO FJ GH HK JM KE MO PA QA TT TZ UG ZW".split())


def address_gaps(a: Address) -> list[str]:
    """What a courier needs from the delivery address that isn't there."""
    gaps = [
        name
        for name, value in (
            ("recipient name", a.name or a.company),
            ("street", a.line1),
            ("town or city", a.city),
            ("country", a.country),
        )
        if not value.strip()
    ]
    if a.country and a.country not in NO_POSTCODE and not a.postcode.strip():
        gaps.append("postcode")
    return gaps


def resolve_lines(
    store: Store, shop: str, snap: FoSnapshot, items: dict[str, ItemFacts]
) -> list[CustomsLine]:
    lines = []
    for ln in snap.lines:
        record = items.get(ln.inventory_item_id or "") or ItemFacts(None, None, None)
        pid = ln.product_id or ln.title
        hs = record.hs_code or store.fact(shop, "product", pid, "hs_code")
        origin = record.origin_country or store.fact(shop, "product", pid, "origin_country")
        known_weight = store.fact(shop, "item", ln.inventory_item_id or "", "weight_g")
        weight = ln.weight_g or record.weight_g or (int(known_weight) if known_weight else None)
        description = store.fact(shop, "product", pid, "customs_description")
        from_shopify = bool(record.hs_code and record.origin_country)
        lines.append(
            CustomsLine(
                fulfillment_order_line_item_id=ln.id,
                variant_id=ln.variant_id,
                inventory_item_id=ln.inventory_item_id,
                product_id=ln.product_id,
                product_type=ln.product_type,
                variant_title=ln.variant_title,
                sku=ln.sku,
                title=ln.title,
                # The merchant's own words if given; else their product type/title from Shopify.
                customs_description=description or ln.product_type or ln.title,
                quantity=ln.quantity,
                unit_value=ln.unit_value,
                unit_weight_g=weight,
                hs_code=hs,
                origin_country=origin,
                facts_source="shopify" if from_shopify else "knowledge",
            )
        )
    return lines


def _hs_suggestion(store: Store, shop: str, line: CustomsLine) -> str | None:
    if not line.product_type:
        return None
    for subject, value, _ in store.facts(shop, "product", "hs_code"):
        if (
            subject != line.product_id
            and store.fact(shop, "product", subject, "product_type") == line.product_type
        ):
            return value
    return None


def questions(
    store: Store,
    shop: str,
    lines: list[CustomsLine],
    has_package: bool,
    destination: Address | None = None,
) -> list[Question]:
    out: list[Question] = []
    gaps = address_gaps(destination) if destination is not None else []
    if gaps:
        out.append(
            Question(
                kind="address",
                subject="address",
                text=f"The delivery address has no {' or '.join(gaps)}. Fix it on the order "
                "in Shopify; CLIVE picks the change up by itself.",
            )
        )
    if not has_package:
        out.append(
            Question(
                kind="package",
                subject="first_package",
                text="Enter the package you ship in, once: its name, size and empty weight. "
                "CLIVE remembers it for every order after this.",
            )
        )
    seen: set[tuple[str, str]] = set()
    for ln in lines:
        pid = ln.product_id or ln.title
        if not ln.unit_weight_g and ("weight", pid) not in seen:
            seen.add(("weight", pid))
            out.append(
                Question(
                    kind="weight",
                    subject=pid,
                    text=f"How much does one {ln.title} weigh on its own, in grams? "
                    "It's saved to the product in Shopify.",
                )
            )
        if not ln.hs_code and ("customs", pid) not in seen:
            seen.add(("customs", pid))
            hint = _hs_suggestion(store, shop, ln)
            out.append(
                Question(
                    kind="customs",
                    subject=pid,
                    text=f"{ln.title} hasn't shipped abroad before. What's its HS "
                    "(commodity) code, and how should customs describe it? Saved to every size "
                    "in Shopify.",
                    suggestion=hint,
                    choices=[ln.product_type or ln.title],  # description prefill: their own words
                )
            )
        if not ln.origin_country and ("origin", pid) not in seen:
            seen.add(("origin", pid))
            used = []
            for _, value, _ in store.facts(shop, "product", "origin_country"):
                if value not in used:
                    used.append(value)
            out.append(
                Question(
                    kind="origin",
                    subject=pid,
                    text=f"Where is {ln.title} made? Saved to every size in Shopify.",
                    choices=used[:3],
                )
            )
    return out
