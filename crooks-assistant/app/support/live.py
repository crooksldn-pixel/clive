"""The live readers: the application's own read-only tools, already bound at startup.

Four functions answer the evidence bundle's four questions, and each is a read the assistant
already makes for the order card: the order search, the hydrated order (history and inbox
included when they arrive in time), the inbox correlation, and one thread. Nothing here can
write; the tools these call are the GREEN and AMBER reads, and the write tools live in other
modules this one never imports. A store or inbox that is not configured is reported by the
tools as a `ToolError` or an `available: False` answer, which the gatherer records as a
named problem in the bundle rather than a crash.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.tools import gmail_tools, shopify_tools
from config.settings import Settings, get_settings

# How long the hydrated order waits for the customer's history and inbox correlation. A
# support investigation is not a spoken turn: a few seconds for the full picture is right.
ORDER_BUDGET_S = 6.0
SEARCH_LIMIT = 5


async def find_order(query: str) -> dict[str, Any]:
    return await shopify_tools.shopify_find_order(query, limit=SEARCH_LIMIT)


async def order_detail(order_id: str) -> dict[str, Any]:
    return await shopify_tools.hydrator().order(str(order_id), budget_s=ORDER_BUDGET_S)


async def threads_for(**kwargs: Any) -> dict[str, Any]:
    return await gmail_tools.threads_for(**kwargs)


async def read_thread(thread_id: str) -> dict[str, Any]:
    return await gmail_tools.gmail_read_thread(str(thread_id))


def readers(settings: Settings | None = None, *, kb_dir: Path | None = None) -> dict[str, Any]:
    """The keyword arguments `app.support.evidence.gather` takes, bound to the live tools."""
    settings = settings or get_settings()
    return {
        "find_order": find_order,
        "order_detail": order_detail,
        "threads_for": threads_for,
        "read_thread": read_thread,
        "kb_dir": Path(kb_dir) if kb_dir is not None else settings.kb_dir,
    }
