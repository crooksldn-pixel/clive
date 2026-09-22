// `:core` is a plain JVM library. It must never gain an Android dependency: the whole point
// of the module is that a build machine with no emulator and no tablet can still RUN the
// shell's decisions and prove them. If a future change needs `android.*` in here, the change
// is in the wrong module.
plugins {
    id("org.jetbrains.kotlin.jvm")
    `java-library`
}

java {
    // Java 17 is what AGP 8 requires of the Android module; keeping `:core` on the same level
    // means one language level across the build and no surprises when `:app` consumes it.
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        // Warnings are not errors here only because the Kotlin 2.0 deprecation surface moves
        // between point releases and a shell that will not build is worse than a warning.
        allWarningsAsErrors.set(false)
    }
}

sourceSets {
    named("main") { kotlin.srcDir("src/main/kotlin") }
    named("test") { kotlin.srcDir("src/test/kotlin") }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}

tasks.withType<Test>().configureEach {
    useJUnit()
    testLogging {
        events("passed", "failed", "skipped")
        showStandardStreams = false
    }
}
