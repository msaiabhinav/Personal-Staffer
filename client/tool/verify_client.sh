#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export CI=true
flutter --suppress-analytics pub get --enforce-lockfile
flutter --suppress-analytics analyze
flutter --suppress-analytics test
