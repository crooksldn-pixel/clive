"""launchctl, as launchd actually behaves — the double every lifecycle test now runs against.

The double this replaces answered 0 to everything. A double that always succeeds cannot fail,
and what it hid is the defect that made Stop-then-Start do nothing at all:

    `launchctl kickstart` on a job launchd does not have LOADED does not start it.
    It exits 3 and says "Could not find service". Only `bootstrap` loads a job, and
    `bootout` unloads it.

Neither verb touches the plist FILE, which sits on disk from the moment it is installed until
somebody deletes it. So "the plist is there" and "launchd has it" are two different facts, and
a layer that reads the first when it means the second is a layer whose Start button does
nothing the second time it is pressed. That is what the old double could not express.

WHAT THIS STILL DOES NOT PROVE, said before anything it does: there is no launchctl on this
machine and no macOS to run one. Nothing here shows that `bootstrap gui/501 …` is accepted by
any real launchd, that `kickstart -k` is the right verb for this macOS, or that a plist
rendered from these templates loads. What it models is the one BEHAVIOUR whose absence made
the product wrong — which verb changes which fact, and what the other verbs say afterwards.
"""

from __future__ import annotations

from pathlib import Path

from scripts.service import Ran

# launchctl's own numbers, used because the layer under test reads them.
#   3   there is no such service in this domain — what kickstart and bootout say about a job
#       that is not loaded. It is the number the old double could never return, which is the
#       whole reason A1 could sit in the product with the suite green.
#   37  EALREADY: bootstrap on a job that is already loaded.
#   127 there is no launchctl at all (not a Mac, or a broken PATH).
NO_SUCH_SERVICE = 3
ALREADY_LOADED = 37
NO_LAUNCHCTL = 127


def printed(*, running: bool, pid: int = 4242, last_exit_code: int = 0) -> str:
    """What `launchctl print gui/501/<label>` prints, trimmed to the three lines this layer
    reads by name. The real output is a hundred lines of tree."""
    if running:
        return f"\tstate = running\n\tpid = {pid}\n\tlast exit code = {last_exit_code}\n"
    return f"\tstate = not running\n\tlast exit code = {last_exit_code}\n"


class LaunchdDouble:
    """One launchd, holding the only state launchd itself holds: which labels are loaded, and
    which of those have a process. `on_kickstart` and `on_bootout` are how a test says what
    else happens on the Mac when a service really starts or really stops — /health beginning
    to answer, the port going quiet — without replacing the double and losing its rules.
    """

    def __init__(self, *, loaded=(), running=(), on_kickstart=None, on_bootout=None,
                 last_exit_code: int = 0, absent: bool = False) -> None:
        self.loaded: set[str] = set(loaded)
        self.running: set[str] = set(running)
        self.on_kickstart = on_kickstart
        self.on_bootout = on_bootout
        self.last_exit_code = last_exit_code
        # No launchctl on this machine at all: every invocation is 127. Not the same state as
        # a launchd that refuses, and the layer above must not report them the same way.
        self.absent = absent
        self.calls: list[list[str]] = []

    # ----------------------------------------------------------------- what was asked

    def verbs(self) -> list[str]:
        return [call[1] for call in self.calls if call and call[0] == "launchctl" and len(call) > 1]

    def ran(self, word: str) -> list[list[str]]:
        return [call for call in self.calls if any(word in part for part in call)]

    # ----------------------------------------------------------------- the verbs

    @staticmethod
    def _label(argv: list[str]) -> str:
        """bootstrap names a plist path; everything else names gui/<uid>/<label>."""
        tail = argv[-1] if argv else ""
        if tail.endswith(".plist"):
            return Path(tail).name[: -len(".plist")]
        return tail.rsplit("/", 1)[-1]

    def __call__(self, argv, *, timeout_s: float = 60.0) -> Ran:
        argv = list(argv)
        self.calls.append(argv)
        if not argv or argv[0] != "launchctl":
            return Ran(tuple(argv), 0, "", "")
        if self.absent:
            return Ran(tuple(argv), NO_LAUNCHCTL, "", "launchctl: not found")
        verb = argv[1] if len(argv) > 1 else ""
        handler = getattr(self, f"_{verb.replace('-', '_')}", None)
        if handler is None:
            return Ran(tuple(argv), 0, "", "")
        return handler(argv, self._label(argv))

    def _print(self, argv: list[str], label: str) -> Ran:
        if label not in self.loaded:
            # Non-zero, which is the only thing the layer above reads. The exact number real
            # launchctl uses for this is not known from a machine with no launchctl, so one is
            # not invented here — the WORD it prints is what the layer quotes back.
            return Ran(tuple(argv), 1, "", f'Could not find service "{label}" in domain for gui')
        return Ran(tuple(argv), 0,
                   printed(running=label in self.running, last_exit_code=self.last_exit_code))

    def _bootstrap(self, argv: list[str], label: str) -> Ran:
        if label in self.loaded:
            return Ran(tuple(argv), ALREADY_LOADED, "", f"Bootstrap failed: {ALREADY_LOADED}: Service is already loaded")
        self.loaded.add(label)
        return Ran(tuple(argv), 0, "", "")

    def _load(self, argv: list[str], label: str) -> Ran:
        # The legacy verb service.Launchd falls back to on an older macOS. It loads a job that
        # is not loaded and refuses one that is — it is NOT a second chance at the same job,
        # and writing it as one would put an always-succeeds pocket back into this double.
        if label in self.loaded:
            return Ran(tuple(argv), ALREADY_LOADED, "", f"Load failed: {ALREADY_LOADED}: Operation already in progress")
        self.loaded.add(label)
        return Ran(tuple(argv), 0, "", "")

    def _bootout(self, argv: list[str], label: str) -> Ran:
        if label not in self.loaded:
            return Ran(tuple(argv), NO_SUCH_SERVICE, "", f"Boot-out failed: {NO_SUCH_SERVICE}: No such process")
        self.loaded.discard(label)
        self.running.discard(label)
        if self.on_bootout is not None:
            self.on_bootout(label)
        return Ran(tuple(argv), 0, "", "")

    def _kickstart(self, argv: list[str], label: str) -> Ran:
        # THE rule. A kickstart of a job launchd does not have is not a start; it is an error,
        # and a Start button built on the opposite belief leaves the appliance off.
        if label not in self.loaded:
            return Ran(tuple(argv), NO_SUCH_SERVICE, "", f'Could not find service "{label}" in domain for gui')
        self.running.add(label)
        if self.on_kickstart is not None:
            self.on_kickstart(label)
        return Ran(tuple(argv), 0, "", "")
