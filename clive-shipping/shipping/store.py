"""Persistence: one SQLite file for Phase 1. Every table is keyed by shop, and every read takes
the shop, so one merchant's id can never fetch another's record.

The purchase ledger's safety does not rest on the in-process lock alone: a partial unique index
allows only one open buy operation per shipment, so two workers (or two processes) racing to
buy the same label cannot both get a row.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
from datetime import UTC, datetime

from shipping.models import OPEN_OP_STATES, ProviderOp, Shipment

SCHEMA = """
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


class OpenOperationExists(RuntimeError):
    """Another buy for this shipment is already in flight or being checked."""


class Store:
    def __init__(self, path: str) -> None:
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        self.lock = threading.RLock()

    # ---------------------------------------------------------------- shipments

    def save(self, s: Shipment) -> Shipment:
        s.updated_at = now()
        with self.lock:
            self._db.execute(
                "INSERT INTO shipments (shop, id, order_id, fulfillment_order_id, status, "
                "updated_at, doc) VALUES (?,?,?,?,?,?,?) ON CONFLICT(shop, id) DO UPDATE SET "
                "status=excluded.status, updated_at=excluded.updated_at, doc=excluded.doc",
                (
                    s.shop,
                    s.id,
                    s.order_id,
                    s.fulfillment_order_id,
                    s.status.value,
                    s.updated_at.isoformat(),
                    s.model_dump_json(),
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
        op.updated_at = now()
        with self.lock:
            self._db.execute(
                "UPDATE provider_ops SET state=?, open=?, doc=? WHERE shop=? AND id=?",
                (
                    op.state.value,
                    1 if op.state in OPEN_OP_STATES else 0,
                    op.model_dump_json(),
                    op.shop,
                    op.id,
                ),
            )

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
