import Foundation

// One value, holding everything the app draws. The SwiftUI layer reads it and lays it out; it
// decides nothing, because everything worth deciding is decided here, where it can be tested
// on any machine with a Swift toolchain.
//
// The shape follows §5 and §5.8. The first viewport answers five questions and no more:
//
//     IS CROOKS OS RUNNING?     the state block — one word, as large as the window allows
//     IS THE TABLET CONNECTED?  the pad card
//     ARE SERVICES HEALTHY?     seven pips, not a table of fourteen rows
//     WHAT VERSION?             one line, quietly, at the foot
//     IS A TEST SESSION ACTIVE?  a band that only exists while one is
//
// Everything else — the rows the script also sends, the argv behind each button, the raw text
// of a failure — lives in `developer`, which is nil unless the owner has turned Developer Mode
// on. That is §5.7: it is there, it is complete, and it does not dominate.

public enum Accent: String, Equatable {
    case online
    case testing
    case caution
    case danger
    case idle
}

public struct ServiceTile: Equatable, Identifiable {
    public let key: String
    public let name: String
    public let health: Health
    public let value: String
    public let detail: String
    /// The assistant cannot work without this one. Its being down is why the state is an
    /// error rather than a grumble.
    public let essential: Bool

    public var id: String { key }

    public init(key: String, name: String, health: Health, value: String, detail: String, essential: Bool) {
        self.key = key
        self.name = name
        self.health = health
        self.value = value
        self.detail = detail
        self.essential = essential
    }
}

public struct PadCard: Equatable {
    public let presence: PadPresence
    public let word: String
    public let detail: String
    public let health: Health
    /// The address the pad uses, for Developer Mode and for the OPEN CROOKS PAD button.
    public let address: String

    public init(presence: PadPresence, word: String, detail: String, health: Health, address: String) {
        self.presence = presence
        self.word = word
        self.detail = detail
        self.health = health
        self.address = address
    }
}

public struct SessionBand: Equatable {
    public let active: Bool
    public let name: String
    public let id: String

    public init(active: Bool, name: String, id: String) {
        self.active = active
        self.name = name
        self.id = id
    }
}

public struct IdentityLine: Equatable {
    /// "claude/crooks-appliance-phase6 · e43aecd8f1"
    public let checkout: String
    /// What the RUNNING backend calls itself — a different fact from the commit, and the one
    /// that shows a restart did not happen.
    public let runningBuild: String
    public let uptime: String
    public let lastKnownGood: String

    public init(checkout: String, runningBuild: String, uptime: String, lastKnownGood: String) {
        self.checkout = checkout
        self.runningBuild = runningBuild
        self.uptime = uptime
        self.lastKnownGood = lastKnownGood
    }
}

public enum Severity: Int, Equatable, Comparable {
    case normal = 0
    case caution = 1
    case danger = 2

    public static func < (lhs: Severity, rhs: Severity) -> Bool { lhs.rawValue < rhs.rawValue }
}

public struct ActionButton: Equatable, Identifiable {
    public let id: String
    public let label: String
    public let why: String
    public let kind: String
    public let severity: Severity
    public let enabled: Bool
    /// Why it is greyed. Shown on hover and — for the important ones — under the button, so
    /// a disabled control is never a mystery.
    public let disabledReason: String?
    public let confirmText: String?
    // What to run, open or reveal — carried through from the document untouched, because the
    // app hard-codes none of them. None of the three is ever drawn: they are absolute paths
    // on this Mac, and the first viewport is not a terminal.
    public let command: [String]?
    public let url: String?
    public let path: String?
    /// The folder the command expects to be run in. Carried because some of the scripts behind
    /// these buttons resolve relative paths against it, and running one from the wrong place
    /// fails in a way that is hard to read.
    public let cwd: String?
    /// Whether pressing this changes whether CROOKS OS is running, and in which direction.
    /// Decided by the core from the id (see `KnownAction.intent`), never by the view.
    public let intent: Intent?

    public init(id: String, label: String, why: String, kind: String, severity: Severity,
                enabled: Bool, disabledReason: String?, confirmText: String?,
                command: [String]?, url: String? = nil, path: String? = nil,
                cwd: String? = nil, intent: Intent? = nil) {
        self.id = id
        self.label = label
        self.why = why
        self.kind = kind
        self.severity = severity
        self.enabled = enabled
        self.disabledReason = disabledReason
        self.confirmText = confirmText
        self.command = command
        self.url = url
        self.path = path
        self.cwd = cwd
        self.intent = intent
    }

    public var needsConfirmation: Bool { confirmText != nil }
}

public struct ActionGroup: Equatable, Identifiable {
    public let key: String
    public let title: String
    public let buttons: [ActionButton]

    public var id: String { key }

    public init(key: String, title: String, buttons: [ActionButton]) {
        self.key = key
        self.title = title
        self.buttons = buttons
    }
}

public struct Notice: Equatable {
    public enum Tone: String, Equatable { case info, caution, danger }
    public let tone: Tone
    public let text: String
    public let fix: String?

    public init(tone: Tone, text: String, fix: String?) {
        self.tone = tone
        self.text = text
        self.fix = fix
    }
}

public struct UpdatePanel: Equatable {
    public let verdict: UpdateVerdict
    public let headline: String
    public let sentence: String
    public let stages: [Stage]

    public init(verdict: UpdateVerdict, headline: String, sentence: String, stages: [Stage]) {
        self.verdict = verdict
        self.headline = headline
        self.sentence = sentence
        self.stages = stages
    }
}

/// §5.7. Everything the app knows, with nothing taken out except credentials, behind a switch
/// that is off.
public struct DeveloperPanel: Equatable {
    public let rows: [StatusDocument.Row]
    public let commands: [(String, [String])]
    public let lastFailure: String?
    public let contract: Int
    public let port: Int?
    public let dirty: [String]

    public init(rows: [StatusDocument.Row], commands: [(String, [String])], lastFailure: String?,
                contract: Int, port: Int?, dirty: [String]) {
        self.rows = rows
        self.commands = commands
        self.lastFailure = lastFailure
        self.contract = contract
        self.port = port
        self.dirty = dirty
    }

    public static func == (lhs: DeveloperPanel, rhs: DeveloperPanel) -> Bool {
        lhs.rows == rhs.rows
            && lhs.lastFailure == rhs.lastFailure
            && lhs.contract == rhs.contract
            && lhs.port == rhs.port
            && lhs.dirty == rhs.dirty
            && lhs.commands.map(\.0) == rhs.commands.map(\.0)
            && lhs.commands.map(\.1) == rhs.commands.map(\.1)
    }
}

public struct Dashboard: Equatable {
    public let lifecycle: Lifecycle
    /// "CROOKS OS IS ONLINE" — the one thing a glance from across the room must land on.
    public let headline: String
    public let explanation: String
    public let accent: Accent
    public let services: [ServiceTile]
    public let pad: PadCard
    public let session: SessionBand
    public let identity: IdentityLine
    public let groups: [ActionGroup]
    public let update: UpdatePanel
    /// At most one. Never a stack.
    public let notice: Notice?
    /// Controls §5.2 asks for that this CROOKS OS does not offer. Listed, not invented.
    public let missingControls: [String]
    public let busy: String?
    public let developer: DeveloperPanel?

    public init(lifecycle: Lifecycle, headline: String, explanation: String, accent: Accent,
                services: [ServiceTile], pad: PadCard, session: SessionBand, identity: IdentityLine,
                groups: [ActionGroup], update: UpdatePanel, notice: Notice?, missingControls: [String],
                busy: String?, developer: DeveloperPanel?) {
        self.lifecycle = lifecycle
        self.headline = headline
        self.explanation = explanation
        self.accent = accent
        self.services = services
        self.pad = pad
        self.session = session
        self.identity = identity
        self.groups = groups
        self.update = update
        self.notice = notice
        self.missingControls = missingControls
        self.busy = busy
        self.developer = developer
    }

    /// Every string this dashboard would put in front of the owner, in one list. It exists for
    /// the test that walks it and asserts nothing credential-shaped is in any of them; it is
    /// also the honest definition of "user-visible", since a test that checked three fields it
    /// happened to think of would pass while a fourth leaked.
    public var everyVisibleString: [String] {
        var out = [headline, explanation, update.headline, update.sentence, pad.word, pad.detail,
                   pad.address, identity.checkout, identity.runningBuild, identity.uptime,
                   identity.lastKnownGood, session.name, session.id, busy ?? ""]
        out += missingControls
        out += services.flatMap { [$0.name, $0.value, $0.detail] }
        out += groups.flatMap { group in
            [group.title] + group.buttons.flatMap { [$0.label, $0.why, $0.disabledReason ?? "", $0.confirmText ?? ""] }
        }
        out += update.stages.flatMap { [$0.stage, $0.detail] }
        if let notice { out += [notice.text, notice.fix ?? ""] }
        return out.filter { !$0.isEmpty }
    }
}
