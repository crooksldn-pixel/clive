package com.crooks.pad

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import com.crooks.pad.core.PadEventSpec
import org.junit.Test
import org.w3c.dom.Element
import org.w3c.dom.Node
import java.io.File
import javax.xml.parsers.DocumentBuilderFactory

/**
 * CROOKS Pad — §7, enforced against the layout file itself.
 *
 * There is no emulator on this build machine, so no test here can put a finger on a screen.
 * What CAN be checked is the property that made the Phase 4 defect possible in the first
 * place: a view that sits above the interactive layer while being invisible to the eye.
 *
 * In Phase 4 that was `body[data-mode="orb"] .talk{inset:0}` — a transparent voice target the
 * size of the viewport, over controls trapped in a lower stacking context. Sixty-three
 * ordinary taps became voice recordings in one evening, the speech pipeline reported them as
 * "too short", and the analyser concluded that speech was the product's top improvement
 * candidate during a session in which speech was the one thing working. One layering defect
 * produced a false engineering priority.
 *
 * In the native shell the same shape would be worse: a view in activity_pad.xml sits above the
 * WebView, so it would swallow every control in the entire product at once, and the pad would
 * look frozen with nothing in any log to say why.
 *
 * So this test reads the XML and holds three rules. It is not a substitute for touching a
 * tablet — nothing here proves a button is tappable — but it makes the specific defect
 * unshippable, which is what §7 asks for.
 */
class PadLayoutTest {

    private val ANDROID_NS = "http://schemas.android.com/apk/res/android"

    private fun layout(): Element {
        // Resolved from the module directory so it works from Gradle and from an IDE alike.
        val file = File("src/main/res/layout/activity_pad.xml")
        assertTrue("the layout must exist at ${file.absolutePath}", file.exists())
        val factory = DocumentBuilderFactory.newInstance().apply {
            isNamespaceAware = true
            // The file is ours and local, but a parser that resolves external entities is a
            // parser that reads arbitrary files when pointed at something that is not.
            setFeature("http://apache.org/xml/features/disallow-doctype-decl", true)
            isXIncludeAware = false
            isExpandEntityReferences = false
        }
        return factory.newDocumentBuilder().parse(file).documentElement
    }

    private fun childElements(parent: Element): List<Element> =
        (0 until parent.childNodes.length)
            .map { parent.childNodes.item(it) }
            .filter { it.nodeType == Node.ELEMENT_NODE }
            .map { it as Element }

    private fun id(element: Element): String =
        element.getAttributeNS(ANDROID_NS, "id").substringAfterLast("/")

    @Test fun `the web layer is the first child, so everything else is above it`() {
        val children = childElements(layout())
        assertTrue("the layout must have children", children.isNotEmpty())
        assertEquals(
            "web_host must be first; a sibling declared before it would be BELOW the workspace " +
                "and invisible for ever, which is a different bug but still a bug",
            "web_host",
            id(children.first()),
        )
    }

    @Test fun `every layer above the web layer ships GONE`() {
        // THE ASSERTION. A new overlay that ships visible — or with no declared visibility,
        // which means visible — fails the build here rather than in a workroom.
        val children = childElements(layout())
        for (child in children.drop(1)) {
            val visibility = child.getAttributeNS(ANDROID_NS, "visibility")
            assertEquals(
                "${id(child)} sits above the workspace and must declare android:visibility=\"gone\". " +
                    "Not \"invisible\" and not an alpha animation: an INVISIBLE view above the " +
                    "WebView is still laid out, and in a FrameLayout it still intercepts nothing " +
                    "— but a VISIBLE transparent one eats every control in the product. Read the " +
                    "note at the top of activity_pad.xml.",
                "gone",
                visibility,
            )
        }
    }

    @Test fun `no layer above the web layer is transparent`() {
        // An overlay is opaque and present, or it is gone. A transparent full-size overlay is
        // precisely the Phase 4 shape.
        for (child in childElements(layout()).drop(1)) {
            val background = child.getAttributeNS(ANDROID_NS, "background")
            assertTrue(
                "${id(child)} is a full-screen layer and must paint an opaque background",
                background.startsWith("@color/crooks_bg"),
            )
            val alpha = child.getAttributeNS(ANDROID_NS, "alpha")
            assertTrue("${id(child)} must not ship with a reduced alpha", alpha.isEmpty() || alpha == "1.0")
        }
    }

    @Test fun `every layer the shell can name exists in the layout`() {
        // ShellLayer is exhaustive by construction; this checks the drawing side has kept up,
        // so a layer added to the model cannot silently have nowhere to be drawn.
        val ids = childElements(layout()).map { id(it) }.toSet()
        for (required in listOf("web_host", "layer_launch", "layer_recovery", "layer_admin", "layer_diagnostics")) {
            assertTrue("$required is missing from activity_pad.xml", required in ids)
        }
    }

    @Test fun `every control a finger presses is at least 48dp tall`() {
        // Not a rendering check — nothing here is rendered — but a check that the declared
        // sizes are not smaller than the target. These are pressed by someone who is already
        // annoyed, on a 601-pixel-wide screen, possibly across a counter.
        val root = layout()
        val buttons = mutableListOf<Element>()
        fun walk(element: Element) {
            if (element.tagName == "Button" || element.tagName == "EditText") buttons += element
            childElements(element).forEach(::walk)
        }
        walk(root)
        assertTrue("the layout should contain controls", buttons.isNotEmpty())
        for (button in buttons) {
            val height = button.getAttributeNS(ANDROID_NS, "layout_height")
            // A styled control inherits its height; the style sets 56dp and is checked below.
            if (height.isEmpty()) continue
            if (height == "wrap_content" || height == "match_parent") continue
            val dp = height.removeSuffix("dp").toIntOrNull()
            assertTrue("${id(button)} is ${height}, below the 48dp minimum", dp != null && dp >= 48)
        }
    }

    @Test fun `the shared admin button style is also at least 48dp`() {
        val styles = File("src/main/res/values/styles.xml").readText()
        val height = Regex("""name="android:layout_height">(\d+)dp""").find(styles)?.groupValues?.get(1)?.toIntOrNull()
        assertTrue("AdminButton must declare a height of at least 48dp", height != null && height >= 48)
    }
}

/**
 * §6.2 and §6.4 held as facts about the source, because neither can be demonstrated on a
 * machine with no tablet. These are not a substitute for looking at a running app; they are
 * the parts that CAN be checked, checked.
 */
class PadHardeningTest {

    /**
     * EVERY SCAN IN THIS CLASS RUNS OVER CODE WITH THE COMMENTS REMOVED, and that is not a
     * convenience.
     *
     * This file is full of prose that names the dangerous thing in order to explain why it is
     * absent — "handler.proceed() is one line and it undoes HTTPS", "no runNativeCommand", "NOT
     * ACCESS_FINE_LOCATION". A scanner that reads the comments finds every one of those and
     * fails, which would leave exactly two options: delete the explanations, or delete the
     * test. Both are worse than the bug the test was for.
     *
     * The subtler half is that it cuts the other way too. A scanner fooled by prose can be
     * SATISFIED by prose: somebody writes the forbidden call, the scan is red, and the quickest
     * way to green is to move the reasoning rather than the code. Stripping comments means the
     * check only ever looks at what the compiler looks at.
     */
    private fun stripComments(text: String): String {
        val withoutBlocks = text.replace(Regex("""/\*.*?\*/""", RegexOption.DOT_MATCHES_ALL), " ")
        // `//` to end of line, EXCEPT when it follows a colon — otherwise "https://host" inside
        // a string literal would be truncated and the scan would read something that is not
        // there.
        return withoutBlocks.replace(Regex("""(?<!:)//[^\n]*"""), " ")
    }

    private fun stripXmlComments(text: String): String =
        text.replace(Regex("""<!--.*?-->""", RegexOption.DOT_MATCHES_ALL), " ")

    private fun source(name: String): String {
        val file = File("src/main/kotlin/com/crooks/pad/$name")
        assertTrue("${file.absolutePath} must exist", file.exists())
        return stripComments(file.readText())
    }

    private fun allSource(): String =
        File("src/main/kotlin/com/crooks/pad").listFiles().orEmpty()
            .joinToString("\n") { stripComments(it.readText()) }

    private fun manifest(): String = stripXmlComments(File("src/main/AndroidManifest.xml").readText())

    @Test fun `WebView debugging has exactly one call site and it reads the build flag`() {
        // §6.4: on in debug, off in release. The way that is guaranteed is that there is one
        // call and its only argument is BuildConfig.WEBVIEW_DEBUG, which the release build type
        // sets to false. No runtime switch, no setting, no admin toggle.
        val all = allSource()
        val calls = Regex("""setWebContentsDebuggingEnabled\(""").findAll(all).count()
        assertEquals("there must be exactly one call site for WebView debugging", 1, calls)
        assertTrue(
            "the call must be driven by BuildConfig.WEBVIEW_DEBUG and nothing else",
            source("PadWebView.kt").contains("setWebContentsDebuggingEnabled(BuildConfig.WEBVIEW_DEBUG)"),
        )
    }

    @Test fun `the release build type switches WebView debugging off`() {
        val gradle = File("build.gradle.kts").readText()
        val release = gradle.substringAfter("release {").substringBefore("}")
        assertTrue(
            "the release build type must set WEBVIEW_DEBUG false",
            release.contains("""buildConfigField("boolean", "WEBVIEW_DEBUG", "false")"""),
        )
    }

    /**
     * §26 / C1, HELD AGAINST THE ACTIVITY ITSELF.
     *
     * `PageLoadGuard` in `:core` is where the rule lives that a main-frame failure poisons the
     * load, and ConnectionMachineTest replays Chromium's real callback order against it. What
     * that test cannot see is whether this module still ASKS. There is no emulator here, so the
     * only available check is the source — but it is a real one: the four call sites below are
     * the entire path from a WebView callback to a PageOutcome, and if somebody puts the
     * decision back into the Activity, one of them goes missing and this goes red.
     */
    @Test fun `how a load went is decided by the guard in core, not by the Activity`() {
        val activity = source("PadActivity.kt")
        for (call in listOf(
            "loadGuard.shellStartedLoad()",
            "loadGuard.pageFinished(",
            "loadGuard.mainFrameFailed(",
            "loadGuard.readinessAnswered(",
        )) {
            assertTrue("PadActivity must reach the load guard through $call", activity.contains(call))
        }

        // THE DEFECT, NAMED. onPageFinished used to set this flag itself, which is how a load
        // that had already reported a 502 was handed back to the readiness probe and from there
        // to ONLINE. The flag now belongs to the guard and this module may not write it.
        assertFalse(
            "awaitingReadiness must not be assignable from the Activity: that assignment IS the " +
                "bug in which a 502 reached ONLINE. Ask PageLoadGuard instead.",
            Regex("""awaitingReadiness\s*=""").containsMatchIn(activity),
        )
        assertFalse(
            "workspaceLoading was the other half of the same hand-rolled state; the guard owns it",
            activity.contains("workspaceLoading"),
        )
    }

    /**
     * CONTRACT 1 / C2. pad_* events do not go to `/telemetry`, and the cadence is not here.
     */
    @Test fun `the appliance's liveness goes to the heartbeat and never to slash telemetry`() {
        val all = allSource()
        assertFalse(
            "/telemetry is the WEB PAGE's account of itself and is silent outside a test " +
                "session. An appliance's liveness must not travel on it; see Heartbeat.",
            all.contains("\"/telemetry\""),
        )
        val activity = source("PadActivity.kt")
        assertTrue("the beat must go to the path :core states", activity.contains("probe.post(Heartbeat.PATH"))
        assertTrue("and its events must be the queued pad_* events", activity.contains("sink.drain()"))
    }

    @Test fun `the heartbeat cadence is read from the answer and is not a constant in this module`() {
        val activity = source("PadActivity.kt")
        assertTrue("the timer must ask :core whether a beat is due", activity.contains("heartbeat.isDue("))
        assertTrue("and every answer must be read", activity.contains("heartbeat.onAnswer("))
        assertTrue(
            "the response field must be spelled once, in :core",
            activity.contains("Heartbeat.KEY_INTERVAL_S"),
        )
        // And no constant in this module may quietly become the cadence again. ONLINE_PING_MS
        // is a different thing — how often the shell asks the Mac about the MAC — and is named
        // so that it cannot be mistaken for this one.
        val cadenceConstant = Regex("""const val [A-Z_]*(HEARTBEAT|BEAT)[A-Z_]*""")
        assertFalse(
            "a cadence constant in the APK is a cadence nobody can change without a cable: " +
                "the interval comes off interval_s on every beat",
            cadenceConstant.containsMatchIn(allSource()),
        )
    }

    /**
     * CONTRACT 3, HELD AT THE CALL SITES.
     *
     * PadTelemetryTest proves the VOCABULARY matches the Mac's table. This proves the SHELL
     * matches the vocabulary — by reading every `record("pad_…")` in the Activity, which is the
     * only place the shell emits anything, and comparing the set for equality.
     *
     * Equality in both directions is the point. `containsAll` one way would let the shell emit
     * a kind the Mac throws away; `containsAll` the other way would let a kind the Mac expects
     * quietly stop being emitted, which is the failure that leaves a Control app drawing a
     * tablet that looks healthy because the event that would have said otherwise was deleted.
     */
    @Test fun `the kinds this shell actually records are exactly the vocabulary`() {
        val recorded = Regex("""record\(\s*"(pad_[a-z0-9_]+)"""")
            .findAll(source("PadActivity.kt"))
            .map { it.groupValues[1] }
            .toSet()
        assertEquals(
            "every kind PadActivity records must be in the Mac's table, and every kind in the " +
                "Mac's table must be recorded by PadActivity",
            PadEventSpec.SPECS.keys,
            recorded,
        )
    }

    @Test fun `the duplicate and deleted event spellings appear nowhere in the shell`() {
        val all = allSource()
        for (gone in listOf(
            "pad_foreground", "pad_background", "pad_state_changed", "pad_battery_changed",
        )) {
            assertFalse(
                "$gone is a spelling CONTRACT 3 deletes; two spellings of one event put half " +
                    "of a tablet's history under each",
                Regex("""\"$gone\"""").containsMatchIn(all),
            )
        }
    }

    @Test fun `an SSL error is never proceeded past`() {
        // `handler.proceed()` is one line and it undoes HTTPS entirely. It is the most common
        // critical finding in Android security reviews and it is always written for a good
        // local reason that outlives the reason.
        val all = allSource()
        assertFalse("no code path may call handler.proceed() on an SSL error", all.contains(".proceed()"))
        assertTrue(source("PadWebViewClient.kt").contains("handler.cancel()"))
    }

    @Test fun `the JavaScript bridge is one read-only method wide`() {
        // §6.5. The surface is checked by counting annotations, not by reading the comment
        // above them: a second @JavascriptInterface added in a hurry fails the build.
        val all = allSource()
        val annotations = Regex("""@JavascriptInterface""").findAll(all).count()
        assertEquals("the bridge must expose exactly one method", 1, annotations)

        val bridge = source("DeviceBridge.kt")
        // And nothing shaped like a dispatcher, which is what makes a bridge's size stop being
        // reviewable.
        for (forbidden in listOf("runNativeCommand", "invoke(", "execute(", "call(", "eval(", "setProperty")) {
            assertFalse("the bridge must not expose anything like $forbidden", bridge.contains(forbidden))
        }
        assertTrue("the one method must return a snapshot", bridge.contains("fun snapshot(): String"))
    }

    @Test fun `file and content access are switched off`() {
        val web = source("PadWebView.kt")
        for (setting in listOf(
            "allowFileAccess = false",
            "allowContentAccess = false",
            "allowFileAccessFromFileURLs = false",
            "allowUniversalAccessFromFileURLs = false",
        )) {
            assertTrue("§6.4 requires $setting", web.contains(setting))
        }
        assertTrue("mixed content must never be allowed", web.contains("MIXED_CONTENT_NEVER_ALLOW"))
        assertTrue("geolocation must be off", web.contains("setGeolocationEnabled(false)"))
    }

    @Test fun `the manifest refuses cleartext and backs nothing up`() {
        val manifest = manifest()
        assertTrue(manifest.contains("""android:usesCleartextTraffic="false""""))
        assertTrue(manifest.contains("""android:allowBackup="false""""))
        assertTrue(manifest.contains("""android:networkSecurityConfig="@xml/network_security_config""""))
        // No location permission anywhere, which is what makes "the pad never reads the SSID"
        // a platform guarantee rather than a promise in a comment.
        assertFalse("the pad must not ask for location", manifest.contains("ACCESS_FINE_LOCATION"))
        assertFalse("the pad must not ask for coarse location", manifest.contains("ACCESS_COARSE_LOCATION"))
        assertFalse("the pad has no use for the camera", manifest.contains("android.permission.CAMERA"))
    }

    @Test fun `the HOME alias ships disabled`() {
        // §13/§14: being the launcher is what makes a tablet hard to get out of. It is an
        // alias that ships off and is switched on from behind the admin PIN.
        val manifest = manifest()
        val alias = manifest.substringAfter("<activity-alias").substringBefore("</activity-alias>")
        assertTrue("the HOME alias must ship disabled", alias.contains("""android:enabled="false""""))
        assertTrue("and it must be the alias that carries CATEGORY_HOME", alias.contains("android.intent.category.HOME"))
        assertFalse(
            "the main activity must not carry CATEGORY_HOME itself",
            manifest.substringBefore("<activity-alias").contains("android.intent.category.HOME"),
        )
    }

    @Test fun `the owner is never shown a browser dialog`() {
        // §6.2. A window.alert renders a Chromium dialog with the ORIGIN IN ITS TITLE, which
        // is a URL on screen in a product whose whole premise is that there is no browser.
        val chrome = source("PadWebChromeClient.kt")
        for (override in listOf("onJsAlert", "onJsConfirm", "onJsBeforeUnload")) {
            assertTrue("$override must be intercepted", chrome.contains("override fun $override"))
        }
    }

    @Test fun `no credential, key or PIN is written into the source`() {
        // §28, checked rather than asserted in a comment. The CROOKS origin is present and is
        // not a credential: it is a Tailscale hostname, useless to anything not on the tailnet.
        val all = allSource() + "\n" + stripComments(File("build.gradle.kts").readText())
        for (smell in listOf("api_key", "apiKey", "secret", "password =", "Bearer ", "DEFAULT_PIN", "ADMIN_PIN")) {
            assertFalse("the source must not contain $smell", all.contains(smell))
        }
    }

    @Test fun `back does not leave the application`() {
        // §6.2, "no accidental navigation out". The hardware Back in a WebView shell means
        // "go back in history", which on the last page means "leave".
        val activity = source("PadActivity.kt")
        val back = activity.substringAfter("override fun onBackPressed()").substringBefore("\n    }")
        assertFalse("Back must not finish the activity", back.contains("finish()"))
        assertFalse("Back must not walk the WebView's history", back.contains("goBack()"))
    }
}
