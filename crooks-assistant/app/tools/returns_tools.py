"""CROOKS Returns in the conversation: what needs the owner, where a return is, a period's numbers,
and the actions he approves (app/clients/crooks_returns.py talks to the service).

The owner's brief (docs/returns/BRIEF_CLIVE.md on the service's branch, section 6): read-only
first; a write is a proposal; money moves only on his hold. So:

- Three reads, the owner's alone (no staff member's set names them, app/people/staff.py, and no
  bounded service work may call them, app/tools/authority.py): returns_open, return_find,
  returns_stats. AMBER, because a return names its customer.
- One write, return_action, which never acts when called. It reads the return, asks the service's
  /preview (which changes nothing and checks the same rules an execute does), and stages a card
  that IS that preview: its `will` lines and its money exactly as the service returned them. A
  refused preview is said and nothing is staged. Only the owner's gesture on the card executes it,
  through the action engine, with a fresh idempotency key made for that card alone (the service
  scopes it to the return and the action) and actor "clive for George". The result is then the
  service's own: verified when the return shows what the service said it did and it reported no
  error, otherwise the error it returned, in its words.
- Moving money is the strongest gesture this card has: approving with a label bought now or with
  nothing coming back, buying a label (a label action with no tracking), receiving in condition ok,
  and completing are raised to RED by the risk hook, which makes them hold-to-arm; everything else
  is the owner's swipe, as every change is under the current authority model.
- Every argument the service is sent was decided here, at staging: an approve's postage mode and a
  receive's condition are written out even where the service has a default, so what executes is
  what the card showed. Never the customers' portal, never the service's database, never Shopify's
  return mutations for these returns: shopify_refund_create is not how a return's money moves.
"""

from __future__ import annotations

import secrets
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Any

from app.actions.models import Observed, Prepared
from app.capabilities.families import CapabilityFamily, register
from app.clients import crooks_returns as client
from app.returns import views
from app.tools.gate import Tier
from app.tools.registry import ToolError, WriteSpec, tool

READS = ("returns_open", "return_find", "returns_stats")
WRITE = "return_action"
TOOLS = (*READS, WRITE)

POSTAGE_MODES = ("label_now", "self_ship", "label_later", "no_return")
CONDITIONS = ("ok", "damaged", "worn", "missing")
MAX_REASON = 200
MAX_NOTE = 500
MAX_WILL = 8
MAX_WILL_CHARS = 400
# Each read waits for the service at most this long (app/clients/crooks_returns.py), and a little over.
ONE_READ_S = client.READ_TIMEOUT_S + 2.0

TITLES = {
    "approve": "Approve the return", "decline": "Decline the return", "label": "Return label",
    "tracking": "Add the customer's tracking", "receive": "Receive the return", "complete": "Complete the return",
    "cancel": "Cancel the return", "note": "Note on the return",
}
DONE = {
    "approve": "Return approved", "decline": "Return declined", "label": "Label done", "tracking": "Tracking added",
    "receive": "Return received", "complete": "Return completed", "cancel": "Return cancelled", "note": "Note added",
}
MODE_WORDS = views.MODE_WORDS


async def _probe_reads(_runtime: Any) -> dict[str, str]:
    """A key is READY (the reads say themselves whether it still works); none is DISCONNECTED,
    which takes the reads off what the model is offered and tells it why in one line. With no
    keys at all the two families say the same reason, so they share that one line."""
    if not client.read_key():
        return {"state": "DISCONNECTED", "detail": NO_KEYS}
    return {"state": "READY", "detail": "CROOKS Returns is connected"}


async def _probe_actions(_runtime: Any) -> dict[str, str]:
    """No write key is DISCONNECTED. With one, the operation's own state stands (changes off is
    READ_ONLY, as for every other write), so this says nothing."""
    if not client.write_key():
        return {"state": "DISCONNECTED", "detail": NO_KEYS if not client.read_key() else "no CROOKS Returns write key stored"}
    return {}


NO_KEYS = "no CROOKS Returns keys stored"
register(CapabilityFamily(
    key="returns_reads", label="Reading returns", area="orders",
    what="the open returns and what each needs from you, one return's story, and a period's numbers (CROOKS Returns)",
    tools=READS, state="READY", detail="ready", probe=_probe_reads,
))
register(CapabilityFamily(
    key="returns_actions", label="Acting on returns", area="orders",
    what="approve, decline, label, receive, complete, cancel or note a return, each on your gesture (CROOKS Returns)",
    operations=(WRITE,), tools=(WRITE,), state="READY", detail="ready", probe=_probe_actions,
))


def _failed(exc: client.ReturnsUnavailable) -> ToolError:
    return ToolError(str(exc))


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: float | datetime) -> str:
    when = datetime.fromtimestamp(moment, UTC) if isinstance(moment, (int, float)) else moment
    return when.isoformat(timespec="seconds").replace("+00:00", "Z")


# ------------------------------------------------------------------ reads


@tool(
    name="returns_open",
    description=("CROOKS Returns: the open returns, those needing the owner first, each with what it needs; and "
                 "paid labels never posted after 14 days, to cancel on parcel2go.com."),
    input_schema={"type": "object", "properties": {}},
    tier=Tier.AMBER,
    timeout_s=ONE_READ_S,
)
async def returns_open() -> dict[str, Any]:
    try:
        rows, at = await client.OPEN.get()
    except client.ReturnsUnavailable as exc:
        raise _failed(exc) from None
    return views.open_view(rows, now=_now(), checked_at=_iso(at))


@tool(
    name="return_find",
    description=("One CROOKS Returns return in full (status, tracking link, timeline, money), by return_id or by "
                 "order number (2131, #2131, CROOKS-2131). For 'where is my return?'."),
    input_schema={
        "type": "object",
        "properties": {"return_id": {"type": "string", "maxLength": 48}, "order": {"type": "string", "maxLength": 20}},
    },
    tier=Tier.AMBER,
    timeout_s=ONE_READ_S,
)
async def return_find(return_id: str = "", order: str = "") -> dict[str, Any]:
    try:
        if str(return_id or "").strip():
            found = [await client.get_return(return_id)]
        elif str(order or "").strip():
            found = await client.order_returns(order)
        else:
            raise ToolError("Give a return id or an order number.")
    except client.ReturnsUnavailable as exc:
        raise _failed(exc) from None
    out: dict[str, Any] = {"returns": [views.detail(r) for r in found[:4]], "count": len(found)}
    if order and not return_id:
        out["order_number"] = f"#{client.order_digits(order)}"
        if not found:
            out["note"] = f"CROOKS Returns has no return on order #{client.order_digits(order)}."
    return out


@tool(
    name="returns_stats",
    description=("CROOKS Returns over the last `days`: kept share, top reasons and SKUs, size swaps per product "
                 "(repeated too-small is a size-chart finding), bonus given, label fees recovered."),
    input_schema={"type": "object", "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 365}}},
    tier=Tier.AMBER,
    timeout_s=2 * ONE_READ_S,
)
async def returns_stats(days: int = 30) -> dict[str, Any]:
    try:
        days = max(1, min(int(days), 365))
    except (TypeError, ValueError):
        raise ToolError("days must be a whole number of days.") from None
    since = _iso(_now() - timedelta(days=days))
    try:
        counted = await client.stats(since)
        changed = await client.list_returns(since=since, limit=client.MAX_LIST)
    except client.ReturnsUnavailable as exc:
        raise _failed(exc) from None
    return views.stats_view(counted, changed, days=days, since=since)


# ------------------------------------------------------------------ the write


def money_moving(action: str, params: dict[str, Any]) -> bool:
    """The changes the owner's brief names as moving money: they always take his strongest gesture."""
    if action == "approve":
        return params.get("postage_mode") in ("label_now", "no_return")
    if action == "label":
        return not params.get("tracking")
    if action == "receive":
        return params.get("condition") == "ok"
    return action == "complete"


def _short(value: Any, limit: int, what: str) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        raise ToolError(f"The {what} is longer than {limit} characters.")
    if "<" in text:
        raise ToolError(f"The {what} must be plain text.")
    return text


def params_for(action: str, ret: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """Exactly what the service is sent, decided now and shown on the card. Where the service has
    a default (an approve's postage, a receive's condition) it is written out, so the execute can
    never mean something the preview did not."""
    if action == "approve":
        chosen = str((ret.get("postage") or {}).get("chosen") or "")
        mode = str(args.get("postage_mode") or ("self_ship" if chosen == "self_ship" else "label_now"))
        if mode not in POSTAGE_MODES:
            raise ToolError("postage_mode must be label_now, self_ship, label_later or no_return.")
        return {"postage_mode": mode}
    if action in ("decline", "cancel"):
        reason = _short(args.get("reason"), MAX_REASON, "reason")
        return {"reason": reason} if reason else {}
    if action == "label":
        tracking = _short(args.get("tracking"), 40, "tracking number")
        carrier = _short(args.get("carrier"), 40, "carrier")
        return {"tracking": tracking, **({"carrier": carrier} if carrier else {})} if tracking else {}
    if action == "tracking":
        number = "".join(_short(args.get("tracking"), 40, "tracking number").split()).upper()
        if not 6 <= len(number) <= 40:
            raise ToolError("Give the customer's tracking number (6 to 40 letters and digits).")
        carrier = _short(args.get("carrier"), 40, "carrier")
        return {"number": number, **({"carrier": carrier} if carrier else {})}
    if action == "receive":
        condition = str(args.get("condition") or "ok").lower()
        if condition not in CONDITIONS:
            raise ToolError("condition must be ok, damaged, worn or missing.")
        restock = args.get("restock")
        note = _short(args.get("text"), MAX_NOTE, "note")
        return {"condition": condition, "restock": True if restock is None else bool(restock), **({"note": note} if note else {})}
    if action == "note":
        text = _short(args.get("text"), MAX_NOTE, "note")
        if not text:
            raise ToolError("Say what the note should say.")
        return {"text": text}
    return {}


def fingerprint(ret: dict[str, Any]) -> dict[str, Any]:
    """What the engine holds the return to: its status and money (the precondition), and how many
    timeline entries it has, whether it carries an error and who made the last one (the proof).
    No customer's detail."""
    events = [e for e in ret.get("timeline") or [] if isinstance(e, dict)]
    last = events[-1] if events else {}
    held = ret.get("money") if isinstance(ret.get("money"), dict) else {}
    return {
        "status": str(ret.get("status") or ""),
        "money": {k: v for k, v in sorted(held.items()) if client.pence(v) is not None},
        "events": len(events),
        "error": bool(ret.get("last_error")),
        "last": f"{last.get('type', '')}:{'clive' if last.get('actor') == client.ACTOR else 'other'}:{bool(last.get('verified'))}",
    }


async def _settle(_execution: dict, _sent: dict) -> None:
    """Nothing to wait for. Declared so that an action whose answer never came back (a timeout, or
    a 503 after the service had already made the Shopify return) is never written off as "nothing
    was changed" on one re-read: the engine says it could not confirm it, and to check the return."""
    return None


async def _observe(execution: dict) -> Observed:
    try:
        ret = await client.get_return(execution["return_id"])
    except client.ReturnsUnavailable as exc:
        raise _failed(exc) from None
    return Observed(fingerprint=fingerprint(ret), entity=views.detail(ret))


# What each execute answered, by its idempotency key, for the proof that follows it: the engine
# hands the proof the return as re-read, and the service's own verdict (verified, error) is here.
_OUTCOMES: OrderedDict[str, dict[str, Any]] = OrderedDict()
MAX_OUTCOMES = 64


def _remember(key: str, answer: dict[str, Any]) -> None:
    _OUTCOMES[key] = {
        "from": str(answer.get("from") or ""), "status": str(answer.get("status") or ""),
        "verified": bool(answer.get("verified")), "error": str(answer.get("error") or ""),
        "replayed": bool(answer.get("replayed")),
    }
    while len(_OUTCOMES) > MAX_OUTCOMES:
        _OUTCOMES.popitem(last=False)


async def _execute(execution: dict) -> dict:
    """Sent only by the action engine, after the owner's gesture on this card."""
    key = str(execution["idempotency_key"])
    answer = await client.execute(execution["return_id"], execution["action"], dict(execution["params"]),
                                  idempotency_key=key)
    _remember(key, answer)
    client.forget()                       # the open returns are read whole after a change
    return {"status": str(answer.get("status") or ""), "done": not answer.get("error")}


def _outcome_words(action: str, out: dict[str, Any]) -> str:
    status = out["status"]
    said = f"It is now {views.STATUS_WORDS.get(status, status.replace('_', ' '))}."
    if action in ("approve", "label", "complete", "receive", "cancel") and out["verified"]:
        said += " Read back from Shopify." if action != "label" else " Confirmed."
    elif status == "completed" and not out["verified"]:
        said += " Shopify hasn't shown the money yet; CROOKS Returns will mark it when it does."
    return said


def verify(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    """Proven when the re-read return shows what the service said it did, and the service reported
    no error. A failure carries the service's own words, which the card and the voice say."""
    action = str(execution.get("action") or "")
    out = _OUTCOMES.get(str(execution.get("idempotency_key") or ""))
    if out is None:
        # The answer never came back (the engine settled it by looking): proven only if the return
        # gained an entry of ours and carries no error.
        ours = observed.get("events", 0) > before.get("events", 0) and ":clive:" in str(observed.get("last") or "")
        if ours and not observed.get("error"):
            return True, f"It is now {views.STATUS_WORDS.get(observed.get('status'), observed.get('status'))}."
        return False, "CLIVE lost CROOKS Returns' answer, so check the return before asking again."
    if out["error"]:
        return False, f"CROOKS Returns recorded it, but part of it failed: {client.scrub(out['error'])}"
    if observed.get("status") != out["status"]:
        return False, "The return doesn't show what CROOKS Returns said it did; check it before asking again."
    if action == "note":
        return observed.get("events", 0) > before.get("events", 0), ""
    if out["status"] == out["from"] and not out["replayed"]:
        return False, "CROOKS Returns answered, but the return did not move; check it before asking again."
    return True, _outcome_words(action, out)


def _risk(prepared: Prepared) -> str:
    return "RED" if prepared.summary.get("money_moving") else ""


def _money_facts(held: dict[str, Any]) -> list[dict[str, str]]:
    facts = []
    for key, label in views.MONEY_WORDS:
        amount = client.pence(held.get(key))
        if amount:
            tone = "bad" if key in ("refund_pence",) else ""
            facts.append({"label": label, "value": client.pounds(amount), "tone": tone})
    return facts


def _present(proposal) -> dict:
    s = proposal.summary
    action = str(s.get("action") or "")
    title = TITLES.get(action, "Return")
    if action == "approve" and s.get("mode"):
        title = f"{title} · {MODE_WORDS.get(str(s.get('mode')), s.get('mode'))}"
    facts = [{"label": "Customer", "value": str(s.get("customer") or "")},
             {"label": "Now", "value": str(s.get("status_words") or "")}]
    facts += _money_facts(s.get("money") if isinstance(s.get("money"), dict) else {})
    if s.get("money_moving"):
        facts.append({"label": "Moves money", "value": "yes: hold the card, then tap", "tone": "bad"})
    will = [str(w) for w in s.get("will") or []]
    summary = str(s.get("return_summary") or "")
    return {
        "title": title,
        # The return as the service sums it up, unless the preview already says it word for word.
        "summary": "" if summary and any(summary in w for w in will) else summary,
        # The service's own preview, line for line: what the gesture authorises.
        "body": "\n".join(will),
        "detail": "CROOKS Returns does it, then reads it back from Shopify.",
        "facts": facts[:8],
        "done_title": DONE.get(action, "Done"),
    }


@tool(
    name=WRITE,
    description=("Stage one CROOKS Returns action for the owner's gesture; the service's preview is the card. "
                 "approve (postage_mode), decline/cancel (reason), label (tracking to attach; none buys one), "
                 "tracking, receive (condition, restock, text), complete, note (text). A return's money moves only "
                 "here, never via shopify_refund_create."),
    input_schema={
        "type": "object",
        "properties": {
            "return_id": {"type": "string"},
            "action": {"type": "string", "enum": list(client.ACTIONS)},
            "postage_mode": {"type": "string", "enum": list(POSTAGE_MODES)},
            "condition": {"type": "string", "enum": list(CONDITIONS)},
            "restock": {"type": "boolean"},
            "tracking": {"type": "string", "maxLength": 40},
            "carrier": {"type": "string", "maxLength": 40},
            "reason": {"type": "string", "maxLength": MAX_REASON},
            "text": {"type": "string", "maxLength": MAX_NOTE},
        },
        "required": ["return_id", "action"],
    },
    tier=Tier.AMBER,
    issued_id_args=("return_id",),
    # A read of the return, then the service's preview, which may price a label at Parcel2Go.
    timeout_s=client.READ_TIMEOUT_S + client.PREVIEW_TIMEOUT_S + 2.0,
    write=WriteSpec(
        operation="return_action",
        entity_kind="return",
        entity_arg="return_id",
        mutation="returns:action",
        observe=_observe,
        execute=_execute,
        present=_present,
        verify=verify,
        settle=_settle,
        risk=_risk,
        # The owner's swipe at the tool's own tier; the risk hook makes a money-moving card his hold.
        interaction="swipe_commit",
        op_class="irreversible",
        reversible=False,
        precondition_keys=("status", "money"),
        service=client.NAME,
        says_failure=True,
        spoken_success="Done, on the return for order {label}.",
        spoken_failure="CROOKS Returns didn't confirm that; check the return before asking again.",
        spoken_stale="That return changed since this was prepared, so nothing was sent.",
    ),
)
async def return_action(return_id: str, action: str, postage_mode: str = "", condition: str = "", restock: bool | None = None,
                        tracking: str = "", carrier: str = "", reason: str = "", text: str = "") -> Prepared:
    """Prepare, never send: read the return, ask the service's preview, and stage what it said."""
    if action not in client.ACTIONS:
        raise ToolError(f"action must be one of {', '.join(client.ACTIONS)}.")
    try:
        ret = await client.get_return(return_id)
        params = params_for(action, ret, {"postage_mode": postage_mode, "condition": condition, "restock": restock,
                                          "tracking": tracking, "carrier": carrier, "reason": reason, "text": text})
        said = await client.preview(return_id, action, params)
    except client.ReturnsUnavailable as exc:
        raise _failed(exc) from None
    will = [str(w)[:MAX_WILL_CHARS] for w in (said.get("will") or []) if isinstance(w, str)][:MAX_WILL]
    if not will:
        raise ToolError("CROOKS Returns' preview said nothing it would do, so nothing was prepared.")
    held = said.get("money") if isinstance(said.get("money"), dict) else {}
    status = str(ret.get("status") or "")
    moving = money_moving(action, params)
    number = views.order_number(ret)
    customer = " ".join(str(ret.get("customer_name") or "").split())[:60]
    read_back = f"{TITLES[action].lower()} on order {number.lstrip('#')}"
    if action == "approve":
        read_back += f", {MODE_WORDS[params['postage_mode']]}"
    return Prepared(
        execution={"return_id": str(ret.get("id")), "action": action, "params": params,
                   # This card's own key, made now and used once, when the owner approves it.
                   "idempotency_key": f"clive-{action}-{secrets.token_hex(8)}"},
        before=fingerprint(ret),
        expected_after={},
        entity_ref=str(ret.get("id")),
        entity_label=number or str(ret.get("order_name") or ""),
        summary={
            "action": action, "mode": params.get("postage_mode", ""), "will": will,
            "money": {k: v for k, v in held.items() if client.pence(v) is not None},
            "money_moving": moving, "status_words": views.STATUS_WORDS.get(status, status), "customer": customer,
            "return_summary": " ".join(str(ret.get("summary") or "").split())[:240], "read_back": read_back,
            "pii": [customer] if customer else [],
            "ledger": {"action": action, "money_moving": moving,
                       **{k: v for k, v in held.items() if client.pence(v) and k in ("refund_pence", "credit_pence")}},
        },
    )


# ------------------------------------------------------------------ for the order card and the story


async def returns_on_order(order_number: Any, *, wait_s: float = 2.0) -> dict[str, Any] | None:
    """The returns on one order, for its card: None when CROOKS Returns is not connected (nothing
    to say), {"returns": [...]} when it answered, {"note": ...} when it did not, within `wait_s`."""
    import asyncio

    if not client.read_key():
        return None
    try:
        found = await asyncio.wait_for(client.order_returns(order_number), wait_s)
    except (TimeoutError, client.ReturnsUnavailable) as exc:
        said = str(exc) if isinstance(exc, client.ReturnsUnavailable) else f"{client.NAME} did not answer in time."
        return {"note": said}
    return {"returns": views.on_order(found)}


async def returns_for_story(order_numbers: list[str], *, wait_s: float = 2.0) -> tuple[list[dict[str, Any]], str]:
    """A customer's returns across their recent orders, for their story, and what the source said."""
    import asyncio

    if not client.read_key():
        return [], "not connected"
    numbers = [n for n in dict.fromkeys(order_numbers) if n][:5]
    if not numbers:
        return [], "no orders"
    try:
        found = await asyncio.wait_for(asyncio.gather(*(client.order_returns(n) for n in numbers)), wait_s)
    except (TimeoutError, client.ReturnsUnavailable):
        return [], "unavailable"
    rows = [r for group in found for r in group]
    return rows, f"{len(rows)} return{'s' if len(rows) != 1 else ''}"
