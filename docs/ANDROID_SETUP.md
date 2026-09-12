# Android client

The target phone is the specified Samsung Galaxy S25 Ultra. Confirm its installed Android version. The app shares the same backend account and state as Windows.

## Build and local run

Use Flutter **3.47.4**, Dart **3.13.3**, a full JDK 17 with `javac` (a JRE is insufficient), Android SDK platforms 34, 35 and 36 (the locked plugins compile against these), build tools 36.0.0, and the NDK selected by Flutter (**28.2.13676358** in this SDK). Install the tooling through [Android Studio](https://developer.android.com/studio) or the official command-line tools, then follow [Flutter's Android release instructions](https://docs.flutter.dev/deployment/android).

From `client/`:

```text
flutter doctor -v
flutter pub get --enforce-lockfile
flutter analyze
flutter test
flutter run -d YOUR_DEVICE_ID --dart-define=API_BASE_URL=https://YOUR-AUTHORIZED-SERVER
```

For a debug emulator, `http://10.0.2.2:5555` reaches a backend listening on the host. For a USB device with ADB port reverse, `adb reverse tcp:5555 tcp:5555` allows `http://127.0.0.1:5555` in debug. Release builds require HTTPS; cleartext is disabled in the release manifest. App data backup is disabled to avoid restoring encrypted bytes without the device key. No iOS or web substitute is included.

## Signing

Generate and retain your private release keystore outside Git. Create ignored `client/android/key.properties` locally:

```properties
storeFile=/absolute/private/path/personal-staffer.jks
storePassword=CONFIGURE_SECURELY
keyAlias=personal-staffer
keyPassword=CONFIGURE_SECURELY
```

Then run `flutter build apk --release --dart-define=API_BASE_URL=https://YOUR-AUTHORIZED-SERVER`. Gradle uses the protected release key only when supplied; it does not silently use the debug key for a release. An unsigned APK is not an installable private release. Keep the same signing key and increase the app version for updates.

Inspect a produced APK with `apksigner verify --print-certs`, calculate its SHA256, transfer it through your chosen private channel, and use `adb install -r PATH_TO_SIGNED_APK` on the authorized phone. No signing key or device is present in the engineering environment, so signed installation/update verification remains pending.

## FCM

Configure an Android Firebase app whose application ID matches `com.personalstaffer.personal_staffer`. Place its public client configuration in ignored `android/app/google-services.json`. The Gradle Google services plugin activates when that file exists. Supply FCM **server** credentials securely to the backend, never in this file or Dart defines. Build with `--dart-define=FCM_ENABLED=true` only after both sides are configured.

The native integration requests notification permission, registers and rotates tokens, refreshes authoritative state on foreground messages, handles background-open and terminated `getInitialMessage`, and retains exact notification routing through sign-in. Without configuration it is `NOT_CONFIGURED`; the persistent database inbox and manual tracking remain usable. Push contains notification IDs and minimal text, not mailbox bodies or application authority. See [FCM Flutter receive lifecycle](https://firebase.google.com/docs/cloud-messaging/flutter/receive-messages).

## Device acceptance

```text
flutter test integration_test/device_storage_test.dart -d YOUR_DEVICE_ID --dart-define=API_BASE_URL=https://YOUR-AUTHORIZED-SERVER
adb shell am start -a android.intent.action.VIEW -d personalstaffer://applications/AUTHORIZED_UUID
```

Verify Google login, secure key/cache round trip after process restart, Save/Apply pending while disconnected, reconnect sync, cross-device stale correction conflicts, correct unread count, exact job/application/report/review destinations, foreground/background/terminated FCM, force-stop recovery, back gesture, 48dp touch targets and large fonts. Capture screenshots from the device using `adb exec-out screencap -p` for final visual QA. Linux widget tests cover layout logic but are not Samsung or Android lifecycle verification.

## Engineering environment evidence

The Linux engineering environment downloaded the official Flutter 3.47.4 release, Android command-line tools, the required SDK/NDK packages and a full Corretto JDK 17. The Android command-line tools archive SHA256 was `4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583`; the Corretto archive SHA256 was `74ff458657da91ca222681993e3c6b9a8e3629ca8e61c0d8cd90527280da9aa5` and matched its official checksum.

For this environment, Java needs the configured network proxy supplied through standard Gradle system properties. Corretto also needs the environment's existing trusted CA store (`-Djavax.net.ssl.trustStore=/etc/ssl/certs/java/cacerts`). This preserves TLS certificate verification. `CI=true` prevents Flutter's optional cloud-host metadata probe; `--suppress-analytics` suppresses analytics. These are environment setup details, not app requirements.

The final release compile succeeded with exit 0, producing `Personal-Staffer-0.1.0-unsigned.apk` (62,268,066 bytes). SHA256: `823f076beefd0f80b33e6bed35c070eefda4dbff30539c3306ee0b64fe5655dd`. This is a **compile artifact**, built with the reserved invalid origin `https://backend-not-configured.invalid` and FCM disabled. It must be rebuilt with your authorized server and signed before installation. `apksigner verify` rejected it as unsigned as expected; there is no signing certificate or debug-key fallback.

The packaged manifest was inspected with Android `aapt2`: cleartext traffic and backup are disabled. The APK contains real application and encrypted SQLite native libraries for arm64-v8a, armeabi-v7a and x86_64. A recognized private-key/token pattern scan of every ZIP entry found no matches; that bounded scan is not proof against every possible secret. Evidence is retained in `docs/verification/android-artifact.json`, `android-manifest.log`, `android-apk.sha256` and `android-release-build.log`.

Both final native debug passes completed with clean `flutter analyze` and **20 passing tests** each, including encrypted Linux file reopening, snapshot replacement, account/session race protection, exact navigation, large fonts, first-view revision handling, and startup-error redaction. Logs are `docs/verification/native-pass-1.log` and `native-pass-2.log`. These are host tests, not Samsung installation, Android keystore, FCM lifecycle, or cross-device backend acceptance. The build reports nonfatal upstream Firebase/Kotlin transition, SDK XML-version, and Cupertino font lookup warnings; device visual validation remains pending.
