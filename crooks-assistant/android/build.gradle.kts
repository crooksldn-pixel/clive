// Versions live here and are applied in the modules.
//
// Android Gradle Plugin 8.6.1 rather than something newer: AGP 8.7 and above default to
// build-tools 35.0.0, and the only build-tools installed on the build machine is 34.0.0.
// Pinning 8.6.1 means the build resolves with what is actually on disk instead of reaching
// for a component that would have to be downloaded and might not be available offline.
plugins {
    id("com.android.application") version "8.6.1" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
    id("org.jetbrains.kotlin.jvm") version "2.0.21" apply false
}
