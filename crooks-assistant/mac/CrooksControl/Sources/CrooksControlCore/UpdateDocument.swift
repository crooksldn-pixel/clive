import Foundation

// `crooks-control plan`, `apply` and `rollback` all print one shape: the update document.
// Which fields are filled depends on how far the run got, so nearly all of them are optional.
//
// Nothing in here decides whether an update worked. That is UpdateVerdict's job, and it is
// kept separate because the interesting mistake — treating "the command finished" as "the new
// build is healthy" — is a mistake of judgement, not of decoding.

public struct Stage: Decodable, Equatable, Identifiable {
    public let stage: String
    /// "ok" | "skip" | "fail" | "warn"
    public let state: String
    public let detail: String

    public var id: String { stage + "/" + detail }
    public var failed: Bool { state == "fail" }
    public var warned: Bool { state == "warn" }

    public init(stage: String, state: String, detail: String) {
        self.stage = stage
        self.state = state
        self.detail = detail
    }

    enum CodingKeys: String, CodingKey { case stage, state, detail }

    public init(from decoder: Decoder) throws {
        let box = try decoder.container(keyedBy: CodingKeys.self)
        stage = box.value(.stage, or: "")
        state = box.value(.state, or: "")
        detail = box.value(.detail, or: "")
    }
}

public struct Stop: Decodable, Equatable {
    public let stage: String
    public let reason: String

    public init(stage: String, reason: String) {
        self.stage = stage
        self.reason = reason
    }

    enum CodingKeys: String, CodingKey { case stage, reason }

    public init(from decoder: Decoder) throws {
        let box = try decoder.container(keyedBy: CodingKeys.self)
        stage = box.value(.stage, or: "")
        reason = box.value(.reason, or: "")
    }
}

public struct UpdateDocument: Decodable, Equatable {
    public let envelope: Envelope
    public let update: Run?
    public let build: BuildIdentifiers?
    public let localWork: LocalWork?
    public let rollback: RollbackDecision?
    public let stages: [Stage]
    public let markedGood: Marked?
    public let stop: Stop?
    /// "done" | "up_to_date" | "rollback" | "blocked" | "verify_by_hand" | "click_to_apply"
    public let next: String
    public let click: Click?

    /// `crooks-update`'s own document, nested. `moved`/`tested`/`restarted`/`verified` are the
    /// four facts the verdict is built out of.
    public struct Run: Decodable, Equatable {
        public let branch: String
        public let behind: Int
        public let ahead: Int
        public let fastForward: Bool
        public let deps: [String]
        public let changedFiles: Int
        public let moved: Bool
        public let tested: Bool
        public let restarted: Bool
        /// /health answered AFTER the restart. Not "the restart command returned".
        public let verified: Bool
        public let stages: [Stage]
        public let stop: Stop?
        public let current: BuildIdentifiers.Build?
        public let candidate: BuildIdentifiers.Build?

        public init(branch: String = "", behind: Int = 0, ahead: Int = 0, fastForward: Bool = false,
                    deps: [String] = [], changedFiles: Int = 0, moved: Bool = false, tested: Bool = false,
                    restarted: Bool = false, verified: Bool = false, stages: [Stage] = [], stop: Stop? = nil,
                    current: BuildIdentifiers.Build? = nil, candidate: BuildIdentifiers.Build? = nil) {
            self.branch = branch
            self.behind = behind
            self.ahead = ahead
            self.fastForward = fastForward
            self.deps = deps
            self.changedFiles = changedFiles
            self.moved = moved
            self.tested = tested
            self.restarted = restarted
            self.verified = verified
            self.stages = stages
            self.stop = stop
            self.current = current
            self.candidate = candidate
        }

        enum CodingKeys: String, CodingKey {
            case branch, behind, ahead, fastForward, deps, changedFiles, moved, tested
            case restarted, verified, stages, stop, current, candidate
        }

        public init(from decoder: Decoder) throws {
            let box = try decoder.container(keyedBy: CodingKeys.self)
            branch = box.value(.branch, or: "")
            behind = box.value(.behind, or: 0)
            ahead = box.value(.ahead, or: 0)
            fastForward = box.value(.fastForward, or: false)
            deps = box.value(.deps, or: [])
            changedFiles = box.value(.changedFiles, or: 0)
            moved = box.value(.moved, or: false)
            tested = box.value(.tested, or: false)
            restarted = box.value(.restarted, or: false)
            verified = box.value(.verified, or: false)
            stages = box.value(.stages, or: [])
            stop = box.maybe(.stop)
            current = box.maybe(.current)
            candidate = box.maybe(.candidate)
        }
    }

    /// What was written to logs/last_known_good.json. Its presence after a move is the single
    /// strongest signal that the new build came up: the control script refuses to record a
    /// build it could not read /health back from.
    public struct Marked: Decodable, Equatable {
        public let short: String
        public let build: String

        public init(short: String = "", build: String = "") {
            self.short = short
            self.build = build
        }

        enum CodingKeys: String, CodingKey { case short, build }

        public init(from decoder: Decoder) throws {
            let box = try decoder.container(keyedBy: CodingKeys.self)
            short = box.value(.short, or: "")
            build = box.value(.build, or: "")
        }
    }

    public struct Click: Decodable, Equatable {
        public let label: String
        public let enabled: Bool

        public init(label: String = "", enabled: Bool = false) {
            self.label = label
            self.enabled = enabled
        }

        enum CodingKeys: String, CodingKey { case label, enabled }

        public init(from decoder: Decoder) throws {
            let box = try decoder.container(keyedBy: CodingKeys.self)
            label = box.value(.label, or: "")
            enabled = box.value(.enabled, or: false)
        }
    }

    enum CodingKeys: String, CodingKey {
        case contract, command, ok, at
        case update, build, localWork, rollback, stages, markedGood, stop, next, click
    }

    public init(from decoder: Decoder) throws {
        let box = try decoder.container(keyedBy: CodingKeys.self)
        let version = try box.decode(Int.self, forKey: .contract)
        envelope = Envelope(
            contract: version,
            command: box.value(.command, or: ""),
            ok: box.value(.ok, or: false),
            at: box.maybe(.at)
        )
        update = box.maybe(.update)
        build = box.maybe(.build)
        localWork = box.maybe(.localWork)
        rollback = box.maybe(.rollback)
        stages = box.value(.stages, or: [])
        markedGood = box.maybe(.markedGood)
        stop = box.maybe(.stop)
        next = box.value(.next, or: "")
        click = box.maybe(.click)
    }

    /// Every stage of the run, in the order they happened: the updater's own, then the control
    /// script's (tablet route, mark good).
    public var allStages: [Stage] { (update?.stages ?? []) + stages }

    public var firstStop: Stop? { stop ?? update?.stop }
}
