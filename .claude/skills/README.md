# Vendored design skills

Pinned copies of upstream skills, committed to this repository on purpose.

## Why they are in the repository rather than installed

CROOKS OS is built in throwaway containers. An account-level or machine-level skill install does
not survive one — that is the concrete failure this directory exists to fix: the skills were
installed on the owner's Mac and the build container could not see them, so the design work had
nothing to work with. A skill the build cannot see is a skill the build does not have.

Vendoring means checking the repository out is enough.

`.gitignore` still excludes the rest of `.claude/` (the agent worktrees, which are checkouts of
this repository living inside it). The rule had to become `.claude/*` rather than `.claude/` for
the negation to work at all: **git cannot re-include anything beneath a directory it has
excluded outright**, so `!.claude/skills/` under a bare `.claude/` silently does nothing.

## What is here, and where each came from

Every `SKILL.md` is **byte-identical to upstream** — verified with `diff` at install time.
Nothing was rewritten, summarised or adapted.

| directory | YAML `name:` | upstream |
|---|---|---|
| `design-taste-frontend/` | `design-taste-frontend` | `Leonxlnx/taste-skill` → `skills/taste-skill/SKILL.md` |
| `high-end-visual-design/` | `high-end-visual-design` | `Leonxlnx/taste-skill` → `skills/soft-skill/SKILL.md` |
| `image-to-code/` | `image-to-code` | `Leonxlnx/taste-skill` → `skills/image-to-code-skill/SKILL.md` |
| `web-design-guidelines/` | `web-design-guidelines` | `vercel-labs/agent-skills` → `skills/web-design-guidelines/SKILL.md` |

Pinned at:

```
Leonxlnx/taste-skill        ccbc15639c97057cbfcf32ecebc38ef716e4bb37
vercel-labs/agent-skills    063bee94c3f4df8453406c830b0a7df0f2860278
```

**The upstream directory names are not the skill names.** `design-taste-frontend` lives in a
directory called `taste-skill`, and `high-end-visual-design` lives in one called `soft-skill`.
The YAML `name:` is what Claude uses, and that is what each directory here is named after, so
the two agree.

That repository holds thirteen skills; only these three were taken. The others
(`brandkit`, `industrial-brutalist-ui`, `minimalist-ui`, `gpt-taste`, `stitch-design-taste`,
`redesign-existing-projects`, `full-output-enforcement`, the two `imagegen-*`, and
`design-taste-frontend-v1`) are deliberately not vendored — they are alternative house styles or
unrelated tools, and pulling in a style skill would fight the CROOKS design direction rather than
serve it.

## One supporting file, and why it is here

`web-design-guidelines/SKILL.md` does not contain its own rules. It instructs the agent to fetch
them at review time from:

```
https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md
```

That fetch was tested from this container and answers HTTP 200, so the skill works as written.
`web-interface-guidelines.command.md` is a pinned copy of that file kept beside it as an offline
fallback, for the same reason the skills are vendored at all: the network policy of a build
container is not a thing to depend on. It is a copy of the skill's data, not an edit of the
skill's instructions — `SKILL.md` itself is untouched.

## Discovery

Claude Code builds its skill registry when a session starts, so skills added mid-session are on
disk and correct but not yet invocable through the `Skill` tool. They are picked up by the next
session. Reading the file directly does the same thing in the meantime — loading a skill IS
putting its instructions into context.
