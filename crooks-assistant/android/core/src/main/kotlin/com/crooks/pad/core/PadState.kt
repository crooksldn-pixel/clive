package com.crooks.pad.core

/**
 * CROOKS Pad — §17, the eight things the pad can be.
 *
 * Each state exists because it demands a *different* response from the owner. That is the
 * test for whether a state deserves to exist at all: if two situations ask the same thing of
 * the person holding the tablet, they are one state with two causes, and splitting them only
 * makes the pad harder to read across a workroom.
 *
 * And §17's other rule, which is the one that is easy to lose: no infinite meaningless
 * spinners. Every state below either retries by itself — and says when the next attempt is —
 * or offers exactly one thing to do. A state that does neither is a bug in this file.
 */
enum class PadState {

    /**
     * We are trying. The Mac has not said no; it has not said yes yet either. Shown as the
     * CROOKS launch path on the first attempt of a process and as the recovery card after
     * that, because "Starting CROOKS OS…" is reassuring the first time and a lie the fourth.
     */
    CONNECTING,

    /**
     * CROOKS is up and the owner is using it. THE SHELL IS INVISIBLE HERE — §19. Nothing
     * native is drawn, no banner, no badge, no toast. This is the only state in which the
     * WebView is the whole screen.
     */
    ONLINE,

    /**
     * The tablet has a network; the Mac is not answering. Almost always: the Mac is asleep or
     * off. The useful action is not on the tablet at all, so the card says so in one line and
     * keeps retrying, so that turning the Mac on is genuinely the only step.
     */
    MAC_OFFLINE,

    /**
     * The tablet has no network. Distinct from MAC_OFFLINE because the thing to go and touch
     * is different, and because the pad must not accuse the Mac of being off when it cannot
     * see anything at all. Precedence: this beats MAC_OFFLINE always.
     */
    NETWORK_OFFLINE,

    /**
     * The Mac answered, and told us it has only just come up. A distinct state because a
     * pad that says "CROOKS Mac is off" three seconds after the owner pressed the Mac's power
     * button is wrong in a way that teaches the owner to distrust it.
     */
    CROOKS_OS_STARTING,

    /**
     * The Mac answers `/ping` — the process is alive — but the workspace will not load or
     * `/health` will not answer. Process up, application not serving. This is the state §26
     * warns about in its own vocabulary: "process reported started vs genuinely healthy". The
     * pad is the only thing in the system positioned to notice the difference, so it has a
     * name for it.
     */
    CROOKS_OS_UNHEALTHY,

    /**
     * This shell is older than the Mac will work with. The pad stops pretending and says so,
     * because a subtly incompatible pad producing subtly wrong screens is worse than a pad
     * that has stopped.
     */
    UPDATE_REQUIRED,

    /**
     * Something about this tablet's own installation is wrong — a start address that is not a
     * CROOKS address, a WebView that will not initialise, a renderer that has crashed
     * repeatedly. Terminal: it does not retry, because retrying a broken installation forever
     * is the infinite spinner wearing a different hat. Diagnostics and admin are still
     * reachable.
     */
    APP_ERROR,
    ;

    /** Does the pad keep trying on its own, or is it waiting for a person? */
    val retriesAutomatically: Boolean
        get() = when (this) {
            CONNECTING, MAC_OFFLINE, NETWORK_OFFLINE, CROOKS_OS_STARTING, CROOKS_OS_UNHEALTHY -> true
            ONLINE, UPDATE_REQUIRED, APP_ERROR -> false
        }

    /** Is the web layer the thing on screen? True for exactly one state, and that is the point. */
    val showsWorkspace: Boolean get() = this == ONLINE
}

/**
 * Which single layer of the shell is on screen.
 *
 * §7 IS WHY THIS IS AN ENUM AND NOT A SET OF BOOLEANS. In Phase 4, sixty-three ordinary
 * control taps became voice recordings because a transparent full-viewport surface sat over
 * the controls. The native shell has exactly the same shape of opportunity — a recovery view
 * that was made invisible rather than removed, a launch view left at alpha 0 — and exactly
 * the same consequence, except that in the native layer the WebView underneath would receive
 * nothing at all and the pad would look frozen.
 *
 * So the shell cannot express "two layers at once". [ShellLayer] is one value, and the Android
 * layer's only job is to show the one it names.
 *
 * There is one asymmetry in how that is done, and it is worth writing down because it looks
 * like an inconsistency and is not. THE OVERLAY LAYERS — launch, recovery, admin — are set to
 * View.GONE when they are not the named layer, never INVISIBLE and never alpha 0. They sit
 * ABOVE the web layer, so an overlay that is merely not drawn is an overlay that still eats
 * every touch in the product: the Phase 4 defect exactly, in the one place JavaScript cannot
 * argue with it. GONE is the word that matters, because a GONE view is not laid out and
 * cannot receive a pointer.
 *
 * THE WEB LAYER, by contrast, is set to INVISIBLE rather than GONE while it is loading. It is
 * the bottom layer, so nothing is underneath it to steal from, and it MUST keep its real size
 * while it loads: a WebView laid out at zero by zero reports `window.innerWidth` as 0, which
 * takes every CSS media query and every layout measurement in the web layer with it. So it
 * keeps its bounds, stops being drawn, and — because an INVISIBLE child is skipped by
 * ViewGroup's touch dispatch just as a GONE one is — receives nothing.
 */
enum class ShellLayer {
    /** The CROOKS wordmark and the startup line. First connection of the process only. */
    LAUNCH,

    /** The web layer, alone, full screen, with nothing over it. */
    WEB,

    /** A CROOKS-native card explaining a state and offering at most two things to do. */
    RECOVERY,

    /** The admin sheet. Reached only through the hardware-key gesture and a PIN. */
    ADMIN,

    /**
     * The read-only diagnostics screen. Reachable from every recovery card WITHOUT a PIN,
     * which is deliberate: it is the one screen that explains why nothing is working, and
     * putting it behind the admin PIN would guarantee that nobody ever reads it at the moment
     * it would help. It shows nothing secret — [DiagnosticsReport] is the exhaustive list of
     * what it may contain.
     */
    DIAGNOSTICS,
}

object ShellVisibility {

    /**
     * @param hasEverConnected whether this process has shown the workspace at least once —
     *   which is what separates "starting up" from "lost it and getting it back".
     *
     * Precedence is admin, then diagnostics, then the state's own layer. Admin wins because it
     * is the only screen someone deliberately asked for with a gesture and a PIN, and a
     * connection state changing under them must not throw them out of it mid-PIN.
     */
    fun layerFor(
        state: PadState,
        adminOpen: Boolean,
        hasEverConnected: Boolean,
        diagnosticsOpen: Boolean = false,
        micExplanationPending: Boolean = false,
    ): ShellLayer {
        if (adminOpen) return ShellLayer.ADMIN
        if (diagnosticsOpen) return ShellLayer.DIAGNOSTICS
        // §8 against §19, and §8 wins for as long as the card is up.
        //
        // A microphone refusal happens while everything else is working perfectly: the owner
        // holds the orb, says a sentence, and NOTHING HAPPENS. The page cannot explain it —
        // from inside the document a refused getUserMedia is indistinguishable from a
        // microphone that is not there — so if the shell stays invisible here, the product's
        // answer to "CROOKS cannot hear me" is silence, and the owner learns that the
        // microphone is unreliable. That is the worst thing that can happen to a voice
        // product, and it is exactly what §8 means by "not silent failure".
        //
        // So this is the one case where the shell covers a healthy workspace uninvited. It is
        // dismissible, and dismissing it returns the pad to WEB immediately.
        if (micExplanationPending) return ShellLayer.RECOVERY
        return when (state) {
            PadState.ONLINE -> ShellLayer.WEB
            PadState.CONNECTING -> if (hasEverConnected) ShellLayer.RECOVERY else ShellLayer.LAUNCH
            PadState.CROOKS_OS_STARTING -> if (hasEverConnected) ShellLayer.RECOVERY else ShellLayer.LAUNCH
            PadState.MAC_OFFLINE,
            PadState.NETWORK_OFFLINE,
            PadState.CROOKS_OS_UNHEALTHY,
            PadState.UPDATE_REQUIRED,
            PadState.APP_ERROR -> ShellLayer.RECOVERY
        }
    }
}
