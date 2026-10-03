#!/usr/bin/env bash
set -euo pipefail
SUBMISSION_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
THREADS=${1:-32}
[[ "$THREADS" =~ ^[0-9]+$ ]] && (( THREADS >= 1 && THREADS <= 32 )) || { echo 'threads must be between 1 and 32' >&2; exit 2; }
BASE_SOURCE=${OPENROAD_BASE_ROOT:-/opt/contest/openroad-base}
[[ -f "$BASE_SOURCE/CMakeLists.txt" ]] || { echo "Missing complete OpenROAD base: $BASE_SOURCE. Run build.sh inside the supplied contest Docker image." >&2; exit 2; }
[[ -f "$SUBMISSION_DIR/openroad_overlay/src/grt/src/GlobalRouter.cpp" ]] || { echo 'Missing GRT source overlay; run submission/package.py in the source project first.' >&2; exit 2; }
BUILD_ROOT=${SUBMISSION_BUILD_DIR:-${TMPDIR:-/tmp}/open3dbench-grt-build-${UID}}
mkdir -p "$BUILD_ROOT"
exec 9>"$BUILD_ROOT/.build.lock"
flock 9
python3 "$SUBMISSION_DIR/src/materialize_source.py" "$BASE_SOURCE" "$SUBMISSION_DIR/openroad_overlay" "$BUILD_ROOT/openroad-src"
cmake_args=(-S "$BUILD_ROOT/openroad-src" -B "$BUILD_ROOT/openroad-build" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$BUILD_ROOT/install")
if [[ -d /usr/local/lib/cmake/Boost-1.89.0 ]]; then
  cmake_args+=(-DBoost_ROOT=/usr/local -DBoost_DIR=/usr/local/lib/cmake/Boost-1.89.0)
fi
if command -v ninja >/dev/null 2>&1; then cmake_args+=(-G Ninja); fi
cmake "${cmake_args[@]}"
cmake --build "$BUILD_ROOT/openroad-build" --target openroad -j "$THREADS"
"$BUILD_ROOT/openroad-build/bin/openroad" -version
python3 "$SUBMISSION_DIR/src/materialize_source.py" --fingerprint "$SUBMISSION_DIR/openroad_overlay" > "$BUILD_ROOT/.submission-source-sha256"
