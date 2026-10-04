"""Who pays import charges, said honestly.

CROOKS ships DAP today: the recipient may be asked for import VAT, customs duty and a carrier
handling fee before delivery. Nothing here claims those are prepaid unless the merchant's
policy says so AND the shipment qualifies. The policy is a per-shop setting (DutiesPolicy), so
adding an IOSS number or DDP later changes data, not this model.

IOSS covers EU import VAT on consignments of intrinsic value up to €150. Deciding that needs
the value in euros; without a reliable rate we don't guess, we leave IOSS off and say why.
"""

from __future__ import annotations

from shipping.models import DutiesPolicy, DutiesTerms
from shipping.money import Money

EU = frozenset(
    "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split()
)
IOSS_LIMIT_EUR_MINOR = 15000

# EU countries whose territories by postcode sit outside the EU VAT area: the Canary Islands
# (35, 38), Ceuta (51) and Melilla (52). Parcels there clear customs like any non-EU import,
# and IOSS doesn't apply.
OUTSIDE_EU_VAT = {"ES": ("35", "38", "51", "52")}


def in_eu_vat_area(country: str, postcode: str = "") -> bool:
    country = (country or "").upper()
    if country not in EU:
        return False
    pc = (postcode or "").strip().replace(" ", "")
    return not any(pc.startswith(p) for p in OUTSIDE_EU_VAT.get(country, ()))


def terms(
    policy: DutiesPolicy,
    destination: str,
    goods_value: Money,
    value_in_eur_minor: int | None = None,
    postcode: str = "",
) -> DutiesTerms:
    in_eu = in_eu_vat_area(destination, postcode)
    if policy.ioss_number and in_eu:
        if value_in_eur_minor is not None and value_in_eur_minor <= IOSS_LIMIT_EUR_MINOR:
            return DutiesTerms(
                incoterm="DAP",
                ioss_number=policy.ioss_number,
                recipient_may_pay=True,
                summary=(
                    "Import VAT was collected at checkout under your IOSS number, so the "
                    "customer shouldn't be asked for VAT on delivery. Customs duty or a carrier "
                    "fee may still apply."
                ),
            )
        reason = (
            "it's over €150"
            if value_in_eur_minor is not None
            else "its value in euros couldn't be confirmed"
        )
        return DutiesTerms(
            incoterm="DAP",
            recipient_may_pay=True,
            summary=(
                f"Your IOSS number isn't used for this parcel because {reason}. The customer "
                "may be asked to pay import VAT, any customs duty and a carrier handling fee "
                "before delivery."
            ),
        )
    if policy.mode == "DDP":
        # Not offered by the v1 provider; readiness turns this into a question rather than
        # pretending charges are prepaid.
        return DutiesTerms(
            incoterm="DDP",
            recipient_may_pay=False,
            summary="Duties and taxes are to be prepaid by you (DDP).",
        )
    charges = "import VAT, any customs duty" if in_eu else "import duties and taxes"
    return DutiesTerms(
        incoterm="DAP",
        recipient_may_pay=True,
        summary=(
            f"The customer may be asked to pay {charges} and a carrier handling fee before "
            f"delivery. Nothing is prepaid (goods value {goods_value})."
        ),
    )
