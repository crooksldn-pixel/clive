package com.crooks.pad

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.UserManager
import com.crooks.pad.core.BootAction
import com.crooks.pad.core.BootPolicy

/**
 * CROOKS Pad — §14, coming back after the tablet is switched on.
 *
 * The decision is [BootPolicy] in `:core`, where it is tested. What is here is the broadcast
 * plumbing and the one thing the policy cannot know: whether the user has unlocked the device.
 *
 * WHAT THIS CAN AND CANNOT PROMISE, stated here rather than discovered in a workroom:
 *
 *   - `BOOT_COMPLETED` is delivered only after the user has unlocked the device at least once,
 *     if a secure lock screen is set. A tablet with a PIN on its lock screen does NOT start
 *     CROOKS by itself after a power cut; it starts CROOKS when somebody unlocks it. The fix
 *     is a device setting — no secure lock screen on a fixture — not something an app can do.
 *   - Samsung's One UI is aggressive about background start-ups, and an activity started from
 *     a receiver at boot is not guaranteed to come to the front on every firmware. This is
 *     best-effort and the diagnostics screen says so.
 *   - The reliable mechanism on an unmanaged tablet is the HOME role, because the system
 *     starts the home activity itself rather than being asked to. That alias ships disabled
 *     and is switched on from admin.
 *
 * The receiver is exported, because BOOT_COMPLETED requires it. So it does nothing at all for
 * any action it was not registered for, and [BootPolicy] is where that is asserted.
 */
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val userUnlocked = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            (context.getSystemService(Context.USER_SERVICE) as? UserManager)?.isUserUnlocked ?: true
        } else {
            true
        }

        val prefs = runCatching { PadPrefs(context) }.getOrNull()
        val decision = BootPolicy.decide(
            intentAction = intent.action,
            // Reading preferences before the user has unlocked throws, because credential-
            // encrypted storage is not available yet. That is exactly the case the policy
            // answers SKIP for, so defaulting to the policy's own default here is safe.
            autoStartEnabled = prefs?.autoStart ?: true,
            userUnlocked = userUnlocked,
            isDefaultHome = isDefaultHome(context),
        )

        if (decision.action != BootAction.START) return

        runCatching {
            val launch = Intent(context, PadActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)
            context.startActivity(launch)
        }
    }

    private fun isDefaultHome(context: Context): Boolean = runCatching {
        val home = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
        context.packageManager
            .resolveActivity(home, PackageManager.MATCH_DEFAULT_ONLY)
            ?.activityInfo?.packageName == context.packageName
    }.getOrDefault(false)
}
