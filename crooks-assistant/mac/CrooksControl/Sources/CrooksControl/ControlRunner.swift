import Foundation
import CrooksControlCore

// Where the checkout is, and how the control script is run.
//
// This is the part of the Phase 5 app that was right and is kept. Everything this app does to
// the Mac goes through one command — the project's own scripts/control.py, run by the
// project's own .venv — and that is the whole of the app's authority. It knows the name of
// that script and nothing else about how CROOKS OS works.
//
// What has changed underneath it: the contract version is now read BEFORE the document is
// decoded, and every failure comes back as a typed `ControlFailure` rather than as a string
// that was already half a sentence. Both so that the core decides what the owner is told.

enum Checkout {
    static let key = "crooks.projectFolder"

    /// The folder the owner picked, if it still looks like the project; otherwise the first of
    /// the usual places that does. `nil` means: ask him.
    static func resolve() -> URL? {
        if let saved = UserDefaults.standard.string(forKey: key) {
            let url = URL(fileURLWithPath: saved, isDirectory: true)
            if looksRight(url) { return url }
        }
        let home = FileManager.default.homeDirectoryForCurrentUser
        let candidates = [
            "crooks-assistant",
            "Shopify-theme/crooks-assistant",
            "Documents/crooks-assistant",
            "Developer/crooks-assistant",
            "code/crooks-assistant",
        ].map { home.appendingPathComponent($0, isDirectory: true) }
        return candidates.first(where: looksRight)
    }

    static func looksRight(_ url: URL) -> Bool {
        FileManager.default.fileExists(atPath: url.appendingPathComponent("scripts/control.py").path)
    }

    static func remember(_ url: URL) {
        UserDefaults.standard.set(url.path, forKey: key)
    }
}

/// One run of `crooks-control <subcommand>`, decoded.
struct ControlRunner {
    let root: URL

    var python: URL { root.appendingPathComponent(".venv/bin/python") }
    var script: URL { root.appendingPathComponent("scripts/control.py") }

    static func here() throws -> ControlRunner {
        guard let root = Checkout.resolve() else { throw ControlFailure.noCheckout }
        return ControlRunner(root: root)
    }

    func status(fresh: Bool = false) async throws -> StatusDocument {
        try await document(.status(fresh: fresh))
    }

    func actions() async throws -> ActionsDocument {
        try await document(.actions)
    }

    /// "Check for update": fetches, and changes nothing.
    func plan() async throws -> UpdateDocument {
        try await document(.plan)
    }

    /// The click. Fast-forward only, the suite, the restart, the health read, the tablet's
    /// address and the mark — all of it on the script's side.
    func apply() async throws -> UpdateDocument {
        try await document(.apply)
    }

    func rollback() async throws -> UpdateDocument {
        try await document(.rollback)
    }

    private func document<T: Decodable>(_ subcommand: ControlSubcommand) async throws -> T {
        let data = try await run(subcommand.argv, timeout: subcommand.timeout)
        // Version first, always. A script one version ahead with a field moved must come back
        // as "build the app again", not as "I could not read that".
        let verdict = Contract.check(data)
        guard verdict.isUsable else { throw ControlFailure.wrongContract(verdict) }
        do {
            return try Contract.decoder.decode(T.self, from: data)
        } catch {
            throw ControlFailure.unreadableAnswer(raw: String(decoding: data.prefix(2000), as: UTF8.self))
        }
    }

    /// The subprocess. stdout is one JSON document; a non-zero exit is NOT an error here,
    /// because the document itself says what went wrong and is worth drawing — a refused
    /// update exits 1 and has more to say than any message this app could invent.
    private func run(_ arguments: [String], timeout: Int) async throws -> Data {
        guard FileManager.default.isExecutableFile(atPath: python.path) else {
            throw ControlFailure.noPython(path: python.path)
        }
        let root = self.root
        let python = self.python
        let script = self.script
        return try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let task = Process()
                task.executableURL = python
                task.arguments = [script.path] + arguments
                task.currentDirectoryURL = root
                let out = Pipe(), err = Pipe()
                task.standardOutput = out
                task.standardError = err
                do {
                    try task.run()
                } catch {
                    continuation.resume(throwing: ControlFailure.commandNotFound(python.path))
                    return
                }
                // A watchdog, because a hung control script is otherwise a spinner with no end.
                // The core's own patience covers the case where this never fires; this covers
                // the case where the process is alive and silent.
                let deadline = DispatchWorkItem { if task.isRunning { task.terminate() } }
                DispatchQueue.global().asyncAfter(deadline: .now() + .seconds(timeout), execute: deadline)

                let data = out.fileHandleForReading.readDataToEndOfFile()
                let problem = String(decoding: err.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
                task.waitUntilExit()
                deadline.cancel()

                if data.isEmpty {
                    if task.terminationReason == .uncaughtSignal {
                        continuation.resume(throwing: ControlFailure.timedOut(seconds: timeout))
                    } else {
                        continuation.resume(throwing: ControlFailure.emptyAnswer(stderr: problem))
                    }
                } else {
                    continuation.resume(returning: data)
                }
            }
        }
    }
}

extension ControlSubcommand {
    /// How long each subcommand is given. The poll is short because it is on a timer and a
    /// slow one would stack up; the update is long because it runs the offline suite.
    var timeout: Int {
        switch self {
        case .status, .actions: return 30
        case .plan, .markGood: return 120
        case .apply, .rollback: return 1800
        }
    }
}

/// A button of kind "shell" or "control" whose output the owner watches: the suite, the UI
/// run, a report. Lines arrive as they are printed.
@MainActor
final class CommandLog: ObservableObject {
    @Published var title: String = ""
    @Published var lines: [String] = []
    @Published var running = false
    @Published var finished: Int32?

    private var task: Process?

    /// Returns nil when it started, or the reason it would not.
    @discardableResult
    func start(_ action: ActionButton) -> ControlFailure? {
        if let refusal = CommandGuard.refuse(action.command) {
            return .refusedCommand(refusal)
        }
        guard let argv = action.command, let first = argv.first else { return .refusedCommand(.empty) }
        stop()
        title = action.label
        lines = []
        finished = nil
        running = true
        let process = Process()
        process.executableURL = URL(fileURLWithPath: first)
        process.arguments = Array(argv.dropFirst())
        if let cwd = action.cwd {
            process.currentDirectoryURL = URL(fileURLWithPath: cwd, isDirectory: true)
        }
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        // Both handlers are called on a background thread, so each one hops to the main actor
        // before it touches anything published.
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let chunk = handle.availableData
            guard !chunk.isEmpty else { return }
            let text = String(decoding: chunk, as: UTF8.self)
            guard let self else { return }
            Task { @MainActor in self.append(text) }
        }
        process.terminationHandler = { [weak self] ended in
            let code = ended.terminationStatus
            pipe.fileHandleForReading.readabilityHandler = nil
            guard let self else { return }
            Task { @MainActor in
                self.running = false
                self.finished = code
            }
        }
        do {
            try process.run()
            task = process
            return nil
        } catch {
            running = false
            return .commandNotFound(first)
        }
    }

    func stop() {
        if let task, task.isRunning { task.terminate() }
        task = nil
        running = false
    }

    private func append(_ text: String) {
        for line in text.split(separator: "\n", omittingEmptySubsequences: false) where !line.isEmpty {
            // The log window shows raw output on purpose — it is where the tracebacks and the
            // exit codes belong — but a credential is never raw anywhere.
            lines.append(Redaction.scrub(String(line)))
        }
        // An hour of output is not something anyone reads; the last thousand lines are.
        if lines.count > 1000 { lines.removeFirst(lines.count - 1000) }
    }
}
