# prompt2dataset

Production-ready self-hosted multi-service orchestration for web data extraction and analysis.

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/docker-ready-brightgreen.svg)](https://www.docker.com/)

## Overview

**prompt2dataset** is a comprehensive data extraction and analysis platform that combines:

- 🤖 **AI-Powered Agents**: Extraction, vision, orchestration, and discovery
- 🌐 **Web Scraping**: HTML parsing and browser automation
- 🔍 **Search Integration**: Privacy-focused search via SearxNG
- 🧠 **Local LLMs**: Ollama with vision and text models
- 🗄️ **Vector Database**: PostgreSQL with pgvector
- 🔄 **Workflow Automation**: n8n for complex pipelines
- 📊 **Service Discovery**: Automatic health monitoring

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- 50GB+ free disk space (for LLM models)
- 8GB+ RAM (16GB+ recommended for vision models)

### Local Development

```bash
# 1. Clone repository
git clone <your-repo-url>
cd prompt2dataset

# 2. Configure environment
cp config/.env.example .env
# Edit .env with your settings

# 3. Start services
docker-compose -f docker-compose.local.yml up -d

# 4. Download LLM models
docker exec -it mvp-ollama bash
ollama pull mistral:latest
ollama pull llava:latest
exit

# 5. Verify services
python scripts/service_tracker.py
```

### Test the Stack

```bash
# Health check
curl http://localhost:8000/health

# Extract data from URL
curl -X POST http://localhost:8000/api/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "type": "full"}'

# Or use Python SDK
python scripts/service_client.py --test
```

---

## Architecture

```
┌───────────────────────────────────────────────────┐
│              Agent Gateway (Port 8000)            │
│              Unified API Entry Point              │
└───────────────────────────────────────────────────┘
                        ↓
┌───────────────────────────────────────────────────┐
│                 Agent Layer                       │
│  ┌─────────┐  ┌──────┐  ┌────────┐  ┌─────────┐ │
│  │Extraction│  │Vision│  │Orchestr│  │Discovery│ │
│  │ (8001)  │  │(8002)│  │ (8003) │  │ (8004) │ │
│  └─────────┘  └──────┘  └────────┘  └─────────┘ │
└───────────────────────────────────────────────────┘
                        ↓
┌───────────────────────────────────────────────────┐
│              Utility Services                     │
│     HTML Parser (5000) | Camoufox (3000)         │
│     SearxNG (8888)     | n8n (5678)              │
└───────────────────────────────────────────────────┘
                        ↓
┌───────────────────────────────────────────────────┐
│              Data & ML Layer                      │
│  PostgreSQL+pgvector (5432) | Ollama (11434)     │
└───────────────────────────────────────────────────┘
```

---

## Services

| Service | Purpose | Port | Status |
|---------|---------|------|--------|
| **agent-gateway** | API Gateway | 8000 | ✅ Ready |
| **extraction-agent** | Data extraction | 8001 | ✅ Ready |
| **vision-agent** | Image analysis | 8002 | ✅ Ready |
| **orchestrator-agent** | Workflow coordination | 8003 | ✅ Ready |
| **discovery-agent** | Service discovery | 8004 | ✅ Ready |
| **html-parser** | HTML parsing | 5000 | ✅ Ready |
| **postgres** | Database + vector | 5432 | ✅ Ready |
| **ollama** | Local LLMs | 11434 | ✅ Ready |
| **camoufox** | Browser automation | 3000 | ✅ Ready |
| **searxng** | Privacy search | 8888 | ✅ Ready |
| **n8n** | Workflow automation | 5678 | ✅ Ready |

**Detailed Service Documentation**: [docs/SERVICES.md](docs/SERVICES.md)

---

## Key Features

### 🎯 Unified API Gateway

Single entry point for all operations:

```python
from scripts.service_client import ServiceClient

client = ServiceClient('http://localhost:8000')

# Extract data
data = client.extract_data('https://example.com')

# Analyze image
analysis = client.analyze_image(
    image_url='https://example.com/image.jpg',
    prompt='What is in this image?'
)

# Run complete pipeline
result = client.run_pipeline(
    url='https://example.com',
    query='related content',
    include_images=True
)
```

### 🤖 Multi-Agent Workflows

Coordinate complex tasks across multiple agents:

```bash
curl -X POST http://localhost:8000/api/orchestrate \
  -H "Content-Type: application/json" \
  -d '{
    "workflow": "full-analysis",
    "url": "https://example.com",
    "query": "machine learning"
  }'
```

**Available Workflows**:
- `extract-and-analyze`: Extract content + analyze images
- `discover-and-extract`: Find related content + extract
- `full-analysis`: Complete analysis with all agents

### 🔍 Privacy-Focused Search

Discover content without tracking:

```bash
curl -X POST http://localhost:8000/api/discover \
  -H "Content-Type: application/json" \
  -d '{"query": "artificial intelligence", "limit": 10}'
```

### 🧠 Local Vision & LLMs

Process images and text without external APIs:

```bash
curl -X POST http://localhost:8000/api/analyze-image \
  -H "Content-Type: application/json" \
  -d '{
    "image_url": "https://example.com/chart.png",
    "prompt": "Extract all data from this chart"
  }'
```

### 🗄️ Vector Database

Store and search embeddings with pgvector:

```python
# Automatic storage of extracted data
# Query with semantic search
# Powered by PostgreSQL + pgvector
```

### 📊 Service Monitoring

Real-time health tracking:

```bash
# CLI monitoring
python scripts/service_tracker.py --watch

# API monitoring
curl http://localhost:8000/api/services/status
```

---

## API Endpoints

### Gateway Endpoints (Port 8000)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Gateway health check |
| `/api/extract` | POST | Extract data from URL |
| `/api/analyze-image` | POST | Analyze image with vision model |
| `/api/orchestrate` | POST | Run multi-agent workflow |
| `/api/discover` | POST | Discover related content |
| `/api/services` | GET | List all services |
| `/api/services/status` | GET | Get service health status |
| `/api/pipeline` | POST | Run complete extraction pipeline |

**Complete API Documentation**: [docs/API_ENDPOINTS.md](docs/API_ENDPOINTS.md)

---

## Deployment

### Local Development

```bash
docker-compose -f docker-compose.local.yml up -d
```

### Coolify Production Deployment

1. **Connect Repository**
   - Link your `prompt2dataset` repo to Coolify
   - Select branch: `main`
   - Set compose file: `coolify-manifest.yaml`

2. **Configure Environment**
   - Add variables from `config/.env.example`
   - Set `DB_PASSWORD`, `DOMAIN`, etc.

3. **Deploy Services**
   - Deploy in order: postgres → ollama → agents → gateway
   - Wait for each service to be healthy

4. **Download Models**
   ```bash
   docker exec <ollama-container> ollama pull mistral:latest
   docker exec <ollama-container> ollama pull llava:latest
   ```

**Complete Deployment Guide**: [DEPLOYMENT.md](DEPLOYMENT.md)

---

## Usage Examples

### Extract Data from Website

```python
from scripts.service_client import ServiceClient

client = ServiceClient('http://localhost:8000')

# Extract all data
result = client.extract_data('https://news.ycombinator.com')

print(f"Title: {result['title']}")
print(f"Links found: {len(result['links'])}")
print(f"Images found: {len(result['images'])}")
```

### Analyze Product Images

```python
# Analyze product image
analysis = client.analyze_image(
    image_url='https://example.com/product.jpg',
    prompt='Describe this product and identify its key features'
)

print(analysis['analysis'])
```

### Discover Related Content

```python
# Find related articles
discoveries = client.discover_content(
    query='machine learning tutorials',
    limit=10
)

for url in discoveries['urls']:
    print(f"{url['title']}: {url['url']}")
```

### Complete Data Pipeline

```python
# Run full pipeline
result = client.run_pipeline(
    url='https://example.com/article',
    query='similar articles',
    include_images=True
)

# Access results
extraction = result['extraction']
discoveries = result['discovery']
image_analyses = result['analyzed_images']
```

### CLI Usage

```bash
# Health check
python scripts/service_client.py --health

# Extract data
python scripts/service_client.py --extract "https://example.com"

# Discover content
python scripts/service_client.py --discover "AI trends"

# Run pipeline
python scripts/service_client.py --pipeline "https://example.com" \
  --query "related" --export results.json
```

---

## Configuration

### Environment Variables

Copy and configure:

```bash
cp config/.env.example .env
```

**Key Variables**:

```bash
# Database
DB_PASSWORD=your_secure_password
DB_HOST=postgres
DB_NAME=app_db

# Domain (production)
DOMAIN=yourdomain.com

# Service URLs (internal)
EXTRACTION_AGENT_URL=http://extraction-agent:8001
VISION_AGENT_URL=http://vision-agent:8002
OLLAMA_URL=http://ollama:11434

# Logging
LOG_LEVEL=info
```

### Service Registry

All services are defined in `services.json`:

```json
{
  "project": "MVP",
  "version": "1.0.0",
  "services": {
    "extraction-agent": {
      "port": 8001,
      "health_check": "http://localhost:8001/health"
    }
  }
}
```

---

## Development

### Project Structure

```
prompt2dataset/
├── services/                  # Microservices
│   ├── html-parser/          # HTML parsing service
│   ├── extraction-agent/     # Data extraction agent
│   ├── vision-agent/         # Vision analysis agent
│   ├── orchestrator-agent/   # Workflow coordination
│   ├── discovery-agent/      # Service discovery
│   └── agent-gateway/        # API gateway
├── config/                    # Configuration files
│   ├── .env.example          # Environment template
│   └── .env.*                # Service-specific configs
├── scripts/                   # Utility scripts
│   ├── service_tracker.py    # Service monitoring
│   └── service_client.py     # Client SDK
├── docs/                      # Documentation
│   ├── SERVICES.md           # Service details
│   ├── API_ENDPOINTS.md      # API reference
│   └── TROUBLESHOOTING.md    # Common issues
├── services.json             # Service registry
├── coolify-manifest.yaml     # Coolify deployment
├── docker-compose.local.yml  # Local development
└── DEPLOYMENT.md             # Deployment guide
```

### Adding New Services

1. Create service directory in `services/`
2. Add Dockerfile, requirements.txt, app.py
3. Update `services.json` with service info
4. Update `coolify-manifest.yaml` and `docker-compose.local.yml`
5. Document in `docs/SERVICES.md`

### Local Development

```bash
# Start specific services
docker-compose -f docker-compose.local.yml up -d postgres html-parser

# View logs
docker-compose -f docker-compose.local.yml logs -f extraction-agent

# Restart service
docker-compose -f docker-compose.local.yml restart vision-agent

# Rebuild after changes
docker-compose -f docker-compose.local.yml build --no-cache extraction-agent
```

---

## Monitoring

### Service Health Tracking

```bash
# Check all services
python scripts/service_tracker.py

# Detailed report
python scripts/service_tracker.py --detailed

# Continuous monitoring
python scripts/service_tracker.py --watch --interval 10

# Export status
python scripts/service_tracker.py --export status.json
```

### Service Status API

```bash
# Get all service statuses
curl http://localhost:8000/api/services/status

# List all services
curl http://localhost:8000/api/services
```

### Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f extraction-agent

# Last 100 lines
docker-compose logs --tail=100
```

---

## Troubleshooting

### Common Issues

**Service won't start**:
```bash
# Check logs
docker logs <container-name>

# Restart
docker-compose restart <service-name>
```

**Connection refused**:
```bash
# Verify service is running
docker ps | grep <service>

# Check health
curl http://localhost:<port>/health
```

**Out of memory**:
```bash
# Check usage
docker stats

# Increase limits in docker-compose.yml
```

**Complete Troubleshooting Guide**: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)

---

## Performance

### Resource Requirements

**Minimum**:
- 4 CPU cores
- 8GB RAM
- 50GB disk space

**Recommended**:
- 8+ CPU cores
- 16GB+ RAM (for vision models)
- 100GB+ SSD
- GPU (for faster LLM inference)

### Optimization Tips

1. **Use GPU for Ollama**: 10x faster inference
2. **Scale agents horizontally**: Run multiple extraction agent replicas
3. **Add caching**: Cache extracted data and LLM responses
4. **Optimize database**: Add indexes, vacuum regularly
5. **Limit concurrent requests**: Queue requests to prevent overload

---

## Security

### Best Practices

- [ ] Change default passwords in `.env`
- [ ] Use HTTPS for production (Coolify handles this)
- [ ] Limit database access to internal network
- [ ] Enable firewall rules
- [ ] Regular security updates
- [ ] Monitor logs for suspicious activity

### Production Checklist

- [ ] Environment variables configured
- [ ] Database backed up regularly
- [ ] SSL certificates active
- [ ] Monitoring enabled
- [ ] Logs rotated
- [ ] Resource limits set
- [ ] Health checks configured

---

## Documentation

- **[DEPLOYMENT.md](DEPLOYMENT.md)**: Complete deployment guide
- **[docs/SERVICES.md](docs/SERVICES.md)**: Service details and architecture
- **[docs/API_ENDPOINTS.md](docs/API_ENDPOINTS.md)**: API reference
- **[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)**: Common issues and solutions

---

## Tech Stack

**Frontend/Gateway**:
- Flask (Python web framework)
- Flask-CORS (Cross-origin support)

**Agents**:
- Python 3.11
- Requests (HTTP client)
- BeautifulSoup4 (HTML parsing)

**Data Storage**:
- PostgreSQL 16
- pgvector (Vector embeddings)

**AI/ML**:
- Ollama (Local LLM inference)
- Mistral, Llava models

**Orchestration**:
- Docker & Docker Compose
- Coolify (Deployment platform)
- n8n (Workflow automation)

**Search & Scraping**:
- SearxNG (Meta-search engine)
- Camoufox (Browser automation)

---

## Roadmap

- [ ] Authentication and API keys
- [ ] Rate limiting
- [ ] Advanced caching layer (Redis)
- [ ] Batch processing
- [ ] Streaming responses
- [ ] WebSocket support
- [ ] Grafana dashboards
- [ ] Automated backups
- [ ] Multi-region deployment
- [ ] Frontend UI dashboard

---

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Support

### Need Help?

1. Check [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
2. Review service logs: `docker-compose logs`
3. Run diagnostics: `python scripts/service_tracker.py --detailed`
4. Check health endpoints: `curl http://localhost:8000/health`

### Resources

- **Documentation**: See `docs/` directory
- **Examples**: See `n8n-workflows/examples/`
- **Issues**: GitHub Issues
- **Discussions**: GitHub Discussions

---

## Acknowledgments

Built with:
- [Ollama](https://ollama.ai/) - Local LLM inference
- [pgvector](https://github.com/pgvector/pgvector) - Vector similarity search
- [SearxNG](https://github.com/searxng/searxng) - Privacy-respecting metasearch
- [n8n](https://n8n.io/) - Workflow automation
- [Camoufox](https://github.com/daijro/camoufox) - Stealth browser automation
- [Coolify](https://coolify.io/) - Self-hosted deployment platform

---

**Made with ❤️ for self-hosted data extraction and analysis**

---

## Quick Reference

```bash
# Start all services
docker-compose -f docker-compose.local.yml up -d

# Stop all services
docker-compose -f docker-compose.local.yml down

# Monitor services
python scripts/service_tracker.py --watch

# Test gateway
curl http://localhost:8000/health

# Extract data
python scripts/service_client.py --extract "https://example.com"

# View logs
docker-compose logs -f

# Rebuild service
docker-compose build --no-cache <service-name>
```
