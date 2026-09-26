import Foundation

// Fake credentials for these tests: every one is assembled here, at runtime, and nowhere else.
//
// The owner's rule of 2026-09-25 ("rule B", docs/product-memory/OWNER_DECISIONS_2026-09-25.md):
// fake credentials in tests are assembled at runtime through one shared test helper, and they
// are never listed in the secret-scan baseline. The repository is public, the acceptance gate
// runs gitleaks over the whole tree, and CLIVE's Knowledge Digester reads this tree like any
// other artifact: a key-shaped literal in a test is a finding in all three places.
//
// So no line here holds a credential's prefix and its body together. Each prefix is written in
// pieces and joined to a body generated from a seed. The same seed always gives the same value,
// so a test stays reproducible; a test that needs two different keys of one kind uses two seeds.
//
// This is the Swift side of crooks-assistant/tests/fake_credentials.py, which serves the Python
// suite with the same approach (FNV-1a over the seed feeding a 64-bit LCG). A shape added to
// one belongs in the other.

enum FakeCredential {
    static let alphanumeric = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    static let digits = "0123456789"
    static let hex = "0123456789abcdef"

    /// `length` characters from `alphabet`, fixed by `seed`.
    static func body(_ seed: String, length: Int, alphabet: String = FakeCredential.alphanumeric) -> String {
        let characters = Array(alphabet)
        var state: UInt64 = 0xcbf2_9ce4_8422_2325
        for byte in seed.utf8 {
            state = (state ^ UInt64(byte)) &* 0x0000_0100_0000_01b3
        }
        var out = ""
        for _ in 0..<max(length, 0) {
            state = state &* 6_364_136_223_846_793_005 &+ 1_442_695_040_888_963_407
            out.append(characters[Int((state >> 33) % UInt64(characters.count))])
        }
        return out
    }

    private static func seeded(_ shape: String, _ seed: String) -> String {
        return shape + ":" + seed
    }

    /// A Shopify token in lower-case hex: `kind` at, ca, pa or ss.
    static func shopifyToken(_ seed: String = "", kind: String = "at") -> String {
        let value = body(seeded("shopify-" + kind, seed), length: 32, alphabet: hex)
        return "shp\(kind)_" + value
    }

    /// An Anthropic credential: `api03` for an API key, `oat01` for a Claude Code OAuth token.
    static func anthropicKey(_ seed: String = "", kind: String = "api03") -> String {
        let value = body(seeded("anthropic-" + kind, seed), length: 93)
        return ["sk", "ant", kind, value].joined(separator: "-") + "AA"
    }

    /// An OpenAI project key.
    static func openAIKey(_ seed: String = "", kind: String = "proj") -> String {
        let value = body(seeded("openai-" + kind, seed), length: 48)
        return ["sk", kind, value].joined(separator: "-")
    }

    /// A classic GitHub token: `kind` p (personal), o (OAuth), u, s or r.
    static func githubToken(_ seed: String = "", kind: String = "p") -> String {
        let value = body(seeded("github-" + kind, seed), length: 36)
        return "gh\(kind)_" + value
    }

    /// A fine-grained GitHub personal access token.
    static func githubFineGrainedToken(_ seed: String = "") -> String {
        let id = body(seeded("github-pat-id", seed), length: 22)
        let value = body(seeded("github-pat", seed), length: 59)
        return ["github", "pat", id, value].joined(separator: "_")
    }

    /// A Slack token: `kind` b (bot) or p (user).
    static func slackToken(_ seed: String = "", kind: String = "b") -> String {
        let team = body(seeded("slack-team", seed), length: 10, alphabet: digits)
        let user = body(seeded("slack-user", seed), length: 12, alphabet: digits)
        let value = body(seeded("slack-" + kind, seed), length: 24)
        return ["xox" + kind, team, user, value].joined(separator: "-")
    }

    /// A Google OAuth access token.
    static func googleOAuthToken(_ seed: String = "") -> String {
        let value = body(seeded("google-oauth", seed), length: 64)
        return ["ya29", value].joined(separator: ".")
    }

    /// A Google API key: a fixed prefix and exactly 35 characters.
    static func googleAPIKey(_ seed: String = "") -> String {
        let value = body(seeded("google-api", seed), length: 35)
        return "AI" + "za" + value
    }

    /// A password as a person would have set one.
    static func password(_ seed: String = "") -> String {
        return body(seeded("password", seed), length: 16)
    }
}
