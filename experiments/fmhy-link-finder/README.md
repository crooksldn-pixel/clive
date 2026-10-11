# FMHY public title-page finder — experiment

Branch-only proof of concept. Nothing in this directory is part of CLIVE production.

## Goal

Given a movie/TV title and optional year, search one or more ordinary public catalogue/search pages,
match the correct result and return its public title-page URL.

The experiment deliberately stops before media/player delivery.

## Start here

Claude:
1. read `PROMPT.md`;
2. read `ACCEPTANCE.md`;
3. read `REFERENCES.md`;
4. load the `fmhy-link-finder` skill;
5. use the custom discovery/builder/verifier/reviewer agents.

The branch also provides project-scoped Context7 and Playwright MCP servers through root
`.mcp.json`.

## Build status

Bootstrap package only. Implementation has intentionally not been written yet.

The first implementation task is to run discovery, choose one simple public search target, then
build one adapter end-to-end before adding anything else.
