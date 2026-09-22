package com.crooks.pad.core

/**
 * CROOKS Pad — ONE LOAD OF THE WORKSPACE, and whether it may still be believed.
 *
 * WHY THIS IS A CLASS IN `:core` RATHER THAN FOUR FIELDS IN THE ACTIVITY. The shell learns how
 * a load went from five Chromium callbacks that arrive in an order nobody chose, and the answer
 * it has to produce is a single [PageOutcome] for [ConnectionMachine]. That reduction is a
 * decision, and a decision living in an Activity on a build machine with no emulator is a
 * decision nothing can test — which is exactly how the defect below survived review.
 *
 * THE DEFECT THIS FILE EXISTS TO MAKE IMPOSSIBLE. Chromium does not stop at the error callback.
 * For a main-frame 502 it fires, in this order:
 *
 *     onPageStarted  ->  onReceivedHttpError(502)  ->  onPageFinished
 *
 * The shell used to record the error, settle the connection at CROOKS_OS_UNHEALTHY — and then,
 * one callback later, treat `onPageFinished` as the start of an ordinary successful load: arm
 * the readiness probe, ask the 502's error body whether the CROOKS workspace was in it, get no
 * for six seconds, and take READY_ASSUMED, which reaches ONLINE. The owner's tablet showed a
 * reverse-proxy error page while the Mac's health endpoint said the pad was fine. That is §26's
 * lie in its purest form: the green light measured the arrival of bytes.
 *
 * THE FIX IS SCOPED TO THE LOAD, NOT TO THE WebView. A main-frame failure POISONS the load that
 * is in flight and nothing else. `onPageFinished` for a poisoned load is ignored; so is a
 * readiness answer that arrives for one, which also covers the reverse ordering — an error
 * landing while the readiness poll is already running. The poison is lifted by the next load
 * THE SHELL ITSELF STARTS ([shellStartedLoad]), so the ordinary recovery path — probe succeeds,
 * `loadWorkspace()`, page loads cleanly — reaches ONLINE exactly as before. A WebView is never
 * poisoned permanently; only the attempt is.
 *
 * `onPageStarted` deliberately does NOT lift the poison. Chromium fires it for the error page
 * it substitutes after a failed navigation, so treating it as "a fresh load has begun" would
 * hand the poison straight back to the callback sequence that created it.
 */

/** What the shell should do with a WebView callback. The shell obeys; it does not decide. */
sealed interface LoadDecision {
    /** Nothing at all. The callback belongs to a load that is settled, poisoned or untrusted. */
    data object Ignore : LoadDecision

    /** Arm the readiness probe: ask the document whether the CROOKS workspace is really there. */
    data object AskWhetherCrooksIsThere : LoadDecision

    /** The document has not answered yet and the deadline has not passed. Ask again shortly. */
    data object AskAgainShortly : LoadDecision

    /** The load is over. Feed [outcome] to the [ConnectionMachine] and to nothing else. */
    data class Settle(val outcome: PageOutcome) : LoadDecision
}

class PageLoadGuard {

    /** Which load is in flight. Incremented only by [shellStartedLoad]. */
    private var load = 0L

    /**
     * The load a main-frame failure has poisoned. Compared against [load], never against a
     * boolean: that is what makes the poison belong to ONE ATTEMPT rather than to the WebView.
     */
    private var poisonedLoad = -1L

    /** The load whose readiness probe is armed, so a late answer for an older one is ignored. */
    private var armedLoad = -1L

    /** True when the load in flight has already reported a main-frame failure. */
    fun isPoisoned(): Boolean = load == poisonedLoad

    /** True while a load the shell started has neither settled nor failed. */
    var loadInFlight: Boolean = false
        private set

    /** True while the readiness probe is running. */
    var awaitingReadiness: Boolean = false
        private set

    /** The shell has begun a load of the workspace: `loadWorkspace()`, a reload, a deferred url. */
    fun shellStartedLoad() {
        // The poison is lifted here and ONLY here, by the counter moving past it.
        load += 1
        loadInFlight = true
        awaitingReadiness = false
    }

    /**
     * `onReceivedHttpError`, `onReceivedError` or `onReceivedSslError`, main frame only.
     * Sub-frame failures never reach here: a missing image is the page's business.
     */
    fun mainFrameFailed(outcome: PageOutcome): LoadDecision {
        // THE POISON. From here until the shell starts another load, nothing this load does
        // can be read as success — not its onPageFinished, not a readiness answer already in
        // flight for it.
        poisonedLoad = load
        awaitingReadiness = false
        loadInFlight = false
        return LoadDecision.Settle(outcome)
    }

    /** `onPageFinished`. [fromTrustedOrigin] is the allow-list's verdict on the finished url. */
    fun pageFinished(fromTrustedOrigin: Boolean): LoadDecision {
        if (!fromTrustedOrigin) return LoadDecision.Ignore
        // Chromium fires onPageFinished for a 502's error body exactly as it fires it for the
        // real page. Asking that body whether CROOKS is in it, and taking READY_ASSUMED when it
        // says no, is how a bad gateway used to reach ONLINE.
        if (isPoisoned()) return LoadDecision.Ignore
        armedLoad = load
        awaitingReadiness = true
        return LoadDecision.AskWhetherCrooksIsThere
    }

    /** The readiness question came back from the document. */
    fun readinessAnswered(crooksIsThere: Boolean, deadlinePassed: Boolean): LoadDecision {
        if (!awaitingReadiness || armedLoad != load) return LoadDecision.Ignore
        // Belt and braces for the reverse ordering: an error that lands while the poll is
        // already running.
        if (isPoisoned()) { awaitingReadiness = false; return LoadDecision.Ignore }
        return when {
            crooksIsThere -> { settle(); LoadDecision.Settle(PageOutcome.READY_CONFIRMED) }
            deadlinePassed -> { settle(); LoadDecision.Settle(PageOutcome.READY_ASSUMED) }
            else -> LoadDecision.AskAgainShortly
        }
    }

    private fun settle() {
        awaitingReadiness = false
        loadInFlight = false
    }
}
