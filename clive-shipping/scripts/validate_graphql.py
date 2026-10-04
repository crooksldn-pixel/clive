"""Validate every Admin GraphQL document Shipping sends against its pinned API version, with the
Shopify AI Toolkit's validator (local schema, telemetry off). Exits non-zero on any failure.

    python scripts/validate_graphql.py
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shipping import shopify  # noqa: E402

PATTERN = os.path.expanduser(
    "~/.claude/plugins/cache/*/shopify-ai-toolkit/*/skills/shopify-admin/scripts/validate.mjs"
)


def main() -> int:
    found = sorted(glob.glob(PATTERN))
    if not found:
        print("Shopify AI Toolkit not installed (the shopify-ai-toolkit plugin).")
        return 2
    env = {**os.environ, "OPT_OUT_INSTRUMENTATION": "true"}
    failed = 0
    for name in shopify.DOCUMENTS:
        run = subprocess.run(
            [
                "node",
                found[-1],
                "--code",
                getattr(shopify, name),
                "--version",
                shopify.API_VERSION,
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        try:
            out = json.loads(run.stdout)
            reply = out["responses"][0]
            ok = out.get("success") and reply["result"] == "success"
            version = out.get("resolvedVersion")
        except (ValueError, KeyError, IndexError):
            ok, version, reply = False, None, {"resultDetail": run.stdout + run.stderr}
        ok = ok and version == shopify.API_VERSION
        failed += not ok
        detail = reply.get("resultDetail", "").splitlines()
        print(f"{'ok  ' if ok else 'FAIL'} {name:<24} {version}  {detail[-1] if detail else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
