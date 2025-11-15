#!/bin/bash
set -e

# Ultra-fast setup for testing (skips health checks, uses minimal models)

echo "🚀 Quick Start - Getting you running in 5 minutes!"
echo ""

# Create minimal environment
if [ ! -f .env ]; then
    cp .env.example .env
    sed -i.bak 's/changeme_secure_password/quickstart123/' .env 2>/dev/null || \
    sed -i 's/changeme_secure_password/quickstart123/' .env
fi

# Minimal models only
cat > models.config << EOF
# Quick Start - Bare minimum
llama3.1
llava
EOF

# Create directories
mkdir -p data/{mongodb,ollama,gateway,discovery,camoufox,vision,extraction,n8n}

# Pull and start
echo "Starting services..."
docker-compose up -d mongodb ollama 2>&1 | grep -v "^#" || true

echo "Waiting for database..."
sleep 5

docker-compose up -d 2>&1 | grep -v "^#" || true

echo ""
echo "✓ Services starting in background"
echo ""
echo "Monitor startup:"
echo "  docker-compose logs -f"
echo ""
echo "Once ready (5-10 min), access:"
echo "  http://localhost:8000/docs"
echo ""
echo "Check status:"
echo "  curl http://localhost:8000/health"
