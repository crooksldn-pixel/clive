"""M13's rule is that logs contain no personal data. This is how that stays true."""

from __future__ import annotations

import json

import pytest

from app.logging.turnlog import TurnLog, redact, redact_text


def test_emails_are_redacted():
    assert "jo@example.com" not in redact_text("write to jo@example.com today")


def test_uk_postcodes_are_redacted():
    assert "SW1A 1AA" not in redact_text("ships to SW1A 1AA")
    assert "E8 3RL" not in redact_text("address is E8 3RL")


def test_phone_numbers_are_redacted():
    assert "07700 900123" not in redact_text("call 07700 900123")
    assert "+44 7700 900123" not in redact_text("call +44 7700 900123")


def test_card_numbers_are_redacted():
    assert "4111 1111 1111 1111" not in redact_text("card 4111 1111 1111 1111")


def test_address_keys_are_redacted_whatever_the_value():
    out = redact({"shippingAddress": {"street": "12 Rivington St"}, "city": "London"})
    assert out["shippingAddress"] == "[redacted]"
    assert out["city"] == "London", "non-identifying fields should survive"


def test_message_bodies_are_redacted():
    assert redact({"body": "anything at all"})["body"] == "[redacted]"


def test_empty_values_are_not_replaced_with_the_marker():
    assert redact({"phone": None})["phone"] is None


def test_nested_structures_are_walked():
    out = redact({"threads": [{"from_email": "a@b.com", "subject": "hi jo@example.com"}]})
    assert out["threads"][0]["from_email"] == "[redacted]"
    assert "jo@example.com" not in out["threads"][0]["subject"]


def test_order_numbers_survive_redaction():
    """Over-redacting is a real risk: an order number must still be readable in the log."""
    assert "4832" in redact_text("found order 4832")


def test_written_log_line_contains_no_personal_data(tmp_path):
    TurnLog(tmp_path).write(
        {
            "text": "email jo@example.com about order 4832",
            "result": {"shippingAddress": {"street": "12 Rivington St"}, "phone": "07700900123"},
        }
    )
    written = (tmp_path / "turns.jsonl").read_text()
    for leak in ("jo@example.com", "Rivington", "07700900123"):
        assert leak not in written, f"{leak!r} reached the log file"
    assert json.loads(written)["text"].startswith("email [email]")


# --- the review's findings: ids must survive, stdlib logging must be covered ----------

def test_shopify_gids_and_proposal_ids_survive_redaction():
    text = "order gid://shopify/Order/1000000000013 staged prop_2593c23364af for jo@x.com"
    out = redact_text(text)
    assert "gid://shopify/Order/1000000000013" in out
    assert "prop_2593c23364af" in out
    assert "jo@x.com" not in out


def test_customer_name_keys_are_redacted_but_order_name_survives():
    out = redact({"name": "CROOKS-1928", "customer_name": "Anna Dummy", "from": "Anna <a@b.com>"})
    assert out["name"] == "CROOKS-1928"
    assert out["customer_name"] == "[redacted]"
    assert out["from"] == "[redacted]"


def test_redacting_filter_covers_stdlib_logging(caplog):
    import logging

    from app.logging.turnlog import RedactingFilter

    logger = logging.getLogger("crooks.test.filter")
    logger.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO, logger="crooks.test.filter"):
        logger.info("transcript: email me at %s or call %s", "jo@example.com", "07700 900123")
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "jo@example.com" not in joined and "07700 900123" not in joined
    assert "[email]" in joined and "[phone]" in joined


# --- the completed review: free-text answers, and over-redaction ------------

def test_known_names_are_scrubbed_from_free_text():
    out = redact_text("CROOKS-1928 was placed by Jane Smith. She has moved.", names=["Jane Smith"])
    assert "Jane Smith" not in out and "[name]" in out and "CROOKS-1928" in out


@pytest.mark.parametrize(
    "text",
    ["[Errno -1094995529] Invalid data", "saved 20260907-225520.webm", "SS24 2XL sold out", "gid://shopify/Order/1000000000013"],
)
def test_identifiers_and_size_codes_are_not_mangled(text):
    assert redact_text(text) == text


def test_real_postcode_still_redacted_after_size_exclusion():
    assert "[postcode]" in redact_text("send to SW1A 1AA")
    assert "[postcode]" in redact_text("E8 3RL please")


def test_turn_log_scrubs_names_the_tools_returned(tmp_path):
    TurnLog(tmp_path).write(
        {"answer": "Order CROOKS-1928 is Anna Dummy's, shipped yesterday.", "question": "whose is 1928"},
        names={"Anna Dummy"},
    )
    written = (tmp_path / "turns.jsonl").read_text()
    assert "Anna Dummy" not in written and "CROOKS-1928" in written
