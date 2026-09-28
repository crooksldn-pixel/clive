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
