package com.crooks.pad

import android.annotation.SuppressLint
import android.content.Context
import android.view.View
import android.webkit.CookieManager
import android.webkit.WebSettings
import android.webkit.WebView
import androidx.webkit.WebSettingsCompat
import androidx.webkit.WebViewFeature

/**
 * CROOKS Pad — §6.4, building the WebView, and everything that is switched OFF.
 *
 * A WebView out of the box is a browser engine with most of a browser's capabilities and none
 * of a browser's defences, because the app is assumed to be in charge. This function is what
 * "in charge" means in practice, and the interesting half of it is the settings that are set
 * to false — each one is a door that is open by default.
 *
 * Rebuilt from scratch, not merely reloaded, whenever the renderer dies: a WebView whose
 * render process has gone is permanently dead and every method on it throws.
 */
object PadWebViewFactory {

    /**
     * Debugging is a build-type decision and nothing else.
     *
     * `setWebContentsDebuggingEnabled(true)` opens the page to anything that can reach ADB on
     * the device — full DevTools, arbitrary script evaluation, the lot. §6.4 requires it off
     * in release, and the way it is kept off is that the ONLY call site is this one and the
     * only thing it consults is BuildConfig.WEBVIEW_DEBUG, which the release build type sets
     * to false in app/build.gradle.kts. There is no runtime switch, no setting, no admin
     * toggle. PadHardeningTest asserts that this remains true of the source.
     */
    fun applyProcessWideDebugging() {
        WebView.setWebContentsDebuggingEnabled(BuildConfig.WEBVIEW_DEBUG)
    }

    @SuppressLint("SetJavaScriptEnabled")
    fun create(context: Context): WebView {
        val web = WebView(context)

        // INVISIBLE, not GONE: it must keep its real bounds so the page lays out at the
        // tablet's actual viewport while it loads. An INVISIBLE child receives no touches,
        // which is the property that matters. See ShellLayer for the full reasoning.
        web.visibility = View.INVISIBLE
        web.setBackgroundColor(0xFF07070A.toInt())   // CROOKS ground, so no white flash
        web.overScrollMode = View.OVER_SCROLL_NEVER  // no blue glow: that is a browser tell

        with(web.settings) {
            // On, because CROOKS is an application. This is the one powerful thing that has
            // to be enabled, and it is why everything below is disabled.
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true

            // ---- the doors that are open by default, closed ----

            // File and content access. With these on, a page — or anything that reached one —
            // can read file:// and content:// URIs, which on Android means other apps'
            // exported providers and, historically, this app's own private data directory.
            // CROOKS is served over https and never opens a local file, so all of it goes.
            allowFileAccess = false
            allowContentAccess = false
            @Suppress("DEPRECATION")
            allowFileAccessFromFileURLs = false
            @Suppress("DEPRECATION")
            allowUniversalAccessFromFileURLs = false

            // No mixed content, ever. The network security config refuses cleartext as well,
            // so this is the second of two locks on the same door — and deliberately so,
            // because a future change to one of them should not silently open it.
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW

            // Geolocation. The pad does not know where it is and does not need to.
            setGeolocationEnabled(false)

            // Save nothing that looks like a form entry. This is a shop's tablet; the owner
            // types customer names and order numbers into it all day.
            @Suppress("DEPRECATION")
            saveFormData = false

            // Windows. `window.open` and target=_blank would produce a second WebView with no
            // shell around it — no navigation guard, no permission policy, no way back. There
            // is no onCreateWindow handler either, so a page that tries gets nothing.
            setSupportMultipleWindows(false)
            javaScriptCanOpenWindowsAutomatically = false

            // Zoom. Pinch-zooming an appliance's own interface is a browser behaviour and it
            // wrecks a layout designed for one viewport.
            setSupportZoom(false)
            builtInZoomControls = false
            displayZoomControls = false

            // The page is designed for this exact viewport. Letting the WebView emulate a
            // desktop width and scale it down would undo every measurement in web/style.css.
            useWideViewPort = false
            loadWithOverviewMode = false

            // Media. The web layer plays the spoken answer, which must start when the page
            // says so rather than after a tap the owner has no reason to make.
            mediaPlaybackRequiresUserGesture = false

            // Cache normally; the page has a service worker that owns its own freshness and
            // the shell must not second-guess it.
            cacheMode = WebSettings.LOAD_DEFAULT

            // A plain WebView user agent, with CROOKS appended so the Mac's logs can tell the
            // pad from Chrome on the same tailnet. Not a spoofed desktop UA: lying to your own
            // backend produces one confusing afternoon per year, for ever.
            userAgentString = userAgentString + " CROOKSPad/" + BuildConfig.VERSION_NAME
        }

        // Safe Browsing, where this device's WebView has it. Asked for rather than assumed:
        // the SM-T290's WebView may be years behind, and a hardening call that throws on the
        // one device the product runs on is not hardening.
        if (WebViewFeature.isFeatureSupported(WebViewFeature.SAFE_BROWSING_ENABLE)) {
            WebSettingsCompat.setSafeBrowsingEnabled(web.settings, true)
        }

        // Cookies for the CROOKS origin, which is how the page holds its session. Third-party
        // cookies off: nothing on this pad is third-party, so anything asking for one is not
        // something we put there.
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false)

        // No long-press context menu — "Copy link address", "Open in new tab", "Share" is the
        // browser wearing a hat. And no text selection handles on a screen the owner touches
        // to give commands.
        web.isLongClickable = false
        web.setOnLongClickListener { true }
        web.isHapticFeedbackEnabled = false

        return web
    }

    /**
     * The readiness probe, run after a page finishes loading. This is the difference between
     * "some bytes arrived and parsed" and "CROOKS is on screen" — §26's "app launched vs
     * CROOKS loaded", made into a question the shell can actually ask.
     *
     * It reads two elements that have been in web/index.html since the shell was built and
     * that the whole product is arranged around: the orb's frame and the stage. It changes
     * nothing, defines nothing and leaves no global behind — it is an expression, not a
     * script, and the page cannot tell it ran.
     *
     * If the web layer ever renames them, this returns false, the shell takes the weaker
     * signal, and it SAYS SO rather than refusing to work. See PageOutcome.READY_ASSUMED.
     */
    const val READINESS_EXPRESSION =
        "(!!document.getElementById('orb-frame') && !!document.getElementById('stage'))"
}
