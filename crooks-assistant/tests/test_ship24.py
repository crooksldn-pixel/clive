"""Ship24 parcel tracking (app/clients/ship24.py, app/tools/ship24_tools.py, the Connections card).

Every call goes to a fake api.ship24.com through an httpx MockTransport: nothing reaches Ship24,
and the key is a fake from tests/fake_credentials.py, assembled at runtime. The response shapes
are the docs' own examples (https://docs.ship24.com/tracking-api-reference, the OpenAPI file's
`response-result-tracker`), with a recipient added to prove it is never read.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any

import httpx
import pytest

from app.capabilities import families
from app.clients import ship24
from app.connections import catalog, testers
from app.routes import connections as connection_routes
from app.secrets import keychain, linux_store
from app.tools import registry, ship24_tools
from app.tools.gate import Disposition, Tier, classify
from app.tools.registry import ToolError
from tests import fake_credentials as fake
from tests.test_actions_routes import client  # noqa: F401 - a fixture `world` needs
from tests.test_connections_routes import (  # noqa: F401 - `world` is a fixture
    HEADERS,
    PROXIED,
    register,
    save,
    world,
)

KEY = fake.bearer_token("ship24-key", length=30)
NUMBER = "9400115901047177598206"

# The docs' example tracking (OpenAPI components.examples.response-result-tracker), as Ship24
# returns it from GET /trackers/search/{n}/results and POST /trackers/track.
DOC_TRACKING: dict[str, Any] = {
    "tracker": {
        "trackerId": "26148317-7502-d3ac-44a9-546d240ac0dd", "trackingNumber": NUMBER,
        "shipmentReference": "c6e4fef4-a816-b68f-4024-3b7e4c5a9f81",
        "clientTrackerId": "3fa99515-3ca0-4901-85bb-056ee016799b", "isSubscribed": True, "isTracked": True,
        "createdAt": "2021-03-10T05:13:00.000Z",
    },
    "shipment": {
        "shipmentId": "f4f888d7-d140-423f-9a48-e0689d27e098", "statusCode": "delivery_delivered",
        "statusCategory": "delivery", "statusMilestone": "delivered", "originCountryCode": "US",
        "destinationCountryCode": "CN",
        "delivery": {"estimatedDeliveryDate": "2021-03-04T18:00:00",
                     "courierEstimatedDeliveryDate": {"from": "2021-03-04T17:00:00", "to": "2021-03-04T18:00:00"},
                     "service": None, "signedBy": None},
        "trackingNumbers": [{"tn": NUMBER}, {"tn": "9400111202544843610364"}],
        # Not in the docs' example (it has nulls): here so the test can prove it is never read.
        "recipient": {"name": "Jo Recipient", "address": "12 Private Road", "postCode": "94901", "city": None,
                      "subdivision": None},
    },
    "events": [
        {"eventId": "ee8ebe96-4eae-4a91-9a99-8f3afa6a0f46", "trackingNumber": "9400111202544843610364",
         "eventTrackingNumber": "9400111202544843610364", "status": "Delivered to the addressee",
         "occurrenceDatetime": "2021-03-04T17:12:57", "order": 9, "location": "SAN RAFAEL, CA 94901",
         "sourceCode": "usps-tracking", "courierCode": "us-post", "statusCode": "delivery_delivered",
         "statusCategory": "delivery", "statusMilestone": "delivered"},
        {"eventId": "ee8ebe96-4eae-4a91-9a99-8f3afa6a00ja", "trackingNumber": "9400111202544843610364",
         "eventTrackingNumber": "9400111202544843610364", "status": "Out for Delivery",
         "occurrenceDatetime": "2021-03-04T10:12:57", "order": 8, "location": "SAN RAFAEL, CA 94901",
         "sourceCode": "usps-tracking", "courierCode": "us-post", "statusCode": "delivery_out_for_delivery",
         "statusCategory": "delivery", "statusMilestone": "out_for_delivery"},
        {"eventId": "ee8ebe96-4eae-4a91-9a99-8f3afa6a0765", "trackingNumber": "9400111202544843610364",
         "eventTrackingNumber": "9400111202544843610364", "status": "Arrived at Hub, Your item arrived at the hub.",
         "occurrenceDatetime": "2021-03-04T06:12:57", "order": 7, "location": "SAN RAFAEL, CA 94901",
         "sourceCode": "usps-tracking", "courierCode": "us-post", "statusCode": None, "statusCategory": None,
         "statusMilestone": "in_transit"},
        {"eventId": "ee8ebe96-4eae-4a91-9a99-8f3afa6a0f67", "trackingNumber": "9400111202544843610364",
         "eventTrackingNumber": "9400111202544843610364", "status": "Processed Through Regional Facility",
         "occurrenceDatetime": "2021-03-03T17:12:57", "order": 6,
         "location": "LOS ANGELES CA INTERNATIONAL DISTRIBUTION CENTER", "sourceCode": "usps-tracking",
         "courierCode": "us-post", "statusCode": None, "statusCategory": None, "statusMilestone": "in_transit"},
        {"eventId": "ee8ebe96-4eae-4a91-9a99-8f3afa6a0f24", "trackingNumber": "9400111202544843610364",
         "eventTrackingNumber": "9400111202544843610364", "status": "Arrived at Regional Facility",
         "occurrenceDatetime": "2021-03-03T15:38:57", "order": 5,
         "location": "LOS ANGELES CA INTERNATIONAL DISTRIBUTION CENTER", "sourceCode": "usps-tracking",
         "courierCode": "us-post", "statusCode": None, "statusCategory": None, "statusMilestone": "in_transit"},
        {"eventId": "5adff7f7-c370-4026-9ff5-2ff4156ff2ff", "trackingNumber": "9400111202544843610364",
         "eventTrackingNumber": NUMBER, "status": "Flight Departure", "occurrenceDatetime": "2021-03-02T23:24:50",
         "order": 4, "location": "Beijing airport", "sourceCode": "china-post-tracking", "courierCode": "cn-post",
         "statusCode": None, "statusCategory": None, "statusMilestone": "in_transit"},
        {"eventId": "918c20dc-9a9b-4588-bf62-ded9761d9621", "trackingNumber": "9400111202544843610364",
         "eventTrackingNumber": NUMBER, "status": "Dispatched from Office of Exchange",
         "occurrenceDatetime": "2021-03-02T22:23:41", "order": 3, "location": "Beijing",
         "sourceCode": "china-post-tracking", "courierCode": "cn-post", "statusCode": None, "statusCategory": None,
         "statusMilestone": "in_transit"},
        {"eventId": "b8dabe5f-1022-41c5-ad3a-8c8e4aacc965", "trackingNumber": "9400111202544843610364",
         "eventTrackingNumber": NUMBER, "status": "Departure from Local Sorting Center",
         "occurrenceDatetime": "2021-03-02T19:24:57", "order": 2, "location": "Beijing",
         "sourceCode": "china-post-tracking", "courierCode": "cn-post", "statusCode": None, "statusCategory": None,
         "statusMilestone": "in_transit"},
        {"eventId": "ee8ebe96-4eae-4a91-9a99-6f3afa6a0f45", "trackingNumber": "9400111202544843610364",
         "eventTrackingNumber": NUMBER, "status": "Package Received", "occurrenceDatetime": "2021-03-02T15:38:57",
         "order": 1, "location": "Beijing", "sourceCode": "china-post-tracking", "courierCode": "cn-post",
         "statusCode": None, "statusCategory": "transit", "statusMilestone": "in_transit"},
    ],
    "statistics": {"timestamps": {
        "infoReceivedDatetime": "2021-03-02T15:38:57", "inTransitDatetime": "2021-03-02T15:38:57",
        "outForDeliveryDatetime": "2021-03-04T10:12:57", "failedAttemptDatetime": None,
        "availableForPickupDatetime": None, "exceptionDatetime": None, "deliveredDatetime": "2021-03-04T17:12:57",
    }},
}


def results(*found: dict[str, Any]) -> dict[str, Any]:
    return {"data": {"trackings": [copy.deepcopy(t) for t in found]}}


def error(code: str, message: str = "MARKER from Ship24") -> dict[str, Any]:
    return {"errors": [{"code": code, "message": message}], "data": None}


NO_PLAN = (403, error("no_active_subscription"))
NOT_TRACKED = (404, error("tracker_not_found", "Tracker not found."))


class FakeShip24:
    """The parts of api.ship24.com CLIVE asks, and every request it was sent. An answer is
    (status, body), an exception to raise, or a function of the request, keyed by (method,
    path-after-/public/v1)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.answers: dict[tuple[str, str], Any] = {}

    def on(self, method: str, path: str, answer: Any) -> None:
        self.answers[(method, path)] = answer

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == "api.ship24.com"
        path = request.url.raw_path.decode().split("?")[0].removeprefix("/public/v1")
        answer = self.answers.get((request.method, path))
        if answer is None:
            return httpx.Response(404, json=error("not_in_this_test"))
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            return answer(request)
        status, body = answer
        headers = {"Retry-After": "7"} if status == 429 else {}
        return httpx.Response(status, json=body, headers=headers)

    def calls(self) -> list[tuple[str, str]]:
        return [(r.method, r.url.raw_path.decode().split("?")[0].removeprefix("/public/v1")) for r in self.requests]


SEARCH = f"/trackers/search/{NUMBER}/results"


@pytest.fixture
def api(monkeypatch) -> FakeShip24:
    fake_api = FakeShip24()
    store = {ship24.KEY_NAME: KEY}
    monkeypatch.setattr(keychain, "get_optional", lambda key: store.get(key))
    monkeypatch.setattr(ship24, "http_client",
                        lambda timeout_s: httpx.AsyncClient(transport=httpx.MockTransport(fake_api.handle)))
    monkeypatch.setattr(testers, "http_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake_api.handle)))
    ship24.forget_plan()
    fake_api.store = store
    yield fake_api
    ship24.forget_plan()


def key_only_in_the_header(api: FakeShip24) -> None:
    assert api.requests, "nothing was asked"
    for request in api.requests:
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert KEY not in str(request.url) and KEY not in request.content.decode()


# ------------------------------------------------------------------ the key's test (Connections)

async def run(values):
    return await testers.run("ship24", values, None)


async def test_the_tester_lists_one_tracker_and_creates_none(api):
    api.on("GET", "/trackers", (200, {"data": {"trackers": [DOC_TRACKING["tracker"]]}}))
    outcome = await run({"ship24_api_key": KEY})
    assert outcome.ok and outcome.detail == "Ship24 accepted the key."
    assert api.calls() == [("GET", "/trackers")] and api.requests[0].url.params["limit"] == "1"
    key_only_in_the_header(api)


@pytest.mark.parametrize("status, body, ok, says", [
    (401, error("unauthorized"), False, "refused that key"),
    (429, {"errors": []}, False, "limiting requests"),
    (403, error("no_active_subscription"), True, "no per-shipment plan"),
    (503, {}, False, "answered 503"),
])
async def test_the_tester_names_each_answer_in_our_words(api, status, body, ok, says):
    api.on("GET", "/trackers", (status, body))
    outcome = await run({"ship24_api_key": KEY})
    assert outcome.ok is ok and says in outcome.detail
    assert "MARKER" not in outcome.detail and KEY not in outcome.detail
    assert [m for m, _ in api.calls()] == ["GET"]               # a refused key is never retried as a POST


async def test_the_tester_cannot_reach_ship24_is_a_failed_test(api):
    api.on("GET", "/trackers", httpx.ConnectError("no route"))
    outcome = await run({"ship24_api_key": KEY})
    assert not outcome.ok and "could not be reached" in outcome.detail


# ------------------------------------------------------------------ the client reads the docs' shape

def test_the_docs_example_reads_as_carrier_status_estimate_and_scans():
    out = ship24.summary(copy.deepcopy(DOC_TRACKING), number=NUMBER, plan_=ship24.PER_SHIPMENT)
    assert out["tracking_number"] == NUMBER
    assert out["courier"] == "us-post, cn-post"                         # latest carrier first
    assert out["status"] == "Delivered" and out["milestone"] == "delivered"
    assert out["estimated_delivery"] == {"earliest": "2021-03-04T17:00:00", "latest": "2021-03-04T18:00:00",
                                         "source": "the carrier"}
    assert out["delivered_at"] == "2021-03-04T17:12:57"
    assert (out["origin"], out["destination"]) == ("US", "CN")
    assert out["events"][0] == {"at": "2021-03-04T17:12:57", "location": "SAN RAFAEL, CA 94901",
                                "status": "Delivered to the addressee"}
    assert out["events"][-1]["status"] == "Package Received" and out["events_total"] == 9
    said = json.dumps(out)
    assert "Jo Recipient" not in said and "Private Road" not in said and "recipient" not in said


def test_without_the_carriers_window_the_date_or_ship24s_prediction_is_the_estimate():
    tracking = copy.deepcopy(DOC_TRACKING)
    tracking["shipment"]["delivery"]["courierEstimatedDeliveryDate"] = None
    assert ship24.summary(tracking, number=NUMBER, plan_="")["estimated_delivery"]["latest"] == "2021-03-04T18:00:00"
    tracking["shipment"]["delivery"] = {"aiPredictiveDeliveryDate": {"from": "2021-03-05T09:00:00+01:00",
                                                                     "to": "2021-03-05T13:00:00+01:00"}}
    estimate = ship24.summary(tracking, number=NUMBER, plan_="")["estimated_delivery"]
    assert estimate["source"] == "Ship24's prediction" and estimate["earliest"].startswith("2021-03-05T09")
    tracking["shipment"]["delivery"] = {}
    assert ship24.summary(tracking, number=NUMBER, plan_="")["estimated_delivery"] is None


@pytest.mark.parametrize("said, number", [
    ("  9400 1159 0104 7177 5982 06 ", NUMBER),
    ("ship24_sample_delivered_000", "SHIP24_SAMPLE_DELIVERED_000"),
])
def test_a_number_is_sent_as_ship24_answers_it(said, number):
    assert ship24.tracking_number(said) == number


@pytest.mark.parametrize("said", ["", "1234", "AB12-<script>", "x" * 51, "JD 0002; DROP"])
async def test_what_is_not_a_tracking_number_is_refused_before_any_request(api, said):
    with pytest.raises(ToolError, match="isn't a tracking number"):
        await ship24_tools.track_parcel(said)
    assert api.requests == []


# ------------------------------------------------------------------ the tool, per-shipment

async def test_a_tracked_parcel_is_read_from_its_tracker_and_nothing_is_created(api):
    api.on("GET", SEARCH, (200, results(DOC_TRACKING)))
    out = await registry.invoke("track_parcel", {"tracking_number": NUMBER}, timeout_s=5)
    assert api.calls() == [("GET", SEARCH)]
    assert out["status"] == "Delivered" and out["new_tracker"] is False and out["plan"] == "per-shipment"
    assert out["checked_at"].endswith("+00:00") and "note" not in out
    assert ship24.plan() == ship24.PER_SHIPMENT
    key_only_in_the_header(api)


async def test_a_number_ship24_is_not_tracking_yet_is_tracked_now_and_says_so(api):
    api.on("GET", SEARCH, NOT_TRACKED)
    api.on("POST", "/trackers/track", (200, results(DOC_TRACKING)))
    out = await ship24_tools.track_parcel(NUMBER, courier="Royal Mail")
    assert api.calls() == [("GET", SEARCH), ("POST", "/trackers/track")]
    sent = json.loads(api.requests[1].content)
    assert sent == {"trackingNumber": NUMBER, "courierName": "Royal Mail"}
    assert out["new_tracker"] is True and "started tracking" in out["note"]
    key_only_in_the_header(api)


async def test_a_courier_code_ship24_does_not_know_is_dropped_and_asked_again(api):
    api.on("GET", SEARCH, NOT_TRACKED)
    seen: list[dict] = []

    def track(request):
        seen.append(json.loads(request.content))
        return (httpx.Response(400, json=error("validation_error")) if "courierCode" in seen[-1]
                else httpx.Response(200, json=results(DOC_TRACKING)))

    api.on("POST", "/trackers/track", track)
    out = await ship24_tools.track_parcel(NUMBER, courier="not-a-courier")
    assert seen == [{"trackingNumber": NUMBER, "courierCode": ["not-a-courier"]}, {"trackingNumber": NUMBER}]
    assert out["status"] == "Delivered"


async def test_of_several_trackers_on_one_number_the_couriers_own_is_read(api):
    other = copy.deepcopy(DOC_TRACKING)
    other["tracker"]["createdAt"] = "2025-01-01T00:00:00.000Z"
    other["events"] = [dict(e, courierCode="dpd-uk", status="Elsewhere") for e in other["events"][:2]]
    api.on("GET", SEARCH, (200, results(other, DOC_TRACKING)))
    assert (await ship24_tools.track_parcel(NUMBER, courier="cn-post"))["events"][0]["status"] == "Delivered to the addressee"
    assert (await ship24_tools.track_parcel(NUMBER))["trackers"] == 2


async def test_a_parcel_with_no_scans_yet_is_pending_and_says_why(api):
    pending = {"tracker": DOC_TRACKING["tracker"], "shipment": {"statusMilestone": "pending", "delivery": {}},
               "events": [], "statistics": {"timestamps": {}}}
    api.on("GET", SEARCH, (200, results(pending)))
    out = await ship24_tools.track_parcel(NUMBER)
    assert out["status"] == "No carrier scans yet" and out["events"] == [] and "No carrier scans" in out["note"]


# ------------------------------------------------------------------ the plans

async def test_a_per_call_key_is_answered_by_tracking_search_and_remembered(api):
    api.on("GET", SEARCH, NO_PLAN)
    api.on("POST", "/tracking/search", (201, results({k: v for k, v in DOC_TRACKING.items() if k != "tracker"})))
    out = await ship24_tools.track_parcel(NUMBER)
    assert api.calls() == [("GET", SEARCH), ("POST", "/tracking/search")]
    assert out["plan"] == "per-call" and out["tracking_number"] == NUMBER and out["status"] == "Delivered"
    assert ship24.plan() == ship24.PER_CALL
    api.requests.clear()
    await ship24_tools.track_parcel(NUMBER)
    assert api.calls() == [("POST", "/tracking/search")]               # straight to the plan it is on
    key_only_in_the_header(api)


async def test_a_key_with_no_plan_at_all_is_told_so_and_where_to_choose_one(api):
    api.on("GET", SEARCH, NO_PLAN)
    api.on("POST", "/tracking/search", NO_PLAN)
    with pytest.raises(ToolError) as refused:
        await ship24_tools.track_parcel(NUMBER)
    said = str(refused.value)
    assert "no active plan" in said and "dashboard.ship24.com" in said and "MARKER" not in said
    assert ("POST", "/trackers/track") not in api.calls() and ship24.plan() == ""


async def test_a_new_key_is_asked_which_plan_it_is_on_again(api):
    from app.connections import service

    ship24._PLAN["plan"] = ship24.PER_CALL
    await service.after_change(None, ("ship24_api_key",))
    assert ship24.plan() == ""


# ------------------------------------------------------------------ refusals, in our words

@pytest.mark.parametrize("answer, says", [
    ((401, error("unauthorized")), "refused CLIVE's key"),
    ((403, error("quota_limit_reached")), "allowance for this billing period is used up"),
    ((429, {"errors": []}), "slow down; try again in 7 seconds"),
    ((500, {}), "having trouble"),
    ((400, error("validation_error")), "didn't accept that tracking number"),
    (httpx.ConnectError("no route"), "could not be reached"),
    (httpx.ReadTimeout("slow"), "did not answer in time"),
])
async def test_each_refusal_reaches_the_owner_as_words_and_never_quotes_ship24(api, answer, says):
    api.on("GET", SEARCH, answer)
    with pytest.raises(ToolError) as refused:
        await ship24_tools.track_parcel(NUMBER)
    assert says in str(refused.value) and "MARKER" not in str(refused.value)
    assert ("POST", "/trackers/track") not in api.calls()            # a refusal never makes a tracker


async def test_a_first_look_up_still_running_says_to_ask_again(api):
    api.on("GET", SEARCH, NOT_TRACKED)
    api.on("POST", "/trackers/track", httpx.ReadTimeout("slow"))
    with pytest.raises(ToolError, match="Ask again shortly"):
        await ship24_tools.track_parcel(NUMBER)


async def test_no_key_says_how_to_connect_and_asks_nobody(api):
    api.store.clear()
    with pytest.raises(ToolError, match="add the Ship24 key on the Connections screen"):
        await ship24_tools.track_parcel(NUMBER)
    assert api.requests == []


# ------------------------------------------------------------------ bounded, and the key never shows

async def test_the_result_is_bounded_however_much_ship24_sends(api):
    many = copy.deepcopy(DOC_TRACKING)
    many["events"] = [dict(many["events"][0], status="S" * 5000, location="L" * 5000, courierCode=f"c-{i}")
                      for i in range(400)]
    api.on("GET", SEARCH, (200, results(many)))
    out = await ship24_tools.track_parcel(NUMBER)
    assert len(out["events"]) == ship24.MAX_EVENTS == 15 and out["events_total"] == 400
    assert all(len(e["status"]) <= ship24.MAX_STATUS and len(e["location"]) <= ship24.MAX_LOCATION
               for e in out["events"])
    assert len(out["courier"].split(", ")) <= ship24.MAX_COURIERS
    assert len(json.dumps(out)) < 6_000


async def test_the_key_appears_in_no_result_refusal_or_log_line(api, caplog):
    caplog.set_level(logging.DEBUG)
    echoed = error("validation_error", f"bad key {KEY}")
    for answer in ((200, results(DOC_TRACKING)), (400, echoed), (401, echoed), (403, echoed), (500, echoed)):
        api.on("GET", SEARCH, answer)
        ship24.forget_plan()
        try:
            said = json.dumps(await registry.invoke("track_parcel", {"tracking_number": NUMBER}, timeout_s=5))
        except ToolError as exc:
            said = str(exc)
        assert KEY not in said
    api.on("GET", "/trackers", (400, echoed))
    assert KEY not in (await run({"ship24_api_key": KEY})).detail
    assert KEY not in caplog.text


# ------------------------------------------------------------------ the family, the gate, the catalog

async def test_the_family_is_ready_with_a_key_and_says_how_to_connect_without_one(api):
    from app.families import load_all

    load_all()          # the shipping families (app/families/shipping.py), as the runtime loads them
    table = await families.states(None)
    assert table["parcel_tracking"]["state"] == "READY" and table["parcel_tracking"]["tools"] == ["track_parcel"]
    assert table["delivery_tracking"]["state"] == "READY"
    api.store.clear()
    table = await families.states(None)
    row = table["parcel_tracking"]
    assert row["state"] == "DISCONNECTED"
    assert row["detail"] == "not connected — add the Ship24 key on the Connections screen"
    assert table["delivery_tracking"]["state"] == "DISCONNECTED"
    # One line for both, said once at the top of the turn, and the tool is not offered.
    lines = [line for line in families.words(table) if "Ship24" in line]
    assert lines == ["- DISCONNECTED — not connected — add the Ship24 key on the Connections screen: "
                     "Delivery status, Parcel tracking"]

    from types import SimpleNamespace

    from app.runtime import Runtime

    assert "track_parcel" in Runtime.withheld_by_family(SimpleNamespace(family_states_table=table))


def test_track_parcel_is_a_green_read_that_never_reads_as_a_write():
    from app.tools import gate

    spec = registry.get("track_parcel")
    assert spec.tier is Tier.GREEN and spec.write is None and spec.batch is None
    assert "track_parcel" in gate._KNOWN_TOOLS and not gate._looks_like_mutation("track_parcel")
    decided = classify("track_parcel", {"tracking_number": NUMBER})
    assert decided.disposition is Disposition.EXECUTE_NOW and decided.tier is Tier.GREEN
    assert "shopify_order_detail" in spec.description and "Changes nothing in Shopify" in spec.description


def test_nothing_in_the_tool_or_its_client_can_reach_shopify():
    import inspect

    for module in (ship24, ship24_tools):
        source = inspect.getsource(module)
        assert "app.clients.shopify" not in source and "shopify_writes" not in source


def test_the_catalog_offers_ship24_with_one_key_field_and_the_secret_is_known():
    from scripts import provision_secrets

    connection = catalog.get("ship24")
    assert connection is not None and connection.label == "Ship24"
    assert [f.key for f in connection.fields] == ["ship24_api_key"] and connection.fields[0].secret
    assert "dashboard.ship24.com" in connection.fields[0].hint
    assert connection.requires == ("ship24_api_key",) and connection.family == "parcel_tracking"
    assert "ship24" in testers.TESTERS and connection_routes.NAME.fullmatch("ship24")
    assert "ship24_api_key" in keychain.KNOWN_KEYS and provision_secrets.HELP.get("ship24_api_key")
    assert "ship24_api_key" in linux_store.STATIC_KEYS


# ------------------------------------------------------------------ the Connections routes

def ship24_too(http, api: FakeShip24, monkeypatch) -> None:
    """The route tests' services, with api.ship24.com answered by `api`."""
    def handler(request):
        return api.handle(request) if request.url.host == "api.ship24.com" else http.services(request)

    monkeypatch.setattr(testers, "http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_the_key_is_saved_from_the_connections_screen_after_its_test(world, monkeypatch):  # noqa: F811 - the fixture imported above
    api = FakeShip24()
    api.on("GET", "/trackers", (200, {"data": {"trackers": []}}))
    ship24_too(world, api, monkeypatch)
    ship24._PLAN["plan"] = ship24.PER_CALL
    await register(world)
    done = await save(world, "ship24", {"ship24_api_key": KEY})
    assert done.status_code == 200, done.text
    assert done.json()["result"]["ok"] is True and KEY not in done.text
    assert linux_store.read("ship24_api_key") == KEY and linux_store.where("ship24_api_key") == "app"
    assert ship24.api_key() == KEY and ship24.plan() == ""              # live at once, plan asked again
    key_only_in_the_header(api)
    state = await world.get("/connections/state", headers=PROXIED)
    assert KEY not in state.text
    card = next(c for c in state.json()["connections"] if c["name"] == "ship24")
    assert card["state"] == "connected" and card["testable"] and card["fields"][0]["where"] == "saved here"
    tested = await world.post("/connections/ship24/test", json={}, headers=HEADERS)
    assert tested.status_code == 200 and tested.json()["result"]["ok"] is True


async def test_a_ship24_key_that_fails_its_test_is_never_stored(world, monkeypatch):  # noqa: F811 - the fixture imported above
    api = FakeShip24()
    api.on("GET", "/trackers", (401, error("unauthorized")))
    ship24_too(world, api, monkeypatch)
    await register(world)
    done = await save(world, "ship24", {"ship24_api_key": KEY})
    assert done.status_code == 422 and "refused that key" in done.json()["detail"]
    assert linux_store.where("ship24_api_key") == ""
