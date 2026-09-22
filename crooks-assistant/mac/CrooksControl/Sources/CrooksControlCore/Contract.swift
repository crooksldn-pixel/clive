import Foundation

// The agreement between this app and `scripts/control.py`, and the one decoder both sides of
// it use. Nothing here knows what CROOKS OS is; it only knows what a document from the
// control script looks like and what to do when it is not the shape this build expects.

public enum Contract {
    /// The document version this build of the app understands. `CONTRACT` in control.py.
    public static let understood = 2

    /// Every version this build can actually decode — NOT just the current one.
    ///
    /// The first version of this checked `version == understood`, and that is a deadlock with a
    /// fuse on it. The control script grows additively: a workstream adds a field, bumps the
    /// number, and every installed copy of this app refuses every document until each one has
    /// been rebuilt. It happened here, for a day, between one workstream bumping CONTRACT to 2
    /// and this side still declaring 1 — the app would have drawn nothing but a version error
    /// against a perfectly healthy Mac.
    ///
    /// So the app declares a RANGE. `understood` is what it is built against and what the
    /// parity test holds to control.py's CONTRACT exactly; `readable` is what it will accept,
    /// and control.py's COMPATIBLE_CLIENTS promises to keep printing something each of these
    /// can read.
    public static let readable: Set<Int> = [1, 2]

    /// Can this build decode a document stamped with this version?
    public static func canRead(_ version: Int) -> Bool { readable.contains(version) }

    /// One decoder for every document. The Python side writes snake_case; this side reads
    /// camelCase, and the strategy does the conversion rather than a `CodingKeys` block per
    /// struct that would go stale the first time a field was renamed.
    public static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }()

    /// The version check, run BEFORE the full decode.
    ///
    /// The first version of this app decoded the whole document and only then looked at
    /// `contract`. That got the order exactly wrong: a script one version ahead, with a field
    /// moved, failed as "answered something I could not read" — a dead end — when the true
    /// answer was "build the app again from this checkout". So the version is read on its own
    /// first, out of a probe that has one field in it and therefore cannot fail for any other
    /// reason.
    public static func check(_ data: Data) -> ContractVerdict {
        struct Probe: Decodable { let contract: Int? }
        guard let probe = try? decoder.decode(Probe.self, from: data), let version = probe.contract else {
            return .notADocument
        }
        if canRead(version) { return .understood }
        // Outside the range, and which way matters: a script AHEAD of everything this build can
        // read is fixed by rebuilding the app; one BEHIND is fixed by updating the folder.
        return version > (readable.max() ?? understood) ? .scriptIsNewer(version) : .scriptIsOlder(version)
    }
}

public enum ContractVerdict: Equatable {
    case understood
    /// The control script on this Mac speaks a version this app has never seen.
    case scriptIsNewer(Int)
    /// The app is from a newer checkout than the script it is pointed at.
    case scriptIsOlder(Int)
    /// Whatever came back, it was not one of the control script's documents at all.
    case notADocument

    public var isUsable: Bool { self == .understood }

    /// What the owner reads. Version numbers are not jargon here — they are the whole of the
    /// explanation and the whole of the fix — but "decode error" and "schema" are, so neither
    /// appears.
    public var sentence: String? {
        switch self {
        case .understood:
            return nil
        case .scriptIsNewer(let version):
            return "CROOKS OS on this Mac is newer than this app (it speaks version \(version); "
                + "this app reads version \(Contract.understood)). Build the app again from this "
                + "checkout — `make control-app` — and they will match."
        case .scriptIsOlder(let version):
            return "This app is newer than the CROOKS OS in the folder it is pointed at (the folder "
                + "speaks version \(version); this app reads version \(Contract.understood)). Update "
                + "the folder, or point the app at the right one."
        case .notADocument:
            return "CROOKS OS answered with something that is not one of its own documents. "
                + "Open the logs to see what it said."
        }
    }
}

// MARK: - Tolerant decoding

// Why the whole document is decoded leniently, except for two fields.
//
// The control script grows: a workstream adds `service`, another adds a row, another adds a
// field to `tablet`. If every field here were required, ONE added or renamed field in Python
// would leave the owner looking at an app that draws nothing at all and says only that it
// could not read the answer. That is a worse failure than a missing line.
//
// So: `contract` is required (a document without it is not a document), the state is read
// leniently into a case that includes "I do not recognise this", and everything else falls
// back to an empty value. What must NOT happen is a fallback that reads as good news — an
// absent service is "not reported", never "ok"; an absent pad heartbeat is "cannot tell",
// never "connected". Those rules are in the types themselves, further down the package.

extension KeyedDecodingContainer {
    /// The value at `key`, or `fallback` when it is missing, null, or of a shape this build
    /// does not expect.
    func value<T: Decodable>(_ key: Key, or fallback: T) -> T {
        ((try? decodeIfPresent(T.self, forKey: key)) ?? nil) ?? fallback
    }

    /// The value at `key`, or nil — for the fields whose absence is itself meaningful.
    func maybe<T: Decodable>(_ key: Key) -> T? {
        (try? decodeIfPresent(T.self, forKey: key)) ?? nil
    }
}

/// The envelope every document carries: `contract`, `command`, `ok`, `at`.
public struct Envelope: Equatable {
    public let contract: Int
    public let command: String
    /// The script's own verdict on its run. Deliberately NOT trusted as "it worked": an
    /// `apply` that moved the build and then could not read /health back still comes back
    /// `ok: true`, because the command did what it was asked. Success is decided in
    /// `UpdateVerdict`, from what actually happened.
    public let ok: Bool
    public let at: Double?

    public init(contract: Int, command: String, ok: Bool, at: Double?) {
        self.contract = contract
        self.command = command
        self.ok = ok
        self.at = at
    }
}
