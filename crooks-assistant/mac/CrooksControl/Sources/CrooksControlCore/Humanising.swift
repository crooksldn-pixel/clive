import Foundation

// Every failure the owner is ever shown passes through here, and comes out a sentence.
//
// The standard is simple and it is absolute: a man who has turned on a Mac and a tablet, and
// has done nothing else, must be able to read what went wrong and know what to do. "exit
// status 127" fails that. So does "Traceback (most recent call last)", "ENOENT", "errno 2",
// "NSPOSIXErrorDomain", and a fifty-line Python stack. Those are what Developer Mode and the
// log window are for, and the log window shows them verbatim — but they do not go in the
// sentence.
//
// The failure that taught this: a missing virtualenv used to surface as "The operation
// couldn't be completed. No such file or directory", which names neither the file, nor the
// fix, nor even which of the two machines had the problem.

/// Everything that can go wrong between pressing a button and having a document.
public enum ControlFailure: Equatable {
    /// No folder on this Mac looks like the CROOKS OS checkout.
    case noCheckout
    /// The folder is there but its Python is not.
    case noPython(path: String)
    /// The command could not be started at all — the usual shape of exit 127.
    case commandNotFound(String)
    /// It ran and stopped. The code is carried so Developer Mode can show it; the sentence
    /// never contains it.
    case exited(code: Int32, stderr: String)
    /// It ran, said nothing, and stopped.
    case emptyAnswer(stderr: String)
    /// It answered, but not with one of its documents.
    case unreadableAnswer(raw: String)
    /// It answered with a document from a version this app does not read.
    case wrongContract(ContractVerdict)
    /// It never came back.
    case timedOut(seconds: Int)
    /// A button whose command the app refused to run (see CommandGuard).
    case refusedCommand(CommandGuard.Refusal)

    /// The one line the owner reads. Always redacted, never technical, always ending in
    /// something he can do.
    public var sentence: String {
        Redaction.scrub(Humanising.sentence(for: self))
    }

    /// The extra line under it, when there is one worth having — still plain, still redacted.
    public var advice: String? {
        switch self {
        case .noCheckout:
            return "Click “Choose folder…” and pick the folder that holds CROOKS OS."
        case .noPython:
            return "In that folder, run `make venv` once. It only has to be done again if the folder is replaced."
        case .exited, .emptyAnswer, .unreadableAnswer, .commandNotFound:
            return "Open the logs to see exactly what it said."
        case .timedOut:
            return "Open the logs, and try again. If it happens twice, restart the Mac."
        case .wrongContract, .refusedCommand:
            return nil
        }
    }

    /// What Developer Mode shows: the same failure with nothing taken out except credentials.
    ///
    /// The redaction is not optional here and it is not belt-and-braces. §28 says no printing
    /// of tokens or keys, full stop — Developer Mode is a switch in an app, not a clearance,
    /// and the stderr of a command that was handed a bad API key quotes it.
    public var technicalDetail: String {
        Redaction.scrub(rawDetail)
    }

    private var rawDetail: String {
        switch self {
        case .noCheckout:
            return "no directory containing scripts/control.py was found"
        case .noPython(let path):
            return "not executable: \(path)"
        case .commandNotFound(let what):
            return "command not found: \(what)"
        case .exited(let code, let stderr):
            return "exit status \(code)\n\(stderr)"
        case .emptyAnswer(let stderr):
            return "empty stdout\n\(stderr)"
        case .unreadableAnswer(let raw):
            return "undecodable stdout\n\(raw)"
        case .wrongContract(let verdict):
            return "contract verdict: \(verdict)"
        case .timedOut(let seconds):
            return "no answer within \(seconds)s"
        case .refusedCommand(let refusal):
            return "command refused: \(refusal)"
        }
    }
}

public enum Humanising {
    /// Technical fragments, and what each one actually means to the man reading it.
    ///
    /// THE ORDER IS THE LOGIC: the first match wins, so the specific patterns come first and
    /// the catch-alls come last. This was written the other way round to begin with, with
    /// "traceback" near the top, and a missing dependency — which has a precise fix, `make
    /// venv` — came out as "CROOKS OS stopped part-way through with a fault of its own",
    /// because every Python failure has a traceback in it. The test that caught it is
    /// testAPythonTracebackBecomesOneSentence.
    private static let translations: [(needle: String, sentence: String)] = [
        ("command not found",
         "CROOKS OS's control command is not where this app expected it. Choose the CROOKS OS folder again."),
        ("no such file or directory",
         "Something CROOKS OS needs is missing from its folder. Choose the folder again, or reinstall it."),
        ("permission denied",
         "This Mac would not let CROOKS OS run that. Check the CROOKS OS folder is the one you installed, not a copy from elsewhere."),
        ("operation not permitted",
         "macOS blocked CROOKS OS from doing that. Give CROOKS Control permission in System Settings › Privacy & Security."),
        ("connection refused",
         "Nothing is listening where CROOKS OS should be. It is not running; press START."),
        ("address already in use",
         "Something else on this Mac has taken the port CROOKS OS uses. Restart the Mac, then press START."),
        ("timed out",
         "CROOKS OS took too long to answer."),
        ("modulenotfounderror",
         "CROOKS OS is missing part of itself. In its folder, run `make venv` to put it back."),
        ("no module named",
         "CROOKS OS is missing part of itself. In its folder, run `make venv` to put it back."),
        ("not a git repository",
         "The folder this app is pointed at is not a CROOKS OS checkout. Choose the right folder."),
        ("could not resolve host",
         "This Mac cannot reach the internet, so the update could not be checked."),
        ("network is unreachable",
         "This Mac cannot reach the internet, so the update could not be checked."),
        // Last, and only when nothing more precise matched: every Python failure has one of
        // these in it, so matching it early would swallow all of the above.
        ("traceback (most recent call last)",
         "CROOKS OS stopped part-way through with a fault of its own."),
    ]

    static func sentence(for failure: ControlFailure) -> String {
        switch failure {
        case .noCheckout:
            return "I cannot find CROOKS OS on this Mac."
        case .noPython(let path):
            // The path is worth naming — it is where the owner should look — but the reason is
            // not "ENOENT", it is that the folder has not been set up yet.
            return "CROOKS OS is in this folder but has not been set up on this Mac yet (nothing at \(path))."
        case .commandNotFound:
            return "CROOKS OS's control command is not where this app expected it."
        case .exited(_, let stderr):
            // The exit code is NOT in the sentence. It never is. It carries no meaning to the
            // person reading and it crowds out the part that does.
            return translate(stderr) ?? "CROOKS OS could not finish that."
        case .emptyAnswer(let stderr):
            return translate(stderr) ?? "CROOKS OS finished without saying anything."
        case .unreadableAnswer(let raw):
            return translate(raw) ?? "CROOKS OS answered with something this app could not read."
        case .wrongContract(let verdict):
            return verdict.sentence ?? "CROOKS OS and this app do not agree on what they are saying to each other."
        case .timedOut(let seconds):
            return "CROOKS OS did not answer within \(seconds) seconds."
        case .refusedCommand(let refusal):
            return refusal.sentence
        }
    }

    /// Find a known technical fragment anywhere in the text and return its plain meaning.
    /// A Python traceback is read from the BOTTOM — the last line is the one that says what
    /// actually happened, and everything above it is the route it took to get there.
    static func translate(_ raw: String) -> String? {
        let text = raw.lowercased()
        for translation in translations where text.contains(translation.needle) {
            return translation.sentence
        }
        return nil
    }

    /// The last line worth reading out of a wall of output — for the log window's summary, not
    /// for a sentence. Blank lines and the frame lines of a traceback are skipped.
    public static func lastMeaningfulLine(_ raw: String) -> String {
        let lines = raw
            .split(separator: "\n", omittingEmptySubsequences: false)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty && !$0.hasPrefix("File \"") && !$0.hasPrefix("at ") }
        return Redaction.scrub(String(lines.last ?? ""))
    }
}
