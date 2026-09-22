package com.crooks.pad.core

/**
 * CROOKS Pad — §6.5, the device bridge, and the one line in it that matters most:
 *
 *     THERE IS NO runNativeCommand(String). THERE IS NOTHING EQUIVALENT TO ONE.
 *
 * A JavaScript bridge is a hole in the side of the application, and the size of the hole is
 * decided entirely by the shape of the methods on it. `runNativeCommand(String)` — or
 * `invoke(name, argsJson)`, or `getProperty(String)`, or anything else that takes a name and
 * dispatches on it — makes the hole the size of whatever the dispatcher can reach, forever,
 * including the things somebody adds to it next year. This bridge instead exposes ONE method
 * that returns ONE immutable snapshot of facts the page could mostly observe anyway, and the
 * @JavascriptInterface surface is one method wide.
 *
 * It is also READ-ONLY IN THE STRONGEST SENSE: there is no method here that changes anything.
 * The page cannot ask the shell to reload, to navigate, to exit, to grant a permission, to
 * open admin, or to alter a setting. Not because such a method would necessarily be misused,
 * but because CROOKS' central invariant is that the model never performs privileged
 * operations and the client never supplies mutation arguments — and a bridge method that
 * changes the shell is, structurally, a privileged operation reachable from a document. The
 * shell watches the page; the page does not drive the shell.
 *
 * NO SECRETS CROSS IT (§6.4). Read the fields below and note what is absent: no token, no
 * cookie, no credential, no serial number, no IMEI, no Android ID, no advertising ID, no
 * account, no Wi-Fi SSID or BSSID, no IP address, no MAC address, no location. Model and OS
 * version are here because they are the two things a bug report is useless without, and they
 * identify a product line, not a tablet.
 *
 * ON WI-FI, SPECIFICALLY, because "wifi where accessible" in the brief invites the wrong
 * answer. Reading the SSID on Android 8.1 and later requires a location permission, and the
 * SSID is a place-identifying string that would then be in telemetry. The pad never asks for
 * location and never reads the SSID. What it reports is transport and signal strength in
 * bars, which answers every question the pad actually has — "is this on Wi-Fi", "is the Wi-Fi
 * weak" — and identifies nothing.
 */
data class DeviceSnapshot(
    /** 0..100. From the battery broadcast, not polled. */
    val batteryPercent: Int,
    val charging: Boolean,
    /** "ac", "usb", "wireless", "none". Useful for "is this pad on its stand". */
    val powerSource: String,
    val networkOnline: Boolean,
    val transport: Transport,
    /** 0..4, or null when the transport is not Wi-Fi. Never an SSID. See the note above. */
    val wifiSignalBars: Int?,
    /** e.g. "SM-T290". A product line, not a tablet. */
    val deviceModel: String,
    /** e.g. "11". */
    val androidRelease: String,
    val apiLevel: Int,
    val appVersionName: String,
    val appVersionCode: Int,
    /** "portrait" or "landscape". */
    val orientation: String,
    /** Whether the shell is the foreground activity right now. */
    val foreground: Boolean,
    val screenOn: Boolean,
    /** Milliseconds since the app was last resumed, or null if it has never been backgrounded. */
    val msSinceResume: Long?,
    /** Which shell state the pad is in, so the page can tell a reload from a fresh start. */
    val padState: String,
    /**
     * The Mac's running observability session, straight off the last §16 heartbeat answer, or
     * null when nothing is collecting.
     *
     * IT IS HERE SO THAT THE PAGE DOES NOT HAVE TO ASK. `POST /telemetry` keeps nothing unless
     * a session is running, so web/telemetry.js has to know whether one is — and every pad
     * polling `/health` on its own timer for a field the heartbeat was already fetching is a
     * second clock, a second failure mode and real work on the Mac for an answer it just gave.
     * Reading it here turns the page's telemetry on and off within one beat.
     *
     * It is not a secret and not an identifier: it is the name of a test session that the page
     * already receives from `/health` today, and it changes whenever somebody starts one.
     */
    val testSession: String? = null,
) {

    /**
     * Hand-rolled JSON, because adding a serialisation library to an appliance shell to
     * encode fourteen scalars would be a dependency earning nothing — and because the
     * escaping below is then something a test can hold to account rather than something
     * assumed. The string fields all originate from Build.MODEL and friends, which are
     * manufacturer-supplied and have historically contained quotes and worse.
     */
    fun toJson(): String = buildString {
        append('{')
        num("battery_percent", batteryPercent)
        bool("charging", charging)
        str("power_source", powerSource)
        bool("network_online", networkOnline)
        str("transport", transport.name.lowercase())
        if (wifiSignalBars != null) num("wifi_signal_bars", wifiSignalBars) else nul("wifi_signal_bars")
        str("device_model", deviceModel)
        str("android_release", androidRelease)
        num("api_level", apiLevel)
        str("app_version", appVersionName)
        num("app_version_code", appVersionCode)
        str("orientation", orientation)
        bool("foreground", foreground)
        bool("screen_on", screenOn)
        if (msSinceResume != null) num("ms_since_resume", msSinceResume) else nul("ms_since_resume")
        str("pad_state", padState)
        if (testSession != null) str("test_session", testSession, last = true) else nul("test_session", last = true)
        append('}')
    }

    private fun StringBuilder.str(key: String, value: String, last: Boolean = false) {
        append('"').append(key).append("\":\"").append(escape(value)).append('"')
        if (!last) append(',')
    }

    private fun StringBuilder.num(key: String, value: Number) {
        append('"').append(key).append("\":").append(value).append(',')
    }

    private fun StringBuilder.bool(key: String, value: Boolean) {
        append('"').append(key).append("\":").append(value).append(',')
    }

    private fun StringBuilder.nul(key: String, last: Boolean = false) {
        append('"').append(key).append("\":null")
        if (!last) append(',')
    }

    companion object {
        /**
         * The escaping. Quote, backslash and every control character, plus U+2028 and U+2029
         * — which are legal in JSON strings and illegal in JavaScript string literals, and so
         * break any consumer that evaluates rather than parses. Belt and braces, since the
         * value crosses into a JavaScript engine.
         */
        fun escape(raw: String): String {
            val out = StringBuilder(raw.length + 8)
            for (c in raw) {
                when {
                    c == '"' -> out.append("\\\"")
                    c == '\\' -> out.append("\\\\")
                    c == '\n' -> out.append("\\n")
                    c == '\r' -> out.append("\\r")
                    c == '\t' -> out.append("\\t")
                    c.code < 0x20 || c.code == 0x7F || c.code == 0x2028 || c.code == 0x2029 ->
                        out.append("\\u").append(c.code.toString(16).padStart(4, '0'))
                    else -> out.append(c)
                }
            }
            return out.toString()
        }
    }
}
