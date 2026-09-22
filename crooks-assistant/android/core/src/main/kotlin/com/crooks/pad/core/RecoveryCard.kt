package com.crooks.pad.core

/**
 * CROOKS Pad — what the recovery card offers, for each state.
 *
 * The wording lives in res/values/strings.xml, where translators and copy changes belong. The
 * STRUCTURE lives here, where it can be tested, because the structure is where §17's rule
 * gets broken: "each with clear meaning, minimal useful action, automatic retry where
 * appropriate. No infinite meaningless spinners."
 *
 * Two things are asserted about every state by [RecoveryCardTest], and they are the two ways
 * this goes wrong in practice:
 *
 *   1. A state that does not retry by itself MUST offer something to press. Otherwise the pad
 *      is a dead end with a sentence on it.
 *   2. A state that retries by itself MUST show when the next attempt is. A spinner with no
 *      countdown is indistinguishable from a hang, and after about fifteen seconds an owner
 *      correctly concludes that the thing is broken.
 *
 * Diagnostics is on every card. That is deliberate: the recovery card is the only screen the
 * owner can reach when nothing works, and burying the one screen that explains why behind an
 * admin PIN would be a fine way to guarantee that nobody ever reads it. Diagnostics is
 * read-only and shows nothing secret — see DiagnosticsReport.
 */

enum class RecoveryAction {
    /** Try now. Resets the backoff ladder, so it visibly does something. */
    RETRY,

    /** The read-only diagnostics screen. No PIN. */
    DIAGNOSTICS,

    /** Ask Android for the microphone. Only on the microphone card. */
    REQUEST_MICROPHONE,

    /** Open Android's app settings, for a permission that has been refused permanently. */
    OPEN_APP_SETTINGS,
}

data class RecoveryCard(
    val state: PadState,
    /** True when the pad is counting down to its own next attempt. */
    val retriesAutomatically: Boolean,
    /** In order. First is the prominent one. */
    val actions: List<RecoveryAction>,
)

object RecoveryCards {

    fun forState(state: PadState): RecoveryCard = when (state) {
        PadState.ONLINE ->
            // Never drawn. Present so that `forState` is total and a future state cannot be
            // added without deciding what its card is.
            RecoveryCard(state, retriesAutomatically = false, actions = emptyList())

        PadState.CONNECTING, PadState.CROOKS_OS_STARTING ->
            RecoveryCard(state, retriesAutomatically = true, actions = listOf(RecoveryAction.DIAGNOSTICS))

        PadState.MAC_OFFLINE, PadState.NETWORK_OFFLINE, PadState.CROOKS_OS_UNHEALTHY ->
            RecoveryCard(
                state,
                retriesAutomatically = true,
                actions = listOf(RecoveryAction.RETRY, RecoveryAction.DIAGNOSTICS),
            )

        PadState.UPDATE_REQUIRED, PadState.APP_ERROR ->
            // No automatic retry — retrying a broken installation forever is the spinner in
            // disguise — so there must be something to press, and there is.
            RecoveryCard(
                state,
                retriesAutomatically = false,
                actions = listOf(RecoveryAction.RETRY, RecoveryAction.DIAGNOSTICS),
            )
    }

    /**
     * The countdown line. Rounds UP, so a card never says "Retrying in 0s" for a second while
     * nothing happens — the one number that makes a countdown feel broken.
     */
    fun secondsUntilRetry(nextRetryAt: Long?, now: Long): Int? {
        if (nextRetryAt == null) return null
        val remaining = nextRetryAt - now
        if (remaining <= 0) return 0
        return ((remaining + 999) / 1000).toInt()
    }
}

/**
 * The diagnostics screen's contents, assembled here so that what it may and may not contain is
 * one reviewable list rather than a scattering of `append` calls in a view.
 *
 * §28: no tokens, no keys, no environment. The address is here because it is a tailnet
 * hostname the owner already knows and because "which Mac is this pad pointed at" is the
 * first question of any real support conversation.
 */
data class DiagnosticsReport(
    val appVersion: String,
    val padState: PadState,
    val stateForMs: Long,
    val attempt: Int,
    val lastConnectedAt: Long?,
    val readinessAssumed: Boolean,
    val crooksOrigin: String,
    val backendBuild: String?,
    val backendUptimeS: Double?,
    val networkOnline: Boolean,
    val transport: Transport,
    val deviceModel: String,
    val androidRelease: String,
    val apiLevel: Int,
    val kiosk: KioskReadiness,
    val micPermission: OsMicPermission,
    val telemetryEmitted: Int,
    val telemetrySuppressed: Int,
    val telemetryRejected: Int,
    /** Events waiting for the next §16 beat, and events the bounded queue had to drop. */
    val telemetryQueued: Int,
    val telemetryDropped: Int,
    /** §16. How the appliance's own "I am here" is going, and whose number the cadence is. */
    val heartbeatsSent: Long,
    val heartbeatsAnswered: Long,
    val heartbeatIntervalS: Int,
    val heartbeatCadenceFromBackend: Boolean,
    val recentEvents: List<String>,
)
