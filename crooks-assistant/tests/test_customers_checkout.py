"""A checkout link for a customer: Shopify's draft and price, the exact email, his hold, the proof.

George, 2 October 2026: "Clive still cannot send a checkout link for a customer."

"Send Mia a checkout link for the black tee, size M" is one call (app/families/checkout_link.py):
the customer read by id, the item found as exactly one variant for sale, a draft order made by the
reviewed `draftOrderCreate` and read back with the link Shopify holds for it, and a card that IS
the email — to, items, Shopify's price, the link, the words. Nothing is sent until the hold; the
hold sends it from the shop's Gmail; the proof is the sent message read back by its own id.
"""

from __future__ import annotations

import pytest

from app.tools.gate import Disposition, Tier, classify
from tests.customers_world import ALICIA, INVOICE_HOST, MIA, cards, hold, say, vid, world_fixture

world = pytest.fixture(world_fixture)

TEE = {"customer_id": MIA, "items": [{"item": "black tee", "size": "M"}],
       "message": "Hi Mia, here's the link for the black tee in a medium you asked about."}


async def _prepare(world, args: dict | None = None) -> dict:
    return await say(world, "send Mia a checkout link for the black tee, size M",
                     ("shopify_find_customer", {"query": "Mia Jones"}), ("shopify_checkout_link_send", dict(args or TEE)))


def _sends(world) -> list:
    return [c for c in world.gmail.calls if c[0] in ("send", "send_draft")]


async def test_the_card_is_the_email_with_shopifys_price_and_link_and_nothing_is_sent(world):
    body = await _prepare(world)
    (card,) = cards(body, "confirmation")
    draft = next(iter(world.store.drafts.values()))
    facts = {f["label"]: f["value"] for f in card["facts"]}
    assert card["title"] == "Send a checkout link"
    assert facts["To"] == "Mia Jones <mia.jones@example.com>"
    assert facts["Items"] == "Convict T-Shirt Black / M · £30.00"
    assert facts["Total"] == "£30.00"
    assert facts["Link"] == draft["invoiceUrl"] and facts["Link"].startswith(f"https://{INVOICE_HOST}/")
    assert facts["Draft"].startswith(f"{draft['name']} in Shopify — a draft, not an order")
    assert card["body"] == (f"{TEE['message']}\n\nConvict T-Shirt — Black / M: £30.00\n\nTotal: £30.00\n\n"
                            f"Pay here: {draft['invoiceUrl']}\n\nCROOKS")
    # His hold, not a tap: a message to a customer cannot be unsent.
    assert card["interaction"]["kind"] == "hold_to_arm" and card["risk"] == "red"
    # The draft went to Shopify in the reviewed shape — a variant and a quantity, never a price.
    [(name, sent)] = world.store.mutations
    assert name == "draft_order_create"
    assert sent["input"]["lineItems"] == [{"variantId": vid(7202), "quantity": 1}]
    assert sent["input"]["customerId"] == MIA and "CROOKS assistant" in sent["input"]["tags"]
    # And nothing has gone anywhere.
    assert _sends(world) == []


async def test_the_hold_sends_it_and_it_is_proven_by_reading_it_back(world):
    body = await _prepare(world)
    (card,) = cards(body, "confirmation")
    done = await hold(world, card["proposal_id"])
    assert done["status"] == "verified", done
    assert done["spoken"] == "Checkout link sent to Mia."
    assert len(_sends(world)) == 1
    # The proof: Gmail asked for the message by its own Message-ID, in Sent.
    assert any(c[0] == "find" and "in:sent" in c[1] for c in world.gmail.calls)
    sent = next(m for ms in world.gmail.threads.values() for m in ms if "SENT" in m["labels"])
    assert sent["headers"]["to"] == "Mia Jones <mia.jones@example.com>"
    assert next(iter(world.store.drafts.values()))["invoiceUrl"] in sent["body"]
    # Recorded as CLIVE's change on her record, with ids and outcomes only.
    events = [e for e in world.runtime.actions.ledger.read() if e.get("operation") == "checkout_link_send"]
    assert [e["event"] for e in events][-1] == "VERIFIED" and events[-1]["entity_ref"] == MIA
    assert "mia.jones" not in str(events)


async def test_the_price_is_never_the_models(world):
    """There is no price argument at all: the card prints Shopify's arithmetic on its own draft."""
    from app.tools import registry

    schema = registry.get("shopify_checkout_link_send").input_schema
    assert "price" not in str(schema) and "amount" not in str(schema)


async def test_two_items_that_could_be_meant_are_a_question_and_nothing_is_made(world):
    await _prepare(world, {**TEE, "items": [{"item": "black tee"}]})
    told = next(c for c in world.model.calls if c.name == "shopify_checkout_link_send")
    assert not told.ok and "2 match 'black tee': Convict T-Shirt Black / S; Convict T-Shirt Black / M" in told.error
    assert world.store.mutations == [] and _sends(world) == []


async def test_a_link_off_the_shops_own_domain_is_not_sent(world):
    world.store.twist = {"invoiceUrl": "https://evil.example/pay"}
    await _prepare(world)
    told = next(c for c in world.model.calls if c.name == "shopify_checkout_link_send")
    assert not told.ok and "not on the shop's own domain" in told.error
    assert _sends(world) == []


async def test_a_draft_changed_after_the_card_is_never_sent(world):
    body = await _prepare(world)
    (card,) = cards(body, "confirmation")
    draft = next(iter(world.store.drafts.values()))
    draft["totalPriceSet"] = {"shopMoney": {"amount": "1.00", "currencyCode": "GBP"}}
    done = await hold(world, card["proposal_id"])
    assert done["status"] == "stale", done
    assert _sends(world) == []


async def test_preparing_the_same_link_again_uses_the_same_draft(world):
    await _prepare(world)
    await _prepare(world)
    assert [m[0] for m in world.store.mutations] == ["draft_order_create"] and len(world.store.drafts) == 1


async def test_a_variant_this_conversation_never_looked_up_is_refused(world):
    await _prepare(world, {**TEE, "items": [{"variant_id": vid(7202)}]})
    told = next(c for c in world.model.calls if c.name == "shopify_checkout_link_send")
    assert not told.ok and "not one this conversation has looked up" in told.error
    assert world.store.mutations == []


async def test_a_variant_from_a_search_this_conversation_made_is_taken(world):
    await say(world, "black tee in medium?", ("shopify_variant_search", {"product": "black tee", "size": "M"}))
    body = await _prepare(world, {**TEE, "items": [{"variant_id": vid(7202), "quantity": 2}]})
    facts = {f["label"]: f["value"] for f in cards(body, "confirmation")[0]["facts"]}
    assert facts["Items"] == "Convict T-Shirt Black / M ×2 · £60.00" and facts["Total"] == "£60.00"


async def test_a_link_in_his_words_is_refused_the_shops_link_is_the_only_one(world):
    await _prepare(world, {**TEE, "message": "Pay at https://crooksldn.com/somewhere"})
    told = next(c for c in world.model.calls if c.name == "shopify_checkout_link_send")
    assert not told.ok and "Leave the link out" in told.error and world.store.mutations == []


def test_the_gate_stages_it_for_the_owner_and_never_runs_it():
    issued = {MIA}
    decision = classify("shopify_checkout_link_send", dict(TEE), issued_ids=issued)
    assert decision.disposition is Disposition.STAGE_FOR_OWNER and decision.tier is Tier.RED
    assert classify("shopify_checkout_link_send", dict(TEE)).disposition is Disposition.DENY, "a customer nobody looked up"


def test_the_team_is_not_offered_it():
    from app.people import staff

    assert "shopify_checkout_link_send" not in staff.TOOLS


@pytest.mark.usefixtures("owner_asking")
async def test_called_straight_through_the_dispatcher_it_is_held_and_nothing_is_sent(world):
    """The same call without a turn around it: the gate stages it on the session, and that is all."""
    from app.session.models import Session
    from app.tools.dispatch import dispatch

    session = Session(session_id="direct")
    session.issue(MIA)
    calls: list = []
    text = await dispatch("shopify_checkout_link_send", dict(TEE), session=session, timeout_s=5, calls=calls)
    assert text.startswith("PROPOSED") and "It has NOT happened" in text, text
    (proposal,) = [p for p in session.proposals if p.operation == "checkout_link_send"]
    assert proposal.summary["total"] == "£30.00" and proposal.execution["to"] == "mia.jones@example.com"
    assert _sends(world) == []


async def test_the_prepare_step_on_its_own_builds_the_email_and_sends_nothing(world):
    from app.families.checkout_link import shopify_checkout_link_send

    prepared = await shopify_checkout_link_send(MIA, [{"item": "black tee", "size": "M"}], TEE["message"])
    assert prepared.expected_after == {"sent": 1} and prepared.before["sent"] == 0
    assert prepared.execution["draft_id"] == "", "a fresh message, never a Gmail draft sent in its place"
    assert prepared.execution["checkout_draft_id"] in world.store.drafts
    assert _sends(world) == []


async def test_words_naming_another_customers_order_are_refused_before_any_draft_is_made(world):
    """The check every new email gets (app/tools/gmail_writes.py): an email to Alicia that names
    #2205 — Mia's order, on the screen a moment ago — is refused, and no draft is left behind."""
    await say(world, "show me order 2205", ("shopify_find_order", {"query": "2205"}))
    await say(world, "send Alicia a checkout link for the black tee, size M",
              ("shopify_find_customer", {"query": "Alicia Grant"}),
              ("shopify_checkout_link_send", {"customer_id": ALICIA, "items": [{"item": "black tee", "size": "M"}],
                                              "message": "Hi Alicia, following up on order 2205, here is the tee."}))
    told = next(c for c in world.model.calls if c.name == "shopify_checkout_link_send")
    assert not told.ok and "names order 2205" in told.error and "not the customer on that order" in told.error
    assert world.store.mutations == [] and world.store.drafts == {} and _sends(world) == []


@pytest.mark.usefixtures("owner_asking")
async def test_a_draft_made_before_a_later_check_failed_is_named_not_nothing_changed(world):
    """The draft is made, then Shopify's link fails the check: the draft is in Admin, and the
    model is told so — never "Nothing was changed"."""
    from app.session.models import Session
    from app.tools.dispatch import dispatch

    world.store.twist = {"invoiceUrl": "https://evil.example/pay"}
    session = Session(session_id="direct")
    session.issue(MIA)
    text = await dispatch("shopify_checkout_link_send", dict(TEE), session=session, timeout_s=5, calls=[])
    (draft,) = world.store.drafts.values()
    assert "Nothing was changed" not in text, text
    assert f"Draft {draft['name']} is left in Admin" in text and "not on the shop's own domain" in text
    assert _sends(world) == []


async def test_a_new_size_says_the_draft_for_the_old_one_is_left_in_admin(world):
    await _prepare(world)
    first = next(iter(world.store.drafts.values()))
    body = await _prepare(world, {**TEE, "items": [{"item": "black tee", "size": "S"}]})
    facts = {f["label"]: f["value"] for f in cards(body, "confirmation")[-1]["facts"]}
    assert len(world.store.drafts) == 2
    assert facts["Earlier"] == f"{first['name']}, made for the earlier items, is left in Admin"
