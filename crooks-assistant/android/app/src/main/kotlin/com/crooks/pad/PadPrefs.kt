package com.crooks.pad

import android.content.Context
import android.content.SharedPreferences

/**
 * CROOKS Pad — the four things this tablet remembers.
 *
 * App-private shared preferences, with backup and device transfer switched off in the
 * manifest. There are deliberately only four keys, and none of them is a credential:
 *
 *   pin_hash            a PBKDF2 hash of the admin PIN. Not the PIN. See PinHasher for an
 *                       honest statement of what that does and does not defend against.
 *   last_connected_at   when this tablet last saw the workspace, so the recovery card can say
 *                       "last connected at 14:02" instead of leaving the owner wondering
 *                       whether it has ever worked at all.
 *   autostart           whether to come back after a boot. §14.
 *   home_role           whether the HOME alias has been enabled from admin. Kept alongside
 *                       the component state so the admin screen can show the right label
 *                       without a package-manager query on every draw.
 *
 * Nothing about the conversation, the shop, the owner or the network is stored here. The pad
 * is a window, and a window does not keep notes.
 */
class PadPrefs(context: Context) {

    private val prefs: SharedPreferences =
        context.applicationContext.getSharedPreferences("crooks_pad", Context.MODE_PRIVATE)

    var pinHash: String?
        get() = prefs.getString(KEY_PIN_HASH, null)
        set(value) = prefs.edit().putString(KEY_PIN_HASH, value).apply()

    val hasPin: Boolean get() = !pinHash.isNullOrEmpty()

    var lastConnectedAt: Long?
        get() = prefs.getLong(KEY_LAST_CONNECTED, 0L).takeIf { it > 0L }
        set(value) = prefs.edit().putLong(KEY_LAST_CONNECTED, value ?: 0L).apply()

    /**
     * On by default. A fixture that has to be started by hand after every power cut is not a
     * fixture, and the owner who would want it off can turn it off in admin.
     */
    var autoStart: Boolean
        get() = prefs.getBoolean(KEY_AUTOSTART, true)
        set(value) = prefs.edit().putBoolean(KEY_AUTOSTART, value).apply()

    var homeRoleEnabled: Boolean
        get() = prefs.getBoolean(KEY_HOME_ROLE, false)
        set(value) = prefs.edit().putBoolean(KEY_HOME_ROLE, value).apply()

    private companion object {
        const val KEY_PIN_HASH = "pin_hash"
        const val KEY_LAST_CONNECTED = "last_connected_at"
        const val KEY_AUTOSTART = "autostart"
        const val KEY_HOME_ROLE = "home_role"
    }
}
