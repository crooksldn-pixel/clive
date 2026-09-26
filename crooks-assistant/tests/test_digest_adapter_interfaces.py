"""The interfaces adapter: OpenAPI and Swagger (JSON and YAML), GraphQL SDL, JSON Schema and MCP
tool manifests read into capability and interface Units — every capability tagged read, write
or unknown — under the contract every adapter shares: it only reads, it is bounded, the same
artifact gives the same Units in the same order at the same places, and malformed input
becomes an 'unparsed' Unit rather than an exception."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

from app.digest import ARTIFACT_KINDS, Artifact, Location, Source, Unit, content_digest
from app.digest.adapters import interfaces
from app.digest.model import MAX_BODY, MAX_TITLE

SOURCE = Source(
    origin="https://example.invalid/api.git", origin_kind="git",
    pinned_ref="0123456789abcdef0123456789abcdef01234567", licence=None,
    taken_at="2026-09-26T10:00:00+00:00", content_digest=content_digest(b"interfaces"),
)
ART = SOURCE.artifact_id

OPENAPI = """\
{
  "openapi": "3.0.3",
  "info": {"title": "Pet Store", "version": "1.0.0"},
  "security": [{"api_key": []}],
  "paths": {
    "/pets": {
      "parameters": [{"name": "tenant", "in": "header", "schema": {"type": "string"}}],
      "get": {
        "operationId": "listPets",
        "summary": "List pets",
        "parameters": [
          {"name": "limit", "in": "query", "schema": {"type": "integer"}},
          {"$ref": "#/components/parameters/Page"}
        ],
        "responses": {"200": {"description": "ok"}},
        "security": [{"oauth": ["read:pets"]}]
      },
      "post": {
        "summary": "Create a pet",
        "requestBody": {"required": true, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}}},
        "responses": {"201": {"description": "created"}}
      }
    },
    "/pets/{id}": {
      "put": {"summary": "Replace a pet", "responses": {}},
      "patch": {"summary": "Update a pet", "responses": {}},
      "delete": {"summary": "Delete a pet", "security": [{"oauth": ["write:pets", "admin"]}]},
      "head": {"summary": "Check a pet"}
    }
  },
  "components": {
    "parameters": {"Page": {"name": "page", "in": "query", "required": true, "schema": {"type": "integer"}}},
    "schemas": {
      "Pet": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "name": {"type": "string"}}
      },
      "Error": {"type": "object"}
    }
  }
}
"""

SWAGGER = """\
# A Swagger 2 document in the YAML subset OpenAPI files use.
swagger: "2.0"
info:
  title: Petstore
  version: 1.0.0
securityDefinitions:
  api_key: {type: apiKey, name: api_key, in: header}
paths:
  /pets/{petId}:
    get:
      summary: Find pet by ID  # the comment is not part of it
      description: |
        Returns a single pet.
        Nothing else.
      operationId: getPetById
      parameters:
        - name: petId
          in: path
          required: true
          type: integer
      responses:
        "200":
          description: ok
      security:
        - api_key: []
        - petstore_auth: [read:pets, 'write:pets']
    delete:
      summary: Deletes a pet
      responses:
        '204': {description: gone}
definitions:
  Pet:
    type: object
    required: [id, name]
    properties:
      id: {type: integer, format: int64}
      name:
        type: string
        description: >-
          What the pet
          is called.
"""

GRAPHQL = '''\
"""A pet in the store."""
type Pet implements Node & Named @key(fields: "id") {
  id: ID!
  "What it is called"
  name: String
  tags(first: Int = 10): [String!]!
}

interface Node { id: ID! }

enum Status { AVAILABLE SOLD }

union Result = Pet | Error

input NewPet { name: String! = "Rex" }

scalar DateTime

type Query {
  "Find a pet."
  pet(id: ID!): Pet
  pets(status: Status, after: String): [Pet!]!
}

type Mutation {
  addPet(input: NewPet!): Pet
  deletePet(id: ID!): Boolean
}

type Subscription { petAdded: Pet }

directive @key(fields: String!) repeatable on OBJECT | INTERFACE
'''

ORDER = """\
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.invalid/order.schema.json",
  "title": "Order",
  "description": "An order and its lines.",
  "type": "object",
  "properties": {"id": {"type": "string"}, "lines": {"type": "array", "items": {"$ref": "#/$defs/Line"}}},
  "$defs": {
    "Line": {"type": "object", "properties": {"sku": {"type": "string"}}}
  }
}
"""

SERVER = json.dumps({
    "$schema": "https://static.modelcontextprotocol.io/schemas/2025-07-09/server.schema.json",
    "name": "io.example/orders",
    "description": "Orders over MCP",
    "version": "1.0.0",
    "packages": [{"registryType": "npm", "identifier": "@example/orders", "version": "1.0.0"}],
    "tools": [
        {"name": "list_orders", "description": "List orders",
         "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
         "annotations": {"readOnlyHint": True}},
        {"name": "refund_order", "description": "Refund an order",
         "inputSchema": {"type": "object", "required": ["id"],
                         "properties": {"id": {"type": "string"}}},
         "annotations": {"readOnlyHint": False, "destructiveHint": True}},
        {"name": "mystery", "description": "Does something", "inputSchema": {"type": "object"}},
    ],
}, indent=2)

TOOLS = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"tools": [
    {"name": "get_weather", "description": "Weather for a city",
     "inputSchema": {"type": "object", "properties": {"city": {"type": "string"}}},
     "annotations": {"readOnlyHint": True, "destructiveHint": False}},
    {"name": "add_note", "inputSchema": {"type": "object"},
     "annotations": {"destructiveHint": False}},
    {"name": "ping", "inputSchema": {"type": "object"}},
]}}, indent=2)

LIST = json.dumps([
    {"name": "echo", "description": "Echo", "inputSchema": {"type": "object"},
     "annotations": {"title": "Echo"}},
    "not a tool",
], indent=2)

FIXTURE = {
    "api/openapi.json": OPENAPI,
    "specs/petstore.yaml": SWAGGER,
    "graphql/schema.graphql": GRAPHQL,
    "schemas/order.schema.json": ORDER,
    "mcp/server.json": SERVER,
    "mcp/tools.json": TOOLS,
    # Not specifications: read past, not reported.
    "tsconfig.json": json.dumps({"$schema": "https://json.schemastore.org/tsconfig",
                                 "compilerOptions": {"strict": True}}),
    "docker-compose.yml": "services:\n  web:\n    image: example\n",
    "README.md": "# Not read\n",
}


def _write(root: Path, files: dict[str, str | bytes], *, reverse: bool = False) -> Path:
    for name in sorted(files, reverse=reverse):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        content = files[name]
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return root


def _units(root: Path) -> list[Unit]:
    return interfaces.decompose(root, ART)


def _line(text: str, needle: str) -> int:
    found = [number for number, line in enumerate(text.splitlines(), 1) if needle in line]
    assert len(found) == 1, (needle, found)
    return found[0]


def _access(unit: Unit) -> str:
    found = [tag for tag in unit.tags if tag in interfaces.ACCESS]
    assert len(found) == 1, unit
    return found[0]


def _titled(units: list[Unit], title: str) -> Unit:
    found = [unit for unit in units if unit.title == title]
    assert len(found) == 1, (title, [unit.title for unit in units])
    return found[0]


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    found = {}
    for directory, _, filenames in os.walk(root):
        for name in filenames:
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file():
                continue
            found[path.relative_to(root).as_posix()] = (path.read_bytes(), path.stat().st_mtime_ns)
    return found


# --- the shared contract -----------------------------------------------------------------------


def test_the_adapter_has_the_shared_shape():
    assert interfaces.NAME == "interfaces"
    assert interfaces.HANDLES and set(interfaces.HANDLES) <= set(ARTIFACT_KINDS)
    assert callable(interfaces.decompose)
    # A namespace package: sibling adapters add their own modules beside this one.
    assert not (Path(interfaces.__file__).parent / "__init__.py").exists()


def test_the_adapter_imports_nothing_that_could_run_what_it_reads():
    tree = ast.parse(Path(interfaces.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {
        "__future__", "app", "bisect", "dataclasses", "inspect", "json", "os", "pathlib", "re",
        "stat", "typing",
    }
    called = {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not called & {"eval", "exec", "compile", "__import__", "open"}


def test_units_belong_to_the_artifact_and_round_trip(tmp_path):
    units = _units(_write(tmp_path, FIXTURE))
    artifact = Artifact(source=SOURCE, kinds=interfaces.HANDLES, units=tuple(units))
    assert Artifact.from_dict(json.loads(json.dumps(artifact.to_dict()))) == artifact


# --- OpenAPI and Swagger -----------------------------------------------------------------------


def test_openapi_operations_become_capabilities_and_schemas_interfaces(tmp_path):
    units = _units(_write(tmp_path, {"api/openapi.json": OPENAPI}))
    capabilities = [unit for unit in units if unit.kind == "capability"]
    assert [unit.title for unit in capabilities] == [
        "GET /pets", "POST /pets", "PUT /pets/{id}", "PATCH /pets/{id}", "DELETE /pets/{id}",
        "HEAD /pets/{id}",
    ]
    assert [_access(unit) for unit in capabilities] == [
        "read", "write", "write", "write", "write", "read",
    ]
    get, post, put, _, delete, _ = capabilities
    assert get.location == Location(
        "api/openapi.json", _line(OPENAPI, '"get"'), _line(OPENAPI, '"post"') - 1
    )
    for fragment in (
        "GET /pets", "API: Pet Store 1.0.0", "Operation: listPets", "Summary: List pets",
        "- tenant (header, string)", "- limit (query, integer)",
        "- page (query, integer, required)", "Responses: 200", "Security: oauth [read:pets]",
    ):
        assert fragment in get.body, fragment
    assert "Request body (required):\n- application/json: Pet" in post.body
    assert "Security: api_key" in put.body            # the document's, where it says none
    assert "Security: oauth [write:pets, admin]" in delete.body
    assert put.location == Location("api/openapi.json", _line(OPENAPI, '"put"'),
                                    _line(OPENAPI, '"put"'))

    schemas = [unit for unit in units if unit.kind == "interface"]
    assert [unit.title for unit in schemas] == ["schema Pet", "schema Error"]
    assert schemas[0].location == Location(
        "api/openapi.json", _line(OPENAPI, '"Pet": {'), _line(OPENAPI, '"Error"') - 1
    )
    assert '"name"' in schemas[0].body
    assert all("openapi" in unit.tags for unit in units)
    assert len(units) == len(capabilities) + len(schemas)


def test_swagger_yaml_is_read_through_the_safe_subset(tmp_path):
    units = _units(_write(tmp_path, {"specs/petstore.yaml": SWAGGER}))
    get = _titled(units, "GET /pets/{petId}")
    delete = _titled(units, "DELETE /pets/{petId}")
    assert (get.kind, _access(get)) == ("capability", "read")
    assert (delete.kind, _access(delete)) == ("capability", "write")
    assert "Summary: Find pet by ID\n" in get.body and "comment" not in get.body
    assert "Description: Returns a single pet.\nNothing else." in get.body
    assert "- petId (path, integer, required)" in get.body
    assert "Security: api_key or petstore_auth [read:pets, write:pets]" in get.body
    assert "API: Petstore 1.0.0" in get.body
    assert get.location == Location(
        "specs/petstore.yaml", _line(SWAGGER, "    get:"), _line(SWAGGER, "    delete:") - 1
    )
    assert delete.location == Location(
        "specs/petstore.yaml", _line(SWAGGER, "    delete:"), _line(SWAGGER, "definitions:") - 1
    )
    pet = _titled(units, "schema Pet")
    assert pet.kind == "interface"
    assert pet.location == Location(
        "specs/petstore.yaml", _line(SWAGGER, "  Pet:"), len(SWAGGER.splitlines())
    )
    assert '"int64"' in pet.body and '"What the pet is called."' in pet.body
    assert len(units) == 3


def test_the_yaml_reader_reads_the_subset_openapi_files_use():
    text = (
        "openapi: 3.0.0\n"
        "info:\n"
        "  title: 'It''s here'   # a comment\n"
        '  version: "1.0"\n'
        "tags:\n"
        "- name: a\n"
        '  x-list: [1, 2.5, true, null, "q"]\n'
        "- b\n"
        "empty:\n"
        "literal: |+\n"
        "  one\n"
        "   two\n"
        "\n"
        "folded: >\n"
        "  a\n"
        "  b\n"
        "url: http://example.invalid/#frag\n"
    )
    assert interfaces._Yaml(text).parse() == {
        "openapi": "3.0.0",
        "info": {"title": "It's here", "version": "1.0"},
        "tags": [{"name": "a", "x-list": [1, 2.5, True, None, "q"]}, "b"],
        "empty": None,
        "literal": "one\n two\n\n",
        "folded": "a b\n",
        "url": "http://example.invalid/#frag",
    }


# --- GraphQL -----------------------------------------------------------------------------------


def test_graphql_types_are_interfaces_queries_read_and_mutations_write(tmp_path):
    units = _units(_write(tmp_path, {"graphql/schema.graphql": GRAPHQL}))
    types = [unit for unit in units if unit.kind == "interface"]
    assert [unit.title for unit in types] == [
        "type Pet implements Node & Named", "interface Node", "enum Status", "union Result",
        "input NewPet", "scalar DateTime",
    ]
    pet = types[0]
    assert pet.location == Location("graphql/schema.graphql", 1, 7)
    assert "A pet in the store." in pet.body
    assert "- name: String — What it is called" in pet.body
    assert "- tags(first: Int = 10): [String!]!" in pet.body
    assert "Values: AVAILABLE, SOLD" in types[2].body
    assert "Members: Pet | Error" in types[3].body
    assert '- name: String! = "Rex"' in types[4].body

    capabilities = [unit for unit in units if unit.kind == "capability"]
    assert [(unit.title, _access(unit)) for unit in capabilities] == [
        ("query pet", "read"), ("query pets", "read"), ("mutation addPet", "write"),
        ("mutation deletePet", "write"), ("subscription petAdded", "read"),
    ]
    query = capabilities[0]
    assert "query pet(id: ID!): Pet" in query.body and "Find a pet." in query.body
    assert query.location == Location(
        "graphql/schema.graphql", _line(GRAPHQL, '"Find a pet."'), _line(GRAPHQL, "  pet(id")
    )
    assert "- input: NewPet!" in capabilities[2].body
    assert all("graphql" in unit.tags for unit in units)


def test_graphql_root_types_come_from_the_schema_definition_in_any_file(tmp_path):
    units = _units(_write(tmp_path, {
        "graphql/a_schema.graphql": "schema { query: Root mutation: Change }\n",
        "graphql/b_types.graphql": (
            "type Root { ping: String }\n"
            "type Change { reset(all: Boolean): Boolean }\n"
            "type Mutation { notRoot: Int }\n"
            "extend type Change { wipe: Boolean }\n"
        ),
    }))
    assert [(unit.kind, unit.title) for unit in units] == [
        ("capability", "query ping"), ("capability", "mutation reset"),
        ("interface", "type Mutation"), ("capability", "mutation wipe"),
    ]
    assert [_access(unit) for unit in units if unit.kind == "capability"] == [
        "read", "write", "write",
    ]


# --- JSON Schema and MCP -----------------------------------------------------------------------


def test_json_schema_files_become_interfaces(tmp_path):
    units = _units(_write(tmp_path, {
        "schemas/order.schema.json": ORDER, "tsconfig.json": FIXTURE["tsconfig.json"],
    }))
    assert [(unit.kind, unit.title) for unit in units] == [
        ("interface", "JSON Schema Order"), ("interface", "JSON Schema Order: Line"),
    ]
    order, line = units
    assert order.location == Location("schemas/order.schema.json", 1, len(ORDER.splitlines()))
    assert "An order and its lines." in order.body and '"$defs"' in order.body
    line_number = _line(ORDER, '"Line": {')
    assert line.location == Location("schemas/order.schema.json", line_number, line_number)
    assert '"sku"' in line.body
    assert all(unit.tags == ("json_schema",) for unit in units)


def test_mcp_tools_are_tagged_from_their_own_annotations(tmp_path):
    units = _units(_write(tmp_path, {
        "mcp/server.json": SERVER, "mcp/tools.json": TOOLS, "mcp/list.json": LIST,
    }))
    capabilities = [unit for unit in units if unit.kind == "capability"]
    assert [(unit.location.path, unit.title, _access(unit)) for unit in capabilities] == [
        ("mcp/list.json", "MCP tool echo", "unknown"),
        ("mcp/server.json", "MCP server io.example/orders", "unknown"),
        ("mcp/server.json", "MCP tool list_orders", "read"),
        ("mcp/server.json", "MCP tool refund_order", "write"),
        ("mcp/server.json", "MCP tool mystery", "unknown"),
        ("mcp/tools.json", "MCP tool get_weather", "read"),
        ("mcp/tools.json", "MCP tool add_note", "write"),
        ("mcp/tools.json", "MCP tool ping", "unknown"),
    ]
    server = _titled(units, "MCP server io.example/orders")
    assert server.location == Location("mcp/server.json", 1, len(SERVER.splitlines()))
    assert "@example/orders" in server.body and "Tools listed: 3" in server.body

    listing = _titled(units, "MCP tool list_orders")
    assert '"limit"' in listing.body                              # its input schema
    assert "Access: read (from the tool's own annotations)" in listing.body
    assert listing.location == Location(
        "mcp/server.json", _line(SERVER, '"name": "list_orders"') - 1,
        _line(SERVER, '"name": "refund_order"') - 2,
    )
    refund = _titled(units, "MCP tool refund_order")
    assert "destructive" in refund.tags and '"required"' in refund.body
    assert "Access: unknown (the tool does not say)" in _titled(units, "MCP tool mystery").body
    assert "Title: Echo" in _titled(units, "MCP tool echo").body

    unparsed = [unit for unit in units if "unparsed" in unit.tags]
    assert len(unparsed) == 1
    assert unparsed[0].location.path == "mcp/list.json"
    assert "tool 2 is not an object with a name" in unparsed[0].body


def test_every_capability_is_tagged_read_write_or_unknown(tmp_path):
    units = _units(_write(tmp_path, FIXTURE))
    capabilities = [unit for unit in units if unit.kind == "capability"]
    assert {_access(unit) for unit in capabilities} == {"read", "write", "unknown"}
    for unit in units:
        if unit.kind != "capability":
            assert not set(unit.tags) & set(interfaces.ACCESS), unit
    tags = {tag for unit in units for tag in unit.tags}
    assert {"openapi", "graphql", "json_schema", "mcp"} <= tags
    assert {unit.kind for unit in units} == {"capability", "interface"}
    # tsconfig.json, docker-compose.yml and README.md are not specifications.
    assert {unit.location.path for unit in units} == {
        "api/openapi.json", "specs/petstore.yaml", "graphql/schema.graphql",
        "schemas/order.schema.json", "mcp/server.json", "mcp/tools.json",
    }


# --- deterministic -----------------------------------------------------------------------------


def test_the_same_artifact_gives_the_same_units_in_the_same_order(tmp_path):
    one = _units(_write(tmp_path / "one", FIXTURE))
    again = _units(tmp_path / "one")
    other = _units(_write(tmp_path / "other", FIXTURE, reverse=True))
    assert one == again == other
    assert [unit.id for unit in one] == [unit.id for unit in other]
    assert len({unit.id for unit in one}) == len(one)
    paths = [unit.location.path for unit in one]
    assert paths == sorted(paths)                  # file by file, in path order


# --- bounded -----------------------------------------------------------------------------------


def _schema(description: str = "small") -> str:
    return json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema",
                       "type": "object", "description": description})


def test_a_file_over_the_size_bound_is_not_read_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(interfaces, "MAX_FILE_BYTES", 200)
    units = _units(_write(tmp_path, {"big.json": _schema("x" * 500), "small.json": _schema()}))
    assert [(unit.location.path, unit.kind) for unit in units] == [
        ("big.json", "knowledge"), ("small.json", "interface"),
    ]
    assert units[0].tags == ("unparsed",) and "larger than 200 bytes" in units[0].body


def test_the_bytes_read_from_one_artifact_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(interfaces, "MAX_TOTAL_BYTES", 10)
    units = _units(_write(tmp_path, {"a.json": _schema(), "b.json": _schema()}))
    assert [(unit.location.path, unit.kind) for unit in units] == [
        ("a.json", "interface"), ("b.json", "knowledge"),
    ]
    assert "unparsed" in units[1].tags and "already came to 10 bytes" in units[1].body


def test_the_files_read_from_one_artifact_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(interfaces, "MAX_FILES", 2)
    units = _units(_write(tmp_path, {name: _schema() for name in ("a.json", "b.json", "c.json")}))
    assert [unit.location.path for unit in units] == ["a.json", "b.json", "."]
    assert "unparsed" in units[-1].tags and "1 more specification files" in units[-1].body


def test_the_entries_looked_at_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(interfaces, "MAX_ENTRIES", 2)
    units = _units(_write(tmp_path, {name: _schema() for name in ("a.json", "b.json", "c.json")}))
    assert len(units) == 1
    assert units[0].location == Location(".") and "more than 2 entries" in units[0].body


def test_the_units_from_one_artifact_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(interfaces, "MAX_UNITS", 3)
    units = _units(_write(tmp_path, {"api/openapi.json": OPENAPI}))
    assert len(units) == 3
    assert units[-1].location == Location(".") and "unparsed" in units[-1].tags
    assert "at most 3" in units[-1].body


def test_bodies_and_titles_are_bounded(tmp_path):
    long_path = "/" + "a" * 500
    units = _units(_write(tmp_path, {
        "long.json": _schema("d" * (MAX_BODY * 2)),
        "path.json": json.dumps({"openapi": "3.0.0", "paths": {long_path: {"get": {}}}}),
    }))
    schema, operation = units
    assert len(schema.body) == MAX_BODY and schema.body.endswith("…")
    assert len(operation.title) == MAX_TITLE and operation.kind == "capability"


# --- malformed input ---------------------------------------------------------------------------

MALFORMED = [
    ("broken.json", '{"openapi": "3.0.0", "paths": {', "line 1"),
    ("empty.json", "", "expected a JSON value"),
    ("nan.json", '{"a": NaN}', "expected a JSON value"),
    ("deep.json", "[" * 5000 + "]" * 5000, "deeper than"),
    ("binary.json", b"\xff\xfe\x00\x81", "UTF-8"),
    ("paths.json", '{"openapi": "3.0.0", "paths": []}', "'paths' is not a mapping"),
    ("operation.json",
     '{"openapi": "3.0.0", "paths": {"/x": {"get": "nope"}, "/y": {"post": {"summary": "Make"}}}}',
     "GET /x is not a mapping"),
    ("anchors.yaml", "openapi: 3.0.0\ninfo: &info\n  title: x\n", "anchors"),
    ("aliases.yaml", "openapi: 3.0.0\ninfo:\n  title: x\nother: *info\n", "anchors"),
    ("tabs.yaml", "openapi: 3.0.0\ninfo:\n\ttitle: x\n", "tab"),
    ("documents.yaml", "openapi: 3.0.0\n---\nopenapi: 3.1.0\n", "more than one document"),
    ("flow.yaml", "openapi: 3.0.0\ntags: [a,\n  b]\n", "does not close"),
    ("quoted.yaml", 'openapi: 3.0.0\ninfo:\n  title: "open\n    ended"\n', "does not close"),
    ("indent.yaml", "openapi: 3.0.0\ninfo:\n  title: x\n    version: 1\n", "indentation"),
    ("unclosed.graphql", "type Pet {\n  id: ID!\n", "ends"),
    ("query.graphql", "query { pets }\n", "schemas, not queries"),
    ("string.graphql", '"""never ends\ntype A { a: Int }\n', "does not end"),
    ("deep.graphql", "type A { a: " + "[" * 500 + "Int" + "]" * 500 + " }\n", "deeper than"),
    ("tools.json", '[{"name": "a", "inputSchema": {}}, 7]', "tool 2"),
]


@pytest.mark.parametrize(("name", "content", "reason"), MALFORMED,
                         ids=[name for name, _, _ in MALFORMED])
def test_malformed_input_becomes_an_unparsed_unit(tmp_path, name, content, reason):
    units = _units(_write(tmp_path, {name: content}))
    unparsed = [unit for unit in units if "unparsed" in unit.tags]
    assert len(unparsed) == 1, units
    assert unparsed[0].kind == "knowledge" and unparsed[0].location.path == name
    assert reason in unparsed[0].body


def test_what_can_be_read_beside_what_cannot_still_is(tmp_path):
    units = _units(_write(tmp_path, {"api/openapi.json": OPENAPI, "broken.json": "{"}))
    assert _titled(units, "Unparsed: broken.json").kind == "knowledge"
    assert len([unit for unit in units if unit.kind == "capability"]) == 6


def test_a_root_that_is_not_a_directory_is_said_so_not_raised(tmp_path):
    for root in (tmp_path / "missing", _write(tmp_path, {"file.json": "{}"}) / "file.json"):
        units = interfaces.decompose(root, ART)
        assert len(units) == 1 and units[0].tags == ("unparsed",)
        assert units[0].location == Location(".")


# --- read-only ---------------------------------------------------------------------------------


def test_the_adapter_only_reads_and_follows_no_links(tmp_path):
    outside = _write(tmp_path / "outside", {"openapi.json": OPENAPI, "more/server.json": SERVER})
    root = _write(tmp_path / "artifact", FIXTURE)
    (root / "linked.json").symlink_to(outside / "openapi.json")
    (root / "linked").symlink_to(outside / "more", target_is_directory=True)
    if hasattr(os, "mkfifo"):
        os.mkfifo(root / "pipe.json")               # would block a reader that opened it
    before = _snapshot(root)

    units = _units(root)

    assert not any(unit.location.path.startswith(("linked", "pipe")) for unit in units)
    assert units == _units(_write(tmp_path / "plain", FIXTURE))
    assert _snapshot(root) == before
