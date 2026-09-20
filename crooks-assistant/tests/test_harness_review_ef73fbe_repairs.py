"""The fourth independent review of the harness candidate (ef73fbe, bridge inbox 4adc375…,
verdict REJECT — REPAIR REQUIRED): one finding, R-01, in the shared lexer. One negative test
per review reproducer, using the review's own command strings; the neighbouring vectors the
repair inbox asked for (continuations next to glued, spaced and descriptor redirects, in
copy / install / delete operands, after `cd`, in double quotes, inside a command word, in
chained redirects and shell wrappers, and in a publish the gitleaks gate must still see);
positive controls for the single-quoted continuation bash keeps literal; and a witness that
runs real bash on scratch files so the semantics the lexer now matches are shown, not
asserted.

Every reproducer below was run against the source of ef73fbe before the repair; the ones the
review found (and the neighbours that fail for the same reason) were ALLOWED or, for the
gitleaks gate, found no publish. The same file passes after the repair. Nothing here touches
git, the network, a service or a real protected path: the guard reads text only, and the
bash witness writes only under pytest's tmp_path. No secret value appears here.

Root cause, as the review reduced it and the repair addresses it:
  * bash removes an unquoted or double-quoted backslash-newline pair from its input before
    it reads a word (the pair is a line continuation), so `echo x >\\<newline>/opt/x` is
    `echo x >/opt/x`, `2\\<newline>>f` is `2>f` and `bash \\<newline><<EOF` owns the heredoc.
    The lexer kept the pair, and shlex turned it into a literal newline inside the following
    word, so a redirect target, copy destination or delete operand began with "\\n" instead
    of "/" and was resolved as a relative path under a non-protected working directory.
  * The pair is now removed by the segmenter itself (`_join_continuations`, quote-aware:
    single-quoted pairs stay literal, comments run to the end of their physical line), so
    the guard, the heredoc owner and the gitleaks gate inherit one correction; and the
    heredoc stripper reads logical lines the way bash does (joining continued command
    lines, and continued body lines of an unquoted heredoc before the delimiter check).
"""

from __future__ import annotations

import json
import shutil
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
MAIN = "/opt/crooks-os/app/main.py"
NL = "\\\n"  # a real backslash immediately followed by a real newline: a bash line continuation


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
# R-01 (H): the review's own reproducers, verbatim.
# ---------------------------------------------------------------------------------------------

R01_REVIEW_REPRODUCERS = [
    ("echo x >\\\n/opt/crooks-os/app/main.py", "PROTECTED-PATH"),
    ("echo x>\\\n/opt/crooks-os/app/main.py", "PROTECTED-PATH"),
    ("cp /tmp/x \\\n/opt/crooks-os/app/main.py", "PROTECTED-PATH"),
    ("rm -rf \\\n/opt/crooks-os", "RM-RECURSIVE"),
]


@pytest.mark.parametrize(("command", "rule"), R01_REVIEW_REPRODUCERS)
def test_r01_a_continuation_before_the_target_is_the_target(command: str, rule: str) -> None:
    denied(command, rule)


# ---------------------------------------------------------------------------------------------
# The lexer itself: what bash removes, the segmenter removes; what bash keeps, it keeps.
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("text", "joined"), [
    ("a\\\nb", "ab"),  # unquoted: the pair vanishes and the word continues
    ('"a\\\nb"', '"ab"'),  # double-quoted: the same
    ("'a\\\nb'", "'a\\\nb'"),  # single-quoted: both characters are literal
    ("a\\\\\nb", "a\\\\\nb"),  # an escaped backslash, then a newline that ends the command
    ("a\\\n\\\nb", "ab"),  # two continuations in a row
    ("a\\\n#b", "a#b"),  # `#` after a continuation is mid-word, not a comment
    ("# c \\\nb", "# c \\\nb"),  # a comment runs to its newline; its backslash continues nothing
    ("echo hi # c \\\nb", "echo hi # c \\\nb"),
    ("a \\", "a \\"),  # a dangling escape is kept for the tokenizer to refuse
    ("it's \\\nb", "it's \\\nb"),  # an unbalanced quote is left for the segmenter to refuse
    ("\"it's\" \\\nb", "\"it's\" b"),  # an apostrophe inside double quotes is not a quote
    ("a\\nb", "a\\nb"),  # the two characters backslash, n: not a newline, not touched
])
def test_r01_join_continuations_matches_bash(text: str, joined: str) -> None:
    assert gb._join_continuations(text) == joined


@pytest.mark.parametrize(("line", "continued"), [
    ("cp /tmp/x \\", True),
    ("cp /tmp/x \\\\", False),
    ("cp /tmp/x \\\\\\", True),
    ("echo 'a \\", False),
    ('echo "a \\', True),
    ("# comment \\", False),
    ("echo x # comment \\", False),
    ("echo a#b \\", True),
    ("echo x", False),
    ("", False),
])
def test_r01_a_physical_line_ends_in_a_continuation_only_when_bash_says_so(
    line: str, continued: bool
) -> None:
    assert gb._continued(line) is continued


@pytest.mark.parametrize(("segment", "tokens"), [
    ("echo x >\\\n/opt/x", ["echo", "x", ">/opt/x"]),
    ("echo x>\\\n/opt/x", ["echo", "x", ">/opt/x"]),
    ("echo x \\\n>/opt/x", ["echo", "x", ">/opt/x"]),
    ("echo x 2\\\n>/opt/x", ["echo", "x", "2>/opt/x"]),  # the descriptor stays with its operator
    ("echo x >\\\n|/opt/x", ["echo", "x", ">|/opt/x"]),  # an operator split by a continuation
    ("echo x >\\\n>/opt/x", ["echo", "x", ">>/opt/x"]),
    ("echo x &\\\n>/opt/x", ["echo", "x", "&>/opt/x"]),
    ('echo x >"\\\n/opt/x"', ["echo", "x", ">/opt/x"]),
    ("echo 'a\\\nb'", ["echo", "a\\\nb"]),  # single-quoted: the literal pair reaches the token
    ("echo a\\\n#b", ["echo", "a#b"]),
    ("ec\\\nho x", ["echo", "x"]),
    ("rm -r\\\nf /opt/x", ["rm", "-rf", "/opt/x"]),
])
def test_r01_tokens_are_the_words_bash_reads(segment: str, tokens: list[str]) -> None:
    assert gb._tokens(segment)[0] == tokens


def test_r01_segment_boundaries_survive_a_continuation() -> None:
    assert gb._segments("ls \\\n| wc") == [("ls", False), ("wc", True)]
    assert gb._segments("ls \\\n&& rm x") == [("ls", False), ("rm x", False)]
    assert gb._segments("ls \\\n; rm x") == [("ls", False), ("rm x", False)]
    assert gb._segments("echo $(ls \\\n-a)") == [("ls -a", False), ("echo $SUBST", False)]


def test_r01_a_dangling_backslash_is_refused_not_guessed() -> None:
    denied("echo x >/tmp/out \\", "UNPARSEABLE")
    denied("rm -rf /tmp/scratch \\", "UNPARSEABLE")


def test_r01_the_heredoc_stripper_reads_logical_lines() -> None:
    assert gb._strip_heredocs("bash \\\n<<EOF\nbody\nEOF") == ("bash <<EOF", [("shell", "body")])
    assert gb._strip_heredocs("cat <<EOF \\\n| bash\nbody\nEOF") == (
        "cat <<EOF | bash", [("shell", "body")])
    # an unquoted body joins a continued line before the delimiter check, as bash does
    assert gb._strip_heredocs("cat <<EOF\nfoo \\\nEOF\nbar\nEOF") == ("cat <<EOF", [])
    assert gb._strip_heredocs("bash <<EOF\nfoo \\\nEOF\nbar\nEOF") == (
        "bash <<EOF", [("shell", "foo EOF\nbar")])
    # a quoted body does not
    assert gb._strip_heredocs("cat <<'EOF'\nfoo \\\nEOF\nbar\nEOF") == (
        "cat <<'EOF'\nbar\nEOF", [])
    # an escaped backslash at the end of a body line is not a continuation
    assert gb._strip_heredocs("cat <<EOF\nfoo \\\\\nEOF\nbar\nEOF") == ("cat <<EOF\nbar\nEOF", [])


# ---------------------------------------------------------------------------------------------
# Continuations next to every redirection operator: glued, spaced, appended, clobbering,
# descriptor-numbered, and split through the operator itself.
# ---------------------------------------------------------------------------------------------

OPERATORS = [">", ">>", ">|", "&>", "&>>", "1>", "2>", "2>>", "<>"]
READ_ONLY_BASES = ["echo x", "printf x", "cat /tmp/x"]
ABSOLUTE_DESTINATIONS = [MAIN, "/etc/crooks-os/x", "/etc/hosts", "/root/.bashrc",
                         "/root/.claude/settings.json"]


@pytest.mark.parametrize("op", OPERATORS)
@pytest.mark.parametrize("head", READ_ONLY_BASES)
@pytest.mark.parametrize("dest", ABSOLUTE_DESTINATIONS)
def test_r01_every_operator_with_a_continuation_before_an_absolute_protected_target(
    op: str, head: str, dest: str
) -> None:
    denied(f"{head} {op}{NL}{dest}", "PROTECTED-PATH")  # spaced operator, continued target
    denied(f"{head}{op}{NL}{dest}", "PROTECTED-PATH")  # glued operator, continued target


@pytest.mark.parametrize("op", OPERATORS)
def test_r01_a_continuation_before_or_inside_the_operator(op: str) -> None:
    denied(f"echo x {NL}{op}{MAIN}", "PROTECTED-PATH")
    denied(f"echo x{NL}{op} {MAIN}", "PROTECTED-PATH")
    if len(op) > 1:
        denied(f"echo x {op[0]}{NL}{op[1:]}{MAIN}", "PROTECTED-PATH")


@pytest.mark.parametrize("command", [
    f"echo x >{NL}| {MAIN}",  # the clobber operator, split
    f"echo x >{NL}> {MAIN}",  # the append operator, split
    f"echo x &{NL}> {MAIN}",
    f"echo x 2{NL}>{MAIN}",  # the descriptor and its operator, split
    f"echo x 1{NL}>>{MAIN}",
    f"echo x >{NL}{NL}{MAIN}",  # two continuations
    f"echo x >/opt/crooks-os/{NL}app/main.py",  # inside the target
    f"echo x >/opt/{NL}crooks-os/app/main.py",
    f"echo x > /opt/crooks-os/app/{NL}main.py",
    f"echo x >{NL}/tmp/a >{MAIN}",  # chained: the protected one second
    f"echo x >/tmp/a >{NL}{MAIN}",
    f"echo x >{NL}/tmp/a 2>{NL}{MAIN}",
    f"echo x 2>&1 >{NL}{MAIN}",
    f"tee {NL}{MAIN} </tmp/x",
    f"tee -a {NL}{MAIN} </tmp/x",
])
def test_r01_redirect_neighbours(command: str) -> None:
    denied(command, "PROTECTED-PATH")


@pytest.mark.parametrize("command", [
    f"cat /tmp/x >{NL}/dev/sda",
    f"cat /tmp/x > {NL}/dev/nvme0n1",
    f"cat /tmp/x 1>>{NL}/dev/sdb1",
])
def test_r01_f6d_block_device_after_a_continuation(command: str) -> None:
    denied(command, "DISK-DESTRUCTIVE")


# ---------------------------------------------------------------------------------------------
# After `cd`: relative protected destinations, with the continuation on either side.
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("command", "rule"), [
    (f"cd /opt/crooks-os && echo x >{NL}app/main.py", "PROTECTED-PATH"),
    (f"cd {NL}/opt/crooks-os && echo x >app/main.py", "PROTECTED-PATH"),
    (f"cd /opt/crooks-os {NL}&& echo x >app/main.py", "PROTECTED-PATH"),
    (f"cd /opt/crooks-os &&{NL}echo x >app/main.py", "PROTECTED-PATH"),
    (f"cd /opt/{NL}crooks-os && echo x >app/main.py", "PROTECTED-PATH"),
    (f"cd /opt/crooks-os && cp /tmp/x {NL}app/main.py", "PROTECTED-PATH"),
    (f"cd /opt/crooks-os && cp {NL}/tmp/x app/main.py", "PROTECTED-PATH"),
    (f"cd /opt/crooks-os && rm -rf {NL}app", "RM-RECURSIVE"),
    (f"cd {NL}/opt/crooks-os && rm -rf app", "RM-RECURSIVE"),
    (f"cd /etc/crooks-os && printf x >>{NL}settings.toml", "PROTECTED-PATH"),
    (f"cd /root && echo x >{NL}.profile", "PROTECTED-PATH"),
    (f"cd /opt/crooks-builder && echo x >{NL}../crooks-os/app/main.py", "PROTECTED-PATH"),
])
def test_r01_after_cd_a_relative_destination_is_resolved(command: str, rule: str) -> None:
    denied(command, rule)


@pytest.mark.parametrize(("command", "cwd"), [
    (f"echo x >{NL}main.py", PROD + "/app"),
    (f"echo x>{NL}main.py", PROD + "/app"),
    (f"cp /tmp/x {NL}main.py", PROD + "/app"),
    (f"printf x >{NL}./config/settings.py", PROD),
])
def test_r01_the_hook_payload_cwd_inside_a_protected_directory_counts(
    command: str, cwd: str
) -> None:
    denied(command, "PROTECTED-PATH", cwd=cwd)


# ---------------------------------------------------------------------------------------------
# Copy, install and delete operands.
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    f"cp /tmp/x {NL}{MAIN}",
    f"cp {NL}/tmp/x {MAIN}",
    f"cp {NL}/tmp/x {NL}{MAIN}",
    f"cp -r /tmp/x {NL}/opt/crooks-os/app/",
    f"cp /tmp/x {NL}{MAIN} 2>/dev/null",  # F-6b and R-01 together
    f"cp /tmp/x {NL}{MAIN} >{NL}/tmp/log",
    f"install -m 644 /tmp/x {NL}{MAIN}",
    f"install -m 644 /tmp/x -t {NL}/etc/crooks-os",
    f"install {NL}-m 644 /tmp/x /etc/crooks-os/x",
    f"install /tmp/x {NL}/etc/systemd/system/x.service",
    f"rsync -a /tmp/x/ {NL}/opt/crooks-os/app/",
    f"scp /tmp/x {NL}/opt/crooks-os/app/x",
    f"mv /tmp/x {NL}{MAIN}",
    f"mv {NL}/tmp/x {MAIN}",
    f"sed -i s/a/b/ {NL}{MAIN}",
    f"truncate -s 0 {NL}{MAIN}",
    f"chmod 600 {NL}{MAIN}",
    f"touch {NL}/root/.claude/x",
    f"ln -sf /tmp/x {NL}/etc/crooks-os/x",
])
def test_r01_copy_install_and_write_operands(command: str) -> None:
    denied(command, "PROTECTED-PATH")


@pytest.mark.parametrize("command", [
    f"rm -rf {NL}/opt/crooks-os",
    f"rm {NL}-rf /opt/crooks-os",
    f"rm -r{NL}f /opt/crooks-os",
    f"rm -rf /opt/{NL}crooks-os",
    f"rm -rf /opt/crooks-os/{NL}app",
    f"rm -rf /tmp/x {NL}/opt/crooks-os",
    f"rm -rf {NL}/etc/crooks-os",
    f"rm -rf {NL}/root/.claude",
    f"rm -rf {NL}/",
    f"rm -rf {NL}/opt/crooks-builder",  # a checkout root, never deleted whole
    f"rm -rf -- {NL}/opt/crooks-os",
    f"r{NL}m -rf /opt/crooks-os",
])
def test_r01_recursive_delete_operands(command: str) -> None:
    denied(command, "RM-RECURSIVE")


@pytest.mark.parametrize(("command", "rule"), [
    (f"find {NL}/opt/crooks-os -name '*.pyc' -delete", "FIND-DELETE"),
    (f"find /opt/crooks-os {NL}-delete", "FIND-DELETE"),
    (f"git reset {NL}--hard", "GIT-RESET-HARD"),
    (f"git re{NL}set --hard", "GIT-RESET-HARD"),
    (f"git push {NL}--force origin claude/x", "GIT-PUSH-FORCE"),
    (f"git push origin {NL}main", "GIT-PUSH-PROTECTED-REF"),
    (f"git -C {NL}/opt/crooks-os add .", "PROTECTED-PATH"),
    (f"cat {NL}/etc/crooks-os/credentials/x", "SECRET-FILE-READ"),
    (f"cat {NL}.env", "SECRET-FILE-READ"),
    (f"systemctl {NL}restart crooks-assistant", "SERVICE-MUTATION"),
    (f"tailscale {NL}serve 8000", "TAILSCALE-MUTATION"),
    (f"claude {NL}mcp add x", "GLOBAL-CLAUDE-CONFIG"),
])
def test_r01_other_rules_read_the_joined_words(command: str, rule: str) -> None:
    denied(command, rule)


# ---------------------------------------------------------------------------------------------
# Double-quoted continuations are removed, as in bash.
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("command", "rule"), [
    (f'echo x >"{NL}{MAIN}"', "PROTECTED-PATH"),
    (f'echo x >"/opt/crooks-os/app/{NL}main.py"', "PROTECTED-PATH"),
    (f'echo x > "{NL}{MAIN}"', "PROTECTED-PATH"),
    (f'cp /tmp/x "{NL}{MAIN}"', "PROTECTED-PATH"),
    (f'cp "{NL}/tmp/x" "{NL}{MAIN}"', "PROTECTED-PATH"),
    (f'rm -rf "{NL}/opt/crooks-os"', "RM-RECURSIVE"),
    (f'rm -rf "/opt/{NL}crooks-os"', "RM-RECURSIVE"),
    (f'cd "{NL}/opt/crooks-os" && echo x >app/main.py', "PROTECTED-PATH"),
    (f'echo x >"/opt/crooks-os/app/"{NL}main.py', "PROTECTED-PATH"),  # quoted then unquoted
])
def test_r01_double_quoted_continuation_is_removed(command: str, rule: str) -> None:
    denied(command, rule)


# ---------------------------------------------------------------------------------------------
# Single-quoted continuations are literal, as in bash: kept in the word, and not overblocked.
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    f"echo 'a{NL}b'",
    f"printf '%s{NL}' a",
    f"echo 'a{NL}b' >/tmp/out",
    f"grep 'foo{NL}bar' /tmp/x",
    f"echo x >'{NL}/tmp/out'",  # a literal relative name under the builder, as bash reads it
    f"rm -rf '/tmp/scratch{NL}x'",  # a literal name under /tmp
    f"git commit -m 'one{NL}two'",
    f"python3 -c 'print(1){NL}'",
])
def test_r01_single_quoted_continuation_is_literal_and_allowed(command: str) -> None:
    allowed(command)


def test_r01_single_quoted_continuation_reaches_the_token_literally() -> None:
    assert gb._tokens(f"echo 'a{NL}b'")[0] == ["echo", "a\\\nb"]
    assert gb._tokens(f"echo x >'{NL}/tmp/out'")[0] == ["echo", "x", ">\\\n/tmp/out"]
    assert gb._redirect_targets(gb._tokens(f"echo x >'{NL}/tmp/out'")[0]) == ["\\\n/tmp/out"]


def test_r01_a_single_quoted_continuation_does_not_hide_a_target_after_it() -> None:
    denied(f"echo 'a{NL}b' >{NL}{MAIN}", "PROTECTED-PATH")
    denied(f"echo 'a{NL}b' >{MAIN}", "PROTECTED-PATH")
    denied(f"cp '/tmp/a{NL}b' {NL}{MAIN}", "PROTECTED-PATH")


# ---------------------------------------------------------------------------------------------
# A continuation inside an ordinary command or word; comments.
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    f"ec{NL}ho hi",
    f"ls {NL}-la /tmp",
    f"ls -l{NL}a /tmp",
    f"git {NL}status",
    f"git sta{NL}tus --short",
    f"python3 -m pytest {NL}tests -q",
    f"echo a{NL}#b",
    f"echo hi {NL}{NL}there",
    f"cp /tmp/a {NL}/tmp/b",
    f"echo x >{NL}/tmp/out",
    f"rm -rf {NL}/tmp/scratch/x",
    f"echo x >/tmp/out # note {NL}",
])
def test_r01_benign_continuations_stay_allowed(command: str) -> None:
    allowed(command)


@pytest.mark.parametrize(("command", "rule"), [
    (f"ec{NL}ho x >{MAIN}", "PROTECTED-PATH"),  # was already denied: the target token was clean
    (f"ec{NL}ho x >{NL}{MAIN}", "PROTECTED-PATH"),
    (f"# note {NL}echo x >{MAIN}", "PROTECTED-PATH"),  # a comment's backslash continues nothing
    (f"echo hi # trailing {NL}rm -rf /opt/crooks-os", "RM-RECURSIVE"),
    (f"echo hi; # trailing {NL}rm -rf /opt/crooks-os", "RM-RECURSIVE"),
])
def test_r01_command_word_and_comment_neighbours(command: str, rule: str) -> None:
    denied(command, rule)


def test_r01_a_hash_after_a_continuation_is_part_of_the_word() -> None:
    assert gb._tokens(f"echo a{NL}#b")[0] == ["echo", "a#b"]
    assert gb._segments(f"echo a{NL}#b")


# ---------------------------------------------------------------------------------------------
# Shell wrappers, shell strings, here-strings and heredocs.
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("command", "rule"), [
    (f"sudo cp /tmp/x {NL}{MAIN}", "PROTECTED-PATH"),
    (f"sudo {NL}rm -rf /opt/crooks-os", "RM-RECURSIVE"),
    (f"env FOO=1 {NL}cp /tmp/x {MAIN}", "PROTECTED-PATH"),
    (f"timeout 5 {NL}rm -rf /opt/crooks-os", "RM-RECURSIVE"),
    (f"nohup {NL}rm -rf /opt/crooks-os", "RM-RECURSIVE"),
    (f"bash -c 'echo x >{NL}{MAIN}'", "PROTECTED-PATH"),  # the inner shell removes the pair
    (f'bash -c "echo x >{NL}{MAIN}"', "PROTECTED-PATH"),  # the outer shell removes it
    (f"bash {NL}-c 'rm -rf /opt/crooks-os'", "RM-RECURSIVE"),
    (f"sh -c 'rm -rf {NL}/opt/crooks-os'", "RM-RECURSIVE"),
    (f"eval 'cp /tmp/x {NL}{MAIN}'", "PROTECTED-PATH"),
    (f"eval cp /tmp/x {NL}{MAIN}", "PROTECTED-PATH"),
    (f"bash <<< 'rm -rf {NL}/opt/crooks-os'", "RM-RECURSIVE"),
    (f"bash {NL}<<< 'rm -rf /opt/crooks-os'", "RM-RECURSIVE"),
    (f"watch {NL}rm -rf /opt/crooks-os", "RM-RECURSIVE"),
    (f"xargs {NL}rm -rf /opt/crooks-os </tmp/list", "RM-RECURSIVE"),
    (f"(cp /tmp/x {NL}{MAIN})", "PROTECTED-PATH"),
    (f"{{ cp /tmp/x {NL}{MAIN}; }}", "PROTECTED-PATH"),
    (f"true && cp /tmp/x {NL}{MAIN}", "PROTECTED-PATH"),
    (f"true || rm -rf {NL}/opt/crooks-os", "RM-RECURSIVE"),
    (f"ls | tee {NL}{MAIN}", "PROTECTED-PATH"),
    (f"echo $(cp /tmp/x {NL}{MAIN})", "PROTECTED-PATH"),
    (f'echo "$(cp /tmp/x {NL}{MAIN})"', "PROTECTED-PATH"),
])
def test_r01_wrappers_and_shell_text(command: str, rule: str) -> None:
    denied(command, rule)


@pytest.mark.parametrize(("command", "rule"), [
    (f"bash <<EOF\necho x >{NL}{MAIN}\nEOF", "PROTECTED-PATH"),
    (f"bash <<'EOF'\necho x >{NL}{MAIN}\nEOF", "PROTECTED-PATH"),
    (f"bash {NL}<<EOF\nrm -rf /opt/crooks-os\nEOF", "RM-RECURSIVE"),  # the owner, split
    (f"bash {NL}<<'EOF'\nrm -rf /opt/crooks-os\nEOF", "RM-RECURSIVE"),
    (f"sudo {NL}bash <<EOF\nrm -rf /opt/crooks-os\nEOF", "RM-RECURSIVE"),
    (f"cat <<EOF {NL}| bash\ngit reset --hard\nEOF", "GIT-RESET-HARD"),
    (f"cat {NL}<<EOF | bash\ngit reset --hard\nEOF", "GIT-RESET-HARD"),
    (f"cat <<EOF | {NL}bash\ngit reset --hard\nEOF", "GIT-RESET-HARD"),
    (f"python3 {NL}<<EOF\nimport os; os.system('rm -rf /opt/crooks-os')\nEOF",
     "INTERPRETER-PROTECTED-PATH"),
    # an unquoted body joins its continued line, so the shell runs everything up to the second
    # delimiter — including the write
    (f"bash <<EOF\nfoo {NL}EOF\necho x >{MAIN}\nEOF", "PROTECTED-PATH"),
    # a quoted body does not join: the heredoc ends at the first delimiter and the write runs
    (f"cat <<'EOF'\nfoo {NL}EOF\necho x >{MAIN}\nEOF", "PROTECTED-PATH"),
    # an escaped backslash is not a continuation: the body ends and the write runs
    (f"cat <<EOF\nfoo \\\\\nEOF\necho x >{MAIN}\nEOF", "PROTECTED-PATH"),
])
def test_r01_heredoc_neighbours(command: str, rule: str) -> None:
    denied(command, rule)


def test_r01_an_unquoted_prose_heredoc_body_joins_its_continued_line_as_bash_does() -> None:
    # bash reads `foo \` + `EOF` as one body line ("foo EOF"), so the document runs on to the
    # second delimiter and the write is text `cat` prints, not a command that runs
    # (witnessed below in test_r01_bash_witness).
    allowed(f"cat <<EOF\nfoo {NL}EOF\necho x >{MAIN}\nEOF")


# ---------------------------------------------------------------------------------------------
# The gitleaks gate shares the lexer: a continuation cannot launder a publish.
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    f"git {NL}push origin claude/x",
    f"git pu{NL}sh origin claude/x",
    f"git push {NL}origin claude/x",
    f"git push origin {NL}claude/x",
    f"git push origin claude/x {NL}&>/tmp/log",
    f"git push origin claude/x 2>{NL}/tmp/log",
    f"sudo {NL}git push origin claude/x",
    f"bash -c 'git {NL}push origin claude/x'",
    f"eval git {NL}push origin claude/x",
    f"cd /tmp/repo && git {NL}push origin claude/x",
])
def test_r01_the_gate_still_sees_a_push_across_a_continuation(command: str) -> None:
    actions = gate._publish_actions(command)
    assert [a[0] for a in actions] == ["push"], (command, actions)
    sub, rest, _chdir = actions[0]
    assert rest[:2] == ["origin", "claude/x"], (command, rest)  # no newline-prefixed operand


def test_r01_the_gate_reads_the_joined_commit_flags_and_paths() -> None:
    actions = gate._publish_actions(f"git commit -m x {NL}-a")
    assert actions == [("commit", ["-m", "x", "-a"], None)]
    actions = gate._publish_actions(f"git -C {NL}/tmp/repo push origin claude/x")
    assert actions == [("push", ["origin", "claude/x"], "/tmp/repo")]
    actions = gate._publish_actions(f"git commit -m 'one{NL}two'")
    assert actions == [("commit", ["-m", "one\\\ntwo"], None)]  # single-quoted: literal


def test_r01_the_gate_scans_a_push_whose_subcommand_follows_a_continuation(monkeypatch) -> None:
    scans: list[list[str]] = []

    def fake_scan(binary: str, repo: str, mode_args: list[str], deadline: float) -> gb.Decision:
        scans.append(mode_args)
        return gb.ALLOW

    monkeypatch.setattr(gate, "_scan", fake_scan)
    payload = json.dumps({"tool_name": "Bash", "tool_input": {
        "command": f"git {NL}push origin claude/x"}, "cwd": CWD}).encode()
    result = gate.run_gate(payload, gitleaks="/nonexistent/gitleaks")
    assert not result.denied
    assert scans == [["--log-opts=--all --not --remotes"]]


# ---------------------------------------------------------------------------------------------
# Nothing already closed reopens.
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "echo pwned>/opt/crooks-os/app/main.py",
    "cd /opt/crooks-os && printf x>>app/routes.py",
    "cp /tmp/x /opt/crooks-os/app/ 2>/dev/null",
])
def test_r01_f6_stays_closed(command: str) -> None:
    denied(command, "PROTECTED-PATH")


@pytest.mark.parametrize("command", [
    "ls 2>&1",
    "echo x>|/tmp/f",
    "cd /opt/crooks-os && git status 2>&1",
    "echo done>/tmp/log",
    "cat <<EOF\nplain prose\nEOF",
    "git push origin claude/x",
])
def test_r01_benign_forms_stay_allowed(command: str) -> None:
    allowed(command)


def test_r01_a_quoted_heredoc_body_is_not_joined() -> None:
    denied("cat <<'EOF'\nprose \\\nEOF\nrm -rf /opt/crooks-os\nEOF", "RM-RECURSIVE")


# ---------------------------------------------------------------------------------------------
# The finding as the hook process itself decides it (the review confirmed exit 0 before).
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("command", "rule"), R01_REVIEW_REPRODUCERS)
def test_the_hook_process_exits_2_for_the_r01_reproducers(command: str, rule: str) -> None:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command},
                          "cwd": CWD}).encode()
    proc = subprocess.run([sys.executable, str(HOOKS_DIR / "guard_bash.py")], input=payload,
                          capture_output=True, timeout=30, check=False)
    assert proc.returncode == 2, (command, proc.stdout, proc.stderr)
    assert proc.stdout == b""
    assert f"DENY [{rule}]".encode() in proc.stderr


def test_the_hook_process_exits_0_for_a_single_quoted_continuation() -> None:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": f"echo 'a{NL}b'"},
                          "cwd": CWD}).encode()
    proc = subprocess.run([sys.executable, str(HOOKS_DIR / "guard_bash.py")], input=payload,
                          capture_output=True, timeout=30, check=False)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)


# ---------------------------------------------------------------------------------------------
# Witness: real bash, on scratch files only, doing what the lexer now assumes it does.
# ---------------------------------------------------------------------------------------------

BASH = shutil.which("bash")


def _bash(script: str, cwd: Path) -> str:
    proc = subprocess.run([BASH, "-c", script], capture_output=True, text=True, timeout=30,
                          check=False, cwd=str(cwd))
    return proc.stdout


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_r01_bash_witness(tmp_path: Path) -> None:
    (tmp_path / "in.txt").write_text("x")
    # single-quoted: literal; double-quoted and unquoted: removed
    assert _bash("printf '%s' 'a\\\nb'", tmp_path) == "a\\\nb"
    assert _bash('printf "%s" "a\\\nb"', tmp_path) == "ab"
    assert _bash("pr\\\nintf '%s' N", tmp_path) == "N"
    # the four review shapes, against scratch names (the continuation joins the operand)
    assert _bash("printf x >\\\nout.txt", tmp_path) == "" and (tmp_path / "out.txt").read_text() == "x"
    assert _bash("printf x>\\\nout2.txt", tmp_path) == "" and (tmp_path / "out2.txt").read_text() == "x"
    _bash("cp in.txt \\\nout3.txt", tmp_path)
    assert (tmp_path / "out3.txt").read_text() == "x"
    (tmp_path / "d").mkdir()
    assert _bash("rm -rf \\\nd; test -e d || printf gone", tmp_path) == "gone"
    # an operator and a descriptor split by a continuation
    assert _bash("printf x >\\\n| out4.txt; cat out4.txt", tmp_path) == "x"
    assert _bash("printf x 2\\\n>err.txt; test -e err.txt && printf ok", tmp_path) == "xok"
    # a comment's backslash continues nothing; `#` after a continuation is mid-word
    assert _bash("# c \\\nprintf A", tmp_path) == "A"
    assert _bash("printf '%s' a\\\n#b", tmp_path) == "a#b"
    # a shell owns the heredoc across a continuation
    assert _bash("bash \\\n<<EOF\nprintf C\nEOF", tmp_path) == "C"
    # an unquoted body joins its continued line before the delimiter check; a quoted one does not
    assert _bash("cat <<EOF\nfoo \\\nEOF\nbar\nEOF", tmp_path) == "foo EOF\nbar\n"
    assert _bash("cat <<'EOF'\nfoo \\\nEOF\nprintf B", tmp_path) == "foo \\\nB"
