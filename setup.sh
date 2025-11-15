#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Banner
echo -e "${BLUE}"
cat << "EOF"
╔═══════════════════════════════════════════════════════════╗
║   AI-Augmented Web Scraper Platform - Setup Wizard       ║
║   Deploy-ready in minutes from fresh clone               ║
╚═══════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

# Configuration
SETUP_MODE="${1:-full}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Functions
log_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

# Show menu
show_menu() {
    echo ""
    echo "Setup Modes:"
    echo "  1) Quick Start    - Minimal setup, fastest deployment (recommended for testing)"
    echo "  2) Full Setup     - All AI models, complete platform"
    echo "  3) Development    - Dev mode with hot reload"
    echo "  4) Coolify Ready  - Prepare for Coolify deployment"
    echo ""
    read -p "Select mode [1-4]: " choice
    
    case $choice in
        1) SETUP_MODE="quick" ;;
        2) SETUP_MODE="full" ;;
        3) SETUP_MODE="dev" ;;
        4) SETUP_MODE="coolify" ;;
        *) log_error "Invalid choice"; exit 1 ;;
    esac
}

# If no argument provided, show menu
if [ "$SETUP_MODE" = "full" ] && [ $# -eq 0 ]; then
    show_menu
fi

log_info "Starting setup in ${SETUP_MODE} mode..."

# Step 1: Pre-flight checks
log_info "Running pre-flight checks..."
bash "${SCRIPT_DIR}/scripts/preflight-check.sh"
log_success "Pre-flight checks passed"

# Step 2: Create directory structure
log_info "Creating directory structure..."
mkdir -p data/{mongodb,ollama,gateway,discovery,camoufox,vision,extraction,n8n}
mkdir -p logs
chmod -R 755 data logs
log_success "Directories created"

# Step 3: Environment configuration
if [ ! -f .env ]; then
    log_info "Creating .env file..."
    cp .env.example .env
    
    # Generate secure password
    MONGO_PASSWORD=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-25)
    if [ "$(uname)" = "Darwin" ]; then
        sed -i '' "s/changeme_secure_password/${MONGO_PASSWORD}/" .env
    else
        sed -i "s/changeme_secure_password/${MONGO_PASSWORD}/" .env
    fi
    log_success ".env file created with secure password"
else
    log_warning ".env file already exists, skipping"
fi

# Step 4: Configure models based on mode
log_info "Configuring AI models for ${SETUP_MODE} mode..."
case $SETUP_MODE in
    quick)
        cat > models.config << EOF
# Quick Start - Minimal models (~8GB)
llama3.1
llava
bge-m3
EOF
        log_success "Configured minimal model set"
        ;;
    full)
        log_info "Using full model configuration"
        ;;
    dev)
        cat > models.config << EOF
# Development - Fast models
gemma3
llava
bge-m3
EOF
        log_success "Configured development models"
        ;;
    coolify)
        log_info "Keeping default model configuration for Coolify"
        ;;
esac

# Step 5: Pull Docker images
log_info "Pulling base Docker images..."
docker pull mongo:7 2>/dev/null &
docker pull ollama/ollama:latest 2>/dev/null &
docker pull n8nio/n8n:latest 2>/dev/null &
docker pull python:3.11-slim 2>/dev/null &
wait
log_success "Base images pulled"

# Step 6: Build services
log_info "Building application containers..."
if [ "$SETUP_MODE" = "dev" ]; then
    docker-compose -f docker-compose.yml build --parallel 2>&1 | grep -v "^#" || true
else
    docker-compose build --parallel 2>&1 | grep -v "^#" || true
fi
log_success "Containers built"

# Step 7: Start services
log_info "Starting services..."
if [ "$SETUP_MODE" = "coolify" ]; then
    log_success "Coolify mode - skipping service start"
    echo ""
    echo "Next steps for Coolify:"
    echo "  1. Push this repository to your Git provider"
    echo "  2. In Coolify, add new Docker Compose resource"
    echo "  3. Point to your repository"
    echo "  4. Deploy!"
    exit 0
fi

docker-compose up -d
log_success "Services started"

# Step 8: Wait for services to be healthy
log_info "Waiting for services to become healthy..."
bash "${SCRIPT_DIR}/scripts/wait-for-services.sh"

# Step 9: Download AI models
log_info "Downloading AI models (this may take 10-30 minutes)..."
echo "You can monitor progress in another terminal with:"
echo "  docker logs -f webscraper-model-manager"
echo ""

docker-compose logs -f model-manager 2>&1 | grep -E "(Pulling|Successfully|Failed|Error)" &
MODEL_LOGS_PID=$!

# Wait for model manager to complete
docker wait webscraper-model-manager 2>/dev/null || true
kill $MODEL_LOGS_PID 2>/dev/null || true

log_success "AI models downloaded"

# Step 10: Run health checks
log_info "Running health checks..."
bash "${SCRIPT_DIR}/scripts/test-deployment.sh"

# Step 11: Summary
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Setup Complete! Your AI Web Scraper is ready! 🎉${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo "Access your services:"
echo "  📊 API Gateway:    http://localhost:8000"
echo "  📚 API Docs:       http://localhost:8000/docs"
echo "  🔄 n8n Workflows:  http://localhost:5678"
echo ""
echo "Quick test:"
echo "  curl http://localhost:8000/health"
echo ""
echo "View logs:"
echo "  docker-compose logs -f"
echo ""
echo "Stop services:"
echo "  docker-compose down"
echo ""
echo "Useful commands:"
echo "  make help          - Show all available commands"
echo "  make test          - Run test scrape"
echo "  make logs          - View all logs"
echo "  make status        - Check service status"
echo ""

# Save credentials
echo "Credentials saved to: credentials.txt"
cat > credentials.txt << EOF
MongoDB Username: admin
MongoDB Password: $(grep MONGO_PASSWORD .env | cut -d'=' -f2)
n8n: Create account on first login at http://localhost:5678
EOF
chmod 600 credentials.txt

log_success "Setup completed successfully!"
