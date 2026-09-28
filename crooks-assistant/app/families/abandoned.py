"""Abandoned checkouts (brief §14): a real read, and one that says what the data is.

"How many people abandoned their basket this week, and what were they trying to buy?" was
answered in Phase 2 with "I don't have a tool for that". This is the read, and the most
important thing in the file is not the query — it is the sentence the result carries, because
three different things get called the same thing and only one of them is in this data.

    a CART abandoned          somebody put things in a basket and left. NOT HERE, and not
                              anywhere: the Admin API has no cart resource. A shop learns
                              this from its storefront analytics, not from Shopify's API.
    a CHECKOUT abandoned      somebody began the checkout — reached the point of giving an
                              email or an address — and did not pay. THIS IS THE DATA.
                              `abandonedCheckouts`, served by `read_orders`.
    an order UNFULFILLED      somebody paid and it has not gone out. A different question
                              with its own tools, and nothing to do with abandonment.

Conflating them is not a rounding error: "twelve people abandoned their baskets" said of
twelve abandoned checkouts understates the first number and overstates what the shop can
know. So `shopify_abandoned_checkouts` returns the limitation as a field (`note`) rather than
leaving it to whoever reads the number.

The ranking is by OCCURRENCES, not by value: what is being asked is which garment people
keep failing to buy, and a £200 checkout with one hoodie in it does not make that hoodie
harder to sell than one that appears in nine checkouts. The value is carried alongside.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.capabilities.families import CapabilityFamily
from app.capabilities.families import register as register_family
from app.clients.shopify import ShopifyClient, ShopifyError
from app.surfaces import Freshness, Surface
from app.tools.gate import Tier
from app.tools.registry import ToolError, tool
from app.tools.shopify_tools import _c

log = logging.getLogger("crooks.families.abandoned")

READ_TOOL = "shopify_abandoned_checkouts"
SHOP_TZ = ZoneInfo("Europe/London")

DEFAULT_DAYS = 14
MAX_DAYS = 90
DEFAULT_LIMIT = 25
MAX_LIMIT = 50
MAX_RANKED = 8
MAX_DRILLDOWN = 6
# How many pages of `limit` checkouts one answer reads before it stops and says it stopped.
# The count and the value are the WINDOW's, so the read follows Shopify's pages to the end of
# the window — within this bound, which keeps one question to a handful of Shopify calls
# (four pages of the default 25 is the most recent hundred). Past it, the figures are the
# checkouts read and are labelled as that, never passed off as the window's total (the
# round-10 deploy review, F-01).
MAX_PAGES = 4

# The one sentence this family exists to keep saying. Held once, on the result the model
# reads, so what it says cannot drift from what the data is.
WHAT_IT_IS = (
    "Checkouts begun and not paid for — not baskets left on the site, which Shopify's Admin "
    "API does not expose at all, and not orders waiting to go out."
)

ABANDONED_QUERY = """
query CrooksAbandonedCheckouts($q: String!, $n: Int!, $after: String) {
  abandonedCheckouts(first: $n, query: $q, after: $after, sortKey: CREATED_AT, reverse: true) {
    edges {
      node {
        id
        name
        createdAt
        completedAt
        totalPriceSet { shopMoney { amount currencyCode } }
        customer { id displayName }
        lineItems(first: 20) {
          edges {
            node {
              title
              variantTitle
              quantity
              variant { id }
              product { id title }
            }
          }
        }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def _money(node: Any) -> float:
    try:
        return round(float(((node or {}).get("shopMoney") or {})["amount"]), 2)
    except (TypeError, KeyError, ValueError):
        return 0.0


def _currency(node: Any) -> str:
    try:
        return str(((node or {}).get("shopMoney") or {}).get("currencyCode") or "GBP")
    except AttributeError:
        return "GBP"


def display(amount: float, currency: str = "GBP") -> str:
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get(currency.upper())
    return f"{symbol}{amount:,.2f}" if symbol else f"{amount:,.2f} {currency}"


def _since(days: int) -> str:
    """The start of the window, in the SHOP's zone, as Shopify's search wants it. A window
    computed in UTC starts an hour into the wrong day for half the year."""
    first = (datetime.now(SHOP_TZ) - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    return first.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _read(client: ShopifyClient, days: int, limit: int, after: str | None = None) -> dict[str, Any]:
    since = _since(days)
    variables: dict[str, Any] = {"q": f"created_at:>='{since}'", "n": limit}
    if after:
        variables["after"] = after
    payload = await client.graphql(ABANDONED_QUERY, variables)
    body = (payload.get("data") or {}).get("abandonedCheckouts")
    if not isinstance(body, dict):
        # Named, not swallowed. A store whose plan or scopes do not serve this gets the
        # limitation as an error the assistant can read out, never "I don't have a tool".
        raise ToolError(
            "Shopify did not return the abandoned checkouts. The shop needs read_orders, and "
            "abandoned checkouts are only available to shops on a plan that has them."
        )
    return body


async def _read_window(client: ShopifyClient, days: int, limit: int) -> tuple[list[dict[str, Any]], bool, int, str]:
    """Every page of the window's checkouts, up to MAX_PAGES of them.

    Returns the checkout nodes, whether the whole window was read, how many pages it took, and
    — when it was not — why not, in words. The first page failing is the answer failing (the
    caller hears Shopify's own reason); a later page failing leaves what was already read, said
    to be partial, rather than losing the whole answer to it.
    """
    nodes: list[dict[str, Any]] = []
    after: str | None = None
    for page in range(MAX_PAGES):
        try:
            body = await _read(client, days, limit, after)
        except (ShopifyError, ToolError) as exc:
            if page == 0:
                raise
            return nodes, False, page, f"Shopify stopped answering after {len(nodes)} checkouts ({type(exc).__name__})"
        nodes.extend((edge or {}).get("node") or {} for edge in (body.get("edges") or []))
        info = body.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            return nodes, True, page + 1, ""
        after = str(info.get("endCursor") or "")
        if not after:
            return nodes, False, page + 1, "Shopify said there were more checkouts but gave no way to read them"
    return nodes, False, MAX_PAGES, f"the window holds more than the {len(nodes)} most recent checkouts read"


def _lines(node: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for edge in ((node.get("lineItems") or {}).get("edges") or []):
        line = (edge or {}).get("node") or {}
        product = line.get("product") or {}
        variant = line.get("variant") or {}
        title = str(line.get("title") or product.get("title") or "").strip()
        if not title:
            continue
        out.append({
            "title": title,
            "variant": str(line.get("variantTitle") or "").strip(),
            "quantity": int(line.get("quantity") or 1),
            "variant_id": str(variant.get("id") or ""),
            "product_id": str(product.get("id") or ""),
        })
    return out


def rank(checkouts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Which variants appear in the most abandoned checkouts.

    Counted per CHECKOUT, not per unit: two of the same hoodie in one abandoned checkout is
    one checkout in which that hoodie was not bought, and counting the units would make a
    single bulk order look like a pattern. The units are carried alongside, because "nine
    checkouts, eleven units" is a different fact from "nine checkouts, nine units".
    """
    tally: dict[str, dict[str, Any]] = {}
    for checkout in checkouts:
        seen: set[str] = set()
        for line in checkout["lines"]:
            key = line["variant_id"] or f"{line['title']}|{line['variant']}"
            row = tally.setdefault(key, {
                "label": line["title"], "variant": line["variant"], "checkouts": 0, "units": 0,
                "value": 0.0, "variant_id": line["variant_id"], "product_id": line["product_id"],
            })
            row["units"] += line["quantity"]
            if key not in seen:
                row["checkouts"] += 1
                row["value"] += checkout["total"]
                seen.add(key)
    ordered = sorted(tally.values(), key=lambda r: (-r["checkouts"], -r["units"], r["label"]))
    return ordered[:MAX_RANKED]


@tool(
    name=READ_TOOL,
    description=(
        "Checkouts begun and not paid for, in a window: how many, what they were worth, and "
        "which variants keep appearing. Not baskets left on the site (not in Shopify's API) "
        "and not unfulfilled orders."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "days": {"type": "integer", "minimum": 1, "maximum": MAX_DAYS, "description": f"Back from today; {DEFAULT_DAYS} if unsaid."},
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT},
        },
    },
    # A checkout carries who began it. The result names people, so the assistant reads the
    # identifying detail back rather than acting on it — the same rule every customer read
    # here keeps.
    tier=Tier.AMBER,
)
async def shopify_abandoned_checkouts(days: int = DEFAULT_DAYS, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """The window's abandoned checkouts, counted, valued and ranked.

    `what_it_is` and `not_included` are fields of the result rather than words on the card
    alone, because the model reads this too and "twelve people abandoned their baskets" is
    the sentence this family exists to stop.
    """
    days = max(1, min(int(days or DEFAULT_DAYS), MAX_DAYS))
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    nodes, complete, pages, short = await _read_window(_c(), days, limit)
    currency = "GBP"
    checkouts: list[dict[str, Any]] = []
    for node in nodes:
        if not node.get("id") or node.get("completedAt"):
            # A checkout that was completed is an order, not an abandonment. Shopify's own
            # filter is `completedAt: null`, and a shop whose window overlaps a recovery
            # would otherwise be told it lost a sale it made.
            continue
        total = _money(node.get("totalPriceSet"))
        currency = _currency(node.get("totalPriceSet")) or currency
        checkouts.append({
            "checkout_id": str(node["id"]),
            "name": str(node.get("name") or ""),
            "at": str(node.get("createdAt") or ""),
            "total": total,
            "customer_name": str((node.get("customer") or {}).get("displayName") or ""),
            "lines": _lines(node),
        })
    value = round(sum(c["total"] for c in checkouts), 2)
    ranked = rank(checkouts)
    # When the window was not read to its end, every figure below is of the checkouts that
    # were read, and the result says so in the fields the model reads and the cards draw from.
    partial = "" if complete else (
        f"Partial: {short}, so the count and the value are at least these — the checkouts "
        "read, not the whole window."
    )
    return {
        "days": days,
        "count": len(checkouts),
        "value": f"{value:.2f}",
        "value_display": display(value, currency),
        "average_display": display(round(value / len(checkouts), 2) if checkouts else 0.0, currency),
        "currency": currency,
        "complete": complete,
        "more": not complete,
        "pages": pages,
        "counted": "the whole window" if complete else "the checkouts read",
        "partial": partial,
        "items": [
            {"item": r["label"], "variant": r["variant"], "checkouts": r["checkouts"], "units": r["units"],
             "value_display": display(round(r["value"], 2), currency), "variant_id": r["variant_id"]}
            for r in ranked
        ],
        "recent": [
            {"name": c["name"], "at": c["at"], "total_display": display(c["total"], currency),
             "customer_name": c["customer_name"],
             "items": ", ".join(f"{line['quantity']} x {line['title']}" for line in c["lines"][:3]) or "nothing listed"}
            for c in checkouts[:MAX_DRILLDOWN]
        ],
        "what_it_is": "checkout abandonment",
        "not_included": (
            "baskets abandoned before checkout (Shopify's Admin API has no cart resource) and "
            "orders that were paid for and have not been fulfilled"
        ),
        "note": f"{WHAT_IT_IS} {partial}".strip(),
    }


# --------------------------------------------------------------------------- the capability


# --------------------------------------------------------------------------- the cards


def _window_words(days: int) -> str:
    if days == 1:
        return "in the last day"
    if days == 7:
        return "in the last week"
    return f"in the last {days} days"


def cards(body: dict[str, Any]) -> list[Surface]:
    """Two cards, from the read: the numbers, and what keeps being left behind.

    Both are built here, key by key, from the tool's own result — the same discipline
    app/presentation.py keeps — and both name what the data is in their own words, because a
    card read on its own must not be able to say the wrong thing. Drawn for the model's call
    of `shopify_abandoned_checkouts` (app/presentation.py `_family_cards`).
    """
    days = int(body.get("days") or DEFAULT_DAYS)
    count = int(body.get("count") or 0)
    when = _window_words(days)
    # Complete only when the read said so: a body without the flag (or with `more`) is a
    # subset, and a card read on its own must not present a subset as the window's total.
    complete = body.get("complete") is True and not body.get("more")
    partial = str(body.get("partial") or "") or "Partial: not every checkout in the window was read."
    at_least = "" if complete else "at least "
    caveat = "" if complete else "Partial: the checkouts read, not the whole window."
    figures = Surface(
        surface_type="analytics",
        ui_type="metric_group",
        title="Checkouts not paid for",
        data={
            "title": "Checkouts not paid for",
            "subtitle": f"{when} · {WHAT_IT_IS}",
            "metrics": [
                {"value": f"{at_least}{count}", "label": "checkouts abandoned" if complete else "checkouts abandoned, of those read"},
                {"value": f"{at_least}{body.get('value_display') or '—'}", "label": "not taken" if complete else "not taken, of those read"},
                {"value": str(body.get("average_display") or "—"), "label": "average each" if complete else "average of those read"},
            ],
            "note": WHAT_IT_IS if complete else f"{partial} {WHAT_IT_IS}",
            "complete": complete,
            "truncated": not complete,
        },
        freshness=Freshness(source="shopify", complete=complete, caveat=caveat),
    )
    items = [i for i in (body.get("items") or []) if isinstance(i, dict)]
    if not items:
        return [figures]
    most = max(int(i.get("checkouts") or 0) for i in items) or 1
    ranking = Surface(
        surface_type="analytics",
        ui_type="ranking",
        title="Left behind most often",
        data={
            "title": "Left behind most often",
            "subtitle": f"by how many abandoned checkouts they appear in, {when}" + ("" if complete else ", of those read"),
            "rows": [
                {
                    "rank": index + 1,
                    "label": str(item.get("item") or ""),
                    "sublabel": str(item.get("variant") or ""),
                    "ref": str(item.get("variant_id") or ""),
                    "kind": "variant",
                    "primary": {"value": str(item.get("checkouts") or 0), "label": "checkouts"},
                    "secondary": {"value": str(item.get("units") or 0), "label": "units"},
                    "pct": round(100.0 * int(item.get("checkouts") or 0) / most, 1),
                }
                for index, item in enumerate(items)
            ],
            "totals": [
                {"value": f"{at_least}{count}", "label": "abandoned"},
                {"value": f"{at_least}{body.get('value_display') or '—'}", "label": "not taken"},
            ],
            "note": "Ranked by how many checkouts each appears in, not by value: what is being asked is which items keep not being bought."
                    + ("" if complete else f" {partial}"),
            "complete": complete,
        },
        freshness=Freshness(source="shopify", complete=complete, caveat=caveat),
    )
    return [figures, ranking]


async def _probe(runtime: Any) -> dict[str, Any]:
    """Whether this shop's abandoned checkouts can be read at all.

    `abandonedCheckouts` is served by `read_orders`, which every read in this build already
    needs — so the honest states are READY and TEMPORARILY_UNAVAILABLE, and the thing worth
    saying is the one this family cannot do at all: carts. That belongs in `what`, where the
    owner and the model both read it, not in a state.
    """
    try:
        granted = set(await runtime.shopify.access_scopes())
    except Exception as exc:  # noqa: BLE001 — Shopify not answering is not a missing grant
        return {"state": "TEMPORARILY_UNAVAILABLE",
                "detail": f"the Shopify scope check did not answer ({type(exc).__name__})", "scope": "read_orders"}
    if "read_orders" not in granted:
        return {"state": "MISSING_SCOPE",
                "detail": "the store has not granted read_orders, which is what serves abandoned checkouts",
                "scope": "read_orders"}
    return {"state": "READY", "detail": "ready — checkouts begun and not paid for; carts are not in the API",
            "scope": "read_orders"}


register_family(CapabilityFamily(
    key="abandoned_checkouts",
    label="Abandoned checkouts",
    area="analytics",
    what=(
        "Checkouts begun and not paid for, with what keeps being left behind. Baskets abandoned "
        "before checkout are not in Shopify's Admin API at all, and unfulfilled orders are a "
        "different question"
    ),
    tools=(READ_TOOL,),
    scopes=("read_orders",),
    state="READY",
    probe=_probe,
))

__all__ = ["READ_TOOL", "WHAT_IT_IS", "cards", "display", "rank"]
