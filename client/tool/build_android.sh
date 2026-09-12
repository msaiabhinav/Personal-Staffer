#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${STAFFER_API_ORIGIN:?Set STAFFER_API_ORIGIN to the authorized HTTPS server origin}"
export CI=true
flutter --suppress-analytics pub get --enforce-lockfile
flutter --suppress-analytics analyze
flutter --suppress-analytics test
flutter --suppress-analytics build apk --release "--dart-define=API_BASE_URL=$STAFFER_API_ORIGIN" "--dart-define=FCM_ENABLED=${STAFFER_FCM_ENABLED:-false}"
find build/app/outputs -name '*.apk' -print -exec sha256sum '{}' \;
if [[ ! -f android/key.properties ]]; then
  echo 'Release signing is NOT_CONFIGURED. An unsigned APK is not an installable private release.'
fi
