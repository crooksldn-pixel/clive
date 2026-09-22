package com.crooks.pad

import android.webkit.ConsoleMessage
import android.webkit.JsResult
import android.webkit.PermissionRequest
import android.webkit.WebChromeClient
import android.webkit.WebView
import com.crooks.pad.core.MediaResource
import com.crooks.pad.core.MicDecision
import com.crooks.pad.core.MicPermissionPolicy
import com.crooks.pad.core.MicRequest
import com.crooks.pad.core.OsMicPermission

/**
 * CROOKS Pad — the microphone, the dialogs that are not shown, and the console.
 *
 * The decision about who may hold the microphone is in [MicPermissionPolicy] in `:core`, where
 * it is tested. This file is the Android plumbing, plus the three `WebChromeClient` overrides
 * that exist purely to make sure Chromium never draws anything of its own on a CROOKS screen.
 */
class PadWebChromeClient(
    private val policy: MicPermissionPolicy,
    private val listener: Listener,
) : WebChromeClient() {

    interface Listener {
        fun osMicrophonePermission(): OsMicPermission
        fun onMicrophoneDenied(reason: String, canAskAgain: Boolean)
        fun onMicrophoneGranted()
        fun onMicrophoneRefusedToUntrustedOrigin(reason: String)
    }

    override fun onPermissionRequest(request: PermissionRequest) {
        val resources = request.resources.map { resource ->
            when (resource) {
                PermissionRequest.RESOURCE_AUDIO_CAPTURE -> MediaResource.AUDIO_CAPTURE
                PermissionRequest.RESOURCE_VIDEO_CAPTURE -> MediaResource.VIDEO_CAPTURE
                PermissionRequest.RESOURCE_MIDI_SYSEX -> MediaResource.MIDI_SYSEX
                PermissionRequest.RESOURCE_PROTECTED_MEDIA_ID -> MediaResource.PROTECTED_MEDIA_ID
                else -> MediaResource.OTHER
            }
        }.toSet()

        val outcome = policy.decide(
            MicRequest(
                // `request.origin` is a Uri such as "https://host/". The allow-list's parser
                // handles that shape; there is deliberately no second, looser origin check
                // anywhere in this application.
                origin = request.origin?.toString(),
                resources = resources,
                osPermission = listener.osMicrophonePermission(),
            )
        )

        when (outcome.decision) {
            MicDecision.GRANT -> {
                // The granted set comes from the policy, NOT from `request.resources`. The
                // usual shape of this bug is `request.grant(request.resources)` once the
                // answer is yes, which hands over the camera to any page that asked for both.
                request.grant(arrayOf(PermissionRequest.RESOURCE_AUDIO_CAPTURE))
                listener.onMicrophoneGranted()
            }
            MicDecision.DENY_EXPLAIN -> {
                request.deny()
                listener.onMicrophoneDenied(outcome.reason, canAskAgain = outcome.reason == "os_denied_can_ask")
            }
            MicDecision.DENY_SILENT -> {
                request.deny()
                listener.onMicrophoneRefusedToUntrustedOrigin(outcome.reason)
            }
        }
    }

    override fun onPermissionRequestCanceled(request: PermissionRequest) {
        // Nothing to undo: the shell holds no state between the request and the answer.
    }

    /**
     * The three dialogs Chromium draws by default, all refused.
     *
     * A `window.alert` on a CROOKS screen renders a Chromium dialog with the ORIGIN IN ITS
     * TITLE — "crooks-assistant.taildfb357.ts.net says". That is a URL on screen, in a product
     * whose §6.2 requirement is that the owner never has reason to know a WebView is involved.
     * The web layer has its own notes surface and uses it; nothing in CROOKS calls these.
     * Returning true means "handled", and handling consists of confirming the result the page
     * would have got from a dismissed dialog and drawing nothing.
     */
    override fun onJsAlert(view: WebView?, url: String?, message: String?, result: JsResult?): Boolean {
        result?.confirm()
        return true
    }

    override fun onJsConfirm(view: WebView?, url: String?, message: String?, result: JsResult?): Boolean {
        result?.cancel()
        return true
    }

    override fun onJsBeforeUnload(view: WebView?, url: String?, message: String?, result: JsResult?): Boolean {
        result?.confirm()
        return true
    }

    /**
     * Console messages are dropped on the floor in release and in debug alike.
     *
     * Not forwarded to logcat, and deliberately so: the page logs order numbers, customer
     * names and email subjects while it works, and logcat is world-readable to anything with
     * ADB and, on older firmware, to other applications. Invariant 10 — PII stays out of
     * telemetry — is not satisfied by keeping PII out of the telemetry endpoint while pouring
     * it into the system log.
     */
    override fun onConsoleMessage(message: ConsoleMessage?): Boolean = true
}
