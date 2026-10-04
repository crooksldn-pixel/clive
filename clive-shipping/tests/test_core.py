from decimal import Decimal

import pytest

from shipping.basis import basis
from shipping.models import ShipmentStatus as S
from shipping.money import Money, to_minor
from shipping.states import IllegalTransition, move

from .conftest import NOW, make_shipment


def test_money_is_integer_minor_units():
    assert to_minor(10.69) == 1069  # not 1068.9999…
    assert to_minor("0.1") + to_minor("0.2") == 30
    assert to_minor(Decimal("2.385")) == 239  # half up
    assert to_minor(None) == 0
    assert str(Money(minor=1124)) == "£11.24"
    with pytest.raises(ValueError):
        Money(minor=1) + Money(minor=1, currency="EUR")


def test_no_shortcuts_through_the_state_machine(store, provider):
    s = make_shipment(store, provider)
    with pytest.raises(IllegalTransition):
        move(s, S.fulfilled, at=NOW, actor="x", event="cheat")
    with pytest.raises(IllegalTransition):
        move(s, S.label_purchased, at=NOW, actor="x", event="cheat")
    move(s, S.purchasing, at=NOW, actor="x", event="ok")
    with pytest.raises(IllegalTransition):
        move(s, S.cancelled, at=NOW, actor="x", event="money may have moved")


def test_basis_changes_with_anything_a_purchase_depends_on(store, provider):
    s = make_shipment(store, provider)
    b = basis(s)
    assert basis(s) == b
    for change in (
        lambda x: setattr(x.lines[0], "quantity", 3),
        lambda x: setattr(x.destination, "postcode", "10117"),
        lambda x: setattr(x.package, "empty_weight_g", 90),
        lambda x: setattr(x.quote, "amount", Money(minor=1200)),
        lambda x: setattr(x.lines[0], "origin_country", "CN"),
    ):
        copy = s.model_copy(deep=True)
        change(copy)
        assert basis(copy) != b
