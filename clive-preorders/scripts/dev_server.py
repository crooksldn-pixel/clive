"""CLIVE Preorders on a pretend store, for looking at the screens. Nothing touches Shopify, nothing
is emailed (emails are kept in memory), no secrets needed.

    cd clive-preorders && python scripts/dev_server.py [PORT]      # default 8130
    open http://127.0.0.1:8130/admin

The store has the Black Jogger from the brief (XS 7, S 0 / 30 coming, M 0 / 50 coming, L 0,
XL 3), a tee with a batch already preordering, orders including a mixed one, and Notify me
signups. /dev/storefront shows a product page with the storefront block on it.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ.setdefault("PREORDERS_ENV_FILE", "")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402

from preorders.app import build_service, create_app  # noqa: E402
from preorders.comms import RecordingMailer  # noqa: E402
from preorders.fake import FakeShopify  # noqa: E402
from preorders.settings import Settings  # noqa: E402

EXTENSION = Path(__file__).resolve().parents[2] / "crooks-returns/extensions/clive-preorders"


def seed(svc, shop: FakeShopify) -> None:
    jogger = shop.add_product("Black Jogger", {"XS": 7, "S": 0, "M": 0, "L": 0, "XL": 3}, 4000)
    tee = shop.add_product("Week Tee", {"S": 0, "M": 0, "L": 0}, 3000)
    shop.add_product("Crest Hoodie", {"S": 12, "M": 0, "L": 4}, 8500)
    svc.refresh_catalog()
    v = lambda pid, size: shop.variant(pid, size).variant_id  # noqa: E731
    today = datetime.now(UTC).date()
    jb = svc.create_batch(
        reference="Jogger Batch 2",
        expected_arrival_at=str(today + timedelta(days=12)),
        expected_dispatch_at=str(today + timedelta(days=15)),
        supplier_reference="PO-2207",
        status="IN_TRANSIT",
        lines=[
            {"variant_id": v(jogger, "S"), "expected_quantity": 30},
            {"variant_id": v(jogger, "M"), "expected_quantity": 50, "preorder_allocation": 45},
        ],
        actor="Dev",
    )
    offer = svc.configure_offer(
        product_id=jogger,
        batch_id=jb["id"],
        discount_type="PERCENTAGE",
        discount_value=10,
        actor="Dev",
    )
    svc.activate_offer(offer["id"], "Dev")
    tb = svc.create_batch(
        reference="T-Shirt Week Batch 2",
        expected_arrival_at=str(today + timedelta(days=3)),
        expected_dispatch_at=str(today + timedelta(days=6)),
        status="ORDERED",
        lines=[
            {"variant_id": v(tee, "S"), "expected_quantity": 40},
            {"variant_id": v(tee, "M"), "expected_quantity": 70},
            {"variant_id": v(tee, "L"), "expected_quantity": 60, "preorder_allocation": 8},
        ],
        actor="Dev",
    )
    toffer = svc.configure_offer(product_id=tee, batch_id=tb["id"], actor="Dev")
    svc.activate_offer(toffer["id"], "Dev")
    people = ["Ann Byrne", "Kofi Mensah", "Priya Shah", "Tom Ellis", "Mia Chen", "Leo Hart"]
    for i, name in enumerate(people):
        email = name.lower().replace(" ", ".") + "@example.com"
        at = datetime.now(UTC) - timedelta(days=6 - i)
        size = "S" if i % 2 else "M"
        if i == 0:  # a mixed order: one in stock, one preorder
            lines = [(v(jogger, "XS"), 1, None), (v(jogger, "M"), 1, shop.plan_of(v(jogger, "M")))]
        else:
            lines = [(v(jogger, size), 1 + i % 2, shop.plan_of(v(jogger, size)))]
        svc.ingest_order(shop.checkout(lines, email=email, name=name, at=at))
    for i in range(4):
        svc.ingest_order(
            shop.checkout(
                [(v(tee, "L"), 2, shop.plan_of(v(tee, "L")))],
                email=f"tee{i}@example.com",
                name=f"Tee Buyer {i}",
            )
        )
    for i in range(9):
        svc.waitlist.signup(variant_id=v(jogger, "L"), email=f"wait{i}@example.com")
    for i in range(3):
        svc.waitlist.signup(variant_id=v(tee, "L"), email=f"tl{i}@example.com")
    svc.waitlist.signup(variant_id=v(jogger, "L"), email="late@example.com")


def storefront(svc, shop: FakeShopify) -> str:
    """The block's markup as Liquid would render it for the Black Jogger, inside a minimal
    product form, so the script can be tried in a browser."""
    import json

    product = next(x for x in shop.variants_by_id.values() if x.product_title == "Black Jogger")
    variants = [x for x in shop.variants_by_id.values() if x.product_id == product.product_id]
    data = []
    for x in variants:
        plan = shop.plan_of(x.variant_id)
        spec = next((p.spec for g in shop.groups.values() for p in g.plans if p.id == plan), None)
        price = x.price_minor * (1 - (spec.discount_percent if spec else 0) / 100)
        data.append(
            {
                "id": int(x.variant_id.rsplit("/", 1)[1]),
                "available": x.available > 0 or x.inventory_policy == "CONTINUE",
                "quantity": x.available,
                "tracked": "shopify",
                "plan": {
                    "id": int(plan.rsplit("/", 1)[1]),
                    "name": spec.plan_name,
                    "description": spec.description,
                    "price": f"£{price / 100:.2f}",
                    "compare": f"£{x.price_minor / 100:.2f}" if spec.discount_percent else None,
                }
                if plan and spec
                else None,
            }
        )
    css = (EXTENSION / "assets/preorder.css").read_text()
    js = (EXTENSION / "assets/preorder.js").read_text()
    options = "".join(
        f'<option value="{d["id"]}">{x.variant_title}</option>'
        for d, x in zip(data, variants, strict=True)
    )
    return f"""<!doctype html><html lang="en"><head><meta name="viewport"
content="width=device-width, initial-scale=1"><title>Black Jogger</title><style>
body{{font-family:Helvetica,Arial,sans-serif;max-width:480px;margin:32px auto;padding:0 16px}}
.button{{background:#111;color:#fff;border:0;padding:12px;font:inherit;cursor:pointer}}
.button--secondary{{background:#fff;color:#111;border:1px solid #111}}{css}</style></head><body>
<section class="shopify-section"><h1>Black Jogger</h1><p>£40.00</p>
<form action="/cart/add" method="post" id="product-form"><label>Size
<select name="id">{options}</select></label>
<div class="clive-preorder" data-clive-preorder data-proxy="/proxy/preorders">
<script type="application/json" data-clive-variants>{json.dumps(data)}</script>
<div class="clive-preorder__panel" data-clive-panel="preorder" hidden aria-live="polite">
<p class="clive-preorder__badge">Pre-order</p><p class="clive-preorder__date" data-clive-date>
Expected dispatch date to be confirmed</p><p class="clive-preorder__price"><span data-clive-price>
</span><s class="clive-preorder__was" data-clive-was hidden></s></p><p class="clive-preorder__note">
You pay the full price today. This item ships separately from anything in stock.</p></div>
<div class="clive-preorder__panel" data-clive-panel="notify" hidden>
<p class="clive-preorder__note">This size is sold out. Leave your email and we'll tell you when
it's available.</p><button type="button" class="button button--secondary clive-preorder__open"
data-clive-open aria-expanded="false">Notify me</button>
<div class="clive-preorder__form" data-clive-form role="group" hidden><label
class="clive-preorder__label" for="e1">Email</label><input id="e1" class="clive-preorder__input"
type="email" name="email" autocomplete="email" required><button type="button"
class="button clive-preorder__submit" data-clive-submit>Notify me</button><p
class="clive-preorder__small">We'll only email you about this size.</p></div>
<p class="clive-preorder__message" data-clive-message
role="status" aria-live="polite" hidden></p><template data-clive-strings>"You're on the list.
We'll email you when this size becomes available."|"That didn't work."|"Pre-order"</template>
</div></div>
<button type="submit" name="add" class="button"><span>Add to cart</span></button></form></section>
<script>{js}</script></body></html>"""


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8130
    db = Path(tempfile.mkdtemp(prefix="preorders-dev-")) / "dev.sqlite3"
    settings = Settings(
        shopify_backend="fake",
        selling_plans="shopify",
        db_path=str(db),
        dev_skip_admin_auth=True,
        tick_interval_s=0,
        reconcile_every_min=0,
        shopify_client_secret="dev-secret",
    )
    shop = FakeShopify()
    svc = build_service(settings, shopify=shop, mailer=RecordingMailer())
    seed(svc, shop)
    app = create_app(settings, svc)

    @app.get("/dev/storefront", response_class=HTMLResponse, include_in_schema=False)
    def dev_storefront() -> str:
        return storefront(svc, shop)

    @app.get("/dev/emails", include_in_schema=False)
    def dev_emails() -> list[dict[str, str]]:
        return svc.comms.mailer.sent

    print(f"CLIVE Preorders dev: http://127.0.0.1:{port}/admin  (storefront: /dev/storefront)")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
