"""Select physical label bytes without modifying the provider's stored original."""

import re
from io import BytesIO

from pypdf import PdfReader, PdfWriter

from shipping.models import DocumentKind, PageSize
from shipping.printing import PrintError

# "CN23" not glued to another code (CN230, XCN23). Text extraction runs the live form's heading
# into the next words ("DECLARATION CN23May be opened"), so a word boundary after it is not
# required: only that no further digit follows.
CN23 = re.compile(r"(?<![A-Z0-9])CN\s*23(?!\d)", re.IGNORECASE)

CN23_NOTE = (
    "Original PDF includes a CN23 customs declaration on page 2. "
    "Open PDF retains both pages; physical label printing excludes the CN23."
)


def easyship_cn23(body: bytes) -> bool:
    """Positive evidence of the verified two-page 4x6 label + CN23 layout."""
    try:
        r = PdfReader(BytesIO(body), strict=True)
        if r.is_encrypted or len(r.pages) != 2:
            return False
        for p in r.pages:
            w, h = float(p.mediabox.width) * 25.4 / 72, float(p.mediabox.height) * 25.4 / 72
            if not (98 <= w <= 104 and 148 <= h <= 155):
                return False
            if p.rotation % 360 or list(p.cropbox) != list(p.mediabox):
                return False
        text = r.pages[1].extract_text() or ""
        return bool(CN23.search(text))
    except Exception:
        return False


def select_shipping_label_pdf(
    body: bytes,
    *,
    provider: str,
    carrier: str,
    service: str,
    kind: DocumentKind,
    page_size: PageSize,
) -> bytes:
    if kind != DocumentKind.shipping_label or page_size != PageSize.label_4x6:
        raise PrintError("Only a stored 4x6 shipping-label document can be printed.")
    try:
        reader = PdfReader(BytesIO(body), strict=True)
        if reader.is_encrypted or not reader.pages:
            raise ValueError()
        if len(reader.pages) == 1:
            return body  # Dedicated Parcel2Go Label4X6 remains byte-for-byte unchanged.
        known_service = (
            "royal mail" in f"{carrier} {service}".lower()
            and ("tracked 48" in service.lower() or "tracked 24" in service.lower())
            and "small parcel" in service.lower()
        )
        # Verified Easyship Royal Mail format (Tracked 48 and 24, live 2026-10-05): label first,
        # CN23 second. Never infer page identity from dimensions alone; another 4x6 page can be
        # customs paperwork.
        if provider.casefold() != "easyship" or not known_service or not easyship_cn23(body):
            raise ValueError()
        first_text = reader.pages[0].extract_text() or ""
        if CN23.search(first_text):
            raise ValueError()
        writer = PdfWriter()
        writer.add_page(reader.pages[0])
        stream = BytesIO()
        writer.write(stream)
        return stream.getvalue()
    except Exception:
        raise PrintError(
            "Cannot confidently identify a single-page shipping label in this PDF; "
            "use Open PDF for the unchanged original."
        ) from None
