"""Persistence: one SQLite file. A return is stored whole as JSON with its indexed fields beside
it; every change appends to its timeline, and idempotency keys remember the answer to an
action so a retried request never repeats a refund.

The outbox (on only when CLIVE's hook is configured, `outbox=True`): every event a save adds to a
return's timeline gets one row in the same transaction, which the doorbell (returns/doorbell.py)
posts to CLIVE. A row that cannot be written never stops the return being saved."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import sqlite3
import threading
from datetime import UTC, datetime

from returns.models import OPEN_STATUSES, Return, Status

SCHEMA = """
CREATE TABLE IF NOT EXISTS returns (
  id TEXT PRIMARY KEY,
  order_id TEXT NOT NULL,
  order_name TEXT NOT NULL,
  status TEXT NOT NULL,
  shopify_return_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  doc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS returns_order ON returns(order_id);
CREATE INDEX IF NOT EXISTS returns_status ON returns(status, updated_at);
CREATE INDEX IF NOT EXISTS returns_shopify ON returns(shopify_return_id);
CREATE TABLE IF NOT EXISTS idempotency (
  key TEXT PRIMARY KEY,
  at TEXT NOT NULL,
  response TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS options (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
  id TEXT PRIMARY KEY,
  return_id TEXT NOT NULL,
  content_type TEXT NOT NULL,
  at TEXT NOT NULL,
  body BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
  id TEXT PRIMARY KEY,
  return_id TEXT NOT NULL,
  type TEXT NOT NULL,
  at TEXT NOT NULL,
  queued_at TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  next_at TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'waiting',
  tried_at TEXT,
  last_answer TEXT
);
CREATE INDEX IF NOT EXISTS outbox_due ON outbox(state, next_at);
"""

log = logging.getLogger("returns.store")


def now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(5)}"


def event_id(return_id: str, index: int, at: str, kind: str) -> str:
    """An event's id for CLIVE: the same event always gets the same id, two never share one."""
    digest = hashlib.sha256(f"{return_id}|{index}|{at}|{kind}".encode()).hexdigest()
    return f"evt_{digest[:24]}"


class Store:
    def __init__(self, path: str, *, outbox: bool = False) -> None:
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        self._lock = threading.RLock()
        # Whether a save writes its new events to the outbox (CLIVE's hook is configured).
        self.outbox = outbox

    # One writer at a time: an action reads, decides and writes under this lock.
    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def save(self, ret: Return) -> Return:
        ret.updated_at = now()
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                known = self._events_saved(ret.id) if self.outbox else 0
                self._db.execute(
                    "INSERT INTO returns (id, order_id, order_name, status, shopify_return_id, "
                    "created_at, updated_at, doc) VALUES (?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET status=excluded.status, "
                    "shopify_return_id=excluded.shopify_return_id, updated_at=excluded.updated_at, "
                    "doc=excluded.doc",
                    (
                        ret.id,
                        ret.order_id,
                        ret.order_name,
                        ret.status.value,
                        ret.shopify.return_id,
                        ret.created_at.isoformat(),
                        ret.updated_at.isoformat(),
                        ret.model_dump_json(),
                    ),
                )
                if self.outbox:
                    self._queue_new_events(ret, known)
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        return ret

    # ---------------------------------------------------------------------- the outbox

    def _events_saved(self, return_id: str) -> int:
        """How many timeline events the stored copy already has: the ones after are new."""
        row = self._db.execute("SELECT doc FROM returns WHERE id=?", (return_id,)).fetchone()
        if not row:
            return 0
        try:
            return len(json.loads(row[0]).get("timeline") or [])
        except (ValueError, AttributeError):
            return 0

    def _queue_new_events(self, ret: Return, known: int) -> None:
        """One outbox row per new event, inside the save's transaction. A row that cannot be
        written is logged and the return is saved regardless (a savepoint undoes only the rows)."""
        new = list(enumerate(ret.timeline))[known:]
        if not new:
            return
        queued = now().isoformat(timespec="microseconds")
        self._db.execute("SAVEPOINT outbox")
        try:
            for index, event in new:
                at = event.at.isoformat()
                self._db.execute(
                    "INSERT OR IGNORE INTO outbox (id, return_id, type, at, queued_at, next_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        event_id(ret.id, index, at, event.type),
                        ret.id,
                        event.type,
                        at,
                        queued,
                        queued,
                    ),
                )
            self._db.execute("RELEASE outbox")
        except sqlite3.Error:
            self._db.execute("ROLLBACK TO outbox")
            self._db.execute("RELEASE outbox")
            log.exception("outbox: %d event(s) of %s were not queued for CLIVE", len(new), ret.id)

    def outbox_due(self, at: str, limit: int) -> list[dict]:
        """The waiting rows whose time has come, oldest first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, return_id, type, at, queued_at, attempts FROM outbox "
                "WHERE state='waiting' AND next_at <= ? ORDER BY queued_at, id LIMIT ?",
                (at, limit),
            ).fetchall()
        keys = ("id", "return_id", "type", "at", "queued_at", "attempts")
        return [dict(zip(keys, r, strict=True)) for r in rows]

    def outbox_retry(
        self, row_id: str, attempts: int, next_at: str, answer: str, tried_at: str
    ) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE outbox SET attempts=?, next_at=?, tried_at=?, last_answer=? "
                "WHERE id=? AND state='waiting'",
                (attempts, next_at, tried_at, answer, row_id),
            )

    def outbox_done(
        self, row_id: str, state: str, answer: str, tried_at: str, attempts: int | None = None
    ) -> None:
        """Delivered, or given up: never sent again."""
        with self._lock:
            self._db.execute(
                "UPDATE outbox SET state=?, last_answer=?, attempts=COALESCE(?, attempts + 1), "
                "tried_at=? WHERE id=?",
                (state, answer, attempts, tried_at, row_id),
            )

    def outbox_prune(self, before: str) -> None:
        """Forget delivered and given-up rows older than `before`; waiting ones are kept."""
        with self._lock:
            self._db.execute(
                "DELETE FROM outbox WHERE state != 'waiting' AND tried_at < ?", (before,)
            )

    def outbox_counts(self) -> dict[str, int]:
        rows = self._db.execute("SELECT state, COUNT(*) FROM outbox GROUP BY state").fetchall()
        return {state: count for state, count in rows}

    def outbox_last(self) -> dict | None:
        """The most recent try, for returns-ctl doorbell."""
        row = self._db.execute(
            "SELECT type, state, attempts, last_answer, tried_at FROM outbox "
            "WHERE tried_at IS NOT NULL ORDER BY tried_at DESC LIMIT 1"
        ).fetchone()
        keys = ("type", "state", "attempts", "last_answer", "at")
        return dict(zip(keys, row, strict=True)) if row else None

    # Settings staff change from the admin screen; these win over the .env value once set.
    def get_option(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM options WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_option(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO options (key, value, at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, at=excluded.at",
                (key, value, now().isoformat()),
            )

    def get(self, return_id: str) -> Return | None:
        row = self._db.execute("SELECT doc FROM returns WHERE id=?", (return_id,)).fetchone()
        return Return.model_validate_json(row[0]) if row else None

    def by_shopify_id(self, shopify_return_id: str) -> Return | None:
        row = self._db.execute(
            "SELECT doc FROM returns WHERE shopify_return_id=?", (shopify_return_id,)
        ).fetchone()
        return Return.model_validate_json(row[0]) if row else None

    def for_order(self, order_id: str) -> list[Return]:
        rows = self._db.execute(
            "SELECT doc FROM returns WHERE order_id=? ORDER BY created_at", (order_id,)
        ).fetchall()
        return [Return.model_validate_json(r[0]) for r in rows]

    def for_order_name(self, order_name: str) -> list[Return]:
        rows = self._db.execute(
            "SELECT doc FROM returns WHERE order_name=? ORDER BY created_at", (order_name,)
        ).fetchall()
        return [Return.model_validate_json(r[0]) for r in rows]

    def search(
        self,
        status: list[str] | None = None,
        since: datetime | None = None,
        open_only: bool = False,
        limit: int = 100,
    ) -> list[Return]:
        sql, args = "SELECT doc FROM returns WHERE 1=1", []
        if open_only:
            status = [s.value for s in OPEN_STATUSES]
        if status:
            sql += f" AND status IN ({','.join('?' * len(status))})"
            args += status
        if since:
            # Stored as UTC ISO text, so the bound is compared in UTC too.
            at = since if since.tzinfo else since.replace(tzinfo=UTC)
            sql += " AND updated_at >= ?"
            args.append(at.astimezone(UTC).isoformat())
        sql += " ORDER BY updated_at DESC LIMIT ?"
        args.append(limit)
        return [Return.model_validate_json(r[0]) for r in self._db.execute(sql, args).fetchall()]

    def open_reserved_qty(self, fulfillment_line_item_id: str) -> int:
        """Quantity of a line already in a return that is still in flight, so a customer cannot
        request the same item twice before Shopify knows about the first request."""
        total = 0
        for ret in self.search(open_only=True, limit=10_000):
            if ret.shopify.return_id:
                continue  # Shopify's returnable quantity already accounts for it.
            for line in ret.lines:
                if line.fulfillment_line_item_id == fulfillment_line_item_id:
                    total += line.quantity
        return total

    # ---------------------------------------------------------------------- idempotency

    def remembered(self, key: str) -> dict | None:
        row = self._db.execute("SELECT response FROM idempotency WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def remember(self, key: str, response: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO idempotency (key, at, response) VALUES (?,?,?)",
                (key, now().isoformat(), json.dumps(response, default=str)),
            )

    # ---------------------------------------------------------------------------- files

    def put_file(self, return_id: str, content_type: str, body: bytes) -> str:
        file_id = new_id("file")
        with self._lock:
            self._db.execute(
                "INSERT INTO files (id, return_id, content_type, at, body) VALUES (?,?,?,?,?)",
                (file_id, return_id, content_type, now().isoformat(), body),
            )
        return file_id

    def get_file(self, file_id: str) -> tuple[str, bytes] | None:
        row = self._db.execute(
            "SELECT content_type, body FROM files WHERE id=?", (file_id,)
        ).fetchone()
        return (row[0], bytes(row[1])) if row else None


def is_open(ret: Return) -> bool:
    return ret.status in OPEN_STATUSES


__all__ = ["Store", "event_id", "new_id", "now", "is_open", "Status"]
