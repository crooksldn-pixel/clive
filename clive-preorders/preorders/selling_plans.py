"""The selling-plan boundary. Nothing else in CLIVE Preorders creates, changes or attaches
selling plans, so the whole preorder system works the same whether or not the app has Shopify's
purchase-option access; only this adapter says whether a preorder can actually be sold.

Without access (or with PREORDERS_SELLING_PLANS=off) nothing is offered on the storefront as a
preorder: no cart properties, no negative inventory, no imitation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from preorders.shopify import PlanSpec, ShopifyPort, ShopifyRefused


class PlansUnavailable(Exception):
    """Preorders can't be put on sale: why, in words for the owner."""


class SellingPlanPort(Protocol):
    """Putting things on sale (create, replace, attach) needs purchase-option access; taking
    them off sale (members, detach) is always attempted, even when selling is unavailable."""

    available: bool
    reason: str

    def create(self, spec: PlanSpec, variant_ids: list[str]) -> tuple[str, str]: ...
    def replace(self, group_id: str, old_plan_id: str | None, spec: PlanSpec) -> str: ...
    def members(self, group_id: str) -> set[str] | None: ...
    def attach(self, group_id: str, variant_ids: list[str]) -> None: ...
    def detach(self, group_id: str, variant_ids: list[str]) -> None: ...
    def retry(self) -> None: ...


NO_ACCESS = (
    "Shopify hasn't given CROOKS Operations purchase-option access (write_purchase_options), so "
    "preorders can't be sold yet. Everything else works. See docs/preorders/IMPLEMENTATION_PLAN.md."
)
OFF = "Preorder selling is switched off on the server (PREORDERS_SELLING_PLANS=off)."


@dataclass
class UnavailablePlans:
    """Selling switched off. With Shopify at hand (the kill switch after offers went live) it can
    still read a group and take variants out of it, so nothing stays on sale by accident."""

    reason: str = OFF
    shopify: ShopifyPort | None = None
    available: bool = False

    def _no(self) -> None:
        raise PlansUnavailable(self.reason)

    def create(self, spec: PlanSpec, variant_ids: list[str]) -> tuple[str, str]:
        self._no()
        raise AssertionError  # unreachable

    def replace(self, group_id: str, old_plan_id: str | None, spec: PlanSpec) -> str:
        self._no()
        raise AssertionError

    def members(self, group_id: str) -> set[str] | None:
        return self.shopify.group_variants(group_id) if self.shopify else None

    def attach(self, group_id: str, variant_ids: list[str]) -> None:
        self._no()

    def detach(self, group_id: str, variant_ids: list[str]) -> None:
        if self.shopify is None:
            self._no()
        else:
            self.shopify.remove_from_group(group_id, variant_ids)

    def retry(self) -> None:
        pass  # switched off on the server: only a restart with the setting changed turns it on


class ShopifyPlans:
    """Selling plans in Shopify. An access refusal switches the adapter off with the reason."""

    def __init__(self, shopify: ShopifyPort) -> None:
        self.shopify = shopify
        self.available = True
        self.reason = ""

    def retry(self) -> None:
        """Access refused earlier: try again (the next pass shows whether it is back)."""
        self.available, self.reason = True, ""

    def _guard(self, exc: ShopifyRefused) -> None:
        if "ACCESS_DENIED" in exc.codes or "access denied" in str(exc).lower():
            self.available, self.reason = False, NO_ACCESS
            raise PlansUnavailable(NO_ACCESS) from exc

    def create(self, spec: PlanSpec, variant_ids: list[str]) -> tuple[str, str]:
        try:
            return self.shopify.create_plan_group(spec, variant_ids)
        except ShopifyRefused as exc:
            self._guard(exc)
            raise

    def replace(self, group_id: str, old_plan_id: str | None, spec: PlanSpec) -> str:
        try:
            return self.shopify.replace_plan(group_id, old_plan_id, spec)
        except ShopifyRefused as exc:
            self._guard(exc)
            raise

    def members(self, group_id: str) -> set[str] | None:
        return self.shopify.group_variants(group_id)

    def attach(self, group_id: str, variant_ids: list[str]) -> None:
        try:
            self.shopify.add_to_group(group_id, variant_ids)
        except ShopifyRefused as exc:
            self._guard(exc)
            raise

    def detach(self, group_id: str, variant_ids: list[str]) -> None:
        self.shopify.remove_from_group(group_id, variant_ids)
