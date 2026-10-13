"""SQLite: the operational source of truth for batches, offers, preorder lines, the waitlist and
every message sent. Relational tables with constraints, not one JSON document.

- Counts are derived from rows (sold = the preorder lines that hold units), never incremented.
- Writes that decide capacity or stock happen inside `tx()` (BEGIN IMMEDIATE: one writer).
- Shopify ids are unique keys, so a webhook seen twice changes nothing the second time.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any


def now() -> datetime:
    return datetime.now(UTC)


def iso(at: datetime | None) -> str | None:
    return at.astimezone(UTC).isoformat() if at else None


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


MIGRATIONS: list[str] = [
    # 1: the first schema
    """
    CREATE TABLE batches (
      id TEXT PRIMARY KEY, shop TEXT NOT NULL, reference TEXT NOT NULL, status TEXT NOT NULL,
      supplier_reference TEXT NOT NULL DEFAULT '', expected_arrival_at TEXT,
      expected_dispatch_at TEXT, notes TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE batch_lines (
      id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(id),
      product_id TEXT NOT NULL, variant_id TEXT NOT NULL, inventory_item_id TEXT,
      sku TEXT NOT NULL DEFAULT '', product_title TEXT NOT NULL DEFAULT '',
      variant_title TEXT NOT NULL DEFAULT '',
      expected_quantity INTEGER NOT NULL CHECK (expected_quantity >= 0),
      received_quantity INTEGER NOT NULL DEFAULT 0 CHECK (received_quantity >= 0),
      preorder_allocation INTEGER NOT NULL DEFAULT 0 CHECK (preorder_allocation >= 0),
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      UNIQUE (batch_id, variant_id),
      CHECK (preorder_allocation <= expected_quantity)
    );
    CREATE TABLE offers (
      id TEXT PRIMARY KEY, shop TEXT NOT NULL, product_id TEXT NOT NULL,
      product_title TEXT NOT NULL DEFAULT '', batch_id TEXT NOT NULL REFERENCES batches(id),
      status TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'AUTO',
      discount_type TEXT NOT NULL DEFAULT 'NONE', discount_value REAL NOT NULL DEFAULT 0,
      dispatch_at TEXT, selling_plan_group_id TEXT, selling_plan_id TEXT,
      plan_signature TEXT, synced_at TEXT, sync_error TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      UNIQUE (shop, product_id, batch_id)
    );
    CREATE TABLE selling_plans (
      plan_id TEXT PRIMARY KEY, offer_id TEXT NOT NULL REFERENCES offers(id),
      dispatch_at TEXT, discount_percent REAL NOT NULL DEFAULT 0, name TEXT NOT NULL,
      created_at TEXT NOT NULL, retired_at TEXT
    );
    CREATE TABLE offer_variants (
      id TEXT PRIMARY KEY, offer_id TEXT NOT NULL REFERENCES offers(id),
      variant_id TEXT NOT NULL, batch_line_id TEXT NOT NULL REFERENCES batch_lines(id),
      enabled INTEGER NOT NULL DEFAULT 1, override_state TEXT,
      original_policy TEXT, last_metafield TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      UNIQUE (offer_id, variant_id)
    );
    CREATE TABLE preorder_lines (
      id TEXT PRIMARY KEY, shop TEXT NOT NULL,
      order_id TEXT NOT NULL, order_name TEXT NOT NULL, line_item_id TEXT NOT NULL UNIQUE,
      customer_name TEXT, customer_email TEXT,
      product_id TEXT, variant_id TEXT, sku TEXT NOT NULL DEFAULT '',
      title TEXT NOT NULL DEFAULT '',
      selling_plan_id TEXT, offer_id TEXT, batch_id TEXT, batch_line_id TEXT,
      quantity INTEGER NOT NULL, current_quantity INTEGER NOT NULL,
      fulfilled_quantity INTEGER NOT NULL DEFAULT 0,
      unit_price_minor INTEGER NOT NULL DEFAULT 0, discount_minor INTEGER NOT NULL DEFAULT 0,
      currency TEXT NOT NULL DEFAULT 'GBP',
      promised_dispatch_at TEXT, current_dispatch_at TEXT,
      state TEXT NOT NULL, ready_quantity INTEGER NOT NULL DEFAULT 0,
      cancelled_at TEXT, ordered_at TEXT NOT NULL,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX preorder_lines_offer ON preorder_lines (offer_id, variant_id);
    CREATE INDEX preorder_lines_order ON preorder_lines (order_id);
    CREATE INDEX preorder_lines_batch ON preorder_lines (batch_line_id);
    CREATE TABLE unplanned_lines (
      line_item_id TEXT PRIMARY KEY, shop TEXT NOT NULL, order_id TEXT NOT NULL,
      order_name TEXT NOT NULL, variant_id TEXT NOT NULL, quantity INTEGER NOT NULL,
      seen_at TEXT NOT NULL, resolved_at TEXT
    );
    CREATE TABLE waitlist (
      id TEXT PRIMARY KEY, shop TEXT NOT NULL, product_id TEXT NOT NULL,
      variant_id TEXT NOT NULL, product_title TEXT NOT NULL DEFAULT '',
      variant_title TEXT NOT NULL DEFAULT '', email TEXT NOT NULL, customer_id TEXT,
      status TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'storefront',
      subscribed_at TEXT NOT NULL, notified_at TEXT, notification_reason TEXT,
      converted_at TEXT, unsubscribed_at TEXT
    );
    CREATE UNIQUE INDEX waitlist_one_active ON waitlist (shop, variant_id, email)
      WHERE status = 'ACTIVE';
    CREATE INDEX waitlist_variant ON waitlist (shop, variant_id, status);
    CREATE TABLE communications (
      id TEXT PRIMARY KEY, shop TEXT NOT NULL, kind TEXT NOT NULL, recipient TEXT NOT NULL,
      dedupe_key TEXT NOT NULL UNIQUE, order_id TEXT, variant_id TEXT, batch_id TEXT,
      status TEXT NOT NULL, provider_id TEXT, error TEXT, detail TEXT NOT NULL DEFAULT '{}',
      actor TEXT NOT NULL DEFAULT 'system', created_at TEXT NOT NULL, sent_at TEXT
    );
    CREATE TABLE receipts (
      id TEXT PRIMARY KEY, batch_line_id TEXT NOT NULL REFERENCES batch_lines(id),
      quantity INTEGER NOT NULL CHECK (quantity > 0), idempotency_key TEXT NOT NULL UNIQUE,
      location_id TEXT, status TEXT NOT NULL, error TEXT, actor TEXT NOT NULL,
      created_at TEXT NOT NULL, applied_at TEXT
    );
    CREATE TABLE webhook_inbox (
      event_id TEXT PRIMARY KEY, topic TEXT NOT NULL, resource_id TEXT NOT NULL,
      received_at TEXT NOT NULL, processed_at TEXT, attempts INTEGER NOT NULL DEFAULT 0,
      error TEXT
    );
    CREATE TABLE catalog (
      variant_id TEXT PRIMARY KEY, shop TEXT NOT NULL, product_id TEXT NOT NULL,
      product_title TEXT NOT NULL, variant_title TEXT NOT NULL, sku TEXT NOT NULL DEFAULT '',
      inventory_item_id TEXT, inventory_policy TEXT, tracked INTEGER NOT NULL DEFAULT 1,
      available INTEGER NOT NULL DEFAULT 0, committed INTEGER NOT NULL DEFAULT 0,
      incoming INTEGER NOT NULL DEFAULT 0, on_hand INTEGER NOT NULL DEFAULT 0,
      price_minor INTEGER NOT NULL DEFAULT 0, currency TEXT NOT NULL DEFAULT 'GBP',
      image_url TEXT, handle TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL DEFAULT 0,
      refreshed_at TEXT NOT NULL
    );
    CREATE INDEX catalog_product ON catalog (shop, product_id);
    CREATE TABLE events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, shop TEXT NOT NULL, at TEXT NOT NULL,
      kind TEXT NOT NULL, subject TEXT NOT NULL DEFAULT '', actor TEXT NOT NULL DEFAULT 'system',
      detail TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX events_subject ON events (shop, subject);
    """,
    # 2: a ready preorder is offered for release once; set when its fulfilment order is open.
    "ALTER TABLE preorder_lines ADD COLUMN released_at TEXT",
]


class Store:
    def __init__(self, path: str) -> None:
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._lock = threading.RLock()
        self._depth = 0
        self._migrate()

    def _migrate(self) -> None:
        self._db.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = self._db.execute("SELECT MAX(version) FROM schema_version").fetchone()
        done = row[0] or 0
        for version, script in enumerate(MIGRATIONS, start=1):
            if version <= done:
                continue
            with self.tx():
                for statement in [s.strip() for s in script.split(";") if s.strip()]:
                    self._db.execute(statement)
                self._db.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))

    @contextmanager
    def tx(self) -> Iterator[None]:
        """One writer at a time. Nested calls join the outer transaction."""
        with self._lock:
            outer = self._depth == 0
            if outer:
                self._db.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield
            except BaseException:
                self._depth -= 1
                if outer:
                    self._db.execute("ROLLBACK")
                raise
            self._depth -= 1
            if outer:
                self._db.execute("COMMIT")

    def x(self, sql: str, args: tuple[Any, ...] | list[Any] = ()) -> int:
        with self._lock:
            return self._db.execute(sql, args).rowcount

    def all(self, sql: str, args: tuple[Any, ...] | list[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple[Any, ...] | list[Any] = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(sql, args).fetchone()
            return dict(row) if row else None

    def value(self, sql: str, args: tuple[Any, ...] | list[Any] = ()) -> Any:
        with self._lock:
            row = self._db.execute(sql, args).fetchone()
            return row[0] if row else None

    def insert(self, table: str, row: dict[str, Any]) -> None:
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        self.x(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(row.values()))

    def update(self, table: str, key: str, ident: Any, changes: dict[str, Any]) -> int:
        sets = ", ".join(f"{k} = ?" for k in changes)
        return self.x(f"UPDATE {table} SET {sets} WHERE {key} = ?", [*changes.values(), ident])

    def event(
        self,
        shop: str,
        kind: str,
        subject: str = "",
        detail: dict[str, Any] | None = None,
        actor: str = "system",
    ) -> None:
        """The audit trail: what happened, to what, by whom. Identifiers, never payloads."""
        self.insert(
            "events",
            {
                "shop": shop,
                "at": iso(now()),
                "kind": kind,
                "subject": subject,
                "actor": actor,
                "detail": json.dumps(detail or {}, default=str),
            },
        )
