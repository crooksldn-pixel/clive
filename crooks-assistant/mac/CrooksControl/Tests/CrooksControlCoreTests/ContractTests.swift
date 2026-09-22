import XCTest
@testable import CrooksControlCore

/// Decoding, and what happens when the two sides do not agree.
final class ContractTests: XCTestCase {

    func decode<T: Decodable>(_ type: T.Type, _ data: Data, file: StaticString = #filePath, line: UInt = #line) throws -> T {
        try Contract.decoder.decode(type, from: data)
    }

    // MARK: - The version check

    func testTheVersionIsCheckedBeforeTheDocumentIsDecoded() throws {
        // A document from a newer script, with two fields moved to shapes this build does not
        // expect: `state` is now an object, `rows` is now a string.
        let fromTheFuture = Data(#"{"contract": 9, "state": {"colour": "GREEN"}, "rows": "moved"}"#.utf8)
        XCTAssertEqual(Contract.check(fromTheFuture), .scriptIsNewer(9))

        // The decode does NOT throw — every field here is read leniently on purpose, so that
        // one added field in Python cannot blank the whole app. What it produces instead is a
        // document with nothing in it: an unrecognised colour and no rows. Drawn, that is a
        // blank panel with no explanation, which is exactly why the version has to be checked
        // FIRST and the owner shown "build the app again" instead.
        //
        // The first version of this app checked `contract` AFTER decoding, which meant a
        // moved field surfaced as "answered something I could not read" — a dead end — rather
        // than as the one-line fix it actually is.
        let drawnAnyway = try decode(StatusDocument.self, fromTheFuture)
        XCTAssertEqual(drawnAnyway.colour, .unknown)
        XCTAssertTrue(drawnAnyway.rows.isEmpty)
        XCTAssertFalse(drawnAnyway.backendAnswering)
    }

    func testAnOlderScriptIsNamedAsOlder() {
        XCTAssertEqual(Contract.check(Data(#"{"contract": 0}"#.utf8)), .scriptIsOlder(0))
    }

    func testSomethingThatIsNotADocumentAtAll() {
        XCTAssertEqual(Contract.check(Data("Traceback (most recent call last):".utf8)), .notADocument)
        XCTAssertEqual(Contract.check(Data(#"{"error": "no"}"#.utf8)), .notADocument)
    }

    func testTheRealDocumentPasses() {
        XCTAssertEqual(Contract.check(Fixture.onlineStatus), .understood)
        XCTAssertEqual(Contract.check(Fixture.actions), .understood)
        XCTAssertEqual(Contract.check(Fixture.applySucceeded), .understood)
    }

    func testEveryMismatchGivesTheOwnerSomethingToDo() {
        for verdict in [ContractVerdict.scriptIsNewer(9), .scriptIsOlder(0), .notADocument] {
            let sentence = verdict.sentence ?? ""
            XCTAssertFalse(sentence.isEmpty, "\(verdict) must say something")
            // "decode", "schema" and "JSON" are words about the machine, not about the shop.
            for jargon in ["decode", "schema", "JSON", "keyNotFound", "typeMismatch"] {
                XCTAssertFalse(sentence.lowercased().contains(jargon.lowercased()),
                               "\(verdict) says “\(jargon)”: \(sentence)")
            }
        }
        XCTAssertNil(ContractVerdict.understood.sentence)
    }

    // MARK: - Decoding a real status document

    func testDecodingTheOfflineDocumentThisMachineActuallyProduced() throws {
        let status = try decode(StatusDocument.self, Fixture.offlineStatus)
        XCTAssertEqual(status.envelope.contract, 1)
        XCTAssertEqual(status.envelope.command, "status")
        XCTAssertEqual(status.colour, .red)
        XCTAssertEqual(status.headline, "CROOKS — Offline")
        XCTAssertEqual(status.port, 8000)
        XCTAssertFalse(status.backendAnswering)
        XCTAssertEqual(status.row("online")?.health, .bad)
        XCTAssertEqual(status.issues, ["the assistant is not answering"])
        XCTAssertFalse(status.rows.isEmpty)
    }

    func testDecodingTheOnlineDocument() throws {
        let status = try decode(StatusDocument.self, Fixture.onlineStatus)
        XCTAssertEqual(status.colour, .green)
        XCTAssertTrue(status.backendAnswering)
        XCTAssertEqual(status.row("claude")?.health, .ok)
        XCTAssertEqual(status.row("shopify")?.health, .ok)
        XCTAssertEqual(status.tablet.host, "crooks-mini.tail1234.ts.net")
        XCTAssertTrue(status.mutation.isReady, "three READY families means changes can run")
        XCTAssertEqual(status.build.current?.branch, "main")
        XCTAssertEqual(status.build.current?.build, "2026.09.12+2b25230")
        XCTAssertFalse(status.testSession.active)
    }

    func testDecodingTheDegradedAndRecordingDocuments() throws {
        let degraded = try decode(StatusDocument.self, Fixture.degradedStatus)
        XCTAssertEqual(degraded.colour, .amber)
        XCTAssertEqual(degraded.row("gmail")?.health, .bad)
        XCTAssertTrue(degraded.issues.isEmpty, "Gmail is not one of the three essentials")
        XCTAssertFalse(degraded.degraded.isEmpty)
        XCTAssertTrue(degraded.backendAnswering)

        let recording = try decode(StatusDocument.self, Fixture.recordingStatus)
        XCTAssertEqual(recording.colour, .blue)
        XCTAssertTrue(recording.testSession.active)
        XCTAssertEqual(recording.testSession.id, "2026-09-12-shopfloor")
        XCTAssertEqual(recording.testSession.name, "Saturday shop floor")
    }

    func testAnEssentialBeingDownIsStillAnAnsweringBackend() throws {
        // RED, but the backend IS up — it is Claude that is down. The difference decides
        // whether the app offers START (wrong: it is running) or RESTART (right).
        let status = try decode(StatusDocument.self, Fixture.essentialDownStatus)
        XCTAssertEqual(status.colour, .red)
        XCTAssertTrue(status.backendAnswering,
                      "the online row says it is answering, so RED here means a subsystem, not the process")
        XCTAssertEqual(status.issues, ["claude"])
    }

    // MARK: - Tolerance

    func testAFieldTheScriptAddsLaterDoesNotBlankTheApp() throws {
        // Workstream A will add fields to this document. The app has to keep drawing.
        var raw = try XCTUnwrap(String(data: Fixture.onlineStatus, encoding: .utf8))
        raw = raw.replacingOccurrences(
            of: "\"port\": 8000",
            with: "\"port\": 8000,\n  \"something_nobody_has_written_yet\": {\"deep\": [1, 2, 3]}"
        )
        let status = try decode(StatusDocument.self, Data(raw.utf8))
        XCTAssertTrue(status.backendAnswering)
        XCTAssertEqual(status.colour, .green)
    }

    func testAMissingSectionLeavesAnEmptySectionNotAFailedDecode() throws {
        let minimal = Data(#"{"contract": 1, "command": "status", "state": "GREEN"}"#.utf8)
        let status = try decode(StatusDocument.self, minimal)
        XCTAssertEqual(status.colour, .green)
        XCTAssertTrue(status.rows.isEmpty)
        XCTAssertEqual(status.rollback, RollbackDecision())
        XCTAssertNil(status.port)
        XCTAssertNil(status.service)
        XCTAssertNil(status.pad)
    }

    func testADocumentWithNoContractNumberIsRefused() {
        // The one thing that is NOT tolerated. Without a version this is not the control
        // script's document, and drawing it would be drawing whatever answered the port.
        XCTAssertThrowsError(try Contract.decoder.decode(
            StatusDocument.self, from: Data(#"{"command": "status", "state": "GREEN"}"#.utf8)))
    }

    func testAColourNobodyHasInventedYetIsNotDrawnAsHealth() throws {
        let raw = Data(#"{"contract": 1, "command": "status", "state": "MAUVE"}"#.utf8)
        let status = try decode(StatusDocument.self, raw)
        XCTAssertEqual(status.colour, .unknown)
        XCTAssertFalse(status.backendAnswering, "an unrecognised colour must never read as well")
    }

    // MARK: - The actions document

    func testDecodingTheActionsDocument() throws {
        let document = try decode(ActionsDocument.self, Fixture.actions)
        XCTAssertEqual(document.envelope.contract, 1)
        XCTAssertEqual(document.actions.count, 13)
        let update = try XCTUnwrap(document.actions.first { $0.id == "update" })
        XCTAssertTrue(update.confirm)
        XCTAssertTrue(update.needsPlan)
        XCTAssertEqual(update.kind, "control")
        XCTAssertEqual(update.group, "update")
        XCTAssertEqual(update.command?.last, "--yes")
        let logs = try XCTUnwrap(document.actions.first { $0.id == "logs" })
        XCTAssertEqual(logs.kind, "open_path")
        XCTAssertNotNil(logs.path)
    }
}
