#!/bin/sh
# Microsoft's Playwright MCP server (@playwright/mcp), launched for wherever this runs.
# Claude Code cloud images ship Chromium at /opt/pw-browsers/chromium but no Google Chrome
# (the server's default) and possibly not the Chromium build this release expects, so point
# it at the installed one. Elsewhere (a Mac, a laptop) Playwright's own defaults apply.
# Screenshots and traces go outside the repo.
VERSION=0.0.83   # tested 2026-10-05; bump deliberately
OUT="${PLAYWRIGHT_MCP_OUTPUT_DIR:-${TMPDIR:-/tmp}/playwright-mcp}"
if [ -x /opt/pw-browsers/chromium ]; then
  exec npx -y "@playwright/mcp@$VERSION" --browser chromium \
    --executable-path /opt/pw-browsers/chromium --headless --output-dir "$OUT" "$@"
fi
exec npx -y "@playwright/mcp@$VERSION" --output-dir "$OUT" "$@"
