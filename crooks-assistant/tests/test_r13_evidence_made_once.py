"""Round 13's evidence for round 12's made-once findings: a card makes ONE thing, whatever the
owner's hands, the network or Shopify do in between.

Round 12's review could not settle these from the files it was handed, and asked for tests that
drive the commit route itself (docs/review/deploy-review-round-12-findings.md):

* S2a-03: two hold cards from one order card committed at once, a commit retried while the
  first is still sending, and a commit without its hold. Exactly one order, whichever way round.
* S2b-02: a credit whose answer never came back, and a second hold card from the same card.
  One credit.
* T1-01: an order prepared, then changed by voice and by a tap, and the old hold card held.
  No completion.
* T3-01: a credit and a code whose card moved without passing through the withdrawal, and the
  old hold card held. Nothing sent.
* T3-02: a completion that fails at `draft_order_complete` itself, the reads beside it working.
  Only a completion that certainly never left gives the card back; one that left is never made
  twice.

Two things did not hold at 361b0138; each was reproduced here as found, and is fixed in
app/families/_workspace.py (round 13):

* the made-once mark was released by the commit of any hold card of the card, not only by the
  commit that set it, so a withdrawn card committed while another hold was still at its
  precondition read freed the card for a second Prepare and a second credit (S2a-03). The
  reservation now names its proposal, and only that proposal's commit settles or releases it;
* a send that left and whose answer was lost, read back unchanged at once, was ruled "not made"
  and the card given back — "Nothing was credited; prepare it again" — although Shopify may still
  apply it: a second credit, and with the card changed a second order (S2b-02, T3-02). It is now
  sent, not confirmed, and the card makes nothing more; only a send proven not to have left, or
  refused by Shopify, gives the card back.

Everything reaches the Mac as the tablet does: /turn with Claude scripted, /command for taps,
/actions for the hold. The fake shop is round 12's (tests/test_r12_made_once.py Shop), which
records every mutation it is sent; where the network must stall or fail, its `mutate` is wrapped
on the instance, so what the fake records is still what the application sent. Every name here is
invented.
"""

from __future__ import annotations

import asyncio
import copy

import httpx
import pytest

from app.clients.shopify import ShopifyError, ShopifyUnreached
from tests.test_r12_made_once import (  # noqa: F401 (the fixture)
    _hold,
    _hold_card,
    _workspace,
    open_code,
    open_credit,
    sent,
    shop,
)
from tests.test_r12_orders import PROXIED, card, open_theo, say, tap

# What the application's Shopify client raises for a request that left and whose answer never came
# back: httpx's ReadTimeout is an HTTPError that is not a connect error, and `ShopifyClient._post`
# turns it into a plain ShopifyError — neither `unsent` nor `refused` (app/clients/shopify.py).
TIMED_OUT = "Could not reach Shopify: " + str(httpx.ReadTimeout("The read operation timed out"))

async def _arm(client, proposal_id: str) -> str:
    """The owner's hold begins: the token the commit must carry, and the hold's dwell spent."""
    armed = await client.post(f"/actions/{proposal_id}/arm", data={"session_id": "g1"}, headers=PROXIED)
    assert armed.status_code == 200, armed.text
    client.runtime.actions.find(proposal_id).armed_at -= 1.0
    return armed.json()["nonce"]


def _commit(client, proposal_id: str, nonce: str = ""):
    headers = {**PROXIED, "X-Crooks-Arm": nonce} if nonce else PROXIED
    return client.post(f"/actions/{proposal_id}/commit", data={"session_id": "g1"}, headers=headers)


async def _second_hold_card(client, command: str, ident: str, first: str) -> str:
    """A second hold card from the same card, both waiting at once.

    The engine keeps one proposal per request in one position (app/actions/engine.py `stage`), so
    Prepare tapped again hands the first card back. Its fingerprint is set aside here so that
    Prepare makes a second one exactly as it made the first — its own prepare, its own fresh read —
    and the commit route's made-once check (app/families/_workspace.py `commit_refused`) is then
    the only thing between two holds and two changes."""
    client.runtime.actions.find(first).fingerprint += ":set-aside-by-the-test"
    staged = await tap(client, command, workspace_id=ident)
    second = staged["changed"]["proposal_id"]
    assert second != first
    assert {i["data"]["proposal_id"] for i in staged["ui"] if i["type"] == "confirmation"} == {first, second}
    assert client.runtime.actions.find(first).status.value == "PENDING"
    assert client.runtime.actions.find(second).status.value == "PENDING"
    return second


def _held_at(store, name: str) -> tuple[asyncio.Event, asyncio.Event, list[str]]:
    """Shopify, slow to take `name`: the mutation waits at the door until released. Returns (it has
    arrived, let it through, every mutation the application asked for, in order)."""
    arrived, release, asked = asyncio.Event(), asyncio.Event(), []
    real = store.mutate

    async def mutate(mutation: str, variables: dict) -> dict:
        asked.append(mutation)
        if mutation == name:
            arrived.set()
            await release.wait()
        return await real(mutation, variables)

    store.mutate = mutate
    return arrived, release, asked


# ============================================================ S2a-03: made once, however it is held


async def test_s2a_03_two_hold_cards_from_one_order_committed_at_once_make_one_order(shop):  # noqa: F811 - the fixture is tests/test_r12_made_once.py shop
    """Two hold cards from one order card, both held at once. Whichever reaches Shopify first is
    held there; the other is refused 409 `already_made` without waiting for it, and nothing more is
    sent. Released, the first makes the order; the card is finished and prepares nothing more."""
    ident = card(await open_theo(shop))["workspace_id"]
    first = _hold_card(await tap(shop, "order.stage", workspace_id=ident))["proposal_id"]
    second = await _second_hold_card(shop, "order.stage", ident, first)
    nonces = {first: await _arm(shop, first), second: await _arm(shop, second)}
    arrived, release, asked = _held_at(shop.store, "draft_order_complete")

    tasks = {pid: asyncio.create_task(_commit(shop, pid, nonces[pid])) for pid in (first, second)}
    await asyncio.wait_for(arrived.wait(), timeout=5)
    done, _ = await asyncio.wait(set(tasks.values()), timeout=5, return_when=asyncio.FIRST_COMPLETED)
    assert len(done) == 1, "one commit is held at Shopify; the other is answered without waiting for it"
    (refused,) = [pid for pid, task in tasks.items() if task in done]
    answer = tasks[refused].result()
    assert answer.status_code == 409 and answer.json()["code"] == "already_made", answer.text
    assert "already made what it was for" in answer.json()["detail"]
    assert shop.runtime.actions.find(refused).status.value == "REVOKED"

    release.set()
    (made,) = [pid for pid in tasks if pid != refused]
    finished = await asyncio.wait_for(tasks[made], timeout=10)
    assert finished.status_code == 200 and finished.json()["status"] == "verified", finished.text
    assert asked.count("draft_order_complete") == 1 and sent(shop, "draft_order_complete") == 1
    again = await tap(shop, "order.stage", workspace_id=ident)
    assert again["ok"] is False and "already created" in again["detail"]
    assert sent(shop, "draft_order_complete") == 1


async def test_s2a_03_a_commit_retried_while_the_first_is_sending_waits_for_it_and_sends_nothing(shop):  # noqa: F811 - the fixture is tests/test_r12_made_once.py shop
    """The same hold card committed twice — a retried request, an Android double-fire — while the
    first is still at Shopify. The retry is the engine's: it waits for the first's outcome and
    hands that back. The card is not withdrawn under the commit that is sending it."""
    ident = card(await open_theo(shop))["workspace_id"]
    first = _hold_card(await tap(shop, "order.stage", workspace_id=ident))["proposal_id"]
    nonce = await _arm(shop, first)
    arrived, release, asked = _held_at(shop.store, "draft_order_complete")

    sending = asyncio.create_task(_commit(shop, first, nonce))
    await asyncio.wait_for(arrived.wait(), timeout=5)
    retry = asyncio.create_task(_commit(shop, first, nonce))
    await asyncio.sleep(0.05)
    assert not retry.done(), "the retry waits for the first commit's outcome"
    assert shop.runtime.actions.find(first).status.value == "EXECUTING"
    release.set()
    one, two = await asyncio.wait_for(asyncio.gather(sending, retry), timeout=10)
    assert one.status_code == 200 and one.json()["code"] == "verified", one.text
    assert two.status_code == 200 and two.json()["code"] == "already_executed", two.text
    assert asked.count("draft_order_complete") == 1 and sent(shop, "draft_order_complete") == 1


async def test_s2a_03_a_prepare_tapped_while_the_hold_is_sending_is_refused(shop):  # noqa: F811 - the fixture is tests/test_r12_made_once.py shop
    """Prepare tapped again while the hold is at Shopify: the card is finished from the moment the
    commit claimed it (`before_commit`, then the family's own `sending`), so it prepares nothing
    and no second card or draft is made."""
    ident = card(await open_theo(shop))["workspace_id"]
    first = _hold_card(await tap(shop, "order.stage", workspace_id=ident))["proposal_id"]
    nonce = await _arm(shop, first)
    arrived, release, asked = _held_at(shop.store, "draft_order_complete")
    sending = asyncio.create_task(_commit(shop, first, nonce))
    await asyncio.wait_for(arrived.wait(), timeout=5)
    drafts = sent(shop, "draft_order_create")
    again = await tap(shop, "order.stage", workspace_id=ident)
    assert again["ok"] is False and "has not said whether it made it" in again["detail"], again
    assert sent(shop, "draft_order_create") == drafts
    release.set()
    assert (await asyncio.wait_for(sending, timeout=10)).json()["status"] == "verified"
    assert asked.count("draft_order_complete") == 1


async def test_s2a_03_a_withdrawn_hold_card_committed_meanwhile_leaves_the_sending_card_finished(shop):  # noqa: F811 - the fixture is tests/test_r12_made_once.py shop
    """The reservation belongs to the commit that made it. A £20 credit is being applied: its hold
    has claimed the card and Shopify is answering its balance read (£15), slowly. Meanwhile a hold
    card this same card withdrew earlier is committed — a page that had not caught up, a double
    fire — and is answered `revoked`. The card must still be finished while the first is sending
    (app/routes/actions.py: "while this one is being applied the card is finished, so a second
    Prepare meanwhile cannot make a second"): Prepare tapped now is refused, and Shopify is sent one
    credit whatever the owner does next."""
    ident = await open_credit(shop)
    withdrawn = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))["proposal_id"]
    assert (await tap(shop, "credit.field", workspace_id=ident, field="amount", value="25"))["changed"]["withdrawn"] == [withdrawn]
    await tap(shop, "credit.field", workspace_id=ident, field="amount", value="20")
    live = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))["proposal_id"]
    nonce = await _arm(shop, live)

    # Shopify reads the balance for the precondition at once, and its answer is slow to arrive.
    read, release, real = asyncio.Event(), asyncio.Event(), shop.store.graphql

    async def graphql(query: str, variables: dict | None = None) -> dict:
        answer = await real(query, variables)
        if "CrooksStoreCredit" in query and not read.is_set():
            read.set()
            await release.wait()
        return answer

    shop.store.graphql = graphql
    sending = asyncio.create_task(_commit(shop, live, nonce))
    await asyncio.wait_for(read.wait(), timeout=5)
    stray = await _commit(shop, withdrawn)
    assert stray.json().get("code") == "revoked", stray.text

    again = await tap(shop, "credit.stage", workspace_id=ident)
    if again["ok"]:
        # Prepared while the first is still sending: held, it is applied.
        extra = await _hold(shop, again["changed"]["proposal_id"])
        assert extra.status_code == 200, extra.text
    release.set()
    first = await asyncio.wait_for(sending, timeout=10)
    assert first.status_code == 200, first.text
    assert sent(shop, "store_credit_credit") == 1, (
        f"{sent(shop, 'store_credit_credit')} credits sent: Prepare {'was taken' if again['ok'] else 'was refused'} while the "
        f"first was being applied; balance now £{shop.store.balance:.2f}")
    assert again["ok"] is False, "Prepare was taken while the first credit was still being applied"


async def test_s2a_03_a_withdrawn_hold_card_committed_while_nothing_is_in_flight_frees_nothing_and_takes_nothing(shop):  # noqa: F811 - the fixture is tests/test_r12_made_once.py shop
    """The edge of the fix: the same stray commit with no hold in flight. It is answered `revoked`,
    sends nothing, and leaves the card exactly as it was — his, with its live hold card still
    waiting, which then gives the one £20. And on a card whose last send was proven never to have
    left, the stray commit of that failed card leaves the card given back with its reason."""
    from app.families import _workspace as ws

    ident = await open_credit(shop)
    withdrawn = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))["proposal_id"]
    await tap(shop, "credit.field", workspace_id=ident, field="amount", value="25")
    await tap(shop, "credit.field", workspace_id=ident, field="amount", value="20")
    live = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))["proposal_id"]
    stray = await _commit(shop, withdrawn)
    assert stray.json().get("code") == "revoked", stray.text
    workspace = shop.runtime.sessions.get("g1").branch().workspace
    assert ws.noted(workspace) is None, "nothing noted against the card"
    assert shop.runtime.actions.find(live).status.value == "PENDING"
    assert (await _hold(shop, live)).json()["status"] == "verified"
    assert sent(shop, "store_credit_credit") == 1 and shop.store.balance == 35.0

    ident = await open_credit(shop)            # a new card, whose send never leaves
    failed = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))["proposal_id"]
    real = shop.store.mutate

    async def unreached(name: str, variables: dict) -> dict:
        if name == "store_credit_credit":
            raise ShopifyUnreached("Could not reach Shopify: connection refused")
        return await real(name, variables)

    shop.store.mutate = unreached
    assert (await _hold(shop, failed)).json()["status"] == "failed"
    shop.store.mutate = real
    again = await _commit(shop, failed)
    assert again.status_code == 200 and again.json()["status"] == "failed", again.text     # the engine's settled answer
    back = _workspace(again.json()["ui"], ident)
    assert back["kicker"] == "Store credit · not given" and "Could not reach Shopify" in back["notes"][0], back
    assert (await tap(shop, "credit.stage", workspace_id=ident))["ok"], "the card is still his to prepare"
    assert sent(shop, "store_credit_credit") == 1


async def test_s2a_03_a_commit_without_its_hold_sends_nothing_and_leaves_the_card_his(shop):  # noqa: F811 - the fixture is tests/test_r12_made_once.py shop
    """A commit that carries no hold is refused (409 `not_armed`) and the mark `before_commit` put
    on the card is taken off again (`after_commit`): the card is not left finished, so the real
    hold that follows makes the one order."""
    ident = card(await open_theo(shop))["workspace_id"]
    first = _hold_card(await tap(shop, "order.stage", workspace_id=ident))["proposal_id"]
    stray = await _commit(shop, first)
    assert stray.status_code == 409 and stray.json()["code"] == "not_armed", stray.text
    assert sent(shop, "draft_order_complete") == 0
    assert shop.runtime.actions.find(first).status.value == "PENDING"
    held = await _hold(shop, first)
    assert held.status_code == 200 and held.json()["status"] == "verified", held.text
    assert sent(shop, "draft_order_complete") == 1


# ============================================================ S2b-02: a credit whose answer was lost


def _credit_answer_lost(store, *, landed: bool, reread_fails: bool) -> list[str]:
    """Shopify was sent the credit and its answer never came back (a read timeout). `landed`: it
    had made the credit by the time the Mac read the balance again. `reread_fails`: the balance
    cannot be read back either. Returns every mutation the application asked for."""
    asked: list[str] = []
    real_mutate, real_graphql = store.mutate, store.graphql
    lost = {"credit": False}

    async def mutate(name: str, variables: dict) -> dict:
        asked.append(name)
        if name == "store_credit_credit":
            store.mutations.append((name, copy.deepcopy(variables)))
            if landed:
                store.balance = round(store.balance + float(variables["creditInput"]["creditAmount"]["amount"]), 2)
            lost["credit"] = True
            raise ShopifyError(TIMED_OUT)
        return await real_mutate(name, variables)

    async def graphql(query: str, variables: dict | None = None) -> dict:
        if reread_fails and lost["credit"] and "CrooksStoreCredit" in query:
            raise ShopifyError(TIMED_OUT)
        return await real_graphql(query, variables)

    store.mutate, store.graphql = mutate, graphql
    return asked


@pytest.mark.parametrize(("landed", "reread_fails"), [(True, True), (False, True), (True, False)],
                         ids=["made-and-unreadable", "unmade-and-unreadable", "made-and-read-back"])
async def test_s2b_02_a_credit_whose_answer_was_lost_is_locked_against_a_second_hold_card(shop, landed, reread_fails):  # noqa: F811 - the fixture is tests/test_r12_made_once.py shop
    """The answer to a £20 credit never came back. Whether the balance cannot be read back
    (unconfirmed) or reads £35 (made), the card is finished: a second hold card prepared from the
    same card is refused 409 `already_made`, and Shopify is sent one credit."""
    ident = await open_credit(shop)
    first = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))["proposal_id"]
    second = await _second_hold_card(shop, "credit.stage", ident, first)
    later = await _arm(shop, second)
    asked = _credit_answer_lost(shop.store, landed=landed, reread_fails=reread_fails)

    lost = await _hold(shop, first)
    assert lost.status_code == 200 and lost.json()["status"] in ("unverified", "verified"), lost.text
    refused = await _commit(shop, second, later)
    assert refused.status_code == 409 and refused.json()["code"] == "already_made", refused.text
    assert asked.count("store_credit_credit") == 1 and sent(shop, "store_credit_credit") == 1
    assert shop.store.balance == (35.0 if landed else 15.0)


async def test_s2b_02_a_timed_out_credit_the_reread_finds_unmade_is_not_given_again(shop):  # noqa: F811 - the fixture is tests/test_r12_made_once.py shop
    """The case the one re-read cannot settle. The £20 credit left and its answer never came back
    (a read timeout, which is neither `unsent` nor `refused`); read again at once, the balance is
    still £15 — which Shopify may yet change, since a request that timed out on this side can still
    be applied on Shopify's. A second hold card from the same card must be refused (409
    `already_made`) with one credit sent: the card's own words are that money is never sent twice
    (app/families/store_credit.py `_execute`), and only a refusal or a send that never left gives a
    card back (app/families/_workspace.py `sending`)."""
    ident = await open_credit(shop)
    first = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))["proposal_id"]
    second = await _second_hold_card(shop, "credit.stage", ident, first)
    later = await _arm(shop, second)
    asked = _credit_answer_lost(shop.store, landed=False, reread_fails=False)

    lost = await _hold(shop, first)
    assert lost.status_code == 200, lost.text
    refused = await _commit(shop, second, later)
    assert refused.status_code == 409 and refused.json()["code"] == "already_made", (lost.json()["status"], refused.text)
    assert asked.count("store_credit_credit") == 1 and sent(shop, "store_credit_credit") == 1


async def test_s2b_02_a_timed_out_credit_is_drawn_as_sent_not_confirmed_and_prepares_nothing(shop):  # noqa: F811 - the fixture is tests/test_r12_made_once.py shop
    """The same timed-out £20, on the path the owner is actually on: the card that comes back. It
    may have been given, so it says so — sent, not confirmed — and Prepare on it is refused; one
    credit is sent whatever he taps."""
    ident = await open_credit(shop)
    first = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))["proposal_id"]
    asked = _credit_answer_lost(shop.store, landed=False, reread_fails=False)
    lost = (await _hold(shop, first)).json()
    back = _workspace(lost["ui"], ident)
    again = await tap(shop, "credit.stage", workspace_id=ident)
    if again["ok"]:
        # Handed back as "not given": prepared again, and held, it is applied.
        await _hold(shop, again["changed"]["proposal_id"])
    assert asked.count("store_credit_credit") == 1, (
        f"{asked.count('store_credit_credit')} credits sent; the card came back as {back['kicker']!r}: {back['notes'][0]!r}")
    assert back["settled"] == "unconfirmed" and again["ok"] is False


@pytest.mark.parametrize("how", ["never left", "refused", "failed before it was sent"])
async def test_s2b_02_a_credit_proven_not_given_is_given_back_and_the_next_hold_gives_one(shop, how):  # noqa: F811 - the fixture is tests/test_r12_made_once.py shop
    """The edge of the fix: where CLIVE has proof that nothing was given, the card is his again, as
    before. The connection was never made (`unsent`); Shopify answered and refused it (`refused`);
    or the balance read before sending failed, so nothing was sent. Each time the card comes back
    "not given" with the reason, Prepare works, and the next hold gives the one £20."""
    from app.clients.shopify import ShopifyRefused

    ident = await open_credit(shop)
    first = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))["proposal_id"]
    real_mutate, real_graphql = shop.store.mutate, shop.store.graphql
    once = {"left": False}

    async def mutate(name: str, variables: dict) -> dict:
        if name == "store_credit_credit" and not once["left"]:
            once["left"] = True
            if how == "never left":
                raise ShopifyUnreached("Could not reach Shopify: connection refused")
            if how == "refused":
                shop.store.mutations.append((name, copy.deepcopy(variables)))
                raise ShopifyRefused("The store credit account is disabled.")
        return await real_mutate(name, variables)

    async def graphql(query: str, variables: dict | None = None) -> dict:
        if how == "failed before it was sent" and "CrooksStoreCredit" in query and not once["left"]:
            once["left"] = True
            raise ShopifyError("Could not reach Shopify: the balance could not be read")
        return await real_graphql(query, variables)

    shop.store.mutate, shop.store.graphql = mutate, graphql
    done = (await _hold(shop, first)).json()
    assert done["status"] == "failed", done
    back = _workspace(done["ui"], ident)
    assert back["kicker"] == "Store credit · not given" and back["settled"] == "", back
    assert back["notes"][0].startswith("The credit was not given: "), back["notes"]
    again = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))["proposal_id"]
    assert (await _hold(shop, again)).json()["status"] == "verified"
    assert shop.store.balance == 35.0
    assert sent(shop, "store_credit_credit") == (2 if how == "refused" else 1)


# ============================================================ T1-01: an order changed after Prepare


async def test_t1_01_an_order_changed_by_voice_and_by_tap_after_prepare_never_completes_the_old_hold_card(shop):  # noqa: F811 - the fixture is tests/test_r12_made_once.py shop
    """Prepared, and the hold begun — the token in hand — then five pounds of postage said and a
    note typed. The old hold card is for the order as it was: committed with its token it is
    refused, and Shopify is sent no completion. Prepared again, the hold makes the order as the
    card now says it, once."""
    ident = card(await open_theo(shop))["workspace_id"]
    old = _hold_card(await tap(shop, "order.stage", workspace_id=ident))
    nonce = await _arm(shop, old["proposal_id"])

    spoken = await say(shop, "add five pounds postage", ("shopify_order_build", {"postage": 5}))
    assert old["proposal_id"] in spoken["revoked"]
    typed = await tap(shop, "order.field", workspace_id=ident, field="note", value="Leave it with the porter")
    assert typed["ok"], typed
    assert shop.runtime.actions.find(old["proposal_id"]).status.value == "REVOKED"

    stale = await _commit(shop, old["proposal_id"], nonce)
    assert stale.json().get("status") != "verified", stale.text
    assert stale.status_code == 409 or stale.json()["code"] in ("revoked", "stale"), stale.text
    assert sent(shop, "draft_order_complete") == 0

    new = _hold_card(await tap(shop, "order.stage", workspace_id=ident))
    assert new["proposal_id"] != old["proposal_id"]
    done = await _hold(shop, new["proposal_id"])
    assert done.json()["status"] == "verified", done.text
    completed = [v["id"] for n, v in shop.store.mutations if n == "draft_order_complete"]
    assert len(completed) == 1
    draft = shop.store.drafts[completed[0]]
    assert draft["totalShippingPriceSet"]["shopMoney"]["amount"] == "5.00", "the order as the card now says it"


async def test_t1_01_the_old_hold_card_is_refused_even_when_nothing_withdrew_it(shop):  # noqa: F811 - the fixture is tests/test_r12_made_once.py shop
    """The floor under the withdrawal, for voice and tap alike: the card moved (postage, then a
    note) without passing through `touched`, and the old hold card is committed with its token.
    Refused at the door (409, the card changed), and no completion is sent."""
    ident = card(await open_theo(shop))["workspace_id"]
    old = _hold_card(await tap(shop, "order.stage", workspace_id=ident))["proposal_id"]
    nonce = await _arm(shop, old)
    workspace = shop.runtime.sessions.get("g1").branch().workspace
    workspace["values"]["postage"] = "5"
    workspace["values"]["note"] = "Leave it with the porter"
    refused = await _commit(shop, old, nonce)
    assert refused.status_code == 409 and "The card changed since this was prepared" in refused.text, refused.text
    assert sent(shop, "draft_order_complete") == 0


# ============================================================ T3-01: a credit or a code, stale


async def test_t3_01_a_credit_whose_card_moved_without_a_withdrawal_is_never_given(shop):  # noqa: F811 - the fixture is tests/test_r12_made_once.py shop
    """The card's amount changed and then its customer, neither through `touched`: the old hold
    card is refused at the door (409), and no credit is sent. And a balance that moved in Admin
    after Prepare makes the hold card stale in the engine's own precondition."""
    ident = await open_credit(shop)
    old = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))["proposal_id"]
    workspace = shop.runtime.sessions.get("g1").branch().workspace
    workspace["values"]["amount"] = "30"
    refused = await _hold(shop, old)
    assert refused.status_code == 409 and "The card changed since this was prepared" in refused.text, refused.text
    assert sent(shop, "store_credit_credit") == 0

    workspace["values"]["amount"] = "20"
    again = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))["proposal_id"]
    workspace["facts"]["customer"] = {**workspace["facts"]["customer"], "customer_id": "gid://shopify/Customer/8102"}
    refused = await _hold(shop, again)
    assert refused.status_code == 409 and "The card changed since this was prepared" in refused.text, refused.text
    assert sent(shop, "store_credit_credit") == 0

    ident = await open_credit(shop)       # a new card for the same credit
    fresh = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))["proposal_id"]
    shop.store.balance = 25.0             # someone else's credit landed in Admin meanwhile
    moved = await _hold(shop, fresh)
    assert moved.status_code == 200 and moved.json()["status"] == "stale", moved.text
    assert sent(shop, "store_credit_credit") == 0


async def test_t3_01_a_code_whose_card_moved_without_a_withdrawal_is_never_created(shop):  # noqa: F811 - the fixture is tests/test_r12_made_once.py shop
    """The code's value changed, then its basis, neither through `touched`: the old hold card is
    refused at the door (409), and no code is created."""
    code = await open_code(shop)
    old = _hold_card(await tap(shop, "discount.stage", workspace_id=code))["proposal_id"]
    workspace = shop.runtime.sessions.get("g1").branch().workspace
    workspace["values"]["value"] = "25"
    refused = await _hold(shop, old)
    assert refused.status_code == 409 and "The card changed since this was prepared" in refused.text, refused.text

    workspace["values"]["value"] = "20"
    again = _hold_card(await tap(shop, "discount.stage", workspace_id=code))["proposal_id"]
    workspace["choices"]["basis"] = "amount"
    refused = await _hold(shop, again)
    assert refused.status_code == 409 and "The card changed since this was prepared" in refused.text, refused.text
    assert sent(shop, "discount_code_create") == 0


# ============================================================ T3-02: a completion that fails at Shopify's door


async def test_t3_02_a_completion_that_never_left_gives_the_card_back_and_the_next_hold_makes_one(shop):  # noqa: F811 - the fixture is tests/test_r12_made_once.py shop
    """Every read works; only `draft_order_complete` fails, and it fails before it left this Mac
    (a connection never made: `unsent`). The attempt is made, once; the card is given back with
    the reason; the next hold makes the order, once."""
    ident = card(await open_theo(shop))["workspace_id"]
    first = _hold_card(await tap(shop, "order.stage", workspace_id=ident))["proposal_id"]
    asked: list[str] = []
    real = shop.store.mutate

    async def mutate(name: str, variables: dict) -> dict:
        asked.append(name)
        if name == "draft_order_complete" and asked.count(name) == 1:
            raise ShopifyUnreached("Could not reach Shopify: connection refused")
        return await real(name, variables)

    shop.store.mutate = mutate
    done = (await _hold(shop, first)).json()
    assert asked == ["draft_order_complete"], "the completion itself was attempted, and nothing else was sent"
    assert done["status"] == "failed", done
    back = _workspace(done["ui"], ident)
    assert back["settled"] == "" and "Could not reach Shopify" in back["notes"][0], back
    again = _hold_card(await tap(shop, "order.stage", workspace_id=ident))["proposal_id"]
    assert (await _hold(shop, again)).json()["status"] == "verified"
    assert asked.count("draft_order_complete") == 2 and sent(shop, "draft_order_complete") == 1


async def test_t3_02_a_completion_that_left_and_landed_after_the_mac_gave_up_is_never_made_twice(shop):  # noqa: F811 - the fixture is tests/test_r12_made_once.py shop
    """The completion left and its answer never came back; read again at once the draft is still
    open. The card stays sent, not confirmed (at 361b0138 it was given back, and only the next
    Prepare's read of the drafts this card made stood between it and a second order). Shopify then
    finishes it. Prepare is refused on the card itself, and no second completion is sent."""
    ident = card(await open_theo(shop))["workspace_id"]
    first = _hold_card(await tap(shop, "order.stage", workspace_id=ident))["proposal_id"]
    asked: list[str] = []
    late: list[str] = []
    real = shop.store.mutate

    async def mutate(name: str, variables: dict) -> dict:
        asked.append(name)
        if name == "draft_order_complete" and not late:
            late.append(str(variables["id"]))
            raise ShopifyError(TIMED_OUT)
        return await real(name, variables)

    shop.store.mutate = mutate
    done = (await _hold(shop, first)).json()
    assert asked == ["draft_order_complete"] and done["status"] in ("failed", "unverified"), done
    kept = _workspace(done["ui"], ident)
    assert kept["settled"] == "unconfirmed" and kept["kicker"] == "Sent · not confirmed", kept
    assert kept["notes"] == ["Look at it in Admin before making it again."] and kept["actions"] == []
    draft = shop.store.drafts[late[0]]
    draft["status"], draft["order"] = "COMPLETED", {"id": "gid://shopify/Order/3001", "name": "CROOKS-3001"}

    again = await tap(shop, "order.stage", workspace_id=ident)
    assert again["ok"] is False and "has not said whether it made it" in again["detail"], again
    assert "look in Admin before making it again" in again["detail"]
    assert asked == ["draft_order_complete"], "no second completion was sent"


async def test_t3_02_a_completion_that_left_is_never_given_back_as_not_made(shop):  # noqa: F811 - the fixture is tests/test_r12_made_once.py shop
    """The reviewer's rule for T3-02: only a completion that certainly never left gives the card
    back. This one left — a read timeout, neither `unsent` nor `refused` — and read again at once
    the draft is still open, which proves nothing about a request Shopify may still be applying.
    The card must stay finished (sent, not confirmed), and Prepare on it is refused. At 361b0138 it
    was given back instead: he added postage — so the next Prepare priced a NEW draft, and the check
    of the drafts this card made found the first still open — Shopify then finished the first,
    and the hold on the new one made a second order. Shopify finishes the first here whatever the
    Mac said, after his next Prepare."""
    ident = card(await open_theo(shop))["workspace_id"]
    first = _hold_card(await tap(shop, "order.stage", workspace_id=ident))["proposal_id"]
    asked: list[str] = []
    late: list[str] = []
    real = shop.store.mutate

    async def mutate(name: str, variables: dict) -> dict:
        asked.append(name)
        if name == "draft_order_complete" and not late:
            late.append(str(variables["id"]))
            raise ShopifyError(TIMED_OUT)
        return await real(name, variables)

    shop.store.mutate = mutate
    done = (await _hold(shop, first)).json()
    back = _workspace(done["ui"], ident)
    if back["settled"] == "":
        await say(shop, "add five pounds postage", ("shopify_order_build", {"postage": 5}))
    again = await tap(shop, "order.stage", workspace_id=ident)
    draft = shop.store.drafts[late[0]]             # Shopify finishes the first completion now
    draft["status"], draft["order"] = "COMPLETED", {"id": "gid://shopify/Order/3001", "name": "CROOKS-3001"}
    if again["ok"]:
        await _hold(shop, again["changed"]["proposal_id"])
    completed = [d["id"] for d in shop.store.drafts.values() if d["status"] == "COMPLETED"]
    assert len(completed) == 1, (
        f"{len(completed)} orders made; after the lost answer the card came back as {back['kicker']!r}: {back['notes'][0]!r}")
    assert back["settled"] == "unconfirmed"
