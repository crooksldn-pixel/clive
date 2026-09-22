package com.crooks.pad.core

/**
 * CROOKS Pad — the address, the version, and the two ways a configuration can be wrong.
 *
 * There is exactly one address in this application and it arrives through BuildConfig. It is
 * not a credential — it is a Tailscale hostname, useless to anybody not on the tailnet — so
 * §28 is satisfied by it being in the build rather than in a file somebody has to copy.
 *
 * What matters here is that a wrong address must fail LOUDLY AND EARLY. A shell that is handed
 * "htps://crooks..." and responds by showing a spinner is the worst available outcome: the
 * owner sees a CROOKS-branded screen that will never finish, and no part of the product says
 * why. [PadConfig.parse] is therefore called before the WebView is created, and a failure
 * goes straight to APP ERROR with the reason on the diagnostics screen.
 */

sealed interface PadConfig {
    data class Valid(val origin: WebOrigin, val startUrl: String, val allowList: OriginAllowList) : PadConfig
    data class Invalid(val reason: String) : PadConfig

    companion object {
        /**
         * @param configuredOrigin the value of BuildConfig.CROOKS_ORIGIN — an origin, with no
         *   path. A path here would be a mistake worth catching, because the shell appends
         *   "/" itself and "https://host/app" + "/" is not an address anybody meant.
         */
        fun parse(configuredOrigin: String?): PadConfig {
            if (configuredOrigin.isNullOrBlank()) return Invalid("no CROOKS address is configured in this build")
            val trimmed = configuredOrigin.trim().removeSuffix("/")
            val origin = UrlParser.origin(trimmed)
                ?: return Invalid("the configured CROOKS address is not a usable https address")
            if (origin.scheme != "https") return Invalid("the configured CROOKS address is not https")
            // Anything after the authority means the build was configured with a page rather
            // than an origin.
            if (trimmed != origin.toString()) return Invalid("the configured CROOKS address must be an origin with no path")
            return Valid(
                origin = origin,
                startUrl = origin.toString() + "/",
                allowList = OriginAllowList(listOf(origin)),
            )
        }
    }
}

/**
 * §17's UPDATE REQUIRED, and one deliberate decision to fail OPEN.
 *
 * Everywhere else in CROOKS, an unknown answer fails closed — invariant 7 is explicit that
 * unknown mutations must. This is not that. A version gate decides whether the pad will
 * REFUSE TO WORK, and the failure modes are not symmetrical:
 *
 *   - fail closed on an unparseable minimum: one typo on the Mac, in a field nobody looks at,
 *     and every tablet in the building shows "a new CROOKS is required" and stops. Nothing
 *     the owner can do fixes it from the tablet.
 *   - fail open on an unparseable minimum: a pad that should have been stopped keeps running
 *     a version the Mac has doubts about, and the workspace inside it is still the Mac's own
 *     current page, served fresh.
 *
 * The second is plainly the lesser harm, and the asymmetry is why invariant 7 does not reach
 * here: nothing is being mutated, and nothing is being trusted — the shell is only deciding
 * whether to disable itself. UNKNOWN therefore means "carry on", and it is recorded so that
 * a Mac quietly sending nonsense shows up in the timeline rather than in nobody's notes.
 */
enum class UpdateVerdict { UP_TO_DATE, UPDATE_REQUIRED, UNKNOWN }

object PadVersion {

    /** Parses "1.2.3" and "1.2" and "1". Anything else is null. Suffixes are not accepted. */
    fun parse(version: String?): IntArray? {
        if (version.isNullOrBlank()) return null
        val parts = version.trim().split('.')
        if (parts.isEmpty() || parts.size > 3) return null
        val out = IntArray(3)
        for ((i, part) in parts.withIndex()) {
            if (part.isEmpty() || part.length > 6) return null
            for (c in part) if (c !in '0'..'9') return null
            out[i] = part.toInt()
        }
        return out
    }

    fun compare(a: String?, b: String?): Int? {
        val left = parse(a) ?: return null
        val right = parse(b) ?: return null
        for (i in 0..2) {
            if (left[i] != right[i]) return if (left[i] < right[i]) -1 else 1
        }
        return 0
    }
}

object UpdatePolicy {

    /**
     * @param minimumFromMac the minimum pad version the Mac says it supports, or null when it
     *   has not said — which is the case today: no endpoint in the current backend carries
     *   such a field, so this returns UP_TO_DATE in production and UPDATE_REQUIRED is
     *   unreachable until somebody adds it. That is written down in android/docs/DECISIONS.md
     *   as a handoff rather than left as a surprise.
     */
    fun verdict(currentVersion: String?, minimumFromMac: String?): UpdateVerdict {
        if (minimumFromMac.isNullOrBlank()) return UpdateVerdict.UP_TO_DATE
        val cmp = PadVersion.compare(currentVersion, minimumFromMac) ?: return UpdateVerdict.UNKNOWN
        return if (cmp < 0) UpdateVerdict.UPDATE_REQUIRED else UpdateVerdict.UP_TO_DATE
    }
}
