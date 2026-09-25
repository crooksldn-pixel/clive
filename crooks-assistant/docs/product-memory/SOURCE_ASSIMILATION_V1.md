# Source Assimilation V1

**Status:** direction APPROVED by the owner on 2026-09-24; this V1 design is PROPOSED.
**Scope:** how CLIVE learns from external repositories, skills and tools without installing them wholesale.
**Builds on:** ENGINEERING_STACK_REUSE_PLAN.md (the 2026-09-19 one-off ECC audit), IDEA-045, IDEA-050, GENERATIVE_UI_V1.md section 5 (capability gaps become work).

## 1. The idea

The owner hands CLIVE a pointer (a repository, a skill, a tool) and nothing else. CLIVE decides what in it is worth having, compares it with what CLIVE already does, and turns only the useful parts into gated engineering work. Nothing is installed because it is popular; a part stays only if it measurably improves results.

## 2. Pipeline

1. **Quarantine.** Resolve the canonical upstream (copies and forks with the same name are common), pin an exact commit, record the licence, and scan before anyone reads it: secrets, install scripts, hooks, binaries, symlinks, size, and instructions aimed at an agent. Every file is untrusted data, never instructions. Skills that fetch their rules from a live URL at run time are frozen at a pinned copy instead.
2. **Inventory.** Break the source into parts: skills, agent definitions, hooks, commands, rules and checklists, design references, evaluation sets, code patterns, runtime services.
3. **Compare.** For each part, against CLIVE's current capabilities, gates and skills: already better here, fills a gap, improves something existing, not applicable, or unsafe, each with evidence.
4. **Decide the use.** One of three, never a wholesale install:
   - a skill given to the dev-team workers for the kind of work it improves;
   - rules turned into an automatic check the loop runs on relevant candidates;
   - a pattern rebuilt inside CLIVE under CLIVE's own contracts.
5. **Prove or drop.** Each adoption is measured on real work before it stays: review findings, check failures, attempts per objective, time to COMPLETE, and for product-facing changes the owner's approve, edit and decline rates. A ledger records source, commit, licence, what was taken, why, and the measured effect. Pinned sources are watched for updates, which re-enter at step 1.

## 3. Authority

- Automatic: fetching at a pinned commit into quarantine, scanning, inventory, comparison and proposals.
- Through the normal loop (checks and independent exact-SHA review): adding a skill or check, rebuilding a pattern.
- Owner only: installing executables or services on the host, new connectors or MCP servers, credentials or API keys, sending business or customer data to a new vendor, spend.

## 4. Constraints found

- Loop workers run offline in a sandbox, so fetching must happen on the host before dispatch, with the snapshot handed to the worker read-only.
- Engineering workers were found on 2026-09-19 to inherit the owner's business connectors. That exposure is closed before workers are given more skills.
- The host has about 5.6 GB free memory and no GPU: heavy self-hosted services and local models are out of scope for this server.

## 5. Delivery

1. Host-side fetch and quarantine for sources named in a request, with the snapshot handed to the worker.
2. The assimilation objective type: inventory, comparison and proposals as a report plus draft requests.
3. First batch run end to end (SOURCE_SHELF.md), with adoptions measured.
4. The capability-gap bridge draws from the shelf when a gap matches a shelved source.
