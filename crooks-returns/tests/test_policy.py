from datetime import date, timedelta

import pytest

from returns import policy
from returns.fake import sample_orders
from returns.models import Postage, Reason, Resolution, Selection

from .conftest import NOW

TODAY = date(2026, 10, 3)
TEE, JEANS = "gid://shopify/FulfillmentLineItem/1", "gid://shopify/FulfillmentLineItem/2"


@pytest.fixture
def orders():
    recent, old, guest = sample_orders(NOW)
    return recent, old, guest


def sel(fli, reason, qty=1):
    return Selection(fulfillment_line_item_id=fli, quantity=qty, reason=reason)


def option(q, resolution):
    return next(o for o in q.options if o.resolution == resolution)


def test_owner_bonus_examples(settings):
    # "£60 should be £70, a £25 tee should be £30"
    assert 2500 + policy.credit_bonus(2500, settings) == 3000
    assert 6000 + policy.credit_bonus(6000, settings) == 7000


def test_fourteen_days_from_delivery(orders, settings):
    recent, old, _ = orders
    check = policy.check_line(recent, recent.lines[0], TODAY, settings)
    assert check.code == "ok"
    assert check.window_ends == (NOW - timedelta(days=5)).date() + timedelta(days=14)
    late = policy.check_line(old, old.lines[0], TODAY, settings)
    assert late.code == "fault_only"
    assert set(late.allowed_reasons) == {Reason.faulty, Reason.wrong_item, Reason.not_as_described}


def test_window_closes_entirely_after_thirty_days(orders, settings):
    recent, _, _ = orders
    check = policy.check_line(recent, recent.lines[0], TODAY + timedelta(days=30), settings)
    assert check.code == "window_closed" and not check.allowed_reasons


def test_not_delivered_without_any_fulfilment(orders, settings):
    recent, _, _ = orders
    recent.delivered_at = recent.fulfilled_at = None
    assert policy.check_line(recent, recent.lines[0], TODAY, settings).code == "not_delivered"


def test_change_of_mind_after_window_is_refused(orders, settings):
    _, old, _ = orders
    with pytest.raises(policy.PolicyError):
        policy.quote(old, [sel(TEE, Reason.changed_mind)], TODAY, settings)


def test_non_returnable_tag_allows_faults_only(orders, settings):
    recent, _, _ = orders
    recent.lines[0].tags = ["Non-Returnable"]
    with pytest.raises(policy.PolicyError):
        policy.quote(recent, [sel(TEE, Reason.changed_mind)], TODAY, settings)
    assert policy.quote(recent, [sel(TEE, Reason.faulty)], TODAY, settings).options


def test_size_swap_first_then_credit_then_refund(orders, settings):
    recent, _, _ = orders
    q = policy.quote(recent, [sel(TEE, Reason.too_small)], TODAY, settings)
    assert [o.resolution for o in q.options] == [
        Resolution.exchange,
        Resolution.store_credit,
        Resolution.refund,
    ]
    sizes = [v.title for v in q.options[0].exchange_choices[TEE]]
    assert sizes == ["L"]  # bigger only; not M (theirs), not the out-of-stock XL


def test_exchange_and_credit_postage_is_free(orders, settings):
    recent, _, _ = orders
    q = policy.quote(recent, [sel(JEANS, Reason.changed_mind)], TODAY, settings)
    for resolution in (Resolution.exchange, Resolution.store_credit):
        assert all(p.fee_pence == 0 for p in option(q, resolution).postage)
    credit = option(q, Resolution.store_credit)
    assert credit.postage[0].total_pence == 7000


def test_change_of_mind_refund_label_at_cost_or_self_ship(orders, settings):
    recent, _, _ = orders
    q = policy.quote(recent, [sel(TEE, Reason.changed_mind)], TODAY, settings)
    refund = option(q, Resolution.refund)
    by = {p.choice: p for p in refund.postage}
    assert by[Postage.paid_label].fee_pence == 350
    assert by[Postage.paid_label].total_pence == 2500 - 350
    assert by[Postage.self_ship].total_pence == 2500
    assert Postage.free_label not in by


def test_no_label_cost_configured_means_self_ship_only(orders, settings):
    recent, _, _ = orders
    settings.return_label_cost_pence = None
    q = policy.quote(recent, [sel(TEE, Reason.changed_mind)], TODAY, settings)
    assert [p.choice for p in option(q, Resolution.refund).postage] == [Postage.self_ship]


def test_faulty_refund_is_free_and_full(orders, settings):
    recent, _, _ = orders
    q = policy.quote(recent, [sel(TEE, Reason.faulty)], TODAY, settings)
    refund = option(q, Resolution.refund)
    assert {p.choice for p in refund.postage} == {Postage.free_label, Postage.self_ship}
    assert all(p.total_pence == 2500 for p in refund.postage)
    # A faulty item may be swapped like-for-like.
    assert "M" in [v.title for v in option(q, Resolution.exchange).exchange_choices[TEE]]


def test_returning_everything_refunds_delivery(orders, settings):
    recent, _, _ = orders
    q = policy.quote(
        recent, [sel(TEE, Reason.changed_mind), sel(JEANS, Reason.changed_mind)], TODAY, settings
    )
    refund = option(q, Resolution.refund)
    assert refund.shipping_refund_pence == 395
    part = policy.quote(recent, [sel(TEE, Reason.changed_mind)], TODAY, settings)
    assert option(part, Resolution.refund).shipping_refund_pence == 0


def test_guest_orders_get_no_store_credit(orders, settings):
    _, _, guest = orders
    q = policy.quote(guest, [sel(TEE, Reason.too_big)], TODAY, settings)
    assert Resolution.store_credit not in [o.resolution for o in q.options]


def test_quantity_and_ownership_checked(orders, settings):
    recent, _, _ = orders
    with pytest.raises(policy.PolicyError):
        policy.quote(recent, [sel(TEE, Reason.too_big, qty=2)], TODAY, settings)
    with pytest.raises(policy.PolicyError):
        policy.quote(
            recent, [sel("gid://shopify/FulfillmentLineItem/999", Reason.too_big)], TODAY, settings
        )


def test_too_big_offers_only_smaller_sizes(orders, settings):
    recent, _, _ = orders
    q = policy.quote(recent, [sel(JEANS, Reason.too_big)], TODAY, settings)
    assert [v.title for v in option(q, Resolution.exchange).exchange_choices[JEANS]] == ["30"]


def test_too_small_in_the_biggest_size_offers_no_swap(orders, settings):
    recent, _, _ = orders
    recent.lines[1].variant_id = "gid://shopify/ProductVariant/jeans-34"
    recent.lines[1].options = {"Size": "34"}
    q = policy.quote(recent, [sel(JEANS, Reason.too_small)], TODAY, settings)
    assert Resolution.exchange not in [o.resolution for o in q.options]


def test_size_swap_keeps_colour_and_goes_nearest_first(orders, settings):
    from returns.models import Variant

    recent, _, _ = orders
    line = recent.lines[0]
    line.sizes = ["XS", "S", "M", "L", "XL"]
    line.options = {"Colour": "Black", "Size": "S"}
    line.siblings = [
        Variant(
            id=f"v-{c}-{s}",
            title=f"{c} / {s}",
            price_pence=2500,
            available=True,
            options={"Colour": c, "Size": s},
        )
        for c in ("White", "Black")
        for s in line.sizes
    ]
    line.variant_id = "v-Black-S"
    q = policy.quote(recent, [sel(TEE, Reason.too_small)], TODAY, settings)
    titles = [v.title for v in option(q, Resolution.exchange).exchange_choices[TEE]]
    assert titles == ["Black / M", "Black / L", "Black / XL"]
    q = policy.quote(recent, [sel(TEE, Reason.changed_mind)], TODAY, settings)
    assert len(option(q, Resolution.exchange).exchange_choices[TEE]) == 9  # any other variant


def test_size_chart_parsing():
    from returns.shopify import parse_size_chart, size_option_of

    rows = parse_size_chart('[{"size":"M","chest":"110.5cm"},{"bad":1},"x"]')
    assert rows == [{"size": "M", "chest": "110.5cm"}]
    assert parse_size_chart("not json") == [] and parse_size_chart(None) == []
    opts = [
        {"name": "Colour", "optionValues": [{"name": "Black"}]},
        {"name": "Size", "optionValues": [{"name": "S"}, {"name": "M"}]},
    ]
    assert size_option_of(opts) == ("Size", ["S", "M"])


def test_reasons_map_to_the_stores_library():
    from returns.shopify import reason_ids_from

    live = [
        "unknown",
        "changed-my-mind",
        "item-not-as-described",
        "received-the-wrong-item",
        "other-reason",
        "damaged-or-defective",
        "too-small",
        "too-big",
        "style",
        "color",
    ]
    ids = reason_ids_from([{"id": f"gid://{h}", "handle": h, "deleted": False} for h in live])
    assert len(ids) == 6
    assert ids["faulty"] == "gid://damaged-or-defective"
