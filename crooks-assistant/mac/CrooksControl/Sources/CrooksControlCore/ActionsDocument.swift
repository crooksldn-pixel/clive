import Foundation

// `crooks-control actions` — the buttons, and the command behind each.
//
// The app hard-codes no command. It draws the list the script sends, which is why a button
// that changes in Python changes on the Mac without anybody rebuilding anything, and why the
// app cannot offer a control the script cannot perform.
//
// That last part is not a slogan. If the script sends no `start` action then this app draws
// no START button — it says, in words, that the CROOKS OS in this folder has no start
// control and what to do about it. A button that looks like it starts CROOKS OS and does
// nothing is worse than no button, because the owner walks away believing it is starting.

public struct ActionsDocument: Decodable, Equatable {
    public let envelope: Envelope
    public let actions: [Action]

    public struct Action: Decodable, Equatable, Identifiable {
        public let id: String
        public let label: String
        /// "shell" | "control" | "open_url" | "open_path", or something a newer script invents.
        public let kind: String
        /// "use" | "update" | "test" | "look", or something a newer script invents.
        public let group: String
        public let command: [String]?
        public let cwd: String?
        public let url: String?
        public let path: String?
        public let confirm: Bool
        public let confirmText: String?
        public let why: String
        /// Set on `update`: the button means nothing until a plan has been fetched.
        public let needsPlan: Bool

        public init(id: String, label: String, kind: String, group: String, command: [String]? = nil,
                    cwd: String? = nil, url: String? = nil, path: String? = nil, confirm: Bool = false,
                    confirmText: String? = nil, why: String = "", needsPlan: Bool = false) {
            self.id = id
            self.label = label
            self.kind = kind
            self.group = group
            self.command = command
            self.cwd = cwd
            self.url = url
            self.path = path
            self.confirm = confirm
            self.confirmText = confirmText
            self.why = why
            self.needsPlan = needsPlan
        }

        enum CodingKeys: String, CodingKey {
            case id, label, kind, group, command, cwd, url, path, confirm, confirmText, why, needsPlan
        }

        public init(from decoder: Decoder) throws {
            let box = try decoder.container(keyedBy: CodingKeys.self)
            id = box.value(.id, or: "")
            label = box.value(.label, or: "")
            kind = box.value(.kind, or: "")
            group = box.value(.group, or: "")
            command = box.maybe(.command)
            cwd = box.maybe(.cwd)
            url = box.maybe(.url)
            path = box.maybe(.path)
            confirm = box.value(.confirm, or: false)
            confirmText = box.maybe(.confirmText)
            why = box.value(.why, or: "")
            needsPlan = box.value(.needsPlan, or: false)
        }
    }

    enum CodingKeys: String, CodingKey { case contract, command, ok, at, actions }

    public init(from decoder: Decoder) throws {
        let box = try decoder.container(keyedBy: CodingKeys.self)
        let version = try box.decode(Int.self, forKey: .contract)
        envelope = Envelope(
            contract: version,
            command: box.value(.command, or: "actions"),
            ok: box.value(.ok, or: false),
            at: box.maybe(.at)
        )
        actions = box.value(.actions, or: [])
    }
}

// MARK: - The ids the app knows by name

/// Ids the app treats specially — for ORDER and SEVERITY only, never to invent a command.
/// An id that is not in this list is still drawn, still run, and still grouped; it simply
/// lands after the ones that are, with no local opinion about how dangerous it is beyond
/// whatever the document's own `confirm` flag says.
public enum KnownAction {
    /// The order buttons appear in within their group. The list is the brief's §5.2 order.
    public static let order: [String] = [
        // use
        "start", "stop", "restart", "open", "health",
        // update
        "check", "update", "rollback",
        // test
        "test_start", "session_start", "test_stop", "session_stop", "test_analyse",
        "stop_and_analyse", "report", "report_open", "tests", "tests_ui",
        // pad
        "pad_install", "pad_update", "pad_open",
        // look
        "logs", "diagnostics", "doctor", "folder",
    ]

    /// Actions that change this Mac, the running system, or the tablet. Drawn apart from the
    /// rest: heavier weight, a warning tint, and never side by side with a harmless button in
    /// a way that lets a stray click land on one instead of the other.
    ///
    /// This is a PRESENTATION table. It cannot add a command, remove one, or change what one
    /// does. Its worst possible failure is drawing a harmless button as though it mattered.
    public static let dangerous: Set<String> = [
        "stop", "restart", "update", "rollback", "pad_install", "pad_update", "reset",
    ]

    /// Controls reported as MISSING when the script does not send them, so the owner is told
    /// the control does not exist here rather than wondering where the button went.
    ///
    /// §5.2 asks for more than these seven — check health, start and stop a physical test,
    /// stop and analyse, open the latest report, open diagnostics, install CROOKS Pad. They
    /// are not on this list, and the omission is deliberate: this list is "ids this app is
    /// certain of". Five of the seven are in the Phase 5 actions document already, and the
    /// brief states that start and stop are being added under those exact ids. For the rest,
    /// the id is a guess — CHECK HEALTH could reasonably be `health`, `doctor` or `check`,
    /// and announcing "this CROOKS OS has no CHECK HEALTH control" about a script that has
    /// one under a name we did not guess is a false alarm, which is worse than silence.
    ///
    /// Anything the script does send is drawn whether it is on this list or not. Adding an id
    /// here only makes its ABSENCE speak.
    public static let expected: [(id: String, name: String)] = [
        ("start", "START"),
        ("stop", "STOP"),
        ("restart", "RESTART"),
        ("check", "CHECK FOR UPDATE"),
        ("update", "UPDATE"),
        ("open", "OPEN CROOKS PAD"),
        ("logs", "OPEN LOGS"),
    ]

    public static func rank(_ id: String) -> Int {
        order.firstIndex(of: id) ?? order.count
    }

    /// Which buttons mean "I am changing whether CROOKS OS is running", so the state block can
    /// say STARTING the moment one is pressed.
    ///
    /// This lives here, and not in the view layer, because of the shape of the mistake it
    /// prevents. The obvious place to work it out is inside the switch that decides HOW to run
    /// a button — and that switch branches on `kind`. START is `kind: "shell"` today; if the
    /// control script ever makes it `kind: "control"` instead, a mapping nested inside that
    /// switch silently stops firing, the machine never enters STARTING, and the app sits on
    /// OFFLINE while the backend comes up. Deciding it from the id alone, here, cannot break
    /// that way — and can be tested, which the view cannot.
    public static func intent(for id: String) -> Intent? {
        switch id {
        case "start": return .start
        case "stop": return .stop
        case "restart": return .restart
        default: return nil
        }
    }
}

// MARK: - What may be run

/// Whether a command out of the actions document may be run at all.
///
/// The app runs commands the control script names, with `Process` and an argv array — never
/// through a shell, so there is no string for anything to be injected into. This guard closes
/// the remaining door: it refuses a document that tries to make the app run a shell *as* the
/// command, which is the one way an edited or swapped actions document could turn a renderer
/// into an arbitrary execution surface. Typed, fixed operations only (§28).
public enum CommandGuard {
    /// Executables that are a shell, and therefore a way to run anything at all.
    static let shells: Set<String> = [
        "sh", "bash", "zsh", "dash", "ksh", "csh", "tcsh", "fish",
        "osascript", "env", "xargs", "eval", "perl", "ruby", "node", "npx",
    ]

    public enum Refusal: Equatable {
        case empty
        case notAbsolute(String)
        case isAShell(String)

        /// Refusals are shown to the owner, so they are sentences. They also name the thing
        /// refused, because a refusal nobody can act on is only a silence with extra steps.
        public var sentence: String {
            switch self {
            case .empty:
                return "This button has no command behind it, so there is nothing to run."
            case .notAbsolute(let what):
                return "This button asks to run `\(what)`, which is not a full path. "
                    + "CROOKS Control only runs commands named by their full path."
            case .isAShell(let what):
                return "This button asks to run a shell (`\(what)`). CROOKS Control runs the "
                    + "commands CROOKS OS names, one at a time, and never a shell."
            }
        }
    }

    /// nil means the command may run.
    public static func refuse(_ argv: [String]?) -> Refusal? {
        guard let argv, let executable = argv.first, !executable.isEmpty else { return .empty }
        guard executable.hasPrefix("/") else { return .notAbsolute(executable) }
        let name = (executable as NSString).lastPathComponent
        if shells.contains(name) { return .isAShell(name) }
        return nil
    }

    public static func allows(_ argv: [String]?) -> Bool {
        refuse(argv) == nil
    }
}

// MARK: - The subcommands the app runs itself

/// The control subcommands the app invokes directly — the poll, and the three that make up
/// the update. Typed, so there is no place for a string to arrive from anywhere else.
public enum ControlSubcommand: Equatable {
    case status(fresh: Bool)
    case actions
    case plan
    case apply
    case rollback
    case markGood

    public var argv: [String] {
        switch self {
        case .status(let fresh): return fresh ? ["status", "--fresh"] : ["status"]
        case .actions: return ["actions"]
        case .plan: return ["plan"]
        // `--yes` is the click. The control script will not move anything without it, and it
        // is written here rather than anywhere a user could reach.
        case .apply: return ["apply", "--yes"]
        case .rollback: return ["rollback", "--yes"]
        case .markGood: return ["mark-good"]
        }
    }
}
