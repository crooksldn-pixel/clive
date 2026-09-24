# Generative UI V1

**Status:** APPROVED by the owner on 2026-09-24. Implementation proceeds through the remote engineering loop after the operational-alpha repair lands.
**Scope:** how CLIVE decides what appears on screen, for any connected capability, present or future.
**Doctrine:** PRODUCT_BRAIN 3.6, CLIVE_INTENT_TO_EXECUTION_PHILOSOPHY 7-8 and 14, CLIVE_IDENTITY_AND_HOME_SURFACE 3-7, CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI 5.

## 1. The rule

> Connectors describe data. CLIVE decides what to show. The screen shows findings, not sources.

CLIVE is the single entity doing the work. Shopify, Gmail, a courier, an ads platform or any future connection are tools CLIVE uses, never the shape of the interface. A new connection must become useful on screen without anyone writing interface code for it.

## 2. Evidence that motivated this

On 2026-09-24 the owner asked the live runtime "any customers who need a reply", twice.

- The first answer was one true sentence (nobody needed a reply), but the screen drew five cards and more than forty rows: a who-has-written table, cross-reference counts, revenue figures, all-time totals and a ranked list of twenty-five customers with their email addresses. None of it answered the question, and it exposed customer personal data without need.
- The second answer interpreted the same words as fulfilment ("5 orders to go out") and drew an order list.
- Settings exposed engineering diagnostics and stale wording ("the Mac is still reading Shopify", "needs a logged-in Mac") on a server runtime.

Cause: `app/presentation.py` maps tool results to about thirty-five fixed, provider-shaped card types, so whatever an investigation touches is drawn, and every new connector would need new card types. The interpretation failure belongs to Support Investigator / Derived Truth and is not fixed by this spec; this spec makes sure whatever is concluded is shown with discipline.

## 3. Architecture

**Layer 1 - evidence, connector-agnostic.** Every tool result is normalised into typed evidence: records whose fields declare their meaning (money with currency, count, ratio, date/time, duration, status, person, link, text, time series), with provenance (source, observed at, query). A connector registers a field descriptor for its outputs; no UI code. Existing Shopify, Gmail and analytics outputs get descriptors first.

**Layer 2 - significance.** Reuse Derived Truth + Attention: findings carry ACTION_REQUIRED, DECISION_REQUIRED, RISK, UNCERTAINTY, LIMITATION or CONTEXT. Only findings that answer the request or earn attention compete for space.

**Layer 3 - scene compiler.** The model proposes a scene plan in a strict schema from a closed set of semantic primitives:

- Answer - the headline, one or two lines;
- Finding - one significant result, with its evidence one tap away;
- Entity - one thing (an order, a customer, a campaign), fields chosen by relevance;
- Collection - a list or table, columns chosen by relevance, bounded rows;
- Measure - a number that matters, with its unit and period;
- Comparison, Trend (series), Timeline;
- Proposal - an action under the existing proposal/authority/verification rules;
- Question - a clarification CLIVE genuinely needs.

The plan references evidence handles only. It cannot invent values, markup or code. The server validates and enforces:

- every rendered value is bound to evidence returned this session;
- every element justifies its place by answering the request or carrying a finding;
- an attention budget per scene (default: one Answer plus at most three further elements; more only when the request asks to see a set);
- role/privacy scope (no customer contact details unless the task needs them);
- a recorded decision trace: why each element is present, for evaluation.

If planning fails, the scene degrades to the Answer alone. Render identity and patch semantics from `app/render.py` are kept so scenes update in place as evidence settles.

**Empty is correct.** When nothing needs the owner, the scene is one line, for example: "No one's waiting on a reply - 31 inbox threads and 5 outgoing orders checked." The checked evidence opens only on request.

**A new connection.** Connect an ads platform and ask "how are the ads doing": its campaign fields self-describe (spend is money, ROAS is a ratio, daily spend is a series), so the scene is an Answer plus one Finding for the losing campaign, with no platform-specific screen.

## 4. Chrome, density and settings

- Persistent chrome is minimal. No permanent Back / Previous / Next strip, no provider or service status in the header; health appears only in context of the current objective. The orb is presence, not a large microphone button.
- Density: fewer elements with more value, clear type hierarchy, generous spacing; never fill space to occupy it. CLIVE should read as the most premium AI work surface, not a dashboard.
- Settings are user-facing: voice, what CLIVE may do on the owner's behalf, who and what CLIVE can reach, what it has learned and what it needs from the owner. Engineering diagnostics move behind a developer view. No runtime-host wording (Mac, launchd, CLI login) reaches the owner.
- Microphone: request permission only on the first hold-to-speak, reuse one stream for the session, never prompt on load.

## 5. Capability gaps become work, not logs

When CLIVE cannot complete an objective, it classifies the gap (missing capability or integration, missing evidence, insufficient authority, ambiguity, physical-world step, unavailable participant, safety boundary). Where a repository-only capability would close it, CLIVE drafts an engineering objective, links it to the originating objective, and asks the owner once to submit it to the engineering loop. The loop builds, checks and independently reviews it; credentials, new connector grants, spend and deployment remain owner-gated. When the capability lands, CLIVE resumes or offers the original objective.

Example: support needs courier-movement evidence and only fulfilment records exist. CLIVE proposes building a tracking reader for the existing shipping provider; the owner's step is the credential, not the engineering.

This bridge is delivered as its own objective track (capability-gap-bridge-v1) after the core scene work.

## 6. Acceptance

- The two 2026-09-24 "any customers who need a reply" cases render as one Answer plus drill-down, with no unrelated cards and no customer contact details.
- A "nothing needs you" case renders one line.
- The same words under different hidden contexts produce different, appropriate scenes; different words for the same objective produce equivalent scenes.
- A synthetic connector with no interface code renders useful scenes from its field descriptor alone.
- Every rendered value traces to evidence; the decision trace explains every element; the budget and privacy rules hold under adversarial plans.
- Blind comparison against the current cards on recorded real sessions favours the new scenes before any old card type is retired.

## 7. Delivery

Objectives, each an exact-SHA independently reviewed candidate, in order:

1. evidence model, descriptors for existing tools, scene schema, server validator and decision trace;
2. general scene renderer, reduced chrome and user-facing settings, microphone fix;
3. planner integration, fallback and the evaluation set above;
4. capability-gap bridge V1.

Production promotion stays a separate owner-authorised step. Old card types are retired, not preserved, once the evaluation gate is passed.

## 7.1 Non-goals

Model-generated markup or code, model-invented values, new business writes, new connectors.
