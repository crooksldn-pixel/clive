package com.crooks.pad.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The connection machine, and in particular the two lies §26 warns about.
 *
 * Read `ping alone never reaches ONLINE` and `a 502 is not a successful load` first: those two
 * tests are the reason this class exists rather than a handful of booleans in an Activity.
 */
class ConnectionMachineTest {

    private fun machine(now: Long = 0L, lastConnected: Long? = null) = ConnectionMachine(now, lastConnected)

    @Test fun `it starts by connecting, not by claiming anything`() {
        val m = machine()
        assertEquals(PadState.CONNECTING, m.status.state)
        assertNotNull("a connecting pad must be counting down to something", m.status.nextRetryAt)
    }

    @Test fun `ping alone never reaches ONLINE`() {
        // §26, literally: "tablet connected vs backend merely reachable". /ping succeeding
        // means a process is bound to a port. The owner cannot ask that anything. If this
        // assertion ever has to be relaxed, the product has been broken, not the test.
        val m = machine()
        m.on(Event.ProbeSucceeded(build = "abc", uptimeSeconds = 5000.0), 1_000)
        assertEquals(PadState.CONNECTING, m.status.state)
        assertFalse(m.status.state.showsWorkspace)
    }

    @Test fun `only a loaded workspace reaches ONLINE`() {
        val m = machine()
        m.on(Event.ProbeSucceeded("abc", 5000.0), 1_000)
        m.on(Event.PageLoaded(PageOutcome.READY_CONFIRMED), 2_000)
        assertEquals(PadState.ONLINE, m.status.state)
        assertEquals(2_000L, m.status.lastConnectedAt)
        assertEquals(0, m.status.attempt)
        assertNull("ONLINE must not be counting down to a retry", m.status.nextRetryAt)
        assertFalse(m.status.readinessAssumed)
    }

    @Test fun `a load that could not be confirmed still connects but says so`() {
        // The honesty clause. The weaker measurement is taken — a pad that refused to work
        // because an element was renamed would be a worse product — and the fact that it is
        // the weaker measurement is carried on the status, shown in diagnostics and recorded.
        val m = machine()
        m.on(Event.PageLoaded(PageOutcome.READY_ASSUMED), 2_000)
        assertEquals(PadState.ONLINE, m.status.state)
        assertTrue("the shell must remember that it assumed rather than confirmed", m.status.readinessAssumed)
    }

    /**
     * THE REPLAY. §26: "app launched vs CROOKS loaded".
     *
     * The old version of this test stopped one callback too early. It fed the machine
     * `PageLoaded(HTTP_ERROR)` and asserted CROOKS_OS_UNHEALTHY — which the machine has always
     * done correctly — and then stopped, because the ordering of Chromium's callbacks was not
     * part of anything it modelled. Chromium does not stop there. For a main-frame 502 it fires
     *
     *     onPageStarted  ->  onReceivedHttpError(502)  ->  onPageFinished
     *
     * and the shell's `onPageFinished` path used to treat that third callback as the start of
     * an ordinary successful load: arm the readiness probe, ask the 502's error body whether
     * the CROOKS workspace is in it, get no for six seconds, take READY_ASSUMED — and reach
     * ONLINE. A test that never delivers the third callback cannot see any of that, and this
     * one delivers all three, in the order the tablet delivers them.
     *
     * The only thing this test does that the shell does not is the three-line `when` below,
     * which maps a [LoadDecision] onto the machine. PadActivity has the same three lines, and
     * PadHardeningTest reads its source to check that it still does.
     */
    @Test fun `a 502 is not a successful load, through the whole Chromium callback sequence`() {
        val m = machine()
        val guard = PageLoadGuard()
        m.on(Event.ProbeSucceeded("abc", 5000.0), 1_000)

        // loadWorkspace()
        guard.shellStartedLoad()
        // onPageStarted
        m.on(Event.PageLoadStarted, 1_500)

        // onReceivedHttpError(502) on the main frame.
        val failure = guard.mainFrameFailed(PageOutcome.HTTP_ERROR)
        assertEquals(LoadDecision.Settle(PageOutcome.HTTP_ERROR), failure)
        m.on(Event.PageLoaded(PageOutcome.HTTP_ERROR), 2_000)
        assertEquals(PadState.CROOKS_OS_UNHEALTHY, m.status.state)

        // onPageFinished — fired by Chromium for the 502's error body exactly as for the real
        // page. THIS is the callback the old test never delivered.
        assertEquals(
            "a load that has already reported a main-frame failure must be poisoned: " +
                "onPageFinished must not be able to re-arm the readiness probe for it",
            LoadDecision.Ignore,
            guard.pageFinished(fromTrustedOrigin = true),
        )

        // And if the readiness probe is asked anyway, six seconds of a 502 body that does not
        // contain the CROOKS marker must not become READY_ASSUMED.
        assertEquals(
            LoadDecision.Ignore,
            guard.readinessAnswered(crooksIsThere = false, deadlinePassed = true),
        )

        // The pad is still telling the truth about the tablet in the owner's hands.
        assertEquals(PadState.CROOKS_OS_UNHEALTHY, m.status.state)
        assertFalse("a 502 must never leave the pad claiming to be showing the workspace", m.status.state.showsWorkspace)
    }

    @Test fun `the poison is scoped to the load, so the next load can still recover`() {
        // The other half of the fix. Poisoning the WebView for ever would turn one bad gateway
        // into a pad that never comes back until somebody restarts it by hand — a worse bug
        // than the one being fixed, and the one that a careless version of this fix produces.
        val m = machine()
        val guard = PageLoadGuard()

        guard.shellStartedLoad()
        m.on(Event.PageLoadStarted, 1_000)
        guard.mainFrameFailed(PageOutcome.HTTP_ERROR)
        m.on(Event.PageLoaded(PageOutcome.HTTP_ERROR), 1_100)
        guard.pageFinished(fromTrustedOrigin = true)
        assertEquals(PadState.CROOKS_OS_UNHEALTHY, m.status.state)

        // The Mac comes back, the shell loads the workspace again, and the page is really there.
        guard.shellStartedLoad()
        m.on(Event.PageLoadStarted, 30_000)
        assertEquals(LoadDecision.AskWhetherCrooksIsThere, guard.pageFinished(fromTrustedOrigin = true))
        assertEquals(
            LoadDecision.Settle(PageOutcome.READY_CONFIRMED),
            guard.readinessAnswered(crooksIsThere = true, deadlinePassed = false),
        )
        m.on(Event.PageLoaded(PageOutcome.READY_CONFIRMED), 31_000)
        assertEquals(PadState.ONLINE, m.status.state)
        assertFalse("a recovered load is confirmed, not assumed", m.status.readinessAssumed)
    }

    @Test fun `a transport failure that arrives while the readiness probe is running still poisons`() {
        // The reverse ordering. Chromium is not contractually obliged to deliver the error
        // before onPageFinished, and on a slow tailnet an ERR_CONNECTION_RESET for the main
        // frame can land while the shell is already polling the document. The load is poisoned
        // either way, so the poll cannot promote it afterwards.
        val guard = PageLoadGuard()
        guard.shellStartedLoad()
        assertEquals(LoadDecision.AskWhetherCrooksIsThere, guard.pageFinished(fromTrustedOrigin = true))
        assertEquals(LoadDecision.AskAgainShortly, guard.readinessAnswered(crooksIsThere = false, deadlinePassed = false))

        guard.mainFrameFailed(PageOutcome.TRANSPORT_ERROR)

        assertEquals(
            "the readiness poll must not outlive the failure of the load it is polling",
            LoadDecision.Ignore,
            guard.readinessAnswered(crooksIsThere = false, deadlinePassed = true),
        )
    }

    @Test fun `a page that finishes on an untrusted origin is never asked about readiness`() {
        val guard = PageLoadGuard()
        guard.shellStartedLoad()
        assertEquals(LoadDecision.Ignore, guard.pageFinished(fromTrustedOrigin = false))
    }

    @Test fun `no network beats no Mac, because the thing to go and touch is different`() {
        val m = machine()
        m.on(Event.NetworkChanged(online = false, transport = Transport.NONE), 1_000)
        assertEquals(PadState.NETWORK_OFFLINE, m.status.state)
        // And a probe failing while there is no network must not start accusing the Mac.
        m.on(Event.ProbeFailed(ProbeFailure.UNREACHABLE), 2_000)
        assertEquals(PadState.NETWORK_OFFLINE, m.status.state)
    }

    @Test fun `an unreachable Mac with a working network is MAC OFFLINE`() {
        val m = machine()
        m.on(Event.NetworkChanged(true, Transport.WIFI), 500)
        m.on(Event.ProbeFailed(ProbeFailure.UNREACHABLE), 1_000)
        assertEquals(PadState.MAC_OFFLINE, m.status.state)
    }

    @Test fun `a Mac that answers badly is UNHEALTHY, not OFFLINE`() {
        // Process up, application not serving — the distinction §26 asks for by name.
        val m = machine()
        m.on(Event.ProbeFailed(ProbeFailure.BAD_ANSWER), 1_000)
        assertEquals(PadState.CROOKS_OS_UNHEALTHY, m.status.state)
    }

    @Test fun `a Mac that has just come up is STARTING, not broken`() {
        val m = machine()
        m.on(Event.ProbeSucceeded("abc", uptimeSeconds = 3.0), 1_000)
        assertEquals(PadState.CROOKS_OS_STARTING, m.status.state)
        m.on(Event.ProbeSucceeded("abc", uptimeSeconds = 40.0), 30_000)
        assertEquals(PadState.CONNECTING, m.status.state)
    }

    @Test fun `the network coming back resets the ladder so the Mac is asked at once`() {
        // THE FAILURE THIS EXISTS FOR: the owner walks in, turns the Mac on, picks the tablet
        // up, and the pad is half a minute into a thirty-second sleep. "Turn the Mac on and
        // do nothing else" must not mean "and then wait".
        val m = machine()
        m.on(Event.NetworkChanged(true, Transport.WIFI), 0)
        repeat(6) { i -> m.on(Event.ProbeFailed(ProbeFailure.UNREACHABLE), (i + 1) * 1_000L) }
        assertEquals(6, m.status.attempt)
        assertEquals(Backoff.MAX_DELAY_MS, m.status.nextRetryAt!! - 6_000L)

        m.on(Event.NetworkChanged(false, Transport.NONE), 7_000)
        m.on(Event.NetworkChanged(true, Transport.WIFI), 8_000)
        assertEquals(PadState.CONNECTING, m.status.state)
        assertEquals(0, m.status.attempt)
        assertEquals(8_000L + Backoff.delayMs(0), m.status.nextRetryAt)
    }

    @Test fun `Retry resets the ladder, so the button visibly does something`() {
        val m = machine()
        repeat(6) { i -> m.on(Event.ProbeFailed(ProbeFailure.UNREACHABLE), (i + 1) * 1_000L) }
        m.on(Event.RetryRequested, 10_000)
        assertEquals(PadState.CONNECTING, m.status.state)
        assertEquals(0, m.status.attempt)
        assertEquals(10_000L + Backoff.delayMs(0), m.status.nextRetryAt)
    }

    @Test fun `coming back to the foreground resets the ladder without changing the state`() {
        val m = machine()
        repeat(4) { i -> m.on(Event.ProbeFailed(ProbeFailure.UNREACHABLE), (i + 1) * 1_000L) }
        assertEquals(PadState.MAC_OFFLINE, m.status.state)
        val sinceBefore = m.status.since
        m.on(Event.Resumed, 20_000)
        assertEquals(PadState.MAC_OFFLINE, m.status.state)
        assertEquals("the state has not changed, so neither should its age", sinceBefore, m.status.since)
        assertEquals(0, m.status.attempt)
    }

    @Test fun `one missed poll does not tear the workspace away from under the owner`() {
        // The page has its own connection and its own opinion about it. A single failed /ping
        // while the owner is mid-sentence must not replace the screen with a recovery card.
        val m = machine()
        m.on(Event.PageLoaded(PageOutcome.READY_CONFIRMED), 1_000)
        m.on(Event.ProbeFailed(ProbeFailure.UNREACHABLE), 2_000)
        assertEquals(PadState.ONLINE, m.status.state)
    }

    @Test fun `a renderer crash is recovered, and a crash loop is not recovered forever`() {
        // §11: handle onRenderProcessGone or the app dies. And §17: a pad that flickers CROOKS
        // at the owner every eight seconds and never arrives is the infinite spinner wearing
        // an expensive costume.
        val m = machine()
        m.on(Event.PageLoaded(PageOutcome.READY_CONFIRMED), 1_000)
        m.on(Event.RendererGone(didCrash = true), 2_000)
        assertEquals(PadState.CONNECTING, m.status.state)

        m.on(Event.RendererGone(true), 3_000)
        assertEquals(PadState.CONNECTING, m.status.state)

        m.on(Event.RendererGone(true), 4_000)
        assertEquals(PadState.APP_ERROR, m.status.state)
        assertEquals("renderer_crash_loop", m.status.errorDetail)
    }

    @Test fun `crashes far apart do not add up to a loop`() {
        val m = machine()
        m.on(Event.RendererGone(true), 0)
        m.on(Event.RendererGone(true), 60_000)
        m.on(Event.RendererGone(true), 200_000)
        assertEquals(PadState.CONNECTING, m.status.state)
    }

    @Test fun `a successful load forgives the crash history`() {
        val m = machine()
        m.on(Event.RendererGone(true), 0)
        m.on(Event.RendererGone(true), 1_000)
        m.on(Event.PageLoaded(PageOutcome.READY_CONFIRMED), 2_000)
        m.on(Event.RendererGone(true), 3_000)
        assertEquals(PadState.CONNECTING, m.status.state)
    }

    @Test fun `APP ERROR is terminal and does not retry`() {
        val m = machine()
        m.on(Event.ConfigInvalid("the configured CROOKS address is not https"), 1_000)
        assertEquals(PadState.APP_ERROR, m.status.state)
        assertNull("a broken installation must not spin forever", m.status.nextRetryAt)
        // A network blip must not hide a broken installation behind an ordinary recovery card.
        m.on(Event.NetworkChanged(false, Transport.NONE), 2_000)
        m.on(Event.NetworkChanged(true, Transport.WIFI), 3_000)
        m.on(Event.RetryRequested, 4_000)
        assertEquals(PadState.APP_ERROR, m.status.state)
    }

    @Test fun `UPDATE REQUIRED is terminal too`() {
        val m = machine()
        m.on(Event.UpdateRequired("0.2.0"), 1_000)
        assertEquals(PadState.UPDATE_REQUIRED, m.status.state)
        assertNull(m.status.nextRetryAt)
        m.on(Event.PageLoaded(PageOutcome.READY_CONFIRMED), 2_000)
        assertEquals("a stale shell must not be able to load its way out of being stale", PadState.UPDATE_REQUIRED, m.status.state)
    }

    @Test fun `a certificate failure is filed against the Mac and named`() {
        val m = machine()
        m.on(Event.PageLoaded(PageOutcome.SSL_ERROR), 1_000)
        assertEquals(PadState.CROOKS_OS_UNHEALTHY, m.status.state)
        assertEquals("certificate", m.status.errorDetail)
    }

    @Test fun `a transport failure after the Mac has answered blames the Mac, not the Wi-Fi`() {
        val m = machine()
        m.on(Event.ProbeSucceeded("abc", 5000.0), 1_000)
        m.on(Event.PageLoaded(PageOutcome.TRANSPORT_ERROR), 2_000)
        assertEquals(PadState.CROOKS_OS_UNHEALTHY, m.status.state)
    }

    @Test fun `a transport failure before the Mac has ever answered blames the Mac being off`() {
        val m = machine()
        m.on(Event.PageLoaded(PageOutcome.TRANSPORT_ERROR), 2_000)
        assertEquals(PadState.MAC_OFFLINE, m.status.state)
    }

    @Test fun `a probe that answers proves there is a network whatever the callback said`() {
        // Samsung's connectivity stack can leave a network marked unvalidated during a
        // captive-portal check while it is perfectly usable. Evidence beats notification.
        val m = machine()
        m.on(Event.NetworkChanged(false, Transport.NONE), 1_000)
        assertEquals(PadState.NETWORK_OFFLINE, m.status.state)
        m.on(Event.ProbeSucceeded("abc", 5000.0), 2_000)
        assertTrue(m.networkIsOnline())
        assertEquals(PadState.CONNECTING, m.status.state)
    }

    /** Drive a fresh machine into [target] and hand back its status. */
    private fun drive(target: PadState): PadStatus {
        val m = machine()
        when (target) {
            PadState.CONNECTING -> Unit
            PadState.ONLINE -> m.on(Event.PageLoaded(PageOutcome.READY_CONFIRMED), 1_000)
            PadState.MAC_OFFLINE -> m.on(Event.ProbeFailed(ProbeFailure.UNREACHABLE), 1_000)
            PadState.NETWORK_OFFLINE -> m.on(Event.NetworkChanged(false, Transport.NONE), 1_000)
            PadState.CROOKS_OS_STARTING -> m.on(Event.ProbeSucceeded("b", 2.0), 1_000)
            PadState.CROOKS_OS_UNHEALTHY -> m.on(Event.ProbeFailed(ProbeFailure.BAD_ANSWER), 1_000)
            PadState.UPDATE_REQUIRED -> m.on(Event.UpdateRequired("9.9.9"), 1_000)
            PadState.APP_ERROR -> m.on(Event.ConfigInvalid("bad address"), 1_000)
        }
        assertEquals("the test helper failed to reach $target", target, m.status.state)
        return m.status
    }

    @Test fun `every state either counts down or is terminal, and none is a bare spinner`() {
        // §17's no-infinite-spinner rule, enforced over the whole enum by actually DRIVING the
        // machine into each state rather than by reading the enum's own opinion of itself. A
        // state added later cannot quietly become a spinner: it has to be reachable here, and
        // when it is, it must either schedule its own next attempt or offer something to press.
        for (state in PadState.entries) {
            val status = drive(state)
            val card = RecoveryCards.forState(state)
            if (state == PadState.ONLINE) {
                assertNull("ONLINE draws nothing and waits for nothing", status.nextRetryAt)
                continue
            }
            if (state.retriesAutomatically) {
                assertNotNull("$state retries, so it must know when", status.nextRetryAt)
                assertTrue("$state's card must agree that it retries", card.retriesAutomatically)
            } else {
                assertNull("$state is terminal, so it must not pretend to be counting down", status.nextRetryAt)
                assertTrue("$state does not retry, so it must offer something to press", card.actions.isNotEmpty())
            }
        }
    }
}
