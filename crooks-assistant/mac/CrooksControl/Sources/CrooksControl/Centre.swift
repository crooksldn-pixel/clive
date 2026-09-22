import AppKit
import Combine
import SwiftUI
import CrooksControlCore

// The one object the views observe. It runs the control script, feeds what comes back into
// the core, and publishes the `Dashboard` the core builds.
//
// It makes no judgements. Every `if` in this file is about WHEN to ask something, never about
// what the answer means — that is all in CrooksControlCore, where it is tested. If a rule
// about what is healthy, what is connected or what counts as a successful update ever appears
// in this file, it is in the wrong place.

@MainActor
final class Centre: ObservableObject {
    @Published private(set) var dashboard: Dashboard = DashboardBuilder.build(DashboardInput())
    @Published private(set) var announcement: TransitionAnnouncer.Announcement?
    @Published var developerMode = UserDefaults.standard.bool(forKey: "crooks.developerMode") {
        didSet {
            UserDefaults.standard.set(developerMode, forKey: "crooks.developerMode")
            rebuild()
        }
    }
    @Published var log = CommandLog()

    private var status: StatusDocument?
    private var actions: [ActionsDocument.Action] = []
    private var actionsReadWhenRouteWas: String?
    private var plan: UpdateDocument?
    private var outcome: UpdateDocument?
    private var failure: ControlFailure?
    private var busy: String?
    private var machine = LifecycleMachine()
    private var announcer = TransitionAnnouncer()
    private var poller: Task<Void, Never>?

    /// Fifteen seconds, which is what /health's own cache is built for. A manual refresh skips
    /// the cache; nothing else does.
    private let pollEvery: UInt64 = 15 * 1_000_000_000

    var accent: Color { dashboard.accent.colour }

    init() {
        // The poll starts here rather than waiting for a view to appear.
        //
        // It used to start in the window's `.task`, which is fine while the window is open and
        // wrong the moment it is not: macOS restores an app with its windows as they were left,
        // so a Mac where the owner had closed the window would come up showing a menu-bar item
        // that said CHECKING and went on saying it. Nothing would be read until he opened the
        // window, which is the one thing the product promises he will not have to do.
        begin()
    }

    // MARK: - The poll

    func begin() {
        guard poller == nil else { return }
        poller = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refresh()
                try? await Task.sleep(nanoseconds: self?.pollEvery ?? 15_000_000_000)
            }
        }
    }

    func refresh(fresh: Bool = false) async {
        do {
            let runner = try ControlRunner.here()
            let document = try await runner.status(fresh: fresh)
            status = document
            failure = nil
            machine.observe(.status(document), at: Date())
            // The actions list is read once rather than every fifteen seconds: it names
            // absolute paths that do not move while the app is open, and re-reading it on
            // every poll would be four subprocesses a minute for nothing.
            //
            // It IS re-read when the tablet's route changes, because control.py bakes that
            // address into the OPEN CROOKS PAD action when the document is built. Without
            // this, a Tailscale that comes up after the app started would leave that button
            // pointing at loopback until the app was reopened.
            if actions.isEmpty || actionsReadWhenRouteWas != document.tablet.host {
                actions = try await runner.actions().actions
                actionsReadWhenRouteWas = document.tablet.host
            }
        } catch let problem as ControlFailure {
            failure = problem
            machine.observe(.unreadable(problem), at: Date())
        } catch {
            let problem = ControlFailure.unreadableAnswer(raw: "\(error)")
            failure = problem
            machine.observe(.unreadable(problem), at: Date())
        }
        rebuild()
    }

    /// The app's own clock, so a START that never comes back resolves even when the script has
    /// gone quiet between polls.
    func tick() {
        machine.tick(at: Date())
        rebuild()
    }

    // MARK: - Buttons

    /// A button was pressed. What it is and what it runs came from the document; this only
    /// obeys it, and tells the core what was intended so the state block can say STARTING.
    func perform(_ button: ActionButton, showOutput: () -> Void) {
        guard button.enabled else { return }
        // Before the kind switch, deliberately. Whether a button changes the running state is
        // decided by the core from its id; branching on `kind` first is how START would stop
        // saying STARTING the day the control script changed it from "shell" to "control".
        if let intent = button.intent {
            runInLog(button, intent: intent, showOutput: showOutput)
            return
        }
        switch button.kind {
        case "open_url":
            if let raw = button.url, let url = URL(string: raw) {
                NSWorkspace.shared.open(url)
            }
        case "open_path":
            revealNewest(button)
        case "control":
            switch button.id {
            case "check": Task { await check() }
            case "update": Task { await update() }
            case "rollback": Task { await rollBack() }
            default: runInLog(button, intent: nil, showOutput: showOutput)
            }
        default:
            runInLog(button, intent: nil, showOutput: showOutput)
        }
    }

    private func runInLog(_ button: ActionButton, intent: Intent?, showOutput: () -> Void) {
        if let intent {
            // Said before the command has finished, deliberately: the owner needs STARTING the
            // moment he presses it, and the command's exit code will not be evidence either way.
            machine.intend(intent, at: Date())
            rebuild()
        }
        if let problem = log.start(button) {
            failure = problem
            if let intent { machine.commandFinished(intent, failure: problem, at: Date()) }
            rebuild()
            return
        }
        if intent == nil { showOutput() }
    }

    // MARK: - The update, in three steps

    func check() async {
        busy = "Checking for an update"
        rebuild()
        defer { busy = nil; rebuild() }
        do {
            plan = try await ControlRunner.here().plan()
            outcome = nil
            failure = nil
        } catch let problem as ControlFailure {
            failure = problem
        } catch {
            failure = .unreadableAnswer(raw: "\(error)")
        }
    }

    func update() async {
        busy = "Updating CROOKS OS"
        rebuild()
        defer { busy = nil }
        do {
            outcome = try await ControlRunner.here().apply()
            failure = nil
        } catch let problem as ControlFailure {
            failure = problem
        } catch {
            failure = .unreadableAnswer(raw: "\(error)")
        }
        await refresh(fresh: true)
    }

    func rollBack() async {
        busy = "Going back to the last build that worked"
        rebuild()
        defer { busy = nil }
        do {
            outcome = try await ControlRunner.here().rollback()
            failure = nil
        } catch let problem as ControlFailure {
            failure = problem
        } catch {
            failure = .unreadableAnswer(raw: "\(error)")
        }
        await refresh(fresh: true)
    }

    // MARK: - The folder

    func chooseFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.prompt = "Use this folder"
        panel.message = "The CROOKS OS folder — the one holding scripts/control.py."
        if panel.runModal() == .OK, let url = panel.url {
            Checkout.remember(url)
            actions = []
            actionsReadWhenRouteWas = nil
            plan = nil
            outcome = nil
            Task { await refresh() }
        }
    }

    /// "Open latest report" is the newest file in the folder the document named, or the folder
    /// itself when there is nothing in it yet.
    private func revealNewest(_ button: ActionButton) {
        guard let path = button.path else { return }
        let url = URL(fileURLWithPath: path, isDirectory: true)
        let manager = FileManager.default
        let contents = (try? manager.contentsOfDirectory(
            at: url, includingPropertiesForKeys: [.contentModificationDateKey])) ?? []
        let newest = contents
            .filter { ["md", "html", "log", "txt"].contains($0.pathExtension) }
            .max { left, right in
                let l = (try? left.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
                let r = (try? right.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
                return l < r
            }
        NSWorkspace.shared.open(newest ?? url)
    }

    // MARK: - One value, rebuilt

    private func rebuild() {
        dashboard = DashboardBuilder.build(DashboardInput(
            status: status,
            actions: actions,
            machine: machine,
            plan: plan,
            outcome: outcome,
            failure: failure,
            busy: busy,
            developerMode: developerMode,
            now: Date()
        ))
        // At most one line, and only when a settled state is genuinely new. §5.8.
        if let said = announcer.consider(machine) {
            announcement = said
        }
    }
}
