"""Choosing a service. Stage 2 keeps this deliberately small: the cheapest quote that exists.
Stage 4 replaces recommend() with recommended / cheapest / fastest (price, speed and carrier
reliability), without changing callers."""

from __future__ import annotations

from shipping.models import Quote


def recommend(quotes: list[Quote]) -> Quote | None:
    if not quotes:
        return None
    return min(quotes, key=lambda q: (q.amount.minor, q.est_days_max or 99))
