"""Making a discount code (brief §12): the collision read, the workspace, one reviewed create.

"Set up a code for fifteen per cent off until the end of the month" was refused all through
Phase 2 — honestly, because there was no discount tool at all. This is the family that makes
it, and the shape of it answers the two questions that matter before the owner's finger moves:
WHAT does this code do, and IS THAT CODE ALREADY TAKEN.

    the model, or a control       →  shopify_discount_open   a read: is the code taken?
    typing, tapping, speaking     →  discount.field/.choose  the Mac's copy, redrawn
    the hold on the card          →  /actions/…/commit       the one mutation

Four things about it are deliberate.

**The collision is read BEFORE the card, and again at the tap.** Shopify refuses
`discountCodeBasicCreate` for a code that already exists, and a refusal AFTER the owner has
held a card is a worse answer than a sentence saying "SUMMER15 is Mia's summer sale, still
running". So the code is read when the workspace opens, read again whenever the code changes,
and the fingerprint the engine holds the change to says the code did not exist — which makes
"somebody made that code in Admin while the card was up" a STALE proposal and not a failure.

**Nothing here is a question the owner has to answer.** The workspace has every field on it
at once, with what the Mac made of each one, and the ones it cannot prepare from say so on
the card (`_blocked`). Phase 2 asked for the percentage, then the dates, then the limit, in
four round trips to a language model; this asks for none of them and shows all of them.

**The percentage the mutation carries is Shopify's fraction, and the one on the card is the
owner's number.** `DiscountPercentageInput.percentage` is between 0 and 1 — 0.15 is fifteen
per cent — and the reviewed shape in app/clients/shopify.py refuses anything else, because
"15" there is a fifteen-hundred-per-cent discount. The owner types 15 and reads 15%.

**Said out loud, it is the model's.** "Create a code for fifteen per cent off until the end
of the month" goes to Claude like every other sentence, whose job here is exactly the parse a
language model is good at — and its parse lands in a workspace where the owner can see and
correct it, instead of becoming the arguments of a change. The touch route (`discount.open`
and the recipe below) needs no model at all.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from app.actions.models import Observed, Prepared
from app.capabilities.families import CapabilityFamily
from app.capabilities.families import register as register_family
from app.clients.shopify import (
    DISCOUNT_CODE,
    MAX_DISCOUNT_AMOUNT,
    MAX_DISCOUNT_USES,
    ShopifyClient,
    ShopifyError,
)
from app.commands import Command, Outcome
from app.commands import Ctx as CommandCtx
from app.commands import register as register_command
from app.families import _workspace as ws
from app.reads.scheduler import Read, ReadPlan, ReadResult
from app.recipes import CACHE_NONE, Ctx, Recipe, RecipeAnswer, register
from app.tools.gate import Tier
from app.tools.registry import ToolError, WriteSpec, tool
from app.tools.shopify_tools import _c

log = logging.getLogger("crooks.families.discounts")

KIND = "discount"
WORKSPACE_PREFIX = "dsc"
CHECK_TOOL = "shopify_discount_check"
OPEN_TOOL = "shopify_discount_open"
WRITE_TOOL = "shopify_discount_create"
OPERATION = "discount_code_create"
SCOPE = "write_discounts"
READ_SCOPE = "read_discounts"

# The shop's clock. "Until the end of the month" is the owner's month, and a window resolved
# in UTC starts a day early for the hour either side of midnight in summer.
SHOP_TZ = ZoneInfo("Europe/London")

MAX_TITLE_CHARS = 80


# --------------------------------------------------------------------------- the read

DISCOUNT_BY_CODE_QUERY = """
query CrooksDiscountByCode($code: String!) {
  codeDiscountNodeByCode(code: $code) {
    id
    codeDiscount {
      __typename
      ... on DiscountCodeBasic {
        title
        status
        startsAt
        endsAt
        usageLimit
        asyncUsageCount
        customerGets {
          value {
            __typename
            ... on DiscountPercentage { percentage }
            ... on DiscountAmount { amount { amount currencyCode } }
          }
        }
      }
    }
  }
}
"""


def normalise_code(said: str) -> str:
    """A code as Shopify stores it and as a person reads it out: upper case, no spaces.

    A dictated code arrives with the spaces the microphone heard ("summer fifteen" is not
    this function's problem, but "SUMMER 15" is), and a typed one arrives with whatever the
    thumb caught. Both become one token, because a code with a space in it is a code the shop
    cannot say down the phone.
    """
    return re.sub(r"[^A-Z0-9-]", "", str(said or "").upper().replace(" ", ""))[:30]


def value_words(basis: str, amount: float, currency: str) -> str:
    """What the code takes off, as one short string. This IS the verification: it is what the
    fingerprint carries and what the re-read is compared against, so it must be built the
    same way from a fresh read as from the workspace."""
    if basis == "percentage":
        return f"{amount:g}%"
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get(currency.upper(), "")
    return f"{symbol}{amount:,.2f}" if symbol else f"{amount:,.2f} {currency.upper()}"


def _node_value(node: dict[str, Any]) -> str:
    """The same string, from what Shopify answered. `percentage` comes back as the fraction."""
    money = ((node.get("customerGets") or {}).get("value")) or {}
    if money.get("__typename") == "DiscountPercentage":
        try:
            return value_words("percentage", round(float(money["percentage"]) * 100, 4), "")
        except (TypeError, ValueError, KeyError):
            return ""
    amount = money.get("amount") or {}
    try:
        return value_words("amount", float(amount["amount"]), str(amount.get("currencyCode") or "GBP"))
    except (TypeError, ValueError, KeyError):
        return ""


async def _read_by_code(client: ShopifyClient, code: str) -> dict[str, Any] | None:
    """What the shop already has under this code, or None. A read, and the only one this
    family makes: `codeDiscountNodeByCode` is served by `read_discounts`."""
    payload = await client.graphql(DISCOUNT_BY_CODE_QUERY, {"code": code})
    node = (payload.get("data") or {}).get("codeDiscountNodeByCode")
    if not isinstance(node, dict) or not node.get("id"):
        return None
    return node


def code_fingerprint(node: dict[str, Any] | None, code: str) -> dict[str, Any]:
    """What the shop must show for this creation to be the one that was prepared.

    `exists` is the whole precondition: a code created in Admin between the card and the tap
    means this proposal would collide, and Shopify would refuse it after the gesture. The
    value and the status are what the proof reads.
    """
    if node is None:
        return {"exists": False, "code": code, "value": "", "status": ""}
    inner = node.get("codeDiscount") or {}
    return {
        "exists": True, "code": code, "value": _node_value(inner),
        "status": str(inner.get("status") or ""),
    }


@tool(
    name=CHECK_TOOL,
    description="Whether a discount code already exists in the shop, and what it does if it does.",
    input_schema={
        "type": "object",
        "properties": {"code": {"type": "string", "maxLength": 32}},
        "required": ["code"],
    },
    tier=Tier.GREEN,
)
async def shopify_discount_check(code: str) -> dict[str, Any]:
    """The collision read on its own, so that "is SUMMER15 taken?" is answerable without a
    workspace and so the recipe below can re-read it as the code is typed."""
    wanted = normalise_code(code)
    if not wanted:
        raise ToolError("That is not a code I can look up.")
    node = await _read_by_code(_c(), wanted)
    if node is None:
        return {"code": wanted, "taken": False, "note": f"No discount in the shop uses {wanted}."}
    inner = node.get("codeDiscount") or {}
    return {
        "code": wanted, "taken": True, "title": str(inner.get("title") or "")[:MAX_TITLE_CHARS],
        "status": str(inner.get("status") or ""), "takes_off": _node_value(inner),
        "used": inner.get("asyncUsageCount"), "usage_limit": inner.get("usageLimit"),
        "note": f"{wanted} is already in use by {str(inner.get('title') or 'a discount')!r}; pick another code.",
    }


# --------------------------------------------------------------------------- the workspace

_TODAY_HINT = "A date as YYYY-MM-DD, or leave it empty."


def _shop_today() -> date:
    return datetime.now(SHOP_TZ).date()


def _instant(day: date, *, end: bool = False) -> str:
    """A day, as the instant Shopify wants: the shop's own midnight, not UTC's. `end` takes
    the last moment of the day, so "ends on the 30th" includes the 30th."""
    moment = datetime.combine(day, time(23, 59, 59) if end else time(0, 0, 0), tzinfo=SHOP_TZ)
    return moment.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean_code(raw: str) -> tuple[str, str, str]:
    value = normalise_code(raw)
    if not value:
        return "", "invalid", "A code is letters, digits and hyphens — SUMMER15."
    if not DISCOUNT_CODE.match(value):
        return value, "invalid", "Three to thirty characters, starting with a letter or a digit."
    return value, "ok", ""


def _clean_number(raw: str) -> tuple[str, str, str]:
    said = str(raw or "").strip().replace(",", "").lstrip("£$€").rstrip("%")
    if not said:
        return "", "invalid", "How much it takes off."
    try:
        amount = round(float(said), 2)
    except ValueError:
        return said[:10], "invalid", f"{said[:20]!r} is not a number."
    if amount <= 0:
        return f"{amount:g}", "invalid", "It has to take something off."
    return f"{amount:g}", "ok", ""


def _clean_currency(raw: str) -> tuple[str, str, str]:
    """Three letters, and the length is checked BEFORE anything is truncated: "pounds"
    truncated to three characters is "POU", which is not a currency and would have gone to
    Shopify looking exactly like one."""
    value = re.sub(r"[^A-Z]", "", str(raw or "").upper())
    if len(value) != 3:
        return value[:3], "invalid", "Three letters — GBP, USD, EUR."
    return value, "ok", ""


def _clean_day(raw: str) -> tuple[str, str, str]:
    said = str(raw or "").strip()
    if not said:
        return "", "ok", ""
    try:
        day = date.fromisoformat(said)
    except ValueError:
        return said[:10], "invalid", _TODAY_HINT
    return day.isoformat(), "ok", ""


def _clean_uses(raw: str) -> tuple[str, str, str]:
    said = re.sub(r"[^0-9]", "", str(raw or ""))
    if not said:
        return "", "ok", ""
    uses = int(said)
    if not 1 <= uses <= MAX_DISCOUNT_USES:
        return said[:5], "invalid", f"Between 1 and {MAX_DISCOUNT_USES:,} uses."
    return str(uses), "ok", ""


FIELDS: tuple[ws.Field, ...] = (
    ws.Field(name="code", label="Code", kind="code", placeholder="SUMMER15", maxlength=30, clean=_clean_code),
    ws.Field(name="value", label="Takes off", kind="money", placeholder="15", maxlength=10, clean=_clean_number),
    ws.Field(name="currency", label="Currency", kind="code", placeholder="GBP", maxlength=3, clean=_clean_currency),
    ws.Field(name="starts", label="Starts", kind="code", placeholder="today", maxlength=10, clean=_clean_day),
    ws.Field(name="ends", label="Ends", kind="code", placeholder="no end", maxlength=10, clean=_clean_day),
    ws.Field(name="uses", label="Total uses", kind="quantity", placeholder="no limit", maxlength=5, clean=_clean_uses),
)
FIELD_NAMES = tuple(f.name for f in FIELDS)

CHOICES: tuple[ws.Choice, ...] = (
    ws.Choice(name="basis", label="What it takes off", options=(("percentage", "Per cent"), ("amount", "Money"))),
    ws.Choice(name="each", label="Who may use it",
              options=(("anyone", "Anyone, any number of times"), ("once", "Once per customer"))),
)


def _amount(workspace: dict[str, Any]) -> float | None:
    try:
        return round(float(ws.value(workspace, "value")), 2)
    except (TypeError, ValueError):
        return None


def _blocked(workspace: dict[str, Any]) -> str:
    """Why this cannot be prepared yet, in the owner's words. Empty when it can.

    Every one of these is a sentence on the card rather than a refusal after a gesture: a
    form that lets you press the button and then says no is a form that wasted the gesture.
    """
    code = ws.value(workspace, "code")
    if not code or ws.status(workspace, "code") != "ok":
        return "It needs a code customers can type."
    taken = ws.fact(workspace, "taken_by")
    if taken:
        return f"{code} is already in use by {str(taken)!r}. Pick another code."
    basis = ws.chosen(workspace, "basis", "percentage")
    amount = _amount(workspace)
    if amount is None or ws.status(workspace, "value") != "ok":
        return "It needs a percentage, or an amount to take off."
    if basis == "percentage" and not 0 < amount <= 100:
        return "A percentage is between 1 and 100."
    if basis == "amount":
        if not 0 < amount <= MAX_DISCOUNT_AMOUNT:
            return f"An amount off is between 0.01 and {MAX_DISCOUNT_AMOUNT:,.0f}."
        if ws.status(workspace, "currency") != "ok":
            return "An amount off needs a currency — GBP."
    for day in ("starts", "ends"):
        if ws.status(workspace, day) != "ok":
            return f"The {day} date is not a date I can read. {_TODAY_HINT}"
    if ws.status(workspace, "uses") != "ok":
        return "The number of uses is not a number."
    window = _window(workspace)
    if window[1] and window[1] <= window[0]:
        return "It would end before it started."
    return ""


def _window(workspace: dict[str, Any]) -> tuple[date, date | None]:
    starts = ws.value(workspace, "starts")
    ends = ws.value(workspace, "ends")
    try:
        first = date.fromisoformat(starts) if starts else _shop_today()
    except ValueError:
        first = _shop_today()
    try:
        last = date.fromisoformat(ends) if ends else None
    except ValueError:
        last = None
    return first, last


def _window_words(workspace: dict[str, Any]) -> str:
    first, last = _window(workspace)
    today = _shop_today()
    lead = "from today" if first <= today else f"from {first.isoformat()}"
    return f"{lead} until the end of {last.isoformat()}" if last else f"{lead}, with no end date"


def _title(workspace: dict[str, Any]) -> str:
    """The discount's name in Admin. Built from what the code does, never from the model: a
    title is what the owner will scan a list of discounts by."""
    basis = ws.chosen(workspace, "basis", "percentage")
    amount = _amount(workspace) or 0.0
    return f"{value_words(basis, amount, ws.value(workspace, 'currency', 'GBP'))} off — {ws.value(workspace, 'code')}"[:MAX_TITLE_CHARS]


def _facts(workspace: dict[str, Any]) -> list[dict[str, Any]]:
    basis = ws.chosen(workspace, "basis", "percentage")
    amount = _amount(workspace)
    taken = ws.fact(workspace, "taken_by")
    checked = ws.fact(workspace, "checked_code")
    rows: list[dict[str, Any]] = []
    if amount is not None:
        rows.append({"label": "Takes off", "value": value_words(basis, amount, ws.value(workspace, "currency", "GBP"))})
    rows.append({"label": "When", "value": _window_words(workspace)})
    uses = ws.value(workspace, "uses")
    rows.append({"label": "Uses", "value": f"{uses} in total" if uses else "no limit"})
    if ws.chosen(workspace, "each", "anyone") == "once":
        rows.append({"label": "Per customer", "value": "once each"})
    if taken:
        rows.append({"label": "That code", "value": f"already {str(taken)!r}", "tone": "bad"})
    elif checked:
        rows.append({"label": "That code", "value": f"free — nothing in the shop uses {checked}", "tone": "ok"})
    return rows


def _notes(workspace: dict[str, Any]) -> list[str]:
    notes = [
        "It applies to everything in the shop and combines with nothing else — not with "
        "another code, not with an automatic discount, not with a shipping discount.",
        "A code cannot be edited from here once it exists; it can be deactivated in Admin.",
    ]
    if not ws.fact(workspace, "checked_code"):
        notes.append("The code has not been checked against the shop yet.")
    return notes


ACTIONS: tuple[ws.Action, ...] = (
    ws.Action(id="prepare", label="Prepare the code", command="discount.stage", risk="red"),
    ws.Action(id="discard", label="Discard", command="discount.discard"),
)
# What the card says when a hold card prepared from it was withdrawn because it changed.
CHANGED = "The code changed — prepare it again."


def _makes(workspace: dict[str, Any]) -> dict[str, Any]:
    """What this card would make (app/families/_workspace.py `makes`): the code, what it takes
    off, when, how often — every field and choice on it, each of which goes into the code."""
    return {"values": dict(workspace.get("values") or {}), "choices": dict(workspace.get("choices") or {})}


ws.makes(KIND, _makes)


def created(workspace: dict[str, Any] | None) -> str:
    """Why nothing more may be done to this card — the code exists, or it left and was not
    proven — or "" while it is still his to write (app/families/_workspace.py "made once")."""
    made = ws.finished(workspace)
    if made is None:
        return ""
    code = ws.value(workspace, "code") or "That code"
    if made.get("state") == ws.DONE:
        return f"{code} is created; another discount is a new code — open a new one."
    return f"{code} was sent to Shopify and it has not said whether it was made; look in Admin before making it again."


def _created_surface(workspace: dict[str, Any], made: dict[str, str]):
    """The card once its code exists: the code, what it takes off and when, and nothing to type,
    tap or prepare. The same card in the same place."""
    code = ws.value(workspace, "code")
    done = made.get("state") == ws.DONE
    facts = [{"label": "Takes off", "value": str(made.get("takes_off") or "")},
             {"label": "Status", "value": str(made.get("status") or "").lower() or "created", "tone": "ok"}] if done \
        else [{"label": "Code", "value": "sent to Shopify; it has not said whether it made it", "tone": "warn"}]
    return ws.surface(
        workspace, fields=(), choices=(),
        kicker="Discount code · created" if done else "Discount code · sent, not confirmed",
        title=code or "A discount code", subtitle=_window_words(workspace),
        facts=[f for f in facts if f["value"]], actions=(),
        notes=["It cannot be edited from here; it can be deactivated in Admin."] if done
        else ["Look at the discounts in Admin before making it again."],
        settled="created" if done else "unconfirmed",
        spoken=f"{code} is created." if done else "Sent to Shopify, not confirmed.",
    )


def workspace_surface(workspace: dict[str, Any]):
    made = ws.finished(workspace)
    if made is not None:
        return _created_surface(workspace, made)
    blocked = _blocked(workspace)
    code = ws.value(workspace, "code")
    notes = _notes(workspace)
    if ws.failed(workspace):
        notes = [f"The code was not created: {ws.failed(workspace)}. Nothing was made; prepare it again.", *notes]
    return ws.surface(
        workspace, fields=FIELDS, choices=CHOICES,
        kicker="Discount code · not created",
        title=code or "A discount code",
        subtitle=_window_words(workspace),
        facts=_facts(workspace), notes=notes, actions=ACTIONS,
        field_command="discount.field", blocked=blocked,
        spoken="Nothing is created until you hold the card that follows.",
    )


def _spoken(workspace: dict[str, Any]) -> str:
    """What is said when the workspace goes up. The grounded half of the answer: every word
    of it is the Mac's own reading of the shop and of what has been filled in."""
    code = ws.value(workspace, "code") or "no code yet"
    blocked = _blocked(workspace)
    if blocked:
        return f"{code}: {blocked} Nothing is created."
    amount = _amount(workspace) or 0.0
    takes = value_words(ws.chosen(workspace, "basis", "percentage"), amount, ws.value(workspace, "currency", "GBP"))
    return (
        f"{code} would take {takes} off, {_window_words(workspace)}. "
        f"Nothing in the shop uses that code. Nothing is created until you hold the card."
    )


# --------------------------------------------------------------------------- the read tools


def _session_and_branch() -> tuple[Any, Any]:
    from app.tools.context import CURRENT_SESSION, acting_branch

    session = CURRENT_SESSION.get()
    if session is None:
        raise ToolError("There is no conversation to write a discount in.")
    return session, session.branch(acting_branch(session))


async def _fill_collision(workspace: dict[str, Any]) -> None:
    """Read the shop for the code now in the workspace and record what it found. Best effort:
    a Shopify that will not answer leaves `checked_code` empty, the card says the code has
    not been checked, and `_blocked` does not claim it is free."""
    code = ws.value(workspace, "code")
    if not code or ws.status(workspace, "code") != "ok":
        workspace["facts"].pop("checked_code", None)
        workspace["facts"].pop("taken_by", None)
        return
    try:
        node = await _read_by_code(_c(), code)
    except (ShopifyError, ToolError) as exc:
        log.info("the discount collision read did not answer: %s", exc)
        workspace["facts"].pop("checked_code", None)
        workspace["facts"].pop("taken_by", None)
        return
    workspace["facts"]["checked_code"] = code
    if node is None:
        workspace["facts"].pop("taken_by", None)
    else:
        workspace["facts"]["taken_by"] = str((node.get("codeDiscount") or {}).get("title") or "a discount")[:MAX_TITLE_CHARS]


@tool(
    name=OPEN_TOOL,
    description=(
        "Put a discount code on the owner's screen as fields, after reading whether the shop "
        "already uses that code, and return its workspace_id. Creates nothing."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "maxLength": 32},
            "percent": {"type": "number", "minimum": 0.01, "maximum": 100, "description": "Per cent off: 15, not 0.15."},
            "amount": {"type": "number", "minimum": 0.01, "maximum": MAX_DISCOUNT_AMOUNT, "description": "Money off instead."},
            "starts": {"type": "string", "maxLength": 10, "description": "YYYY-MM-DD; today if unsaid."},
            "ends": {"type": "string", "maxLength": 10, "description": "YYYY-MM-DD."},
            "uses": {"type": "integer", "minimum": 1, "maximum": MAX_DISCOUNT_USES},
            "once_each": {"type": "boolean", "description": "One use per customer."},
        },
        "required": ["code"],
    },
    tier=Tier.GREEN,
)
async def shopify_discount_open(
    code: str, percent: float | None = None, amount: float | None = None, starts: str = "",
    ends: str = "", uses: int | None = None, once_each: bool = False,
) -> dict[str, Any]:
    """The workspace, opened by the model from what the owner said. A READ tool because it
    reads and changes nothing outside the Mac: the shop is asked whether the code is taken,
    the branch gets a context, the session is issued its id, the card goes up.

    That id is what lets `shopify_discount_create` be staged at all — the gate holds it to
    this conversation like any other issued id — so a code can only be prepared from a
    workspace whose card the owner has already read.
    """
    session, branch = _session_and_branch()
    money = amount is not None and percent is None
    workspace = ws.open_workspace(
        branch, kind=KIND, workspace_id=ws.new_id(WORKSPACE_PREFIX),
        values={
            "code": "", "value": "", "currency": "GBP",
            "starts": "", "ends": "", "uses": "",
        },
        choices={"basis": "amount" if money else "percentage", "each": "once" if once_each else "anyone"},
    )
    for name, raw in (
        ("code", code), ("value", amount if money else percent), ("starts", starts),
        ("ends", ends), ("uses", uses),
    ):
        if raw not in (None, ""):
            ws.type_into(workspace, FIELDS, name, str(raw))
    await _fill_collision(workspace)
    session.issue(str(workspace["workspace_id"]))
    surface = workspace_surface(workspace)
    return {
        "workspace_id": str(workspace["workspace_id"]),
        "code": ws.value(workspace, "code"),
        "taken_by": ws.fact(workspace, "taken_by") or None,
        "blocked": _blocked(workspace),
        "when": _window_words(workspace),
        "_surfaces": [surface.as_ui()],
        "staged": False,
        "note": (
            "The discount is on the owner's screen and nothing is created. The owner's gesture "
            "on Prepare the code stages it; a hold on the card that follows creates it."
        ),
    }


# --------------------------------------------------------------------------- the write


async def _observe(execution: dict) -> Observed:
    node = await _read_by_code(_c(), str(execution["code"]))
    entity = None
    if node is not None:
        inner = node.get("codeDiscount") or {}
        entity = {
            "discount_id": str(node.get("id") or ""), "code": str(execution["code"]),
            "title": str(inner.get("title") or "")[:MAX_TITLE_CHARS],
            "status": str(inner.get("status") or ""), "takes_off": _node_value(inner),
        }
    return Observed(fingerprint=code_fingerprint(node, str(execution["code"])), entity=entity)


async def _execute(execution: dict) -> dict:
    payload = await ws.sending(str(execution.get("workspace_id") or ""),
                               _c().mutate("discount_code_create", {"basicCodeDiscount": dict(execution["input"])}))
    node = ((payload.get("data") or {}).get("discountCodeBasicCreate") or {}).get("codeDiscountNode") or {}
    if not node.get("id"):
        raise ShopifyError("Shopify did not confirm the discount was created.")
    # Shopify has said which discount it made: the code exists, proven or not.
    ws.note(str(execution.get("workspace_id") or ""), ws.DONE, code=str(execution.get("code") or ""))
    return {"discount_id": str(node["id"])}


def _verify(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    """Proof, by reading the code back out of the shop: it resolves to a discount now, it is
    the code that was asked for, and it takes off what was on the card.

    "A discount with that code exists" would have passed before the change was sent, since
    the precondition is that it did NOT — so the value is checked too, which is what tells a
    code this proposal made from one somebody else made in the same second.
    """
    if not observed.get("exists"):
        return False, ""
    if str(observed.get("code") or "") != str(execution.get("code") or ""):
        return False, ""
    if str(observed.get("value") or "") != str(execution.get("value_words") or ""):
        return False, ""
    status = str(observed.get("status") or "").upper()
    if status and status not in ("ACTIVE", "SCHEDULED"):
        # Created, and not usable: an expired window, or a shop that has turned it off. The
        # change landed and the card says to look, which is not the same as a failure.
        return True, f"Shopify reports it as {status.lower()}; check the dates."
    if status == "SCHEDULED" and not execution.get("scheduled"):
        return True, "it is scheduled rather than live; check the start date."
    return True, ""


def _present(proposal) -> dict:
    s = proposal.summary
    facts = [
        {"label": "Code", "value": str(s.get("code") or "")},
        {"label": "Takes off", "value": str(s.get("value_words") or ""), "tone": "warn"},
        {"label": "Applies to", "value": "everything in the shop"},
        {"label": "When", "value": str(s.get("when") or "")},
        {"label": "Uses", "value": str(s.get("uses_words") or "")},
        {"label": "Combines with", "value": "nothing else"},
        {"label": "That code now", "value": str(s.get("collision") or "")},
    ]
    return {
        "title": "Create the discount code",
        "summary": "",
        "detail": "Anyone with the code can use it the moment it exists. It cannot be undone from here; it can be deactivated in Admin.",
        "facts": facts,
        "done_title": "Discount created",
    }


@tool(
    name=WRITE_TOOL,
    description="Prepare the discount code the owner has on screen. Needs the workspace_id from shopify_discount_open.",
    input_schema={
        "type": "object",
        "properties": {"workspace_id": {"type": "string", "description": "From shopify_discount_open."}},
        "required": ["workspace_id"],
    },
    tier=Tier.RED,
    issued_id_args=("workspace_id",),
    write=WriteSpec(
        operation=OPERATION,
        entity_kind="discount",
        entity_arg="workspace_id",
        mutation="discount_code_create",
        observe=_observe,
        execute=_execute,
        present=_present,
        verify=_verify,
        op_class="irreversible",
        reversible=False,
        # The precondition is the collision and nothing else: a value read alongside it must
        # not make an absent code look like a changed one.
        precondition_keys=("exists", "code"),
        spoken_success="{label} is live — {to} off.",
        spoken_failure="I couldn't confirm the code was created. Look at the discounts in Admin before asking again.",
        spoken_stale="Somebody created that code since this was prepared, so I haven't sent it.",
    ),
)
async def shopify_discount_create(workspace_id: str) -> Prepared:
    """Prepare, never create: read the code out of the shop one more time, build the reviewed
    input from the MAC's copy of the workspace, and hand the engine a change to hold.

    Not one value here comes from the tablet or from the model at this point. The tablet
    posted a workspace id; the model, if it was the model, posted the same. Everything else —
    the code, the fraction Shopify wants, the instants the window becomes, the title — is
    built from the dictionary the Mac has been validating keystroke by keystroke.
    """
    _session, branch = _session_and_branch()
    workspace = ws.held(branch, KIND, str(workspace_id))
    if workspace is None:
        raise ToolError("There is no discount open on this half to create.")
    if created(workspace):
        raise ToolError(created(workspace))
    blocked = _blocked(workspace)
    if blocked:
        raise ToolError(blocked)

    code = ws.value(workspace, "code")
    # The collision, read again at the moment of preparing. The fingerprint below holds the
    # change to it as well, so a code made between here and the tap is STALE rather than a
    # refusal from Shopify after the owner's hold.
    existing = await _read_by_code(_c(), code)
    if existing is not None:
        title = str((existing.get("codeDiscount") or {}).get("title") or "a discount")[:MAX_TITLE_CHARS]
        workspace["facts"]["checked_code"] = code
        workspace["facts"]["taken_by"] = title
        raise ToolError(f"{code} is already in use by {title!r}; nothing was created. Pick another code.")

    basis = ws.chosen(workspace, "basis", "percentage")
    amount = _amount(workspace) or 0.0
    currency = ws.value(workspace, "currency", "GBP")
    first, last = _window(workspace)
    uses = ws.value(workspace, "uses")
    once = ws.chosen(workspace, "each", "anyone") == "once"
    words = value_words(basis, amount, currency)

    discount_input: dict[str, Any] = {
        "title": _title(workspace),
        "code": code,
        "startsAt": _instant(first),
        "customerSelection": {"all": True},
        "customerGets": {
            # Shopify's own fraction for a percentage — 0.15 is fifteen per cent — and a
            # plain decimal string for money. The reviewed shape refuses the other reading.
            "value": ({"percentage": round(amount / 100.0, 6)} if basis == "percentage"
                      else {"discountAmount": {"amount": f"{amount:.2f}", "appliesOnEachItem": False}}),
            "items": {"all": True},
        },
        "combinesWith": {"orderDiscounts": False, "productDiscounts": False, "shippingDiscounts": False},
        "appliesOncePerCustomer": once,
    }
    if last is not None:
        discount_input["endsAt"] = _instant(last, end=True)
    if uses:
        discount_input["usageLimit"] = int(uses)

    scheduled = first > _shop_today()
    uses_words = f"{uses} in total" if uses else "no limit"
    if once:
        uses_words = f"{uses_words}, once per customer"
    read_back = f"create the code {code} for {words} off, {_window_words(workspace)}"
    ws.prepared(workspace)
    return Prepared(
        execution={
            "workspace_id": str(workspace["workspace_id"]),
            "code": code,
            "value_words": words,
            "scheduled": scheduled,
            "input": discount_input,
        },
        before=code_fingerprint(None, code),
        expected_after={
            "exists": True, "code": code, "value": words,
            "status": "SCHEDULED" if scheduled else "ACTIVE",
        },
        # There is no Shopify id to name yet: the workspace IS the thing being authorised,
        # which is why its id is the one the gate held to this conversation.
        entity_ref=str(workspace["workspace_id"]),
        entity_label=code,
        summary={
            "code": code,
            "value_words": words,
            "basis": basis,
            "currency": currency,
            "when": _window_words(workspace),
            "uses_words": uses_words,
            "collision": f"free — nothing in the shop uses {code}",
            "amount": f"{amount:.2f}",
            "read_back": read_back,
            "spoken_to": words,
            "ledger": {"basis": basis[:24], "value": f"{amount:.2f}", "currency": currency[:24], "uses": int(uses or 0)},
        },
    )


# --------------------------------------------------------------------------- the commands


def _no_workspace() -> Outcome:
    return Outcome.refused("no_workspace", "There is no discount open on this half to do that to.")


def _open(ctx: CommandCtx) -> Outcome:
    """A control — the capability card's, or a dock landing's. Opens an EMPTY workspace and
    reads nothing: a command is synchronous by design (app/commands.py), and with no code in
    it yet there is nothing to check against the shop. The first code typed is what names the
    recipe below, and that is where the read happens."""
    workspace = ws.open_workspace(
        ctx.branch, kind=KIND, workspace_id=ws.new_id(WORKSPACE_PREFIX),
        values={"code": "", "value": "", "currency": "GBP", "starts": "", "ends": "", "uses": ""},
        choices={"basis": "percentage", "each": "anyone"},
    )
    # Issued here as well as by the read tool: the staging command checks the id against this
    # conversation, and a workspace opened by touch is as much this conversation's as one
    # opened by the model.
    ctx.session.issue(str(workspace["workspace_id"]))
    return Outcome(answer="A discount code, with nothing in it yet. Type the code and what it takes off.",
                   surfaces=[workspace_surface(workspace)],
                   changed={"workspace_id": str(workspace["workspace_id"]), "kind": KIND})


def _field(ctx: CommandCtx) -> Outcome:
    """A precision field on the workspace, typed.

    The tablet posts a workspace id, a field NAME from the family's own closed set, and the
    characters. It does not post an execution argument, and nothing it posts is sent
    anywhere: the Mac validates the value into its own copy and answers with the card again.

    When the CODE changes, the answer needs a read — is that code taken? — and a command
    cannot read. So this names the recipe below and `app/routes/command.py` runs it through
    the read scheduler, with no model on the path.
    """
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id") or ctx.arg("compose_id"))
    if workspace is None:
        return _no_workspace()
    if created(workspace):
        return Outcome.refused("already_created", created(workspace))
    name = ctx.arg("field")
    before, was = ws.card_state(workspace), ws.value(workspace, name)
    ok, why = ws.type_into(workspace, FIELDS, name, str(ctx.args.get("value") or ""))
    if not ok:
        return Outcome.refused("unknown_field", why)
    # Withdrawn only when the code it would make changes: the same value typed again is not.
    gone = ws.touched(ctx.session, workspace, CHANGED, before=before)
    withdrew = {"withdrawn": gone, "withdrawn_words": CHANGED} if gone else {}
    if name == "code" and ws.value(workspace, "code") != was:
        # The code moved: what the card says about the collision is now about the old one.
        workspace["facts"].pop("checked_code", None)
        workspace["facts"].pop("taken_by", None)
        if ws.status(workspace, "code") == "ok":
            return Outcome(answer="", changed={"recipe": "discount_code", "workspace_id": str(workspace["workspace_id"]),
                                               "field": name, "status": ws.status(workspace, name), **withdrew})
    return Outcome(answer="", surfaces=[workspace_surface(workspace)],
                   changed={"workspace_id": str(workspace["workspace_id"]), "field": name,
                            "status": ws.status(workspace, name), **withdrew})


def _choose(ctx: CommandCtx) -> Outcome:
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id"))
    if workspace is None:
        return _no_workspace()
    if created(workspace):
        return Outcome.refused("already_created", created(workspace))
    before = ws.card_state(workspace)
    ok, why = ws.choose(workspace, CHOICES, ctx.arg("field"), ctx.arg("option"))
    if not ok:
        return Outcome.refused("unknown_choice", why)
    gone = ws.touched(ctx.session, workspace, CHANGED, before=before)
    return Outcome(answer="", surfaces=[workspace_surface(workspace)],
                   changed={"workspace_id": str(workspace["workspace_id"]), "chose": ctx.arg("option"),
                            **({"withdrawn": gone, "withdrawn_words": CHANGED} if gone else {})})


def _stage(ctx: CommandCtx) -> Outcome:
    """Prepare the code, tapped. Prepares the change; creates nothing.

    The staging itself happens in `POST /command` (`changed["stage"]`), because a command is
    synchronous and preparing a change is a fresh read of the shop. What crosses that line is
    a registered write tool's NAME and one id — never a value, and never anything the tablet
    posted that has not been through the field's own `clean`.
    """
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id"))
    if workspace is None:
        return _no_workspace()
    if created(workspace):
        return Outcome.refused("already_created", created(workspace))
    blocked = _blocked(workspace)
    if blocked:
        return Outcome.refused("not_ready", blocked)
    ident = str(workspace["workspace_id"])
    if ident not in (getattr(ctx.session, "issued_ids", None) or frozenset()):
        return Outcome.refused("not_held", "That is not a discount this conversation opened.")
    return Outcome(answer="", changed={
        "workspace_id": ident,
        "stage": {"tool": WRITE_TOOL, "args": {"workspace_id": ident},
                  "what": f"create the code {ws.value(workspace, 'code')}"},
    })


def _discard(ctx: CommandCtx) -> Outcome:
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id"))
    if workspace is None:
        return _no_workspace()
    made = ws.finished(workspace)
    gone = ws.withdraw(ctx.session, workspace, "The code was discarded.")
    ws.discard(ctx.branch)
    if made is not None:
        return Outcome(answer="The card is put away; the code it made stays." if made.get("state") == ws.DONE
                       else "The card is put away. Look in Admin for the code it was sending.",
                       changed={"workspace": None, "discarded": str(workspace["workspace_id"])})
    return Outcome(answer="Gone. Nothing was created.",
                   changed={"workspace": None, "discarded": str(workspace["workspace_id"]),
                            **({"withdrawn": gone, "withdrawn_words": "The code was discarded."} if gone else {})})


# Touch only, all five. A spoken instruction to make a discount is a model turn, and Claude
# calls `shopify_discount_open`.
register_command(Command("discount.open", "Start a discount code", _open, voice=False))
register_command(Command("discount.field", "Type into the discount being written", _field, voice=False))
register_command(Command("discount.choose", "Pick what the discount takes off", _choose, voice=False))
register_command(Command("discount.stage", "Prepare the discount code for authorising", _stage, voice=False))
register_command(Command("discount.discard", "Throw away the discount being written", _discard, voice=False))


# --------------------------------------------------------------------------- the recipe
#
# One read, run for a tap: is the code that has just been typed taken? It redraws the same
# workspace with what the shop said, and it stages nothing and cannot — a recipe naming a
# write tool is a crash at start-up (app/recipes.py assert_read_only).


def _plan(ctx: Ctx) -> ReadPlan | None:
    workspace = ws.held(ctx.branch, KIND)
    if workspace is None:
        return None
    code = ws.value(workspace, "code")
    if not code:
        return None
    return ReadPlan([Read("discount", CHECK_TOOL, {"code": code}, source="shopify", cost=60.0, optional=False)],
                    label="discount_code")


def _render(ctx: Ctx, result: ReadResult) -> RecipeAnswer:
    workspace = ws.held(ctx.branch, KIND)
    if workspace is None:
        return RecipeAnswer(answer="", defer="the discount was closed while the shop was being read")
    if created(workspace):
        # Made while this was being read: nothing read now goes onto it.
        return RecipeAnswer(answer=created(workspace), calls=list(result.calls), drawn=[],
                            surfaces=[workspace_surface(workspace)], partial=result.partial)
    body = result.values.get("discount")
    if isinstance(body, dict) and str(body.get("code") or "") == ws.value(workspace, "code"):
        workspace["facts"]["checked_code"] = str(body["code"])
        if body.get("taken"):
            workspace["facts"]["taken_by"] = str(body.get("title") or "a discount")[:MAX_TITLE_CHARS]
        else:
            workspace["facts"].pop("taken_by", None)
    return RecipeAnswer(
        answer=_spoken(workspace), calls=list(result.calls), drawn=[],
        surfaces=[workspace_surface(workspace)], partial=result.partial,
        trace={"code": ws.value(workspace, "code"), "taken": bool(ws.fact(workspace, "taken_by"))},
    )


register(Recipe(
    recipe_id="discount_code",
    read_primitives=(CHECK_TOOL,), parallel_nodes=(("discount",),), ui="workspace",
    # Never cached: whether a code is taken is exactly what must not be stale on the card the
    # owner is about to authorise a creation from.
    cache_policy=CACHE_NONE, target_ms=900,
    plan=_plan, render=_render,
))

# --------------------------------------------------------------------------- the capability


async def _probe(runtime: Any) -> dict[str, Any]:
    """Whether this Mac could create a discount code right now. One read — the scopes the
    store has granted, cached with the rest of the capability table — and never a mutation.

    The two grants are told apart deliberately. Without `write_discounts` nothing can be
    created and the family says so, names the scope, and `runtime.withheld_by_family()` stops
    the model being offered the write tool at all. Without `read_discounts` the collision
    read cannot be made — and a discount family that cannot say whether a code is taken is
    worse than one that says it cannot, because Shopify would refuse the creation after the
    owner had held the card.
    """
    try:
        granted = set(await runtime.shopify.access_scopes())
    except Exception as exc:  # noqa: BLE001 — Shopify not answering is not a missing grant
        return {"state": "TEMPORARILY_UNAVAILABLE",
                "detail": f"the Shopify scope check did not answer ({type(exc).__name__})", "scope": SCOPE}
    if SCOPE not in granted:
        return {"state": "MISSING_SCOPE",
                "detail": f"the store has not granted {SCOPE}; add it on the Dev Dashboard and approve it in the store admin",
                "scope": SCOPE}
    if READ_SCOPE not in granted:
        return {"state": "MISSING_SCOPE",
                "detail": (f"the store has granted {SCOPE} but not {READ_SCOPE}, so I cannot tell you whether a "
                           "code is already taken before creating it"),
                "scope": READ_SCOPE}
    return {"state": "READY", "detail": "ready — a discount code can be created", "scope": SCOPE}


register_family(CapabilityFamily(
    key="discount_create",
    label="Discount codes",
    area="orders",
    what="Create a discount code — a percentage or an amount off, with dates and a usage limit — after checking the code is free",
    operations=(OPERATION,),
    tools=(CHECK_TOOL, OPEN_TOOL, WRITE_TOOL),
    scopes=(SCOPE,),
    state="READY",
    probe=_probe,
))

__all__ = [
    "CHECK_TOOL", "FIELDS", "KIND", "OPEN_TOOL", "OPERATION", "SCOPE", "WRITE_TOOL",
    "code_fingerprint", "normalise_code", "value_words", "workspace_surface",
]
