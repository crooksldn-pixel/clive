"""Safe quote diagnostics keep fallback providers purchasable."""

import json

import httpx
import pytest

from shipping import views
from shipping.models import ShipmentStatus

from . import test_easyship as easy
from .conftest import SHOP

es_server = easy.es_server
es = easy.es
p2g_fake = easy.p2g_fake
shopify = easy.shopify
svc = easy.svc


@pytest.mark.parametrize(
    ("detail", "category", "field"),
    [
        ("destination_address.city is invalid", "address_validation", "destination.city"),
        ("parcels.items.hs_code invalid", "customs_validation", "lines.hs_code"),
        ("contact_phone invalid", "contact_validation", "contact.phone"),
        ("total_actual_weight invalid", "package_validation", "package.total_weight_g"),
        ("courier_service_id invalid", "service_validation", "service"),
    ],
)
def test_order_specific_failures_keep_fallback(svc, shopify, es_server, detail, category, field):
    es_server.faults["rates"] = httpx.Response(
        422, json={"error": {"message": "Invalid content", "details": [detail]}}
    )
    s = easy.guernsey_order(svc, shopify)
    assert s.status == ShipmentStatus.ready and s.quote.provider == "Parcel2Go"
    f = s.provider_failures[0]
    assert f.provider == "Easyship" and f.category == category and f.fields == [field]
    assert f.actionable and not f.retryable
    output = views.detail(s, svc.recommendation(s), [])["shipping"]
    assert output["provider_failures"][0]["safe_message"] == f.safe_message
    assert "Parcel2Go rates are shown instead" in output["note"]
    assert svc.store.get(SHOP, s.id).provider_failures == s.provider_failures
    # Quote fallback remains eligible for preview and the existing purchase safeguards.
    assert svc.preview(SHOP, s.id)["service"]


@pytest.mark.parametrize(
    ("fault", "category"),
    [
        ("timeout", "timeout"),
        (httpx.Response(503), "server_error"),
        (httpx.Response(429), "rate_limit"),
    ],
)
def test_temporary_failures(svc, shopify, es_server, fault, category):
    es_server.faults["rates"] = fault
    s = easy.guernsey_order(svc, shopify)
    f = s.provider_failures[0]
    assert s.status == ShipmentStatus.ready and f.retryable and not f.actionable
    assert f.category == category
    assert "just now" in f.safe_message or "temporarily" in f.safe_message


def test_auth_and_untrusted_body_never_leak(svc, shopify, es_server):
    secret = "SECRET-TOKEN-SENTINEL"
    es_server.faults["rates"] = httpx.Response(401, text=secret)
    s = easy.guernsey_order(svc, shopify)
    output = json.dumps(views.detail(s, svc.recommendation(s), []))
    assert secret not in output
    assert s.provider_failures[0].category == "auth"
    assert "connection needs attention" in output
    es_server.faults["rates"] = httpx.Response(
        422, json={"error": {"message": secret, "details": ["hs_code invalid " + secret]}}
    )
    s = svc.prepare(SHOP, s.id)
    assert secret not in json.dumps(views.detail(s, svc.recommendation(s), []))
    assert s.provider_failures[0].fields == ["lines.hs_code"]


def test_both_fail_safe_overall_attention(svc, shopify, es_server, p2g_fake, monkeypatch):
    from shipping.providers.base import ProviderUnavailable

    def down(shipment):
        raise ProviderUnavailable("SECRET-RAW-BODY")

    monkeypatch.setattr(p2g_fake, "quotes", down)
    es_server.faults["rates"] = httpx.Response(401, text="SECRET-RAW-BODY")
    s = easy.guernsey_order(svc, shopify)
    assert s.status == ShipmentStatus.needs_attention
    assert s.questions[0].kind == "provider_unavailable"
    assert len(s.provider_failures) == 2
    assert "SECRET-RAW-BODY" not in s.model_dump_json()


def test_failure_clears_when_provider_recovers(svc, shopify, es_server):
    es_server.faults["rates"] = "timeout"
    s = easy.guernsey_order(svc, shopify)
    assert s.provider_failures
    s = svc.prepare(SHOP, s.id)
    assert not s.provider_failures and not s.rates_unavailable


@pytest.mark.parametrize("recovery", ["prepare", "refresh", "tick"])
def test_current_attempt_recovery_and_recommendation(
    svc, shopify, es_server, p2g_fake, monkeypatch, recovery
):
    from unittest.mock import Mock

    from fastapi.testclient import TestClient

    from shipping.app import create_app
    from shipping.settings import Settings

    from .fake_easyship import service

    es_server.services = [service("rm48", "Royal Mail", "Domestic Tracked 48 Small Parcel", 3.01)]
    es_server.faults["rates"] = "timeout"
    s = easy.guernsey_order(svc, shopify)
    assert s.provider_failures[0].retryable and s.provider_failures[0].occurred_at
    assert svc.recommendation(s).recommended.quote.provider == "Parcel2Go"
    assert s.quote.amount.minor == 1651
    p2g = Mock(wraps=p2g_fake.quotes)
    es = Mock(wraps=svc.provider.by_name("Easyship").quotes)
    monkeypatch.setattr(p2g_fake, "quotes", p2g)
    monkeypatch.setattr(svc.provider.by_name("Easyship"), "quotes", es)
    if recovery == "prepare":
        svc.prepare(SHOP, s.id)
    elif recovery == "tick":
        svc.tick(SHOP)
    else:
        cfg = Settings(
            shop_domain=SHOP, provider="fake", dev_skip_admin_auth=True, tick_interval_s=0
        )
        with TestClient(create_app(cfg, svc)) as client:
            response = client.post(f"/admin/api/shipments/{s.id}/refresh")
            assert response.status_code == 200
            assert response.json()["shipping"]["provider_failures"] == []
    assert p2g.call_count == 1 and es.call_count == 1
    s = svc.store.get(SHOP, s.id)
    assert not s.provider_failures and not s.rates_unavailable
    assert {q.provider for q in s.rates} == {"Easyship", "Parcel2Go"}
    assert svc.recommendation(s).recommended.quote.amount.minor == 301
    assert s.quote.provider == "Easyship" and s.quote.amount.minor == 301
    output = views.detail(s, svc.recommendation(s), [])
    assert output["shipping"]["note"] is None
    assert not output["shipping"]["provider_failures"]
    assert not es_server.charges and not p2g_fake.charges


def test_success_then_failure_replaces_rates(svc, shopify, es_server):
    s = easy.guernsey_order(svc, shopify)
    assert any(q.provider == "Easyship" for q in s.rates)
    es_server.faults["rates"] = "timeout"
    s = svc.prepare(SHOP, s.id)
    assert [q.provider for q in s.rates] == ["Parcel2Go"]
    assert s.provider_failures[0].retryable and s.status == ShipmentStatus.ready
    assert s.label is None and not svc.store._db.execute("SELECT * FROM provider_ops").fetchall()


def test_purchased_shipment_never_requotes_or_replaces_history(svc, shopify, monkeypatch):
    from .test_printing import bought

    s = bought(svc, shopify)
    svc.tick(SHOP)  # Finish existing post-purchase housekeeping before checking stability.
    before = svc.store.get(SHOP, s.id).model_dump(exclude={"version", "updated_at"})

    def forbidden(*args):
        raise AssertionError("Purchased shipment must not requote")

    for provider in svc.provider.providers:
        monkeypatch.setattr(provider, "quotes", forbidden)
    svc.prepare(SHOP, s.id)
    svc.tick(SHOP)
    assert svc.store.get(SHOP, s.id).model_dump(exclude={"version", "updated_at"}) == before


def test_quote_does_not_normalise_or_guess_address(es, store, provider, es_server):
    s = easy.make_shipment(store, provider)
    s.destination = easy.GG.model_copy(
        update={"city": "Guernsey", "line1": "24 Example Estate, Road, St Peter Port"}
    )
    original = s.destination.model_dump()
    assert es.quotes(s)
    body = es_server.bodies[-1][1]["destination_address"]
    assert body["city"] == "Guernsey" and body["line_1"] == original["line1"]
    assert s.destination.model_dump() == original


def test_unknown_refusal_has_no_invented_field_or_raw_text(svc, shopify, es_server):
    es_server.faults["rates"] = httpx.Response(422, text="PRIVATE-PAYLOAD unknown refusal")
    s = easy.guernsey_order(svc, shopify)
    assert s.provider_failures[0].category == "validation"
    assert s.provider_failures[0].fields == []
    assert "PRIVATE-PAYLOAD" not in s.model_dump_json()


def test_browser_script_recovery_and_edit_purchase_guards(svc, shopify, es_server, tmp_path):
    import shutil
    import subprocess
    from pathlib import Path

    from .fake_easyship import service

    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is needed for the UI runtime check")
    es_server.services = [service("rm48", "Royal Mail", "Domestic Tracked 48 Small Parcel", 3.01)]
    es_server.faults["rates"] = "timeout"
    s = easy.guernsey_order(svc, shopify)
    before = views.detail(s, svc.recommendation(s), [])
    s = svc.prepare(SHOP, s.id)
    after = views.detail(s, svc.recommendation(s), [])
    data = tmp_path / "quotes.json"
    data.write_text(json.dumps([before, after]), encoding="utf-8")
    html = Path(__file__).parents[1] / "shipping/static/admin.html"
    runner = Path(__file__).with_name("quote_recovery_ui.cjs")
    result = subprocess.run(
        [node, str(runner), str(html), str(data)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
