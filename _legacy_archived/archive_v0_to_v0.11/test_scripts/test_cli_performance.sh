#!/bin/bash
# CLI Performance & Cache Test Script
# Tests: output quality, performance, cache hit, performance improvement

set -e

echo "=================================="
echo "OLAV CLI Performance Test"
echo "=================================="
echo ""

# Test queries
QUERY1="List all devices"
QUERY2="Show device count"
QUERY3="List all devices"  # Same as QUERY1 to test cache

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to run query and measure time
run_query() {
    local query="$1"
    local test_name="$2"
    
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}Test: ${test_name}${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "Query: $query"
    echo ""
    
    # Measure execution time
    START_TIME=$(date +%s.%N)
    
    # Run CLI with echo
    OUTPUT=$(echo "$query" | uv run olav 2>&1)
    EXIT_CODE=$?
    
    END_TIME=$(date +%s.%N)
    DURATION=$(echo "$END_TIME - $START_TIME" | bc)
    
    echo "Output:"
    echo "$OUTPUT"
    echo ""
    
    # Check for cache indicators
    if echo "$OUTPUT" | grep -qi "cache\|cached\|FastPath"; then
        echo -e "${GREEN}✓ Cache Hit Detected${NC}"
        CACHE_HIT="YES"
    else
        echo -e "${YELLOW}○ No Cache Indicator${NC}"
        CACHE_HIT="NO"
    fi
    
    # Check exit code
    if [ $EXIT_CODE -eq 0 ]; then
        echo -e "${GREEN}✓ Exit Code: 0 (Success)${NC}"
    else
        echo -e "${YELLOW}⚠ Exit Code: $EXIT_CODE${NC}"
    fi
    
    # Display timing
    echo -e "${GREEN}⏱ Duration: ${DURATION}s${NC}"
    echo ""
    
    # Return duration for comparison
    echo "$DURATION"
}

# Array to store timings
declare -a TIMINGS

echo "Starting tests..."
echo ""

# Test 1: First query (cold start)
TIMINGS[0]=$(run_query "$QUERY1" "Test 1: First Query (Cold)")

sleep 1

# Test 2: Different query
TIMINGS[1]=$(run_query "$QUERY2" "Test 2: Different Query")

sleep 1

# Test 3: Repeat first query (cache test)
TIMINGS[2]=$(run_query "$QUERY3" "Test 3: Repeated Query (Cache Test)")

# Summary
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}Performance Summary${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Test 1 (Cold):     ${TIMINGS[0]}s"
echo "Test 2 (Different): ${TIMINGS[1]}s"
echo "Test 3 (Cached):    ${TIMINGS[2]}s"
echo ""

# Calculate speedup
if (( $(echo "${TIMINGS[0]} > 0" | bc -l) )); then
    SPEEDUP=$(echo "scale=2; ${TIMINGS[0]} / ${TIMINGS[2]}" | bc)
    IMPROVEMENT=$(echo "scale=1; (${TIMINGS[0]} - ${TIMINGS[2]}) / ${TIMINGS[0]} * 100" | bc)
    echo -e "${GREEN}Cache Speedup: ${SPEEDUP}x${NC}"
    echo -e "${GREEN}Performance Improvement: ${IMPROVEMENT}%${NC}"
else
    echo "Unable to calculate speedup"
fi

echo ""
echo -e "${GREEN}✓ Performance test completed${NC}"
