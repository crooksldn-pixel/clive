"""What the label printer prints for a parcel, never modifying the provider's stored original."""

import re
from io import BytesIO
from typing import Any

from pypdf import PdfReader

from shipping.models import DocumentKind, PageSize
from shipping.printing import PrintError

# "CN23" not glued to another code (CN230, XCN23). Text extraction runs the live form's heading
# into the next words ("DECLARATION CN23May be opened"), so a word boundary after it is not
# required: only that no further digit follows.
CN23 = re.compile(r"(?<![A-Z0-9])CN\s*23(?!\d)", re.IGNORECASE)

CN23_NOTE = (
    "The label file has the shipping label and, on page 2, the CN23 customs declaration. "
    "Both print, and both go on the parcel."
)

# A label file is the label plus whatever the carrier needs on the parcel with it (a CN22/CN23
# customs form): a handful of pages at most.
MAX_PARCEL_PAGES = 4


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


def label_page(page: Any) -> bool:
    """A portrait 4x6 page as made, never one that would be scaled, cropped or turned."""
    w, h = float(page.mediabox.width) * 25.4 / 72, float(page.mediabox.height) * 25.4 / 72
    return (
        98 <= w <= 104
        and 148 <= h <= 155
        and not page.rotation % 360
        and list(page.cropbox) == list(page.mediabox)
    )


def parcel_label_pdf(body: bytes, *, kind: DocumentKind, page_size: PageSize) -> bytes:
    """What goes on the parcel from the label printer: the provider's label file unchanged,
    every page of it. International labels carry the customs form with them (Easyship's Royal
    Mail CN23 is page 2), so no page is ever dropped. Only a file that is all 4x6 label pages
    goes to the label printer; anything else is for Open PDF."""
    if kind != DocumentKind.shipping_label or page_size != PageSize.label_4x6:
        raise PrintError("Only a stored 4x6 shipping-label document can be printed.")
    try:
        reader = PdfReader(BytesIO(body), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_PARCEL_PAGES:
            raise ValueError()
        if not all(label_page(p) for p in reader.pages):
            raise ValueError()
    except Exception:
        raise PrintError(
            "This label file isn't all 4x6 label pages; use Open PDF and print every page "
            "that goes on the parcel."
        ) from None
    return body
