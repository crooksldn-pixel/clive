package com.crooks.pad.core

/**
 * CROOKS Pad — how often to try again.
 *
 * The shape of the schedule matters more than its numbers, and the shape is chosen against
 * one specific failure that this product will meet constantly: THE MAC IS TURNED ON WHILE THE
 * PAD IS SITTING IN ITS LONGEST BACKOFF. The owner walks in, presses the Mac's power button,
 * picks up the tablet, and waits. If the pad is sixty seconds into a sixty-second sleep, the
 * product's whole promise — "turn the Mac on, turn the Samsung on, do nothing else" — becomes
 * "turn them on and then wait around a minute for no visible reason".
 *
 * So the backoff grows, but it is RESET rather than continued by three things that all mean
 * "the world just changed, ask again now": the network coming back, the app coming to the
 * foreground, and the owner tapping Retry. Those resets are in [ConnectionMachine]; what is
 * here is only the curve.
 *
 * The curve is bounded at thirty seconds, not sixty. A `/ping` is a few hundred bytes against
 * a Mac on the same tailnet and costs the Mac nothing measurable — the endpoint exists
 * precisely so the pad can ask cheaply — so there is no reason to buy quiet at the price of
 * half a minute of dead pad.
 */
object Backoff {

    /** Seconds, by attempt number. Attempt 0 is the first retry after the first failure. */
    private val LADDER_S = longArrayOf(1, 2, 4, 8, 15, 30)

    const val MAX_DELAY_MS: Long = 30_000

    /** The unjittered delay before attempt [attempt] (0-based). Clamped at both ends. */
    fun delayMs(attempt: Int): Long {
        if (attempt < 0) return LADDER_S[0] * 1000
        val i = if (attempt >= LADDER_S.size) LADDER_S.size - 1 else attempt
        return LADDER_S[i] * 1000
    }

    /**
     * The same delay with ±20% of jitter applied, [random] being a value in [0.0, 1.0).
     *
     * Jitter is not here for thundering-herd reasons — there is one tablet, and a second and
     * third would not constitute a herd. It is here so that a pad and a Mac that are both
     * restarting cannot settle into a rhythm where every probe lands in the same unlucky
     * window of the Mac's own startup. Passing the randomness in rather than calling
     * `Math.random()` is what lets the test pin both ends of the range exactly.
     */
    fun jitteredMs(attempt: Int, random: Double): Long {
        val base = delayMs(attempt)
        val r = when {
            random < 0.0 -> 0.0
            random >= 1.0 -> 0.999999
            else -> random
        }
        val factor = 0.8 + 0.4 * r
        return (base * factor).toLong().coerceAtLeast(1L)
    }
}
