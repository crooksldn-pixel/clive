# CROOKS Pad — release shrinking rules.
#
# Minification is currently OFF in the release build type (see app/build.gradle.kts). That is
# deliberate for an appliance that is sideloaded onto one tablet: the APK is under two
# megabytes either way, and an obfuscated stack trace from a workroom with no debugger attached
# is worth considerably less than the kilobytes saved.
#
# These rules exist so that switching it on is a one-line change rather than an afternoon of
# discovering what R8 removed.

# THE ONE THAT MATTERS. A @JavascriptInterface method is called only from JavaScript, so R8 can
# see no caller and will remove it — and the failure is silent: the page calls CrooksPad.snapshot()
# and gets undefined, with nothing in any log. This is the classic WebView release-build bug.
-keepclassmembers class com.crooks.pad.DeviceBridge {
    public *;
}
-keepattributes JavascriptInterface

# The state and policy types in :core are plain data and reflection-free, so nothing else needs
# keeping. If that changes, it should be listed here with the reason, not covered by a wildcard.
