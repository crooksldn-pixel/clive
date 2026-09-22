package com.crooks.pad.core

/**
 * CROOKS Pad — the state machine that decides what the pad is, from what the pad has seen.
 *
 * Everything here is pure: facts in, a [PadStatus] out, a clock passed as a number. That is
 * what makes it the one part of the shell this build machine can actually prove, and it is
 * why the Android layer below contains no `if (reachable) showOffline()` of its own — every
 * such decision would be a decision nothing tests.
 *
 * THE §26 LESSON IS THE WHOLE DESIGN OF THIS FILE. "Tablet connected vs backend merely
 * reachable" and "app launched vs CROOKS loaded" are named in the brief as the ways a green
 * light lies, and both are reachable states in a naive shell:
 *
 *   - A pad that calls itself ONLINE because `/ping` answered is measuring that a Python
 *     process is bound to a port. The owner cannot ask it anything.
 *   - A pad that calls itself ONLINE because `onPageFinished` fired is measuring that some
 *     bytes arrived and parsed. A 502 from the reverse proxy fires `onPageFinished` too.
 *
 * So ONLINE is reachable here from exactly one input — [Event.PageLoaded] — and that event
 * carries a [PageOutcome] that the Android layer may only set to READY_CONFIRMED after
 * finding the CROOKS workspace's own elements in the loaded document. `/ping` succeeding
 * moves the pad from "the Mac is off" to "the Mac is there"; it never, by itself, moves it
 * to ONLINE.
 *
 * And the honesty clause. The marker check can fail for an innocent reason — the web layer
 * renames an element and the shell is a version behind. A shell that then sat in CONNECTING
 * forever would be a worse product than one that trusts a clean 200. So READY_ASSUMED exists:
 * it reaches ONLINE, and it sets [PadStatus.readinessAssumed], which diagnostics shows and
 * telemetry records. The weaker measurement is taken, and it SAYS that it is the weaker
 * measurement, which is the rule §26 actually states.
 */

/** How a page load ended. Computed by the Android layer; interpreted only here. */
enum class PageOutcome {
    /** Loaded from a trusted origin AND the CROOKS workspace's own elements were found. */
    READY_CONFIRMED,

    /**
     * Loaded from a trusted origin with a clean status, but the workspace marker was not
     * found before the deadline. Accepted as ONLINE, flagged as assumed, recorded.
     */
    READY_ASSUMED,

    /** The Mac answered the navigation with an error status: 4xx or 5xx on the main frame. */
    HTTP_ERROR,

    /** The load never reached the Mac: DNS, refused, timed out, reset. */
    TRANSPORT_ERROR,

    /** A certificate problem. Never overridden; see PadWebViewClient. */
    SSL_ERROR,
}

/** Why a `/ping` failed. Enough to tell "no route" from "the Mac said no". */
enum class ProbeFailure {
    /** Nothing came back: timeout, refused, DNS, reset. The Mac is off or unreachable. */
    UNREACHABLE,

    /** Something answered but not with a healthy CROOKS answer. The Mac is up; CROOKS is not. */
    BAD_ANSWER,
}

/** What the transport is, for diagnostics and telemetry. Never an SSID; see DeviceSnapshot. */
enum class Transport { WIFI, ETHERNET, CELLULAR, OTHER, NONE }

sealed interface Event {
    data class NetworkChanged(val online: Boolean, val transport: Transport) : Event

    /** `/ping` answered. [uptimeSeconds] is the Mac's, and is what reveals a fresh start. */
    data class ProbeSucceeded(val build: String, val uptimeSeconds: Double) : Event

    data class ProbeFailed(val failure: ProbeFailure) : Event

    /** The WebView has begun loading a CROOKS address. */
    data object PageLoadStarted : Event

    data class PageLoaded(val outcome: PageOutcome) : Event

    /** onRenderProcessGone. §11: handle it or the app dies. */
    data class RendererGone(val didCrash: Boolean) : Event

    /** The Mac says this shell is too old. Not reachable today; see UpdatePolicy. */
    data class UpdateRequired(val minimumVersion: String) : Event

    /** The installation itself is wrong. Terminal. */
    data class ConfigInvalid(val detail: String) : Event

    /** The owner tapped Retry. */
    data object RetryRequested : Event

    /** The app came to the foreground. The owner has just picked the tablet up. */
    data object Resumed : Event

    /** The app went to the background. */
    data object Paused : Event
}

data class PadStatus(
    val state: PadState,
    /** When the pad entered [state], on the injected clock. */
    val since: Long,
    /** Consecutive failed attempts. Reset by success and by the three "world changed" events. */
    val attempt: Int,
    /** The last time this pad saw the workspace, across launches. Null means never. */
    val lastConnectedAt: Long?,
    /** When the next automatic attempt is due, or null when nothing is scheduled. */
    val nextRetryAt: Long?,
    /** ONLINE was reached on the weaker signal. Shown in diagnostics, recorded once. */
    val readinessAssumed: Boolean = false,
    /** Set by ConfigInvalid and by the renderer-crash circuit-breaker. For diagnostics. */
    val errorDetail: String? = null,
)

class ConnectionMachine(
    now: Long,
    lastConnectedAt: Long? = null,
    private val startingUptimeS: Double = STARTING_UPTIME_S,
) {

    companion object {
        /**
         * A Mac whose CROOKS process has been up for less than this is treated as still
         * coming up, rather than as healthy-but-not-serving. Twenty-five seconds is chosen
         * from what the backend actually does at boot: it warms a provider client, reads the
         * Shopify scope table and builds a catalogue before it is much use. The cost of being
         * wrong in this direction is a pad that says "starting" for a few seconds too long;
         * the cost of being wrong in the other direction is a pad that says the Mac is broken
         * while the Mac is starting normally, which is the accusation that destroys trust.
         */
        const val STARTING_UPTIME_S: Double = 25.0

        /**
         * The renderer-crash circuit breaker. A WebView renderer that dies is recoverable —
         * §11 requires that it be recovered — but a renderer that dies three times in two
         * minutes is not a blip, it is a tablet that is out of memory or a WebView that is
         * broken, and reloading it forever is the infinite spinner in its most expensive
         * form: a pad that flickers CROOKS at the owner every eight seconds and never
         * arrives. After the third, the pad stops and says so.
         */
        const val RENDERER_CRASH_LIMIT = 3
        const val RENDERER_CRASH_WINDOW_MS = 120_000L
    }

    /**
     * The first attempt is due immediately — a pad that waits a second before its first probe
     * is a pad that takes a second longer to start, every single time, for no reason. Every
     * attempt after that is due at `now + Backoff.delayMs(attempt)`, and the Android layer's
     * only job is to probe whenever the clock passes [PadStatus.nextRetryAt]. That is why
     * Retry schedules rather than probing directly: one timer, one rule, no double probes.
     */
    var status: PadStatus = PadStatus(
        state = PadState.CONNECTING,
        since = now,
        attempt = 0,
        lastConnectedAt = lastConnectedAt,
        nextRetryAt = now,
    )
        private set

    private var networkOnline = true
    private var macAnswered = false
    private var hasEverConnected = false
    private var rendererCrashes = ArrayDeque<Long>()

    /** True once the workspace has been shown in this process; drives LAUNCH vs RECOVERY. */
    fun hasEverConnected(): Boolean = hasEverConnected

    fun networkIsOnline(): Boolean = networkOnline

    /** Apply an event. Returns the new status, which is also left in [status]. */
    fun on(event: Event, now: Long): PadStatus {
        // Two states are terminal and swallow everything except the events that can legitimately
        // clear them. Letting a network blip move the pad out of APP_ERROR would hide a broken
        // installation behind an ordinary-looking recovery card.
        if (status.state == PadState.APP_ERROR && event !is Event.ConfigInvalid) {
            return status
        }
        if (status.state == PadState.UPDATE_REQUIRED && event !is Event.ConfigInvalid) {
            return status
        }

        return when (event) {
            is Event.ConfigInvalid -> enter(PadState.APP_ERROR, now, attempt = 0, detail = event.detail)

            is Event.UpdateRequired -> enter(PadState.UPDATE_REQUIRED, now, attempt = 0, detail = event.minimumVersion)

            is Event.NetworkChanged -> onNetwork(event, now)

            is Event.ProbeSucceeded -> {
                macAnswered = true
                if (!networkOnline) {
                    // The probe answered, so there is a network whatever the callback said.
                    // Trusting the evidence over the notification matters on Samsung's stack,
                    // where a captive-portal check can leave a network briefly marked
                    // unvalidated while it is perfectly usable.
                    networkOnline = true
                }
                when {
                    event.uptimeSeconds < startingUptimeS -> enter(PadState.CROOKS_OS_STARTING, now, attempt = 0)
                    status.state == PadState.ONLINE -> status
                    else -> enter(PadState.CONNECTING, now, attempt = 0)
                }
            }

            is Event.ProbeFailed -> {
                macAnswered = event.failure == ProbeFailure.BAD_ANSWER
                val next = when {
                    !networkOnline -> PadState.NETWORK_OFFLINE
                    event.failure == ProbeFailure.BAD_ANSWER -> PadState.CROOKS_OS_UNHEALTHY
                    else -> PadState.MAC_OFFLINE
                }
                // A probe failing while the workspace is up and working is not a reason to
                // tear the workspace away from under the owner's hands: the page has its own
                // connection and its own opinion, and one missed poll is not an outage. The
                // pad waits for the page itself to fail.
                if (status.state == PadState.ONLINE) status
                else enter(next, now, attempt = status.attempt + 1)
            }

            is Event.PageLoadStarted ->
                if (status.state == PadState.ONLINE) status
                else enter(PadState.CONNECTING, now, attempt = status.attempt)

            is Event.PageLoaded -> onPageLoaded(event.outcome, now)

            is Event.RendererGone -> onRendererGone(now)

            is Event.RetryRequested ->
                // Retry means "ask again now", so the ladder goes back to the bottom. If it
                // did not, the button would visibly do nothing for half a minute, which is
                // the worst kind of control: one that lies about having worked.
                enter(PadState.CONNECTING, now, attempt = 0)

            is Event.Resumed ->
                if (status.state == PadState.ONLINE) status
                else enter(status.state, now, attempt = 0, keepSince = true)

            is Event.Paused -> status
        }
    }

    private fun onNetwork(event: Event.NetworkChanged, now: Long): PadStatus {
        val was = networkOnline
        networkOnline = event.online
        return when {
            !event.online -> enter(PadState.NETWORK_OFFLINE, now, attempt = status.attempt + 1)
            // Coming back. The world has just changed, so the ladder goes back to its first
            // rung rather than continuing from wherever the outage left it.
            !was -> enter(PadState.CONNECTING, now, attempt = 0)
            else -> status
        }
    }

    private fun onPageLoaded(outcome: PageOutcome, now: Long): PadStatus {
        return when (outcome) {
            PageOutcome.READY_CONFIRMED, PageOutcome.READY_ASSUMED -> {
                hasEverConnected = true
                rendererCrashes.clear()
                status = status.copy(
                    state = PadState.ONLINE,
                    since = now,
                    attempt = 0,
                    lastConnectedAt = now,
                    nextRetryAt = null,
                    readinessAssumed = outcome == PageOutcome.READY_ASSUMED,
                    errorDetail = null,
                )
                status
            }
            PageOutcome.HTTP_ERROR ->
                // The Mac answered the request with an error. The process is there; the
                // application is not serving. That is precisely CROOKS OS UNHEALTHY, and it
                // is a different sentence from "the Mac is off".
                enter(PadState.CROOKS_OS_UNHEALTHY, now, attempt = status.attempt + 1)
            PageOutcome.SSL_ERROR ->
                // Never overridden and never retried into silence. On a tailnet this almost
                // always means the certificate is being reissued, so it retries like any
                // other outage, but it is filed against the Mac rather than the network so
                // diagnostics can name it.
                enter(PadState.CROOKS_OS_UNHEALTHY, now, attempt = status.attempt + 1, detail = "certificate")
            PageOutcome.TRANSPORT_ERROR ->
                enter(
                    if (!networkOnline) PadState.NETWORK_OFFLINE
                    else if (macAnswered) PadState.CROOKS_OS_UNHEALTHY
                    else PadState.MAC_OFFLINE,
                    now,
                    attempt = status.attempt + 1,
                )
        }
    }

    private fun onRendererGone(now: Long): PadStatus {
        rendererCrashes.addLast(now)
        while (rendererCrashes.isNotEmpty() && now - rendererCrashes.first() > RENDERER_CRASH_WINDOW_MS) {
            rendererCrashes.removeFirst()
        }
        if (rendererCrashes.size >= RENDERER_CRASH_LIMIT) {
            return enter(PadState.APP_ERROR, now, attempt = 0, detail = "renderer_crash_loop")
        }
        return enter(PadState.CONNECTING, now, attempt = 0)
    }

    private fun enter(
        state: PadState,
        now: Long,
        attempt: Int,
        detail: String? = null,
        keepSince: Boolean = false,
    ): PadStatus {
        val nextRetry = if (state.retriesAutomatically) now + Backoff.delayMs(attempt) else null
        status = status.copy(
            state = state,
            since = if (keepSince && status.state == state) status.since else now,
            attempt = attempt,
            nextRetryAt = nextRetry,
            readinessAssumed = if (state == PadState.ONLINE) status.readinessAssumed else false,
            errorDetail = detail ?: if (state == status.state) status.errorDetail else null,
        )
        return status
    }
}
