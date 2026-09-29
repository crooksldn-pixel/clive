"""Putting store credit on a customer's account (brief §13), if the store has it at all.

The brief's instruction about this one is the interesting part: implement it only if the
2025-07 Admin API and the store's configuration genuinely permit it, and if they do not, do
NOT fake it — say what feature is unavailable, what is required, and whether the code exists
and the permission does not.

Both halves are here, and they are told apart by a READ rather than by a guess:

* the API half is real. `storeCreditAccountCredit` is in Admin API 2025-07, it takes a
  customer (or an account) and a money amount, and it is a reviewed mutation in
  app/clients/shopify.py like every other change this build makes.
* the STORE half cannot be assumed. Store credit is not on every shop, and a shop that has
  the grant may still have no store credit accounts. So `_probe` reads two things — the
  scope, and whether the shop actually answers with a store credit account for a customer —
  and reports:

      MISSING_SCOPE           the code is here, `write_store_credit_account_transactions`
                              is not granted, and the card names it
      NOT_SUPPORTED_BY_STORE  the grant is there and the shop does not serve the field:
                              store credit is not available on this store
      TEMPORARILY_UNAVAILABLE the shop did not answer the probe
      READY                   both

That is the difference the brief asks for between "we cannot do this" and "you have not let
us do this", and it is a difference the owner can act on.

The change itself is money that can be spent, so it is the gravest thing here: RED, `money`,
a hold and a drag onto the target. The balance is read before the card, held to as the
precondition — so a credit spent or added in Admin between the card and the tap is STALE and
nothing is sent — and read again to prove the new one.
"""

from __future__ import annotations

import logging
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.actions.models import Observed, Prepared
from app.capabilities.families import CapabilityFamily
from app.capabilities.families import register as register_family
from app.clients.shopify import MAX_STORE_CREDIT, ShopifyClient, ShopifyError
from app.commands import Command, Outcome, may_open
from app.commands import Ctx as CommandCtx
from app.commands import register as register_command
from app.families import _workspace as ws
from app.tools.gate import Tier
from app.tools.registry import ToolError, WriteSpec, tool
from app.tools.shopify_tools import _c

log = logging.getLogger("crooks.families.store_credit")

KIND = "store_credit"
WORKSPACE_PREFIX = "crd"
OPEN_TOOL = "shopify_store_credit"
WRITE_TOOL = "shopify_store_credit_add"
OPERATION = "store_credit_credit"
SCOPE = "write_store_credit_account_transactions"
READ_SCOPE = "read_store_credit_accounts"

# What the assistant says when the store does not have the feature. Held once so the probe,
# the workspace and the model's copy cannot say three different things about it.
NOT_ON_THIS_STORE = (
    "This store does not have store credit: Shopify did not return a store credit account "
    "for a customer. The code for it is here and reviewed; nothing is missing but the store's "
    "own configuration, and Shopify enables store credit per store."
)

STORE_CREDIT_QUERY = """
query CrooksStoreCredit($id: ID!) {
  customer(id: $id) {
    id
    displayName
    defaultEmailAddress { emailAddress }
    storeCreditAccounts(first: 5) {
      edges { node { id balance { amount currencyCode } } }
    }
  }
}
"""


def _amount_of(node: Any) -> float | None:
    try:
        return round(float((node or {})["amount"]), 2)
    except (TypeError, KeyError, ValueError):
        return None


def display(amount: float | None, currency: str = "GBP") -> str:
    if amount is None:
        return "—"
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get(currency.upper())
    return f"{symbol}{amount:,.2f}" if symbol else f"{amount:,.2f} {currency}"


class StoreCreditUnavailable(ToolError):
    """The store does not offer store credit. Not a failure to report as one: the code is
    here, the mutation is reviewed, and what is absent is the store's own configuration."""


async def read_accounts(client: ShopifyClient, customer_id: str) -> dict[str, Any]:
    """The customer and their store credit accounts, as the shop holds them now.

    A shop without store credit answers `storeCreditAccounts: null` (or errors on the field),
    and that is the NOT_SUPPORTED_BY_STORE case — told apart here, once, so that neither the
    card nor the probe has to guess at it.
    """
    payload = await client.graphql(STORE_CREDIT_QUERY, {"id": customer_id})
    node = (payload.get("data") or {}).get("customer")
    if not isinstance(node, dict) or node.get("id") != customer_id:
        raise ToolError(f"No customer with id {customer_id}.")
    accounts = node.get("storeCreditAccounts")
    if not isinstance(accounts, dict):
        raise StoreCreditUnavailable(NOT_ON_THIS_STORE)
    rows = []
    for edge in (accounts.get("edges") or []):
        account = (edge or {}).get("node") or {}
        if account.get("id"):
            rows.append({
                "account_id": str(account["id"]),
                "balance": _amount_of(account.get("balance")),
                "currency": str((account.get("balance") or {}).get("currencyCode") or "GBP"),
            })
    return {
        "customer_id": str(node["id"]),
        "name": str(node.get("displayName") or ""),
        "email": str(((node.get("defaultEmailAddress") or {}).get("emailAddress")) or ""),
        "accounts": rows,
    }


def credit_fingerprint(state: dict[str, Any], currency: str) -> dict[str, Any]:
    """What the account must still show for this credit to be the one prepared.

    The balance IN THE CURRENCY BEING CREDITED, and how many accounts there are. A customer
    may hold an account per currency, and a balance summed across them would make a euro
    credit look like it had changed a sterling one.
    """
    matching = [a for a in state["accounts"] if str(a.get("currency") or "").upper() == currency.upper()]
    balance = matching[0]["balance"] if matching and matching[0].get("balance") is not None else 0.0
    return {
        "balance": f"{float(balance):.2f}",
        "currency": currency.upper(),
        "accounts": len(state["accounts"]),
    }


# --------------------------------------------------------------------------- the workspace


def _clean_money(raw: str) -> tuple[str, str, str]:
    said = str(raw or "").strip().replace(",", "").lstrip("£$€")
    if not said:
        return "", "invalid", "How much credit?"
    try:
        amount = round(float(said), 2)
    except ValueError:
        return said[:10], "invalid", f"{said[:20]!r} is not an amount."
    if amount <= 0:
        return f"{amount:g}", "invalid", "Credit has to be more than nothing."
    if amount > MAX_STORE_CREDIT:
        return f"{amount:g}", "invalid", f"At most {display(MAX_STORE_CREDIT)} at a time from here."
    return f"{amount:.2f}", "ok", ""


def _clean_currency(raw: str) -> tuple[str, str, str]:
    """Three letters, and the length is checked BEFORE anything is truncated: "pounds"
    truncated to three characters is "POU", which is not a currency and would have gone to
    Shopify looking exactly like one."""
    value = re.sub(r"[^A-Z]", "", str(raw or "").upper())
    if len(value) != 3:
        return value[:3], "invalid", "Three letters — GBP, USD, EUR."
    return value, "ok", ""


def _clean_reason(raw: str) -> tuple[str, str, str]:
    return " ".join(str(raw or "").split())[:120], "ok", ""


FIELDS: tuple[ws.Field, ...] = (
    ws.Field(name="amount", label="Credit", kind="money", placeholder="20.00", maxlength=10, clean=_clean_money),
    ws.Field(name="currency", label="Currency", kind="code", placeholder="GBP", maxlength=3, clean=_clean_currency),
    ws.Field(name="reason", label="Why", kind="text", placeholder="for the record", maxlength=120, rows=1, clean=_clean_reason),
)
FIELD_NAMES = tuple(f.name for f in FIELDS)


def _customer(workspace: dict[str, Any]) -> dict[str, Any]:
    return dict(ws.fact(workspace, "customer") or {})


def _amount(workspace: dict[str, Any]) -> float | None:
    try:
        return round(float(ws.value(workspace, "amount")), 2)
    except (TypeError, ValueError):
        return None


def _balance(workspace: dict[str, Any]) -> float | None:
    """The balance in the currency being credited, or None when the shop has not been read."""
    accounts = ws.fact(workspace, "accounts")
    if not isinstance(accounts, list):
        return None
    currency = ws.value(workspace, "currency", "GBP").upper()
    matching = [a for a in accounts if str(a.get("currency") or "").upper() == currency]
    # No account in that currency, and the shop HAS been read: nothing, which is a balance
    # and not an unknown. "Not read yet" is the None above, and the card says which.
    return matching[0].get("balance") if matching else 0.0


def _blocked(workspace: dict[str, Any]) -> str:
    if ws.fact(workspace, "unavailable"):
        return NOT_ON_THIS_STORE
    if not _customer(workspace).get("customer_id"):
        return "It needs a customer."
    if ws.status(workspace, "amount") != "ok" or _amount(workspace) is None:
        return "It needs an amount to credit."
    if ws.status(workspace, "currency") != "ok":
        return "It needs a currency — GBP."
    if ws.fact(workspace, "accounts") is None:
        return "The customer's current balance has not been read yet."
    return ""


def _facts(workspace: dict[str, Any]) -> list[dict[str, Any]]:
    person = _customer(workspace)
    currency = ws.value(workspace, "currency", "GBP")
    balance = _balance(workspace)
    amount = _amount(workspace)
    rows: list[dict[str, Any]] = []
    if person.get("name"):
        rows.append({"label": "Customer", "value": f"{person['name']} · {person.get('email') or 'no address'}", "tone": "ok"})
    if ws.fact(workspace, "unavailable"):
        rows.append({"label": "Store credit", "value": "not available on this store", "tone": "bad"})
        return rows
    rows.append({"label": "Has now", "value": display(balance, currency) if balance is not None else "not read yet"})
    if amount is not None:
        rows.append({"label": "Adding", "value": display(amount, currency), "tone": "warn"})
        if balance is not None:
            rows.append({"label": "Would have", "value": display(round(balance + amount, 2), currency), "tone": "warn"})
    if len(ws.fact(workspace, "accounts") or []) > 1:
        rows.append({"label": "Accounts", "value": f"{len(ws.fact(workspace, 'accounts'))} — one per currency", "tone": "warn"})
    if ws.value(workspace, "reason"):
        rows.append({"label": "Why", "value": ws.value(workspace, "reason")})
    return rows


def _notes(workspace: dict[str, Any]) -> list[str]:
    if ws.fact(workspace, "unavailable"):
        return [NOT_ON_THIS_STORE]
    return [
        "Store credit is money the customer can spend in the shop. It cannot be taken back "
        "from here — debiting an account is a separate change this build does not make.",
        "The balance on this card was read from Shopify just now; if it moves before you "
        "authorise this, nothing is sent and the card says so.",
    ]


ACTIONS: tuple[ws.Action, ...] = (
    ws.Action(id="prepare", label="Prepare the credit", command="credit.stage", risk="red"),
    ws.Action(id="discard", label="Discard", command="credit.discard"),
)
# What the card says when a hold card prepared from it was withdrawn because it changed.
CHANGED = "The credit changed — prepare it again."


def _makes(workspace: dict[str, Any]) -> dict[str, Any]:
    """What this card would give (app/families/_workspace.py `makes`): whose account, how much,
    in what currency. The reason is on the card for the record and is not sent."""
    return {"customer": _customer(workspace).get("customer_id"),
            "amount": ws.value(workspace, "amount") if ws.status(workspace, "amount") == "ok" else None,
            "currency": ws.value(workspace, "currency", "GBP").upper()}


ws.makes(KIND, _makes)


def given(workspace: dict[str, Any] | None) -> str:
    """Why nothing more may be done to this card — the credit is given, or it left and was not
    proven — or "" while it is still his to decide (app/families/_workspace.py "made once")."""
    made = ws.finished(workspace)
    if made is None:
        return ""
    person = _customer(workspace or {})
    currency = ws.value(workspace, "currency", "GBP")
    amount = display(_amount(workspace), currency)
    if made.get("state") == ws.DONE:
        return (f"This credit is given — {amount} is on {person.get('name') or 'their'} account; "
                "open a new credit to give more.")
    return (f"This credit of {amount} was sent to Shopify and it has not said whether it was given; "
            "check the customer's account before giving it again.")


def _given_surface(workspace: dict[str, Any], made: dict[str, str]):
    """The card once its credit has gone: what was given and what they have now, and nothing to
    type, tap or prepare. The same card in the same place."""
    person = _customer(workspace)
    currency = ws.value(workspace, "currency", "GBP")
    amount = _amount(workspace)
    done = made.get("state") == ws.DONE
    facts = [{"label": "Customer", "value": f"{person.get('name') or ''} · {person.get('email') or 'no address'}"},
             {"label": "Given" if done else "Sent", "value": display(amount, currency), "tone": "ok" if done else "warn"}]
    if done and made.get("balance"):
        facts.append({"label": "Has now", "value": str(made["balance"])})
    if ws.value(workspace, "reason"):
        facts.append({"label": "Why", "value": ws.value(workspace, "reason")})
    return ws.surface(
        workspace, fields=(),
        kicker="Store credit · given" if done else "Store credit · sent, not confirmed",
        title=person.get("name") or "Store credit",
        subtitle=f"{display(amount, currency)} onto their account",
        facts=facts, actions=(),
        notes=["More credit is a new credit: open one for them again."] if done
        else ["Check the customer's account before giving it again."],
        settled="created" if done else "unconfirmed", settled_word="Given" if done else "Not confirmed",
        spoken=f"{display(amount, currency)} is on their account." if done else "Sent to Shopify, not confirmed.",
    )


def workspace_surface(workspace: dict[str, Any]):
    made = ws.finished(workspace)
    if made is not None:
        return _given_surface(workspace, made)
    person = _customer(workspace)
    currency = ws.value(workspace, "currency", "GBP")
    amount = _amount(workspace)
    notes = _notes(workspace)
    if ws.failed(workspace):
        notes = [f"The credit was not given: {ws.failed(workspace)}. Nothing was credited; prepare it again.", *notes]
    return ws.surface(
        workspace, fields=FIELDS,
        kicker="Store credit · not given",
        title=person.get("name") or "Store credit",
        subtitle=(f"{display(amount, currency)} onto their account" if amount is not None
                  else "nothing decided yet"),
        facts=_facts(workspace), notes=notes, actions=ACTIONS,
        field_command="credit.field", blocked=_blocked(workspace),
        spoken="Nothing is credited until you authorise the card that follows.",
    )


def _spoken(workspace: dict[str, Any]) -> str:
    if ws.fact(workspace, "unavailable"):
        return NOT_ON_THIS_STORE
    person = _customer(workspace)
    currency = ws.value(workspace, "currency", "GBP")
    balance = _balance(workspace)
    amount = _amount(workspace)
    blocked = _blocked(workspace)
    lead = f"{person.get('name') or 'Nobody'} has {display(balance, currency)} in store credit."
    if amount is None or blocked:
        return f"{lead} {blocked}" if blocked else lead
    return (
        f"{lead} This would add {display(amount, currency)}, taking them to "
        f"{display(round((balance or 0.0) + amount, 2), currency)}. Nothing is credited until you authorise it."
    )


# --------------------------------------------------------------------------- the read tool


def _session_and_branch() -> tuple[Any, Any]:
    from app.tools.context import CURRENT_SESSION, acting_branch

    session = CURRENT_SESSION.get()
    if session is None:
        raise ToolError("There is no conversation to credit an account in.")
    return session, session.branch(acting_branch(session))


@tool(
    name=OPEN_TOOL,
    description=(
        "Read a customer's store credit balance and put a credit on the owner's screen as "
        "fields; returns its workspace_id. Credits nothing. Says so if the store has no store "
        "credit."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "description": "From a customer lookup."},
            "amount": {"type": "number", "minimum": 0.01, "maximum": MAX_STORE_CREDIT},
            "currency": {"type": "string", "maxLength": 3, "description": "GBP if unsaid."},
            "reason": {"type": "string", "maxLength": 120},
        },
        "required": ["customer_id"],
    },
    tier=Tier.AMBER,
    issued_id_args=("customer_id",),
)
async def shopify_store_credit(
    customer_id: str, amount: float | None = None, currency: str = "GBP", reason: str = "",
) -> dict[str, Any]:
    """The workspace, opened from what the owner said. A READ tool: the balance is read and
    nothing is credited.

    A store without store credit is reported here, in the words the owner needs — what is
    unavailable, and that the code for it exists — rather than as a failure.
    """
    session, branch = _session_and_branch()
    state = await read_accounts(_c(), str(customer_id))
    workspace = ws.open_workspace(
        branch, kind=KIND, workspace_id=ws.new_id(WORKSPACE_PREFIX),
        values={"amount": "", "currency": "GBP", "reason": ""},
        facts={"customer": {"customer_id": state["customer_id"], "name": state["name"], "email": state["email"]},
               "accounts": state["accounts"]},
    )
    ws.type_into(workspace, FIELDS, "currency", currency or "GBP")
    if amount is not None:
        ws.type_into(workspace, FIELDS, "amount", str(amount))
    if reason:
        ws.type_into(workspace, FIELDS, "reason", reason)
    session.issue(str(workspace["workspace_id"]))
    session.remember_pii(*[v for v in (state["name"], state["email"]) if v])
    return {
        "workspace_id": str(workspace["workspace_id"]),
        "customer_name": state["name"],
        "balance": display(_balance(workspace), ws.value(workspace, "currency", "GBP")),
        "accounts": len(state["accounts"]),
        "blocked": _blocked(workspace),
        "_surfaces": [workspace_surface(workspace).as_ui()],
        "staged": False,
        "note": (
            "The credit is on the owner's screen and nothing has been given. The owner's "
            "gesture on Prepare the credit stages it; a hold and a drag on the card that "
            "follows applies it."
        ),
    }


# --------------------------------------------------------------------------- the write


async def _observe(execution: dict) -> Observed:
    state = await read_accounts(_c(), str(execution["customer_id"]))
    currency = str(execution["currency"])
    return Observed(fingerprint=credit_fingerprint(state, currency), entity={
        "customer_id": state["customer_id"], "customer_name": state["name"],
        "balance": display(
            next((a["balance"] for a in state["accounts"] if str(a.get("currency") or "").upper() == currency.upper()), 0.0),
            currency,
        ),
        "accounts": len(state["accounts"]),
    })


async def _execute(execution: dict) -> dict:
    """The one mutation. `id` is the customer — Shopify's own `storeCreditAccountCredit`
    accepts the account or its owner — and the amount is the one stored at staging time."""
    # Noted as sending before it leaves, and as failed when Shopify refused it or it never left
    # (app/families/_workspace.py `sending`): money, of all things, is never sent twice.
    payload = await ws.sending(str(execution.get("workspace_id") or ""), _c().mutate("store_credit_credit", {
        "id": str(execution["customer_id"]),
        "creditInput": dict(execution["input"]),
    }))
    body = ((payload.get("data") or {}).get("storeCreditAccountCredit") or {}).get("storeCreditAccountTransaction") or {}
    account = body.get("account") or {}
    if not account.get("id"):
        raise ShopifyError("Shopify did not confirm the credit.")
    # Shopify has said the credit went on the account: it is given, proven or not.
    ws.note(str(execution.get("workspace_id") or ""), ws.DONE)
    return {"account_id": str(account["id"])}


def _pence(value: Any) -> int | None:
    """A money figure as a whole number of the currency's minor unit, or None when it is not
    one. Decimal rather than float, because "15.10" + "20.00" must be 3510 pence exactly and
    never 3509.9999 rounded one way or the other."""
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite():
        return None
    return int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _verify(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    """Proof, by re-reading the balance: it is EXACTLY the old one plus what was credited, to
    the penny, in the currency it was credited in. Anything else is not proof.

    A predicate rather than an equality on the whole fingerprint, because the account COUNT
    moves when a customer's first credit in a currency creates their account for it — which
    is a normal thing to happen on exactly the change this is.

    It used to accept any rise as proof, with a caveat: £15 before, £20 sent, £40 after was
    "applied". That is £5 nobody can account for called a verified credit, on money a customer
    can spend (the 2026-09-28 deploy review, round 9, I-tests4 I-01). A balance that moved by
    anything but the amount sent — someone else's credit landing in between, a spend, a
    different amount going through — is now "I couldn't confirm the credit", which tells the
    owner to look at the account before asking again, and that is the true state of things.
    """
    was, now, added = _pence(before.get("balance")), _pence(observed.get("balance")), _pence(execution.get("amount"))
    if was is None or now is None or added is None or added <= 0:
        return False, "the balance could not be read as money, so the credit is not proven"
    sent_in = str(execution.get("currency") or before.get("currency") or "").strip().upper()
    if not sent_in or str(observed.get("currency") or "").strip().upper() != sent_in \
            or str(before.get("currency") or "").strip().upper() != sent_in:
        return False, "the balance read back is not in the currency that was credited"
    if now == was + added:
        return True, ""
    expected = display((was + added) / 100, sent_in)
    return False, f"the balance is {display(now / 100, sent_in)}, not {expected}; the credit is not proven"


def _present(proposal) -> dict:
    s = proposal.summary
    currency = str(s.get("currency") or "GBP")
    facts = [
        {"label": "Customer", "value": str(s.get("customer") or "")},
        {"label": "Has now", "value": display(float(s.get("balance") or 0), currency)},
        {"label": "Credit", "value": display(float(s.get("amount") or 0), currency), "tone": "warn"},
        {"label": "Will have", "value": display(float(s.get("after") or 0), currency), "tone": "bad"},
        {"label": "Spendable", "value": "immediately, on anything in the shop"},
    ]
    if s.get("reason"):
        facts.append({"label": "Why", "value": str(s.get("reason"))})
    if s.get("accounts_note"):
        facts.append({"label": "Accounts", "value": str(s.get("accounts_note")), "tone": "warn"})
    return {
        "title": "Credit the account",
        "summary": "",
        "detail": "Money the customer can spend in the shop. It cannot be taken back from here.",
        "facts": facts,
        "done_title": "Credit given",
    }


@tool(
    name=WRITE_TOOL,
    description="Prepare the store credit the owner has on screen. Needs the workspace_id from shopify_store_credit.",
    input_schema={
        "type": "object",
        "properties": {"workspace_id": {"type": "string", "description": "From shopify_store_credit."}},
        "required": ["workspace_id"],
    },
    tier=Tier.RED,
    issued_id_args=("workspace_id",),
    write=WriteSpec(
        operation=OPERATION,
        entity_kind="customer",
        entity_arg="workspace_id",
        mutation="store_credit_credit",
        observe=_observe,
        execute=_execute,
        present=_present,
        verify=_verify,
        # Money that can be spent. RED and money is the gravest gesture this build has.
        op_class="money",
        reversible=False,
        # The balance and its currency are the precondition; the account COUNT is on the
        # fingerprint for the proof and moves legitimately on a first credit, so holding the
        # change to it would make every first credit stale.
        precondition_keys=("balance", "currency"),
        # `{label}` deliberately unused: the entity here is a PERSON, and `entity_label`
        # reaches the ledger (app/actions/ledger.py) where a customer's name may not go —
        # the same reason `gmail_send_new` labels its entity "customer" and not an address.
        # The name is on the card, where the owner is reading it.
        spoken_success="Their store credit is {to} now.",
        spoken_failure="I couldn't confirm the credit. Check the customer's account before asking again.",
        spoken_stale="Their balance moved since this was prepared, so I haven't credited anything.",
    ),
)
async def shopify_store_credit_add(workspace_id: str) -> Prepared:
    """Prepare, never credit: read the balance again, build the reviewed input from the MAC's
    copy, and hand the engine a change to hold."""
    _session, branch = _session_and_branch()
    workspace = ws.held(branch, KIND, str(workspace_id))
    if workspace is None:
        raise ToolError("There is no store credit open on this half to give.")
    if given(workspace):
        raise ToolError(given(workspace))
    person = _customer(workspace)
    # Read again at the moment of preparing: the balance on the card is the balance the
    # engine will hold the change to, and it must be one read seconds ago rather than one
    # read when the workspace opened.
    state = await read_accounts(_c(), str(person.get("customer_id") or ""))
    workspace["facts"]["accounts"] = state["accounts"]
    workspace["facts"]["customer"] = {"customer_id": state["customer_id"], "name": state["name"], "email": state["email"]}
    blocked = _blocked(workspace)
    if blocked:
        raise ToolError(blocked)

    currency = ws.value(workspace, "currency", "GBP").upper()
    amount = _amount(workspace) or 0.0
    before = credit_fingerprint(state, currency)
    balance = round(float(before["balance"]), 2)
    after = round(balance + amount, 2)
    reason = ws.value(workspace, "reason")
    accounts_note = (
        f"{len(state['accounts'])} accounts, one per currency; this credits the {currency} one"
        if len(state["accounts"]) > 1 else ""
    )
    read_back = f"credit {person.get('name') or 'them'} with {display(amount, currency)} of store credit"
    ws.prepared(workspace)
    return Prepared(
        execution={
            "workspace_id": str(workspace["workspace_id"]),
            "customer_id": str(state["customer_id"]),
            "currency": currency,
            "amount": f"{amount:.2f}",
            "input": {"creditAmount": {"amount": f"{amount:.2f}", "currencyCode": currency}},
        },
        before=before,
        expected_after={"balance": f"{after:.2f}", "currency": currency, "accounts": max(1, len(state["accounts"]))},
        entity_ref=str(state["customer_id"]),
        # Never the name. `entity_label` goes into the ledger, and the ledger carries
        # identities, counts and controlled words — a customer's name is none of those.
        entity_label="customer",
        summary={
            "customer": str(state["name"] or ""),
            "balance": f"{balance:.2f}",
            "amount": f"{amount:.2f}",
            "after": f"{after:.2f}",
            "currency": currency,
            "reason": reason,
            "accounts_note": accounts_note,
            "read_back": read_back,
            "spoken_to": display(after, currency),
            "ledger": {"amount": f"{amount:.2f}", "currency": currency[:24], "was": f"{balance:.2f}"},
        },
    )


# --------------------------------------------------------------------------- the commands


def _no_workspace() -> Outcome:
    return Outcome.refused("no_workspace", "There is no store credit being decided on this half.")


def _field(ctx: CommandCtx) -> Outcome:
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id") or ctx.arg("compose_id"))
    if workspace is None:
        return _no_workspace()
    if given(workspace):
        return Outcome.refused("already_given", given(workspace))
    before = ws.card_state(workspace)
    ok, why = ws.type_into(workspace, FIELDS, ctx.arg("field"), str(ctx.args.get("value") or ""))
    if not ok:
        return Outcome.refused("unknown_field", why)
    # Withdrawn only when the credit it would give changes: the same amount again, or the
    # reason (which is on the card for the record and is not sent), leaves the hold card.
    gone = ws.touched(ctx.session, workspace, CHANGED, before=before)
    return Outcome(answer="", surfaces=[workspace_surface(workspace)],
                   changed={"workspace_id": str(workspace["workspace_id"]), "field": ctx.arg("field"),
                            "status": ws.status(workspace, ctx.arg("field")),
                            **({"withdrawn": gone, "withdrawn_words": CHANGED} if gone else {})})


def _stage(ctx: CommandCtx) -> Outcome:
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id"))
    if workspace is None:
        return _no_workspace()
    if given(workspace):
        return Outcome.refused("already_given", given(workspace))
    blocked = _blocked(workspace)
    if blocked:
        return Outcome.refused("not_ready", blocked)
    ident = str(workspace["workspace_id"])
    if ident not in (getattr(ctx.session, "issued_ids", None) or frozenset()):
        return Outcome.refused("not_held", "That is not a credit this conversation opened.")
    person = _customer(workspace)
    if not may_open(ctx, "customer", str(person.get("customer_id") or "")):
        return Outcome.refused("not_held", "I do not have that customer to hand; look them up again.")
    return Outcome(answer="", changed={
        "workspace_id": ident,
        "stage": {"tool": WRITE_TOOL, "args": {"workspace_id": ident}, "what": "credit the account"},
    })


def _discard(ctx: CommandCtx) -> Outcome:
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id"))
    if workspace is None:
        return _no_workspace()
    made = ws.finished(workspace)
    gone = ws.withdraw(ctx.session, workspace, "The credit was discarded.")
    ws.discard(ctx.branch)
    if made is not None:
        return Outcome(answer="The card is put away; the credit it gave stays given." if made.get("state") == ws.DONE
                       else "The card is put away. Check the customer's account for the credit it was sending.",
                       changed={"workspace": None, "discarded": str(workspace["workspace_id"])})
    return Outcome(answer="Gone. Nothing was credited.",
                   changed={"workspace": None, "discarded": str(workspace["workspace_id"]),
                            **({"withdrawn": gone, "withdrawn_words": "The credit was discarded."} if gone else {})})


# Touch only. There is no `credit.open`: opening this workspace needs a READ of the balance,
# and a command is synchronous by design (app/commands.py) — so the way in is the model
# calling `shopify_store_credit` for a customer this conversation has looked up, and the
# three commands here are what a finger does to the card that comes back.
register_command(Command("credit.field", "Type into the store credit being decided", _field, voice=False))
register_command(Command("credit.stage", "Prepare the store credit for authorising", _stage, voice=False))
register_command(Command("credit.discard", "Throw away the store credit being decided", _discard, voice=False))


# --------------------------------------------------------------------------- the capability


async def _probe(runtime: Any) -> dict[str, Any]:
    """The two halves, told apart by reading rather than by guessing.

    The scope first, because a store that has not granted it cannot be asked anything useful
    about store credit anyway. Then the FEATURE: one read of a customer's store credit
    accounts, and a shop that does not serve the field is NOT_SUPPORTED_BY_STORE with the
    sentence that says the code is here and the store's configuration is not.

    Never a mutation, like every probe. And a shop that simply does not answer is
    TEMPORARILY_UNAVAILABLE — "the store does not have store credit" is a claim, and it is
    only made when Shopify answered and the field was not there.
    """
    try:
        granted = set(await runtime.shopify.access_scopes())
    except Exception as exc:  # noqa: BLE001 — Shopify not answering is not a missing grant
        return {"state": "TEMPORARILY_UNAVAILABLE",
                "detail": f"the Shopify scope check did not answer ({type(exc).__name__})", "scope": SCOPE}
    if SCOPE not in granted:
        return {"state": "MISSING_SCOPE",
                "detail": (f"the code is here and the store has not granted {SCOPE}; add it on the Dev Dashboard "
                           "and approve it in the store admin"),
                "scope": SCOPE}
    if READ_SCOPE not in granted:
        return {"state": "MISSING_SCOPE",
                "detail": (f"the store has granted {SCOPE} but not {READ_SCOPE}, so a credit could be given and "
                           "not proven — which is not a change this build will make"),
                "scope": READ_SCOPE}
    probe = getattr(runtime, "store_credit_sample", "") or ""
    if not probe:
        # Nothing to ask about yet. The grants are there and the feature is unproven, which
        # is honest: the first `shopify_store_credit` finds out, and says so.
        return {"state": "READY",
                "detail": "ready — the grants are in place; whether the store has store credit is proven on first use",
                "scope": SCOPE}
    try:
        await read_accounts(runtime.shopify, str(probe))
    except StoreCreditUnavailable:
        return {"state": "NOT_SUPPORTED_BY_STORE", "detail": NOT_ON_THIS_STORE, "scope": SCOPE}
    except Exception as exc:  # noqa: BLE001
        return {"state": "TEMPORARILY_UNAVAILABLE",
                "detail": f"the store credit check did not answer ({type(exc).__name__})", "scope": SCOPE}
    return {"state": "READY", "detail": "ready — a customer's account can be credited", "scope": SCOPE}


register_family(CapabilityFamily(
    key="store_credit",
    label="Store credit",
    area="customers",
    what="Put store credit on a customer's account, in a named currency, after reading what they already have",
    operations=(OPERATION,),
    tools=(OPEN_TOOL, WRITE_TOOL),
    scopes=(SCOPE,),
    state="READY",
    probe=_probe,
))

__all__ = [
    "FIELDS", "FIELD_NAMES", "KIND", "NOT_ON_THIS_STORE", "OPEN_TOOL", "OPERATION", "SCOPE",
    "WRITE_TOOL", "StoreCreditUnavailable", "credit_fingerprint", "display", "read_accounts",
    "workspace_surface",
]
