import Foundation

// `crooks-control status`, as types. Every field is named in `crooks-control contract`.
//
// The one rule that governs this whole file: an absent field must never read as good news.
// A service the document does not mention is "not reported", not "ok". A pad the document
// does not mention is "cannot tell", not "connected". The app is allowed to say less than it
// would like; it is not allowed to say something it has not been told.

/// The colour the control script decided on. RED beats BLUE beats AMBER beats GREEN, and that
/// ordering is decided in Python — this is only the name of the answer.
public enum Colour: String, Decodable, Equatable {
    case green = "GREEN"
    case blue = "BLUE"
    case amber = "AMBER"
    case red = "RED"
    /// A colour a newer script invented. Drawn as a caution, never as "all well".
    case unknown

    public init(raw: String?) {
        self = Colour(rawValue: (raw ?? "").uppercased()) ?? .unknown
    }
}

/// How one line of the status document is doing. `notReported` is this side's own case: it is
/// what a row the document did not send becomes, and it exists so that a missing subsystem
/// cannot be drawn with the same dot as a working one.
public enum Health: String, Equatable {
    case ok
    case off
    case bad
    case notReported

    public init(raw: String?) {
        switch (raw ?? "").lowercased() {
        case "ok": self = .ok
        case "off": self = .off
        case "bad": self = .bad
        default: self = .notReported
        }
    }
}

public struct StatusDocument: Decodable, Equatable {
    public let envelope: Envelope
    public let colour: Colour
    public let headline: String
    public let why: String
    public let issues: [String]
    public let degraded: [String]
    public let rows: [Row]
    public let build: BuildIdentifiers
    public let tablet: TabletRoute
    public let mutation: Mutation
    public let testSession: TestSession
    public let localWork: LocalWork
    public let rollback: RollbackDecision
    public let port: Int?

    // Two fields the control script does not send today, both optional on purpose.
    //
    // `service` is the process truth — is the backend's launchd job loaded, does it have a
    // pid, and (the only part that counts) did /health answer. Workstream A owns start/stop;
    // when it adds a `service` block this app reads it without a rebuild, and until then the
    // app falls back to the `online` row, which has said the same thing since Phase 5.
    //
    // `pad` is the CROOKS Pad's own check-in. There is no substitute for it: see PadPresence
    // for why a Tailscale route is not evidence that a tablet is connected.
    public let service: ServiceReport?
    public let pad: PadReport?

    /// Seconds the backend has been up, when the document says so as a number. The `online`
    /// row's detail carries it as prose ("up 4m · 2 session(s)") and that prose is shown as
    /// it is — but it is not parsed back into a number here. Reading a duration out of an
    /// English sentence is the kind of thing that keeps working until the sentence changes
    /// and then silently shows the wrong figure.
    public let uptimeS: Double?

    public struct Row: Decodable, Equatable, Identifiable {
        public let key: String
        public let label: String
        public let health: Health
        public let value: String
        public let detail: String

        public var id: String { key }

        public init(key: String, label: String, health: Health, value: String, detail: String) {
            self.key = key
            self.label = label
            self.health = health
            self.value = value
            self.detail = detail
        }

        enum CodingKeys: String, CodingKey { case key, label, state, value, detail }

        public init(from decoder: Decoder) throws {
            let box = try decoder.container(keyedBy: CodingKeys.self)
            key = box.value(.key, or: "")
            label = box.value(.label, or: "")
            health = Health(raw: box.maybe(.state))
            value = box.value(.value, or: "")
            detail = box.value(.detail, or: "")
        }
    }

    public struct TabletRoute: Decodable, Equatable {
        /// The Tailscale name the Mac is serving the pad's page on, if it is serving one.
        public let host: String
        public let url: String
        public let note: String
        public let local: String

        public init(host: String = "", url: String = "", note: String = "", local: String = "") {
            self.host = host
            self.url = url
            self.note = note
            self.local = local
        }

        enum CodingKeys: String, CodingKey { case host, url, note, local }

        public init(from decoder: Decoder) throws {
            let box = try decoder.container(keyedBy: CodingKeys.self)
            host = box.value(.host, or: "")
            url = box.value(.url, or: "")
            note = box.value(.note, or: "")
            local = box.value(.local, or: "")
        }
    }

    public struct Mutation: Decodable, Equatable {
        /// "ready" | "read_only" | "blocked" | "unknown" — whether CROOKS OS can make changes.
        public let state: String
        public let detail: String

        public var isReady: Bool { state == "ready" }
        public var isReadOnly: Bool { state == "read_only" || state == "blocked" }

        public init(state: String = "unknown", detail: String = "") {
            self.state = state
            self.detail = detail
        }

        enum CodingKeys: String, CodingKey { case state, detail }

        public init(from decoder: Decoder) throws {
            let box = try decoder.container(keyedBy: CodingKeys.self)
            state = box.value(.state, or: "unknown")
            detail = box.value(.detail, or: "")
        }
    }

    public struct TestSession: Decodable, Equatable {
        public let active: Bool
        public let id: String
        public let name: String

        public init(active: Bool = false, id: String = "", name: String = "") {
            self.active = active
            self.id = id
            self.name = name
        }

        enum CodingKeys: String, CodingKey { case active, id, name }

        public init(from decoder: Decoder) throws {
            let box = try decoder.container(keyedBy: CodingKeys.self)
            active = box.value(.active, or: false)
            id = box.value(.id, or: "")
            name = box.value(.name, or: "")
        }
    }

    enum CodingKeys: String, CodingKey {
        case contract, command, ok, at
        case state, headline, why, issues, degraded, rows, build, tablet, mutation
        case testSession, localWork, rollback, port, service, pad, uptimeS
    }

    public init(from decoder: Decoder) throws {
        let box = try decoder.container(keyedBy: CodingKeys.self)
        // The only required field. Everything else has a safe absence; a document with no
        // contract number is not this script's document at all and there is nothing to draw.
        let version = try box.decode(Int.self, forKey: .contract)
        envelope = Envelope(
            contract: version,
            command: box.value(.command, or: "status"),
            ok: box.value(.ok, or: false),
            at: box.maybe(.at)
        )
        colour = Colour(raw: box.maybe(.state))
        headline = box.value(.headline, or: "")
        why = box.value(.why, or: "")
        issues = box.value(.issues, or: [])
        degraded = box.value(.degraded, or: [])
        rows = box.value(.rows, or: [])
        build = box.value(.build, or: BuildIdentifiers())
        tablet = box.value(.tablet, or: TabletRoute())
        mutation = box.value(.mutation, or: Mutation())
        testSession = box.value(.testSession, or: TestSession())
        localWork = box.value(.localWork, or: LocalWork())
        rollback = box.value(.rollback, or: RollbackDecision())
        port = box.maybe(.port)
        service = box.maybe(.service)
        pad = box.maybe(.pad)
        uptimeS = box.maybe(.uptimeS)
    }

    // MARK: - What the app asks this document

    public func row(_ key: String) -> Row? {
        rows.first { $0.key == key }
    }

    /// Is CROOKS OS actually answering?
    ///
    /// This is the question the whole first viewport turns on, so it is worth being careful
    /// about what counts as an answer. A process id does not count. A launchd job being
    /// loaded does not count. What counts is that something answered on the loopback port,
    /// because that is the only fact that means the owner can talk to CROOKS OS.
    ///
    ///   1. `service.healthy`, when a newer script sends it — it is the same question asked
    ///      at the source, and `service.pid` is deliberately ignored.
    ///   2. otherwise the `online` row, which has meant "answering on 127.0.0.1:<port>"
    ///      since Phase 5.
    ///   3. otherwise the colour, and only because control.py's own roll-up cannot produce
    ///      any colour but RED without /health having answered first.
    public var backendAnswering: Bool {
        if let healthy = service?.healthy { return healthy }
        if let online = row("online") { return online.health == .ok }
        switch colour {
        case .green, .blue, .amber: return true
        case .red, .unknown: return false
        }
    }

    /// The subsystems the assistant cannot work without that are down. RED's reason.
    public var essentialsDown: [String] { issues }
}

/// The process truth, when the control script reports it. Optional in the contract, and
/// treated as a hint rather than a verdict everywhere except `healthy`.
public struct ServiceReport: Decodable, Equatable {
    /// "running" | "stopped" | "starting" | "stopping" | anything a newer script invents.
    public let state: String
    public let detail: String
    /// Whether launchd (or whatever supervises it) owns the process at all.
    public let managed: Bool?
    /// Present for completeness and for Developer Mode. Never read as "CROOKS OS is up": a
    /// process with a pid that is wedged, or listening on nothing, is exactly the failure the
    /// owner would otherwise be told was a success.
    public let pid: Int?
    /// The only field here that decides anything: the script read /health back and it answered.
    public let healthy: Bool?

    public init(state: String = "", detail: String = "", managed: Bool? = nil, pid: Int? = nil, healthy: Bool? = nil) {
        self.state = state
        self.detail = detail
        self.managed = managed
        self.pid = pid
        self.healthy = healthy
    }

    enum CodingKeys: String, CodingKey { case state, detail, managed, pid, healthy }

    public init(from decoder: Decoder) throws {
        let box = try decoder.container(keyedBy: CodingKeys.self)
        state = box.value(.state, or: "")
        detail = box.value(.detail, or: "")
        managed = box.maybe(.managed)
        pid = box.maybe(.pid)
        healthy = box.maybe(.healthy)
    }
}

/// The CROOKS Pad's own check-in, when the control script reports one.
public struct PadReport: Decodable, Equatable {
    /// When the pad last spoke to the backend, as a unix time.
    public let seenAt: Double?
    /// What spoke — "crooks-pad 1.4.0 (SM-T290)", or a browser's user agent.
    public let agent: String
    /// Where from, for Developer Mode.
    public let address: String
    /// Which build of the pad app, when it says.
    public let build: String

    public init(seenAt: Double? = nil, agent: String = "", address: String = "", build: String = "") {
        self.seenAt = seenAt
        self.agent = agent
        self.address = address
        self.build = build
    }

    enum CodingKeys: String, CodingKey { case seenAt, agent, address, build }

    public init(from decoder: Decoder) throws {
        let box = try decoder.container(keyedBy: CodingKeys.self)
        seenAt = box.maybe(.seenAt)
        agent = box.value(.agent, or: "")
        address = box.value(.address, or: "")
        build = box.value(.build, or: "")
    }
}

public struct BuildIdentifiers: Decodable, Equatable {
    public let current: Build?
    public let candidate: Build?
    public let lastKnownGood: Build?
    public let was: Build?

    public init(current: Build? = nil, candidate: Build? = nil, lastKnownGood: Build? = nil, was: Build? = nil) {
        self.current = current
        self.candidate = candidate
        self.lastKnownGood = lastKnownGood
        self.was = was
    }

    enum CodingKeys: String, CodingKey { case current, candidate, lastKnownGood, was }

    public init(from decoder: Decoder) throws {
        let box = try decoder.container(keyedBy: CodingKeys.self)
        current = box.maybe(.current)
        candidate = box.maybe(.candidate)
        lastKnownGood = box.maybe(.lastKnownGood)
        was = box.maybe(.was)
    }

    public struct Build: Decodable, Equatable {
        public let sha: String
        public let short: String
        public let branch: String
        public let detached: Bool
        public let subject: String
        /// What the RUNNING backend calls itself. Deliberately a different identifier from
        /// the commit: a build id that has not moved after an update is how the app knows the
        /// restart did not happen.
        public let build: String
        public let version: String
        public let recordedAt: Double?

        public init(sha: String = "", short: String = "", branch: String = "", detached: Bool = false,
                    subject: String = "", build: String = "", version: String = "", recordedAt: Double? = nil) {
            self.sha = sha
            self.short = short
            self.branch = branch
            self.detached = detached
            self.subject = subject
            self.build = build
            self.version = version
            self.recordedAt = recordedAt
        }

        enum CodingKeys: String, CodingKey {
            case sha, short, branch, detached, subject, build, version, recordedAt
        }

        public init(from decoder: Decoder) throws {
            let box = try decoder.container(keyedBy: CodingKeys.self)
            sha = box.value(.sha, or: "")
            short = box.value(.short, or: "")
            branch = box.value(.branch, or: "")
            detached = box.value(.detached, or: false)
            subject = box.value(.subject, or: "")
            build = box.value(.build, or: "")
            version = box.value(.version, or: "")
            recordedAt = box.maybe(.recordedAt)
        }

        /// `main · a1b2c3d4e5`, or as much of it as there is. Never an empty string with a
        /// separator hanging off it.
        public var line: String {
            let parts = [detached ? "detached HEAD" : branch, short].filter { !$0.isEmpty }
            return parts.joined(separator: " · ")
        }
    }
}

public struct LocalWork: Decodable, Equatable {
    public let dirty: [String]
    /// The subset of `dirty` that stops an update. Uncommitted work is never thrown away.
    public let blocking: [String]
    public let stops: Bool

    public init(dirty: [String] = [], blocking: [String] = [], stops: Bool = false) {
        self.dirty = dirty
        self.blocking = blocking
        self.stops = stops
    }

    enum CodingKeys: String, CodingKey { case dirty, blocking, stops }

    public init(from decoder: Decoder) throws {
        let box = try decoder.container(keyedBy: CodingKeys.self)
        dirty = box.value(.dirty, or: [])
        blocking = box.value(.blocking, or: [])
        stops = box.value(.stops, or: false)
    }
}

public struct RollbackDecision: Decodable, Equatable {
    /// There is a recorded known-good build, and it is in this checkout.
    public let available: Bool
    /// …and going back to it would not carry uncommitted work onto an older build.
    public let safe: Bool
    public let sha: String
    public let short: String
    public let reason: String
    public let note: String

    public init(available: Bool = false, safe: Bool = false, sha: String = "",
                short: String = "", reason: String = "", note: String = "") {
        self.available = available
        self.safe = safe
        self.sha = sha
        self.short = short
        self.reason = reason
        self.note = note
    }

    enum CodingKeys: String, CodingKey { case available, safe, sha, short, reason, note }

    public init(from decoder: Decoder) throws {
        let box = try decoder.container(keyedBy: CodingKeys.self)
        available = box.value(.available, or: false)
        safe = box.value(.safe, or: false)
        sha = box.value(.sha, or: "")
        short = box.value(.short, or: "")
        reason = box.value(.reason, or: "")
        note = box.value(.note, or: "")
    }
}
