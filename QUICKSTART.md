# Quick Start Guide

Get the AI-Augmented Web Scraper running in 5 minutes!

## Prerequisites

- Docker & Docker Compose installed
- 8GB+ RAM available
- (Optional) NVIDIA GPU for faster AI processing

## Installation

### 1. Clone and Setup

```bash
# Clone repository
git clone <your-repo-url>
cd <repo-name>

# Run automated setup
sudo bash setup.sh
```

The setup script will:
- Create data directories
- Build Docker images
- Start all services
- Verify health

### 2. Download AI Models

After services start, download the recommended models:

```bash
curl -X POST http://localhost:8000/models/download/recommended
```

This downloads:
- `llava` - Vision model for image processing
- `llama3.1` - LLM for text extraction
- `bge-m3` - Embedding model
- `deepseek-coder` - Code model
- `llama3-chatqa` - Q&A model

⏱️ **Note**: Model downloads take 10-30 minutes depending on your internet speed.

### 3. Verify Installation

```bash
# Check all services are healthy
curl http://localhost:8000/health

# Expected output:
# {
#   "status": "healthy",
#   "agent": "gateway",
#   "dependencies": {
#     "discovery": true,
#     "extraction": true,
#     "vision": true,
#     "camoufox": true,
#     "model_manager": true,
#     "mongodb": true
#   }
# }
```

## Your First Scrape

### Example 1: Simple Web Page

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "scraping_type": "extraction"
  }' | jq
```

### Example 2: Extract with LLM

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://news.ycombinator.com",
    "scraping_type": "extraction",
    "llm_extraction_prompt": "Extract the top 5 article headlines with their links"
  }' | jq
```

### Example 3: Process Image

```bash
curl -X POST http://localhost:8003/ocr \
  -H "Content-Type: application/json" \
  -d '{
    "image_urls": ["https://via.placeholder.com/400x200.png?text=Sample+Text"]
  }' | jq
```

## Access Points

Once running, access these services:

| Service | URL | Description |
|---------|-----|-------------|
| Gateway API | http://localhost:8000 | Main API endpoint |
| API Docs | http://localhost:8000/docs | Interactive API documentation |
| Discovery Agent | http://localhost:8001 | Web crawling service |
| Extraction Agent | http://localhost:8002 | Data extraction service |
| Vision Agent | http://localhost:8003 | Image processing service |
| Browser Agent | http://localhost:8004 | Browser automation |
| Model Manager | http://localhost:8005 | AI model management |

## Common Commands

```bash
# View logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f gateway

# Restart a service
docker-compose restart gateway

# Stop all services
docker-compose down

# Stop and remove all data
docker-compose down -v

# Rebuild and restart
docker-compose up -d --build
```

## Monitor Model Downloads

```bash
# Check download status
curl http://localhost:8005/models/download/status | jq

# List all models
curl http://localhost:8005/models | jq
```

## Next Steps

1. **Read the Documentation**:
   - [README.md](README.md) - Complete documentation
   - [API_DOCUMENTATION.md](API_DOCUMENTATION.md) - Full API reference
   - [EXAMPLES.md](EXAMPLES.md) - Usage examples
   - [DEPLOYMENT.md](DEPLOYMENT.md) - Production deployment

2. **Try Advanced Features**:
   - Browser automation for JavaScript sites
   - Multi-page crawling
   - Image analysis and OCR
   - Custom LLM prompts

3. **Configure for Your Needs**:
   - Edit `.env` for custom settings
   - Choose different AI models
   - Adjust resource limits

## Troubleshooting

### Services Not Starting?

```bash
# Check Docker resources
docker stats

# Ensure enough memory allocated
# Edit Docker Desktop settings or /etc/docker/daemon.json
```

### Models Not Downloading?

```bash
# Check Ollama logs
docker-compose logs ollama

# Manually pull a model
docker exec -it webscraper-ollama ollama pull llama3.1
```

### Gateway Shows Degraded?

```bash
# Check which service is down
curl http://localhost:8000/health | jq '.dependencies'

# Restart the failing service
docker-compose restart <service-name>
```

### Out of Disk Space?

```bash
# Check Docker disk usage
docker system df

# Clean up
docker system prune -a --volumes
```

## Getting Help

- Check logs: `docker-compose logs`
- View health: `curl http://localhost:8000/health`
- Read [README.md](README.md) troubleshooting section
- Open GitHub issue with logs and error details

## What's Running?

After setup, you have:

- **6 Microservices**: Gateway, Discovery, Extraction, Vision, Browser, Model Manager
- **3 Infrastructure Services**: MongoDB, Redis, Ollama
- **9 Containers Total**
- **SOTA AI Models**: Ready for inference

---

**🎉 You're ready to build AI-powered web scrapers!**

Check [EXAMPLES.md](EXAMPLES.md) for real-world use cases and code samples.
