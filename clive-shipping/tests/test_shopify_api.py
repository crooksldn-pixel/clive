"""The Admin API version is pinned, and every GraphQL document is listed for validation
(scripts/validate_graphql.py checks each against that version's schema)."""

from shipping import shopify


def test_admin_api_version_is_pinned():
    assert shopify.API_VERSION == "2026-10"
    client = shopify.GraphQLShopify("crooks.myshopify.com", "id", "secret")
    assert client.api_version == "2026-10"


def test_every_graphql_document_is_listed_for_validation():
    sent = {
        name
        for name, value in vars(shopify).items()
        if name[:2] in ("Q_", "M_") and isinstance(value, str)
    }
    assert sent == set(shopify.DOCUMENTS)
