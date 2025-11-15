#!/bin/bash

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

PASSED=0
FAILED=0

test_endpoint() {
    NAME=$1
    URL=$2
    EXPECTED=$3
    
    echo -n "Testing $NAME... "
    RESPONSE=$(curl -s "$URL")
    
    if echo "$RESPONSE" | grep -q "$EXPECTED"; then
        echo -e "${GREEN}✓ PASSED${NC}"
        PASSED=$((PASSED + 1))
        return 0
    else
        echo -e "${RED}✗ FAILED${NC}"
        echo "  Expected: $EXPECTED"
        echo "  Got: $RESPONSE"
        FAILED=$((FAILED + 1))
        return 1
    fi
}

echo "Running Deployment Tests"
echo "========================"
echo ""

# Test health endpoints
test_endpoint "Gateway Health" "http://localhost:8000/health" '"status":"ok"'
test_endpoint "Discovery Health" "http://localhost:8001/health" '"status":"ok"'
test_endpoint "Camoufox Health" "http://localhost:8002/health" '"status":"ok"'
test_endpoint "Vision Health" "http://localhost:8003/health" '"status":"ok"'
test_endpoint "Extraction Health" "http://localhost:8004/health" '"status":"ok"'
test_endpoint "n8n Health" "http://localhost:5678/healthz" "ok"

# Test Ollama models
echo -n "Testing Ollama models... "
MODELS=$(curl -s http://localhost:11434/api/tags)
if echo "$MODELS" | grep -q "models"; then
    MODEL_COUNT=$(echo "$MODELS" | grep -o "name" | wc -l)
    echo -e "${GREEN}✓ PASSED${NC} ($MODEL_COUNT models installed)"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}✗ FAILED${NC}"
    FAILED=$((FAILED + 1))
fi

# Test Gateway service connections
echo -n "Testing Gateway service connections... "
GATEWAY_HEALTH=$(curl -s http://localhost:8000/health)
if echo "$GATEWAY_HEALTH" | grep -q '"discovery":"ok"'; then
    echo -e "${GREEN}✓ PASSED${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}✗ FAILED${NC}"
    echo "  Gateway cannot connect to downstream services"
    FAILED=$((FAILED + 1))
fi

# Test a simple scrape job
echo -n "Testing scrape job creation... "
JOB_RESPONSE=$(curl -s -X POST http://localhost:8000/scrape \
    -H "Content-Type: application/json" \
    -d '{"url":"https://example.com","strategy":"full","use_vision":false}')

if echo "$JOB_RESPONSE" | grep -q "job_id"; then
    echo -e "${GREEN}✓ PASSED${NC}"
    JOB_ID=$(echo "$JOB_RESPONSE" | grep -o '"job_id":"[^"]*"' | cut -d'"' -f4)
    echo "  Job ID: $JOB_ID"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}✗ FAILED${NC}"
    FAILED=$((FAILED + 1))
fi

echo ""
echo "========================"
echo "Test Results:"
echo "  ${GREEN}Passed: $PASSED${NC}"
echo "  ${RED}Failed: $FAILED${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}✗ Some tests failed${NC}"
    echo "Check logs with: docker-compose logs"
    exit 1
fi
