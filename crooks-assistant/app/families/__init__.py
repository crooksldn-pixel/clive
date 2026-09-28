"""The Phase 3 capability families, each in its own module, all loaded here.

A family is one thing the shop can do — edit an order's lines, create a discount code, read
the abandoned checkouts, compose to any address — and everything that goes with it: its tools
(`@tool`, into the registry), its commands (`app.commands.register`), the recipes its taps
name (`app.recipes.register`) and its capability state (`app.capabilities.families.register`). Each module registers its own on
import; this package imports every module it contains, so adding a family is adding a file,
and two families never edit the same line of a shared table.

Nothing here is a second mutation system. A family's writes are `WriteSpec`s through the one
action engine, gated by the one write boundary, verified by the one re-read rule.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

log = logging.getLogger("crooks.families")

_loaded: list[str] = []


def load_all() -> list[str]:
    """Import every family module once. Idempotent; a family that fails to import is logged
    by name and does not take the others with it — a broken discount module must not cost the
    shop its order editing."""
    if _loaded:
        return list(_loaded)
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if info.name.startswith("_"):
            continue
        try:
            importlib.import_module(f"{__name__}.{info.name}")
            _loaded.append(info.name)
        except Exception as exc:  # noqa: BLE001 — one family must not take the rest down
            log.error("family %s failed to load: %s: %s", info.name, type(exc).__name__, exc)
    return list(_loaded)


def loaded() -> list[str]:
    return list(_loaded)
