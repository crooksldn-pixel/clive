# What this machine can and cannot verify

Written first, before any code, because §26's lesson is that a green result means nothing
until you know what it measured — and half of Phase 6 is native code for two platforms this
build machine is not.

**This machine:** Ubuntu 24.04, x86_64, Linux. Not macOS. No physical Samsung attached.

| | available | what that means |
|---|---|---|
| Swift | **6.0.3 for Linux**, installed at `/opt/swift` | Foundation-only Swift **compiles and its tests run here**. SwiftUI and AppKit are macOS frameworks and are **not** present — anything importing them cannot be compiled on this machine at all. |
| Xcode / `xcodebuild` | **no** | No `.app` bundle can be produced or signed here. |
| Android SDK | **installed** at `/opt/android-sdk` — platforms **android-30** (Android 11, the SM-T290 target) and android-34, build-tools 34.0.0, `adb` 1.0.41 | A **real APK can be built** here, for the real target API. |
| Gradle / JDK | Gradle at `/opt/gradle`, OpenJDK 21 | Android unit tests (JVM) run here. |
| Android emulator | **no `/dev/kvm`** | No emulator. **No screenshot of a running Android app is possible on this machine.** |
| Physical SM-T290 | not attached | No `adb install`, no touch test, no microphone test. |

## The consequences, stated before the work rather than after

1. **The Mac app cannot be compiled whole here.** So it is deliberately split: a
   Foundation-only core that holds every decision the app makes — state, contract decoding,
   action dispatch, error wording, update verdicts — which **does** compile and **is** unit
   tested on this machine; and a SwiftUI layer that draws it, which is not compiled here and
   is honestly unverified until the owner builds it on the Mac. The split is not a workaround:
   pushing the decisions out of the views is the right architecture anyway, and it is what
   makes them testable at all.

2. **The Android APK can be genuinely built.** `assembleDebug` producing an APK for API 30 is
   a real result and is reported as one.

3. **No native screen of either app can be photographed here.** §27's visual review is
   therefore split: the web UI inside the shell is photographed at 601×889 exactly as Phase 5
   did, and the native screens are reviewed from their layout source with the limitation
   stated. Nothing will be claimed to "look right" that was never rendered.

4. **No physical behaviour is claimed.** Touch, microphone, sleep/wake, Wi-Fi loss and kiosk
   behaviour are written, unit-tested where logic permits, and left for the physical scripts.
