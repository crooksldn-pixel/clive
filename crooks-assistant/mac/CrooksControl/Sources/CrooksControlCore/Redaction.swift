import Foundation

// Nothing that looks like a credential reaches the screen.
//
// The control script redacts everything it prints (`redact()` in scripts/control.py, with a
// test that puts a real-looking token in the environment and asserts it is not in the
// output). This is the second pass, on this side, and it exists because the app also shows
// text the script never saw: a subprocess's stderr, a decode failure's raw body, the output
// of a button. Those arrive unredacted, and they end up in sentences under the owner's nose.
//
// The shapes are deliberately the SAME shapes control.py uses. Two lists that drift apart are
// worse than one list, because whichever side is behind is the side that leaks.
//
// What is NOT redacted, on purpose: bare hexadecimal. Git SHAs are forty hex characters and
// the whole app is built around showing them. A rule that hid them would make the update
// screen useless in order to protect something that is not a secret.

public enum Redaction {
    public static let mask = "[redacted]"

    /// Shopify, Anthropic, OpenAI-style, GitHub, Slack, Google. Same set as control.py's
    /// SECRET_SHAPES; kept in the same order so the two can be read side by side.
    private static let shapes: NSRegularExpression? = try? NSRegularExpression(
        pattern: "(shpat_|shpca_|shpss_|shppa_|sk-ant-[A-Za-z0-9-]*|sk-|ghp_|gho_|github_pat_|xoxb-|xoxp-|ya29\\.|AIza)[A-Za-z0-9_\\-]{6,}",
        options: []
    )

    /// `ANTHROPIC_API_KEY=...`, `token: ...`, `--password ...` — a credential named as one,
    /// whatever shape its value happens to take.
    private static let namedValue: NSRegularExpression? = try? NSRegularExpression(
        pattern: "(?i)\\b([A-Za-z0-9_.\\-]*(?:token|secret|password|passwd|credential|cookie|api[_-]?key|apikey|authorization)[A-Za-z0-9_.\\-]*)\\s*[:=]\\s*[\"']?([^\\s\"',;]{6,})",
        options: []
    )

    /// Replace anything credential-shaped with the mask, keeping the sentence readable.
    public static func scrub(_ text: String) -> String {
        guard !text.isEmpty else { return text }
        var out = text
        if let shapes {
            out = shapes.stringByReplacingMatches(
                in: out, options: [], range: NSRange(out.startIndex..., in: out), withTemplate: mask
            )
        }
        if let namedValue {
            // The key stays, so the sentence still says WHICH credential was involved; only
            // the value goes. "ANTHROPIC_API_KEY=[redacted]" is useful; "[redacted]" is not.
            out = namedValue.stringByReplacingMatches(
                in: out, options: [], range: NSRange(out.startIndex..., in: out), withTemplate: "$1=\(mask)"
            )
        }
        return out
    }

    /// True when the text still contains something credential-shaped. Used by the tests, and
    /// by nothing else — a caller that needs this in anger should be calling `scrub`.
    public static func looksLikeASecret(_ text: String) -> Bool {
        guard let shapes else { return false }
        let range = NSRange(text.startIndex..., in: text)
        return shapes.firstMatch(in: text, options: [], range: range) != nil
    }
}
