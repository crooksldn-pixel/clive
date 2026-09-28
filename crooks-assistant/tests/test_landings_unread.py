"""A read that did not answer is not an empty list: the Orders landing, tapped, when a read fails.

The 2026-09-28 deploy review, round 9, E-06. The Orders landing makes two reads — the orders
still to go out, and today's — and `landings._orders_render` treated a failed first read as an
empty one: with the open-orders read down and today's answering, the owner was told "Nothing is
waiting to go out." That is a false answer to the one question the landing exists for. Driven
here through the real dock tap (`POST /command`, `open.area`), the real recipe and the real read
scheduler, with only the read itself made to fail.
"""

from __future__ import annotations

import pytest

from app.tools import registry
from app.tools.registry import ToolError
from experience.harness import harness


@pytest.fixture()
async def stage():
    async with harness(admitted=True) as h:
        yield h


def _failing(monkeypatch, *, periods: tuple[str, ...]) -> None:
    """The order reads for these periods raise, as a Shopify that did not answer does. Every
    other tool runs as it always does."""
    real = registry.invoke

    async def invoke(name, args, *, timeout_s):
        if name == "commerce_query" and str((args or {}).get("period") or "") in periods:
            raise ToolError("Shopify did not answer in time.")
        return await real(name, args, timeout_s=timeout_s)

    monkeypatch.setattr(registry, "invoke", invoke)


async def test_an_unread_open_orders_list_is_never_said_to_be_empty(stage, monkeypatch):
    _failing(monkeypatch, periods=("last_30_days",))
    tapped = await stage.touch("open.area", area="orders", session_id="unread1")
    assert tapped.raw.get("ok") is True, tapped.raw
    answer = tapped.answer
    assert "Nothing is waiting to go out" not in answer, answer
    assert "could not read the orders still to go out" in answer, answer
    assert "today" in answer.lower(), "the half that did answer is still said"
    assert (tapped.raw.get("changed") or {}).get("partial") is True, "and the answer is marked partial"


async def test_an_unread_today_is_not_none_in_today(stage, monkeypatch):
    _failing(monkeypatch, periods=("today",))
    tapped = await stage.touch("open.area", area="orders", session_id="unread2")
    assert tapped.raw.get("ok") is True, tapped.raw
    assert "None in today yet" not in tapped.answer, tapped.answer
    assert "Today's orders could not be read" in tapped.answer, tapped.answer
    assert (tapped.raw.get("changed") or {}).get("partial") is True


async def test_both_read_is_the_landing_it_always_was(stage):
    """The control: nothing failed, nothing is hedged."""
    tapped = await stage.touch("open.area", area="orders", session_id="unread3")
    assert tapped.raw.get("ok") is True, tapped.raw
    assert "could not" not in tapped.answer, tapped.answer
    assert (tapped.raw.get("changed") or {}).get("partial") is False


# ------------------------------------- the same rule on the Products and Inbox landings


def _failing_tools(monkeypatch, *names: str) -> None:
    """These read tools raise, as a source that did not answer does; every other runs."""
    real = registry.invoke

    async def invoke(name, args, *, timeout_s):
        if name in names:
            raise ToolError("The source did not answer in time.")
        return await real(name, args, timeout_s=timeout_s)

    monkeypatch.setattr(registry, "invoke", invoke)


async def test_unread_stock_is_never_said_to_be_nothing_running_out(stage, monkeypatch):
    """The Products landing had E-06's hole too: the stock read down, and the owner was told
    "Nothing is close to running out."."""
    _failing_tools(monkeypatch, "inventory_query")
    tapped = await stage.touch("open.area", area="products", session_id="unread4")
    assert tapped.raw.get("ok") is True, tapped.raw
    assert "Nothing is close to running out" not in tapped.answer, tapped.answer
    assert "could not read the stock levels" in tapped.answer, tapped.answer
    assert (tapped.raw.get("changed") or {}).get("partial") is True


async def test_unread_best_sellers_are_never_said_to_be_nothing_sold(stage, monkeypatch):
    _failing_tools(monkeypatch, "commerce_aggregate")
    tapped = await stage.touch("open.area", area="products", session_id="unread5")
    assert tapped.raw.get("ok") is True, tapped.raw
    assert "Nothing sold this month" not in tapped.answer, tapped.answer
    assert "could not read this month's best sellers" in tapped.answer, tapped.answer
    assert (tapped.raw.get("changed") or {}).get("partial") is True


async def test_an_unread_reply_queue_is_said_rather_than_left_out(stage, monkeypatch):
    """The Inbox landing with the needs-reply read down: the recent threads still come, and
    the answer says the queue was not read instead of letting them stand in for it."""
    _failing_tools(monkeypatch, "email_query")
    tapped = await stage.touch("open.area", area="email", session_id="unread6")
    assert tapped.raw.get("ok") is True, tapped.raw
    assert "could not read who is waiting on a reply" in tapped.answer, tapped.answer
    assert "Nobody is waiting" not in tapped.answer, tapped.answer
    assert (tapped.raw.get("changed") or {}).get("partial") is True
