"""The third independent review of the harness candidate (fe96bb6, bridge inbox 5217469…,
verdict REJECT — REPAIR REQUIRED): one finding, F-6, with two compounding causes in the
guard's redirect handling. One negative test per reproducer, using the review's own command
strings; the operator × command × destination matrix the repair inbox asked for; positive
controls for the benign glued redirects that must stay allowed; and interaction tests showing
that the parser change does not reopen F-1 … F-5 or the heredoc / here-string / descriptor
redirect behaviour that already passed.

Every reproducer below was run against the source of fe96bb6 before the repair and was
ALLOWED; the same file passes after it. Nothing here touches git, the network, a service or a
real path: the guard reads text only. No secret value appears here.

Root cause, as the review reduced it and the repair addresses it:
  * bash treats an unquoted `>` (and `>>`, `>|`, `&>`, `&>>`, `>&`, `<>`) as a metacharacter:
    `echo x>f` is `echo x >f`. shlex does not, so the target of a redirect glued to a word was
    never extracted. The tokenizer now ends every word at an unquoted redirection operator
    (`_split_redirects`), keeping a bare descriptor number with its operator (`2>f`, `2>&1`),
    and the segmenter no longer splits `>|`, `&>`, `&>>`, `>&` at their `|` / `&`;
  * every output redirection is a write whatever the base command: the targets that
    `_redirect_targets` extracts are checked before, and independently of, the read-only
    classification, through the same `_write_target_problem` resolution as spaced redirects.
  * F-6b, found in the same function while repairing F-6: a redirect after a copy destination
    (`cp x /opt/crooks-os/app/ >log`, `… 2>/dev/null`) was read as the destination and the copy
    branch returned early, so the real destination was never checked. Operands are now read
    with redirections removed (`_without_redirections`).
  * F-6c, a regression the tokenizer change would otherwise have introduced: the heredoc owner
    read its words with plain shlex, so `cat <<EOF|bash` (glued `|`) was already ALLOWED and
    `cat<<EOF|bash` was refused only by accident. The owner now reads words through the
    shared segmenter/tokenizer, so both feed a shell like `cat <<EOF | bash`.
  * F-6d, in the disk rule: only a glued `>/dev/sda` was seen; the spaced `> /dev/sda` was
    ALLOWED. The rule now reads the same targets as the path rule.
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
# F-6 (H): the review's own reproducers, verbatim.
# ---------------------------------------------------------------------------------------------

F6_REVIEW_REPRODUCERS = [
    ("echo pwned>/opt/crooks-os/app/main.py", CWD),
    ("printf x>/etc/crooks-os/x", CWD),
    ("echo x>/root/.bashrc", CWD),
    ("cd /opt/crooks-os && echo pwned>app/main.py", CWD),
    ("cd /opt/crooks-os && printf x>>app/routes.py", CWD),
    ("cd /opt/crooks-os && cat /tmp/x>config/settings.py", CWD),
    ("cd /opt/crooks-os && echo x>{app,config}/main.py", CWD),
    ("echo pwned>main.py", PROD + "/app"),
]


@pytest.mark.parametrize(("command", "cwd"), F6_REVIEW_REPRODUCERS)
def test_f6_a_redirect_glued_to_a_word_is_a_protected_path(command: str, cwd: str) -> None:
    denied(command, "PROTECTED-PATH", cwd=cwd)


# ---------------------------------------------------------------------------------------------
# The matrix the repair inbox required: every operator, glued after a word, for echo / printf /
# cat, against relative destinations under a protected cwd and absolute destinations under
# each protected root.
# ---------------------------------------------------------------------------------------------

GLUED_OPERATORS = [">", ">>", ">|", "&>", "&>>", ">&", "<>"]
READ_ONLY_BASES = ["echo x", "printf x", "cat /tmp/x"]
ABSOLUTE_DESTINATIONS = ["/opt/crooks-os/app/main.py", "/etc/crooks-os/x", "/etc/hosts",
                         "/root/.bashrc", "/root/.claude/settings.json"]


@pytest.mark.parametrize("op", GLUED_OPERATORS)
@pytest.mark.parametrize("head", READ_ONLY_BASES)
@pytest.mark.parametrize("dest", ABSOLUTE_DESTINATIONS)
def test_f6_every_operator_glued_after_a_word_to_an_absolute_protected_path(
    op: str, head: str, dest: str
) -> None:
    denied(f"{head}{op}{dest}", "PROTECTED-PATH")


@pytest.mark.parametrize("op", GLUED_OPERATORS)
@pytest.mark.parametrize("head", READ_ONLY_BASES)
def test_f6_every_operator_glued_after_a_word_to_a_relative_path_under_a_protected_cwd(
    op: str, head: str
) -> None:
    denied(f"cd /opt/crooks-os && {head}{op}app/main.py", "PROTECTED-PATH")
    denied(f"cd /etc/crooks-os && {head}{op}settings.toml", "PROTECTED-PATH")
    denied(f"cd /root && {head}{op}notes.txt", "PROTECTED-PATH")


@pytest.mark.parametrize("op", GLUED_OPERATORS)
def test_f6_the_hook_payload_cwd_inside_a_protected_directory_counts(op: str) -> None:
    denied(f"echo x{op}main.py", "PROTECTED-PATH", cwd=PROD + "/app")
    denied(f"printf x{op}./config/settings.py", "PROTECTED-PATH", cwd=PROD)
    denied(f"cat /tmp/x{op}x", "PROTECTED-PATH", cwd="/etc/crooks-os")
    denied(f"echo x{op}.profile", "PROTECTED-PATH", cwd="/root")


@pytest.mark.parametrize("command", [
    # brace forms, glued
    "cd /opt/crooks-os && echo x>{app,config}/main.py",
    "echo x>/opt/{crooks-os,tmp}/x",
    "echo x>>/opt/crooks-os/{app,config}/main.py",
    # globs, glued
    "cd /opt/crooks-os && echo x>app/*.py",
    "echo x>/opt/crooks-os/app/main.p?",
    "echo x>/opt/crooks-*/app/main.py",
    # traversal, glued
    "cd /opt/crooks-builder && echo x>../crooks-os/app/main.py",
    "echo x>/tmp/../opt/crooks-os/app/main.py",
    "cd /opt && printf x>>crooks-os/app/main.py",
    "cd /tmp && cat /tmp/x>../etc/hosts",
    # home-anchored, glued
    "echo x>~/.bashrc",
    "echo x>$HOME/.profile",
    "echo x>${HOME}/.claude/settings.json",
])
def test_f6_brace_glob_traversal_and_home_forms_resolve_like_spaced_ones(command: str) -> None:
    denied(command, "PROTECTED-PATH")


def test_f6_an_unresolvable_glued_target_under_a_protected_cwd_fails_closed() -> None:
    denied("cd /opt/crooks-os/$X && echo x>main.py", "PROTECTED-CWD")
    denied("cd /opt/crooks-os && echo x>$OUT", "PROTECTED-CWD")
    denied("cd /opt/crooks-os && printf x>>$OUT/y", "PROTECTED-CWD")
    denied("echo x>$OUT", "PROTECTED-CWD", cwd=PROD)


@pytest.mark.parametrize("command", [
    # the review's non-read-only controls still deny, and glued now too
    "cd /opt/crooks-os && tee app/main.py",
    "cd /opt/crooks-os && dd of=app/main.py",
])
def test_f6_non_read_only_bases_under_a_protected_cwd_still_hit_the_backstop(command: str) -> None:
    denied(command, "PROTECTED-CWD")


@pytest.mark.parametrize("command", [
    "sudo echo x>/opt/crooks-os/app/main.py",  # behind a wrapper
    "env X=1 printf x>>/etc/hosts",
    "cd /opt/crooks-os && command cat /tmp/x>app/main.py",
    "bash -c 'echo x>/opt/crooks-os/app/main.py'",  # inside shell text the hook reads
    "eval 'echo x>/opt/crooks-os/app/main.py'",
    "sh -c 'cd /opt/crooks-os && echo x>app/main.py'",
    "echo x>/opt/crooks-os/app/main.py; ls",  # before a separator
    "ls; echo x>/opt/crooks-os/app/main.py",  # after one
    "true && echo x>/opt/crooks-os/app/main.py",
    "( echo x>/opt/crooks-os/app/main.py )",
    "{ echo x>/opt/crooks-os/app/main.py; }",
    "echo $(date)>/opt/crooks-os/app/main.py",  # a substitution in the word before
    "echo x>/opt/crooks-os/app/main.py>/tmp/log",  # two glued redirects
    "echo x>/tmp/log>/opt/crooks-os/app/main.py",
    "X=1>/opt/crooks-os/app/main.py",  # an assignment with a redirect and no command
    ">/opt/crooks-os/app/main.py",  # a redirect and nothing else truncates the file
])
def test_f6_the_glued_operator_is_found_in_every_command_shape(command: str) -> None:
    denied(command, "PROTECTED-PATH")


def test_f6_glued_redirects_into_the_write_sensitive_project_paths() -> None:
    denied("echo x>.claude/settings.json", "PROJECT-CLAUDE-WRITE")
    denied("printf x>>.claude/rules/a.md", "PROJECT-CLAUDE-WRITE")
    denied("echo x>.git/hooks/pre-commit", "GIT-HOOKS-WRITE")
    denied("cat /tmp/x>./.git/hooks/post-checkout", "GIT-HOOKS-WRITE")


# ---------------------------------------------------------------------------------------------
# F-6b (found in the same function): a redirect after a copy destination is not the destination.
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "cp /tmp/x /opt/crooks-os/app/ >/tmp/log",
    "cp /tmp/x /opt/crooks-os/app/ > /tmp/log",
    "cp /tmp/x /opt/crooks-os/app/main.py 2>/dev/null",
    "cp /tmp/x /opt/crooks-os/app/main.py 2>&1",
    "cp /tmp/x /opt/crooks-os/app/main.py >/dev/null 2>&1",
    "install /tmp/x /etc/crooks-os/x >/dev/null",
    "rsync -a /tmp/d/ /opt/crooks-os/app/ >>/tmp/log",
    "cd /opt/crooks-os && cp /tmp/x app/main.py 2>/dev/null",
    "cd /opt/crooks-os && cp /tmp/x . >/tmp/log",
])
def test_f6b_a_trailing_redirect_does_not_hide_the_copy_destination(command: str) -> None:
    denied(command, "PROTECTED-PATH")


def test_f6b_copies_to_benign_destinations_with_redirects_stay_allowed() -> None:
    allowed("cp a b >/tmp/log")
    allowed("cp a b 2>/dev/null")
    allowed("cp /opt/crooks-os/app/main.py /tmp/ >/dev/null 2>&1")
    allowed("rsync -a ./dist/ host:/srv/x >/tmp/log")
    allowed("scp x host:y 2>&1")
    allowed("install -m 644 x dist/x >/dev/null")


# ---------------------------------------------------------------------------------------------
# Positive controls: benign glued redirects stay allowed.
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "echo x>out.txt",
    "cd /tmp && echo x>y",
    "echo done>/tmp/log",
    "printf x>>/tmp/log",
    "cat a>b",
    "cat a>>b",
    "echo x>|/tmp/y",
    "echo x&>/tmp/y",
    "echo x&>>/tmp/y",
    "echo x>&/tmp/y",
    "echo x<>/tmp/y",
    "echo x>/var/tmp/y",
    "echo x>dist/out.txt",
    "echo x>./out.txt",
    "git log>/tmp/log.txt",
    "pytest -q>/tmp/pytest.log",
    "ruff check app>/tmp/ruff.txt",
    "cd /opt/crooks-os && cat app/main.py>/tmp/copy.py",  # a read out of production
    "cd /opt/crooks-os && git log>/tmp/log.txt",
    "cd /opt/crooks-os && ls>/dev/null",
    "cd /opt/crooks-os && cd /tmp && echo x>y",
    "echo x>/dev/null",
    "echo x>/dev/stderr",
])
def test_f6_benign_glued_redirects_stay_allowed(command: str) -> None:
    allowed(command)


@pytest.mark.parametrize("command", [
    "echo 'x>/opt/crooks-os/app/main.py'",  # quoted: text, not a redirect
    'echo "x>/opt/crooks-os/app/main.py"',
    "echo x\\>/opt/crooks-os/app/main.py",  # escaped: text
    "grep -c 'a>b' /tmp/f",
    'echo "a>b" "c>>d"',
    "awk '{ if ($1>2) print }' /tmp/f",
    "cd /opt/crooks-os && echo 'x>app/main.py'",
    "cd /opt/crooks-os && grep -rn 'a>b' app",
])
def test_f6_quoted_and_escaped_operators_are_text(command: str) -> None:
    allowed(command)


def test_f6_a_quoted_bare_operator_is_still_read_as_one_after_shlex() -> None:
    # Known and unchanged: shlex drops the quotes, so a word that is exactly `'>'` is
    # indistinguishable from the operator afterwards and the next word is taken as its
    # target. This is a false denial (fail closed), the same on fe96bb6 and here.
    denied("cd /opt/crooks-os && grep -rn '>' app", "PROTECTED-PATH")
    allowed("grep -rn '>' /tmp/f")


# ---------------------------------------------------------------------------------------------
# The tokenizer and segmenter, unit-level: the word ends where bash ends it.
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("segment", "words"), [
    ("echo x>f", ["echo", "x", ">f"]),
    ("echo x>>f", ["echo", "x", ">>f"]),
    ("echo x>|f", ["echo", "x", ">|f"]),
    ("echo x&>f", ["echo", "x", "&>f"]),
    ("echo x&>>f", ["echo", "x", "&>>f"]),
    ("echo x>&f", ["echo", "x", ">&f"]),
    ("echo x<>f", ["echo", "x", "<>f"]),
    ("echo x>a>b", ["echo", "x", ">a", ">b"]),
    ("echo x> f", ["echo", "x", ">", "f"]),
    ("'ls'>f", ["ls", ">f"]),
    ('echo "2">f', ["echo", "2", ">f"]),  # a quoted 2 is a word, not a descriptor
    ("echo x2>f", ["echo", "x2", ">f"]),  # `x2` is a word, not a descriptor
    ("echo \\2>f", ["echo", "2", ">f"]),  # an escaped 2 is a word
    ("ls 2>f", ["ls", "2>f"]),  # a bare descriptor number keeps its operator
    ("ls 2>>f", ["ls", "2>>f"]),
    ("ls 2>&1", ["ls", "2>&1"]),
    ("ls 12>&1", ["ls", "12>&1"]),
    ("echo x>&2", ["echo", "x", ">&2"]),
    ("echo x >& 2", ["echo", "x", ">&", "2"]),
    ("echo 2&>f", ["echo", "2", "&>f"]),  # `&>` takes no descriptor
    ("echo x\\>f", ["echo", "x>f"]),  # escaped: text
    ("echo 'x>f'", ["echo", "x>f"]),  # quoted: text
    ('echo "x>f"', ["echo", "x>f"]),
    ("echo x'>'f", ["echo", "x>f"]),
    ("echo $SUBST>f", ["echo", "$SUBST", ">f"]),  # the substitution marker is a word
    ("bash<<<'ls'", ["bash", "<<<ls"]),  # a glued here-string reaches the shell rule
    ("cat<<EOF", ["cat", "<<EOF"]),
    ("cat<<-EOF", ["cat", "<<-EOF"]),
    ("cat<f", ["cat", "<f"]),
    ("cat 0<&3", ["cat", "0<&3"]),
    ("X=1>f", [">f"]),  # the assignment is popped; the redirect remains
    ("echo x >f", ["echo", "x", ">f"]),  # already spaced: unchanged
    ("echo x > f", ["echo", "x", ">", "f"]),
])
def test_f6_the_tokenizer_ends_a_word_at_an_unquoted_redirection(segment: str,
                                                                    words: list[str]) -> None:
    assert gb._tokens(segment)[0] == words


def test_f6_the_split_only_inserts_spaces() -> None:
    for segment in ["echo x>f", "echo x>|f&>g>&h<>i", "'a>b'c>d", "echo x", "2>f 3>>g"]:
        split = gb._split_redirects(segment)
        assert split.replace(" ", "") == segment.replace(" ", ""), (segment, split)


@pytest.mark.parametrize(("text", "segments"), [
    ("echo x>|f", [("echo x>|f", False)]),  # `>|` is the clobber operator, not a pipe
    ("echo x >| f", [("echo x >| f", False)]),
    ("echo x&>f", [("echo x&>f", False)]),  # `&>` is a redirection, not a background `&`
    ("echo x &> f", [("echo x &> f", False)]),
    ("echo x&>>f", [("echo x&>>f", False)]),
    ("echo x>&f", [("echo x>&f", False)]),
    ("ls 2>&1", [("ls 2>&1", False)]),
    ("cat 0<&3", [("cat 0<&3", False)]),
    ("a | b", [("a", False), ("b", True)]),  # the ordinary operators are unchanged
    ("a|b", [("a", False), ("b", True)]),
    ("a & b", [("a", False), ("b", False)]),
    ("a && b", [("a", False), ("b", False)]),
    ("a || b", [("a", False), ("b", False)]),
    ("a; b", [("a", False), ("b", False)]),
    ("echo 'x>|y'", [("echo 'x>|y'", False)]),
    ('echo "x&>y"', [('echo "x&>y"', False)]),
    ("echo x\\>|cat", [("echo x\\>", False), ("cat", True)]),  # an escaped `>` is text: `|` pipes
    ("echo x>>|cat", [("echo x>>", False), ("cat", True)]),  # `>>|` is `>>` then a pipe, as in bash
    ("echo x> |cat", [("echo x>", False), ("cat", True)]),
])
def test_f6_the_segmenter_keeps_redirection_operators_whole(text: str,
                                                            segments: list[tuple[str, bool]]) -> None:
    assert gb._segments(text) == segments


def test_f6_redirect_targets_are_read_from_either_token_shape() -> None:
    assert gb._redirect_targets(["echo", "x", ">f"]) == ["f"]
    assert gb._redirect_targets(["echo", "x", ">", "f"]) == ["f"]
    assert gb._redirect_targets(["ls", "2>err", "1>out"]) == ["err", "out"]
    assert gb._redirect_targets(["ls", "2>>", "err"]) == ["err"]
    assert gb._redirect_targets(["echo", "x", ">|f", "&>g", "&>>h", "<>i"]) == ["f", "g", "h", "i"]
    assert gb._redirect_targets(["echo", "x", ">&f"]) == ["f"]  # `>&word` is `&>word`
    assert gb._redirect_targets(["echo", "x", ">&", "f"]) == ["f"]
    assert gb._redirect_targets(["ls", "2>&1", ">&2", ">&-", "3>&", "1"]) == []  # descriptors
    assert gb._redirect_targets(["echo", "x", ">"]) == []  # nothing after the operator
    assert gb._redirect_targets(["cat", "<f", "<<EOF", "<<<x"]) == []  # input, not output
    assert gb._without_redirections(["cp", "a", "b", ">log", "2>&1"]) == ["cp", "a", "b"]
    assert gb._without_redirections(["cp", "a", "b", ">", "log"]) == ["cp", "a", "b"]
    assert gb._without_redirections(["cp", "a", "<in", "b"]) == ["cp", "a", "b"]


# ---------------------------------------------------------------------------------------------
# Interaction: the parser change does not reopen F-1 … F-5.
# ---------------------------------------------------------------------------------------------

def test_f1_spaced_and_copy_forms_still_resolve_against_the_cwd() -> None:
    denied("cd /opt/crooks-os && echo pwned > app/main.py", "PROTECTED-PATH")
    denied("cd /opt/crooks-os && echo x &> app/log", "PROTECTED-PATH")
    denied("cd /opt/crooks-os && ls 2> app/err", "PROTECTED-PATH")
    denied("cd /opt/crooks-os && cp /tmp/x app/main.py", "PROTECTED-PATH")
    denied("cd /opt && echo x > crooks-os/app/main.py", "PROTECTED-PATH")
    denied("echo x > app/main.py", "PROTECTED-PATH", cwd=PROD)
    denied("cd /opt/crooks-os/$X && echo x > main.py", "PROTECTED-CWD")
    allowed("cd /opt/crooks-os && cat app/main.py > /tmp/copy.py")


@pytest.mark.parametrize("command", [
    "$(echo 'git push --force origin main')>/tmp/log",  # F-2: still the command word
    "`echo 'git reset --hard'`>/tmp/log",
    "$(echo git)>/tmp/log push --force origin main",
    "sudo $(echo git) push --force origin main>/tmp/log",  # F-3
    "env X=1 $(echo systemctl) restart crooks-assistant>/tmp/log",
    "p=push; git $p --force origin main>/tmp/log",  # F-4
    "git ${SUB} --hard>/tmp/log",
    "git $(echo push) --force origin main 2>&1",
])
def test_f2_f3_f4_dynamic_command_words_are_still_unparseable_with_a_redirect(command: str) -> None:
    denied(command, "UNPARSEABLE")


def test_f2_the_substitution_body_is_still_evaluated_with_a_glued_redirect() -> None:
    denied("echo $(rm -rf /opt/crooks-os)>/tmp/x", "RM-RECURSIVE")
    denied("$(rm -rf /opt/crooks-os)>/tmp/x", "RM-RECURSIVE")
    denied('echo "$(git reset --hard)">/tmp/x', "GIT-RESET-HARD")
    allowed("echo $(date)>/tmp/x")
    allowed("HEAD=$(git rev-parse HEAD); echo $HEAD>/tmp/head")


def test_f4_a_literal_git_subcommand_with_a_redirect_still_reads_its_flags() -> None:
    denied("git push --force origin $BRANCH>/tmp/log", "GIT-PUSH-FORCE")
    denied("git push --force origin main 2>&1", "GIT-PUSH-FORCE")
    denied("git reset --hard>/tmp/log", "GIT-RESET-HARD")
    denied("git push origin main>/tmp/log", "GIT-PUSH-PROTECTED-REF")
    allowed("git push origin claude/harness-hooks-experiment>/tmp/log")
    allowed("git push origin claude/harness-hooks-experiment 2>&1 | tee /tmp/log")
    allowed("git log --oneline -5>/tmp/log")
    allowed("git commit -m msg>/tmp/log")


def test_f5_the_gate_still_sees_a_publish_through_a_redirect() -> None:
    def subs(command: str) -> list[str]:
        return [a[0] for a in gate._publish_actions(command)]

    assert subs("git push origin x>/tmp/log") == ["push"]
    assert subs("git push origin x 2>&1") == ["push"]
    assert subs("git push origin x 2>&1 | tee /tmp/log") == ["push"]
    assert subs("git commit -m msg>/tmp/log") == ["commit"]
    assert subs("bash -c 'git push origin x'>/tmp/log") == ["push"]
    assert subs("bash<<<'git push origin x'") == ["push"]
    assert subs("echo x>/tmp/log") == []
    for laundered in ["$(echo 'git push origin x')>/tmp/log", "git $(echo push) origin x>/tmp/log",
                      "sudo $(echo git) push origin x 2>&1"]:
        with pytest.raises(ValueError):
            gate._publish_actions(laundered)


# ---------------------------------------------------------------------------------------------
# Interaction: heredoc, here-string and descriptor redirect behaviour is preserved.
# ---------------------------------------------------------------------------------------------

def test_heredocs_keep_their_owner_logic_with_glued_and_spaced_operators() -> None:
    denied("sh <<'EOF'\ngit reset --hard\nEOF", "GIT-RESET-HARD")
    denied("sh<<'EOF'\ngit reset --hard\nEOF", "GIT-RESET-HARD")
    denied("cat <<EOF | bash\ngit reset --hard\nEOF", "GIT-RESET-HARD")
    # F-6c: the owner logic read its words with plain shlex, so a `|bash` glued to the
    # delimiter was invisible. `cat <<EOF|bash` was ALLOWED on fe96bb6; `cat<<EOF|bash` was
    # UNPARSEABLE there only by accident and would have become ALLOWED with the F-6 tokenizer.
    denied("cat <<EOF|bash\ngit reset --hard\nEOF", "GIT-RESET-HARD")
    denied("cat<<EOF|bash\ngit reset --hard\nEOF", "GIT-RESET-HARD")
    denied("cat<<'EOF'|sh\ngit reset --hard\nEOF", "GIT-RESET-HARD")
    denied("cat <<EOF|python3\nimport os; os.environ['SHOPIFY_TOKEN']\nEOF",
           "INTERPRETER-SECRET-READ")
    assert gb._heredoc_owner("cat<<EOF|bash") == "shell"
    assert gb._heredoc_owner("cat <<EOF|bash") == "shell"
    assert gb._heredoc_owner("cat <<EOF|python3") == "code"
    assert gb._heredoc_owner("cat<<EOF>/tmp/x") == "prose"
    assert gb._heredoc_owner("cat <<EOF | bash") == "shell"  # the spaced forms are unchanged
    assert gb._heredoc_owner("cat > notes.md <<'EOF'") == "prose"
    denied("cat > x <<EOF\n$(rm -rf /tmp)\nEOF", "RM-RECURSIVE")
    denied("cat>/opt/crooks-os/app/main.py <<'EOF'\nx\nEOF", "PROTECTED-PATH")
    denied("cat>>app/main.py <<'EOF'\nx\nEOF", "PROTECTED-PATH", cwd=PROD)
    allowed("cat > notes.md <<'EOF'\ngit reset --hard is destructive\nrm -rf / too\nEOF")
    allowed("cat>notes.md <<'EOF'\ngit reset --hard is destructive\nEOF")
    allowed("cat <<-EOF\n\tDROP TABLE users;\n\tEOF")
    allowed("cat<<EOF>/tmp/x\nhello\nEOF")


def test_here_strings_keep_their_semantics_and_the_glued_form_now_reaches_them() -> None:
    denied("bash <<< 'git reset --hard'", "GIT-RESET-HARD")
    denied("bash <<<'git reset --hard'", "GIT-RESET-HARD")
    denied("bash<<<'git reset --hard'", "GIT-RESET-HARD")  # ALLOWED on fe96bb6: word was `bash<<<…`
    denied('bash <<< "$X"', "UNPARSEABLE")
    denied('bash<<<"$X"', "UNPARSEABLE")
    denied('cat <<< "$SHOPIFY_TOKEN"', "SECRET-ECHO")
    allowed("echo done <<< 'rm -rf /'")
    allowed("echo done<<<'rm -rf /'")
    allowed("grep x <<< 'git reset --hard'")


def test_descriptor_redirects_are_descriptors_not_targets() -> None:
    allowed("ls 2>&1")
    allowed("ls 2>&1 | head")
    allowed("echo x>&2")
    allowed("echo x >&2")
    allowed("echo x 1>&2")
    allowed("ls 2>&-")
    allowed("cat 0<&3")
    allowed("cd /opt/crooks-os && ls 2>&1")  # PROTECTED-CWD on fe96bb6: `1` became a command word
    allowed("cd /opt/crooks-os && git status 2>&1")
    allowed("cd /opt/crooks-os && echo x>&2")
    denied("cd /opt/crooks-os && ls 2>app/err", "PROTECTED-PATH")
    denied("cd /opt/crooks-os && ls 2>>app/err", "PROTECTED-PATH")
    denied("ls 2>/etc/hosts", "PROTECTED-PATH")
    denied("ls 2>&/opt/crooks-os/app/log", "PROTECTED-PATH")  # `>&word` writes the word
    denied("echo x >& /root/.profile", "PROTECTED-PATH")
    allowed("ls 2>/tmp/err")
    allowed("ls 2>&/tmp/err")
    allowed("echo x >& /tmp/y")


def test_shell_text_skips_a_redirect_operand_and_still_finds_the_code() -> None:
    denied("bash -c 'git reset --hard' >& /tmp/log", "GIT-RESET-HARD")
    denied("bash >& /tmp/log -c 'git reset --hard'", "GIT-RESET-HARD")
    denied("bash 2>&1 -c 'git reset --hard'", "GIT-RESET-HARD")
    denied("bash -c 'git reset --hard'>/tmp/log", "GIT-RESET-HARD")
    denied("bash 2>/tmp/err -c 'git reset --hard'", "GIT-RESET-HARD")


def test_earlier_redirect_rules_still_hold() -> None:
    denied("echo x >> ~/.ssh/authorized_keys", "PROTECTED-PATH")
    denied("echo x>>~/.ssh/authorized_keys", "PROTECTED-PATH")
    denied("echo x 2>> /root/.profile", "PROTECTED-PATH")
    denied("echo x &>> /root/.profile", "PROTECTED-PATH")
    denied("printf x > .claude/settings.json", "PROJECT-CLAUDE-WRITE")
    # F-6d: the disk rule read only glued tokens, so the spaced `> /dev/sda` was ALLOWED on
    # fe96bb6. It now reads the same targets as the path rule.
    denied("cat /tmp/x > /dev/sda", "DISK-DESTRUCTIVE")
    denied("cat /tmp/x>/dev/sda", "DISK-DESTRUCTIVE")
    denied("cat /tmp/x >> /dev/nvme0n1", "DISK-DESTRUCTIVE")
    denied("dd if=/tmp/x of=/dev/sda", "DISK-DESTRUCTIVE")
    allowed("cat /tmp/x > /dev/null")
    denied("ls /etc/crooks-os/secrets>/tmp/x", "SECRET-FILE-READ")
    denied("echo x>/etc/crooks-os/secrets/x", "SECRET-FILE-READ")


# ---------------------------------------------------------------------------------------------
# The finding as the hook process itself decides it (the review confirmed ALLOW before).
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("command", "cwd"), [
    ("echo pwned>/opt/crooks-os/app/main.py", CWD),
    ("cd /opt/crooks-os && echo pwned>app/main.py", CWD),
    ("echo pwned>main.py", PROD + "/app"),
    ("cp /tmp/x /opt/crooks-os/app/ >/tmp/log", CWD),
])
def test_the_hook_process_exits_2_for_the_f6_reproducers(command: str, cwd: str) -> None:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command},
                          "cwd": cwd}).encode()
    proc = subprocess.run([sys.executable, str(HOOKS_DIR / "guard_bash.py")], input=payload,
                          capture_output=True, timeout=30, check=False)
    assert proc.returncode == 2, (command, proc.stdout, proc.stderr)
    assert proc.stdout == b""
    assert b"DENY" in proc.stderr
    assert b"pwned" not in proc.stderr  # a reason never echoes the command text


def test_the_hook_process_exits_0_for_a_benign_glued_redirect() -> None:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo done>/tmp/log"},
                          "cwd": CWD}).encode()
    proc = subprocess.run([sys.executable, str(HOOKS_DIR / "guard_bash.py")], input=payload,
                          capture_output=True, timeout=30, check=False)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
