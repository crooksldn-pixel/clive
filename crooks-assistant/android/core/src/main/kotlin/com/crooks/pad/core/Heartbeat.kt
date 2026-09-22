package com.crooks.pad.core

/**
 * CROOKS Pad — §16, THE HEARTBEAT. The appliance saying "I am here", to the one endpoint whose
 * job is to listen.
 *
 * WHY THIS IS NOT `/telemetry`. `/telemetry` is the WEB PAGE's account of itself and it is
 * silent unless a test session is running on the Mac — by design, in `app/routes/observe.py`,
 * which is inside Phase 6's non-regression boundary. An appliance whose liveness travelled on
 * that endpoint would be invisible for the ninety-nine percent of its life when no session is
 * running, and the Control app on George's Mac would have nothing to draw. So the pad posts to
 * `POST /pad/heartbeat`, which exists for exactly this, and pad_* events ride along with it.
 *
 * THE CADENCE IS NOT A KOTLIN CONSTANT, AND THAT IS THE WHOLE POINT OF THE CLASS.
 * [DEFAULT_INTERVAL_S] is used for the FIRST beat and for nothing else. Every answer carries
 * `interval_s`, and from the first answer onwards the backend's number is the cadence. The Mac
 * can quieten a fleet of pads, or ask for a fast beat while somebody is watching the Control
 * app, without anybody rebuilding an APK and walking it onto a tablet with a cable — which,
 * on an appliance that is sideloaded onto one tablet in a shop, is the difference between a
 * knob that exists and a knob that does not.
 *
 * THE ANSWER ALSO CARRIES THE RUNNING TEST SESSION, which is how the page's own telemetry is
 * turned on and off within one beat: the pad reads `test_session` here and hands it to the
 * document through the device bridge, instead of every pad polling `/health` on its own timer
 * for a field that the beat was already going to fetch.
 *
 * Everything in this file is pure — strings in, a string out, a clock passed as a number — so
 * the build machine can run all of it. The Android side owns one socket and no judgement.
 */
class Heartbeat(
    private val appVersion: String,
    private val deviceModel: String,
    private val osVersion: String,
    /**
     * Fresh per process. It is what lets the Mac tell "this pad has been up for a week" from
     * "this pad has restarted six times this morning", which are completely different
     * sentences about the same tablet. Not a device identifier: it changes on every launch,
     * which is precisely why it is safe to send.
     */
    private val bootId: String,
) {

    companion object {
        /** The one endpoint. */
        const val PATH = "/pad/heartbeat"

        /** Response field names. Named here so the Android side cannot spell them its own way. */
        const val KEY_INTERVAL_S = "interval_s"
        const val KEY_TEST_SESSION = "test_session"

        /**
         * The FIRST beat's cadence and nothing else. Twenty seconds: fast enough that a pad
         * switched on in the morning appears in the Control app while the owner is still
         * looking at it, slow enough to be nothing on a tailnet. Overwritten by the backend's
         * `interval_s` the moment the first answer arrives.
         */
        const val DEFAULT_INTERVAL_S = 20

        /**
         * Rails, not policy. The backend's number wins inside these; outside them something is
         * wrong at the far end and the pad refuses to be turned either into a packet storm or
         * into a tablet that checks in once a day. Both bounds are far outside any cadence
         * anybody would choose on purpose.
         */
        const val MIN_INTERVAL_S = 5
        const val MAX_INTERVAL_S = 3_600
    }

    /** The cadence in force. Read on every beat; never assumed. */
    var intervalS: Int = DEFAULT_INTERVAL_S
        private set

    /** False until the backend has answered once. Shown in diagnostics so "20s" is not a lie. */
    var cadenceCameFromBackend: Boolean = false
        private set

    /** The Mac's running observability session, or null. Straight from the last answer. */
    var testSessionId: String? = null
        private set

    var beatsSent: Long = 0
        private set

    var answersSeen: Long = 0
        private set

    fun intervalMs(): Long = intervalS * 1_000L

    /** When the next beat is due, given when the last one went. */
    fun nextBeatDueAt(lastBeatAt: Long): Long = lastBeatAt + intervalMs()

    /** The single timer asks this and nothing else. */
    fun isDue(now: Long, lastBeatAt: Long): Boolean = now >= nextBeatDueAt(lastBeatAt)

    /**
     * The body of one beat: the five facts CONTRACT 1 names, plus the queued events when there
     * are any. `events` is omitted entirely when empty rather than sent as `[]`, because an
     * absent key and an empty list mean the same thing and one of them is smaller.
     *
     * `at` IS EPOCH MILLISECONDS, and it is stated here because it is the one field whose unit
     * cannot be inferred from the value. It matches `t` on every event and `Date.now()` in
     * web/telemetry.js, which is the house convention; the Mac's `clock_skew_s` is in seconds
     * and must divide. Getting this wrong in either direction produces a skew of about fifty
     * years, which is at least loud.
     *
     * Hand-rolled JSON for the same reason [DeviceSnapshot] hand-rolls its own: a serialisation
     * library to encode five scalars and a list would be a dependency earning nothing, and the
     * escaping is then something a test holds to account rather than something assumed. Every
     * string goes through [DeviceSnapshot.escape]; `device_model` in particular is
     * manufacturer-supplied and has historically contained quotes.
     */
    fun body(at: Long, events: List<PadEvent> = emptyList()): String = buildString {
        append('{')
        append("\"app_version\":\"").append(DeviceSnapshot.escape(appVersion)).append("\",")
        append("\"device_model\":\"").append(DeviceSnapshot.escape(deviceModel)).append("\",")
        append("\"os_version\":\"").append(DeviceSnapshot.escape(osVersion)).append("\",")
        append("\"at\":").append(at).append(',')
        append("\"boot_id\":\"").append(DeviceSnapshot.escape(bootId)).append('"')
        if (events.isNotEmpty()) {
            append(",\"events\":[")
            for ((index, event) in events.withIndex()) {
                if (index > 0) append(',')
                append("{\"kind\":\"").append(DeviceSnapshot.escape(event.kind)).append('"')
                for ((key, value) in event.fields) {
                    if (value == null) continue
                    append(",\"").append(DeviceSnapshot.escape(key)).append("\":").append(encode(value))
                }
                append('}')
            }
            append(']')
        }
        append('}')
    }

    /** Called after a beat has actually gone out, so the counter counts beats and not attempts. */
    fun beatSent() {
        beatsSent += 1
    }

    /**
     * Read the answer. [intervalS] is whatever the response's `interval_s` was, or null when
     * the field was absent or unreadable; [testSession] likewise for `test_session`.
     *
     * A missing or nonsensical `interval_s` leaves the cadence exactly as it was rather than
     * resetting it to the built-in default: the last number the backend gave is a better guess
     * about what the backend wants than a constant compiled into the tablet in March.
     */
    fun onAnswer(intervalS: Int?, testSession: String?) {
        answersSeen += 1
        testSessionId = testSession?.takeIf { it.isNotEmpty() && it != "null" }
        if (intervalS == null || intervalS <= 0) return
        this.intervalS = intervalS.coerceIn(MIN_INTERVAL_S, MAX_INTERVAL_S)
        cadenceCameFromBackend = true
    }

    /**
     * A beat that did not get an answer. The cadence is deliberately left alone — a Mac that is
     * off is not a Mac asking for a different cadence — and the test session is cleared,
     * because a session the pad can no longer confirm is a session it must stop claiming.
     */
    fun onBeatFailed() {
        testSessionId = null
    }

    private fun encode(value: Any): String = when (value) {
        is Boolean, is Int, is Long, is Short, is Byte -> value.toString()
        is Double -> if (value.isFinite()) value.toString() else "null"
        is Float -> if (value.isFinite()) value.toString() else "null"
        else -> "\"" + DeviceSnapshot.escape(value.toString()) + "\""
    }
}
