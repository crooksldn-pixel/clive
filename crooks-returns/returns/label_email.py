"""The words of the CROOKS label email for a return staff issued: what is coming back, the
refund, the QR code to show at the drop-off point (or the label to print), the nearest drop-off
points and the tracking number. Plain text and HTML say the same thing."""

from __future__ import annotations

import html
from typing import Any

from returns.models import Resolution, Return, gbp

QR_CID = "return-qr"


def _miles(metres: int | None) -> str:
    if metres is None:
        return ""
    miles = metres / 1609.344
    return f"{miles:.1f} miles away" if miles >= 0.1 else "under 0.1 miles away"


def _item(ln: Any) -> str:
    size = f" — {ln.variant_title}" if ln.variant_title else ""
    return f"{ln.quantity} × {ln.title}{size}"


def compose(
    ret: Return, qr_png: bytes | None, label_pdf: bytes | None, label_url: str | None
) -> dict[str, Any]:
    first = (ret.customer_name or "").split(" ")[0] or "there"
    order = ret.order_name if ret.order_name.startswith("#") else f"#{ret.order_name}"
    p = ret.postage
    where = p.service_name or (f"a {p.carrier} drop-off point" if p.carrier else "the drop-off")
    if ret.resolution == Resolution.refund and ret.money.refund_pence:
        refund = (
            f"Your refund: {gbp(ret.money.refund_pence)} back to your original payment method "
            "once your return arrives and has been checked."
        )
    elif ret.resolution == Resolution.store_credit and ret.money.credit_pence:
        refund = f"Your store credit: {gbp(ret.money.credit_pence)} once your return arrives."
    else:
        refund = "No refund is due for this return."
    items = [_item(ln) for ln in ret.lines]
    shops = p.shops[:3]

    # ------------------------------------------------------------------ text
    t = [f"Hi {first},", "", f"Your return for order {order} is ready to send.", ""]
    t += ["Returning:", *[f"  {i}" for i in items], "", refund, ""]
    if qr_png:
        t.append(f"Show the QR code in this email (also attached) at {where}. No printing needed.")
        if p.drop_off_text:
            t.append(f"If it can't be scanned, give them this code: {p.drop_off_text}")
    else:
        t.append("Print the attached label and stick it on the parcel.")
    if shops:
        t += ["", "Your nearest drop-off points:"]
        for sh in shops:
            line = f"  {sh.get('name')}, {sh.get('address')}"
            extra = ", ".join(x for x in (_miles(sh.get("distance_m")), sh.get("hours")) if x)
            t.append(line + (f" ({extra})" if extra else ""))
    if p.tracking:
        t += ["", f"Tracking: {p.tracking}"]
    if label_url:
        t += ["", f"The label is also here: {label_url}"]
    t += ["", "Thanks,", "CROOKS"]

    # ------------------------------------------------------------------ html
    e = html.escape
    h = [
        '<div style="font-family:Helvetica,Arial,sans-serif;font-size:15px;line-height:1.5;'
        'color:#111;max-width:560px">',
        f"<p>Hi {e(first)},</p>",
        f"<p>Your return for order <strong>{e(order)}</strong> is ready to send.</p>",
        "<p><strong>Returning</strong><br>" + "<br>".join(e(i) for i in items) + "</p>",
        f"<p><strong>{e(refund)}</strong></p>",
    ]
    if qr_png:
        h.append(
            f"<p>Show this QR code at <strong>{e(where)}</strong>. No printing needed.</p>"
            f'<p><img src="cid:{QR_CID}" alt="Return QR code" width="220" height="220" '
            'style="display:block;border:0"></p>'
        )
        if p.drop_off_text:
            h.append(
                f"<p>If it can't be scanned, give them this code: "
                f"<strong>{e(p.drop_off_text)}</strong></p>"
            )
    else:
        h.append("<p>Print the attached label and stick it on the parcel.</p>")
    if shops:
        rows = "".join(
            f'<li style="margin-bottom:8px"><strong>{e(str(sh.get("name") or ""))}</strong><br>'
            f"{e(str(sh.get('address') or ''))}"
            + "".join(
                f'<br><span style="color:#555">{e(x)}</span>'
                for x in (_miles(sh.get("distance_m")), sh.get("hours"))
                if x
            )
            + "</li>"
            for sh in shops
        )
        h.append(
            f'<p><strong>Your nearest drop-off points</strong></p><ul style="padding-left:'
            f'18px">{rows}</ul>'
        )
    if p.tracking:
        h.append(f"<p>Tracking: {e(p.tracking)}</p>")
    if label_url:
        h.append(f'<p><a href="{e(label_url)}">Open the label</a></p>')
    h.append("<p>Thanks,<br>CROOKS</p></div>")

    attachments = []
    if qr_png:
        attachments.append({"filename": "return-qr.png", "content": qr_png, "content_id": QR_CID})
    if label_pdf:
        attachments.append({"filename": "return-label.pdf", "content": label_pdf})
    return {
        "subject": f"Your CROOKS return label — order {order}",
        "text": "\n".join(t),
        "html_body": "".join(h),
        "attachments": attachments,
    }
