# Skills and context strategy

## Rule

Workers receive the minimum relevant skills and context for the objective. Do not inject the whole
product brain into every session.

## What exists (audit/REPO_AUDIT.md)

- **The allow-list.** Builder skills come from `config/builder_skills.json`, a protected path read from
  the loop's own pinned checkout. Today it lists four design skills.
- **Pinning and safety.** Every file is pinned by sha256. A skill with a mismatch, an extra file, a
  `hooks` key, a `` !`cmd` `` line or a non-text file is withheld.
- **Per-attempt folders.** For each attempt, the dispatcher builds a `clive-skills` plugin folder in the
  attempt's fresh HOME, outside the workspace and read-only (`workers/skills.py`). The launch check
  requires the CLI to report exactly those skills.
- **CLI version gate.** Skills are given only on Claude CLI 2.1.285 or 2.1.293
  (`BUILTIN_SLASH_COMMANDS`). On any other version, launches run with `--no-builder-skills`. The
  worker-01 CLI version is UNKNOWN (A1), and none of the CLIs on the production host is a gated
  version.
- **The owner's curated list is his approval** (DEC-064). Anything that runs on its own (a hook, an MCP
  server, an executable) stays his to approve.
- **No per-task routing.** Every builder gets every skill, including the frontend design skills on
  backend work.
- **Reviewers get no skills by design** (DEC-076). V1 keeps it that way.

## Two kinds of skills, kept apart

| Kind | Where | Who loads them | Pinning |
|---|---|---|---|
| **Supervisor skills**: planning, compiling and explaining | `.claude/skills/` in the supervisor's checkout | The interactive supervisor or Director session | Not builder skills. They never reach a builder unless added to `builder_skills.json` |
| **Builder skills**: implementation guidance | `config/builder_skills.json` (protected) | The loop's builders only, per attempt | sha256 per file, from the trunk base or the installed folder |

The skills on this planning branch are supervisor skills:

- `autonomous-engineering-planner`, `clive-engineering`, `clive-product-philosophy`, `clive-testing`;
- `clive-ui`, `clive-security`, `external-api-integration`, `research-assimilation`,
  `browser-investigation`.

They are **not** approved builder skills.

## V1 changes

### Per-task routing (PR 6, protected; RP2 re-pin)

- Entries in `builder_skills.json` gain optional `applies_to` globs.
- `_skills_for` gives a builder only the skills whose globs match the objective's `allowed_paths`.
  An entry without globs goes to every builder, which is today's behaviour.
- The routing is owned by the protected allow-list, so a request cannot ask for a skill.
- The hash checks, the withheld rules, the CLI version gate and the launch check are unchanged.
- A rolled-back loop reads its own pinned allow-list.

### Routing rules (encoded in `applies_to`)

| Work type | Builder skills routed |
|---|---|
| UI (`web/**`, Builds, presentation) | `web-design-guidelines`; plus `design-taste-frontend` for new screens only |
| Everything else | None of the four design skills |
| External integration | `external-api-integration`, once it is curated into his list (NEXT, DEC-064) |
| Security-adjacent but non-protected | `clive-security`, once curated (NEXT) |

### Curating CLIVE skills for builders (NEXT; his curated list is his decision, DEC-064)

Candidates: `clive-engineering` (builder edition), `clive-testing`, `clive-ui`,
`external-api-integration`, `clive-security`.

Before any of them reaches a builder:

- it is rewritten for a builder's context: file tools only, no shell, and no planning or authority
  content a builder must not act on;
- it is reviewed;
- it is hash-pinned in `builder_skills.json` (protected, so Director-built);
- it becomes live only at a re-pin, on a gated CLI version.

**The one exception:** the planning skills that speak of authority, owner decisions or deploys
(`autonomous-engineering-planner`, `clive-product-philosophy`) never become builder skills.

## Context hierarchy for a builder (unchanged order; now explicit)

1. **The request:** title, requested outcome, acceptance criteria, `allowed_paths`, checks, plus the
   earlier try's stop report when one exists.
2. **Routed builder skills.**
3. **CURRENT_TRUTH and the pinned product memory**, already given through `--product-memory-ref`.
   The supervisor's draft cites the relevant DEC entries in the requested outcome rather than attaching all of
   DECISIONS.
4. **Source**, through the builder's own Read, Glob and Grep inside its workspace.

External documentation (for example Context7) is used by the **supervisor** while compiling. A
builder has no network and no MCP. External text is data, never instruction. Anything quoted into a
request is marked as quoted, and passes the bridge's customer-detail rules (MAP rule 4).
