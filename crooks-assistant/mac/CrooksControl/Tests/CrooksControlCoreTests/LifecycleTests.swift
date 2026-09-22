import XCTest
@testable import CrooksControlCore

/// The state machine: offline → starting → online, and every way that can go wrong.
final class LifecycleTests: XCTestCase {

    let epoch = Date(timeIntervalSince1970: 1_789_000_000)

    func status(_ data: Data) throws -> StatusDocument {
        try Contract.decoder.decode(StatusDocument.self, from: data)
    }

    func at(_ seconds: TimeInterval) -> Date { epoch.addingTimeInterval(seconds) }

    // MARK: - The happy path

    func testOfflineThenStartingThenOnline() throws {
        var machine = LifecycleMachine()
        XCTAssertEqual(machine.phase, .unknown)

        machine.observe(.status(try status(Fixture.offlineStatus)), at: at(0))
        XCTAssertEqual(machine.phase, .offline)
        XCTAssertTrue(machine.explanation.lowercased().contains("start"),
                      "offline must say what to press: \(machine.explanation)")

        machine.intend(.start, at: at(1))
        XCTAssertEqual(machine.phase, .starting)

        // Three polls while it warms up. It is not online, and it is not an error either.
        for second in [4.0, 9.0, 20.0] {
            machine.observe(.status(try status(Fixture.offlineStatus)), at: at(second))
            XCTAssertEqual(machine.phase, .starting, "still starting at \(second)s")
        }

        machine.observe(.status(try status(Fixture.onlineStatus)), at: at(26))
        XCTAssertEqual(machine.phase, .online)
        XCTAssertEqual(machine.since, at(26), "the clock on ONLINE starts when it came up")
    }

    // MARK: - The lesson: a command exiting 0 is not a system being up

    func testAStartCommandThatSucceedsDoesNotMakeTheAppSayOnline() throws {
        // `launchctl kickstart` returns 0 the moment launchd accepts the job. If that were
        // allowed to mean ONLINE, the app would show green while the backend died in a loop.
        var machine = LifecycleMachine()
        machine.observe(.status(try status(Fixture.offlineStatus)), at: at(0))
        machine.intend(.start, at: at(1))

        machine.commandFinished(.start, failure: nil, at: at(2))
        XCTAssertEqual(machine.phase, .starting,
                       "the command succeeding is evidence about the command, not about CROOKS OS")

        // And still nothing but a real status document moves it.
        machine.observe(.status(try status(Fixture.offlineStatus)), at: at(3))
        XCTAssertEqual(machine.phase, .starting)
        machine.observe(.status(try status(Fixture.onlineStatus)), at: at(4))
        XCTAssertEqual(machine.phase, .online)
    }

    func testAProcessWithAPidThatIsNotAnsweringIsNotOnline() throws {
        // The forward-compatible `service` block, filled in the way a start script would fill
        // it half a second after kicking the job: managed, running, pid — and not healthy.
        let raw = Data(#"""
        {"contract": 1, "command": "status", "state": "RED", "headline": "CROOKS — Offline",
         "why": "nothing is answering on 127.0.0.1:8000",
         "rows": [{"key": "online", "label": "Online", "state": "bad", "value": "nothing answering", "detail": ""}],
         "service": {"state": "running", "managed": true, "pid": 4242, "healthy": false,
                     "detail": "launchd has it, it has not opened the port"}}
        """#.utf8)
        let document = try status(raw)
        XCTAssertEqual(document.service?.pid, 4242)
        XCTAssertFalse(document.backendAnswering, "a pid is not an answer")

        var machine = LifecycleMachine()
        machine.intend(.start, at: at(0))
        machine.observe(.status(document), at: at(5))
        XCTAssertEqual(machine.phase, .starting)
    }

    func testAServiceBlockThatSaysHealthyIsBelieved() throws {
        // The other direction: when a newer script does answer the question at the source,
        // the app uses that answer rather than inferring one from the rows.
        let raw = Data(#"""
        {"contract": 1, "command": "status", "state": "GREEN", "headline": "CROOKS — Online",
         "why": "everything answering", "rows": [],
         "service": {"state": "running", "managed": true, "pid": 4242, "healthy": true, "detail": "ok"}}
        """#.utf8)
        XCTAssertTrue(try status(raw).backendAnswering)
    }

    // MARK: - The lesson: a spinner that never resolves is a lie

    func testStartingGivesUpAndSaysSoRatherThanSpinningForever() throws {
        var machine = LifecycleMachine()
        machine.intend(.start, at: at(0))
        machine.observe(.status(try status(Fixture.offlineStatus)), at: at(119))
        XCTAssertEqual(machine.phase, .starting)

        machine.observe(.status(try status(Fixture.offlineStatus)), at: at(121))
        XCTAssertEqual(machine.phase, .error)
        XCTAssertTrue(machine.explanation.contains("did not come up"), machine.explanation)
        XCTAssertTrue(machine.explanation.lowercased().contains("logs"),
                      "an error the owner cannot act on is only a silence: \(machine.explanation)")
    }

    func testTheTimeoutAlsoFiresWhenThePollsStopComingBack() {
        // The poll can stop arriving — the machine slept, the script hung. The app's own clock
        // still has to resolve STARTING, or the window sits on a spinner until it is closed.
        var machine = LifecycleMachine()
        machine.intend(.start, at: at(0))
        machine.tick(at: at(60))
        XCTAssertEqual(machine.phase, .starting)
        machine.tick(at: at(200))
        XCTAssertEqual(machine.phase, .error)
    }

    func testAStartThatCouldNotBeRunIsAnErrorImmediately() {
        var machine = LifecycleMachine()
        machine.intend(.start, at: at(0))
        machine.commandFinished(.start, failure: .exited(code: 127, stderr: "sh: crooks-control: command not found"),
                                at: at(1))
        XCTAssertEqual(machine.phase, .error)
        XCTAssertFalse(machine.explanation.contains("127"), machine.explanation)
    }

    // MARK: - Stopping

    func testOnlineThenStoppingThenOffline() throws {
        var machine = LifecycleMachine()
        machine.observe(.status(try status(Fixture.onlineStatus)), at: at(0))
        XCTAssertEqual(machine.phase, .online)

        machine.intend(.stop, at: at(1))
        XCTAssertEqual(machine.phase, .stopping)

        machine.observe(.status(try status(Fixture.onlineStatus)), at: at(3))
        XCTAssertEqual(machine.phase, .stopping, "it is still answering, so it has not stopped")

        machine.observe(.status(try status(Fixture.offlineStatus)), at: at(6))
        XCTAssertEqual(machine.phase, .offline)
    }

    func testSomethingThatWillNotStopBecomesAnErrorRatherThanOffline() throws {
        var machine = LifecycleMachine()
        machine.observe(.status(try status(Fixture.onlineStatus)), at: at(0))
        machine.intend(.stop, at: at(1))
        machine.observe(.status(try status(Fixture.onlineStatus)), at: at(60))
        XCTAssertEqual(machine.phase, .error)
        XCTAssertTrue(machine.explanation.contains("still answering"), machine.explanation)
    }

    func testARestartIsWaitedOnAsAStart() throws {
        var machine = LifecycleMachine()
        machine.observe(.status(try status(Fixture.onlineStatus)), at: at(0))
        machine.intend(.restart, at: at(1))
        XCTAssertEqual(machine.phase, .starting)
        XCTAssertTrue(machine.explanation.contains("Restarting"), machine.explanation)
        machine.observe(.status(try status(Fixture.onlineStatus)), at: at(9))
        XCTAssertEqual(machine.phase, .online)
    }

    // MARK: - An error that explains itself does not get quietly overwritten

    func testAFailedStartStaysOnScreenInsteadOfTurningBackIntoAPlainOffline() throws {
        // Press START, watch it fail, and fifteen seconds later the poll comes back saying the
        // same thing the error already said: it is not running. Letting that overwrite the
        // error leaves the owner looking at OFFLINE with no idea why, so he presses START
        // again, and again.
        var machine = LifecycleMachine()
        machine.intend(.start, at: at(0))
        machine.commandFinished(.start, failure: .exited(code: 1, stderr: "Permission denied"), at: at(2))
        XCTAssertEqual(machine.phase, .error)
        let said = machine.explanation

        for second in [17.0, 32.0, 47.0] {
            machine.observe(.status(try status(Fixture.offlineStatus)), at: at(second))
            XCTAssertEqual(machine.phase, .error, "still an error at \(second)s")
            XCTAssertEqual(machine.explanation, said, "and still saying why")
        }

        // It clears the moment something actually changes.
        machine.observe(.status(try status(Fixture.onlineStatus)), at: at(60))
        XCTAssertEqual(machine.phase, .online)
        XCTAssertNil(machine.fault)
    }

    func testPressingStartAgainClearsTheError() throws {
        var machine = LifecycleMachine()
        machine.intend(.start, at: at(0))
        machine.commandFinished(.start, failure: .noPython(path: "/x/.venv/bin/python"), at: at(1))
        XCTAssertEqual(machine.phase, .error)
        machine.intend(.start, at: at(30))
        XCTAssertEqual(machine.phase, .starting, "the owner acted; the old failure is not the news")
        XCTAssertNil(machine.fault)
    }

    func testAnUnreachableScriptClearsAsSoonAsAnyDocumentComesBack() throws {
        // The other kind of error, and it must NOT be sticky: the problem was reaching CROOKS
        // OS, and a document coming back is proof that it is over — even a document that says
        // CROOKS OS is off.
        var machine = LifecycleMachine()
        machine.observe(.unreadable(.noCheckout), at: at(0))
        XCTAssertEqual(machine.phase, .error)
        XCTAssertEqual(machine.fault, .unreachable)
        machine.observe(.status(try status(Fixture.offlineStatus)), at: at(15))
        XCTAssertEqual(machine.phase, .offline)
        XCTAssertNil(machine.fault)
    }

    func testAStartThatTimedOutIsAlsoStickyAndDoesNotFlickerToOffline() throws {
        var machine = LifecycleMachine()
        machine.intend(.start, at: at(0))
        machine.observe(.status(try status(Fixture.offlineStatus)), at: at(130))
        XCTAssertEqual(machine.phase, .error)
        XCTAssertEqual(machine.fault, .didNotMove)
        machine.observe(.status(try status(Fixture.offlineStatus)), at: at(145))
        XCTAssertEqual(machine.phase, .error)
        XCTAssertTrue(machine.explanation.contains("did not come up"), machine.explanation)
    }

    // MARK: - The script itself failing is not the same as CROOKS OS being off

    func testAnUnreachableControlScriptIsAnErrorNotAnOffline() {
        var machine = LifecycleMachine()
        machine.observe(.unreadable(.noCheckout), at: at(0))
        XCTAssertEqual(machine.phase, .error,
                       "this is the Mac's problem, not CROOKS OS's, and OFFLINE would send the "
                        + "owner to press START, which cannot possibly work")
        XCTAssertFalse(machine.explanation.isEmpty)
    }

    // MARK: - What the line under the big word says

    func testOnlineWithATestSessionSaysWhatIsRecording() throws {
        var machine = LifecycleMachine()
        machine.observe(.status(try status(Fixture.recordingStatus)), at: at(0))
        XCTAssertEqual(machine.phase, .online)
        XCTAssertTrue(machine.explanation.contains("Saturday shop floor"), machine.explanation)
    }

    func testOnlineWithAnEssentialDownSaysWhichOne() throws {
        var machine = LifecycleMachine()
        machine.observe(.status(try status(Fixture.essentialDownStatus)), at: at(0))
        XCTAssertEqual(machine.phase, .online, "the process is up; it is Claude that is not")
        XCTAssertTrue(machine.explanation.lowercased().contains("claude"), machine.explanation)
    }

    // MARK: - Saying it once

    func testOneTransitionProducesOneLineNotFive() throws {
        var machine = LifecycleMachine()
        var announcer = TransitionAnnouncer()
        var said: [String] = []

        func poll(_ data: Data, _ seconds: TimeInterval) throws {
            machine.observe(.status(try status(data)), at: at(seconds))
            if let announcement = announcer.consider(machine) { said.append(announcement.text) }
        }

        try poll(Fixture.offlineStatus, 0)           // the first reading is not news
        machine.intend(.start, at: at(1))
        if let a = announcer.consider(machine) { said.append(a.text) }
        try poll(Fixture.offlineStatus, 5)
        try poll(Fixture.offlineStatus, 10)
        try poll(Fixture.offlineStatus, 15)
        try poll(Fixture.onlineStatus, 22)
        try poll(Fixture.onlineStatus, 37)           // still online: still not news
        try poll(Fixture.onlineStatus, 52)

        XCTAssertEqual(said, ["CROOKS OS is online."],
                       "§5.8: one state transition is enough. Got \(said)")
    }

    func testTheFirstReadingAfterLaunchIsNotAnnounced() throws {
        var machine = LifecycleMachine()
        var announcer = TransitionAnnouncer()
        machine.observe(.status(try status(Fixture.onlineStatus)), at: at(0))
        XCTAssertNil(announcer.consider(machine),
                     "finding out what was already true is not something that just happened")
    }

    func testGoingOfflineIsAnnouncedOnce() throws {
        var machine = LifecycleMachine()
        var announcer = TransitionAnnouncer()
        machine.observe(.status(try status(Fixture.onlineStatus)), at: at(0))
        _ = announcer.consider(machine)
        machine.intend(.stop, at: at(1))
        XCTAssertNil(announcer.consider(machine), "STOPPING is shown, not announced")
        machine.observe(.status(try status(Fixture.offlineStatus)), at: at(4))
        XCTAssertEqual(announcer.consider(machine)?.text, "CROOKS OS is stopped.")
        machine.observe(.status(try status(Fixture.offlineStatus)), at: at(19))
        XCTAssertNil(announcer.consider(machine))
    }
}
