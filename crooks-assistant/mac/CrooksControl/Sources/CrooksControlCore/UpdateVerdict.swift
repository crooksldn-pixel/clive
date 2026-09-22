import Foundation

// Did the update work?
//
// The §26 trap in this one is "update completed vs new version actually healthy". It is the
// easiest mistake in the whole app to make, because the control script hands you a field
// called `ok` and it is `true`.
//
// It is true on purpose. `crooks-control apply` returns ok:true when it did everything it was
// asked to: fetched, fast-forwarded, installed dependencies, ran the suite, restarted the
// agents. If the backend then fails to answer /health, the script says so — `next` becomes
// "verify_by_hand" and `marked_good` stays null, because it refuses to record a build as
// known-good that it could not read back — but `ok` is still true, and the run still exited 0.
//
// A control panel that reads `ok` and draws a tick has just told the owner his shop is
// running a new build that is, in fact, dead. So:
//
//   AN UPDATE SUCCEEDED ONLY IF THE BUILD MOVED, /health ANSWERED AFTERWARDS, AND THE SCRIPT
//   RECORDED IT AS KNOWN-GOOD. Anything else that moved the build is a FAILURE, and a failure
//   that moved the build is where the rollback belongs.

public struct UpdateOffer: Equatable {
    public let from: String
    public let to: String
    public let commits: Int
    public let files: Int
    public let dependenciesChange: [String]
    public let fastForward: Bool

    public init(from: String, to: String, commits: Int, files: Int,
                dependenciesChange: [String], fastForward: Bool) {
        self.from = from
        self.to = to
        self.commits = commits
        self.files = files
        self.dependenciesChange = dependenciesChange
        self.fastForward = fastForward
    }

    public var sentence: String {
        var text = "\(from) → \(to): \(commits) commit\(commits == 1 ? "" : "s"), "
            + "\(files) file\(files == 1 ? "" : "s")."
        if !fastForward {
            text += " This Mac has work the new build does not, so the update cannot be taken cleanly."
        }
        if !dependenciesChange.isEmpty {
            text += " It also changes what CROOKS OS is built from (\(dependenciesChange.joined(separator: ", ")))."
        }
        return text
    }
}

public struct RollbackOffer: Equatable {
    public let short: String
    public let safe: Bool
    public let reason: String

    public init(short: String, safe: Bool, reason: String) {
        self.short = short
        self.safe = safe
        self.reason = reason
    }
}

public enum UpdateVerdict: Equatable {
    /// Nothing to take.
    case upToDate(at: String)
    /// There is a new build, and here is what taking it would mean.
    case available(UpdateOffer, rollback: RollbackOffer?)
    /// It will not run, and nothing has moved: a dirty tree, a diverged branch, no network.
    case refused(reason: String)
    /// It moved, it came back, and it is recorded as the build to return to.
    case installed(build: String, from: String?)
    /// Something went wrong. `rollbackExpected` is the part that matters: it is true when the
    /// build MOVED and did not come up, which is the only situation where going back is the
    /// answer rather than trying again.
    case failed(reason: String, rollbackExpected: Bool, rollback: RollbackOffer?)
    /// Nothing has been asked yet.
    case notChecked

    public var isFailure: Bool {
        if case .failed = self { return true }
        return false
    }

    public var rollbackExpected: Bool {
        if case .failed(_, let expected, _) = self { return expected }
        return false
    }

    /// The headline over the update panel.
    public var headline: String {
        switch self {
        case .notChecked: return "Not checked"
        case .upToDate: return "Up to date"
        case .available: return "A new build is ready"
        case .refused: return "Not taken"
        case .installed: return "Updated"
        case .failed: return "Update failed"
        }
    }

    /// The line under it — always a sentence, always something to do next.
    public var sentence: String {
        switch self {
        case .notChecked:
            return "Press CHECK FOR UPDATE. Nothing moves until you press UPDATE afterwards."
        case .upToDate(let at):
            return at.isEmpty ? "This Mac has the newest build." : "This Mac has the newest build (\(at))."
        case .available(let offer, _):
            return offer.sentence
        case .refused(let reason):
            return reason
        case .installed(let build, let from):
            let was = from.map { " It was on \($0)." } ?? ""
            return "CROOKS OS is running \(build) and answering. This build is now the one to come back to."
                + was
        case .failed(let reason, _, _):
            return reason
        }
    }
}

public enum UpdateJudge {
    /// Read a `plan` document — a check, which by definition has moved nothing.
    public static func judgePlan(_ document: UpdateDocument) -> UpdateVerdict {
        let rollback = offer(from: document.rollback)
        guard let run = document.update else {
            if let stop = document.firstStop { return .refused(reason: Redaction.scrub(stop.reason)) }
            return .refused(reason: "CROOKS OS could not say what an update would do.")
        }
        if let stop = document.firstStop {
            return .refused(reason: Redaction.scrub(stop.reason))
        }
        if run.behind == 0 || document.next == "up_to_date" {
            return .upToDate(at: run.current?.short ?? "")
        }
        // The tree stops it. This is a refusal, not a failure: nothing has been risked.
        if document.localWork?.stops == true {
            let listed = (document.localWork?.blocking ?? []).prefix(5).joined(separator: ", ")
            return .refused(reason: "There is unsaved work in the CROOKS OS folder"
                + (listed.isEmpty ? "" : " (\(listed))")
                + ". Nothing has been changed, and nothing has been thrown away.")
        }
        return .available(
            UpdateOffer(
                from: run.current?.short ?? "?",
                to: run.candidate?.short ?? "?",
                commits: run.behind,
                files: run.changedFiles,
                dependenciesChange: run.deps,
                fastForward: run.fastForward
            ),
            rollback: rollback
        )
    }

    /// Read an `apply` document — a run that may well have moved the build.
    ///
    /// The order of these tests is the whole of the logic, so it is written out rather than
    /// folded into one expression:
    ///
    ///   1. A stop with nothing moved is a refusal. Safe.
    ///   2. Nothing to do is up to date.
    ///   3. The build MOVED. From here on, `ok` is not consulted again.
    ///   4. /health did not answer afterwards → FAILED, and going back is the answer.
    ///   5. Nothing was recorded as known-good → FAILED, same reason: the script only refuses
    ///      to record when it could not confirm the build.
    ///   6. A stage failed → FAILED.
    ///   7. Everything held → installed.
    public static func judgeApply(_ document: UpdateDocument) -> UpdateVerdict {
        let rollback = offer(from: document.rollback)
        let run = document.update
        let moved = run?.moved ?? false

        if let stop = document.firstStop, !moved {
            return .refused(reason: Redaction.scrub(stop.reason))
        }
        if !moved {
            if document.next == "up_to_date" || (run?.behind ?? 0) == 0 {
                return .upToDate(at: run?.current?.short ?? "")
            }
            return .refused(reason: Redaction.scrub(
                document.firstStop?.reason ?? "Nothing was changed."))
        }

        let newBuild = document.markedGood?.short
            ?? document.build?.current?.short
            ?? run?.candidate?.short
            ?? "the new build"
        let previous = document.build?.was?.short ?? run?.current?.short

        if run?.verified != true {
            return .failed(
                reason: "CROOKS OS was updated to \(newBuild), but it has not answered since. "
                    + "The new build is on this Mac and it is not running."
                    + (rollback?.safe == true
                        ? " Going back to \(rollback?.short ?? "the last good build") is safe."
                        : " " + (rollback?.reason ?? "There is no recorded build to go back to.")),
                rollbackExpected: true,
                rollback: rollback
            )
        }
        if document.markedGood == nil {
            return .failed(
                reason: "CROOKS OS was updated to \(newBuild), but it was not confirmed healthy, "
                    + "so it has NOT been recorded as a build to come back to. Check the logs before "
                    + "relying on it.",
                rollbackExpected: true,
                rollback: rollback
            )
        }
        if let failure = document.allStages.first(where: { $0.failed }) {
            return .failed(
                reason: "CROOKS OS was updated to \(newBuild), but \(failure.stage) failed: "
                    + Redaction.scrub(failure.detail),
                rollbackExpected: true,
                rollback: rollback
            )
        }
        if document.next == "rollback" {
            return .failed(
                reason: Redaction.scrub(document.firstStop?.reason
                    ?? "The update did not come up, and going back is the answer."),
                rollbackExpected: true,
                rollback: rollback
            )
        }
        return .installed(build: newBuild, from: previous)
    }

    /// Read a `rollback` document.
    public static func judgeRollback(_ document: UpdateDocument) -> UpdateVerdict {
        let rollback = offer(from: document.rollback)
        if let stop = document.firstStop {
            return .failed(reason: Redaction.scrub(stop.reason), rollbackExpected: false, rollback: rollback)
        }
        let verified = document.allStages.contains { $0.stage == "verify" && $0.state == "ok" }
        let short = document.build?.current?.short ?? document.rollback?.short ?? "the last good build"
        if !verified {
            return .failed(
                reason: "This Mac went back to \(short), but CROOKS OS has not answered since. "
                    + "Open the logs; a restart of the Mac is the next thing to try.",
                rollbackExpected: false,
                rollback: rollback
            )
        }
        return .installed(build: short, from: nil)
    }

    /// Route by the document's own command, so a caller cannot accidentally judge an `apply`
    /// with the gentler rules a `plan` gets.
    public static func judge(_ document: UpdateDocument) -> UpdateVerdict {
        switch document.envelope.command {
        case "plan": return judgePlan(document)
        case "apply": return judgeApply(document)
        case "rollback": return judgeRollback(document)
        default: return judgeApply(document)
        }
    }

    private static func offer(from decision: RollbackDecision?) -> RollbackOffer? {
        guard let decision, decision.available || !decision.reason.isEmpty else { return nil }
        return RollbackOffer(
            short: decision.short,
            safe: decision.safe,
            reason: Redaction.scrub(decision.reason)
        )
    }
}
