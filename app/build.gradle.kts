plugins {
    id("com.android.application")
}

android {
    namespace = "com.jumpterminator.app"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.jumpterminator.app"
        minSdk = 28
        targetSdk = 36
        versionCode = 10
        versionName = "0.0.10-s0"
        testInstrumentationRunner = "android.app.Instrumentation"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    lint {
        // AGP 9.0.1 documents Gradle 9.1.0 as its baseline; keep the S0 toolchain pinned.
        disable += "AndroidGradlePluginVersion"
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}
