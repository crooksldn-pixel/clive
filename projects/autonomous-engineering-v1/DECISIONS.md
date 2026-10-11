# Planning decisions

These are project-planning decisions only. They do not amend CLIVE's canonical DECISIONS.md until implementation is approved and recorded through the normal product-memory process.

## P-001 — Desktop is supervisor, not durable worker
Claude Desktop over SSH is the interactive control surface. Durable execution belongs to CLIVE's existing engineering control plane.

## P-002 — reuse before replace
Dispatcher, workspaces, reviewers, checks, engineering bridge, Builds and Bench are presumed valuable until evidence proves otherwise.

## P-003 — no automatic production deploy
Engineering autonomy may reach accepted/trunk state under existing authority. Production deployment remains owner-triggered.

## P-004 — no agent swarm by default
Start with supervisor, builder, verifier when required and independent reviewer.

## P-005 — measured concurrency
Increase concurrency only after baseline/resource/quality evidence.

## P-006 — CLI before engineering MCP
V1 prefers a small deterministic supervisor CLI/control interface. Build an MCP later only if measured friction justifies it.

## P-007 — selective skills/context
Workers receive task-relevant context and skills, not the full product brain by default.

## P-008 — evidence-backed completion
A model statement is never sufficient proof of completion.

## Open owner decisions after audit
- long-term worker topology if current hosts differ from documentation;
- hard OAMAB threshold after a real baseline;
- whether selected S4 work requires heterogeneous dual review;
- whether any low-risk accepted work may land without a separate gesture beyond project approval under existing authority rules.
