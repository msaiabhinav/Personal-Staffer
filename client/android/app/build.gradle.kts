import java.util.Properties
import java.io.FileInputStream

plugins {
    id("com.android.application")
    id("com.google.gms.google-services") apply false
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

if(file("google-services.json").exists()) apply(plugin = "com.google.gms.google-services")
val releaseKeys = Properties()
val releaseKeyFile = rootProject.file("key.properties")
if(releaseKeyFile.exists()) FileInputStream(releaseKeyFile).use { releaseKeys.load(it) }

android {
    namespace = "com.personalstaffer.personal_staffer"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        isCoreLibraryDesugaringEnabled = true
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = "com.personalstaffer.personal_staffer"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = maxOf(flutter.minSdkVersion, 23)
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        if(releaseKeyFile.exists()) create("release") {
            keyAlias = releaseKeys["keyAlias"] as String
            keyPassword = releaseKeys["keyPassword"] as String
            storeFile = file(releaseKeys["storeFile"] as String)
            storePassword = releaseKeys["storePassword"] as String
        }
    }
    buildTypes {
        release {
            // No debug signing keys are silently used for a release. Without
            // protected release keys Gradle produces an unsigned APK.
            if(releaseKeyFile.exists()) signingConfig = signingConfigs.getByName("release")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}

 dependencies { coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.5") }
