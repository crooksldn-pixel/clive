"""The Add button on the variant picker prepares a change to the order on screen, and to no other.

The 2026-09-28 deploy review, round 9, E-01. The picker is drawn for the order this half has
open, but its Add button carries the order id it was drawn with. The owner opens the picker on
one order, moves to another on the same half, and the old picker is still on the glass: its Add
posts the FIRST order. That order was issued to this conversation, so the one check
`_stage_add_item` made — `may_open` — passed it, and the change was staged against the first
order while its card was labelled with the second order's number.

These hold the repair: a posted order must be the order this half has open, the label is that
same order's, and the refusal says what to do. The route-level half — the stale picker tapped
through `POST /command` with nothing prepared and no calculation run — is the golden scenario
`order_add_item_stale_picker` (experience/scenario_packs/order_edit.py).
"""

from __future__ import annotations

from app import commands
from app.commands import Ctx
from app.families import order_edit  # noqa: F401 — registers the two commands
from app.session.models import Session

FIRST = "gid://shopify/Order/1930"
SECOND = "gid://shopify/Order/1931"
HOODIE = "gid://shopify/ProductVariant/9102"


def _ctx(session, branch, **args):
    return Ctx(runtime=None, session=session, branch=branch, args={k: str(v) for k, v in args.items()})


def _session_on_two_orders() -> tuple[Session, object]:
    """A conversation that has been shown both orders and the hoodie, and is now on the SECOND."""
    session = Session(session_id="bind1")
    session.issue(FIRST, SECOND, HOODIE)
    branch = session.branch()
    branch.visit("order", FIRST, "#1930")
    branch.visit("order", SECOND, "#1931")
    return session, branch


def test_a_stale_picker_for_another_order_is_refused():
    """The picker was drawn on #1930; the owner is on #1931 now; Add posts #1930. Before the
    repair this staged a change to #1930 labelled "#1931". It must stage nothing."""
    session, branch = _session_on_two_orders()
    outcome = commands.run("order_edit.stage", _ctx(session, branch, order_id=FIRST, variant_id=HOODIE, quantity=1))
    assert not outcome.ok and outcome.code == "wrong_order", outcome
    assert "stage" not in outcome.changed, "a refused Add names no change to prepare"
    assert "Open the picker again" in outcome.detail


def test_the_order_on_screen_is_the_order_staged_and_the_label_is_its_own():
    session, branch = _session_on_two_orders()
    outcome = commands.run("order_edit.stage", _ctx(session, branch, order_id=SECOND, variant_id=HOODIE, quantity=2))
    assert outcome.ok, outcome.detail
    assert outcome.changed["stage"]["args"] == {"order_id": SECOND, "variant_id": HOODIE, "quantity": 2}
    assert outcome.changed["entity"] == {"kind": "order", "ref": SECOND, "label": "#1931"}


def test_an_add_that_names_no_order_means_the_order_on_screen():
    """The tablet always posts the picker's order; a form without one means the open order,
    which is the only order it could mean."""
    session, branch = _session_on_two_orders()
    outcome = commands.run("order_edit.stage", _ctx(session, branch, variant_id=HOODIE))
    assert outcome.ok, outcome.detail
    assert outcome.changed["stage"]["args"]["order_id"] == SECOND


def test_with_no_order_open_nothing_is_staged_whatever_was_posted():
    """A half that has moved off orders entirely — onto a customer — has no order for an old
    picker's Add to reach, even one this conversation was shown."""
    session, branch = _session_on_two_orders()
    branch.visit("customer", "gid://shopify/Customer/7001", "Mia Jones")
    outcome = commands.run("order_edit.stage", _ctx(session, branch, order_id=FIRST, variant_id=HOODIE))
    assert not outcome.ok and "stage" not in outcome.changed, outcome
