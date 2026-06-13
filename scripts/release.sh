#!/bin/bash
# Release script — build + baseline validation + publish
#
# Usage:
#   bash scripts/release.sh                    # Full: olav + netops → TestPyPI
#   bash scripts/release.sh --core-only        # olav core only
#   bash scripts/release.sh --netops-only      # netops extension only
#   bash scripts/release.sh --no-publish       # Validate only, don't publish
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PHASE_ARG="${1:-}"
NO_PUBLISH=false
[[ "$PHASE_ARG" == "--no-publish" ]] && NO_PUBLISH=true && PHASE_ARG=""

echo "=== Build ==="
cd "$REPO_ROOT"
rm -rf dist/
uv build
WHEEL=$(ls dist/*.whl | tail -1)
echo "  Built: $(basename "$WHEEL")"

echo ""
echo "=== Tier 0 Baseline ==="
# Kill stale services
pkill -f "uvicorn.*olav.*2280" 2>/dev/null || true
pkill -f "syslog_receiver" 2>/dev/null || true
pkill -f "olav.*daemon" 2>/dev/null || true
sleep 1

bash tests/ci/tier0_packaging.sh ${PHASE_ARG}

if [ "$NO_PUBLISH" = true ]; then
    echo ""
    echo "=== --no-publish: skipping upload ==="
    exit 0
fi

echo ""
echo "=== Publish to TestPyPI ==="
if [ -f "${REPO_ROOT}/.pypirc_test" ]; then
    uv run twine upload --repository testpypi --config-file "${REPO_ROOT}/.pypirc_test" dist/*
    echo ""
    VERSION=$(grep 'version = ' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
    echo "✅ Released olav ${VERSION} → https://test.pypi.org/project/olav/${VERSION}/"
else
    echo "  .pypirc_test not found — skipping upload"
    echo "  Wheel ready at: ${WHEEL}"
fi
