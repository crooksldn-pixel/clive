package com.crooks.pad

import android.graphics.Bitmap
import android.net.http.SslError
import android.os.Build
import android.webkit.RenderProcessGoneDetail
import android.webkit.SslErrorHandler
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import com.crooks.pad.core.NavigationPolicy
import com.crooks.pad.core.NavigationRequest
import com.crooks.pad.core.NavigationVerdict

/**
 * CROOKS Pad — the door. Every navigation, every failure, every renderer death.
 *
 * There is no policy in this file. Every decision is made by [NavigationPolicy] in `:core`,
 * which is tested on this build machine; what is here is the Android plumbing that asks it
 * the question and does what it says. That separation is the only reason any of this is
 * verifiable at all, since nothing in this file can be run without a tablet.
 */
class PadWebViewClient(
    private val policy: NavigationPolicy,
    private val listener: Listener,
) : WebViewClient() {

    interface Listener {
        fun onNavigationAllowed(url: String)
        fun onNavigationBlocked(url: String, reason: String)
        fun onNavigationDeferred(url: String)
        fun onPageStarted(url: String)
        fun onPageFinished(url: String)
        fun onMainFrameHttpError(status: Int)
        fun onMainFrameTransportError(code: Int, description: String)
        fun onCertificateError(primaryError: Int)
        fun onRendererGone(didCrash: Boolean)
        fun networkIsOnline(): Boolean
    }

    /** Set by the activity when it wants the next load to be counted as a deliberate one. */
    var pendingDeferredUrl: String? = null
        private set

    override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
        val url = request.url?.toString()
        val verdict = policy.decide(
            NavigationRequest(
                url = url,
                isMainFrame = request.isForMainFrame,
                isRedirect = request.isRedirect,
                hasUserGesture = request.hasGesture(),
            ),
            networkOnline = listener.networkIsOnline(),
        )
        return when (verdict) {
            NavigationVerdict.ALLOW -> {
                listener.onNavigationAllowed(url.orEmpty())
                false   // let the WebView proceed
            }
            NavigationVerdict.BLOCK -> {
                // Returning true means "handled", and what we do with it is NOTHING. The
                // WebView stays exactly where it was and the owner sees no flicker, no error,
                // no dialog — because from their side nothing happened, and an explanation of
                // something that did not happen is itself a browser experience.
                listener.onNavigationBlocked(url.orEmpty(), reasonFor(request))
                true
            }
            NavigationVerdict.DEFER -> {
                // A CROOKS address while the network is down. Attempting it would produce
                // Chromium's own ERR_NAME_NOT_RESOLVED page — the single most browser-
                // revealing thing this product can do. Queue it for the reconnect instead.
                pendingDeferredUrl = url
                listener.onNavigationDeferred(url.orEmpty())
                true
            }
        }
    }

    fun takeDeferredUrl(): String? {
        val url = pendingDeferredUrl
        pendingDeferredUrl = null
        return url
    }

    private fun reasonFor(request: WebResourceRequest): String {
        val scheme = request.url?.scheme?.lowercase()
        return when {
            scheme == null -> "no_scheme"
            scheme == "http" -> "http_downgrade"
            scheme != "https" -> "scheme_$scheme"
            request.isForMainFrame -> "untrusted_origin"
            else -> "untrusted_subframe"
        }
    }

    override fun onPageStarted(view: WebView, url: String?, favicon: Bitmap?) {
        listener.onPageStarted(url.orEmpty())
    }

    override fun onPageFinished(view: WebView, url: String?) {
        listener.onPageFinished(url.orEmpty())
    }

    /**
     * The Mac answered the navigation with a 4xx or 5xx.
     *
     * This callback is the ONLY reason the shell can tell "CROOKS is serving" from "something
     * answered". `onPageFinished` fires for a 502's error body exactly as it fires for the
     * real page — §26's "app launched vs CROOKS loaded" — so without this, a reverse proxy
     * answering 502 would look like a successful load for ever.
     */
    override fun onReceivedHttpError(view: WebView, request: WebResourceRequest, errorResponse: WebResourceResponse) {
        if (!request.isForMainFrame) return   // a missing image is the page's business
        listener.onMainFrameHttpError(errorResponse.statusCode)
    }

    override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
        if (!request.isForMainFrame) return
        val code = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) error.errorCode else -1
        val description = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) error.description?.toString().orEmpty() else ""
        listener.onMainFrameTransportError(code, description)
    }

    /**
     * A certificate problem. `handler.cancel()`, always, with no branch and no setting.
     *
     * `handler.proceed()` is one line and it undoes HTTPS entirely — it is the single most
     * common critical finding in Android security reviews, and it is always written for a
     * good local reason that outlives the reason. On a tailnet the honest failure is a
     * CROOKS-native card saying the Mac is not answering properly, which is what the shell
     * shows, and which is recoverable by fixing the certificate rather than by ignoring it.
     */
    override fun onReceivedSslError(view: WebView, handler: SslErrorHandler, error: SslError) {
        handler.cancel()
        listener.onCertificateError(error.primaryError)
    }

    /**
     * §11. The render process has died — out of memory, a WebView crash, or the system
     * reclaiming it while the pad was in the background.
     *
     * RETURNING FALSE HERE KILLS THE APPLICATION. That is the documented default: if the
     * client does not handle it, Android terminates the process. On a tablet that is meant to
     * be a fixture, that means the owner finds it on the launcher, and the product's whole
     * promise is broken by an event that is entirely survivable.
     *
     * So it returns true, and the activity throws the dead WebView away and builds another.
     * There is no repairing one: every method on a WebView whose renderer has gone throws.
     */
    override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail?): Boolean {
        val didCrash = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) detail?.didCrash() ?: true else true
        listener.onRendererGone(didCrash)
        return true
    }
}
