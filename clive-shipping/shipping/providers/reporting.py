"""Curated operational diagnostics; never forward provider text to the merchant."""

import re

from shipping.models import ProviderFailure
from shipping.providers.base import ProviderRefused, ProviderUnavailable

# Only known field tokens determine the message, never response values or arbitrary prose.
FIELD_MESSAGES = {
    "destination_address.city": (
        "address_validation",
        "destination.city",
        "a valid destination city",
    ),
    "destination_address.postal_code": (
        "address_validation",
        "destination.postcode",
        "a valid destination postcode",
    ),
    "destination_address.line_1": (
        "address_validation",
        "destination.line1",
        "a valid destination street address",
    ),
    "destination_address.state": (
        "address_validation",
        "destination.region",
        "a valid destination region/state",
    ),
    "destination_address.country_alpha2": (
        "address_validation",
        "destination.country",
        "a valid destination country",
    ),
    "contact_phone": ("contact_validation", "contact.phone", "a valid phone/contact number"),
    "contact_email": ("contact_validation", "contact.email", "a valid contact email"),
    "hs_code": ("customs_validation", "lines.hs_code", "a valid customs HS code"),
    "origin_country_alpha2": (
        "customs_validation",
        "lines.origin_country",
        "a valid item country of origin",
    ),
    "declared_customs_value": (
        "customs_validation",
        "lines.unit_value",
        "a valid declared customs value",
    ),
    "total_actual_weight": (
        "package_validation",
        "package.total_weight_g",
        "a valid parcel weight",
    ),
    "box": ("package_validation", "package", "valid package dimensions"),
    "courier_service_id": ("service_validation", "service", "an available service for this parcel"),
}


def quote_failure(provider: str, error: Exception) -> ProviderFailure:
    code = getattr(error, "code", "")
    if code in ("auth", "401", "403"):
        return ProviderFailure(
            provider=provider,
            category="auth",
            code="auth",
            safe_message=f"{provider} connection needs attention. Check Shipping Setup.",
            actionable=True,
        )
    if isinstance(error, ProviderUnavailable):
        category = code if code in ("rate_limit", "timeout", "server_error") else "unavailable"
        message = (
            f"{provider} is temporarily rate limited. CLIVE will retry automatically."
            if category == "rate_limit"
            else f"{provider} didn't answer just now. CLIVE will retry automatically."
        )
        return ProviderFailure(
            provider=provider,
            category=category,
            code=category,
            safe_message=message,
            retryable=True,
        )
    if isinstance(error, ProviderRefused):
        text = str(error).lower()
        matched = [
            info
            for token, info in FIELD_MESSAGES.items()
            if re.search(r"(?<![a-z_])" + re.escape(token) + r"(?![a-z_])", text)
        ]
        if matched:
            return ProviderFailure(
                provider=provider,
                category=matched[0][0],
                code=matched[0][0],
                safe_message=f"{provider} needs "
                + "; ".join(dict.fromkeys(m[2] for m in matched))
                + ". Check these fields and refresh rates.",
                fields=list(dict.fromkeys(m[1] for m in matched)),
                actionable=True,
            )
        return ProviderFailure(
            provider=provider,
            category="validation",
            code="validation",
            safe_message=(
                f"{provider} refused to quote this shipment. "
                "Check provider-required shipment details, then refresh rates."
            ),
            actionable=True,
        )
    return ProviderFailure(
        provider=provider,
        category="unavailable",
        code="unexpected",
        safe_message=(
            f"{provider} couldn't quote this shipment just now. Its connection needs attention."
        ),
        retryable=True,
    )
