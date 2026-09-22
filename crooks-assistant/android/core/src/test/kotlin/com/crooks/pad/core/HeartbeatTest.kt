package com.crooks.pad.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * CONTRACT 1, §16 — the heartbeat, and in particular the one assertion the whole design exists
 * for: THE CADENCE IS NOT A KOTLIN CONSTANT.
 */
class HeartbeatTest {

    private fun beat() = Heartbeat(
        appVersion = "0.1.0",
        deviceModel = "SM-T290",
        osVersion = "Android 11 (api 30)",
        bootId = "boot-abc",
    )

    /**
     * THE TEST THIS FILE EXISTS FOR.
     *
     * A shell that posts on a timer built from a constant compiled into the APK has a cadence
     * nobody can change without a cable and a tablet in their hand. The contract is that the
     * backend's `interval_s` decides, on EVERY beat — so a Mac that answers 45 moves the next
     * beat to 45 seconds, and the number in the Kotlin is left behind the moment the first
     * answer arrives.
     *
     * The assertion is deliberately written against a number that is NOT the built-in default,
     * and asserts that fact first: a test that happened to choose 20 would pass against a shell
     * that ignored the field entirely, which is the "green because the double answered" trap.
     */
    @Test fun `the backend's interval_s becomes the cadence, not the built-in default`() {
        val h = beat()
        assertEquals(
            "the first beat may use the built-in default, and only the first",
            Heartbeat.DEFAULT_INTERVAL_S,
            h.intervalS,
        )
        assertFalse(h.cadenceCameFromBackend)
        assertFalse(
            "this test is worthless if 45 is what the constant already says",
            Heartbeat.DEFAULT_INTERVAL_S == 45,
        )

        h.onAnswer(intervalS = 45, testSession = null)

        assertEquals(45, h.intervalS)
        assertEquals(45_000L, h.intervalMs())
        assertTrue(h.cadenceCameFromBackend)

        // And the scheduler really moves: the next beat is due 45 seconds after the last one,
        // and is NOT due at the old cadence.
        val lastBeatAt = 1_000_000L
        assertEquals(1_045_000L, h.nextBeatDueAt(lastBeatAt))
        assertFalse("a beat at 20s would be the Kotlin constant still in charge", h.isDue(1_020_000L, lastBeatAt))
        assertFalse(h.isDue(1_044_999L, lastBeatAt))
        assertTrue(h.isDue(1_045_000L, lastBeatAt))
    }

    @Test fun `every answer decides again, so the Mac can speed up and slow down`() {
        val h = beat()
        h.onAnswer(60, null)
        assertEquals(60, h.intervalS)
        h.onAnswer(10, null)
        assertEquals("the cadence is read on every beat, not latched on the first", 10, h.intervalS)
    }

    @Test fun `an answer with no interval leaves the last one the Mac gave`() {
        // Not the built-in default: the last number the backend chose is a better guess about
        // what the backend wants than a constant compiled into the tablet in March.
        val h = beat()
        h.onAnswer(45, null)
        h.onAnswer(null, null)
        assertEquals(45, h.intervalS)
        h.onAnswer(0, null)
        assertEquals(45, h.intervalS)
    }

    @Test fun `the rails hold, so a broken answer cannot make a packet storm or a silent pad`() {
        val h = beat()
        h.onAnswer(0 - 5, null)
        assertEquals("a negative interval is not an instruction", Heartbeat.DEFAULT_INTERVAL_S, h.intervalS)
        h.onAnswer(1, null)
        assertEquals(Heartbeat.MIN_INTERVAL_S, h.intervalS)
        h.onAnswer(999_999, null)
        assertEquals(Heartbeat.MAX_INTERVAL_S, h.intervalS)
    }

    @Test fun `the test session comes off the answer and is dropped when a beat fails`() {
        val h = beat()
        assertNull(h.testSessionId)
        h.onAnswer(20, "session-2026-09-13")
        assertEquals("session-2026-09-13", h.testSessionId)
        // The endpoint's JSONObject.optString gives "" for an absent field and the literal
        // string "null" for a JSON null. Neither is a session.
        h.onAnswer(20, "")
        assertNull(h.testSessionId)
        h.onAnswer(20, "null")
        assertNull(h.testSessionId)
        h.onAnswer(20, "session-2")
        h.onBeatFailed()
        assertNull("a session the pad can no longer confirm must stop being claimed", h.testSessionId)
    }

    @Test fun `a failed beat does not change the cadence`() {
        // A Mac that is off is not a Mac asking for a different cadence.
        val h = beat()
        h.onAnswer(45, null)
        h.onBeatFailed()
        assertEquals(45, h.intervalS)
    }

    @Test fun `the body carries exactly the five facts CONTRACT 1 names`() {
        val body = beat().body(at = 1_700_000_000_000L)
        assertTrue(body.contains("\"app_version\":\"0.1.0\""))
        assertTrue(body.contains("\"device_model\":\"SM-T290\""))
        assertTrue(body.contains("\"os_version\":\"Android 11 (api 30)\""))
        // Epoch MILLISECONDS, matching `t` on every event and Date.now() in web/telemetry.js.
        // The Mac's clock_skew_s is in seconds and divides; the unit is asserted here because
        // it is the one field on the wire whose unit cannot be inferred from the value.
        assertTrue(body.contains("\"at\":1700000000000"))
        assertTrue(body.contains("\"boot_id\":\"boot-abc\""))
        // `events` is optional in the contract and absent rather than empty when there are none.
        assertFalse(body.contains("events"))
        assertTrue(body.startsWith("{"))
        assertTrue(body.endsWith("}"))
        assertFalse("a trailing comma is not JSON", body.contains(",}"))
    }

    @Test fun `queued events ride the beat rather than going to slash telemetry`() {
        val body = beat().body(
            at = 5,
            events = listOf(
                PadEvent("pad_app_started", mapOf("name" to "CROOKS Pad 0.1.0", "t" to 4L)),
                PadEvent("pad_battery", mapOf("percent" to 90, "charging" to true, "t" to 5L)),
            ),
        )
        assertTrue(body.contains("\"events\":["))
        assertTrue(body.contains("\"kind\":\"pad_app_started\""))
        assertTrue(body.contains("\"name\":\"CROOKS Pad 0.1.0\""))
        assertTrue(body.contains("\"kind\":\"pad_battery\""))
        assertTrue("a number must not be quoted", body.contains("\"percent\":90"))
        assertTrue("a boolean must not be quoted", body.contains("\"charging\":true"))
        assertFalse(body.contains(",]"))
        assertFalse(body.contains(",}"))
    }

    @Test fun `a hostile manufacturer string cannot break out of the body`() {
        // Build.MODEL is manufacturer-supplied and has historically contained quotes.
        val h = Heartbeat("0.1.0", "SM\"-T290\\\n evil", "11", "boot")
        val body = h.body(at = 1)
        assertTrue(body.contains("\\\""))
        assertTrue(body.contains("\\\\"))
        assertTrue(body.contains("\\n"))
        assertFalse("no raw newline may survive into the body", body.contains("\n"))
    }

    @Test fun `the endpoint and the response field names are stated once, here`() {
        // The Android side spells nothing itself; if the Mac renames a field the change lands
        // in one place. CONTRACT 1 names all three.
        assertEquals("/pad/heartbeat", Heartbeat.PATH)
        assertEquals("interval_s", Heartbeat.KEY_INTERVAL_S)
        assertEquals("test_session", Heartbeat.KEY_TEST_SESSION)
    }
}
