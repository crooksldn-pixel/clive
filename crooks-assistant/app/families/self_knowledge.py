"""A question about the screen is answered by the Mac, not guessed at by the model (§15).

    "What does the split button do?"
    "I don't know what that button is — not something I control, so best to check with
     whoever built the tablet screen."

The model had nothing to answer from, so it disclaimed the product's own primary control. The
answer exists — `app/observability/ui_semantics.py` is a bounded manifest of what each control
does, derived from the command registry that implements them — and this family is what reaches
it. One read family, no tools, no model, no reads at all: the answer is already on the Mac.

Two bounds make this safe to route so confidently.

* The signal is the manifest itself. `asks_about_the_screen` is true only when the manifest
  has a matching entry for the sentence, which needs both a frame that reads as a question
  about the interface AND an entry whose own pattern matches. "Go back" is not a question and
  still navigates; "has the order come back yet" is about the shop and never reaches here.
* It explains, and never acts. "How do I go back?" is answered with where Back is and what it
  does — it does not go back. A sentence that means the move ("go back", "back") carries no
  question frame, so it keeps `navigation_back` as it always did.

The confidence is deliberately above `navigation_back`'s: the one sentence where the two
families overlap is "how do I go back", and that is a question about a control. Anything
softer put it inside the router's margin and sent a question about the screen to the model,
which is the defect this family exists to close.
"""

from __future__ import annotations

import re

from app.capabilities import screen as screen_mod
from app.fastpath.intent import Family, extend, signal
from app.fastpath.models import Ctx, FastAnswer
from app.fastpath.recipes import CACHE_NONE, Recipe, register
from app.observability import feedback, ui_semantics
from app.reads.scheduler import ReadPlan, ReadResult
from app.surfaces import Freshness, Surface

# ------------------------------------------------------------------ §23's own questions
#
# Seven questions the brief names, and two more the coordinator added from the timeline. Held
# here as the list they are, because every one of them has to be answered from first-party
# semantics rather than disclaimed:
#
#   "What does Split do?"        the manifest's `split`      (Phase 4)
#   "How do I go back?"          the manifest's `back`       (Phase 4)
#   "How do I type this?"        the manifest's `composer`   (Phase 4)
#   "What happens if I merge?"   the manifest's `merge`      (Phase 4)
#   "What does Next mean?"       the manifest's `next`       — the pattern wanted "do" after
#                                                             the control's name, so "mean"
#                                                             matched nothing
#   "What is this screen?"       THIS SCREEN, live           — new
#   "Why is this here?"          THIS SCREEN, live           — new
#   "What is on this screen?"    THIS SCREEN, live           — new (D-11)
#   "What is this?" / "what is it doing?" with an empty deck  — new (D-11)
#
# The last four cannot come from a fixed table: the answer is what is on the glass at the
# moment he asks. `app/capabilities/screen.py` derives that from the session, and the entry
# below exists so that the manifest COVERS the question — `check()`, the report and
# `/health` all see it — while the words come from the live state.
THIS_SCREEN = "this_screen"

# The bare form, which is what the owner actually said twice with the deck empty: "What is it?
# What… why is there bullshit on the screen right now?" and "What is, what is it doing?". It
# names no control and no record, so it is only a question about the screen when there is no
# record open for it to be about — with an order on screen, "what is it doing" is about the
# order, and the model answers that.
_BARE_SCREEN = re.compile(r"^what(?:'?s| is| was| are)?\s+(?:this|it|that|these)"
                          r"(?:\s+(?:doing|showing|for|here|then|about|mean|means))?\s*\??$", re.I)


def _asks_about_this_screen(sig) -> bool:
    """Whether this sentence is asking what is on the glass RIGHT NOW.

    Two shapes. The explicit one goes through the manifest's `this_screen` entry, so the
    question is in the table like every other. The bare one — "what is this", "what is it
    doing" — is only this question when the half holds no record.
    """
    said = " ".join(sig.words)
    found = ui_semantics.lookup(said)
    if found is not None and found.entry.key == THIS_SCREEN:
        return True
    return bool(_BARE_SCREEN.match(str(getattr(sig, "raw", "") or said).strip())) and not sig.has_entity


def _asks_about_the_screen(sig) -> bool:
    """Whether the manifest can answer this sentence. The predicate IS the lookup, so the
    family cannot route a question the manifest then fails to answer.

    `this_screen` is excluded: it is in the manifest so the question is covered and checked,
    but its answer is the LIVE screen, which a fixed sentence cannot give. `screen_state`
    below answers it, and two families on one sentence would route nothing at all.
    """
    found = ui_semantics.lookup(" ".join(sig.words))
    return found is not None and found.entry.key != THIS_SCREEN


def _reports_a_defect(sig) -> bool:
    """Whether the sentence is a bug report rather than a question.

    "Record that the next button does nothing" names a control and is not asking what it is
    for. Both families would otherwise see it, land within the router's margin and send it to
    the model — which is where both of the September sentences went.
    """
    return feedback.recognise(" ".join(sig.words)) is not None


_SAYS_UI = signal("asks_about_the_screen", _asks_about_the_screen)
_SAYS_THIS_SCREEN = signal("asks_about_this_screen", _asks_about_this_screen)
_REPORTS_DEFECT = signal("reports_a_defect", _reports_a_defect)

# The manifest entry for the question, registered from here because the ANSWER is live. It
# carries no `what` of its own worth reading aloud — `screen_state` below composes the words
# from `app/capabilities/screen.py` — but it is in the table, so `check()` covers it, the
# report can see it, and the settings sheet lists the question as answerable.
ui_semantics.extend([
    ui_semantics.Entry(
        key=THIS_SCREEN, control="This screen", group="screen",
        what="What is on the glass right now: the cards on the deck, and the furniture that is "
             "there whether or not any card is — the orb, the dock, a chip per half while the "
             "conversation is divided, and Back and Home once this half has a trail",
        where="Asked at the moment you ask it, from what CLIVE has actually put on the "
              "screen. An empty deck is not an empty screen",
        says=("what is on this screen", "why is this here"),
        also=("dock", "split", "back"),
        asks=ui_semantics._asks(
            r"\bwhat(?:'?s| is| are)?\b.{0,12}\b(?:on )?(?:this|the) screen\b",
            r"\bwhat (?:screen|am i (?:on|looking at))\b",
            r"\bwhat(?:'?s| is)? (?:this|that) (?:screen|page|view|showing)\b",
            r"\bwhy (?:is|are) (?:this|that|these|those|it|there)\b.{0,24}\b(?:here|on (?:the )?screen|showing|up)\b",
            r"\bwhat am i looking at\b",
            r"\bwhat(?:'?s| is)? (?:on|up on) (?:the|my) (?:screen|glass|display)\b",
        ),
    ),
])


def _plan(ctx: Ctx) -> ReadPlan | None:       # noqa: ARG001 — nothing is read
    return None


def _surface(answer: ui_semantics.Answer) -> Surface:
    """The manifest as a card, in the vocabulary the tablet already draws.

    The `capability` renderer, because that is what this is: what the product can do, said
    about its own controls rather than about the shop. A new card type would be the defect
    D-15 names — a shape one side can emit and the other cannot draw.
    """
    groups = ui_semantics.groups()
    asked = answer.entry.group
    # The group the question was about first, so the answer is the first thing on screen.
    groups.sort(key=lambda g: (g["area"] != asked,))
    return Surface(
        surface_type="capability", ui_type="capability",
        title="The controls",
        subtitle=answer.entry.control,
        data={
            "title": "The controls",
            "build": "", "fingerprint": "", "writes_enabled": False,
            "counts": {"reads": sum(len(g["items"]) for g in groups), "changes": 0, "bulk": 0},
            "groups": groups,
            "examples": ["What does Split do?", "How do I go back?", "What does Applying mean?"],
            "note": "",
        },
        freshness=Freshness(source="mac", complete=True),
        spoken_summary=answer.words,
    )


def _render(ctx: Ctx, result: ReadResult) -> FastAnswer:      # noqa: ARG001 — nothing was read
    answer = ui_semantics.lookup(ctx.text)
    if answer is None:
        # The router matched on the tokenised words and the manifest is being asked with the
        # sentence as it was said. If those ever disagree, the model takes the turn rather
        # than this family inventing something.
        return FastAnswer(answer="", defer="the manifest has no entry for that control")
    return FastAnswer(
        answer=ui_semantics.spoken(answer),
        surfaces=[_surface(answer)], drawn=[],
        trace={"source": "ui_semantics", "entry": answer.entry.key,
               "command": answer.entry.command or None},
    )


register(Recipe(
    recipe_id="ui_semantics", intent_family="ui_semantics", read_primitives=(),
    ui="capability", cache_policy=CACHE_NONE, min_confidence=0.72, target_ms=40,
    plan=_plan, render=_render,
))


# -------------------------------------------------------------- what is on the glass (D-11)


def _screen_surface(here: screen_mod.Screen) -> Surface:
    """This screen, as a card. The `capability` renderer again, for the reason `_surface`
    gives: what the product is doing, said about itself."""
    groups = [{
        "area": "screen", "label": "On the deck" if here.cards else "The deck is empty",
        "count": len(here.cards), "truncated": False,
        "items": [{"name": name, "what": "", "kind": "read", "state": "ready",
                   "area": "screen", "operation": "", "risk": "", "reversible": True}
                  for name in screen_mod._readable(here.cards)] or
                 [{"name": "no cards", "what": "Nothing has been drawn on this half yet.",
                   "kind": "read", "state": "ready", "area": "screen", "operation": "",
                   "risk": "", "reversible": True}],
    }, {
        "area": "chrome", "label": "On the glass whatever the deck holds",
        "count": len(here.furniture), "truncated": False,
        "items": [{"name": c.name, "what": f"{c.what}. {c.does.capitalize()}." if c.does else f"{c.what}.",
                   "kind": "read", "state": "ready", "area": "chrome", "operation": "",
                   "risk": "", "reversible": True}
                  for c in here.furniture],
    }]
    return Surface(
        surface_type="capability", ui_type="capability",
        title="This screen", subtitle=here.headline or ("divided" if here.divided else here.mode),
        data={
            "title": "This screen",
            "build": "", "fingerprint": "", "writes_enabled": False,
            "counts": {"reads": len(here.cards) + len(here.furniture), "changes": 0, "bulk": 0},
            "groups": groups,
            "examples": ["What is on this screen?", "Why is this here?", "What does Split do?"],
            "note": "",
        },
        freshness=Freshness(source="mac", complete=True),
        spoken_summary=screen_mod.words(here),
    )


def _screen_render(ctx: Ctx, result: ReadResult) -> FastAnswer:     # noqa: ARG001 — nothing was read
    """What is on the glass, chrome included.

    The answer the live session did not have. Its two attempts — "no card's up on my end" and
    "nothing pending on a card" — were about the assistant's own outbox, and the owner was
    looking at an orb, a dock and two half chips he could not press. `screen.words` names what
    IS there and what he can do next; nothing here can say the screen is empty, because the
    orb and the dock are always on it.
    """
    here = screen_mod.state(ctx.session, ctx.branch)
    said = screen_mod.words(here)
    if screen_mod.claims_an_empty_screen(said):        # pragma: no cover — a guard on ourselves
        return FastAnswer(answer="", defer="the screen model produced a claim it cannot support")
    return FastAnswer(answer=said, surfaces=[_screen_surface(here)], drawn=[],
                      trace={"source": "screen", **here.as_dict()})


register(Recipe(
    recipe_id="screen_state", intent_family="screen_state", read_primitives=(),
    ui="capability", cache_policy=CACHE_NONE, min_confidence=0.72, target_ms=40,
    plan=_plan, render=_screen_render,
))

extend([
    # Above `navigation_back` (0.85) on purpose: "how do I go back" is the one sentence both
    # families see, and it is a question about a control. Blocked by everything that makes a
    # sentence about the shop instead, so a question with an order number or a period in it
    # never reaches the manifest.
    # Not blocked by `waiting`: the router counts "back" among the words of someone waiting to
    # hear back, so blocking it would have ruled out every question about the Back button.
    # The manifest's own frame is what keeps "who is waiting to hear back" out of here — it
    # is not a question about a control, so `asks_about_the_screen` is false for it.
    # `serves_mutation_words`: "what does the refund button do" carries a mutation verb and
    # is a question about a control. This family reads nothing and names no tool, and the
    # manifest lookup is the gate — "refund them the postage" has no question frame, so it
    # never reaches here.
    Family("ui_semantics", needs=(_SAYS_UI,), boosts=("question",),
           blocks=(_REPORTS_DEFECT, "order_number", "period", "ranking", "known_name",
                   "possessive_name", "stock", "running_out", "delayed",
                   "address", "status", "bought"),
           base=0.93, floor=0.72, max_words=12, serves_mutation_words=True),
    # D-11. Above `ui_semantics` (0.93), because the two overlap on exactly one kind of
    # sentence — a question about the screen — and where they do, the LIVE answer is the right
    # one: a fixed sentence about what a screen is cannot tell him what is on his.
    # `_asks_about_this_screen` excludes itself from `asks_about_the_screen`, so in practice
    # only one of the two can match at all; the margin is belt and braces.
    Family("screen_state", needs=(_SAYS_THIS_SCREEN,), boosts=("question",),
           blocks=(_REPORTS_DEFECT, "order_number", "period", "ranking", "known_name",
                   "possessive_name", "names_a_person", "stock", "running_out", "delayed",
                   "address", "status", "bought", "metric", "email"),
           base=0.96, floor=0.72, max_words=12, serves_mutation_words=True),
])
