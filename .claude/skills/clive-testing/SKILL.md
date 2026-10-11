---
name: clive-testing
description: Apply CLIVE's layered evidence model: focused tests, integration, browser, Bench, exact-SHA acceptance and independent review.
---

# CLIVE Testing

Principles:
- run focused tests for fast feedback;
- final acceptance refers to the exact candidate SHA;
- tests and reviewer answer different questions;
- UI behavior needs browser evidence;
- assistant/tool/presentation behavior may need Bench;
- security/permission changes need targeted negative tests;
- a builder never certifies its own candidate;
- failed evidence is carried into bounded repair;
- selective tests may optimize feedback but never silently replace required final gates.

Before adding a new harness inspect existing tests, acceptance.yml, orchestrator check sandbox, Bench and browser setup. Prefer extending existing evidence paths.
