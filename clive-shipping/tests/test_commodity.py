"""Finding commodity codes from plain English, decided by the official UK Trade Tariff.

The tariff here is the real one, recorded (tests/fixtures/tariff, read 2026-10-08 from
www.trade-tariff.service.gov.uk): the headings' official trees and the official entry of every
code the helper can reach. No test states a code from memory: each expected code is the line the
official tree leads to, and the fixture proves it exists and can be declared.
"""

import json
from pathlib import Path

import httpx
import pytest

from shipping.commodity import (
    CommodityAssistant,
    RuleClassifier,
    TariffUnavailable,
    UkTradeTariff,
    spaced,
)
from shipping.fake_shopify import FakeShopify, fo, tee_line
from shipping.purchase import ActionError, Purchases
from shipping.service import ShippingService

from .conftest import SHOP

FIX = Path(__file__).parent / "fixtures" / "tariff"
COMMODITIES = json.loads((FIX / "commodities.json").read_text())


class OfficialTariff:
    """The UK Trade Tariff API, answering from the recorded official responses."""

    def __init__(self) -> None:
        self.down = False
        self.extra: dict[str, dict] = {}
        self.asked: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.asked.append(path)
        if self.down:
            raise httpx.ConnectError("tariff unreachable", request=request)
        if "/headings/" in path:
            f = FIX / f"heading_{path.rsplit('/', 1)[1]}.json"
            return (
                httpx.Response(200, json=json.loads(f.read_text()))
                if f.exists()
                else httpx.Response(404)
            )
        code = path.rsplit("/", 1)[1]
        found = self.extra.get(code) or COMMODITIES.get(code)
        return (
            httpx.Response(200, json=found)
            if found
            else httpx.Response(404, json={"errors": [{"detail": "not found"}]})
        )


@pytest.fixture
def official():
    return OfficialTariff()


@pytest.fixture
def helper(official):
    tariff = UkTradeTariff(
        "https://tariff.test/uk/api", http=httpx.Client(transport=httpx.MockTransport(official))
    )
    return CommodityAssistant(tariff)


def ask(helper, text, **answers):
    return helper.suggest(text, answers)


# ------------------------------------------------------------------ plain English → code


def test_jorts_need_only_who_they_are_cut_for_and_the_fibre(helper):
    first = ask(helper, "jorts")
    assert first.state == "question" and first.question.fact == "gender"  # denim → woven: known
    second = ask(helper, "jorts", gender="men")
    assert second.state == "question" and second.question.fact == "fibre"
    done = ask(helper, "jorts", gender="men", fibre="cotton")
    assert done.state == "candidate" and done.code == "6203429000"
    assert done.entry.path[-3:] == [
        "Trousers, bib and brace overalls, breeches and shorts",
        "Of cotton",
        "Other",
    ]
    assert any("denim" in r for r in done.reasons)  # says why, in words


def test_what_is_already_known_is_never_asked(helper):
    done = ask(helper, "Men's cotton jeans")
    assert done.state == "candidate" and done.code == "6203423100"
    assert done.entry.description == "Of denim"


def test_joggers_ask_knitted_or_woven(helper):
    q = ask(helper, "Joggers")
    assert q.state == "question" and q.question.fact == "construction"
    assert ask(helper, "Women's cotton joggers", construction="knitted").code == "6104620000"


def test_a_hoodie_for_anyone_is_classified_as_womens_by_note_9(helper):
    done = ask(helper, "Unisex cotton hoodie")
    assert done.state == "candidate" and done.code == "6110209900"
    assert any("note 9" in r for r in done.reasons)


def test_t_shirt_and_skirt(helper):
    assert ask(helper, "Cotton T-shirt").code == "6109100010"
    skirt = ask(helper, "denim skirt")  # women's by heading, woven by denim: only the fibre
    assert skirt.state == "question" and skirt.question.fact == "fibre"
    assert ask(helper, "denim skirt", fibre="cotton").code == "6204520090"


def test_woven_cotton_trousers_ask_the_fabric_in_the_tariffs_words(helper):
    q = ask(helper, "Men's cotton trousers", construction="woven")
    assert q.state == "question" and q.question.fact == "weave"
    labels = [o["label"] for o in q.question.options]
    assert labels[:2] == ["Of denim", "Of cut corduroy"]  # the official lines themselves
    assert (
        ask(helper, "Men's cotton trousers", construction="woven", weave="neither").code
        == "6203423500"
    )


def test_something_it_cannot_classify_is_handed_back(helper):
    assert ask(helper, "leather jacket").state == "manual"
    wool = ask(helper, "Men's wool jumper")  # turns on weight (600 g): never assumed
    assert wool.state == "manual" and wool.code is None


def test_every_reachable_code_is_a_current_declarable_line():
    for code, entry in COMMODITIES.items():
        a = entry["data"]["attributes"]
        assert (
            entry["data"]["type"] == "commodity" and a["declarable"] and not a["validity_end_date"]
        )
        assert a["goods_nomenclature_item_id"] == code and len(code) == 10


# ------------------------------------------------------------------ failures


def test_tariff_unavailable_means_manual_never_a_guess(helper, official):
    official.down = True
    out = ask(helper, "Men's cotton jeans")
    assert out.state == "manual" and out.code is None and "couldn't be reached" in out.message


def test_a_failing_classifier_means_manual(official):
    class Broken(RuleClassifier):
        def facts(self, text, answers):
            raise RuntimeError("model offline")

    tariff = UkTradeTariff(
        "https://tariff.test/uk/api", http=httpx.Client(transport=httpx.MockTransport(official))
    )
    out = CommodityAssistant(tariff, Broken()).suggest("jeans")
    assert out.state == "manual" and "by hand" in out.message


def test_codes_are_strings_with_their_leading_zeros(helper, official):
    official.extra["0101210000"] = {"data": {"type": "commodity", "attributes": {
        "goods_nomenclature_item_id": "0101210000", "description": "Pure-bred breeding animals",
        "declarable": True, "validity_end_date": None}}, "included": []}  # fmt: skip
    entry = helper.check("0101210000")
    assert entry is not None and entry.code == "0101210000"
    assert spaced("0101210000") == "0101 21 00 00"
    assert helper.check("6203999999") is None  # not in the tariff


# ------------------------------------------------- confirming, through the one path


@pytest.fixture
def svc(store, provider, clock, helper):
    shopify = FakeShopify()
    service = ShippingService(
        store,
        shopify,
        provider,
        Purchases(store, provider, clock=clock),
        clock=clock,
        commodity=helper,
    )
    shopify.add(fo(2145, [tee_line()]))
    service.sync(SHOP)
    return service


def customs_question(s):
    return next((q for q in s.questions if q.kind == "customs"), None)


def asked(s):
    q = customs_question(s)
    assert q is not None, "the customs question should be asked"
    return q


def test_a_suggestion_is_not_a_fact_until_confirmed(svc):
    (s,) = svc.store.shipments(SHOP)
    q = asked(s)
    assert q is not None
    out = svc.commodity.suggest("Express Tee cotton T-Shirt", {})
    assert out.code == "6109100010"
    s = svc.store.get(SHOP, s.id)
    assert customs_question(s) is not None  # still asked: nothing was saved
    assert svc.store.fact(SHOP, "product", q.subject, "hs_code") is None


def test_confirming_saves_through_the_product_facts_path_and_is_reused(svc):
    (s,) = svc.store.shipments(SHOP)
    q = asked(s)
    found = svc.commodity.suggest("cotton T-Shirt", {})
    given = {
        "method": "suggested",
        "code": found.code,
        "inputs": found.inputs,
        "reasons": found.reasons,
    }
    svc.answer(
        SHOP,
        s.id,
        "customs",
        q.subject,
        {"hs_code": found.code, "description": "Cotton T-shirt", "classification": given},
        "Sam",
    )
    assert svc.store.fact(SHOP, "product", q.subject, "hs_code") == "6109100010"
    evidence = json.loads(svc.store.fact(SHOP, "product", q.subject, "hs_classification"))
    assert evidence["verified"] and evidence["method"] == "suggested, then confirmed"
    assert "T-shirts" in evidence["official_description"] and evidence["confirmed_by"] == "Sam"
    assert evidence["source"].endswith("/commodities/6109100010")
    assert any(w[2] == "6109100010" for w in svc.shopify.writes)  # in Shopify too
    # The next order of the same product isn't asked again.
    svc.shopify.add(fo(2146, [tee_line(n=7)]))
    svc.sync(SHOP)
    nxt = next(x for x in svc.store.shipments(SHOP) if x.order_name == "CROOKS-2146")
    assert customs_question(nxt) is None


def test_a_code_the_tariff_does_not_have_is_refused(svc):
    (s,) = svc.store.shipments(SHOP)
    q = asked(s)
    with pytest.raises(ActionError) as caught:
        svc.answer(
            SHOP,
            s.id,
            "customs",
            q.subject,
            {"hs_code": "6203999999", "description": "Shorts"},
            "Sam",
        )
    assert caught.value.status == 422 and "isn't a current UK commodity code" in str(caught.value)
    assert svc.store.fact(SHOP, "product", q.subject, "hs_code") is None


def test_typing_a_code_still_works_when_the_tariff_is_down(svc, official):
    (s,) = svc.store.shipments(SHOP)
    q = asked(s)
    official.down = True
    svc.answer(
        SHOP,
        s.id,
        "customs",
        q.subject,
        {"hs_code": "610910", "description": "Cotton T-shirt"},
        "Sam",
    )
    svc.answer(
        SHOP,
        s.id,
        "customs",
        q.subject,
        {"hs_code": "6109100010", "description": "Cotton T-shirt"},
        "Sam",
    )
    evidence = json.loads(svc.store.fact(SHOP, "product", q.subject, "hs_classification"))
    assert evidence["verified"] is False and "couldn't be reached" in evidence["note"]
    assert svc.store.fact(SHOP, "product", q.subject, "hs_code") == "6109100010"


def test_a_suggestion_edited_by_hand_is_recorded_as_manual(svc):
    (s,) = svc.store.shipments(SHOP)
    q = asked(s)
    given = {"method": "suggested", "code": "6109100010", "inputs": {}, "reasons": []}
    svc.answer(
        SHOP,
        s.id,
        "customs",
        q.subject,
        {"hs_code": "6109902000", "description": "Polyester T-shirt", "classification": given},
        "Sam",
    )
    evidence = json.loads(svc.store.fact(SHOP, "product", q.subject, "hs_classification"))
    assert evidence["method"] == "manual"  # the code saved is not the one suggested


def test_no_lookup_configured_means_manual_entry_as_before(store, provider, clock):
    shopify = FakeShopify()
    service = ShippingService(
        store, shopify, provider, Purchases(store, provider, clock=clock), clock=clock
    )
    shopify.add(fo(2147, [tee_line()]))
    service.sync(SHOP)
    (s,) = service.store.shipments(SHOP)
    q = asked(s)
    service.answer(
        SHOP, s.id, "customs", q.subject, {"hs_code": "6203999999", "description": "Shorts"}, "Sam"
    )
    assert service.store.fact(SHOP, "product", q.subject, "hs_code") == "6203999999"


def test_unavailable_is_an_error_type_of_its_own():
    assert issubclass(TariffUnavailable, Exception) and not issubclass(
        TariffUnavailable, ActionError
    )


def test_the_admin_endpoint_uses_what_shopify_already_says(svc):
    from fastapi.testclient import TestClient

    from shipping.app import create_app
    from shipping.settings import Settings

    (s,) = svc.store.shipments(SHOP)
    q = asked(s)
    cfg = Settings(shop_domain=SHOP, provider="fake", dev_skip_admin_auth=True, tick_interval_s=0)
    with TestClient(create_app(cfg, svc)) as c:
        # "cotton" is the merchant's word; "T-Shirt" comes from the product's type in Shopify.
        r = c.post(
            "/admin/api/commodity/suggest",
            json={"text": "cotton", "sid": s.id, "subject": q.subject},
        )
        body = r.json()
        assert body["state"] == "candidate" and body["candidate"]["code"] == "6109100010"
        assert body["candidate"]["spaced"] == "6109 10 00 10" and body["candidate"]["path"]
        empty = c.post("/admin/api/commodity/suggest", json={"text": "a thing"}).json()
        assert empty["state"] == "manual"
