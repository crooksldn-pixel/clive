"""CURRENT_TRUTH.md says what is true of the build loop on 16 October 2026, and the text that
update replaced is kept word for word in the history file.

Proved here, on the files as they stand in this checkout:

- the "As of" line reads 2026-10-16 and still names production as `dc59047e`;
- the loop row names `ef204bc2`, re-pinned on 16 Oct 2026, its re-pin review READY with no waiver;
- "The build loop" says DEC-068 and DEC-076 are in force (claude-reviewer in place of GPT, stop
  reports served to production over the tailnet only, builder skills off on CLI 2.1.280, 2 repair
  rounds by default, 2 builders at once), that the production host's own loop was stopped and
  disabled under DEC-071 ruling 11 so worker-01 runs the only loop, that `cdee8fce` was reviewed by
  claude-reviewer and landed by the loop, and the 76 requests since 25 Sep;
- "The loop's current pin." is no longer on the "Not verified from here" list;
- every line the update replaced or removed is in the history file, unchanged, and gone from
  CURRENT_TRUTH;
- the file's headings, the live table's shape and the points kept are unchanged.
"""

from __future__ import annotations

from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"
TRUTH = DOCS / "product-memory" / "CURRENT_TRUTH.md"
HISTORY = DOCS / "history" / "CURRENT_TRUTH_HISTORY.md"

HEADINGS = [
    "# CLIVE — Current Truth",
    "## Now — 2026-10-05",
    "### What is live",
    "### Production switches and what runs",
    "### CROOKS Returns: live beside CLIVE, not in it",
    "### Open pull requests",
    "### Merged, not deployed",
    "### The build loop",
    "### Recorded in DECISIONS on 5 October",
    "### Still the owner's",
    "### Not verified from here",
]

# What CURRENT_TRUTH said before 16 Oct 2026 and no longer says, line for line.
REPLACED = (
    "**As of:** 2026-10-14 (production is `dc59047e`; `clive/trunk` additionally contains DEC-079, which is on the trunk only and not in production).",
    '| **The loop** (clive-worker-01) | not recorded | See "The build loop" below. |',
    '- **Back at work on 7–8 Oct:** it landed the five builds listed under "Merged, not deployed". The counts in the next point stop at 7 Oct and are not updated here.',
    "- **Quiet since 1 Oct.** Since 25 Sep, the loop on clive-worker-01 has taken 65 requests:",
    "  - 21 COMPLETE;",
    "  - 40 BLOCKED: 17 at the repair-round limit, 10 reported blocked by their builder, 7 on a red GitHub run, 4 on workspace errors and 2 on failed checks;",
    "  - 2 OWNER_GATE;",
    "  - 2 refused at intake.",
    "  The last request was recorded on **1 Oct at 22:08 UTC**. It still publishes its status to `clive/control/worker-01-status` about every ten minutes (still on 7 Oct).",
    "- **Its pin is not recorded.** PR #72 records a re-pin to `b577bc97` on 1 Oct, at which the owner waived two findings. A later re-pin review of `b577bc97..4daf49e1` asked for changes, which PR #88 (`718fbc41`) answered. Which SHA the loop runs now is not recorded in the repository.",
    "- **The loop upgrade of 7 Oct is on the trunk and not in force** ([DEC-068](./DECISIONS.md)). It takes effect only at clive-worker-01's re-pin, which the owner approved on the Director's go. From then:",
    "  - why a build stopped (the reviewer's findings, the failing output, the builder's words) is kept on worker-01 and served over the tailnet only, to `crooks-os-prod-1` named by its full tailnet name. The Builds screen shows it once `CROOKS_ENGINEERING_PRIVATE_URL` is set in production's `.env`; until then it says the wording is kept on the build server;",
    "  - a build filed again starts with the earlier try's findings, and a request without its own number gets the host's default repair rounds;",
    "  - builders get the four design skills, but only on Claude CLI 2.1.285 or 2.1.293. On any other version the loop runs with `--no-builder-skills`;",
    "- **The Claude reviewer is built and not in force** ([DEC-076](./DECISIONS.md), PR #114). At the next re-pin of clive-worker-01, Claude on the owner's plan reviews the loop's candidates in place of GPT. It is read-only, in a session and room of its own, and the review contract is unchanged. `--reviewer gpt` falls back. The re-pin's own review (`root-repin.sh`) stays GPT until he decides otherwise.",
    "- The loop's current pin.",
)

# Points of "The build loop" that the update kept as they were.
KEPT = (
    "  - checks can drive Chromium once it is installed on worker-01.",
    "- **The loop landed 7 builds itself on 1 Oct.** Every trunk change after its last landing (`8ad7477d`, 1 Oct 22:27 UTC) came from builders outside it: PRs #89–#95, and two direct landings (`1d03efd6`, `4d2dc00f`).",
)


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").split("\n")


def _section(heading: str) -> str:
    text = TRUTH.read_text(encoding="utf-8")
    body = text.split(f"\n{heading}\n", 1)[1]
    return body.split("\n### ", 1)[0]


def _loop_row() -> list[str]:
    for line in _lines(TRUTH):
        if line.startswith("| **The loop**"):
            return [cell.strip() for cell in line.strip().strip("|").split("|")]
    raise AssertionError("no loop row in the live table")


def test_as_of_line_reads_16_october():
    lines = [line for line in _lines(TRUTH) if line.startswith("**As of:**")]
    assert len(lines) == 1
    assert lines[0].startswith("**As of:** 2026-10-16 (")
    assert "production is `dc59047e`" in lines[0]


def test_loop_row_is_the_16_october_re_pin():
    label, sha, what = _loop_row()
    assert label == "**The loop** (clive-worker-01)"
    assert sha == "`ef204bc2`"
    assert "Re-pinned on **16 Oct 2026**" in what
    assert "re-pin review was READY, with no waiver" in what
    assert "not recorded" not in what


def test_build_loop_says_dec_068_and_dec_076_are_in_force():
    loop = _section("### The build loop")
    assert "**DEC-068 and DEC-076 are in force there**" in loop
    assert "as `claude-reviewer`, in place of GPT" in loop
    assert "served to production over the tailnet only" in loop
    assert "builder skills are off" in loop
    assert "the worker CLI is 2.1.280" in loop
    assert "default of 2 repair rounds" in loop
    assert "it runs 2 builders at once" in loop
    assert "not in force" not in loop


def test_build_loop_says_worker_01_runs_the_only_loop():
    loop = _section("### The build loop")
    assert (
        "The production host's own engineering loop was stopped and disabled on 16 Oct 2026 "
        "under [DEC-071](./DECISIONS.md) ruling 11, so worker-01 runs the only loop."
    ) in loop


def test_build_loop_says_the_first_build_on_the_new_pin_landed():
    loop = _section("### The build loop")
    assert (
        "**Its first build on the new pin,** `cdee8fce`, was reviewed by `claude-reviewer` "
        "and landed by the loop."
    ) in loop
    assert "re-pinned on 16 oct 2026" in loop.lower()
    assert "`ef204bc2`" in loop


def test_build_loop_counts_76_requests_since_25_september():
    loop = _section("### The build loop")
    assert (
        "had taken 76 requests: 27 COMPLETE, 45 BLOCKED, 2 at an owner gate and 2 refused."
    ) in loop
    assert "**76 requests since 25 Sep.**" in loop
    assert "65 requests" not in loop


def test_current_pin_is_no_longer_unverified():
    unverified = _section("### Not verified from here")
    assert "The loop's current pin" not in unverified
    assert unverified.lstrip("\n").startswith("- The owner's phone check for `b33ccbc2`.")


def test_replaced_text_is_kept_word_for_word_in_the_history():
    history = _lines(HISTORY)
    truth = _lines(TRUTH)
    for line in REPLACED:
        assert line in history, line
        assert line not in truth, line
    # It sits above the line under which the 5 October file is kept byte for byte.
    text = HISTORY.read_text(encoding="utf-8")
    above, below = text.split("\n---\n", 1)
    assert "## Replaced on 16 October 2026" in above
    assert below.startswith("\n# CLIVE — Current Truth\n")


def test_everything_else_is_unchanged():
    lines = _lines(TRUTH)
    assert [line for line in lines if line.startswith("#")] == HEADINGS
    table = [line for line in lines if line.startswith("| ")]
    assert table[0] == "| | SHA | What it is |"
    assert [line.split("|")[1].strip() for line in table[1:4]] == [
        "**Production** (`crooks-os-prod-1`, `/opt/crooks-os`)",
        "**Trunk** (`clive/trunk`)",
        "**The loop** (clive-worker-01)",
    ]
    loop = _section("### The build loop")
    for line in KEPT:
        assert line in loop.split("\n"), line
    assert '- **Back at work on 7–8 Oct:** it landed the five builds listed under "Merged, not deployed".' in loop
    assert "- **GitHub Apps for the Director and CLIVE** are specified in" in loop
