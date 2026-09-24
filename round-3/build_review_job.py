#!/usr/bin/env python3
"""Build a standalone exact-SHA GPT review job for a candidate the Dispatcher did not produce.

Writes <out>/job.json and <out>/packet.md in exactly the shape that
``python -m app.orchestrator.reviewers.gpt <out>`` reads (see reviewers/gpt.py). It never
reads the API key: job.json records only the key file's path, as the Dispatcher does.

Everything that frames the review is read from git at named commits (the original spec,
the Director's queued request, the handoff invariants), so the candidate's author does
not get to phrase the acceptance criteria. Must be run with PYTHONPATH pointing at a
TRUSTED checkout's crooks-assistant directory (never the candidate's), because it imports
PROTECTED_PATHS from there.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from app.orchestrator.objectives import PROTECTED_PATHS  # trusted checkout on PYTHONPATH


def git(repo: str, *args: str) -> str:
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def section(text: str, heading: str) -> str:
    lines, out, on = text.splitlines(), [], False
    for line in lines:
        if line.startswith("## "):
            on = line.strip() == f"## {heading}"
            continue
        if on:
            out.append(line)
    return "\n".join(out).strip()


def block(text: str, start: str, stop_prefixes: tuple[str, ...]) -> str:
    lines, out, on = text.splitlines(), [], False
    for line in lines:
        if line.startswith(start):
            on = True
        elif on and line.startswith(stop_prefixes):
            break
        if on:
            out.append(line)
    if not out:
        sys.exit(f"could not find {start!r} in the materiality source")
    return "\n".join(out).strip()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True, help="git repo holding the candidate objects (engineering repo)")
    p.add_argument("--candidate", required=True)
    p.add_argument("--reviewed-base", required=True, help="last SHA of this line with an admitted GPT review")
    p.add_argument("--spec", default="d00267d7f5f96fa8515869f1a2be71073d74696a:crooks-assistant/docs/product-memory/REMOTE_ENGINEERING_CONTROL_V1.md")
    p.add_argument("--request", default="origin/clive/control/owner-inbox:requests/remote-engineering-control-v1-activation-readiness.json")
    p.add_argument("--handoff", default="origin/chatgpt/opus-5-5-handoff-2026-09-24:crooks-assistant/docs/product-memory/OPUS_5_5_HANDOFF_2026-09-24.md")
    p.add_argument("--prior-findings", default=None, help="optional JSON list of earlier findings this candidate repairs")
    p.add_argument("--ci-evidence", default=None, help="optional JSON: GitHub acceptance run url/conclusion/artifact block")
    p.add_argument("--out", required=True)
    p.add_argument("--key-file", required=True)
    p.add_argument("--model", default="gpt-5.6-sol")
    p.add_argument("--effort", default="high")
    p.add_argument("--task-id", default="remote-engineering-control-v1-activation")
    p.add_argument("--run", type=int, default=1)
    p.add_argument("--materiality", action="store_true",
                   help="include the owner's frozen materiality standard (DEC-057 and the 2026-09-23 "
                        "self-referential convergence rule), verbatim from git")
    p.add_argument("--decisions", default="origin/chatgpt/product-memory-reconcile-2026-09-23:crooks-assistant/docs/product-memory/DECISIONS.md")
    p.add_argument("--reconciliation", default="origin/chatgpt/product-memory-reconcile-2026-09-23:crooks-assistant/docs/product-memory/RECONCILIATION_2026-09-23.md")
    a = p.parse_args()

    sha = git(a.repo, "rev-parse", "--verify", f"{a.candidate}^{{commit}}").strip()
    if sha != a.candidate or len(sha) != 40:
        sys.exit(f"--candidate must be the exact 40-hex SHA; {a.candidate!r} resolves to {sha!r}")
    base = git(a.repo, "rev-parse", "--verify", f"{a.reviewed_base}^{{commit}}").strip()
    if subprocess.run(["git", "-C", a.repo, "merge-base", "--is-ancestor", base, sha]).returncode != 0:
        sys.exit(f"{base} is not an ancestor of {sha}")

    spec = git(a.repo, "show", a.spec)
    request = json.loads(git(a.repo, "show", a.request))
    handoff = git(a.repo, "show", a.handoff)
    invariants = section(handoff, "3. Permanent authority / safety invariants")
    changed = [x for x in git(a.repo, "diff", "--no-renames", "--name-only", base, sha).splitlines() if x]
    protected_hits = [c for c in changed if any(c == pp or c.startswith(pp.rstrip("/") + "/") for pp in PROTECTED_PATHS)]
    commits = git(a.repo, "log", "--reverse", "--format=%H  %an <%ae>  %s", f"{base}..{sha}").strip()
    diff = git(a.repo, "diff", "--no-renames", "--stat", "--patch", base, sha)
    attempt_id = f"{sha[:12]}-exact-sha-review"

    header = {
        "task_id": a.task_id, "task_revision": 1, "attempt_id": attempt_id, "candidate_sha": sha,
        "base_sha": base, "repository": "crooksldn-pixel/clive", "reviewer_principal": "gpt",
        "review_mechanism": f"openai-responses:{a.model}", "courier": False,
        "authorship_note": ("commits 2426923b..abaefa52 were authored in the ChatGPT Director session and were "
                            "reviewed by Claude, whose findings are listed below; the final commit was authored "
                            "by Claude (Opus 5.5). Judge the whole candidate at this exact SHA."),
    }
    lines = [
        f"# CLIVE review packet — {a.task_id} r1 {attempt_id}", "",
        "```json", json.dumps(header, indent=2, sort_keys=True), "```", "",
        f"Your verdict applies to exactly `{sha}` and to nothing else. It is the host activation gate: "
        "READY means this exact SHA may be run as the long-lived remote engineering loop on the engineering host.", "",
        "## Objective (the Director's queued request, verbatim from git)", "", request["requested_outcome"], "",
        "## Acceptance criteria", "",
        *[f"- {c}" for c in request["acceptance_criteria"]],
        "- every item in the original spec's Tests section (below) holds at this SHA",
        "- no permanent authority/safety invariant (below) is weakened", "",
        "## Original spec (verbatim, " + a.spec.split(":")[0] + ")", "", spec, "",
        "## Permanent authority / safety invariants (verbatim from the handoff)", "", invariants, "",
        "## Scope", "",
        *[f"- allowed: `{x}`" for x in request["allowed_paths"]],
        "- also changed on this line: product-memory docs `crooks-assistant/docs/product-memory/"
        "REMOTE_ENGINEERING_CONTROL_V1.md` and its README index entry",
        f"- protected paths touched (mechanical check against trusted PROTECTED_PATHS): {protected_hits or 'none'}", "",
        "## Commits under review (reviewed base..candidate)", "", "```", commits, "```", "",
    ]
    if a.materiality:
        dec = block(git(a.repo, "show", a.decisions), "## DEC-057", ("## DEC-", "# ", "---"))
        rule = block(git(a.repo, "show", a.reconciliation), "### Self-referential convergence rule", ("## ", "### "))
        lines += [
            "## Materiality standard for this round (owner doctrine, verbatim from git)", "",
            "The acceptance criteria above are frozen for this round. The subject is machinery that governs its own "
            "improvement, so the owner's standard below decides which findings are material. A finding is material "
            "when it shows a failure of an acceptance criterion above (including any credential or secret value "
            "reaching a receipt, log, output or the public projection) or one of the failure kinds listed below. "
            "Record any other improvement as a finding with material=false; it becomes backlog and does not block.", "",
            dec, "", rule, "",
        ]
    if a.ci_evidence:
        lines += ["## Mechanical evidence (GitHub acceptance for this exact SHA)", "", "```json",
                  Path(a.ci_evidence).read_text(encoding="utf-8").strip(), "```", ""]
    else:
        lines += ["## Mechanical evidence", "", "(none attached: the review is not an activation gate without it)", ""]
    if a.prior_findings:
        prior = json.loads(Path(a.prior_findings).read_text(encoding="utf-8"))
        lines += ["## Findings of the earlier review of abaefa52 (this candidate claims to repair them; verify, do not trust)", "",
                  *[f"- [{f['finding_id']}] {f['finding']} — required: {f['required_repair']}" for f in prior], ""]
    lines += ["## Changed paths (git diff --no-renames, base..candidate)", "", *[f"- `{c}`" for c in changed], "",
              "## Diff", "```diff", diff, "```", ""]

    out = Path(a.out)
    (out / "results").mkdir(parents=True, exist_ok=True)
    packet = out / "packet.md"
    packet.write_text("\n".join(lines), encoding="utf-8")
    job = {"task_id": a.task_id, "task_revision": 1, "attempt_id": attempt_id, "dispatch_seq": 1,
           "candidate_sha": sha, "packet_path": str(packet), "repo": str(Path(a.repo).resolve()),
           "key_file": a.key_file, "model": a.model, "effort": a.effort, "api_base": "https://api.openai.com/v1",
           "timeout_s": 1800, "run": a.run}
    (out / "job.json").write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"job": str(out / "job.json"), "packet_bytes": packet.stat().st_size,
                      "changed_paths": len(changed), "protected_hits": protected_hits}, indent=2))
    return 1 if protected_hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
