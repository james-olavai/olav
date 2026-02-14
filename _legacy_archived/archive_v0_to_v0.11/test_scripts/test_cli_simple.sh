#!/bin/bash
# Simplified CLI Performance Test
set -e

echo "==================================="
echo "OLAV CLI Performance & Cache Test"
echo "==================================="
echo ""

# Test queries
Q1="List all devices"
Q2="Show device count"  
Q3="List all devices"  # Repeat Q1 for cache test

echo "Test 1: First query (cold start)"
echo "Query: $Q1"
echo ""
T1_START=$(date +%s%N)
echo "$Q1" | uv run olav 2>&1 | tee /tmp/olav_test1.txt
T1_END=$(date +%s%N)
T1_MS=$(( (T1_END - T1_START) / 1000000 ))
echo ""
echo "Duration: ${T1_MS}ms"
echo ""
sleep 1

echo "==================================="
echo "Test 2: Different query"
echo "Query: $Q2"
echo ""
T2_START=$(date +%s%N)
echo "$Q2" | uv run olav 2>&1 | tee /tmp/olav_test2.txt
T2_END=$(date +%s%N)
T2_MS=$(( (T2_END - T2_START) / 1000000 ))
echo ""
echo "Duration: ${T2_MS}ms"
echo ""
sleep 1

echo "==================================="
echo "Test 3: Repeated query (cache test)"
echo "Query: $Q3"
echo ""
T3_START=$(date +%s%N)
echo "$Q3" | uv run olav 2>&1 | tee /tmp/olav_test3.txt
T3_END=$(date +%s%N)
T3_MS=$(( (T3_END - T3_START) / 1000000 ))
echo ""
echo "Duration: ${T3_MS}ms"
echo ""

echo "==================================="
echo "Performance Summary"
echo "==================================="
echo "Test 1 (Cold):      ${T1_MS}ms"
echo "Test 2 (Different): ${T2_MS}ms"
echo "Test 3 (Cached):    ${T3_MS}ms"
echo ""

# Check for cache indicators
if grep -qi "cache\|cached\|FastPath" /tmp/olav_test3.txt; then
    echo "✓ Cache hit detected in Test 3"
else
    echo "○ No cache indicator found"
fi

# Calculate speedup
if [ $T3_MS -gt 0 ]; then
    SPEEDUP=$(awk "BEGIN {printf \"%.2f\", $T1_MS / $T3_MS}")
    IMPROVE=$(awk "BEGIN {printf \"%.1f\", ($T1_MS - $T3_MS) * 100.0 / $T1_MS}")
    echo "Cache Speedup: ${SPEEDUP}x"
    echo "Performance Improvement: ${IMPROVE}%"
fi

echo ""
echo "Full outputs saved to /tmp/olav_test*.txt"
