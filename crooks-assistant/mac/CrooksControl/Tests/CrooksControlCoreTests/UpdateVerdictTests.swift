import XCTest
@testable import CrooksControlCore

/// "update completed vs new version actually healthy" (§26).
final class UpdateVerdictTests: XCTestCase {

    func document(_ data: Data) throws -> UpdateDocument {
        try Contract.decoder.decode(UpdateDocument.self, from: data)
    }

    // MARK: - THE ONE THAT MATTERS

    func testAnUpdateThatMovedTheBuildAndDidNotComeBackIsAFailure() throws {
        let applied = try document(Fixture.applyMovedButUnhealthy)

        // First, what the script actually said — asserted here so that if control.py ever
        // changes its mind about these three fields, this test says so instead of quietly
        // passing against a document that no longer exists.
        XCTAssertTrue(applied.envelope.ok, "the script reports ok:true — it did what it was asked")
        XCTAssertEqual(applied.next, "verify_by_hand")
        XCTAssertNil(applied.markedGood, "and it refused to record a build it could not read back")
        XCTAssertEqual(applied.update?.moved, true)
        XCTAssertEqual(applied.update?.verified, false)

        let verdict = UpdateJudge.judge(applied)
        XCTAssertTrue(verdict.isFailure, "got \(verdict)")
        XCTAssertTrue(verdict.rollbackExpected,
                      "the build moved and did not come up — going back is the answer, not trying again")
        XCTAssertEqual(verdict.headline, "Update failed")
        XCTAssertTrue(verdict.sentence.contains("has not answered since"), verdict.sentence)
        XCTAssertTrue(verdict.sentence.contains("9f31c22b17"),
                      "name the build that is on the Mac: \(verdict.sentence)")
    }

    func testTheFailureIsNotDecidedByTheExitCodeOrTheOkFlag() throws {
        // Belt and braces. `ok` is true in the fixture above and false in the one below, and
        // the verdicts do not follow it: the first is a failure, the second is a refusal.
        let unhealthy = try document(Fixture.applyMovedButUnhealthy)
        let blocked = try document(Fixture.applyBlocked)
        XCTAssertTrue(unhealthy.envelope.ok)
        XCTAssertFalse(blocked.envelope.ok)
        XCTAssertTrue(UpdateJudge.judge(unhealthy).isFailure)
        if case .refused = UpdateJudge.judge(blocked) {} else {
            XCTFail("a run that moved nothing is a refusal: \(UpdateJudge.judge(blocked))")
        }
        XCTAssertFalse(UpdateJudge.judge(blocked).rollbackExpected,
                       "nothing moved, so there is nothing to go back from")
    }

    func testAnUpdateThatCameBackHealthyAndWasRecordedIsSuccess() throws {
        let applied = try document(Fixture.applySucceeded)
        XCTAssertEqual(applied.next, "done")
        XCTAssertNotNil(applied.markedGood)
        let verdict = UpdateJudge.judge(applied)
        guard case .installed(let build, let from) = verdict else {
            return XCTFail("expected installed, got \(verdict)")
        }
        XCTAssertEqual(build, "9f31c22b17")
        XCTAssertEqual(from, "2b25230a5a",
                       "and where it came from: update.py reads HEAD before the pull and never "
                        + "rewrites the sha, which is what makes that sentence possible")
        XCTAssertFalse(verdict.isFailure)
        XCTAssertTrue(verdict.sentence.contains("answering"), verdict.sentence)
        XCTAssertTrue(verdict.sentence.contains("It was on 2b25230a5a."), verdict.sentence)
    }

    func testVerifiedWithoutARecordIsStillAFailure() throws {
        // The narrower version of the same trap: /health answered, but the script did not
        // record the build as known-good. It only declines to record when something about the
        // verification did not satisfy it, and a build nobody would roll back TO is not a
        // build to call updated.
        var raw = try XCTUnwrap(String(data: Fixture.applySucceeded, encoding: .utf8))
        raw = raw.replacingOccurrences(of: "\"next\": \"done\"", with: "\"next\": \"verify_by_hand\"")
        let start = try XCTUnwrap(raw.range(of: "\"marked_good\": {"))
        let end = try XCTUnwrap(raw.range(of: "}", range: start.upperBound..<raw.endIndex))
        raw.replaceSubrange(start.lowerBound..<end.upperBound, with: "\"marked_good\": null")

        let applied = try document(Data(raw.utf8))
        XCTAssertNil(applied.markedGood)
        XCTAssertEqual(applied.update?.verified, true)
        let verdict = UpdateJudge.judge(applied)
        XCTAssertTrue(verdict.isFailure, "got \(verdict)")
        XCTAssertTrue(verdict.rollbackExpected)
        XCTAssertTrue(verdict.sentence.contains("NOT been recorded"), verdict.sentence)
    }

    func testAFailedStageAfterAMoveIsAFailureEvenWithEverythingElseGreen() throws {
        var raw = try XCTUnwrap(String(data: Fixture.applySucceeded, encoding: .utf8))
        raw = raw.replacingOccurrences(
            of: "\"stage\": \"tablet\",\n      \"state\": \"ok\"",
            with: "\"stage\": \"tablet\",\n      \"state\": \"fail\"")
        let applied = try document(Data(raw.utf8))
        XCTAssertTrue(applied.allStages.contains { $0.failed }, "the edit landed")
        let verdict = UpdateJudge.judge(applied)
        XCTAssertTrue(verdict.isFailure, "got \(verdict)")
        XCTAssertTrue(verdict.sentence.contains("tablet"), verdict.sentence)
    }

    // MARK: - Checking, which risks nothing

    func testACheckThatFoundSomethingDescribesItBeforeAnythingMoves() throws {
        let plan = try document(Fixture.planAvailable)
        let verdict = UpdateJudge.judgePlan(plan)
        guard case .available(let offer, _) = verdict else {
            return XCTFail("expected available, got \(verdict)")
        }
        XCTAssertEqual(offer.from, "2b25230a5a")
        XCTAssertEqual(offer.to, "9f31c22b17")
        XCTAssertEqual(offer.commits, 3)
        XCTAssertEqual(offer.files, 17)
        XCTAssertTrue(offer.fastForward)
        XCTAssertEqual(offer.dependenciesChange, ["requirements.txt"])
        // Both SHAs in the sentence: §5.3 says the owner sees them before he decides.
        XCTAssertTrue(verdict.sentence.contains("2b25230a5a → 9f31c22b17"), verdict.sentence)
        XCTAssertTrue(verdict.sentence.contains("3 commits"), verdict.sentence)
    }

    func testACheckThatFoundNothing() throws {
        let verdict = UpdateJudge.judgePlan(try document(Fixture.planUpToDate))
        guard case .upToDate = verdict else { return XCTFail("got \(verdict)") }
        XCTAssertEqual(verdict.headline, "Up to date")
    }

    func testUnsavedWorkIsARefusalThatSaysNothingWasThrownAway() throws {
        let verdict = UpdateJudge.judgePlan(try document(Fixture.planBlockedDirty))
        guard case .refused(let reason) = verdict else { return XCTFail("got \(verdict)") }
        XCTAssertTrue(reason.lowercased().contains("thrown away"),
                      "the owner's first fear is losing work: \(reason)")
        XCTAssertFalse(verdict.isFailure)
    }

    func testSingularAndPluralAreWrittenOut() throws {
        var raw = try XCTUnwrap(String(data: Fixture.planAvailable, encoding: .utf8))
        raw = raw.replacingOccurrences(of: "\"behind\": 3", with: "\"behind\": 1")
        raw = raw.replacingOccurrences(of: "\"changed_files\": 17", with: "\"changed_files\": 1")
        let verdict = UpdateJudge.judgePlan(try document(Data(raw.utf8)))
        XCTAssertTrue(verdict.sentence.contains("1 commit,"), verdict.sentence)
        XCTAssertTrue(verdict.sentence.contains("1 file."), verdict.sentence)
    }

    // MARK: - Nothing asked yet

    func testBeforeAnythingIsAskedTheOwnerIsToldWhatPressingCheckWouldDo() {
        let verdict = UpdateVerdict.notChecked
        XCTAssertTrue(verdict.sentence.contains("CHECK FOR UPDATE"), verdict.sentence)
        XCTAssertTrue(verdict.sentence.lowercased().contains("nothing moves"),
                      "the promise that checking is safe: \(verdict.sentence)")
    }

    // MARK: - Routing

    func testAPlanIsNeverJudgedWithApplysRules() throws {
        // judge() routes on the document's own command, so a caller cannot pass a plan to the
        // harsher path (or, worse, an apply to the gentler one) by mistake.
        let plan = try document(Fixture.planAvailable)
        XCTAssertEqual(plan.envelope.command, "plan")
        XCTAssertEqual(UpdateJudge.judge(plan), UpdateJudge.judgePlan(plan))
        let applied = try document(Fixture.applyMovedButUnhealthy)
        XCTAssertEqual(applied.envelope.command, "apply")
        XCTAssertEqual(UpdateJudge.judge(applied), UpdateJudge.judgeApply(applied))
    }
}
