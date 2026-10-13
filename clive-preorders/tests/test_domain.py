"""The rules on their own: state per variant, capacity, readiness, classification."""

from datetime import UTC, date, datetime

from preorders import domain
from preorders.domain import Classification, CommerceState, LineState, Mode

D = domain.derive_state


def test_state_follows_shelf_then_preorder_then_notify():
    assert D(available=20, offer_active=False, allocation=0, sold=0) == CommerceState.IN_STOCK
    assert D(available=0, offer_active=True, allocation=90, sold=31) == CommerceState.PREORDER
    assert D(available=0, offer_active=True, allocation=90, sold=90) == CommerceState.NOTIFY_ME
    assert D(available=0, offer_active=False, allocation=0, sold=0) == CommerceState.NOTIFY_ME
    # Preorders committed against Shopify's figure push it below zero: still nothing on the shelf.
    assert D(available=-31, offer_active=True, allocation=90, sold=31) == CommerceState.PREORDER
    # Stock arrives: it sells normally.
    assert D(available=34, offer_active=True, allocation=90, sold=31) == CommerceState.IN_STOCK


def test_modes_and_override():
    assert (
        D(available=5, offer_active=True, allocation=10, sold=0, mode=Mode.PREORDER_ONLY)
        == CommerceState.PREORDER
    )
    assert (
        D(available=0, offer_active=True, allocation=10, sold=0, mode=Mode.NOTIFY_ONLY)
        == CommerceState.NOTIFY_ME
    )
    assert (
        D(available=5, offer_active=False, allocation=0, sold=0, override=CommerceState.NOTIFY_ME)
        == CommerceState.NOTIFY_ME
    )


def test_capacity_never_negative_and_oversell_is_visible():
    assert domain.remaining(90, 31) == 59
    assert domain.remaining(90, 92) == 0
    assert domain.oversold(90, 92) == 2


def test_received_stock_covers_oldest_preorders_first():
    t = lambda d: datetime(2026, 10, d, tzinfo=UTC)  # noqa: E731
    lines = [
        domain.OpenLine("b", t(3), 2),
        domain.OpenLine("a", t(1), 3),
        domain.OpenLine("c", t(5), 4),
    ]
    assert domain.ready_units(lines, 6) == {"a": 3, "b": 2, "c": 1}
    assert domain.ready_units(lines, 0) == {"a": 0, "b": 0, "c": 0}


def test_line_states_and_classification():
    assert domain.line_state(cancelled=False, units_open=2, fulfilled=0, ready=2) == LineState.READY
    assert (
        domain.line_state(cancelled=False, units_open=2, fulfilled=0, ready=1)
        == LineState.AWAITING_STOCK
    )
    assert (
        domain.line_state(cancelled=False, units_open=0, fulfilled=2, ready=0)
        == LineState.FULFILLED
    )
    assert (
        domain.line_state(cancelled=True, units_open=2, fulfilled=0, ready=0) == LineState.CANCELLED
    )
    assert domain.classify(None) == Classification.IN_STOCK
    assert domain.classify(LineState.AWAITING_STOCK) == Classification.PREORDER_WAITING
    assert domain.classify(LineState.READY) == Classification.PREORDER_READY
    assert domain.classify(LineState.CANCELLED) == Classification.CANCELLED


def test_customer_words():
    assert domain.dispatch_words(date(2026, 11, 7)) == "Expected to dispatch by 7 November"
    assert domain.plan_name(date(2026, 11, 7)) == "Pre-order: expected to dispatch by 7 November"
    assert domain.discount_ok("PERCENTAGE", 10) and domain.discount_ok("NONE", 0)
    assert not domain.discount_ok("PERCENTAGE", 0) and not domain.discount_ok("FIXED", 5)


def test_a_version_1_database_upgrades_in_place(tmp_path):
    import sqlite3

    from preorders.store import MIGRATIONS, Store

    path = str(tmp_path / "old.sqlite3")
    db = sqlite3.connect(path)
    db.executescript(MIGRATIONS[0])
    db.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    db.execute("INSERT INTO schema_version VALUES (1)")
    db.commit()
    db.close()
    store = Store(path)
    columns = {r["name"] for r in store.all("PRAGMA table_info(preorder_lines)")}
    assert "released_at" in columns
    assert store.value("SELECT MAX(version) FROM schema_version") == len(MIGRATIONS)
    Store(path)  # opening again changes nothing
