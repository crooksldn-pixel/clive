"""The Knowledge Digester's dataset adapter: CSV, TSV, JSON arrays, JSON Lines and SQLite become
data_schema Units with types, row counts, null rates and distinct counts; personal columns are
marked and their values never appear; SQLite is opened read-only and nothing is written back;
the same input gives the same Units; every size is bounded; and malformed input gives an
'unparsed' Unit rather than an exception."""

from __future__ import annotations

import json
import sqlite3
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


def test_a_missing_artifact_is_unparsed_not_raised(tmp_path):
    [unit] = data.decompose(tmp_path / "missing", ARTIFACT)
    assert unit.tags == ("unparsed",) and unit.location.path == "."
