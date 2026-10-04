"""A stand-in provider that behaves like Parcel2Go did in its sandbox, including the dangerous
part: paying an already-paid order charges again. Tests switch failures on to prove the
purchase protocol never lets that happen.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from shipping.models import Quote, Shipment
from shipping.money import Money
from shipping.providers.base import (
    Documents,
    OrderReadback,
    ProviderOrder,
    ProviderRefused,
    ProviderUnavailable,
    ProviderUncertain,
)
from shipping.store import now


@dataclass
class FakeOrder:
    ref: str
    reference: str
    amount_minor: int
    paid: bool = False


@dataclass
class FakeProvider:
    name: str = "Parcel2Go"
    price_minor: int = 1069  # what verify and create answer
    orders: dict[str, FakeOrder] = field(default_factory=dict)
    charges: list[str] = field(default_factory=list)  # one entry per money movement
    calls: list[str] = field(default_factory=list)
    # Failure switches, each consumed once unless noted.
    lose_pay_reply: bool = False  # charges, then the reply is lost (ProviderUncertain)
    pay_uncertain_not_charged: bool = False  # times out and, in truth, did not charge
    refuse_pay: bool = False  # declined, not charged (ProviderRefused)
    pay_unreachable: bool = False  # request never delivered (ProviderUnavailable)
    create_uncertain: bool = False  # order may or may not exist
    documents_down: int = 0  # documents fail this many times
    read_down: int = 0  # read_order fails this many times
    readback_lags: int = 0  # read_order says unpaid this many times even if paid
    _ids: itertools.count = field(default_factory=lambda: itertools.count(91234))

    def quotes(self, shipment: Shipment) -> list[Quote]:
        self.calls.append("quotes")
        return [
            Quote(
                provider=self.name,
                carrier="DPD",
                service_code="dpd-classic",
                service_name="Classic",
                amount=Money(minor=self.price_minor),
                est_days_min=2,
                est_days_max=3,
                generated_at=now(),
            ),
        ]

    def verify(self, shipment: Shipment, quote: Quote) -> int:
        self.calls.append("verify")
        return self.price_minor

    def create_order(self, shipment: Shipment, quote: Quote, reference: str) -> ProviderOrder:
        self.calls.append("create_order")
        ref = f"fake:{next(self._ids)}"
        self.orders[ref] = FakeOrder(ref=ref, reference=reference, amount_minor=self.price_minor)
        if self.create_uncertain:
            self.create_uncertain = False
            raise ProviderUncertain("timed out after sending")
        return ProviderOrder(ref=ref, amount_minor=self.price_minor, currency="GBP")

    def pay(self, ref: str) -> None:
        self.calls.append("pay")
        if self.pay_unreachable:
            self.pay_unreachable = False
            raise ProviderUnavailable("connection refused")
        if self.refuse_pay:
            self.refuse_pay = False
            raise ProviderRefused("Not enough PrePay balance")
        if self.pay_uncertain_not_charged:
            self.pay_uncertain_not_charged = False
            raise ProviderUncertain("timed out; the payment did not actually go through")
        order = self.orders[ref]
        # Like the real thing: a paid order paid again is charged again.
        order.paid = True
        self.charges.append(ref)
        if self.lose_pay_reply:
            self.lose_pay_reply = False
            raise ProviderUncertain("connection lost before the reply")

    def read_order(self, ref: str) -> OrderReadback:
        self.calls.append("read_order")
        if self.read_down:
            self.read_down -= 1
            raise ProviderUnavailable("read failed")
        order = self.orders[ref]
        if self.readback_lags:
            self.readback_lags -= 1
            return OrderReadback(paid=False, amount_minor=order.amount_minor)
        return OrderReadback(paid=order.paid, amount_minor=order.amount_minor)

    def documents(self, ref: str) -> Documents:
        self.calls.append("documents")
        if self.documents_down:
            self.documents_down -= 1
            raise ProviderUnavailable("label not ready")
        if not self.orders[ref].paid:
            raise ProviderRefused("order not paid")
        return Documents(
            label_4x6=b"%PDF 4x6 " + ref.encode(),
            label_a4=b"%PDF a4 " + ref.encode(),
            tracking_number=f"H{ref[-5:]}GB",
            tracking_url=f"https://track.example/{ref[-5:]}",
        )

    def charges_for(self, ref: str) -> int:
        return self.charges.count(ref)
