package com.crooks.pad.core

/**
 * CROOKS Pad — §13, kiosk in three stages, of which exactly one is switched on.
 *
 * The instruction is to implement stage 1, write the detection and the pathway for stages 2
 * and 3, and not enable them. This file is that pathway, and the reason it is a pathway
 * rather than a feature is worth being blunt about: a kiosk lock that is applied and cannot
 * be removed turns a £130 tablet into a brick, on a device nobody in the building can reflash,
 * a week before anybody notices. Stage 2 and stage 3 are one-way doors on an unmanaged
 * device, and this phase has no tablet to test them on. So they are detected, described, and
 * left off.
 *
 * WHAT THE STAGES ARE
 *
 *   STAGE 1 — IMMERSIVE. Fullscreen, sticky immersive, no status bar, no navigation bar, the
 *   screen kept on while CROOKS is showing, back gestures handled by the shell. Ordinary
 *   Android underneath: the recents key still exists, the app can still be left, ADB still
 *   works, and a tablet in this state can always be recovered by anybody. This is what ships.
 *
 *   STAGE 2 — LOCK TASK. `startLockTask()`. On an UNMANAGED device this is Android's screen
 *   pinning: the app fills the screen and leaving it requires the gesture plus, if one is set,
 *   the device lock. It can be entered without a device owner, and it is genuinely reversible.
 *   It is off here for one reason: combined with the HOME alias it produces a tablet where the
 *   only way back to Settings is through an admin PIN this shell stores as a hash it cannot
 *   recover, and that combination has not been rehearsed on the real device.
 *
 *   STAGE 3 — DEVICE OWNER. Android Enterprise "dedicated device": true kiosk, boot straight
 *   into the app, no way out without a factory reset. Requires the app to be provisioned as
 *   device owner on a freshly-reset tablet with no Google account, over ADB or NFC. This is
 *   the one-way door.
 *
 * KNOX IS DETECTED, NOT ASSUMED. The brief is specific about this and it is correct to be:
 * the SM-T290 is a consumer Galaxy Tab A, and Samsung's Knox SDK is present on Samsung
 * ENTERPRISE devices and on consumer devices only partially and inconsistently by firmware.
 * Writing `if (isSamsung) useKnox()` would produce an app that crashes on exactly the device
 * it was written for. [KioskFacts.knoxPresent] is filled in by a class lookup on the Android
 * side and is reported honestly in diagnostics, including when it is false.
 */

enum class KioskStage {
    STAGE_1_IMMERSIVE,
    STAGE_2_LOCK_TASK,
    STAGE_3_DEVICE_OWNER,
}

/** What the Android layer has found out about this tablet. Facts only, no opinions. */
data class KioskFacts(
    /** DevicePolicyManager.isDeviceOwnerApp(packageName). */
    val isDeviceOwner: Boolean,
    /**
     * Whether this app may enter lock task without being device owner — which on an unmanaged
     * device means ordinary screen pinning, available since API 21 and normally true.
     */
    val lockTaskAvailable: Boolean,
    /** Whether `com.samsung.android.knox.EnterpriseDeviceManager` could be loaded at all. */
    val knoxPresent: Boolean,
    /** Whether the HOME alias is currently the tablet's default launcher. */
    val isDefaultHome: Boolean,
)

data class KioskReadiness(
    /** Every stage this tablet could technically support. */
    val available: Set<KioskStage>,
    /** The stage actually in force. Always STAGE_1 in Phase 6. */
    val enabled: KioskStage,
    /** One line for the diagnostics screen, naming why the higher stages are not on. */
    val note: String,
)

object KioskCapability {

    /**
     * Phase 6 ships stage 1 and only stage 1. The constant is here rather than inline so that
     * enabling a higher stage is a deliberate, greppable, reviewable edit in one place —
     * and so that [KioskCapabilityTest] can assert that a fully-capable tablet STILL comes
     * back as stage 1. That test is the point: a detection routine that quietly promotes
     * itself the moment it meets a capable device is how a one-way door gets opened by
     * accident.
     */
    val ENABLED_STAGE: KioskStage = KioskStage.STAGE_1_IMMERSIVE

    fun assess(facts: KioskFacts): KioskReadiness {
        val available = mutableSetOf(KioskStage.STAGE_1_IMMERSIVE)
        if (facts.lockTaskAvailable || facts.isDeviceOwner) available += KioskStage.STAGE_2_LOCK_TASK
        if (facts.isDeviceOwner) available += KioskStage.STAGE_3_DEVICE_OWNER

        val note = buildString {
            append("Stage 1 (immersive) is in force. ")
            append(
                if (KioskStage.STAGE_2_LOCK_TASK in available) {
                    "Stage 2 (screen pinning) is available and deliberately off. "
                } else {
                    "Stage 2 (screen pinning) is not available on this tablet. "
                }
            )
            append(
                if (facts.isDeviceOwner) {
                    "This app IS device owner, so stage 3 is available and deliberately off. "
                } else {
                    "This app is not device owner, so stage 3 would need a factory reset to reach. "
                }
            )
            append(if (facts.knoxPresent) "Knox was found on this tablet and is unused. " else "No Knox on this tablet. ")
            append(if (facts.isDefaultHome) "CROOKS is the home screen." else "CROOKS is not the home screen.")
        }

        return KioskReadiness(available = available, enabled = ENABLED_STAGE, note = note)
    }
}

/**
 * §14, boot. What the shell does when the tablet is switched on, and the honest limits of it
 * on a tablet nobody manages.
 *
 * THE LIMITS, STATED RATHER THAN DISCOVERED LATER:
 *
 *   - `BOOT_COMPLETED` is delivered only after the user has unlocked the device at least once
 *     if a secure lock screen is set. A tablet with a PIN on the lock screen does NOT start
 *     CROOKS by itself after a power cut; it starts CROOKS the moment somebody unlocks it.
 *     The only way round that is to have no secure lock screen, which is the right setting
 *     for a fixture on a counter and is a device setting, not something an app can do.
 *   - Samsung's One UI is aggressive about background start-ups. An activity started from a
 *     broadcast receiver at boot is not guaranteed to come to the front; on some firmware it
 *     is silently dropped. This is why the HOME alias exists: being the launcher is the only
 *     mechanism on an unmanaged tablet that reliably puts an app on screen after a boot,
 *     because the system starts the home activity itself rather than being asked to.
 *   - The alias ships disabled and is switched on from admin. So out of the box, boot
 *     behaviour is best-effort, and it is described as best-effort on the diagnostics screen
 *     rather than promised.
 */
enum class BootAction { START, SKIP }

data class BootDecision(val action: BootAction, val reason: String)

object BootPolicy {

    fun decide(
        intentAction: String?,
        autoStartEnabled: Boolean,
        userUnlocked: Boolean,
        isDefaultHome: Boolean,
    ): BootDecision {
        if (!autoStartEnabled) return BootDecision(BootAction.SKIP, "autostart_off")
        return when (intentAction) {
            "android.intent.action.BOOT_COMPLETED" ->
                if (userUnlocked) BootDecision(BootAction.START, "boot_completed")
                else BootDecision(BootAction.SKIP, "locked_user")

            "android.intent.action.LOCKED_BOOT_COMPLETED" ->
                // Before the user has unlocked, app-private storage is not readable and the
                // WebView cannot be created. Starting here would produce a black screen and a
                // crash. The shell waits for the unlocked broadcast — and if the HOME alias
                // is on, the system will start it anyway at that moment, which is why this
                // says so rather than pretending it is a failure.
                BootDecision(
                    BootAction.SKIP,
                    if (isDefaultHome) "locked_boot_home_will_start" else "locked_boot_too_early",
                )

            "android.intent.action.MY_PACKAGE_REPLACED" ->
                // The shell has just been updated in place. Coming straight back is what makes
                // an update invisible to the owner rather than a tablet found on the launcher.
                BootDecision(BootAction.START, "package_replaced")

            else -> BootDecision(BootAction.SKIP, "unexpected_action")
        }
    }
}
