#!/bin/bash
# One-line installer: bash <(curl -fsSL https://raw.githubusercontent.com/your-repo/main/scripts/one-line-install.sh)

set -e

echo "🚀 AI Web Scraper - One Line Install"
echo ""

# Check if git is installed
if ! command -v git &> /dev/null; then
    echo "❌ Git is not installed. Please install git first."
    exit 1
fi

# Check if docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install docker first."
    echo "Visit: https://docs.docker.com/get-docker/"
    exit 1
fi

# Clone or update repo
if [ -d "ai-scraper" ]; then
    echo "📥 Updating existing installation..."
    cd ai-scraper
    git pull
else
    echo "📥 Cloning repository..."
    git clone https://github.com/your-username/ai-scraper.git
    cd ai-scraper
fi

# Run setup
echo "🔧 Running setup..."
bash setup.sh quick

echo ""
echo "✅ Installation complete!"
echo ""
echo "Access your services:"
echo "  http://localhost:8000/docs"
echo "  http://localhost:5678"
echo ""
