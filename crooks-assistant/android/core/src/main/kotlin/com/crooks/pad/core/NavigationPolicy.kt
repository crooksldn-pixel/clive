package com.crooks.pad.core

/**
 * CROOKS Pad — what may be navigated to, and what happens to everything else.
 *
 * §6.2 says the owner must never have reason to know a WebView is involved. Most of that is
 * chrome that is simply absent. The part that is not absence is this: a browser, when it is
 * asked to go somewhere it should not, *goes there* and then shows you where you are. The
 * shell must instead refuse, stay exactly where it was, and say nothing — because from the
 * owner's side nothing happened, and an explanation of something that did not happen is
 * itself a browser experience.
 *
 * WHAT THIS COVERS, AND WHAT IT DOES NOT. This policy governs navigation: the address the
 * top-level document is being asked to become. It does not govern sub-resources — images,
 * fonts, XHR — and that is a decision rather than a gap. The CROOKS page serves its own
 * images through the Mac's media proxy, so today every sub-resource is same-origin anyway;
 * but if that ever changes, the right place to say which resources a page may load is the
 * page's own Content-Security-Policy on the Mac, which can be tested against the real page.
 * A second, blunter copy of that rule inside the shell would be untestable on this build
 * machine and would eventually break rendering in a way nobody could reproduce. The shell
 * owns the door; the backend owns the furniture.
 */

enum class NavigationVerdict {
    /** A CROOKS address. Let the WebView load it. */
    ALLOW,

    /**
     * Not CROOKS. Do not load, do not leave the current page, do not show anything. Recorded
     * as `pad_navigation_blocked` so a blocked navigation is visible to diagnostics even
     * though it is invisible to the owner.
     */
    BLOCK,

    /**
     * A CROOKS address, but the shell is not currently in a state where loading it is the
     * right answer — the network is down, or the shell is showing a recovery state. The
     * caller queues it and loads it when the connection comes back, instead of letting the
     * WebView produce Chromium's own error page. This is the verdict that stops §6.3's
     * "NEVER a Chromium error page" from depending on good luck.
     */
    DEFER,
}

/** Everything the policy is allowed to know about a navigation. Nothing about the page. */
data class NavigationRequest(
    val url: String?,
    val isMainFrame: Boolean,
    val isRedirect: Boolean,
    /** True when a finger caused it; false for script-initiated navigation. */
    val hasUserGesture: Boolean,
)

class NavigationPolicy(private val allowList: OriginAllowList) {

    fun decide(request: NavigationRequest, networkOnline: Boolean): NavigationVerdict {
        if (!allowList.allows(request.url)) return NavigationVerdict.BLOCK
        // A sub-frame asking for a CROOKS address is fine; a sub-frame asking for anything
        // else was blocked by the line above. The main/sub distinction does not change the
        // answer, and pretending it does would be a branch nothing tests.
        if (!request.isMainFrame) return NavigationVerdict.ALLOW
        return if (networkOnline) NavigationVerdict.ALLOW else NavigationVerdict.DEFER
    }

    /**
     * The very first load of the process. Separate from [decide] because a configured start
     * URL that is not on the allow-list is not a blocked navigation — it is a broken
     * installation, and it must fail into APP ERROR rather than into silence. A shell that
     * silently refuses to load its own home address and then shows a blank screen is the
     * worst outcome available.
     */
    fun startUrlIsUsable(url: String?): Boolean = allowList.allows(url)
}
