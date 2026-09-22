// CROOKS Pad — the Gradle root for the native Android shell.
//
// Two modules, and the split is deliberate rather than tidy-minded. `:core` is a plain JVM
// Kotlin library with NO Android dependency at all, and it holds every decision the shell
// makes: which origins are trusted, what state the connection is in, when to retry, whether
// a microphone request may be granted, what a telemetry event is allowed to say. `:app` is
// the Android layer that draws those decisions and talks to the hardware.
//
// The reason for the split is that this repository is built on a Linux machine with no
// emulator and no attached tablet, so anything that needs a device cannot be exercised here
// at all. Putting the decisions in a module the plain JVM can run means the decisions ARE
// tested, honestly, by `:core:test` — and the compiler enforces the boundary: if someone
// reaches for `android.*` inside `:core`, it does not compile.

pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "crooks-pad"
include(":core")
include(":app")
