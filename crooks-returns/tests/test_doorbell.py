"""The doorbell to CLIVE (returns/doorbell.py, the outbox in returns/store.py): each recorded event
posted to CLIVE's door by id and type only, signed, retried with backoff, never in the way of the
person acting, and off when no address is set.

CLIVE is stood in for by an httpx MockTransport; nothing here reaches a network. The fixture shop's
customer (Sam Taylor, customer@example.com) is the detail that must never go out.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from returns import doorbell as bell
from returns.app import create_app
from returns.models import Postage, Resolution
from returns.service import ReturnsService
from returns.store import Store

from .conftest import RecordingNotifier
from .test_service import act, submit

HOOK = "https://hooks.example.com/hooks/returns"
SECRET = "doorbell-test-secret-0123456789abcdef"


class FakeClive:
    """CLIVE's door: answers each post with the next of `answers` (a status, or an exception)."""

    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.posts: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.posts.append(request)
        answer = self.answers.pop(0) if self.answers else 200
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(answer)

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.posts]


class Clock:
    """The doorbell's clock, a moment after the events these tests record (they are queued at the
    real time), moved on by hand."""

    def __init__(self) -> None:
        self.now = time.time() + 5

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def hooked(settings, shop, labels, clock):
    """The service with CLIVE's hook set, its doorbell driven by hand (no thread)."""
    settings.clive_webhook_url = HOOK
    settings.clive_webhook_secret = SECRET
    svc = ReturnsService(
        settings, Store(settings.db_path), shop, labels, RecordingNotifier(settings), clock=clock
    )
    clive = FakeClive()
    svc.doorbell._http = httpx.Client(transport=httpx.MockTransport(clive))
    svc.doorbell.clock = Clock()
    svc.clive = clive  # type: ignore[attr-defined]
    return svc


def waiting(svc) -> list[dict]:
    return svc.store.outbox_due("9999", 1000)


def test_off_when_no_address_is_set(svc):
    assert svc.doorbell.on is False and svc.store.outbox is False
    submit(svc, Resolution.refund, Postage.self_ship)
    assert svc.store.outbox_counts() == {}, "no row is written"
    assert svc.doorbell.start() is False, "no thread starts"
    assert svc.doorbell.deliver_due() == 0


def test_every_recorded_event_gets_one_row_in_the_same_save(hooked):
    ret = submit(hooked, Resolution.refund, Postage.self_ship)
    act(hooked, ret, "approve")
    act(hooked, ret, "note", text="rang them")
    saved = hooked.store.get(ret.id)
    rows = waiting(hooked)
    assert [r["type"] for r in rows] == [e.type for e in saved.timeline]
    assert len({r["id"] for r in rows}) == len(rows), "two events never share an id"
    hooked.store.save(saved)  # saved again with nothing new
    assert len(waiting(hooked)) == len(rows), "saving again never makes a second row"
    first = saved.timeline[0]
    assert rows[0]["id"] == bell.event_id(ret.id, 0, first.at.isoformat(), first.type)


def test_what_goes_out_is_the_event_and_never_the_customer(hooked):
    ret = submit(hooked, Resolution.refund, Postage.self_ship)
    assert hooked.doorbell.deliver_due() == 1
    [post] = hooked.clive.posts
    sent = json.loads(post.content)
    assert set(sent) == {"id", "type", "return_id", "at", "sent_at"}
    assert (sent["type"], sent["return_id"]) == ("requested", ret.id)
    assert abs(sent["sent_at"] - hooked.doorbell.clock()) < 1
    raw = post.content.decode()
    for private in ("Sam Taylor", "customer@example.com", ret.order_name, ret.order_id, "Docket"):
        assert private not in raw, private
    assert str(post.url) == HOOK and post.method == "POST"


def test_the_post_is_signed_over_its_raw_body(hooked):
    submit(hooked, Resolution.refund, Postage.self_ship)
    hooked.doorbell.deliver_due()
    [post] = hooked.clive.posts
    expected = hmac.new(SECRET.encode(), post.content, hashlib.sha256).hexdigest()
    assert post.headers[bell.SIGNATURE_HEADER] == f"sha256={expected}"
    assert post.headers["content-type"] == "application/json"


def test_a_delivered_event_is_never_sent_again(hooked):
    submit(hooked, Resolution.refund, Postage.self_ship)
    assert hooked.doorbell.deliver_due() == 1
    assert hooked.doorbell.deliver_due() == 0
    assert len(hooked.clive.posts) == 1
    assert hooked.store.outbox_counts() == {"delivered": 1}


@pytest.mark.parametrize(
    "trouble",
    [500, 403, 404, 302, httpx.ConnectTimeout("slow"), httpx.ConnectError("refused")],
    ids=["500", "403", "404", "redirect", "timeout", "unreachable"],
)
def test_anything_but_a_2xx_is_tried_again_later_with_backoff(hooked, trouble):
    ret = submit(hooked, Resolution.refund, Postage.self_ship)
    hooked.clive.answers = [trouble, trouble, 200]
    clock = hooked.doorbell.clock
    assert hooked.doorbell.deliver_due() == 0
    assert hooked.doorbell.deliver_due() == 0, "not due again for 30 seconds"
    clock.now += 31
    assert hooked.doorbell.deliver_due() == 0
    clock.now += 31
    assert hooked.doorbell.deliver_due() == 0, "the second wait is a minute"
    clock.now += 30
    assert hooked.doorbell.deliver_due() == 1
    sent = hooked.clive.bodies()
    assert [b["return_id"] for b in sent] == [ret.id] * 3, "the same event, three tries"
    assert len({b["id"] for b in sent}) == 1
    assert [p.url for p in hooked.clive.posts] == [httpx.URL(HOOK)] * 3, (
        "a redirect is never followed"
    )


def test_backoff_doubles_to_an_hour():
    assert [bell.backoff(n) for n in (1, 2, 3, 4, 8, 20)] == [30, 60, 120, 240, 3600, 3600]


def test_after_a_day_an_event_is_given_up(hooked, caplog):
    submit(hooked, Resolution.refund, Postage.self_ship)
    hooked.clive.answers = [503] * 100
    clock = hooked.doorbell.clock
    clock.now += 24 * 3600 + 1
    hooked.doorbell.deliver_due()
    assert hooked.store.outbox_counts() == {"given_up": 1}
    clock.now += 3600
    assert hooked.doorbell.deliver_due() == 0 and len(hooked.clive.posts) == 1
    assert "gave up" in caplog.text and "Sam Taylor" not in caplog.text


def test_a_crlf_env_posts_to_the_address_the_doorbell_checked(hooked):
    """A .env saved with CRLF endings gives the address a trailing `\\r`. `on` ignores it, so the
    post goes to the same address without it, rather than to one httpx refuses."""
    hooked.s.clive_webhook_url = HOOK + "\r"
    submit(hooked, Resolution.refund, Postage.self_ship)
    assert hooked.doorbell.deliver_due() == 1
    assert [p.url for p in hooked.clive.posts] == [httpx.URL(HOOK)]
    assert hooked.store.outbox_counts() == {"delivered": 1}


@pytest.mark.parametrize(
    "address",
    ["https://hooks.example.com\r/hooks/returns", "http://[::1/hooks/returns"],
    ids=["a-cr-inside", "a-typo"],
)
def test_an_address_httpx_refuses_is_a_try_given_up_after_a_day_and_every_row_is_tried(
    hooked, caplog, address
):
    """Every row of the pass gets its try (answer "error"), waits its backoff, and is given up
    after a day like any other failure; the pass itself never raises."""
    hooked.s.clive_webhook_url = address
    ret = submit(hooked, Resolution.refund, Postage.self_ship)
    act(hooked, ret, "approve")
    rows = len(waiting(hooked))
    assert rows >= 2
    assert hooked.doorbell.deliver_due() == 0
    tried = hooked.store._db.execute("SELECT state, attempts, last_answer FROM outbox").fetchall()
    assert tried == [("waiting", 1, "error")] * rows, "each row of the batch was tried once"
    assert hooked.doorbell.deliver_due() == 0, "not due again for 30 seconds"
    hooked.doorbell.clock.now += 24 * 3600 + 1
    assert hooked.doorbell.deliver_due() == 0
    assert hooked.store.outbox_counts() == {"given_up": rows}
    assert "InvalidURL" in caplog.text and "\r" not in caplog.text and "[::1" not in caplog.text


def test_a_post_that_fails_oddly_never_stops_the_rest_of_the_batch(hooked):
    ret = submit(hooked, Resolution.refund, Postage.self_ship)
    act(hooked, ret, "approve")
    rows = len(waiting(hooked))
    hooked.clive.answers = [ValueError("not an httpx error")]
    assert hooked.doorbell.deliver_due() == rows - 1, "the rest of the batch went"
    assert hooked.store.outbox_counts() == {"delivered": rows - 1, "waiting": 1}
    hooked.doorbell.clock.now += 31
    assert hooked.doorbell.deliver_due() == 1, "the odd one is tried again on schedule"


def test_without_a_secret_nothing_goes_unsigned(hooked, caplog):
    hooked.s.clive_webhook_secret = ""
    submit(hooked, Resolution.refund, Postage.self_ship)
    assert hooked.doorbell.deliver_due() == 0
    assert hooked.clive.posts == [], "nothing is sent unsigned"
    assert hooked.store.outbox_counts() == {"waiting": 1}, "it waits for the secret"
    assert "RETURNS_CLIVE_WEBHOOK_SECRET is not set" in caplog.text
    hooked.s.clive_webhook_secret = SECRET
    hooked.doorbell.clock.now += 31
    assert hooked.doorbell.deliver_due() == 1


def test_a_failing_clive_never_slows_or_fails_the_person_acting(hooked):
    """Nothing on the request path posts: the actions finish with CLIVE unreachable, and the posts
    happen only when the doorbell runs."""
    hooked.clive.answers = [httpx.ConnectError("down")] * 50
    ret = submit(hooked, Resolution.refund, Postage.self_ship)
    out = act(hooked, ret, "approve")
    assert out["status"] == "awaiting_shipment"
    assert hooked.clive.posts == [], "the actions posted nothing themselves"
    hooked.doorbell.deliver_due()
    assert len(hooked.clive.posts) == len(hooked.store.get(ret.id).timeline)


def test_a_row_that_cannot_be_written_never_stops_the_return_being_saved(hooked, caplog):
    hooked.store._db.execute("DROP TABLE outbox")
    ret = submit(hooked, Resolution.refund, Postage.self_ship)
    assert hooked.store.get(ret.id) is not None, "the return is saved"
    assert "were not queued for CLIVE" in caplog.text


def test_a_save_that_fails_records_no_event(hooked, monkeypatch):
    """The row and the return are one transaction: a return that was not saved sent nothing."""
    ret = submit(hooked, Resolution.refund, Postage.self_ship)
    before = len(waiting(hooked))
    doc = hooked.store.get(ret.id)
    doc.timeline.append(doc.timeline[0].model_copy(update={"type": "note"}))
    monkeypatch.setattr(
        type(doc), "model_dump_json", lambda self, **kw: (_ for _ in ()).throw(RuntimeError("disk"))
    )
    with pytest.raises(RuntimeError):
        hooked.store.save(doc)
    assert len(waiting(hooked)) == before


def test_events_another_process_records_are_sent_by_the_running_service(hooked, settings):
    """returns-ctl writes to the same database: its events go out from the running service's outbox."""
    ret = submit(hooked, Resolution.refund, Postage.self_ship)
    hooked.doorbell.deliver_due()
    other = Store(settings.db_path, outbox=True)
    doc = other.get(ret.id)
    doc.timeline.append(doc.timeline[0].model_copy(update={"type": "note"}))
    other.save(doc)
    assert hooked.doorbell.deliver_due() == 1
    assert hooked.clive.bodies()[-1]["type"] == "note"


def test_the_running_service_rings_by_itself(settings, shop, labels, clock):
    """With the address set, the app's own thread posts each event shortly after it is recorded."""
    settings.clive_webhook_url = HOOK
    settings.clive_webhook_secret = SECRET
    svc = ReturnsService(settings, Store(settings.db_path), shop, labels, clock=clock)
    clive = FakeClive()
    svc.doorbell._http = httpx.Client(transport=httpx.MockTransport(clive))
    with TestClient(create_app(settings, svc)):
        submit(svc, Resolution.refund, Postage.self_ship)
        for _ in range(100):
            if clive.posts:
                break
            time.sleep(0.05)
    assert [b["type"] for b in clive.bodies()] == ["requested"]
    assert svc.doorbell._thread is None, "stopped with the app"


def test_returns_ctl_says_whether_events_reach_clive(hooked, monkeypatch, capsys):
    from returns import ctl

    monkeypatch.setattr(ctl, "build_service", lambda settings: hooked)
    hooked.s.clive_webhook_url = ""
    assert ctl.main(["doorbell"]) == 0
    assert "Off: RETURNS_CLIVE_WEBHOOK_URL is not set" in capsys.readouterr().out
    hooked.s.clive_webhook_url = HOOK
    ret = submit(hooked, Resolution.refund, Postage.self_ship)
    hooked.clive.answers = [403]
    hooked.doorbell.deliver_due()
    assert ctl.main(["doorbell"]) == 0
    said = capsys.readouterr().out
    assert f"To {HOOK}: 1 waiting, 0 delivered, 0 given up" in said
    assert "a requested event, answer 403 (waiting, try 1)" in said
    assert ret.id not in said and "Sam Taylor" not in said
