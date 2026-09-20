"""The fifth independent review of the harness candidate (c16d6db, bridge inbox b8cd403…,
verdict REJECT — REPAIR REQUIRED): two findings, both pre-existing, both repaired here.

A-01 (HIGH) — the copy branch of `_path_rule` read the LAST operand of `cp`/`install` as the
destination, so `install -t /etc/crooks-os /tmp/x` — coreutils' own spelling for placing a
file into a system directory — was ALLOWED: `-t DIR` copies every operand INTO DIR, and DIR
is not last. The repair reads coreutils' option grammar (`COPY_OPTIONS`, `_copy_destinations`):
`-t DIR`, `-tDIR`, `--target-directory DIR`, `--target-directory=DIR`, any bundle (`-rt DIR`)
and any abbreviation GNU getopt accepts (`--targ DIR`, `--t=DIR`); an option's value is never
an operand (`install x DIR -m 644` writes DIR, not `644`); `install -d` makes every operand a
directory; `--` ends the options; a line the table cannot read checks every operand. Scoped
to `cp` and `install` only: rsync's `-t` is `--times` and scp's sink mode names its directory
last, so for both the last operand stays the destination.

A-02 (MEDIUM) — the shared scanners did not open a nested context for a substitution inside
double quotes, so `echo "$(echo "it's")" >/opt/crooks-os/app/main.py` followed by a line with
one more apostrophe left the quote state believing the redirect was inside a single-quoted
string: the command was ALLOWED while bash writes production on line 1 before failing on
line 2 (witnessed below). The repair is parser-level, in one rule shared by every scanner
(see the comment block above `_unquoted_heredoc_ops` in guard_bash.py): a `$( … )` or
backtick substitution, unquoted or inside double quotes, is a command of its own with fresh
quote/comment/paren state, and the enclosing state resumes after it; the segmenter emits its
body as segments and puts the marker in its place, so the tokenizer never meets a nested
quote. A malformed quote later in the text can no longer reach back over an executable
redirect; it makes the whole command UNPARSEABLE (fail closed).

Two directly adjacent siblings in the same scanner (the heredoc-operator reader), found while
making its state bash-appropriate and repaired by the same change: a `<<EOF` inside a comment
(`echo hi # <<EOF`) read the following lines as a heredoc body although bash runs them as
commands; and a `<<EOF` inside a backtick substitution that closes on its line did the same
(bash parses that text on its own; the following lines are commands). Both hid an
`rm -rf /opt/crooks-os`. Witnessed with real bash below.

Every reproducer below was run against the hooks of c16d6db before the repair; the ones the
review found, and the neighbours that fail for the same reason, were ALLOWED (or, for the
gitleaks gate, found no publish). The same file passes after the repair. Nothing here touches
git, the network, a service or a real protected path: the guard reads text only, and the
witnesses write only under pytest's tmp_path. No secret value appears here.
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
PROTECTED_ROOTS = ["/etc/crooks-os", "/opt/crooks-os/app", "/etc/systemd/system", "/root/.claude",
                   "/etc", "/root", "~/.claude", "$HOME/.claude"]


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


def run_hook(command: str, cwd: str = CWD) -> subprocess.CompletedProcess[str]:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}
    return subprocess.run([sys.executable, str(HOOKS_DIR / "guard_bash.py")],
                          input=json.dumps(payload), capture_output=True, text=True,
                          timeout=30, check=False)


# ---------------------------------------------------------------------------------------------
# A-01 (H): the review's own reproducers, verbatim.
# ---------------------------------------------------------------------------------------------

A01_REVIEW_REPRODUCERS = [
    "install -t /etc/crooks-os /tmp/x",
    "install -t /opt/crooks-os/app /tmp/x",
    "install --target-directory=/opt/crooks-os/app /tmp/x",
    "install --target-directory /root/.claude /tmp/x",
    "install -t /etc/systemd/system /tmp/x.service",
    "cp -t /opt/crooks-os/app /tmp/x",
    "cp -t /etc/crooks-os /tmp/x",
    "cp --target-directory=/opt/crooks-os/app /tmp/x",
    "install -m 644 -t /etc/crooks-os /tmp/x /tmp/y",
]


@pytest.mark.parametrize("command", A01_REVIEW_REPRODUCERS)
def test_a01_a_target_directory_is_the_destination(command: str) -> None:
    denied(command, "PROTECTED-PATH")


@pytest.mark.parametrize("command", A01_REVIEW_REPRODUCERS)
def test_a01_the_hook_process_exits_2_for_the_review_reproducers(command: str) -> None:
    proc = run_hook(command)
    assert proc.returncode == 2, proc
    assert "PROTECTED-PATH" in proc.stderr
    assert "/tmp/x" not in proc.stderr  # the reason never echoes what the model typed


@pytest.mark.parametrize("command", [
    "install -m 644 /tmp/x /etc/crooks-os/x",
    "cp /tmp/x /opt/crooks-os/app/main.py",
])
def test_a01_the_review_controls_stay_denied(command: str) -> None:
    denied(command, "PROTECTED-PATH")


# Every spelling coreutils accepts, for both commands, into every protected root.

A01_SPELLINGS = [
    "{cmd} -t {dir} /tmp/x",  # short form, separate value
    "{cmd} -t{dir} /tmp/x",  # short form, attached value
    "{cmd} --target-directory {dir} /tmp/x",  # long form, separate value
    "{cmd} --target-directory={dir} /tmp/x",  # long form, equals value
    "{cmd} -t {dir} /tmp/x /tmp/y /tmp/z",  # multi-source
    "{cmd} /tmp/x -t {dir}",  # option after the operand: getopt permutes
    "{cmd} /tmp/x /tmp/y --target-directory={dir}",
    "{cmd} -vt {dir} /tmp/x",  # bundled with a flag
    "{cmd} -v -t {dir} -- /tmp/x",  # `--` ends the options; the target came before it
    "{cmd} --targ {dir} /tmp/x",  # an abbreviation getopt accepts
    "{cmd} --t={dir} /tmp/x",
    "{cmd} --target={dir} /tmp/x",
    "sudo {cmd} -t {dir} /tmp/x",  # behind a passthrough wrapper
    "{cmd} -t {dir} /tmp/x >/tmp/log",  # a redirection after it is not the destination
    "{cmd} -t {dir} /tmp/x 2>/dev/null",
    "{cmd} -t {NL}{dir} /tmp/x",  # with the R-01 continuation before the value
]


@pytest.mark.parametrize("spelling", A01_SPELLINGS)
@pytest.mark.parametrize("cmd", ["cp", "install"])
@pytest.mark.parametrize("root", PROTECTED_ROOTS)
def test_a01_every_spelling_into_every_protected_root(spelling: str, cmd: str, root: str) -> None:
    denied(spelling.format(cmd=cmd, dir=root, NL=NL), "PROTECTED-PATH")


@pytest.mark.parametrize("command", [
    "cp -rt /opt/crooks-os/app /tmp/x",
    "cp -Rvt /opt/crooks-os/app /tmp/x",
    "cp -at /etc/crooks-os /tmp/x",
    "cp -rft/etc/crooks-os /tmp/x",
    "install -D -t /etc/crooks-os /tmp/x",
    "install -o root -g root -m 0644 -t /etc/crooks-os /tmp/x",
    "install -m644 -t /etc/crooks-os /tmp/x",  # `-m` takes the rest of its bundle as the value
    "install -m 644 -o root -t /etc/systemd/system /tmp/x.service",
    "install -pt /etc/crooks-os /tmp/x",
    "cp --no-clobber --target-directory /opt/crooks-os/app /tmp/x",
    "cp --preserve=all -t /opt/crooks-os/app /tmp/x",
    "cp --backup -t /opt/crooks-os/app /tmp/x",  # `--backup` takes no separate value
    "cp --sparse always -t /opt/crooks-os/app /tmp/x",  # `--sparse` takes a separate value
    "cp -S .bak -t /opt/crooks-os/app /tmp/x",
    "cp -t /opt/crooks-os/app -t /tmp/ok /tmp/x",  # every target named is checked
    "cp -t /tmp/ok -t /opt/crooks-os/app /tmp/x",
])
def test_a01_bundles_values_and_other_options_around_the_target(command: str) -> None:
    denied(command, "PROTECTED-PATH")


@pytest.mark.parametrize("command", [
    "install /tmp/x /etc/crooks-os/x -m 644",  # the value of `-m` is not the last operand
    "install /tmp/x /etc/crooks-os/x -m644",
    "install /tmp/x /etc/crooks-os/x --mode 644",
    "install /tmp/x /etc/crooks-os/x -o root -g root",
    "cp /tmp/x /opt/crooks-os/app/main.py --suffix bak",
    "cp /tmp/x /opt/crooks-os/app/main.py -S bak",
    "cp /tmp/x /opt/crooks-os/app/main.py --sparse never",
    "install -d /etc/crooks-os/newdir /tmp/b",  # `-d`: every operand is a directory to create
    "install --directory /etc/crooks-os/newdir /tmp/b",
    "install -dm 755 /etc/crooks-os/newdir /tmp/b",
    "install -d /tmp/a /root/.claude/b /tmp/c",
])
def test_a01_an_option_value_is_never_read_as_the_destination(command: str) -> None:
    # Adjacent to A-01, same function, same root cause (the option grammar was not read):
    # coreutils permutes options after operands, so the last word of these lines is an
    # option's value and the real destination sits before it. Witnessed with real coreutils
    # below.
    denied(command, "PROTECTED-PATH")


@pytest.mark.parametrize("command", [
    "cp --frobnicate /tmp/x /opt/crooks-os/app/main.py",
    "cp --frobnicate /opt/crooks-os/app/main.py /tmp/x",  # unknown option: every operand is checked
    "install -q -t /etc/crooks-os /tmp/x",
    "install -q /opt/crooks-os/app/main.py /tmp/x",
])
def test_a01_a_line_the_table_cannot_read_checks_every_operand(command: str) -> None:
    denied(command, "PROTECTED-PATH")


@pytest.mark.parametrize(("command", "rule"), [
    ("cp -t app /tmp/x", "PROTECTED-PATH"),  # relative target, resolved under the cwd (F-1)
    ("cp -t . /tmp/x", "PROTECTED-PATH"),
    ("install -t ./config /tmp/x", "PROTECTED-PATH"),
    ("cd /opt/crooks-os && cp -t app /tmp/x", "PROTECTED-PATH"),
])
def test_a01_a_relative_target_is_resolved_where_the_shell_resolves_it(command: str,
                                                                         rule: str) -> None:
    denied(command, rule, cwd=PROD)


@pytest.mark.parametrize("command", [
    "cp -t /tmp/a /tmp/x",
    "cp -t /tmp/a /tmp/x /tmp/y",
    "cp -t . /tmp/x",
    "cp -t /var/tmp/out /opt/crooks-os/app/main.py",  # a copy OUT of production is a read
    "cp -t /tmp/out /opt/crooks-os/app/main.py /opt/crooks-os/app/x.py",
    "install -t /tmp/a /tmp/x /tmp/y",
    "install -m 644 -t /tmp/a /tmp/x",
    "install -m644 /tmp/x /tmp/y",
    "install /tmp/x /tmp/y -m 644",
    "cp /tmp/x /tmp/y --suffix bak",
    "cp -S .bak /tmp/x /tmp/y",
    "cp --sparse always /tmp/x /tmp/y",
    "install -d /tmp/a /tmp/b",
    "cp -T /tmp/x /tmp/y",
    "cp --no-target-directory /tmp/x /tmp/y",
    "cp /opt/crooks-os/app/main.py /tmp/",
    "cp -r /opt/crooks-os/app /tmp/copy",
    "cp -- /tmp/x /tmp/y",
    "cp -t",  # coreutils refuses this line; nothing is written
    "cp --target-directory",
])
def test_a01_ordinary_safe_copies_stay_allowed(command: str) -> None:
    allowed(command)


@pytest.mark.parametrize(("command", "rule"), [
    ("rsync -t /opt/crooks-os/app /tmp/x", None),  # rsync `-t` is `--times`: dest is last
    ("rsync -avt /opt/crooks-os/app/ /tmp/x/", None),
    ("rsync -t /tmp/x /opt/crooks-os/app", "PROTECTED-PATH"),
    ("rsync -avt --delete /tmp/x/ /etc/crooks-os/", "PROTECTED-PATH"),
    ("rsync --times /tmp/x /root/.claude/", "PROTECTED-PATH"),
    ("scp -t /etc/crooks-os", "PROTECTED-PATH"),  # scp's sink mode: the directory is last
    ("scp /tmp/x host:/tmp/x", None),
    ("scp /tmp/x /etc/crooks-os/x", "PROTECTED-PATH"),
    ("mv -t /etc/crooks-os /tmp/x", "PROTECTED-PATH"),  # already caught by the general branch
    ("ln -t /etc/crooks-os /tmp/x", "PROTECTED-PATH"),
    ("mv --target-directory=/opt/crooks-os/app /tmp/x", "PROTECTED-PATH"),
])
def test_a01_the_rule_is_scoped_to_cp_and_install(command: str, rule: str | None) -> None:
    if rule is None:
        allowed(command)
    else:
        denied(command, rule)


@pytest.mark.parametrize(("base", "operands", "expected"), [
    ("cp", ["-t", "D", "a", "b"], ["D"]),
    ("cp", ["-tD", "a"], ["D"]),
    ("cp", ["-rt", "D", "a"], ["D"]),
    ("cp", ["-rtD", "a"], ["D"]),
    ("cp", ["--target-directory", "D", "a"], ["D"]),
    ("cp", ["--target-directory=D", "a"], ["D"]),
    ("cp", ["--targ", "D", "a"], ["D"]),
    ("cp", ["--t=D", "a"], ["D"]),
    ("cp", ["a", "-t", "D"], ["D"]),
    ("cp", ["-t", "D", "--", "a", "-t", "E"], ["D"]),  # after `--`, `-t E` are operands
    ("cp", ["-t", "D1", "-t", "D2", "a"], ["D1", "D2"]),
    ("cp", ["a", "b"], ["b"]),
    ("cp", ["-S", ".bak", "a", "b"], ["b"]),
    ("cp", ["a", "b", "-S", ".bak"], ["b"]),
    ("cp", ["a", "b", "--suffix", ".bak"], ["b"]),
    ("cp", ["a", "b", "--suffix=.bak"], ["b"]),
    ("cp", ["--backup", "a", "b"], ["b"]),  # optional value: never the next word
    ("cp", ["--sparse", "always", "a", "b"], ["b"]),
    ("cp", ["--", "-t", "D"], ["D"]),
    ("cp", ["-T", "a", "b"], ["b"]),
    ("cp", ["-t"], []),
    ("cp", ["a", "-t"], ["a"]),  # unreadable: every operand
    ("cp", ["--frobnicate", "a", "b"], ["a", "b"]),
    ("cp", ["-q", "a", "b"], ["a", "b"]),
    ("cp", ["-"], ["-"]),
    ("install", ["-m", "644", "a", "b"], ["b"]),
    ("install", ["-m644", "a", "b"], ["b"]),
    ("install", ["a", "b", "-m", "644"], ["b"]),
    ("install", ["-o", "root", "-g", "root", "-m", "0644", "-t", "D", "a"], ["D"]),
    ("install", ["-d", "D1", "D2"], ["D1", "D2"]),
    ("install", ["--directory", "D1", "D2"], ["D1", "D2"]),
    ("install", ["-dm", "755", "D1", "D2"], ["D1", "D2"]),
    ("install", ["-D", "a", "b"], ["b"]),
])
def test_a01_copy_destinations_reads_the_coreutils_grammar(base: str, operands: list[str],
                                                           expected: list[str]) -> None:
    assert gb._copy_destinations(base, operands) == expected


# ---------------------------------------------------------------------------------------------
# A-02 (M): the review's reproducer, verbatim, and its single-line control.
# ---------------------------------------------------------------------------------------------

A02_REVIEW_REPRODUCER = 'echo "$(echo "it\'s")" >/opt/crooks-os/app/main.py\necho it\'s'


def test_a02_the_review_reproducer_is_refused() -> None:
    # bash runs line 1 — the write — before it fails on line 2 (witnessed below). The
    # substitution's apostrophe no longer leaks into the enclosing state, so the malformed
    # second line makes the command unparseable instead of turning the redirect into text.
    denied(A02_REVIEW_REPRODUCER, "UNPARSEABLE")


def test_a02_the_hook_process_exits_2_for_the_review_reproducer() -> None:
    proc = run_hook(A02_REVIEW_REPRODUCER)
    assert proc.returncode == 2, proc
    assert "UNPARSEABLE" in proc.stderr
    assert "main.py" not in proc.stderr


@pytest.mark.parametrize("command", [
    'echo "$(echo "a")" >/opt/crooks-os/app/main.py',  # the review's control
    'echo "$(echo "it\'s")" >/opt/crooks-os/app/main.py',  # balanced: was UNPARSEABLE by luck
    'echo "$(echo "it\'s")" >' + NL + '/opt/crooks-os/app/main.py',
    "echo \"$(echo 'a\")')\" >/opt/crooks-os/app/main.py",  # a `"` and a `)` inside single quotes
    'echo "$(echo "$(echo "it\'s")")" >/opt/crooks-os/app/main.py',  # nested twice
    'echo "`echo "it\'s"`" >/opt/crooks-os/app/main.py',  # backticks inside double quotes
    'echo `echo "it\'s"` >/opt/crooks-os/app/main.py',
    'echo "$(echo `echo "it\'s"`)" >/opt/crooks-os/app/main.py',
    'x="$(echo "it\'s")"; echo x >/opt/crooks-os/app/main.py',
    'echo "$(echo "it\'s") $(echo "b\'")" >/opt/crooks-os/app/main.py',  # two on one line
    'echo "$(echo "it\'s")" "$(echo "b\'")" >/opt/crooks-os/app/main.py',
    'echo "$(echo "it\'s" # )\n)" >/opt/crooks-os/app/main.py',  # a comment inside, spanning lines
    'echo "$(echo "it\'s"\n)" >/opt/crooks-os/app/main.py',  # a substitution spanning lines
    "echo $(echo 'a)b') >/opt/crooks-os/app/main.py",
    'echo "$(echo "it\'s")" >/opt/crooks-os/app/main.py; echo "b\'"',
    'echo "$(echo "it\'s")" >/opt/crooks-os/app/main.py\necho "$(echo "b\'")"',  # both lines valid
    'echo "$(echo "it\'s")">/opt/crooks-os/app/main.py',  # glued redirection (F-6)
    'echo "$(echo "it\'s")" 2>/opt/crooks-os/app/main.py',
    'echo "$(echo "it\'s")" &>/opt/crooks-os/app/main.py',
    'echo "$(echo "it\'s")" | tee /opt/crooks-os/app/main.py',
    'cp "$(echo "it\'s")" /opt/crooks-os/app/main.py',
    'cp /tmp/x "$(echo "it\'s")" /opt/crooks-os/app/main.py',
    'sudo sh -c \'echo x >/opt/crooks-os/app/main.py\' "$(echo "it\'s")"',
])
def test_a02_a_redirect_after_a_nested_quote_is_still_a_redirect(command: str) -> None:
    denied(command, "PROTECTED-PATH")


@pytest.mark.parametrize("command", [
    # Later malformed quote state cannot hide an earlier executable line (fail closed).
    A02_REVIEW_REPRODUCER,
    'echo "$(echo "it\'s")" x\nrm -rf /opt/crooks-os\necho it\'s',
    'echo "$(echo "it\'s")" >' + NL + '/opt/crooks-os/app/main.py\necho it\'s',
    'echo `echo "it\'s"` >/opt/crooks-os/app/main.py\necho it\'s',
    'echo "`echo "it\'s"`" >/opt/crooks-os/app/main.py\necho it\'s',
    'echo "$(echo "$(echo "it\'s")")" >/opt/crooks-os/app/main.py\necho it\'s',
    'x="$(echo "it\'s")"; echo x >/opt/crooks-os/app/main.py\necho it\'s',
    'echo "$(echo "it\'s"\n)" >/opt/crooks-os/app/main.py\necho it\'s',
    'echo "$(echo "it\'s")" >/opt/crooks-os/app/main.py; echo it\'s',
    'echo "$(echo "it\'s")" >/opt/crooks-os/app/main.py\necho "it',
    'echo "$(echo "it\'s")" >/opt/crooks-os/app/main.py\necho `',
    'echo "$(echo "it\'s")" >/opt/crooks-os/app/main.py\necho $(',
])
def test_a02_a_later_malformed_line_makes_the_command_unparseable(command: str) -> None:
    denied(command, "UNPARSEABLE")


def test_a02_a_later_dangling_backslash_does_not_hide_the_earlier_redirect() -> None:
    # Line 1 is complete and is read first; the dangling escape on line 2 is refused by the
    # tokenizer of its own segment, but the protected write has already been named.
    denied('echo "$(echo "it\'s")" >/opt/crooks-os/app/main.py\n' + "echo '#' \\",
           "PROTECTED-PATH")


@pytest.mark.parametrize("command", [
    'echo "$(echo "it\'s")" x\nrm -rf /opt/crooks-os',
    'echo "`echo "it\'s"`" x\nrm -rf /opt/crooks-os',
    'echo "$(echo "it\'s")" \'<<EOF\'\nrm -rf /opt/crooks-os\nEOF',  # not a heredoc: quoted
    'echo "$(echo "it\'s")"; rm -rf /opt/crooks-os',
])
def test_a02_a_later_executable_line_is_read_after_a_nested_quote(command: str) -> None:
    denied(command, "RM-RECURSIVE")


@pytest.mark.parametrize(("command", "rule"), [
    ('echo "$(rm -rf /opt/crooks-os)"', "RM-RECURSIVE"),  # the body still runs, and is read
    ('echo "`rm -rf /opt/crooks-os`"', "RM-RECURSIVE"),
    ('echo "$(echo "it\'s"; rm -rf /opt/crooks-os)"', "RM-RECURSIVE"),
    ('echo "$(echo "$(rm -rf /opt/crooks-os)")"', "RM-RECURSIVE"),
    ('echo "$(cat .env)"', "SECRET-FILE-READ"),
    ('echo "$(cat /etc/crooks-os/credentials/x)"', "SECRET-FILE-READ"),
    ('echo "$(echo x >/opt/crooks-os/app/main.py)"', "PROTECTED-PATH"),
    ('x="$(git push --force origin main)"', "GIT-PUSH-FORCE"),
    ('"$(date)"', "UNPARSEABLE"),  # the marker in command position (D-03)
    ('"$(echo "it\'s")" x', "UNPARSEABLE"),
    ('"a$(echo "it\'s")b" x', "UNPARSEABLE"),
])
def test_a02_a_double_quoted_body_is_evaluated_as_before(command: str, rule: str) -> None:
    denied(command, rule)


@pytest.mark.parametrize("command", [
    'echo "$(echo "it\'s")"',
    'echo "$(echo "it\'s")" >/tmp/x',
    'echo "$(echo "it\'s")" x\necho "b\'"',
    'x="$(echo "it\'s")"; echo "$x"',
    'echo "`echo "it\'s"`" >/tmp/x',
    'echo "$(date)" >/tmp/x',
    'echo "a$(date)b"',
    'echo "$(echo "$(echo "it\'s")")"',
    "echo \"$(echo 'a)b')\"",
    'echo "$(echo "it\'s" # comment\n)"',
    'echo "$(echo "it\'s"\n)" >/tmp/x',
    "echo '$(rm -rf /opt/crooks-os)'",  # single-quoted: literal text, no substitution
    'echo "\\$(rm -rf /opt/crooks-os)"',  # escaped: literal text
    'git commit -m "$(cat /tmp/msg)"',
    'bash -c "echo $(date)"',
    'echo "$(printf "%s" "it\'s")" | wc -c',
])
def test_a02_valid_quoted_data_stays_allowed(command: str) -> None:
    allowed(command)


# The shared rule, scanner by scanner.


@pytest.mark.parametrize("text", [
    # Each of these is one whole substitution: it must close at its last character.
    '$(echo "it\'s")',
    '$(echo "a")',
    "$(echo 'a)b')",  # `)` inside single quotes closes nothing
    '$(echo ")")',  # `)` inside double quotes closes nothing
    "$(echo x # )\n)",  # `)` inside a comment closes nothing
    "$(echo x #)\n)",
    "$(echo x#)",  # a mid-word `#` is not a comment
    '$(echo "$(echo "it\'s")")',  # nested: the inner one is closed first
    "$(echo `echo \"it's\"`)",
    "$(echo \\))",  # an escaped `)` closes nothing
    "$( (a) )",  # a bare paren pair inside
    "`echo \"it's\"`",
    "`echo 'a`",  # the first unescaped backtick ends it, whatever quotes sit inside
    "`echo \"a`",
    "`echo a\\`b`",  # an escaped backtick does not
])
def test_a02_substitution_end_reads_a_nested_command_with_its_own_state(text: str) -> None:
    assert gb._substitution_end(text, 0) == len(text) - 1


def test_a02_substitution_end_inside_a_double_quoted_word() -> None:
    text = 'x="$(echo "it\'s")" y'
    end = gb._substitution_end(text, 3)
    assert text[end] == ")" and text[end + 1 :] == '" y'


@pytest.mark.parametrize("text", [
    "$(echo 'a)",
    '$(echo ")',
    "$(echo # )",
    '$(echo "$(echo "it\'s")"',
    "`echo a\\`",
    "$(" * (gb.MAX_SUBSTITUTION_NESTING + 2) + "x" + ")" * (gb.MAX_SUBSTITUTION_NESTING + 2),
])
def test_a02_substitution_end_refuses_what_it_cannot_close(text: str) -> None:
    with pytest.raises(ValueError):
        gb._substitution_end(text, 0)


@pytest.mark.parametrize(("text", "joined"), [
    # The enclosing quote resumes after the substitution: the redirect target is joined.
    ('echo "$(echo "it\'s")" >\\\n/opt/x\necho it\'s', 'echo "$(echo "it\'s")" >/opt/x\necho it\'s'),
    # Inside a substitution the pair is removed, with the substitution's own quotes deciding.
    ('echo "$(echo a\\\nb)"', 'echo "$(echo ab)"'),
    ("echo `echo a\\\nb`", "echo `echo ab`"),
    ('echo "`echo a\\\nb`"', 'echo "`echo ab`"'),
    ("echo $(echo 'a\\\nb')", "echo $(echo 'a\\\nb')"),  # single-quoted inside: literal
    ('echo "$(echo \'a\\\nb\')"', 'echo "$(echo \'a\\\nb\')"'),
    ("echo `echo 'a\\\nb'`", "echo `echo 'a\\\nb'`"),
    # A comment inside a substitution runs to its newline and continues nothing.
    ("echo $(echo x # c\\\n) y", "echo $(echo x # c\\\n) y"),
    # An unterminated substitution: what follows is its own text, read with fresh state.
    ("echo $(echo 'a\\\nb", "echo $(echo 'a\\\nb"),
    ('echo "$(echo a\\\nb', 'echo "$(echo ab'),
    ("echo `echo a\\\nb", "echo `echo ab"),
    # R-01 forms are unchanged.
    ("echo x >\\\n/opt/x", "echo x >/opt/x"),
    ("echo 'a\\\nb'", "echo 'a\\\nb'"),
    ("echo x # c\\\nrm -rf /", "echo x # c\\\nrm -rf /"),
])
def test_a02_continuations_are_removed_with_the_substitution_s_own_state(text: str,
                                                                          joined: str) -> None:
    assert gb._join_continuations(text) == joined


@pytest.mark.parametrize(("line", "continued"), [
    ('echo "$(echo "it\'s")" \\', True),
    ("echo $(echo 'a\\", False),  # inside the substitution's single quotes: literal
    ('echo "$(echo "a\\', True),
    ("echo `echo 'a\\", False),
    ("echo `echo a` \\", True),
    ("x=$(echo a # \\", False),  # inside a comment
])
def test_a02_a_physical_line_ends_in_a_continuation_only_when_bash_says_so(
    line: str, continued: bool,
) -> None:
    assert gb._continued(line) is continued


@pytest.mark.parametrize(("line", "ops"), [
    ('echo "$(echo "it\'s")" <<EOF', [("EOF", False, False)]),  # after the substitution
    ("echo \"$(echo \"it's\")\" '<<EOF'", []),  # quoted: text
    ('echo "$(cat <<EOF', [("EOF", False, False)]),  # inside a `$( … )` still open
    ("x=$(cat <<EOF", [("EOF", False, False)]),
    ("echo $(cat <<EOF)", [("EOF", False, False)]),  # closed on the line: bash 5.2 reads the body below
    ("x=`cat <<EOF", [("EOF", False, False)]),  # a backtick still open: its text continues below
    ("echo `cat <<EOF`", []),  # closed on the line: its heredoc ends with it
    ("echo hi # <<EOF", []),  # a comment
    ("echo hi;# <<EOF", []),
    ("echo hi '#' <<EOF", [("EOF", False, False)]),  # not a comment
    ("echo hi# <<EOF", [("EOF", False, False)]),
    ("echo $(echo 'x') <<EOF", [("EOF", False, False)]),
    ("echo $(echo '<<EOF')", []),  # single-quoted inside the substitution
    ('echo "$(echo "<<EOF")"', []),
    ("cat <<A <<B", [("A", False, False), ("B", False, False)]),
    ("cat <<-'A'", [("A", True, True)]),
])
def test_a02_heredoc_operators_are_read_with_the_shared_state(line: str,
                                                              ops: list[tuple]) -> None:
    assert gb._unquoted_heredoc_ops(line) == ops


def test_a02_the_segmenter_replaces_a_double_quoted_substitution_by_the_marker() -> None:
    segs = gb._segments('echo "$(echo "it\'s")" >/opt/x\necho b')
    assert segs == [('echo "it\'s"', False), ('echo "$SUBST" >/opt/x', False), ("echo b", False)]
    toks, _ = gb._tokens(segs[1][0])
    assert toks == ["echo", "$SUBST", ">/opt/x"]
    assert gb._redirect_targets(toks) == ["/opt/x"]


def test_a02_the_segmenter_emits_nested_bodies_innermost_first() -> None:
    segs = gb._segments('echo "$(echo "$(rm -rf x)")"')
    assert segs == [("rm -rf x", False), ('echo "$SUBST"', False), ('echo "$SUBST"', False)]


def test_a02_the_segmenter_refuses_a_later_unbalanced_quote() -> None:
    with pytest.raises(ValueError):
        gb._segments(A02_REVIEW_REPRODUCER)


# ---------------------------------------------------------------------------------------------
# The two adjacent siblings in the heredoc-operator reader.
# ---------------------------------------------------------------------------------------------

SIBLING_REPRODUCERS = [
    "echo hi # <<EOF\nrm -rf /opt/crooks-os\nEOF",  # a commented operator reads no body
    "echo hi ;# <<EOF\nrm -rf /opt/crooks-os\nEOF",
    "echo hi #<<EOF\nrm -rf /opt/crooks-os\nEOF",
    "echo `cat <<EOF`\nrm -rf /opt/crooks-os\nEOF",  # a backtick closed on its line: no body
    "x=`cat <<EOF`; echo x\nrm -rf /opt/crooks-os\nEOF",
]


@pytest.mark.parametrize("command", SIBLING_REPRODUCERS)
def test_siblings_a_hidden_line_after_a_false_heredoc_is_read(command: str) -> None:
    denied(command, "RM-RECURSIVE")


@pytest.mark.parametrize("command", SIBLING_REPRODUCERS)
def test_siblings_the_hook_process_exits_2(command: str) -> None:
    proc = run_hook(command)
    assert proc.returncode == 2, proc
    assert "RM-RECURSIVE" in proc.stderr


@pytest.mark.parametrize("command", [
    "echo hi '#' <<EOF\nrm -rf /opt/crooks-os\nEOF",  # a real heredoc: the body is prose
    "echo hi# <<EOF\nrm -rf /opt/crooks-os\nEOF",
    "x=$(cat <<EOF\nrm -rf /opt/crooks-os\nEOF\n)",  # a `$( … )` spanning lines: body is data
    'x="$(cat <<EOF\nrm -rf /opt/crooks-os\nEOF\n)"',
    "x=`cat <<EOF\nrm -rf /opt/crooks-os\nEOF\n`",  # a backtick spanning lines: body is data
    "echo $(cat <<EOF)\nrm -rf /opt/crooks-os\nEOF",  # closed on its line: bash 5.2 reads the body below
    'echo "$(cat <<EOF)"\nrm -rf /opt/crooks-os\nEOF',
    "x=$(cat <<EOF\nit's prose\nEOF\n)",  # prose with an apostrophe: owned by cat, not read
    'x="$(cat <<EOF\nit\'s prose\nEOF\n)"',
    "x=`cat <<EOF\nit's prose\nEOF\n`",
    'y="$(echo "it\'s")" x=$(cat <<EOF\nit\'s prose\nEOF\n)',
    "cat <<EOF\nhello\nEOF",
    "cat <<EOF # comment\nhello\nEOF",  # a comment AFTER the operator
])
def test_siblings_a_real_heredoc_body_is_still_prose(command: str) -> None:
    allowed(command)


@pytest.mark.parametrize(("line", "owner_text"), [
    ('x="$(cat <<EOF', "cat <<EOF"),
    ("x=$(cat <<EOF", "cat <<EOF"),
    ("x=`cat <<EOF", "cat <<EOF"),
    ('echo "$(cat <<EOF)" | bash', "cat <<EOF"),  # closed on the line: up to its `)`
    ('echo "$(bash <<EOF)"', "bash <<EOF"),
    ("cat <<EOF | bash", "cat <<EOF | bash"),  # outside any substitution: the whole line
    ("echo $(echo 'x') <<EOF", "echo $(echo 'x') <<EOF"),
])
def test_siblings_the_owner_of_an_operator_inside_a_substitution_is_its_own_text(
    line: str, owner_text: str,
) -> None:
    ops, start, end = gb._heredoc_scan(line)
    assert ops == [("EOF", False, False)]
    assert line[start:end] == owner_text


@pytest.mark.parametrize(("command", "rule"), [
    ('x="$(bash <<EOF\nrm -rf /opt/crooks-os\nEOF\n)"', "RM-RECURSIVE"),  # a shell owner inside
    ("x=$(bash <<EOF\nrm -rf /opt/crooks-os\nEOF\n)", "RM-RECURSIVE"),
    ("x=`bash <<EOF\nrm -rf /opt/crooks-os\nEOF\n`", "RM-RECURSIVE"),
    ('echo "$(bash <<EOF)"\nrm -rf /opt/crooks-os\nEOF', "RM-RECURSIVE"),
    ('x="$(python3 <<EOF\nimport os; os.environ["X"]\nEOF\n)"', "INTERPRETER-SECRET-READ"),
    ("cat <<EOF | bash\nrm -rf /opt/crooks-os\nEOF", "RM-RECURSIVE"),
    ('echo "$(cat <<EOF\n$(rm -rf /opt/crooks-os)\nEOF\n)"', "RM-RECURSIVE"),  # prose body substitution
    # The substitution's output reaching a shell outside it is a pipe the hook cannot read.
    ('echo "$(cat <<EOF)" | bash\nrm -rf /opt/crooks-os\nEOF', "UNPARSEABLE"),
    ("echo $(cat <<EOF) | bash\nrm -rf /opt/crooks-os\nEOF", "UNPARSEABLE"),
    ('bash -c "$(cat <<EOF\nrm -rf /opt/crooks-os\nEOF\n)"', "UNPARSEABLE"),
])
def test_siblings_a_heredoc_that_feeds_a_shell_is_still_evaluated(command: str,
                                                                  rule: str) -> None:
    denied(command, rule)


# ---------------------------------------------------------------------------------------------
# The gitleaks gate reads the same segments.
# ---------------------------------------------------------------------------------------------


def test_gate_a_publish_after_a_nested_quote_is_seen() -> None:
    actions = gate._publish_actions('echo "$(echo "it\'s")"; git push origin claude/x')
    assert actions == [("push", ["origin", "claude/x"], None)]


def test_gate_a_message_built_from_a_substitution_is_the_marker() -> None:
    actions = gate._publish_actions('git commit -m "$(echo "it\'s")"')
    assert actions == [("commit", ["-m", "$SUBST"], None)]


def test_gate_a_later_malformed_line_is_refused_not_laundered() -> None:
    command = 'echo "$(echo "it\'s")"; git push origin claude/x\necho it\'s'
    with pytest.raises(ValueError):
        gate._publish_actions(command)
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": CWD})
    result = gate.run_gate(payload.encode(), gitleaks="/nonexistent/gitleaks")
    assert result.denied and result.rule == "UNPARSEABLE"


def test_gate_a_push_hidden_behind_a_commented_heredoc_is_seen() -> None:
    actions = gate._publish_actions("echo hi # <<EOF\ngit push origin claude/x\nEOF")
    assert actions == [("push", ["origin", "claude/x"], None)]


# ---------------------------------------------------------------------------------------------
# Witnesses: real bash and real coreutils on tmp_path show the semantics matched above.
# ---------------------------------------------------------------------------------------------

BASH = shutil.which("bash")
CP = shutil.which("cp")
INSTALL = shutil.which("install")


def _bash(script: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    path = cwd / "script.sh"
    path.write_text(script)
    return subprocess.run([BASH, str(path)], cwd=cwd, capture_output=True, text=True,
                          timeout=30, check=False)


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_witness_bash_writes_before_it_fails_on_the_later_apostrophe(tmp_path: Path) -> None:
    proc = _bash('echo "$(echo "it\'s")" >out.txt\necho it\'s\n', tmp_path)
    assert proc.returncode != 0 and "unexpected EOF" in proc.stderr
    assert (tmp_path / "out.txt").read_text() == "it's\n"  # line 1 ran: the redirect was real


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_witness_bash_runs_the_line_a_nested_quote_would_have_hidden(tmp_path: Path) -> None:
    proc = _bash('echo "$(echo "it\'s")" x\ntouch ran\necho it\'s\n', tmp_path)
    assert proc.returncode != 0
    assert (tmp_path / "ran").exists()


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_witness_bash_removes_continuations_inside_substitutions(tmp_path: Path) -> None:
    proc = _bash('echo `echo a\\\nb`\necho "$(echo c\\\nd)"\necho "`echo e\\\nf`"\n'
                 "echo \"$(echo 'g\\\nh')\"\n", tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "ab\ncd\nef\ng\\\nh\n"  # single-quoted inside: the pair is literal


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_witness_bash_reads_a_substitution_with_its_own_state(tmp_path: Path) -> None:
    proc = _bash("echo $(echo x # )\n)\necho \"$(echo 'a)b')\"\necho \"$(echo ')')\"\n"
                 'echo "$(echo "$(echo "it\'s")")"\n', tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "x\na)b\n)\nit's\n"


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_witness_bash_ends_a_backtick_at_the_first_unescaped_backtick(tmp_path: Path) -> None:
    proc = _bash('echo `echo "a` >out.txt\necho next\n', tmp_path)
    assert proc.returncode == 0  # the substitution fails; the command — and its redirect — runs
    assert (tmp_path / "out.txt").exists()
    assert "next" in proc.stdout


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_witness_bash_does_not_read_a_heredoc_body_after_a_commented_operator(
    tmp_path: Path,
) -> None:
    proc = _bash("echo hi # <<EOF\ntouch ran\nEOF\n", tmp_path)
    assert (tmp_path / "ran").exists()  # the line after the comment is a command
    assert "EOF: command not found" in proc.stderr


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_witness_bash_runs_the_lines_after_a_backtick_that_closes_on_its_line(
    tmp_path: Path,
) -> None:
    proc = _bash("echo `cat <<EOF`\ntouch ran\nEOF\n", tmp_path)
    assert (tmp_path / "ran").exists()
    assert "EOF: command not found" in proc.stderr
    # ... and reads the body of one that spans lines.
    proc = _bash("x=`cat <<EOF\ntouch ran2\nEOF\n`\necho \"$x\"\n", tmp_path)
    assert proc.returncode == 0 and proc.stdout == "touch ran2\n"
    assert not (tmp_path / "ran2").exists()


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_witness_bash_reads_a_heredoc_body_inside_a_quoted_substitution(tmp_path: Path) -> None:
    proc = _bash('echo "$(cat <<EOF\ntouch ran\nEOF\n)"\n', tmp_path)
    assert proc.returncode == 0 and proc.stdout == "touch ran\n"
    assert not (tmp_path / "ran").exists()


@pytest.mark.skipif(CP is None or INSTALL is None, reason="no coreutils cp/install here")
def test_witness_coreutils_target_directory_and_option_values(tmp_path: Path) -> None:
    src = tmp_path / "x"
    src.write_text("hi\n")
    dest = tmp_path / "dest"
    dest.mkdir()

    def run(*args: str) -> None:
        subprocess.run(list(args), cwd=tmp_path, check=True, capture_output=True, timeout=30)

    run(INSTALL, "-t", str(dest), str(src))  # `-t DIR SRC` writes DIR/x
    assert (dest / "x").read_text() == "hi\n"
    run(CP, "-t" + str(dest), str(src))  # attached value
    run(CP, "--targ", str(dest), str(src))  # an abbreviation getopt accepts
    run(CP, "--t=" + str(dest), str(src))
    run(INSTALL, "-m644", "-t", str(dest), str(src))
    run(INSTALL, str(src), str(dest / "y"), "-m", "644")  # the value of `-m` is not the dest
    assert (dest / "y").exists()
    run(CP, str(src), str(dest / "z"), "--suffix", "bak")
    assert (dest / "z").exists()
    run(INSTALL, "-d", str(dest / "n1"), str(tmp_path / "n2"))  # `-d`: every operand
    assert (dest / "n1").is_dir() and (tmp_path / "n2").is_dir()
    run(CP, "-rt", str(tmp_path / "n2"), str(src))
    assert (tmp_path / "n2" / "x").exists()
