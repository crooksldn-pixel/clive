"""The label purchase over HTTP (GraphQLShopify), against a fake Shopify transport: sent once,
whatever happens, and every answer sorted into not sent / refused / may have bought."""

from __future__ import annotations

import json

import httpx
import pytest

from shipping.shopify import (
    M_SHIPPING_LABEL_PURCHASE,
    GraphQLShopify,
    ShopifyError,
    ShopifyNotSent,
    ShopifyRefused,
)

SHOP = "crooks.myshopify.com"
PURCHASE = {"fulfillmentOrderId": "gid://shopify/FulfillmentOrder/1"}
OK = {
    "data": {
        "shippingLabelPurchase": {
            "shippingLabelPurchaseResult": {
                "id": "gid://shopify/ShippingLabelPurchaseResult/1",
                "status": "PENDING_PURCHASE",
                "done": False,
            },
            "userErrors": [],
        }
    }
}


class FakeShopifyHttp:
    """Answers the token endpoint, and the GraphQL endpoint with `answer` (a response or an
    exception). Counts every GraphQL POST: the mutation must arrive exactly once."""

    def __init__(self, answer) -> None:
        self.answer = answer
        self.graphql: list[dict] = []
        self.gets: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/admin/oauth/access_token":
            return httpx.Response(200, json={"access_token": "shpat_test", "expires_in": 3600})
        if request.method == "GET":
            self.gets.append(request)
            return httpx.Response(
                200, content=b"%PDF-1.4 label", headers={"content-type": "application/pdf"}
            )
        self.graphql.append(json.loads(request.content))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def client(answer) -> tuple[GraphQLShopify, FakeShopifyHttp]:
    fake = FakeShopifyHttp(answer)
    return GraphQLShopify(
        SHOP, "id", "secret", http=httpx.Client(transport=httpx.MockTransport(fake))
    ), fake


def test_the_mutation_is_sent_with_the_purchase_and_its_result_returned():
    gql, fake = client(httpx.Response(200, json=OK))
    payload = gql.purchase_label(PURCHASE)
    assert payload["shippingLabelPurchaseResult"]["status"] == "PENDING_PURCHASE"
    (sent,) = fake.graphql
    assert sent["query"] == M_SHIPPING_LABEL_PURCHASE
    assert sent["variables"] == {"input": PURCHASE}


def test_user_errors_come_back_as_the_payload():
    refusal = [{"field": None, "code": "RATES_NOT_FOUND", "message": "x"}]
    body = {"data": {"shippingLabelPurchase": {"shippingLabelPurchaseResult": None,
                                               "userErrors": refusal}}}  # fmt: skip
    gql, fake = client(httpx.Response(200, json=body))
    assert gql.purchase_label(PURCHASE)["userErrors"][0]["code"] == "RATES_NOT_FOUND"
    assert len(fake.graphql) == 1


@pytest.mark.parametrize(
    ("answer", "kind"),
    [
        # Never reached Shopify, or turned away before acting: not done.
        (httpx.ConnectError("refused"), ShopifyNotSent),
        (httpx.ConnectTimeout("slow connect"), ShopifyNotSent),
        (httpx.Response(429, json={"errors": "Throttled"}), ShopifyNotSent),
        (
            httpx.Response(
                200,
                json={"errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}]},
            ),
            ShopifyNotSent,
        ),
        # Shopify said no: not done.
        (httpx.Response(403, text="Forbidden"), ShopifyRefused),
        (
            httpx.Response(
                200,
                json={
                    "data": {"shippingLabelPurchase": None},
                    "errors": [
                        {"message": "Access denied", "extensions": {"code": "ACCESS_DENIED"}}
                    ],
                },
            ),
            ShopifyRefused,
        ),
        # Sent, and the answer is lost or unreadable: may have bought.
        (httpx.ReadTimeout("no answer"), ShopifyError),
        (httpx.RemoteProtocolError("reset"), ShopifyError),
        (httpx.Response(502, text="Bad gateway"), ShopifyError),
        (httpx.Response(200, text="<html>oops</html>"), ShopifyError),
        (httpx.Response(200, json={"data": {}}), ShopifyError),
    ],
)
def test_every_outcome_is_sorted_and_nothing_is_ever_sent_twice(answer, kind):
    gql, fake = client(answer)
    with pytest.raises(kind) as caught:
        gql.purchase_label(PURCHASE)
    if kind is ShopifyError:  # "may have bought" is never mistaken for a definite answer
        assert not isinstance(caught.value, (ShopifyNotSent, ShopifyRefused))
    assert len(fake.graphql) == 1


def test_documents_are_fetched_over_https_without_the_apps_token():
    gql, fake = client(httpx.Response(200, json=OK))
    kind, body = gql.download("https://shipping.shopify.test/labels/1.pdf")
    assert kind == "application/pdf" and body.startswith(b"%PDF")
    (got,) = fake.gets
    assert "x-shopify-access-token" not in {k.lower() for k in got.headers}
    with pytest.raises(ShopifyError):
        gql.download("http://shipping.shopify.test/labels/1.pdf")
