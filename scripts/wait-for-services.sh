#!/bin/bash

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

wait_for_service() {
    SERVICE=$1
    URL=$2
    MAX_ATTEMPTS=60
    ATTEMPT=0
    
    echo -n "Waiting for $SERVICE..."
    
    while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
        if curl -sf "$URL" > /dev/null 2>&1; then
            echo -e " ${GREEN}✓${NC}"
            return 0
        fi
        echo -n "."
        sleep 2
        ATTEMPT=$((ATTEMPT + 1))
    done
    
    echo -e " ${YELLOW}timeout${NC}"
    return 1
}

# Wait for core services
wait_for_service "MongoDB" "http://localhost:27017"
wait_for_service "Ollama" "http://localhost:11434/api/tags"
wait_for_service "Gateway" "http://localhost:8000/health"
wait_for_service "Discovery" "http://localhost:8001/health"
wait_for_service "Camoufox" "http://localhost:8002/health"
wait_for_service "Vision" "http://localhost:8003/health"
wait_for_service "Extraction" "http://localhost:8004/health"
wait_for_service "n8n" "http://localhost:5678/healthz"

echo ""
echo -e "${GREEN}All services are healthy!${NC}"
