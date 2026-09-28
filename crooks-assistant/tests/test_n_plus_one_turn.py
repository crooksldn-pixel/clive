"""The N+1 bound, measured on a spoken turn rather than on a tool called directly.

The 2026-09-28 deploy review, round 9, I-tests3 I-04: `tests/test_n_plus_one.py::turn` hands
`commerce_summary` and its task straight to `dispatch`, so it bounds the TOOL and says nothing
about what a sentence costs once the model has chosen its reads. These go through `POST /turn`
on an admitted harness, with the model's reads scripted — the two shapes a model can choose for
"has anyone bought today that has bought before?" — and count what actually went to the shop,
by operation, for each:

* the summary read: no per-customer read at all, whatever the day holds;
* the pattern the model used on 11 September (D-4): the day's orders, then one customer history
  per buyer — one entity read per buyer, measured, which is the bill the summary removes.

What is scripted is the model's CHOICE (see `Harness.ask`); what is measured is what the gate,
the read layer and the shop do with it.
"""

from __future__ import annotations

import pytest

from experience.fixtures import world
from experience.harness import harness

SAID = "has anyone bought today that has bought before?"
PER_CUSTOMER = "CrooksCustomerOrders"


@pytest.fixture()
async def stage():
    async with harness(admitted=True) as h:
        yield h


def _sent(stage, before: int) -> list[str]:
    return [operation for operation, _ in stage.store.queries[before:]]


async def test_the_summary_read_costs_no_customer_read_on_a_spoken_turn(stage):
    before = len(stage.store.queries)
    c = await stage.ask(SAID, ("commerce_summary", {"task": "returning_customers", "period": "today"}),
                        reply="One of today's buyers has bought before.", session_id="n1")
    sent = _sent(stage, before)
    assert c.model_calls == 1 and c.scripted == ["commerce_summary"]
    called = c.raw.get("tool_calls") or []
    assert [t.get("name") for t in called] == ["commerce_summary"] and all(t.get("ok") for t in called), called
    assert PER_CUSTOMER not in sent, f"a per-customer read went out on the summary path: {sent}"
    assert len(sent) <= 1, f"the day is one read of the shop at most (the cache holds it): {sent}"


async def test_the_per_buyer_pattern_costs_one_customer_read_per_buyer(stage):
    """The measured BEFORE, on the same turn path: what the summary saves is real only if the
    other shape really costs this."""
    buyers = sorted({o.person.customer_id for o in world.today()})
    assert len(buyers) >= 2, "the golden day has more than one buyer to read"
    reads = [("commerce_query", {"entity": "orders", "period": "today", "limit": 25})]
    reads += [("shopify_customer_history", {"customer_id": cid}) for cid in buyers]
    # The ids have to be ones this conversation was shown, as they would be after the listing.
    await stage.ask("show me today's orders", ("commerce_query", {"entity": "orders", "period": "today", "limit": 25}),
                    reply="Today's orders.", session_id="n2")
    before = len(stage.store.queries)
    c = await stage.ask(SAID, *reads, reply="One has bought before.", session_id="n2")
    sent = _sent(stage, before)
    assert c.model_calls == 1 and all(t.get("ok") for t in c.raw.get("tool_calls") or []), c.raw.get("tool_calls")
    assert sent.count(PER_CUSTOMER) == len(buyers), f"one entity read per buyer, measured: {sent}"
