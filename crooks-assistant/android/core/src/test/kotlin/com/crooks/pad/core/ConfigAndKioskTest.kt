package com.crooks.pad.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BackoffTest {

    @Test fun `the ladder climbs and then stops climbing`() {
        assertEquals(1_000L, Backoff.delayMs(0))
        assertEquals(2_000L, Backoff.delayMs(1))
        assertEquals(4_000L, Backoff.delayMs(2))
        assertEquals(8_000L, Backoff.delayMs(3))
        assertEquals(15_000L, Backoff.delayMs(4))
        assertEquals(30_000L, Backoff.delayMs(5))
        assertEquals(30_000L, Backoff.delayMs(6))
        assertEquals(30_000L, Backoff.delayMs(500))
    }

    @Test fun `the cap is half a minute, not a minute`() {
        // A pad sitting sixty seconds from its next attempt when the Mac comes on is a pad
        // that makes "turn the Mac on and do nothing else" false. /ping is a few hundred bytes.
        assertEquals(Backoff.MAX_DELAY_MS, Backoff.delayMs(99))
        assertTrue(Backoff.MAX_DELAY_MS <= 30_000L)
    }

    @Test fun `a negative attempt is treated as the first`() {
        assertEquals(1_000L, Backoff.delayMs(-1))
    }

    @Test fun `jitter stays inside twenty per cent either way`() {
        for (attempt in 0..7) {
            val base = Backoff.delayMs(attempt)
            assertEquals((base * 0.8).toLong(), Backoff.jitteredMs(attempt, 0.0))
            val top = Backoff.jitteredMs(attempt, 0.999999)
            assertTrue("jitter must not exceed +20%", top <= (base * 1.2).toLong())
            assertTrue("jitter must reach most of +20%", top >= (base * 1.19).toLong())
            // Out-of-range randomness is clamped rather than trusted.
            assertEquals((base * 0.8).toLong(), Backoff.jitteredMs(attempt, -5.0))
            assertTrue(Backoff.jitteredMs(attempt, 7.0) <= (base * 1.2).toLong())
        }
    }

    @Test fun `a jittered delay is never zero`() {
        assertTrue(Backoff.jitteredMs(0, 0.0) > 0)
    }
}

class PadConfigTest {

    private val CROOKS = "https://crooks-assistant.taildfb357.ts.net"

    @Test fun `the configured origin produces a start url and an allow-list`() {
        val config = PadConfig.parse(CROOKS)
        assertTrue(config is PadConfig.Valid)
        config as PadConfig.Valid
        assertEquals("$CROOKS/", config.startUrl)
        assertTrue(config.allowList.allows(config.startUrl))
        assertFalse(config.allowList.allows("https://evil.example/"))
    }

    @Test fun `a trailing slash in the build config is tolerated, not punished`() {
        val config = PadConfig.parse("$CROOKS/") as PadConfig.Valid
        assertEquals("$CROOKS/", config.startUrl)
    }

    @Test fun `a broken address fails loudly rather than spinning`() {
        // The worst available outcome is a CROOKS-branded screen that will never finish and
        // no part of the product saying why. Each of these goes to APP ERROR before the
        // WebView is even created.
        for (bad in listOf(null, "", "   ", "htps://crooks-assistant.taildfb357.ts.net",
                           "http://crooks-assistant.taildfb357.ts.net", "crooks-assistant.taildfb357.ts.net",
                           "https://crooks-assistant.taildfb357.ts.net/app", "https://")) {
            val config = PadConfig.parse(bad)
            assertTrue("$bad must not be accepted", config is PadConfig.Invalid)
            assertTrue("the refusal must say something usable", (config as PadConfig.Invalid).reason.isNotEmpty())
        }
    }
}

class PadVersionTest {

    @Test fun `versions compare by number, not by string`() {
        assertEquals(-1, PadVersion.compare("0.9.0", "0.10.0"))
        assertEquals(1, PadVersion.compare("1.0.0", "0.99.99"))
        assertEquals(0, PadVersion.compare("1.2.3", "1.2.3"))
        assertEquals(0, PadVersion.compare("1.2", "1.2.0"))
        assertEquals(0, PadVersion.compare("1", "1.0.0"))
    }

    @Test fun `anything that is not a plain version is unparseable rather than guessed at`() {
        assertNull(PadVersion.parse("1.2.3-beta"))
        assertNull(PadVersion.parse("v1.2.3"))
        assertNull(PadVersion.parse("1.2.3.4"))
        assertNull(PadVersion.parse(""))
        assertNull(PadVersion.parse(null))
        assertNull(PadVersion.compare("1.0.0", "banana"))
    }

    @Test fun `the version gate fails OPEN, and that is deliberate`() {
        // Everywhere else in CROOKS an unknown answer fails closed. Not here: this gate
        // decides whether the pad REFUSES TO WORK, and one typo in a field nobody looks at
        // would otherwise stop every tablet in the building with nothing the owner can do
        // from the tablet. Nothing is being mutated and nothing is being trusted; the shell
        // is only deciding whether to disable itself, and the lesser harm is plainly to
        // carry on. If this assertion is ever inverted, read the note in PadConfig.kt first.
        assertEquals(UpdateVerdict.UNKNOWN, UpdatePolicy.verdict("0.1.0", "not a version"))
        assertEquals(UpdateVerdict.UNKNOWN, UpdatePolicy.verdict("garbage", "0.2.0"))
    }

    @Test fun `a Mac that says nothing is a Mac with no opinion`() {
        // Which is the case today: no endpoint in the current backend carries a minimum pad
        // version, so UPDATE REQUIRED is unreachable in production until one does.
        assertEquals(UpdateVerdict.UP_TO_DATE, UpdatePolicy.verdict("0.1.0", null))
        assertEquals(UpdateVerdict.UP_TO_DATE, UpdatePolicy.verdict("0.1.0", ""))
    }

    @Test fun `a shell older than the minimum is stopped`() {
        assertEquals(UpdateVerdict.UPDATE_REQUIRED, UpdatePolicy.verdict("0.1.0", "0.2.0"))
        assertEquals(UpdateVerdict.UP_TO_DATE, UpdatePolicy.verdict("0.2.0", "0.2.0"))
        assertEquals(UpdateVerdict.UP_TO_DATE, UpdatePolicy.verdict("0.3.0", "0.2.0"))
    }
}

class KioskCapabilityTest {

    private fun facts(owner: Boolean = false, lockTask: Boolean = true, knox: Boolean = false, home: Boolean = false) =
        KioskFacts(isDeviceOwner = owner, lockTaskAvailable = lockTask, knoxPresent = knox, isDefaultHome = home)

    /**
     * THE ASSERTION THAT MATTERS. A detection routine that promotes itself the moment it meets
     * a capable device is how a one-way door gets opened by accident — and stage 3 on an
     * unmanaged tablet is a factory reset to undo, on a device nobody in the building can
     * reflash, discovered a week after it happens.
     */
    @Test fun `a fully capable tablet still runs stage 1`() {
        val readiness = KioskCapability.assess(facts(owner = true, lockTask = true, knox = true, home = true))
        assertTrue(KioskStage.STAGE_2_LOCK_TASK in readiness.available)
        assertTrue(KioskStage.STAGE_3_DEVICE_OWNER in readiness.available)
        assertEquals("Phase 6 ships stage 1 and only stage 1", KioskStage.STAGE_1_IMMERSIVE, readiness.enabled)
    }

    @Test fun `stage 1 is always available, whatever the tablet is`() {
        assertTrue(KioskStage.STAGE_1_IMMERSIVE in KioskCapability.assess(facts(lockTask = false)).available)
    }

    @Test fun `device ownership is what unlocks stage 3, and nothing else pretends to`() {
        assertFalse(KioskStage.STAGE_3_DEVICE_OWNER in KioskCapability.assess(facts(owner = false, knox = true)).available)
        assertTrue(KioskStage.STAGE_3_DEVICE_OWNER in KioskCapability.assess(facts(owner = true)).available)
    }

    @Test fun `Knox is reported, never assumed, and never used`() {
        // The SM-T290 is a consumer Galaxy Tab A. `if (isSamsung) useKnox()` produces an app
        // that crashes on exactly the device it was written for.
        val without = KioskCapability.assess(facts(knox = false))
        assertTrue(without.note.contains("No Knox"))
        val with = KioskCapability.assess(facts(knox = true))
        assertTrue(with.note.contains("Knox was found"))
        assertTrue("Knox must not change what is enabled", with.enabled == without.enabled)
    }

    @Test fun `the note says why the higher stages are off, in plain words`() {
        val note = KioskCapability.assess(facts()).note
        assertTrue(note.contains("Stage 1"))
        assertTrue(note.contains("deliberately off") || note.contains("not available"))
    }
}

class BootPolicyTest {

    @Test fun `an ordinary boot starts CROOKS`() {
        val decision = BootPolicy.decide("android.intent.action.BOOT_COMPLETED", true, userUnlocked = true, isDefaultHome = false)
        assertEquals(BootAction.START, decision.action)
    }

    @Test fun `a boot before the user has unlocked does not start CROOKS`() {
        // App-private storage is unreadable and the WebView cannot be created. Starting here
        // produces a black screen and a crash, which is worse than not starting.
        val decision = BootPolicy.decide("android.intent.action.LOCKED_BOOT_COMPLETED", true, userUnlocked = false, isDefaultHome = false)
        assertEquals(BootAction.SKIP, decision.action)
        assertEquals("locked_boot_too_early", decision.reason)
    }

    @Test fun `the home role is named as the thing that will start it instead`() {
        val decision = BootPolicy.decide("android.intent.action.LOCKED_BOOT_COMPLETED", true, userUnlocked = false, isDefaultHome = true)
        assertEquals("locked_boot_home_will_start", decision.reason)
    }

    @Test fun `an in-place update comes straight back`() {
        // Otherwise the owner finds the tablet on the launcher after an update, which is
        // exactly the "no make up, no Terminal" promise broken by a background job.
        val decision = BootPolicy.decide("android.intent.action.MY_PACKAGE_REPLACED", true, true, false)
        assertEquals(BootAction.START, decision.action)
    }

    @Test fun `autostart off means off, whatever the broadcast`() {
        for (action in listOf("android.intent.action.BOOT_COMPLETED", "android.intent.action.MY_PACKAGE_REPLACED")) {
            assertEquals(BootAction.SKIP, BootPolicy.decide(action, autoStartEnabled = false, userUnlocked = true, isDefaultHome = true).action)
        }
    }

    @Test fun `an unexpected broadcast does nothing`() {
        // The receiver is exported, so anything on the device can send it an intent. It must
        // do nothing interesting for anything it was not registered for.
        assertEquals(BootAction.SKIP, BootPolicy.decide("com.evil.LAUNCH_NOW", true, true, true).action)
        assertEquals(BootAction.SKIP, BootPolicy.decide(null, true, true, true).action)
    }
}

class RecoveryCardTest {

    @Test fun `no state is a dead end and no state is a bare spinner`() {
        for (state in PadState.entries) {
            if (state == PadState.ONLINE) continue
            val card = RecoveryCards.forState(state)
            assertTrue(
                "$state must either retry by itself or offer something to press",
                card.retriesAutomatically || card.actions.isNotEmpty(),
            )
            assertTrue(
                "$state must offer diagnostics — it may be the only screen the owner can reach",
                RecoveryAction.DIAGNOSTICS in card.actions,
            )
        }
    }

    @Test fun `a terminal state offers Retry even though it does not retry itself`() {
        for (state in listOf(PadState.APP_ERROR, PadState.UPDATE_REQUIRED)) {
            val card = RecoveryCards.forState(state)
            assertFalse(card.retriesAutomatically)
            assertTrue(RecoveryAction.RETRY in card.actions)
        }
    }

    @Test fun `the countdown rounds up, so it never shows a stuck zero`() {
        assertEquals(3, RecoveryCards.secondsUntilRetry(3_000, 0))
        assertEquals(3, RecoveryCards.secondsUntilRetry(2_001, 0))
        assertEquals(1, RecoveryCards.secondsUntilRetry(1, 0))
        assertEquals(0, RecoveryCards.secondsUntilRetry(0, 0))
        assertEquals(0, RecoveryCards.secondsUntilRetry(-5_000, 0))
        assertNull(RecoveryCards.secondsUntilRetry(null, 0))
    }
}

class DeviceSnapshotTest {

    private fun snapshot(model: String = "SM-T290") = DeviceSnapshot(
        batteryPercent = 91, charging = true, powerSource = "ac",
        networkOnline = true, transport = Transport.WIFI, wifiSignalBars = 3,
        deviceModel = model, androidRelease = "11", apiLevel = 30,
        appVersionName = "0.1.0", appVersionCode = 1,
        orientation = "portrait", foreground = true, screenOn = true,
        msSinceResume = 4_200, padState = "ONLINE",
    )

    @Test fun `the snapshot encodes as JSON with no trailing comma`() {
        val json = snapshot().toJson()
        assertTrue(json.startsWith("{"))
        assertTrue(json.endsWith("}"))
        assertFalse(json.contains(",}"))
        assertTrue(json.contains("\"battery_percent\":91"))
        assertTrue(json.contains("\"charging\":true"))
        assertTrue(json.contains("\"transport\":\"wifi\""))
        assertTrue(json.contains("\"device_model\":\"SM-T290\""))
    }

    @Test fun `absent values are null rather than absent`() {
        val json = snapshot().copy(wifiSignalBars = null, msSinceResume = null).toJson()
        assertTrue(json.contains("\"wifi_signal_bars\":null"))
        assertTrue(json.contains("\"ms_since_resume\":null"))
    }

    @Test fun `a hostile manufacturer string cannot break out of the JSON`() {
        // Build.MODEL is manufacturer-supplied and has historically contained quotes. The
        // value crosses into a JavaScript engine, so it is escaped here rather than hoped about.
        val json = snapshot(model = "SM\"-T290\\\n evil").toJson()
        assertTrue(json.contains("\\\""))
        assertTrue(json.contains("\\\\"))
        assertTrue(json.contains("\\n"))
        assertTrue("U+2028 is legal JSON and illegal JavaScript", json.contains("\\u2028"))
        assertFalse("no raw newline may survive", json.contains("\n"))
    }

    @Test fun `the snapshot carries the running test session, so the page need not poll health`() {
        // CONTRACT 1: the heartbeat's answer carries the Mac's test session, and the page reads
        // it from here. `POST /telemetry` keeps nothing unless a session is running, so the page
        // has to know — and a second clock in the page asking /health for a field the beat just
        // fetched is a second failure mode for no new information.
        assertTrue(snapshot().copy(testSession = "session-2026-09-13").toJson()
            .contains("\"test_session\":\"session-2026-09-13\""))
        // Absent rather than omitted, like every other nullable field on this snapshot: a page
        // reading `undefined` cannot tell "no session" from "old shell".
        assertTrue(snapshot().toJson().contains("\"test_session\":null"))
        assertFalse("no trailing comma", snapshot().toJson().contains(",}"))
    }

    @Test fun `the snapshot carries nothing that identifies a person or a place`() {
        // §6.5 and invariant 10, held as a shape rather than as a promise: read the field
        // names of the encoded form and check that none of the forbidden ones is among them.
        val json = snapshot().toJson()
        for (forbidden in listOf("ssid", "bssid", "mac_address", "ip", "serial", "imei",
                                 "android_id", "advertising_id", "account", "email", "latitude", "token")) {
            assertFalse("the device bridge must never carry $forbidden", json.contains(forbidden))
        }
    }
}
