#!/bin/bash
set -e

echo "================================================"
echo "AI-Augmented Web Scraper - Setup Script"
echo "================================================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "⚠️  Warning: This script should be run as root for creating data directories"
    echo "If you encounter permission errors, please run with sudo"
    echo ""
fi

# Create data directories
echo "📁 Creating data directories..."
mkdir -p /data/mongodb
mkdir -p /data/redis
mkdir -p /data/ollama
mkdir -p /data/models
mkdir -p /data/scraper
chmod -R 755 /data

echo "✅ Data directories created"
echo ""

# Check for .env file
if [ ! -f .env ]; then
    echo "📝 Creating .env file from template..."
    cp .env.example .env
    echo "⚠️  Please edit .env file with your configuration"
    echo ""
else
    echo "✅ .env file already exists"
    echo ""
fi

# Check Docker installation
echo "🐳 Checking Docker installation..."
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not found. Please install Docker first:"
    echo "   https://docs.docker.com/engine/install/"
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose not found. Please install Docker Compose:"
    echo "   https://docs.docker.com/compose/install/"
    exit 1
fi

echo "✅ Docker and Docker Compose are installed"
echo ""

# Check for GPU support (optional)
echo "🎮 Checking for NVIDIA GPU support..."
if command -v nvidia-smi &> /dev/null; then
    echo "✅ NVIDIA GPU detected"
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
    echo ""
    echo "GPU acceleration will be enabled for Ollama"
else
    echo "⚠️  No NVIDIA GPU detected. Ollama will run on CPU (slower)"
    echo "   For GPU support, install NVIDIA Docker runtime:"
    echo "   https://github.com/NVIDIA/nvidia-docker"
fi
echo ""

# Build images
echo "🔨 Building Docker images..."
echo "This may take several minutes..."
docker-compose build

echo "✅ Docker images built successfully"
echo ""

# Start services
echo "🚀 Starting services..."
docker-compose up -d

echo ""
echo "⏳ Waiting for services to be ready..."
sleep 10

# Check health
echo ""
echo "🏥 Checking service health..."
for i in {1..30}; do
    if curl -f http://localhost:8000/health &> /dev/null; then
        echo "✅ Gateway is healthy!"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "⚠️  Gateway health check timed out. Check logs with: docker-compose logs gateway"
    fi
    echo "   Waiting for gateway... ($i/30)"
    sleep 2
done

echo ""
echo "================================================"
echo "✅ Setup Complete!"
echo "================================================"
echo ""
echo "🌐 Service URLs:"
echo "   Gateway:        http://localhost:8000"
echo "   API Docs:       http://localhost:8000/docs"
echo "   Discovery:      http://localhost:8001"
echo "   Extraction:     http://localhost:8002"
echo "   Vision:         http://localhost:8003"
echo "   Camoufox:       http://localhost:8004"
echo "   Model Manager:  http://localhost:8005"
echo "   Ollama:         http://localhost:11434"
echo ""
echo "📊 To download recommended AI models, run:"
echo "   curl -X POST http://localhost:8000/models/download/recommended"
echo ""
echo "📝 To view logs:"
echo "   docker-compose logs -f"
echo ""
echo "🛑 To stop services:"
echo "   docker-compose down"
echo ""
echo "🗑️  To remove all data:"
echo "   docker-compose down -v"
echo ""
