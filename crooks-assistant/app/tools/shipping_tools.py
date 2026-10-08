"""CLIVE Shipping in the conversation: the international orders by stage, one order in full, its
tracking, what changed, and the three changes the owner approves on a card: buy a label, print it,
print another copy (app/clients/crooks_shipping.py talks to the service).

Approved by the owner on 7 October 2026, exactly: "read shipments; preview and buy a label on his
hold; print. Printing goes through the Shipping service's own PrintNode connection rather than CLIVE
holding a second key." So:

- Four reads, the owner's alone (no staff member's set names them, app/people/staff.py, and no
  bounded service work may call them, app/tools/authority.py): shipments_open, shipment_find,
  shipment_tracking, shipping_events. GREEN: the service's rows name no customer, and a sentence it
  wrote is scrubbed before it is kept (app/tools/shipping_views.py).
- Three writes, each staged and never sent when called, each sent only by the action engine after
  the owner's gesture on its card, each with a fresh idempotency key made for that card and actor
  "George" (recorded by the service as "George (CLIVE)"), each proved by reading the order back:
    shipping_label_buy      the card IS the service's own preview (its `will` lines, its exact
                            price and who is charged); the buy carries that preview's `basis`, so
                            the service buys nothing if the order or the price changed. It moves
                            money, so it is the owner's hold (op_class "money": hold to arm).
    shipping_label_print    the label's first print, through the service's PrintNode. His swipe.
    shipping_label_reprint  one extra copy, sent with the service's `confirm: true`. His swipe.
  Printing never buys postage; buying never prints. Whether buying is allowed at all stays the
  service's own authorisation (SHIPPING_BUYING_ENABLED, SHIPPING_AUTHORISED_ORDERS): CLIVE has no
  way round it, and says so instead of staging a card the service would refuse.
- Never the Shipping screen's own routes, never its database, never Shopify's fulfilment mutations
  or Parcel2Go directly: the service's /api/v1 is the only way in.
"""

from __future__ import annotations

import secrets
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Any

from app.actions.models import Observed, Prepared
from app.capabilities.families import CapabilityFamily, register
from app.clients import crooks_shipping as client
from app.tools import shipping_views as views
from app.tools.gate import Tier
from app.tools.registry import ToolError, WriteSpec, tool

READS = ("shipments_open", "shipment_find", "shipment_tracking", "shipping_events")
BUY, PRINT, REPRINT = "shipping_label_buy", "shipping_label_print", "shipping_label_reprint"
WRITES = (BUY, PRINT, REPRINT)
TOOLS = (*READS, *WRITES)

MAX_WILL = 8
MAX_WILL_CHARS = 300
MAX_EVENT_PAGES = 5
# Each read waits for the service at most this long (app/clients/crooks_shipping.py), and a little over.
ONE_READ_S = client.READ_TIMEOUT_S + 2.0
NO_KEYS = "no CLIVE Shipping keys stored"


async def _probe_reads(_runtime: Any) -> dict[str, str]:
    """A read key is READY (the reads say themselves whether it still works); none is DISCONNECTED,
    which takes the reads off what the model is offered and tells it why in one line."""
    if not client.read_key():
        return {"state": "DISCONNECTED", "detail": NO_KEYS}
    return {"state": "READY", "detail": "CLIVE Shipping is connected"}


async def _probe_labels(_runtime: Any) -> dict[str, str]:
    """Both keys are needed: a change is staged from reads and the service's preview, which carry the
    read key, and sent with the write key. With both, the operations' own state stands (changes off
    is READ_ONLY, as for every other write)."""
    read, write = client.read_key(), client.write_key()
    if not read and not write:
        return {"state": "DISCONNECTED", "detail": NO_KEYS}
    if not read or not write:
        return {"state": "DISCONNECTED", "detail": f"no CLIVE Shipping {'read' if not read else 'write'} key stored"}
    return {}


register(CapabilityFamily(
    key="shipping_reads", label="Reading shipping", area="shipping",
    what="your international orders by stage, one order's payment, label, print and tracking, and what changed "
         "(CLIVE Shipping)",
    tools=READS, state="READY", detail="ready", probe=_probe_reads,
))
register(CapabilityFamily(
    key="shipping_labels", label="Buying and printing labels", area="shipping",
    what="buy an international label at the price checked, print it, or print another copy, each on your gesture "
         "(CLIVE Shipping, printing through its PrintNode)",
    operations=WRITES, tools=WRITES, state="READY", detail="ready", probe=_probe_labels,
))


def _failed(exc: client.ShippingUnavailable) -> ToolError:
    return ToolError(str(exc))


def _iso(when: datetime) -> str:
    return when.isoformat(timespec="seconds").replace("+00:00", "Z")


def _money(minor: Any, currency: Any) -> str:
    """1179, "GBP" -> "£11.79", as the service shows money; anything not whole minor units -> ""."""
    if not isinstance(minor, int) or isinstance(minor, bool):
        return ""
    whole, part = divmod(abs(minor), 100)
    symbol = {"GBP": "£", "EUR": "€", "USD": "$"}.get(str(currency or "GBP").upper())
    amount = f"{'-' if minor < 0 else ''}{whole:,}.{part:02d}"
    return f"{symbol}{amount}" if symbol else f"{amount} {str(currency)[:3]}"


# ------------------------------------------------------------------ reads


@tool(
    name="shipments_open",
    description=("CLIVE Shipping (international orders): orders in a stage, with what blocks each, payment, price, "
                 "print and carrier. No stage: all still going out, counted by stage."),
    input_schema={"type": "object", "properties": {"stage": {"type": "string", "enum": list(client.STAGES)}}},
    tier=Tier.GREEN,
    timeout_s=ONE_READ_S,
)
async def shipments_open(stage: str = "") -> dict[str, Any]:
    stage = str(stage or "").strip()
    if stage and stage not in client.STAGES:
        raise ToolError(f"stage is one of {', '.join(client.STAGES)}.")
    try:
        rows = await client.list_shipments(stage=stage or "all")
    except client.ShippingUnavailable as exc:
        raise _failed(exc) from None
    return views.open_view(rows, stage=stage, checked_at=_iso(datetime.now(UTC)))


async def _by_order(order: Any) -> list[dict[str, Any]]:
    rows = await client.find_order(order)
    return [await client.get_shipment(r.get("id")) for r in rows[:3]]


def _none_for(order: Any) -> str:
    return (f"CLIVE Shipping has no order #{client.order_digits(order)}; it holds international orders only "
            "(UK orders go through Shopify's own shipping).")


@tool(
    name="shipment_find",
    description=("One CLIVE Shipping order in full, by shipment_id or order number: stage, blockers, payment, price, "
                 "label, tracking, print, carrier."),
    input_schema={
        "type": "object",
        "properties": {"shipment_id": {"type": "string", "maxLength": 48}, "order": {"type": "string", "maxLength": 20}},
    },
    tier=Tier.GREEN,
    timeout_s=4 * ONE_READ_S,
)
async def shipment_find(shipment_id: str = "", order: str = "") -> dict[str, Any]:
    try:
        if str(shipment_id or "").strip():
            found = [await client.get_shipment(shipment_id)]
        elif str(order or "").strip():
            found = await _by_order(order)
        else:
            raise ToolError("Give a shipment id or an order number.")
    except client.ShippingUnavailable as exc:
        raise _failed(exc) from None
    out: dict[str, Any] = {"shipments": [views.detail(d) for d in found], "count": len(found)}
    if order and not str(shipment_id or "").strip():
        out["order_number"] = f"#{client.order_digits(order)}"
        if not found:
            out["note"] = _none_for(order)
    return out


@tool(
    name="shipment_tracking",
    description=("The carrier's tracking of a CLIVE Shipping label, asked of Shopify now (shipment_id or order "
                 "number)."),
    input_schema={
        "type": "object",
        "properties": {"shipment_id": {"type": "string", "maxLength": 48}, "order": {"type": "string", "maxLength": 20}},
    },
    tier=Tier.GREEN,
    timeout_s=client.TRACKING_TIMEOUT_S + 3 * ONE_READ_S,
)
async def shipment_tracking(shipment_id: str = "", order: str = "") -> dict[str, Any]:
    try:
        if str(shipment_id or "").strip():
            sid = client.shipment_id(shipment_id)
        elif str(order or "").strip():
            found = await _by_order(order)
            bought = [d for d in found if d.get("label")]
            if not bought:
                number = f"#{client.order_digits(order)}"
                return {"shipments": [], "count": 0, "order_number": number,
                        "note": f"{number} has no label bought yet, so there is no tracking." if found else _none_for(order)}
            sid = str(bought[0].get("id"))
        else:
            raise ToolError("Give a shipment id or an order number.")
        d = await client.refresh_tracking(sid)
    except client.ShippingUnavailable as exc:
        raise _failed(exc) from None
    shaped = views.detail(d)
    return {"shipments": [shaped], "count": 1, "order_number": shaped["order_number"]}


@tool(
    name="shipping_events",
    description=("What changed in CLIVE Shipping in the last `hours` (default 24): labels, prints, carrier scans, "
                 "payment, alerts; who, and whether checked."),
    input_schema={"type": "object", "properties": {"hours": {"type": "integer", "minimum": 1, "maximum": 720}}},
    tier=Tier.GREEN,
    timeout_s=MAX_EVENT_PAGES * ONE_READ_S,
)
async def shipping_events(hours: int = 24) -> dict[str, Any]:
    try:
        hours = max(1, min(int(hours), 720))
    except (TypeError, ValueError):
        raise ToolError("hours must be a whole number of hours.") from None
    since = _iso(datetime.now(UTC) - timedelta(hours=hours))
    found: list[dict[str, Any]] = []
    cursor, more = since, False
    try:
        for _ in range(MAX_EVENT_PAGES):
            page = await client.events(since=cursor, limit=200)
            batch = [e for e in page.get("events") or [] if isinstance(e, dict)]
            found += batch
            more = bool(page.get("has_more")) and bool(batch)
            if not more:
                break
            cursor = str(batch[-1].get("at") or cursor)
    except client.ShippingUnavailable as exc:
        raise _failed(exc) from None
    return views.events_view(found, hours=hours, since=since, more=more)


# ------------------------------------------------------------------ the writes: shared


def fingerprint(d: dict[str, Any]) -> dict[str, Any]:
    """What the engine holds an order to: its stage, whether a label is bought and has its tracking
    number, and its prints (the state, how many attempts, how many extra copies). It is written to
    the action ledger and, from there, the timeline, so it says WHETHER the tracking number is in,
    never the number: that is the customer's parcel. No customer's detail, and nothing that moves on
    its own between two reads (a status's wording, a carrier check's time)."""
    printing = d.get("print_status") if isinstance(d.get("print_status"), dict) else {}
    history = printing.get("history") if isinstance(printing.get("history"), list) else []
    reprints = printing.get("reprint_count")
    label = d.get("label") if isinstance(d.get("label"), dict) else None
    return {
        "stage": str(d.get("stage") or ""),
        "bought": label is not None,
        "tracking": bool((label or {}).get("tracking_number")),
        "print": str(printing.get("state") or ""),
        "prints": len(history),
        "reprints": reprints if isinstance(reprints, int) else 0,
    }


async def _observe(execution: dict) -> Observed:
    try:
        d = await client.get_shipment(execution["shipment_id"])
    except client.ShippingUnavailable as exc:
        raise _failed(exc) from None
    return Observed(fingerprint=fingerprint(d), entity=views.detail(d))


async def _settle(_execution: dict, _sent: dict) -> None:
    """Nothing to wait for. Declared so that a change whose answer never came back (a timeout, or a
    503 after the courier may have been paid) is never written off as "nothing was changed" on one
    re-read: the engine says it could not confirm it, and to look at the order."""
    return None


# What each send answered, by its idempotency key, for the proof that follows it: the engine hands
# the proof the order as re-read, and the service's own verdict is here.
_OUTCOMES: OrderedDict[str, dict[str, Any]] = OrderedDict()
MAX_OUTCOMES = 64


def _remember(key: str, outcome: dict[str, Any]) -> None:
    _OUTCOMES[key] = outcome
    while len(_OUTCOMES) > MAX_OUTCOMES:
        _OUTCOMES.popitem(last=False)


async def _send(execution: dict, call) -> dict[str, Any]:
    """Send one approved change and keep what the service said, refusals included, for its proof."""
    key = str(execution["idempotency_key"])
    try:
        answer = await call(key)
    except client.ShippingUnavailable as exc:
        if exc.refused:
            _remember(key, {"refused": str(exc)})
        raise
    return answer


def _lost(observed: dict, before: dict, moved: bool, what: str) -> tuple[bool, str]:
    """The answer never came back (the engine settled it by looking)."""
    if moved:
        return True, f"CLIVE lost {client.NAME}'s answer, but the order now shows the {what}."
    return False, (f"CLIVE lost {client.NAME}'s answer, and the order doesn't show the {what}. Look at it in Shipping "
                   "before asking again.")


def _order_of(d: dict[str, Any]) -> str:
    return views.order_number(d) or str(d.get("order") or "")


async def _read_for_staging(shipment_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        d = await client.get_shipment(shipment_id)
    except client.ShippingUnavailable as exc:
        raise _failed(exc) from None
    return d, views.detail(d)


# ------------------------------------------------------------------ buy


def _without_tracking(words: str, d: Any) -> str:
    """The service's sentence with the order's own tracking number taken out: what the proof says is
    written to the ledger and the timeline, and the number is the customer's."""
    label = d.get("label") if isinstance(d, dict) and isinstance(d.get("label"), dict) else {}
    number = str(label.get("tracking_number") or "").strip()
    return words.replace(number, "[tracking number]") if number else words


async def _execute_buy(execution: dict) -> dict:
    """Sent only by the action engine, after the owner's hold on this card."""
    answer = await _send(execution, lambda key: client.buy(execution["shipment_id"], basis=execution["basis"],
                                                           idempotency_key=key))
    error = client.scrub(answer.get("error")) if answer.get("error") else ""
    _remember(str(execution["idempotency_key"]), {
        "charged": answer.get("charged") is True, "may_have_been_charged": answer.get("may_have_been_charged") is True,
        "replayed": answer.get("replayed") is True, "status": str(answer.get("status") or ""),
        "error": _without_tracking(error, answer.get("shipment")),
    })
    return {"status": str(answer.get("status") or ""), "done": answer.get("charged") is True}


def verify_buy(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    """Proven when the order, read back, shows the label the service says it bought."""
    out = _OUTCOMES.get(str(execution.get("idempotency_key") or ""))
    bought = bool(observed.get("bought"))
    if out is None:
        return _lost(observed, before, bought and not before.get("bought"), "label")
    if out.get("refused"):
        return False, f"{client.NAME} refused it: {out['refused']}"
    if not bought:
        if out.get("may_have_been_charged"):
            return False, ("The courier may have taken the payment, and CLIVE Shipping is checking it. Don't buy "
                           "again: look at the order in Shipping.")
        return False, f"{client.NAME} answered, but the order shows no label" + (f": {out['error']}" if out["error"] else ".")
    # Whether the number is in, never the number: this note is the ledger's reason and the timeline's.
    # George reads the number on the order's card, drawn from the order as read back.
    said = ["Tracking number in." if observed.get("tracking") else
            "No tracking number yet; CLIVE Shipping adds it when the courier sends it."]
    if out["error"]:
        said.append(f"The label is bought, but: {out['error']}")
    return True, " ".join(said)


def _present_buy(proposal) -> dict:
    s = proposal.summary
    number = str(s.get("order_number") or proposal.entity_label or "")
    facts = [{"label": "Order", "value": number}, {"label": "To", "value": str(s.get("country") or "")},
             {"label": "Service", "value": str(s.get("service") or "")}]
    if s.get("days"):
        facts.append({"label": "Delivery", "value": str(s.get("days"))})
    facts.append({"label": "Price", "value": str(s.get("price") or "")})
    # What the hold is for comes before anything else that could be cut.
    facts.append({"label": "Moves money", "value": "yes: hold the card, then tap", "tone": "bad"})
    if s.get("emails_customer"):
        facts.append({"label": "Customer emailed", "value": "yes (by Shopify)"})
    will = [str(w) for w in s.get("will") or []]
    return {
        "title": f"Buy the label for {number}",
        "summary": str(s.get("charged") or ""),
        # The service's own preview, line for line: what the hold authorises.
        "body": "\n".join(will),
        "detail": "CLIVE Shipping buys at this price or not at all: if the order or the price has changed, nothing is bought.",
        "facts": facts[:8],
        "done_title": "Label bought",
    }


def _days(service: dict[str, Any]) -> str:
    days = service.get("days") if isinstance(service.get("days"), list) else []
    low, high = (days + [None, None])[:2]
    if isinstance(low, int) and isinstance(high, int) and low and high and low != high:
        return f"{low}–{high} days"
    if isinstance(high, int) and high:
        return f"up to {high} day{'s' if high != 1 else ''}"
    return ""


@tool(
    name=BUY,
    description=("Stage buying a CLIVE Shipping label for the owner's hold; the card is the service's own price "
                 "check. The order must be ready."),
    input_schema={"type": "object", "properties": {"shipment_id": {"type": "string"}}, "required": ["shipment_id"]},
    tier=Tier.AMBER,
    issued_id_args=("shipment_id",),
    # A read of the order, the service's preview (Shopify and the courier), and a read again.
    timeout_s=2 * client.READ_TIMEOUT_S + client.PREVIEW_TIMEOUT_S + 2.0,
    write=WriteSpec(
        operation=BUY,
        entity_kind="shipment",
        entity_arg="shipment_id",
        mutation="shipping:buy",
        observe=_observe,
        execute=_execute_buy,
        present=_present_buy,
        verify=verify_buy,
        settle=_settle,
        interaction="hold_to_arm",
        # Money leaves: the owner's hold (app/actions/grammar.py: AMBER and money is hold to arm).
        op_class="money",
        reversible=False,
        precondition_keys=("stage", "bought"),
        service=client.NAME,
        says_failure=True,
        spoken_success="Label bought for order {label}, {amount}.",
        spoken_failure="CLIVE Shipping didn't confirm the label; look at the order in Shipping before buying again.",
        spoken_stale="That order changed since its price was checked, so nothing was bought.",
    ),
)
async def shipping_label_buy(shipment_id: str) -> Prepared:
    """Prepare, never buy: read the order, ask the service's preview, and stage what it said."""
    d, v = await _read_for_staging(shipment_id)
    number = _order_of(d)
    if v["label"]:
        # Whether its tracking number is in, not the number: a refusal is written to the log and the
        # timeline. The order's card (shipment_find) shows the number.
        raise ToolError(f"{number} already has a label bought ({v['label']['provider']}, tracking number "
                        f"{'in' if v['label']['tracking_number'] else 'not in yet'}). Nothing to buy.")
    if v["stage"] != "ready":
        why = " · ".join(v["reasons"]) or v["status"] or v["stage_words"]
        raise ToolError(f"{number} isn't ready for a label: {why}. Nothing was prepared.")
    try:
        said = await client.preview(shipment_id)
    except client.ShippingUnavailable as exc:
        raise _failed(exc) from None
    will = [str(w)[:MAX_WILL_CHARS] for w in (said.get("will") or []) if isinstance(w, str)][:MAX_WILL]
    money = said.get("money") if isinstance(said.get("money"), dict) else {}
    minor, currency = money.get("shipping_minor"), str(money.get("currency") or "GBP")[:3]
    price = _money(minor, currency)
    basis = str(said.get("basis") or "")
    if not will or not basis or not price:
        raise ToolError("CLIVE Shipping's price check didn't say what it would buy, so nothing was prepared.")
    service = said.get("service") if isinstance(said.get("service"), dict) else {}
    service_words = " · ".join(str(service.get(k)) for k in ("carrier", "name") if service.get(k)) or v["service"]
    if not v["can_buy"]:
        raise ToolError(f"Buying isn't authorised for {number} on the shipping server, so no card was made. The exact "
                        f"price now is {price} ({service_words}). The server allows it when {number.lstrip('#')} is in "
                        f"SHIPPING_AUTHORISED_ORDERS, or SHIPPING_BUYING_ENABLED is true, in {client.ENV_FILE}.")
    # Read again: the preview may have written the exact price onto the order.
    after, _ = await _read_for_staging(shipment_id)
    return Prepared(
        execution={"shipment_id": str(d.get("id")), "basis": basis,
                   # This card's own key, made now and used once, when the owner approves it.
                   "idempotency_key": f"clive-buy-{secrets.token_hex(8)}"},
        before=fingerprint(after),
        expected_after={},
        entity_ref=str(d.get("id")),
        entity_label=number,
        summary={
            "order_number": number, "country": v["country"], "service": service_words, "days": _days(service),
            "price": price, "amount": minor / 100, "currency": currency, "will": will,
            "charged": client.scrub(said.get("charged"), 120),
            "emails_customer": any("email the customer" in w for w in will),
            "read_back": f"buy the label for order {number.lstrip('#')} at {price}",
            "ledger": {"amount_minor": minor, "currency": currency},
        },
    )


# ------------------------------------------------------------------ print, and print again


def _execute_print(reprint: bool):
    async def execute(execution: dict) -> dict:
        """Sent only by the action engine, after the owner's swipe on this card."""
        send = client.reprint if reprint else client.print_label
        answer = await _send(execution, lambda key: send(execution["shipment_id"], idempotency_key=key))
        intent = answer.get("print_intent") if isinstance(answer.get("print_intent"), dict) else {}
        _remember(str(execution["idempotency_key"]), {
            "sent": answer.get("sent_to_printer") is True, "state": str(intent.get("state") or ""),
            "error": client.scrub(intent.get("error")) if intent.get("error") else "",
        })
        return {"status": str(intent.get("state") or ""), "done": answer.get("sent_to_printer") is True}
    return execute


def _verify_print(reprint: bool):
    def verify(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
        """Proven when the service says PrintNode took the job and the order, read back, shows one
        more print (or one more copy). Taken by PrintNode is not paper in the tray: never "printed"."""
        out = _OUTCOMES.get(str(execution.get("idempotency_key") or ""))
        counted = "reprints" if reprint else "prints"
        moved = observed.get(counted, 0) > before.get(counted, 0) and observed.get("print") in ("printing", "printed")
        if out is None:
            return _lost(observed, before, moved, "print")
        if out.get("refused"):
            return False, f"{client.NAME} refused it: {out['refused']}"
        if not out["sent"]:
            if out["state"] == "unknown":
                return False, ("PrintNode didn't say whether it took the label, and CLIVE Shipping never resends by "
                               "itself. Check the printer before printing again.")
            return False, f"The label didn't go to the printer: {out['error'] or 'PrintNode refused it.'}"
        if not moved:
            return False, "PrintNode took it, but the order doesn't show the print yet; look at it in Shipping."
        return True, "It counts as printed once PrintNode says the printer has finished."
    return verify


def _present_print(reprint: bool):
    def present(proposal) -> dict:
        s = proposal.summary
        number = str(s.get("order_number") or proposal.entity_label or "")
        facts = [{"label": "Order", "value": number}, {"label": "Label", "value": str(s.get("label") or "")}]
        if s.get("tracking"):
            facts.append({"label": "Tracking", "value": str(s.get("tracking"))})
        if reprint:
            facts.append({"label": "Printed before", "value": str(s.get("before") or "")})
        facts.append({"label": "Moves money", "value": "no: printing never buys postage"})
        lines = ([f"Print one extra copy of the 4×6 label for {number} through PrintNode."] if reprint else
                 [f"Send the 4×6 label for {number} to the label printer through PrintNode, once."])
        lines.append("It counts as printed once PrintNode says the printer has finished.")
        return {
            "title": f"{'Print another copy' if reprint else 'Print the label'} for {number}",
            "summary": "",
            "body": "\n".join(lines),
            "detail": "PrintNode prints only while the computer it runs on is switched on.",
            "facts": facts[:8],
            "done_title": "Sent to the printer",
        }
    return present


async def _stage_print(shipment_id: str, *, reprint: bool) -> Prepared:
    d, v = await _read_for_staging(shipment_id)
    number = _order_of(d)
    if not v["label"]:
        raise ToolError(f"{number} has no label bought yet, so there is nothing to print.")
    printing = v["printing"] or {}
    # The service's own line between the two: a first print stays available until an attempt might
    # have printed (none yet, or every one definitely failed). Until then a copy is the wrong ask.
    if reprint and (not printing.get("attempts") or printing.get("first_print_available")):
        raise ToolError(f"The label for {number} hasn't been printed yet ({printing.get('label') or 'Not printed'}): "
                        "ask to print it, not for another copy.")
    if not reprint and not printing.get("first_print_available"):
        raise ToolError(f"The label for {number} has already gone to the printer ({printing.get('label') or 'sent'}). "
                        "Ask for another copy to print it again.")
    label = v["label"]
    before = printing.get("label") or ""
    if reprint and printing.get("reprints"):
        before += f", {printing['reprints']} extra cop{'ies' if printing['reprints'] != 1 else 'y'}"
    kind = "reprint" if reprint else "print"
    return Prepared(
        execution={"shipment_id": str(d.get("id")), "idempotency_key": f"clive-{kind}-{secrets.token_hex(8)}"},
        before=fingerprint(d),
        expected_after={},
        entity_ref=str(d.get("id")),
        entity_label=number,
        summary={
            "order_number": number, "label": " · ".join(x for x in (label["provider"], label["service"]) if x),
            "tracking": label["tracking_number"], "before": before,
            "read_back": f"{'print another copy of' if reprint else 'print'} the label for order {number.lstrip('#')}",
            "ledger": {"reprint": reprint},
        },
    )


def _print_spec(reprint: bool) -> WriteSpec:
    name = REPRINT if reprint else PRINT
    return WriteSpec(
        operation=name,
        entity_kind="shipment",
        entity_arg="shipment_id",
        mutation=f"shipping:{'reprint' if reprint else 'print'}",
        observe=_observe,
        execute=_execute_print(reprint),
        present=_present_print(reprint),
        verify=_verify_print(reprint),
        settle=_settle,
        # No money and no customer: the owner's swipe (AMBER and irreversible), as every change is.
        interaction="swipe_commit",
        op_class="irreversible",
        reversible=False,
        precondition_keys=("bought", "prints", "reprints"),
        service=client.NAME,
        says_failure=True,
        spoken_success=("Sent another copy of the label for order {label} to the printer." if reprint else
                        "Sent the label for order {label} to the printer."),
        spoken_failure="CLIVE Shipping didn't confirm the print; check the printer and the order before printing again.",
        spoken_stale="That label's prints changed since this was prepared, so nothing was sent.",
    )


@tool(
    name=PRINT,
    description="Stage the first print of a bought CLIVE Shipping label, via its PrintNode, for the owner's gesture.",
    input_schema={"type": "object", "properties": {"shipment_id": {"type": "string"}}, "required": ["shipment_id"]},
    tier=Tier.AMBER,
    issued_id_args=("shipment_id",),
    timeout_s=ONE_READ_S,
    write=_print_spec(reprint=False),
)
async def shipping_label_print(shipment_id: str) -> Prepared:
    return await _stage_print(shipment_id, reprint=False)


@tool(
    name=REPRINT,
    description="Stage an extra copy of a printed CLIVE Shipping label, via its PrintNode, for the owner's gesture.",
    input_schema={"type": "object", "properties": {"shipment_id": {"type": "string"}}, "required": ["shipment_id"]},
    tier=Tier.AMBER,
    issued_id_args=("shipment_id",),
    timeout_s=ONE_READ_S,
    write=_print_spec(reprint=True),
)
async def shipping_label_reprint(shipment_id: str) -> Prepared:
    return await _stage_print(shipment_id, reprint=True)
