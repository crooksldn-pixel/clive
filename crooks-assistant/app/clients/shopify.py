"""Shopify Admin GraphQL client.

Two auth modes. `client_credentials` exchanges the Dev Dashboard app's Client ID and secret for
a 24-hour token, forever, with no human in the loop — the intended path. `static_token` uses a
legacy `shpat_` Admin API token, which is the documented fallback for the one failure that has
no config fix: an app and a store in different Shopify organisations.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app import readonly
from app.secrets import keychain

log = logging.getLogger("crooks.shopify")

# Refresh a little before the hour is up rather than racing the expiry.
TOKEN_REFRESH_MARGIN_S = 300


class ShopifyAuthError(RuntimeError):
    """Authentication failed in a way that needs a human, not a retry."""


class ShopifyError(RuntimeError):
    """A query failed. Carries the message the assistant should read out."""


class ShopifyThrottled(ShopifyError):
    """The query cost bucket was short. Carries how long Shopify said it takes to refill."""

    def __init__(self, message: str, wait_s: float = 0.5) -> None:
        super().__init__(message)
        self.wait_s = wait_s


class ShopifyRefused(ShopifyError):
    """Shopify ran the mutation and answered with user errors: the change was not made, for
    a reason it stated. Not a lost answer — the re-read confirms nothing moved, and the
    reason is the one line worth showing."""

    refused = True


class ShopifyUnreached(ShopifyError):
    """Shopify could not be reached at all: the connection was never made, so no request left
    this Mac and nothing can have been applied. Told apart from an answer that never came back,
    which is a request that DID leave (round 12's second check: a completion that never left
    must not lock the card it was prepared from as "sent")."""

    unsent = True


class ShopifyWithheld(ShopifyError):
    """A change this Mac refused to send: not a reviewed mutation, or not the reviewed shape.
    Nothing left, so nothing can have been applied."""

    unsent = True


class ShopifyPreconditionFailed(ShopifyError):
    """Shopify refused a change because the entity was not as the sender assumed — a
    compare-and-swap that found another quantity, an order that cannot be cancelled as it
    stands. Nothing was applied, and the sender's picture of the entity is out of date."""


# The user-error codes that mean "the entity is not as you thought", across payloads.
PRECONDITION_CODES = frozenset({
    "CHANGE_FROM_QUANTITY_STALE", "COMPARE_QUANTITY_STALE", "ORDER_NOT_CANCELLABLE", "ALREADY_CANCELLED",
    "ORDER_ALREADY_CANCELLED", "NOT_CANCELLABLE", "INVALID_FULFILLMENT_ORDER", "FULFILLMENT_ORDER_NOT_FOUND",
})


class ShopifyScopeRefused(ShopifyError):
    """Shopify refused a mutation for want of a scope, and said so in the response. Proof that
    nothing was applied — which is what makes one retry with a freshly minted token safe. No
    other failure means this: a 5xx whose body happens to mention the words does not."""


@dataclass(slots=True)
class _Token:
    value: str
    expires_at: float
    expires_in: int

    @property
    def fresh(self) -> bool:
        return time.time() < self.expires_at - TOKEN_REFRESH_MARGIN_S


# ------------------------------------------------------------ reviewed writes
#
# The assistant sends no mutation it did not ship with. `graphql()` refuses any mutation
# document outright; the only way to change anything is `mutate()`, which takes a NAME from
# this table — a reviewed document with a fixed, bounded variable set — and never a document.
# A future action adds its own entry here, individually, with its own review. Nothing here is
# built from a caller's string.


@dataclass(frozen=True, slots=True)
class ReviewedMutation:
    name: str
    document: str
    # The exact variable names the document takes, and the Python type each must have.
    variables: dict[str, type]
    # The Admin API access scope the shop must have granted for this to work.
    scope: str
    # Longest string any variable may carry. Shopify's own limit on an order note is 5000.
    max_chars: int = 5000
    # Whether sending it twice with the same variables leaves the same state (setting a note
    # to a value: yes; a refund, a cancel, an adjustment by a delta: no). Only an idempotent
    # mutation is ever sent a second time, and then only after a proven scope refusal.
    idempotent: bool = False
    # The payload's root field, so a refusal can be told from a redaction: a root that came
    # back null was refused; a root that came back with a redacted field inside it ran.
    root: str = ""
    # For a mutation that takes a nested input object: validate(variable name, value) walks it
    # against the reviewed shape — known keys, enum values, numeric bounds — and refuses the
    # rest. A nested input is never sent on the strength of the top-level check alone.
    validate: Any = None


REVIEWED_MUTATIONS: dict[str, ReviewedMutation] = {
    # Phase 1: the order note. `orderUpdate` overwrites the note, which is why the desired
    # value is built on the Mac from a fresh read and checked against it again before sending.
    "order_note_set": ReviewedMutation(
        name="order_note_set",
        document="""
            mutation CrooksOrderNoteSet($id: ID!, $note: String!) {
              orderUpdate(input: {id: $id, note: $note}) {
                order { id name note }
                userErrors { field message }
              }
            }
        """,
        variables={"id": str, "note": str},
        scope="write_orders",
        idempotent=True,
        root="orderUpdate",
    ),
    # Tags. tagsAdd and tagsRemove are set operations: sending either twice leaves the same
    # tags, so both may be retried after a proven scope refusal.
    "order_tags_add": ReviewedMutation(
        name="order_tags_add",
        document="""
            mutation CrooksOrderTagsAdd($id: ID!, $tags: [String!]!) {
              tagsAdd(id: $id, tags: $tags) {
                node { id }
                userErrors { field message }
              }
            }
        """,
        variables={"id": str, "tags": list},
        scope="write_orders",
        max_chars=40,
        idempotent=True,
        root="tagsAdd",
    ),
    # Cancellation. Shopify cancels in a job that finishes later; the engine waits for it
    # (app/tools/shopify_writes.py settle) and proves the cancellation by re-reading. Not
    # idempotent — never sent twice. The refund method is a fixed shape validated below.
    "order_cancel": ReviewedMutation(
        name="order_cancel",
        document="""
            mutation CrooksOrderCancel($orderId: ID!, $reason: OrderCancelReason!, $refundMethod: OrderCancelRefundMethodInput!, $restock: Boolean!, $notifyCustomer: Boolean!, $staffNote: String) {
              orderCancel(orderId: $orderId, reason: $reason, refundMethod: $refundMethod, restock: $restock, notifyCustomer: $notifyCustomer, staffNote: $staffNote) {
                job { id done }
                orderCancelUserErrors { field message code }
              }
            }
        """,
        variables={"orderId": str, "reason": str, "refundMethod": dict, "restock": bool, "notifyCustomer": bool, "staffNote": str},
        scope="write_orders",
        max_chars=200,
        idempotent=False,
        root="orderCancel",
        validate=lambda key, value: key == "refundMethod" and set(value) == {"originalPaymentMethodsRefund"} and isinstance(value["originalPaymentMethodsRefund"], bool),
    ),
    # A refund. Never idempotent, never sent twice. The input is a nested object; every key,
    # enum and amount in it is checked against the reviewed shape below before it leaves.
    "refund_create": ReviewedMutation(
        name="refund_create",
        document="""
            mutation CrooksRefundCreate($input: RefundInput!) {
              refundCreate(input: $input) {
                refund { id createdAt totalRefundedSet { shopMoney { amount currencyCode } } }
                userErrors { field message }
              }
            }
        """,
        variables={"input": dict},
        scope="write_orders",
        max_chars=200,
        idempotent=False,
        root="refundCreate",
        validate=lambda key, value: key == "input" and refund_input_ok(value),
    ),
    "order_tags_remove": ReviewedMutation(
        name="order_tags_remove",
        document="""
            mutation CrooksOrderTagsRemove($id: ID!, $tags: [String!]!) {
              tagsRemove(id: $id, tags: $tags) {
                node { id }
                userErrors { field message }
              }
            }
        """,
        variables={"id": str, "tags": list},
        scope="write_orders",
        max_chars=40,
        idempotent=True,
        root="tagsRemove",
    ),
    # Phase E: the shipping address, and the reprint note in the same write. `orderUpdate`
    # overwrites both, which is why the Mac merges the changed fields into the address as
    # it is now and builds the note from a fresh read, and checks both again before sending.
    # Setting values: idempotent. The selection carries ids only — never the address.
    "order_shipping_address_set": ReviewedMutation(
        name="order_shipping_address_set",
        document="""
            mutation CrooksOrderShippingAddressSet($id: ID!, $address: MailingAddressInput!, $note: String!) {
              orderUpdate(input: {id: $id, shippingAddress: $address, note: $note}) {
                order { id name }
                userErrors { field message }
              }
            }
        """,
        variables={"id": str, "address": dict, "note": str},
        scope="write_orders",
        idempotent=True,
        root="orderUpdate",
        validate=lambda key, value: key == "address" and mailing_address_ok(value),
    ),
    # Phase G: a fulfilment, from the order's own fulfilment orders resolved on the Mac at
    # staging time, with the carrier named as Shopify names it. Creating one is not
    # idempotent — never sent twice. The selection is the id and status of what was made.
    "fulfillment_create": ReviewedMutation(
        name="fulfillment_create",
        document="""
            mutation CrooksFulfillmentCreate($fulfillment: FulfillmentInput!) {
              fulfillmentCreate(fulfillment: $fulfillment) {
                fulfillment { id status }
                userErrors { field message }
              }
            }
        """,
        variables={"fulfillment": dict},
        scope="write_merchant_managed_fulfillment_orders",
        root="fulfillmentCreate",
        validate=lambda key, value: key == "fulfillment" and fulfillment_input_ok(value),
    ),
    # Tracking on a shipment already marked shipped (Click & Drop prints the label; the number
    # arrives afterwards). Setting a value: idempotent. The selection is the shipment's own.
    "fulfillment_tracking_set": ReviewedMutation(
        name="fulfillment_tracking_set",
        document="""
            mutation CrooksFulfillmentTrackingSet($fulfillmentId: ID!, $trackingInfoInput: FulfillmentTrackingInput!, $notifyCustomer: Boolean) {
              fulfillmentTrackingInfoUpdate(fulfillmentId: $fulfillmentId, trackingInfoInput: $trackingInfoInput, notifyCustomer: $notifyCustomer) {
                fulfillment { id status trackingInfo { company number url } }
                userErrors { field message }
              }
            }
        """,
        variables={"fulfillmentId": str, "trackingInfoInput": dict, "notifyCustomer": bool},
        scope="write_merchant_managed_fulfillment_orders",
        idempotent=True,
        root="fulfillmentTrackingInfoUpdate",
        validate=lambda key, value: key == "trackingInfoInput" and tracking_input_ok(value),
    ),
    # Phase I: one variant's available stock at one location, set to a number decided on the
    # Mac from a fresh read, guarded by Shopify's own compare-and-swap: the quantity is only
    # written if the store still holds the number the Mac read (COMPARE_QUANTITY_STALE
    # otherwise, and nothing changes). Never resent. API 2025-07 shape; 2026-04 and later
    # rename compareQuantity to changeFromQuantity and require an @idempotent key.
    "inventory_set_quantities": ReviewedMutation(
        name="inventory_set_quantities",
        document="""
            mutation CrooksInventorySet($input: InventorySetQuantitiesInput!) {
              inventorySetQuantities(input: $input) {
                inventoryAdjustmentGroup { id reason changes { name delta quantityAfterChange } }
                userErrors { field message code }
              }
            }
        """,
        variables={"input": dict},
        scope="write_inventory",
        root="inventorySetQuantities",
        validate=lambda key, value: key == "input" and inventory_input_ok(value),
    ),
    # Phase 3: adding a line to an order (app/tools/shopify_writes.py, app/families/order_edit.py).
    # Three mutations, and only the third changes the order. `orderEditBegin` opens a
    # CalculatedOrder — a scratch copy Shopify prices for us — and `orderEditAddVariant` puts
    # the variant on THAT. Nothing the customer or the shop can see moves until
    # `orderEditCommit`, which is why the financial consequence on the card is Shopify's own
    # arithmetic rather than ours, and why the first two run at PREPARE time and the third
    # only after the owner's gesture.
    #
    # Beginning an edit leaves the same state however many times it is done (a fresh scratch
    # copy), so it may be resent after a proven scope refusal. Adding a variant and
    # committing may not: a second send would be a second line, or a second commit.
    "order_edit_begin": ReviewedMutation(
        name="order_edit_begin",
        document="""
            mutation CrooksOrderEditBegin($id: ID!) {
              orderEditBegin(id: $id) {
                calculatedOrder { id committed }
                userErrors { field message }
              }
            }
        """,
        variables={"id": str},
        scope="write_order_edits",
        idempotent=True,
        root="orderEditBegin",
    ),
    # `allowDuplicates: false` is sent always and is never an argument: the owner asking for
    # a second hoodie means one more of the hoodie, not a second line saying the same thing.
    # Shopify may therefore fold the addition into a line the order already has — which is
    # why the proof is "a line for that variant carrying at least the quantity asked for"
    # and never "one more line than before" (see _verify_order_add_item).
    "order_edit_add_variant": ReviewedMutation(
        name="order_edit_add_variant",
        document="""
            mutation CrooksOrderEditAddVariant($id: ID!, $variantId: ID!, $quantity: Int!, $allowDuplicates: Boolean!) {
              orderEditAddVariant(id: $id, variantId: $variantId, quantity: $quantity, allowDuplicates: $allowDuplicates) {
                calculatedLineItem {
                  id
                  title
                  variantTitle
                  quantity
                  originalUnitPriceSet { shopMoney { amount currencyCode } }
                }
                calculatedOrder {
                  id
                  subtotalPriceSet { shopMoney { amount currencyCode } }
                  totalPriceSet { shopMoney { amount currencyCode } }
                  totalOutstandingSet { shopMoney { amount currencyCode } }
                  lineItems(first: 50) { edges { node { id quantity variant { id } } } }
                }
                userErrors { field message }
              }
            }
        """,
        variables={"id": str, "variantId": str, "quantity": int, "allowDuplicates": bool},
        scope="write_order_edits",
        max_chars=200,
        idempotent=False,
        root="orderEditAddVariant",
    ),
    # The one that changes the order. `notifyCustomer: false` is sent always: an email about
    # money now owed is the owner's to send in his own words, not a side effect of a tap.
    "order_edit_commit": ReviewedMutation(
        name="order_edit_commit",
        document="""
            mutation CrooksOrderEditCommit($id: ID!, $notifyCustomer: Boolean!, $staffNote: String!) {
              orderEditCommit(id: $id, notifyCustomer: $notifyCustomer, staffNote: $staffNote) {
                order { id name }
                userErrors { field message }
              }
            }
        """,
        variables={"id": str, "notifyCustomer": bool, "staffNote": str},
        scope="write_order_edits",
        max_chars=200,
        idempotent=False,
        root="orderEditCommit",
    ),
    # ------------------------------------------------------------ Phase 3: commerce writes
    #
    # Three families of NEW things, and each one is something the shop could not do before:
    # a discount code, an order made from nothing, and money put on a customer's account.
    # All three are creations, which changes nothing about the boundary — the Mac reads
    # first, builds the input itself, and sends one named document after the gesture — but
    # it does change what "the entity" is: there is no id to act on until the change has
    # been made. So each acts on a WORKSPACE the Mac holds (app/families/_workspace.py),
    # whose id is issued to the conversation like any other id, and each proves itself by
    # reading the thing it made rather than by comparing a fingerprint of something already
    # there.
    #
    # A discount code (app/families/discounts.py). One code, one value — a percentage or a
    # fixed amount — an optional window and an optional usage limit. Never idempotent: sent
    # twice it would collide with itself, so it is sent once and the collision is read
    # BEFORE the card goes up as well as again at the tap.
    "discount_code_create": ReviewedMutation(
        name="discount_code_create",
        document="""
            mutation CrooksDiscountCodeCreate($basicCodeDiscount: DiscountCodeBasicInput!) {
              discountCodeBasicCreate(basicCodeDiscount: $basicCodeDiscount) {
                codeDiscountNode {
                  id
                  codeDiscount {
                    ... on DiscountCodeBasic {
                      title
                      status
                      startsAt
                      endsAt
                      usageLimit
                      appliesOncePerCustomer
                      codes(first: 1) { edges { node { code } } }
                    }
                  }
                }
                userErrors { field message code }
              }
            }
        """,
        variables={"basicCodeDiscount": dict},
        scope="write_discounts",
        max_chars=200,
        idempotent=False,
        root="discountCodeBasicCreate",
        validate=lambda key, value: key == "basicCodeDiscount" and discount_code_input_ok(value),
    ),
    # An order made from nothing (app/families/order_create.py). TWO mutations, and the
    # first is the reason this is safe to offer at all: `draftOrderCreate` makes a DRAFT — a
    # real object, priced by Shopify, visible in Admin, which is not an order and for which
    # nobody is charged — and `draftOrderComplete` turns that draft into the order. So the
    # draft is the reviewable intermediate: every number on the card is Shopify's own
    # arithmetic on the draft, and the gesture authorises the completion alone.
    #
    # Creating a draft is not idempotent — a second send is a second draft — so it is never
    # resent, and the workspace remembers the one it made rather than making another.
    "draft_order_create": ReviewedMutation(
        name="draft_order_create",
        document="""
            mutation CrooksDraftOrderCreate($input: DraftOrderInput!) {
              draftOrderCreate(input: $input) {
                draftOrder {
                  id
                  name
                  status
                  totalPriceSet { shopMoney { amount currencyCode } }
                  subtotalPriceSet { shopMoney { amount currencyCode } }
                  totalShippingPriceSet { shopMoney { amount currencyCode } }
                  totalTaxSet { shopMoney { amount currencyCode } }
                  appliedDiscount { title value valueType }
                  customer { id displayName }
                  email
                  shippingAddress { address1 address2 city zip countryCodeV2 }
                  lineItems(first: 20) {
                    edges { node {
                      id title quantity custom variantTitle
                      variant { id }
                      appliedDiscount { title value valueType }
                      originalUnitPriceSet { shopMoney { amount currencyCode } }
                      discountedTotalSet { shopMoney { amount currencyCode } }
                    } }
                  }
                }
                userErrors { field message }
              }
            }
        """,
        variables={"input": dict},
        scope="write_draft_orders",
        max_chars=500,
        idempotent=False,
        root="draftOrderCreate",
        validate=lambda key, value: key == "input" and draft_order_input_ok(value),
    ),
    # The one that makes the order. `paymentPending` is decided on the Mac from the payment
    # state chosen on the workspace; it is never a value the tablet posts.
    "draft_order_complete": ReviewedMutation(
        name="draft_order_complete",
        document="""
            mutation CrooksDraftOrderComplete($id: ID!, $paymentPending: Boolean!) {
              draftOrderComplete(id: $id, paymentPending: $paymentPending) {
                draftOrder {
                  id
                  name
                  status
                  order { id name }
                }
                userErrors { field message }
              }
            }
        """,
        variables={"id": str, "paymentPending": bool},
        scope="write_draft_orders",
        idempotent=False,
        root="draftOrderComplete",
    ),
    # Money onto a customer's store credit account (app/families/store_credit.py). Money
    # that can be spent, so never idempotent and never resent; the balance is read before
    # the card, held to as the precondition, and read again to prove the new one.
    "store_credit_credit": ReviewedMutation(
        name="store_credit_credit",
        document="""
            mutation CrooksStoreCreditCredit($id: ID!, $creditInput: StoreCreditAccountCreditInput!) {
              storeCreditAccountCredit(id: $id, creditInput: $creditInput) {
                storeCreditAccountTransaction {
                  amount { amount currencyCode }
                  balanceAfterTransaction { amount currencyCode }
                  account { id balance { amount currencyCode } }
                }
                userErrors { field message code }
              }
            }
        """,
        variables={"id": str, "creditInput": dict},
        scope="write_store_credit_account_transactions",
        max_chars=64,
        idempotent=False,
        root="storeCreditAccountCredit",
        validate=lambda key, value: key == "creditInput" and store_credit_input_ok(value),
    ),
}

_GID = re.compile(r"^gid://shopify/[A-Za-z]+/\d+$")
_DECIMAL = re.compile(r"^\d{1,7}(?:\.\d{1,2})?$")
_RESTOCK = frozenset({"RETURN", "CANCEL", "NO_RESTOCK"})


def refund_input_ok(value: Any) -> bool:
    """The RefundInput shape this project sends, and nothing else: known keys, enum values,
    bounded amounts, ids that are ids. A refund is money leaving; the shape is held here as
    well as where it is built."""
    if not isinstance(value, dict) or not value:
        return False
    allowed = {"orderId", "note", "notify", "currency", "refundLineItems", "shipping", "transactions"}
    if set(value) - allowed or not _GID.match(str(value.get("orderId", ""))):
        return False
    if "note" in value and (not isinstance(value["note"], str) or len(value["note"]) > 200):
        return False
    if "notify" in value and not isinstance(value["notify"], bool):
        return False
    if "currency" in value and (not isinstance(value["currency"], str) or not re.match(r"^[A-Z]{3}$", value["currency"])):
        return False
    lines = value.get("refundLineItems", [])
    if not isinstance(lines, list) or len(lines) > 50:
        return False
    for line in lines:
        if not isinstance(line, dict) or set(line) - {"lineItemId", "quantity", "restockType", "locationId"}:
            return False
        if not _GID.match(str(line.get("lineItemId", ""))) or not isinstance(line.get("quantity"), int) or isinstance(line.get("quantity"), bool) or not 1 <= line["quantity"] <= 50:
            return False
        if str(line.get("restockType", "NO_RESTOCK")) not in _RESTOCK:
            return False
        if "locationId" in line and not _GID.match(str(line["locationId"])):
            return False
    shipping = value.get("shipping")
    if shipping is not None:
        if not isinstance(shipping, dict) or set(shipping) - {"amount", "fullRefund"} or not shipping:
            return False
        if "amount" in shipping and not _DECIMAL.match(str(shipping["amount"])):
            return False
        if "fullRefund" in shipping and not isinstance(shipping["fullRefund"], bool):
            return False
    transactions = value.get("transactions", [])
    if not isinstance(transactions, list) or not transactions or len(transactions) > 10:
        return False
    for t in transactions:
        if not isinstance(t, dict) or set(t) != {"orderId", "gateway", "kind", "amount", "parentId"}:
            return False
        if t["kind"] != "REFUND" or not _DECIMAL.match(str(t["amount"])) or not _GID.match(str(t["parentId"])) or not _GID.match(str(t["orderId"])):
            return False
        if not isinstance(t["gateway"], str) or not 1 <= len(t["gateway"]) <= 60:
            return False
    return True


_ADDRESS_KEYS = frozenset({"firstName", "lastName", "company", "address1", "address2", "city", "provinceCode", "zip", "countryCode", "phone"})
_COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")
_PROVINCE_CODE = re.compile(r"^[A-Z0-9]{1,5}$")
_PHONE = re.compile(r"^\+?[0-9 ()\-]{6,20}$")


def mailing_address_ok(value: Any) -> bool:
    """The MailingAddressInput shape this project sends: Shopify's own ten fields, plain
    text under a hundred characters each, a two-letter country, a street line present.
    A parcel goes where this says; the shape is held here as well as where it is built."""
    if not isinstance(value, dict) or not value or set(value) - _ADDRESS_KEYS:
        return False
    for text in value.values():
        if not isinstance(text, str) or not text or len(text) > 100 or "<" in text or any(ord(ch) < 32 for ch in text):
            return False
    if not value.get("address1") or not value.get("countryCode"):
        return False
    if not _COUNTRY_CODE.match(value["countryCode"]):
        return False
    if "provinceCode" in value and not _PROVINCE_CODE.match(value["provinceCode"]):
        return False
    if "phone" in value and not _PHONE.match(value["phone"]):
        return False
    return True


_TRACKING_NUMBER = re.compile(r"^[A-Za-z0-9\-]{8,34}$")


def fulfillment_input_ok(value: Any) -> bool:
    """The FulfillmentInput shape this project sends: which fulfilment-order lines, how many
    of each, one carrier and one number, whether the customer hears. Nothing else."""
    if not isinstance(value, dict) or set(value) - {"notifyCustomer", "trackingInfo", "lineItemsByFulfillmentOrder"}:
        return False
    if "notifyCustomer" in value and not isinstance(value["notifyCustomer"], bool):
        return False
    tracking = value.get("trackingInfo")
    if tracking is not None:
        if not isinstance(tracking, dict) or not tracking or set(tracking) - {"company", "number"}:
            return False
        if "company" in tracking and (not isinstance(tracking["company"], str) or not 1 <= len(tracking["company"]) <= 60 or "<" in tracking["company"]):
            return False
        if "number" in tracking and (not isinstance(tracking["number"], str) or not _TRACKING_NUMBER.match(tracking["number"])):
            return False
    orders = value.get("lineItemsByFulfillmentOrder")
    if not isinstance(orders, list) or not orders or len(orders) > 10:
        return False
    for entry in orders:
        if not isinstance(entry, dict) or set(entry) != {"fulfillmentOrderId", "fulfillmentOrderLineItems"}:
            return False
        if not _GID.match(str(entry["fulfillmentOrderId"])):
            return False
        lines = entry["fulfillmentOrderLineItems"]
        if not isinstance(lines, list) or not lines or len(lines) > 50:
            return False
        for line in lines:
            if not isinstance(line, dict) or set(line) != {"id", "quantity"} or not _GID.match(str(line["id"])):
                return False
            if not isinstance(line["quantity"], int) or isinstance(line["quantity"], bool) or not 1 <= line["quantity"] <= 500:
                return False
    return True


def tracking_input_ok(value: Any) -> bool:
    """The FulfillmentTrackingInput this project sends: a carrier as Shopify names it and one
    number. Never a URL from anyone: Shopify builds the link from a name it knows."""
    if not isinstance(value, dict) or not value or set(value) - {"company", "number"} or "number" not in value:
        return False
    if not isinstance(value["number"], str) or not _TRACKING_NUMBER.match(value["number"]):
        return False
    if "company" in value and (not isinstance(value["company"], str) or not 1 <= len(value["company"]) <= 60 or "<" in value["company"]):
        return False
    return True


_STOCK_REASONS = frozenset({"correction", "received", "damaged", "restock", "shrinkage", "other"})
MAX_STOCK_QUANTITY = 100_000


def inventory_input_ok(value: Any) -> bool:
    """The InventorySetQuantitiesInput shape this project sends: one available quantity at
    one location, with the compare quantity always present. Never on_hand, never several."""
    if not isinstance(value, dict) or set(value) != {"name", "reason", "referenceDocumentUri", "ignoreCompareQuantity", "quantities"}:
        return False
    if value["name"] != "available" or value["reason"] not in _STOCK_REASONS or value["ignoreCompareQuantity"] is not False:
        return False
    uri = value["referenceDocumentUri"]
    if not isinstance(uri, str) or not re.match(r"^gid://crooks-assistant/[A-Za-z]+/[A-Za-z0-9-]{1,40}$", uri):
        return False
    quantities = value["quantities"]
    if not isinstance(quantities, list) or len(quantities) != 1:
        return False
    q = quantities[0]
    if not isinstance(q, dict) or set(q) != {"inventoryItemId", "locationId", "quantity", "compareQuantity"}:
        return False
    if not _GID.match(str(q["inventoryItemId"])) or not _GID.match(str(q["locationId"])):
        return False
    for key in ("quantity", "compareQuantity"):
        if not isinstance(q[key], int) or isinstance(q[key], bool) or not -MAX_STOCK_QUANTITY <= q[key] <= MAX_STOCK_QUANTITY:
            return False
    return q["quantity"] >= 0


# ------------------------------------------------------------ Phase 3: the created things
#
# Three input shapes for three creations. Held here, beside the documents that carry them,
# as well as where they are built — the same rule the refund and the address keep, and for
# the same reason: the shape a mutation may be sent with is a reviewed fact about this
# application, not a property of whichever function happened to assemble it.

_CURRENCY = re.compile(r"^[A-Z]{3}$")
# A discount code as Shopify stores it and as a person types it at the till: upper case,
# digits and hyphens. Deliberately narrower than Shopify's own rule (which allows almost
# anything) because a code with a space or a slash in it is a code the shop cannot read out.
DISCOUNT_CODE = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,29}$")
# An instant, as Shopify wants it and as the Mac builds it: never a phrase, never a date on
# its own — "the 12th" is a different moment in two time zones.
_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$")
MAX_DISCOUNT_USES = 10_000
MAX_DISCOUNT_AMOUNT = 1_000.0
MAX_DRAFT_LINES = 20
MAX_DRAFT_QUANTITY = 50
# A custom line's unit price, and a fixed amount off a line or an order. The owner says these
# out loud, and "twelve pounds" misheard as "twelve hundred" is the mistake this bound is for.
MAX_CUSTOM_LINE_PRICE = 1_000.0
MAX_CUSTOM_TITLE_CHARS = 60
MAX_STORE_CREDIT = 1_000.0


def discount_code_input_ok(value: Any) -> bool:
    """The DiscountCodeBasicInput shape this project sends: one code, one value — a
    percentage of everything or a fixed amount off the order — for every customer, combining
    with nothing, optionally within a window and optionally limited in use.

    `percentage` is Shopify's fraction, between 0 and 1: 0.15 is fifteen per cent. Sending
    15 there would be a fifteen-hundred-per-cent discount, which is exactly the class of
    mistake a reviewed shape exists to make impossible.
    """
    allowed = {
        "title", "code", "startsAt", "endsAt", "usageLimit", "appliesOncePerCustomer",
        "customerSelection", "customerGets", "combinesWith",
    }
    required = {"title", "code", "startsAt", "customerSelection", "customerGets", "combinesWith"}
    if not isinstance(value, dict) or set(value) - allowed or required - set(value):
        return False
    if not isinstance(value["title"], str) or not 1 <= len(value["title"]) <= 120 or "<" in value["title"]:
        return False
    if not isinstance(value["code"], str) or not DISCOUNT_CODE.match(value["code"]):
        return False
    for key in ("startsAt", "endsAt"):
        if key in value and (not isinstance(value[key], str) or not _INSTANT.match(value[key])):
            return False
    if "usageLimit" in value:
        limit = value["usageLimit"]
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_DISCOUNT_USES:
            return False
    if "appliesOncePerCustomer" in value and not isinstance(value["appliesOncePerCustomer"], bool):
        return False
    # Everyone, and nothing else: a discount aimed at a segment is a different review.
    if value["customerSelection"] != {"all": True}:
        return False
    # Never stacked. A code that combines with the shop's own automatic discounts can take
    # an order below its cost without anybody deciding that it should.
    if value["combinesWith"] != {"orderDiscounts": False, "productDiscounts": False, "shippingDiscounts": False}:
        return False
    gets = value["customerGets"]
    if not isinstance(gets, dict) or set(gets) != {"value", "items"} or gets["items"] != {"all": True}:
        return False
    money = gets["value"]
    if not isinstance(money, dict) or len(money) != 1:
        return False
    if "percentage" in money:
        share = money["percentage"]
        if isinstance(share, bool) or not isinstance(share, (int, float)) or not 0 < float(share) <= 1:
            return False
        return True
    amount = money.get("discountAmount")
    if not isinstance(amount, dict) or set(amount) != {"amount", "appliesOnEachItem"}:
        return False
    if amount["appliesOnEachItem"] is not False or not _DECIMAL.match(str(amount["amount"])):
        return False
    return 0 < float(amount["amount"]) <= MAX_DISCOUNT_AMOUNT


def _applied_discount_ok(off: Any) -> bool:
    """A DraftOrderAppliedDiscountInput, on a line or on the whole draft: a title, a value, and
    whether the value is a percentage (at most 100) or a fixed amount of money (bounded)."""
    if not isinstance(off, dict) or set(off) != {"title", "value", "valueType"}:
        return False
    if off["valueType"] not in ("PERCENTAGE", "FIXED_AMOUNT"):
        return False
    if isinstance(off["value"], bool) or not isinstance(off["value"], (int, float)) or not 0 < float(off["value"]):
        return False
    if off["valueType"] == "PERCENTAGE" and float(off["value"]) > 100:
        return False
    if off["valueType"] == "FIXED_AMOUNT" and float(off["value"]) > MAX_CUSTOM_LINE_PRICE:
        return False
    return isinstance(off["title"], str) and 1 <= len(off["title"]) <= 60 and "<" not in off["title"]


def _draft_line_ok(line: Any) -> bool:
    """One DraftOrderLineItemInput, of exactly two kinds.

    A CATALOGUE line is a variant id and a quantity, and never a price: Shopify prices it from
    the catalogue, and a variant line carrying `originalUnitPrice` would be a price of ours
    overriding the shop's. A CUSTOM line — a print, a repair, a thing the shop does not list —
    has no catalogue price to read, so it carries the title and the unit price the owner gave,
    and no variant. Either may carry its own discount.
    """
    if not isinstance(line, dict):
        return False
    quantity = line.get("quantity")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= MAX_DRAFT_QUANTITY:
        return False
    if "appliedDiscount" in line and not _applied_discount_ok(line["appliedDiscount"]):
        return False
    keys = set(line) - {"appliedDiscount"}
    if keys == {"variantId", "quantity"}:
        return bool(_GID.match(str(line["variantId"])))
    if keys == {"title", "originalUnitPrice", "quantity"}:
        title, price = line["title"], line["originalUnitPrice"]
        if not isinstance(title, str) or not 1 <= len(title) <= MAX_CUSTOM_TITLE_CHARS or "<" in title or any(ord(c) < 32 for c in title):
            return False
        return isinstance(price, str) and bool(_DECIMAL.match(price)) and 0 <= float(price) <= MAX_CUSTOM_LINE_PRICE
    return False


def draft_order_input_ok(value: Any) -> bool:
    """The DraftOrderInput shape this project sends: whose order it is, what is on it, where
    it goes, what the shop charges for postage, and any discount. A catalogue line is a
    variant id and a quantity and Shopify prices it; a custom line carries the owner's own
    title and price because the catalogue has none (`_draft_line_ok`).

    A draft with no lines is not an order anybody meant, and a draft with no customer is one
    nobody can be told about; both are refused here as well as where the workspace is built.
    """
    allowed = {
        "lineItems", "customerId", "email", "note", "tags", "useCustomerDefaultAddress",
        "shippingAddress", "shippingLine", "appliedDiscount",
    }
    if not isinstance(value, dict) or set(value) - allowed or "lineItems" not in value or "customerId" not in value:
        return False
    if not _GID.match(str(value.get("customerId", ""))):
        return False
    lines = value["lineItems"]
    if not isinstance(lines, list) or not lines or len(lines) > MAX_DRAFT_LINES:
        return False
    if not all(_draft_line_ok(line) for line in lines):
        return False
    if "email" in value and (not isinstance(value["email"], str) or not 3 <= len(value["email"]) <= 254 or "@" not in value["email"]):
        return False
    if "note" in value and (not isinstance(value["note"], str) or len(value["note"]) > 500):
        return False
    tags = value.get("tags")
    if tags is not None and (not isinstance(tags, list) or len(tags) > 5 or any(not isinstance(t, str) or not 1 <= len(t) <= 40 for t in tags)):
        return False
    if "useCustomerDefaultAddress" in value and not isinstance(value["useCustomerDefaultAddress"], bool):
        return False
    if "shippingAddress" in value and not mailing_address_ok(value["shippingAddress"]):
        return False
    postage = value.get("shippingLine")
    if postage is not None:
        if not isinstance(postage, dict) or set(postage) != {"title", "price"}:
            return False
        if not isinstance(postage["title"], str) or not 1 <= len(postage["title"]) <= 60 or "<" in postage["title"]:
            return False
        if not _DECIMAL.match(str(postage["price"])):
            return False
    return "appliedDiscount" not in value or _applied_discount_ok(value["appliedDiscount"])


def store_credit_input_ok(value: Any) -> bool:
    """The StoreCreditAccountCreditInput shape this project sends: one amount in one named
    currency, and an expiry only when the owner set one. Money that can be spent, so the
    bound is here as well as on the card."""
    if not isinstance(value, dict) or set(value) - {"creditAmount", "expiresAt"} or "creditAmount" not in value:
        return False
    money = value["creditAmount"]
    if not isinstance(money, dict) or set(money) != {"amount", "currencyCode"}:
        return False
    if not _CURRENCY.match(str(money["currencyCode"])) or not _DECIMAL.match(str(money["amount"])):
        return False
    if not 0 < float(money["amount"]) <= MAX_STORE_CREDIT:
        return False
    if "expiresAt" in value and (not isinstance(value["expiresAt"], str) or not _INSTANT.match(value["expiresAt"])):
        return False
    return True


KEEPALIVE_CONNECTIONS = 4
KEEPALIVE_EXPIRY_S = 120.0
# When Shopify says the query cost bucket is short, a read waits this long at most for it
# to refill, once, before being reported as throttled.
THROTTLE_WAIT_MAX_S = 1.5

SCOPES_TTL_S = 600.0
# How long a failed scope check is remembered as failed, so a Shopify that is not answering
# is not asked again on every turn and every tap.
SCOPES_FAILED_TTL_S = 30.0


class ShopifyClient:
    def __init__(
        self,
        shop_domain: str,
        api_version: str,
        *,
        auth_mode: str = "client_credentials",
        timeout_s: float = 15.0,
    ) -> None:
        self.shop_domain = shop_domain
        self.api_version = api_version
        self.auth_mode = auth_mode
        self._timeout = timeout_s
        self._token: _Token | None = None
        self._lock = asyncio.Lock()
        self._tz: ZoneInfo | None = None
        self._shop: dict[str, Any] | None = None
        self.token_requests = 0  # M6 asserts the second run reuses the cache
        self.last_partial_errors: str | None = None
        # One HTTPS connection, kept open between calls. A TLS handshake to Shopify costs a
        # few hundred milliseconds; a question that makes two lookups was paying it twice.
        self._http: httpx.AsyncClient | None = None
        self.mutations_sent = 0   # every reviewed mutation this process has sent
        self._scopes: frozenset[str] | None = None
        self._scopes_at = 0.0
        self._scopes_failed_at = 0.0
        # What the last answer said about the query cost bucket: requested, actual, and how
        # much is left. For the timings, and for waiting rather than failing when it is short.
        self.last_cost: dict[str, float] = {}

    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            # Kept warm for minutes, not httpx's five seconds: the order, the customer's
            # history and the scope check go out together and must not each open a socket.
            self._http = httpx.AsyncClient(
                timeout=self._timeout,
                limits=httpx.Limits(max_keepalive_connections=KEEPALIVE_CONNECTIONS, keepalive_expiry=KEEPALIVE_EXPIRY_S),
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()
        self._http = None

    # ---------------------------------------------------------------- auth

    @property
    def graphql_url(self) -> str:
        return f"https://{self.shop_domain}/admin/api/{self.api_version}/graphql.json"

    async def _access_token(self) -> str:
        if self.auth_mode == "static_token":
            token = keychain.get_optional("shopify_static_token")
            if not token:
                raise ShopifyAuthError(
                    "auth_mode is static_token but no shopify_static_token is stored. "
                    "Run: python scripts/set_secrets.py shopify_static_token"
                )
            return token

        async with self._lock:
            if self._token and self._token.fresh:
                return self._token.value

            client_id = keychain.get("shopify_client_id")
            client_secret = keychain.get("shopify_client_secret")
            self.token_requests += 1

            url = f"https://{self.shop_domain}/admin/oauth/access_token"
            try:
                response = await self._client().post(
                    url,
                    json={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "grant_type": "client_credentials",
                    },
                )
            except httpx.HTTPError as exc:
                raise ShopifyAuthError(f"Could not reach Shopify to mint a token: {exc}") from exc

            if response.status_code != 200:
                body = response.text[:300]
                if "shop_not_permitted" in body:
                    raise ShopifyAuthError(
                        "shop_not_permitted — the app and the store are in different Shopify "
                        "organisations. This cannot be fixed in config and apps cannot be moved. "
                        "Either recreate the app in the store's organisation, or set "
                        "CROOKS_SHOPIFY_AUTH_MODE=static_token and store a legacy shpat_ token."
                    )
                raise ShopifyAuthError(
                    f"Token request failed ({response.status_code}): {body}. "
                    "Check the app version was released and installed on the store."
                )

            payload = response.json()
            expires_in = int(payload.get("expires_in", 86399))
            self._token = _Token(
                value=payload["access_token"],
                expires_at=time.time() + expires_in,
                expires_in=expires_in,
            )
            log.info("minted Shopify token, expires_in=%s", expires_in)
            return self._token.value

    @property
    def token_expires_in(self) -> int | None:
        return self._token.expires_in if self._token else None

    # ------------------------------------------------------------- graphql

    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        # Reads only, enforced HERE and not only by the scope list the owner types into a
        # console. A document whose operation is a mutation never leaves this process by this
        # path; the reviewed writes go through `mutate()`, by name.
        if _is_mutation(query):
            raise ShopifyError("Refused: this path never sends a Shopify mutation.")
        try:
            return await self._post(query, variables)
        except ShopifyThrottled as exc:
            # The bucket was short. A read is safe to send again: wait for the refill Shopify
            # itself described (bounded), then once more. A mutation never takes this path.
            wait = min(max(exc.wait_s, 0.2), THROTTLE_WAIT_MAX_S)
            log.info("Shopify throttled a read; waiting %.1fs once", wait)
            await asyncio.sleep(wait)
            return await self._post(query, variables)

    async def mutate(self, name: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Send one reviewed mutation by name. The document comes from REVIEWED_MUTATIONS,
        the variables must be exactly the set it declares, and every string is bounded. There
        is no way to pass a document in."""
        # Before the name is even looked up. Every Shopify change in the application comes
        # through here, so a process that has latched read-only cannot make one.
        readonly.assert_writable(f"the Shopify mutation {name!r}")
        reviewed = REVIEWED_MUTATIONS.get(name)
        if reviewed is None:
            raise ShopifyWithheld(f"Refused: {name!r} is not a reviewed mutation.")
        if not isinstance(variables, dict) or set(variables) != set(reviewed.variables):
            raise ShopifyWithheld(f"Refused: {name} variables do not match the reviewed set.")
        for key, kind in reviewed.variables.items():
            value = variables[key]
            if not isinstance(value, kind) or isinstance(value, bool) and kind is not bool:
                raise ShopifyWithheld(f"Refused: {name}.{key} has the wrong type.")
            if isinstance(value, str) and (not value.strip() if key == "id" else len(value) > reviewed.max_chars):
                raise ShopifyWithheld(f"Refused: {name}.{key} is out of bounds.")
            if isinstance(value, list):
                # A list carries strings only, each bounded, and not too many of them.
                if not value or len(value) > 20 or any(not isinstance(v, str) or not v.strip() or len(v) > reviewed.max_chars for v in value):
                    raise ShopifyWithheld(f"Refused: {name}.{key} is out of bounds.")
            if isinstance(value, dict) and reviewed.validate is not None and not reviewed.validate(key, value):
                raise ShopifyWithheld(f"Refused: {name}.{key} does not match the reviewed shape.")
        self.mutations_sent += 1
        log.info("mutation %s sent", name)
        try:
            return await self._post(reviewed.document, variables, mutation=True, root=reviewed.root)
        except ShopifyScopeRefused:
            if self.auth_mode == "static_token" or self._token is None or not reviewed.idempotent:
                # Never a second send of a change that could apply twice. The scope refusal
                # is reported; the owner grants the scope and asks again.
                raise
            # A client-credentials token lives a day and carries the scopes granted when it was
            # minted. The store granted write_orders after that: one fresh token, one retry —
            # for a mutation that leaves the same state however many times it is sent, and
            # only after a refusal that proved nothing ran (the root came back null).
            log.warning("mutation %s refused for scope; re-minting the token once", name)
            self._token = None
            self._scopes = None
            self.mutations_sent += 1
            return await self._post(reviewed.document, variables, mutation=True, root=reviewed.root)

    async def job_done(self, job_id: str) -> bool | None:
        """Whether a job Shopify started has finished. None when Shopify no longer knows it."""
        payload = await self.graphql("query CrooksJob($id: ID!) { job(id: $id) { id done } }", {"id": job_id})
        job = (payload.get("data") or {}).get("job")
        if not isinstance(job, dict):
            return None
        return bool(job.get("done"))

    async def access_scopes(self, *, refresh: bool = False) -> frozenset[str]:
        """What the store has granted this app. A read, cached briefly: the write preflight
        asks on every health poll and must not cost a query each time."""
        if self._scopes is not None and not refresh and time.time() - self._scopes_at < SCOPES_TTL_S:
            return self._scopes
        if not refresh and time.time() - self._scopes_failed_at < SCOPES_FAILED_TTL_S:
            # It did not answer a moment ago. Asking again on every turn and every tap would
            # spend the preflight's whole bound each time, and the caller treats a scope check
            # it cannot make as "unknown" — which is applicable, with Shopify deciding the tap.
            raise ShopifyError("the scope check failed a moment ago")
        try:
            payload = await self.graphql(
                "query CrooksScopes { currentAppInstallation { accessScopes { handle } } }"
            )
        except Exception:
            self._scopes_failed_at = time.time()
            raise
        installation = (payload.get("data") or {}).get("currentAppInstallation") or {}
        self._scopes = frozenset(
            str(s.get("handle", "")) for s in installation.get("accessScopes") or [] if isinstance(s, dict)
        )
        self._scopes_at = time.time()
        self._scopes_failed_at = 0.0
        return self._scopes

    async def _post(self, query: str, variables: dict[str, Any] | None = None, *, mutation: bool = False, root: str = "") -> dict[str, Any]:
        token = await self._access_token()
        try:
            response = await self._client().post(
                self.graphql_url,
                headers={
                    "X-Shopify-Access-Token": token,
                    "Content-Type": "application/json",
                },
                json={"query": query, "variables": variables or {}},
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise ShopifyUnreached(f"Could not reach Shopify: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ShopifyError(f"Could not reach Shopify: {exc}") from exc

        if response.status_code == 401:
            self._token = None
            raise ShopifyAuthError("Shopify rejected the token (401). It may have been revoked.")
        if response.status_code == 429:
            raise ShopifyThrottled("Shopify is rate-limiting us. Try again in a moment.", wait_s=_retry_after(response))
        if response.status_code != 200:
            raise ShopifyError(f"Shopify returned {response.status_code}: {response.text[:200]}")

        payload = response.json()
        self.last_cost = _cost_of(payload)

        # A 200 with an `errors` array is normal for protected customer data: fields come back
        # null and the reason is in `errors`. Reading only `data` makes that look like an outage.
        errors = payload.get("errors")
        self.last_partial_errors = None
        if errors:
            messages = "; ".join(
                str(e.get("message", e)) for e in errors if isinstance(e, dict)
            ) or str(errors)
            codes = {
                str((e.get("extensions") or {}).get("code", "")).upper()
                for e in errors if isinstance(e, dict)
            }
            # Throttling and cost overruns come back as HTTP 200 with an errors array, not 429.
            if "THROTTLED" in codes:
                raise ShopifyThrottled("Shopify is rate-limiting us. Try again in a moment.", wait_s=_refill_wait(self.last_cost))
            if "MAX_COST_EXCEEDED" in codes:
                raise ShopifyError("That query was too expensive for Shopify; narrow it.")
            data = payload.get("data")
            root_value = (data or {}).get(root) if isinstance(data, dict) and root else None
            if mutation and "ACCESS_DENIED" in codes and (data is None or (root and root_value is None)):
                # For a read, ACCESS_DENIED is protected customer data coming back redacted and
                # the rest of the answer stands. For a mutation it is a refusal ONLY when the
                # mutation's own root came back null: a root that came back, with a redacted
                # field inside it, is a change that RAN. This type is raised for the refusal
                # alone — it is what permits a second send, and a second send of a change
                # that ran would be a second change.
                raise ShopifyScopeRefused(f"Shopify refused the change (ACCESS_DENIED): {messages[:160]}")
            if data is None:
                raise ShopifyError(f"Shopify rejected the query: {messages}")
            log.warning("Shopify partial errors (likely protected-data redaction): %s", messages)
            payload.setdefault("_partial_errors", messages)
            self.last_partial_errors = messages

        user_errors = _collect_user_errors(payload.get("data") or {})
        if user_errors:
            codes = {str(e.get("code") or "").upper() for e in user_errors if isinstance(e, dict)}
            messages = "; ".join(str(e.get("message", e)) for e in user_errors)
            if codes & PRECONDITION_CODES:
                raise ShopifyPreconditionFailed(messages)
            raise ShopifyRefused(messages)

        return payload

    # ---------------------------------------------------------------- shop

    async def shop(self, *, refresh: bool = False) -> dict[str, Any]:
        if self._shop is not None and not refresh:
            return self._shop
        payload = await self.graphql(
            """
            query Shop {
              shop {
                name
                myshopifyDomain
                ianaTimezone
                currencyCode
                plan { publicDisplayName }
              }
            }
            """
        )
        self._shop = payload["data"]["shop"]
        self._tz = ZoneInfo(self._shop["ianaTimezone"])
        return self._shop

    async def timezone(self) -> ZoneInfo:
        """The shop's timezone, read from Shopify. Never hardcode the offset: it is correct all
        winter and an hour wrong all summer, which is the worst possible failure shape."""
        if self._tz is None:
            await self.shop()
        assert self._tz is not None
        return self._tz

    async def local_day_bounds(self, days_back: int = 0) -> tuple[str, str]:
        """UTC instants bracketing a shop-local day, as ISO-8601 for a Shopify search query."""
        tz = await self.timezone()
        now_local = datetime.now(tz)
        start_local = (now_local - timedelta(days=days_back)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end_local = start_local + timedelta(days=1)
        return _iso_utc(start_local), _iso_utc(end_local)

    async def health(self) -> tuple[bool, str]:
        try:
            shop = await self.shop(refresh=True)
            return True, f"{shop['name']} ({shop['ianaTimezone']})"
        except (ShopifyAuthError, ShopifyError) as exc:
            return False, str(exc)
        except Exception as exc:  # noqa: BLE001
            return False, f"Shopify check failed: {exc}"


_MUTATION_RE = re.compile(r"^\s*(?:#[^\n]*\n\s*)*mutation\b", re.I)


def _is_mutation(document: str) -> bool:
    """True if the document holds a mutation operation anywhere in it. Anonymous `{ ... }` and
    `query` documents are reads; `mutation Name(`, `mutation Name {`, `mutation {` and
    `mutation{` — first in the document or after another operation — are all writes, and this
    path never sends one."""
    return bool(_MUTATION_RE.match(document or "")) or bool(
        re.search(r"(?:^|[\s};])mutation\b\s*(?:\w+\s*)?[({]", document or "", re.I)
    )


def _cost_of(payload: dict[str, Any]) -> dict[str, float]:
    """The cost extension, as numbers: requested, actual, available, restore rate."""
    cost = (payload.get("extensions") or {}).get("cost") if isinstance(payload, dict) else None
    if not isinstance(cost, dict):
        return {}
    throttle = cost.get("throttleStatus") or {}
    out: dict[str, float] = {}
    for key, value in (
        ("requested", cost.get("requestedQueryCost")), ("actual", cost.get("actualQueryCost")),
        ("available", throttle.get("currentlyAvailable")), ("restore_rate", throttle.get("restoreRate")),
        ("maximum", throttle.get("maximumAvailable")),
    ):
        try:
            if value is not None:
                out[key] = float(value)
        except (TypeError, ValueError):
            pass
    return out


def _refill_wait(cost: dict[str, float]) -> float:
    """How long until the bucket holds what the last query asked for, by Shopify's own numbers."""
    requested, available, rate = cost.get("requested"), cost.get("available"), cost.get("restore_rate")
    if requested is None or available is None or not rate:
        return 0.5
    return max(0.0, (requested - available) / rate)


def _retry_after(response: httpx.Response) -> float:
    try:
        return float(response.headers.get("retry-after", "0.5"))
    except ValueError:
        return 0.5


def _iso_utc(dt: datetime) -> str:

    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _collect_user_errors(node: Any, found: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Every user error in a payload, whatever the payload calls its list: `userErrors`,
    `orderCancelUserErrors`, `inventoryAdjustQuantitiesUserErrors` — any key ending in
    UserErrors. Each is a dict with at least a message, and a code when Shopify gave one."""
    found = found if found is not None else []
    if isinstance(node, dict):
        for key, value in node.items():
            if key.endswith("UserErrors") or key == "userErrors":
                if isinstance(value, list):
                    found.extend(
                        {"message": str(e.get("message", e)), "code": e.get("code"), "field": e.get("field")}
                        for e in value if isinstance(e, dict)
                    )
            else:
                _collect_user_errors(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_user_errors(item, found)
    return found
