package com.crooks.pad

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * CROOKS Pad — the native shell paints the same CROOKS as the web layer, checked rather than
 * hoped.
 *
 * The palette is duplicated by necessity. The whole point of §6.3's branded launch path is that
 * the shell can paint CROOKS before a single byte of the web layer has arrived, which means the
 * colours have to exist natively, in `res/values/colors.xml`, with no reference to anything the
 * Mac serves.
 *
 * Duplicated values drift. And the drift here would be quiet and ugly in a specific way: the
 * launch screen and the recovery card are what the owner sees at the exact moment the product
 * is already failing them, and a shell whose black is one shade off the page's black reads as
 * a different, cheaper application arriving to apologise for the real one.
 *
 * So this test reads `web/style.css` — the source of truth, which this workstream does not own
 * and must not modify — and holds the native copies to it. If a designer changes a token on the
 * web side, this goes red and names the token, which is exactly the moment to change both.
 *
 * It reads the file read-only and from outside the Gradle project, which is unusual and worth
 * the unusualness: the alternative is a comment claiming the two agree.
 */
class ThemeTokensTest {

    /** The CSS file lives two directories up from this module: crooks-assistant/web/style.css. */
    private fun css(): String {
        val file = File("../../web/style.css")
        assertTrue(
            "web/style.css must be readable at ${file.absolutePath}; if the web layer has moved, " +
                "fix this path rather than deleting the check",
            file.exists(),
        )
        return file.readText()
    }

    private fun cssToken(css: String, name: String): String? =
        Regex("""--$name\s*:\s*(#[0-9a-fA-F]{3,8})""").find(css)?.groupValues?.get(1)?.lowercase()

    private fun androidColour(name: String): String? {
        val xml = File("src/main/res/values/colors.xml").readText()
        val raw = Regex("""<color name="$name">#([0-9a-fA-F]{6,8})</color>""").find(xml)?.groupValues?.get(1)?.lowercase()
            ?: return null
        // Android writes AARRGGBB; CSS writes RRGGBB. Compare the colour, not the alpha.
        return "#" + if (raw.length == 8) raw.substring(2) else raw
    }

    @Test fun `the native palette matches the web tokens`() {
        val css = css()
        val pairs = listOf(
            "bg-0" to "crooks_bg_0",
            "bg-1" to "crooks_bg_1",
            "bg-2" to "crooks_bg_2",
            "ink" to "crooks_ink",
            "ink-2" to "crooks_ink_2",
            "ink-3" to "crooks_ink_3",
            "ok" to "crooks_ok",
            "warn" to "crooks_warn",
            "bad" to "crooks_bad",
        )
        for ((token, colour) in pairs) {
            val fromCss = cssToken(css, token)
            assertTrue("web/style.css no longer defines --$token; the native copy is now unanchored", fromCss != null)
            assertEquals(
                "the native colour '$colour' has drifted from web/style.css's --$token. " +
                    "Change both, or the launch screen stops looking like the product it is launching.",
                fromCss,
                androidColour(colour),
            )
        }
    }

    @Test fun `the launch background is the same black the page paints`() {
        // The single most visible one: this is the colour of the window before any of our code
        // runs, and a mismatch here is a flash of the wrong black on every single launch.
        val theme = File("src/main/res/values/themes.xml").readText()
        assertTrue(
            "the window background must be the CROOKS ground colour, or the tablet flashes " +
                "something else before the first frame",
            theme.contains("""<item name="android:windowBackground">@color/crooks_bg_0</item>"""),
        )
        assertEquals(cssToken(css(), "bg-0"), androidColour("crooks_bg_0"))
    }
}
