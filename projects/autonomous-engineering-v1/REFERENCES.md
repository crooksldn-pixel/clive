# References

## CLIVE internal authority

Read current versions from the repository:
- crooks-assistant/MAP.md
- crooks-assistant/docs/product-memory/CURRENT_TRUTH.md
- crooks-assistant/docs/product-memory/DECISIONS.md
- crooks-assistant/docs/product-memory/ENGINEERING_DISPATCHER_V1.md
- crooks-assistant/docs/product-memory/REMOTE_ENGINEERING_CONTROL_V1.md
- crooks-assistant/docs/product-memory/REVIEW_ACCEPTANCE_CONTRACT.md
- crooks-assistant/docs/product-memory/SOURCE_ASSIMILATION_V1.md
- crooks-assistant/docs/product-memory/ENGINEERING_CONTROL_PLANE_VNEXT.md
- crooks-assistant/docs/product-memory/CLIVE_INTENT_TO_EXECUTION_PHILOSOPHY.md
- crooks-assistant/docs/ENGINEERING_LOOP.md
- crooks-assistant/docs/BENCH.md
- crooks-assistant/app/orchestrator/
- crooks-assistant/app/remote_engineering/
- crooks-assistant/app/engineering_bridge/
- crooks-assistant/app/builds/
- crooks-assistant/app/bench/
- crooks-assistant/config/builder_skills.json
- .github/workflows/acceptance.yml

## External primary sources

Use current official sources and pin exact versions/commits if adopting a pattern.

Anthropic:
- Claude Code docs for skills, subagents, hooks, MCP, sessions and permissions;
- Claude Agent SDK docs;
- official Anthropic plugin examples.

Microsoft Playwright:
- https://github.com/microsoft/playwright-mcp
- https://github.com/microsoft/playwright-cli
- https://playwright.dev/

Context7:
- https://github.com/upstash/context7
- https://context7.com/docs

GitHub:
- GitHub Actions docs;
- GitHub Apps docs;
- Git/worktree documentation where relevant.

## External-source rule

Before adoption: resolve canonical upstream, pin exact version/commit, record license, inspect hooks/installers/binaries/symlinks/agent instructions, compare with CLIVE, adopt only the bounded useful part, and define evidence that it improved results.
