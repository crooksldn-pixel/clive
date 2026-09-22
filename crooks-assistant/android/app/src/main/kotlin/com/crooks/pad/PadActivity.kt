package com.crooks.pad

import android.Manifest
import android.app.Activity
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.KeyEvent
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import android.webkit.WebStorage
import android.webkit.WebView
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.crooks.pad.core.AdminGestureRecogniser
import com.crooks.pad.core.AdminPhase
import com.crooks.pad.core.AdminSession
import com.crooks.pad.core.ConnectionMachine
import com.crooks.pad.core.DeviceSnapshot
import com.crooks.pad.core.DiagnosticsReport
import com.crooks.pad.core.Event
import com.crooks.pad.core.Heartbeat
import com.crooks.pad.core.KioskCapability
import com.crooks.pad.core.LoadDecision
import com.crooks.pad.core.MicPermissionPolicy
import com.crooks.pad.core.NavigationPolicy
import com.crooks.pad.core.OsMicPermission
import com.crooks.pad.core.PadConfig
import com.crooks.pad.core.PadState
import com.crooks.pad.core.PadBattery
import com.crooks.pad.core.PadTelemetry
import com.crooks.pad.core.PageLoadGuard
import com.crooks.pad.core.PageOutcome
import com.crooks.pad.core.PinHasher
import com.crooks.pad.core.PinLockout
import com.crooks.pad.core.PinPolicy
import com.crooks.pad.core.PinVerdict
import com.crooks.pad.core.RecoveryAction
import com.crooks.pad.core.RecoveryCards
import com.crooks.pad.core.ShellLayer
import com.crooks.pad.core.ShellVisibility
import com.crooks.pad.core.hostOnly
import com.crooks.pad.core.Transport
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID

/**
 * CROOKS Pad — the shell.
 *
 * This class owns the Android side of everything and decides nothing. Every judgement — what
 * state the pad is in, whether an address may be loaded, when to try again, whether the
 * microphone may be granted, what a telemetry event may say, whether the PIN was right — is
 * made by `:core`, which runs on a plain JVM and is tested on the build machine. What is here
 * is lifecycle, views and hardware, none of which can be exercised without a tablet, and all
 * of which is therefore kept as thin and as boring as it can be made.
 *
 * §19 IS THE ORGANISING IDEA. When CROOKS is healthy, this class draws NOTHING. No banner, no
 * badge, no status pip, no toast. The web layer fills the screen and the shell is a frame that
 * the owner has no reason to think about. It earns visibility in five situations and gives it
 * straight back: launching, disconnected, updating, recovering, being administered.
 */
class PadActivity : Activity(),
    PadWebViewClient.Listener,
    PadWebChromeClient.Listener,
    DeviceFacts.Listener {

    private lateinit var config: PadConfig.Valid
    private lateinit var machine: ConnectionMachine
    private lateinit var prefs: PadPrefs
    private lateinit var facts: DeviceFacts
    private lateinit var probe: BackendProbe
    private lateinit var telemetry: PadTelemetry
    private lateinit var sink: TelemetrySink

    /**
     * CONTRACT 1 / §16. The appliance's own "I am here", and the only thing on this tablet that
     * decides how often it says it — by not deciding, and reading `interval_s` off every answer.
     */
    private lateinit var heartbeat: Heartbeat

    /**
     * Fresh every launch, and deliberately nothing else. It lets the Mac tell one long uptime
     * from six restarts this morning. Because it changes on every launch it is not a device
     * identifier, which is exactly why it is safe to send.
     */
    private val bootId: String = UUID.randomUUID().toString()
    private lateinit var navigationPolicy: NavigationPolicy
    private lateinit var micPolicy: MicPermissionPolicy

    private val handler = Handler(Looper.getMainLooper())
    private val gesture = AdminGestureRecogniser()
    private val admin = AdminSession()
    private val lockout = PinLockout()

    private var web: WebView? = null
    private var webClient: PadWebViewClient? = null

    private var adminOpen = false
    private var diagnosticsOpen = false
    private var micDenialToShow: String? = null
    private var micCanAskAgain = true
    private var lastBackendBuild: String? = null
    private var lastBackendUptime: Double? = null
    private var loadStartedAt = 0L
    private var lastResumeAt = 0L
    private var lastPauseAt = 0L
    private var foreground = false
    private var readinessDeadlineAt = 0L

    /**
     * §26. Which load is in flight and whether it may still be believed. Every rule about that
     * lives in `:core` — see [PageLoadGuard], and the test that replays Chromium's real callback
     * order for a 502 — because a rule about a WebView callback that lives in an Activity is a
     * rule this build machine cannot run.
     */
    private val loadGuard = PageLoadGuard()

    /**
     * The state, mirrored for the bridge. `DeviceBridge.snapshot()` is called on the WebView's
     * JavaScript thread, not the main thread, so it must not read a plain `var` that the main
     * thread writes — the comment in DeviceBridge promises it reads volatile fields, and this
     * is the field that makes the promise true.
     */
    @Volatile private var stateForBridge: String = PadState.CONNECTING.name

    /**
     * True when the configured CROOKS address is not usable, which means nothing beyond the
     * APP ERROR card was ever constructed. Guards every path that would touch a `lateinit`
     * field that was never assigned — most importantly the admin gesture, which would
     * otherwise reach diagnostics and crash on the first uninitialised field it read.
     */
    private var configBroken = false

    // ------------------------------------------------------------------ lifecycle

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_pad)

        prefs = PadPrefs(this)
        machine = ConnectionMachine(now(), prefs.lastConnectedAt)

        // Debugging is switched by build type and by nothing else. §6.4.
        PadWebViewFactory.applyProcessWideDebugging()

        // The address is validated BEFORE a WebView exists. A configured address that is not a
        // CROOKS https origin is a broken installation, and the worst available outcome is a
        // CROOKS-branded screen that will never finish loading with nothing saying why.
        when (val parsed = PadConfig.parse(BuildConfig.CROOKS_ORIGIN)) {
            is PadConfig.Valid -> config = parsed
            is PadConfig.Invalid -> {
                // Enough of the shell is set up to draw the APP ERROR card and diagnostics, and
                // nothing more is created: no WebView, no probe, no network callbacks.
                configBroken = true
                setUpFailedConfig(parsed.reason)
                return
            }
        }

        navigationPolicy = NavigationPolicy(config.allowList)
        micPolicy = MicPermissionPolicy(config.allowList)
        probe = BackendProbe(config.origin.toString())
        sink = TelemetrySink()
        telemetry = PadTelemetry(sink = { sink.accept(it) })
        facts = DeviceFacts(this)
        heartbeat = Heartbeat(
            appVersion = BuildConfig.VERSION_NAME,
            deviceModel = facts.deviceModel,
            osVersion = "Android ${facts.androidRelease} (api ${facts.apiLevel})",
            bootId = bootId,
        )

        wireControls()
        createWebView()
        facts.start(this)

        // The screen stays on while CROOKS is showing. §11. A fixture on a counter that has
        // gone black is a fixture whose first question of the afternoon begins with a tap to
        // wake it, and then a tap to dismiss whatever Android put there. The owner can still
        // use the power button, and onResume handles coming back.
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        record(
            "pad_app_started",
            mapOf(
                "name" to "CROOKS Pad ${BuildConfig.VERSION_NAME}",
                "detail" to "${facts.deviceModel} Android ${facts.androidRelease} api ${facts.apiLevel}",
                "mode" to KioskCapability.ENABLED_STAGE.name.lowercase(),
            ),
        )
        record("pad_version", mapOf("name" to BuildConfig.VERSION_NAME, "detail" to BuildConfig.VERSION_CODE.toString()))
        record("pad_kiosk_stage", mapOf("stage" to KioskCapability.ENABLED_STAGE.name.lowercase()))

        render()
        handler.post(tick)
    }

    override fun onResume() {
        super.onResume()
        foreground = true
        lastResumeAt = now()
        applyImmersive()
        if (!::config.isInitialized) return
        web?.onResume()
        web?.resumeTimers()
        val away = if (lastPauseAt > 0) lastResumeAt - lastPauseAt else 0L
        record("pad_app_foreground", mapOf("state" to "foreground", "elapsed_ms" to away))
        // Coming back is one of the three "the world has just changed" events: the owner has
        // physically picked the tablet up, so the pad asks again immediately rather than
        // finishing whatever backoff it was in the middle of.
        apply(Event.Resumed)
    }

    override fun onPause() {
        super.onPause()
        foreground = false
        lastPauseAt = now()
        if (!::config.isInitialized) return
        record("pad_app_background", mapOf("state" to "background", "elapsed_ms" to (lastPauseAt - lastResumeAt)))
        // One last beat on the way out, so the events of the session just ending are on the Mac
        // rather than waiting in a queue on a tablet that may not come back for hours.
        sendHeartbeat()
        apply(Event.Paused)
        // Timers are NOT paused and the WebView is NOT suspended here. The web layer may be
        // mid-turn with an answer arriving, and a shell that freezes the page because the
        // screen turned off would produce exactly the "first question of the afternoon fails"
        // failure the whole appliance layer exists to remove.
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        if (::facts.isInitialized) facts.stop()
        if (::probe.isInitialized) probe.shutdown()
        destroyWebView()
        super.onDestroy()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) applyImmersive()
    }

    /**
     * Back does nothing. §6.2: no accidental navigation out.
     *
     * The web layer owns its own navigation — it has a cursor, a Back chip and a Home chip,
     * all of which are its business — and the hardware/gesture Back in a WebView shell means
     * "go back in HISTORY", which on the last page means "leave the application". On an
     * appliance that is never what anybody wanted.
     */
    @Deprecated("Back is deliberately inert on the pad; see the comment.")
    override fun onBackPressed() {
        when {
            adminOpen -> closeAdmin("back")
            diagnosticsOpen -> { diagnosticsOpen = false; render() }
            else -> Unit   // nothing. Not finish(), not web.goBack().
        }
    }

    /**
     * §12, the admin gesture: six alternating volume presses.
     *
     * THE PRESSES ARE OBSERVED AND NOT CONSUMED — `super` is called and its answer returned —
     * which is the whole reason this is the right gesture. The volume genuinely changes as
     * they are pressed, so an owner adjusting the volume is not fighting the shell; the
     * sequence is volume-neutral, so performing it leaves the volume where it was; and no
     * touch event is involved anywhere, so §7's class of defect — an invisible surface
     * stealing control taps — cannot be reproduced by it at all.
     */
    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        // Not on a broken installation. The address is compiled into the build, so there is
        // nothing admin could change about it, and the reason is already the only thing on
        // screen. Opening the sheet there would reach a diagnostics screen whose every field
        // belongs to a shell that was never constructed.
        if (!configBroken && gesture.onKeyDown(keyCode, event.repeatCount > 0, now())) openAdmin()
        return super.onKeyDown(keyCode, event)
    }

    // ------------------------------------------------------------------ the web layer

    private fun createWebView() {
        destroyWebView()
        val view = PadWebViewFactory.create(this)
        val client = PadWebViewClient(navigationPolicy, this)
        view.webViewClient = client
        view.webChromeClient = PadWebChromeClient(micPolicy, this)
        view.addJavascriptInterface(DeviceBridge { snapshot() }, DeviceBridge.JS_NAME)
        findViewById<android.widget.FrameLayout>(R.id.web_host).addView(
            view,
            android.widget.FrameLayout.LayoutParams(
                android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
                android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
            ),
        )
        web = view
        webClient = client
        loadWorkspace()
    }

    private fun destroyWebView() {
        val view = web ?: return
        web = null
        webClient = null
        runCatching {
            (view.parent as? android.view.ViewGroup)?.removeView(view)
            view.stopLoading()
            view.webChromeClient = null
            view.removeJavascriptInterface(DeviceBridge.JS_NAME)
            view.destroy()
        }
    }

    private fun loadWorkspace() {
        val view = web ?: return
        loadStartedAt = now()
        loadGuard.shellStartedLoad()
        view.loadUrl(config.startUrl)
    }

    /**
     * Called after every successful probe. The guard exists because of a loop that is easy to
     * write and hard to see: while CROOKS OS is STARTING the probe succeeds every second, and
     * an unguarded `loadWorkspace()` on each success would reload the page once a second for
     * as long as the Mac took to come up — a pad flashing CROOKS at the owner while the Mac
     * boots, which looks exactly like the thing being broken.
     *
     * So: never while a load is already in flight, never while the Mac says it is still coming
     * up, and never when the workspace is already there.
     */
    private fun loadWorkspaceIfItIsTimeTo() {
        if (loadGuard.loadInFlight || loadGuard.awaitingReadiness) return
        when (machine.status.state) {
            PadState.ONLINE, PadState.CROOKS_OS_STARTING, PadState.APP_ERROR, PadState.UPDATE_REQUIRED -> return
            else -> loadWorkspace()
        }
    }

    private fun currentLayer(): ShellLayer = ShellVisibility.layerFor(
        state = machine.status.state,
        adminOpen = adminOpen,
        hasEverConnected = machine.hasEverConnected(),
        diagnosticsOpen = diagnosticsOpen,
        micExplanationPending = micDenialToShow != null,
    )

    override fun onNavigationAllowed(url: String) = Unit

    override fun onNavigationBlocked(url: String, reason: String) {
        // The HOST and nothing else — no scheme, no port, no path, no query — because the
        // Mac's table names exactly one field for this event and because a blocked address is
        // attacker-controlled text. [hostOnly] is the only route a value takes to get here, and
        // an address the shell's own parser will not accept contributes no field at all.
        // `reason` is offered and will be DROPPED: the Mac's table names `host` for this event
        // and PadTelemetry builds the outgoing map from the declaration and nothing else. It is
        // passed rather than deleted so that the call site still says what the shell knows, and
        // so that it starts arriving by itself if the Mac's table ever admits it.
        record("pad_navigation_blocked", mapOf("host" to hostOnly(url), "reason" to reason))
    }

    override fun onNavigationDeferred(url: String) {
        record("pad_webview_error", mapOf("code" to "deferred", "reason" to "no_network"))
    }

    override fun onPageStarted(url: String) {
        apply(Event.PageLoadStarted)
    }

    override fun onPageFinished(url: String) {
        // §26, the second lie: onPageFinished fires for a 502's error body exactly as it fires
        // for the real page — AND CHROMIUM FIRES IT AFTER THE ERROR CALLBACK, so this used to
        // be the line that handed a bad gateway back to the readiness probe and from there to
        // ONLINE. The guard refuses a load that has already failed; see PageLoadGuard.
        obey(loadGuard.pageFinished(config.allowList.allows(url)))
    }

    private fun askWhetherCrooksIsReallyThere() {
        val view = web ?: return
        view.evaluateJavascript(PadWebViewFactory.READINESS_EXPRESSION) { answer ->
            obey(loadGuard.readinessAnswered(answer == "true", now() >= readinessDeadlineAt))
        }
    }

    /**
     * The shell's whole part in deciding how a load went: carry out what [PageLoadGuard] says.
     * There is no `if` here about outcomes, error codes or readiness, because every one of
     * those is a judgement and judgements live in `:core` where they can be run.
     */
    private fun obey(decision: LoadDecision) {
        when (decision) {
            LoadDecision.Ignore -> Unit
            LoadDecision.AskWhetherCrooksIsThere -> {
                readinessDeadlineAt = now() + READINESS_DEADLINE_MS
                askWhetherCrooksIsReallyThere()
            }
            // The page may still be assembling itself. Ask again shortly.
            LoadDecision.AskAgainShortly ->
                handler.postDelayed({ askWhetherCrooksIsReallyThere() }, READINESS_POLL_MS)
            is LoadDecision.Settle -> finishLoad(decision.outcome)
        }
    }

    private fun finishLoad(outcome: PageOutcome) {
        if (outcome == PageOutcome.READY_CONFIRMED || outcome == PageOutcome.READY_ASSUMED) {
            record(
                "pad_webview_loaded",
                mapOf(
                    "mode" to if (outcome == PageOutcome.READY_CONFIRMED) "confirmed" else "assumed",
                    "ms" to (now() - loadStartedAt),
                ),
            )
        }
        apply(Event.PageLoaded(outcome))
        prefs.lastConnectedAt = machine.status.lastConnectedAt
    }

    override fun onMainFrameHttpError(status: Int) {
        record("pad_webview_error", mapOf("code" to status.toString(), "error_kind" to "http"))
        obey(loadGuard.mainFrameFailed(PageOutcome.HTTP_ERROR))
    }

    override fun onMainFrameTransportError(code: Int, description: String) {
        record("pad_webview_error", mapOf("code" to code.toString(), "error_kind" to "transport"))
        obey(loadGuard.mainFrameFailed(PageOutcome.TRANSPORT_ERROR))
    }

    override fun onCertificateError(primaryError: Int) {
        record("pad_webview_error", mapOf("code" to primaryError.toString(), "error_kind" to "certificate"))
        obey(loadGuard.mainFrameFailed(PageOutcome.SSL_ERROR))
    }

    override fun onRendererGone(didCrash: Boolean) {
        record("pad_renderer_crash", mapOf("reason" to if (didCrash) "crashed" else "reclaimed"))
        // A WebView whose renderer has gone is permanently dead: every method on it throws. The
        // only recovery is to throw it away and build another, which is what the web_host
        // container in the layout exists for.
        apply(Event.RendererGone(didCrash))
        if (machine.status.state != PadState.APP_ERROR) createWebView()
    }

    override fun networkIsOnline(): Boolean = machine.networkIsOnline()

    // ------------------------------------------------------------------ the microphone

    override fun osMicrophonePermission(): OsMicPermission = when {
        checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED ->
            OsMicPermission.GRANTED
        // shouldShowRequestPermissionRationale is false BOTH before the first ask and after a
        // permanent refusal, so it is only meaningful once a refusal has happened. The shell
        // treats "never asked" as can-ask, which is right: the prompt will appear.
        shouldShowRequestPermissionRationale(Manifest.permission.RECORD_AUDIO) ->
            OsMicPermission.DENIED_CAN_ASK
        micAskedOnce -> OsMicPermission.DENIED_PERMANENTLY
        else -> OsMicPermission.DENIED_CAN_ASK
    }

    private var micAskedOnce = false

    override fun onMicrophoneGranted() {
        micDenialToShow = null
        record("pad_mic_permission", mapOf("outcome" to "granted", "reason" to "trusted_origin_audio"))
    }

    override fun onMicrophoneDenied(reason: String, canAskAgain: Boolean) {
        // §8: never silent. The owner asked CROOKS to listen and it did not; a pad that simply
        // does nothing teaches the owner that the microphone is unreliable, which is the worst
        // thing that can happen to a voice product.
        record("pad_mic_permission", mapOf("outcome" to "denied", "reason" to reason))
        micDenialToShow = reason
        micCanAskAgain = canAskAgain
        render()
    }

    override fun onMicrophoneRefusedToUntrustedOrigin(reason: String) {
        // Silent to the owner, loud here. Showing a microphone explanation for this would
        // train the owner to grant a microphone to whatever asked.
        record("pad_mic_permission", mapOf("outcome" to "refused", "reason" to reason))
    }

    private fun askAndroidForTheMicrophone() {
        micAskedOnce = true
        requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), REQUEST_MIC)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != REQUEST_MIC) return
        val granted = grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED
        record("pad_mic_permission", mapOf("outcome" to if (granted) "granted" else "denied", "reason" to "os_prompt"))
        if (granted) {
            micDenialToShow = null
            // The page's getUserMedia call has already failed by now, so the workspace is
            // reloaded to put it back in a state where voice will work on the next hold.
            loadGuard.shellStartedLoad()
            web?.reload()
        }
        render()
    }

    // ------------------------------------------------------------------ connectivity

    override fun onNetworkChanged(online: Boolean, transport: Transport) {
        record("pad_network_changed", mapOf("state" to transport.name.lowercase(), "reachable" to online))
        apply(Event.NetworkChanged(online, transport))
        if (online) {
            // A navigation that was deferred because there was no network is taken now rather
            // than lost — §6.3's "never a Chromium error page" only works if the deferred load
            // actually happens afterwards.
            webClient?.takeDeferredUrl()?.let { url ->
                loadGuard.shellStartedLoad()
                web?.loadUrl(url)
            }
        }
    }

    /**
     * The single timer. Probes when the machine says an attempt is due, keeps the countdown on
     * the recovery card honest, expires an abandoned admin sheet, and occasionally asks the
     * Mac whether a test session is running.
     *
     * One timer rather than four, because four timers on a tablet that must survive weeks of
     * uptime is four things to leak and four things to get out of step with each other.
     */
    private val tick = object : Runnable {
        override fun run() {
            handler.postDelayed(this, TICK_MS)
            if (!::config.isInitialized) return
            val now = now()

            if (admin.expireIfIdle(now)) {
                adminOpen = false
                record("pad_admin_exited", mapOf("via" to "idle"))
                render()
            }

            val due = machine.status.nextRetryAt
            if (due != null && now >= due && !probeInFlight) runProbe()

            // A slow `/ping` while everything is working. NOT so the shell can second-guess
            // the page — a failed ping while ONLINE deliberately changes nothing, because the
            // page has its own connection and its own opinion about it — but so that two
            // things stay true: diagnostics knows the Mac's build and uptime when somebody
            // finally looks, and a Mac that has been RESTARTED is noticed, because its uptime
            // resets and the pad's session on the old process is gone.
            if (machine.status.state == PadState.ONLINE && now - lastProbeAt > ONLINE_PING_MS && !probeInFlight) {
                runProbe()
            }

            // §16. The cadence is the Mac's, not this file's: `heartbeat.isDue` is the whole
            // rule, and the number inside it came off the last answer.
            if (heartbeat.isDue(now, lastBeatAt) && !beatInFlight) sendHeartbeat()

            if (currentLayer() == ShellLayer.RECOVERY) renderCountdown()
        }
    }

    private var probeInFlight = false
    private var lastProbeAt = 0L

    private var beatInFlight = false

    /**
     * Zero, so the first tick after launch beats immediately. A pad that waited twenty seconds
     * before announcing itself is a pad that is missing from the Control app for twenty seconds
     * every time it is switched on, which is exactly the moment somebody is looking for it.
     */
    private var lastBeatAt = 0L

    private fun runProbe() {
        probeInFlight = true
        lastProbeAt = now()
        probe.probe { result ->
            handler.post {
                probeInFlight = false
                when (result) {
                    is BackendProbe.Result.Ok -> {
                        lastBackendBuild = result.success.build
                        lastBackendUptime = result.success.uptimeSeconds
                        record("pad_backend_reachable", mapOf("state" to "reachable", "ms" to result.success.elapsedMs))
                        apply(Event.ProbeSucceeded(result.success.build, result.success.uptimeSeconds))
                        loadWorkspaceIfItIsTimeTo()
                    }
                    is BackendProbe.Result.Bad -> {
                        record(
                            "pad_backend_unreachable",
                            mapOf(
                                "state" to "unreachable",
                                "reason" to result.failure.detail,
                                "count" to machine.status.attempt,
                            ),
                        )
                        apply(Event.ProbeFailed(result.failure.failure))
                    }
                }
            }
        }
    }

    /**
     * §16, one beat.
     *
     * WHAT THIS IS NOT: it is not `/telemetry`. That endpoint is the web page's account of
     * itself and is silent outside a test session; an appliance's liveness travelling on it
     * would be invisible almost always. `POST /pad/heartbeat` exists for this, it answers with
     * the cadence for the next beat, and the pad's queued pad_* events ride along with it.
     *
     * IT IS SENT IN EVERY STATE, including MAC_OFFLINE. A beat that fails is the most
     * informative beat there is on the pad's side — it is how [Heartbeat.onBeatFailed] knows to
     * stop claiming a test session — and the cost of trying is one socket on a tailnet.
     *
     * THE CADENCE IS NOT DECIDED HERE. Nothing in this method chooses when the next beat goes;
     * [Heartbeat.isDue] does, using the `interval_s` the Mac put on the last answer.
     */
    private fun sendHeartbeat() {
        if (!::heartbeat.isInitialized) return
        beatInFlight = true
        lastBeatAt = now()
        recordBattery()
        val body = heartbeat.body(lastBeatAt, sink.drain())
        heartbeat.beatSent()
        probe.post(Heartbeat.PATH, body) { answer ->
            handler.post {
                beatInFlight = false
                if (answer == null) {
                    heartbeat.onBeatFailed()
                    return@post
                }
                heartbeat.onAnswer(
                    intervalS = answer.optInt(Heartbeat.KEY_INTERVAL_S, -1).takeIf { it > 0 },
                    testSession = answer.optString(Heartbeat.KEY_TEST_SESSION, ""),
                )
            }
        }
    }

    /**
     * §18's one battery event, offered once per beat and dropped by [PadTelemetry] unless the
     * bucketed level or the charging flag has actually moved. The raw percentage never reaches
     * an event: [PadBattery.bucket] is the only way in.
     */
    private fun recordBattery() {
        val bucket = PadBattery.bucket(facts.batteryPercent) ?: return
        record("pad_battery", mapOf("percent" to bucket, "charging" to facts.charging))
    }

    // ------------------------------------------------------------------ state and drawing

    private fun apply(event: Event) {
        val before = machine.status.state
        val after = machine.on(event, now()).state
        stateForBridge = after.name
        // No `pad_state_changed` event. It was a second spelling of what the pad's own state
        // already is — the Mac reads that from the heartbeat's `state`, and the transitions that
        // matter each have an event of their own — and two spellings of one fact is how a
        // timeline ends up with half a tablet's history under each.
        if (before != after) render()
    }

    /**
     * The one place a view's visibility is set.
     *
     * §7 IS ENFORCED HERE AND NOWHERE ELSE. `ShellVisibility.layerFor` returns ONE layer;
     * everything else is set to GONE — never INVISIBLE, never alpha 0 — because an overlay
     * that is merely undrawn still eats every touch beneath it, which in this shell means
     * every control in the product. The WebView is the exception and is set INVISIBLE rather
     * than GONE, because it is the bottom layer with nothing to steal from and it must keep
     * its real bounds to lay the page out at the tablet's actual viewport.
     */
    private fun render() {
        val status = machine.status
        val layer = currentLayer()

        findViewById<View>(R.id.layer_launch).visibility = if (layer == ShellLayer.LAUNCH) View.VISIBLE else View.GONE
        findViewById<View>(R.id.layer_recovery).visibility = if (layer == ShellLayer.RECOVERY) View.VISIBLE else View.GONE
        findViewById<View>(R.id.layer_admin).visibility = if (layer == ShellLayer.ADMIN) View.VISIBLE else View.GONE
        findViewById<View>(R.id.layer_diagnostics).visibility = if (layer == ShellLayer.DIAGNOSTICS) View.VISIBLE else View.GONE
        web?.visibility = if (layer == ShellLayer.WEB) View.VISIBLE else View.INVISIBLE

        when (layer) {
            ShellLayer.LAUNCH -> renderLaunch(status.state)
            ShellLayer.RECOVERY -> renderRecovery()
            ShellLayer.ADMIN -> renderAdmin()
            ShellLayer.DIAGNOSTICS -> findViewById<TextView>(R.id.diagnostics_text).text = diagnosticsText()
            ShellLayer.WEB -> Unit   // §19: when healthy, the shell draws nothing at all.
        }
    }

    private fun renderLaunch(state: PadState) {
        // §6.3's branded path. Three lines in order, each true when it is shown: the wordmark
        // first because it is instant, then what the shell is doing, then what it is waiting
        // for. Nothing here is a fake progress bar.
        findViewById<TextView>(R.id.launch_line).setText(
            when (state) {
                PadState.CROOKS_OS_STARTING -> R.string.launch_starting
                else -> if (lastBackendBuild != null) R.string.launch_loading else R.string.launch_connecting
            }
        )
    }

    private fun renderRecovery() {
        val status = machine.status
        val title = findViewById<TextView>(R.id.recovery_title)
        val detail = findViewById<TextView>(R.id.recovery_detail)
        val micButton = findViewById<Button>(R.id.recovery_microphone)

        val dismiss = findViewById<Button>(R.id.recovery_dismiss)
        val denial = micDenialToShow
        if (denial != null) {
            // §8. The owner held the orb, said a sentence and nothing happened; the page
            // cannot explain that, so the shell does. It covers a healthy workspace, which is
            // the one time it does so uninvited, and it closes in one tap.
            title.setText(R.string.state_mic_denied_title)
            detail.setText(
                if (micCanAskAgain) R.string.state_mic_denied_detail else R.string.state_mic_denied_permanent_detail
            )
            micButton.visibility = View.VISIBLE
            dismiss.visibility = View.VISIBLE
            findViewById<TextView>(R.id.recovery_last_seen).text = ""
            findViewById<TextView>(R.id.recovery_countdown).text = ""
            findViewById<Button>(R.id.recovery_retry).visibility = View.GONE
            return
        } else {
            micButton.visibility = View.GONE
            dismiss.visibility = View.GONE
            when (status.state) {
                PadState.MAC_OFFLINE -> { title.setText(R.string.state_mac_offline_title); detail.setText(R.string.state_mac_offline_detail) }
                PadState.NETWORK_OFFLINE -> { title.setText(R.string.state_network_offline_title); detail.setText(R.string.state_network_offline_detail) }
                PadState.CROOKS_OS_STARTING -> { title.setText(R.string.state_starting_title); detail.setText(R.string.state_starting_detail) }
                PadState.CROOKS_OS_UNHEALTHY -> { title.setText(R.string.state_unhealthy_title); detail.setText(R.string.state_unhealthy_detail) }
                PadState.UPDATE_REQUIRED -> { title.setText(R.string.state_update_title); detail.setText(R.string.state_update_detail) }
                PadState.APP_ERROR -> { title.setText(R.string.state_app_error_title); detail.setText(R.string.state_app_error_detail) }
                else -> { title.setText(R.string.launch_connecting); detail.text = "" }
            }
        }

        val card = RecoveryCards.forState(status.state)
        findViewById<Button>(R.id.recovery_retry).visibility =
            if (RecoveryAction.RETRY in card.actions) View.VISIBLE else View.GONE

        findViewById<TextView>(R.id.recovery_last_seen).text =
            status.lastConnectedAt?.let { getString(R.string.last_connected_fmt, clockOf(it)) }
                ?: getString(R.string.last_connected_never)

        renderCountdown()
    }

    /**
     * §17: no infinite meaningless spinners. A pad that is retrying says when, in seconds,
     * counting down — because a spinner with no number is indistinguishable from a hang, and
     * after about fifteen seconds an owner correctly decides the thing is broken.
     */
    private fun renderCountdown() {
        val status = machine.status
        val view = findViewById<TextView>(R.id.recovery_countdown)
        val seconds = RecoveryCards.secondsUntilRetry(status.nextRetryAt, now())
        view.text = when {
            seconds == null -> ""
            probeInFlight || seconds <= 0 -> getString(R.string.retrying_now)
            else -> getString(R.string.retrying_in_fmt, seconds)
        }
    }

    // ------------------------------------------------------------------ admin

    private fun openAdmin() {
        adminOpen = true
        diagnosticsOpen = false
        admin.onGesture(prefs.hasPin, lockout, now())
        record("pad_admin_entered", mapOf("via" to "volume_sequence"))
        render()
    }

    private fun closeAdmin(via: String) {
        val openMs = admin.close(now())
        adminOpen = false
        findViewById<EditText>(R.id.admin_pin).setText("")
        record("pad_admin_exited", mapOf("via" to via, "elapsed_ms" to openMs))
        render()
    }

    private fun renderAdmin() {
        val prompt = findViewById<TextView>(R.id.admin_prompt)
        val pin = findViewById<EditText>(R.id.admin_pin)
        val submit = findViewById<Button>(R.id.admin_submit)
        val tools = findViewById<LinearLayout>(R.id.admin_tools)
        val error = findViewById<TextView>(R.id.admin_error)

        admin.onInteraction(now())
        when (admin.phase) {
            AdminPhase.ENROLLING -> {
                // §28: there is no PIN in the source and no default. A tablet that has not been
                // provisioned has NO admin, not a known one, and the first performance of the
                // gesture is what sets it.
                prompt.setText(R.string.admin_set_pin_detail)
                pin.visibility = View.VISIBLE
                pin.setHint(R.string.admin_set_pin)
                submit.visibility = View.VISIBLE
                tools.visibility = View.GONE
            }
            AdminPhase.ASKING -> {
                prompt.setText(R.string.admin_enter_pin)
                pin.visibility = View.VISIBLE
                pin.setHint(R.string.admin_enter_pin)
                submit.visibility = View.VISIBLE
                tools.visibility = View.GONE
            }
            AdminPhase.LOCKED_OUT -> {
                prompt.text = getString(R.string.admin_pin_locked_fmt, (lockout.remainingMs(now()) / 1000).toInt())
                pin.visibility = View.GONE
                submit.visibility = View.GONE
                tools.visibility = View.GONE
            }
            AdminPhase.OPEN -> {
                prompt.text = ""
                pin.visibility = View.GONE
                submit.visibility = View.GONE
                tools.visibility = View.VISIBLE
                error.visibility = View.GONE
                findViewById<TextView>(R.id.admin_diagnostics_text).text = diagnosticsText()
                findViewById<Button>(R.id.admin_home_role).setText(
                    if (prefs.homeRoleEnabled) R.string.admin_home_role_off else R.string.admin_home_role_on
                )
            }
            AdminPhase.CLOSED -> Unit
        }
    }

    private fun submitPin() {
        val field = findViewById<EditText>(R.id.admin_pin)
        val error = findViewById<TextView>(R.id.admin_error)
        val entered = field.text.toString()
        admin.onInteraction(now())

        fun fail(messageId: Int) {
            error.setText(messageId)
            error.visibility = View.VISIBLE
            field.setText("")
        }

        when (admin.phase) {
            AdminPhase.ENROLLING -> {
                when (PinPolicy.check(entered)) {
                    PinVerdict.TOO_SHORT -> fail(R.string.admin_pin_too_short)
                    PinVerdict.NOT_DIGITS -> fail(R.string.admin_pin_too_short)
                    PinVerdict.TOO_SIMPLE -> fail(R.string.admin_pin_too_simple)
                    PinVerdict.OK -> {
                        prefs.pinHash = PinHasher.encode(entered.toCharArray(), PinHasher.newSalt())
                        field.setText("")
                        error.visibility = View.GONE
                        admin.onUnlocked(now())
                        renderAdmin()
                    }
                }
            }
            AdminPhase.ASKING -> {
                if (lockout.isLocked(now())) { renderAdmin(); return }
                if (PinHasher.verify(entered.toCharArray(), prefs.pinHash)) {
                    lockout.onSuccess()
                    field.setText("")
                    error.visibility = View.GONE
                    admin.onUnlocked(now())
                    renderAdmin()
                } else {
                    val locked = lockout.onFailure(now())
                    fail(R.string.admin_pin_wrong)
                    if (locked) {
                        admin.onGesture(true, lockout, now())
                        renderAdmin()
                    }
                }
            }
            else -> Unit
        }
    }

    private fun wireControls() {
        findViewById<Button>(R.id.recovery_retry).setOnClickListener {
            apply(Event.RetryRequested)
            runProbe()
        }
        findViewById<Button>(R.id.recovery_diagnostics).setOnClickListener {
            diagnosticsOpen = true
            render()
        }
        findViewById<Button>(R.id.recovery_microphone).setOnClickListener {
            if (micCanAskAgain) askAndroidForTheMicrophone() else openAndroidAppSettings()
        }
        findViewById<Button>(R.id.recovery_dismiss).setOnClickListener {
            // The owner may be content to work by touch this afternoon. Dismissing returns the
            // pad to the workspace at once; the card comes back the next time the microphone is
            // actually refused, which is when it is useful rather than when it is nagging.
            micDenialToShow = null
            render()
        }
        findViewById<Button>(R.id.diagnostics_close).setOnClickListener {
            diagnosticsOpen = false
            render()
        }
        findViewById<Button>(R.id.admin_submit).setOnClickListener { submitPin() }
        findViewById<Button>(R.id.admin_close).setOnClickListener { closeAdmin("close") }
        findViewById<Button>(R.id.admin_reconnect).setOnClickListener {
            admin.onInteraction(now())
            apply(Event.RetryRequested)
            runProbe()
        }
        findViewById<Button>(R.id.admin_reload).setOnClickListener {
            admin.onInteraction(now())
            loadWorkspace()
            closeAdmin("reload")
        }
        findViewById<Button>(R.id.admin_clear_cache).setOnClickListener {
            admin.onInteraction(now())
            web?.clearCache(true)
            WebStorage.getInstance().deleteAllData()
            loadWorkspace()
            closeAdmin("clear_cache")
        }
        findViewById<Button>(R.id.admin_home_role).setOnClickListener {
            admin.onInteraction(now())
            toggleHomeRole()
            renderAdmin()
        }
        findViewById<Button>(R.id.admin_exit).setOnClickListener {
            admin.onInteraction(now())
            record("pad_admin_exited", mapOf("via" to "exit_kiosk", "action" to "leave"))
            sendHeartbeat()
            // §13 stage 1: recoverable. Leaving is a real thing the owner can do, and it is
            // finish() rather than anything cleverer precisely so that nothing in this shell
            // can trap a tablet.
            finishAndRemoveTask()
        }
    }

    /**
     * §14, the HOME role. The alias ships DISABLED and is switched on here by someone who has
     * typed the PIN, and off again from the same button.
     *
     * Being the launcher is the only mechanism on an unmanaged tablet that reliably puts an
     * app on screen after a boot — the system starts the home activity itself rather than
     * being asked to, which is why BOOT_COMPLETED alone is best-effort on Samsung's firmware.
     * It is also what makes a tablet hard to get out of, which is why it is behind the PIN and
     * why it is reversible from the same screen.
     */
    private fun toggleHomeRole() {
        val enable = !prefs.homeRoleEnabled
        val component = ComponentName(this, "com.crooks.pad.PadHomeAlias")
        packageManager.setComponentEnabledSetting(
            component,
            if (enable) PackageManager.COMPONENT_ENABLED_STATE_ENABLED else PackageManager.COMPONENT_ENABLED_STATE_DISABLED,
            PackageManager.DONT_KILL_APP,
        )
        prefs.homeRoleEnabled = enable
        if (enable) {
            // Android will not silently make an app the launcher. Enabling the alias only makes
            // it ELIGIBLE; the owner still has to choose it, and sending them to the chooser is
            // the honest thing to do rather than leaving them wondering why nothing happened.
            runCatching { startActivity(Intent(Settings.ACTION_HOME_SETTINGS)) }
        }
    }

    private fun openAndroidAppSettings() {
        runCatching {
            startActivity(
                Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null))
            )
        }
    }

    // ------------------------------------------------------------------ diagnostics

    private fun report(): DiagnosticsReport {
        val status = machine.status
        return DiagnosticsReport(
            appVersion = "${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})",
            padState = status.state,
            stateForMs = now() - status.since,
            attempt = status.attempt,
            lastConnectedAt = status.lastConnectedAt,
            readinessAssumed = status.readinessAssumed,
            crooksOrigin = config.origin.toString(),
            backendBuild = lastBackendBuild,
            backendUptimeS = lastBackendUptime,
            networkOnline = facts.networkOnline,
            transport = facts.transport,
            deviceModel = facts.deviceModel,
            androidRelease = facts.androidRelease,
            apiLevel = facts.apiLevel,
            kiosk = KioskCapability.assess(facts.kioskFacts()),
            micPermission = osMicrophonePermission(),
            telemetryEmitted = telemetry.emitted,
            telemetrySuppressed = telemetry.suppressed,
            telemetryRejected = telemetry.rejected,
            telemetryQueued = sink.queued(),
            telemetryDropped = sink.dropped,
            heartbeatsSent = heartbeat.beatsSent,
            heartbeatsAnswered = heartbeat.answersSeen,
            heartbeatIntervalS = heartbeat.intervalS,
            heartbeatCadenceFromBackend = heartbeat.cadenceCameFromBackend,
            recentEvents = sink.recent(),
        )
    }

    /**
     * §28: no tokens, no keys, no environment, nothing printed that is secret. The CROOKS
     * address is here because it is a tailnet hostname the owner already knows and because
     * "which Mac is this pad pointed at" is the first question of any real support
     * conversation. [DiagnosticsReport] is the exhaustive list of what may appear.
     */
    private fun diagnosticsText(): String {
        val r = report()
        return buildString {
            appendLine("CROOKS Pad ${r.appVersion}")
            appendLine("state      ${r.padState} for ${r.stateForMs / 1000}s, attempt ${r.attempt}")
            appendLine("last seen  ${r.lastConnectedAt?.let { clockOf(it) } ?: "never"}")
            if (r.readinessAssumed) {
                // The honest line. ONLINE was reached on the weaker signal, and the pad says so
                // rather than letting a renamed element look like a healthy connection.
                appendLine("readiness  ASSUMED — the CROOKS workspace marker was not found")
            }
            appendLine("address    ${r.crooksOrigin}")
            appendLine("mac build  ${r.backendBuild ?: "not seen"}${r.backendUptimeS?.let { ", up ${it.toInt()}s" } ?: ""}")
            appendLine("network    ${if (r.networkOnline) "online" else "offline"} via ${r.transport.name.lowercase()}")
            appendLine("tablet     ${r.deviceModel}, Android ${r.androidRelease} (api ${r.apiLevel})")
            appendLine("microphone ${r.micPermission.name.lowercase()}")
            appendLine("kiosk      ${r.kiosk.note}")
            appendLine(
                "telemetry  ${r.telemetryEmitted} emitted, ${r.telemetrySuppressed} suppressed, " +
                    "${r.telemetryRejected} rejected, ${r.telemetryQueued} queued, ${r.telemetryDropped} dropped"
            )
            appendLine(
                "heartbeat  ${r.heartbeatsSent} sent, ${r.heartbeatsAnswered} answered, every " +
                    "${r.heartbeatIntervalS}s " +
                    if (r.heartbeatCadenceFromBackend) "(the Mac's number)" else "(built-in default, the Mac has not answered yet)"
            )
            appendLine()
            for (line in r.recentEvents) appendLine(line)
        }
    }

    // ------------------------------------------------------------------ odds and ends

    /**
     * §13 stage 1. Sticky immersive: no status bar, no navigation bar, and a swipe from an
     * edge brings them back briefly rather than permanently. Reapplied on every focus change
     * because a system dialog, a notification shade pull or a permission prompt all drop it.
     */
    private fun applyImmersive() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.setDecorFitsSystemWindows(false)
            window.insetsController?.let { controller ->
                controller.hide(WindowInsets.Type.statusBars() or WindowInsets.Type.navigationBars())
                controller.systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = (
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                    or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                    or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                    or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                    or View.SYSTEM_UI_FLAG_FULLSCREEN
                    or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                )
        }
    }

    private fun snapshot(): DeviceSnapshot = DeviceSnapshot(
        batteryPercent = facts.batteryPercent,
        charging = facts.charging,
        powerSource = facts.powerSource,
        networkOnline = facts.networkOnline,
        transport = facts.transport,
        wifiSignalBars = facts.wifiSignalBars(),
        deviceModel = facts.deviceModel,
        androidRelease = facts.androidRelease,
        apiLevel = facts.apiLevel,
        appVersionName = BuildConfig.VERSION_NAME,
        appVersionCode = BuildConfig.VERSION_CODE,
        // Fixed portrait — see android/docs/DECISIONS.md — so this is a constant rather than a
        // configuration read. It is reported anyway because the page should not have to know
        // that the shell has made the decision.
        orientation = "portrait",
        foreground = foreground,
        screenOn = true,
        msSinceResume = if (lastResumeAt > 0) now() - lastResumeAt else null,
        padState = stateForBridge,
        testSession = if (::heartbeat.isInitialized) heartbeat.testSessionId else null,
    )

    private fun record(kind: String, fields: Map<String, Any?> = emptyMap()) {
        if (::telemetry.isInitialized) telemetry.record(kind, fields, now())
    }

    private fun setUpFailedConfig(reason: String) {
        // No WebView, no probe, no network callbacks — nothing that could half-work. The
        // recovery card and diagnostics are the whole application in this state.
        machine = ConnectionMachine(now(), null)
        machine.on(Event.ConfigInvalid(reason), now())
        findViewById<View>(R.id.layer_recovery).visibility = View.VISIBLE
        findViewById<TextView>(R.id.recovery_title).setText(R.string.state_app_error_title)
        findViewById<TextView>(R.id.recovery_detail).text = reason
        findViewById<TextView>(R.id.recovery_countdown).text = ""
        findViewById<TextView>(R.id.recovery_last_seen).text = ""
        findViewById<Button>(R.id.recovery_retry).visibility = View.GONE
        findViewById<Button>(R.id.recovery_diagnostics).visibility = View.GONE
        findViewById<ScrollView>(R.id.layer_admin).visibility = View.GONE
        findViewById<ScrollView>(R.id.layer_diagnostics).visibility = View.GONE
    }

    private fun now(): Long = System.currentTimeMillis()

    private fun clockOf(at: Long): String = SimpleDateFormat("HH:mm", Locale.UK).format(Date(at))

    private companion object {
        const val REQUEST_MIC = 4201

        /** How often the single timer runs. One second keeps the countdown honest. */
        const val TICK_MS = 1_000L

        /**
         * How long the shell will keep asking the loaded document whether CROOKS is really
         * there before accepting the weaker "it loaded cleanly" signal. Six seconds is chosen
         * against a cold WebView on a 2019 chip with a service worker to start; beyond that,
         * refusing to show a page that did load is worse than showing it with a note.
         */
        const val READINESS_DEADLINE_MS = 6_000L
        const val READINESS_POLL_MS = 250L

        /**
         * How often `/ping` is asked while the workspace is up and working. Thirty seconds:
         * a few hundred bytes on the same tailnet, which costs the Mac nothing measurable and
         * keeps the diagnostics screen from being a page of dashes at the moment it is needed.
         *
         * This is NOT the §16 heartbeat and must not be confused with it. `/ping` tells the
         * shell about the Mac; the heartbeat tells the Mac about the pad, and its cadence is
         * the Mac's to choose — see [Heartbeat].
         */
        const val ONLINE_PING_MS = 30_000L
    }
}
