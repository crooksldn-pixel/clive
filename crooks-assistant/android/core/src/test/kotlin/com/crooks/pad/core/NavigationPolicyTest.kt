package com.crooks.pad.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NavigationPolicyTest {

    private val CROOKS = "https://crooks-assistant.taildfb357.ts.net"
    private val policy = NavigationPolicy(OriginAllowList.of(CROOKS))

    private fun request(url: String?, main: Boolean = true, redirect: Boolean = false, gesture: Boolean = true) =
        NavigationRequest(url, main, redirect, gesture)

    @Test fun `a crooks page loads`() {
        assertEquals(NavigationVerdict.ALLOW, policy.decide(request("$CROOKS/"), networkOnline = true))
    }

    @Test fun `anything else is blocked, whatever caused it`() {
        // The four ways a WebView is talked somewhere else: a link, a redirect, a script, and
        // a scheme that is not the web at all. None of them changes the answer.
        for (gesture in listOf(true, false)) {
            for (redirect in listOf(true, false)) {
                assertEquals(
                    NavigationVerdict.BLOCK,
                    policy.decide(request("https://evil.example/", redirect = redirect, gesture = gesture), true),
                )
            }
        }
        assertEquals(NavigationVerdict.BLOCK, policy.decide(request("intent://x#Intent;end"), true))
        assertEquals(NavigationVerdict.BLOCK, policy.decide(request("market://details?id=com.android.chrome"), true))
        assertEquals(NavigationVerdict.BLOCK, policy.decide(request("mailto:hello@example.com"), true))
        assertEquals(NavigationVerdict.BLOCK, policy.decide(request("tel:999"), true))
    }

    @Test fun `mailto and tel are blocked rather than handed to another app`() {
        // This looks unhelpful and is not. Handing a mailto: to Android opens Gmail ON TOP of
        // CROOKS, on a tablet with no visible way back, in an app that is signed in to the
        // business mailbox. §6.2's "no accidental navigation out" includes leaving by the
        // side door.
        assertEquals(NavigationVerdict.BLOCK, policy.decide(request("mailto:orders@example.com?subject=x"), true))
    }

    @Test fun `a crooks navigation while the network is down is deferred, never attempted`() {
        // This is what keeps Chromium's own error page off the screen. Attempting the load
        // would produce "ERR_NAME_NOT_RESOLVED" in Chromium's typeface, which is the single
        // most browser-revealing thing that can happen to this product.
        assertEquals(NavigationVerdict.DEFER, policy.decide(request("$CROOKS/"), networkOnline = false))
    }

    @Test fun `a blocked address is blocked whether or not the network is up`() {
        assertEquals(NavigationVerdict.BLOCK, policy.decide(request("https://evil.example/"), networkOnline = false))
    }

    @Test fun `a sub-frame may load crooks and nothing else`() {
        assertEquals(NavigationVerdict.ALLOW, policy.decide(request("$CROOKS/x", main = false), true))
        assertEquals(NavigationVerdict.BLOCK, policy.decide(request("https://evil.example/", main = false), true))
    }

    @Test fun `the start url is checked separately, because a bad one is a broken install`() {
        assertTrue(policy.startUrlIsUsable("$CROOKS/"))
        assertFalse(policy.startUrlIsUsable("http://crooks-assistant.taildfb357.ts.net/"))
        assertFalse(policy.startUrlIsUsable(null))
    }
}
