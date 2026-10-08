"""Internal reads: things CLIVE can look up that are not model-facing tools.

A closed table of named async functions, read-only by construction: nothing is dispatched by
name from outside this module, and a name the table does not hold is a skipped prediction rather
than an import (app/anticipation/engine.py refuses it).

The table is empty. Its one entry was the shipping context, read from the old Easyship boundary
(app/shipping) for §18's "shipping/tracking context available internally"; that boundary was
deleted on the owner's ruling of 8 October (DEC-071, ruling 24), now CLIVE Shipping carries
labels and tracking as tools of its own (app/tools/shipping_tools.py). The table stays so that an
internal read, if one is ever needed, has one closed place to be added and the engine's refusal
of anything else is still tested.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger("crooks.anticipation")


READS: dict[str, Callable[[dict[str, Any]], Awaitable[Any]]] = {}


def known(name: str) -> bool:
    return name in READS


async def run(name: str, args: dict[str, Any]) -> Any:
    """One internal read, or None when there is no such read."""
    handler = READS.get(name)
    if handler is None:
        log.debug("no internal read called %s", name)
        return None
    return await handler(dict(args or {}))
