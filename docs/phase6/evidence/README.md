# Raw evidence

Kept because §33 asks for it: *"preserve raw evidence"*. These are the unedited outputs, not
summaries of them. Where a number appears in a Phase 6 document, it came from a file here.

| file | what it is |
|---|---|
| `baseline_premerge.txt` | the full Phase 5 suite on the integration branch at 5d4ee5c — BEFORE any workstream was merged. The control measurement, so that any drift afterwards is attributable to the merge rather than argued about. `2814 passed, 2 skipped in 1017.91s`, exit 0. |

## On the traceback at the end of `baseline_premerge.txt`

`Exception ignored in: BaseSubprocessTransport.__del__ … RuntimeError: Event loop is closed`,
repeated. It is a garbage-collection-time teardown of the Chromium subprocess transport after
asyncio's loop has already closed, and it is printed **after** the summary line — so every test
had already reported before it appeared, and the process exited 0.

It is recorded rather than deleted because a traceback in an evidence file that nobody explains
is a traceback somebody will worry about later. It is cosmetic and it is not introduced by
Phase 6: the tree measured here is Phase 5's code plus documentation.

## `apk_release_inspection.txt`

The §28 and §34 claims checked **against the shipped binary** rather than against the source
comments that make them. `aapt2 dump` on `app-release-unsigned.apk` (1,706,449 bytes), built by
Gradle from `crooks-assistant/android`.

What it establishes, each of which is a claim made elsewhere in these documents:

| checked | value | the claim it supports |
|---|---|---|
| `targetSdkVersion` | **30** | the SM-T290 runs Android 11 / API 30 — the package targets the device it is for, not a newer one |
| `allowBackup` | **false** | the admin PIN hash cannot reach a cloud backup and be attacked by somebody who never touched the tablet |
| `usesCleartextTraffic` | **false** | enforced by the platform, not only by the shell's own URL checks |
| `android:debuggable` | **absent** | the release package is not debuggable |
| `PadHomeAlias` `enabled` | **false** | §34 — the kiosk HOME role genuinely ships OFF. Being the launcher is what makes a tablet hard to get out of, and nothing in the shipped package turns it on |
| declared permissions | **six** | RECORD_AUDIO, INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, RECEIVE_BOOT_COMPLETED, WAKE_LOCK. **No location permission of any kind** — the deliberate omission holds in the artefact, so the Wi-Fi SSID cannot be read and cannot reach telemetry |

`com.crooks.pad.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION` is injected by the Android Gradle
Plugin for API 33+ receiver registration. It is not declared by this project.

**What this does NOT establish.** That `WEBVIEW_DEBUG` is false in the release build is verified
in the build configuration and in `PadWebView.kt`, not here: the compiler inlines the boolean,
so there is no manifest attribute or string to read back out of the package. And nothing here
says the app runs — see `CROOKS_PAD_ACCEPTANCE.md`. An APK that assembles and declares the right
things is not an APK anybody has watched start.
