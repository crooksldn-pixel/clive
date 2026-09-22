package com.crooks.pad.core

/**
 * CROOKS Pad — which addresses are CROOKS, and everything else.
 *
 * This is the shell's outer wall. The pad exists to show one origin and nothing else, and the
 * single most damaging thing a WebView can do is quietly become a browser pointed somewhere
 * else. So the check is written here, by hand, rather than delegated to `java.net.URL` or
 * `Uri.parse`.
 *
 * That is a deliberate refusal of the obvious. Both of those parsers are *lenient* — they are
 * built to make sense of a messy address, which is exactly the wrong instinct for a gate.
 * `java.net.URL` treats an unknown scheme as a protocol error rather than a rejection; it
 * happily keeps user-info in the authority; its `equals` performs DNS resolution. Android's
 * `Uri` accepts a great deal and tells you very little. A gate should be pedantic and should
 * say no when it is unsure, so the parser below accepts a small, exactly-specified shape and
 * returns null for everything else.
 *
 * The attacks it is written against, each of which has a test:
 *
 *   user-info        https://crooks-assistant.taildfb357.ts.net@evil.example/   — the host is
 *                    evil.example; the trusted name is decoration. REJECTED: an authority
 *                    containing '@' is refused outright rather than parsed.
 *   suffix           https://crooks-assistant.taildfb357.ts.net.evil.example/   — a longer
 *                    name that starts with ours. REJECTED: the host must match exactly, never
 *                    by prefix, suffix or `endsWith`.
 *   subdomain        https://anything.crooks-assistant.taildfb357.ts.net/       — REJECTED.
 *                    `tailscale serve` answers on one name; a subdomain of it is not a thing
 *                    that exists, so a request for one means something is wrong.
 *   homograph        a host containing non-ASCII, or a punycode `xn--` label. REJECTED by the
 *                    exact match: nothing that is not byte-for-byte the configured host passes.
 *   downgrade        http:// anything. REJECTED, and the platform refuses it a second time
 *                    through the network security config.
 *   other schemes    intent:, javascript:, file:, content:, data:, blob:, market:, mailto:,
 *                    tel:. REJECTED. `intent:` in particular is how a WebView is talked into
 *                    launching another application.
 *   port             an explicit port that is not the scheme default. REJECTED.
 *
 * One judgement worth stating because it looks like an omission. A trailing dot —
 * `https://crooks-assistant.taildfb357.ts.net./` — names the same machine to DNS, and it
 * would have been defensible to normalise it away. It is rejected instead, because a browser
 * treats it as a *different origin*: different localStorage, different service worker,
 * different microphone grant. A page that loaded there would look right and would have lost
 * its session. The shell never produces that address, so anything that does is not something
 * we asked for.
 */

/** A parsed, normalised web origin: scheme, host, port. Nothing else is kept. */
data class WebOrigin(val scheme: String, val host: String, val port: Int) {
    /** The canonical form, with the default port left implicit, as a browser would write it. */
    override fun toString(): String =
        if (port == defaultPortFor(scheme)) "$scheme://$host" else "$scheme://$host:$port"

    companion object {
        fun defaultPortFor(scheme: String): Int = if (scheme == "https") 443 else 80
    }
}

object UrlParser {

    /** Hosts are ASCII letters, digits, hyphen and dot, and nothing else. */
    private fun hostCharOk(c: Char): Boolean =
        (c in 'a'..'z') || (c in '0'..'9') || c == '-' || c == '.'

    /**
     * Parse to an origin, or null. Null means "not a shape we accept" and the caller must
     * treat it as a refusal — never as "parse failed, carry on".
     */
    fun origin(url: String?): WebOrigin? {
        if (url.isNullOrEmpty()) return null
        // A control character anywhere is a rejection before anything else happens: tab,
        // newline and carriage return are stripped by some URL parsers mid-host, which is a
        // classic way to smuggle a different authority past a check that ran first.
        for (c in url) if (c.code < 0x20 || c.code == 0x7F) return null

        val schemeEnd = url.indexOf("://")
        if (schemeEnd <= 0) return null
        val scheme = url.substring(0, schemeEnd).lowercase()
        if (scheme != "https" && scheme != "http") return null
        for ((i, c) in scheme.withIndex()) {
            val ok = if (i == 0) c in 'a'..'z' else (c in 'a'..'z' || c in '0'..'9' || c == '+' || c == '-' || c == '.')
            if (!ok) return null
        }

        val rest = url.substring(schemeEnd + 3)
        var end = rest.length
        for ((i, c) in rest.withIndex()) {
            if (c == '/' || c == '?' || c == '#' || c == '\\') { end = i; break }
        }
        val authority = rest.substring(0, end)
        if (authority.isEmpty()) return null
        // User-info is never present in anything the shell asks for, and its only use here
        // would be to make a hostile host look like ours. Refuse the whole address.
        if (authority.contains('@')) return null
        // IPv6 literals are bracketed. The pad talks to one Tailscale name; a literal address
        // is not it, and bracket parsing is a needless extra shape to get wrong.
        if (authority.contains('[') || authority.contains(']')) return null

        var host = authority
        var port = -1
        val colon = authority.lastIndexOf(':')
        if (colon >= 0) {
            val portText = authority.substring(colon + 1)
            if (portText.isEmpty()) return null
            for (c in portText) if (c !in '0'..'9') return null
            if (portText.length > 5) return null
            port = portText.toInt()
            if (port !in 1..65535) return null
            host = authority.substring(0, colon)
        }

        host = host.lowercase()
        if (host.isEmpty() || host.length > 253) return null
        if (host.startsWith('.') || host.endsWith('.')) return null     // see the note above
        if (host.startsWith('-') || host.endsWith('-')) return null
        if (host.contains("..")) return null
        for (c in host) if (!hostCharOk(c)) return null
        // A label must be 1..63 characters and must not begin or end with a hyphen.
        for (label in host.split('.')) {
            if (label.isEmpty() || label.length > 63) return null
            if (label.startsWith('-') || label.endsWith('-')) return null
        }

        if (port < 0) port = WebOrigin.defaultPortFor(scheme)
        return WebOrigin(scheme, host, port)
    }
}

/**
 * The allow-list itself. Constructed from configuration, never from anything the page says.
 *
 * `allows` governs TOP-LEVEL NAVIGATION. It deliberately does not govern sub-resources — see
 * [NavigationPolicy] for why the shell owns navigation and the backend owns content policy.
 */
class OriginAllowList(origins: Collection<WebOrigin>) {

    val origins: List<WebOrigin> = origins.toList()

    init {
        require(this.origins.isNotEmpty()) { "an empty allow-list would trust nothing, including CROOKS" }
        // An http origin in the allow-list would be a configuration mistake that silently
        // undoes the whole file. It is refused at construction so the mistake is loud.
        require(this.origins.all { it.scheme == "https" }) { "only https origins may be trusted" }
    }

    fun allows(url: String?): Boolean {
        val parsed = UrlParser.origin(url) ?: return false
        return origins.any { it == parsed }
    }

    /**
     * Deliberately not an overload of [allows]. Two `allows` differing only in a nullable
     * parameter type make `allows(null)` ambiguous at the call site, and the resolution a
     * caller reaches for under time pressure is whichever one compiles — which is exactly how
     * a gate ends up being asked the wrong question.
     */
    fun allowsParsedOrigin(origin: WebOrigin?): Boolean = origin != null && origins.any { it == origin }

    /**
     * The form a WebChromeClient permission request arrives in: a bare origin string such as
     * "https://host" with no path. Parsed by exactly the same parser, because a second,
     * looser code path for origins is how allow-lists develop holes.
     */
    fun allowsOriginString(origin: String?): Boolean = allows(origin)

    companion object {
        /** Build from configured URLs. Any URL that does not parse takes the whole list down. */
        fun of(vararg urls: String): OriginAllowList {
            val parsed = urls.map { UrlParser.origin(it) ?: throw IllegalArgumentException("not a usable origin: $it") }
            return OriginAllowList(parsed)
        }
    }
}
