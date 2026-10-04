# Vendored skills

`systematic-debugging`, `test-driven-development`, `verification-before-completion` and
`receiving-code-review` are copied unchanged (apart from the `crooks-dev:` skill prefix) from
[obra/superpowers](https://github.com/obra/superpowers) at commit
`5bf4e78011075bcfc0dc295f0724994cd123ee71` (v6.4.1), under the MIT licence in
`LICENSE-superpowers`.

Only these four are taken. The full plugin is not installed because its SessionStart hook makes
skill use mandatory before any action (brainstorming before any build, plans before any code).
These sister apps keep their own workflow (see the repo's CLAUDE.md); the skills are engineering
discipline used on demand, not product or architecture direction.

To update: re-copy the four directories from a newer upstream commit and update the hash here.
