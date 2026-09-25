"""The capability manifest: the Mac's own account of itself.

Generated, never written by hand. Every entry comes from a registry that the running system
actually consults, so the manifest cannot drift from the truth the way a paragraph in a
system prompt does. Claude is told what it can do from this; it is never asked to guess.

Semantic tags, as the brief names them: READS, WRITES, BATCH ACTIONS, QUERY DIMENSIONS,
SUPPORTED ENTITY TYPES, UI COMPONENTS, AVAILABLE DATA SOURCES, ACTION RISK TYPES.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

SCHEMA_VERSION = 3

# What a tool is for, in the owner's words rather than the registry's. Keyed by prefix, so a
# tool added to a family inherits its description without a new line here.
_FAMILY = {
    "shopify_": ("shopify", "the shop"),
    "gmail_": ("gmail", "the inbox"),
    "commerce_": ("shopify", "the read layer"),
    "inventory_": ("shopify", "the read layer"),
    "email_": ("gmail", "the read layer"),
    "batch_": ("mac", "bulk changes"),
}


def _source_of(name: str) -> tuple[str, str]:
    for prefix, pair in _FAMILY.items():
        if name.startswith(prefix):
            return pair
    return ("mac", "the assistant")


def build(*, build_id: str = "", writes_enabled: bool = True) -> dict[str, Any]:
    """The manifest as it stands in this process."""
    from app.analytics import periods, query
    from app.presentation import UI_TYPES
    from app.tools import registry
    from app.tools.gate import Tier

    reads: list[dict[str, Any]] = []
    writes: list[dict[str, Any]] = []
    batches: list[dict[str, Any]] = []
    for spec in registry.all_specs():
        if spec.name.startswith("mock_"):
            continue
        source, area = _source_of(spec.name)
        entry = {"name": spec.name, "source": source, "area": area, "tier": spec.tier.value,
                 "what": spec.description.split(".")[0].strip()[:180]}
        if spec.batch is not None:
            batches.append({**entry, "operation": spec.batch.operation, "child_tool": spec.batch.child_tool,
                            "set_kinds": list(spec.batch.set_kinds), "max_members": spec.batch.max_members,
                            "verb": spec.batch.verb, "noun": spec.batch.noun})
        elif spec.write is not None:
            writes.append({**entry, "operation": spec.write.operation, "entity_kind": spec.write.entity_kind,
                           "risk": spec.write.kind, "reversible": bool(spec.write.reversible),
                           "gesture": spec.write.interaction, "mutation": spec.write.mutation})
        elif spec.tier is not Tier.RED:
            reads.append(entry)

    manifest: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "build": build_id or "",
        "writes_enabled": bool(writes_enabled),
        "reads": sorted(reads, key=lambda e: e["name"]),
        "writes": sorted(writes, key=lambda e: e["name"]) if writes_enabled else [],
        "batches": sorted(batches, key=lambda e: e["name"]) if writes_enabled else [],
        "query_dimensions": {
            "entities": list(query.ENTITIES),
            "group_by": list(query.GROUPS),
            "metrics": list(query.METRICS),
            "filters": sorted(query.FILTERS),
            # The other names that resolve to those filters, and the keys a listing can be
            # sorted by. Both are part of what the language ACCEPTS, so both belong in the
            # account it gives of itself: a name nothing publishes is a name that gets
            # guessed, and a guessed name costs a turn.
            "filter_aliases": sorted(query.ALIASES),
            "sort_keys": sorted(set(query.LISTING_SORT_KEYS) | set(query.SORT_WORDS)),
            "views": list(query.VIEWS),
            "periods": list(periods.NAMED) + ["{days: N}", "{start, end}"],
            "compare": True,
            "max_limit": query.MAX_LIMIT,
        },
        "entity_types": ["order", "customer", "product", "variant", "email_thread", "working_set"],
        "ui_components": sorted(UI_TYPES),
        "data_sources": [
            {"name": "shopify", "what": "orders, customers, products, inventory", "api": "Admin GraphQL 2025-07"},
            {"name": "gmail", "what": "the shop's inbox: threads, senders, drafts", "api": "Gmail v1"},
            {"name": "mac", "what": "the order cache, working sets, the action ledger", "api": "local"},
        ],
        "risk_types": ["reversible", "irreversible", "money"],
        "gestures": ["tap_commit", "swipe_commit", "hold_to_arm", "hold_drag_target"],
        # The capability families and their static state. The live state — scope granted,
        # store supports it, provider connected — is /health's; this says what is BUILT.
        "families": [
            {"key": f.key, "label": f.label, "area": f.area, "what": f.what, "state": f.state,
             "operations": list(f.operations), "tools": list(f.tools), "scopes": list(f.scopes)}
            for f in _families()
        ],
    }
    manifest["fingerprint"] = fingerprint(manifest)
    manifest["counts"] = {"reads": len(manifest["reads"]), "writes": len(manifest["writes"]), "batches": len(manifest["batches"])}
    return manifest


def _families() -> list[Any]:
    from app.capabilities import families

    return families.all_families()


def fingerprint(manifest: dict[str, Any]) -> str:
    """What changed between two builds, reduced to sixteen characters. Deliberately blind to
    the build id and to prose: a reworded description is not a new capability."""
    shape = {
        "reads": sorted(e["name"] for e in manifest.get("reads", [])),
        "writes": sorted((e["name"], e.get("risk"), e.get("gesture")) for e in manifest.get("writes", [])),
        "batches": sorted((e["name"], e.get("child_tool"), tuple(e.get("set_kinds") or ())) for e in manifest.get("batches", [])),
        "query": {k: v for k, v in sorted((manifest.get("query_dimensions") or {}).items())},
        "ui": sorted(manifest.get("ui_components", [])),
        "entities": sorted(manifest.get("entity_types", [])),
        "families": sorted((f["key"], f.get("state")) for f in manifest.get("families", [])),
    }
    blob = json.dumps(shape, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# The families a person asks about, and the tools that serve them. Used for the spoken
# summary so the answer is grouped the way the owner thinks rather than tool by tool.
_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("look up orders and customers", ("shopify_find_order", "shopify_order_detail", "shopify_find_customer", "shopify_customer_history")),
    ("answer questions about sales", ("commerce_aggregate", "commerce_query")),
    ("check stock and what is running out", ("inventory_query", "shopify_inventory", "shopify_product_info")),
    ("read and search the inbox", ("gmail_search", "gmail_read_thread", "email_query")),
)


def spoken_summary(manifest: dict[str, Any], *, limit: int = 6) -> str:
    """"What can you do?", answered from the manifest in one breath. No tool names: the owner
    asked what the assistant can do, not what it is made of."""
    names = {e["name"] for e in manifest.get("reads", [])}
    lines = [what for what, tools in _GROUPS if names.intersection(tools)]
    writes = manifest.get("writes") or []
    batches = manifest.get("batches") or []
    if writes:
        kinds = sorted({e.get("entity_kind", "") for e in writes if e.get("entity_kind")})
        lines.append("change things in the shop and the inbox — " + ", ".join(kinds[:4]) + " — each one staged for you to apply with a gesture")
    if batches:
        lines.append(f"apply {len(batches)} kinds of bulk change to a whole set at once")
    if not writes:
        lines.append("read only, at the moment: changes are switched off")
    head = "I can " + "; ".join(lines[:limit]) + "."
    dims = manifest.get("query_dimensions") or {}
    if dims.get("group_by"):
        head += f" Sales questions can be grouped {len(dims['group_by'])} ways and compared against the period before."
    return head
