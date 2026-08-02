plugins {
    id("com.android.application")
}

android {
    namespace = "com.jumpterminator.testsource"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.jumpterminator.testsource"
        minSdk = 28
        targetSdk = 36
        versionCode = 6
        versionName = "0.0.6-s0"
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
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}
