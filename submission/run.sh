#!/usr/bin/env bash
set -euo pipefail
SUBMISSION_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$SUBMISSION_DIR/src/run_router.py" "$@"
