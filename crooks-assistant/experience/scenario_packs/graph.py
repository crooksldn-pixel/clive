"""The customer / order / email graph, driven the way the tablet drives it (brief §16).

Two things that were broken on the bench, in the order they happen on the workbench:

    a thread showed its words and hid its order      → the linked_order strip, and a tap on it
    an order hid the email about it                   → the order's Email tab

The compound sentence ("have they emailed … and draft the reply") was answered by a
word-matching recipe until 28 September 2026, when the owner had that lane removed: it is the
model's now, like every sentence, and its scenarios went with the recipe. Nothing here may
write.
"""

from __future__ import annotations

from experience.harness import Harness

# `Result`, `check` and the shared assertions live in experience/scenarios.py, which collects
# the packs at the END of its own module body, so these names are bound by the time this is
# imported. Importing them keeps one definition of what a check is.
from experience.scenarios import Result, a_model_turn, a_surface, check, deterministic, grounded

MIA_THREAD = "aa70d3f83dbef06e"
MIA_ORDER = "gid://shopify/Order/1938"


def _ok(c) -> bool:
    return bool(c.raw.get("ok", True))


def _detail(c) -> str:
    return f"code={c.raw.get('code')!r} detail={c.raw.get('detail')!r}"


def _issued(h: Harness, session_id: str) -> set[str]:
    """The ids this conversation has been shown. The gate refuses every id that is not in here
    (app/tools/gate.py), which is exactly what happened to the bench turn's two thread reads."""
    return set(getattr(h.runtime.sessions.get(session_id), "issued_ids", ()) or ())


async def graph_thread_to_order(h: Harness) -> Result:
    r = Result("graph_thread_to_order", "Open Mia's thread from the queue, then its order")
    q = await h.touch("open.area", area="email", scenario="graph_thread_to_order", session_id="graph1")
    r.captures.append(q)
    r.checks.append(check("the Inbox landing's queue is the Mac's own, tapped", q.model_calls == 0, f"model_calls={q.model_calls}"))
    r.checks.append(check("Mia's thread is a row on it, so the conversation has been shown that id",
                          MIA_THREAD in _issued(h, "graph1"), f"issued={sorted(_issued(h, 'graph1'))[:6]}"))

    c = await h.touch("open.entity", scenario="graph_thread_to_order", session_id="graph1",
                      kind="email_thread", ref=MIA_THREAD, label="Order 1938")
    r.captures.append(c)
    r.checks.append(check("a row on the queue opens", c.status == 200 and _ok(c), _detail(c)))
    r.checks += a_surface(c, "email_thread", what="draws the thread")
    r.checks.append(deterministic(c))
    card = c.data("email_thread")
    linked = card.get("linked_order") if isinstance(card.get("linked_order"), dict) else {}
    r.checks.append(check("the thread says which order it is about", bool(linked.get("order_id")),
                          f"link_confidence={card.get('link_confidence')!r} linked_order={linked}"))
    r.checks.append(check("and how sure that is, in words", card.get("link_confidence") == "confident" and bool(card.get("link_provenance")),
                          f"confidence={card.get('link_confidence')!r} why={card.get('link_provenance')}"))
    if grounded(h):
        r.checks.append(check("the money and the status are on the strip, so the owner need not open it",
                              linked.get("order_number") == "#1938" and linked.get("total") == "£89.00" and linked.get("fulfillment") == "unfulfilled",
                              f"linked_order={linked}"))
    # Tappable is not a claim about the DOM: it is that the ref the strip carries was issued to
    # this conversation, so the tap the renderer wires up is a tap the gate will honour.
    r.checks.append(check("the strip's order was issued, so the tap on it is not refused",
                          str(linked.get("order_id") or "") in _issued(h, "graph1"), f"order_id={linked.get('order_id')!r}"))

    o = await h.touch("open.entity", scenario="graph_thread_to_order", session_id="graph1",
                      kind="order", ref=str(linked.get("order_id") or MIA_ORDER), label="#1938")
    r.captures.append(o)
    r.checks.append(check("tapping it opens the order", o.status == 200 and _ok(o), _detail(o)))
    r.checks += a_surface(o, "order", what="draws the order")
    r.checks.append(deterministic(o))
    r.checks.append(check("the order is now what the conversation is on", (o.entity or {}).get("ref") == MIA_ORDER, f"entity={o.entity}"))
    return r


async def graph_order_to_email(h: Harness) -> Result:
    r = Result("graph_order_to_email", "Order 1938, and the email about it")
    c = await h.open_order("1938", scenario="graph_order_to_email", session_id="graph2")
    r.captures.append(c)
    r.checks += a_surface(c, "order", what="draws the order")
    r.checks.append(a_model_turn(c))
    email = c.data("order").get("email") if isinstance(c.data("order").get("email"), dict) else {}
    threads = [t for t in (email.get("threads") or []) if isinstance(t, dict)]
    r.checks.append(check("the order card carries the inbox around it", bool(email.get("available")) and bool(threads),
                          f"email={ {k: email.get(k) for k in ('available', 'reason')} } threads={len(threads)}"))
    r.checks.append(check("Mia's thread about it is one of them",
                          MIA_THREAD in [str(t.get("thread_id")) for t in threads],
                          f"threads={[str(t.get('subject')) for t in threads]}"))
    if grounded(h):
        mine = next((t for t in threads if str(t.get("thread_id")) == MIA_THREAD), {})
        r.checks.append(check("and it says why it is on this order — her address and the number, not her name",
                              mine.get("match") == "both" and mine.get("sender_match") is True,
                              f"match={mine.get('match')!r} sender_match={mine.get('sender_match')!r}"))
    tab = await h.touch("surface.tab", scenario="graph_order_to_email", session_id="graph2", surface="order", tab="email")
    r.captures.append(tab)
    r.checks.append(check("the Email tab is a place on the order, not a new question",
                          tab.status == 200 and _ok(tab) and (tab.raw.get("changed") or {}).get("tab") == "email", _detail(tab)))
    return r


SCENARIOS = (
    ("graph_thread_to_order", graph_thread_to_order),
    ("graph_order_to_email", graph_order_to_email),
)
