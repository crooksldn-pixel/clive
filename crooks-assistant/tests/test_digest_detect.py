"""Knowledge Digester 3: recognising what an artifact is (app/digest/detect.py).

Every kind has a fixture built in tmp_path; a real artifact is usually several kinds at once,
so the fixtures are also merged and detected together. Detection is reading names and small
heads: the tests watch os.open and os.read to hold it to that, and refuse every way of running
something while it works.
"""

from __future__ import annotations

import json
import os
import runpy
import subprocess
from pathlib import Path

import pytest

from app.digest import detect


def _skill(name: str) -> str:
    return f"---\nname: {name}\ndescription: Does {name} things\n---\n# {name}\n"


FIXTURES: dict[str, dict[str, str | bytes]] = {
    "git_repository": {
        ".git/HEAD": "ref: refs/heads/main\n",
        ".git/config": "[core]\n\tbare = false\n",
        "README.md": "# demo\n",
    },
    "agent_skill": {"SKILL.md": _skill("pdf-tools")},
    "skill_collection": {
        "skills/pdf/SKILL.md": _skill("pdf"),
        "skills/xlsx/SKILL.md": _skill("xlsx"),
    },
    "agent_config": {
        "CLAUDE.md": "# Project instructions\n",
        "AGENTS.md": "# Agents\n",
        ".cursor/rules/style.mdc": "---\ndescription: house style\n---\nUse British spelling.\n",
    },
    "mcp_server": {
        "package.json": '{"name": "weather-mcp", "dependencies": {"@modelcontextprotocol/sdk": "^1.0.0"}}',
        "src/index.ts": 'import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";\n',
    },
    "openapi_spec": {
        "openapi.yaml": "openapi: 3.1.0\ninfo:\n  title: Shop\n  version: 1.0.0\npaths: {}\n",
    },
    "json_schema_set": {
        "schemas/order.schema.json": '{"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}',
        "schemas/customer.schema.json": '{"$schema": "http://json-schema.org/draft-07/schema#", "type": "object"}',
    },
    "graphql_schema": {"schema.graphql": "type Query {\n  shop: Shop\n}\n\ntype Shop {\n  name: String\n}\n"},
    "python_package": {
        "pyproject.toml": '[project]\nname = "demo"\nversion = "0.1.0"\n',
        "src/demo/__init__.py": "",
    },
    "node_package": {
        "package.json": '{"name": "demo", "version": "1.0.0"}',
        "index.js": "module.exports = 1;\n",
    },
    "swift_project": {
        "Package.swift": "// swift-tools-version:5.9\nimport PackageDescription\n",
        "Sources/App/main.swift": 'print("hello")\n',
        "App.xcodeproj/project.pbxproj": "// !$*UTF8*$!\n",
    },
    "go_project": {"go.mod": "module example.com/demo\n\ngo 1.22\n", "main.go": "package main\n"},
    "rust_project": {
        "Cargo.toml": '[package]\nname = "demo"\nversion = "0.1.0"\n',
        "src/main.rs": "fn main() {}\n",
    },
    "java_project": {
        "pom.xml": '<?xml version="1.0"?>\n<project xmlns="http://maven.apache.org/POM/4.0.0">\n</project>\n',
        "src/main/java/App.java": "class App {}\n",
    },
    "shopify_theme": {
        "layout/theme.liquid": "<html>{{ content_for_layout }}</html>\n",
        "templates/index.json": "{}",
        "sections/header.liquid": "<header></header>\n",
        "snippets/icon.liquid": "<svg></svg>\n",
        "config/settings_schema.json": "[]",
        "locales/en.default.json": "{}",
    },
    "website": {
        "index.html": "<!doctype html>\n<html><body>Hello</body></html>\n",
        "about.html": "<!DOCTYPE html><html></html>\n",
        "style.css": "body { margin: 0 }\n",
    },
    "browser_extension": {
        "manifest.json": '{"manifest_version": 3, "name": "Demo", "version": "1.0", "background": {"service_worker": "bg.js"}}',
        "bg.js": "",
    },
    "mobile_app": {
        "app/src/main/AndroidManifest.xml": '<manifest package="com.demo"/>\n',
        "pubspec.yaml": "name: demo\ndependencies:\n  flutter:\n    sdk: flutter\n",
    },
    "jupyter_notebooks": {
        "analysis.ipynb": '{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}',
    },
    "documentation_set": {
        "mkdocs.yml": "site_name: Demo\n",
        "docs/index.md": "# Home\n",
        "docs/guide.md": "# Guide\n",
    },
    "office_documents": {
        "report.docx": b"PK\x03\x04" + b"\x00" * 26,
        "figures.xlsx": b"PK\x03\x04" + b"\x00" * 26,
        "deck.pptx": b"PK\x03\x04" + b"\x00" * 26,
        "paper.pdf": b"%PDF-1.7\n",
    },
    "dataset": {
        "orders.csv": "id,total,currency\n1,10.00,GBP\n",
        "rows.tsv": "a\tb\n1\t2\n",
        "events.jsonl": '{"a": 1}\n{"a": 2}\n',
        "table.parquet": b"PAR1" + b"\x00" * 8 + b"PAR1",
        "store.sqlite": b"SQLite format 3\x00" + b"\x00" * 84,
    },
    "design_tokens": {
        "tokens.json": '{"color": {"brand": {"$value": "#ff0000", "$type": "color"}}}',
        "tailwind.config.js": "module.exports = { theme: {} };\n",
        "styles/vars.css": ":root {\n  --brand: #f00;\n  --ink: #111;\n  --paper: #fff;\n}\n",
    },
    "images": {"a.png": b"\x89PNG\r\n\x1a\n", "b.jpg": b"\xff\xd8\xff\xe0"},
    "audio": {"a.mp3": b"ID3\x04", "b.wav": b"RIFF\x00\x00\x00\x00WAVE"},
    "video": {"a.mp4": b"\x00\x00\x00\x18ftypmp42", "b.mov": b"\x00\x00\x00\x14ftypqt  "},
    "infrastructure": {
        "Dockerfile": "FROM python:3.12-slim\nCOPY . /app\n",
        "compose.yaml": "services:\n  app:\n    build: .\n",
        "deploy/app.service": "[Unit]\nDescription=App\n\n[Service]\nExecStart=/bin/true\n",
        "infra/main.tf": 'resource "aws_s3_bucket" "b" {}\n',
    },
    "ci_workflows": {
        ".github/workflows/ci.yml": "name: CI\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n",
        ".gitlab-ci.yml": "test:\n  script: [make test]\n",
    },
}


def _write(root: Path, rel: str, content: str | bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def _build(root: Path, files: dict[str, str | bytes]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        _write(root, rel, content)
    return root


def _assert_well_formed(report: detect.DetectionReport, root: Path) -> None:
    confidences = [detection.confidence for detection in report.kinds]
    assert confidences == sorted(confidences, reverse=True)
    assert report.failures == {}
    for detection in report.kinds:
        assert detection.evidence, detection.kind
        for evidence in detection.evidence:
            assert evidence.signal
            assert evidence.weight <= detection.confidence
            assert (root / evidence.path).exists(), (detection.kind, evidence.path)


def test_every_registered_kind_has_a_fixture():
    assert {registration.kind for registration in detect.registered()} == set(FIXTURES)


@pytest.mark.parametrize("kind", sorted(FIXTURES))
def test_each_kind_is_recognised_with_evidence(tmp_path, kind):
    root = _build(tmp_path / kind, FIXTURES[kind])

    report = detect.detect_kinds(root)

    assert kind in report, report.names()
    assert detect.UNKNOWN not in report
    assert report.get(kind).confidence >= 0.5
    assert report.get(kind).label
    _assert_well_formed(report, root)


def test_every_kind_at_once_in_one_tree(tmp_path):
    root = tmp_path / "artifact"
    for kind, files in FIXTURES.items():
        _build(root / kind, files)

    report = detect.detect_kinds(root)

    assert set(FIXTURES) <= set(report.names())
    _assert_well_formed(report, root)


MULTI_KIND = {
    ".git/HEAD": "ref: refs/heads/main\n",
    "pyproject.toml": '[project]\nname = "toolkit"\nversion = "1.0"\n',
    "src/toolkit/__init__.py": "",
    "src/toolkit/core.py": "def run():\n    return 1\n",
    "skills/summarise/SKILL.md": _skill("summarise"),
    "skills/translate/SKILL.md": _skill("translate"),
    ".github/workflows/ci.yml": "on: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n",
    "CLAUDE.md": "# Instructions\n",
    "README.md": "# toolkit\n",
}


def test_a_python_package_that_is_also_a_skill_collection_with_ci(tmp_path):
    root = _build(tmp_path / "toolkit", MULTI_KIND)

    report = detect.detect_kinds(root)

    assert {
        "git_repository", "python_package", "skill_collection", "agent_skill", "ci_workflows",
        "agent_config",
    } <= set(report.names())
    assert detect.UNKNOWN not in report
    _assert_well_formed(report, root)

    python = report.get("python_package")
    assert python.evidence[0].path == "pyproject.toml"
    assert "declares a Python project" in python.evidence[0].signal
    assert "src/toolkit" in [evidence.path for evidence in python.evidence]

    collection = report.get("skill_collection")
    top = collection.evidence[0]
    assert top.path == "skills"
    assert "summarise" in top.signal and "translate" in top.signal

    workflows = report.get("ci_workflows")
    assert [evidence.path for evidence in workflows.evidence] == [".github/workflows/ci.yml"]

    git = report.get("git_repository")
    assert git.evidence[0].path == ".git"
    assert "refs/heads/main" in git.evidence[0].signal


def test_the_census_counts_extensions_and_top_level_layout(tmp_path):
    root = _build(tmp_path / "toolkit", MULTI_KIND)

    census = detect.detect_kinds(root).census

    # .git is walked past, not into: named as skipped, its contents not counted.
    assert census.files == len(MULTI_KIND) - 1
    assert census.by_extension == {".md": 4, ".py": 2, ".toml": 1, ".yml": 1}
    assert census.skipped == (".git",)
    assert census.top_level[".git"] == {"type": "dir", "files": 0, "skipped": True}
    assert census.top_level["skills"] == {"type": "dir", "files": 2, "skipped": False}
    assert census.top_level["pyproject.toml"] == {"type": "file"}
    assert census.truncated is False
    assert census.heads_read > 0


def test_ranking_puts_the_strongest_kind_first(tmp_path):
    root = _build(tmp_path / "pkg", {
        "pyproject.toml": '[project]\nname = "pkg"\n',
        "src/pkg/__init__.py": "",
        "src/pkg/core.py": "",
        "README.md": "# pkg\n",
        "assets/logo.png": b"\x89PNG\r\n\x1a\n",
    })

    report = detect.detect_kinds(root)

    assert report.names()[0] == "python_package"
    assert report.get("images").confidence < report.get("python_package").confidence
    _assert_well_formed(report, root)


def test_a_mislabelled_document_is_reported_with_weaker_evidence(tmp_path):
    root = _build(tmp_path / "docs", {
        "real.pdf": b"%PDF-1.4\n",
        "fake.pdf": b"MZ\x90\x00 not a pdf",
    })

    office = detect.detect_kinds(root).get("office_documents")

    by_path = {evidence.path: evidence for evidence in office.evidence}
    assert "signature verified" in by_path["real.pdf"].signal
    assert "is not a PDF document" in by_path["fake.pdf"].signal
    assert by_path["fake.pdf"].weight < by_path["real.pdf"].weight


def test_a_plain_skill_md_without_front_matter_is_not_an_agent_skill(tmp_path):
    root = _build(tmp_path / "plain", {"SKILL.md": "# Notes\nJust some notes about a skill.\n"})

    report = detect.detect_kinds(root)

    assert "agent_skill" not in report, report.names()
    assert "skill_collection" not in report


def test_a_plain_skill_md_is_only_weak_evidence_beside_a_real_skill(tmp_path):
    root = _build(tmp_path / "mixed", {
        "SKILL.md": _skill("real"),
        "drafts/SKILL.md": "# Draft\n",
    })

    skill = detect.detect_kinds(root).get("agent_skill")

    by_path = {evidence.path: evidence for evidence in skill.evidence}
    assert by_path["drafts/SKILL.md"].weight < by_path["SKILL.md"].weight
    assert skill.confidence >= 0.9


def test_an_unterminated_front_matter_block_is_not_front_matter(tmp_path):
    root = _build(tmp_path / "unterminated", {
        "SKILL.md": "---\nJust some notes about a skill,\nwith no closing delimiter.\n",
        "skills/pdf/SKILL.md": "---\nname: pdf\ndescription: Does pdf things\n# pdf\n",
        "skills/xlsx/SKILL.md": "---\nname: xlsx\ndescription: Does xlsx things\n# xlsx\n",
    })

    report = detect.detect_kinds(root)

    assert "agent_skill" not in report, report.names()
    assert "skill_collection" not in report, report.names()


def test_an_openapi_version_after_another_property_is_recognised(tmp_path):
    spec = {"info": {"title": "Shop", "version": "1.0.0"}, "openapi": "3.1.0", "paths": {}}
    legacy = {"info": {"title": "Pets", "version": "1"}, "host": "example.com", "swagger": "2.0"}
    root = _build(tmp_path / "specs", {
        "contract.json": json.dumps(spec),
        "legacy/service-v1.json": json.dumps(legacy, indent=2),
    })

    openapi = detect.detect_kinds(root).get("openapi_spec")

    assert openapi is not None
    by_path = {evidence.path: evidence for evidence in openapi.evidence}
    assert by_path["contract.json"].signal == "openapi 3.1.0 document"
    assert by_path["legacy/service-v1.json"].signal == "swagger 2.0 document"
    assert openapi.confidence >= 0.9


def test_an_openapi_key_nested_below_the_top_level_is_not_a_spec(tmp_path):
    root = _build(tmp_path / "config", {
        "settings.json": json.dumps({"x-tools": {"openapi": "3.0.0"}, "name": "demo"}),
    })

    assert "openapi_spec" not in detect.detect_kinds(root)


def test_a_nested_yaml_openapi_key_is_not_a_spec(tmp_path):
    root = _build(tmp_path / "config", {
        "generator.yaml": "name: client\ngenerator:\n  openapi: 3.1.0\n",
        "tools/settings.yml": "service:\n  swagger:\n    2.0\nlegacy:\n\tswagger: 2.0\n",
    })

    assert "openapi_spec" not in detect.detect_kinds(root)


def test_a_top_level_yaml_openapi_key_after_other_properties_is_recognised(tmp_path):
    root = _build(tmp_path / "specs", {
        "contract.yaml": "info:\n  title: Shop\n  version: 1.0.0\nopenapi: 3.1.0\npaths: {}\n",
    })

    openapi = detect.detect_kinds(root).get("openapi_spec")

    assert openapi is not None
    by_path = {evidence.path: evidence for evidence in openapi.evidence}
    assert by_path["contract.yaml"].signal == "openapi 3.1.0 document"


def test_an_mcp_client_is_not_an_mcp_server(tmp_path):
    root = _build(tmp_path / "clients", {
        "node/package.json": '{"name": "mcp-client", "dependencies": {"@modelcontextprotocol/sdk": "^1.0.0"}}',
        "node/src/client.ts": (
            'import { Client } from "@modelcontextprotocol/sdk/client/index.js";\n'
            'import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";\n'
            'const client = new Client({ name: "demo", version: "1.0.0" });\n'
        ),
        "py/pyproject.toml": '[project]\nname = "mcp-client"\ndependencies = ["mcp>=1.0", "fastmcp"]\n',
        "py/requirements.txt": "mcp>=1.0\n",
        "py/mcp_client.py": (
            "import mcp\n"
            "from mcp import ClientSession, StdioServerParameters\n"
            "from mcp.client.stdio import stdio_client\n"
            "from fastmcp import Client\n"
        ),
    })

    report = detect.detect_kinds(root)

    assert "mcp_server" not in report, report.names()
    assert {"node_package", "python_package"} <= set(report.names())


def test_an_mcp_server_needs_server_evidence_and_dependencies_only_corroborate(tmp_path):
    root = _build(tmp_path / "server", {
        "pyproject.toml": '[project]\nname = "weather"\ndependencies = ["mcp[cli]>=1.2"]\n',
        "weather.py": 'from mcp.server.fastmcp import FastMCP\n\nmcp = FastMCP("weather")\n',
    })

    server = detect.detect_kinds(root).get("mcp_server")

    assert server is not None
    by_path = {evidence.path: evidence for evidence in server.evidence}
    assert server.evidence[0].path == "weather.py"
    assert "server API" in by_path["weather.py"].signal
    assert by_path["pyproject.toml"].weight < by_path["weather.py"].weight


def test_a_graphql_operations_document_is_not_a_schema(tmp_path):
    root = _build(tmp_path / "ops", {
        "queries/shop.graphql": "query Shop {\n  shop {\n    name\n    type\n  }\n}\n",
        "queries/order.gql": "mutation Close($id: ID!) {\n  close(id: $id) {\n    id\n  }\n}\n",
    })

    report = detect.detect_kinds(root)

    assert "graphql_schema" not in report, report.names()


def test_unknown_carries_the_file_type_census(tmp_path):
    root = _build(tmp_path / "blob", {
        "blob.bin": b"\x00\x01\x02",
        "other.bin": b"\x03\x04",
        "notes": b"\x05",
    })

    report = detect.detect_kinds(root)

    assert report.names() == [detect.UNKNOWN]
    assert report.census.by_extension == {".bin": 2, detect.NO_EXTENSION: 1}
    signals = [evidence.signal for evidence in report.kinds[0].evidence]
    assert any("2 file(s) with extension .bin" in signal for signal in signals)
    _assert_well_formed(report, root)


def test_an_empty_directory_is_unknown(tmp_path):
    report = detect.detect_kinds(tmp_path)

    assert report.names() == [detect.UNKNOWN]
    assert report.census.files == 0


def test_a_single_file_is_detected_on_its_own(tmp_path):
    _write(tmp_path, "report.pdf", b"%PDF-1.7\n")
    _write(tmp_path, "SKILL.md", _skill("neighbour"))

    report = detect.detect_kinds(tmp_path / "report.pdf")

    assert report.names() == ["office_documents"]
    assert report.census.files == 1
    assert report.census.top_level == {"report.pdf": {"type": "file"}}
    # Its neighbours are not part of it, and are not read.
    assert detect.Tree(tmp_path / "report.pdf").head("SKILL.md") == ""


def test_the_report_is_plain_data(tmp_path):
    root = _build(tmp_path / "toolkit", MULTI_KIND)

    data = json.loads(json.dumps(detect.detect_kinds(root).to_dict()))

    assert data["kinds"][0]["evidence"][0]["path"]
    assert data["census"]["by_extension"][".md"] == 4


# --- the registry ---------------------------------------------------------------------------


def test_a_new_recogniser_can_be_registered_and_is_used(tmp_path):
    root = _build(tmp_path / "poems", {"autumn.haiku": "old pond\nfrog leaps in\nsplash\n"})
    assert detect.detect_kinds(root).names() == [detect.UNKNOWN]

    @detect.register("haiku_collection", "haiku collection")
    def haiku(tree: detect.Tree) -> detect.Match | None:
        found = detect.Findings()
        for rel in tree.suffixed(".haiku"):
            if len(tree.head(rel).splitlines()) == 3:
                found.add(rel, "three lines", 0.9)
        return found.match()

    try:
        assert "haiku_collection" in [registration.kind for registration in detect.registered()]
        report = detect.detect_kinds(root)
        assert report.names() == ["haiku_collection"]
        detection = report.get("haiku_collection")
        assert detection.label == "haiku collection"
        assert detection.confidence == 0.9
        assert detection.evidence == (detect.Evidence("autumn.haiku", "three lines", 0.9),)

        with pytest.raises(ValueError):
            detect.register("haiku_collection")(haiku)
        detect.register("haiku_collection", "haiku", replace=True)(haiku)
        assert detect.detect_kinds(root).get("haiku_collection").label == "haiku"
    finally:
        detect.unregister("haiku_collection")

    assert detect.detect_kinds(root).names() == [detect.UNKNOWN]


def test_unknown_is_reserved():
    with pytest.raises(ValueError):
        detect.register(detect.UNKNOWN)


def test_a_failing_recogniser_does_not_stop_the_others(tmp_path):
    root = _build(tmp_path / "pkg", FIXTURES["python_package"])

    @detect.register("broken")
    def broken(tree: detect.Tree) -> detect.Match | None:
        raise RuntimeError("boom")

    try:
        report = detect.detect_kinds(root)
    finally:
        detect.unregister("broken")

    assert "python_package" in report
    assert report.failures == {"broken": "RuntimeError: boom"}


def test_detection_can_be_limited_to_chosen_recognisers(tmp_path):
    root = _build(tmp_path / "toolkit", MULTI_KIND)
    chosen = [r for r in detect.registered() if r.kind in ("python_package", "ci_workflows")]

    report = detect.detect_kinds(root, recognisers=chosen)

    assert sorted(report.names()) == ["ci_workflows", "python_package"]


# --- reading, never running -----------------------------------------------------------------


def test_nothing_is_executed(tmp_path, monkeypatch):
    marker = tmp_path / "EXECUTED"
    root = _build(tmp_path / "artifact", {
        "setup.py": f"open({str(marker)!r}, 'w').write('ran')\n",
        "docs/conf.py": f"open({str(marker)!r}, 'w').write('ran')\n",
        "package.json": '{"name": "x", "scripts": {"postinstall": "touch EXECUTED"}}',
        "run.sh": f"#!/bin/sh\ntouch {marker}\n",
        "gradlew": f"#!/bin/sh\ntouch {marker}\n",
        "Makefile": f"all:\n\ttouch {marker}\n",
    })
    (root / "run.sh").chmod(0o755)
    (root / "gradlew").chmod(0o755)

    def refuse(*args, **kwargs):
        raise AssertionError("detection tried to run something")

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "Popen", refuse)
        patch.setattr(runpy, "run_path", refuse)
        patch.setattr(runpy, "run_module", refuse)
        for name in (
            "system", "popen", "execv", "execve", "execvp", "execvpe", "fork", "forkpty",
            "posix_spawn", "posix_spawnp", "spawnv", "spawnve",
        ):
            patch.setattr(os, name, refuse, raising=False)
        report = detect.detect_kinds(root)

    assert not marker.exists()
    assert {"python_package", "node_package", "java_project", "documentation_set"} <= set(report.names())
    assert report.failures == {}


def test_only_names_and_small_heads_are_read(tmp_path, monkeypatch):
    root = tmp_path / "artifact"
    for kind, files in FIXTURES.items():
        _build(root / kind, files)
    # A spec whose version key sits past the head: it is not seen, because it is not read.
    _write(root, "late/spec.json", "{" + " " * (detect.HEAD_BYTES * 3) + '"openapi": "3.0.0"}')
    _write(tmp_path, "outside.txt", "not part of the artifact")

    opened: list[Path] = []
    requested: list[int] = []
    real_open, real_read = os.open, os.read

    def spy_open(path, flags, *args, **kwargs):
        opened.append(Path(path))
        return real_open(path, flags, *args, **kwargs)

    def spy_read(fd, size):
        requested.append(size)
        return real_read(fd, size)

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", spy_open)
        patch.setattr(os, "read", spy_read)
        report = detect.detect_kinds(root)
        tree = detect.Tree(root)
        assert tree.head("../outside.txt") == ""
        assert tree.head(str(tmp_path / "outside.txt")) == ""
        assert tree.head("website") == ""  # a directory has no head

    assert opened and requested
    assert all(size <= detect.HEAD_BYTES for size in requested)
    assert len(opened) == report.census.heads_read
    resolved = root.resolve()
    for path in opened:
        assert path.resolve().is_relative_to(resolved), path
        assert path.is_file()
    assert "openapi_spec" in report
    assert "late/spec.json" not in [e.path for e in report.get("openapi_spec").evidence]


def test_symlinks_are_listed_and_never_followed(tmp_path):
    outside = _build(tmp_path / "outside", {
        "SKILL.md": _skill("elsewhere"),
        "pyproject.toml": '[project]\nname = "elsewhere"\n',
    })
    root = _build(tmp_path / "artifact", {"notes.bin": b"\x00\x01"})
    try:
        (root / "SKILL.md").symlink_to(outside / "SKILL.md")
        (root / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available here")

    report = detect.detect_kinds(root)

    assert report.names() == [detect.UNKNOWN]
    assert report.census.symlinks == 2
    assert report.census.top_level["SKILL.md"] == {"type": "symlink"}
    assert report.census.top_level["linked"] == {"type": "symlink"}
    tree = detect.Tree(root)
    assert tree.head("SKILL.md") == ""
    assert tree.head("linked/pyproject.toml") == ""
    with pytest.raises(ValueError):
        detect.Tree(root / "linked")


# --- hostile trees: bounded, linear, never raising --------------------------------------------


def test_a_tree_deeper_than_the_stack_is_walked_without_recursing(tmp_path):
    import inspect
    import sys

    depth = 400
    root = _build(tmp_path / "deep", {"pyproject.toml": '[project]\nname = "deep"\n'})
    (root / "/".join(["d"] * depth)).mkdir(parents=True)
    (root / "/".join(["d"] * depth) / "leaf.txt").write_text("leaf\n", encoding="utf-8")
    # A walk that recursed once per folder would need `depth` frames; the stack is limited to
    # far fewer, as a real tree deeper than the default limit (~1000) would do, without
    # leaving such a tree behind for every later temporary-directory clean-up to trip on.
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(len(inspect.stack(0)) + 100)
    try:
        report = detect.detect_kinds(root)
    finally:
        sys.setrecursionlimit(limit)

    assert "python_package" in report
    assert report.census.files == 2
    assert report.census.dirs == depth


def test_every_entry_counts_towards_the_walk_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(detect, "MAX_ENTRIES", 50)
    root = _build(tmp_path / "wide", {"pyproject.toml": '[project]\nname = "wide"\n'})
    for n in range(60):
        (root / "empty" / f"folder{n:02}").mkdir(parents=True)

    report = detect.detect_kinds(root)

    # Folders are entries too, and a folder is listed in full or not at all.
    assert report.census.truncated is True
    assert report.census.dirs == 1 and report.census.files == 1
    assert "python_package" in report


def test_many_folders_of_one_sort_are_looked_at_a_bounded_number_of_times(tmp_path):
    files: dict[str, str | bytes] = {}
    for n in range(detect.CANDIDATES + 20):
        for name in ("a.md", "b.md"):
            files[f"part{n:02}/docs/{name}"] = "# Page\n"
            files[f"part{n:02}/prompts/{name}"] = "Summarise this.\n"
        files[f"part{n:02}/tokens/colors.json"] = '{"brand": {"$value": "#f00"}}'
    root = _build(tmp_path / "parts", files)

    report = detect.detect_kinds(root)

    for kind in ("documentation_set", "agent_config", "design_tokens"):
        detection = report.get(kind)
        assert detection is not None, kind
        # At most CANDIDATES folders, and one signal for the files taken together.
        signals = len(detection.evidence) + detection.more_evidence
        assert signals <= detect.CANDIDATES + 1, (kind, signals)
        assert any(e.path.count("/") == 1 for e in detection.evidence), kind


def _best_of_three(run) -> float:
    import time

    best = float("inf")
    for _ in range(3):
        start = time.perf_counter()
        run()
        best = min(best, time.perf_counter() - start)
    return best


def test_expressions_run_on_a_head_in_linear_time():
    import re

    width = detect.HEAD_BYTES
    heads = {
        "newlines": "\n" * width,
        "blank lines": " \n" * (width // 2),
        "tabbed lines": "\t\n" * (width // 2),
        "open brackets": "mcp[\n" * (width // 5),
    }
    patterns = {name: value for name, value in vars(detect).items() if isinstance(value, re.Pattern)}
    assert {"_MCP_PY_LINE", "_DOCKER_FROM", "_TERRAFORM_BLOCK", "_FLUTTER", "_TAILWIND_THEME"} <= set(patterns)
    for name, pattern in patterns.items():
        for label, head in heads.items():
            took = _best_of_three(lambda p=pattern, h=head: (p.search(h), p.findall(h)))
            assert took < 0.02, (name, label, took)

    nested = '{"x": [' + '"openapi": "3.0.0", ' * (width // 20) + '], "openapi": "3.1.0"}'
    assert detect._openapi_version(nested).group(2) == "3.1.0"
    assert _best_of_three(lambda: detect._openapi_version(nested[:width])) < 0.01


def test_a_recogniser_that_answers_with_something_else_is_a_failure_not_a_crash(tmp_path):
    root = _build(tmp_path / "pkg", FIXTURES["python_package"])
    answers = {
        "answers_a_dict": {"confidence": 0.9},
        "answers_strings": detect.Match(0.9, ("pyproject.toml",)),
        "answers_nan": detect.Match(float("nan"), (detect.Evidence("pyproject.toml", "x", 0.5),)),
    }
    for kind, answer in answers.items():
        detect.register(kind)(lambda tree, answer=answer: answer)
    try:
        report = detect.detect_kinds(root)
    finally:
        for kind in answers:
            detect.unregister(kind)

    assert "python_package" in report
    assert set(report.failures) == set(answers)
    assert not set(answers) & set(report.names())


def test_a_folder_swapped_for_a_link_after_it_was_checked_is_not_read(tmp_path, monkeypatch):
    outside = _build(tmp_path / "outside", {"SKILL.md": _skill("elsewhere")})
    root = _build(tmp_path / "artifact", {"sub/SKILL.md": _skill("inside")})
    tree = detect.Tree(root)
    real_open = os.open

    def swap_then_open(path, flags, *args, **kwargs):
        if Path(path) == root / "sub" / "SKILL.md" and not (root / "sub").is_symlink():
            (root / "sub").rename(root / "sub.checked")
            (root / "sub").symlink_to(outside, target_is_directory=True)
        return real_open(path, flags, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", swap_then_open)
        head = tree.head("sub/SKILL.md")

    assert (root / "sub").is_symlink()      # the swap happened between the check and the open
    assert "elsewhere" not in head
    assert head == ""


def test_a_head_the_budget_does_not_allow_is_not_called_a_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(detect, "MAX_HEADS", 1)
    root = _build(tmp_path / "docs", {"a.pdf": b"%PDF-1.7\n", "b.pdf": b"%PDF-1.7\n"})

    report = detect.detect_kinds(root)

    by_path = {evidence.path: evidence for evidence in report.get("office_documents").evidence}
    assert "signature verified" in by_path["a.pdf"].signal
    assert "is not a PDF" not in by_path["b.pdf"].signal
    assert "not opened" in by_path["b.pdf"].signal
    assert report.census.heads_read == 1 and report.census.heads_refused >= 1


@pytest.mark.parametrize("files", [
    {"main.go": (
        'package main\n\nimport "github.com/mark3labs/mcp-go/server"\n\n'
        'func main() { server.ServeStdio(server.NewMCPServer("demo", "1.0")) }\n'
    )},
    {"main.go": (
        'package main\n\nimport "github.com/modelcontextprotocol/go-sdk/mcp"\n\n'
        'func main() { _ = mcp.NewServer(&mcp.Implementation{Name: "demo"}, nil) }\n'
    )},
    {"src/main.rs": "use rmcp::ServerHandler;\n\nstruct Demo;\n\nimpl ServerHandler for Demo {}\n"},
    {"src/main/java/Server.java": (
        "import io.modelcontextprotocol.server.McpServer;\n\n"
        "class Server { Object s = McpServer.sync(transport).build(); }\n"
    )},
    {"Program.cs": (
        "using ModelContextProtocol.Server;\n\n"
        "builder.Services.AddMcpServer().WithStdioServerTransport();\n"
    )},
], ids=["go-mcp-go", "go-sdk", "rust-rmcp", "java-sdk", "csharp-sdk"])
def test_mcp_servers_written_with_the_other_sdks_are_recognised(tmp_path, files):
    root = _build(tmp_path / "server", files)

    server = detect.detect_kinds(root).get("mcp_server")

    assert server is not None
    assert server.evidence[0].path == next(iter(files))
    assert "server API" in server.evidence[0].signal


def test_an_mcp_client_in_go_is_not_an_mcp_server(tmp_path):
    root = _build(tmp_path / "client", {
        "go.mod": "module example.com/client\n\nrequire github.com/mark3labs/mcp-go v0.30.0\n",
        "main.go": (
            'package main\n\nimport "github.com/mark3labs/mcp-go/client"\n\n'
            'func main() { c, _ := client.NewStdioMCPClient("server", nil); _ = c }\n'
        ),
    })

    assert "mcp_server" not in detect.detect_kinds(root)
