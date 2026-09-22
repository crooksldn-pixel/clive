import Foundation

// IS CROOKS OS RUNNING? — the first question the first viewport answers, and the one this
// file decides.
//
// The control script reports a colour (GREEN/BLUE/AMBER/RED) about a system that either is or
// is not answering. It has no word for "the owner pressed START four seconds ago and it has
// not come up yet", because from the script's side that is indistinguishable from OFFLINE.
// The app does know, because the app is the thing that was pressed, and STARTING is what the
// owner needs to see in those seconds — otherwise he presses START again, and again.
//
// Two rules hold this together, and both of them are the §26 lesson:
//
//   1. STARTING NEVER BECOMES ONLINE BECAUSE A COMMAND SUCCEEDED. The start command exiting 0
//      means launchd accepted the job. It does not mean the backend is up, it does not mean
//      /health answers, and it certainly does not mean the owner can talk to CROOKS OS. Only
//      a status document that reads back as answering moves the app to ONLINE.
//
//   2. STARTING IS NOT ALLOWED TO LAST FOREVER. A spinner that never resolves is the most
//      dishonest thing a control panel can do, because it looks like progress. After the
//      grace period, STARTING becomes ERROR with a sentence saying it did not come up.

public enum Lifecycle: String, Equatable, CaseIterable {
    /// Nothing has been read yet — the first moments after launch.
    case unknown
    case offline
    case starting
    case online
    case stopping
    /// Something is wrong that is not simply "it is not running": the control script cannot be
    /// reached, or a start or stop did not take.
    case error

    /// The word the first viewport shows, in the brief's own vocabulary (§5).
    public var word: String {
        switch self {
        case .unknown: return "CHECKING"
        case .offline: return "OFFLINE"
        case .starting: return "STARTING"
        case .online: return "ONLINE"
        case .stopping: return "STOPPING"
        case .error: return "ERROR"
        }
    }

    /// The same fact as a sentence, for the one line the first viewport is built around.
    ///
    /// `word` is the badge — the menu bar, the pill — where a single token is what fits.
    /// This is the headline, and it is written out separately because "CROOKS OS IS ERROR" is
    /// not English, and a control centre that cannot manage a grammatical sentence at
    /// thirty point has already told the owner what sort of thing it is.
    public var headline: String {
        switch self {
        case .unknown: return "READING CROOKS OS"
        case .offline: return "CROOKS OS IS OFFLINE"
        case .starting: return "CROOKS OS IS STARTING"
        case .online: return "CROOKS OS IS ONLINE"
        case .stopping: return "CROOKS OS IS STOPPING"
        case .error: return "CROOKS OS HAS A PROBLEM"
        }
    }

    /// Whether the app is waiting on something and should be showing it.
    public var isTransitional: Bool { self == .starting || self == .stopping }

    /// Whether this is a state worth announcing once it settles. Transitional states are shown
    /// live, in the state block itself; announcing them as well is how five toasts happen.
    public var isSettled: Bool { self == .offline || self == .online || self == .error }
}

/// What the owner asked for.
public enum Intent: Equatable {
    case start
    case stop
    case restart
}

/// What the app just learned.
public enum Reading: Equatable {
    /// A status document came back and was understood.
    case status(StatusDocument)
    /// The control script itself could not answer. This is NOT the same as CROOKS OS being
    /// offline — offline is a thing the script tells us calmly. This is the script being
    /// unreachable, which is the Mac's problem, not CROOKS OS's, and it gets its own state.
    case unreadable(ControlFailure)
}

public struct LifecycleMachine: Equatable {
    /// How long a start or a stop is given before the app stops believing in it.
    ///
    /// 120 seconds for a start because the backend loads a model and warms clients; a cold
    /// start on the Mac Mini has been seen to take over a minute. 45 for a stop because
    /// nothing that shuts down takes longer than that without being stuck.
    public struct Patience: Equatable {
        public var start: TimeInterval
        public var stop: TimeInterval

        public init(start: TimeInterval = 120, stop: TimeInterval = 45) {
            self.start = start
            self.stop = stop
        }
    }

    /// Why the app is in ERROR, which decides how long it stays there.
    public enum Fault: Equatable {
        /// The control script itself could not be reached. Clears the moment one document
        /// comes back, whatever that document says — the problem was reaching CROOKS OS, and
        /// we just did.
        case unreachable
        /// A start or a stop did not take. Does NOT clear on a status that merely agrees with
        /// it. Pressing START and watching it fail, then being shown a plain OFFLINE fifteen
        /// seconds later with no mention of what happened, invites a second press and a third;
        /// the explanation has to survive until either the owner acts or CROOKS OS comes up.
        case didNotMove
    }

    public private(set) var phase: Lifecycle
    public private(set) var since: Date
    /// The plain line under the big word. Never empty once anything has been read.
    public private(set) var explanation: String
    public private(set) var fault: Fault?
    public var patience: Patience

    public init(phase: Lifecycle = .unknown, since: Date = Date(timeIntervalSince1970: 0),
                explanation: String = "Reading CROOKS OS…", patience: Patience = Patience()) {
        self.phase = phase
        self.since = since
        self.explanation = explanation
        self.patience = patience
    }

    /// The owner pressed a button. Note what this does NOT do: it does not wait for the
    /// command, and it does not care what the command returns. The command's exit code is
    /// evidence about the command, not about CROOKS OS.
    public mutating func intend(_ intent: Intent, at now: Date) {
        switch intent {
        case .start:
            move(to: .starting, at: now, because: "Starting CROOKS OS. This takes up to two minutes from cold.")
        case .stop:
            move(to: .stopping, at: now, because: "Stopping CROOKS OS.")
        case .restart:
            // A restart is a stop and a start run back to back by one command; from here it is
            // a start, because the thing being waited for is CROOKS OS coming back.
            move(to: .starting, at: now, because: "Restarting CROOKS OS.")
        }
    }

    /// A command the app ran on the owner's behalf has finished. Deliberately narrow: a
    /// failure here is worth knowing about, a success is worth nothing at all.
    ///
    /// This is the line that keeps the app honest. `launchctl kickstart` returns 0 the moment
    /// launchd accepts the job; if that were allowed to mean ONLINE, the app would show green
    /// while the backend was still dying in a loop.
    public mutating func commandFinished(_ intent: Intent, failure: ControlFailure?, at now: Date) {
        guard let failure else { return }
        switch intent {
        case .start, .restart:
            move(to: .error, at: now, because: "CROOKS OS would not start. " + failure.sentence,
                 fault: .didNotMove)
        case .stop:
            move(to: .error, at: now, because: "CROOKS OS would not stop. " + failure.sentence,
                 fault: .didNotMove)
        }
    }

    /// A poll came back. Everything above is intent; this is the only evidence.
    public mutating func observe(_ reading: Reading, at now: Date) {
        switch reading {
        case .unreadable(let failure):
            // Whatever we were waiting for, we have lost sight of the thing we were waiting on.
            move(to: .error, at: now, because: failure.sentence, fault: .unreachable)

        case .status(let status):
            let answering = status.backendAnswering
            // A start or a stop that failed stands until something changes. A poll that only
            // agrees with it — "still not running", which is precisely what the error said —
            // is not a change, and replacing "CROOKS OS would not start" with a plain OFFLINE
            // fifteen seconds later is how the owner ends up pressing START three times
            // without ever being told why it did not work.
            if phase == .error, fault == .didNotMove, !answering { return }
            switch phase {
            case .starting:
                if answering {
                    move(to: .online, at: now, because: settledExplanation(status))
                } else if now.timeIntervalSince(since) >= patience.start {
                    move(to: .error, at: now, because:
                        "CROOKS OS did not come up within \(Format.seconds(patience.start)). "
                        + "Open the logs to see how far it got, then try START again.",
                         fault: .didNotMove)
                } else {
                    // Still starting. The explanation is left alone so the line under the big
                    // word does not flicker between two ways of saying the same thing.
                    explanation = "Starting CROOKS OS — it is not answering yet (\(Format.seconds(now.timeIntervalSince(since))) so far)."
                }
            case .stopping:
                if !answering {
                    move(to: .offline, at: now, because: "CROOKS OS is stopped. Press START when you want it back.")
                } else if now.timeIntervalSince(since) >= patience.stop {
                    move(to: .error, at: now, because:
                        "CROOKS OS is still answering \(Format.seconds(patience.stop)) after being asked to stop. "
                        + "Open the logs, or restart the Mac.",
                         fault: .didNotMove)
                } else {
                    explanation = "Stopping CROOKS OS — it is still answering."
                }
            default:
                move(to: answering ? .online : .offline, at: now, because:
                    answering ? settledExplanation(status)
                              : (status.why.isEmpty ? "CROOKS OS is not running. Press START." : status.why))
            }
        }
    }

    /// Time passed without a poll — used by the app's own timer so a start that never comes
    /// back still resolves even if the script has gone quiet.
    public mutating func tick(at now: Date) {
        switch phase {
        case .starting where now.timeIntervalSince(since) >= patience.start:
            move(to: .error, at: now, because:
                "CROOKS OS did not come up within \(Format.seconds(patience.start)). "
                + "Open the logs to see how far it got, then try START again.", fault: .didNotMove)
        case .stopping where now.timeIntervalSince(since) >= patience.stop:
            move(to: .error, at: now, because:
                "CROOKS OS is still answering \(Format.seconds(patience.stop)) after being asked to stop. "
                + "Open the logs, or restart the Mac.", fault: .didNotMove)
        default:
            break
        }
    }

    /// The line under ONLINE. It is where the difference between "online" and "online but
    /// something is wrong" lives — the big word stays ONLINE because CROOKS OS is running and
    /// the owner can talk to it, and the sentence says what is not right.
    private func settledExplanation(_ status: StatusDocument) -> String {
        if status.testSession.active {
            let name = status.testSession.name.isEmpty ? status.testSession.id : status.testSession.name
            return name.isEmpty ? "A test session is recording." : "Recording the test session “\(name)”."
        }
        if !status.issues.isEmpty { return status.why }
        if !status.degraded.isEmpty { return status.why }
        return status.why.isEmpty ? "Everything answering." : status.why
    }

    private mutating func move(to next: Lifecycle, at now: Date, because reason: String,
                               fault: Fault? = nil) {
        let reason = Redaction.scrub(reason)
        if next != phase {
            phase = next
            since = now
        }
        explanation = reason
        // The fault only means anything while the phase is ERROR. Leaving a stale one behind
        // would make the next error inherit the last one's stickiness.
        self.fault = next == .error ? fault : nil
    }
}

// MARK: - Saying it once

/// One state transition is enough (§5.8). Five toasts is what happens when every change of
/// every field is treated as news.
///
/// The rule: only a SETTLED phase is ever announced, and only when it is different from the
/// last thing announced. So offline → starting → starting → starting → online produces one
/// line, "CROOKS OS is online", and the starting is shown in the state block where it belongs
/// rather than shouted three times.
public struct TransitionAnnouncer: Equatable {
    private var lastAnnounced: Lifecycle?

    public init(lastAnnounced: Lifecycle? = nil) {
        self.lastAnnounced = lastAnnounced
    }

    public struct Announcement: Equatable {
        public let phase: Lifecycle
        public let text: String
    }

    /// nil means: say nothing, the state block already shows it.
    public mutating func consider(_ machine: LifecycleMachine) -> Announcement? {
        let phase = machine.phase
        guard phase.isSettled else { return nil }
        guard phase != lastAnnounced else { return nil }
        // The first settled reading after launch is not news either — the app has only just
        // finished finding out what was already true.
        let firstReading = lastAnnounced == nil
        lastAnnounced = phase
        if firstReading { return nil }
        switch phase {
        case .online: return Announcement(phase: phase, text: "CROOKS OS is online.")
        case .offline: return Announcement(phase: phase, text: "CROOKS OS is stopped.")
        case .error: return Announcement(phase: phase, text: machine.explanation)
        default: return nil
        }
    }
}
