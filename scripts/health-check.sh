#!/bin/bash
# Quick health check script

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "================================================"
echo "prompt2dataset - Quick Health Check"
echo "================================================"
echo ""

# Service endpoints
declare -A SERVICES=(
    ["PostgreSQL"]="http://localhost:5432"
    ["Ollama"]="http://localhost:11434/api/tags"
    ["Camoufox"]="http://localhost:3000/health"
    ["HTML Parser"]="http://localhost:5000/health"
    ["SearXNG"]="http://localhost:8888/"
    ["n8n"]="http://localhost:5678/rest/health"
    ["Agent Gateway"]="http://localhost:8000/health"
    ["Extraction Agent"]="http://localhost:8001/health"
    ["Vision Agent"]="http://localhost:8002/health"
    ["Orchestrator Agent"]="http://localhost:8003/health"
    ["Discovery Agent"]="http://localhost:8004/health"
)

check_service() {
    local name=$1
    local url=$2
    
    # Special case for PostgreSQL (check with pg_isready or docker)
    if [[ $name == "PostgreSQL" ]]; then
        if docker ps --filter "name=postgres" --filter "status=running" -q | grep -q .; then
            echo -e "${GREEN}✓${NC} $name is running"
            return 0
        else
            echo -e "${RED}✗${NC} $name is not running"
            return 1
        fi
    fi
    
    # HTTP health check
    if curl -s -f -o /dev/null -m 5 "$url" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} $name is healthy"
        return 0
    else
        echo -e "${RED}✗${NC} $name is not responding"
        return 1
    fi
}

# Check all services
healthy_count=0
total_count=${#SERVICES[@]}

for service in "${!SERVICES[@]}"; do
    if check_service "$service" "${SERVICES[$service]}"; then
        ((healthy_count++))
    fi
done

echo ""
echo "================================================"
echo "Summary: $healthy_count/$total_count services healthy"
echo "================================================"
echo ""

if [ $healthy_count -eq $total_count ]; then
    echo -e "${GREEN}✓ All services are healthy!${NC}"
    exit 0
elif [ $healthy_count -eq 0 ]; then
    echo -e "${RED}✗ No services are running${NC}"
    echo "Run: docker-compose -f docker-compose.local.yml up -d"
    exit 1
else
    echo -e "${YELLOW}⚠ Some services need attention${NC}"
    echo ""
    echo "For detailed status, run:"
    echo "  python3 scripts/service_tracker.py"
    exit 1
fi
