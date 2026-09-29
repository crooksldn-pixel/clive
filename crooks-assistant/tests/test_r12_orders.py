"""Round 12: creating an order by voice, and finding the order or customer he means.

George, 29 September: "i tried today to create an order, firstly it couldn't add the item, or
a custom item for that matter, it couldn't add a line discount or percent discount … trying to
give clive a name, an address and an item they ordered is enough evidence yet it doesn't do
what's asked. if i ask, find the customer who ordered this with this address and create a new
order for them in the next size up, this is something it finds near impossible without trying
to pull up a customer screen first and then me having to ask and ask again."

Every test here is that, said. A sentence goes to the real `POST /turn`; the one stand-in is
Claude — a scripted model that calls the tools Claude is offered, with arguments their schemas
admit, through the real gate and dispatcher — and the assertions are about what the owner
would SEE (the card the turn returns) and what the shop would be SENT. The shop is a fake with
a catalogue in real sizes, customers with one name between two of them, and orders delivered
to addresses, which prices a draft the way Shopify does and completes one only after the hold.
Every name, address and postcode here is invented.
"""

from __future__ import annotations

import copy
from typing import Any

import httpx
import pytest

from app.actions.ledger import ActionLedger
from app.clients.shopify import (
    REVIEWED_MUTATIONS,
    ShopifyClient,
    ShopifyError,
    draft_order_input_ok,
)
from app.families import _sizes as sizes
from app.main import app
from app.providers.base import TurnResult
from app.session.manager import SessionManager
from app.tools import shopify_tools
from app.tools.dispatch import dispatch
from tests.test_context import inbox

OWNER = "owner@example.com"
PROXIED = {"Tailscale-User-Login": OWNER, "X-Forwarded-For": "100.64.0.9"}

# --------------------------------------------------------------------------- the shop


def _variant(number: int, colour: str, size: str | None, sku: str, price: str, stock: int, *, for_sale: bool | None = None,
             size_name: str = "Size") -> dict[str, Any]:
    options = [("Colour", colour)] + ([(size_name, size)] if size else [])
    return {"id": f"gid://shopify/ProductVariant/{number}", "title": " / ".join(v for _, v in options), "sku": sku,
            "price": price, "stock": stock, "for_sale": stock > 0 if for_sale is None else for_sale, "options": options}


HOODIE = {"id": "gid://shopify/Product/9001", "title": "Convict Hoodie", "status": "ACTIVE", "variants": [
    _variant(9110, "Black", "XS", "CRK-HOOD-BLK-XS", "60.00", 2),
    _variant(9111, "Black", "S", "CRK-HOOD-BLK-S", "60.00", 4),
    _variant(9112, "Black", "M", "CRK-HOOD-BLK-M", "60.00", 5),
    _variant(9113, "Black", "L", "CRK-HOOD-BLK-L", "60.00", 7),
    _variant(9114, "Black", "XL", "CRK-HOOD-BLK-XL", "60.00", 0),         # sold out, and not sold on
    _variant(9121, "Bone", "S", "CRK-HOOD-BON-S", "60.00", 3),
    _variant(9122, "Bone", "M", "CRK-HOOD-BON-M", "60.00", 2),            # Bone stops at M
]}
JEANS = {"id": "gid://shopify/Product/9002", "title": "Yard Jeans", "status": "ACTIVE", "variants": [
    _variant(9228, "Indigo", "28", "CRK-JEAN-IND-28", "85.00", 2, size_name="Waist"),
    _variant(9230, "Indigo", "30", "CRK-JEAN-IND-30", "85.00", 0, for_sale=True, size_name="Waist"),   # sold on backorder
    _variant(9232, "Indigo", "32", "CRK-JEAN-IND-32", "85.00", 6, size_name="Waist"),
    _variant(9234, "Indigo", "34", "CRK-JEAN-IND-34", "85.00", 1, size_name="Waist"),
]}
CAP = {"id": "gid://shopify/Product/9003", "title": "Crooks Cap", "status": "ACTIVE", "variants": [
    _variant(9301, "Black", "One size", "CRK-CAP-BLK", "18.00", 31),
]}
TOTE = {"id": "gid://shopify/Product/9004", "title": "Yard Tote", "status": "ACTIVE", "variants": [
    _variant(9401, "Natural", None, "CRK-TOTE-NAT", "20.00", 12),
]}
CATALOGUE = [HOODIE, JEANS, CAP, TOTE]
VARIANTS = {v["id"]: (p, v) for p in CATALOGUE for v in p["variants"]}


def vid(number: int) -> str:
    return f"gid://shopify/ProductVariant/{number}"


THEO, MIA, MIA_TWIN, AVA, RAVI = (f"gid://shopify/Customer/{n}" for n in (8101, 8102, 8103, 8104, 8105))
PEOPLE = {
    THEO: {"name": "Theo Marsh", "email": "theo.marsh@example.com", "orders": 1,
           "home": {"address1": "3 Mill Lane", "address2": "", "city": "Bray", "provinceCode": "", "zip": "SL6 2AB",
                    "country": "United Kingdom", "countryCodeV2": "GB"}},
    MIA: {"name": "Mia Jones", "email": "mia.jones@example.com", "orders": 2, "home": None},
    MIA_TWIN: {"name": "Mia Jones", "email": "m.jones@example.net", "orders": 1, "home": None},
    AVA: {"name": "Ava Stone", "email": "ava.stone@example.com", "orders": 2, "home": None},
    RAVI: {"name": "Ravi Patel", "email": "ravi.patel@example.com", "orders": 1, "home": None},
}


def _parcel(customer: str, address1: str, city: str, postcode: str) -> dict[str, Any]:
    first, _, last = PEOPLE[customer]["name"].partition(" ")
    return {"firstName": first, "lastName": last, "company": "", "address1": address1, "address2": "", "city": city,
            "provinceCode": "", "zip": postcode, "countryCodeV2": "GB", "phone": ""}


# (number, customer, days ago, [(variant, quantity)], delivery address)
ORDERS = [
    (2101, THEO, 10, [(9112, 1), (9301, 1)], _parcel(THEO, "3 Mill Lane", "Bray", "SL6 2AB")),
    (2102, MIA, 30, [(9111, 1)], _parcel(MIA, "12 Bridge Street", "Windsor", "SL4 1QN")),
    (2103, MIA_TWIN, 20, [(9122, 1)], _parcel(MIA_TWIN, "40 Kings Road", "Reading", "RG1 3AR")),
    (2104, AVA, 12, [(9234, 1)], _parcel(AVA, "7 Station Road", "Slough", "SL1 1AA")),
    (2106, AVA, 5, [(9113, 1)], _parcel(AVA, "7 Station Road", "Slough", "SL1 1AA")),
    (2107, MIA, 3, [(9112, 1)], _parcel(MIA, "12 Bridge Street", "Windsor", "SL4 1QN")),
    (2109, RAVI, 8, [(9228, 1), (9401, 1)], _parcel(RAVI, "22 Newhall Street", "Birmingham", "B3 3AS")),
]


def _money(amount: float) -> dict[str, Any]:
    return {"shopMoney": {"amount": f"{amount:.2f}", "currencyCode": "GBP"}}


def order_node(number: int) -> dict[str, Any]:
    _n, customer, days, items, address = next(o for o in ORDERS if o[0] == number)
    person = PEOPLE[customer]
    goods = sum(float(VARIANTS[vid(v)][1]["price"]) * q for v, q in items)
    return {
        "id": f"gid://shopify/Order/{number}", "name": f"CROOKS-{number}",
        "createdAt": f"2026-09-{29 - days:02d}T10:00:00Z", "processedAt": f"2026-09-{29 - days:02d}T10:00:00Z",
        "cancelledAt": None, "email": person["email"],
        "displayFulfillmentStatus": "FULFILLED", "displayFinancialStatus": "PAID",
        "currentTotalPriceSet": _money(goods + 5),
        "customer": {"id": customer, "displayName": person["name"], "defaultEmailAddress": {"emailAddress": person["email"]}},
        "shippingAddress": dict(address),
        "lineItems": {"edges": [{"node": {
            "title": VARIANTS[vid(v)][0]["title"], "variantTitle": VARIANTS[vid(v)][1]["title"],
            "sku": VARIANTS[vid(v)][1]["sku"], "quantity": q, "variant": {"id": vid(v)},
        }} for v, q in items]},
    }


class Counter(ShopifyClient):
    """The shop: customers, a catalogue in real sizes, orders with addresses, and draft orders
    priced as the card words them — a line's fixed discount off each unit. It searches
    orders only by what Shopify's order search takes (a name, an email, customer ids, SKUs),
    and completes a draft only when the engine sends the one reviewed completion."""

    def __init__(self) -> None:
        super().__init__("fake.myshopify.com", "2025-07")
        from zoneinfo import ZoneInfo

        self._shop = {"name": "CROOKS LDN", "myshopifyDomain": "fake.myshopify.com", "ianaTimezone": "Europe/London", "currencyCode": "GBP"}
        self._tz = ZoneInfo("Europe/London")
        self.queries: list[tuple[str, dict]] = []
        self.mutations: list[tuple[str, dict]] = []
        self.drafts: dict[str, dict] = {}
        self.draft_number = 5000
        self.drop_lines = False                 # a Shopify that makes a draft without its lines
        self.ignore_search = False              # a Shopify whose search ignores the filters
        self.fail_orders = False                # a Shopify that does not answer an order search

    # ---- the reads

    def _orders(self, q: str | None) -> list[dict[str, Any]]:
        import re

        q = str(q or "")
        found = []
        for number, customer, _days, items, _address in sorted(ORDERS, key=lambda o: o[2]):
            if not self.ignore_search:
                name = re.search(r"\bname:#?(\d+)", q)
                if name and str(number) != name.group(1):
                    continue
                email = re.search(r'\bemail:"?([^"\s]+)"?', q)
                if email and PEOPLE[customer]["email"] != email.group(1).lower():
                    continue
                ids = re.findall(r"\bcustomer_id:(\d+)", q)
                if ids and customer.rsplit("/", 1)[-1] not in ids:
                    continue
                skus = re.findall(r"\bsku:([^\s()]+)", q)
                if skus and not any(VARIANTS[vid(v)][1]["sku"] in skus for v, _ in items):
                    continue
            found.append(order_node(number))
        return found

    def _product(self, product: dict[str, Any]) -> dict[str, Any]:
        options: dict[str, list[str]] = {}
        for variant in product["variants"]:
            for name, value in variant["options"]:
                options.setdefault(name, [])
                if value not in options[name]:
                    options[name].append(value)
        return {
            "id": product["id"], "title": product["title"], "status": product["status"],
            "options": [{"name": n, "values": vs} for n, vs in options.items()],
            "variants": {"edges": [{"node": {
                "id": v["id"], "title": v["title"], "sku": v["sku"], "price": v["price"],
                "availableForSale": v["for_sale"], "inventoryQuantity": v["stock"],
                "selectedOptions": [{"name": n, "value": val} for n, val in v["options"]],
            }} for v in product["variants"]]},
        }

    def _people(self, q: str) -> list[dict[str, Any]]:
        term = q.strip().strip('"').lower()
        if term.startswith("email:"):
            wanted = term[6:].strip().strip('"')
            rows = [(i, p) for i, p in PEOPLE.items() if p["email"] == wanted]
        else:
            rows = [(i, p) for i, p in PEOPLE.items() if term and (term in p["name"].lower() or term == p["email"])]
        return [{"id": i, "displayName": p["name"], "numberOfOrders": str(p["orders"]),
                 "defaultEmailAddress": {"emailAddress": p["email"]}, "amountSpent": _money(100)} for i, p in rows]

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        variables = dict(variables or {})
        self.queries.append((query, variables))
        if "CrooksScopes" in query:
            scopes = ("read_orders", "write_orders", "read_customers", "read_products",
                      "read_draft_orders", "write_draft_orders")
            return {"data": {"currentAppInstallation": {"accessScopes": [{"handle": h} for h in scopes]}}}
        if "CrooksOrderEvidence" in query:
            if self.fail_orders:
                raise ShopifyError("Shopify did not answer.")
            orders = self._orders(variables.get("q"))[: int(variables.get("n") or 25)]
            return {"data": {"orders": {"pageInfo": {"hasNextPage": False}, "edges": [{"node": o} for o in orders]}}}
        if "CrooksOrderForNewOrder" in query:
            number = int(str(variables.get("id") or "0").rsplit("/", 1)[-1])
            return {"data": {"order": order_node(number) if any(o[0] == number for o in ORDERS) else None}}
        if "FindCustomers" in query or "CrooksCustomerCandidates" in query:
            return {"data": {"customers": {"edges": [{"node": n} for n in self._people(str(variables.get("q") or ""))]}}}
        if "CrooksCustomerForOrder" in query:
            person = PEOPLE.get(str(variables.get("id") or ""))
            return {"data": {"customer": person and {
                "id": variables["id"], "displayName": person["name"], "numberOfOrders": str(person["orders"]),
                "defaultEmailAddress": {"emailAddress": person["email"]}, "defaultAddress": person["home"],
            }}}
        if "CrooksVariantSearch" in query:
            term = str(variables.get("q") or "").strip().lower()
            if term.startswith("sku:"):
                chosen = [p for p in CATALOGUE if any(v["sku"].lower() == term[4:] for v in p["variants"])]
            else:
                chosen = [p for p in CATALOGUE if term in p["title"].lower()]
            return {"data": {"products": {"pageInfo": {"hasNextPage": False}, "edges": [{"node": self._product(p)} for p in chosen]}}}
        if "CrooksVariantForOrderEdit" in query or "CrooksVariantSiblings" in query:
            found = VARIANTS.get(str(variables.get("id") or ""))
            if found is None:
                return {"data": {"productVariant": None}}
            product, variant = found
            return {"data": {"productVariant": {
                "id": variant["id"], "title": variant["title"], "sku": variant["sku"], "price": variant["price"],
                "availableForSale": variant["for_sale"], "inventoryQuantity": variant["stock"],
                "selectedOptions": [{"name": n, "value": val} for n, val in variant["options"]],
                "product": self._product(product),
            }}}
        if "CrooksDraftOrder" in query:
            draft = self.drafts.get(str(variables.get("id") or ""))
            return {"data": {"draftOrder": copy.deepcopy(draft) if draft else None}}
        return {"data": {}}

    # ---- the two mutations

    @staticmethod
    def _priced(index: int, line: dict[str, Any]) -> dict[str, Any]:
        if "variantId" in line:
            product, variant = VARIANTS[line["variantId"]]
            unit, title, variant_title = float(variant["price"]), product["title"], variant["title"]
        else:
            unit, title, variant_title = float(line["originalUnitPrice"]), line["title"], None
        off = line.get("appliedDiscount") or {}
        each = (unit * off["value"] / 100.0 if off.get("valueType") == "PERCENTAGE"
                else min(unit, off["value"]) if off.get("valueType") == "FIXED_AMOUNT" else 0.0)
        return {"id": f"gid://shopify/DraftOrderLineItem/{index}", "title": title, "variantTitle": variant_title,
                "quantity": line["quantity"], "custom": "variantId" not in line,
                "variant": {"id": line["variantId"]} if "variantId" in line else None,
                "appliedDiscount": dict(off) or None, "originalUnitPriceSet": _money(unit),
                "discountedTotalSet": _money((unit - each) * line["quantity"])}

    async def mutate(self, name: str, variables: dict) -> dict:
        reviewed = REVIEWED_MUTATIONS[name]
        assert set(variables) == set(reviewed.variables), "the reviewed variable set, exactly"
        for key, value in variables.items():
            if isinstance(value, dict) and reviewed.validate is not None:
                assert reviewed.validate(key, value), f"{name}.{key} is not the reviewed shape: {value}"
        self.mutations.append((name, copy.deepcopy(variables)))
        if name == "draft_order_create":
            body = variables["input"]
            lines = [self._priced(i, line) for i, line in enumerate(body["lineItems"])]
            goods = round(sum(float(line["discountedTotalSet"]["shopMoney"]["amount"]) for line in lines), 2)
            off = body.get("appliedDiscount") or {}
            cut = (goods * off["value"] / 100.0 if off.get("valueType") == "PERCENTAGE"
                   else min(goods, off["value"]) if off.get("valueType") == "FIXED_AMOUNT" else 0.0)
            postage = float((body.get("shippingLine") or {}).get("price") or 0)
            self.draft_number += 1
            draft_id = f"gid://shopify/DraftOrder/{self.draft_number}"
            self.drafts[draft_id] = {
                "id": draft_id, "name": f"#D{self.draft_number}", "status": "OPEN",
                "totalPriceSet": _money(round(goods - cut + postage, 2)), "subtotalPriceSet": _money(round(goods - cut, 2)),
                "totalShippingPriceSet": _money(postage), "totalTaxSet": _money(0),
                "appliedDiscount": dict(off) or None,
                "customer": {"id": body["customerId"], "displayName": PEOPLE[body["customerId"]]["name"]},
                "email": body.get("email") or "", "order": None,
                "lineItems": {"edges": [] if self.drop_lines else [{"node": line} for line in lines]},
            }
            return {"data": {"draftOrderCreate": {"draftOrder": copy.deepcopy(self.drafts[draft_id]), "userErrors": []}}}
        if name == "draft_order_complete":
            draft = self.drafts[variables["id"]]
            draft["status"], draft["order"] = "COMPLETED", {"id": "gid://shopify/Order/3001", "name": "CROOKS-3001"}
            return {"data": {"draftOrderComplete": {"draftOrder": copy.deepcopy(draft), "userErrors": []}}}
        raise AssertionError(f"nothing else may reach the shop ({name})")


# --------------------------------------------------------------------------- Claude, scripted


class Scripted:
    """Claude, as far as the routes are concerned: each turn runs the step the test queued —
    real tool calls through the real dispatcher and gate — and answers with what it returns."""

    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.prompts: list[str] = []
        self.steps: list = []
        self.calls: list = []            # every call made, with what it returned to "Claude"

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def health(self): return True, "fake"
    async def reset_session(self, session_id): ...
    async def set_system_prompt(self, prompt): ...
    async def interrupt(self, session_id): return True

    async def turn(self, session_id: str, text: str) -> TurnResult:
        self.prompts.append(text)
        session = self.runtime.sessions.get_or_create(session_id)
        calls: list = []
        step = self.steps.pop(0) if self.steps else None
        answer = await step(session, calls) if step is not None else "the model answered"
        self.calls.extend(calls)
        return TurnResult(text=answer, tool_calls=calls, session_id=session_id)


def calls_(*steps: tuple[str, Any]):
    """A turn that makes these tool calls in order. An argument given as a function is worked
    out from the calls before it, as Claude reads an id off the last result. Every call is held
    to what Claude is actually offered: the tool's own schema (`_claude_could_make`)."""
    async def step(session, calls):
        for name, args in steps:
            given = args(calls) if callable(args) else args
            _claude_could_make(name, given)
            await dispatch(name, given, session=session, timeout_s=5, calls=calls)
        return "Done."
    return step


def _claude_could_make(name: str, args: dict[str, Any]) -> None:
    from app.tools import registry
    from experience.harness import _fits

    spec = registry.get(name)
    properties = spec.input_schema.get("properties") or {}
    assert not set(args) - set(properties), f"{name} has no argument {sorted(set(args) - set(properties))}"
    for key in spec.input_schema.get("required") or []:
        assert key in args, f"{name} requires {key}"
    for key, value in args.items():
        assert not _fits(properties[key], value), f"{name}.{key}: {_fits(properties[key], value)}"


def last(calls, name: str) -> dict[str, Any]:
    return next(c.result for c in reversed(calls) if c.name == name and c.ok)


@pytest.fixture()
async def shop(monkeypatch, tmp_path):
    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)

    async def fake_scribe_health(self):
        return True, "fake scribe"

    monkeypatch.setattr(ScribeClient, "health", fake_scribe_health)
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))

    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        store = Counter()
        runtime.shopify = store
        shopify_tools.bind(store, threads_for=inbox())
        runtime.actions.ledger = ActionLedger(tmp_path)
        runtime.sessions = SessionManager()
        runtime.sessions.on_drop.append(runtime.actions.forget_session)
        runtime.provider = Scripted(runtime)
        runtime.settings = runtime.settings.model_copy(
            update={"writes_enabled": True, "allowed_logins": OWNER, "writes_local_owner": False, "tailscale_verify": False}
        )
        app.state.allowed_logins = runtime.allowed_logins
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            client.runtime, client.store, client.model = runtime, store, runtime.provider
            yield client


async def say(client, text: str, *steps, session_id: str = "g1") -> dict:
    """He says `text`; Claude makes `steps`; the body is what the tablet gets back."""
    client.model.steps.append(calls_(*steps))
    response = await client.post("/turn", json={"text": text, "session_id": session_id}, headers=PROXIED)
    assert response.status_code == 200, response.text
    return response.json()


async def tap(client, command: str, session_id: str = "g1", **fields) -> dict:
    response = await client.post("/command", data={"session_id": session_id, "command": command, **fields}, headers=PROXIED)
    assert response.status_code == 200, response.text
    return response.json()


def card(body: dict) -> dict:
    """The order being built, as the tablet draws it — and it is the FIRST card: the task, not
    the records read on the way to it."""
    items = [i for i in body["ui"] if i["type"] != "context_stack"]
    assert items and items[0]["type"] == "workspace", [i["type"] for i in items]
    return items[0]["data"]


def rows(data: dict) -> list[tuple[str, str, str, str]]:
    return [(r["title"], r["detail"].split(" · ")[0], r["quantity"], r["amount"]) for r in data["rows"]]


# ============================================================ 1. building an order by voice


async def open_theo(shop, **extra) -> dict:
    return await say(shop, "start an order for Theo Marsh with a black medium hoodie",
                     ("shopify_order_open", {"customer": "Theo Marsh", "item": "black medium hoodie", **extra}))


async def test_an_item_said_when_the_order_is_opened_goes_on_it(shop):
    """"It couldn't add the item." The item he named was typed into a field and never added;
    the card said "nothing on it yet". Now the line is on the card he is shown, at the
    catalogue's price, and nothing is blocking the Prepare."""
    body = await open_theo(shop)
    data = card(body)
    assert rows(data) == [("Convict Hoodie", "Black / M", "× 1", "£60.00")]
    assert data["blocked"] == "", data["blocked"]
    assert data["title"] == "Theo Marsh"
    assert shop.store.mutations == [], "nothing is created by opening"


async def test_a_custom_item_is_added_by_voice_to_the_same_card(shop):
    """"Or a custom item for that matter." A print the shop does not list goes on with his own
    title and price, and the SAME card comes back with it on — never a second card."""
    first = card(await open_theo(shop))
    body = await say(shop, "add a custom back print, twelve pounds, two of them",
                     ("shopify_order_build", {"add": [{"title": "Custom back print", "price": 12, "quantity": 2}]}))
    data = card(body)
    assert data["workspace_id"] == first["workspace_id"], "the same order, not another"
    assert rows(data) == [("Convict Hoodie", "Black / M", "× 1", "£60.00"), ("Custom back print", "", "× 2", "£24.00")]
    assert data["rows"][1]["stock"] == "custom item"
    assert data["subtitle"] == "2 lines, £84.00 of goods"
    assert len([i for i in body["ui"] if i["type"] == "workspace"]) == 1


async def test_a_quantity_changed_and_a_line_taken_off_by_voice(shop):
    await open_theo(shop)
    await say(shop, "and a cap", ("shopify_order_build", {"add": [{"item": "cap"}]}))
    body = await say(shop, "make the hoodie two and take the cap off",
                     ("shopify_order_build", {"lines": [{"line": 1, "quantity": 2}, {"line": 2, "quantity": 0}]}))
    assert rows(card(body)) == [("Convict Hoodie", "Black / M", "× 2", "£120.00")]


async def test_a_discount_on_one_line_as_a_percentage_or_an_amount(shop):
    """"It couldn't add a line discount." Ten per cent off the hoodie; five pounds off each cap."""
    await open_theo(shop)
    await say(shop, "add two caps", ("shopify_order_build", {"add": [{"item": "cap", "quantity": 2}]}))
    body = await say(shop, "take ten percent off the hoodie and a fiver off each cap",
                     ("shopify_order_build", {"lines": [{"line": 1, "percent_off": 10}, {"line": 2, "amount_off": 5}]}))
    data = card(body)
    hoodie, caps = data["rows"]
    assert (hoodie["discount"], hoodie["amount"], hoodie["was"]) == ("10% off", "£54.00", "£60.00")
    assert (caps["discount"], caps["amount"], caps["was"]) == ("£5.00 off each", "£26.00", "£36.00")
    assert data["subtitle"] == "2 lines, £80.00 of goods"


async def test_a_discount_on_the_whole_order_as_a_percentage_or_an_amount(shop):
    """"…or percent discount." On the order: 15%, then changed to £10 off."""
    await open_theo(shop)
    body = await say(shop, "fifteen percent off the order", ("shopify_order_build", {"percent_off": 15}))
    facts = {f["label"]: f["value"] for f in card(body)["facts"]}
    assert facts["Discount"] == "15% off the order"
    body = await say(shop, "actually make it a tenner off", ("shopify_order_build", {"amount_off": 10}))
    facts = {f["label"]: f["value"] for f in card(body)["facts"]}
    assert facts["Discount"] == "£10.00 off the order"
    choices = {c["name"]: [o["id"] for o in c["options"] if o["selected"]] for c in card(body)["choices"]}
    assert choices["discount_basis"] == ["amount"], "the card's own switch says money off, not per cent"
    body = await say(shop, "no discount", ("shopify_order_build", {"percent_off": 0}))
    assert "Discount" not in {f["label"] for f in card(body)["facts"]}


async def test_postage_a_note_and_where_it_goes_by_voice(shop):
    await open_theo(shop)
    body = await say(shop, "four pounds postage, note it's a gift, send it to 9 Oak Way, Cookham, SL6 9QT",
                     ("shopify_order_build", {"postage": 4, "note": "Gift, no receipt",
                                              "address": {"address1": "9 Oak Way", "city": "Cookham", "zip": "sl6 9qt", "country_code": "gb"}}))
    data = card(body)
    facts = {f["label"]: f["value"] for f in data["facts"]}
    assert facts["Postage"] == "£4.00" and facts["Address"] == "9 Oak Way, Cookham, SL6 9QT"
    assert {f["name"]: f["value"] for f in data["fields"]}["note"] == "Gift, no receipt"
    assert data["blocked"] == ""


async def test_the_customer_changed_by_voice_and_two_of_one_name_are_not_guessed(shop):
    await open_theo(shop)
    body = await say(shop, "no, it's for Mia Jones", ("shopify_order_build", {"customer": "Mia Jones"}))
    data = card(body)
    assert "2 customers match that name and I will not guess" in data["blocked"]
    assert all(a["enabled"] is False for a in data["actions"] if a["risk"] == "red")


async def test_an_item_that_is_several_is_a_choice_and_the_choice_is_taken_by_voice_or_by_tap(shop):
    """Five black hoodies match "black hoodie": none is added, all are offered on the card, and
    "the large" (said) or a tap on one (touched) puts that one on."""
    await say(shop, "an order for Theo Marsh", ("shopify_order_open", {"customer": "Theo Marsh"}))
    body = await say(shop, "add a black hoodie", ("shopify_order_build", {"add": [{"item": "black hoodie"}]}))
    data = card(body)
    assert data["rows"] == [] and len(data["picks"]) == 5
    assert data["picks_title"] == "Which one? 5 match 'black hoodie'"
    assert [p["detail"].split(" · ")[0] for p in data["picks"]] == ["Black / XS", "Black / S", "Black / M", "Black / L", "Black / XL"]
    assert data["picks"][4]["stock"] == "not for sale", "sold out is shown, not hidden"
    # Said: Claude reads the choices off its result and adds the one he named.
    body = await say(shop, "the large", ("shopify_order_build", {"add": [{"variant_id": vid(9113)}]}))
    assert rows(card(body)) == [("Convict Hoodie", "Black / L", "× 1", "£60.00")] and card(body)["picks"] == []
    # Touched: the same choice again, and a tap on the small's own Add.
    offered = card(await say(shop, "and another black hoodie", ("shopify_order_build", {"add": [{"item": "black hoodie"}]})))
    small = next(p for p in offered["picks"] if p["detail"].startswith("Black / S"))
    assert small["button"] == {"label": "Add", "command": "order.additem",
                               "args": f"workspace_id={data['workspace_id']}&variant_id={vid(9111)}"}
    tapped = await tap(shop, "order.additem", workspace_id=data["workspace_id"], variant_id=vid(9111))
    assert rows(card(tapped)) == [("Convict Hoodie", "Black / L", "× 1", "£60.00"), ("Convict Hoodie", "Black / S", "× 1", "£60.00")]
    # And once chosen, the choice is gone: a variant no card is offering now is not a choice.
    stale = await tap(shop, "order.additem", workspace_id=data["workspace_id"], variant_id=vid(9112))
    assert stale["ok"] is False and stale["code"] == "not_offered"


async def test_how_many_he_said_is_how_many_a_tap_on_the_choice_adds(shop):
    ident = card(await say(shop, "an order for Theo Marsh", ("shopify_order_open", {"customer": "Theo Marsh"})))["workspace_id"]
    await say(shop, "two black hoodies", ("shopify_order_build", {"add": [{"item": "black hoodie", "quantity": 2}]}))
    tapped = await tap(shop, "order.additem", workspace_id=ident, variant_id=vid(9113))
    assert rows(card(tapped)) == [("Convict Hoodie", "Black / L", "× 2", "£120.00")]


async def test_every_change_redraws_the_same_card_and_it_never_closes(shop):
    """Round 12: "a task is asked, a screen is shown, an edit is asked, the edit succeeds
    however the screen disappears". Every spoken change to the order comes back with the order's
    card first, the same workspace, as it now stands."""
    ident = card(await open_theo(shop))["workspace_id"]
    for said, args in (("add a cap", {"add": [{"item": "cap"}]}),
                       ("ten percent off the cap", {"lines": [{"line": 2, "percent_off": 10}]}),
                       ("postage three pounds", {"postage": 3}),
                       ("mark it paid", {"paid": True})):
        body = await say(shop, said, ("shopify_order_build", args))
        assert card(body)["workspace_id"] == ident, said
    assert {c["name"]: [o["id"] for o in c["options"] if o["selected"]] for c in card(body)["choices"]}["payment"] == ["paid"]


async def test_the_card_s_own_field_names_are_never_taken_for_a_customer_s_name(shop):
    """A customer's name, email and address, read for the order, are remembered as personal
    data so every log redacts them. The card's FIELD names — "email", "note", "customer" — are
    not: once they were, the timeline wrote every "email_thread" as "[name]_thread"."""
    await open_theo(shop)
    await say(shop, "add a print", ("shopify_order_build", {"add": [{"title": "Print", "price": 10}]}))
    seen = shop.runtime.sessions.get("g1").pii_seen
    assert {"Theo Marsh", "theo.marsh@example.com"} <= seen
    assert not {"email", "note", "customer", "item", "postage", "payment", "address"} & seen


async def test_the_model_is_told_the_order_is_there_to_change(shop):
    """The next sentence's "where we are" names the order being built and how it is changed,
    so "add a print to it" goes to that card rather than starting another."""
    ident = card(await open_theo(shop))["workspace_id"]
    await say(shop, "add a cap", ("shopify_order_build", {"add": [{"item": "cap"}]}))
    assert f"building a new order ({ident}) for Theo Marsh, 1 line, not created — change it with shopify_order_build" in shop.model.prompts[-1]
    await say(shop, "and a tote", ("shopify_order_build", {"add": [{"item": "tote"}]}))
    assert f"({ident}) for Theo Marsh, 2 lines," in shop.model.prompts[-1], "as it stood when he spoke"


# ------------------------------------------------------------ the hold, and what it makes


async def _prepare_and_hold(shop, ident: str, session_id: str = "g1") -> dict:
    staged = await tap(shop, "order.stage", session_id=session_id, workspace_id=ident)
    confirmation = next(i["data"] for i in staged["ui"] if i["type"] == "confirmation")
    proposal_id = confirmation["proposal_id"]
    armed = await shop.post(f"/actions/{proposal_id}/arm", data={"session_id": session_id}, headers=PROXIED)
    assert armed.status_code == 200, armed.text
    shop.runtime.actions.find(proposal_id).armed_at -= 1.0
    done = await shop.post(f"/actions/{proposal_id}/commit", data={"session_id": session_id},
                           headers={**PROXIED, "X-Crooks-Arm": armed.json()["nonce"]})
    assert done.status_code == 200, done.text
    return {"confirmation": confirmation, "done": done.json()}


async def test_the_hold_creates_exactly_the_lines_and_discounts_on_the_card(shop):
    """A catalogue line with its own discount, a custom line with its own price, a discount on
    the order and postage: the draft Shopify is sent carries exactly those, the card he holds is
    Shopify's arithmetic on them, and the completion is proven."""
    ident = card(await open_theo(shop))["workspace_id"]
    await say(shop, "a custom print at twelve pounds, ten percent off the hoodie, a fiver off the order, four pounds postage",
              ("shopify_order_build", {"add": [{"title": "Custom back print", "price": 12}],
                                       "lines": [{"line": 1, "percent_off": 10}], "amount_off": 5, "postage": 4}))
    held = await _prepare_and_hold(shop, ident)
    sent = [name for name, _ in shop.store.mutations]
    assert sent == ["draft_order_create", "draft_order_complete"]
    draft = shop.store.mutations[0][1]["input"]
    assert draft["lineItems"] == [
        {"variantId": vid(9112), "quantity": 1, "appliedDiscount": {"title": "Discount", "value": 10.0, "valueType": "PERCENTAGE"}},
        {"title": "Custom back print", "originalUnitPrice": "12.00", "quantity": 1},
    ]
    assert draft["appliedDiscount"] == {"title": "Discount", "value": 5.0, "valueType": "FIXED_AMOUNT"}
    assert draft["shippingLine"] == {"title": "Postage", "price": "4.00"}
    assert draft["customerId"] == THEO and draft["useCustomerDefaultAddress"] is True
    facts = {f["label"]: f["value"] for f in held["confirmation"]["facts"]}
    # £54 + £12 = £66 of goods, less £5, plus £4: Shopify's figure, on the card he held.
    assert facts["Total"] == "£65.00"
    assert facts["Discount"] == "£5.00 off the order; 10% off Convict Hoodie"
    assert facts["Items"] == "1 x Convict Hoodie (Black / M), 10% off, 1 x Custom back print (custom)"
    assert held["done"]["status"] == "verified"


async def test_a_draft_that_does_not_carry_the_card_is_never_offered_to_hold(shop):
    """Shopify made a draft without the lines asked for: nothing is offered, nothing completed,
    and the owner is told plainly."""
    ident = card(await open_theo(shop))["workspace_id"]
    shop.store.drop_lines = True
    staged = await tap(shop, "order.stage", workspace_id=ident)
    assert not [i for i in staged["ui"] if i["type"] == "confirmation"]
    assert "does not carry exactly the lines and discounts" in str(staged)
    assert [name for name, _ in shop.store.mutations] == ["draft_order_create"]


async def test_taps_still_build_it(shop):
    """The thumb's way in is unchanged: a typed discount, the basis switched to money, a line
    taken off by its own Remove."""
    data = card(await open_theo(shop))
    ident = data["workspace_id"]
    await tap(shop, "order.field", workspace_id=ident, field="discount", value="7.5")
    after = await tap(shop, "order.choose", workspace_id=ident, field="discount_basis", option="amount")
    assert {f["label"]: f["value"] for f in card(after)["facts"]}["Discount"] == "£7.50 off the order"
    removal = card(after)["rows"][0]["button"]
    assert removal["command"] == "order.removeitem" and removal["args"] == f"workspace_id={ident}&line=v9112"
    gone = await tap(shop, "order.removeitem", workspace_id=ident, line="v9112")
    assert card(gone)["rows"] == [] and "It has nothing on it" in card(gone)["blocked"]


# ============================================================ 2. finding by evidence


async def test_a_name_and_a_postcode_tell_two_customers_of_one_name_apart(shop):
    """Two Mia Joneses. The name alone is two people; the name and where it went is one."""
    body = await say(shop, "the Mia Jones in Reading, RG1 3AR",
                     ("shopify_find_order", {"name": "Mia Jones", "address": "RG1 3AR"}))
    result = next(t for t in body["tool_calls"] if t["name"] == "shopify_find_order")
    assert result["ok"], result
    session = shop.runtime.sessions.get("g1")
    found = [i["data"] for i in body["ui"] if i["type"] == "order"]
    assert [o["order_number"] for o in found] == ["#2103"], body["ui"]
    assert MIA_TWIN in session.issued_ids and MIA not in session.issued_ids


async def test_an_item_and_a_postcode_with_no_name_find_the_one_order(shop):
    body = await say(shop, "who ordered the black hoodie to SL6 2AB",
                     ("shopify_find_order", {"item": "black hoodie", "address": "SL6 2AB"}))
    assert [i["data"]["order_number"] for i in body["ui"] if i["type"] == "order"] == ["#2101"]
    searched = [v["q"] for q, v in shop.store.queries if "CrooksOrderEvidence" in q]
    assert searched and "sku:CRK-HOOD-BLK-M" in searched[0], "the item went to Shopify as the SKUs it names"


async def test_several_that_fit_are_a_short_choice_and_none_is_chosen(shop):
    """Mia (the Windsor one) has had two black hoodies sent to SL4 1QN."""
    body = await say(shop, "the black hoodie to SL4 1QN", ("shopify_find_order", {"item": "black hoodie", "address": "SL4 1QN"}))
    (listing,) = [i["data"] for i in body["ui"] if i["type"] == "order_list"]
    assert listing["title"] == "Which order?" and [o["order_number"] for o in listing["orders"]] == ["#2107", "#2102"]
    assert not [i for i in body["ui"] if i["type"] == "order"]


async def test_none_that_fits_says_so_plainly_and_which_fact_nothing_had(shop):
    body = await say(shop, "the bone hoodie to SL6 2AB", ("shopify_find_order", {"item": "bone hoodie", "address": "SL6 2AB"}))
    (empty,) = [i["data"] for i in body["ui"] if i["type"] == "order_list"]
    assert empty["empty"] is True
    assert empty["note"] == "I checked 1 order with bone hoodie on it; none has SL6 2AB in the delivery address.", empty


async def test_an_order_number_and_an_email_are_evidence_too(shop):
    body = await say(shop, "order 2104 for ava.stone@example.com going to Slough",
                     ("shopify_find_order", {"query": "2104", "email": "ava.stone@example.com", "address": "Slough"}))
    assert [i["data"]["order_number"] for i in body["ui"] if i["type"] == "order"] == ["#2104"]
    wrong = await say(shop, "order 2104 for theo", ("shopify_find_order", {"query": "2104", "name": "Theo Marsh"}))
    assert not [i for i in wrong["ui"] if i["type"] == "order"], "an order that is not his is not his"


async def test_an_order_is_returned_only_when_it_is_shown_to_match(shop):
    """A Shopify whose search ignored every filter would return every order; each is checked
    here against every fact, and only the one that has them all comes back."""
    shop.store.ignore_search = True
    body = await say(shop, "who ordered the black hoodie to SL6 2AB",
                     ("shopify_find_order", {"item": "black hoodie", "address": "SL6 2AB"}))
    assert [i["data"]["order_number"] for i in body["ui"] if i["type"] == "order"] == ["#2101"]


async def test_a_search_the_shop_did_not_answer_is_said_and_nothing_is_guessed(shop):
    shop.store.fail_orders = True
    body = await say(shop, "who ordered the black hoodie to SL6 2AB",
                     ("shopify_find_order", {"item": "black hoodie", "address": "SL6 2AB"}))
    assert not [i for i in body["ui"] if i["type"] in ("order", "workspace")]
    assert [t["ok"] for t in body["tool_calls"] if t["name"] == "shopify_find_order"] == [False]


# ============================================================ 3. the next size up


THE_SENTENCE = "find the customer who ordered the black hoodie to SL6 2AB and make a new order for them in the next size up"


def the_sentence(item: str, address: str):
    """Claude taking the sentence as asked: find the order by the evidence, then open a new
    order from it — its customer, its address — with the next size of the line that matched."""
    found = lambda calls: last(calls, "shopify_find_order")["orders"][0]  # noqa: E731
    return (
        ("shopify_find_order", {"item": item, "address": address}),
        ("shopify_order_open", lambda calls: {"order_id": found(calls)["order_id"],
                                              "variant_id": found(calls)["matched_items"][0]["variant_id"], "size_step": 1}),
    )


async def test_the_whole_sentence_is_one_request_and_ends_ready_to_confirm(shop):
    """THE complaint, in his words. One spoken request: the order found from the item and the
    postcode, a new order for its customer with the same garment one size up, going where the
    last one went — on screen first, ready for Prepare. Then the hold makes exactly that."""
    body = await say(shop, THE_SENTENCE, *the_sentence("black hoodie", "SL6 2AB"))
    assert len(shop.model.prompts) == 1, "one request"
    data = card(body)
    assert data["title"] == "Theo Marsh"
    assert rows(data) == [("Convict Hoodie", "Black / L", "× 1", "£60.00")], "M was ordered; L is one up"
    assert data["rows"][0]["stock"] == "7 in stock"
    facts = {f["label"]: f["value"] for f in data["facts"]}
    assert facts["Address"] == "as on CROOKS-2101: 3 Mill Lane, Bray, SL6 2AB" and facts["Made from"] == "order CROOKS-2101"
    assert data["blocked"] == "" and next(a for a in data["actions"] if a["id"] == "prepare")["enabled"] is True
    assert [i["type"] for i in body["ui"] if i["type"] != "context_stack"][:2] == ["workspace", "order"], \
        "the new order leads; the order that proved who it is for sits under it"
    assert not [i for i in body["ui"] if i["type"] in ("customer", "customer_list")], "no customer screen first"
    held = await _prepare_and_hold(shop, data["workspace_id"])
    draft = shop.store.mutations[0][1]["input"]
    assert draft["customerId"] == THEO and draft["lineItems"] == [{"variantId": vid(9113), "quantity": 1}]
    assert draft["shippingAddress"] == {"firstName": "Theo", "lastName": "Marsh", "address1": "3 Mill Lane", "city": "Bray",
                                        "zip": "SL6 2AB", "countryCode": "GB"}
    assert draft["useCustomerDefaultAddress"] is False
    assert held["done"]["status"] == "verified"


async def test_there_is_no_size_past_the_largest_and_clive_says_so(shop):
    body = await say(shop, "the jeans that went to SL1 1AA, again a size up", *the_sentence("jeans", "SL1 1AA"))
    data = card(body)
    assert data["rows"] == []
    assert {f["label"]: f["value"] for f in data["facts"]}["That item"] == "34 is the largest size Yard Jeans comes in."
    opened = next(t for t in body["tool_calls"] if t["name"] == "shopify_order_open")
    assert opened["ok"]


async def test_out_of_stock_is_shown_not_hidden(shop):
    """28 was ordered; 30 is out of stock but sold on backorder — it goes on, flagged. The
    black XL is out of stock and NOT sold on — it goes on flagged, and the Prepare says why."""
    body = await say(shop, "ravi's jeans to B3 3AS, next size up", *the_sentence("jeans", "B3 3AS"))
    data = card(body)
    assert rows(data) == [("Yard Jeans", "Indigo / 30", "× 1", "£85.00")] and data["rows"][0]["stock"] == "out of stock"
    assert data["blocked"] == ""
    body = await say(shop, "ava's black hoodie to SL1, next size up", *the_sentence("black hoodie", "SL1 1AA"))
    data = card(body)
    assert data["rows"][0]["detail"].startswith("Black / XL") and data["rows"][0]["stock"] == "not for sale"
    assert "not for sale" in data["blocked"]


async def test_no_size_option_and_one_size_get_no_guess(shop):
    tote = await say(shop, "ravi's tote, next size up", *the_sentence("tote", "B3 3AS"))
    assert {f["label"]: f["value"] for f in card(tote)["facts"]}["That item"] == "Yard Tote has no size option, so there is no other size to go to."
    cap = await say(shop, "theo's cap, a size up", *the_sentence("cap", "SL6 2AB"))
    assert {f["label"]: f["value"] for f in card(cap)["facts"]}["That item"] == "Crooks Cap comes in one size only."


async def test_a_colour_that_stops_short_is_said_not_skipped(shop):
    """Bone comes in S and M. One up from M in Bone does not exist; the Mac does not jump to
    another colour or the size after."""
    body = await say(shop, "the bone hoodie to RG1 3AR, next size up", *the_sentence("bone hoodie", "RG1 3AR"))
    assert {f["label"]: f["value"] for f in card(body)["facts"]}["That item"] == "There is no Bone Convict Hoodie in L. It comes in S, M."
    assert card(body)["rows"] == []


# ============================================================ the rules underneath


@pytest.mark.parametrize("values,expected", [
    (["L", "S", "XL", "M"], ["S", "M", "L", "XL"]),
    (["XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL"], ["XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL"]),
    (["Large", "Small", "Medium"], ["Small", "Medium", "Large"]),
    (["2XL", "XL", "3XL"], ["XL", "2XL", "3XL"]),
    (["M/L", "S/M", "L/XL"], ["S/M", "M/L", "L/XL"]),
    (["10", "8", "6", "12"], ["6", "8", "10", "12"]),
    (["32", "28", "30", "34"], ["28", "30", "32", "34"]),
    (["UK 10", "UK 8"], ["UK 8", "UK 10"]),
])
def test_sizes_are_ordered_as_a_scale(values, expected):
    assert sizes.ladder(values)[0] == expected


@pytest.mark.parametrize("values,why", [
    (["One size"], "one size"), (["Regular", "Tall"], "not a scale"), (["S", "32"], "not a scale"),
    (["M", "Medium"], "not a scale"),
])
def test_values_that_are_not_a_scale_are_not_stepped(values, why):
    assert sizes.ladder(values) == ([], why)


def test_the_reviewed_draft_shape_takes_a_custom_line_and_line_discounts_and_nothing_looser():
    good = {"customerId": THEO, "lineItems": [
        {"variantId": vid(9112), "quantity": 1, "appliedDiscount": {"title": "Discount", "value": 10.0, "valueType": "PERCENTAGE"}},
        {"title": "Custom back print", "originalUnitPrice": "12.00", "quantity": 2},
    ], "appliedDiscount": {"title": "Discount", "value": 5.0, "valueType": "FIXED_AMOUNT"}}
    assert draft_order_input_ok(good)
    bad_lines = (
        {"variantId": vid(9112), "quantity": 1, "originalUnitPrice": "0.01"},                 # a price of ours on a catalogue line
        {"title": "Print", "originalUnitPrice": "12.00", "quantity": 1, "variantId": vid(9112)},
        {"title": "", "originalUnitPrice": "12.00", "quantity": 1},
        {"title": "Print", "originalUnitPrice": "1200.00", "quantity": 1},                   # "twelve" misheard
        {"title": "Print", "originalUnitPrice": 12.0, "quantity": 1},                        # a float, not Shopify's decimal
        {"title": "<b>Print</b>", "originalUnitPrice": "12.00", "quantity": 1},
        {"variantId": vid(9112), "quantity": 1, "appliedDiscount": {"title": "D", "value": 150, "valueType": "PERCENTAGE"}},
        {"variantId": vid(9112), "quantity": 1, "appliedDiscount": {"title": "D", "value": 5000, "valueType": "FIXED_AMOUNT"}},
        {"variantId": vid(9112), "quantity": 0},
    )
    for line in bad_lines:
        assert not draft_order_input_ok({**good, "lineItems": [line]}), line


async def test_a_variant_nobody_looked_up_cannot_be_added_by_voice(shop):
    """The model may add a variant only when a read in this conversation returned it — the
    same rule as every id — so a guessed variant id is refused, and says so, and the rest of
    the order is untouched."""
    await open_theo(shop)
    body = await say(shop, "add variant 9230", ("shopify_order_build", {"add": [{"variant_id": vid(9230)}]}))
    assert rows(card(body)) == [("Convict Hoodie", "Black / M", "× 1", "£60.00")]
    told = last(shop.model.calls, "shopify_order_build")
    assert told["not_done"] == [{"asked": vid(9230), "why": "That is not an item this conversation has looked up; search for it first."}]


async def test_what_cannot_be_done_is_said_and_the_rest_still_happens(shop):
    """Sixty is not fifty: a quantity past the limit is refused, never clamped. A discount
    bigger than the price is refused. A custom item with no price is refused. Everything else
    in the same sentence is applied, and the card comes back with it."""
    await open_theo(shop)
    body = await say(shop, "sixty hoodies, eighty quid off the hoodie, a print with no price, and postage of three",
                     ("shopify_order_build", {"lines": [{"line": 1, "quantity": 60}, {"line": 1, "amount_off": 80}],
                                              "add": [{"title": "Print"}], "postage": 3}))
    told = last(shop.model.calls, "shopify_order_build")
    assert [n["why"] for n in told["not_done"]] == [
        "How many is a whole number from 1 to 50.",
        "£80.00 off each is more than Convict Hoodie costs (£60.00).",
        "A custom item needs a name and a price.",
    ]
    assert told["done"] == ["postage £3.00"]
    data = card(body)
    assert rows(data) == [("Convict Hoodie", "Black / M", "× 1", "£60.00")]
    assert {f["label"]: f["value"] for f in data["facts"]}["Postage"] == "£3.00"


async def test_a_catalogue_that_does_not_answer_is_said_and_the_card_stays(shop):
    """A slow or failed Shopify read in the middle of building: the item it was for is not
    added and he is told; the custom item said in the same breath is added; the card is back."""
    await open_theo(shop)
    real = shop.store.graphql

    async def catalogue_down(query, variables=None):
        if "CrooksVariantSearch" in query:
            raise ShopifyError("Shopify did not answer.")
        return await real(query, variables)

    shop.store.graphql = catalogue_down
    body = await say(shop, "add a cap and a print at ten pounds",
                     ("shopify_order_build", {"add": [{"item": "cap"}, {"title": "Print", "price": 10}]}))
    told = last(shop.model.calls, "shopify_order_build")
    assert told["not_done"] == [{"asked": "cap", "why": "The shop did not answer about that item, so nothing was added for it. Ask again."}]
    assert rows(card(body))[-1] == ("Print", "", "× 1", "£10.00")


async def test_an_order_that_cannot_be_read_leaves_the_one_being_built_as_it_was(shop):
    """He is building Theo's order and asks for a new one from an order the shop then fails to
    read: nothing replaces Theo's order, which is still there to go back to."""
    ident = card(await open_theo(shop))["workspace_id"]
    real = shop.store.graphql

    async def order_down(query, variables=None):
        if "CrooksOrderForNewOrder" in query:
            raise ShopifyError("Shopify did not answer.")
        return await real(query, variables)

    shop.store.graphql = order_down
    body = await say(shop, THE_SENTENCE, *the_sentence("black hoodie", "SL6 2AB"))
    assert [t["ok"] for t in body["tool_calls"]] == [True, False]
    branch = shop.runtime.sessions.get("g1").branch()
    assert branch.workspace["workspace_id"] == ident and len(branch.workspace["facts"]["lines"]) == 1


async def test_no_order_being_built_is_said_rather_than_one_being_invented(shop):
    body = await say(shop, "add a cap to the order", ("shopify_order_build", {"add": [{"item": "cap"}]}))
    assert [t["ok"] for t in body["tool_calls"]] == [False]
    assert not [i for i in body["ui"] if i["type"] == "workspace"]


async def test_a_tap_during_a_turn_and_the_turn_both_land_on_the_one_order(shop):
    """He taps Remove on the cap while Claude is still working out "and a print at ten pounds".
    Both are changes to the one order: the tap's lands first, the sentence's after it, and the
    card the turn returns has both — the cap gone, the print there."""
    import asyncio

    ident = card(await open_theo(shop))["workspace_id"]
    await say(shop, "and a cap", ("shopify_order_build", {"add": [{"item": "cap"}]}))
    reached, release = asyncio.Event(), asyncio.Event()

    async def slow(session, calls):
        reached.set()
        await release.wait()
        await dispatch("shopify_order_build", {"add": [{"title": "Print", "price": 10}]}, session=session, timeout_s=5, calls=calls)
        shop.model.calls.extend(calls)
        return "Added."

    shop.model.steps.append(slow)
    turn = asyncio.create_task(shop.post("/turn", json={"text": "and a print at ten pounds", "session_id": "g1"}, headers=PROXIED))
    await asyncio.wait_for(reached.wait(), 5)
    tapped = await tap(shop, "order.removeitem", workspace_id=ident, line="v9301")
    assert [r["title"] for r in card(tapped)["rows"]] == ["Convict Hoodie"]
    release.set()
    body = (await asyncio.wait_for(turn, 5)).json()
    assert [r["title"] for r in card(body)["rows"]] == ["Convict Hoodie", "Print"]


# ============================================================ the golden world


async def test_in_the_golden_world_the_sentence_finds_mias_two_hoodies_and_asks_which():
    """The shop every scenario and every browser run uses. Mia Jones has had two black hoodies
    sent to SL4 1QN — an S in August and an M today — so "the black hoodie to SL4 1QN" is two
    orders, and they are the choice; said with the size, it is one, and the new order is the L."""
    from experience.harness import harness

    async with harness(admitted=True) as h:
        found = await h.ask("who ordered the black hoodie to SL4 1QN",
                            ("shopify_find_order", {"item": "black hoodie", "address": "SL4 1QN"}))
        assert found.unmakeable == {}
        listing = found.data("order_list")
        assert listing["title"] == "Which order?" and [o["order_number"] for o in listing["orders"]] == ["#1938", "#1912"]

        def opened(calls):
            order = calls[0].result["orders"][0]
            return {"order_id": order["order_id"], "variant_id": order["matched_items"][0]["variant_id"], "size_step": 1}

        made = await h.ask("the medium one to SL4 1QN, a new order a size up",
                           ("shopify_find_order", {"item": "black medium hoodie", "address": "SL4 1QN"}),
                           ("shopify_order_open", opened))
        assert made.unmakeable == {}
        assert made.surface_types[0] == "workspace"
        data = made.data("workspace")
        assert data["title"] == "Mia Jones" and [r["detail"].split(" · ")[0] for r in data["rows"]] == ["Black / L"]
        assert data["blocked"] == ""

        largest = await h.ask("david's hoodie to LS1 6BY, a size up",
                              ("shopify_find_order", {"item": "hoodie", "address": "LS1 6BY"}),
                              ("shopify_order_open", opened))
        facts = {f["label"]: f["value"] for f in largest.data("workspace")["facts"]}
        assert facts["That item"] == "L is the largest size Convict Hoodie comes in."
