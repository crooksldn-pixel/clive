# Venture Engine V1

**Status:** CANDIDATE — repository-only, first increment on `claude/venture-engine-v1-2026-09-29`; not independently reviewed, not accepted, not landed, not deployed.
**Owner intent:** the owner's words of 29 September 2026, recorded verbatim in [OWNER_DECISIONS_2026-09-29.md](./OWNER_DECISIONS_2026-09-29.md) and joined to the log as DEC-061.
**Scope of this increment:** a deterministic, read-only planning core in `crooks-assistant/app/ventures/`, its tests, three illustrative candidates and a command line. Nothing in CLIVE calls it.
**Builds on:** the 2026-09-29 research (thirteen tracks) and plan: `reports/AI dropshipping business generator plan.md` and `research_notes/AI dropshipping business generator plan/` on `crooksldn-pixel/AGENT-ENVIRONMENT`, branch `claude/clive-agent-environment-8dbjjx`.
**Serves:** the owner's attention (one decision package in place of research by hand) and the safety and provenance that make it trustworthy (the rules are code, and every owner gate is named).

This document authorises no deployment, no spend, no store, listing or post, no message to anyone, no new credential or connector, and no change to a protected path.

## 1. What the owner asked for

A button that produces and runs whole product businesses of the kind the owner pointed to: research what is selling and which content spreads and which flops, choose the products and suppliers, build the store, set the prices, make the videos (ElevenLabs or another method), decide exactly when and how to post and publish on every platform, market and advertise at the right times, handle all customer support, and manage the company end to end, "with relatively little to zero human involvement". The owner's three examples were researched: "roosddflare" is RoadFlare, a one-product store for a flint plate that makes riding boots throw sparks; "babyrideshop" is most probably BabyRide, which sells lie-flat baby car beds; "rooog.co" does not resolve: DNS reports no such domain, and the registry could not be checked.

## 2. What the research found that shapes the engine

- **Median advertising loses money.** Triple Whale's median Meta ecommerce results for August 2025 to July 2026 are a ROAS of 1.88 and $38.99 per purchase. A typical China-sourced product priced at 2.5 to 3 times its cost breaks even at a ROAS of about 2.1 in the US, 2.6 in the UK (VAT-registered) and 3.8 in the EU after the new per-item duties. Profit comes only from the rare product and creative pairs well above the median, so the engine is a testing machine that kills most tests fast by fixed rules.
- **A human is unavoidable at identity and money.** A UK company needs an identity-verified natural-person director; Shopify Payments, the bank and every ad account verify a person; the platforms forbid automated account creation, and a ban follows the person across every brand. So the engine runs a few durable brands under one verified owner and never farms accounts.
- **Publishing is gated.** TikTok's posting API keeps unaudited apps private and asks a person to confirm each post; YouTube keeps unaudited uploads private; Instagram allows 100 API posts a day. Every platform demotes reposted and templated content.
- **Truth is a legal line.** An AI presenter may demonstrate a product, but an AI "customer" is a fake testimonial (FTC rule 16 CFR 465; the UK DMCC Act). EU AI Act Article 50 labelling applies from 2 August 2026. Delivery promises fall under the FTC Mail Order Rule.
- **The owner's examples sit in regulated categories.** Baby car beds are child restraints; children's costumes need flammability testing (the UK regulator found over 80% of 128 children's Halloween costumes failing); US children's products need a certificate that has been filed at entry since 8 July 2026; nothing regulates boots that throw sparks, which is itself the risk.
- **CLIVE's doctrine already fits.** Models propose and deterministic capabilities execute under the owner's authority. The research's reconciliation of "zero human involvement" with that doctrine is: the button produces a decision package, and autonomy is measured by how rarely the owner must step in while agents work inside a spending mandate the owner granted. Mandates are a later increment and a separate owner decision (section 6).

## 3. This increment: the planning core

`crooks-assistant/app/ventures/`, standard library only:

| Module | What it does |
|---|---|
| `markets` | Market codes (UK, UK-NOVAT, US, EU-DE, EU-FR, EU-ES, EU-IT, EU-NL, EU-IE): currency and how VAT sits in the shown price. |
| `economics` | One order taken apart: contribution before advertising, break-even ROAS and cost per purchase, and the price floor. Money is Decimal; floats are refused; no cost has a default. |
| `pricing` | Price presentation from the floor (a .99 ending or a round price), the free-shipping threshold (1.3 to 1.5 times the median order), and reference-price checks. |
| `rules` | Kill and scale rules for creative concepts and whole products, from Poisson arithmetic. |
| `scoring` | Product score and lifecycle stage from market and early test signals. |
| `compliance` | The category screen: BLOCK, OWNER or CLEAR, before any score. |
| `seasons` | Retail dates by market, computed from their rules; supplier slowdowns; launch timing. |
| `brief` | One candidate in, one decision package out, as readable text or JSON (`clive.venture_brief.v1`). |
| `__main__` | `python -m app.ventures brief CANDIDATE.json` and `python -m app.ventures dates --market UK`. |

The rules it applies:

- **Price floor.** With the tax in the shown price `t`, the order must pay the target cost per purchase `A` and keep the target margin `m` of net revenue: net price at least `(fixed costs per order + A) / (1 - (card fee + commission) x (1 + t) - returns allowance - m)`. With no tax in the price this is the research formula. The floor is rounded up to the cent; a cheap item needs a higher multiple of its cost than a dear one.
- **Reference prices.** In the EU the prior price shown with a reduction must be the lowest price of the previous 30 days, and the reduction is measured from it (Omnibus Directive; CJEU, Aldi Süd, 26 September 2024); a product not on sale for 30 days shows no reduction. In the UK and US the engine's own conservative default applies: the reference price must have been the price on each of the 28 days before the sale and on at least half of the 90 days before it. That default is the engine's rule, not the law, and is tunable. The engine needs its own price ledger, because Shopify sends no notification when a price list changes.
- **Kill.** A concept is killed at 3 times the target cost per purchase with no purchase (a concept that was on target is killed this way 5% of the time), at 5 times with at most one (4%), or when even the optimistic end of its true cost per purchase is above the target. The common "kill at 1 to 2 times" rule would kill 14 to 37% of concepts that were on target.
- **Scale.** At 20 purchases at or under the target; below 20 only at or under 0.6 times the target, and from at least 5 purchases (that floor is the engine's assumption). Twenty purchases still leave the true cost per purchase between about 0.65 and 1.64 times the observed figure.
- **Product.** Stopped after 3 genuinely different concepts fail, or once 12 times the target cost per purchase is spent and it still loses money.
- **Score.** Demand momentum, economics, one minus saturation and validation, as a geometric mean on a 0 to 100 scale, less a weighted risk. A missing signal scores below the middle and is listed; blocked products are excluded; the owner sees at most five. Every threshold is a starting prior to recalibrate from the engine's own results.
- **Compliance.** Blocked outright: child restraints; weapons; spark devices for children; US children's products without a Children's Product Certificate and CPSC-accepted lab reports; UK and EU children's toys and costumes without marking and EN 71; children's costumes without flammability reports; hood or neck drawstrings on children's clothing; US button-cell products without Reese's Law evidence; lithium batteries without a UN 38.3 summary; EU sales without a responsible person and GPSR safety information; licensed characters without a licence; "dupe", "replica", "knock-off" and "inspired by" wording. To the owner, default reject: adult spark devices, carriers, ride-ons, and categories the screen does not cover (cosmetics, supplements, food, medical claims, mains electrical). CLEAR is not legal clearance.
- **Timing.** The last customer order is the event less the slow end of delivery and a 3-day ordering buffer; scaling starts 14 days before that and testing 10 days before scaling. Golden Week and a Spring Festival window from ten days before to twenty days after Chinese New Year are flagged (the window's width is the engine's assumption). As of 29 September 2026, China-direct Halloween is already too late; Christmas is reachable if testing starts by early November.
- **Brief.** Verdicts are BLOCKED, NOT_VIABLE, NEEDS_OWNER or READY_TO_PROPOSE. Each brief states what an order would make or lose at the median ROAS of 1.88, and ends with what the owner would be asked to decide, in CLIVE's decision kinds (SAFETY, PRODUCT_DIRECTION). The asks are text; nothing executes.

Evidence: `tests/test_ventures_*.py` (economics, pricing, rules, scoring, compliance, seasons, brief and command line, boundary), 132 tests, with the three candidates in `tests/fixtures/ventures/`. Their figures are illustrative, not quotes.

## 4. Authority

- **Read-only by construction.** `tests/test_ventures_boundary.py` proves from the source that the package imports only the standard library and itself, opens no socket or process, writes no file and runs no dynamic code, and that only the command line reads a file (the one it is handed).
- **Not reachable by the model.** No venture tool is in the gate's list and nothing else in `app/` imports the package; the same test fails if either changes.
- **No authority is created.** The brief's asks are words for the owner. DEC-005, DEC-007, DEC-008 and DEC-027 apply unchanged.

## 5. Proposed: exposing the planning core to CLIVE's model

This is the owner's change to make, because it edits protected files. It is written here so it can be made exactly:

1. A new auto-loaded module `app/families/ventures.py` registering two read tools with a capability family (key `ventures`, state READY): `venture_brief` (a candidate object in; the brief as data out) and `venture_dates` (a market and a number of `days`, which the gate already bounds to 1 to 365). Neither name contains a mutation verb, and neither uses the `commerce_` prefix, which has its own byte budget.
2. `app/tools/gate.py`: add both names to `_KNOWN_TOOLS` (protected).
3. `tests/test_gate.py`: the known-tool count goes from 44 to 46 (protected).
4. `tests/test_registry.py`: raise the tool-description byte ceiling by the measured amount; about 22 bytes of headroom remain today.
5. `web/app.js` `DETAIL_WORDS`: `venture_brief: ['Preparing', 'a venture brief'],` and `venture_dates: ['Checking', 'the retail calendar'],`.
6. Regenerate `docs/phase4/TOOL_MATRIX.md` (`make tool-matrix`) and add a usage line in `app/kb/loader.py`.
7. `tests/test_ventures_boundary.py`: replace the not-reachable assertion with one that names the two tools.

Two known interactions: "what price should I set" matches the price-change limitation in `app/observability/contract.py` and would tell the model the Mac cannot change a price, so the tool description must say that a venture brief changes no price; and every typed or spoken request stays a model turn (OWNER_DECISIONS_2026-09-28), so nothing routes venture questions by keyword. Recommended order: independent exact-SHA review of this increment first, then the exposure as its own change.

## 6. Later increments, each its own owner decision

1. **Research connectors (read-only).** Licensed data only: TikTok Shop analytics APIs (FastMoss, EchoTik), Keepa for Amazon history, Pinterest Trends, Google Merchant best sellers, the CJdropshipping catalogue and freight API. No scraping; Meta's terms forbid automated collection without written permission. New keys and data leaving the host are owner-gated.
2. **Store building on development stores.** Shopify CLI 4.8 scripts development stores (up to 250 per organisation, password-protected, no real payments); theme code lives in git and goes through the normal review; going live is the owner's DEPLOYMENT decision, and Shopify requires the owner to accept a transferred store and verify payments personally.
3. **Content pipeline.** A truth pack from a physical sample (specifications, reference photos, real clips); every claim traced to it; ElevenLabs for voice, music and effects; video models behind an adapter chosen by product fidelity (OpenAI switched off the Sora 2 API on 24 September 2026); logos and prices added in the edit, not generated; AI content labelled; AI presenters never pose as customers; automated quality checks with human review of flagged items.
4. **Mandates.** Structured spend on owner decisions; standing, capped, expiring, revocable mandates; a budget ledger in the owner's currency; a global and per-venture kill switch; decisions that expire to no spend; live, test and simulated labels. Enforced in code and at the card issuer (virtual cards with limits), as an owner-gated action class on the action engine. No agent resolves an owner decision (Anthropic's Project Vend: an agent shopkeeper priced below cost, invented a payment account and approved discounts far more often than it refused them).
5. **Publishing and advertising.** Audited apps, TikTok's business-account endpoint or an already-approved posting service; campaigns built paused; pausing and cutting spend automatic, activating or raising spend only inside a mandate.
6. **Support and back office.** An AI agent that says it is one, answers from order data, refunds by rule under a cap and escalates a fixed list (safety, legal threats, large refunds, data requests, a request for a person); CJ disputes by API, AliExpress disputes by a person; chargeback evidence by API; bookkeeping and VAT through Xero and Making Tax Digital.

Always the owner's: the one-time genesis (director identity, bank and payment KYC, owning the platform accounts, the spending envelope), HMRC re-authorisation at least every 18 months, annual sign-offs, inspecting samples, and exceptions.

## 7. Open owner rulings

1. Where this work sits against F0 (finish first) and the approved next phase.
2. Whether and when to expose the planning core to the model (section 5).
3. Market and category policy for the first businesses. The research recommends UK customers and adult, unregulated, visually demonstrable products first, with baby and children's categories off by default.
4. Whether the ventures run apart from CROOKS LDN (their own company, brands and accounts), given that platform bans follow the person.
5. The form of "zero human involvement": the research recommends one genesis session and standing mandates (section 6.4).

## 8. Not yet verified

The research ran with most web pages blocked and a spent search allowance, so these rest on summaries and need checking before the increments that depend on them: the single-source report that TikTok Shop US bars international suppliers; the platforms' current restricted-product lists; any controlled comparison of labelled AI creative against human UGC; the exact wording of several regulators' pages; UK VAT registration details; and the supplier-slowdown window. The candidates' figures in the tests are illustrative.
