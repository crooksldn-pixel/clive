package com.crooks.pad.core

import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec

/**
 * CROOKS Pad — §12, the way out, and why it is a pair of volume keys.
 *
 * THE GESTURE IS NOT A TOUCH GESTURE, AND THAT IS THE WHOLE POINT. The obvious design is a
 * hidden hit region — five taps in the top-left corner, a long press on the wordmark, a
 * two-finger hold. Every one of those is the Phase 4 defect with a smaller rectangle. In
 * Phase 4, sixty-three ordinary control taps became voice recordings because an invisible
 * surface sat where the controls were; the lesson recorded in web/touch.js is explicit that
 * the fix "is not a bigger hit region with more exceptions". Putting a new invisible
 * rectangle into the native shell — where it would sit ABOVE the WebView and therefore above
 * every control in the product — would be committing the same error in the one layer that
 * cannot be argued with from JavaScript.
 *
 * So the admin gesture consumes no touch events at all. It is a sequence of volume-key
 * presses: VOLUME_DOWN, VOLUME_UP, VOLUME_DOWN, VOLUME_UP, VOLUME_DOWN, VOLUME_UP. Six
 * presses, alternating, each within [MAX_GAP_MS] of the one before.
 *
 * Three properties fall out of that choice, and each is worth having:
 *
 *   - The WebView never sees a volume key, so no CROOKS control can be stolen by it, ever,
 *     under any layout, at any density. The class of defect is unreachable rather than
 *     avoided.
 *   - The presses are not consumed. The volume genuinely goes down and up as they are pressed,
 *     which means (a) the owner adjusting the volume is not fighting the shell, and (b) the
 *     sequence is volume-neutral: six alternating presses end where they began.
 *   - It is not discoverable by a customer leaning on the tablet, and it survives the screen
 *     being anywhere — the recovery card, the workspace, a modal in the web layer.
 *
 * An accidental trigger costs nothing: the PIN sheet appears with a Close button and no
 * information on it.
 */
object AdminGesture {

    const val KEY_VOLUME_UP = 24     // android.view.KeyEvent.KEYCODE_VOLUME_UP
    const val KEY_VOLUME_DOWN = 25   // android.view.KeyEvent.KEYCODE_VOLUME_DOWN

    /** The sequence, start to finish. */
    val SEQUENCE = intArrayOf(
        KEY_VOLUME_DOWN, KEY_VOLUME_UP, KEY_VOLUME_DOWN, KEY_VOLUME_UP, KEY_VOLUME_DOWN, KEY_VOLUME_UP,
    )

    /** How long a press may lag the one before it before the sequence is considered abandoned. */
    const val MAX_GAP_MS: Long = 1_200
}

/**
 * Recognises [AdminGesture.SEQUENCE]. Stateful, cheap, and deliberately forgiving about
 * restarts: a press that does not continue the sequence but does start it restarts the
 * sequence rather than killing it, so an owner who fumbles the first press is not locked out
 * of trying again for a second.
 */
class AdminGestureRecogniser {

    private var index = 0
    private var lastAt = 0L

    /**
     * @param isRepeat true for auto-repeat while a key is held. Held keys are ignored: a held
     *   volume key is someone changing the volume, not someone entering a sequence.
     * @return true exactly once, on the press that completes the sequence.
     */
    fun onKeyDown(keyCode: Int, isRepeat: Boolean, now: Long): Boolean {
        if (isRepeat) return false
        if (keyCode != AdminGesture.KEY_VOLUME_UP && keyCode != AdminGesture.KEY_VOLUME_DOWN) {
            // Any other key abandons the attempt. There are almost none on this tablet, but a
            // sequence that could be interleaved with other input would be a sequence that
            // could be entered by accident over a minute of ordinary use.
            index = 0
            return false
        }
        if (index > 0 && now - lastAt > AdminGesture.MAX_GAP_MS) index = 0
        lastAt = now

        if (keyCode == AdminGesture.SEQUENCE[index]) {
            index++
            if (index == AdminGesture.SEQUENCE.size) { index = 0; return true }
            return false
        }
        // Wrong key. If it is the key the sequence starts with, this press is the new first
        // press; otherwise we are back to nothing.
        index = if (keyCode == AdminGesture.SEQUENCE[0]) 1 else 0
        return false
    }

    fun reset() { index = 0 }

    /** For diagnostics only: how far through the sequence the recogniser currently is. */
    fun progress(): Int = index
}

/**
 * The PIN.
 *
 * §28 says no admin PIN in source, and this file contains none — there is no default, no
 * fallback, no "engineering" code. A tablet with no PIN set has not been provisioned, and the
 * first time the gesture is performed it offers to set one instead of asking for one. That
 * enrolment window closes the moment a PIN exists and cannot be reopened from inside the app:
 * the only reset is clearing the app's data from Android Settings, which needs the same
 * physical access to an unlocked tablet that setting it did.
 *
 * Storage is a PBKDF2-HMAC-SHA256 hash with a random 16-byte salt, encoded with its own
 * iteration count so the cost can be raised later without stranding existing tablets. It
 * lives in app-private shared preferences, and backup and device-transfer are both switched
 * off in the manifest — a hash that has been copied into a cloud backup is a hash that can be
 * attacked by someone who never touched the tablet.
 *
 * What this does NOT claim: it is not hardware-backed. A six-digit PIN is a hundred thousand
 * possibilities, and an attacker who has extracted the preferences file — which needs root,
 * or an unlocked bootloader, or ADB with the device already trusted — can grind it offline
 * whatever the iteration count. The iteration count buys minutes, not safety. The honest
 * statement of the boundary is: this PIN keeps a customer, a curious member of staff or a
 * child out of the admin screen on a tablet sitting on a counter. It does not defend against
 * someone who has taken the tablet away and opened it up, and the upgrade if that ever
 * matters is an Android Keystore-backed key, written down here rather than left implied.
 */
object PinHasher {

    private const val ALGORITHM = "PBKDF2WithHmacSHA256"

    /**
     * 120,000 iterations. On the SM-T290's Exynos 7904 this is expected to be on the order of
     * a second — slow enough to be worth something against a grind, fast enough that an owner
     * typing a PIN does not think the tablet has hung. It is UNMEASURED on that hardware:
     * this repository has no attached device, so the figure is reasoned from the chip, not
     * timed on it, and the first person to run this on the real tablet should time it and say
     * so here.
     */
    const val DEFAULT_ITERATIONS = 120_000

    private const val KEY_LENGTH_BITS = 256
    private const val SALT_BYTES = 16

    fun newSalt(random: SecureRandom = SecureRandom()): ByteArray =
        ByteArray(SALT_BYTES).also { random.nextBytes(it) }

    /**
     * `pbkdf2_sha256$<iterations>$<b64 salt>$<b64 key>` — Django's shape, because it is
     * already familiar to anyone who reads the Python half of this repository, and because
     * carrying the iteration count inside the encoded value is what lets the cost be raised
     * later without stranding a tablet that was provisioned at the old cost.
     *
     * Built by concatenation rather than by a template, because a Kotlin template containing
     * a literal `$` next to an interpolation is exactly the kind of line that reads correctly
     * and compiles into something else.
     */
    const val SEPARATOR = "$"

    fun encode(pin: CharArray, salt: ByteArray, iterations: Int = DEFAULT_ITERATIONS): String {
        val key = derive(pin, salt, iterations)
        val b64 = Base64.getEncoder()
        return listOf("pbkdf2_sha256", iterations.toString(), b64.encodeToString(salt), b64.encodeToString(key))
            .joinToString(SEPARATOR)
    }

    /**
     * Constant-time against the stored hash. A PIN comparison that returns early on the first
     * wrong byte leaks the prefix to anyone who can time it; on a six-digit PIN that turns a
     * hundred thousand guesses into sixty.
     */
    fun verify(pin: CharArray, encoded: String?): Boolean {
        if (encoded.isNullOrEmpty()) return false
        val parts = encoded.split("$")
        if (parts.size != 4 || parts[0] != "pbkdf2_sha256") return false
        val iterations = parts[1].toIntOrNull() ?: return false
        if (iterations !in 1_000..2_000_000) return false
        val decoder = Base64.getDecoder()
        val salt = try { decoder.decode(parts[2]) } catch (e: IllegalArgumentException) { return false }
        val expected = try { decoder.decode(parts[3]) } catch (e: IllegalArgumentException) { return false }
        val actual = derive(pin, salt, iterations)
        return MessageDigest.isEqual(expected, actual)
    }

    private fun derive(pin: CharArray, salt: ByteArray, iterations: Int): ByteArray {
        val spec = PBEKeySpec(pin, salt, iterations, KEY_LENGTH_BITS)
        try {
            return SecretKeyFactory.getInstance(ALGORITHM).generateSecret(spec).encoded
        } finally {
            spec.clearPassword()
        }
    }
}

/** Whether a proposed PIN is acceptable. Refusals are named so the sheet can say which. */
enum class PinVerdict { OK, TOO_SHORT, NOT_DIGITS, TOO_SIMPLE }

object PinPolicy {

    const val MIN_LENGTH = 6

    /**
     * Rejected outright. Not a blocklist of "common PINs" — those lists are long, arbitrary
     * and always incomplete — but the three shapes that a person picks when they have decided
     * not to think: every digit the same, a straight run up, a straight run down. Anything
     * else is the owner's business.
     */
    fun check(pin: String): PinVerdict {
        if (pin.length < MIN_LENGTH) return PinVerdict.TOO_SHORT
        if (!pin.all { it in '0'..'9' }) return PinVerdict.NOT_DIGITS
        if (pin.toSet().size == 1) return PinVerdict.TOO_SIMPLE
        val ascending = pin.zipWithNext().all { (a, b) -> b - a == 1 }
        val descending = pin.zipWithNext().all { (a, b) -> a - b == 1 }
        if (ascending || descending) return PinVerdict.TOO_SIMPLE
        return PinVerdict.OK
    }
}

/**
 * The lockout. Five wrong PINs and the sheet stops accepting for a minute, doubling to a cap.
 *
 * The point is not to stop a determined attacker — see the note on PinHasher for what this
 * does and does not defend. It is to make a hundred thousand guesses take longer than a
 * person will stand in front of a counter, and to make the attempt visible: every lockout is
 * a `pad_admin_entered` with outcome "locked" in the timeline.
 */
class PinLockout(private val maxAttempts: Int = 5) {

    private var failures = 0
    private var lockedUntil = 0L
    private var lockoutLevel = 0

    fun isLocked(now: Long): Boolean = now < lockedUntil

    fun remainingMs(now: Long): Long = (lockedUntil - now).coerceAtLeast(0)

    /** Record a wrong PIN. Returns true when this attempt started a lockout. */
    fun onFailure(now: Long): Boolean {
        failures++
        if (failures < maxAttempts) return false
        failures = 0
        val seconds = LOCKOUT_LADDER_S[lockoutLevel.coerceAtMost(LOCKOUT_LADDER_S.size - 1)]
        lockoutLevel++
        lockedUntil = now + seconds * 1000
        return true
    }

    /** A correct PIN forgives everything, including the escalation. */
    fun onSuccess() {
        failures = 0
        lockoutLevel = 0
        lockedUntil = 0
    }

    companion object {
        private val LOCKOUT_LADDER_S = longArrayOf(60, 300, 900, 3600)
    }
}

/**
 * What the admin sheet is doing. A small machine rather than a pile of booleans, because
 * "unlocked" and "asking" and "locked out" have leaked into each other in every admin screen
 * this author has ever seen written with flags.
 */
enum class AdminPhase { CLOSED, ENROLLING, ASKING, LOCKED_OUT, OPEN }

class AdminSession(private val idleTimeoutMs: Long = IDLE_TIMEOUT_MS) {

    companion object {
        /**
         * The admin sheet closes itself after two minutes with nothing pressed. A tablet left
         * on the admin screen is a tablet with its server address, its diagnostics and its
         * "leave CROOKS" button sitting open on a counter; and §19 says the shell earns
         * visibility and then gives it back.
         */
        const val IDLE_TIMEOUT_MS: Long = 120_000
    }

    var phase: AdminPhase = AdminPhase.CLOSED
        private set

    private var lastInteractionAt = 0L
    private var openedAt = 0L

    /** The gesture fired. [hasPin] decides whether this is enrolment or a challenge. */
    fun onGesture(hasPin: Boolean, lockout: PinLockout, now: Long): AdminPhase {
        lastInteractionAt = now
        phase = when {
            lockout.isLocked(now) -> AdminPhase.LOCKED_OUT
            !hasPin -> AdminPhase.ENROLLING
            else -> AdminPhase.ASKING
        }
        return phase
    }

    fun onUnlocked(now: Long): AdminPhase {
        openedAt = now
        lastInteractionAt = now
        phase = AdminPhase.OPEN
        return phase
    }

    fun onInteraction(now: Long) { lastInteractionAt = now }

    fun close(now: Long): Long {
        val open = if (openedAt == 0L) 0L else now - openedAt
        phase = AdminPhase.CLOSED
        openedAt = 0L
        return open
    }

    /** Called on a timer. True when the sheet has just been closed for being left alone. */
    fun expireIfIdle(now: Long): Boolean {
        if (phase == AdminPhase.CLOSED) return false
        if (now - lastInteractionAt < idleTimeoutMs) return false
        close(now)
        return true
    }
}
