"""Round 13: a new order whose customer is changed carries nothing of the customer before.

The round-12 deploy review, S2Ba/F-01 and S2Ba/F-02. The confirmation email on a new order was
filled in from the first customer chosen, and only while it was empty; the delivery address of
an order it was made from, and the name on an address he said, belonged to whoever the order
was for at the time. Change the customer — by voice, by id or by name, or by retyping the name
on the card — and the draft Shopify was sent was the new customer's order with the old
customer's email on it (Shopify's confirmation and shipping mails for Bob's order going to
Alice), or Bob's goods going to Alice's door. The draft check called that consistent, because
it compared the draft with the card and the card was wrong.

What holds now, and what these tests hold, through the real `POST /turn` (a scripted model
making the calls Claude would) and the real `POST /command` (the owner's taps):

* a draft's confirmation email is the chosen customer's own, or one typed after that customer
  was chosen. A change of customer replaces an email read off the last one with the new one's
  own; an email he TYPED is taken off, and the card waits for him to type the new one;
* an address taken off an order is used only for that order's customer, and the name on an
  address he said is the name of whoever the order is for now;
* Prepare refuses a card whose email or order address does not belong to the chosen customer,
  whatever put it there.

The shop, the customers and every address are the invented ones of tests/test_r12_orders.py.
"""

from __future__ import annotations

from typing import Any

from app.families import _workspace as ws
from app.families import order_create as oc
from tests import test_r12_orders as r12
from tests.test_r12_orders import (
    AVA,
    MIA_TWIN,
    PEOPLE,
    THE_SENTENCE,
    card,
    open_theo,
    order_node,
    say,
    tap,
    the_sentence,
)

# The shop the round-12 order tests run in, bound under this name so pytest finds it here.
shop = r12.shop

AVA_EMAIL = PEOPLE[AVA]["email"]
THEOS_PARCEL = {"firstName": "Theo", "lastName": "Marsh", "address1": "3 Mill Lane", "city": "Bray",
                "zip": "SL6 2AB", "countryCode": "GB"}


def field(data: dict, name: str) -> dict:
    return next(f for f in data["fields"] if f["name"] == name)


def facts(data: dict) -> dict[str, str]:
    return {f["label"]: f["value"] for f in data["facts"]}


def chosen(data: dict, name: str) -> list[str]:
    return [o["id"] for c in data["choices"] if c["name"] == name for o in c["options"] if o["selected"]]


def drafted(shop) -> dict[str, Any] | None:
    """What the last draft Shopify was asked to make carried, or None when nothing was sent."""
    made = [v["input"] for name, v in shop.store.mutations if name == "draft_order_create"]
    return made[-1] if made else None


def hold_card(body: dict) -> dict:
    (found,) = [i["data"] for i in body["ui"] if i["type"] == "confirmation"]
    return found


def workspace(shop, ident: str) -> dict:
    return ws.held(shop.runtime.sessions.get("g1").branch(), oc.KIND, ident)


async def to_ava_by_voice(shop) -> dict:
    """"No — it's for Ava Stone": Claude finds her, then changes who the order is for by id."""
    return await say(shop, "no, it's for Ava Stone",
                     ("shopify_find_customer", {"query": "Ava Stone"}),
                     ("shopify_order_build", {"customer_id": AVA}))


# ============================================================ F-01: the confirmation email


async def test_f01_a_customer_changed_by_voice_takes_the_new_customers_own_email(shop):
    """The finding's own case. Opened for Theo, his address filled in; changed to Ava by id.
    Before the repair the draft was Ava's order with Theo's address on it."""
    ident = card(await open_theo(shop))["workspace_id"]
    data = card(await to_ava_by_voice(shop))
    assert data["title"] == "Ava Stone"
    assert field(data, "email")["value"] == AVA_EMAIL, field(data, "email")
    staged = await tap(shop, "order.stage", workspace_id=ident)
    assert drafted(shop)["customerId"] == AVA and drafted(shop)["email"] == AVA_EMAIL, drafted(shop)
    assert facts(hold_card(staged))["Customer"] == f"Ava Stone · {AVA_EMAIL}"


async def test_f01_a_customer_changed_by_name_by_voice_takes_the_new_customers_own_email(shop):
    ident = card(await open_theo(shop))["workspace_id"]
    data = card(await say(shop, "it's for Ava Stone", ("shopify_order_build", {"customer": "Ava Stone"})))
    assert data["title"] == "Ava Stone" and field(data, "email")["value"] == AVA_EMAIL
    await tap(shop, "order.stage", workspace_id=ident)
    assert drafted(shop)["email"] == AVA_EMAIL, drafted(shop)


async def test_f01_a_customer_retyped_on_the_card_takes_the_new_customers_own_email(shop):
    """The touch path, live at production: the name retyped on the card, the customer looked up
    by the card's own read, and Prepare tapped."""
    ident = card(await open_theo(shop))["workspace_id"]
    data = card(await tap(shop, "order.field", workspace_id=ident, field="customer", value="Ava Stone"))
    assert data["title"] == "Ava Stone"
    assert field(data, "email")["value"] == AVA_EMAIL, field(data, "email")
    await tap(shop, "order.stage", workspace_id=ident)
    assert drafted(shop)["customerId"] == AVA and drafted(shop)["email"] == AVA_EMAIL, drafted(shop)


async def test_f01_between_the_retype_and_the_lookup_the_old_address_is_not_on_the_card(shop):
    """The retype and the read that says who it is are two steps. In between, the card says the
    order is for nobody yet, and the address read off Theo is not left standing on it."""
    ident = card(await open_theo(shop))["workspace_id"]
    held = workspace(shop, ident)
    from app import commands
    from app.commands import Ctx

    session = shop.runtime.sessions.get("g1")
    out = commands.run("order.field", Ctx(shop.runtime, session, session.branch(),
                                          {"workspace_id": ident, "field": "customer", "value": "Ava Stone"}))
    assert out.ok and out.changed.get("recipe") == "order_customer"
    assert oc._chosen_customer(held) is None
    assert ws.value(held, "email") == "", "Theo's own address is Theo's, not whoever this turns out to be"


async def test_f01_two_of_one_name_and_the_one_he_picks_gets_her_own_email(shop):
    ident = card(await open_theo(shop))["workspace_id"]
    data = card(await say(shop, "no, it's for Mia Jones", ("shopify_order_build", {"customer": "Mia Jones"})))
    assert "2 customers match" in data["blocked"]
    assert field(data, "email")["value"] == "", "Theo's address is not left on an order for a Mia Jones"
    picked = card(await tap(shop, "order.customer", workspace_id=ident, customer_id=MIA_TWIN))
    assert field(picked, "email")["value"] == PEOPLE[MIA_TWIN]["email"]
    await tap(shop, "order.stage", workspace_id=ident)
    assert drafted(shop)["customerId"] == MIA_TWIN and drafted(shop)["email"] == PEOPLE[MIA_TWIN]["email"]


async def test_f01_an_address_he_typed_is_taken_off_when_the_customer_changes_and_is_typed_again(shop):
    """An address the owner typed is his choice for the customer he typed it for. For somebody
    else it is taken off, the card says why, and nothing can be prepared until he types one."""
    ident = card(await open_theo(shop))["workspace_id"]
    typed = card(await tap(shop, "order.field", workspace_id=ident, field="email", value="gifts@example.org"))
    assert field(typed, "email")["value"] == "gifts@example.org" and typed["blocked"] == ""

    data = card(await to_ava_by_voice(shop))
    email = field(data, "email")
    assert email["value"] == "" and email["status"] == "uncertain", email
    assert "Ava Stone" in email["hint"] and "Ava Stone" in data["blocked"], (email, data["blocked"])
    refused = await tap(shop, "order.stage", workspace_id=ident)
    assert refused["ok"] is False and refused["code"] == "not_ready" and "Ava Stone" in refused["detail"]
    assert drafted(shop) is None, "nothing reaches the shop"

    again = card(await tap(shop, "order.field", workspace_id=ident, field="email", value="ava.gift@example.org"))
    assert again["blocked"] == "" and field(again, "email")["status"] == "ok"
    await tap(shop, "order.stage", workspace_id=ident)
    assert drafted(shop)["email"] == "ava.gift@example.org"


async def test_f01_an_address_he_typed_is_taken_off_on_the_touch_path_too(shop):
    ident = card(await open_theo(shop))["workspace_id"]
    await tap(shop, "order.field", workspace_id=ident, field="email", value="gifts@example.org")
    data = card(await tap(shop, "order.field", workspace_id=ident, field="customer", value="Ava Stone"))
    assert data["title"] == "Ava Stone"
    assert field(data, "email")["value"] == "" and "Ava Stone" in data["blocked"]
    refused = await tap(shop, "order.stage", workspace_id=ident)
    assert refused["ok"] is False and drafted(shop) is None


async def test_f01_an_address_he_typed_that_is_the_new_customers_own_stays(shop):
    """Typed while the order was Theo's, and it is Ava's own address: it belongs to her."""
    ident = card(await open_theo(shop))["workspace_id"]
    await tap(shop, "order.field", workspace_id=ident, field="email", value=AVA_EMAIL)
    data = card(await to_ava_by_voice(shop))
    assert field(data, "email")["value"] == AVA_EMAIL and data["blocked"] == ""


async def test_f01_the_same_customer_chosen_again_keeps_the_address_he_typed(shop):
    ident = card(await open_theo(shop))["workspace_id"]
    await tap(shop, "order.field", workspace_id=ident, field="email", value="gifts@example.org")
    data = card(await tap(shop, "order.field", workspace_id=ident, field="customer", value="Theo Marsh"))
    assert data["title"] == "Theo Marsh"
    assert field(data, "email")["value"] == "gifts@example.org" and data["blocked"] == ""
    await tap(shop, "order.stage", workspace_id=ident)
    assert drafted(shop)["email"] == "gifts@example.org"


async def test_f01_prepare_refuses_an_email_that_is_not_the_chosen_customers(shop):
    """The floor under all of the above: whatever put it there, a card whose confirmation
    address was neither read off nor typed for the customer it is for is not prepared."""
    ident = card(await open_theo(shop))["workspace_id"]
    held = workspace(shop, ident)
    held["facts"]["customer"] = {**held["facts"]["customer"], "customer_id": AVA, "name": "Ava Stone"}
    for staged in (await tap(shop, "order.stage", workspace_id=ident),
                   await say(shop, "prepare it", ("shopify_order_create", {"workspace_id": ident}))):
        assert not [i for i in staged["ui"] if i["type"] == "confirmation"], staged
    assert drafted(shop) is None


# ============================================================ F-02: where it goes


async def test_f02_an_order_address_is_dropped_when_the_customer_changes_by_voice(shop):
    """Made from Theo's order, so it goes to Theo's door; then it is Ava's. Before the repair the
    draft carried Ava's goods to 3 Mill Lane."""
    data = card(await say(shop, THE_SENTENCE, *the_sentence("black hoodie", "SL6 2AB")))
    ident = data["workspace_id"]
    assert facts(data)["Address"].startswith("as on CROOKS-2101")
    data = card(await to_ava_by_voice(shop))
    assert chosen(data, "address") == ["customer"], data["choices"]
    assert not facts(data)["Address"].startswith("as on"), facts(data)
    assert "Made from" not in facts(data)
    await tap(shop, "order.stage", workspace_id=ident)
    sent = drafted(shop)
    assert sent["customerId"] == AVA and "shippingAddress" not in sent and sent["useCustomerDefaultAddress"] is True, sent


async def test_f02_an_order_address_is_dropped_when_the_name_is_retyped_on_the_card(shop):
    ident = card(await say(shop, THE_SENTENCE, *the_sentence("black hoodie", "SL6 2AB")))["workspace_id"]
    data = card(await tap(shop, "order.field", workspace_id=ident, field="customer", value="Ava Stone"))
    assert data["title"] == "Ava Stone" and chosen(data, "address") == ["customer"]
    offered = [o["id"] for c in data["choices"] if c["name"] == "address" for o in c["options"]]
    assert "order" not in offered, "Theo's door is not offered on Ava's order"
    await tap(shop, "order.stage", workspace_id=ident)
    sent = drafted(shop)
    assert "shippingAddress" not in sent and sent["useCustomerDefaultAddress"] is True, sent


async def test_f02_the_same_customer_again_keeps_the_address_of_their_order(shop):
    ident = card(await say(shop, THE_SENTENCE, *the_sentence("black hoodie", "SL6 2AB")))["workspace_id"]
    data = card(await tap(shop, "order.field", workspace_id=ident, field="customer", value="Theo Marsh"))
    assert facts(data)["Address"].startswith("as on CROOKS-2101")
    await tap(shop, "order.stage", workspace_id=ident)
    assert drafted(shop)["shippingAddress"] == THEOS_PARCEL


async def test_f02_an_address_he_said_carries_the_name_of_whoever_it_is_for_now(shop):
    ident = card(await open_theo(shop))["workspace_id"]
    await say(shop, "send it to 9 Oak Way, Cookham, SL6 9QT",
              ("shopify_order_build", {"address": {"address1": "9 Oak Way", "city": "Cookham", "zip": "SL6 9QT",
                                                   "country_code": "GB"}}))
    data = card(await to_ava_by_voice(shop))
    assert facts(data)["Address"] == "9 Oak Way, Cookham, SL6 9QT", "his words stand: it is where he said"
    await tap(shop, "order.stage", workspace_id=ident)
    sent = drafted(shop)["shippingAddress"]
    assert (sent["firstName"], sent["lastName"], sent["address1"]) == ("Ava", "Stone", "9 Oak Way"), sent


async def test_f02_prepare_refuses_an_order_whose_customer_is_not_the_one_chosen(shop):
    """Read again at Prepare, the order the address came from is no longer the chosen
    customer's (merged, reassigned in Admin): its address is not theirs to send to."""
    ident = card(await say(shop, THE_SENTENCE, *the_sentence("black hoodie", "SL6 2AB")))["workspace_id"]
    real = shop.store.graphql

    async def reassigned(query, variables=None):
        if "CrooksOrderForNewOrder" in query:
            node = order_node(2101)
            node["customer"] = {"id": AVA, "displayName": "Ava Stone"}
            return {"data": {"order": node}}
        return await real(query, variables)

    shop.store.graphql = reassigned
    staged = await tap(shop, "order.stage", workspace_id=ident)
    assert staged["ok"] is False and "CROOKS-2101" in staged["detail"], staged
    assert drafted(shop) is None


async def test_f02_prepare_refuses_an_order_address_that_is_another_customers(shop):
    """The floor: a card that says "as on the order" for somebody the order is not for."""
    ident = card(await say(shop, THE_SENTENCE, *the_sentence("black hoodie", "SL6 2AB")))["workspace_id"]
    held = workspace(shop, ident)
    held["facts"]["source"] = {**held["facts"]["source"], "customer_id": AVA}
    staged = await tap(shop, "order.stage", workspace_id=ident)
    assert staged["ok"] is False and staged["code"] == "not_ready", staged
    assert drafted(shop) is None
