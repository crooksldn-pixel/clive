# Later candidates — researched, deliberately NOT installed

Phase 10 of the 2026-09-19 builder brief. Nothing in this file is installed. It exists so the
options are recorded with a reason rather than rediscovered.

The standing rules this file obeys: do not install full gstack, do not install any third-party
deploy/ship automation — CROOKS has its own deployment gates and a planned GPT↔Claude hierarchy —
and do not bulk-install skill registries.

| Candidate | Worth it later? | Reasoning |
|---|---|---|
| **Emil Kowalski motion/design skills** | Low priority | CROOKS motion is already a small, deliberate, documented system (`DESIGN.md` §10): three durations, four easings, motion as feedback only, and `prefers-reduced-motion` honoured in eight places. The product's constraint is a Galaxy Tab A 8.0, so the useful direction is *less* motion, not a richer vocabulary. |
| **UI UX Pro Max** | **No** | Explicitly excluded by the brief. A broad generic-aesthetic pack is the exact thing `DESIGN.md` §0 exists to keep out of CROOKS product screens. |
| **gstack — selected concepts only** | **Concepts yes, package no** | Do not install gstack. The *ideas* worth stealing are `investigate`, `QA`, `review` and `design-review`, and they map onto `DEC-013` (implementers do not solely review themselves). Implement them as CROOKS's own specialist-agent slots — see `CLAUDE_PROJECT_LAYOUT.md` §5 — rather than importing someone's framework. |
| **Lighthouse CI** | **Maybe — but measure the right thing** | Lighthouse scores a public web page. CROOKS is a loopback PWA on a private Tailscale network with a fixture world, and its real performance question is "does this render acceptably on a 2015 8-inch tablet", which Lighthouse's synthetic throttling does not answer. A physical-device timing capture would be worth more. Revisit if a public surface ever appears. |
| **Shopify CLI + Theme Check** | **Yes, for the theme side** | The repository root *is* a Shopify theme (`sections/`, `snippets/`, `templates/`, and a `.theme-check.yml` already exists). Theme Check is directly applicable and currently unused. It is out of scope for a round about the assistant's UI, but it is the clearest unclaimed win here. |
| **Semgrep / additional SAST** | **Moderate** | Would overlap SkillSpector (which already bundles Semgrep-adjacent static analyzers) and Trivy. The gap it would close is CROOKS's *own* Python — particularly the action/verification path. Worth it only with a curated ruleset; a default ruleset on a 2800-test codebase produces noise nobody reads, which is the same trap `DEV_ENVIRONMENT.md` §4.1 describes for Biome. |
| **Load testing** | **No, not yet** | Single-owner, single-tablet, loopback. There is no load. Revisit at the subscriber product (`PRODUCT_BRAIN.md` §7). |
| **Python profiling** | **Yes, cheap** | `cProfile`/`py-spy` on the fast lane would directly serve the "low latency" requirement in `PRODUCT_BRAIN.md` §4.1. `py-spy` needs no code change and can sample a running process. Low cost, high relevance. |
| **Disposable container sandboxing for autonomous workers** | **Yes — but it is blocked** | Directly serves `DEC-011` and `DEC-012`. **Cannot be done in the current sandbox:** `/usr` is read-only, so no container runtime can be installed, and installing one is an owner decision about the host regardless. Record as an owner-approval item. |
| **Code-intelligence / LSP tooling** | **Partly already present** | The locally cloned `claude-plugins-official` marketplace already carries `pyright-lsp` and `typescript-lsp` plugins. `ast-grep` 0.40.0 is installed and covers structural search/refactor, which was the main gap. A full LSP server is worth revisiting only if navigation proves to be the bottleneck. |
| **GitHub App** | **Owner decision** | Would replace the bridge's current mechanics and needs credentials and an outward-facing configuration. Not a builder decision. |
| **Privileged Action Broker** | **Product work, not tooling** | This is CROOKS architecture (the capability/authorisation path), not a development tool, and belongs on the roadmap rather than in this environment. |

## Ranked, if only three things happen next

1. **Shopify Theme Check** — already configured (`.theme-check.yml`), currently unused, and the
   theme half of this repository has no linting at all.
2. **`py-spy` profiling of the fast lane** — cheap, no code change, serves a stated product goal.
3. **Semgrep with a hand-picked ruleset over the action/verification path** — narrow enough to
   stay signal, aimed at the code where a defect is most expensive.
