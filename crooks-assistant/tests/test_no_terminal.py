"""§5.2 — the owner is never sent to Terminal.

WHY THIS TEST EXISTS AND WHY IT IS NOT A GREP OF THE README

Phase 6's whole claim is "turn the Mac on, turn the Samsung on, do nothing else". That claim is
not made by a document; it is made, or broken, by every individual sentence the control layer
can put in front of the owner. One string reading "run `make install` once" undoes it, because
the owner reading that sentence is at that moment in exactly the position Phase 6 exists to
remove him from — standing in front of a control panel that has just told him to go and find a
terminal.

The workstream review found ONE such string. That is the reason this test scans rather than
asserting on the one: a defect found by reading is a defect fixed one at a time, and the next
one is written the following week. Seven were reachable when this was first run.

WHAT IT MEASURES, EXACTLY

Two things, and the split matters:

  1. BEHAVIOURAL. The documents the control layer actually builds — status, actions, contract —
     are built for real, and every string in them is checked. This is the strongest evidence
     available without a Mac, because these are the literal bytes the Control app renders.

  2. STATIC. Every string literal handed to `Stopped(...)` in scripts/update.py, and every
     `stop` reason in scripts/control.py, is extracted from the AST. These cannot be reached
     behaviourally without a git repository in seven different broken states, and a test that
     cannot reach them would report success while they sat there — which is precisely the §26
     failure this phase is meant to avoid. So they are read from the source instead, and this
     comment is here so nobody later mistakes the static half for the behavioural half.

WHAT IS ALLOWED

Naming `crooks-control <something>` is allowed. It is the same command the app's own button
runs, the README documents it as the equivalent, and a sentence that offers BOTH ("press
Update, or `crooks-control apply --yes`") is strictly more useful than one that offers only the
button. What is forbidden is a sentence whose ONLY remedy is a shell.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

# The shapes of "go and open Terminal". Each is a thing an owner cannot do from CROOKS Control.
TERMINAL = re.compile(
    r"""(?xi)
      `?\bmake\s+[a-z-]+          # make up, make install, make venv, make logs
    | `?\bgit\s+(checkout|stash|commit|pull|fetch)\b
    | `?\bpython\s+-m\b
    | `?\blaunchctl\s
    | `?\bpip\s+install\b
    | \bcd\s+~?/                  # "cd ~/crooks-assistant"
    | \bsh\s+\S+\.sh\b
    | \./\S+\.(sh|py)\b
    """
)

# TWO NARROW EXEMPTIONS, AND WHY EACH IS NARROW.
#
# The rule being enforced is not "no shell command may ever appear in a string". It is "no
# sentence may leave a shell as the owner's ONLY remedy". Two shapes of sentence name a command
# without doing that, and both are worth keeping:
#
#   1. A sentence that also offers a control. "Press Update, or `crooks-control apply --yes`"
#      answers the owner with a button and adds a footnote for whoever wants it. Strictly more
#      useful than the button alone.
#
#   2. An EQUIVALENCE NOTE. Every entry in the actions document IS a button; a detail reading
#      "the same as `make restart`" is telling the reader what the button he is looking at
#      corresponds to. It is documentation of a control, not a substitute for one.
#
# The exemptions are deliberately keyed on the language of OFFERING and EQUIVALENCE, never on
# the file or the field — an exemption by location would swallow the next real defect that
# happened to be written in the same place. `test_the_exemptions_do_not_swallow_an_instruction`
# is the guard on that, and it is the most important test in this module.
OFFERS_A_CONTROL = re.compile(r"(?i)\b(button|press|tap|click|CROOKS Control|the app's)\b")
# …except when the sentence is DENYING that a control exists. "There is no Update button for
# this. Run `make install` first." names a button and offers nothing — and the first version of
# this file let it straight through, because the word "button" was acting as a password.
# That escape is what `test_the_exemptions_do_not_swallow_an_instruction` exists to catch, and
# it caught it on the first run.
DENIES_A_CONTROL = re.compile(
    r"(?i)\b(no|not|cannot|can't|isn't|is not|there is no|without)\b(?:\s+\S+){0,3}\s+\b(button|control|app)\b"
)
IS_AN_EQUIVALENCE = re.compile(r"(?i)\b(the same as|equivalent to|which is|i\.e\.)\s*`")
# …but only when the sentence does not ALSO tell him to go and do something.
IS_AN_INSTRUCTION = re.compile(
    r"(?i)\b(run|type|open|first|once|then try|try again|do this|you (?:must|need|should|will have to))\b"
)


def _offences(text: str) -> list[str]:
    """The terminal instructions in one string, unless the string offers a control instead."""
    hits = [m.group(0).strip() for m in TERMINAL.finditer(text)]
    if not hits:
        return []
    if OFFERS_A_CONTROL.search(text) and not DENIES_A_CONTROL.search(text):
        return []
    if IS_AN_EQUIVALENCE.search(text) and not IS_AN_INSTRUCTION.search(text):
        return []
    return hits


def test_the_exemptions_do_not_swallow_an_instruction():
    """The guard on the two exemptions above.

    An exemption is a hole, and a hole nobody tests is a hole that grows. These are the
    sentences that MUST still be caught, each written in the shape the exemption is meant to
    let through, and each one an instruction underneath.
    """
    must_be_caught = [
        # Wears the equivalence costume, is an order.
        "the same as `make install` — run it first",
        "which is `make venv`; run that once and then try again",
        # Names a control and an order the control cannot carry out. The word "button" must not
        # be a password that lets any sentence through.
        "There is no Update button for this. Run `make install` in Terminal first.",
        # The plain ones.
        "Run `make venv` once, then try again.",
        "`git checkout <branch>` first.",
    ]
    escaped = [t for t in must_be_caught if not _offences(t)]
    assert not escaped, "these got through the exemptions:\n" + "\n".join(repr(t) for t in escaped)


def test_the_exemptions_do_let_the_two_good_shapes_through():
    """And the other half: the gate must not force the equivalence notes out of the product.
    A gate that can only be satisfied by deleting useful documentation gets deleted itself."""
    should_pass = [
        "the launchd agents, kicked — the same as `make restart`",
        "An update applies on a click. `crooks-control apply --yes`, or the app's Update button.",
        # A real offer plus a real footnote. The owner has a button; the command is for whoever
        # wants it. This must keep passing, or the gate would be satisfiable only by deleting
        # the footnote, which helps nobody.
        "Press Restart in CROOKS Control, or run `make restart` yourself.",
    ]
    caught = [t for t in should_pass if _offences(t)]
    assert not caught, "these were wrongly caught:\n" + "\n".join(repr(t) for t in caught)


def _strings(value, path: str = "") -> list[tuple[str, str]]:
    """Every string in a decoded document, with the path that reaches it."""
    out: list[tuple[str, str]] = []
    if isinstance(value, str):
        out.append((path, value))
    elif isinstance(value, dict):
        for key, item in value.items():
            out.extend(_strings(item, f"{path}.{key}" if path else str(key)))
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            out.extend(_strings(item, f"{path}[{i}]"))
    return out


# --------------------------------------------------------------------- behavioural

@pytest.fixture(scope="module")
def control():
    import importlib.util

    spec = importlib.util.spec_from_file_location("_control_under_test", SCRIPTS / "control.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("builder", ["actions_document", "contract_document"])
def test_the_documents_the_app_draws_send_nobody_to_terminal(control, builder):
    """The two documents that need no running backend, built for real and read string by string."""
    document = getattr(control, builder)()
    bad = [(where, text, hits) for where, text in _strings(document) if (hits := _offences(text))]
    assert not bad, "\n".join(f"{where}: {hits} in {text!r}" for where, text, hits in bad)


def test_the_status_document_sends_nobody_to_terminal_when_nothing_is_running(control):
    """The RED path specifically: the sentence an owner reads when CROOKS OS is NOT up is the
    single most important sentence in the product, because it is the only one he reads while
    something is wrong — and it was the one that said "`make up`, or `make install`"."""
    rolled = control.roll_up(
        None,  # nothing answered on the loopback port
        tablet_host=None,
        session={"active": False},
        mutation={"ready": False, "why": ""},
        the_port=8765,
    )
    bad = [(where, text, hits) for where, text in _strings(rolled) if (hits := _offences(text))]
    assert not bad, "\n".join(f"{where}: {hits} in {text!r}" for where, text, hits in bad)


# -------------------------------------------------------------------------- static

# The keys whose values a person reads. `note` is on this list because leaving it off is how
# the first version of this file missed four strings: `rollback_decision` puts its whole
# explanation of what a rollback does — and how to come forward again — in `note`, and the gate
# walked straight past it.
OWNER_FACING_KEYS = ("reason", "detail", "why", "headline", "note", "summary", "message", "hint")


def _strings_under(node: ast.AST) -> list[tuple[int, str]]:
    return [(n.lineno, n.value) for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _stop_literals(path: Path) -> list[tuple[int, str]]:
    """Every literal string that becomes text an owner reads.

    THREE AST shapes, and the third one is the reason this comment is long.

      1. `raise Stopped("…")`
      2. a dict LITERAL with an owner-facing key: `{"reason": "…"}`
      3. an assignment INTO one: `out["reason"] = "…"`

    Shape 3 was missing from the first version of this gate, and it mattered: the whole of
    `rollback_decision` builds its answer by assigning into a dict it made earlier, so every
    sentence it can say to the owner was invisible to a scan that only knew shapes 1 and 2. A
    gate that reads half the strings and reports a pass is the §26 failure in the gate itself,
    which is worse than not having one, because it is believed.

    Only constant strings. A message built at runtime out of git's own stderr is not something
    this test can police, and pretending otherwise would be the opposite mistake.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        # 1. raise Stopped("…")
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            name = node.exc.func
            if isinstance(name, ast.Name) and name.id == "Stopped":
                for arg in node.exc.args:
                    found.extend(_strings_under(arg))
        # 2. {"reason": "…"}
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value in OWNER_FACING_KEYS:
                    found.extend(_strings_under(value))
        # 3. out["reason"] = "…"  /  out.update({"reason": "…"}) is shape 2 already
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Subscript)
                        and isinstance(target.slice, ast.Constant)
                        and target.slice.value in OWNER_FACING_KEYS):
                    found.extend(_strings_under(node.value))
    return found


def test_the_scan_sees_all_three_shapes():
    """The guard on the scanner itself.

    Without this, widening `_stop_literals` later — or narrowing it by accident — changes what
    the gate can see with no test noticing. Each shape below is written the way the product
    writes it, and each must be found.
    """
    import tempfile

    source = '''
class Stopped(RuntimeError): pass

def one():
    raise Stopped("shape one: `make venv` first")

def two():
    return {"reason": "shape two: `make logs` shows why"}

def three():
    out = {}
    out["note"] = "shape three: `git checkout main` comes forward again"
    return out
'''
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        probe = Path(handle.name)
    try:
        seen = [text for _, text in _stop_literals(probe)]
        for shape in ("shape one", "shape two", "shape three"):
            assert any(shape in text for text in seen), f"the scanner cannot see {shape}: {seen}"
        # And each must be judged an offence, or seeing it bought nothing.
        assert all(_offences(text) for text in seen if "shape" in text)
    finally:
        probe.unlink()


@pytest.mark.parametrize("name", ["update.py", "control.py", "service.py"])
def test_no_stop_reason_tells_the_owner_to_open_terminal(name):
    """The refusals. Unreachable behaviourally without a repository in seven broken states, so
    they are read out of the source — see this module's docstring on why that is deliberate."""
    path = SCRIPTS / name
    if not path.exists():
        pytest.skip(f"scripts/{name} does not exist in this tree")
    bad = [(line, text, hits) for line, text in _stop_literals(path) if (hits := _offences(text))]
    assert not bad, "\n".join(f"scripts/{name}:{line}: {hits} in {text!r}" for line, text, hits in bad)
