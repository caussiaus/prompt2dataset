#!/bin/bash

set -e

echo "======================================"
echo "AI-Augmented Web Scraper Setup"
echo "======================================"

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "Note: Some operations may require sudo privileges"
fi

# Create data directories
echo "Creating data directories..."
mkdir -p data/{mongodb,ollama,gateway,discovery,camoufox,vision,extraction,n8n}
chmod -R 755 data

# Check if .env exists
if [ ! -f .env ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
    echo "⚠️  Please edit .env file with your configuration!"
    echo "   Especially change MONGO_PASSWORD to a secure value."
fi

# Check Docker installation
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    echo "   Visit: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    echo "   Visit: https://docs.docker.com/compose/install/"
    exit 1
fi

# Check for NVIDIA GPU (optional)
if command -v nvidia-smi &> /dev/null; then
    echo "✅ NVIDIA GPU detected"
    if ! docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi &> /dev/null; then
        echo "⚠️  NVIDIA Docker runtime not properly configured"
        echo "   Visit: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
        echo "   GPU acceleration will not be available"
    else
        echo "✅ NVIDIA Docker runtime configured"
    fi
else
    echo "⚠️  No NVIDIA GPU detected. AI models will run on CPU (slower)"
fi

# Pull base images
echo ""
echo "Pulling base Docker images..."
docker pull mongo:7
docker pull ollama/ollama:latest
docker pull n8nio/n8n:latest
docker pull python:3.11-slim
docker pull mcr.microsoft.com/playwright/python:v1.40.0-jammy

echo ""
echo "======================================"
echo "Setup complete!"
echo "======================================"
echo ""
echo "Next steps:"
echo "1. Edit .env file with your configuration"
echo "2. Review models.config and select AI models to download"
echo "3. Run: docker-compose up -d"
echo "4. Wait for models to download (first run takes time)"
echo "5. Access services:"
echo "   - API Gateway: http://localhost:8000"
echo "   - API Docs: http://localhost:8000/docs"
echo "   - n8n: http://localhost:5678"
echo ""
echo "To check status: docker-compose ps"
echo "To view logs: docker-compose logs -f"
echo "To stop: docker-compose down"
echo ""
