"""Round 12's second check: a card makes ONE thing, and a hold card is only for what its card says.

The first fix made an order card finished once its order existed. The check that followed found
what that left open, each of it money:

1. Only the ORDER card finished. A store credit card, redrawn after a verified £20 by the new
   "the card it was prepared from, drawn again" (app/screen.py `after_gesture`), came back as
   "Store credit · not given" with Prepare live — and a second hold gave another £20. A code
   card came back "not created" the same way. Now finishing is every workspace's
   (app/families/_workspace.py "made once"), and each family draws its done card and refuses
   everything after.
2. Prepare again after a TAP handed back the OLD hold card: the engine takes the same tool and
   arguments in one epoch as the same proposal, and a tap does not move the epoch. He prepared
   a hoodie and a £12 print, took the print off, prepared again — and held a card for £72,
   beside an order that showed the hoodie alone. Now any change to a card withdraws the hold
   card prepared from it, says so on the card, and Prepare again is a new hold card for what
   the card says; and a hold card whose card has changed is never applied, whatever path.
3. One failed completion locked the card for ever as "sent, not confirmed". Now a completion
   Shopify refused, or one that never left, gives the card back with the reason; only one that
   left and was never answered stays locked.
4. The order the hold had just made was not issued to the conversation, so "add a note to it"
   needed a search first.

Every test reaches the Mac as the tablet does — /turn with Claude scripted, /command for taps,
/actions for the hold — against a fake shop (tests/test_r12_orders.py) that also keeps store
credit and discount codes. Every name here is invented.
"""

from __future__ import annotations

import copy
import re
from typing import Any

import httpx
import pytest

from app.actions.ledger import ActionLedger
from app.clients.shopify import REVIEWED_MUTATIONS, ShopifyError, ShopifyRefused, ShopifyUnreached
from app.main import app
from app.session.manager import SessionManager
from app.tools import shopify_tools
from tests.test_context import inbox
from tests.test_r12_orders import PROXIED, THEO, Counter, Scripted, card, open_theo, say, tap, vid

SCOPES = ("read_orders", "write_orders", "read_customers", "read_products", "read_draft_orders", "write_draft_orders",
          "read_store_credit_accounts", "write_store_credit_account_transactions", "read_discounts", "write_discounts")


class Shop(Counter):
    """The order shop, with store credit on Theo's account and discount codes — and a Shopify
    that can refuse a completion, be unreachable, or take one and lose the answer."""

    def __init__(self) -> None:
        super().__init__()
        self.balance = 15.0                     # Theo's store credit, GBP
        self.codes: dict[str, dict[str, Any]] = {}
        self.refuse_complete = False            # answers the completion with a user error
        self.unreachable = False                # the connection is never made
        self.lose_answer = False                # completes it, and the answer never comes back
        self.reads_fail = False                 # the draft cannot be read back either

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        variables = dict(variables or {})
        if self.reads_fail and "CrooksDraftOrder" in query:
            raise ShopifyUnreached("Could not reach Shopify: connection refused")
        if "CrooksScopes" in query:
            return {"data": {"currentAppInstallation": {"accessScopes": [{"handle": h} for h in SCOPES]}}}
        if "CrooksStoreCredit" in query:
            if str(variables.get("id")) != THEO:
                return {"data": {"customer": None}}
            return {"data": {"customer": {
                "id": THEO, "displayName": "Theo Marsh", "defaultEmailAddress": {"emailAddress": "theo.marsh@example.com"},
                "storeCreditAccounts": {"edges": [{"node": {"id": "gid://shopify/StoreCreditAccount/1",
                                                           "balance": {"amount": f"{self.balance:.2f}", "currencyCode": "GBP"}}}]},
            }}}
        if "CrooksDiscountByCode" in query:
            found = self.codes.get(str(variables.get("code") or "").upper())
            return {"data": {"codeDiscountNodeByCode": copy.deepcopy(found)}}
        if "query Inventory" in query:
            from tests.test_r12_orders import CATALOGUE

            term = str(variables.get("q") or "").strip().strip('"').lower()
            chosen = [p for p in CATALOGUE if any(w in p["title"].lower() for w in term.split())]
            return {"data": {"products": {"pageInfo": {"hasNextPage": False}, "edges": [{"node": {
                "id": p["id"], "title": p["title"], "status": p["status"], "totalInventory": sum(v["stock"] for v in p["variants"]),
                "variants": {"edges": [{"node": {"id": v["id"], "title": v["title"], "sku": v["sku"], "inventoryQuantity": v["stock"],
                                                  "inventoryPolicy": "DENY", "inventoryItem": {"tracked": True}}}
                                       for v in p["variants"]]}}} for p in chosen]}}}
        if "CrooksOrderContext" in query:
            # An order read in full, for a record Back lands on (the parts the card is drawn from).
            from tests.test_r12_orders import ORDERS, order_node

            number = int(str(variables.get("id") or "0").rsplit("/", 1)[-1])
            if not any(o[0] == number for o in ORDERS):
                return {"data": {"order": None}}
            node = order_node(number)
            node.update({"fulfillments": [], "refunds": [], "events": {"edges": []}, "tags": [], "note": ""})
            for index, edge in enumerate(node["lineItems"]["edges"]):
                edge["node"].update({"id": f"gid://shopify/LineItem/{number}{index}", "currentQuantity": edge["node"]["quantity"]})
            return {"data": {"order": node}}
        if "CrooksCustomerOrders" in query:
            return {"data": {"customer": None}}
        if "CrooksOrderNote" in query:
            wanted = str(variables.get("id") or "")
            known = wanted == "gid://shopify/Order/3001" and any(d.get("order") for d in self.drafts.values())
            return {"data": {"order": {"id": wanted, "name": "CROOKS-3001", "note": ""} if known else None}}
        return await super().graphql(query, variables)

    async def mutate(self, name: str, variables: dict) -> dict:
        if self.unreachable:
            raise ShopifyUnreached("Could not reach Shopify: connection refused")
        if name == "store_credit_credit":
            reviewed = REVIEWED_MUTATIONS[name]
            assert set(variables) == set(reviewed.variables) and reviewed.validate("creditInput", variables["creditInput"])
            self.mutations.append((name, copy.deepcopy(variables)))
            self.balance = round(self.balance + float(variables["creditInput"]["creditAmount"]["amount"]), 2)
            money = {"amount": f"{self.balance:.2f}", "currencyCode": "GBP"}
            return {"data": {"storeCreditAccountCredit": {"storeCreditAccountTransaction": {
                "amount": dict(variables["creditInput"]["creditAmount"]), "balanceAfterTransaction": money,
                "account": {"id": "gid://shopify/StoreCreditAccount/1", "balance": money}}, "userErrors": []}}}
        if name == "discount_code_create":
            reviewed = REVIEWED_MUTATIONS[name]
            assert set(variables) == set(reviewed.variables)
            assert reviewed.validate is None or reviewed.validate("basicCodeDiscount", variables["basicCodeDiscount"])
            self.mutations.append((name, copy.deepcopy(variables)))
            sent = variables["basicCodeDiscount"]
            got = sent["customerGets"]["value"]
            value = ({"__typename": "DiscountPercentage", "percentage": got["percentage"]} if "percentage" in got
                     else {"__typename": "DiscountAmount", "amount": {"amount": got["discountAmount"]["amount"], "currencyCode": "GBP"}})
            node = {"id": "gid://shopify/DiscountCodeNode/9999", "codeDiscount": {
                "__typename": "DiscountCodeBasic", "title": sent["title"], "status": "ACTIVE", "startsAt": sent["startsAt"],
                "endsAt": sent.get("endsAt"), "usageLimit": sent.get("usageLimit"), "asyncUsageCount": 0,
                "customerGets": {"value": value}}}
            self.codes[sent["code"].upper()] = node
            return {"data": {"discountCodeBasicCreate": {"codeDiscountNode": {"id": node["id"], "codeDiscount": {
                "title": sent["title"], "status": "ACTIVE", "startsAt": sent["startsAt"], "endsAt": sent.get("endsAt"),
                "usageLimit": sent.get("usageLimit"), "appliesOncePerCustomer": sent.get("appliesOncePerCustomer"),
                "codes": {"edges": [{"node": {"code": sent["code"]}}]}}}, "userErrors": []}}}
        if name == "draft_order_complete" and self.refuse_complete:
            self.mutations.append((name, copy.deepcopy(variables)))
            raise ShopifyRefused("The draft order cannot be completed: a payment term is required.")
        answer = await super().mutate(name, variables)
        if name == "draft_order_complete" and self.lose_answer:
            self.reads_fail = True
            raise ShopifyError("Shopify took too long to answer.")
        return answer


@pytest.fixture()
async def shop(monkeypatch, tmp_path):
    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    async def fake_scribe_health(self):
        return True, "fake scribe"

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    monkeypatch.setattr(ScribeClient, "health", fake_scribe_health)
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))
    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        store = Shop()
        runtime.shopify = store
        shopify_tools.bind(store, threads_for=inbox())
        runtime.actions.ledger = ActionLedger(tmp_path)
        runtime.sessions = SessionManager()
        runtime.sessions.on_drop.append(runtime.actions.forget_session)
        runtime.provider = Scripted(runtime)
        runtime.settings = runtime.settings.model_copy(
            update={"writes_enabled": True, "allowed_logins": "owner@example.com", "writes_local_owner": False,
                    "tailscale_verify": False})
        app.state.allowed_logins = runtime.allowed_logins
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            client.runtime, client.store, client.model = runtime, store, runtime.provider
            yield client


def _hold_card(body: dict) -> dict:
    (found,) = [i["data"] for i in body["ui"] if i["type"] == "confirmation"]
    return found


async def _hold(shop, proposal_id: str) -> httpx.Response:
    """The owner's hold and drag, as the tablet makes it: arm, the dwell, commit with the token."""
    armed = await shop.post(f"/actions/{proposal_id}/arm", data={"session_id": "g1"}, headers=PROXIED)
    if armed.status_code != 200:
        return armed
    shop.runtime.actions.find(proposal_id).armed_at -= 1.0
    return await shop.post(f"/actions/{proposal_id}/commit", data={"session_id": "g1"},
                           headers={**PROXIED, "X-Crooks-Arm": armed.json()["nonce"]})


def _workspace(ui: list[dict], ident: str) -> dict:
    (found,) = [i["data"] for i in ui if i["type"] == "workspace" and i["data"]["workspace_id"] == ident]
    return found


def sent(shop, name: str) -> int:
    return sum(1 for n, _ in shop.store.mutations if n == name)


async def open_credit(shop) -> str:
    body = await say(shop, "put twenty pounds of store credit on Theo Marsh",
                     ("shopify_find_customer", {"query": "Theo Marsh"}),
                     ("shopify_store_credit", {"customer_id": THEO, "amount": 20}))
    return card(body)["workspace_id"]


async def open_code(shop) -> str:
    body = await say(shop, "make a code AUTUMN20 for twenty percent off",
                     ("shopify_discount_open", {"code": "AUTUMN20", "percent": 20}))
    return card(body)["workspace_id"]


# ============================================================ 1. every card makes one thing


async def test_1_a_credit_given_is_given_once(shop):
    """The blocker. After a verified £20 the card came back "not given" with Prepare live, and a
    second hold gave another £20."""
    ident = await open_credit(shop)
    staged = await tap(shop, "credit.stage", workspace_id=ident)
    done = await _hold(shop, _hold_card(staged)["proposal_id"])
    assert done.status_code == 200 and done.json()["status"] == "verified", done.text
    assert shop.store.balance == 35.0

    given = _workspace(done.json()["ui"], ident)
    assert given["kicker"] == "Store credit · given" and given["settled"] == "created" and given["settled_word"] == "Given"
    assert given["fields"] == [] and not [a for a in given["actions"] if a["id"] == "prepare"]
    assert {f["label"]: f["value"] for f in given["facts"]}["Has now"] == "£35.00"

    again = await tap(shop, "credit.stage", workspace_id=ident)
    assert again["ok"] is False and "This credit is given — £20.00 is on Theo Marsh" in again["detail"], again
    typed = await tap(shop, "credit.field", workspace_id=ident, field="amount", value="40")
    assert typed["ok"] is False and "This credit is given" in typed["detail"]
    brought = await say(shop, "bring that back", ("show_again", {"kind": "building"}))
    assert _workspace(brought["ui"], ident)["kicker"] == "Store credit · given"
    assert sent(shop, "store_credit_credit") == 1 and shop.store.balance == 35.0


async def test_1_a_code_created_is_created_once(shop):
    """The same for a discount code: Shopify would refuse the second, and the card was still
    wrong — "not created", Prepare live."""
    ident = await open_code(shop)
    staged = await tap(shop, "discount.stage", workspace_id=ident)
    done = await _hold(shop, _hold_card(staged)["proposal_id"])
    assert done.json()["status"] == "verified", done.text
    made = _workspace(done.json()["ui"], ident)
    assert made["kicker"] == "Discount code · created" and made["title"] == "AUTUMN20" and made["settled"] == "created"
    assert made["fields"] == [] and made["choices"] == [] and not [a for a in made["actions"] if a["id"] == "prepare"]
    again = await tap(shop, "discount.stage", workspace_id=ident)
    assert again["ok"] is False and "AUTUMN20 is created" in again["detail"]
    chose = await tap(shop, "discount.choose", workspace_id=ident, field="basis", option="amount")
    assert chose["ok"] is False
    assert sent(shop, "discount_code_create") == 1


# ============================================================ 2. a hold card is for what its card says


async def test_2_a_tap_after_prepare_withdraws_the_hold_card_and_prepare_again_holds_the_card(shop):
    """The probe, as it was found: a hoodie and a £12 print prepared (£72), the print taken off
    with a tap, Prepare again — and the old £72 hold card came back beside a card showing the
    hoodie alone. Holding it made the £72 order."""
    ident = card(await open_theo(shop))["workspace_id"]
    await say(shop, "and a print at twelve pounds", ("shopify_order_build", {"add": [{"title": "Print", "price": 12}]}))
    first = _hold_card(await tap(shop, "order.stage", workspace_id=ident))
    assert {f["label"]: f["value"] for f in first["facts"]}["Total"] == "£72.00"

    tapped = await tap(shop, "order.removeitem", workspace_id=ident, line="c1")
    assert tapped["changed"]["withdrawn"] == [first["proposal_id"]]
    assert tapped["changed"]["withdrawn_words"] == "The order changed — prepare it again."
    assert card(tapped)["notes"][0] == "The order changed — prepare it again."
    assert shop.runtime.actions.find(first["proposal_id"]).status.value == "REVOKED"

    second = _hold_card(await tap(shop, "order.stage", workspace_id=ident))
    assert second["proposal_id"] != first["proposal_id"], "a new hold card, not the old one handed back"
    assert {f["label"]: f["value"] for f in second["facts"]}["Total"] == "£60.00"

    stale = await _hold(shop, first["proposal_id"])
    assert stale.status_code != 200 or stale.json().get("status") != "verified"
    done = await _hold(shop, second["proposal_id"])
    assert done.json()["status"] == "verified", done.text
    completed = [v["id"] for n, v in shop.store.mutations if n == "draft_order_complete"]
    assert len(completed) == 1
    assert [e["node"]["title"] for e in shop.store.drafts[completed[0]]["lineItems"]["edges"]] == ["Convict Hoodie"]


async def test_2_a_spoken_change_after_prepare_withdraws_the_hold_card_too(shop):
    ident = card(await open_theo(shop))["workspace_id"]
    await say(shop, "and a print at twelve pounds", ("shopify_order_build", {"add": [{"title": "Print", "price": 12}]}))
    first = _hold_card(await tap(shop, "order.stage", workspace_id=ident))
    body = await say(shop, "take the print off", ("shopify_order_build", {"lines": [{"line": 2, "quantity": 0}]}))
    assert first["proposal_id"] in body["revoked"]
    assert card(body)["notes"][0] == "The order changed — prepare it again."
    second = _hold_card(await tap(shop, "order.stage", workspace_id=ident))
    assert second["proposal_id"] != first["proposal_id"]
    assert (await _hold(shop, first["proposal_id"])).status_code != 200


async def test_2_a_hold_card_whose_card_moved_is_never_applied_whatever_the_path(shop):
    """The floor under the withdrawal: a card changed without passing through it (anything that
    ever forgets to) still cannot have its old hold card applied — refused at the door, and
    stale in the engine's own precondition for an order."""
    from app.tools import registry

    ident = card(await open_theo(shop))["workspace_id"]
    first = _hold_card(await tap(shop, "order.stage", workspace_id=ident))
    workspace = shop.runtime.sessions.get("g1").branch().workspace
    workspace["facts"]["lines"][0]["quantity"] = 3          # the card moved, and nothing withdrew
    refused = await _hold(shop, first["proposal_id"])
    assert refused.status_code == 409 and "The card changed since this was prepared" in refused.text
    assert sent(shop, "draft_order_complete") == 0

    second = _hold_card(await tap(shop, "order.stage", workspace_id=ident))
    workspace["facts"]["lines"][0]["quantity"] = 4
    armed = await shop.post(f"/actions/{second['proposal_id']}/arm", data={"session_id": "g1"}, headers=PROXIED)
    shop.runtime.actions.find(second["proposal_id"]).armed_at -= 1.0
    result = await shop.runtime.actions.commit(second["proposal_id"], "g1", caller="test", spec_lookup=registry.get,
                                               nonce=armed.json()["nonce"])
    assert result.code == "stale" and sent(shop, "draft_order_complete") == 0


async def test_2_a_credit_or_a_code_changed_after_prepare_withdraws_its_hold_card(shop):
    ident = await open_credit(shop)
    first = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))
    typed = await tap(shop, "credit.field", workspace_id=ident, field="amount", value="30")
    assert typed["changed"]["withdrawn"] == [first["proposal_id"]]
    assert card(typed)["notes"][0] == "The credit changed — prepare it again."
    second = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))
    assert second["proposal_id"] != first["proposal_id"]
    assert {f["label"]: f["value"] for f in second["facts"]}["Credit"] == "£30.00"

    code = await open_code(shop)
    first = _hold_card(await tap(shop, "discount.stage", workspace_id=code))
    typed = await tap(shop, "discount.field", workspace_id=code, field="value", value="25")
    assert typed["changed"]["withdrawn"] == [first["proposal_id"]]
    assert card(typed)["notes"][0] == "The code changed — prepare it again."


# ============================================================ 3. a failed completion gives the card back


async def test_3_a_completion_shopify_refused_gives_the_card_back_with_the_reason(shop):
    ident = card(await open_theo(shop))["workspace_id"]
    shop.store.refuse_complete = True
    first = _hold_card(await tap(shop, "order.stage", workspace_id=ident))
    done = (await _hold(shop, first["proposal_id"])).json()
    assert done["status"] == "failed", done
    back = _workspace(done["ui"], ident)
    assert back["kicker"] == "A new order · not created" and back["settled"] == ""
    assert back["notes"][0].startswith("The order was not created: ") and "a payment term is required" in back["notes"][0]
    shop.store.refuse_complete = False
    again = _hold_card(await tap(shop, "order.stage", workspace_id=ident))
    assert (await _hold(shop, again["proposal_id"])).json()["status"] == "verified"


async def test_3_a_completion_that_never_left_gives_the_card_back(shop):
    """The connection was never made — and Shopify cannot be read back either, so the engine
    cannot prove anything. It never left, so nothing was made, and the card is his again."""
    ident = card(await open_theo(shop))["workspace_id"]
    first = _hold_card(await tap(shop, "order.stage", workspace_id=ident))
    shop.store.unreachable, shop.store.reads_fail = True, True
    done = (await _hold(shop, first["proposal_id"])).json()
    assert done["status"] in ("failed", "unverified"), done
    back = _workspace(done["ui"], ident)
    assert back["settled"] == "" and "Could not reach Shopify" in back["notes"][0], back
    shop.store.unreachable, shop.store.reads_fail = False, False
    again = _hold_card(await tap(shop, "order.stage", workspace_id=ident))
    assert (await _hold(shop, again["proposal_id"])).json()["status"] == "verified"
    assert sent(shop, "draft_order_complete") == 1


async def test_3_a_completion_that_left_and_was_never_answered_stays_locked(shop):
    ident = card(await open_theo(shop))["workspace_id"]
    first = _hold_card(await tap(shop, "order.stage", workspace_id=ident))
    shop.store.lose_answer = True
    done = (await _hold(shop, first["proposal_id"])).json()
    assert done["status"] == "unverified", done
    locked = _workspace(done["ui"], ident)
    assert locked["settled"] == "unconfirmed" and locked["actions"] == []
    again = await tap(shop, "order.stage", workspace_id=ident)
    assert again["ok"] is False and "has not said whether it made it" in again["detail"]


# ============================================================ 4. the order just made is this conversation's


async def test_4_the_order_the_hold_just_made_can_be_noted_without_finding_it(shop):
    ident = card(await open_theo(shop))["workspace_id"]
    staged = _hold_card(await tap(shop, "order.stage", workspace_id=ident))
    assert (await _hold(shop, staged["proposal_id"])).json()["status"] == "verified"

    def from_the_screen(_calls):
        # Claude, with the order it is told is on the screen: "where we are" names it.
        return {"order_id": "gid://shopify/Order/3001", "note": "Gift wrap it"}

    body = await say(shop, "add a note to it: gift wrap it", ("shopify_order_note_append", from_the_screen))
    call = next(c for c in shop.model.calls if c.name == "shopify_order_note_append")
    assert call.ok and call.proposal_id, call.error
    assert [i for i in body["ui"] if i["type"] == "confirmation"]
    assert re.search(r"CREATED as order CROOKS-3001 \(order_id gid://shopify/Order/3001\)", shop.model.prompts[-1])


# ============================================================ the third check: friction he would hit
#
# 5. A change that changes nothing withdrew the hold card — and each Prepare after it made another
#    draft in Admin. Re-tapping "Not paid", the same email again and "cap" typed into the search
#    made three drafts for no change. Only what the hold card would MAKE decides it now.
# 6. "Close that" left the half-built order live: the next sentence was still told it was being
#    built, and "add a cap" quietly went back onto the order he had put away.


def drafts(shop) -> int:
    return sent(shop, "draft_order_create")


async def test_5_a_tap_that_changes_nothing_the_hold_card_makes_leaves_it_and_its_draft(shop):
    ident = card(await open_theo(shop))["workspace_id"]
    first = _hold_card(await tap(shop, "order.stage", workspace_id=ident))
    for command, fields in (("order.choose", {"field": "payment", "option": "pending"}),       # "Not paid", again
                            ("order.field", {"field": "email", "value": "theo.marsh@example.com"}),  # the same email
                            ("order.field", {"field": "item", "value": "cap"}),                 # a search, not an item
                            ("order.field", {"field": "quantity", "value": "2"})):              # how many of the search
        tapped = await tap(shop, command, workspace_id=ident, **fields)
        assert tapped["ok"] and "withdrawn" not in tapped["changed"], (command, tapped["changed"])
        assert shop.runtime.actions.find(first["proposal_id"]).status.value == "PENDING", command
        assert _workspace(tapped["ui"], ident)["notes"][0] != "The order changed — prepare it again."
    again = _hold_card(await tap(shop, "order.stage", workspace_id=ident))
    assert again["proposal_id"] == first["proposal_id"] and drafts(shop) == 1, "the same hold card, the same draft"

    # A real change still withdraws it: paid, which the hold card would carry.
    paid = await tap(shop, "order.choose", workspace_id=ident, field="payment", option="paid")
    assert paid["changed"]["withdrawn"] == [first["proposal_id"]]
    second = _hold_card(await tap(shop, "order.stage", workspace_id=ident))
    assert second["proposal_id"] != first["proposal_id"]
    assert drafts(shop) == 1, "paid or not is the completion's, not the draft's: the draft is reused"
    # And an item actually added from the search is a change, where the search itself was not.
    added = await tap(shop, "order.additem", workspace_id=ident)
    assert [r["title"] for r in card(added)["rows"]] == ["Convict Hoodie", "Crooks Cap"]
    assert shop.runtime.actions.find(second["proposal_id"]).status.value == "REVOKED"
    assert card(added)["notes"][0] == "The order changed — prepare it again."
    assert (await _hold(shop, second["proposal_id"])).status_code != 200


async def test_5_a_credit_or_a_code_retyped_as_it_was_keeps_its_hold_card(shop):
    ident = await open_credit(shop)
    first = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))
    for fields in ({"field": "amount", "value": "20"}, {"field": "amount", "value": "£20.00"},
                   {"field": "currency", "value": "gbp"}, {"field": "reason", "value": "a loyal customer"}):
        tapped = await tap(shop, "credit.field", workspace_id=ident, **fields)
        assert "withdrawn" not in tapped["changed"], fields
    assert _hold_card(await tap(shop, "credit.stage", workspace_id=ident))["proposal_id"] == first["proposal_id"]
    moved = await tap(shop, "credit.field", workspace_id=ident, field="amount", value="30")
    assert moved["changed"]["withdrawn"] == [first["proposal_id"]]

    code = await open_code(shop)
    first = _hold_card(await tap(shop, "discount.stage", workspace_id=code))
    for command, fields in (("discount.field", {"field": "code", "value": "autumn20"}),
                            ("discount.field", {"field": "value", "value": "20"}),
                            ("discount.choose", {"field": "basis", "option": "percentage"})):
        tapped = await tap(shop, command, workspace_id=code, **fields)
        assert "withdrawn" not in tapped["changed"], (command, fields)
    assert shop.runtime.actions.find(first["proposal_id"]).status.value == "PENDING"
    moved = await tap(shop, "discount.choose", workspace_id=code, field="basis", option="amount")
    assert moved["changed"]["withdrawn"] == [first["proposal_id"]]


async def test_5_the_floor_still_refuses_a_hold_card_whose_card_would_make_something_else(shop):
    """The safety net is as it was: a change that did not pass through the withdrawal is still
    refused at the door, and a search typed is still not such a change."""
    ident = card(await open_theo(shop))["workspace_id"]
    first = _hold_card(await tap(shop, "order.stage", workspace_id=ident))
    workspace = shop.runtime.sessions.get("g1").branch().workspace
    workspace["values"]["item"] = "a search nobody finished"
    workspace["choices"]["payment"] = "paid"                 # moved, and nothing withdrew it
    refused = await _hold(shop, first["proposal_id"])
    assert refused.status_code == 409 and "The card changed since this was prepared" in refused.text
    assert sent(shop, "draft_order_complete") == 0


async def test_6_an_order_he_closed_is_not_what_add_a_cap_goes_onto(shop):
    ident = card(await open_theo(shop))["workspace_id"]
    closed = await say(shop, "close that", ("close_screen", {}))
    assert closed.get("screen") == "cleared", closed.get("screen")
    body = await say(shop, "add a cap", ("shopify_order_build", {"add": [{"item": "cap"}]}))
    assert f"({ident})" not in shop.model.prompts[-1] and "building a new order" not in shop.model.prompts[-1]
    refused = next(c for c in reversed(shop.model.calls) if c.name == "shopify_order_build")
    assert not refused.ok and "the order for Theo Marsh was put away" in refused.error
    assert "Ask which order he means, or open a new one" in refused.error
    assert not [i for i in body["ui"] if i["type"] == "workspace"]
    branch = shop.runtime.sessions.get("g1").branch()
    assert [line["title"] for line in branch.workspace["facts"]["lines"]] == ["Convict Hoodie"], "nothing went onto it"


async def test_6_brought_back_it_is_the_order_being_built_again_with_its_lines(shop):
    ident = card(await open_theo(shop))["workspace_id"]
    await say(shop, "and a print at twelve pounds", ("shopify_order_build", {"add": [{"title": "Print", "price": 12}]}))
    await say(shop, "close that", ("close_screen", {}))
    back = await say(shop, "pull that back up", ("show_again", {"kind": "building"}))
    assert [r["title"] for r in _workspace(back["ui"], ident)["rows"]] == ["Convict Hoodie", "Print"]
    added = await say(shop, "add a cap", ("shopify_order_build", {"add": [{"item": "cap"}]}))
    assert f"building a new order ({ident})" in shop.model.prompts[-1]
    assert [r["title"] for r in card(added)["rows"]] == ["Convict Hoodie", "Print", "Crooks Cap"]

    # And in one breath: brought back and changed in the same sentence.
    await say(shop, "close that", ("close_screen", {}))
    both = await say(shop, "bring that order back and take the print off",
                     ("show_again", {"kind": "building"}), ("shopify_order_build", {"lines": [{"line": 2, "quantity": 0}]}))
    assert [r["title"] for r in _workspace(both["ui"], ident)["rows"]] == ["Convict Hoodie", "Crooks Cap"]



# ============================================================ the fourth check: only his own close puts it away
#
# 7. Another card taking the order's place is not him closing it. "Have we got the black hoodie in
#    large?" in the middle of an order draws a stock card over it; "add it to the order" goes onto
#    the same order, and the order is back on the glass with it. Only "close that", his Back or
#    Home puts it away — recorded on the Mac as it happens, not guessed from the glass.


async def test_7_a_stock_question_in_the_middle_leaves_the_order_being_built(shop):
    ident = card(await open_theo(shop))["workspace_id"]
    stock = await say(shop, "have we got the black hoodie in large?",
                      ("shopify_inventory", {"product": "black hoodie", "size": "L"}))
    assert [i["type"] for i in stock["ui"] if i["type"] != "context_stack"][0] == "inventory", "the stock card is up"
    added = await say(shop, "add it to the order", ("shopify_order_build", {"add": [{"variant_id": vid(9113)}]}))
    assert f"building a new order ({ident}) for Theo Marsh, 1 line, not created — not on his screen at the moment" \
        in shop.model.prompts[-1]
    built = next(c for c in reversed(shop.model.calls) if c.name == "shopify_order_build")
    assert built.ok, built.error
    back = card(added)
    assert back["workspace_id"] == ident, "the same order, not a new one"
    assert [r["detail"].split(" · ")[0] for r in back["rows"]] == ["Black / M", "Black / L"]
    branch = shop.runtime.sessions.get("g1").branch()
    assert any(i["type"] == "workspace" and i["data"]["workspace_id"] == ident for i in branch.last_ui), \
        "the order is on the glass after"
    await say(shop, "and a cap", ("shopify_order_build", {"add": [{"item": "cap"}]}))
    assert f"building a new order ({ident}) for Theo Marsh, 2 lines, not created — change it with" in shop.model.prompts[-1]


async def test_7_back_off_the_order_on_the_tablet_puts_it_away(shop):
    found = await say(shop, "who had the black hoodie sent to SL6 2AB",
                      ("shopify_find_order", {"item": "black hoodie", "address": "SL6 2AB"}))
    assert [i["data"]["order_number"] for i in found["ui"] if i["type"] == "order"] == ["#2101"]
    await say(shop, "and the jeans that went to SL1 1AA", ("shopify_find_order", {"item": "jeans", "address": "SL1 1AA"}))
    ident = card(await open_theo(shop))["workspace_id"]
    went = await tap(shop, "navigation.back")
    assert went["ok"] and str(went["answer"]).startswith("Back"), went.get("answer")
    assert not [i for i in went["ui"] if i["type"] == "workspace"], "Back took the order off the glass"
    await say(shop, "add a cap", ("shopify_order_build", {"add": [{"item": "cap"}]}))
    assert f"({ident})" not in shop.model.prompts[-1]
    refused = next(c for c in reversed(shop.model.calls) if c.name == "shopify_order_build")
    assert not refused.ok and "the order for Theo Marsh was put away" in refused.error
    back = await say(shop, "pull that back up", ("show_again", {"kind": "building"}))
    assert _workspace(back["ui"], ident)["rows"][0]["title"] == "Convict Hoodie"
    added = await say(shop, "add a cap", ("shopify_order_build", {"add": [{"item": "cap"}]}))
    assert [r["title"] for r in card(added)["rows"]] == ["Convict Hoodie", "Crooks Cap"]
