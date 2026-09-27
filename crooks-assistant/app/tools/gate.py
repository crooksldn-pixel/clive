"""The permission gate.

classify() is a pure function over (tool name, arguments, ids issued this session). It is the
only thing standing between Claude and the outside world, so it is deliberately boring. A
decision has two parts, because risk and what-happens-next are different questions:

  risk         GREEN  a read within bounds
               AMBER  a read that surfaces a person's details (read it back), or a routine
                      reversible write
               RED    a write that is hard to undo, or anything refused

  disposition  EXECUTE_NOW      run the handler now
               STAGE_FOR_OWNER  do not run it: prepare the change and wait for the owner
                                to authorise it on the tablet (app/actions/engine.py)
               DENY             refuse; nothing is prepared and nothing can be authorised

Three rules make it fail closed. An unregistered tool is denied, so adding a tool without a
rule cannot grant access. Any tool whose name reads as a mutation is denied unless it is
registered with a complete write definition (app/tools/registry.py WriteSpec), so a write path
introduced by accident is blocked by its own name. And a write is only ever staged, never
executed here: the gate has no path from a tool call to a mutation.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Tier(StrEnum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


class Disposition(StrEnum):
    EXECUTE_NOW = "EXECUTE_NOW"
    STAGE_FOR_OWNER = "STAGE_FOR_OWNER"
    DENY = "DENY"


@dataclass(slots=True, frozen=True)
class Decision:
    tier: Tier
    reason: str
    disposition: Disposition = Disposition.DENY
    # True when the call was refused for something the model can put right by itself — an id
    # it has not looked up yet. Nothing is forbidden; it went about it the wrong way, and it
    # must not tell the owner it could not do this.
    recoverable: bool = False

    @property
    def allowed(self) -> bool:
        return self.disposition is not Disposition.DENY

    @property
    def executes(self) -> bool:
        return self.disposition is Disposition.EXECUTE_NOW

    @property
    def stages(self) -> bool:
        return self.disposition is Disposition.STAGE_FOR_OWNER


def deny(reason: str, *, recoverable: bool = False) -> Decision:
    return Decision(Tier.RED, reason, Disposition.DENY, recoverable=recoverable)


# Any verb that could change state anywhere is caught on sight, before the rule table is
# consulted. A name that matches is denied unless the registry holds a complete write
# definition for it (see _classify_write), and even then it is only ever staged for the owner:
# a write cannot be introduced by adding a rule, only by declaring one, and never executes here.
_MUTATION_VERBS = (
    "send", "create", "update", "delete", "modify", "write", "draft", "reply", "forward",
    "trash", "archive", "label", "cancel", "refund", "fulfil", "fulfill", "publish",
    "set_", "add_", "remove_", "edit_", "post_", "put_", "patch_", "destroy", "append",
    "restore", "commit", "approve", "execute", "adjust",
)

# Reads that return customer personal data. They run, but the assistant is told to read the
# match back rather than act on it, which is the M13 low-confidence rule in tool form.
_PII_TOOLS = frozenset({"shopify_find_customer", "shopify_order_detail", "shopify_customer_history", "shopify_order_address", "gmail_read_thread", "gmail_find_in_email"})

_KNOWN_TOOLS = frozenset({
    # mocks — M5 only
    "mock_echo", "mock_slow", "mock_danger",
    # Shopify — M7
    "shopify_find_order", "shopify_order_detail", "shopify_list_orders",
    "shopify_find_customer", "shopify_inventory", "shopify_sales_summary",
    "shopify_product_info", "shopify_customer_history", "shopify_order_address",
    # the general read layer (app/tools/analytics_tools.py)
    "commerce_aggregate", "commerce_query", "inventory_query", "commerce_capabilities", "email_query",
    # Gmail — M9
    "gmail_search", "gmail_read_thread", "gmail_find_in_email",
    # Phase 3 families, each adding its own reads. Deliberately named here and not derived
    # from the registry: "an unregistered tool is denied, so adding a tool without a rule
    # cannot grant access" is the rule this list IS, and a read reaches the model only when
    # somebody has written its name down. shopify_variant_search resolves words to variant
    # ids for order editing (app/families/order_edit.py).
    "shopify_variant_search",
    # the composer's two reads (app/families/compose.py). Both change only the Mac's own copy
    # of an email that has not been prepared yet: no source is touched, nothing is staged, and
    # neither can reach a Gmail write method. They are on this list because it is an
    # allow-list — a read tool absent from it is denied, which is the behaviour that makes
    # adding a tool without a rule impossible.
    "gmail_compose_open", "gmail_compose_fill",
    # The commerce families' reads (app/families/discounts.py, order_create.py,
    # store_credit.py, abandoned.py). Each one either reads the shop and returns what it
    # said, or reads the shop and puts a WORKSPACE on the Mac — a form the owner fills, which
    # creates nothing and stages nothing and cannot reach a mutation. They are named here
    # one by one because this is an allow-list: a read tool absent from it is denied, which
    # is what makes adding a tool without a rule impossible.
    "shopify_discount_check", "shopify_discount_open",
    "shopify_abandoned_checkouts",
    "shopify_order_open", "shopify_store_credit",
    # The summary read (app/families/summaries.py). One cache view and pure aggregation on
    # the Mac: it reads no record individually, stages nothing, and returns a count with a
    # few rows. Named here one by one like every other, because this is an allow-list.
    "commerce_summary",
    # The owner's objectives (app/objectives/tools.py). They read and change only CLIVE's own
    # objective records on this machine: no store, inbox, booking, payment or message is reachable
    # from them, exactly like the composer's two reads above. What they cannot do is the owner's:
    # the store refuses to authorise a work item or close an objective unless the owner's own
    # screen asks (app/routes/objectives.py). Named here one by one, because this is an allow-list.
    "objective_open", "objective_list", "objective_show", "objective_note",
    # The engineering loop's status (app/tools/engineering_tools.py). It reads what the loop
    # publishes on GitHub and the inbox branch's head, and nothing else: it stages nothing and
    # cannot reach a write. The head it returns is issued like any id a read returns, and that
    # issued id is what the filing tool, a write staged for the owner, must act on. Named here
    # because this is an allow-list.
    "engineering_status",
    # The owner's screens (app/tools/display_tools.py). They put something CLIVE already read —
    # an order the conversation was shown, an objective, a list — on one of the owner's own
    # screens (a page on his own devices, app/routes/displays.py), and read what was marked done
    # there. Nothing leaves this machine through them and nothing in a store or an inbox changes.
    # The order a slip is drawn from must be an issued id (below). Named here one by one,
    # because this is an allow-list.
    "screen_list", "screen_show",
})

# Tools that may only be called with an id this session already handed to the assistant. Stops
# Claude inventing an order id or a thread id and being told about a stranger's order.
_ISSUED_ID_ARGS: dict[str, tuple[str, ...]] = {
    "shopify_order_detail": ("order_id",),
    "screen_show": ("order_id",),
    "shopify_customer_history": ("customer_id",),
    "gmail_read_thread": ("thread_id",),
}

# Argument bounds. Exceeding one is not an error — it is clamped by the tool — but a wildly
# out-of-range request usually means the model has misunderstood, so it is worth refusing.
_MAX_LIMIT = 50
_MAX_DAYS = 365

_ID_SHAPE = re.compile(r"^[A-Za-z0-9/_.:=+-]{1,200}$")
# The kind of id each detail tool accepts. A Customer gid handed to the order tool is not
# "issued this session" in any sense that matters, even though a search did return it.
_ID_KIND = {
    "order_id": re.compile(r"^gid://shopify/Order/\d+$"),
    "customer_id": re.compile(r"^gid://shopify/Customer/\d+$"),
    "line_item_id": re.compile(r"^gid://shopify/LineItem/\d+$"),
    "variant_id": re.compile(r"^gid://shopify/ProductVariant/\d+$"),
    "thread_id": re.compile(r"^[0-9a-f]{6,}$", re.I),
    "evidence_message_id": re.compile(r"^[0-9a-f]{6,}$", re.I),
    "set_id": re.compile(r"^set_[0-9a-f]{6,}$"),
    # A workspace on the Mac — a discount being written, an order being built, a credit being
    # decided (app/families/_workspace.py). Not a Shopify id: the thing does not exist yet,
    # and the workspace is what the owner is authorising the creation of. Held to its shape
    # here so that a Shopify gid, or a compose id, cannot be handed to a creation tool.
    "workspace_id": re.compile(r"^(?:dsc|ord|crd)_[0-9a-f]{6,}$"),
}


def id_kind_ok(arg: str, value: object) -> bool:
    """Whether a value has the shape of the kind of id this argument takes. For routes that
    take an id from the tablet and must not forward another kind to Shopify."""
    kind = _ID_KIND.get(arg)
    text = str(value or "")
    return bool(_ID_SHAPE.match(text)) and (kind is None or bool(kind.match(text)))


def _looks_like_mutation(name: str) -> bool:
    return any(verb in name for verb in _MUTATION_VERBS)


def classify(
    tool_name: str,
    args: dict[str, Any] | None = None,
    issued_ids: Iterable[str] | None = None,
) -> Decision:
    """Classify one tool call. Pure: no I/O, no globals, no clock."""
    from app.tools.registry import normalise_tool_name

    name = normalise_tool_name(tool_name)
    args = args or {}
    issued = frozenset(issued_ids or ())

    if not name:
        return deny("Empty tool name.")

    spec = _spec(name)
    if _looks_like_mutation(name) or (spec is not None and (spec.write is not None or spec.batch is not None)):
        return _classify_write(name, spec, args, issued)

    if name not in _KNOWN_TOOLS:
        return deny(f"{name} is not a registered tool.")

    if name == "mock_danger":
        return deny("mock_danger exists to prove RED tools never execute.")

    # The registry's ToolSpec is the second source of truth: a tool that declares AMBER or
    # an issued-id argument there gets it here too, so the two tables cannot drift apart.
    spec_tier = spec.tier if spec is not None else None
    spec_id_args = tuple(spec.issued_id_args) if spec is not None else ()
    id_args = tuple(dict.fromkeys(_ISSUED_ID_ARGS.get(name, ()) + spec_id_args))
    if spec_tier is Tier.RED:
        return deny(f"{name} is registered as RED.")

    problem = _check_issued_ids(name, id_args, args, issued, optional=_optional_args(spec, id_args))
    if problem:
        return deny(problem.lstrip(_RECOVERABLE), recoverable=problem.startswith(_RECOVERABLE))

    limit = args.get("limit")
    if limit is not None:
        try:
            if int(limit) > _MAX_LIMIT or int(limit) < 1:
                return deny(f"limit={limit} is outside 1..{_MAX_LIMIT}.")
        except (TypeError, ValueError):
            return deny(f"limit={limit!r} is not a number.")

    days = args.get("days")
    if days is not None:
        try:
            if int(days) > _MAX_DAYS or int(days) < 1:
                return deny(f"days={days} is outside 1..{_MAX_DAYS}.")
        except (TypeError, ValueError):
            return deny(f"days={days!r} is not a number.")

    if name in _PII_TOOLS or spec_tier is Tier.AMBER:
        return Decision(
            Tier.AMBER, f"{name} returns customer personal data; read it back.", Disposition.EXECUTE_NOW,
        )

    return Decision(Tier.GREEN, "Read-only, in scope, arguments within bounds.", Disposition.EXECUTE_NOW)


def _classify_write(name: str, spec, args: dict[str, Any], issued: frozenset[str]) -> Decision:
    """A tool that reads as a write. It is staged for the owner only when it is registered
    with a complete write definition and its arguments pass every bound; otherwise denied."""
    if spec is None:
        return deny(f"{name} reads as a write operation and is not a registered tool.")
    if spec.batch is not None:
        return _classify_batch(name, spec, args, issued)
    write = spec.write
    if write is None or not write.complete:
        return deny(f"{name} reads as a write operation and has no reviewed write definition.")
    if spec.tier is Tier.GREEN:
        return deny(f"{name} is a write and cannot be GREEN.")
    id_args = tuple(dict.fromkeys(spec.issued_id_args))
    if write.entity_arg not in id_args:
        return deny(f"{name} must act on an issued {write.entity_arg}.")
    optional = _optional_args(spec, id_args)
    if write.entity_arg in optional:
        # The schema lets the entity id go unsaid (an email to a customer with no order):
        # then another issued id must name who it acts on. Never none.
        if not any(str(args.get(arg) or "").strip() for arg in id_args):
            return deny(f"{name} requires one of {', '.join(id_args)}, which was not supplied.")
    else:
        optional = optional - {write.entity_arg}
    problem = _check_issued_ids(name, id_args, args, issued, optional=optional)
    if problem:
        return deny(problem.lstrip(_RECOVERABLE), recoverable=problem.startswith(_RECOVERABLE))
    problem = _check_schema_bounds(name, spec.input_schema, args)
    if problem:
        return deny(problem)
    return Decision(
        spec.tier,
        f"{name} is a change to the store: prepared for the owner to authorise on the screen.",
        Disposition.STAGE_FOR_OWNER,
    )


def _classify_batch(name: str, spec, args: dict[str, Any], issued: frozenset[str]) -> Decision:
    """A tool that changes every member of a working set. Staged for the owner only when it
    is declared completely on a reviewed child write tool, acts on an issued set id, and its
    arguments pass every bound; otherwise denied. It never executes here either."""
    batch = spec.batch
    if spec.write is not None:
        return deny(f"{name} declares both a write and a batch; it must be one or the other.")
    if batch is None or not batch.complete:
        return deny(f"{name} is a bulk change with no reviewed batch definition.")
    if spec.tier is Tier.GREEN:
        return deny(f"{name} is a bulk change and cannot be GREEN.")
    child = _spec(batch.child_tool)
    if child is None or child.write is None or not child.write.complete:
        return deny(f"{name} is built on {batch.child_tool}, which is not a reviewed write tool.")
    id_args = tuple(dict.fromkeys(spec.issued_id_args))
    if "set_id" not in id_args:
        return deny(f"{name} must act on an issued set_id.")
    optional = _optional_args(spec, id_args) - {"set_id"}
    problem = _check_issued_ids(name, id_args, args, issued, optional=optional)
    if problem:
        return deny(problem.lstrip(_RECOVERABLE), recoverable=problem.startswith(_RECOVERABLE))
    problem = _check_schema_bounds(name, spec.input_schema, args)
    if problem:
        return deny(problem)
    return Decision(
        spec.tier,
        f"{name} is a change to every item in a working set: prepared for the owner to authorise on the screen.",
        Disposition.STAGE_FOR_OWNER,
    )


# Prefixed to the one refusal reason the model can put right on its own. Stripped before the
# words reach the model; what it marks is whether this was a rule or a wrong turning.
_RECOVERABLE = "\x00"


def _optional_args(spec, id_args: tuple[str, ...]) -> frozenset[str]:
    """The issued-id arguments the tool's own schema does not require (an order a reply is
    about, the email an address came from). Present, they must be issued ids of their kind
    like any other; absent, the tool decides what it can do without them."""
    schema = spec.input_schema if spec is not None and isinstance(spec.input_schema, dict) else {}
    required = set(schema.get("required") or [])
    return frozenset(arg for arg in id_args if arg not in required)


def _check_issued_ids(name: str, id_args: tuple[str, ...], args: dict[str, Any], issued: frozenset[str], *, optional: frozenset[str] = frozenset()) -> str:
    for arg in id_args:
        value = args.get(arg)
        if value is None or not str(value).strip():
            if arg in optional:
                continue
            return f"{name} requires {arg}, which was not supplied."
        value = str(value)
        if not _ID_SHAPE.match(value):
            return f"{arg}={value!r} is not a well-formed id."
        kind = _ID_KIND.get(arg)
        if kind is not None and not kind.match(value):
            return f"{arg}={value!r} is not the kind of id {name} takes."
        if value not in issued:
            return _RECOVERABLE + (
                f"{arg}={value!r} is not an id this conversation has looked up, so {name} was "
                "not run. Nothing is refused: find the record first (for an order, "
                f"shopify_find_order), then call {name} again with the id that lookup returned."
            )
    return ""


def _check_schema_bounds(name: str, schema: dict[str, Any], args: dict[str, Any]) -> str:
    """The input schema's own bounds, enforced here for writes rather than trusted to the
    model: required arguments present, no unknown arguments, strings and numbers within
    their bounds."""
    properties = schema.get("properties") if isinstance(schema, dict) else None
    properties = properties if isinstance(properties, dict) else {}
    for required in schema.get("required", []) if isinstance(schema, dict) else []:
        if required not in args:
            return f"{name} requires {required}, which was not supplied."
    for key, value in args.items():
        if key not in properties:
            return f"{name} does not take an argument called {key}."
        rule = properties.get(key) or {}
        if rule.get("type") == "array":
            if not isinstance(value, list):
                return f"{name}.{key} must be a list."
            if "maxItems" in rule and len(value) > int(rule["maxItems"]):
                return f"{name}.{key} has more than {rule['maxItems']} items."
            if "minItems" in rule and len(value) < int(rule["minItems"]):
                return f"{name}.{key} is empty."
            item_rule = rule.get("items") or {}
            if item_rule.get("type") == "string" and any(not isinstance(v, str) or ("maxLength" in item_rule and len(v) > int(item_rule["maxLength"])) for v in value):
                return f"{name}.{key} has an item that is not short text."
        if rule.get("type") == "string":
            if not isinstance(value, str):
                return f"{name}.{key} must be text."
            length = len(value.strip())
            if "minLength" in rule and length < int(rule["minLength"]):
                return f"{name}.{key} is empty."
            if "maxLength" in rule and len(value) > int(rule["maxLength"]):
                return f"{name}.{key} is longer than {rule['maxLength']} characters."
        if rule.get("type") in ("integer", "number"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return f"{name}.{key} must be a number."
            if "minimum" in rule and value < rule["minimum"]:
                return f"{name}.{key} is below {rule['minimum']}."
            if "maximum" in rule and value > rule["maximum"]:
                return f"{name}.{key} is above {rule['maximum']}."
    return ""


def _spec(name: str):
    """The registered ToolSpec, or None."""
    from app.tools import registry

    try:
        return registry.get(name)
    except KeyError:
        return None
