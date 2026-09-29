"""Round 13: a change that left for Shopify and was not proven made says so on every surface.

The evidence builder's open item. A £20 store credit is sent, and Shopify's answer never comes
back (a read timeout: neither `unsent` nor `refused`). The engine settles it as failed,
`service_unavailable`, because its one re-read still shows £15. The card the credit was prepared
from already knew better (round 13, S2b-02): it left, so it is "sent, not confirmed" and makes
nothing more. But beside it the result card was titled "Not applied", the hold card settled from
the same code (`service_unavailable`) to "Not applied", and /actions/states went on calling it
failed. On the owner's screen that is two answers, and one of them invites him to give the credit
again.

Now the commit's answer, the result card, the voice and every later reconciliation say what the
workspace says: sent, not confirmed. A send proven not to have left keeps saying "Not applied",
and a proven one "Applied". Through the real `/actions` routes, on round 12's fake shop.
"""

from __future__ import annotations

import pytest

from tests.test_r12_orders import PROXIED, tap
from tests.test_r13_evidence_made_once import (  # noqa: F401 (the fixture)
    _credit_answer_lost,
    _hold,
    _hold_card,
    _workspace,
    open_credit,
    shop,
)


def _errors(ui: list) -> list[dict]:
    return [i["data"] for i in ui if i["type"] == "error"]


async def _states(client, proposal_id: str) -> dict:
    answer = await client.get("/actions/states", params={"session_id": "g1", "ids": proposal_id}, headers=PROXIED)
    assert answer.status_code == 200, answer.text
    return answer.json()["states"][proposal_id]


async def test_a_timed_out_credit_is_sent_not_confirmed_on_every_surface(shop):  # noqa: F811
    ident = await open_credit(shop)
    first = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))["proposal_id"]
    _credit_answer_lost(shop.store, landed=False, reread_fails=False)
    lost = (await _hold(shop, first)).json()

    assert _workspace(lost["ui"], ident)["settled"] == "unconfirmed"
    assert (lost["status"], lost["code"]) == ("unverified", "unverified"), lost
    assert "not confirmed" in lost["spoken"] and "Nothing was" not in lost["spoken"], lost["spoken"]
    (result,) = _errors(lost["ui"])
    assert result["title"] != "Not applied" and "not confirmed" in result["recovery"], result
    assert "Nothing was" not in result["recovery"], result
    assert shop.runtime.sessions.get("g1").last_outcome == lost["spoken"]
    later = await _states(shop, first)
    assert (later["status"], later["code"]) == ("unverified", "unverified"), later


async def test_a_credit_proven_never_sent_still_says_not_applied(shop):  # noqa: F811
    """The edge: a connection that was never made changed nothing, and says so."""
    from app.clients.shopify import ShopifyUnreached

    ident = await open_credit(shop)
    first = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))["proposal_id"]
    real = shop.store.mutate

    async def never_left(name: str, variables: dict) -> dict:
        if name == "store_credit_credit":
            raise ShopifyUnreached("Could not reach Shopify: the connection was never made")
        return await real(name, variables)

    shop.store.mutate = never_left
    lost = (await _hold(shop, first)).json()
    assert lost["status"] == "failed" and lost["code"] != "unverified", lost
    assert _workspace(lost["ui"], ident)["settled"] == ""
    (result,) = _errors(lost["ui"])
    assert result["title"] == "Not applied", result
    later = await _states(shop, first)
    assert later["status"] == "failed", later


@pytest.mark.parametrize("reread_fails", [False, True], ids=["read-back", "unreadable"])
async def test_a_credit_that_landed_is_never_called_not_confirmed_once_proven(shop, reread_fails):  # noqa: F811
    """Landed and read back: applied. Landed and unreadable: sent, not confirmed, not failed."""
    ident = await open_credit(shop)
    first = _hold_card(await tap(shop, "credit.stage", workspace_id=ident))["proposal_id"]
    _credit_answer_lost(shop.store, landed=True, reread_fails=reread_fails)
    lost = (await _hold(shop, first)).json()
    if reread_fails:
        assert lost["status"] in ("unverified",) and "Nothing was" not in lost["spoken"], lost
    else:
        assert lost["status"] == "verified" and lost["code"] == "verified", lost
        assert _errors(lost["ui"]) == []
