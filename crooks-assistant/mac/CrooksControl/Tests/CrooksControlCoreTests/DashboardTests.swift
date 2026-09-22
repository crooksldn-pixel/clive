import XCTest
@testable import CrooksControlCore

/// The first viewport, and what Developer Mode is allowed to add to it.
final class DashboardTests: XCTestCase {

    let now = Date(timeIntervalSince1970: 1_789_000_000)

    func status(_ data: Data) throws -> StatusDocument {
        try Contract.decoder.decode(StatusDocument.self, from: data)
    }

    func build(_ data: Data, developerMode: Bool = false, failure: ControlFailure? = nil,
               outcome: UpdateDocument? = nil) throws -> Dashboard {
        let document = try status(data)
        var machine = LifecycleMachine()
        machine.observe(.status(document), at: now)
        let actions = try Contract.decoder.decode(ActionsDocument.self, from: Fixture.actions).actions
        return DashboardBuilder.build(DashboardInput(
            status: document, actions: actions, machine: machine, outcome: outcome,
            failure: failure, developerMode: developerMode, now: now))
    }

    // MARK: - The five questions §5 says the first viewport answers

    func testTheFirstViewportAnswersAllFiveQuestions() throws {
        let dashboard = try build(Fixture.recordingStatus)

        // 1. Is CROOKS OS running?
        XCTAssertEqual(dashboard.headline, "CROOKS OS IS ONLINE")
        XCTAssertEqual(dashboard.lifecycle, .online)
        // 2. Is the tablet connected?
        XCTAssertFalse(dashboard.pad.word.isEmpty)
        // 3. Are services healthy?
        XCTAssertEqual(dashboard.services.map(\.key),
                       ["backend", "speech", "claude", "speaks", "shopify", "gmail", "tablet"])
        // 4. What version?
        XCTAssertEqual(dashboard.identity.checkout, "main · 2b25230a5a")
        XCTAssertEqual(dashboard.identity.runningBuild, "2026.09.12+2b25230")
        // 5. Is a test session active?
        XCTAssertTrue(dashboard.session.active)
        XCTAssertEqual(dashboard.session.name, "Saturday shop floor")
    }

    func testTheBigWordIsTheStateAndNothingElse() throws {
        XCTAssertEqual(try build(Fixture.offlineStatus).headline, "CROOKS OS IS OFFLINE")
        XCTAssertEqual(try build(Fixture.onlineStatus).headline, "CROOKS OS IS ONLINE")
        XCTAssertEqual(try build(Fixture.degradedStatus).headline, "CROOKS OS IS ONLINE",
                       "degraded is still running; the sentence under it carries the bad news")
    }

    func testEveryHeadlineIsASentenceAndNotATemplateWithAWordDroppedIntoIt() {
        // "CROOKS OS IS " + the state's word gives "CROOKS OS IS ERROR", which is the sort of
        // thing that tells a man exactly what kind of software he is looking at.
        for phase in Lifecycle.allCases {
            let headline = phase.headline
            XCTAssertFalse(headline.hasSuffix(" IS ERROR"), headline)
            XCTAssertFalse(headline.hasSuffix(" IS CHECKING"), headline)
            XCTAssertFalse(headline.isEmpty)
            XCTAssertEqual(headline, headline.uppercased(), "the headline is set in caps: \(headline)")
        }
        XCTAssertEqual(Lifecycle.error.headline, "CROOKS OS HAS A PROBLEM")
        XCTAssertEqual(Lifecycle.error.word, "ERROR", "the badge is still one word")
    }

    func testTheColourFollowsTheSameOrderTheControlScriptUses() throws {
        XCTAssertEqual(try build(Fixture.onlineStatus).accent, .online)
        XCTAssertEqual(try build(Fixture.degradedStatus).accent, .caution)
        XCTAssertEqual(try build(Fixture.recordingStatus).accent, .testing)
        XCTAssertEqual(try build(Fixture.essentialDownStatus).accent, .danger,
                       "an essential down outranks a test session, as it does in control.py")
        XCTAssertEqual(try build(Fixture.offlineStatus).accent, .idle)
    }

    // MARK: - Services

    func testAServiceTheDocumentDoesNotMentionIsNotDrawnAsWell() throws {
        // A newer backend stops reporting Gmail. The tile must say so, not go green and not
        // vanish, because a missing subsystem drawn like a working one is the whole failure
        // this rule exists to prevent.
        var raw = try XCTUnwrap(String(data: Fixture.onlineStatus, encoding: .utf8))
        let start = try XCTUnwrap(raw.range(of: "    {\n      \"key\": \"gmail\""))
        let end = try XCTUnwrap(raw.range(of: "},\n", range: start.upperBound..<raw.endIndex))
        raw.replaceSubrange(start.lowerBound..<end.upperBound, with: "")

        let document = try status(Data(raw.utf8))
        XCTAssertNil(document.row("gmail"), "the edit landed")
        let dashboard = DashboardBuilder.build(DashboardInput(status: document, now: now))
        let gmail = try XCTUnwrap(dashboard.services.first { $0.key == "gmail" })
        XCTAssertEqual(gmail.health, .notReported)
        XCTAssertNotEqual(gmail.health, .ok)
        XCTAssertEqual(gmail.value, "not reported")
    }

    func testWithNothingReadAtAllEverythingSaysSoRatherThanLookingWell() {
        let dashboard = DashboardBuilder.build(DashboardInput(now: now))
        XCTAssertEqual(dashboard.lifecycle, .unknown)
        XCTAssertTrue(dashboard.services.allSatisfy { $0.health == .notReported })
        XCTAssertEqual(dashboard.pad.health, .notReported)
        XCTAssertEqual(dashboard.identity.checkout, "not read")
        XCTAssertEqual(dashboard.identity.runningBuild, "not running")
    }

    func testTheThreeEssentialsAreMarkedAsSuch() throws {
        let dashboard = try build(Fixture.onlineStatus)
        let essential = Set(dashboard.services.filter(\.essential).map(\.key))
        XCTAssertEqual(essential, ["backend", "speech", "claude", "shopify"],
                       "control.py's ESSENTIAL, plus the backend itself")
    }

    // MARK: - Uptime

    func testUptimeSaysNotReportedRatherThanGuessingFromProse() throws {
        // The `online` row's detail carries "up 2.1h" as English. Reading a number back out of
        // an English sentence works until the sentence changes, and then shows a wrong figure
        // with no warning. So: the number, or the words "not reported".
        let dashboard = try build(Fixture.onlineStatus)
        XCTAssertNil(try status(Fixture.onlineStatus).uptimeS)
        XCTAssertEqual(dashboard.identity.uptime, "not reported")
        XCTAssertTrue(try XCTUnwrap(status(Fixture.onlineStatus).row("online")).detail.contains("up "),
                      "the prose IS there — it is just not parsed")
    }

    func testUptimeIsShownWhenTheDocumentCarriesANumber() throws {
        var raw = try XCTUnwrap(String(data: Fixture.onlineStatus, encoding: .utf8))
        raw = raw.replacingOccurrences(of: "\"port\": 8000", with: "\"port\": 8000,\n  \"uptime_s\": 7412")
        let document = try status(Data(raw.utf8))
        let dashboard = DashboardBuilder.build(DashboardInput(status: document, now: now))
        XCTAssertEqual(dashboard.identity.uptime, "up 2.1h")
    }

    // MARK: - One notice, never five

    func testAtMostOneNoticeIsEverShown() throws {
        // This document has three things worth saying at once: Gmail is down, one capability
        // family is read-only, and the Phase 5 script has no start or stop. §5.8 says one.
        //
        // There is exactly one `notice` on the type, so this is really a test of the ordering,
        // and the ordering is a product judgement: CROOKS OS is RUNNING here, so the thing the
        // owner can act on now — it cannot make changes — beats a button he does not need this
        // minute. The reverse order was written first and was wrong for exactly that reason.
        let notice = try XCTUnwrap(try build(Fixture.degradedStatus).notice)
        XCTAssertTrue(notice.text.contains("cannot make changes"), notice.text)
        XCTAssertEqual(notice.tone, .caution)
    }

    func testAFailureOutranksEverything() throws {
        let dashboard = try build(Fixture.degradedStatus, failure: .noCheckout)
        XCTAssertEqual(dashboard.notice?.tone, .danger)
        XCTAssertEqual(dashboard.notice?.text, ControlFailure.noCheckout.sentence)
    }

    func testAnUpdateThatLeftADeadBuildSaysSoAndPointsAtRollBack() throws {
        let outcome = try Contract.decoder.decode(UpdateDocument.self, from: Fixture.applyMovedButUnhealthy)
        let dashboard = try build(Fixture.offlineStatus, outcome: outcome)
        let notice = try XCTUnwrap(dashboard.notice)
        XCTAssertEqual(notice.tone, .danger)
        XCTAssertEqual(notice.fix, "Press ROLL BACK to return to the last build that was known to work.")
        XCTAssertTrue(dashboard.update.verdict.isFailure)
    }

    func testARunningSystemWithAnEssentialDownIsCalledOut() throws {
        let dashboard = try build(Fixture.essentialDownStatus)
        let notice = try XCTUnwrap(dashboard.notice)
        XCTAssertEqual(notice.tone, .danger)
        XCTAssertTrue(notice.text.contains("claude"), notice.text)
        XCTAssertTrue(notice.text.contains("cannot do its job"), notice.text)
    }

    // MARK: - Developer Mode

    func testDeveloperModeIsOffAndItsContentsAreNotSmuggledIntoTheFirstViewport() throws {
        let plain = try build(Fixture.onlineStatus, developerMode: false)
        XCTAssertNil(plain.developer)

        // The argv behind each button is on the button — the app has to run it — but no part
        // of it may appear in anything the first viewport DRAWS.
        for text in plain.everyVisibleString {
            XCTAssertFalse(text.contains("/.venv/bin/python"), "a command line is on screen: \(text)")
            XCTAssertFalse(text.contains("scripts/control.py"), "a script path is on screen: \(text)")
            XCTAssertFalse(text.contains("--yes"), "an argument is on screen: \(text)")
        }
    }

    func testDeveloperModeAddsTheDetailAndNothingIsHeldBackFromIt() throws {
        let developer = try XCTUnwrap(try build(Fixture.onlineStatus, developerMode: true,
                                                failure: .exited(code: 127, stderr: "command not found")).developer)
        XCTAssertEqual(developer.contract, 1)
        XCTAssertEqual(developer.port, 8000)
        XCTAssertEqual(developer.rows.count, 14, "every row the script sent, not the seven pips")
        XCTAssertTrue(developer.commands.contains { $0.0 == "update" && $0.1.contains("--yes") })
        XCTAssertTrue(try XCTUnwrap(developer.lastFailure).contains("127"),
                      "§5.7: the detail is here, in full, where it belongs")
    }

    // MARK: - Nothing credential-shaped reaches the screen

    func testNoSecretSurvivesIntoAnythingTheOwnerSees() throws {
        // Defence in depth. control.py redacts everything it prints and has its own test for
        // it; this asserts that if one ever DID arrive — a health detail quoting a header, a
        // button's stderr, a field added later that redact() has not been taught about — the
        // app does not put it on the screen.
        let token = "shpat_" + String(repeating: "9f8e7d6c", count: 4)
        var raw = try XCTUnwrap(String(data: Fixture.onlineStatus, encoding: .utf8))
        raw = raw.replacingOccurrences(of: "crooks-clothing.myshopify.com",
                                       with: "crooks-clothing.myshopify.com (\(token))")
        raw = raw.replacingOccurrences(of: "everything answering, changes ready, tablet routed",
                                       with: "everything answering; ANTHROPIC_API_KEY=sk-ant-api03-LEAKED123456")
        let document = try status(Data(raw.utf8))
        var machine = LifecycleMachine()
        machine.observe(.status(document), at: now)
        let actions = try Contract.decoder.decode(ActionsDocument.self, from: Fixture.actions).actions
        let dashboard = DashboardBuilder.build(DashboardInput(
            status: document, actions: actions, machine: machine,
            failure: .exited(code: 1, stderr: "rejected: \(token)"), now: now))

        for text in dashboard.everyVisibleString {
            XCTAssertFalse(text.contains(token), "a Shopify token is on screen: \(text)")
            XCTAssertFalse(text.contains("sk-ant-api03-LEAKED123456"), "an API key is on screen: \(text)")
            XCTAssertFalse(Redaction.looksLikeASecret(text), "something credential-shaped: \(text)")
        }
        XCTAssertTrue(dashboard.everyVisibleString.contains { $0.contains(Redaction.mask) },
                      "the poison did reach the dashboard — it was masked, not dropped")
    }

    func testTheVisibleStringListIsNotQuietlyEmpty() throws {
        // The test above would pass trivially if everyVisibleString returned nothing, so this
        // one checks the thing that makes it meaningful.
        let dashboard = try build(Fixture.onlineStatus)
        XCTAssertGreaterThan(dashboard.everyVisibleString.count, 40)
        XCTAssertTrue(dashboard.everyVisibleString.contains("CROOKS OS IS ONLINE"))
        XCTAssertTrue(dashboard.everyVisibleString.contains { $0.contains("Check for update") })
    }
}
