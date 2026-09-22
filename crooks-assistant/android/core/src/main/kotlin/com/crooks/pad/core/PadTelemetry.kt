package com.crooks.pad.core

/**
 * CROOKS Pad — §18, the appliance's own account of itself.
 *
 * WHERE THESE EVENTS GO, WHICH CHANGED IN PHASE 6 AND IS THE FIRST THING TO KNOW. A pad_* event
 * does NOT go to `POST /telemetry`. `/telemetry` is the WEB PAGE's account of itself and is
 * silent unless a test session is running; the appliance's liveness must not depend on it.
 * pad_* events ride the §16 HEARTBEAT — `POST /pad/heartbeat`, see [Heartbeat] — whose event
 * table lives in `app/observability/pad.py` on the Mac.
 *
 * THE THING THAT MAKES THIS FILE UNUSUAL, AND THE REASON IT IS WORTH READING. The pad does not
 * own the endpoint it posts to, and that endpoint does two things a naive native client would
 * walk straight into:
 *
 *   1. It admits a FIXED VOCABULARY OF EVENT NAMES. A `kind` outside the table is rejected,
 *      counted in the `rejected` column of the pad block on `/health`, and otherwise gone. A
 *      kind that also fails `^[a-z][a-z0-9_]{0,39}$` never gets that far.
 *   2. It keeps only fields the table names for that kind. A field outside it is DROPPED,
 *      silently, and the event around it is still stored — so the event arrives looking
 *      healthy with the one interesting value missing.
 *
 * That is §26's lesson wearing its most literal costume: a pad that "emits telemetry
 * successfully" while the field that would have explained the outage was thrown away at the
 * door. [BACKEND_KINDS] and [BACKEND_ALLOWED_FIELDS] below are therefore hand copies of the
 * Mac's table, and [PadTelemetryTest] asserts that the set of kinds this shell can emit is
 * EXACTLY [BACKEND_KINDS] and that every field of every one of them is admitted. If either
 * side drifts — a rename here, a rename there — the build goes red in a place that costs a
 * minute, instead of in a timeline nobody can reconstruct six weeks later.
 *
 * PII (§18, invariant 10). The defence is not a scrubber that looks for things that resemble
 * secrets — that is a filter that fails the first time something new resembles nothing. It is
 * a whitelist: each event kind declares the fields it may carry, [record] builds the outgoing
 * map from that declaration and nothing else, and an undeclared key is dropped before it can
 * reach a queue. Specifically never present anywhere in this file: Wi-Fi SSID or BSSID, IP
 * address, MAC address, device serial, any account or e-mail address, any URL path or query,
 * and any text the owner said or the Mac answered. A URL that does reach an event is reduced
 * to its origin by [originOnly] first.
 *
 * NOT SPAMMING (§18, "meaningful transitions only"). Two mechanisms, because they catch
 * different things. Transition events — network, backend reachability, foreground, battery —
 * carry a key and are dropped when the key has not changed. Everything else is dropped when an
 * identical event was emitted within [DEDUPE_WINDOW_MS].
 *
 * The battery deserves a sentence of its own, because it is the event §18 names as the one not
 * to spam and it now exists. It is a transition kind AND its percent is bucketed to five by
 * [PadBattery.bucket] before it is recorded, so the Android broadcast that fires once per
 * percent produces an event about once per five — roughly twenty between full and flat. The
 * rule is arithmetic in `:core` with a test on it, not a comment asking callers to be careful.
 */

data class PadEvent(val kind: String, val fields: Map<String, Any?>)

/** What the shell may emit, and what each kind may say. Nothing outside this reaches the Mac. */
object PadEventSpec {

    /**
     * THE VOCABULARY, copied by hand from the table in crooks-assistant/app/observability/pad.py.
     *
     * Sixteen names and no others. Thirteen are §16's own list; the last three are appliance
     * facts the Control app needs and the Mac's table admits by name. Every other pad_* spelling
     * anybody has ever written — `pad_foreground`, `pad_background`, `pad_state`,
     * `pad_state_changed`, `pad_battery_changed` — IS GONE, because two spellings of one event
     * is how a timeline ends up with half of a device's history under each.
     */
    val BACKEND_KINDS: Set<String> = setOf(
        "pad_app_started",
        "pad_app_foreground",
        "pad_app_background",
        "pad_webview_loaded",
        "pad_webview_error",
        "pad_network_changed",
        "pad_backend_reachable",
        "pad_backend_unreachable",
        "pad_mic_permission",
        "pad_renderer_crash",
        "pad_admin_entered",
        "pad_admin_exited",
        "pad_version",
        "pad_battery",
        "pad_kiosk_stage",
        "pad_navigation_blocked",
    )

    /**
     * A copy, by hand, of every field name the Mac's pad table will keep.
     *
     * Only the subset the pad uses is listed. Copying only what is used means this list can be
     * read as "what a pad event says" rather than as a mirror to be kept in sync wholesale.
     */
    val BACKEND_ALLOWED_FIELDS: Set<String> = setOf(
        "kind", "t", "session_id", "state", "code", "reason", "detail", "name", "mode", "via",
        "status", "ms", "elapsed_ms", "count", "reachable", "offline", "seq", "error_kind",
        "phase", "outcome", "label", "action", "target", "id", "from", "to", "message",
        // The three appliance facts added in Phase 6, with the field names the Mac's table
        // names for them and no others.
        "percent", "charging", "stage", "host",
    )

    val SPECS: Map<String, Set<String>> = mapOf(
        // Once per process. Carries the device snapshot's non-identifying parts so that every
        // later event can be read against a known tablet without repeating itself.
        "pad_app_started" to setOf("name", "detail", "mode", "count", "state"),
        // Lifecycle. `state` is "foreground"/"background"; `elapsed_ms` is how long the other
        // way round lasted, which is what tells a screen-off from a genuine backgrounding.
        // The names are pad_app_* and not pad_*: one spelling, the Mac's.
        "pad_app_foreground" to setOf("state", "elapsed_ms"),
        "pad_app_background" to setOf("state", "elapsed_ms"),
        // The workspace arrived. `mode` is "confirmed" or "assumed" — see ConnectionMachine;
        // this is the field that says which measurement was actually taken.
        "pad_webview_loaded" to setOf("mode", "ms", "state"),
        "pad_webview_error" to setOf("code", "reason", "error_kind", "state"),
        "pad_network_changed" to setOf("state", "reachable", "offline"),
        "pad_backend_reachable" to setOf("state", "ms", "detail"),
        "pad_backend_unreachable" to setOf("state", "reason", "count"),
        "pad_mic_permission" to setOf("outcome", "reason", "state"),
        "pad_renderer_crash" to setOf("reason", "count", "state"),
        "pad_admin_entered" to setOf("via"),
        "pad_admin_exited" to setOf("via", "elapsed_ms", "action"),
        "pad_version" to setOf("name", "detail", "mode"),
        // `percent` is bucketed by [PadBattery.bucket] before it gets here, and the kind is a
        // TRANSITION_KIND, so a tablet discharging normally produces about twenty of these a
        // day rather than one per percent. §18: meaningful transitions only.
        "pad_battery" to setOf("percent", "charging"),
        "pad_kiosk_stage" to setOf("stage"),
        // A navigation the shell refused. The Mac's table names one field, `host`, and the
        // shell sends the HOST AND NOTHING ELSE: no scheme, no port, no path, no query. A
        // CROOKS path can carry an order number or a message id; a host cannot carry anything
        // but the name of the place the tablet was nearly sent to, which is the fact worth
        // having. [hostOnly] is the only way a value reaches this field.
        "pad_navigation_blocked" to setOf("host"),
    )

    fun allows(kind: String): Boolean = kind in SPECS

    fun fieldsFor(kind: String): Set<String> = SPECS[kind].orEmpty()
}

/**
 * §18's anti-spam rule for the battery, expressed as arithmetic rather than as a promise.
 *
 * The Android battery broadcast arrives every time the level moves by one percent. Emitting a
 * pad_battery for each would be a hundred events per discharge and is exactly what "do NOT spam
 * battery ticks" forbids. Bucketing to five, combined with pad_battery being a transition kind,
 * makes the event fire about twenty times between full and flat — which is what somebody asking
 * "is that pad on its charger" actually wants — and makes it impossible for a caller to defeat
 * the rule by passing the raw number, because the raw number never reaches the event.
 */
object PadBattery {
    const val BUCKET = 5

    /** null when the level is not known yet, which is the state before the first broadcast. */
    fun bucket(percent: Int): Int? {
        if (percent < 0) return null
        return (percent.coerceAtMost(100) / BUCKET) * BUCKET
    }
}

/**
 * Reduces any URL to its host, and to nothing else. The only way a value may reach
 * `pad_navigation_blocked`'s `host` field. Null for anything that is not a URL the shell's own
 * parser accepts, which means a blocked address it cannot parse contributes no field at all
 * rather than contributing attacker-shaped text.
 */
fun hostOnly(url: String?): String? = UrlParser.origin(url)?.host

/**
 * Reduces any URL to its origin. Used before a URL-shaped value may go into an event at all.
 * A CROOKS path can carry an order number or a message id; an origin cannot carry anything.
 */
fun originOnly(url: String?): String? = UrlParser.origin(url)?.toString()

class PadTelemetry(
    private val sink: (PadEvent) -> Unit,
    private val dedupeWindowMs: Long = DEDUPE_WINDOW_MS,
) {

    companion object {
        const val DEDUPE_WINDOW_MS: Long = 10_000

        /** Kinds whose point is the transition, not the value. */
        private val TRANSITION_KINDS = setOf(
            "pad_network_changed", "pad_backend_reachable", "pad_backend_unreachable",
            "pad_app_foreground", "pad_app_background", "pad_battery",
        )
    }

    private val lastTransitionKey = HashMap<String, String>()
    private val lastEmittedAt = HashMap<String, Long>()

    var emitted: Int = 0
        private set
    var suppressed: Int = 0
        private set
    var rejected: Int = 0
        private set

    /**
     * Shape, filter and possibly emit. Returns the event that went to the sink, or null when
     * nothing did — and the three counters say which of the three reasons applied, so that
     * "telemetry is quiet" can be told apart from "telemetry is broken" in diagnostics.
     */
    fun record(kind: String, fields: Map<String, Any?> = emptyMap(), now: Long): PadEvent? {
        if (!PadEventSpec.allows(kind)) { rejected++; return null }
        val allowed = PadEventSpec.fieldsFor(kind)
        val shaped = LinkedHashMap<String, Any?>()
        for ((key, value) in fields) {
            if (key !in allowed) continue
            if (value == null) continue
            shaped[key] = bound(value)
        }

        if (kind in TRANSITION_KINDS) {
            val key = shaped.entries.joinToString("|") { "${it.key}=${it.value}" }
            if (lastTransitionKey[kind] == key) { suppressed++; return null }
            lastTransitionKey[kind] = key
        } else {
            val key = kind + "|" + shaped.entries.joinToString("|") { "${it.key}=${it.value}" }
            val last = lastEmittedAt[key]
            if (last != null && now - last < dedupeWindowMs) { suppressed++; return null }
            lastEmittedAt[key] = now
        }

        val event = PadEvent(kind, shaped + mapOf("t" to now))
        emitted++
        sink(event)
        return event
    }

    /**
     * Values are bounded here rather than trusted. The Mac bounds them too, at 2000
     * characters, but a shell that sends a megabyte and relies on the far end to trim it is a
     * shell that will one day be pointed at something that does not trim.
     */
    private fun bound(value: Any): Any = when (value) {
        is String -> if (value.length > 200) value.take(200) + "…" else value
        is Boolean, is Int, is Long, is Double, is Float -> value
        is Enum<*> -> value.name.lowercase()
        else -> value.toString().take(200)
    }
}
