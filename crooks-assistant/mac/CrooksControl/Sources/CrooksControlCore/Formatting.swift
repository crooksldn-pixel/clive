import Foundation

// Durations and times, written the way the control script writes them, so a figure on the Mac
// and the same figure in `crooks-status` read the same. Deliberately not DateComponentsFormatter:
// its output is localised and varies by system, and two machines disagreeing about how long
// something has been up is a bug report nobody can reproduce.

public enum Format {
    /// "45s", "4m", "1.2h" — the same ladder as `_hours()` in scripts/control.py.
    public static func seconds(_ value: TimeInterval?) -> String {
        guard let value, value.isFinite else { return "?" }
        let seconds = max(0, value)
        if seconds < 90 { return String(format: "%.0fs", seconds) }
        if seconds < 5400 { return String(format: "%.0fm", seconds / 60) }
        return String(format: "%.1fh", seconds / 3600)
    }

    /// "4m ago". Never "in 4m": a timestamp from the future is a clock that has slipped, and
    /// the right thing to say about it is "just now", not to invent a time machine.
    public static func ago(_ when: Date?, now: Date) -> String {
        guard let when else { return "at an unknown time" }
        let delta = now.timeIntervalSince(when)
        if delta < 0 { return "just now" }
        if delta < 10 { return "just now" }
        return seconds(delta) + " ago"
    }

    public static func ago(unix: Double?, now: Date) -> String {
        guard let unix, unix > 0 else { return "at an unknown time" }
        return ago(Date(timeIntervalSince1970: unix), now: now)
    }

    /// "up 2.1h", or the honest alternative. The brief asks the first viewport to show uptime;
    /// when the document does not carry one as a number, this says so rather than guessing
    /// from whatever prose happens to be nearby.
    public static func uptime(_ seconds: TimeInterval?) -> String {
        guard let seconds, seconds > 0 else { return "not reported" }
        return "up " + Format.seconds(seconds)
    }

    /// A list, in English. "a, b and c" — not "a, b, c", which reads as a column that lost
    /// its formatting.
    public static func list(_ items: [String]) -> String {
        switch items.count {
        case 0: return ""
        case 1: return items[0]
        case 2: return items[0] + " and " + items[1]
        default: return items.dropLast().joined(separator: ", ") + " and " + (items.last ?? "")
        }
    }

    /// Keep a sentence to a length a control panel can draw without becoming a wall. Cuts on a
    /// word, never mid-word, and says it has cut.
    public static func trim(_ text: String, to limit: Int) -> String {
        guard text.count > limit, limit > 1 else { return text }
        let cut = text.prefix(limit)
        if let space = cut.lastIndex(of: " ") {
            return String(cut[cut.startIndex..<space]) + "…"
        }
        return String(cut) + "…"
    }
}
