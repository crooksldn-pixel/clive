"""Anticipation, end to end (§18, §19).

These go through the same HTTP the tablet goes through, against the golden world. What they are
for is the part a unit test cannot see: that opening an order really does start the background
reads, that MOVING to the next record then costs no read at all because the record was already
there, and that what came back says it was predicted rather than asked for. The scenario that
held the old Easyship boundary (§20) to saying it had checked nothing went with that boundary on
the owner's ruling of 8 October (DEC-071, ruling 24).
"""

from __future__ import annotations

import asyncio

from experience.harness import Harness
from experience.scenarios import Result, check


def _ok(c) -> bool:
    return bool(c.raw.get("ok", True))


def _install(*, on: bool):
    """A fresh anticipation layer, on or off, so a scenario is not affected by the one before."""
    from app.anticipation import engine as anticipation_mod
    from app.anticipation.learning import Learner
    from app.memory.prefetch import Prefetcher

    return anticipation_mod.install(anticipation_mod.Anticipator(
        learner=Learner(), prefetcher=Prefetcher(),
        max_anticipated=4 if on else 0, max_speculative=2 if on else 0,
    ))


async def _open_first(h: Harness, session_id: str) -> tuple[str, dict]:
    """Walk into a working set and open its first record, as the dock does. Returns the order
    and the enrichment payload — which is where "an order opened" is known."""
    await h.touch("open.area", area="orders", session_id=session_id)
    landed = await h.touch("workflow.next", session_id=session_id)
    order_id = (landed.entity or {}).get("ref", "")
    if not order_id:
        return "", {}
    _, enriched = await h.enrich(order_id, session_id=session_id)
    return order_id, enriched


async def anticipation_reads_ahead(h: Harness) -> Result:
    r = Result("anticipation_reads_ahead", "Opening an order reads the background and one guess")
    layer = _install(on=True)
    try:
        order_id, enriched = await _open_first(h, "ant1")
        r.checks.append(check("the set opened on a record", bool(order_id), f"order={order_id!r}"))
        if not order_id:
            return r
        anticipated = enriched.get("anticipated") or {}
        whys = [row.get("why") for row in anticipated.get("reads") or []]
        r.checks.append(check("the card being up starts the background reads",
                              "order.customer_history" in whys and "order.linked_email" in whys, f"{whys}"))
        r.checks.append(check("and one guess about where he goes next",
                              any(str(w).startswith("order.next_in_set") for w in whys), f"{whys}"))
        r.checks.append(check("the state learned from carries no identifier",
                              "@" not in str(anticipated.get("state")) and "Order" not in str(anticipated.get("state")),
                              f"state={anticipated.get('state')!r}"))
        r.checks.append(check("nothing speculative went past the bound",
                              len(whys) <= layer.max_anticipated, f"{len(whys)} started"))
        await asyncio.sleep(0.5)
        r.checks.append(check("every prediction says why it was made and that nobody asked for it",
                              bool(layer.explain()) and all(row["why"] and row["origin"] == "predicted" for row in layer.explain()),
                              f"{[row['why'] for row in layer.explain()]}"))
    finally:
        _install(on=False)
    return r


async def anticipation_makes_next_free(h: Harness) -> Result:
    """The measurement that matters: with the layer on, moving to the next record needs no
    read, because the record is already held — and the cache says it was a predicted one."""
    r = Result("anticipation_makes_next_free", "Next costs no read after an order card came up")
    from app.memory import current as memory

    outcome: dict[str, dict] = {}
    for on in (False, True):
        _install(on=on)
        # A cold Mac for each half. Without this the second half finds the record the first
        # half read still in the tiered cache — which is the cache working, and would make the
        # comparison meaningless.
        memory().clear()
        session = f"antmove{'on' if on else 'off'}"
        order_id, _ = await _open_first(h, session)
        if not order_id:
            r.checks.append(check("the set opened on a record", False, "nothing landed"))
            return r
        await asyncio.sleep(0.5)
        before = memory().counts()["predicted_hits"]
        moved = await h.touch("workflow.next", session_id=session)
        outcome["on" if on else "off"] = {
            "read": bool((moved.raw.get("changed") or {}).get("read")),
            "replayed": bool((moved.raw.get("changed") or {}).get("replayed")),
            "ms": moved.raw.get("served_ms"),
            "predicted_hits": memory().counts()["predicted_hits"] - before,
            "ok": _ok(moved),
        }
        r.captures.append(moved)
    _install(on=False)
    off, on = outcome["off"], outcome["on"]
    r.checks.append(check("with the layer off, the move has to read the record",
                          off["read"] is True, f"off={off}"))
    r.checks.append(check("with it on, the record is already there",
                          on["read"] is False and on["replayed"] is True, f"on={on}"))
    r.checks.append(check("and the cache says what it served was predicted, not asked for",
                          on["predicted_hits"] >= 1 and off["predicted_hits"] == 0,
                          f"on={on['predicted_hits']} off={off['predicted_hits']}"))
    r.checks.append(check("the move is no slower for it", float(on["ms"] or 0) <= float(off["ms"] or 0) + 5,
                          f"on={on['ms']}ms off={off['ms']}ms"))
    return r


async def anticipation_yields_to_the_owner(h: Harness) -> Result:
    """A real request outranks speculation: the reads the layer started about the record he has
    left are dropped rather than finished."""
    r = Result("anticipation_yields_to_the_owner", "Speculation stands down when he asks for something")
    layer = _install(on=True)
    try:
        order_id, _ = await _open_first(h, "antyield")
        if not order_id:
            r.checks.append(check("the set opened on a record", False, "nothing landed"))
            return r
        spoken = await h.say("what's waiting to go out", session_id="antyield")
        r.checks.append(check("the question is answered", spoken.status == 200, f"status={spoken.status}"))
        counts = layer.counts()
        r.checks.append(check("something was predicted at all", counts["started"] >= 1, f"{counts}"))
        r.checks.append(check("nothing speculative is left running for that record",
                              layer.prefetcher.in_flight_for(f"{h.runtime.sessions.get_or_create('antyield').login or 'owner'}|antyield", lane="p2") == 0,
                              f"{layer.prefetcher.counts()}"))
        r.checks.append(check("and no write was ever reachable from it", counts["refused_writes"] == 0 and layer.counts()["started"] >= 1, f"{counts}"))
    finally:
        _install(on=False)
    return r


async def returns_are_not_available_yet(h: Harness) -> Result:
    """A return goes through CROOKS Returns and never through Shopify (DEC-066). The four rows
    that said returns were not built are retired, so the family table has none of them, and
    nothing is registered or reviewed that could make a return in Shopify itself.

    The name is kept because tests/test_crooks_returns.py calls it by it."""
    r = Result("returns_are_not_available_yet", "A return goes through CROOKS Returns, never through Shopify")
    from app.returns import contract
    from app.tools import registry

    families = await h.runtime.family_states() if hasattr(h.runtime, "family_states") else {}
    for key, capability in contract.CAPABILITIES.items():
        r.checks.append(check(f"{capability.label.lower()} has no row in the families table",
                              key not in families, f"{key}={(families.get(key) or {}).get('state')!r}"))
    # CROOKS Returns (app/tools/returns_tools.py, 3 October 2026) adds the only tools named for
    # returns: three reads of the owner's returns service and one change staged through ITS
    # actions. None of them is a Shopify mutation: CLIVE still cannot start a return itself.
    from app.clients.shopify import REVIEWED_MUTATIONS

    registered = sorted(s.name for s in registry.all_specs() if "return" in s.name or "exchange" in s.name)
    r.checks.append(check("the only tools named for returns are CROOKS Returns' own",
                          registered == ["return_action", "return_find", "returns_open", "returns_stats"], f"{registered}"))
    shopify = [s.name for s in registry.all_specs() if ("return" in s.name or "exchange" in s.name)
               and s.write is not None and (s.write.mutation in REVIEWED_MUTATIONS or not s.write.mutation.startswith("returns:"))]
    r.checks.append(check("no Shopify return mutation is registered at all", not shopify, f"{shopify}"))
    # And by what is sent, not by what it is called: no reviewed Shopify document touches a return
    # (returnCreate, returnProcess, returnCancel…) or the parcel coming back.
    touching = shopify_return_documents()
    r.checks.append(check("no reviewed Shopify mutation document touches a return", not touching, f"{touching}"))
    return r


# The words a Shopify mutation about a return, or the parcel coming back, cannot be written without.
RETURN_WORDS = ("return", "reversedelivery", "reversefulfillment")


def shopify_return_documents() -> list[str]:
    """The reviewed Shopify mutations (app/clients/shopify.py) whose document names a return, a
    reverse delivery or a reverse fulfilment, in any case. Empty while a return's changes go only
    through CROOKS Returns."""
    from app.clients.shopify import REVIEWED_MUTATIONS

    return sorted(name for name, reviewed in REVIEWED_MUTATIONS.items()
                  if any(word in reviewed.document.lower() for word in RETURN_WORDS))


SCENARIOS = (
    ("anticipation_reads_ahead", anticipation_reads_ahead),
    ("anticipation_makes_next_free", anticipation_makes_next_free),
    ("anticipation_yields_to_the_owner", anticipation_yields_to_the_owner),
    ("returns_are_not_available_yet", returns_are_not_available_yet),
)
