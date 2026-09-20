"""The second independent review of the harness candidate (d7911b2, bridge inbox 7ac15d08…,
verdict REJECT — REPAIR REQUIRED): five findings, F-1 … F-5, that reduce to three root causes
in the guard's newest parser additions. One negative test per reproducer, using the review's
own command strings; a small set of neighbours that exercise the repaired root cause rather
than the literal strings; and positive controls for the ordinary forms that must stay allowed.

Every reproducer below was run against the source of d7911b2 before the repair and was ALLOWED
(or, for the gate, produced no publish action); the same file passes after it. Nothing here
touches git, the network, a service or a real path: the guard reads text only. No secret value
appears here.

Root causes, as the review reduced them:
  * relative-target resolution (F-1): a redirect or copy destination is now resolved against
    the tracked working directory before the protected-path check, and refused when the
    working directory is a protected checkout — whatever the base command's read-only status;
  * the substitution marker gap (F-2, F-3, F-5): a `$( … )` or backtick substitution is now
    lexed as a piece of a word and replaced by the marker in the enclosing text, so wherever
    its output would be the command word the evaluator (and the gate, through the shared
    lexer) sees a dynamic word and refuses it;
  * the dynamic git subcommand (F-4): `git $p --force` is refused before the flags that only
    the literal subcommand branches inspect can be ignored.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "scripts" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import gitleaks_gate as gate  # noqa: E402
import guard_bash as gb  # noqa: E402

CWD = "/opt/crooks-builder/.worktrees/harness-hooks-experiment"
PROD = "/opt/crooks-os"


def verdict(command: str, cwd: str | None = CWD) -> gb.Decision:
    return gb.evaluate(command, cwd)


def denied(command: str, rule: str, cwd: str | None = CWD) -> None:
    d = verdict(command, cwd)
    assert d.denied, (command, "was ALLOWED")
    assert d.rule == rule, (command, d.rule, d.reason)


def allowed(command: str, cwd: str | None = CWD) -> gb.Decision:
    d = verdict(command, cwd)
    assert not d.denied, (command, d.rule, d.reason)
    return d


# ---------------------------------------------------------------------------------------------
# F-1 (H): a relative output redirect — or copy destination — into a protected checkout.
# ---------------------------------------------------------------------------------------------

F1_REVIEW_REPRODUCERS = [
    "cd /opt/crooks-os && echo pwned  > app/main.py",
    "cd /opt/crooks-os && echo pwned >> app/routes.py",
    "cd /opt/crooks-os && cat /tmp/x  > app/main.py",
    "cd /opt/crooks-os && printf x    > config/settings.py",
]


@pytest.mark.parametrize("command", F1_REVIEW_REPRODUCERS)
def test_f1_relative_redirect_under_a_protected_cwd_is_a_protected_path(command: str) -> None:
    denied(command, "PROTECTED-PATH")


@pytest.mark.parametrize("command", [
    # every redirect operator the rule reads, with a read-only base command
    "cd /opt/crooks-os && echo x &> app/log",
    "cd /opt/crooks-os && ls 2> app/err",
    "cd /opt/crooks-os && date >>app/main.py",
    "cd /opt/crooks-os && echo x > ./app/main.py",
    # the same root cause in the copy-like destinations, which returned before the cwd backstop
    "cd /opt/crooks-os && cp /tmp/x app/main.py",
    "cd /opt/crooks-os && cp /tmp/x .",
    "cd /opt/crooks-os && rsync -a /tmp/d/ app/",
    "cd /opt/crooks-os && install /tmp/x config/settings.py",
    # the working directory is not protected, but the relative target reaches a protected root
    "cd /opt && echo x > crooks-os/app/main.py",
    "cd /opt/crooks-builder && echo x > ../crooks-os/app/main.py",
    "cd /opt/crooks-builder && cp /tmp/x ../crooks-os/app/",
    # D-13 breadth: any protected working directory, not only production
    "cd /etc && echo x > hosts",
    "cd /root && date > notes.txt",
])
def test_f1_relative_targets_resolve_against_the_tracked_cwd(command: str) -> None:
    denied(command, "PROTECTED-PATH")


def test_f1_the_hook_payload_cwd_counts_as_much_as_a_literal_cd() -> None:
    denied("echo x > app/main.py", "PROTECTED-PATH", cwd=PROD)
    denied("cp /tmp/x app/main.py", "PROTECTED-PATH", cwd=PROD)
    denied("cat /tmp/x >> config/settings.py", "PROTECTED-PATH", cwd="/etc/crooks-os")


def test_f1_a_protected_cwd_whose_exact_directory_is_unknown_still_refuses() -> None:
    # `cd /opt/crooks-os/$X` leaves the exact directory unknown but the checkout known.
    denied("cd /opt/crooks-os/$X && echo x > main.py", "PROTECTED-CWD")
    denied("cd /opt/crooks-os/$X && cp /tmp/x app/", "PROTECTED-CWD")
    # A target the hook cannot resolve is refused under a protected cwd rather than assumed.
    denied("cd /opt/crooks-os && echo x > $OUT", "PROTECTED-CWD")
    # Until the repair of fe96bb6 (F-6) the segmenter split `>|` at its `|`, the residual
    # became the command word and the verdict was the cwd backstop by accident. `>|` is now
    # lexed as the clobber operator, so the verdict is the path rule's — still a denial.
    denied("cd /opt/crooks-os && echo x >| app/main.py", "PROTECTED-PATH")


def test_f1_reads_from_and_absolute_writes_out_of_a_protected_cwd_stay_allowed() -> None:
    allowed("cd /opt/crooks-os && git log > /tmp/log.txt")
    allowed("cd /opt/crooks-os && cat app/main.py > /tmp/copy.py")
    allowed("cd /opt/crooks-os && cp app/main.py /tmp/")
    allowed("cd /opt/crooks-os && ls > /dev/null")
    allowed("cd /opt/crooks-os && cd /tmp && echo x > y")
    # ordinary builder work is unchanged
    allowed("echo x > out.txt")
    allowed("cat a >> b")
    allowed("cp a b")
    allowed("install -m 644 x dist/x")
    allowed("cd /tmp && echo x > y")
    allowed("rsync -a ./dist/ host:/srv/x")
    allowed("scp x host:y")


# ---------------------------------------------------------------------------------------------
# F-2 (H): a command that is entirely a `$( )` / backtick substitution.
# ---------------------------------------------------------------------------------------------

F2_REVIEW_REPRODUCERS = [
    "$(echo 'git push --force origin main')",
    "$(printf 'rm -rf /opt/crooks-os')",
    "`echo 'git reset --hard'`",
    "$(echo 'systemctl restart crooks-assistant')",
]


@pytest.mark.parametrize("command", F2_REVIEW_REPRODUCERS)
def test_f2_a_whole_command_substitution_is_unparseable(command: str) -> None:
    denied(command, "UNPARSEABLE")


@pytest.mark.parametrize("command", [
    "$(cat /tmp/cmd)",
    "`cat /tmp/cmd`",
    "$(echo git) $(echo push) --force origin main",  # two substitutions, no literal word
    "$(echo 'git push --force') | cat",  # followed by a pipe rather than by text
    "$(echo ls); git push --force origin main",  # followed by a separator
    "$(echo 'git reset --hard') && echo done",
    "( $(echo 'git reset --hard') )",  # inside a subshell group
    "gi$(echo t) push --force origin main",  # glued to a literal prefix: `git`
    "gi`echo t` push --force origin main",
    "$(echo $(echo git)) push --force origin main",  # nested
    "$(echo x",  # unterminated: refused, not guessed
    "`echo x",
])
def test_f2_the_substitution_is_a_dynamic_word_wherever_it_forms_the_command(command: str) -> None:
    denied(command, "UNPARSEABLE")


def test_f2_the_substitution_body_is_still_evaluated_first() -> None:
    denied("$(rm -rf /opt/crooks-os)", "RM-RECURSIVE")
    denied("echo $(rm -rf /opt/crooks-os)", "RM-RECURSIVE")
    denied("echo y | $(rm -rf /tmp)", "RM-RECURSIVE")


def test_f2_the_segmenter_lexes_a_substitution_as_a_word_piece() -> None:
    assert gb._segments("$(echo git) push") == [("echo git", False), ("$SUBST push", False)]
    assert gb._segments("$(echo x)") == [("echo x", False), ("$SUBST", False)]
    assert gb._segments("sudo $(echo git) push") == [("echo git", False),
                                                     ("sudo $SUBST push", False)]
    assert gb._segments("echo $(date)") == [("date", False), ("echo $SUBST", False)]
    assert gb._segments("x=$(a)$(b)") == [("a", False), ("b", False), ("x=$SUBST$SUBST", False)]
    assert gb._segments("echo $(echo ')')") == [("echo ')'", False), ("echo $SUBST", False)]
    with pytest.raises(ValueError):
        gb._segments("$(" * (gb.MAX_SUBSTITUTION_NESTING + 2))


def test_f2_substitutions_in_argument_position_stay_allowed() -> None:
    allowed("echo $(date)")
    allowed("echo $(git rev-parse HEAD)$(date)")
    allowed("HEAD=$(git rev-parse HEAD); echo $HEAD")
    allowed("x=$(a)$(b); echo $x")
    allowed('git commit -m "$(cat /tmp/msg)"')
    allowed('echo "$(date)"')
    allowed("for f in $(ls); do echo $f; done")
    allowed("kill $(cat /tmp/pid)")
    allowed("cd $(git rev-parse --show-toplevel) && ls")
    allowed("echo $((1+2))")
    allowed('test -n "$(git status --porcelain)"')
    allowed("wc -l $(find . -name '*.py')")


# ---------------------------------------------------------------------------------------------
# F-3 (M): a substitution in command position behind a passthrough wrapper or an assignment.
# ---------------------------------------------------------------------------------------------

F3_REVIEW_REPRODUCERS = [
    "sudo    $(echo git)       push --force origin main",
    "command $(echo git)       push --force origin main",
    "env X=1 $(echo systemctl) restart crooks-assistant",
]


@pytest.mark.parametrize("command", F3_REVIEW_REPRODUCERS)
def test_f3_a_substitution_behind_a_wrapper_is_unparseable(command: str) -> None:
    denied(command, "UNPARSEABLE")


@pytest.mark.parametrize("command", [
    "nohup $(echo git) push --force origin main",
    "exec $(echo git) push --force origin main",
    "time $(echo systemctl) restart crooks-assistant",
    "timeout 5 $(echo git) push --force origin main",
    "X=1 Y=2 $(echo git) push --force origin main",  # leading assignments, no wrapper
    "sudo -u root $(echo systemctl) restart crooks-assistant",  # wrapper options in between
    "env -i $(echo git) push --force origin main",
    "sudo env X=1 $(echo git) push --force origin main",  # two wrappers
    "sudo `echo git` push --force origin main",
    "xargs $(echo rm) -rf /",
])
def test_f3_every_passthrough_wrapper_unwraps_to_the_dynamic_word(command: str) -> None:
    denied(command, "UNPARSEABLE")


def test_f3_wrappers_with_static_commands_and_dynamic_arguments_stay_allowed() -> None:
    allowed("env X=$(date) ls")
    allowed("sudo -u nobody ls $(pwd)")
    allowed("timeout 5 git status")
    allowed("nice -n 5 pytest -q")


# ---------------------------------------------------------------------------------------------
# F-4 (M): a git subcommand supplied dynamically ignores its own destructive flags.
# ---------------------------------------------------------------------------------------------

F4_REVIEW_REPRODUCERS = [
    "p=push;  git $p  --force origin main",
    "s=reset; git $s  --hard",
    "git ${SUB} --hard",
]


@pytest.mark.parametrize("command", F4_REVIEW_REPRODUCERS)
def test_f4_a_dynamic_git_subcommand_is_unparseable(command: str) -> None:
    denied(command, "UNPARSEABLE")


@pytest.mark.parametrize("command", [
    'git "$p" --force origin main',
    "git $(echo push) --force origin main",
    "git `echo push` --force origin main",
    "git -C /tmp/repo $p --force origin main",  # after global options
    "git -c x=y ${SUB} --hard",
    "git pu${x}sh --force origin main",  # partially dynamic
    "git {push,pull} --force origin main",  # brace form
    "git pus? --force origin main",  # glob
])
def test_f4_every_dynamic_spelling_of_the_subcommand_is_refused(command: str) -> None:
    denied(command, "UNPARSEABLE")


def test_f4_dynamic_git_arguments_after_a_literal_subcommand_stay_allowed() -> None:
    allowed("git push origin $BRANCH")
    allowed("git log -1 $REV")
    allowed("git checkout $BRANCH")
    allowed('git commit -m "$MSG"')
    allowed("git -C $DIR status")
    allowed("git push origin claude/harness-hooks-experiment")
    denied("git push --force origin $BRANCH", "GIT-PUSH-FORCE")  # the flag is still read


# ---------------------------------------------------------------------------------------------
# F-5 (M): the gitleaks gate misses a publish laundered through a substitution.
# ---------------------------------------------------------------------------------------------

F5_REVIEW_REPRODUCERS = [
    'bash -c "$(echo git push)"',
    "$(echo 'git push origin x')",
]


@pytest.mark.parametrize("command", [
    *F5_REVIEW_REPRODUCERS,
    "`echo 'git push'`",
    "sudo $(echo git) push origin x",  # F-3 through the shared lexer
    "gi$(echo t) push origin x",
    "p=push; git $p origin x",  # F-4 in the gate: it may be a publish
    "git $(echo push) origin x",
    "git ${SUB} origin x",
])
def test_f5_the_gate_cannot_read_a_laundered_publish_and_says_so(command: str) -> None:
    with pytest.raises(ValueError):
        gate._publish_actions(command)
    raw = json.dumps({"tool_name": "Bash", "tool_input": {"command": command},
                      "cwd": "/tmp"}).encode()
    d = gate.run_gate(raw, gitleaks="/nonexistent")
    assert d.denied and d.rule == "UNPARSEABLE", (command, d)


def test_f5_the_gate_still_finds_literal_publishes_and_ignores_argument_substitutions() -> None:
    def subs(command: str) -> list[str]:
        return [a[0] for a in gate._publish_actions(command)]

    assert subs("bash -c 'git push origin x'") == ["push"]
    assert subs("printf 'git push' | sh") == ["push"]
    assert subs('git commit -m "$(cat /tmp/msg)"') == ["commit"]
    assert subs("git push origin $BRANCH") == ["push"]
    assert subs("echo $(date)") == []
    assert subs("echo 'git push'") == []


# ---------------------------------------------------------------------------------------------
# The two high findings, as the hook process itself decides them (the review confirmed both
# as exit 0 under the system interpreter before the repair).
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("command", "cwd"), [
    ("cd /opt/crooks-os && echo pwned > app/main.py", CWD),
    ("$(echo 'git push --force origin main')", CWD),
    ("echo pwned > app/main.py", PROD),
])
def test_the_hook_process_exits_2_for_the_high_reproducers(command: str, cwd: str) -> None:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command},
                          "cwd": cwd}).encode()
    proc = subprocess.run([sys.executable, str(HOOKS_DIR / "guard_bash.py")], input=payload,
                          capture_output=True, timeout=30, check=False)
    assert proc.returncode == 2, (command, proc.stdout, proc.stderr)
    assert proc.stdout == b""
    assert b"DENY" in proc.stderr
    assert b"pwned" not in proc.stderr  # a reason never echoes the command text
