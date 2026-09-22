package com.crooks.pad

import android.webkit.JavascriptInterface
import com.crooks.pad.core.DeviceSnapshot

/**
 * CROOKS Pad — §6.5, the device bridge. One method. Read-only. No arguments.
 *
 * ============================================================================================
 * THE @JavascriptInterface SURFACE OF THIS APPLICATION, IN FULL:
 *
 *     String snapshot()
 *
 * That is the entire list. Each method on a bridge has to be justified individually, and
 * there is one to justify.
 * ============================================================================================
 *
 * WHY `snapshot()` EXISTS. The web layer can already observe most of what it returns — the
 * Battery Status API, `navigator.onLine`, `document.visibilityState`, the user agent — but it
 * observes them unevenly and, on a 2019 Samsung WebView, sometimes not at all. The pad is an
 * appliance: "is this thing on its charger", "is the Wi-Fi weak", "what version of the shell
 * is this" are questions that decide what the product should say to the owner, and guessing
 * at them from a page is how a fixture ends up lying about itself.
 *
 * WHY IT IS ONE METHOD AND NOT TWELVE. Twelve getters is twelve entries in the surface, twelve
 * things to review, and a standing invitation to add a thirteenth that is not a getter. One
 * method returning one immutable JSON object is a surface that cannot grow sideways: adding a
 * field is a change to a data class in `:core` with a test attached, not a new door.
 *
 * WHY THERE IS NO SECOND METHOD, EVER:
 *
 *   - NO `runNativeCommand(String)`, no `invoke(name, args)`, no `call(name)`, no
 *     `setProperty(k, v)`, and nothing else that takes a name and dispatches on it. A
 *     dispatcher makes the hole the size of whatever it can reach — including whatever
 *     somebody adds to it next year — and its size stops being reviewable.
 *   - NOTHING THAT MUTATES. No reload, no navigate, no exit, no grant, no setting. CROOKS'
 *     central invariant is that the model never performs privileged operations and the client
 *     never supplies mutation arguments; a bridge method that changes the shell is
 *     structurally a privileged operation reachable from a document. The shell watches the
 *     page. The page does not drive the shell.
 *   - NOTHING SECRET CROSSES IT. No token, no cookie, no credential, no serial number, no
 *     IMEI, no Android ID, no advertising ID, no account, no Wi-Fi SSID or BSSID, no IP
 *     address, no MAC address, no location. [DeviceSnapshot] is the exhaustive list of what
 *     does, and DeviceSnapshotTest asserts that none of those words appears in the encoded
 *     form.
 *
 * ON THE @JavascriptInterface ANNOTATION ITSELF. Since API 17 only annotated methods are
 * exposed, which closes the old reflection hole that let any page reach `getClass()` and from
 * there anything on the device. minSdk here is 26, so that is a given rather than a hope — but
 * it is worth writing down, because the reason this class is safe to have at all is that
 * annotation and the smallness of what carries it.
 *
 * THREADING. The method is called on the WebView's JavaScript thread, not the main thread, so
 * it must not touch views and must not block. It reads a snapshot the activity keeps up to
 * date from broadcasts and callbacks, marked @Volatile, and returns immediately.
 */
class DeviceBridge(private val provider: () -> DeviceSnapshot) {

    companion object {
        /**
         * The name the object takes in the page: `window.CrooksPad`. Namespaced so that it
         * cannot collide with anything the web layer defines, and obviously ours so that a
         * page seeing it knows what it is talking to.
         */
        const val JS_NAME = "CrooksPad"
    }

    /**
     * The one exposed method. Returns a JSON object as a string — a string rather than a
     * structured object because the bridge's marshalling supports only primitives and strings,
     * and because a string is one thing to escape correctly rather than a shape to keep in
     * step across two languages.
     *
     * Never throws. An exception crossing the bridge surfaces in the page as an opaque
     * failure at whatever moment the hardware happened to be unreadable, which is the worst
     * possible time for the pad to become mysterious. An empty object is a page that carries
     * on without the extra information.
     */
    @JavascriptInterface
    fun snapshot(): String = try {
        provider().toJson()
    } catch (t: Throwable) {
        "{}"
    }
}
