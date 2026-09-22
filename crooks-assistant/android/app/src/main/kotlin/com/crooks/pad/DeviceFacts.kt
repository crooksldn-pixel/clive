package com.crooks.pad

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.os.BatteryManager
import android.os.Build
import androidx.core.content.ContextCompat
import com.crooks.pad.core.KioskFacts
import com.crooks.pad.core.Transport

/**
 * CROOKS Pad — reading the hardware, and the four things it deliberately does not read.
 *
 * Everything here is a fact about the tablet as a piece of equipment. Nothing here identifies
 * a person, a place or a network:
 *
 *   - NO Wi-Fi SSID or BSSID. Reading either needs a location permission on Android 8.1 and
 *     later, and the SSID is a place-identifying string that would then be in telemetry. What
 *     the pad reports instead is transport and signal strength in bars, which answers every
 *     question it actually has — "is this on Wi-Fi", "is the Wi-Fi weak" — and names nothing.
 *   - NO IP or MAC address. The tailnet address identifies the node; the hardware address
 *     identifies the tablet for ever, across reinstalls.
 *   - NO serial, IMEI, Android ID or advertising ID. The pad has no use for a stable device
 *     identifier and having one is how telemetry becomes tracking.
 *   - NO location, at all. The manifest asks for no location permission, so this is enforced
 *     by the platform and not only by this comment.
 */
class DeviceFacts(private val context: Context) {

    @Volatile var batteryPercent: Int = -1
        private set

    @Volatile var charging: Boolean = false
        private set

    @Volatile var powerSource: String = "unknown"
        private set

    @Volatile var networkOnline: Boolean = false
        private set

    @Volatile var transport: Transport = Transport.NONE
        private set

    private val connectivity: ConnectivityManager? =
        context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager

    /** The shell is told about changes rather than polling for them. §18: transitions only. */
    interface Listener {
        fun onNetworkChanged(online: Boolean, transport: Transport)
    }

    private var listener: Listener? = null

    private val batteryReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent == null) return
            val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
            val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
            batteryPercent = if (level >= 0 && scale > 0) (level * 100) / scale else -1
            val status = intent.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
            charging = status == BatteryManager.BATTERY_STATUS_CHARGING || status == BatteryManager.BATTERY_STATUS_FULL
            powerSource = when (intent.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0)) {
                BatteryManager.BATTERY_PLUGGED_AC -> "ac"
                BatteryManager.BATTERY_PLUGGED_USB -> "usb"
                BatteryManager.BATTERY_PLUGGED_WIRELESS -> "wireless"
                else -> "none"
            }
            // Deliberately NOT reported to the listener. A battery broadcast arrives every
            // time the level moves by a percent; §18 is explicit that battery ticks must not
            // be spammed into telemetry, so the value is kept here and read when something
            // else has a reason to look.
        }
    }

    private val networkCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) = recompute()
        override fun onLost(network: Network) = recompute()
        override fun onCapabilitiesChanged(network: Network, capabilities: NetworkCapabilities) = recompute()
    }

    fun start(listener: Listener) {
        this.listener = listener
        // RECEIVER_NOT_EXPORTED through ContextCompat rather than a bare registerReceiver.
        // On this tablet — API 30, targetSdk 30 — the bare call is legal and the flag is
        // ignored. On API 34 and above a dynamically registered receiver with no export flag
        // throws, so the bare call is a crash lying in wait for whoever raises targetSdk,
        // which android/docs/DECISIONS.md names as a thing that will eventually happen.
        // ACTION_BATTERY_CHANGED is a protected system broadcast, so NOT_EXPORTED is right.
        ContextCompat.registerReceiver(
            context,
            batteryReceiver,
            IntentFilter(Intent.ACTION_BATTERY_CHANGED),
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )
        runCatching { connectivity?.registerDefaultNetworkCallback(networkCallback) }
        recompute()
    }

    fun stop() {
        runCatching { context.unregisterReceiver(batteryReceiver) }
        runCatching { connectivity?.unregisterNetworkCallback(networkCallback) }
        listener = null
    }

    private fun recompute() {
        val capabilities = connectivity?.let { manager ->
            manager.activeNetwork?.let { manager.getNetworkCapabilities(it) }
        }
        val online = capabilities != null &&
            capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
        val kind = when {
            capabilities == null -> Transport.NONE
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> Transport.WIFI
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> Transport.ETHERNET
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> Transport.CELLULAR
            else -> Transport.OTHER
        }
        val changed = online != networkOnline || kind != transport
        networkOnline = online
        transport = kind
        if (changed) listener?.onNetworkChanged(online, kind)
    }

    /**
     * Signal strength in bars, 0..4, or null when this is not Wi-Fi. `calculateSignalLevel`
     * takes the RSSI, which is a number about radio, not about a network — no permission, no
     * identifier, nothing that says which Wi-Fi it is.
     */
    fun wifiSignalBars(): Int? {
        if (transport != Transport.WIFI) return null
        val wifi = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager ?: return null
        return runCatching {
            @Suppress("DEPRECATION")
            val rssi = wifi.connectionInfo.rssi
            @Suppress("DEPRECATION")
            WifiManager.calculateSignalLevel(rssi, 5)
        }.getOrNull()
    }

    /**
     * §13. What kiosk stages this tablet could support. Detected, never assumed — and Knox in
     * particular, because the SM-T290 is a consumer Galaxy Tab A and `if (isSamsung) useKnox()`
     * produces an app that crashes on exactly the device it was written for.
     */
    fun kioskFacts(): KioskFacts {
        val devicePolicy = runCatching {
            val manager = context.getSystemService(Context.DEVICE_POLICY_SERVICE)
                as? android.app.admin.DevicePolicyManager
            manager?.isDeviceOwnerApp(context.packageName) ?: false
        }.getOrDefault(false)

        val knox = runCatching {
            Class.forName("com.samsung.android.knox.EnterpriseDeviceManager")
            true
        }.getOrDefault(false)

        val isHome = runCatching {
            val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
            val resolved = context.packageManager.resolveActivity(intent, PackageManager.MATCH_DEFAULT_ONLY)
            resolved?.activityInfo?.packageName == context.packageName
        }.getOrDefault(false)

        return KioskFacts(
            isDeviceOwner = devicePolicy,
            // Screen pinning without a device owner has existed since API 21 and minSdk is 26,
            // so it is available; it is left as a fact rather than a constant because a
            // managed device can have it switched off by policy, and assess() must be able to
            // say so honestly on the diagnostics screen.
            lockTaskAvailable = true,
            knoxPresent = knox,
            isDefaultHome = isHome,
        )
    }

    val deviceModel: String get() = Build.MODEL ?: "unknown"
    val androidRelease: String get() = Build.VERSION.RELEASE ?: "unknown"
    val apiLevel: Int get() = Build.VERSION.SDK_INT
}
