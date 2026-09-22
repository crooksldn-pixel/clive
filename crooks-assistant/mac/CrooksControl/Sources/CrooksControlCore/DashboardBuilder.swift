import Foundation

// Everything the app knows, turned into the one value it draws. This is the widest piece of
// the core and the reason the SwiftUI layer can be thin enough to be believed without being
// compiled: there is nothing left in the view but layout.

public struct DashboardInput {
    public var status: StatusDocument?
    public var actions: [ActionsDocument.Action]
    public var machine: LifecycleMachine
    /// The last `plan`, if one has been asked for this session.
    public var plan: UpdateDocument?
    /// The last `apply` or `rollback`, if one has been run this session.
    public var outcome: UpdateDocument?
    /// The last thing that went wrong reaching the control script.
    public var failure: ControlFailure?
    /// What the app is waiting on, while it is waiting. Nil when idle.
    public var busy: String?
    public var developerMode: Bool
    public var now: Date

    public init(status: StatusDocument? = nil, actions: [ActionsDocument.Action] = [],
                machine: LifecycleMachine = LifecycleMachine(), plan: UpdateDocument? = nil,
                outcome: UpdateDocument? = nil, failure: ControlFailure? = nil, busy: String? = nil,
                developerMode: Bool = false, now: Date = Date()) {
        self.status = status
        self.actions = actions
        self.machine = machine
        self.plan = plan
        self.outcome = outcome
        self.failure = failure
        self.busy = busy
        self.developerMode = developerMode
        self.now = now
    }
}

public enum DashboardBuilder {
    /// The seven the first viewport shows, in this order.
    ///
    /// §5 names six (Backend, Claude, ElevenLabs, Shopify, Gmail, Tailscale). Hearing is the
    /// seventh because control.py counts it among the three the assistant cannot work without
    /// — if it is down the system is RED, and a viewport that shows the colour without the
    /// reason sends the owner looking through logs for something the app already knew.
    ///
    /// Each is a ROW KEY from the status document. A row the document does not send becomes a
    /// tile marked `notReported`, never a tile marked well.
    static let tiles: [(key: String, name: String, essential: Bool)] = [
        ("backend", "Backend", true),
        ("speech", "Hearing", true),
        ("claude", "Claude", true),
        ("speaks", "ElevenLabs", false),
        ("shopify", "Shopify", true),
        ("gmail", "Gmail", false),
        ("tablet", "Tailscale", false),
    ]

    /// The display name for each group the script sends. An unknown group key is titled from
    /// the key itself rather than dropped — a button the app cannot categorise is still a
    /// button the owner is entitled to.
    static let groupTitles: [String: String] = [
        "use": "Run",
        "update": "Update",
        "test": "Physical test",
        "look": "Look at",
        "pad": "CROOKS Pad",
    ]

    static let groupOrder = ["use", "update", "test", "pad", "look"]

    public static func build(_ input: DashboardInput) -> Dashboard {
        let status = input.status
        let phase = input.machine.phase
        let accent = accent(for: phase, status: status)
        let pad = padCard(status, now: input.now)
        let update = updatePanel(input)
        let groups = actionGroups(input, pad: pad)
        let missing = missingControls(input.actions)

        return Dashboard(
            lifecycle: phase,
            headline: phase.headline,
            explanation: Redaction.scrub(input.machine.explanation),
            accent: accent,
            services: serviceTiles(status),
            pad: pad,
            session: sessionBand(status),
            identity: identity(status, now: input.now),
            groups: groups,
            update: update,
            notice: notice(input, missing: missing, update: update),
            missingControls: missing,
            busy: input.busy,
            developer: input.developerMode ? developerPanel(input) : nil
        )
    }

    // MARK: - The big word's colour

    static func accent(for phase: Lifecycle, status: StatusDocument?) -> Accent {
        switch phase {
        case .error: return .danger
        case .offline: return .idle
        case .starting, .stopping, .unknown: return .caution
        case .online:
            // Running, but not necessarily well. A test session outranks a grumble because it
            // is what the owner most wants to know while one is on; an essential being down
            // outranks both. The same order the control script uses for its colours, kept the
            // same on purpose so the Mac and `crooks-status` never disagree.
            guard let status else { return .online }
            if !status.issues.isEmpty { return .danger }
            if status.testSession.active { return .testing }
            if !status.degraded.isEmpty || status.mutation.isReadOnly { return .caution }
            return .online
        }
    }

    // MARK: - Services

    static func serviceTiles(_ status: StatusDocument?) -> [ServiceTile] {
        tiles.map { tile in
            guard let row = status?.row(tile.key) else {
                return ServiceTile(
                    key: tile.key, name: tile.name, health: .notReported,
                    value: "not reported",
                    detail: "This CROOKS OS does not say anything about \(tile.name).",
                    essential: tile.essential
                )
            }
            return ServiceTile(
                key: tile.key,
                name: tile.name,
                health: row.health,
                value: Redaction.scrub(row.value),
                detail: Redaction.scrub(row.detail),
                essential: tile.essential
            )
        }
    }

    // MARK: - The pad

    static func padCard(_ status: StatusDocument?, now: Date) -> PadCard {
        guard let status else {
            return PadCard(
                presence: .cannotTell(route: "", note: "CROOKS OS has not been read yet."),
                word: PadPresence.cannotTell(route: "", note: "").word,
                detail: "Nothing has been read from CROOKS OS yet.",
                health: .notReported,
                address: ""
            )
        }
        let presence = PadReading.read(status, now: now)
        let address = status.tablet.url.isEmpty ? status.tablet.local : status.tablet.url
        return PadCard(
            presence: presence,
            word: presence.word,
            detail: Redaction.scrub(PadReading.detail(presence, route: status.tablet, now: now)),
            health: presence.health,
            address: address
        )
    }

    // MARK: - Test session

    static func sessionBand(_ status: StatusDocument?) -> SessionBand {
        let session = status?.testSession ?? StatusDocument.TestSession()
        return SessionBand(active: session.active, name: session.name, id: session.id)
    }

    // MARK: - Version

    static func identity(_ status: StatusDocument?, now: Date) -> IdentityLine {
        let current = status?.build.current
        let good = status?.build.lastKnownGood
        return IdentityLine(
            checkout: current?.line ?? "not read",
            runningBuild: (current?.build).flatMap { $0.isEmpty ? nil : $0 } ?? "not running",
            uptime: Format.uptime(status?.uptimeS),
            lastKnownGood: good.map { build in
                let when = Format.ago(unix: build.recordedAt, now: now)
                return build.short.isEmpty ? "none recorded" : "\(build.short), recorded \(when)"
            } ?? "none recorded"
        )
    }

    // MARK: - The update panel

    static func updatePanel(_ input: DashboardInput) -> UpdatePanel {
        // The outcome of a run outranks the plan that led to it: after UPDATE has been pressed,
        // what happened is the news, not what was going to happen.
        if let outcome = input.outcome {
            let verdict = UpdateJudge.judge(outcome)
            return UpdatePanel(verdict: verdict, headline: verdict.headline,
                               sentence: verdict.sentence, stages: outcome.allStages)
        }
        if let plan = input.plan {
            let verdict = UpdateJudge.judgePlan(plan)
            return UpdatePanel(verdict: verdict, headline: verdict.headline,
                               sentence: verdict.sentence, stages: [])
        }
        let verdict = UpdateVerdict.notChecked
        return UpdatePanel(verdict: verdict, headline: verdict.headline,
                           sentence: verdict.sentence, stages: [])
    }

    // MARK: - Buttons

    static func actionGroups(_ input: DashboardInput, pad: PadCard) -> [ActionGroup] {
        var byGroup: [String: [ActionButton]] = [:]
        for action in input.actions {
            let button = button(for: action, input: input, pad: pad)
            byGroup[action.group, default: []].append(button)
        }
        let keys = byGroup.keys.sorted { left, right in
            let l = groupOrder.firstIndex(of: left) ?? groupOrder.count
            let r = groupOrder.firstIndex(of: right) ?? groupOrder.count
            return l == r ? left < right : l < r
        }
        return keys.map { key in
            let buttons = (byGroup[key] ?? []).enumerated().sorted { left, right in
                let l = KnownAction.rank(left.element.id)
                let r = KnownAction.rank(right.element.id)
                // Ties keep the order the document sent them in, so a script that adds three
                // new buttons gets them in the order it meant.
                return l == r ? left.offset < right.offset : l < r
            }.map(\.element)
            // A group key nobody has written a title for is titled from the key. An EMPTY key
            // gets "Other" rather than an empty heading with buttons floating under it.
            let title = groupTitles[key] ?? (key.isEmpty ? "Other" : key.capitalized)
            return ActionGroup(key: key, title: title, buttons: buttons)
        }
    }

    static func button(for action: ActionsDocument.Action, input: DashboardInput, pad: PadCard) -> ActionButton {
        let (enabled, reason) = availability(action, input: input, pad: pad)
        return ActionButton(
            id: action.id,
            label: action.label,
            why: Redaction.scrub(action.why),
            kind: action.kind,
            severity: severity(action),
            enabled: enabled,
            disabledReason: reason,
            confirmText: action.confirm ? Redaction.scrub(action.confirmText ?? "Are you sure?") : nil,
            command: action.command,
            url: action.url,
            path: action.path,
            cwd: action.cwd,
            intent: KnownAction.intent(for: action.id)
        )
    }

    /// Visual weight only. This table can make a harmless button look serious; it cannot make
    /// a serious one run, or stop one running, or change what it does.
    static func severity(_ action: ActionsDocument.Action) -> Severity {
        if KnownAction.dangerous.contains(action.id) { return .danger }
        if action.confirm { return .caution }
        return .normal
    }

    /// Whether a button may be pressed, and the sentence explaining a grey one.
    ///
    /// Every rule here is the same rule: do not offer a control that cannot do anything. A
    /// START that does nothing because CROOKS OS is already running teaches the owner that the
    /// buttons are decorative, and the next time one really matters he will not believe it.
    static func availability(_ action: ActionsDocument.Action, input: DashboardInput, pad: PadCard) -> (Bool, String?) {
        // First: has this button got the thing behind it that its own kind requires? A button
        // with nothing behind it is the purest form of the failure this whole section exists
        // to prevent — it looks exactly like a working one and does nothing at all.
        //
        // Written as a switch with a `default` on purpose. An earlier version asked for a
        // command only when the kind was "shell" or "control", which meant an action whose
        // kind was missing, misspelled or newly invented sailed through with no command and
        // was drawn live. The test that caught it is
        // WiringTests.testTheDashboardSurvivesAnActionsDocumentOfRubbish.
        switch action.kind {
        case "open_url":
            if (action.url ?? "").isEmpty {
                return (false, "This button has no page to open, so there is nothing behind it.")
            }
        case "open_path":
            if (action.path ?? "").isEmpty {
                return (false, "This button has no folder to open, so there is nothing behind it.")
            }
        default:
            if let refusal = CommandGuard.refuse(action.command) {
                return (false, refusal.sentence)
            }
        }
        let phase = input.machine.phase
        let mutating = action.kind == "shell" || action.kind == "control"
        if input.busy != nil, mutating {
            return (false, "Wait for “\(input.busy ?? "")” to finish.")
        }
        switch action.id {
        case "start":
            switch phase {
            case .online: return (false, "CROOKS OS is already running.")
            case .starting: return (false, "CROOKS OS is starting.")
            case .stopping: return (false, "CROOKS OS is still stopping.")
            default: return (true, nil)
            }
        case "stop":
            switch phase {
            case .offline: return (false, "CROOKS OS is not running.")
            case .stopping: return (false, "CROOKS OS is already stopping.")
            default: return (true, nil)
            }
        case "restart":
            if phase == .offline { return (false, "CROOKS OS is not running. Press START.") }
            if phase.isTransitional { return (false, "Wait for CROOKS OS to settle first.") }
            return (true, nil)
        case "open":
            if phase != .online {
                return (false, "There is nothing to open yet — CROOKS OS is not running.")
            }
            return (true, nil)
        case "update":
            // The brief's two-click update: one click to see what is coming, one to take it.
            // The rule is not conditional on the document's `needs_plan` flag — a script that
            // stopped sending that flag would otherwise quietly turn UPDATE into a one-click
            // action that moves the build before the owner has seen either SHA.
            guard let plan = input.plan, !planIsStale(input) else {
                return (false, "Press CHECK FOR UPDATE first, so you can see what would change.")
            }
            if case .available = UpdateJudge.judgePlan(plan) { return (true, nil) }
            if plan.click?.enabled == true { return (true, nil) }
            return (false, "There is nothing to update to.")
        case "rollback":
            let decision = input.status?.rollback
            if decision?.available != true {
                return (false, Redaction.scrub(decision?.reason ?? "There is no recorded build to go back to."))
            }
            if decision?.safe != true {
                return (false, Redaction.scrub(decision?.reason ?? "Going back is not safe right now."))
            }
            return (true, nil)
        case "session_stop", "test_stop", "stop_and_analyse", "test_analyse", "report":
            if input.status?.testSession.active != true {
                return (false, "No test session is recording.")
            }
            return (true, nil)
        case "session_start", "test_start":
            if input.status?.testSession.active == true {
                return (false, "A test session is already recording.")
            }
            if phase != .online { return (false, "CROOKS OS has to be running to record a test.") }
            return (true, nil)
        default:
            return (true, nil)
        }
    }

    /// Has an update or a rollback happened SINCE the plan that is still on screen?
    ///
    /// It matters because of what a stale plan would leave enabled. Press CHECK, press UPDATE,
    /// watch it succeed — and the plan that said "three commits to take" is still in hand,
    /// still saying UPDATE is available, on a Mac that has already taken them. The second press
    /// would be harmless (the script would answer "up to date") but the button was a lie, and a
    /// button that lies about something harmless is the one that is not believed later.
    ///
    /// Every document carries `at`, so the two can simply be compared. A document without one
    /// is treated as stale, because the safe reading of "I do not know which came first" is
    /// "check again".
    static func planIsStale(_ input: DashboardInput) -> Bool {
        guard let outcome = input.outcome else { return false }
        guard let planAt = input.plan?.envelope.at, let outcomeAt = outcome.envelope.at else { return true }
        return outcomeAt >= planAt
    }

    // MARK: - What this CROOKS OS cannot do

    /// §5.2 asks for a set of controls. The app must not draw one the script cannot perform —
    /// the twelfth invariant, in the small: no fake UI or control may be shown if the server
    /// cannot perform it. So a control that is not in the document is reported as absent,
    /// by name, and the owner is told what to do about it.
    static func missingControls(_ actions: [ActionsDocument.Action]) -> [String] {
        guard !actions.isEmpty else { return [] }
        let present = Set(actions.map(\.id))
        return KnownAction.expected.filter { !present.contains($0.id) }.map(\.name)
    }

    // MARK: - One notice, or none

    static func notice(_ input: DashboardInput, missing: [String], update: UpdatePanel) -> Notice? {
        // Ordered by what the owner would want interrupted for, and exactly one is returned:
        // a control panel that stacks five banners has told him nothing, five times.
        if let failure = input.failure {
            return Notice(tone: .danger, text: failure.sentence, fix: failure.advice)
        }
        if update.verdict.rollbackExpected {
            return Notice(tone: .danger, text: update.sentence,
                          fix: "Press ROLL BACK to return to the last build that was known to work.")
        }
        if let status = input.status, !status.issues.isEmpty, input.machine.phase == .online {
            return Notice(
                tone: .danger,
                text: "CROOKS OS is running but " + Format.list(status.issues) + " "
                    + (status.issues.count == 1 ? "is" : "are") + " down. It cannot do its job like this.",
                fix: "Open the logs, then press RESTART."
            )
        }
        // A missing control only outranks everything below it when the owner would be reaching
        // for it THIS MINUTE. No START button on a Mac where CROOKS OS is not running is a dead
        // end and he needs telling; no START button while it is happily running is a note for
        // later, and putting it above "CROOKS OS cannot make changes" would bury the thing he
        // can actually act on.
        if missing.contains("START"), input.machine.phase == .offline || input.machine.phase == .error {
            return Notice(
                tone: .danger,
                text: "CROOKS OS is not running, and the version in this folder has no START "
                    + "control, so this app cannot start it.",
                fix: "Update CROOKS OS from Terminal — `make up` in its folder — then reopen this app."
            )
        }
        if let status = input.status, status.mutation.isReadOnly, input.machine.phase == .online {
            return Notice(tone: .caution,
                          text: "CROOKS OS is running but cannot make changes: "
                            + Redaction.scrub(status.mutation.detail),
                          fix: nil)
        }
        if !missing.isEmpty {
            return Notice(
                tone: .caution,
                text: "The CROOKS OS in this folder has no "
                    + Format.list(missing) + " control, so this app does not show "
                    + (missing.count == 1 ? "that button" : "those buttons") + ".",
                fix: "Update CROOKS OS, then reopen this app."
            )
        }
        if let status = input.status, status.localWork.stops {
            return Notice(
                tone: .caution,
                text: "There is unsaved work in the CROOKS OS folder, so it cannot be updated. "
                    + "Nothing has been thrown away.",
                fix: Format.trim(status.localWork.blocking.joined(separator: ", "), to: 160)
            )
        }
        return nil
    }

    // MARK: - Developer Mode

    static func developerPanel(_ input: DashboardInput) -> DeveloperPanel {
        DeveloperPanel(
            rows: input.status?.rows ?? [],
            commands: input.actions.compactMap { action in
                action.command.map { (action.id, $0) }
            },
            lastFailure: input.failure.map { Redaction.scrub($0.technicalDetail) },
            contract: input.status?.envelope.contract ?? Contract.understood,
            port: input.status?.port,
            dirty: input.status?.localWork.dirty ?? []
        )
    }
}
