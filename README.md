# AI-Augmented Web Scraper

A production-ready, multi-agent web scraping system powered by state-of-the-art AI models. Deploy on Coolify or any Docker-compatible platform.

## 🌟 Features

### Multi-Agent Architecture
- **Gateway Agent**: Orchestrates all services and provides unified API
- **Discovery Agent**: Crawls websites and discovers site structure
- **Extraction Agent**: Extracts structured data using LLMs and CSS selectors
- **Vision Agent**: Processes images with OCR, VQA, and description generation
- **Camoufox Agent**: Stealth browser automation for JavaScript-heavy sites
- **Model Manager**: Handles AI model downloads and lifecycle

### SOTA AI Models Integration
- **Vision-Language Models**: llava, qwen3-vl, llama3.2-vision
- **LLMs**: llama3.1, llama3.3, gemma3, deepseek-r1, qwen3, glm-4.6
- **Embeddings**: bge-m3, bge-large, nomic-embed-text
- **Code Models**: deepseek-coder, codellama, qwen3-coder
- **RAG Models**: llama3-chatqa, deepseek-r1

### Pipeline Capabilities
- ✅ Document ingestion and preprocessing (OCR, Vision-Language)
- ✅ Semantic chunking and parsing
- ✅ Semantic search and retrieval (Embeddings)
- ✅ Summarization, extraction, QA, RAG
- ✅ Coding and automation support
- ✅ Multimodal processing (images, text, tables)

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- 8GB+ RAM (16GB+ recommended)
- NVIDIA GPU (optional, for faster AI processing)
- Linux, macOS, or Windows with WSL2

### Installation

1. **Clone the repository**
```bash
git clone <your-repo-url>
cd <repo-name>
```

2. **Run setup script**
```bash
sudo bash setup.sh
```

This will:
- Create necessary data directories
- Build all Docker images
- Start all services
- Verify health of all components

3. **Download AI models**
```bash
# Download recommended model set
curl -X POST http://localhost:8000/models/download/recommended

# Or download specific models
curl -X POST http://localhost:8000/models/download \
  -H "Content-Type: application/json" \
  -d '{"models": ["llava", "llama3.1", "bge-m3"]}'
```

4. **Access the services**
- Main Gateway: http://localhost:8000
- API Documentation: http://localhost:8000/docs
- Model Manager: http://localhost:8005

## 📖 Usage

### Basic Web Scraping

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "scraping_type": "full",
    "extract_images": true,
    "extract_text": true
  }'
```

### Advanced: LLM-Powered Extraction

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/products",
    "scraping_type": "extraction",
    "llm_extraction_prompt": "Extract product name, price, and description",
    "css_selectors": {
      "title": "h1.product-title",
      "price": ".price"
    }
  }'
```

### Browser Automation for JavaScript Sites

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://spa-website.com",
    "use_browser": true,
    "javascript_enabled": true,
    "wait_for_selector": ".content-loaded"
  }'
```

### Image Processing (OCR, VQA)

```bash
# Direct vision agent call for OCR
curl -X POST http://localhost:8003/ocr?image_url=https://example.com/image.jpg

# Visual Question Answering
curl -X POST "http://localhost:8003/vqa?image_url=https://example.com/chart.jpg&question=What+is+the+trend?"
```

### Site Discovery and Crawling

```bash
curl -X POST http://localhost:8001/discover \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "max_depth": 2,
    "follow_links": true
  }'
```

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Gateway Agent (8000)                  │
│              Main API & Orchestration Layer              │
└─────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  Discovery   │   │  Extraction  │   │    Vision    │
│  Agent       │   │  Agent       │   │    Agent     │
│  (8001)      │   │  (8002)      │   │    (8003)    │
└──────────────┘   └──────────────┘   └──────────────┘
        │                   │                   │
        └───────────────────┼───────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  Camoufox    │   │    Model     │   │   Ollama     │
│  Agent       │   │   Manager    │   │   Server     │
│  (8004)      │   │   (8005)     │   │   (11434)    │
└──────────────┘   └──────────────┘   └──────────────┘
                            │
        ┌───────────────────┴───────────────────┐
        │                                       │
        ▼                                       ▼
┌──────────────┐                       ┌──────────────┐
│   MongoDB    │                       │    Redis     │
│   (27017)    │                       │    (6379)    │
└──────────────┘                       └──────────────┘
```

## 🎯 API Endpoints

### Gateway Agent (Port 8000)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check for all services |
| `/scrape` | POST | Execute scraping task |
| `/tasks/{task_id}` | GET | Get task result |
| `/tasks` | GET | List recent tasks |
| `/models` | GET | List available models |
| `/models/download` | POST | Download models |
| `/models/download/recommended` | POST | Download recommended set |

### Discovery Agent (Port 8001)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/discover` | POST | Discover site structure |
| `/links` | POST | Extract links from page |

### Extraction Agent (Port 8002)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/extract` | POST | Extract structured data |
| `/extract/text` | POST | Extract clean text |

### Vision Agent (Port 8003)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/process` | POST | Process images |
| `/ocr` | POST | Perform OCR |
| `/vqa` | POST | Visual Q&A |
| `/describe` | POST | Image description |
| `/upload` | POST | Upload and process |

### Camoufox Agent (Port 8004)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/scrape` | POST | Browser-based scraping |
| `/scrape/infinite-scroll` | POST | Infinite scroll pages |
| `/scrape/interact` | POST | Interactive scraping |

### Model Manager (Port 8005)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/models` | GET | List all models |
| `/models/{name}` | GET | Model info |
| `/models/download` | POST | Download models |
| `/models/download/status` | GET | Download progress |

## 🔧 Configuration

### Environment Variables

Edit `.env` file to configure:

```bash
# MongoDB
MONGO_ROOT_USERNAME=admin
MONGO_ROOT_PASSWORD=secure_password

# AI Models
VISION_MODEL=llava
LLM_MODEL=llama3.1
EMBEDDING_MODEL=bge-m3
CODE_MODEL=deepseek-coder
RAG_MODEL=llama3-chatqa

# Application
DEBUG=false
MAX_CONCURRENT_REQUESTS=10
REQUEST_TIMEOUT=30
```

### Custom Model Configuration

To use different models, update the environment variables in `docker-compose.yml` or `.env`:

```yaml
environment:
  - VISION_MODEL=qwen3-vl      # For better vision tasks
  - LLM_MODEL=llama3.3          # Latest Llama
  - EMBEDDING_MODEL=nomic-embed-text
```

## 🚢 Deployment

### Coolify Deployment

1. **Add Repository**: In Coolify, add this Git repository as a new resource

2. **Configure Environment**: 
   - Copy variables from `.env.example`
   - Set secure passwords
   - Configure GPU support if available

3. **Deploy**: Coolify will use `docker-compose.yml` automatically

4. **Post-Deploy**: Run model download:
```bash
curl -X POST https://your-domain.com/models/download/recommended
```

### Manual Docker Deployment

```bash
# Build and start
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Remove all data
docker-compose down -v
```

### Production Considerations

1. **GPU Support**: For production AI workloads, GPU is highly recommended
   - Install NVIDIA Docker runtime
   - Uncomment GPU sections in docker-compose.yml

2. **Resource Allocation**: Minimum requirements per service:
   - Gateway: 512MB RAM
   - Discovery: 256MB RAM
   - Extraction: 1GB RAM
   - Vision: 2GB RAM
   - Camoufox: 2GB RAM (with 2GB shared memory)
   - Ollama: 8GB RAM + GPU (or 16GB+ RAM for CPU)
   - MongoDB: 512MB RAM
   - Redis: 256MB RAM

3. **Security**:
   - Change default MongoDB credentials
   - Use reverse proxy (Nginx/Traefik) with SSL
   - Implement API authentication (add to gateway)
   - Use network policies to isolate services

4. **Scaling**:
   - Scale agents horizontally: `docker-compose up -d --scale extraction-agent=3`
   - Use Redis for distributed task queue
   - Add load balancer for gateway

## 📊 Monitoring

### Health Checks

```bash
# Check all services
curl http://localhost:8000/health

# Check individual agents
curl http://localhost:8001/health  # Discovery
curl http://localhost:8002/health  # Extraction
curl http://localhost:8003/health  # Vision
curl http://localhost:8004/health  # Camoufox
curl http://localhost:8005/health  # Model Manager
```

### Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f gateway
docker-compose logs -f extraction-agent

# Last 100 lines
docker-compose logs --tail=100 gateway
```

### Metrics

Each service exposes health endpoints. To add Prometheus metrics:

1. Uncomment prometheus sections in docker-compose.yml
2. Access metrics at: http://localhost:9090

## 🧪 Testing

### Test Basic Scraping

```bash
# Test with a simple website
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://httpbin.org/html",
    "scraping_type": "extraction"
  }'
```

### Test Vision Agent

```bash
# Test OCR
curl -X POST http://localhost:8003/ocr \
  -H "Content-Type: application/json" \
  -d '{"image_urls": ["https://via.placeholder.com/300x200.png?text=Test+Text"]}'
```

### Test Discovery

```bash
# Test link discovery
curl -X POST http://localhost:8001/discover \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "max_depth": 1,
    "follow_links": false
  }'
```

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📝 License

See [LICENSE](LICENSE) file for details.

## 🆘 Troubleshooting

### Services not starting

```bash
# Check logs
docker-compose logs

# Restart services
docker-compose restart

# Rebuild if needed
docker-compose up -d --build
```

### Ollama connection errors

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Restart Ollama
docker-compose restart ollama
```

### Models not downloading

```bash
# Check model manager logs
docker-compose logs model-manager

# Manually pull model in Ollama container
docker exec -it webscraper-ollama ollama pull llama3.1
```

### GPU not detected

```bash
# Install NVIDIA Container Toolkit
# https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html

# Verify GPU access
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
```

### Memory issues

- Increase Docker memory limit
- Reduce concurrent requests: Set `MAX_CONCURRENT_REQUESTS=5`
- Use smaller models: `LLM_MODEL=gemma3`
- Enable swap for Ollama

### Permission errors

```bash
# Fix data directory permissions
sudo chown -R $USER:$USER /data
sudo chmod -R 755 /data
```

## 🔗 Useful Resources

- [Ollama Models](https://ollama.com/library)
- [Hugging Face Models](https://huggingface.co/models)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Docker Compose Reference](https://docs.docker.com/compose/)
- [Coolify Documentation](https://coolify.io/docs)

## 📧 Support

For issues and questions:
- Open an issue on GitHub
- Check existing issues for solutions
- Review logs: `docker-compose logs -f`

---

**Built with ❤️ using SOTA AI models and modern microservices architecture**
