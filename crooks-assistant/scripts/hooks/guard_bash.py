#!/usr/bin/env python3
"""guard_bash — CROOKS fail-closed guard for Claude Code's Bash tool (a PreToolUse hook).

Contract
--------
stdin   the PreToolUse JSON Claude Code sends:
        {"tool_name": "Bash", "tool_input": {"command": "..."}, "cwd": "...", ...}
exit 0  allowed. When the command is allowed but irreversible, stdout carries
        {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "..."}}
        asking for the exact targets and a one-line rollback before it runs. It never carries
        a permissionDecision: this hook narrows, it does not auto-approve.
exit 2  DENIED. The reason is one line on stderr, which Claude Code feeds back to the model.

Fail closed. Input that is absent, oversized, not JSON, not an object, not a Bash call, or a
command that cannot be tokenised is denied. So is a command word the hook cannot resolve
statically (a variable, a substitution, a brace or glob form, `eval` of dynamic text), text fed
to a shell that the hook cannot read (a pipe from anything but a literal `echo`/`printf`, a
here-string or heredoc it did not evaluate, a bare shell reading stdin), and — since the
independent review of 2026-09-19 — an unexpected exception anywhere in the hook: `main` prints
one fixed line and exits 2. There is no environment variable, file, flag or magic comment that
disables or relaxes this hook. It reads nothing but stdin, writes nothing but stdout and
stderr, opens no file and no socket, and never echoes the command text or any argument value:
a reason names a rule id, a command word, or the constant protected path or ref that matched,
never what the model typed.

Provenance
----------
The destructive-Git decision table reimplements — it does not import — the concepts in ECC
GateGuard, `scripts/hooks/gateguard-fact-force.js` at commit
07756cee15788a54506031462794ad645719b028 (sha256 of that file
005ce7a81dc30bae5e3320a005b49bab47add0d4db49607e85f66601503e19d9), audited read-only in the
bridge round of 2026-09-19. Kept: the git subcommand locator that skips `-c`/`-C`/`--git-dir`
global options; the per-subcommand rules for reset, checkout, clean, push (bare force, `+`
refspecs, lease-checked force to a shared branch), commit --amend, rm -r, switch, branch,
stash, reflog, update-ref and restore; quote stripping; subshell and brace-group explosion;
heredoc-body stripping; and the quote-aware second pass that closes the `'rm'`, newline and
`sh -c` bypasses (GHSA-4v57-ph3x-gf55). Not kept, deliberately: every environment bypass
(`GATEGUARD_DISABLED`, `ECC_GATEGUARD`, `GATEGUARD_BASH_EXTRA_DESTRUCTIVE`), the fail-open
state directory, the `node -e` bootstrap, the observer/persistence hooks and the npm runtime.

Everything under "CROOKS additions" below is new: the production/infrastructure path guard,
protected refs, service, Tailscale, secret, live-business-call, global-Claude-config and
pipe-to-shell rules, and the repairs from the review of candidate dd50ebb (defect ids D-01 …
D-13 in the tests).

Known limits — a Bash-text hook is a nudge, not a boundary
----------------------------------------------------------
The boundaries are the watcher's systemd sandbox, the permission layer and the
builder/production directory split. This hook exists so that the ordinary mistake is caught
before those are tested, and so that the reason is written down. What it cannot do, and does
not pretend to:

- **Filesystem aliasing.** A symlink created earlier (`ln -s /opt /tmp/o`) makes
  `/tmp/o/crooks-os` reach production; the hook sees text, not inodes. Bind mounts likewise.
- **Script files.** `bash script.sh`, `source file.sh`, `python3 script.py` and `make` targets
  run whatever the file says. The hook checks that the file is not under a protected path and
  stops there. Text it *can* see — `-c` strings, here-strings, heredocs, `eval`, literal
  `echo … | sh` — it evaluates; text it cannot see from a pipe or a file is refused.
- **Unknown static command words are allowed** (`pytest`, `ruff`, `node`, a project script).
  Only *dynamic* words are refused. A finite allow-list is a separate design decision.
- **Variables inside paths** (`> $OUT`, `cp x $DIR/`) are not resolved beyond assignments on
  the same command line; `cd $DIR` leaves the tracked working directory unknown.
- **`PATH` hijack** (`PATH=/tmp/x git …`) is a script file by another name.
- **Interpreter code is opaque** beyond the substrings it names: `os.system("git reset
  --hard")` inside `python3 -c` is not seen. Protected paths, `.env`-style names and
  environment reads inside inline code are.
"""

from __future__ import annotations

import fnmatch
import json
import posixpath
import re
import shlex
import sys
from dataclasses import dataclass, field

MAX_INPUT_BYTES = 64 * 1024
MAX_COMMAND_CHARS = 16 * 1024
MAX_DEPTH = 4
INTERNAL_ERROR_LINE = "guard_bash: DENY [INTERNAL-ERROR] the hook failed unexpectedly; failing closed"

# ----------------------------------------------------------------------------------------------
# CROOKS constants. Every string here may appear verbatim in a denial reason; nothing else may.
# ----------------------------------------------------------------------------------------------

# Read-only for engineering work: writes, deletes and executes-as-code are denied; reads pass.
# Specific roots come first so that a reason names the most specific one. `/etc` and `/root`
# as a whole are the D-13 rule: engineering workers do not write under either; scratch is
# /tmp, /var/tmp and the checkouts.
PROTECTED_DIRS = (
    "/opt/crooks-os",  # the production checkout
    "/etc/crooks-os",  # production configuration
    "/etc/systemd",  # unit files
    "/root/.claude",  # the account-level Claude login, settings, plugins
    "/etc",
    "/root",
)
PROTECTED_FILES = ("/root/.claude.json",)  # account-level Claude configuration
# No access at all, reads included (D-01): the live credential store.
SECRET_DIRS = ("/etc/crooks-os/credentials", "/etc/crooks-os/secrets")
# Recursive deletes may reach strictly inside these, never the root itself.
CHECKOUT_ROOTS = ("/opt/crooks-builder", "/opt/crooks-ai-bridge", "/opt/crooks-bridge-watcher")
TMP_ROOTS = ("/tmp", "/var/tmp")
PROTECTED_REFS = frozenset(
    {
        "main",
        "master",
        "claude/linux-prod-migration-production",
        "claude/product-memory-foundation",
        "crooks-ai-bridge",
    }
)
# ECC's shared-history set: a lease-checked force push to one of these still rewrites commits
# other clones build on.
SHARED_BRANCHES = frozenset({"main", "master", "develop", "trunk"})

SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
# Commands whose argument is a shell string: it is evaluated as its own command line (D-03).
SHELL_STRING_COMMANDS = frozenset({"eval", "watch", "su"})
INTERPRETER_CODE_FLAG = {"python": "-c", "perl": "-e", "ruby": "-e", "node": "-e", "php": "-r"}
PASSTHROUGH = frozenset(
    {"sudo", "doas", "env", "nohup", "nice", "ionice", "command", "exec", "time", "timeout",
     "xargs", "builtin", "stdbuf", "chronic", "caffeinate"}
)
RESERVED = frozenset({"{", "}", "!", "do", "done", "then", "else", "fi", "elif", "if", "while",
                      "until", "esac"})
ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)
GIT_ENV_PATHS = frozenset({"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                           "GIT_OBJECT_DIRECTORY"})
# The segmenter replaces every `$( … )` or backtick substitution with this word (the body is
# evaluated separately). Wherever the marker lands in command-word position — alone, behind a
# wrapper or an assignment, or glued to a literal prefix — the hook cannot know what will run
# and refuses (D-03; F-2/F-3 of the review of d7911b2). As an argument it is inert.
SUBST_MARKER = "$SUBST"
MAX_SUBSTITUTION_NESTING = 16
DYNAMIC_WORD_CHARS = "$`{*?["

READ_ONLY_COMMANDS = frozenset(
    {"cat", "ls", "stat", "head", "tail", "wc", "grep", "rg", "egrep", "fgrep", "zgrep", "diff",
     "cmp", "comm", "sha256sum", "sha1sum", "md5sum", "sha512sum", "b2sum", "cksum", "du", "df",
     "file", "realpath", "readlink", "tree", "jq", "less", "more", "test", "[", "[[", "echo",
     "printf", "ps", "pgrep", "lsof", "ss", "cd", "pwd", "pushd", "popd", "basename", "dirname",
     "sort", "uniq", "cut", "tr", "awk", "gawk", "column", "nl", "od", "xxd", "hexdump",
     "strings", "tac", "rev", "fold", "type", "which", "true", "false", "sleep", "date", "id",
     "whoami", "uname", "hostname", "getfacl", "namei", "journalctl", "dpkg-query", "yes"}
)
READ_ONLY_SYSTEMCTL = frozenset(
    {"status", "show", "cat", "is-active", "is-enabled", "is-failed", "is-system-running",
     "list-units", "list-unit-files", "list-timers", "list-dependencies", "list-sockets",
     "list-jobs", "show-environment", "get-default", "help", "--version"}
)
SYSTEMCTL_VALUE_OPTS = frozenset(
    {"-n", "--lines", "-o", "--output", "-p", "--property", "-t", "--type", "--state", "-M",
     "--machine", "-H", "--host", "-s", "--signal", "--kill-who", "--job-mode", "--root",
     "--preset-mode", "--timestamp", "--reboot-argument", "--boot-loader-entry"}
)
READ_ONLY_LAUNCHCTL = frozenset({"list", "print", "print-disabled", "blame", "dumpstate", "help"})
READ_ONLY_TAILSCALE = frozenset(
    {"status", "ip", "netcheck", "version", "whois", "ping", "bugreport", "metrics", "help",
     "--version", "dns"}
)
GIT_READ_ONLY_SUBS = frozenset(
    {"status", "log", "diff", "show", "rev-parse", "ls-files", "ls-tree", "cat-file", "describe",
     "blame", "for-each-ref", "rev-list", "merge-base", "name-rev", "shortlog", "count-objects",
     "check-ignore", "check-attr", "diff-tree", "diff-index", "diff-files", "var", "version",
     "help", "grep", "whatchanged", "show-ref", "verify-commit", "verify-tag", "ls-remote",
     "cherry", "range-diff", "annotate", "show-branch", "fsck"}
)
# git subcommands that may name a `.claude/` or `.git/hooks/` path without writing the file.
GIT_SENSITIVE_PATH_OK = GIT_READ_ONLY_SUBS | {"add", "commit", "reset"}
GIT_BRANCH_MUTATING_FLAGS = frozenset(
    {"-d", "-D", "-m", "-M", "-c", "-C", "-f", "--delete", "--move", "--copy", "--force", "-u",
     "--set-upstream-to", "--unset-upstream", "--edit-description", "-t", "--track"}
)
GIT_CONFIG_READ_FLAGS = frozenset(
    {"--get", "--get-all", "--get-regexp", "-l", "--list", "--show-origin", "--show-scope",
     "--get-urlmatch", "get", "list"}
)
# Config keys whose value is a command git runs (D-06): setting one, by `-c`, `--config-env`
# or `git config`, is a way to execute text the hook never sees.
GIT_EXEC_CONFIG_RE = re.compile(
    r"^(core\.(hookspath|fsmonitor|sshcommand|pager|editor|askpass|gitproxy)"
    r"|credential\.|diff\.external|difftool\.|mergetool\.|merge\.[^.]+\.driver|filter\."
    r"|alias\.|gpg\.program|sequence\.editor|uploadpack\.|receive\."
    r"|remote\.[^.]+\.(uploadpack|receivepack)|ssh\.)"
)

MAKE_SERVICE_TARGETS = frozenset(
    {"install", "uninstall", "up", "restart", "commands", "commands-remove", "control-app"}
)
MAKE_SECRET_TARGETS = frozenset({"secrets"})
MAKE_LIVE_TARGETS = frozenset(
    {"gmail", "gmail-verify", "shopify", "voice", "test-live", "experience-live", "check"}
)
SCRIPT_RULES = {
    "install_launchd.py": ("SERVICE-MUTATION", "installs login-time services"),
    "up.py": ("SERVICE-MUTATION", "starts the backend, speech and HTTPS route"),
    "install_commands.py": ("SERVICE-MUTATION", "installs commands on the PATH"),
    "update.py": ("DEPLOY-ACTION", "pulls, installs and restarts"),
    "set_secrets.py": ("SECRET-PROVISION", "stores credentials"),
    "gmail_auth.py": ("LIVE-BUSINESS-CALL", "runs the live Gmail OAuth flow"),
    "voice_check.py": ("LIVE-BUSINESS-CALL", "makes a live ElevenLabs request"),
    "shopify_check.py": ("LIVE-BUSINESS-CALL", "calls the live Shopify store"),
}
SECRET_NAME_RE = re.compile(
    r"(KEY|TOKEN|SECRET|PASS(WORD|WD)?|CREDENTIAL|COOKIE|PRIVATE|BEARER|OAUTH|API_)",
    re.IGNORECASE,
)
SECRET_VAR_REF_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)")
SECRET_FILE_RE = re.compile(
    r"^(\.env(\..+)?|.*credentials\.json|token\.json|.*\.pem|id_(rsa|ed25519|ecdsa|dsa)|.*\.key"
    r"|.*\.p12|.*\.pfx|\.netrc|\.npmrc|\.pypirc|secrets\.json|\.credentials\.json"
    r"|.*\.cred|.*signing_key)$"
)
SECRET_FILE_EXAMPLES = re.compile(r"^\.env\.(example|sample|template|dist)$")
# Dotfile names a dot-prefixed glob (`.en?`, `.env*`) could expand to.
SECRET_DOTFILES = (".env", ".netrc", ".npmrc", ".pypirc", ".credentials.json")
PROC_ENVIRON_RE = re.compile(r"^/proc/[^/]+/environ$")
# Inline interpreter code that reads the environment or a credential file (D-12). Written as
# patterns so that this file itself never contains the literal calls it looks for.
CODE_SECRET_RE = re.compile(
    r"os\.environ|\benviron\b|\bget(env|ENV)\b|process\.env|\$ENV\b|ENV\[|/proc/"
    r"|\.env\b|\.credentials|\.netrc|\.pem\b|\.cred\b|signing_key|_api_key"
)
FILE_READERS = frozenset(
    {"cat", "head", "tail", "less", "more", "bat", "strings", "grep", "rg", "egrep", "fgrep", "awk",
     "gawk", "sed", "xxd", "od", "hexdump", "cut", "sort", "uniq", "tee", "cp", "scp", "rsync",
     "base64", "jq", "wc", "source", ".", "python", "node", "perl", "ruby", "vim", "nano", "vi",
     "diff", "cmp", "tac", "nl", "fold", "column", "tr"}
)
PACKAGE_MANAGERS = {"apt", "apt-get", "aptitude", "yum", "dnf", "pacman", "zypper", "snap",
                    "brew"}
PACKAGE_MUTATING_VERBS = frozenset(
    {"install", "remove", "purge", "upgrade", "dist-upgrade", "full-upgrade", "autoremove",
     "reinstall", "uninstall", "refresh", "revert", "-S", "-R", "-Syu", "-U", "-i"}
)
DISK_COMMANDS = frozenset({"mkfs", "wipefs", "shred", "fdisk", "sfdisk", "parted", "mkswap"})
FIREWALL_COMMANDS = frozenset({"ufw", "iptables", "ip6tables", "nft", "firewall-cmd"})
FIREWALL_MUTATING = frozenset(
    {"-A", "-I", "-D", "-F", "-P", "-X", "-N", "-R", "-Z", "--append", "--insert", "--delete",
     "--flush", "--policy", "--new-chain", "--delete-chain", "add", "delete", "flush", "allow",
     "deny", "reject", "limit", "enable", "disable", "reset", "reload", "insert", "route",
     "default", "--add-port", "--remove-port", "--add-service", "--remove-service"}
)
# curl short options that take a value; needed to read joined bundles like `-sSXPOST` (D-09).
CURL_VALUE_LETTERS = frozenset("AbcCdDeEFHKmoPQrtTuUwxXyYz")
GLOB_CHARS = ("*", "?", "[")

CONTEXT_TEXT = (
    "guard_bash: this command is irreversible or changes shared state. Before running it, "
    "state the exact target(s) and a one-line rollback. If either cannot be stated, do not run "
    "it — report instead."
)


@dataclass
class Decision:
    verdict: str  # "allow" | "deny"
    rule: str = ""
    reason: str = ""
    context: list[str] = field(default_factory=list)

    @property
    def denied(self) -> bool:
        return self.verdict == "deny"


def deny(rule: str, reason: str) -> Decision:
    return Decision("deny", rule, reason)


ALLOW = Decision("allow")


@dataclass
class _Ctx:
    depth: int = 0
    protected_cwd: bool = False
    notes: list[str] = field(default_factory=list)
    cwd: str | None = None  # the tracked absolute working directory, when it is known
    prev_cwd: str | None = None  # what `cd -` would return to, when that is known
    find_scope: str | None = None  # the start directory of a `find … -exec` being evaluated

    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)

    def child(self) -> _Ctx:
        """A context for nested text: one level deeper, same tracked state, shared notes."""
        return _Ctx(depth=self.depth + 1, protected_cwd=self.protected_cwd, notes=self.notes,
                    cwd=self.cwd, prev_cwd=self.prev_cwd, find_scope=self.find_scope)


# ----------------------------------------------------------------------------------------------
# Entry points
# ----------------------------------------------------------------------------------------------


def decide(raw: bytes) -> Decision:
    """The whole hook, on the bytes read from stdin. Pure: no I/O, no environment."""
    if not isinstance(raw, bytes | bytearray):
        return deny("MALFORMED-INPUT", "hook input was not bytes")
    if len(raw) == 0:
        return deny("MALFORMED-INPUT", "hook input was empty")
    if len(raw) > MAX_INPUT_BYTES:
        return deny("OVERSIZED-INPUT", f"hook input exceeded {MAX_INPUT_BYTES} bytes")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return deny("MALFORMED-INPUT", "hook input was not valid UTF-8 JSON")
    if not isinstance(payload, dict):
        return deny("MALFORMED-INPUT", "hook input was not a JSON object")
    tool = payload.get("tool_name")
    if tool != "Bash":
        return deny("UNEXPECTED-TOOL", "this hook only decides Bash calls; anything else is denied")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return deny("MALFORMED-INPUT", "tool_input was not an object")
    command = tool_input.get("command")
    if not isinstance(command, str):
        return deny("MALFORMED-INPUT", "tool_input.command was not a string")
    if not command.strip():
        return deny("MALFORMED-INPUT", "tool_input.command was empty")
    if len(command) > MAX_COMMAND_CHARS:
        return deny("OVERSIZED-INPUT", f"command exceeded {MAX_COMMAND_CHARS} characters")
    cwd = payload.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        return deny("MALFORMED-INPUT", "cwd was not a string")
    return evaluate(command, cwd)


def evaluate(command: str, cwd: str | None = None) -> Decision:
    """Decide one command line. Exposed for tests; `decide` is what the hook runs."""
    ctx = _Ctx()
    if cwd:
        if cwd.startswith(("/", "~")):
            ctx.cwd = _normalise(cwd)
        if _protected_hit(cwd):
            ctx.protected_cwd = True
    result = _evaluate_raw(command, ctx)
    if result.denied:
        return result
    return Decision("allow", context=list(ctx.notes))


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        result = decide(raw)
        if result.denied:
            sys.stderr.write(f"guard_bash: DENY [{result.rule}] {result.reason}\n")
            return 2
        if result.context:
            out = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": " ".join(result.context),
                }
            }
            sys.stdout.write(json.dumps(out) + "\n")
        return 0
    except BaseException:  # noqa: BLE001 — D-11: any failure is a DENY, never a non-blocking error
        try:
            sys.stderr.write(INTERNAL_ERROR_LINE + "\n")
        except BaseException:  # noqa: BLE001
            pass
        return 2


# ----------------------------------------------------------------------------------------------
# Lexing: heredocs, segments, tokens
# ----------------------------------------------------------------------------------------------


def _unquoted_heredoc_ops(line: str) -> list[tuple[str, bool, bool]]:
    """(delimiter, strip_tabs, quoted) for every `<<` that is outside quotes on this line."""
    ops: list[tuple[str, bool, bool]] = []
    quote: str | None = None
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == "\\" and quote != "'":
            i += 2
            continue
        if quote:
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue
        if ch == "<" and line.startswith("<<", i) and not line.startswith("<<<", i) and (
            i == 0 or line[i - 1] != "<"
        ):
            m = re.match(r"<<(-?)\s*(?:'([^']*)'|\"([^\"]*)\"|\\?([A-Za-z_][A-Za-z0-9_]*))",
                         line[i:])
            if m:
                delim = m.group(2) or m.group(3) or m.group(4) or ""
                quoted = m.group(2) is not None or m.group(3) is not None
                if delim:
                    ops.append((delim, m.group(1) == "-", quoted))
                i += m.end()
                continue
        i += 1
    return ops


def _strip_heredocs(raw: str) -> tuple[str, list[tuple[str, str]]]:
    """Remove heredoc bodies from `raw`; return the executable text and the bodies that will
    still be executed, tagged ("shell", body) when the heredoc feeds a shell, ("code", body)
    when it feeds an interpreter, and ("shell", substitution) for each `$(...)` / backtick
    inside an unquoted prose heredoc.

    An unterminated heredoc strips nothing: what cannot be parsed is evaluated in full."""
    lines = raw.split("\n")
    kept: list[str] = []
    extra: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        ops = _unquoted_heredoc_ops(line)
        i += 1
        if not ops:
            continue
        owner = _heredoc_owner(line)
        for delim, strip_tabs, quoted in ops:
            body: list[str] = []
            j = i
            terminated = False
            while j < len(lines):
                probe = lines[j].lstrip("\t") if strip_tabs else lines[j]
                if probe == delim:
                    terminated = True
                    break
                body.append(lines[j])
                j += 1
            if not terminated:
                # Fail closed: keep every line as executable text.
                kept.extend(lines[i:])
                return "\n".join(kept), extra
            text = "\n".join(body)
            if owner in ("shell", "code"):
                extra.append((owner, text))
            elif not quoted:
                extra.extend(("shell", s) for s in _substitution_bodies(text))
            i = j + 1
    return "\n".join(kept), extra


def _heredoc_owner(line: str) -> str:
    """'shell' when the heredoc feeds sh/bash, 'code' when it feeds an interpreter, else
    'prose'. The whole line is read (D-04): `cat <<EOF | bash` feeds a shell even though the
    shell sits to the right of the operator. An owner that cannot be parsed counts as a shell
    (fail closed)."""
    head, _, tail = line.partition("<<")
    try:
        words = shlex.split(head + " " + tail, posix=True)
    except ValueError:
        return "shell"
    bases = [_basename(w) for w in words]
    if any(b in SHELLS for b in bases):
        return "shell"
    if any(_interp(b) for b in bases):
        return "code"
    return "prose"


def _code_mentions_protected(code: str) -> str | None:
    for root in PROTECTED_DIRS + PROTECTED_FILES + ("crooks-os", ".claude", ".git/hooks"):
        if root in code:
            return root
    return None


def _code_reads_secrets(code: str) -> bool:
    return CODE_SECRET_RE.search(code) is not None


def _substitution_bodies(text: str) -> list[str]:
    found = re.findall(r"\$\(((?:[^()]|\([^()]*\))*)\)", text)
    found += re.findall(r"`([^`]*)`", text)
    return [f for f in found if f.strip()]


def _substitution_end(text: str, start: int) -> int:
    """Index of the `)` or backtick that closes the substitution opening at `start` (`$(` or a
    backtick), tracking escapes, quotes and nested parentheses. ValueError when it never
    closes: the hook then refuses the command rather than guess where the substitution ends."""
    j = start + 1
    if text[start] == "`":
        while j < len(text):
            if text[j] == "\\":
                j += 2
                continue
            if text[j] == "`":
                return j
            j += 1
        raise ValueError("unterminated backtick substitution")
    depth = 1
    quote: str | None = None
    j = start + 2
    while j < len(text):
        ch = text[j]
        if ch == "\\" and quote != "'":
            j += 2
            continue
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    raise ValueError("unterminated command substitution")


def _segments(text: str, nesting: int = 0) -> list[tuple[str, bool]]:
    """Split at unquoted `;`, newline, `|`, `&`, `(` and `)`. The second element says whether
    the segment is the right-hand side of a single `|`.

    A `$( … )` or backtick substitution is lexed as a piece of a word, not as a boundary: its
    body is emitted first, as segments of its own (it runs, so it is evaluated as usual), and
    the substitution itself is replaced by SUBST_MARKER in the enclosing text. The evaluator
    then sees a dynamic word wherever the substitution's output would be the command word —
    on its own, behind a passthrough wrapper or an assignment, or glued to a literal prefix
    (D-03; F-2/F-3 of the review of d7911b2) — and leaves it inert as an argument
    (`echo $(date)`, `x=$(…)`). An unterminated substitution raises ValueError."""
    if nesting > MAX_SUBSTITUTION_NESTING:
        raise ValueError("substitutions nested too deeply")
    out: list[tuple[str, bool]] = []
    buf: list[str] = []
    quote: str | None = None
    piped = False
    i = 0
    n = len(text)

    def flush(next_piped: bool) -> None:
        nonlocal buf, piped
        seg = "".join(buf).strip()
        if seg:
            out.append((seg, piped))
        buf = []
        piped = next_piped

    while i < n:
        ch = text[i]
        if ch == "\\" and quote != "'":
            buf.append(text[i : i + 2])
            i += 2
            continue
        if quote:
            if ch == quote:
                quote = None
            buf.append(ch)
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "#" and (i == 0 or text[i - 1] in " \t;|&(\n"):
            # A word-initial unquoted `#` starts a comment. shlex's own comment handling would
            # also treat a mid-word `#` as one (`git push origin#x --force` → `--force` lost),
            # so comments are removed here and shlex runs with comments=False.
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "|":
            if text.startswith("||", i):
                flush(False)
                i += 2
            else:
                flush(True)
                i += 1
            continue
        if ch == "`" or text.startswith("$(", i):
            end = _substitution_end(text, i)
            body = text[i + 1 : end] if ch == "`" else text[i + 2 : end]
            out.extend(_segments(body, nesting + 1))
            buf.append(SUBST_MARKER)
            i = end + 1
            continue
        if ch in ("(", ")", ";", "\n", "&"):
            flush(False)
            i += 1
            continue
        buf.append(ch)
        i += 1
    if quote:
        raise ValueError("unbalanced quote")
    flush(False)
    return out


def _double_quoted_substitutions(segment: str) -> list[str]:
    """Bodies of `$(...)` and backtick substitutions that sit inside double quotes."""
    out: list[str] = []
    quote: str | None = None
    i = 0
    n = len(segment)
    while i < n:
        ch = segment[i]
        if ch == "\\" and quote != "'":
            i += 2
            continue
        if quote == '"':
            if ch == '"':
                quote = None
                i += 1
                continue
            if segment.startswith("$(", i):
                depth = 1
                j = i + 2
                while j < n and depth:
                    if segment[j] == "(":
                        depth += 1
                    elif segment[j] == ")":
                        depth -= 1
                    j += 1
                out.append(segment[i + 2 : j - 1])
                i = j
                continue
            if ch == "`":
                j = segment.find("`", i + 1)
                if j == -1:
                    j = n
                out.append(segment[i + 1 : j])
                i = j + 1
                continue
            i += 1
            continue
        if quote == "'":
            if ch == "'":
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
        i += 1
    return [b for b in out if b.strip()]


def _tokens(segment: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Shell words of one segment, and the leading `NAME=value` assignments that were in front
    of the command word (inspected by the evaluator, D-05)."""
    toks = shlex.split(segment, comments=False, posix=True)
    assigned: list[tuple[str, str]] = []
    while toks and (toks[0] in RESERVED or ASSIGNMENT_RE.match(toks[0])):
        t = toks.pop(0)
        m = ASSIGNMENT_RE.match(t)
        if m and t not in RESERVED:
            assigned.append((m.group(1), m.group(2)))
    while toks and toks[-1] in ("{", "}"):
        toks.pop()
    return toks, assigned


def _basename(token: str) -> str:
    return re.sub(r"^.*[\\/]", "", token or "").removesuffix(".exe").lower()


def _interp(base: str) -> str | None:
    """`python3.12` → `python`; returns the code flag's key or None."""
    if re.match(r"^python\d*(\.\d+)?$", base):
        return "python"
    if base in INTERPRETER_CODE_FLAG:
        return base
    return None


def _dynamic_word(word: str) -> bool:
    """A command word the hook cannot resolve statically (D-03): a variable, a substitution,
    a brace form or a glob. `[` and `[[` are the test builtins, not globs."""
    if word in ("[", "[["):
        return False
    return any(c in word for c in DYNAMIC_WORD_CHARS)


# ----------------------------------------------------------------------------------------------
# Evaluation
# ----------------------------------------------------------------------------------------------


def _evaluate_raw(raw: str, ctx: _Ctx) -> Decision:
    if ctx.depth > MAX_DEPTH:
        return deny("UNPARSEABLE", "command nesting exceeded the depth this hook will follow")
    executable, extra = _strip_heredocs(raw)
    try:
        segs = _segments(executable)
    except ValueError:
        return deny("UNPARSEABLE", "command could not be split into shell words (unbalanced "
                    "quote or unterminated substitution)")
    prev_toks: list[str] | None = None
    for seg, piped in segs:
        try:
            toks, assigned = _tokens(seg)
        except ValueError:
            return deny("UNPARSEABLE", "command could not be tokenised (unbalanced quote)")
        if not toks:
            prev_toks = None
            continue
        result = _evaluate_tokens(toks, ctx, piped_from=prev_toks if piped else None,
                                  assigned=assigned)
        if result.denied:
            return result
        prev_toks = toks
        # `echo "$(rm -rf x)"`: a substitution inside DOUBLE quotes still executes. The segmenter
        # leaves quoted text intact, so those bodies are pulled out here and evaluated on their
        # own. Single-quoted text is literal and is left alone.
        for body in _double_quoted_substitutions(seg):
            result = _evaluate_raw(body, ctx.child())
            if result.denied:
                return result
    for kind, body in extra:
        if kind == "code":
            result = _code_rule(body, "interpreter code fed by heredoc")
            if result is not None:
                return result
            continue
        result = _evaluate_raw(body, ctx.child())
        if result.denied:
            return result
    return ALLOW


def _code_rule(code: str, what: str) -> Decision | None:
    root = _code_mentions_protected(code)
    if root:
        return deny("INTERPRETER-PROTECTED-PATH",
                    f"{what} names {root}; the hook cannot see what it does")
    if _code_reads_secrets(code):
        return deny("INTERPRETER-SECRET-READ",
                    f"{what} reads the environment or a credential file; the hook cannot see "
                    "where the value goes")
    return None


def _evaluate_tokens(toks: list[str], ctx: _Ctx, piped_from: list[str] | None = None,
                     assigned: list[tuple[str, str]] | None = None) -> Decision:
    toks = list(toks)
    assigned = list(assigned or [])
    if toks[0] == SUBST_MARKER:
        return deny("UNPARSEABLE", "the command word is the output of a substitution; the hook "
                    "cannot tell what will run")
    first = _basename(toks[0])
    if piped_from and _basename(piped_from[0]) in ("curl", "wget", "fetch") and (
        first in SHELLS or _interp(first)
    ):
        return deny("PIPE-TO-SHELL", "downloading content and piping it into an interpreter")
    for _ in range(8):  # unwrap sudo/env/timeout/... in front of the real command
        if not toks:
            return ALLOW
        if _dynamic_word(toks[0]):
            return deny("UNPARSEABLE", "the command word contains a variable, substitution, "
                        "brace or glob; the hook cannot tell what will run")
        base = _basename(toks[0])
        if base in SHELLS:
            return _shell_rule(toks, ctx, piped_from)
        if base in SHELL_STRING_COMMANDS:
            return _shell_string_rule(base, toks, ctx)
        if base in PASSTHROUGH:
            if base == "env":
                if len(toks) == 1:
                    return deny("SECRET-ECHO", "bare env prints every variable, credentials included")
                split = _env_split_string(toks)
                if split is not None:
                    return _shell_text(split, ctx)
                assigned.extend(_env_assignments(toks))
            toks = _unwrap(base, toks)
            continue
        break
    if not toks:
        return ALLOW
    base = _basename(toks[0])

    # D-01: the credential store is never named, by any command, in any position.
    for t in [*toks, *(v for _n, v in assigned)]:
        hit = _secret_dir_hit(t)
        if hit:
            return deny("SECRET-FILE-READ", f"naming a path under {hit}; the credential store "
                        "is never read, listed or copied by engineering work")

    if base in ("cd", "pushd", "popd"):
        return _cd_rule(base, toks, ctx)

    result = _assignment_rule(assigned, base, toks)
    if result is not None:
        return result

    if piped_from is not None and _interp(base):
        result = _piped_interpreter_rule(base, toks, piped_from)
        if result is not None:
            return result

    checks = (
        _git_rule,
        _rm_rule,
        _find_rule,
        _service_rule,
        _tailscale_rule,
        _make_rule,
        _script_rule,
        _gh_rule,
        _claude_rule,
        _package_rule,
        _disk_rule,
        _secret_rule,
        _interpreter_rule,
        _network_rule,
        _listen_rule,
        _path_rule,
    )
    for check in checks:
        result = check(base, toks, ctx)
        if result is not None and result.denied:
            return result
    return ALLOW


def _shell_text(text: str, ctx: _Ctx) -> Decision:
    """Evaluate text a shell will execute, refusing text the hook cannot read."""
    if any(c in text for c in "$`"):
        return deny("UNPARSEABLE", "shell text containing a variable or substitution; the hook "
                    "cannot tell what will run")
    return _evaluate_raw(text, ctx.child())


def _shell_rule(toks: list[str], ctx: _Ctx, piped_from: list[str] | None) -> Decision:
    """`bash -c '<code>'`, `bash <<< text`, `bash <<EOF`, `echo text | sh`, `bash script.sh`.
    Whatever the shell will run is evaluated when it can be read and refused when it cannot
    (D-04)."""
    try:
        texts = _shell_texts(toks, piped_from)
    except ValueError as exc:
        return deny("UNPARSEABLE", f"a shell would run text the hook cannot read ({exc})")
    for text in texts:
        if text:
            result = _evaluate_raw(text, ctx.child())
            if result.denied:
                return result
    # `bash script.sh` — a script under a protected path is executing production code.
    for t in toks[1:]:
        hit = _protected_hit(t)
        if hit:
            return deny("PROTECTED-PATH", f"executing a script from {hit} is not read-only")
    return ALLOW


def _shell_texts(toks: list[str], piped_from: list[str] | None) -> list[str]:
    """The command text a shell invocation will execute, when the hook can see it. Raises
    ValueError (with a constant message) when the shell would read text the hook cannot see.
    Returns [] for `bash script.sh` (a documented limit) and for a shell whose stdin is a
    heredoc the caller has already evaluated."""
    texts: list[str] = []
    positional: list[str] = []
    stdin_seen = False
    i = 1
    while i < len(toks):
        t = toks[i]
        if t in ("--version", "--help"):
            return []
        if t == "--":
            positional.extend(toks[i + 1:])
            break
        if t.startswith("<<<"):
            operand = t[3:] if len(t) > 3 else (toks[i + 1] if i + 1 < len(toks) else None)
            if operand is None:
                raise ValueError("here-string without text")
            if any(c in operand for c in "$`"):
                raise ValueError("here-string built from a variable or substitution")
            texts.append(operand)
            stdin_seen = True
            i += 1 if len(t) > 3 else 2
            continue
        if t.startswith("<<"):
            stdin_seen = True  # a heredoc; its body is evaluated by the heredoc owner logic
            i += 1 if len(t) > 2 else 2
            continue
        if re.match(r"^\d*<", t):
            raise ValueError("stdin redirected from a file")
        if re.match(r"^\d*(>>|>\||>|&>>|&>)$", t):
            i += 2
            continue
        if re.match(r"^\d*(>>|>\||>|&>>|&>)", t):
            i += 1
            continue
        if t in ("-o", "+o", "-O", "+O"):
            i += 2
            continue
        if t.startswith("-") and not t.startswith("--") and "c" in t[1:]:
            if i + 1 >= len(toks):
                raise ValueError("-c without a command string")
            texts.append(toks[i + 1])
            return texts
        if t.startswith("-") or t.startswith("+"):
            i += 1
            continue
        positional.append(t)
        i += 1
    if texts or stdin_seen:
        return texts
    if positional and positional[0] != "-":
        return []
    if piped_from is not None:
        fed = _fed_text(piped_from)
        if fed is None:
            raise ValueError("piped from a command whose output the hook cannot read")
        return [fed]
    raise ValueError("no command string, script, here-string or heredoc")


def _piped_interpreter_rule(base: str, toks: list[str],
                            piped_from: list[str]) -> Decision | None:
    """`… | python3`: an interpreter with no code flag and no script file runs its stdin. The
    text is checked when it is a literal echo/printf or an evaluated heredoc, refused when it
    is not (D-04)."""
    key = _interp(base) or ""
    flag = INTERPRETER_CODE_FLAG.get(key, "-c")
    if any(t == flag or (key == "node" and t in ("--eval", "-p", "--print")) for t in toks[1:]):
        return None
    positional = [t for t in toks[1:] if not t.startswith("-") and not re.match(r"^\d*[<>]", t)]
    if positional:
        return None  # `cat data | python3 script.py`: the script is the code, a documented limit
    fed = _fed_text(piped_from)
    if fed is None:
        return deny("UNPARSEABLE", "an interpreter would run text from a pipe that the hook "
                    "cannot read")
    return _code_rule(fed, "interpreter code fed by pipe")


def _fed_text(prev: list[str]) -> str | None:
    """The literal text the previous pipeline stage feeds to a shell or interpreter: the
    arguments of a plain `echo`/`printf`, or "" when that stage owns a heredoc the caller has
    already evaluated. None when the text cannot be known."""
    if any(t.startswith("<<") and not t.startswith("<<<") for t in prev):
        return ""
    base = _basename(prev[0])
    if base not in ("echo", "printf"):
        return None
    args = prev[1:]
    if base == "echo":
        if args and args[0].startswith("-") and "e" in args[0]:
            return None  # `echo -e`: escape sequences the hook does not interpret
        while args and args[0] in ("-n", "-E", "-nE", "-En"):
            args = args[1:]
    text = " ".join(args)
    if any(c in text for c in "$`\\") or (base == "printf" and "%" in text):
        return None
    return text


def _shell_string_rule(base: str, toks: list[str], ctx: _Ctx) -> Decision:
    """`eval`, `watch`, `su -c`: the argument is a shell command line (D-03)."""
    if base == "eval":
        text = " ".join(toks[1:])
    elif base == "watch":
        rest: list[str] = []
        i = 1
        while i < len(toks):
            t = toks[i]
            if t in ("-n", "--interval", "-d", "--differences", "-w", "--wait"):
                i += 2
                continue
            if t.startswith("-"):
                i += 1
                continue
            rest.extend(toks[i:])
            break
        text = " ".join(rest)
    else:  # su
        text = ""
        for i, t in enumerate(toks[1:], start=1):
            if t in ("-c", "--command") and i + 1 < len(toks):
                text = toks[i + 1]
                break
            if t.startswith("--command="):
                text = t.split("=", 1)[1]
                break
        if not text:
            return deny("UNPARSEABLE", "su without -c opens a shell the hook cannot read")
    if not text.strip():
        return ALLOW
    return _shell_text(text, ctx)


def _env_split_string(toks: list[str]) -> str | None:
    """`env -S '<string>'` splits and runs the string: return it."""
    for i, t in enumerate(toks[1:], start=1):
        if t in ("-S", "--split-string") and i + 1 < len(toks):
            return toks[i + 1]
        if t.startswith("--split-string="):
            return t.split("=", 1)[1]
        if t.startswith("-S") and len(t) > 2:
            return t[2:]
        if not t.startswith("-") and not ASSIGNMENT_RE.match(t):
            break
    return None


def _env_assignments(toks: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for t in toks[1:]:
        m = ASSIGNMENT_RE.match(t)
        if m:
            out.append((m.group(1), m.group(2)))
        elif not t.startswith("-"):
            break
    return out


def _unwrap(base: str, toks: list[str]) -> list[str]:
    value_opts = {
        "sudo": {"-u", "-g", "-p", "-C", "-D", "-h", "-r", "-t", "-U"},
        "doas": {"-u", "-C"},
        "env": {"-u", "-C", "-S", "--unset", "--chdir", "--split-string"},
        "timeout": {"-s", "-k", "--signal", "--kill-after"},
        "nice": {"-n", "--adjustment"},
        "ionice": {"-c", "-n", "-p", "-P", "-u"},
        "xargs": {"-I", "-n", "-P", "-L", "-d", "-a", "-E", "-s", "--max-args", "--max-procs",
                  "--replace", "--delimiter", "--arg-file"},
        "stdbuf": {"-i", "-o", "-e"},
    }.get(base, set())
    i = 1
    positional_budget = 1 if base == "timeout" else 0
    while i < len(toks):
        t = toks[i]
        if t == "--":
            i += 1
            break
        if t in value_opts:
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        if base == "env" and ASSIGNMENT_RE.match(t):
            i += 1
            continue
        if positional_budget:
            positional_budget -= 1
            i += 1
            continue
        break
    return toks[i:]


def _assignment_rule(assigned: list[tuple[str, str]], base: str,
                     toks: list[str]) -> Decision | None:
    """Leading `NAME=value` words are not dropped unseen (D-05): a value that reaches a
    protected path is a global option to whatever runs next."""
    for name, value in assigned:
        hit = _protected_hit(value)
        if not hit:
            continue
        if name in GIT_ENV_PATHS:
            if base == "git" and _is_read_only(base, toks):
                continue
            return deny("PROTECTED-PATH", f"{name} points git at {hit}")
        if not _is_read_only(base, toks):
            return deny("PROTECTED-PATH", f"an assignment names {hit} for '{base}', which is not "
                        "a read-only command")
    return None


def _cd_rule(base: str, toks: list[str], ctx: _Ctx) -> Decision:
    """Track the working directory through absolute, home, relative and `-` targets (D-10).
    An unresolvable target leaves it unknown; `cd -` with nothing known to return to is
    refused rather than guessed."""
    if base == "popd":
        target = "-"
    else:
        target = next((t for t in toks[1:] if t == "-" or not t.startswith("-")), "")
    new: str | None
    if target == "":
        new = "/root"
    elif target == "-":
        if ctx.prev_cwd is None:
            return deny("UNPARSEABLE", "cd - with no known previous directory leaves the working "
                        "directory ambiguous")
        new = ctx.prev_cwd
    elif any(c in target for c in "$`") or any(c in target for c in GLOB_CHARS):
        new = None
    elif target.startswith(("/", "~")):
        new = _normalise(target)
    elif ctx.cwd is not None:
        new = posixpath.normpath(posixpath.join(ctx.cwd, target))
    else:
        new = None
    ctx.prev_cwd, ctx.cwd = ctx.cwd, new
    if new is not None:
        ctx.protected_cwd = _protected_hit(new) is not None
    elif _protected_hit(target):
        ctx.protected_cwd = True
    return ALLOW


# ----------------------------------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------------------------------


def _path_candidates(token: str) -> list[str]:
    """Every absolute or home-anchored path-looking substring of a token, so that
    `--git-dir=/opt/x`, `>/opt/x`, `2>>/opt/x`, `host:/opt/x` and `-o/opt/x` are all seen."""
    found = re.findall(r"(?:^|(?<=[=:<>,@|&]))((?:~|\$\{HOME\}|\$HOME|/)[^\s:=,<>|&]*)", token)
    found += re.findall(r"^-[A-Za-z]+((?:~|/)[^\s:=,<>|&]*)", token)
    return found


def _normalise(path: str) -> str:
    p = path
    for home in ("${HOME}", "$HOME", "~root", "~"):
        if p == home or p.startswith(home + "/"):
            p = "/root" + p[len(home):]
            break
    p = re.sub(r"^/+", "/", p)  # `//opt/x` is `/opt/x` on Linux; normpath keeps the pair
    if any(c in p for c in GLOB_CHARS):
        return p
    return posixpath.normpath(p)


def _brace_alternatives(token: str) -> list[str] | None:
    """Expand `{a,b}` groups the way the shell would (D-10). None when the form cannot be
    expanded — a `{a..b}` sequence, nested braces, or too many results — which callers treat
    as unknown. `{}` and `{single}` are literal, as in bash."""
    if "{" not in token:
        return [token]
    m = re.match(r"^([^{}]*)\{([^{}]*)\}(.*)$", token, re.DOTALL)
    if not m:
        return None
    pre, body, post = m.groups()
    rest = _brace_alternatives(post)
    if rest is None:
        return None
    if "," not in body:
        if ".." in body:
            return None
        return [pre + "{" + body + "}" + r for r in rest]
    out: list[str] = []
    for alt in body.split(","):
        out.extend(pre + alt + r for r in rest)
        if len(out) > 32:
            return None
    return out


def _hit(token: str, dirs: tuple[str, ...], files: tuple[str, ...]) -> str | None:
    """The constant path in `dirs`/`files` that a token reaches, or None."""
    alts = _brace_alternatives(token)
    if alts is None:
        alts = [token.split("{", 1)[0] + "*"]  # unexpandable brace: a glob under its prefix
    for alt in alts:
        for cand in _path_candidates(alt) or ([alt] if alt.startswith(("/", "~", "$")) else []):
            p = _normalise(cand)
            if any(c in p for c in GLOB_CHARS):
                literal = re.split(r"[*?\[]", p, maxsplit=1)[0]
                for root in dirs + files:
                    # A glob whose literal prefix sits above the root could expand into it; a
                    # glob whose literal prefix sits at or under the root is inside it.
                    if fnmatch.fnmatchcase(root, p) or root.startswith(literal) or \
                            literal == root or literal.startswith(root + "/"):
                        return root
                continue
            for root in dirs:
                if p == root or p.startswith(root + "/"):
                    return root
            for f in files:
                if p == f:
                    return f
    return None


def _protected_hit(token: str) -> str | None:
    return _hit(token, PROTECTED_DIRS, PROTECTED_FILES)


def _secret_dir_hit(token: str) -> str | None:
    return _hit(token, SECRET_DIRS, ())


def _sensitive_project_path(token: str) -> str | None:
    """`.claude/…` and `.git/hooks/…` in any spelling, relative or absolute (D-08)."""
    t = re.sub(r"^\d*(>>|>\||>|&>>|&>|<)", "", token)
    parts = t.split("/")
    if ".claude" in parts:
        return ".claude"
    if ".git" in parts:
        k = parts.index(".git")
        if parts[k + 1:k + 2] == ["hooks"]:
            return ".git/hooks"
    return None


def _verb_after_options(toks: list[str], value_opts: frozenset[str]) -> str:
    i = 1
    while i < len(toks):
        t = toks[i]
        if t in value_opts:
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        return t
    return ""


def _is_read_only(base: str, toks: list[str]) -> bool:
    if base == "git":
        call = _git_subcommand(toks)
        return call is not None and _git_read_only(call.sub, call.rest)
    if base == "systemctl":
        return (_verb_after_options(toks, SYSTEMCTL_VALUE_OPTS) or "list-units") in READ_ONLY_SYSTEMCTL
    if base == "sed":
        return not any(t == "--in-place" or t.startswith("--in-place=") or
                       (t.startswith("-") and not t.startswith("--") and "i" in t[1:])
                       for t in toks[1:])
    if base == "find":
        return not any(t in ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint",
                             "-fprintf", "-fls", "-fprint0") for t in toks[1:])
    return base in READ_ONLY_COMMANDS


def _write_target_problem(target: str, what: str, ctx: _Ctx, *,
                          remote_ok: bool = False) -> Decision | None:
    """A redirect or copy destination, resolved the way the shell will resolve it (F-1): a
    relative target is joined to the tracked working directory before the protected-path
    check, and a target that is not absolute is refused outright when the working directory
    is a protected checkout — whether or not the exact directory is known, and whatever the
    base command's read-only status. `remote_ok` leaves `host:path` destinations alone."""
    anchored = target.startswith(("/", "~", "$"))
    remote = remote_ok and re.match(r"^[^/]*:", target) is not None
    resolved = target
    if not anchored and not remote and ctx.cwd is not None:
        resolved = posixpath.join(ctx.cwd, target)
    hit = _protected_hit(resolved)
    if hit:
        return deny("PROTECTED-PATH", f"{what} into {hit}")
    if ctx.protected_cwd and not remote and not _normalise(resolved).startswith("/"):
        return deny("PROTECTED-CWD", f"{what} to a relative path while the working directory "
                    "is a protected checkout")
    return _sensitive_write(target)


def _path_rule(base: str, toks: list[str], ctx: _Ctx) -> Decision | None:
    # Redirections into a protected or write-sensitive path, whatever the command.
    targets: list[str] = []
    for i, t in enumerate(toks):
        if re.match(r"^\d*(&>>|&>|>>|>\||>)$", t):
            if i + 1 < len(toks):
                targets.append(toks[i + 1])
            continue
        m = re.match(r"^\d*(&>>|&>|>>|>\||>)([^>|&].*)$", t)
        if m:
            targets.append(m.group(2))
    for target in targets:
        result = _write_target_problem(target, "redirecting output", ctx)
        if result is not None:
            return result
    if base in ("cp", "scp", "rsync", "install"):
        positional = [t for t in toks[1:] if not t.startswith("-")]
        if positional:
            result = _write_target_problem(positional[-1], base, ctx,
                                           remote_ok=base in ("scp", "rsync"))
            if result is not None:
                return result
        return None
    read_only = _is_read_only(base, toks)
    hits = [h for h in (_protected_hit(t) for t in toks) if h]
    if hits and not read_only:
        return deny("PROTECTED-PATH", f"'{base}' is not a read-only command and it names {hits[0]}")
    if not read_only:
        git_ok = False
        if base == "git":
            call = _git_subcommand(toks)
            git_ok = call is not None and call.sub in GIT_SENSITIVE_PATH_OK
        if not git_ok:
            for t in toks[1:]:
                result = _sensitive_write(t)
                if result is not None:
                    return result
    if ctx.protected_cwd and not read_only and base not in ("cd", "pushd", "popd"):
        return deny("PROTECTED-CWD", f"'{base}' is not read-only and the working directory is a "
                    "protected checkout")
    return None


def _sensitive_write(token: str) -> Decision | None:
    sens = _sensitive_project_path(token)
    if sens == ".claude":
        return deny("PROJECT-CLAUDE-WRITE", "writing under a .claude/ directory changes the hooks, "
                    "rules or permissions that govern this session")
    if sens == ".git/hooks":
        return deny("GIT-HOOKS-WRITE", "writing under .git/hooks/ installs code that runs on "
                    "every commit")
    return None


# ----------------------------------------------------------------------------------------------
# git — the ported ECC table, then CROOKS additions
# ----------------------------------------------------------------------------------------------


@dataclass
class _GitCall:
    sub: str
    rest: list[str]
    paths: list[str]  # values of -C, --git-dir, --work-tree
    configs: list[str]  # values of -c and --config-env
    chdir: str | None  # the last -C value: the checkout git runs in


def _git_subcommand(toks: list[str]) -> _GitCall | None:
    """The subcommand and what precedes it — skips git's own global options, recording the
    ones that matter (paths, `-c` configuration, `-C`). Only options *before* the subcommand
    are global: `git commit -C HEAD` is a commit option (D-16)."""
    if not toks or _basename(toks[0]) != "git":
        return None
    value_long = {"--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env"}
    paths: list[str] = []
    configs: list[str] = []
    chdir: str | None = None
    i = 1
    while i < len(toks):
        t = toks[i]
        if t in ("-c", "-C") or t in value_long:
            value = toks[i + 1] if i + 1 < len(toks) else ""
            if t == "-c" or t == "--config-env":
                configs.append(value)
            elif t == "-C":
                paths.append(value)
                chdir = value
            elif t in ("--git-dir", "--work-tree"):
                paths.append(value)
            i += 2
            continue
        if t.startswith(("--git-dir=", "--work-tree=")):
            paths.append(t.split("=", 1)[1])
            i += 1
            continue
        if t.startswith("--config-env="):
            configs.append(t.split("=", 1)[1])
            i += 1
            continue
        if t.startswith("-"):
            i += 1
            continue
        return _GitCall(t.lower(), toks[i + 1:], paths, configs, chdir)
    return None


def _short_has(t: str, letter: str) -> bool:
    return t.startswith("-") and not t.startswith("--") and letter in t[1:]


def _positionals(rest: list[str]) -> list[str]:
    return [t for t in rest if not t.startswith("-")]


def _git_read_only(sub: str, rest: list[str]) -> bool:
    if sub in GIT_READ_ONLY_SUBS:
        return True
    if sub == "remote":
        return not rest or rest[0] in ("-v", "--verbose", "show", "get-url")
    if sub == "branch":
        if any(t in GIT_BRANCH_MUTATING_FLAGS for t in rest):
            return False
        flags = [t for t in rest if t.startswith("-")]
        return bool(flags) or not _positionals(rest)
    if sub == "tag":
        if any(t in ("-d", "--delete", "-a", "-s", "-f", "--force", "-m", "-F") for t in rest):
            return False
        return not rest or any(t in ("-l", "--list") or t.startswith(("-n", "--contains",
                               "--points-at", "--merged", "--no-merged", "--sort")) for t in rest)
    if sub == "config":
        return any(t in GIT_CONFIG_READ_FLAGS for t in rest)
    if sub == "stash":
        return rest[:1] in (["list"], ["show"])  # bare `git stash` is `stash push` (D-02)
    if sub == "reflog":
        return not rest or rest[0] not in ("expire", "delete")
    if sub == "worktree":
        return rest[:1] == ["list"]
    if sub == "symbolic-ref":
        return not any(t in ("-d", "--delete") for t in rest) and len(_positionals(rest)) <= 1
    if sub == "hash-object":
        return "-w" not in rest
    if sub == "notes":
        return not rest or rest[0] in ("list", "show")
    return False


def _push_destinations(rest: list[str]) -> list[str]:
    """Refspec destinations named by a `git push`; the branch names only (no refs/heads/)."""
    value_opts = {"-o", "--push-option", "--receive-pack", "--exec", "--repo"}
    positional: list[str] = []
    remote_via_flag = False
    i = 0
    while i < len(rest):
        t = rest[i]
        if t == "--repo":
            remote_via_flag = True
            i += 2
            continue
        if t.startswith("--repo="):
            remote_via_flag = True
            i += 1
            continue
        if t in value_opts:
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        positional.append(t)
        i += 1
    refspecs = positional if remote_via_flag else positional[1:]
    out: list[str] = []
    for spec in refspecs:
        cleaned = spec[1:] if spec.startswith("+") else spec
        dst = cleaned.split(":", 1)[1] if ":" in cleaned else cleaned
        out.append(dst.removeprefix("refs/heads/"))
    return out


def _git_rule(base: str, toks: list[str], ctx: _Ctx) -> Decision | None:
    if base != "git":
        return None
    call = _git_subcommand(toks)
    if call is None:
        return None
    command, rest = call.sub, call.rest
    if _dynamic_word(command):
        # F-4: `git $p --force`, `git ${SUB} --hard` — the flags below are only read under the
        # literal subcommand they belong to, so an unknown subcommand is refused, not ignored.
        return deny("UNPARSEABLE", "the git subcommand contains a variable, substitution, brace "
                    "or glob; the hook cannot tell which git command will run")

    # ---- global `-c` / `--config-env` (D-06) ----------------------------------------------------
    for conf in call.configs:
        key = conf.split("=", 1)[0].lower()
        if key == "core.hookspath":
            return deny("GIT-CONFIG-HOOKSPATH", "core.hooksPath changes what runs on every commit")
        if GIT_EXEC_CONFIG_RE.match(key):
            return deny("GIT-CONFIG-EXEC", "git -c with a configuration key whose value is a "
                        "command git would run (fsmonitor, sshCommand, pager, editor, "
                        "credential helper, alias, filter, …)")

    # ---- ECC GateGuard table (ported) ---------------------------------------------------------
    if command == "reset":
        if "--hard" in rest:
            return deny("GIT-RESET-HARD", "git reset --hard discards the working tree")
        if "--merge" in rest:  # CROOKS addition
            return deny("GIT-RESET-MERGE", "git reset --merge discards working-tree changes")
        ctx.note(CONTEXT_TEXT)
    if command == "checkout":
        if any(t in ("--", ".", "--force") or _short_has(t, "f") for t in rest):
            return deny("GIT-CHECKOUT-DISCARD", "git checkout -- / . / -f discards uncommitted work")
        if any(_short_has(t, "B") for t in rest):  # CROOKS addition
            return deny("GIT-CHECKOUT-FORCE-BRANCH", "git checkout -B resets an existing branch")
    if command == "clean":
        if any(t == "--force" or _short_has(t, "f") for t in rest):
            return deny("GIT-CLEAN-FORCE", "git clean -f deletes untracked files")
    if command == "push":
        with_lease = bare_force = plus_refspec = False
        for t in rest:
            if t == "--force-with-lease" or t.startswith("--force-with-lease="):
                with_lease = True
            elif t == "--force" or t.startswith("--force="):
                bare_force = True
            elif _short_has(t, "f"):
                bare_force = True
            elif t.startswith("+") and len(t) > 1 and re.match(r"^\+(?:[A-Za-z_/.:]|HEAD)", t):
                plus_refspec = True
        if bare_force or (plus_refspec and not with_lease):
            return deny("GIT-PUSH-FORCE", "force push rewrites a published ref")
        dests = _push_destinations(rest)
        if with_lease and any(d in SHARED_BRANCHES for d in dests):
            return deny("GIT-PUSH-FORCE", "lease-checked force push to a shared branch")
        # CROOKS additions
        if any(t in ("--delete", "-d", "--mirror", "--prune") for t in rest):
            return deny("GIT-PUSH-DELETE", "push that deletes or prunes remote refs")
        for spec in _positionals(rest)[1:]:
            if spec.startswith(":"):
                return deny("GIT-PUSH-DELETE", "an empty-source refspec deletes the remote ref")
        if "--all" in rest:
            return deny("GIT-PUSH-PROTECTED-REF", "git push --all publishes every local branch; "
                        "name the candidate branch instead")
        for d in dests:
            if d in PROTECTED_REFS:
                return deny("GIT-PUSH-PROTECTED-REF",
                            f"pushing to '{d}' is outside the engineering contract")
        ctx.note(CONTEXT_TEXT)
    if command == "commit" and "--amend" in rest:
        return deny("GIT-COMMIT-AMEND", "git commit --amend rewrites the last commit")
    if command == "rm" and any(_short_has(t, "r") or _short_has(t, "R") for t in rest):
        return deny("GIT-RM-RECURSIVE", "git rm -r removes trees from the index and worktree")
    if command == "switch":
        if any(t in ("--discard-changes", "--force") or _short_has(t, "f") or _short_has(t, "C")
               for t in rest):
            return deny("GIT-SWITCH-DISCARD", "git switch --discard-changes / -f / -C")
    if command == "branch":
        delete = force = False
        for t in rest:
            if t == "--delete":
                delete = True
            elif t == "--force":
                force = True
            elif t.startswith("-") and not t.startswith("--"):
                body = t[1:]
                if "D" in body:
                    return deny("GIT-BRANCH-FORCE-DELETE", "git branch -D orphans commits")
                delete = delete or "d" in body
                force = force or "f" in body
        if delete and force:
            return deny("GIT-BRANCH-FORCE-DELETE", "git branch --delete --force orphans commits")
        if delete:
            ctx.note(CONTEXT_TEXT)
    if command == "stash":
        if rest[:1] in (["drop"], ["clear"]):
            return deny("GIT-STASH-DROP", "git stash drop/clear destroys stashed work")
        if rest[:1] not in (["list"], ["show"]):
            ctx.note(CONTEXT_TEXT)  # bare `git stash` included: it is `stash push` (D-02)
    if command == "reflog" and rest[:1] in (["expire"], ["delete"]):
        return deny("GIT-REFLOG-EXPIRE", "git reflog expire/delete removes the recovery net")
    if command == "update-ref" and any(t in ("-d", "--delete") for t in rest):
        return deny("GIT-UPDATE-REF-DELETE", "git update-ref -d deletes a ref")
    if command == "restore":
        staged = any(t == "--staged" or _short_has(t, "S") for t in rest)
        worktree = any(t == "--worktree" or _short_has(t, "W") for t in rest)
        if worktree or not staged:
            return deny("GIT-RESTORE-WORKTREE", "git restore overwrites the working tree")

    # ---- CROOKS additions --------------------------------------------------------------------
    if command == "rebase" and rest[:1] not in (["--abort"], ["--quit"], ["--continue"]):
        return deny("GIT-REBASE-REWRITE", "rebase rewrites history a review may already bind")
    if command in ("filter-branch", "filter-repo", "replace"):
        return deny("GIT-HISTORY-REWRITE", f"git {command} rewrites history")
    if command == "tag" and any(t in ("-d", "--delete") for t in rest):
        return deny("GIT-TAG-DELETE", "git tag -d deletes a ref")
    if command == "remote" and rest[:1] in (["remove"], ["rm"], ["prune"], ["set-url"], ["rename"],
                                            ["set-head"]):
        return deny("GIT-REMOTE-MUTATE", "changing remotes redirects where candidates are published")
    if command == "worktree":
        if rest[:1] == ["remove"] and any(t in ("-f", "--force") for t in rest):
            return deny("GIT-WORKTREE-FORCE-REMOVE", "git worktree remove --force discards work")
        if rest[:1] in (["remove"], ["prune"]):
            ctx.note(CONTEXT_TEXT)
    if command == "gc" and any(t.startswith("--prune") for t in rest):
        return deny("GIT-GC-PRUNE", "git gc --prune deletes unreachable objects")
    if command in ("prune", "prune-packed"):
        return deny("GIT-GC-PRUNE", f"git {command} deletes unreachable objects")
    if command == "config" and not _git_read_only("config", rest):
        keys = [t.lower() for t in _positionals(rest)]
        if any(k == "core.hookspath" for k in keys):
            return deny("GIT-CONFIG-HOOKSPATH", "core.hooksPath changes what runs on every commit")
        if any(GIT_EXEC_CONFIG_RE.match(k) for k in keys):
            return deny("GIT-CONFIG-EXEC", "git config of a key whose value is a command git "
                        "would run (fsmonitor, sshCommand, pager, editor, credential helper, "
                        "alias, filter, …)")
        if any(t in ("--global", "--system") for t in rest):
            return deny("GIT-CONFIG-GLOBAL", "writing global/system git config is account-level")
    if command == "symbolic-ref" and any(t in ("-d", "--delete") for t in rest):
        return deny("GIT-SYMBOLIC-REF-DELETE", "git symbolic-ref -d deletes a ref")
    for p in call.paths:
        hit = _protected_hit(p)
        if hit and not _git_read_only(command, rest):
            return deny("PROTECTED-PATH", f"git {command} against the checkout at {hit}")
    return None


# ----------------------------------------------------------------------------------------------
# rm / find
# ----------------------------------------------------------------------------------------------


def _delete_target_problem(target: str, ctx: _Ctx) -> str | None:
    """Why a recursive delete of this target is refused, or None when it is acceptable."""
    if "$" in target or "`" in target:
        return "target contains an unexpanded variable or substitution"
    if "{}" in target:
        # `find … -exec rm -rf {}`: the start directory is what `find` deletes under, and the
        # find rule checks it. Anywhere else (xargs -I{}) the value is unknown (D-10).
        return None if ctx.find_scope is not None else \
            "target is a placeholder whose value the hook cannot see"
    alts = _brace_alternatives(target)
    if alts is None:
        return "target uses a brace form the hook cannot expand"
    for alt in alts:
        problem = _delete_one_problem(alt, ctx)
        if problem:
            return problem
    return None


def _delete_one_problem(target: str, ctx: _Ctx) -> str | None:
    t = _normalise(target)
    if t in ("/", "~", "/root", ".", "..", "./", "../", "*", "./*", "~/"):
        return "target is the filesystem root, the home directory, the current directory or a bare glob"
    if t.startswith("../") or "/../" in t or t.endswith("/.."):
        return "target is a parent-relative path"
    resolved = False
    if not t.startswith("/") and ctx.cwd is not None:
        joined = posixpath.join(ctx.cwd, t)
        t = joined if any(c in t for c in GLOB_CHARS) else posixpath.normpath(joined)
        resolved = True
    parts = [p for p in t.split("/") if p]
    if ".git" in parts:
        return "target contains a .git component"
    if ".claude" in parts:
        return "target contains a .claude component"
    hit = _protected_hit(target) or (_protected_hit(t) if t.startswith("/") else None)
    if hit:
        return f"target is under a protected path ({hit})"
    if t.startswith("/"):
        if len(parts) <= 1:
            return "target is a top-level directory"
        if any(c in t for c in GLOB_CHARS) and not any(
            t.startswith(r + "/") and len(parts) >= 2 for r in TMP_ROOTS
        ):
            return "target is an absolute glob outside /tmp"
        roots = list(CHECKOUT_ROOTS)
        if ".worktrees" in parts:
            k = parts.index(".worktrees")
            if len(parts) <= k + 2:
                return "target is a worktree directory or the .worktrees tree itself"
            roots = ["/" + "/".join(parts[:k + 2])]  # the worktree is a checkout of its own
        if any(t == r for r in CHECKOUT_ROOTS):
            return "target is a checkout root"
        if any(t.startswith(r + "/") for r in TMP_ROOTS):
            return None
        for r in roots:
            if t.startswith(r + "/"):
                # Strictly inside a checkout. For a path written out in full, at least two
                # levels below its root: the top-level trees (`crooks-assistant`, `.tooling`)
                # are not deleted by a hook-guarded worker. A relative target resolved against
                # the tracked cwd keeps the previous contract: inside the checkout is enough.
                below = [p for p in t[len(r):].split("/") if p]
                if len(below) >= (1 if resolved else 2):
                    return None
                return "target is a top-level tree of a checkout"
        return "target is an absolute path outside /tmp, /var/tmp or a builder checkout"
    if ctx.protected_cwd:
        return "target is relative to a protected working directory"
    return None


def _rm_rule(base: str, toks: list[str], ctx: _Ctx) -> Decision | None:
    if base != "rm":
        return None
    if "--no-preserve-root" in toks:
        return deny("RM-NO-PRESERVE-ROOT", "rm --no-preserve-root")
    flags: list[str] = []
    targets: list[str] = []
    seen_dd = False
    for t in toks[1:]:
        if seen_dd or not t.startswith("-"):
            targets.append(t)
        elif t == "--":
            seen_dd = True
        else:
            flags.append(t)
    recursive = "--recursive" in flags or any(_short_has(f, "r") or _short_has(f, "R")
                                              for f in flags)
    if not recursive:
        return None  # a plain rm on a protected path is caught by _path_rule
    if not targets:
        return deny("RM-RECURSIVE", "recursive delete without a target")
    for target in targets:
        problem = _delete_target_problem(target, ctx)
        if problem:
            return deny("RM-RECURSIVE", f"recursive delete refused: {problem}")
    ctx.note(CONTEXT_TEXT)
    return None


def _find_rule(base: str, toks: list[str], ctx: _Ctx) -> Decision | None:
    if base != "find":
        return None
    starts: list[str] = []
    i = 1
    while i < len(toks) and not toks[i].startswith(("-", "(", "!")):
        starts.append(toks[i])
        i += 1
    if not starts:
        starts = ["."]
    destructive = "-delete" in toks
    j = 0
    while j < len(toks):
        if toks[j] in ("-exec", "-execdir", "-ok", "-okdir"):
            cmd: list[str] = []
            k = j + 1
            while k < len(toks) and toks[k] not in (";", "+"):
                cmd.append(toks[k])
                k += 1
            if cmd:
                ctx.find_scope = starts[0]
                try:
                    inner = _evaluate_tokens(cmd, ctx)
                finally:
                    ctx.find_scope = None
                if inner.denied:
                    return inner
                if _basename(cmd[0]) in ("rm", "rmdir", "unlink", "shred", "mv", "chmod", "chown",
                                         "truncate", "git"):
                    destructive = True
            j = k
        j += 1
    if not destructive:
        return None
    for s in starts:
        # `find .` is the ordinary form and the expression narrows it; the recursive-delete
        # classification applies to everything else (absolute, parent-relative, protected).
        if _normalise(s) == "." and not ctx.protected_cwd:
            continue
        problem = _delete_target_problem(s, ctx)
        if problem:
            return deny("FIND-DELETE", f"find with -delete/-exec refused: {problem}")
    ctx.note(CONTEXT_TEXT)
    return None


# ----------------------------------------------------------------------------------------------
# Services, Tailscale, make, scripts, gh, claude, packages, disks, secrets, interpreters, network
# ----------------------------------------------------------------------------------------------


def _service_rule(base: str, toks: list[str], ctx: _Ctx) -> Decision | None:
    if base == "systemctl":
        verb = _verb_after_options(toks, SYSTEMCTL_VALUE_OPTS) or "list-units"
        if verb not in READ_ONLY_SYSTEMCTL:
            return deny("SERVICE-MUTATION", f"systemctl {verb} — services are an owner decision")
    if base == "service":
        if not (len(toks) >= 3 and toks[2] == "status"):
            return deny("SERVICE-MUTATION", "service <unit> <verb> other than status")
    if base == "launchctl":
        verb = next((t for t in toks[1:] if not t.startswith("-")), "list")
        if verb not in READ_ONLY_LAUNCHCTL:
            return deny("SERVICE-MUTATION", f"launchctl {verb}")
    if base == "crontab" and not any(t == "-l" for t in toks[1:]):
        return deny("SERVICE-MUTATION", "crontab installs persistence")
    if base in ("systemd-run", "at", "batch"):
        return deny("SERVICE-MUTATION", f"{base} starts a transient or scheduled unit; services "
                    "and persistence are an owner decision")
    return None


def _tailscale_rule(base: str, toks: list[str], ctx: _Ctx) -> Decision | None:
    if base != "tailscale":
        return None
    args = [t for t in toks[1:] if not t.startswith("-")]
    verb = args[0] if args else "status"
    if verb in ("serve", "funnel"):
        if args[1:] == ["status"]:
            return None
        return deny("TAILSCALE-MUTATION", f"tailscale {verb} changes the route exposure")
    if verb == "dns" and args[1:2] not in (["status"], []):
        return deny("TAILSCALE-MUTATION", "tailscale dns mutation")
    if verb not in READ_ONLY_TAILSCALE:
        return deny("TAILSCALE-MUTATION", f"tailscale {verb} is not a read-only command")
    return None


def _make_rule(base: str, toks: list[str], ctx: _Ctx) -> Decision | None:
    if base != "make":
        return None
    targets = [t for t in toks[1:] if not t.startswith("-") and "=" not in t]
    variables = [t for t in toks[1:] if "=" in t and not t.startswith("-")]
    for t in targets:
        if t in MAKE_SERVICE_TARGETS:
            return deny("SERVICE-MUTATION", f"make {t} installs, starts or restarts services")
        if t in MAKE_SECRET_TARGETS:
            return deny("SECRET-PROVISION", f"make {t} stores credentials")
        if t in MAKE_LIVE_TARGETS:
            return deny("LIVE-BUSINESS-CALL", f"make {t} calls a live business API")
    if "control" in targets and any(v.upper() in ("WHAT=APPLY", "WHAT=ROLLBACK", "WHAT=MARK-GOOD")
                                    for v in variables):
        return deny("DEPLOY-ACTION", "make control apply/rollback/mark-good changes production")
    if "write-check" in targets and any(v.upper() == "COMMIT=1" for v in variables):
        return deny("LIVE-BUSINESS-CALL", "make write-check COMMIT=1 performs a real write")
    return None


def _script_rule(base: str, toks: list[str], ctx: _Ctx) -> Decision | None:
    # Only when the script would RUN: as the command itself, or under an interpreter/shell.
    # `cat scripts/set_secrets.py` reads source and is not this rule's business.
    runs = _interp(base) is not None or base in SHELLS
    for i, t in enumerate(toks[:3]):
        if i > 0 and not runs:
            break
        name = _basename(t)
        if name in SCRIPT_RULES:
            rule, why = SCRIPT_RULES[name]
            return deny(rule, f"{name} {why}")
        if name == "control.py" and any(a in ("apply", "rollback", "mark-good") for a in toks):
            return deny("DEPLOY-ACTION", "control.py apply/rollback/mark-good changes production")
        if name == "write_check.py" and any(a in ("--commit", "COMMIT=1") for a in toks):
            return deny("LIVE-BUSINESS-CALL", "write_check.py --commit performs a real write")
    if base == "crooks-update":
        return deny("DEPLOY-ACTION", "crooks-update pulls, installs and restarts")
    if base == "crooks-control" and any(a in ("apply", "rollback", "mark-good") for a in toks):
        return deny("DEPLOY-ACTION", "crooks-control apply/rollback/mark-good")
    return None


def _gh_rule(base: str, toks: list[str], ctx: _Ctx) -> Decision | None:
    if base != "gh" or len(toks) < 2:
        return None
    group = toks[1]
    verb = toks[2] if len(toks) > 2 else ""
    if group == "auth" and verb in ("login", "logout", "refresh", "setup-git", "token"):
        rule = "SECRET-ECHO" if verb == "token" else "ACCOUNT-MUTATION"
        return deny(rule, f"gh auth {verb}")
    if group == "pr" and verb == "merge":
        return deny("OUTWARD-MUTATION", "gh pr merge — merging is never the worker's call")
    if group == "repo" and verb in ("delete", "archive", "edit", "rename", "sync"):
        return deny("OUTWARD-MUTATION", f"gh repo {verb}")
    if group == "release" and verb in ("create", "delete", "upload", "edit"):
        return deny("OUTWARD-MUTATION", f"gh release {verb}")
    if group in ("secret", "variable") and verb in ("set", "delete", "remove"):
        return deny("SECRET-PROVISION", f"gh {group} {verb}")
    if group == "api":
        method = ""
        for i, t in enumerate(toks):
            if t in ("-X", "--method") and i + 1 < len(toks):
                method = toks[i + 1].upper()
            elif t.startswith("--method="):
                method = t.split("=", 1)[1].upper()
            elif t.startswith("-X") and len(t) > 2:
                method = t[2:].upper()
        if method not in ("", "GET", "HEAD") or any(
            t in ("-f", "-F", "--field", "--raw-field", "--input") for t in toks
        ):
            return deny("OUTWARD-MUTATION", "gh api with a mutating method or a request body")
    return None


CLAUDE_READ_ONLY = frozenset({("mcp", "list"), ("mcp", "get"), ("plugin", "list"),
                              ("config", "get"), ("config", "list"), ("config", "ls")})


def _claude_rule(base: str, toks: list[str], ctx: _Ctx) -> Decision | None:
    """`claude` from inside a session: only version/help/doctor and read-only queries of the
    account configuration pass. A nested session — print mode, a different permission mode,
    other setting sources, another MCP config, `--bare` — runs outside this harness (D-07)."""
    if base != "claude":
        return None
    args = toks[1:]
    if args and args[0] in ("--version", "-v", "--help", "-h", "doctor"):
        return None
    group = args[0] if args else ""
    verb = args[1] if len(args) > 1 else ""
    if group in ("mcp", "plugin", "config"):
        if (group, verb) in CLAUDE_READ_ONLY or verb in ("", "--help", "-h"):
            return None
        return deny("GLOBAL-CLAUDE-CONFIG", f"claude {group} {verb} changes account-level configuration")
    if group in ("install", "update", "migrate-installer", "setup-token", "login", "logout",
                 "auth"):
        return deny("GLOBAL-CLAUDE-CONFIG", f"claude {group} changes the account-level install or login")
    return deny("NESTED-CLAUDE-SESSION", "launching a nested Claude session (print mode, "
                "permission, settings, MCP, plugin or bare flags) from inside a session escapes "
                "this harness")


def _package_rule(base: str, toks: list[str], ctx: _Ctx) -> Decision | None:
    if base in PACKAGE_MANAGERS:
        verb = next((t for t in toks[1:] if not t.startswith("-")), "")  # `-y` is not a verb (D-09)
        short = [t for t in toks[1:] if t.startswith("-") and not t.startswith("--")]
        if verb in PACKAGE_MUTATING_VERBS or any(s in PACKAGE_MUTATING_VERBS for s in short):
            return deny("SYSTEM-PACKAGE", f"{base} {verb or short[0]} changes the system (and /usr "
                        "is read-only)")
    if base == "dpkg" and any(t in ("-i", "--install", "-r", "--remove", "-P", "--purge",
                                    "--configure", "--unpack") for t in toks[1:]):
        return deny("SYSTEM-PACKAGE", "dpkg install/remove changes the system")
    if base == "npm" and toks[1:2] in (["install"], ["i"], ["add"], ["link"], ["uninstall"],
                                        ["update"]):
        if any(t in ("-g", "--global") for t in toks) or toks[1] == "link":
            return deny("GLOBAL-PACKAGE", "npm global install/link writes outside the checkout")
    if base == "pip" or re.match(r"^pip3(\.\d+)?$", base):
        if toks[1:2] == ["install"] and any(t in ("--user", "--break-system-packages", "--system")
                                             for t in toks):
            return deny("GLOBAL-PACKAGE", "pip install outside a virtual environment")
    return None


def _disk_rule(base: str, toks: list[str], ctx: _Ctx) -> Decision | None:
    if base in DISK_COMMANDS or base.startswith("mkfs."):
        return deny("DISK-DESTRUCTIVE", f"{base}")
    if base == "dd" and any(t.startswith("of=/dev/") for t in toks):
        return deny("DISK-DESTRUCTIVE", "dd writing to a device")
    for t in toks:
        m = re.match(r"^\d*(>>|>)(/dev/(sd|nvme|vd|hd|mmcblk|disk).*)$", t)
        if m:
            return deny("DISK-DESTRUCTIVE", "redirecting into a block device")
    return None


def _names_secret_variable(text: str) -> bool:
    return any(SECRET_NAME_RE.search(name) for name in SECRET_VAR_REF_RE.findall(text))


def _secret_basename(name: str) -> bool:
    if SECRET_FILE_RE.match(name) and not SECRET_FILE_EXAMPLES.match(name):
        return True
    if name.startswith(".") and any(c in name for c in GLOB_CHARS):
        return any(fnmatch.fnmatchcase(dot, name) for dot in SECRET_DOTFILES)
    return False


def _secret_rule(base: str, toks: list[str], ctx: _Ctx) -> Decision | None:
    args = toks[1:]
    if base in ("env", "printenv") and not [a for a in args if not a.startswith("-")]:
        return deny("SECRET-ECHO", f"bare {base} prints every variable, credentials included")
    if base == "printenv" and any(SECRET_NAME_RE.search(a) for a in args):
        return deny("SECRET-ECHO", "printing a credential-named variable")
    if base in ("echo", "printf") and any(_names_secret_variable(a) for a in args):
        return deny("SECRET-ECHO", "echoing a credential-named variable")
    for i, t in enumerate(toks):
        operand = t[3:] if t.startswith("<<<") and len(t) > 3 else (
            toks[i + 1] if t == "<<<" and i + 1 < len(toks) else "")
        if operand and _names_secret_variable(operand):
            return deny("SECRET-ECHO", "feeding a credential-named variable to a command as text")
    if base in ("set", "declare", "typeset", "export") and (
        not args or all(a in ("-p", "-x", "-px", "-xp") for a in args)
    ):
        return deny("SECRET-ECHO", f"bare {base} dumps the environment")
    if any(PROC_ENVIRON_RE.match(t) for t in toks):
        return deny("SECRET-ECHO", "/proc/<pid>/environ is the environment, credentials included")
    if base == "security" and any(a in ("-w", "-g") for a in args) and args[:1] and \
            args[0].startswith("find-"):
        return deny("SECRET-ECHO", "reading a keychain password")
    if base == "keyring":
        if args[:1] == ["get"]:
            return deny("SECRET-ECHO", "keyring get prints a credential")
        if args[:1] in (["set"], ["del"], ["delete"]):
            return deny("SECRET-PROVISION", f"keyring {args[0]}")
    if base == "secret-tool":
        if args[:1] == ["lookup"]:
            return deny("SECRET-ECHO", "secret-tool lookup prints a credential")
        if args[:1] in (["store"], ["clear"]):
            return deny("SECRET-PROVISION", f"secret-tool {args[0]}")
    if base in FILE_READERS or _interp(base):
        for a in args:
            if _secret_basename(_basename(a)):
                return deny("SECRET-FILE-READ", "reading a credential file into the transcript")
    # `< .env` feeds the file to whatever the command is (D-12).
    for i, t in enumerate(toks):
        m = re.match(r"^\d*<(?!<)(.*)$", t)
        if not m:
            continue
        source = m.group(1) or (toks[i + 1] if i + 1 < len(toks) else "")
        if source and _secret_basename(_basename(source)):
            return deny("SECRET-FILE-READ", "redirecting a credential file into a command")
    return None


def _interpreter_rule(base: str, toks: list[str], ctx: _Ctx) -> Decision | None:
    key = _interp(base)
    if key is None:
        return None
    flag = INTERPRETER_CODE_FLAG[key]
    for i, t in enumerate(toks[1:], start=1):
        if t == flag or (key == "node" and t in ("--eval", "-p", "--print")) or \
                (key == "perl" and t == "-E"):
            code = toks[i + 1] if i + 1 < len(toks) else ""
            return _code_rule(code, f"inline {key} code")
    return None


def _curl_request(toks: list[str]) -> tuple[str, bool]:
    """(method, has_body) for curl, reading joined short options (`-XPOST`, `-sSXPOST`,
    `-d'{}'`) as well as separate ones (D-09)."""
    method = ""
    body = False
    i = 1
    while i < len(toks):
        t = toks[i]
        if t in ("-X", "--request", "--method"):
            method = toks[i + 1].upper() if i + 1 < len(toks) else ""
            i += 2
            continue
        if t.startswith(("--request=", "--method=")):
            method = t.split("=", 1)[1].upper()
        elif t == "--json" or t.startswith(("--data", "--form", "--upload-file", "--json=")):
            body = True
            if "=" not in t:
                i += 1
        elif t.startswith("-") and not t.startswith("--") and len(t) > 1:
            letters = t[1:]
            for j, ch in enumerate(letters):
                if ch in ("d", "F", "T"):
                    body = True
                if ch in CURL_VALUE_LETTERS:
                    value = letters[j + 1:]
                    if not value:
                        value = toks[i + 1] if i + 1 < len(toks) else ""
                        i += 1
                    if ch == "X":
                        method = value.upper()
                    break
        i += 1
    return method, body


def _network_rule(base: str, toks: list[str], ctx: _Ctx) -> Decision | None:
    """An outward mutation (POST/PUT/PATCH/DELETE or a request body) to anything that is not
    loopback is outside the engineering contract. Plain GETs are how pins are fetched."""
    if base in FIREWALL_COMMANDS:
        if any(t in FIREWALL_MUTATING for t in toks[1:]):
            return deny("NETWORK-MUTATION", f"{base} changes what the host exposes; networking is "
                        "an owner decision")
        return None
    if base not in ("curl", "wget", "http", "https", "httpie", "xh"):
        return None
    if base == "curl":
        method, body = _curl_request(toks)
    else:
        method = ""
        body = False
        for i, t in enumerate(toks[1:], start=1):
            if t in ("-X", "--request", "--method") and i + 1 < len(toks):
                method = toks[i + 1].upper()
            elif t.startswith(("--request=", "--method=")):
                method = t.split("=", 1)[1].upper()
            elif t in ("-d", "-F", "-T", "--json") or t.startswith(("--data", "--form",
                                                                     "--upload-file", "--post-data",
                                                                     "--post-file", "--body-data")):
                body = True
            elif base in ("http", "https", "httpie", "xh") and t in ("POST", "PUT", "PATCH", "DELETE"):
                method = t
    if method in ("", "GET", "HEAD") and not body:
        return None
    if any(("127.0.0.1" in t or "localhost" in t or "[::1]" in t) for t in toks[1:]):
        return None
    return deny("OUTWARD-MUTATION", f"{base} with a mutating method or request body to a "
                "non-loopback host")


def _listen_rule(base: str, toks: list[str], ctx: _Ctx) -> Decision | None:
    """A listener bound to every interface is public exposure (DEC-020: loopback only)."""
    for t in toks[1:]:
        if re.search(r"(^|[=:])(0\.0\.0\.0|\[::\]|::)$", t):
            return deny("PUBLIC-BIND", "binding a listener to all interfaces; the backend stays on "
                        "127.0.0.1 and the tailnet route is the only exposure")
    return None


if __name__ == "__main__":
    sys.exit(main())
