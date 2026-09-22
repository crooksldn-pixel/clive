package com.crooks.pad.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PadTelemetryTest {

    private val captured = mutableListOf<PadEvent>()
    private fun telemetry() = PadTelemetry(sink = { captured += it })

    /**
     * CONTRACT 3, AND THE TEST THE WHOLE VOCABULARY EXISTS FOR.
     *
     * The backend's table in crooks-assistant/app/observability/pad.py is canonical: it admits
     * a fixed set of pad_* names and nothing else. A name outside it is rejected and counted;
     * a name spelled two ways puts half of a tablet's history under each. So the sixteen names
     * are written out here BY HAND, as a literal, and compared for EQUALITY — not `containsAll`,
     * which would pass while the shell quietly emitted a seventeenth the Mac throws away, and
     * not a loop over SPECS, which would be the shell marking its own homework.
     *
     * If either side drifts — a rename on the Mac, a new kind here — this goes red.
     */
    @Test fun `the kinds this shell can emit are exactly the kinds the backend admits`() {
        val theMacsTable = setOf(
            // §16's thirteen.
            "pad_app_started",
            "pad_app_foreground",
            "pad_app_background",
            "pad_webview_loaded",
            "pad_webview_error",
            "pad_network_changed",
            "pad_backend_reachable",
            "pad_backend_unreachable",
            "pad_mic_permission",
            "pad_renderer_crash",
            "pad_admin_entered",
            "pad_admin_exited",
            "pad_version",
            // The three appliance facts the Control app benefits from.
            "pad_battery",
            "pad_kiosk_stage",
            "pad_navigation_blocked",
        )
        assertEquals(theMacsTable, PadEventSpec.SPECS.keys)
        assertEquals(theMacsTable, PadEventSpec.BACKEND_KINDS)
    }

    /**
     * The other half of CONTRACT 3: the spellings that are GONE.
     *
     * Each of these was emitted by this shell at some point and each duplicates something in
     * the table above. Asserting they are absent from SPECS is not enough — the interesting
     * property is at runtime, that recording one produces nothing and is COUNTED as rejected
     * rather than disappearing.
     */
    @Test fun `the duplicate and deleted spellings are gone and are counted when attempted`() {
        val gone = listOf(
            "pad_foreground",         // duplicate of pad_app_foreground
            "pad_background",         // duplicate of pad_app_background
            "pad_state",              // never a kind; it is a field of the device snapshot
            "pad_state_changed",      // the pad's state is on the heartbeat itself
            "pad_battery_changed",    // duplicate of pad_battery
        )
        val t = telemetry()
        for (kind in gone) {
            assertFalse("$kind must not be in the vocabulary", PadEventSpec.allows(kind))
            assertNull("$kind must not reach a queue", t.record(kind, mapOf("state" to "x"), now = 1_000))
        }
        assertEquals(gone.size, t.rejected)
        assertEquals(0, t.emitted)
        assertTrue(captured.isEmpty())
    }

    /**
     * THE FIELD-LEVEL GUARD.
     *
     * The Mac keeps only the fields its table names for a kind and DROPS the rest silently, so
     * a pad can emit a perfectly shaped event and have the one field that explained the outage
     * thrown away at the door with nothing anywhere saying so. That is §26's lesson in its most
     * literal form — green because the wrong thing was measured — and this assertion is the
     * guard: if anybody adds a field the Mac will not keep, the build goes red HERE, where it
     * costs a minute, instead of in a timeline nobody can reconstruct six weeks later.
     */
    @Test fun `every field of every pad event is one the Mac will actually keep`() {
        for ((kind, fields) in PadEventSpec.SPECS) {
            for (field in fields) {
                assertTrue(
                    "$kind declares field '$field', which the Mac drops silently. Either " +
                        "rename it to one the table in app/observability/pad.py keeps, or " +
                        "accept that the value will never arrive.",
                    field in PadEventSpec.BACKEND_ALLOWED_FIELDS,
                )
            }
        }
    }

    /** The Mac drops any event whose kind does not match `^[a-z][a-z0-9_]{0,39}$`. */
    @Test fun `every pad event kind survives the Mac's kind pattern`() {
        val pattern = Regex("^[a-z][a-z0-9_]{0,39}$")
        for (kind in PadEventSpec.SPECS.keys) {
            assertTrue("$kind would be dropped by the Mac before the table is even reached", pattern.matches(kind))
            assertTrue("$kind should be namespaced pad_*", kind.startsWith("pad_"))
        }
    }

    @Test fun `the workspace-arrived event exists and says which measurement was taken`() {
        // pad_webview_loaded is the event that distinguishes "the CROOKS workspace is on the
        // screen" from "some bytes arrived and parsed", which is §26's whole subject. `mode`
        // carries "confirmed" or "assumed" and is the field that says which one it was.
        assertTrue(PadEventSpec.allows("pad_webview_loaded"))
        assertTrue("mode" in PadEventSpec.fieldsFor("pad_webview_loaded"))
        val t = telemetry()
        val event = t.record("pad_webview_loaded", mapOf("mode" to "assumed", "ms" to 1_200L), now = 1)!!
        assertEquals("assumed", event.fields["mode"])
        assertEquals(1_200L, event.fields["ms"])
    }

    @Test fun `an undeclared field is dropped before it can reach the queue`() {
        // The PII defence is a whitelist, not a scrubber. A scrubber has to recognise the
        // thing it is protecting against; a whitelist does not have to recognise anything.
        val t = telemetry()
        val event = t.record(
            "pad_network_changed",
            mapOf("state" to "wifi", "reachable" to true, "ssid" to "GEORGE-BACK-OFFICE", "ip" to "100.64.1.7"),
            now = 1_000,
        )
        assertNotNull(event)
        assertTrue("state must survive", "state" in event!!.fields)
        assertFalse("an SSID names a place and must never leave the tablet", "ssid" in event.fields)
        assertFalse("an address identifies the tailnet node", "ip" in event.fields)
    }

    @Test fun `an unknown kind is rejected rather than emitted and lost`() {
        val t = telemetry()
        assertNull(t.record("pad_made_up", mapOf("state" to "x"), now = 1_000))
        assertEquals(1, t.rejected)
        assertEquals(0, t.emitted)
        assertTrue(captured.isEmpty())
    }

    @Test fun `the battery event exists and cannot be spammed with it`() {
        // §18: "meaningful transitions only — do NOT spam battery ticks". The Mac's table now
        // admits pad_battery, so the rule can no longer be "there is no such kind". It is
        // arithmetic instead: the Android broadcast fires once per percent, the percentage is
        // bucketed to five before it can reach an event, and the kind is a transition kind —
        // so nineteen of these twenty attempts produce nothing.
        val t = telemetry()
        var emitted = 0
        for (percent in 100 downTo 81) {
            val bucket = PadBattery.bucket(percent)!!
            if (t.record("pad_battery", mapOf("percent" to bucket, "charging" to false), now = percent * 60_000L) != null) {
                emitted++
            }
        }
        // 100, 95, 90, 85 and 80 — five buckets out of twenty broadcasts, which is the ratio
        // the rule promises and the reason it is arithmetic rather than a comment.
        assertEquals(5, emitted)
        assertEquals(15, t.suppressed)

        // Plugging the charger in IS a transition, at the same level.
        assertNotNull(t.record("pad_battery", mapOf("percent" to 80, "charging" to true), now = 99_000_000))
    }

    @Test fun `the battery bucket is the only way a level can reach an event`() {
        assertEquals(100, PadBattery.bucket(100))
        assertEquals(90, PadBattery.bucket(94))
        assertEquals(90, PadBattery.bucket(90))
        assertEquals(0, PadBattery.bucket(4))
        assertNull("before the first broadcast there is no level, and no event", PadBattery.bucket(-1))
        assertEquals("a level over 100 is a broken driver, not a reason to emit 105", 100, PadBattery.bucket(127))
    }

    @Test fun `a transition event repeats only when the transition is real`() {
        val t = telemetry()
        assertNotNull(t.record("pad_network_changed", mapOf("state" to "wifi"), now = 0))
        assertNull("the same network is not a change", t.record("pad_network_changed", mapOf("state" to "wifi"), now = 60_000))
        assertNotNull(t.record("pad_network_changed", mapOf("state" to "none"), now = 61_000))
        assertNotNull("and back again is a change", t.record("pad_network_changed", mapOf("state" to "wifi"), now = 62_000))
        assertEquals(3, t.emitted)
        assertEquals(1, t.suppressed)
    }

    @Test fun `an identical non-transition event is deduplicated for ten seconds`() {
        val t = telemetry()
        assertNotNull(t.record("pad_webview_error", mapOf("code" to "504"), now = 0))
        assertNull(t.record("pad_webview_error", mapOf("code" to "504"), now = 5_000))
        assertNotNull(t.record("pad_webview_error", mapOf("code" to "504"), now = 11_000))
        // A different value is a different event and is never suppressed.
        assertNotNull(t.record("pad_webview_error", mapOf("code" to "502"), now = 11_001))
    }

    @Test fun `every event carries a timestamp the Mac will keep`() {
        val t = telemetry()
        val event = t.record("pad_app_started", mapOf("name" to "CROOKS Pad"), now = 1_234)!!
        assertEquals(1_234L, event.fields["t"])
        assertTrue("t" in PadEventSpec.BACKEND_ALLOWED_FIELDS)
    }

    @Test fun `a long value is bounded here rather than trusted to be bounded there`() {
        val t = telemetry()
        val event = t.record("pad_webview_error", mapOf("reason" to "x".repeat(5_000)), now = 0)!!
        assertEquals(201, (event.fields["reason"] as String).length)
    }

    @Test fun `a url never enters an event with its path attached`() {
        // A CROOKS path can carry an order number or a message id. An origin cannot carry
        // anything, which is why originOnly exists.
        assertEquals(
            "https://crooks-assistant.taildfb357.ts.net",
            originOnly("https://crooks-assistant.taildfb357.ts.net/order/1934?email=george%40example.com"),
        )
        assertNull(originOnly("not a url"))
    }

    @Test fun `a blocked navigation reports a host and can report nothing else`() {
        // The Mac's table names one field for this event, `host`, and hostOnly is the only way
        // a value reaches it: no scheme, no port, no path, no query, and nothing at all from an
        // address the shell's own parser will not accept.
        assertEquals(setOf("host"), PadEventSpec.fieldsFor("pad_navigation_blocked"))
        assertFalse(
            "a blocked address is attacker-controlled text and has no field to arrive in whole",
            "url" in PadEventSpec.fieldsFor("pad_navigation_blocked"),
        )
        assertEquals("evil.example", hostOnly("https://evil.example:8443/pay?card=4111111111111111"))
        assertNull(hostOnly("intent://evil.example/#Intent;scheme=https;end"))
        assertNull(hostOnly("javascript:alert(1)"))

        val t = telemetry()
        val event = t.record(
            "pad_navigation_blocked",
            mapOf("host" to hostOnly("https://evil.example/pay?card=4111111111111111"), "url" to "https://evil.example/pay"),
            now = 0,
        )!!
        assertEquals("evil.example", event.fields["host"])
        assertFalse("the whole address must never survive", "url" in event.fields)
        assertFalse(event.fields.values.any { it.toString().contains("4111") })
    }

    @Test fun `the counters tell quiet apart from broken`() {
        val t = telemetry()
        t.record("pad_app_started", mapOf("name" to "a"), now = 0)
        t.record("pad_app_started", mapOf("name" to "a"), now = 1)
        t.record("pad_nonsense", emptyMap(), now = 2)
        assertEquals(1, t.emitted)
        assertEquals(1, t.suppressed)
        assertEquals(1, t.rejected)
    }
}
