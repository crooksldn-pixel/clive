"""The Knowledge Digester's dataset adapter: CSV, TSV, JSON arrays, JSON Lines and SQLite become
data_schema Units with types, row counts, null rates and distinct counts; personal columns are
marked and their values never appear; SQLite is opened read-only and nothing is written back;
the same input gives the same Units; every size is bounded; and malformed input gives an
'unparsed' Unit rather than an exception."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

from app.digest import Source, Unit, content_digest
from app.digest.adapters import data
from app.digest.model import MAX_BODY

ARTIFACT = Source(
    origin="/quarantine/datasets", origin_kind="directory",
    pinned_ref=content_digest(b"datasets"), licence=None,
    taken_at="2026-09-26T10:00:00+00:00", content_digest=content_digest(b"datasets"),
).artifact_id

PEOPLE = (
    "id,name,email,phone,postcode,signup,active,score,notes\n"
    "1,Ada Lovelace,ada@example.com,+44 20 7946 0958,SW1A 1AA,2026-01-05,true,4.5,first\n"
    "2,Grace Hopper,grace@example.org,020 7946 0000,EC1A 1BB,2026-02-10,false,3,second\n"
    "3,Alan Turing,alan@example.net,(020) 7946 0001,M1 1AE,,yes,2.25,\n"
)
ITEMS = (
    "sku\tseen_at\tqty\tcontact\n"
    "A-1\t2026-09-26T10:00:00+00:00\t5\tbuyer.one@example.com\n"
    "B-2\t2026-09-26 11:30\t\tbuyer.two@example.com\n"
    "C-3\t2026-09-27T09:15:00Z\t7\tsupport\n"
)
ORDERS = [
    {"order": 1, "total": 9.5, "paid": True, "customer_email": "ada@example.com",
     "placed": "2026-09-01", "lines": ["a", "b"]},
    {"order": 2, "total": 12, "paid": False, "customer_email": None, "placed": "2026-09-02"},
    {"order": 3, "total": None, "paid": True, "customer_email": "alan@example.net",
     "placed": "2026-09-03", "note": "gift wrap"},
]
EVENTS = (
    '{"event": "view", "at": "2026-09-26T10:00:00Z", "user_phone": "+44 7700 900123"}\n'
    '{"event": "buy", "at": "2026-09-26T10:05:00Z", "user_phone": "+44 7700 900456", "amount": 20}\n'
    '{"event": "view", "at": "2026-09-26T11:00:00Z"}\n'
)
SHOP = """
CREATE TABLE customers (id INTEGER PRIMARY KEY, full_name TEXT, email TEXT, city TEXT);
INSERT INTO customers VALUES (1, 'Ada Lovelace', 'ada@example.com', 'London'),
                             (2, 'Grace Hopper', 'grace@example.org', 'Arlington'),
                             (3, 'Alan Turing', NULL, 'Wilmslow');
CREATE TABLE products (sku TEXT, price REAL, stocked INTEGER, added TEXT);
INSERT INTO products VALUES ('W-1', 4.5, 1, '2026-09-01'),
                            ('W-2', 12.0, 0, '2026-09-02 10:00:00'),
                            ('W-3', 7.25, 1, NULL);
CREATE VIEW cheap AS SELECT sku FROM products WHERE price < 5;
"""
PERSONAL_VALUES = (
    "Ada Lovelace", "Grace Hopper", "Alan Turing", "ada@example.com", "grace@example.org",
    "alan@example.net", "+44 20 7946 0958", "020 7946 0000", "(020) 7946 0001", "SW1A 1AA",
    "EC1A 1BB", "M1 1AE", "buyer.one@example.com", "buyer.two@example.com", "+44 7700 900123",
    "+44 7700 900456",
)


def _database(path: Path, script: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(script)
        connection.commit()
    finally:
        connection.close()


def _datasets(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "people.csv").write_text(PEOPLE, encoding="utf-8")
    (root / "items.tsv").write_text(ITEMS, encoding="utf-8")
    (root / "orders.json").write_text(json.dumps(ORDERS, indent=2), encoding="utf-8")
    (root / "events.jsonl").write_text(EVENTS, encoding="utf-8")
    (root / "README.md").write_text("# Not a dataset\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "ignored.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    _database(root / "shop.sqlite", SHOP)
    return root


def _by_title(units: list[Unit]) -> dict[str, Unit]:
    titles = [unit.title for unit in units]
    assert len(set(titles)) == len(titles)
    return {unit.title: unit for unit in units}


def _line(unit: Unit, column: str) -> str:
    [line] = [line for line in unit.body.splitlines() if line.startswith(f"- {column}:")]
    return line


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*")) if path.is_file()
    }


# --- the contract ------------------------------------------------------------------------------


def test_the_adapter_follows_the_shared_contract():
    assert isinstance(data.NAME, str) and data.NAME
    assert isinstance(data.HANDLES, tuple) and "dataset" in data.HANDLES
    assert callable(data.decompose)
    assert not (Path(data.__file__).parent / "__init__.py").exists()   # a namespace package


def test_every_dataset_becomes_units_in_path_order(tmp_path):
    units = data.decompose(_datasets(tmp_path / "art"), ARTIFACT)
    assert [unit.title for unit in units] == [
        "Data schema: events.jsonl",
        "Data schema: items.tsv",
        "Data schema: orders.json",
        "Data schema: people.csv",
        "Data schema: shop.sqlite table customers",
        "Data schema: shop.sqlite table products",
        "Not parsed: shop.sqlite",
    ]
    assert all(unit.artifact_id == ARTIFACT for unit in units)
    assert all(unit.kind == "data_schema" for unit in units[:-1])
    for unit in units:
        assert Unit.from_dict(json.loads(json.dumps(unit.to_dict()))) == unit


# --- each format -------------------------------------------------------------------------------


def test_csv_gives_columns_types_counts_and_null_rates(tmp_path):
    unit = _by_title(data.decompose(_datasets(tmp_path), ARTIFACT))["Data schema: people.csv"]
    assert unit.location.to_dict() == {"path": "people.csv", "line_start": 1, "line_end": 4}
    assert unit.tags == ("dataset", "csv", "personal")
    assert 'Format: CSV, delimiter ",", the first row names the columns.' in unit.body
    assert "Rows: 3" in unit.body.splitlines()
    assert "Columns: 9" in unit.body.splitlines()
    assert _line(unit, "id") == '- id: integer; nulls 0.0%; distinct ~3; examples "1", "2", "3"'
    assert _line(unit, "signup") == (
        '- signup: date; nulls 33.3%; distinct ~2; examples "2026-01-05", "2026-02-10"'
    )
    assert _line(unit, "active").startswith("- active: boolean; nulls 0.0%")
    assert _line(unit, "score").startswith("- score: number; nulls 0.0%; distinct ~3")
    assert _line(unit, "notes") == '- notes: text; nulls 33.3%; distinct ~2; examples "first", "second"'
    for column in ("name", "email", "phone", "postcode"):
        assert "personal, values withheld" in _line(unit, column)
        assert "examples" not in _line(unit, column)


def test_tsv_is_sniffed_and_datetimes_are_found(tmp_path):
    unit = _by_title(data.decompose(_datasets(tmp_path), ARTIFACT))["Data schema: items.tsv"]
    assert unit.location.to_dict() == {"path": "items.tsv", "line_start": 1, "line_end": 4}
    assert 'Format: TSV, delimiter "\\t"' in unit.body
    assert _line(unit, "sku") == '- sku: text; nulls 0.0%; distinct ~3; examples "A-1", "B-2", "C-3"'
    assert _line(unit, "seen_at").startswith("- seen_at: datetime; nulls 0.0%; distinct ~3")
    assert _line(unit, "qty").startswith("- qty: integer; nulls 33.3%; distinct ~2")
    # named "contact", but most of its values are email addresses
    assert _line(unit, "contact") == "- contact: text; personal, values withheld; nulls 0.0%; distinct ~3"
    assert "personal" in unit.tags


def test_a_json_array_of_records(tmp_path):
    root = _datasets(tmp_path)
    unit = _by_title(data.decompose(root, ARTIFACT))["Data schema: orders.json"]
    lines = (root / "orders.json").read_text().splitlines()
    assert unit.location.to_dict() == {"path": "orders.json", "line_start": 1, "line_end": len(lines)}
    assert unit.tags == ("dataset", "json", "personal")
    assert "Rows: 3" in unit.body.splitlines()
    assert "Columns: 7" in unit.body.splitlines()
    assert _line(unit, "order").startswith("- order: integer; nulls 0.0%")
    assert _line(unit, "total").startswith("- total: number; nulls 33.3%; distinct ~2")
    assert _line(unit, "paid").startswith("- paid: boolean; nulls 0.0%; distinct ~2")
    assert _line(unit, "placed").startswith("- placed: date; nulls 0.0%")
    assert _line(unit, "note").startswith("- note: text; nulls 66.7%")
    assert _line(unit, "customer_email") == (
        "- customer_email: text; personal, values withheld; nulls 33.3%; distinct ~2"
    )


def test_json_lines(tmp_path):
    unit = _by_title(data.decompose(_datasets(tmp_path), ARTIFACT))["Data schema: events.jsonl"]
    assert unit.location.to_dict() == {"path": "events.jsonl", "line_start": 1, "line_end": 3}
    assert unit.tags == ("dataset", "jsonl", "personal")
    assert "Rows: 3" in unit.body.splitlines()
    assert _line(unit, "event") == '- event: text; nulls 0.0%; distinct ~2; examples "view", "buy"'
    assert _line(unit, "at").startswith("- at: datetime; nulls 0.0%")
    assert _line(unit, "amount").startswith("- amount: integer; nulls 66.7%")
    assert "personal, values withheld" in _line(unit, "user_phone")


def test_json_lines_that_are_not_records_are_skipped_and_said_so(tmp_path):
    (tmp_path / "log.jsonl").write_text('{"a": 1}\n\nnot json\n[1]\n{"a": 2}\n', encoding="utf-8")
    schema, note = data.decompose(tmp_path, ARTIFACT)
    assert schema.kind == "data_schema" and "Rows: 2" in schema.body.splitlines()
    assert schema.location.to_dict() == {"path": "log.jsonl", "line_start": 1, "line_end": 5}
    assert note.kind == "knowledge" and note.tags == ("unparsed",)
    assert note.location.to_dict() == {"path": "log.jsonl", "line_start": 3, "line_end": 3}
    assert "2 lines are not JSON objects" in note.body and "lines 3, 4" in note.body


def test_sqlite_tables_are_read_and_views_are_not_run(tmp_path):
    units = _by_title(data.decompose(_datasets(tmp_path), ARTIFACT))
    customers = units["Data schema: shop.sqlite table customers"]
    assert customers.location.to_dict() == {"path": "shop.sqlite", "line_start": None, "line_end": None}
    assert customers.tags == ("dataset", "sqlite", "personal")
    assert "Rows: 3" in customers.body.splitlines()
    assert _line(customers, "id") == (
        '- id: integer; declared INTEGER; nulls 0.0%; distinct ~3; examples "1", "2", "3"'
    )
    assert _line(customers, "email") == (
        "- email: text; declared TEXT; personal, values withheld; nulls 33.3%; distinct ~2"
    )
    assert "personal, values withheld" in _line(customers, "full_name")
    assert _line(customers, "city").endswith('examples "London", "Arlington", "Wilmslow"')

    products = units["Data schema: shop.sqlite table products"]
    assert products.tags == ("dataset", "sqlite")
    assert _line(products, "price").startswith("- price: number; declared REAL; nulls 0.0%")
    assert _line(products, "stocked").startswith("- stocked: integer; declared INTEGER")
    assert _line(products, "added").startswith("- added: datetime; declared TEXT; nulls 33.3%")

    note = units["Not parsed: shop.sqlite"]
    assert note.tags == ("unparsed",)
    assert "view cheap" in note.body and "would run SQL" in note.body


def test_sqlite_is_opened_read_only_and_nothing_is_written(tmp_path, monkeypatch):
    root = _datasets(tmp_path / "art")
    before = _snapshot(root)
    opened: list[tuple[tuple, dict]] = []
    real_connect = sqlite3.connect

    def spy(*args, **kwargs):
        opened.append((args, kwargs))
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy)
    data.decompose(root, ARTIFACT)
    [(args, kwargs)] = opened
    assert args[0].startswith("file:") and args[0].endswith("shop.sqlite?mode=ro&immutable=1")
    assert kwargs == {"uri": True}
    assert _snapshot(root) == before                          # no journal, no change, nothing new


def test_a_single_file_can_be_the_artifact(tmp_path):
    root = _datasets(tmp_path)
    [unit] = data.decompose(root / "people.csv", ARTIFACT)
    assert unit.title == "Data schema: people.csv" and unit.location.path == "people.csv"


def test_links_are_not_followed(tmp_path):
    (tmp_path / "outside.csv").write_text("secret,value\nx,1\n", encoding="utf-8")
    root = tmp_path / "art"
    root.mkdir()
    (root / "link.csv").symlink_to(tmp_path / "outside.csv")
    assert data.decompose(root, ARTIFACT) == []


# --- personal data -----------------------------------------------------------------------------


def test_personal_values_never_appear_in_any_unit(tmp_path):
    root = _datasets(tmp_path)
    (root / "notes.csv").write_text(
        "topic,remark\nbilling,call ada@example.com today\nshipping,ok\nreturns,fine\nstock,low\n",
        encoding="utf-8",
    )
    units = data.decompose(root, ARTIFACT)
    everything = json.dumps([unit.to_dict() for unit in units], ensure_ascii=False)
    for value in PERSONAL_VALUES:
        assert value not in everything, value
    remark = _line(_by_title(units)["Data schema: notes.csv"], "remark")
    assert "personal" not in remark                   # one email in four is not a personal column,
    assert "call ada" not in remark                   # but that value is never an example
    assert remark.endswith('examples "ok", "fine", "low"')


def test_a_header_that_looks_personal_is_not_shown(tmp_path):
    (tmp_path / "raw.csv").write_text(
        "ada@example.com,3\ngrace@example.org,4\n", encoding="utf-8"
    )
    [unit] = data.decompose(tmp_path, ARTIFACT)
    assert "no header row: columns are numbered." in unit.body
    assert "Rows: 2" in unit.body.splitlines()
    assert "personal, values withheld" in _line(unit, "column_1")
    assert "@" not in unit.body


NEUTRAL_VALUES = (
    "Ada Lovelace", "Grace Hopper", "Turing", "Hopper, Grace", "07700900123", "02079460000",
    "4155550123", "2125550188", "6175550199", "0033612345678", "02139", "10001", "94105-1234",
)


def test_names_phones_and_zip_codes_are_found_by_their_values(tmp_path):
    # neutral column names: only the values say these columns are personal
    (tmp_path / "contacts.csv").write_text(
        "ref,contact,value,code,label\n"
        "1,Ada Lovelace,07700900123,02139,alpha\n"
        "2,Grace Hopper,02079460000,10001,beta\n"
        '3,"Turing, Alan",4155550123,94105-1234,gamma\n',
        encoding="utf-8",
    )
    _database(tmp_path / "leads.sqlite", """
        CREATE TABLE leads (ref INTEGER, who TEXT, reach INTEGER, dial TEXT, area TEXT, tier TEXT);
        INSERT INTO leads VALUES (1, 'Ada Lovelace', 4155550123, '07700900123', '02139', 'gold'),
                                 (2, 'Hopper, Grace', 2125550188, '02079460000', '10001', 'silver'),
                                 (3, 'Dr Alan Turing', 6175550199, '0033612345678', '94105-1234',
                                  'bronze');
    """)
    csv_unit, table = data.decompose(tmp_path, ARTIFACT)
    everything = json.dumps(
        [[unit.title, unit.body, list(unit.tags)] for unit in (csv_unit, table)], ensure_ascii=False
    )
    for value in NEUTRAL_VALUES:
        assert value not in everything, value
    assert csv_unit.tags == ("dataset", "csv", "personal")
    for column in ("contact", "value", "code"):
        assert "personal, values withheld" in _line(csv_unit, column), column
        assert "examples" not in _line(csv_unit, column), column
    assert _line(csv_unit, "ref").endswith('examples "1", "2", "3"')
    assert _line(csv_unit, "label").endswith('examples "alpha", "beta", "gamma"')
    assert table.tags == ("dataset", "sqlite", "personal")
    for column in ("who", "reach", "dial", "area"):
        assert "personal, values withheld" in _line(table, column), column
        assert "examples" not in _line(table, column), column
    assert _line(table, "ref").endswith('examples "1", "2", "3"')
    assert _line(table, "tier").endswith('examples "gold", "silver", "bronze"')


NAMES = ("Ada Lovelace", "Grace Hopper", "Alan Turing")


@pytest.mark.parametrize(
    ("name", "content", "rows"),
    [
        ("people.csv", "Ada Lovelace,London\nGrace Hopper,Arlington\nAlan Turing,Wilmslow\n", 3),
        ("people.tsv", "Ada Lovelace\tLondon\nGrace Hopper\tArlington\nAlan Turing\tWilmslow\n", 3),
        ("one.csv", "Ada Lovelace,London\n", 1),
        ("one.tsv", "Ada Lovelace\tLondon\n", 1),
    ],
)
def test_a_headerless_first_record_of_names_is_counted_and_withheld(tmp_path, name, content, rows):
    (tmp_path / name).write_text(content, encoding="utf-8")
    [unit] = data.decompose(tmp_path, ARTIFACT)
    assert "no header row: columns are numbered." in unit.body
    assert f"Rows: {rows}" in unit.body.splitlines()
    assert unit.location.to_dict() == {"path": name, "line_start": 1, "line_end": rows}
    assert unit.tags == ("dataset", name.rsplit(".", 1)[1], "personal")
    assert "Personal data, values withheld: column_1" in unit.body.splitlines()
    assert _line(unit, "column_1") == (
        f"- column_1: text; personal, values withheld; nulls 0.0%; distinct ~{rows}"
    )
    assert "London" in _line(unit, "column_2")
    everything = json.dumps(unit.to_dict(), ensure_ascii=False)
    for person in NAMES:
        assert person not in everything, person


def test_title_case_headers_are_still_headers(tmp_path):
    (tmp_path / "customers.csv").write_text(
        "First Name,Home City,Unit Price\nAda Lovelace,London,4.5\nGrace Hopper,Arlington,3\n",
        encoding="utf-8",
    )
    [unit] = data.decompose(tmp_path, ARTIFACT)
    assert "the first row names the columns." in unit.body
    assert "Rows: 2" in unit.body.splitlines()
    assert _line(unit, "First Name") == (
        "- First Name: text; personal, values withheld; nulls 0.0%; distinct ~2"
    )
    # written like people's names, so numbered rather than shown
    assert "2 column names are written like people's names and are withheld" in unit.body
    assert _line(unit, "column_2").endswith('examples "London", "Arlington"')
    assert _line(unit, "column_3").startswith("- column_3: number; nulls 0.0%")
    for person in NAMES:
        assert person not in unit.body, person


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("mixed.csv", "Ada Lovelace,London\nunknown,Paris\nunknown,Rome\n"),
        ("mixed.tsv", "Ada Lovelace\tLondon\nunknown\tParis\nunknown\tRome\n"),
    ],
)
def test_a_headerless_first_record_with_one_name_is_counted_and_withheld(tmp_path, name, content):
    # the values below the name are not names: the first row is still a record
    (tmp_path / name).write_text(content, encoding="utf-8")
    [unit] = data.decompose(tmp_path, ARTIFACT)
    assert "no header row: columns are numbered." in unit.body
    assert "Rows: 3" in unit.body.splitlines()
    assert unit.location.to_dict() == {"path": name, "line_start": 1, "line_end": 3}
    assert _line(unit, "column_1") == '- column_1: text; nulls 0.0%; distinct ~2; examples "unknown"'
    assert _line(unit, "column_2").endswith('examples "London", "Paris", "Rome"')
    assert "Ada Lovelace" not in json.dumps(unit.to_dict(), ensure_ascii=False)


def test_people_named_in_a_header_are_not_shown(tmp_path):
    (tmp_path / "scores.csv").write_text(
        "Region,Ada Lovelace,GRACE HOPPER\nnorth,5,6\nsouth,7,8\n", encoding="utf-8"
    )
    [unit] = data.decompose(tmp_path, ARTIFACT)
    assert "the first row names the columns." in unit.body
    assert "Rows: 2" in unit.body.splitlines()
    assert _line(unit, "Region").endswith('examples "north", "south"')
    assert _line(unit, "column_2").endswith('examples "5", "7"')
    assert _line(unit, "column_3").endswith('examples "6", "8"')
    everything = json.dumps(unit.to_dict(), ensure_ascii=False)
    for person in ("Ada Lovelace", "GRACE HOPPER"):
        assert person not in everything, person


UNPUNCTUATED = (
    "ADA LOVELACE", "ALAN TURING", "MARY SOMERVILLE", "GRACE HOPPER", "447700900123",
    "4915123456789", "8613812345678", "33612345678",
)
LEADS = [
    (1, "ADA LOVELACE", 447700900123, "GRACE HOPPER", 33612345678),
    (2, "ALAN TURING", 4915123456789, "ok", 12),
    (3, "MARY SOMERVILLE", 8613812345678, "fine", 34),
]


def test_upper_case_names_and_international_numbers_are_found_by_their_values(tmp_path):
    # neutral column names: only the values say who and reach are personal; remark and code
    # hold one personal value each, never shown though the columns are not personal
    columns = ("ref", "who", "reach", "remark", "code")
    (tmp_path / "leads.csv").write_text(
        ",".join(columns) + "\n" + "".join(",".join(map(str, row)) + "\n" for row in LEADS),
        encoding="utf-8",
    )
    (tmp_path / "leads.json").write_text(
        json.dumps([dict(zip(columns, row, strict=True)) for row in LEADS]), encoding="utf-8"
    )
    connection = sqlite3.connect(tmp_path / "leads.sqlite")
    try:
        connection.execute(
            "CREATE TABLE leads (ref INTEGER, who TEXT, reach INTEGER, remark TEXT, code INTEGER)"
        )
        connection.executemany("INSERT INTO leads VALUES (?, ?, ?, ?, ?)", LEADS)
        connection.commit()
    finally:
        connection.close()
    units = data.decompose(tmp_path, ARTIFACT)
    assert [unit.title for unit in units] == [
        "Data schema: leads.csv", "Data schema: leads.json", "Data schema: leads.sqlite table leads",
    ]
    everything = json.dumps([unit.to_dict() for unit in units], ensure_ascii=False)
    for value in UNPUNCTUATED:
        assert value not in everything, value
    for unit in units:
        assert "personal" in unit.tags
        for column in ("who", "reach"):
            assert "personal, values withheld" in _line(unit, column), column
            assert "examples" not in _line(unit, column), column
        for column, examples in (("remark", '"ok", "fine"'), ("code", '"12", "34"')):
            assert "personal" not in _line(unit, column), column
            assert _line(unit, column).endswith(f"examples {examples}"), column


NESTED = [
    {"ref": 1, "details": {"full_name": "Ada Lovelace", "since": 2020}, "team": ["gold"]},
    {"ref": 2, "details": {"profile": {"display": "GRACE HOPPER"}}, "team": ["Alan Turing", "vip"]},
    {"ref": 3, "details": None, "team": ["silver"]},
]


def test_names_nested_in_json_values_are_found_and_never_shown(tmp_path):
    (tmp_path / "nested.json").write_text(json.dumps(NESTED), encoding="utf-8")
    (tmp_path / "nested.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in NESTED), encoding="utf-8"
    )
    units = data.decompose(tmp_path, ARTIFACT)
    assert [unit.title for unit in units] == [
        "Data schema: nested.json", "Data schema: nested.jsonl",
    ]
    everything = json.dumps([unit.to_dict() for unit in units], ensure_ascii=False)
    for person in ("Ada Lovelace", "GRACE HOPPER", "Alan Turing"):
        assert person not in everything, person
    for unit in units:
        assert "personal" in unit.tags
        assert _line(unit, "details") == (
            "- details: text; personal, values withheld; nulls 33.3%; distinct ~2"
        )
        # one list in three holds a name: not a personal column, but no list is ever shown
        assert _line(unit, "team") == "- team: text; nulls 0.0%; distinct ~3"
        assert _line(unit, "ref").endswith('examples "1", "2", "3"')


POSTAL_NUMBERS = ("90210", "10001", "94105", "60614", "30301")


def test_postal_codes_stored_as_numbers_are_withheld(tmp_path):
    # neutral column names: only the values say these columns are personal
    (tmp_path / "areas.json").write_text(json.dumps([
        {"ref": 1, "area": 90210, "zone": 60614.0, "label": "alpha"},
        {"ref": 2, "area": 10001, "zone": 30301.0, "label": "beta"},
        {"ref": 3, "area": 94105, "zone": None, "label": "gamma"},
    ]), encoding="utf-8")
    _database(tmp_path / "areas.sqlite", """
        CREATE TABLE areas (ref INTEGER, area INTEGER, zone REAL, label TEXT);
        INSERT INTO areas VALUES (1, 90210, 60614, 'alpha'), (2, 10001, 30301, 'beta'),
                                 (3, 94105, NULL, 'gamma');
    """)
    json_unit, table = data.decompose(tmp_path, ARTIFACT)
    assert table.title == "Data schema: areas.sqlite table areas"
    everything = json.dumps(
        [[unit.title, unit.body, list(unit.tags)] for unit in (json_unit, table)], ensure_ascii=False
    )
    for value in POSTAL_NUMBERS:
        assert value not in everything, value
    assert json_unit.tags == ("dataset", "json", "personal")
    assert table.tags == ("dataset", "sqlite", "personal")
    for unit in (json_unit, table):
        assert "Rows: 3" in unit.body.splitlines()
        for column in ("area", "zone"):
            assert "personal, values withheld" in _line(unit, column), column
            assert "examples" not in _line(unit, column), column
        assert _line(unit, "ref").endswith('examples "1", "2", "3"')
        assert _line(unit, "label").endswith('examples "alpha", "beta", "gamma"')


# --- determinism and bounds --------------------------------------------------------------------


def test_the_same_datasets_give_the_same_units(tmp_path):
    one = data.decompose(_datasets(tmp_path / "one"), ARTIFACT)
    again = data.decompose(tmp_path / "one", ARTIFACT)
    two = data.decompose(_datasets(tmp_path / "two"), ARTIFACT)
    assert [unit.to_dict() for unit in one] == [unit.to_dict() for unit in again]
    assert [unit.to_dict() for unit in one] == [unit.to_dict() for unit in two]


def test_rows_are_scanned_up_to_a_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "MAX_ROWS", 10)
    rows = "".join(f"{i},item{i}\n" for i in range(25))
    (tmp_path / "long.csv").write_text("n,label\n" + rows, encoding="utf-8")
    _database(tmp_path / "long.db", "CREATE TABLE t (n INTEGER);" + "".join(
        f"INSERT INTO t VALUES ({i});" for i in range(25)
    ))
    csv_unit, table = data.decompose(tmp_path, ARTIFACT)
    assert table.title == "Data schema: long.db table t"
    for unit in (csv_unit, table):
        assert "Rows: at least 10 (the scan stopped at its limit)" in unit.body
        assert "truncated" in unit.tags
    assert csv_unit.location.to_dict() == {"path": "long.csv", "line_start": 1, "line_end": 11}


def test_examples_are_at_most_three_and_short(tmp_path):
    long_value = "x" * 60
    (tmp_path / "palette.csv").write_text(
        f"colour\n{long_value}\nred\ngreen\nblue\ncyan\n", encoding="utf-8"
    )
    [unit] = data.decompose(tmp_path, ARTIFACT)
    assert _line(unit, "colour") == (
        '- colour: text; nulls 0.0%; distinct ~5; examples "red", "green", "blue"'
    )
    assert long_value not in unit.body


def test_wide_datasets_stay_within_the_body_limit(tmp_path):
    header = ",".join(f"c{i:03d}_" + "x" * 70 for i in range(150))
    rows = "".join(
        ",".join(f"r{r}c{i}_" + "y" * 30 for i in range(150)) + "\n" for r in range(3)
    )
    (tmp_path / "wide.csv").write_text(header + "\n" + rows, encoding="utf-8")
    [unit] = data.decompose(tmp_path, ARTIFACT)
    assert len(unit.body) <= MAX_BODY
    assert "Columns: 150 (the first 100 profiled)" in unit.body
    assert "more lines not shown" in unit.body


def test_a_dataset_profiled_only_in_part_says_so(tmp_path):
    """Personal columns past the ones profiled are not seen, so the profile says it is partial
    and nothing downstream may take it as saying the dataset holds no personal data."""
    header = ",".join(f"c{i}" for i in range(100)) + ",email,phone"
    row = ",".join(str(i) for i in range(100)) + ",ada@example.com,+44 20 7946 0958"
    (tmp_path / "wide.csv").write_text(f"{header}\n{row}\n", encoding="utf-8")
    (tmp_path / "narrow.csv").write_text("sku,qty\nA-1,5\n", encoding="utf-8")
    narrow, wide = data.decompose(tmp_path, ARTIFACT)
    assert "partial" in wide.tags and "personal" not in wide.tags
    assert "partial" not in narrow.tags


def test_text_is_read_up_to_a_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "MAX_TEXT_BYTES", 200)
    (tmp_path / "big.csv").write_text(
        "n,label\n" + "".join(f"{i},item{i}\n" for i in range(50)), encoding="utf-8"
    )
    (tmp_path / "big.json").write_text(
        json.dumps([{"n": i} for i in range(50)]), encoding="utf-8"
    )
    csv_unit, json_unit = data.decompose(tmp_path, ARTIFACT)
    assert csv_unit.kind == "data_schema" and "truncated" in csv_unit.tags
    assert "Only the first 200 bytes were read." in csv_unit.body
    assert json_unit.tags == ("unparsed",) and "read whole" in json_unit.body


def test_files_and_tables_are_counted_up_to_a_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "MAX_FILES", 2)
    monkeypatch.setattr(data, "MAX_TABLES", 1)
    _database(tmp_path / "a.sqlite", "CREATE TABLE one (x); CREATE TABLE two (y);")
    for name in ("b.csv", "c.csv"):
        (tmp_path / name).write_text("a,b\n1,2\n", encoding="utf-8")
    units = data.decompose(tmp_path, ARTIFACT)
    assert [(unit.title, unit.location.path) for unit in units] == [
        ("Data schema: a.sqlite table one", "a.sqlite"),
        ("Not parsed: a.sqlite", "a.sqlite"),
        ("Data schema: b.csv", "b.csv"),
        ("Not parsed: the artifact", "."),
    ]
    assert "1 more tables were not read" in units[1].body
    assert "1 more dataset files were not read" in units[3].body


def test_database_schemas_are_listed_up_to_a_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "MAX_SCHEMA_ENTRIES", 3)
    _database(
        tmp_path / "many.sqlite",
        "".join(f"CREATE TABLE t{i} (x);" for i in range(6)) + "CREATE VIEW v AS SELECT 1;",
    )
    units = data.decompose(tmp_path, ARTIFACT)
    assert [unit.title for unit in units] == [
        "Data schema: many.sqlite table t0",
        "Data schema: many.sqlite table t1",
        "Data schema: many.sqlite table t2",
        "Not parsed: many.sqlite",
    ]
    assert units[-1].tags == ("unparsed",)
    assert "more than 3 tables and views" in units[-1].body


def test_sqlite_values_are_fetched_only_up_to_a_size(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "MAX_CELL_CHARS", 100)
    fetched: list[int] = []
    real_add = data._Column.add

    def spy(self, value):
        if isinstance(value, (str, bytes)):
            fetched.append(len(value))
        real_add(self, value)

    monkeypatch.setattr(data._Column, "add", spy)
    connection = sqlite3.connect(tmp_path / "big.sqlite")
    try:
        connection.execute("CREATE TABLE files (label TEXT, content TEXT, payload BLOB)")
        connection.executemany("INSERT INTO files VALUES (?, ?, ?)", [
            ("small", "tiny", b"\x00\x01"),
            ("large", "z" * 100_000, b"\xff" * 100_000),
        ])
        connection.commit()
    finally:
        connection.close()
    schema, note = data.decompose(tmp_path, ARTIFACT)
    assert fetched and max(fetched) <= 101                  # never a whole oversized value
    assert schema.kind == "data_schema" and "Rows: 2" in schema.body.splitlines()
    assert "2 values were read only up to 100 characters or bytes." in schema.body
    assert _line(schema, "content") == (
        '- content: text; declared TEXT; nulls 0.0%; distinct ~2; examples "tiny"'
    )
    assert _line(schema, "payload") == "- payload: text; declared BLOB; nulls 0.0%; distinct ~2"
    assert "zzz" not in schema.body
    assert note.kind == "knowledge" and note.tags == ("unparsed",)
    assert note.location.path == "big.sqlite"
    assert "2 values longer than 100 characters or bytes" in note.body


# --- malformed input ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "content", "reason"),
    [
        ("broken.json", b'[{"a": 1,', "Not valid JSON"),
        ("object.json", b'{"a": 1}', "not an array of records"),
        ("scalars.json", b"[1, 2, 3]", "holds no objects"),
        ("deep.json", b"[" * 100_000, "JSON"),
        ("empty.csv", b"", "empty"),
        ("empty.json", b"  \n", "empty"),
        ("garbage.jsonl", b"not json\n{broken\n", "No line holds a JSON object"),
        ("fake.sqlite", b"this is not a database", "no SQLite header"),
        ("corrupt.db", data.SQLITE_MAGIC + bytes(range(256)) * 8, ""),
    ],
)
def test_malformed_input_is_unparsed_not_raised(tmp_path, name, content, reason):
    (tmp_path / name).write_bytes(content)
    units = data.decompose(tmp_path, ARTIFACT)
    assert units
    for unit in units:
        assert unit.kind == "knowledge" and unit.tags == ("unparsed",)
        assert unit.location.path == name
    assert reason in units[0].body


def test_an_unreadable_row_stops_the_scan_and_says_where(tmp_path):
    (tmp_path / "huge.csv").write_bytes(b"a,b\n1,2\n3," + b"x" * 200_000 + b"\n")
    schema, note = data.decompose(tmp_path, ARTIFACT)
    assert schema.kind == "data_schema" and "Rows: 1" in schema.body.splitlines()
    assert note.tags == ("unparsed",) and "Stopped reading at line" in note.body
    assert note.location.line_start == note.location.line_end >= 3


@pytest.mark.parametrize(
    ("name", "content", "end"),
    [
        ("open.csv", 'a,b\n1,2\n3,"never closed\n', 3),
        ("open.tsv", 'a\tb\n1\t2\n3\t"never closed\n4\t5\n', 4),
    ],
)
def test_an_unterminated_quote_is_unparsed_not_read_as_a_row(tmp_path, name, content, end):
    (tmp_path / name).write_text(content, encoding="utf-8")
    schema, note = data.decompose(tmp_path, ARTIFACT)
    assert schema.kind == "data_schema" and "Rows: 1" in schema.body.splitlines()
    assert schema.location.to_dict() == {"path": name, "line_start": 1, "line_end": 2}
    assert "never closed" not in schema.body
    assert note.kind == "knowledge" and note.tags == ("unparsed",)
    # from the line the unreadable record begins on to the last line read
    assert note.location.to_dict() == {"path": name, "line_start": 3, "line_end": end}
    assert note.body.startswith("Stopped reading at line 3: ")


def test_a_missing_artifact_is_unparsed_not_raised(tmp_path):
    [unit] = data.decompose(tmp_path / "missing", ARTIFACT)
    assert unit.tags == ("unparsed",) and unit.location.path == "."


# --- repairs: names, depth, keys, run-together names, whole-artifact bounds ----------------------


def test_a_file_whose_name_is_not_utf8_is_counted_not_raised(tmp_path):
    try:
        (tmp_path / os.fsdecode(b"odd\xff.csv")).write_text("a,b\n1,2\n", encoding="utf-8")
    except (OSError, UnicodeEncodeError):
        pytest.skip("the file system refuses names that are not UTF-8")
    (tmp_path / "plain.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    units = data.decompose(tmp_path, ARTIFACT)
    for unit in units:                               # every Unit can be identified and stored
        assert Unit.from_dict(json.loads(json.dumps(unit.to_dict()))) == unit
    assert [unit.title for unit in units] == ["Data schema: plain.csv", "Not parsed: the artifact"]
    assert "1 dataset files whose names cannot be recorded were not read" in units[1].body


def test_directories_nested_past_the_recursion_limit_are_walked_not_raised(tmp_path):
    made = [str(tmp_path)]
    try:
        for _ in range(sys.getrecursionlimit() + 100):
            made.append(made[-1] + "/d")
            os.mkdir(made[-1])
        Path(made[-1], "bottom.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        [unit] = data.decompose(tmp_path, ARTIFACT)
        assert unit.kind == "data_schema" and unit.location.path.endswith("/d/bottom.csv")
    finally:
        # taken down here, bottom up: pytest's own clean-up recurses, and would not get far
        Path(made[-1], "bottom.csv").unlink(missing_ok=True)
        for directory in reversed(made[1:]):
            if os.path.isdir(directory):
                os.rmdir(directory)


def test_directories_count_towards_the_entry_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "MAX_ENTRIES", 5)
    for index in range(10):
        (tmp_path / f"empty{index}").mkdir()
    (tmp_path / "z.csv").write_text("a\n1\n", encoding="utf-8")
    [note] = data.decompose(tmp_path, ARTIFACT)
    assert note.tags == ("unparsed",) and "after 5 directory entries" in note.body


def test_record_keys_and_table_columns_written_like_names_are_withheld(tmp_path):
    records = [{"Ada Lovelace": 3, "GRACE HOPPER": 4, "region": "north"},
               {"Ada Lovelace": 5, "GRACE HOPPER": 6, "region": "south"}]
    (tmp_path / "scores.json").write_text(json.dumps(records), encoding="utf-8")
    (tmp_path / "scores.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    _database(tmp_path / "scores.sqlite", """
        CREATE TABLE scores ("Ada Lovelace" INTEGER, region TEXT);
        INSERT INTO scores VALUES (3, 'north'), (5, 'south');
    """)
    units = data.decompose(tmp_path, ARTIFACT)
    assert [unit.kind for unit in units] == ["data_schema"] * 3
    everything = json.dumps([unit.to_dict() for unit in units], ensure_ascii=False)
    for person in ("Ada Lovelace", "GRACE HOPPER"):
        assert person not in everything, person
    for unit in units:
        assert "written like people's names and are withheld" in unit.body
        assert _line(unit, "column_1").startswith("- column_1: integer")
        assert _line(unit, "region").endswith('examples "north", "south"')


def test_personal_column_names_written_run_together_are_found(tmp_path):
    (tmp_path / "crm.csv").write_text(
        "customername,phonenumber,contactemail,postalcode,dateofbirth,productname\n"
        "ada lovelace,call desk,ada at example,sw1a,1815-12-10,widget\n"
        "grace hopper,ask front,grace at example,ec1a,1906-12-09,gadget\n",
        encoding="utf-8",
    )
    [unit] = data.decompose(tmp_path, ARTIFACT)
    for column in ("customername", "phonenumber", "contactemail", "postalcode", "dateofbirth"):
        assert "personal, values withheld" in _line(unit, column), column
        assert "examples" not in _line(unit, column), column
    assert _line(unit, "productname").endswith('examples "widget", "gadget"')
    for value in ("ada lovelace", "grace hopper", "call desk", "ada at example", "sw1a", "1815"):
        assert value not in unit.body, value


def test_phone_numbers_written_with_dots_are_personal(tmp_path):
    (tmp_path / "dots.csv").write_text(
        "415.555.0123,north\n415.555.0188,south\n", encoding="utf-8"
    )
    (tmp_path / "dates.csv").write_text(
        "when,ratio\n26.09.2026,3.14159\n27.09.2026,2.5\n", encoding="utf-8"
    )
    dates, dots = data.decompose(tmp_path, ARTIFACT)
    assert "no header row: columns are numbered." in dots.body     # a number is not a header
    assert "personal, values withheld" in _line(dots, "column_1")
    assert "415.555" not in json.dumps(dots.to_dict())
    assert "personal" not in dates.tags                              # dotted dates and decimals
    assert "personal" not in _line(dates, "when")
    assert _line(dates, "ratio").endswith('examples "3.14159", "2.5"')


def _aliased_table(path: Path, aliases: int, rows: int) -> None:
    """A hostile database: one table's rows listed under many names, all at one root page."""
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE t (n INTEGER)")
        connection.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(rows)])
        connection.commit()
        [(root,)] = connection.execute("SELECT rootpage FROM sqlite_master WHERE name = 't'")
        connection.execute("PRAGMA writable_schema = ON")
        for index in range(aliases):
            connection.execute(
                "INSERT INTO sqlite_master VALUES ('table', ?, ?, ?, ?)",
                (f"t{index:02d}", f"t{index:02d}", root, f"CREATE TABLE t{index:02d} (n INTEGER)"),
            )
        connection.commit()
    finally:
        connection.close()


def test_the_scan_is_bounded_across_the_whole_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "MAX_TOTAL_CELLS", 100)
    _aliased_table(tmp_path / "a.sqlite", aliases=30, rows=60)
    (tmp_path / "b.csv").write_text("n\n1\n2\n", encoding="utf-8")
    units = data.decompose(tmp_path, ARTIFACT)
    schemas = [unit for unit in units if unit.kind == "data_schema"]
    assert [unit.title for unit in schemas] == [
        "Data schema: a.sqlite table t", "Data schema: a.sqlite table t00",
    ]
    assert "Rows: 60" in schemas[0].body.splitlines()
    assert "truncated" in schemas[1].tags and "the artifact's limit of 100 values" in schemas[1].body
    notes = [unit.body for unit in units if unit.kind == "knowledge"]
    assert any("29 more tables were not read: the artifact's scan limit" in note for note in notes)
    assert units[-1].location.path == "b.csv" and "scan limit" in units[-1].body


def test_sqlite_work_is_bounded_across_the_whole_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "MAX_TOTAL_SQLITE_STEPS", 3)
    _aliased_table(tmp_path / "a.sqlite", aliases=30, rows=5_000)
    units = data.decompose(tmp_path, ARTIFACT)
    assert len([unit for unit in units if unit.kind == "data_schema"]) <= 1
    assert any("more tables were not read" in unit.body for unit in units)


def test_sqlite_errors_never_carry_the_databases_own_text(tmp_path):
    connection = sqlite3.connect(tmp_path / "bad.sqlite")
    try:
        connection.execute("CREATE TABLE t (x)")
        connection.execute("PRAGMA writable_schema = ON")
        connection.execute(
            "UPDATE sqlite_master SET sql = ? WHERE name = 't'",
            ("CREATE TABLE t (x) 'ada@example.com'",),
        )
        connection.commit()
    finally:
        connection.close()
    [note] = data.decompose(tmp_path, ARTIFACT)
    assert note.tags == ("unparsed",) and "malformed database schema" in note.body
    assert "ada@example.com" not in note.body and "example" not in note.body
