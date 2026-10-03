import hashlib
import hmac
import time

from returns import verify
from returns.api import proxy_signature_ok
from returns.fake import sample_orders

from .conftest import NOW


def test_any_one_proof_is_enough():
    order = sample_orders(NOW)[0]
    for proof in (
        "Customer@Example.com ",
        "e16an",
        "E1 6AN",
        "07700 900123",
        "+44 7700 900123",
        "00447700900123",
    ):
        assert verify.proof_matches(order, proof), proof
    for proof in ("", "someone@example.com", "E1 6AB", "07700 900124", "1234"):
        assert not verify.proof_matches(order, proof), proof


def test_order_numbers_normalise():
    assert verify.normalise_order_number("#1939") == "1939"
    assert verify.normalise_order_number(" crooks 1939 ") == "1939"
    assert verify.normalise_order_number("no digits") is None


def test_rate_limit_window():
    rl = verify.RateLimiter(limit=2, window_s=60)
    rl.hit("k", now=0)
    rl.hit("k", now=1)
    assert rl.blocked("k", now=2)
    assert not rl.blocked("k", now=62)


def test_sessions_are_signed_and_expire():
    token = verify.session_for("gid://shopify/Order/1", "s", ttl_s=60)
    assert verify.order_from_session(token, "s") == "gid://shopify/Order/1"
    assert verify.order_from_session(token, "other") is None
    body, mac = token.split(".")
    assert verify.order_from_session(body[:-2] + "xx." + mac, "s") is None
    assert verify.unsign(token, "s", now=time.time() + 120) is None


def test_app_proxy_signature():
    params = [
        ("shop", "5wn03t-nm.myshopify.com"),
        ("path_prefix", "/apps/returns"),
        ("timestamp", "1317327555"),
        ("extra", "1"),
        ("extra", "2"),
    ]
    message = "extra=1,2path_prefix=/apps/returnsshop=5wn03t-nm.myshopify.comtimestamp=1317327555"
    sig = hmac.new(b"secret", message.encode(), hashlib.sha256).hexdigest()
    assert proxy_signature_ok([*params, ("signature", sig)], "secret")
    assert not proxy_signature_ok([*params, ("signature", sig)], "wrong")
    assert not proxy_signature_ok(params, "secret")
