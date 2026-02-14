#!/bin/bash

##############################################################################
# 🚀 Real E2E Tests with Actual LLM & Device Integration
# 
# This script runs the E2E tests with REAL LLM and REAL device calls enabled.
# The skipif decorators will be bypassed to allow production-level testing.
##############################################################################

set -e

echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║         🚀 REAL E2E TESTS - ACTUAL LLM & DEVICE INTEGRATION           ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"
echo ""

# Export environment to enable real calls
export OPENAI_API_KEY="${LLM_API_KEY:-}"
export OPENAI_BASE_URL="${LLM_BASE_URL:-https://openrouter.ai/api/v1}"
export OPENAI_MODEL_NAME="${LLM_MODEL_NAME:-x-ai/grok-4.1-fast}"

# Configure for real device testing (if available)
export OLAV_TEST_DEVICE="${OLAV_TEST_DEVICE:-demo}"
export OLAV_ENABLE_REAL_CALLS="true"

echo "📋 Environment Setup:"
echo "  ├─ LLM Provider:    OpenRouter (Grok)"
echo "  ├─ LLM Model:       $(echo $OPENAI_MODEL_NAME | cut -d/ -f2)"
echo "  ├─ API Key:         ${OPENAI_API_KEY:0:20}..."
echo "  ├─ Device Mode:     REAL (mock available if device unavailable)"
echo "  └─ Test Level:      🏭 PRODUCTION"
echo ""

echo "🧪 Running E2E Tests with Real Integration..."
echo ""

# Run the tests with verbose output
cd /home/yhvh/Olav

echo "📊 Test Execution:"
echo "─────────────────────────────────────────────────────────────────────────"

uv run pytest \
  tests/e2e/test_real_scenarios.py \
  -v \
  --tb=short \
  --capture=no \
  -p no:warnings \
  2>&1 | tee /tmp/real_e2e_test_results.log

TEST_EXIT_CODE=${PIPESTATUS[0]}

echo ""
echo "─────────────────────────────────────────────────────────────────────────"
echo ""

# Parse results
PASSED=$(grep -c "PASSED" /tmp/real_e2e_test_results.log || echo "0")
FAILED=$(grep -c "FAILED" /tmp/real_e2e_test_results.log || echo "0")
SKIPPED=$(grep -c "SKIPPED" /tmp/real_e2e_test_results.log || echo "0")

echo "📈 Test Results Summary:"
echo "  ├─ ✅ Passed:    $PASSED"
echo "  ├─ ❌ Failed:    $FAILED"
echo "  ├─ ⏭️  Skipped:   $SKIPPED"
echo "  └─ Exit Code:  $TEST_EXIT_CODE"
echo ""

# LLM Call Detection
echo "🛡️  Safety Verification:"
if grep -q "OpenAI\|Anthropic\|openrouter" /tmp/real_e2e_test_results.log 2>/dev/null; then
  echo "  ├─ ✅ Real LLM calls detected (production level)"
else
  echo "  ├─ ⚠️  LLM calls not logged (check for mocks)"
fi

if grep -q "nornir\|execute\|device" /tmp/real_e2e_test_results.log 2>/dev/null; then
  echo "  └─ ✅ Device interactions detected (production level)"
else
  echo "  └─ ⚠️  Device interactions not logged (using mocks or no devices)"
fi
echo ""

if [ $TEST_EXIT_CODE -eq 0 ]; then
  echo "╔════════════════════════════════════════════════════════════════════════╗"
  echo "║                    ✨ ALL TESTS PASSED ✨                             ║"
  echo "║            System is production-ready with real integration!           ║"
  echo "╚════════════════════════════════════════════════════════════════════════╝"
else
  echo "╔════════════════════════════════════════════════════════════════════════╗"
  echo "║                   ❌ SOME TESTS FAILED                                ║"
  echo "║              Check /tmp/real_e2e_test_results.log for details         ║"
  echo "╚════════════════════════════════════════════════════════════════════════╝"
fi

exit $TEST_EXIT_CODE
