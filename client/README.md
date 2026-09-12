# Personal Staffer native client

Flutter Windows + Android application. Read the repository's full build specification and current BUILD_STATUS for scope and verification limits.

Use Flutter 3.47.4 / Dart 3.13.3 and the committed `pubspec.lock`. All direct package versions are exact. `hooks.user_defines.sqlite3.source=sqlite3mc` links encryption-capable SQLite; release startup refuses ordinary unencrypted SQLite. Session secrets and the encryption key use OS secure storage.

```text
flutter pub get --enforce-lockfile
flutter analyze
flutter test
flutter run -d windows --dart-define=API_BASE_URL=http://127.0.0.1:8000
```

For SDKs that probe cloud-host metadata, the normal `CI=true` environment flag short-circuits Flutter's optional Azure bot check. Current engineering invocations also use `--suppress-analytics`.

- Windows setup, real-device gates, tray behavior and installer command: `../docs/WINDOWS_SETUP.md`
- Android build, FCM and signing: `../docs/ANDROID_SETUP.md`
- Full upstream references: `../docs/BUILD_SPECIFICATION.md` section 31

No provider secrets in Dart defines. `API_BASE_URL` is an origin, not `/api/v1`. HTTPS is required outside local debug loopback. The server path prefix is added by the client. `DEMO_MODE=true` is opt-in, checks the backend demo flag, and uses a separate local cache; synthetic jobs never populate an ordinary build.

Tests use isolated memory transport or temporary encrypted files. `integration_test/device_storage_test.dart` must additionally run on Windows and Samsung Android; Linux test success does not establish native key-store or notification lifecycle success. Never claim an installer/APK exists unless the relevant native build actually produced it.
