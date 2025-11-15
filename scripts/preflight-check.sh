#!/bin/bash
set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ERRORS=0
WARNINGS=0

check_command() {
    if command -v $1 &> /dev/null; then
        echo -e "${GREEN}✓${NC} $1 is installed"
        return 0
    else
        echo -e "${RED}✗${NC} $1 is not installed"
        ERRORS=$((ERRORS + 1))
        return 1
    fi
}

check_docker_version() {
    if command -v docker &> /dev/null; then
        VERSION=$(docker --version | grep -oE '[0-9]+\.[0-9]+' | head -1)
        MAJOR=$(echo $VERSION | cut -d. -f1)
        if [ "$MAJOR" -ge 20 ]; then
            echo -e "${GREEN}✓${NC} Docker version $VERSION (OK)"
        else
            echo -e "${YELLOW}⚠${NC} Docker version $VERSION (20.0+ recommended)"
            WARNINGS=$((WARNINGS + 1))
        fi
    fi
}

check_docker_compose() {
    if docker compose version &> /dev/null; then
        echo -e "${GREEN}✓${NC} Docker Compose v2 (built-in) is available"
    elif command -v docker-compose &> /dev/null; then
        echo -e "${GREEN}✓${NC} Docker Compose v1 is available"
    else
        echo -e "${RED}✗${NC} Docker Compose is not available"
        ERRORS=$((ERRORS + 1))
    fi
}

check_disk_space() {
    AVAILABLE=$(df -BG . | tail -1 | awk '{print $4}' | sed 's/G//')
    if [ "$AVAILABLE" -gt 50 ]; then
        echo -e "${GREEN}✓${NC} Disk space: ${AVAILABLE}GB available (OK)"
    elif [ "$AVAILABLE" -gt 20 ]; then
        echo -e "${YELLOW}⚠${NC} Disk space: ${AVAILABLE}GB available (50GB+ recommended)"
        WARNINGS=$((WARNINGS + 1))
    else
        echo -e "${RED}✗${NC} Disk space: ${AVAILABLE}GB available (insufficient)"
        ERRORS=$((ERRORS + 1))
    fi
}

check_memory() {
    if [ "$(uname)" = "Darwin" ]; then
        TOTAL_MEM=$(sysctl -n hw.memsize | awk '{print int($1/1024/1024/1024)}')
    else
        TOTAL_MEM=$(free -g | awk '/^Mem:/{print $2}')
    fi
    
    if [ "$TOTAL_MEM" -ge 16 ]; then
        echo -e "${GREEN}✓${NC} Memory: ${TOTAL_MEM}GB (OK)"
    elif [ "$TOTAL_MEM" -ge 8 ]; then
        echo -e "${YELLOW}⚠${NC} Memory: ${TOTAL_MEM}GB (16GB+ recommended)"
        WARNINGS=$((WARNINGS + 1))
    else
        echo -e "${RED}✗${NC} Memory: ${TOTAL_MEM}GB (insufficient)"
        ERRORS=$((ERRORS + 1))
    fi
}

check_gpu() {
    if command -v nvidia-smi &> /dev/null; then
        GPU_COUNT=$(nvidia-smi -L | wc -l)
        echo -e "${GREEN}✓${NC} NVIDIA GPU detected ($GPU_COUNT GPU(s))"
        
        if docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi &> /dev/null; then
            echo -e "${GREEN}✓${NC} NVIDIA Docker runtime configured"
        else
            echo -e "${YELLOW}⚠${NC} NVIDIA Docker runtime not configured (GPU won't be used)"
            WARNINGS=$((WARNINGS + 1))
        fi
    else
        echo -e "${YELLOW}⚠${NC} No NVIDIA GPU detected (will use CPU - slower)"
        WARNINGS=$((WARNINGS + 1))
    fi
}

check_ports() {
    PORTS=(8000 8001 8002 8003 8004 5678 11434 27017)
    for PORT in "${PORTS[@]}"; do
        if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1 || netstat -tuln 2>/dev/null | grep -q ":$PORT "; then
            echo -e "${YELLOW}⚠${NC} Port $PORT is already in use"
            WARNINGS=$((WARNINGS + 1))
        fi
    done
    if [ $WARNINGS -eq 0 ]; then
        echo -e "${GREEN}✓${NC} All required ports are available"
    fi
}

echo "Pre-flight System Checks"
echo "========================"
echo ""

echo "Required Software:"
check_command docker
check_docker_version
check_docker_compose
check_command curl
check_command git
echo ""

echo "System Resources:"
check_memory
check_disk_space
echo ""

echo "Optional Features:"
check_gpu
echo ""

echo "Network:"
check_ports
echo ""

echo "========================"
if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}✗ $ERRORS error(s) found${NC}"
    echo ""
    echo "Please fix the errors above before continuing."
    echo ""
    echo "Installation help:"
    echo "  Docker: https://docs.docker.com/get-docker/"
    echo "  Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
elif [ $WARNINGS -gt 0 ]; then
    echo -e "${YELLOW}⚠ $WARNINGS warning(s) found${NC}"
    echo "You can continue, but some features may not work optimally."
    echo ""
else
    echo -e "${GREEN}✓ All checks passed!${NC}"
    echo ""
fi
