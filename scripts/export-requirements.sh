#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file ../requirements.txt > /dev/null
uv export --frozen --no-emit-project --format requirements-txt --output-file requirements-dev.txt > /dev/null
cp ../README.md ../Readme.txt
