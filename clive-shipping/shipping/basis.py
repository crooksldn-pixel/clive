"""The basis: a fingerprint of everything a label purchase depends on.

A preview returns it; an execute must send it back. If the order's lines, the address, the
package, the service, the price, the customs terms (IOSS) or the sender details the provider is
given (ship-from address, EORI, VAT number) changed in between, the fingerprints differ and the
purchase is refused as STALE before anything is sent (CLIVE's own action engine uses the same
idea).
"""

from __future__ import annotations

import hashlib
import json

from shipping.models import Shipment, ShopConfig


def basis(shipment: Shipment, cfg: ShopConfig | None = None) -> str:
    q = shipment.quote
    p = shipment.package
    d = shipment.destination
    material = {
        "shop": shipment.shop,
        "fo": shipment.fulfillment_order_id,
        "lines": sorted(
            (
                ln.fulfillment_order_line_item_id,
                ln.quantity,
                ln.unit_value.minor,
                ln.unit_value.currency,
                ln.hs_code,
                ln.origin_country,
            )
            for ln in shipment.lines
        ),
        "to": [d.name, d.line1, d.line2, d.city, d.region, d.postcode, d.country],
        "package": [p.length_mm, p.width_mm, p.height_mm, p.total_weight_g] if p else None,
        "service": [q.provider, q.service_code, q.amount.minor, q.amount.currency] if q else None,
        "duties": [shipment.duties.incoterm, shipment.duties.ioss_number]
        if shipment.duties
        else None,
    }
    if cfg is not None:
        o = cfg.origin
        material["sender"] = [
            [o.name, o.company, o.line1, o.line2, o.city, o.postcode, o.country, o.phone, o.email]
            if o
            else None,
            cfg.eori_number,
            cfg.vat_number,
        ]
    raw = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return "b1_" + hashlib.sha256(raw).hexdigest()[:24]
