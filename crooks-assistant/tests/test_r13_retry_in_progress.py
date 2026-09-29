"""Round 13's independent check: a retried commit answered `in_progress` settles nothing.

The same hold card committed twice — a retried request, an Android double-fire — while the first
is still at Shopify. The engine makes the retry wait for the first commit's outcome, for a while
(`WAIT_FOR_OUTCOME_S`), and then answers it `in_progress`. The route then noted that answer on
the card the change was prepared from (app/families/_workspace.py `after_commit`), as if it were
the outcome:

* when the first commit's change had already left, the card was locked as "sent, not confirmed",
  and Shopify's refusal a moment later could no longer give it back;
* when the first commit was still at its read before sending, the card was let go, so Prepare
  made a second hold card, and a second credit, while the first was still on its way.

Now only the commit sending the change settles the card. Through the real /actions routes on
round 12's fake shop; the wait is shortened so the retry is answered while the first still waits.
"""

from __future__ import annotations

import asyncio

from app.actions import engine as engine_module
from app.clients.shopify import ShopifyRefused
from app.families import _workspace as workspaces
from tests.test_r12_orders import tap
from tests.test_r13_evidence_made_once import (  # noqa: F401 (the fixture)
    _arm,
    _commit,
    _hold_card,
    _workspace,
    open_credit,
    sent,
    shop,
)


def _stalled_at(store, *, mutation: str = "", query: str = "", refuse: bool = False):
    """Shopify slow to answer one mutation or one read: it waits at the door until released, then
    answers — or, with `refuse`, refuses the mutation with a user error. (arrived, release)."""
    arrived, release = asyncio.Event(), asyncio.Event()
    real_mutate, real_graphql = store.mutate, store.graphql

    async def mutate(name: str, variables: dict) -> dict:
        if mutation and name == mutation:
            arrived.set()
            await release.wait()
            if refuse:
                raise ShopifyRefused("Store credit is not enabled for this customer")
        return await real_mutate(name, variables)

    async def graphql(text: str, variables: dict | None = None) -> dict:
        if query and query in text and not arrived.is_set():
            arrived.set()
            await release.wait()
        return await real_graphql(text, variables)

    store.mutate, store.graphql = mutate, graphql
    return arrived, release


async def test_a_retry_answered_in_progress_does_not_lock_a_card_shopify_then_refuses(shop, monkeypatch):  # noqa: F811
    monkeypatch.setattr(engine_module, "WAIT_FOR_OUTCOME_S", 0.05)
    ident = await open_credit(shop)
    first = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))["proposal_id"]
    nonce = await _arm(shop, first)
    arrived, release = _stalled_at(shop.store, mutation="store_credit_credit", refuse=True)

    sending = asyncio.create_task(_commit(shop, first, nonce))
    await asyncio.wait_for(arrived.wait(), timeout=5)
    retry = await _commit(shop, first, nonce)
    assert retry.json()["code"] == "in_progress", retry.text
    assert workspaces._NOTED[ident]["state"] == workspaces.SENDING, workspaces._NOTED[ident]

    release.set()
    refused = (await asyncio.wait_for(sending, timeout=10)).json()
    assert refused["code"] == "refused", refused
    back = _workspace(refused["ui"], ident)
    assert back["settled"] == "", back
    assert (await tap(shop, "credit.stage", workspace_id=ident))["ok"] is True, "Shopify refused it: the card is his again"


async def test_a_retry_answered_in_progress_does_not_free_a_card_still_at_its_first_read(shop, monkeypatch):  # noqa: F811
    monkeypatch.setattr(engine_module, "WAIT_FOR_OUTCOME_S", 0.05)
    ident = await open_credit(shop)
    first = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))["proposal_id"]
    nonce = await _arm(shop, first)
    arrived, release = _stalled_at(shop.store, query="CrooksStoreCredit")

    sending = asyncio.create_task(_commit(shop, first, nonce))
    await asyncio.wait_for(arrived.wait(), timeout=5)
    retry = await _commit(shop, first, nonce)
    assert retry.json()["code"] == "in_progress", retry.text
    again = await tap(shop, "credit.stage", workspace_id=ident)
    assert again["ok"] is False, "the card is still being made: nothing more is prepared from it"

    release.set()
    assert (await asyncio.wait_for(sending, timeout=10)).json()["code"] == "verified"
    assert sent(shop, "store_credit_credit") == 1
