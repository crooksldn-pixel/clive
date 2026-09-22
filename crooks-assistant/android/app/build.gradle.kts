plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.crooks.pad"

    // compileSdk 34, targetSdk 30. The two numbers are deliberately different and the reason
    // is written down in android/docs/DECISIONS.md; the short version is that compiling
    // against 34 lets the shell CALL newer APIs behind version guards, while declaring
    // target 30 keeps the shell running under exactly the Android 11 behaviour contract of
    // the one device that exists — the SM-T290. Behaviour changes gated on targetSdk take
    // effect only on devices at that API level, so targeting 34 on an API 30 tablet would
    // buy nothing at runtime and cost a behaviour surface nobody here can test.
    compileSdk = 34
    buildToolsVersion = "34.0.0"

    defaultConfig {
        applicationId = "com.crooks.pad"
        // minSdk 26 (Android 8.0). Not lower, because `WebViewClient.onRenderProcessGone` —
        // the callback without which a WebView renderer crash takes the whole process down —
        // arrived in API 26, and §11 requires that crash to be survivable. Not higher,
        // because there is no reason to exclude an older spare tablet from the fleet.
        minSdk = 26
        targetSdk = 30
        versionCode = 1
        versionName = "0.1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // The one and only place the CROOKS origin is written. It reaches the code through
        // BuildConfig and is validated at startup against the same allow-list the navigation
        // guard uses, so a typo here fails closed into APP ERROR rather than loading
        // something unexpected. It is a hostname, not a credential: nothing secret is here.
        buildConfigField("String", "CROOKS_ORIGIN", "\"https://crooks-assistant.taildfb357.ts.net\"")
    }

    buildFeatures {
        buildConfig = true
        viewBinding = false
    }

    buildTypes {
        debug {
            isMinifyEnabled = false
            // WebView remote debugging is switched on from code, guarded by this flag, and by
            // nothing else. §6.4: it must be off in release. See PadWebView.kt.
            buildConfigField("boolean", "WEBVIEW_DEBUG", "true")
        }
        release {
            isMinifyEnabled = false
            buildConfigField("boolean", "WEBVIEW_DEBUG", "false")
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    sourceSets {
        named("main") { kotlin.srcDir("src/main/kotlin") }
        named("test") { kotlin.srcDir("src/test/kotlin") }
    }

    lint {
        // The shell is sideloaded onto one tablet, not published, so Play's target-API floor
        // does not apply and the lint check that enforces it would be noise. Everything else
        // stays on.
        disable += "ExpiredTargetSdkVersion"
        disable += "OldTargetApi"
        abortOnError = false
    }

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

dependencies {
    implementation(project(":core"))
    implementation("androidx.core:core-ktx:1.13.1")
    // androidx.webkit is here for one reason worth the dependency: WebViewFeature lets the
    // shell ASK whether a hardening feature exists on this device's WebView rather than
    // assuming it, which on a 2019 tablet with a WebView that may be years behind is the
    // difference between hardening and the appearance of hardening.
    implementation("androidx.webkit:webkit:1.11.0")

    testImplementation("junit:junit:4.13.2")
}

tasks.withType<Test>().configureEach {
    testLogging {
        events("passed", "failed", "skipped")
        showStandardStreams = false
    }
}
