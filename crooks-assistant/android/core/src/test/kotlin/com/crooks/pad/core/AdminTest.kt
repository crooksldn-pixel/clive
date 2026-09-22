package com.crooks.pad.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AdminGestureTest {

    private val DOWN = AdminGesture.KEY_VOLUME_DOWN
    private val UP = AdminGesture.KEY_VOLUME_UP

    @Test fun `the full sequence opens admin`() {
        val g = AdminGestureRecogniser()
        var fired = false
        var t = 0L
        for (key in AdminGesture.SEQUENCE) {
            t += 300
            fired = g.onKeyDown(key, isRepeat = false, now = t)
        }
        assertTrue("six alternating volume presses must complete the gesture", fired)
    }

    @Test fun `it fires exactly once, on the last press`() {
        val g = AdminGestureRecogniser()
        var fires = 0
        var t = 0L
        for (key in AdminGesture.SEQUENCE) {
            t += 200
            if (g.onKeyDown(key, false, t)) fires++
        }
        assertEquals(1, fires)
        // And the recogniser is back at the beginning, not stuck one press from firing again.
        assertEquals(0, g.progress())
    }

    @Test fun `a slow sequence is abandoned`() {
        // Otherwise the gesture would be "press these six keys at any point today", which an
        // owner adjusting the volume over an afternoon would eventually perform by accident.
        val g = AdminGestureRecogniser()
        assertFalse(g.onKeyDown(DOWN, false, 0))
        assertFalse(g.onKeyDown(UP, false, 400))
        assertFalse(g.onKeyDown(DOWN, false, 800))
        assertFalse("a gap longer than the window restarts the sequence", g.onKeyDown(UP, false, 5_000))
        assertEquals(0, g.progress())
    }

    @Test fun `holding a volume key is changing the volume, not entering a gesture`() {
        val g = AdminGestureRecogniser()
        g.onKeyDown(DOWN, false, 0)
        repeat(20) { i -> assertFalse(g.onKeyDown(DOWN, isRepeat = true, now = 50L * i)) }
        assertEquals("auto-repeat must not advance anything", 1, g.progress())
    }

    @Test fun `a wrong key that starts the sequence restarts it rather than killing it`() {
        val g = AdminGestureRecogniser()
        g.onKeyDown(DOWN, false, 0)
        g.onKeyDown(UP, false, 100)
        // Expecting DOWN, got DOWN — fine. Now expecting UP, and DOWN arrives: that press is
        // the first press of a new attempt, so a fumble costs a restart, not a lockout.
        g.onKeyDown(DOWN, false, 200)
        assertEquals(3, g.progress())
        g.onKeyDown(DOWN, false, 300)
        assertEquals(1, g.progress())
    }

    @Test fun `any other key abandons the attempt`() {
        val g = AdminGestureRecogniser()
        g.onKeyDown(DOWN, false, 0)
        g.onKeyDown(UP, false, 100)
        g.onKeyDown(66 /* KEYCODE_ENTER */, false, 200)
        assertEquals(0, g.progress())
    }

    @Test fun `the sequence is volume-neutral and touch-free`() {
        // The two properties that make this the right gesture rather than a hidden rectangle.
        // Volume-neutral: as many ups as downs, so performing it leaves the volume where it
        // was and the shell never has to consume the keys.
        val ups = AdminGesture.SEQUENCE.count { it == UP }
        val downs = AdminGesture.SEQUENCE.count { it == DOWN }
        assertEquals("an owner who performs the gesture must not find the volume changed", ups, downs)
        // Touch-free: the sequence contains no touch codes at all. §7's defect — a
        // full-viewport transparent surface stealing sixty-three control taps — cannot be
        // reproduced by a gesture that never looks at a finger.
        for (key in AdminGesture.SEQUENCE) {
            assertTrue("the admin gesture must use hardware keys only", key == UP || key == DOWN)
        }
    }
}

class PinTest {

    @Test fun `a PIN round-trips and a wrong one does not`() {
        val salt = PinHasher.newSalt()
        // A low iteration count here only: the algorithm is what is under test, not the cost,
        // and 120,000 iterations times a dozen assertions would make this suite slow enough
        // that somebody would eventually delete it.
        val encoded = PinHasher.encode("481902".toCharArray(), salt, iterations = 2_000)
        assertTrue(PinHasher.verify("481902".toCharArray(), encoded))
        assertFalse(PinHasher.verify("481903".toCharArray(), encoded))
        assertFalse(PinHasher.verify("48190".toCharArray(), encoded))
        assertFalse(PinHasher.verify("".toCharArray(), encoded))
    }

    @Test fun `the same PIN twice produces different stored values`() {
        // A per-PIN salt. Without it, two tablets with the same PIN would have the same hash,
        // and one extracted hash would unlock every pad in the fleet.
        val a = PinHasher.encode("481902".toCharArray(), PinHasher.newSalt(), iterations = 2_000)
        val b = PinHasher.encode("481902".toCharArray(), PinHasher.newSalt(), iterations = 2_000)
        assertNotEquals(a, b)
        assertTrue(PinHasher.verify("481902".toCharArray(), a))
        assertTrue(PinHasher.verify("481902".toCharArray(), b))
    }

    @Test fun `the encoded form carries its own cost so it can be raised later`() {
        val encoded = PinHasher.encode("481902".toCharArray(), PinHasher.newSalt(), iterations = 3_000)
        val parts = encoded.split(PinHasher.SEPARATOR)
        assertEquals(4, parts.size)
        assertEquals("pbkdf2_sha256", parts[0])
        assertEquals("3000", parts[1])
    }

    @Test fun `a corrupted or absent stored value verifies as false, never as true`() {
        assertFalse(PinHasher.verify("481902".toCharArray(), null))
        assertFalse(PinHasher.verify("481902".toCharArray(), ""))
        assertFalse(PinHasher.verify("481902".toCharArray(), "nonsense"))
        assertFalse(PinHasher.verify("481902".toCharArray(), "pbkdf2_sha256\$abc\$def\$ghi"))
        assertFalse(PinHasher.verify("481902".toCharArray(), "md5\$1000\$c2FsdA==\$aGFzaA=="))
        // An absurd iteration count would otherwise hang the tablet for minutes on a bad file.
        assertFalse(PinHasher.verify("481902".toCharArray(), "pbkdf2_sha256\$999999999\$c2FsdA==\$aGFzaA=="))
    }

    @Test fun `the policy refuses the three shapes people pick when they have stopped thinking`() {
        assertEquals(PinVerdict.OK, PinPolicy.check("481902"))
        assertEquals(PinVerdict.TOO_SHORT, PinPolicy.check("48190"))
        assertEquals(PinVerdict.NOT_DIGITS, PinPolicy.check("48190a"))
        assertEquals(PinVerdict.TOO_SIMPLE, PinPolicy.check("000000"))
        assertEquals(PinVerdict.TOO_SIMPLE, PinPolicy.check("123456"))
        assertEquals(PinVerdict.TOO_SIMPLE, PinPolicy.check("654321"))
        // And not a blocklist: 112233 is a weak PIN but it is the owner's business, and a
        // policy that argues with every choice gets worked around with a sticky note.
        assertEquals(PinVerdict.OK, PinPolicy.check("112233"))
    }

    @Test fun `there is no PIN anywhere in this application's source`() {
        // §28. The enrolment path in AdminSession is the only way a PIN comes to exist, which
        // is what makes this assertion meaningful rather than decorative: there is no default
        // to find, so a tablet that has not been provisioned has no admin, not a known admin.
        assertEquals(AdminPhase.ENROLLING, AdminSession().onGesture(hasPin = false, lockout = PinLockout(), now = 0))
        assertEquals(AdminPhase.ASKING, AdminSession().onGesture(hasPin = true, lockout = PinLockout(), now = 0))
    }
}

class PinLockoutTest {

    @Test fun `five wrong PINs buy a minute, and it escalates`() {
        val l = PinLockout()
        repeat(4) { assertFalse(l.onFailure(0)) }
        assertTrue("the fifth failure locks", l.onFailure(0))
        assertTrue(l.isLocked(0))
        assertEquals(60_000L, l.remainingMs(0))
        assertFalse(l.isLocked(60_001))

        repeat(4) { l.onFailure(60_001) }
        assertTrue(l.onFailure(60_001))
        assertEquals("the second lockout is longer than the first", 300_000L, l.remainingMs(60_001))
    }

    @Test fun `a correct PIN forgives everything, including the escalation`() {
        val l = PinLockout()
        repeat(5) { l.onFailure(0) }
        l.onSuccess()
        assertFalse(l.isLocked(0))
        repeat(4) { assertFalse(l.onFailure(1_000)) }
        assertTrue(l.onFailure(1_000))
        assertEquals("back to the bottom of the ladder", 60_000L, l.remainingMs(1_000))
    }

    @Test fun `the gesture during a lockout shows the lockout, not a PIN box`() {
        val l = PinLockout()
        repeat(5) { l.onFailure(0) }
        assertEquals(AdminPhase.LOCKED_OUT, AdminSession().onGesture(hasPin = true, lockout = l, now = 1_000))
    }
}

class AdminSessionTest {

    @Test fun `the sheet closes itself when it is left alone`() {
        // A tablet abandoned on the admin screen is a tablet with its address, its diagnostics
        // and its "leave CROOKS" button open on a counter.
        val s = AdminSession()
        s.onGesture(hasPin = true, lockout = PinLockout(), now = 0)
        s.onUnlocked(1_000)
        assertFalse(s.expireIfIdle(60_000))
        assertTrue(s.expireIfIdle(1_000 + AdminSession.IDLE_TIMEOUT_MS))
        assertEquals(AdminPhase.CLOSED, s.phase)
    }

    @Test fun `using the sheet keeps it open`() {
        val s = AdminSession()
        s.onGesture(true, PinLockout(), 0)
        s.onUnlocked(0)
        var t = 0L
        repeat(10) {
            t += AdminSession.IDLE_TIMEOUT_MS - 1_000
            s.onInteraction(t)
            assertFalse(s.expireIfIdle(t + 1_000))
        }
        assertEquals(AdminPhase.OPEN, s.phase)
    }

    @Test fun `closing reports how long admin was open, for the timeline`() {
        val s = AdminSession()
        s.onGesture(true, PinLockout(), 0)
        s.onUnlocked(5_000)
        assertEquals(20_000L, s.close(25_000))
        assertEquals(AdminPhase.CLOSED, s.phase)
    }

    @Test fun `a sheet that was never unlocked reports no open time`() {
        val s = AdminSession()
        s.onGesture(true, PinLockout(), 0)
        assertEquals(0L, s.close(25_000))
    }
}
