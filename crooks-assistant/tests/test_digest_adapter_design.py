"""The design adapter: design tokens from CSS, token files and Tailwind configurations; Shopify
sections, snippets and their schemas; the structure of HTML pages and the props of components —
all read, never run, in a deterministic order, within bounds, and with anything malformed
reported as an 'unparsed' Unit rather than raised."""

from __future__ import annotations

import ast
import os
import random
import subprocess
from pathlib import Path

import pytest

from app.digest import Artifact, Location, Source, content_digest
from app.digest.adapters import design
from app.digest.model import MAX_BODY, UNIT_KINDS

SOURCE = Source(
    origin="/quarantine/theme", origin_kind="directory", pinned_ref=content_digest(b"a theme"),
    licence=None, taken_at="2026-09-26T10:00:00+00:00", content_digest=content_digest(b"a theme"),
)
ART = SOURCE.artifact_id

CSS = """\
/* Brand tokens. --color-ghost: #000; is only a comment */
:root {
  --color-primary: #0055ff;
  --color-surface: rgb(255 255 255);
  --brand-ink: #111111;
  --font-body: "Inter", system-ui, sans-serif;
  --line-height-tight: 1.2;
  --space-4: 1rem;
  --radius-md: 8px;
  --shadow-card: 0 1px 2px rgba(0, 0, 0, 0.2);
  --duration-fast: 150ms;
  --z-modal: 100;
}
.button { color: var(--color-primary); background: url(https://example.invalid/x.png); }
"""

TOKENS_JSON = """\
{
  "color": {
    "$type": "color",
    "brand": {
      "primary": { "$value": "#0055ff" },
      "ink": { "$value": "#111111" }
    }
  },
  "space": {
    "sm": { "$value": "4px", "$type": "dimension" }
  },
  "font": {
    "body": { "$value": ["Inter", "sans-serif"], "$type": "fontFamily" }
  },
  "radius": { "md": { "$value": "8px", "$type": "dimension" } },
  "shadow": { "card": { "$value": { "offsetX": "0px", "offsetY": "1px", "blur": "2px", "color": "#0003" }, "$type": "shadow" } },
  "motion": { "fast": { "$value": "150ms", "$type": "duration" } },
  "z": { "modal": { "$value": 100, "$type": "number" } }
}
"""

STYLE_DICTIONARY = """\
{
  "color": { "accent": { "value": "#ff0000" } },
  "size": { "font": { "base": { "value": "16px" } } }
}
"""

TAILWIND = """\
// tailwind.config.js — read as text, never run
const plugin = require('tailwindcss/plugin')   // never required

module.exports = {
  content: ['./src/**/*.{html,js}'],
  theme: {
    fontFamily: {
      sans: ['Inter', 'system-ui'],
    },
    extend: {
      colors: {
        brand: { 50: '#eff6ff', DEFAULT: '#1d4ed8' },
        'ink-muted': "rgb(0 0 0 / 60%)", // a comment: { not a brace
      },
      spacing: { 128: '32rem' },
      borderRadius: { xl2: '1.25rem' },
      boxShadow: { card: '0 1px 2px rgba(0,0,0,0.1)' },
      transitionDuration: { 400: '400ms' },
      zIndex: { 60: '60' },
    },
  },
  plugins: [plugin(function ({ addBase }) { require('child_process').execSync('touch pwned') })],
}
"""

HERO = """\
<div class="hero hero--{{ section.settings.style }}">
  <h2 class="hero__title">{{ section.settings.heading }}</h2>
  {% render 'button', label: section.settings.cta %}
  {% for block in section.blocks %}
    <div class="hero__slide">{{ block.settings.caption }}</div>
  {% endfor %}
</div>
{% javascript %}
  console.log('never run')
{% endjavascript %}
{% schema %}
{
  "name": "Hero",
  "settings": [
    { "type": "text", "id": "heading", "label": "Heading", "default": "Hello" },
    { "type": "select", "id": "style", "label": "Style", "options": [] }
  ],
  "blocks": [
    { "type": "slide", "name": "Slide", "settings": [{ "type": "text", "id": "caption", "label": "Caption" }] }
  ],
  "presets": [{ "name": "Hero" }]
}
{% endschema %}
"""

PRICE = """\
{%- comment -%} Renders a price {%- endcomment -%}
<span class="price price--sale">{{ product.price | money }}</span>
"""

SETTINGS = """\
[
  {
    "name": "theme_info",
    "theme_name": "Crooks",
    "theme_version": "1.0.0"
  },
  {
    "name": "Colours",
    "settings": [
      { "type": "color", "id": "colour_accent", "label": "Accent", "default": "#ff5500" }
    ]
  }
]
"""

PAGE = """\
<!doctype html>
<html lang="en">
<head>
  <title>Crooks — Home</title>
  <script>document.write("<h1>Injected</h1>")</script>
</head>
<body>
  <header class="site-header">
    <nav aria-label="Main" class="nav nav--primary"><a class="nav__link" href="/">Home</a></nav>
  </header>
  <main id="content">
    <h1>Welcome</h1>
    <section class="hero hero--dark"><h2>New <em>season</em></h2></section>
    <product-card class="card card__media"></product-card>
    <form action="/search" method="get" role="search">
      <input type="search" name="q">
      <button type="submit">Go</button>
    </form>
  </main>
  <footer></footer>
  <script src="/app.js"></script>
</body>
</html>
"""

BUTTON = """\
import React from 'react'

export function Button({ label, size = 'md', ...rest }) {
  return <button className={`btn btn--${size}`} {...rest}>{label}</button>
}

export const IconButton = ({ icon, onClick }) => <Button label={icon} onClick={onClick} />

export default function Page(props) {
  return <main>{props.children}</main>
}
"""

CARD = """\
type Tone = 'plain' | 'loud'

export interface CardProps {
  title: string
  tone?: Tone
  onOpen?: (id: string) => void
}

export const Card: React.FC<CardProps> = (props: CardProps) => {
  return <section className="card card--raised">{props.title}</section>
}
"""

BADGE = """\
<template>
  <span class="badge badge--large" role="status">{{ label }}</span>
</template>

<script setup lang="ts">
const props = defineProps({
  label: String,
  count: { type: Number, default: 0 },
})
</script>

<style scoped>
.badge { color: red; }
</style>
"""

COUNTER = """\
<script>
  export let start = 0;
  export let step;
</script>

<button class="counter__button" on:click={increment}>{start}</button>
"""

TAG = """\
<script lang="ts">
  let { text, tone = 'plain' }: { text: string; tone?: string } = $props();
</script>
<em class="tag">{text}</em>
"""

FIXTURES = {
    "styles/tokens.css": CSS,
    "tokens.json": TOKENS_JSON,
    "tokens/base.json": STYLE_DICTIONARY,
    "tailwind.config.js": TAILWIND,
    "sections/hero.liquid": HERO,
    "snippets/price.liquid": PRICE,
    "config/settings_schema.json": SETTINGS,
    "index.html": PAGE,
    "components/Button.jsx": BUTTON,
    "components/Card.tsx": CARD,
    "components/Badge.vue": BADGE,
    "components/Counter.svelte": COUNTER,
    "components/Tag.svelte": TAG,
    "README.md": "# Not a design file, so not read.\n",
    "node_modules/lib/tokens.json": '{"color": {"x": {"$value": "#000"}}}',
    ".cache/cached.css": ":root { --color-cached: #000; }\n",
}


def _write(root: Path, rel: str, content: str | bytes) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _build(root: Path, *, reverse: bool = False) -> Path:
    items = list(FIXTURES.items())
    for rel, content in reversed(items) if reverse else items:
        _write(root, rel, content)
    return root


def _one(units, path: str, kind: str, *tags: str):
    found = [
        unit for unit in units
        if unit.location.path == path and unit.kind == kind and set(tags) <= set(unit.tags)
    ]
    assert len(found) == 1, [(u.kind, u.title, u.tags) for u in units if u.location.path == path]
    return found[0]


def _unparsed(units, path: str) -> list:
    return [unit for unit in units if unit.location.path == path and "unparsed" in unit.tags]


def _lines(unit) -> list[str]:
    return unit.body.splitlines()


# --- the contract ------------------------------------------------------------------------------


def test_the_adapter_meets_the_shared_contract():
    assert isinstance(design.NAME, str) and design.NAME
    assert isinstance(design.HANDLES, tuple) and design.HANDLES
    assert all(isinstance(kind, str) and kind for kind in design.HANDLES)
    assert callable(design.decompose)
    adapters = Path(design.__file__).parent
    assert adapters.name == "adapters"
    assert not (adapters / "__init__.py").exists()      # a namespace package, shared by siblings


def test_every_unit_is_valid_and_belongs_to_the_artifact(tmp_path):
    units = design.decompose(_build(tmp_path), ART)
    artifact = Artifact(source=SOURCE, kinds=("theme", "web_app"), units=tuple(units))
    assert artifact.units == tuple(units)
    assert {unit.kind for unit in units} <= {"design_token", "pattern", "interface", "knowledge"}
    assert all(unit.kind in UNIT_KINDS and len(unit.body) <= MAX_BODY for unit in units)
    assert _unparsed(units, ".") == []
    assert not [unit for unit in units if "unparsed" in unit.tags]
    paths = {unit.location.path for unit in units}
    assert "README.md" not in paths
    assert not any(path.startswith(("node_modules/", ".cache/")) for path in paths)


def test_a_bad_artifact_id_is_the_callers_mistake(tmp_path):
    with pytest.raises(ValueError):
        design.decompose(tmp_path, "not-an-id")


# --- design tokens -----------------------------------------------------------------------------


def test_css_custom_properties_become_grouped_design_tokens(tmp_path):
    _write(tmp_path, "styles/tokens.css", CSS)
    units = design.decompose(tmp_path, ART)
    assert [unit.tags for unit in units] == [("design", group, "css") for group in design.GROUPS]
    assert all(unit.kind == "design_token" for unit in units)
    by_group = {unit.tags[1]: unit for unit in units}
    rel = "styles/tokens.css"
    assert by_group["colour"].title == f"Colour tokens: {rel}"
    assert by_group["colour"].location == Location(rel, 3, 5)
    assert "- --color-primary: #0055ff (line 3)" in _lines(by_group["colour"])
    assert "- --color-surface: rgb(255 255 255) (line 4)" in _lines(by_group["colour"])
    assert "- --brand-ink: #111111 (line 5)" in _lines(by_group["colour"])   # by its value
    assert by_group["typography"].location == Location(rel, 6, 7)
    assert '- --font-body: "Inter", system-ui, sans-serif (line 6)' in _lines(by_group["typography"])
    assert "- --line-height-tight: 1.2 (line 7)" in _lines(by_group["typography"])
    assert by_group["spacing"].location == Location(rel, 8, 8)
    assert by_group["radius"].location == Location(rel, 9, 9)
    assert by_group["shadow"].location == Location(rel, 10, 10)
    assert "- --shadow-card: 0 1px 2px rgba(0, 0, 0, 0.2) (line 10)" in _lines(by_group["shadow"])
    assert by_group["motion"].location == Location(rel, 11, 11)
    assert "- --duration-fast: 150ms (line 11)" in _lines(by_group["motion"])
    everything = "\n".join(unit.body for unit in units)
    assert "--color-ghost" not in everything      # only in a comment
    assert "--z-modal" not in everything          # in none of the groups


def test_design_token_files_become_grouped_design_tokens(tmp_path):
    _write(tmp_path, "tokens.json", TOKENS_JSON)
    _write(tmp_path, "tokens/base.json", STYLE_DICTIONARY)
    units = design.decompose(tmp_path, ART)

    colour = _one(units, "tokens.json", "design_token", "colour", "tokens_json")
    assert colour.location == Location("tokens.json", 5, 6)      # the group's $type is inherited
    assert "- color.brand.primary: #0055ff (line 5)" in _lines(colour)
    assert "- color.brand.ink: #111111 (line 6)" in _lines(colour)
    spacing = _one(units, "tokens.json", "design_token", "spacing")
    assert "- space.sm: 4px (line 10)" in _lines(spacing)
    typography = _one(units, "tokens.json", "design_token", "typography")
    assert '- font.body: ["Inter", "sans-serif"] (line 13)' in _lines(typography)
    assert _one(units, "tokens.json", "design_token", "radius").location == Location("tokens.json", 15, 15)
    shadow = _one(units, "tokens.json", "design_token", "shadow")
    assert shadow.location == Location("tokens.json", 16, 16)
    assert "shadow.card" in shadow.body
    motion = _one(units, "tokens.json", "design_token", "motion")
    assert "- motion.fast: 150ms (line 17)" in _lines(motion)
    assert "z.modal" not in "\n".join(unit.body for unit in units)

    accent = _one(units, "tokens/base.json", "design_token", "colour")
    assert accent.location == Location("tokens/base.json", 2, 2)
    assert "- color.accent: #ff0000 (line 2)" in _lines(accent)
    size = _one(units, "tokens/base.json", "design_token", "typography")
    assert "- size.font.base: 16px (line 3)" in _lines(size)


def test_a_tailwind_configuration_is_read_as_text_and_never_evaluated(tmp_path):
    _write(tmp_path, "tailwind.config.js", TAILWIND)
    units = design.decompose(tmp_path, ART)
    rel = "tailwind.config.js"
    assert [unit.tags[1] for unit in units] == list(design.GROUPS)
    colour = _one(units, rel, "design_token", "colour", "tailwind")
    assert colour.location == Location(rel, 12, 13)
    assert "- extend.colors.brand.50: '#eff6ff' (line 12)" in _lines(colour)
    assert "- extend.colors.brand.DEFAULT: '#1d4ed8' (line 12)" in _lines(colour)
    assert '- extend.colors.ink-muted: "rgb(0 0 0 / 60%)" (line 13)' in _lines(colour)
    typography = _one(units, rel, "design_token", "typography")
    assert "- fontFamily.sans: ['Inter', 'system-ui'] (line 8)" in _lines(typography)
    assert "- extend.spacing.128: '32rem' (line 15)" in _lines(_one(units, rel, "design_token", "spacing"))
    assert "- extend.borderRadius.xl2: '1.25rem' (line 16)" in _lines(_one(units, rel, "design_token", "radius"))
    assert _one(units, rel, "design_token", "shadow").location == Location(rel, 17, 17)
    assert "- extend.transitionDuration.400: '400ms' (line 18)" in _lines(_one(units, rel, "design_token", "motion"))
    everything = "\n".join(unit.body for unit in units)
    assert "zIndex" not in everything and "child_process" not in everything
    assert not (tmp_path / "pwned").exists()


MULTILINE_CSS = """\
:root {
  --shadow-stack:
    0 1px 2px rgba(0, 0, 0, 0.2),
    0 4px 8px rgba(0, 0, 0, 0.1);
  --color-ink: #111;
}
"""

MULTILINE_TOKENS = """\
{
  "font": {
    "body": {
      "$type": "fontFamily",
      "$value": [
        "Inter",
        "sans-serif"
      ]
    }
  },
  "color": {
    "ink": {
      "$value":
        "#111111"
    }
  }
}
"""

MULTILINE_TAILWIND = """\
module.exports = {
  theme: {
    boxShadow: {
      card: [
        '0 1px 2px rgba(0,0,0,0.1)',
        '0 4px 8px rgba(0,0,0,0.1)',
      ],
    },
    colors: { ink: '#111' },
  },
}
"""


def test_a_token_written_over_several_lines_is_located_on_all_of_them(tmp_path):
    _write(tmp_path, "multi.css", MULTILINE_CSS)
    _write(tmp_path, "tokens.json", MULTILINE_TOKENS)
    _write(tmp_path, "tailwind.config.js", MULTILINE_TAILWIND)
    units = design.decompose(tmp_path, ART)
    assert not [unit for unit in units if "unparsed" in unit.tags]

    shadow = _one(units, "multi.css", "design_token", "shadow")
    assert shadow.location == Location("multi.css", 2, 4)
    assert ("- --shadow-stack: 0 1px 2px rgba(0, 0, 0, 0.2), 0 4px 8px rgba(0, 0, 0, 0.1) "
            "(lines 2-4)") in _lines(shadow)
    assert _one(units, "multi.css", "design_token", "colour").location == Location("multi.css", 5, 5)

    typography = _one(units, "tokens.json", "design_token", "typography")
    assert typography.location == Location("tokens.json", 3, 8)
    assert '- font.body: ["Inter", "sans-serif"] (lines 3-8)' in _lines(typography)
    colour = _one(units, "tokens.json", "design_token", "colour")
    assert colour.location == Location("tokens.json", 12, 14)
    assert "- color.ink: #111111 (lines 12-14)" in _lines(colour)

    rel = "tailwind.config.js"
    shadow = _one(units, rel, "design_token", "shadow")
    assert shadow.location == Location(rel, 4, 7)
    [card] = [line for line in _lines(shadow) if line.startswith("- boxShadow.card:")]
    assert "'0 1px 2px rgba(0,0,0,0.1)'" in card and "'0 4px 8px rgba(0,0,0,0.1)'" in card
    assert card.endswith("(lines 4-7)")
    assert _one(units, rel, "design_token", "colour").location == Location(rel, 9, 9)


def test_a_theme_only_code_could_produce_is_reported_not_run(tmp_path):
    _write(tmp_path, "tailwind.config.js", "module.exports = require('./preset')\n")
    [unit] = design.decompose(tmp_path, ART)
    assert unit.kind == "knowledge" and "unparsed" in unit.tags
    assert unit.location == Location("tailwind.config.js")
    assert "never evaluated" in unit.body


# --- Shopify themes ----------------------------------------------------------------------------


def test_a_section_becomes_a_pattern_and_its_schema_an_interface(tmp_path):
    units = design.decompose(_build(tmp_path), ART)
    rel = "sections/hero.liquid"
    pattern = _one(units, rel, "pattern", "shopify", "section")
    assert pattern.title == "Shopify section: hero"
    assert pattern.location == Location(rel, 1, 23)
    lines = _lines(pattern)
    assert 'Schema: lines 11-23, named "Hero": 2 setting(s), 1 block type(s), 1 preset(s)' in lines
    assert "- line 3: render 'button'" in lines
    for setting in ("section.settings.heading", "section.settings.style", "section.settings.cta",
                    "block.settings.caption"):
        assert f"- {setting}" in lines
    assert "- line 2: h2 {{ section.settings.heading }}" in lines
    assert "- hero (3)" in lines
    assert "{% javascript %} blocks: 1, not read or run" in lines
    assert "console.log" not in pattern.body

    schema = _one(units, rel, "interface", "schema")
    assert schema.title == "Schema of Shopify section: hero"
    assert schema.location == Location(rel, 11, 23)
    lines = _lines(schema)
    assert 'name: "Hero"' in lines
    assert '- id "heading", type "text", label "Heading", default "Hello"' in lines
    assert '- type "slide", name "Slide"; settings: caption' in lines
    assert '- "Hero"' in lines
    assert '"presets": [' in schema.body                       # the JSON itself


def test_a_snippet_becomes_a_pattern(tmp_path):
    units = design.decompose(_build(tmp_path), ART)
    snippet = _one(units, "snippets/price.liquid", "pattern", "shopify", "snippet")
    assert snippet.title == "Shopify snippet: price"
    assert snippet.location == Location("snippets/price.liquid", 1, 2)
    assert "Schema: none" in _lines(snippet)
    assert "- price (1)" in _lines(snippet)
    assert [unit.kind for unit in units if unit.location.path == "snippets/price.liquid"] == ["pattern"]


def test_theme_settings_become_interfaces(tmp_path):
    units = design.decompose(_build(tmp_path), ART)
    rel = "config/settings_schema.json"
    groups = [unit for unit in units if unit.location.path == rel]
    assert [(unit.kind, unit.title, unit.location) for unit in groups] == [
        ("interface", "Theme settings: theme_info", Location(rel, 2, 6)),
        ("interface", "Theme settings: Colours", Location(rel, 7, 12)),
    ]
    assert 'theme_name: "Crooks"' in _lines(groups[0])
    assert '- id "colour_accent", type "color", label "Accent", default "#ff5500"' in _lines(groups[1])


# --- web pages and components ------------------------------------------------------------------


def test_a_page_becomes_a_pattern_of_its_structure_without_its_scripts(tmp_path):
    units = design.decompose(_build(tmp_path), ART)
    page = _one(units, "index.html", "pattern", "page")
    assert page.title == "Page index.html: Crooks — Home"
    assert page.location == Location("index.html", 1, 23)
    lines = _lines(page)
    assert "Scripts: 2 <script> element(s), not read or run" in lines
    assert "Landmarks:" in lines
    for landmark in ("- line 8: header", '- line 9: nav aria-label="Main"',
                     '- line 11: main id="content"', "- line 13: section",
                     '- line 15: form role="search"', "- line 20: footer"):
        assert landmark in lines
    assert "- line 12: h1 Welcome" in lines
    assert "- line 13: h2 New season" in lines
    assert ('- line 15: form role="search" action="/search" method="get"; '
            "fields: input search name=q, button submit") in lines
    components = lines.index("Components (by class naming):")
    assert lines[components + 1:components + 4] == ["- nav (2)", "- card (1)", "- hero (1)"]
    assert "- product-card (1)" in lines
    assert "Injected" not in page.body and "document.write" not in page.body


def test_components_become_patterns_with_their_props(tmp_path):
    units = design.decompose(_build(tmp_path), ART)

    button = _one(units, "components/Button.jsx", "pattern", "component", "jsx")
    assert button.title == "Component Button: components/Button.jsx"
    assert button.location == Location("components/Button.jsx", 1, 11)
    for line in ("- Button (line 3)", "  - line 3: label", "  - line 3: size = 'md'",
                 "  - line 3: ...rest", "- IconButton (line 7)", "  - line 7: icon",
                 "  - line 7: onClick", "- Page (line 9): props taken whole, so not listed"):
        assert line in _lines(button)

    card = _one(units, "components/Card.tsx", "pattern", "component", "tsx")
    for line in ("- Card (line 9): props typed as CardProps", "  - line 4: title: string",
                 "  - line 5: tone?: Tone", "  - line 6: onOpen?: (id: string) => void",
                 "Prop types:", "- CardProps (line 3)"):
        assert line in _lines(card)

    badge = _one(units, "components/Badge.vue", "pattern", "component", "vue")
    for line in ("Props:", "- line 7: label: String",
                 "- line 8: count: { type: Number, default: 0 }", "- badge (1)"):
        assert line in _lines(badge)

    counter = _one(units, "components/Counter.svelte", "pattern", "component", "svelte")
    for line in ("- line 2: start = 0", "- line 3: step", "- counter (1)"):
        assert line in _lines(counter)

    tag = _one(units, "components/Tag.svelte", "pattern", "component", "svelte")
    for line in ("- line 2: text", "- line 2: tone = 'plain'"):
        assert line in _lines(tag)


# --- deterministic, read-only, never run -------------------------------------------------------


def test_the_same_artifact_gives_the_same_units_in_the_same_order(tmp_path):
    one = design.decompose(_build(tmp_path / "one"), ART)
    two = design.decompose(_build(tmp_path / "two", reverse=True), ART)
    again = design.decompose(tmp_path / "one", ART)
    assert [unit.to_dict() for unit in one] == [unit.to_dict() for unit in two]
    assert [unit.to_dict() for unit in one] == [unit.to_dict() for unit in again]
    paths = [unit.location.path for unit in one if unit.location.path != "."]
    assert paths == sorted(paths)


def _snapshot(root: Path) -> dict:
    return {
        path.relative_to(root).as_posix(): (
            path.is_dir(), None if path.is_dir() else path.read_bytes(), path.stat().st_mtime_ns,
        )
        for path in sorted(root.rglob("*"))
    }


def test_decomposing_writes_nothing_and_runs_nothing(tmp_path, monkeypatch):
    _build(tmp_path)
    before = _snapshot(tmp_path)

    def refuse(*args, **kwargs):
        raise AssertionError("the adapter tried to run something")

    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(os, "system", refuse)
    assert design.decompose(tmp_path, ART)
    assert _snapshot(tmp_path) == before
    assert not (tmp_path / "pwned").exists()


def test_the_adapter_source_neither_evaluates_nor_writes():
    tree = ast.parse(Path(design.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert imported <= {
        "__future__", "bisect", "json", "os", "re", "stat", "html.parser", "pathlib",
        "app.digest.model",
    }
    calls = [node.func for node in ast.walk(tree) if isinstance(node, ast.Call)]
    names = {func.id for func in calls if isinstance(func, ast.Name)}
    attributes = {func.attr for func in calls if isinstance(func, ast.Attribute)}
    assert not names & {"eval", "exec", "compile", "__import__", "open", "input"}
    assert not attributes & {
        "system", "popen", "Popen", "run", "call", "check_call", "check_output", "execv",
        "spawnv", "import_module", "exec_module", "write", "write_text", "write_bytes", "mkdir",
        "unlink", "rmdir", "rename", "chmod", "touch", "symlink_to",
    }


# --- bounds ------------------------------------------------------------------------------------


def test_the_limits_are_set():
    for limit in ("MAX_FILES", "MAX_ENTRIES", "MAX_FILE_BYTES", "MAX_UNITS", "MAX_TOKENS",
                  "MAX_DEPTH", "MAX_LISTED", "MAX_COMPONENTS"):
        assert isinstance(getattr(design, limit), int) and getattr(design, limit) > 0


def test_a_file_over_the_size_bound_is_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(design, "MAX_FILE_BYTES", 64)
    _write(tmp_path, "big.css", ":root {\n" + "  --color-a: #000000;\n" * 10 + "}\n")
    _write(tmp_path, "small.css", ":root { --color-a: #000; }\n")
    units = design.decompose(tmp_path, ART)
    [skipped] = _unparsed(units, "big.css")
    assert skipped.kind == "knowledge" and "64-byte limit" in skipped.body
    assert [unit.location.path for unit in units if unit.kind == "design_token"] == ["small.css"]


def test_the_number_of_files_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(design, "MAX_FILES", 2)
    for name in ("a", "b", "c"):
        _write(tmp_path, f"{name}.css", ":root { --color-a: #000; }\n")
    units = design.decompose(tmp_path, ART)
    assert [unit.location.path for unit in units if unit.kind == "design_token"] == ["a.css", "b.css"]
    [note] = _unparsed(units, ".")
    assert "more than 2 design files" in note.body


def test_the_number_of_units_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(design, "MAX_UNITS", 2)
    for name in ("a", "b", "c"):
        _write(tmp_path, f"{name}.css", ":root { --color-a: #000; }\n")
    units = design.decompose(tmp_path, ART)
    assert [unit.location.path for unit in units] == ["a.css", "b.css", "."]
    assert "stopped at 2 units: c.css" in units[-1].body


def test_the_directory_entries_looked_at_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(design, "MAX_ENTRIES", 5)
    _write(tmp_path, "a.css", ":root { --color-a: #000; }\n")
    for index in range(10):                                   # more empty directories than the bound
        (tmp_path / "empty" / f"d{index}").mkdir(parents=True)
    _write(tmp_path, "later/b.css", ":root { --color-b: #fff; }\n")
    units = design.decompose(tmp_path, ART)
    assert [unit.location.path for unit in units] == ["a.css", "."]
    note = units[-1]
    assert note.kind == "knowledge" and "unparsed" in note.tags
    assert "more than 5 directory entries in the artifact: empty and the directories after" in note.body
    assert units == design.decompose(tmp_path, ART)


def test_a_deep_tree_of_empty_directories_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(design, "MAX_ENTRIES", 5)
    _write(tmp_path, "a.css", ":root { --color-a: #000; }\n")
    (tmp_path / "deep" / Path(*["x"] * 20)).mkdir(parents=True)
    units = design.decompose(tmp_path, ART)
    assert [unit.location.path for unit in units] == ["a.css", "."]
    assert "more than 5 directory entries in the artifact: deep/x/x/x and" in units[-1].body
    assert units == design.decompose(tmp_path, ART)


def test_the_number_of_tokens_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(design, "MAX_TOKENS", 3)
    _write(tmp_path, "many.css",
           ":root {\n" + "".join(f"  --color-{i}: #00000{i};\n" for i in range(5)) + "}\n")
    units = design.decompose(tmp_path, ART)
    colour = _one(units, "many.css", "design_token", "colour")
    assert colour.location == Location("many.css", 2, 4)
    assert colour.body.startswith("3 colour token(s)")
    [note] = _unparsed(units, "many.css")
    assert "more than 3 design tokens" in note.body


def test_a_long_body_is_cut_to_the_bound(tmp_path):
    _write(tmp_path, "long.css", ":root {\n" + "".join(
        f"  --color-token-number-{i:04d}-with-a-long-name: #123456;\n" for i in range(1500)
    ) + "}\n")
    [colour] = design.decompose(tmp_path, ART)
    assert len(colour.body) == MAX_BODY and colour.body.endswith("…")
    assert colour.location == Location("long.css", 2, 1501)


# --- malformed input ---------------------------------------------------------------------------

MALFORMED = {
    "tokens.json": '{"color": {"primary": {"$value": "#fff"}',
    "deep/tokens.json": "[" * 100_000,
    "config/settings_schema.json": '{"not": "a list"}',
    "styles/binary.css": b"\xff\xfe\x00--color-x: red;",
    "tailwind.config.js": "module.exports = require('./preset')\n",
    "unclosed/tailwind.config.js": "module.exports = { theme: { colors: { red: '#f00' \n",
    "mismatch/tailwind.config.js": "module.exports = { theme: { colors: { red: '#f00' ] } }\n",
    "styles/open-comment.css": ":root { --color-a: #000; }\n/* never closed\n:root { --color-b: #fff; }\n",
    "styles/unclosed.css": ":root {\n  --color-a: #000;\n",
    "sections/broken.liquid": (
        '<div class="broken"></div>\n{% schema %}\n{ "name": "Broken", }\n{% endschema %}\n'
    ),
    "sections/open.liquid": '<div></div>\n{% schema %}\n{ "name": "Open" }\n',
    "sections/twice.liquid": (
        '<div></div>\n{% schema %}\n{ "name": "First" }\n{% endschema %}\n'
        '{% schema %}\n{ "name": "Second" }\n'
    ),
    "snippets/script.liquid": (
        '<div class="x"></div>\n{% javascript %}\n  document.title = "{{ settings.x }}"\n'
    ),
    "components/Broken.jsx": "export function Broken({ a, b\n",
    "components/Mismatch.tsx": "export const Mismatch = ({ a, b ) => null\n",
    "components/Open.vue": (
        "<script setup>\nconst props = defineProps({\n  label: String,\n</script>\n"
        "<template><p>{{ label }}</p></template>\n"
    ),
    "components/Unclosed.svelte": "<script>\n  export let start = 0;\n",
    "pages/odd.html": "<div <<>> </p></p><![bogus[ x ]]><!-- never closed",
    "pages/open-comment.html": (
        "<main>\n<h1>Kept</h1>\n<!-- never closed\n<nav>Hidden</nav>\n<h2>Lost</h2>\n"
    ),
    # quoted strings cut off by a line break, with the brackets around them still pairing
    "styles/cut-string.css": ':root {\n  --color-a: "#f00\n  ;\n  --color-b: #fff;\n}\n',
    "cut/tailwind.config.js": "module.exports = { theme: { colors: { red: '#f00\n } } }\n",
    "components/Cut.jsx": "export function Cut({ label = 'x\n, size }) {\n  return null\n}\n",
    "components/Cut.vue": (
        "<script setup>\nconst props = defineProps({\n  label: 'x,\n})\n</script>\n"
        "<template><p>{{ label }}</p></template>\n"
    ),
}


def test_malformed_input_yields_unparsed_units_not_exceptions(tmp_path):
    for rel, content in MALFORMED.items():
        _write(tmp_path / "bad", rel, content)
    outside = _write(tmp_path / "outside", "secret.css", ":root { --color-secret: #000; }\n")
    (tmp_path / "theme" / "styles").mkdir(parents=True)
    os.symlink(outside, tmp_path / "theme" / "styles" / "linked.css")
    units = design.decompose(tmp_path / "bad", ART) + design.decompose(tmp_path / "theme", ART)

    expected = {
        "tokens.json": "not readable as a design-token file: JSONDecodeError",
        "deep/tokens.json": "not readable as a design-token file",
        "config/settings_schema.json": "is not a JSON array of setting groups",
        "styles/binary.css": "not UTF-8 text",
        "tailwind.config.js": "never evaluated",
        "unclosed/tailwind.config.js": "the theme object cannot be read: the '{' on line 1 is never closed",
        "mismatch/tailwind.config.js": "the theme object cannot be read: the '{' on line 1 is closed by ']'",
        "styles/open-comment.css": "a /* comment on line 2 is never closed",
        "styles/unclosed.css": "the '{' on line 1 is never closed",
        "sections/broken.liquid": "is not a JSON object that can be read: JSONDecodeError",
        "sections/open.liquid": "the {% schema %} on line 2 of sections/open.liquid is never closed",
        "sections/twice.liquid": "the {% schema %} on line 5 of sections/twice.liquid is never closed",
        "pages/open-comment.html": "the <!-- comment on line 3 is never closed: nothing after it is read",
        "snippets/script.liquid": "{% javascript %} block in snippets/script.liquid is never closed",
        "components/Broken.jsx": "the parameters of Broken cannot be read: the '(' on line 1 is never closed",
        "components/Mismatch.tsx": "the parameters of Mismatch cannot be read: the '{' on line 1 is closed by ')'",
        "components/Open.vue": "defineProps cannot be read: the '{' on line 2 is never closed",
        "components/Unclosed.svelte": "the <script> on line 1 is never closed",
        "styles/linked.css": "not a regular file",
        "styles/cut-string.css": "the quoted string opened on line 2 is never closed",
        "cut/tailwind.config.js": "the quoted string opened on line 1 is never closed",
        "components/Cut.jsx": (
            "the parameters of Cut cannot be read: the quoted string opened on line 1 is never closed"
        ),
        "components/Cut.vue": "defineProps cannot be read: the quoted string opened on line 3 is never closed",
    }
    for rel, reason in expected.items():
        [unit] = _unparsed(units, rel)
        assert unit.kind == "knowledge" and unit.tags == ("design", "unparsed"), rel
        assert reason in unit.body, (rel, unit.body)
        assert len(unit.body) <= 1_000, rel                   # the reason is bounded
    spans = {
        "sections/broken.liquid": (2, 4), "sections/open.liquid": (2, 3),
        "sections/twice.liquid": (5, 6), "pages/open-comment.html": (3, 5),
        "styles/open-comment.css": (2, 3), "styles/unclosed.css": (1, 2),
        "snippets/script.liquid": (2, 3), "mismatch/tailwind.config.js": (1, 1),
        "components/Broken.jsx": (1, 1), "components/Mismatch.tsx": (1, 1),
        "components/Open.vue": (2, 4), "components/Unclosed.svelte": (1, 2),
        "styles/cut-string.css": (2, 2), "cut/tailwind.config.js": (1, 1),
        "components/Cut.jsx": (1, 2), "components/Cut.vue": (2, 4),
    }
    for rel, span in spans.items():
        assert _unparsed(units, rel)[0].location == Location(rel, *span), rel
    broken = _one(units, "sections/broken.liquid", "pattern")
    assert "Schema: lines 2-4, not readable (see its 'unparsed' unit)" in _lines(broken)
    script = _one(units, "snippets/script.liquid", "pattern")
    assert "settings.x" not in script.body                   # nothing after the open block is read

    # what cannot be parsed is not passed off as parsed: no tokens from unbalanced theme objects,
    # and a component whose signature does not close is reported rather than "none found"
    assert not [unit for unit in units if unit.location.path.endswith("tailwind.config.js")
                and unit.kind == "design_token"]
    component = _one(units, "components/Broken.jsx", "pattern")
    assert "- Broken (line 1): parameters not readable (see its 'unparsed' unit)" in _lines(component)
    assert "Components: none found" not in component.body
    assert "Not read: 1 part(s), each in an 'unparsed' unit" in _lines(component)
    assert "- Mismatch (line 1): parameters not readable (see its 'unparsed' unit)" in _lines(
        _one(units, "components/Mismatch.tsx", "pattern")
    )
    for rel in ("styles/open-comment.css", "styles/unclosed.css", "styles/cut-string.css"):
        # what could be read still is
        assert _one(units, rel, "design_token", "colour").body.startswith("1 colour token(s)")
    # a value a cut-off string runs into is not passed off as parsed
    assert "--color-a" not in _one(units, "styles/cut-string.css", "design_token").body
    cut = _one(units, "components/Cut.jsx", "pattern")
    assert "- Cut (line 1): parameters not readable (see its 'unparsed' unit)" in _lines(cut)
    assert "label" not in cut.body
    cut = _one(units, "components/Cut.vue", "pattern")
    assert "Props: none readable from the source" in _lines(cut)
    assert "'x" not in cut.body
    # a complete schema before one never closed is read, and the one never closed reported
    twice = _one(units, "sections/twice.liquid", "interface", "schema")
    assert twice.location == Location("sections/twice.liquid", 2, 4) and '"First"' in twice.body
    assert ('Schema: lines 2-4, named "First": 0 setting(s), 0 block type(s), 0 preset(s); '
            "line 5, never closed (see its 'unparsed' unit)") in _lines(
        _one(units, "sections/twice.liquid", "pattern"))
    # a comment never closed hides the rest of the page: only what precedes it is described
    page = _one(units, "pages/open-comment.html", "pattern", "page")
    lines = _lines(page)
    assert "- line 1: main" in lines and "- line 2: h1 Kept" in lines
    assert "Not read: lines 3-5, an unclosed <!-- comment (see its 'unparsed' unit)" in lines
    assert "Hidden" not in page.body and "Lost" not in page.body and "- line 4: nav" not in lines
    # the odd page ends in a comment never closed; a parser that refuses its bogus marked section
    # first reports the whole page instead: either way it is reported, never passed off as read
    [odd] = _unparsed(units, "pages/odd.html")
    if [unit for unit in units if unit.location.path == "pages/odd.html" and unit.kind == "pattern"]:
        assert "the <!-- comment on line 1 is never closed" in odd.body
        assert odd.location == Location("pages/odd.html", 1, 1)
    else:
        assert "not readable as an HTML page" in odd.body
    assert "--color-secret" not in "\n".join(unit.body for unit in units)


def test_an_apostrophe_in_prose_or_a_sass_comment_is_not_a_malformed_string(tmp_path):
    _write(tmp_path, "components/Note.jsx",
           "export function Note({ text }) {\n  return <p>Don't panic: {text}</p>\n}\n")
    _write(tmp_path, "styles/notes.scss", "// Don't inline these\n:root { --color-a: #000; }\n")
    units = design.decompose(tmp_path, ART)
    assert not [unit for unit in units if "unparsed" in unit.tags]
    assert "  - line 1: text" in _lines(_one(units, "components/Note.jsx", "pattern", "component"))
    colour = _one(units, "styles/notes.scss", "design_token", "colour")
    assert "- --color-a: #000 (line 2)" in _lines(colour)


def test_sass_and_less_line_comments_hold_no_tokens_and_no_delimiters(tmp_path):
    _write(tmp_path, "styles/commented.scss", (
        "// --color-fake: #fff;\n"
        "// a brace { and a quote ' in a comment are no code\n"
        ":root {\n"
        "  --color-real: #000; // --space-fake: 4px; }\n"
        "}\n"
        ".hero { background: url(//cdn.example.invalid/hero.png); }\n"   # // in a url() is no comment
        ".logo { background: url(https://example.invalid/logo.png); }\n"
    ))
    _write(tmp_path, "styles/commented.less", (
        "// --radius-fake: 2px; }\n"
        ".card { --radius-card: 4px; } // { never opened\n"
    ))
    units = design.decompose(tmp_path, ART)
    assert not [unit for unit in units if "unparsed" in unit.tags]
    [colour] = [unit for unit in units if unit.location.path == "styles/commented.scss"]
    assert colour.kind == "design_token" and colour.location == Location("styles/commented.scss", 4, 4)
    assert "- --color-real: #000 (line 4)" in _lines(colour)
    [radius] = [unit for unit in units if unit.location.path == "styles/commented.less"]
    assert radius.kind == "design_token" and radius.location == Location("styles/commented.less", 2, 2)
    assert "- --radius-card: 4px (line 2)" in _lines(radius)
    assert "fake" not in "\n".join(unit.body for unit in units)


def test_an_unclosed_script_or_style_is_reported_and_only_what_precedes_it_described(tmp_path):
    _write(tmp_path, "open-script.html", (
        "<html>\n<body>\n<header><h1>Kept</h1></header>\n<script>\n"
        '  var x = "<main>never read</main>";\n</body>\n</html>\n'
    ))
    _write(tmp_path, "open-style.html", (
        "<html><head><title>Styled</title>\n<style>\n  .a { color: red; }\n</head>\n"
        '<body><nav class="menu__x">Hidden</nav></body>\n'
    ))
    units = design.decompose(tmp_path, ART)

    page = _one(units, "open-script.html", "pattern", "page")
    lines = _lines(page)
    assert "- line 3: header" in lines and "- line 3: h1 Kept" in lines   # the prefix is kept
    assert "Scripts: 1 <script> element(s), not read or run" in lines
    assert "Not read: lines 4-7, an unclosed <script> (see its 'unparsed' unit)" in lines
    assert "never read" not in page.body and "- line 5: main" not in lines
    [note] = _unparsed(units, "open-script.html")
    assert note.kind == "knowledge" and note.tags == ("design", "unparsed")
    assert note.location == Location("open-script.html", 4, 7)
    assert "the <script> on line 4 is never closed" in note.body

    page = _one(units, "open-style.html", "pattern", "page")
    assert page.title == "Page open-style.html: Styled"
    assert "Not read: lines 2-5, an unclosed <style> (see its 'unparsed' unit)" in _lines(page)
    assert "Hidden" not in page.body and "menu" not in page.body and "Landmarks:" not in page.body
    [note] = _unparsed(units, "open-style.html")
    assert note.kind == "knowledge" and note.tags == ("design", "unparsed")
    assert note.location == Location("open-style.html", 2, 5)
    assert "the <style> on line 2 is never closed" in note.body
    assert units == design.decompose(tmp_path, ART)


def test_a_quoted_theme_key_is_read_like_a_bare_one(tmp_path):
    _write(tmp_path, "single/tailwind.config.js",
           "module.exports = {'theme': {'colors': {'brand': '#123456'}}}\n")
    _write(tmp_path, "double/tailwind.config.js",
           'module.exports = {"theme": {"extend": {"spacing": {"18": "4.5rem"}}}}\n')
    _write(tmp_path, "open/tailwind.config.js", "module.exports = { 'theme': { colors: { red: '#f00' \n")
    _write(tmp_path, "mismatch/tailwind.config.js",
           'module.exports = { "theme": { colors: { red: "#f00" ] } }\n')
    _write(tmp_path, "other/tailwind.config.js",
           "module.exports = { 'themes': { colors: { red: '#f00' } } }\n")
    units = design.decompose(tmp_path, ART)

    rel = "single/tailwind.config.js"
    colour = _one(units, rel, "design_token", "colour", "tailwind")
    assert colour.location == Location(rel, 1, 1)
    assert "- colors.brand: '#123456' (line 1)" in _lines(colour)
    rel = "double/tailwind.config.js"
    spacing = _one(units, rel, "design_token", "spacing", "tailwind")
    assert '- extend.spacing.18: "4.5rem" (line 1)' in _lines(spacing)
    for rel in ("single/tailwind.config.js", "double/tailwind.config.js"):
        assert _unparsed(units, rel) == []

    expected = {
        "open/tailwind.config.js": "the theme object cannot be read: the '{' on line 1 is never closed",
        "mismatch/tailwind.config.js": "the theme object cannot be read: the '{' on line 1 is closed by ']'",
        "other/tailwind.config.js": "no literal theme object to read",
    }
    for rel, reason in expected.items():
        [unit] = _unparsed(units, rel)
        assert unit.kind == "knowledge" and reason in unit.body, (rel, unit.body)
        assert not [token for token in units
                    if token.location.path == rel and token.kind == "design_token"]


def test_an_artifact_that_is_not_a_directory_is_reported(tmp_path):
    for root in (tmp_path / "missing", _write(tmp_path, "file.css", ":root {}\n")):
        [unit] = design.decompose(root, ART)
        assert unit.kind == "knowledge" and "unparsed" in unit.tags
        assert unit.location == Location(".")


def test_arbitrary_and_truncated_text_never_raises(tmp_path):
    rng = random.Random(7)
    alphabet = "{}[]()<>\"'`/*:;,.-_=$#%@!?\\| \n\tabcAZ09"
    names = list(FIXTURES) + ["assets/theme.css.liquid", "tokens/x.tokens"]
    for round_ in range(4):
        root = tmp_path / f"noise-{round_}"
        for rel in names:
            _write(root, rel, "".join(rng.choice(alphabet) for _ in range(3000)))
        cut = tmp_path / f"cut-{round_}"
        for rel, content in FIXTURES.items():
            _write(cut, rel, content[: rng.randrange(len(content) + 1)])
        for folder in (root, cut):
            units = design.decompose(folder, ART)
            assert units == design.decompose(folder, ART)
            Artifact(source=SOURCE, kinds=("theme",), units=tuple(units))
            assert all(len(unit.body) <= MAX_BODY for unit in units)
