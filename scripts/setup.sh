#!/bin/bash
# Setup script for prompt2dataset repository

set -e

echo "================================================"
echo "prompt2dataset - Setup Script"
echo "================================================"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   echo -e "${RED}Error: Do not run this script as root${NC}"
   exit 1
fi

echo -e "${GREEN}Step 1: Checking prerequisites...${NC}"

# Check Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker is not installed${NC}"
    echo "Please install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi
echo "✓ Docker is installed"

# Check Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}Error: Docker Compose is not installed${NC}"
    echo "Please install Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
fi
echo "✓ Docker Compose is installed"

# Check if Docker daemon is running
if ! docker info &> /dev/null; then
    echo -e "${RED}Error: Docker daemon is not running${NC}"
    echo "Please start Docker and try again"
    exit 1
fi
echo "✓ Docker daemon is running"

echo ""
echo -e "${GREEN}Step 2: Setting up environment...${NC}"

# Create .env file from example if it doesn't exist
if [ ! -f .env ]; then
    if [ -f config/.env.example ]; then
        cp config/.env.example .env
        echo "✓ Created .env from config/.env.example"
        echo -e "${YELLOW}⚠ Please edit .env and update the following:${NC}"
        echo "  - DB_PASSWORD (set a secure password)"
        echo "  - DOMAIN (set your domain name)"
        echo "  - Other service-specific settings"
        echo ""
        read -p "Press Enter to continue after editing .env..."
    else
        echo -e "${RED}Error: config/.env.example not found${NC}"
        exit 1
    fi
else
    echo "✓ .env file already exists"
fi

echo ""
echo -e "${GREEN}Step 3: Creating required directories...${NC}"

mkdir -p data/postgres data/ollama data/n8n
echo "✓ Created data directories"

echo ""
echo -e "${GREEN}Step 4: Validating configuration files...${NC}"

# Validate services.json
if [ -f services.json ]; then
    if python3 -c "import json; json.load(open('services.json'))" 2>/dev/null; then
        echo "✓ services.json is valid"
    else
        echo -e "${RED}Error: services.json is invalid JSON${NC}"
        exit 1
    fi
else
    echo -e "${RED}Error: services.json not found${NC}"
    exit 1
fi

# Validate coolify-manifest.yaml
if [ -f coolify-manifest.yaml ]; then
    echo "✓ coolify-manifest.yaml exists"
else
    echo -e "${RED}Error: coolify-manifest.yaml not found${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}Step 5: Installing Python dependencies for scripts...${NC}"

if command -v pip3 &> /dev/null; then
    pip3 install -q requests
    echo "✓ Installed Python dependencies"
else
    echo -e "${YELLOW}⚠ pip3 not found, skipping Python dependency installation${NC}"
fi

echo ""
echo -e "${GREEN}Step 6: Making scripts executable...${NC}"

chmod +x scripts/*.sh 2>/dev/null || true
chmod +x scripts/*.py 2>/dev/null || true
echo "✓ Made scripts executable"

echo ""
echo "================================================"
echo -e "${GREEN}Setup completed successfully!${NC}"
echo "================================================"
echo ""
echo "Next steps:"
echo ""
echo "1. Local testing:"
echo "   docker-compose -f docker-compose.local.yml up -d"
echo ""
echo "2. Check service health:"
echo "   python3 scripts/service_tracker.py"
echo ""
echo "3. For production deployment to Coolify:"
echo "   - See DEPLOYMENT.md for detailed instructions"
echo "   - Push this repo to GitHub"
echo "   - Connect repo to Coolify"
echo "   - Import coolify-manifest.yaml"
echo ""
echo "4. Test the services:"
echo "   python3 scripts/service_client.py --test"
echo ""
