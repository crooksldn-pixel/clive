"""Persistence: one SQLite file for Phase 1. Every table is keyed by shop, and every read takes
the shop, so one merchant's id can never fetch another's record.

The purchase ledger's safety does not rest on the in-process lock alone: a partial unique index
allows only one open buy operation per shipment, so two workers (or two processes) racing to
buy the same label cannot both get a row.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from shipping.models import OPEN_OP_STATES, ProviderOp, Shipment, ShopConfig

SCHEMA = """
CREATE TABLE IF NOT EXISTS print_intents (
  shop TEXT NOT NULL, id TEXT NOT NULL, request_key TEXT NOT NULL, doc TEXT NOT NULL,
  PRIMARY KEY(shop, id), UNIQUE(shop, request_key)
);
CREATE TABLE IF NOT EXISTS shipments (
  shop TEXT NOT NULL,
  id TEXT NOT NULL,
  order_id TEXT NOT NULL,
  fulfillment_order_id TEXT NOT NULL,
  status TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  doc TEXT NOT NULL,
  PRIMARY KEY (shop, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS shipments_fo ON shipments(shop, fulfillment_order_id);
CREATE INDEX IF NOT EXISTS shipments_status ON shipments(shop, status, updated_at);
CREATE TABLE IF NOT EXISTS provider_ops (
  shop TEXT NOT NULL,
  id TEXT NOT NULL,
  shipment_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  state TEXT NOT NULL,
  open INTEGER NOT NULL,
  doc TEXT NOT NULL,
  PRIMARY KEY (shop, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ops_key ON provider_ops(shop, idempotency_key);
-- At most one buy in flight per shipment, whatever happens above this layer.
CREATE UNIQUE INDEX IF NOT EXISTS ops_one_open ON provider_ops(shop, shipment_id) WHERE open = 1;
CREATE TABLE IF NOT EXISTS shops (
  shop TEXT PRIMARY KEY,
  doc TEXT NOT NULL
);
-- What the merchant confirmed, once. scope: product (HS code, origin, description: the same for
-- every size) or item (weight, per inventory item). Shopify stays the record; these remember
-- who confirmed what, and keep the answer if Shopify refused to store it.
CREATE TABLE IF NOT EXISTS facts (
  shop TEXT NOT NULL,
  scope TEXT NOT NULL,
  subject TEXT NOT NULL,
  fact TEXT NOT NULL,
  value TEXT NOT NULL,
  source TEXT NOT NULL,
  actor TEXT NOT NULL,
  at TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  shopify_written INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (shop, scope, subject, fact)
);
-- Which package a confirmed shipment of these items went in (learned on purchase).
CREATE TABLE IF NOT EXISTS package_choices (
  shop TEXT NOT NULL,
  signature TEXT NOT NULL,
  preset_id TEXT NOT NULL,
  uses INTEGER NOT NULL,
  at TEXT NOT NULL,
  PRIMARY KEY (shop, signature)
);
-- Customs paperwork actually seen on this shop's labels, per service and destination country:
-- what the rate recommendation trusts over any seeded expectation.
CREATE TABLE IF NOT EXISTS service_paperwork (
  shop TEXT NOT NULL,
  service_code TEXT NOT NULL,
  country TEXT NOT NULL,
  mode TEXT NOT NULL,
  copies INTEGER NOT NULL,
  seen INTEGER NOT NULL,
  at TEXT NOT NULL,
  PRIMARY KEY (shop, service_code, country)
);
-- Provider reference data (e.g. Parcel2Go's country list), cached so screens and quotes don't
-- depend on the provider being up. Not per shop: it describes the provider, not a merchant.
CREATE TABLE IF NOT EXISTS reference (
  provider TEXT NOT NULL,
  kind TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  doc TEXT NOT NULL,
  PRIMARY KEY (provider, kind)
);
CREATE TABLE IF NOT EXISTS artifacts (
  shop TEXT NOT NULL,
  id TEXT NOT NULL,
  shipment_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  content_type TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  at TEXT NOT NULL,
  body BLOB NOT NULL,
  PRIMARY KEY (shop, id)
);
"""


def now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


class Conflict(RuntimeError):
    """The shipment changed since it was read; saving this copy would overwrite that change."""


class OpenOperationExists(RuntimeError):
    """Another buy for this shipment is already in flight or being checked."""


class Store:
    def __init__(self, path: str) -> None:
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        self.lock = threading.RLock()
        self._depth = 0

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Several writes as one: all of them, or none (a crash rolls back). Re-entrant."""
        with self.lock:
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

    # ---------------------------------------------------------------- shipments

    def save(self, s: Shipment) -> Shipment:
        """Write the shipment if nobody saved it since this copy was read; else Conflict.

        Without this, a slow reader (a refresh waiting on the provider for quotes) could save
        its old copy over a purchase made meanwhile: a paid shipment back to "ready" with no
        label, and the next click would buy again."""
        with self.lock:
            read_as = s.version
            s.version, s.updated_at = read_as + 1, now()
            doc = s.model_dump_json()
            changed = self._db.execute(
                "UPDATE shipments SET status=?, updated_at=?, doc=? WHERE shop=? AND id=? "
                "AND COALESCE(json_extract(doc, '$.version'), 0)=?",
                (s.status.value, s.updated_at.isoformat(), doc, s.shop, s.id, read_as),
            ).rowcount
            if changed:
                return s
            exists = self._db.execute(
                "SELECT 1 FROM shipments WHERE shop=? AND id=?", (s.shop, s.id)
            ).fetchone()
            if exists:
                s.version = read_as
                raise Conflict(f"Shipment {s.id} changed since it was read.")
            self._db.execute(
                "INSERT INTO shipments (shop, id, order_id, fulfillment_order_id, status, "
                "updated_at, doc) VALUES (?,?,?,?,?,?,?)",
                (
                    s.shop,
                    s.id,
                    s.order_id,
                    s.fulfillment_order_id,
                    s.status.value,
                    s.updated_at.isoformat(),
                    doc,
                ),
            )
        return s

    def get(self, shop: str, shipment_id: str) -> Shipment | None:
        row = self._db.execute(
            "SELECT doc FROM shipments WHERE shop=? AND id=?", (shop, shipment_id)
        ).fetchone()
        return Shipment.model_validate_json(row[0]) if row else None

    def shipments(self, shop: str, statuses: list[str] | None = None) -> list[Shipment]:
        sql, args = "SELECT doc FROM shipments WHERE shop=?", [shop]
        if statuses:
            sql += f" AND status IN ({','.join('?' * len(statuses))})"
            args += statuses
        rows = self._db.execute(sql + " ORDER BY updated_at DESC", args).fetchall()
        return [Shipment.model_validate_json(r[0]) for r in rows]

    # ---------------------------------------------------------------- the ledger

    def add_op(self, op: ProviderOp) -> None:
        try:
            with self.lock:
                self._db.execute(
                    "INSERT INTO provider_ops (shop, id, shipment_id, idempotency_key, state, "
                    "open, doc) VALUES (?,?,?,?,?,?,?)",
                    (
                        op.shop,
                        op.id,
                        op.shipment_id,
                        op.idempotency_key,
                        op.state.value,
                        1,
                        op.model_dump_json(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise OpenOperationExists(str(exc)) from exc

    def save_op(self, op: ProviderOp) -> None:
        """Compare-and-set, like shipments: a copy read before someone else's save (a timer
        sweep, a stalled request thread) is refused with Conflict instead of overwriting."""
        with self.lock:
            read_as = op.version
            op.version = read_as + 1
            changed = self._db.execute(
                "UPDATE provider_ops SET state=?, open=?, doc=? WHERE shop=? AND id=? "
                "AND COALESCE(json_extract(doc, '$.version'), 0)=?",
                (
                    op.state.value,
                    1 if op.state in OPEN_OP_STATES else 0,
                    op.model_dump_json(),
                    op.shop,
                    op.id,
                    read_as,
                ),
            ).rowcount
            if not changed:
                op.version = read_as
                raise Conflict(f"Operation {op.id} changed since it was read.")

    def op(self, shop: str, op_id: str) -> ProviderOp | None:
        row = self._db.execute(
            "SELECT doc FROM provider_ops WHERE shop=? AND id=?", (shop, op_id)
        ).fetchone()
        return ProviderOp.model_validate_json(row[0]) if row else None

    def op_by_key(self, shop: str, key: str) -> ProviderOp | None:
        row = self._db.execute(
            "SELECT doc FROM provider_ops WHERE shop=? AND idempotency_key=?", (shop, key)
        ).fetchone()
        return ProviderOp.model_validate_json(row[0]) if row else None

    def open_op(self, shop: str, shipment_id: str) -> ProviderOp | None:
        row = self._db.execute(
            "SELECT doc FROM provider_ops WHERE shop=? AND shipment_id=? AND open=1",
            (shop, shipment_id),
        ).fetchone()
        return ProviderOp.model_validate_json(row[0]) if row else None

    def ops_for(self, shop: str, shipment_id: str) -> list[ProviderOp]:
        rows = self._db.execute(
            "SELECT doc FROM provider_ops WHERE shop=? AND shipment_id=?", (shop, shipment_id)
        ).fetchall()
        return [ProviderOp.model_validate_json(r[0]) for r in rows]

    def open_ops(self) -> list[ProviderOp]:
        rows = self._db.execute("SELECT doc FROM provider_ops WHERE open=1").fetchall()
        return [ProviderOp.model_validate_json(r[0]) for r in rows]

    # ---------------------------------------------------------------- shop settings

    def config(self, shop: str) -> ShopConfig:
        row = self._db.execute("SELECT doc FROM shops WHERE shop=?", (shop,)).fetchone()
        return ShopConfig.model_validate_json(row[0]) if row else ShopConfig(shop=shop)

    def save_config(self, cfg: ShopConfig) -> None:
        with self.lock:
            self._db.execute(
                "INSERT INTO shops (shop, doc) VALUES (?,?) ON CONFLICT(shop) DO UPDATE SET "
                "doc=excluded.doc",
                (cfg.shop, cfg.model_dump_json()),
            )

    # ---------------------------------------------------------------- knowledge

    def put_fact(
        self,
        shop: str,
        scope: str,
        subject: str,
        fact: str,
        value: str,
        *,
        source: str,
        actor: str,
        label: str = "",
        shopify_written: bool = False,
    ) -> None:
        with self.lock:
            self._db.execute(
                "INSERT INTO facts (shop, scope, subject, fact, value, source, actor, at, label, "
                "shopify_written) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(shop, scope, subject, "
                "fact) DO UPDATE SET value=excluded.value, source=excluded.source, "
                "actor=excluded.actor, at=excluded.at, label=excluded.label, "
                "shopify_written=excluded.shopify_written",
                (
                    shop,
                    scope,
                    subject,
                    fact,
                    value,
                    source,
                    actor,
                    now().isoformat(),
                    label,
                    int(shopify_written),
                ),
            )

    def fact(self, shop: str, scope: str, subject: str, fact: str) -> str | None:
        row = self._db.execute(
            "SELECT value FROM facts WHERE shop=? AND scope=? AND subject=? AND fact=?",
            (shop, scope, subject, fact),
        ).fetchone()
        return row[0] if row else None

    def facts(self, shop: str, scope: str, fact: str) -> list[tuple[str, str, str]]:
        """(subject, value, label) for every confirmed `fact` in this shop."""
        rows = self._db.execute(
            "SELECT subject, value, label FROM facts WHERE shop=? AND scope=? AND fact=? "
            "ORDER BY at DESC",
            (shop, scope, fact),
        ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]

    def record_package_choice(self, shop: str, signature: str, preset_id: str) -> None:
        with self.lock:
            self._db.execute(
                "INSERT INTO package_choices (shop, signature, preset_id, uses, at) VALUES "
                "(?,?,?,1,?) ON CONFLICT(shop, signature) DO UPDATE SET "
                "uses = CASE WHEN preset_id = excluded.preset_id THEN uses + 1 ELSE 1 END, "
                "preset_id=excluded.preset_id, at=excluded.at",
                (shop, signature, preset_id, now().isoformat()),
            )

    def package_choice(self, shop: str, signature: str) -> str | None:
        row = self._db.execute(
            "SELECT preset_id FROM package_choices WHERE shop=? AND signature=?",
            (shop, signature),
        ).fetchone()
        return row[0] if row else None

    # ---------------------------------------------------------------- paperwork seen

    def record_paperwork(
        self, shop: str, service_code: str, country: str, mode: str, copies: int, at: datetime
    ) -> None:
        with self.lock:
            self._db.execute(
                "INSERT INTO service_paperwork VALUES (?,?,?,?,?,1,?) "
                "ON CONFLICT(shop, service_code, country) DO UPDATE SET mode=excluded.mode, "
                "copies=excluded.copies, seen=seen+1, at=excluded.at",
                (shop, service_code, country.upper(), mode, copies, at.isoformat()),
            )

    def paperwork(self, shop: str, service_code: str, country: str) -> tuple[str, int] | None:
        row = self._db.execute(
            "SELECT mode, copies FROM service_paperwork WHERE shop=? AND service_code=? "
            "AND country=?",
            (shop, service_code, country.upper()),
        ).fetchone()
        return (row[0], int(row[1])) if row else None

    # ---------------------------------------------------------------- reference data

    def put_reference(self, provider: str, kind: str, data: Any, at: datetime) -> None:
        with self.lock:
            self._db.execute(
                "INSERT INTO reference (provider, kind, fetched_at, doc) VALUES (?,?,?,?) "
                "ON CONFLICT(provider, kind) DO UPDATE SET fetched_at=excluded.fetched_at, "
                "doc=excluded.doc",
                (provider, kind, at.isoformat(), json.dumps(data)),
            )

    def reference(self, provider: str, kind: str) -> tuple[Any, datetime] | None:
        row = self._db.execute(
            "SELECT doc, fetched_at FROM reference WHERE provider=? AND kind=?", (provider, kind)
        ).fetchone()
        return (json.loads(row[0]), datetime.fromisoformat(row[1])) if row else None

    # ---------------------------------------------------------------- artifacts

    def put_artifact(
        self, shop: str, shipment_id: str, kind: str, content_type: str, body: bytes
    ) -> str:
        artifact_id = new_id("art")
        with self.lock:
            self._db.execute(
                "INSERT INTO artifacts (shop, id, shipment_id, kind, content_type, sha256, at, "
                "body) VALUES (?,?,?,?,?,?,?,?)",
                (
                    shop,
                    artifact_id,
                    shipment_id,
                    kind,
                    content_type,
                    hashlib.sha256(body).hexdigest(),
                    now().isoformat(),
                    body,
                ),
            )
        return artifact_id

    def get_artifact(self, shop: str, artifact_id: str) -> tuple[str, str, bytes] | None:
        row = self._db.execute(
            "SELECT kind, content_type, body FROM artifacts WHERE shop=? AND id=?",
            (shop, artifact_id),
        ).fetchone()
        return (row[0], row[1], row[2]) if row else None

    # Print ledger is separate from the postage purchase ledger.
    def add_print_intent(self, shop, key, record):
        self._db.execute(
            "INSERT INTO print_intents VALUES (?,?,?,?)",
            (shop, record["id"], key, json.dumps(record)),
        )

    def save_print_intent(self, shop, record):
        with self.lock:
            self._db.execute(
                "UPDATE print_intents SET doc=? WHERE shop=? AND id=?",
                (json.dumps(record), shop, record["id"]),
            )

    def print_intent_by_key(self, shop, key):
        row = self._db.execute(
            "SELECT doc FROM print_intents WHERE shop=? AND request_key=?", (shop, key)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def print_intent(self, shop, intent_id):
        row = self._db.execute(
            "SELECT doc FROM print_intents WHERE shop=? AND id=?", (shop, intent_id)
        ).fetchone()
        return json.loads(row[0]) if row else None
