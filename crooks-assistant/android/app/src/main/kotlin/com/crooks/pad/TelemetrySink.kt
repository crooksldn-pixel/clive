package com.crooks.pad

import com.crooks.pad.core.PadEvent

/**
 * CROOKS Pad — where a pad_* event goes.
 *
 * Two destinations, and neither of them is `POST /telemetry` any more. That endpoint is the WEB
 * PAGE's account of itself and it is silent unless a test session is running on the Mac; an
 * appliance whose events travelled on it would be invisible for almost all of its life. So:
 *
 * 1. A LOCAL RING BUFFER, always. Two hundred events, in memory, shown on the diagnostics
 *    screen newest-first. This is the destination that works when the Mac is off — which is
 *    precisely when somebody is looking at diagnostics — and it is why the pad's account of
 *    itself does not depend on the thing it is complaining about being reachable.
 *
 * 2. THE §16 HEARTBEAT, `POST /pad/heartbeat`. Events queue here and [drain] hands them to the
 *    next beat. That is the whole of the network path: this class opens no socket and knows no
 *    URL, which is what lets the queue keep working identically whether the Mac is there or not.
 *
 * THE QUEUE IS BOUNDED, and the bound is the interesting decision. A pad on a counter with the
 * Mac switched off for a fortnight would otherwise accumulate every event of that fortnight in
 * a list nobody will ever read, on a 2019 tablet with 2GB of RAM, and eventually take the
 * process down with an OutOfMemoryError caused entirely by its own reporting. So the queue
 * holds [QUEUE_LIMIT] and drops the OLDEST when it is full — oldest rather than newest, because
 * when the Mac finally answers, the events worth having are the recent ones that explain the
 * state the pad is in now.
 */
class TelemetrySink {

    private val ring = ArrayDeque<String>(RING_SIZE)
    private val pending = ArrayList<PadEvent>(QUEUE_LIMIT)

    /** How many events the queue has had to drop. Shown in diagnostics; never silent. */
    @get:Synchronized
    var dropped: Int = 0
        private set

    @Synchronized
    fun accept(event: PadEvent) {
        ring.addLast(render(event))
        while (ring.size > RING_SIZE) ring.removeFirst()

        pending += event
        while (pending.size > QUEUE_LIMIT) {
            pending.removeAt(0)
            dropped += 1
        }
    }

    /**
     * Take everything queued, for the beat that is about to go out.
     *
     * The queue is cleared HERE rather than after the POST returns, and that is a deliberate
     * trade with its eyes open: a beat that fails loses the events it was carrying. The
     * alternative — hold them until an answer arrives — means a pad with an unreachable Mac
     * keeps every event for ever and re-sends a growing batch on each attempt, which is the
     * unbounded-queue failure wearing a retry costume. The ring buffer still has all two
     * hundred for diagnostics either way, which is where anybody standing at the tablet looks.
     */
    @Synchronized
    fun drain(): List<PadEvent> {
        if (pending.isEmpty()) return emptyList()
        val taken = ArrayList(pending)
        pending.clear()
        return taken
    }

    @Synchronized
    fun queued(): Int = pending.size

    @Synchronized
    fun recent(limit: Int = 40): List<String> = ring.toList().takeLast(limit).asReversed()

    private fun render(event: PadEvent): String {
        val fields = event.fields.entries
            .filter { it.key != "t" }
            .joinToString(" ") { "${it.key}=${it.value}" }
        val at = event.fields["t"] as? Long ?: 0L
        return "$at ${event.kind} $fields".trimEnd()
    }

    private companion object {
        const val RING_SIZE = 200
        const val QUEUE_LIMIT = 200
    }
}
