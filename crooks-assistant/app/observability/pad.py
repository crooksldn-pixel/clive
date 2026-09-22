"""CROOKS PAD: whether the tablet is actually ALIVE, and what the appliance did.

Two things live here, and they are separate on purpose.

The heartbeat (§16)
-------------------
Before this file the only answer to "is the pad there?" was the control layer asking Tailscale
whether a route to the tablet exists. A route is not a tablet. `tailscale serve` will happily
report a healthy route to a Mac whose tablet is face down in a drawer, switched off, or sitting
on the charger with the app crashed — and the Control app would have said CROOKS PAD
connected for every one of those. That is exactly the §26 failure the brief names: "tablet
connected vs backend merely reachable".

So the pad says so itself. The appliance POSTs `/pad/heartbeat` every `HEARTBEAT_INTERVAL_S`
carrying its app version, its device model, its OS version and its own clock. `last_seen` is the
SERVER's clock at the moment that post arrived — never the pad's, which is a number the pad
chose — and `connected` is derived from `now - last_seen` against `STALE_AFTER_S`. Nothing else
sets it. A network that is up, a `tailscale serve` route that resolves, a backend that answers
/ping: none of them can make this say connected, because none of them is a pad checking in. The
test that matters is `test_a_reachable_backend_with_no_pad_reports_disconnected`.

The window is three missed beats plus slack rather than one. A tablet that has just woken its
radio, or that is mid-Wi-Fi-roam between the shop's two access points, routinely misses a beat;
calling that a disconnection would train the owner to ignore the word, which is worse than not
having it. Three in a row is a pad that is not answering.

The appliance telemetry (§18)
-----------------------------
The native layer emits `pad_*` events — started, foregrounded, backgrounded, the WebView loaded
or failed, the network changed, the backend became reachable or stopped being, the microphone
permission, the renderer died, admin was entered or left, the version, the battery, the stage
the kiosk lock reached and a navigation the shell refused. They go onto the SAME
test-session timeline as everything else (`app/observability/timeline.py`), through the same
`emit`, which means through the same scrub: withheld keys, credential shapes and contact-detail
shapes are all already handled there and there is no second redactor here. A device model and an
app version are not personal data; a device NAME would be, so this file never accepts one.

The reason this is not just "forward whatever arrives" is that appliance events are exactly the
ones that arrive in floods. A Wi-Fi access point flapping emits `pad_network_changed` a hundred
times a minute; a WebView in a reload loop emits `pad_webview_error` as fast as it can fail. A
timeline full of those is a timeline nobody reads, and the analyser's counts stop meaning
anything. So an event is written down only when it is a TRANSITION — when it says something
different from the last thing written on its channel — and repeats are folded away and counted,
so that the next accepted event on that channel carries `repeats: N` and nothing is silently
lost. On top of that there is a flat ceiling per minute, because a crash loop can produce a
genuinely different signature every time and a ceiling is the only thing that stops that.

None of this is on a turn's path. A heartbeat is a handful of dict assignments; an event is a
dict lookup and, at most, one `timeline.emit`, which is itself a queue put.
"""

from __future__ import annotations

import re
import time
from collections import deque
from typing import Any

from app.observability import timeline as timeline_module

# How often the appliance is expected to check in, and how long silence is tolerated before
# `connected` becomes false. Three missed beats plus five seconds of slack: see the module
# docstring for why one missed beat is not a disconnection.
HEARTBEAT_INTERVAL_S = 30.0
STALE_AFTER_S = 95.0

# The identity fields a heartbeat may carry, and nothing else. A model and a version describe
# the appliance; a device NAME describes its owner ("George's Tab"), so there is no field for one
# and an appliance cannot invent one.
IDENTITY_FIELDS = ("app_version", "device_model", "os_version", "boot_id")
MAX_IDENTITY_CHARS = 64

# What the pad says is on its screen. §26 names this trap by name — "app launched vs CROOKS
# loaded" — and a heartbeat cannot answer it on its own, because the heartbeat comes from the
# NATIVE shell and the native shell is perfectly capable of being alive around a WebView that
# never loaded, showed Chrome's error page, or was killed for memory. An appliance reporting
# `connected` while the owner is looking at a white rectangle is exactly the fake green this
# whole layer exists to prevent. So the pad may say, and if it does the answer says so too.
# It deliberately does NOT feed `connected`: liveness and what-is-on-screen are two facts, and
# collapsing them would lose the ability to tell "the tablet is off" from "the tablet is on and
# CROOKS is not".
WEBVIEW_STATES = frozenset({"loaded", "loading", "error", "crashed"})
# What survives into a stored identity string. Everything the real values need — "SM-T290",
# "0.3.1", "Android 11 (API 30)" — and nothing that could carry markup or a newline into a
# report that gets pasted somewhere. Square brackets are in the set because the scrub runs
# BEFORE this filter now (see `_identity`), and the markers it leaves behind — "[email]",
# "[secret]" — are the entire point of having run it: a filter that ate them would turn a
# redaction back into a plausible-looking value. They are not new on this surface either;
# "[secret]" is what `app_version` has said since the scrub was first wired in here.
_IDENTITY_SAFE = re.compile(r"[^A-Za-z0-9 ._\-+()/:\[\]]")

# The appliance's vocabulary. Each kind names the CHANNEL it speaks on — a set of mutually
# exclusive states, of which only the current one is interesting — and the fields that make one
# report on that channel different from another. An unknown kind is refused rather than
# forwarded: the "unknown things fail closed" reasoning applies to observability too, and letting
# an unrecognised kind through is how the analyser ends up printing "event kinds this report does
# not read" about our own appliance.
PAD_KINDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "pad_app_started": ("boot", ("boot_id", "app_version")),
    "pad_app_foreground": ("lifecycle", ()),
    "pad_app_background": ("lifecycle", ()),
    "pad_webview_loaded": ("webview", ("url",)),
    "pad_webview_error": ("webview", ("code", "url")),
    "pad_network_changed": ("network", ("to",)),
    "pad_backend_reachable": ("backend", ()),
    "pad_backend_unreachable": ("backend", ("code",)),
    "pad_mic_permission": ("mic", ("state",)),
    "pad_renderer_crash": ("renderer", ("reason",)),
    "pad_admin_entered": ("admin", ()),
    "pad_admin_exited": ("admin", ()),
    "pad_version": ("version", ("version",)),
    # Three appliance facts admitted on top of the original thirteen, because they are real and
    # nothing else in this system can see them. A tablet that has been off its charger since
    # lunchtime, a kiosk lock that did not actually take (so the next person to pick the pad up
    # can leave CROOKS entirely), and a navigation the shell refused — a link out of the app
    # that a finger found. Each is a channel of its own, and each signs on the fields that make
    # one report on it different from the last: 84% charging and 19% on battery are two facts,
    # not one repeated.
    "pad_battery": ("battery", ("percent", "charging")),
    "pad_kiosk_stage": ("kiosk", ("stage",)),
    "pad_navigation_blocked": ("navigation", ("host",)),
}
# Emitted by this file rather than by the appliance: the moments the Mac's view of the pad
# changed. A routine beat writes nothing at all.
HEARTBEAT_KIND = "pad_heartbeat"
# Every kind the timeline may carry from the appliance layer. Read by the analyser
# (`app/observability/report.py`) so these are filed rather than counted as unread.
APPLIANCE_KINDS = frozenset(PAD_KINDS) | {HEARTBEAT_KIND}

# What a pad event may carry. Bounded here and scrubbed by `timeline.emit`; the two are not
# alternatives — this decides what is even a field, that decides what a field may say.
ALLOWED_EVENT_FIELDS = frozenset({
    "at", "state", "to", "from", "code", "reason", "message", "detail", "version",
    "app_version", "ms", "ok", "reachable", "url", "phase", "count", "granted",
    "boot_id", "network", "attempt", "http_status",
    # What the three admitted kinds sign on. A signature field that is not an allowed field is
    # not a signature at all: it is dropped before the signature is built, every report on that
    # channel then signs as the empty string, and the low battery is folded into the full one as
    # a repeat. The table and this set are only correct together.
    "percent", "charging", "stage", "host",
})
MAX_EVENT_STRING = 400
MAX_EVENTS_PER_POST = 50
# The ceiling. Sixty accepted events a minute is one a second of genuinely new information, which
# no appliance running properly will ever approach; a crash loop will pass it in under a second.
# Beyond it events are dropped and counted, and the count is on /health, so a pad that is
# drowning the timeline says so instead of quietly filling it.
MAX_EVENTS_PER_MINUTE = 60
# A state that has not changed is written down again this often, so that a three-hour session
# still shows "foregrounded" somewhere in the middle of it rather than once at the top.
RESTATE_AFTER_S = 900.0


def _identity(value: Any) -> str:
    """One identity string, safe to store and to put on /health.

    Scrubbed through `timeline.scrub` — the same seam every written event passes — rather than
    through a rule of its own, because /health is read by the Control app, pasted into reports
    and handed to engineers exactly as a timeline is.

    The scrub goes FIRST, and that order is the safety rather than a detail of it. The scrub
    finds personal data by SHAPE, and a shape needs its punctuation: filter an e-mail's '@' away
    before the scrub looks and "george@crooks.example" arrives as "georgecrooks.example", which
    matches no pattern, is replaced by nothing, and reaches /health as the owner's login spelled
    out in full — while every assertion of the form "there is no '@' in it" goes on passing,
    because the filter made an '@' impossible either way. So: scrub the original, then filter
    the characters, then cap the length last of all, so that nothing is cut into or out of a
    shape before the scrub has had sight of it.
    """
    raw = str(value or "")
    if not raw.strip():
        return ""
    return _IDENTITY_SAFE.sub("", str(timeline_module.scrub(raw))).strip()[:MAX_IDENTITY_CHARS]


def _ago(seconds: float | None) -> str:
    if seconds is None:
        return "never"
    if seconds < 5:
        return "now"
    if seconds < 90:
        return f"{int(seconds)}s ago"
    if seconds < 5400:
        return f"{int(seconds / 60)}m ago"
    return f"{seconds / 3600:.1f}h ago"


class PadRegistry:
    """What this Mac knows about the pad. One per process; `current()` holds it."""

    def __init__(self, *, clock=time.time) -> None:
        self.clock = clock
        self.last_seen: float | None = None
        self.first_seen: float | None = None
        self.app_version = ""
        self.device_model = ""
        self.os_version = ""
        self.boot_id = ""
        # "" until the pad says. Never guessed: a backend that assumed "loaded" because a
        # heartbeat arrived would be inventing the one fact it cannot observe.
        self.webview = ""
        self.heartbeats = 0
        # The pad's own clock minus ours at the last beat. An appliance whose clock is hours out
        # is a real fault (certificates, scheduling, the timestamps in its own reports) and this
        # is the only place that would ever notice.
        self.clock_skew_s: float | None = None
        # Per-channel: the last signature actually written, and when. Plus how many identical
        # reports have been folded away since.
        self._last: dict[str, tuple[str, float]] = {}
        self._repeats: dict[str, int] = {}
        self._accepted_at: deque[float] = deque()
        self.events_accepted = 0
        self.events_collapsed = 0
        self.events_rejected = 0
        self.events_rate_limited = 0

    # ------------------------------------------------------------------- heartbeat

    def heartbeat(self, **fields: Any) -> dict[str, Any]:
        """One check-in. Returns the status as it stands after it.

        The pad's own `at` is recorded as a SKEW and never as `last_seen`: a clock is a thing the
        pad chose, and liveness must not be. What proves the pad alive is that this call happened
        at all.
        """
        now = float(self.clock())
        was = self.state(now=now)
        gap = None if self.last_seen is None else now - self.last_seen
        identity = {name: _identity(fields.get(name)) for name in IDENTITY_FIELDS}
        changed = [name for name in IDENTITY_FIELDS if identity[name] and identity[name] != getattr(self, name)]
        # A pad that has REBOOTED — which is not the same as one whose boot_id we are learning
        # for the first time (an appliance upgraded mid-shift starts carrying one on a beat that
        # is otherwise the beat it was already sending) and not the same as one that has stopped
        # carrying it. Neither of those is a new life and neither may throw anything away.
        rebooted = bool(self.boot_id and identity["boot_id"] and identity["boot_id"] != self.boot_id)
        for name in IDENTITY_FIELDS:
            if identity[name]:
                setattr(self, name, identity[name])
        if rebooted:
            # A new boot is a new screen. What the dead boot last said about its WebView
            # describes a process that no longer exists, and carried over it answers for a
            # screen nobody has seen: the pad that crashed its renderer and was restarted goes
            # on reading "NOT SHOWING CROOKS (webview crashed)" while it sits there working, and
            # — the same bug the dangerous way up — the pad that had loaded goes on reading
            # `showing_crooks: true` through a new boot whose WebView never came back. So it
            # returns to "has not said", which is the only true thing about it until this boot
            # says otherwise. Cleared BEFORE this beat's own `webview` is read, so a beat that
            # carries a new boot_id and a state together still sets the state.
            self.webview = ""
            # And the collapser's memory goes with it, for the same reason one layer down. It
            # folds any report matching the last one written on its channel within
            # RESTATE_AFTER_S — a quarter of an hour — so an appliance that crashed and came
            # back inside that window would have the new life's "foregrounded" and "loaded"
            # folded into the dead life's and never written at all, and section 17 of the report
            # would then say the rebooted app did neither. The folded COUNTS are deliberately
            # left alone: `_repeats` still rides onto the next accepted event on the channel, so
            # nothing that was collapsed goes unaccounted for.
            self._last.clear()
        webview = str(fields.get("webview") or "").strip().lower()
        if webview in WEBVIEW_STATES:
            self.webview = webview
        at = fields.get("at")
        self.clock_skew_s = round(float(at) - now, 1) if isinstance(at, (int, float)) and not isinstance(at, bool) and at else None
        if self.first_seen is None:
            self.first_seen = now
        self.last_seen = now
        self.heartbeats += 1

        # Meaningful transitions only. A beat every thirty seconds for eight hours is 960 beats
        # and nothing worth reading; what is worth reading is the pad appearing, the pad coming
        # back after an outage, and the pad changing what it says it is.
        if was == "never_seen":
            self._emit_heartbeat("first_seen")
        elif was == "stale":
            self._emit_heartbeat("returned", gap_s=round(gap, 1) if gap is not None else None)
        elif changed:
            self._emit_heartbeat("identity_changed", changed=",".join(sorted(changed)))
        return self.status(now=now)

    def _emit_heartbeat(self, state: str, **fields: Any) -> None:
        timeline_module.emit(
            HEARTBEAT_KIND, source="pad", state=state,
            app_version=self.app_version or None, device_model=self.device_model or None,
            os_version=self.os_version or None,
            **{key: value for key, value in fields.items() if value is not None},
        )

    # ----------------------------------------------------------------------- state

    def state(self, *, now: float | None = None) -> str:
        """`never_seen`, `connected` or `stale`. Nothing but a real check-in moves it."""
        if self.last_seen is None:
            return "never_seen"
        at = float(now if now is not None else self.clock())
        return "connected" if at - self.last_seen < STALE_AFTER_S else "stale"

    def status(self, *, now: float | None = None) -> dict[str, Any]:
        at = float(now if now is not None else self.clock())
        state = self.state(now=at)
        since = None if self.last_seen is None else round(at - self.last_seen, 1)
        return {
            # The one field a caller should branch on, and it is false unless a pad posted a
            # heartbeat less than STALE_AFTER_S ago. Reachability is not an input to it.
            "connected": state == "connected",
            "state": state,
            "detail": self.summary(now=at),
            "last_seen": None if self.last_seen is None else round(self.last_seen, 3),
            "last_seen_s": since,
            "last_seen_text": _ago(since),
            "app_version": self.app_version,
            "device_model": self.device_model,
            "os_version": self.os_version,
            # What the pad last said is on its screen, and the plain answer derived from it.
            # `None` means the pad has never said — which is not "yes", and must not be read as
            # one. It is also None once the pad has gone quiet: the last thing it said about its
            # screen is stale in exactly the way everything else it said is, and a row reading
            # "disconnected, showing CROOKS: yes" is the fake green with two coats of paint.
            "webview": self.webview,
            "showing_crooks": (self.webview == "loaded") if (self.webview and state == "connected") else None,
            "heartbeats": self.heartbeats,
            "clock_skew_s": self.clock_skew_s,
            "interval_s": HEARTBEAT_INTERVAL_S,
            "stale_after_s": STALE_AFTER_S,
            "events": {
                "accepted": self.events_accepted,
                "collapsed": self.events_collapsed,
                "rejected": self.events_rejected,
                "rate_limited": self.events_rate_limited,
            },
        }

    def summary(self, *, now: float | None = None) -> str:
        """The sentence the Control app puts on a row.

        Written on the backend, beside the rule that decides it, rather than in the app that
        displays it: a Control app and a backend of different ages then cannot disagree about
        what the word "connected" means, which is the sort of disagreement nobody notices until
        the one evening it matters.
        """
        state = self.state(now=now)
        if state == "never_seen":
            return "CROOKS PAD has never checked in with this Mac"
        since = None if self.last_seen is None else float(now if now is not None else self.clock()) - self.last_seen
        who = f"app {self.app_version or '?'}, device {self.device_model or '?'}"
        if state != "connected":
            return f"CROOKS PAD DISCONNECTED, last seen {_ago(since)}, {who}"
        if self.webview and self.webview != "loaded":
            # The appliance is alive and CROOKS is not on it. Said out loud, because a row that
            # read "connected" here would be the fake green of §26: the owner is looking at a
            # blank rectangle and the Mac is reporting everything fine.
            return f"CROOKS PAD connected but NOT SHOWING CROOKS (webview {self.webview}), last seen {_ago(since)}, {who}"
        return f"CROOKS PAD connected, last seen {_ago(since)}, {who}"

    # ---------------------------------------------------------------------- events

    def record(self, events: Any) -> dict[str, int]:
        """A batch from the appliance. Returns what happened to it, for the route's header and
        for the tests."""
        result = {"accepted": 0, "collapsed": 0, "rejected": 0, "rate_limited": 0}
        if not isinstance(events, list):
            return result
        for item in events[:MAX_EVENTS_PER_POST]:
            result[self._record_one(item)] += 1
        # Anything past the batch ceiling is refused, and SAID to be refused. Slicing the list
        # and returning a number that did not add up would be the quiet kind of dropping — the
        # appliance would think it had reported something it had not, and /health would show a
        # count that nothing accounted for.
        over = len(events) - MAX_EVENTS_PER_POST
        if over > 0:
            self.events_rate_limited += over
            result["rate_limited"] += over
        return result

    def _record_one(self, item: Any) -> str:
        if not isinstance(item, dict):
            self.events_rejected += 1
            return "rejected"
        kind = str(item.get("kind") or "")
        entry = PAD_KINDS.get(kind)
        if entry is None:
            # Not our vocabulary. Refused at the door so the analyser never has to decide what to
            # do with it, and counted so a pad emitting a kind this backend does not know about
            # is visible on /health rather than silent.
            self.events_rejected += 1
            return "rejected"
        channel, signature_fields = entry
        # The same fact arriving by the other door. An appliance that emits the events need not
        # also carry `webview` on every beat, and vice versa — one field, set from whichever
        # said so last. Done before the collapse test on purpose: a repeat carries the same
        # value, so nothing moves, and a state this registry has forgotten (a restarted backend)
        # is restored by the first event whether or not it is written down.
        if kind in ("pad_webview_loaded", "pad_webview_error", "pad_renderer_crash"):
            self.webview = {"pad_webview_loaded": "loaded", "pad_webview_error": "error"}.get(kind, "crashed")
        fields = {key: _bounded(value) for key, value in item.items() if key in ALLOWED_EVENT_FIELDS}
        signature = "|".join([kind] + [str(fields.get(name, "")) for name in signature_fields])
        now = float(self.clock())
        last = self._last.get(channel)
        if last is not None and last[0] == signature and now - last[1] < RESTATE_AFTER_S:
            self._repeats[channel] = self._repeats.get(channel, 0) + 1
            self.events_collapsed += 1
            return "collapsed"
        # The ceiling is tested AFTER the transition test, so what it catches is a flood of
        # genuinely-different signatures; a flood of identical ones has already been folded.
        while self._accepted_at and now - self._accepted_at[0] > 60.0:
            self._accepted_at.popleft()
        if len(self._accepted_at) >= MAX_EVENTS_PER_MINUTE:
            self.events_rate_limited += 1
            return "rate_limited"
        repeats = self._repeats.pop(channel, 0)
        self._last[channel] = (signature, now)
        self._accepted_at.append(now)
        self.events_accepted += 1
        # `repeats` says how many identical reports of the state this event REPLACES were folded
        # away and never written. Absent when there were none, so an ordinary transition reads as
        # an ordinary transition.
        if repeats:
            fields["repeats"] = repeats
        fields.pop("at", None)   # the pad's clock; the timeline stamps with the Mac's
        timeline_module.emit(kind, source="pad", **fields)
        return "accepted"


def _bounded(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_EVENT_STRING]
    return str(value)[:MAX_EVENT_STRING]


_current = PadRegistry()


def install(registry: PadRegistry) -> PadRegistry:
    global _current
    _current = registry
    return registry


def current() -> PadRegistry:
    return _current


def reset() -> PadRegistry:
    """A pad nobody has ever heard from. For tests, and for a process handed a new tablet."""
    return install(PadRegistry())
