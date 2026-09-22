import XCTest
@testable import CrooksControlCore

/// "tablet connected vs backend merely reachable" (§26), which is the whole of this file.
final class PadTests: XCTestCase {

    let now = Date(timeIntervalSince1970: 1_789_000_000)

    func status(_ data: Data) throws -> StatusDocument {
        try Contract.decoder.decode(StatusDocument.self, from: data)
    }

    /// The online fixture with a pad heartbeat bolted on, as a newer control script would send
    /// one. The heartbeat is the only thing that can make the app say CONNECTED.
    func withPad(seenAt: Double?, agent: String = "crooks-pad 1.4.0 (SM-T290)") throws -> StatusDocument {
        var raw = try XCTUnwrap(String(data: Fixture.onlineStatus, encoding: .utf8))
        let seen = seenAt.map { "\($0)" } ?? "null"
        raw = raw.replacingOccurrences(
            of: "\"port\": 8000",
            with: "\"port\": 8000,\n  \"pad\": {\"seen_at\": \(seen), \"agent\": \"\(agent)\", "
                + "\"address\": \"100.71.4.9\", \"build\": \"1.4.0\"}"
        )
        return try status(Data(raw.utf8))
    }

    // MARK: - The trap

    func testARouteOnItsOwnIsNeverDrawnAsConnected() throws {
        // The status document has a Tailscale host. Everything is GREEN. The tablet could
        // still be switched off in a drawer, and nothing in this document would say so.
        let document = try status(Fixture.onlineStatus)
        XCTAssertFalse(document.tablet.host.isEmpty, "there IS a route — that is the trap")
        XCTAssertNil(document.pad, "and no heartbeat, because this build does not send one")

        let presence = PadReading.read(document, now: now)
        XCTAssertFalse(presence.isConnected)
        guard case .cannotTell = presence else {
            return XCTFail("a route must read as “cannot tell”, got \(presence)")
        }
        XCTAssertEqual(presence.word, "NOT REPORTED")
        XCTAssertEqual(presence.health, .notReported,
                       "not knowing is not a fault — but it is not health either")

        let detail = PadReading.detail(presence, route: document.tablet, now: now)
        XCTAssertTrue(detail.contains("open door"),
                      "the owner is told exactly what the green thing means: \(detail)")
    }

    func testNoRouteAtAllIsItsOwnAnswer() throws {
        let document = try status(Fixture.noRouteStatus)
        let presence = PadReading.read(document, now: now)
        guard case .noRoute = presence else { return XCTFail("expected noRoute, got \(presence)") }
        XCTAssertEqual(presence.health, .bad)
        XCTAssertEqual(presence.word, "NO ROUTE")
    }

    // MARK: - A real heartbeat

    func testAFreshCheckInIsConnected() throws {
        let document = try withPad(seenAt: now.timeIntervalSince1970 - 12)
        let presence = PadReading.read(document, now: now)
        XCTAssertTrue(presence.isConnected)
        XCTAssertEqual(presence.health, .ok)
        let detail = PadReading.detail(presence, route: document.tablet, now: now)
        XCTAssertTrue(detail.contains("SM-T290"), detail)
        XCTAssertTrue(detail.contains("ago"), "§5 asks for last seen: \(detail)")
    }

    func testACheckInFromFourMinutesAgoIsIdleNotConnected() throws {
        let document = try withPad(seenAt: now.timeIntervalSince1970 - 240)
        let presence = PadReading.read(document, now: now)
        XCTAssertFalse(presence.isConnected)
        XCTAssertEqual(presence.word, "IDLE")
        XCTAssertTrue(PadReading.detail(presence, route: document.tablet, now: now).contains("4m ago"))
    }

    func testACheckInFromYesterdayIsDisconnectedAndSaysWhen() throws {
        let document = try withPad(seenAt: now.timeIntervalSince1970 - 86_400)
        let presence = PadReading.read(document, now: now)
        XCTAssertEqual(presence.word, "DISCONNECTED")
        XCTAssertEqual(presence.health, .bad)
        let detail = PadReading.detail(presence, route: document.tablet, now: now)
        XCTAssertTrue(detail.contains("24.0h ago"), detail)
        XCTAssertTrue(detail.lowercased().contains("wake"), "say what to do: \(detail)")
    }

    func testARouteThatHasNeverBeenUsed() throws {
        let document = try withPad(seenAt: nil)
        let presence = PadReading.read(document, now: now)
        XCTAssertEqual(presence.word, "NEVER CONNECTED")
        XCTAssertTrue(PadReading.detail(presence, route: document.tablet, now: now)
            .contains("Install CROOKS Pad"))
    }

    func testTheBoundaryIsWhereItSaysItIs() throws {
        let justInside = try withPad(seenAt: now.timeIntervalSince1970 - (PadReading.connected - 1))
        XCTAssertTrue(PadReading.read(justInside, now: now).isConnected)
        let justOutside = try withPad(seenAt: now.timeIntervalSince1970 - (PadReading.connected + 1))
        XCTAssertFalse(PadReading.read(justOutside, now: now).isConnected)
    }

    func testAClockThatRanBackwardsDoesNotLeaveThePadConnectedForever() throws {
        // The Mac wakes from sleep and re-syncs its clock; a heartbeat can end up in the
        // future. Subtracting would give a negative age, which is inside every window, and the
        // pad would read CONNECTED from then until the app was restarted.
        let document = try withPad(seenAt: now.timeIntervalSince1970 + 3600)
        let presence = PadReading.read(document, now: now)
        XCTAssertTrue(presence.isConnected, "a future stamp is clamped to now, which IS connected")
        let later = PadReading.read(document, now: now.addingTimeInterval(7200))
        XCTAssertFalse(later.isConnected, "and an hour after that stamp it is not")
    }

    // MARK: - What the first viewport ends up with

    func testTheDashboardNeverShowsAGreenPadWithoutAHeartbeat() throws {
        let document = try status(Fixture.onlineStatus)
        var machine = LifecycleMachine()
        machine.observe(.status(document), at: now)
        let dashboard = DashboardBuilder.build(
            DashboardInput(status: document, machine: machine, now: now))
        XCTAssertEqual(dashboard.pad.health, .notReported)
        XCTAssertFalse(dashboard.pad.presence.isConnected)
        XCTAssertEqual(dashboard.pad.address, "https://crooks-mini.tail1234.ts.net/",
                       "the address is still shown — it is real, it is just not a connection")
    }
}
