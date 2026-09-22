import Foundation

// IS THE TABLET CONNECTED? — the second question the first viewport answers.
//
// There is a trap in it, and the brief names it (§26): "tablet connected vs backend merely
// reachable". The status document carries a Tailscale route — a hostname the Mac is serving
// the pad's page on. It is tempting to draw that as "CROOKS Pad: connected", because it is
// green, it is there, and it changes when things change.
//
// It is not the same fact. The route says a DOOR IS OPEN. It says nothing about whether the
// Samsung is switched on, whether it is in the shop or in a drawer, whether it is on the same
// network, or whether the CROOKS Pad app is running on it. Every one of those can be false
// with the route still green. An owner who reads "connected" and walks away from a tablet
// that has been off since Tuesday has been lied to by his own control panel.
//
// So the only thing that counts as connected is the pad ITSELF having checked in recently,
// and if the control script does not report that, this says so in words rather than guessing.

public enum PadPresence: Equatable {
    /// The pad checked in within living memory. The only case that may be drawn as connected.
    case connected(lastSeen: Date, agent: String)
    /// The pad has checked in before, but not lately. Still a fact worth having — "last seen
    /// 40 minutes ago" is how the owner knows it is in a drawer rather than broken.
    case idle(lastSeen: Date, agent: String)
    /// It has been long enough that it is not there.
    case away(lastSeen: Date)
    /// There is a route, but nothing has ever come through it.
    case neverSeen
    /// There is no route at all: Tailscale is not serving the page, so the pad could not reach
    /// this Mac even if it wanted to.
    case noRoute(note: String)
    /// The honest case. The control script on this Mac does not report the pad's own check-in,
    /// so this app cannot tell — and says so instead of showing the route and calling it
    /// connection.
    case cannotTell(route: String, note: String)

    public var isConnected: Bool {
        if case .connected = self { return true }
        return false
    }

    /// What is drawn under "CROOKS PAD".
    public var word: String {
        switch self {
        case .connected: return "CONNECTED"
        case .idle: return "IDLE"
        case .away: return "DISCONNECTED"
        case .neverSeen: return "NEVER CONNECTED"
        case .noRoute: return "NO ROUTE"
        case .cannotTell: return "NOT REPORTED"
        }
    }

    public var health: Health {
        switch self {
        case .connected: return .ok
        case .idle: return .off
        case .away, .neverSeen: return .bad
        case .noRoute: return .bad
        // Not knowing is not a fault, and it must not be drawn as one — but it must not be
        // drawn as health either.
        case .cannotTell: return .notReported
        }
    }
}

public enum PadReading {
    /// How fresh a check-in has to be to count as connected.
    ///
    /// The pad polls /health while its screen is on. A minute and a half covers a slow poll
    /// and a moment of bad wifi without covering a tablet that has been put down.
    public static let connected: TimeInterval = 90
    /// Beyond this it is not idle, it is gone.
    public static let idle: TimeInterval = 15 * 60

    public static func read(_ status: StatusDocument, now: Date) -> PadPresence {
        let route = status.tablet.host
        let note = status.tablet.note

        guard let pad = status.pad else {
            // No heartbeat in this build of the control script. Say which of the two facts we
            // actually have, and do not let the one we have stand in for the one we do not.
            if route.isEmpty {
                return .noRoute(note: note.isEmpty ? "Tailscale is not serving the CROOKS Pad's address." : note)
            }
            return .cannotTell(
                route: status.tablet.url.isEmpty ? route : status.tablet.url,
                note: "CROOKS OS on this Mac reports the address the pad would use, but not whether the pad "
                    + "has used it. A route is an open door, not a tablet on the other side of it."
            )
        }

        guard let seenAt = pad.seenAt, seenAt > 0 else {
            if route.isEmpty { return .noRoute(note: note) }
            return .neverSeen
        }
        let lastSeen = Date(timeIntervalSince1970: seenAt)
        // A clock that has run backwards (the Mac woke and re-synced) must not read as a
        // check-in from the future and therefore as connected forever.
        let age = max(0, now.timeIntervalSince(lastSeen))
        if age <= connected { return .connected(lastSeen: lastSeen, agent: pad.agent) }
        if age <= idle { return .idle(lastSeen: lastSeen, agent: pad.agent) }
        return .away(lastSeen: lastSeen)
    }

    /// The line under the word. This is where "last seen" lives, and where the route is shown
    /// as what it is.
    public static func detail(_ presence: PadPresence, route: StatusDocument.TabletRoute, now: Date) -> String {
        switch presence {
        case .connected(let lastSeen, let agent):
            let who = agent.isEmpty ? "" : "\(agent) · "
            return who + "last heard from " + Format.ago(lastSeen, now: now)
        case .idle(let lastSeen, let agent):
            let who = agent.isEmpty ? "" : "\(agent) · "
            return who + "last heard from " + Format.ago(lastSeen, now: now) + ". The screen is probably off."
        case .away(let lastSeen):
            return "Last heard from " + Format.ago(lastSeen, now: now)
                + ". Wake the tablet, or check it is on the same network."
        case .neverSeen:
            return "The address is being served, but the CROOKS Pad has never used it. "
                + "Install CROOKS Pad on the tablet, or open \(route.url) on it once."
        case .noRoute(let note):
            return note.isEmpty
                ? "The tablet has no way to reach this Mac. Check Tailscale is running."
                : note
        case .cannotTell(let route, let note):
            return "\(route) — \(note)"
        }
    }
}
