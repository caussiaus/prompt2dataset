# prompt2dataset

Production-ready self-hosted service orchestration for web data extraction and processing. Built for deployment on Coolify.

## Overview

prompt2dataset is a modular, microservices-based system that orchestrates web scraping, data extraction, vision analysis, and workflow automation. All services are containerized and managed through a single repository with centralized configuration.

### Key Features

- **Multi-Agent Architecture**: Specialized agents for extraction, vision, discovery, and orchestration
- **LLM-Powered Extraction**: Uses Ollama for intelligent data extraction
- **Vision Analysis**: Image analysis using vision models
- **Search Integration**: SearXNG for privacy-focused web search
- **Workflow Automation**: n8n for complex workflow orchestration
- **PostgreSQL + pgvector**: Vector database for semantic search
- **Single-Repo Management**: All services in one place with centralized config
- **Coolify-Ready**: Deploy entire stack with one manifest

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.11+
- 50GB+ disk space (for LLM models)
- 8GB+ RAM recommended

### Local Development

1. **Clone and setup:**
```bash
git clone https://github.com/yourusername/prompt2dataset.git
cd prompt2dataset
bash scripts/setup.sh
```

2. **Start services:**
```bash
docker-compose -f docker-compose.local.yml up -d
```

3. **Check health:**
```bash
python3 scripts/service_tracker.py
# Or: bash scripts/health-check.sh
```

4. **Test the system:**
```bash
python3 scripts/service_client.py --test
```

### Production Deployment (Coolify)

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for detailed deployment instructions.

Quick summary:
1. Push repo to GitHub
2. Connect repo to Coolify
3. Import `coolify-manifest.yaml`
4. Deploy services in order
5. Monitor with service tracker

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Agent Gateway (8000)                    │
│                   (Central API Gateway)                      │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
┌───────▼────────┐   ┌───────▼────────┐   ┌───────▼────────┐
│  Extraction    │   │  Vision        │   │  Discovery     │
│  Agent (8001)  │   │  Agent (8002)  │   │  Agent (8004)  │
└───────┬────────┘   └───────┬────────┘   └───────┬────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │  Orchestrator      │
                    │  Agent (8003)      │
                    └─────────┬──────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
┌───────▼────────┐   ┌───────▼────────┐   ┌───────▼────────┐
│  PostgreSQL    │   │  Ollama        │   │  SearXNG       │
│  + pgvector    │   │  (LLM)         │   │  (Search)      │
└────────────────┘   └────────────────┘   └────────────────┘
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| **Agent Gateway** | 8000 | Central API gateway |
| **Extraction Agent** | 8001 | Data extraction from web pages |
| **Vision Agent** | 8002 | Image analysis |
| **Orchestrator Agent** | 8003 | Workflow coordination |
| **Discovery Agent** | 8004 | URL discovery & service monitoring |
| **HTML Parser** | 5000 | HTML parsing utility |
| **PostgreSQL** | 5432 | Database with pgvector |
| **Ollama** | 11434 | Local LLM server |
| **Camoufox** | 3000 | Browser automation |
| **SearXNG** | 8888 | Privacy-focused search |
| **n8n** | 5678 | Workflow automation |

See **[SERVICES.md](docs/SERVICES.md)** for detailed service descriptions.

## API Endpoints

### Discovery Agent
- `POST /discover` - Discover URLs using search
- `GET /services` - List all services health status
- `POST /batch-discover` - Batch URL discovery

### Extraction Agent
- `POST /extract` - Extract structured data from URL/HTML
- `POST /batch-extract` - Batch extraction

### Vision Agent
- `POST /analyze-image` - Analyze image content
- `POST /batch-analyze` - Batch image analysis

### Orchestrator Agent
- `POST /orchestrate` - Execute multi-step workflows
- `GET /workflows` - List stored workflows

See **[API_ENDPOINTS.md](docs/API_ENDPOINTS.md)** for complete API documentation.

## Configuration

### Environment Variables

Copy `config/.env.example` to `.env` and update:

```bash
# Critical settings
DB_PASSWORD=your_secure_password
DOMAIN=yourdomain.com

# Service URLs (auto-configured for Docker network)
OLLAMA_URL=http://ollama:11434
SEARXNG_URL=http://searxng:8888
```

### Service Registry

`services.json` is the source of truth for all services. It defines:
- Service metadata
- Health check endpoints
- Environment variables
- Deployment order

## Usage Examples

### Python SDK

```python
from scripts.service_client import ServiceClient

client = ServiceClient('http://localhost:8000')

# Discover URLs
results = client.discover_urls(
    query="python web scraping",
    max_results=10
)

# Extract data
data = client.extract_data(
    url="https://example.com",
    schema={
        "title": "string",
        "price": "number",
        "description": "string"
    }
)

# Analyze image
analysis = client.analyze_image(
    image_url="https://example.com/image.jpg",
    prompt="Describe this product image"
)

# Execute workflow
workflow = client.orchestrate_workflow(
    workflow_name="Extract Product Data",
    steps=[
        {
            "name": "discover",
            "type": "discover",
            "data": {"query": "laptops", "max_results": 5}
        },
        {
            "name": "extract",
            "type": "extract",
            "data": {"schema": {"title": "string", "price": "number"}},
            "depends_on": "discover"
        }
    ]
)
```

### cURL Examples

```bash
# Health check
curl http://localhost:8000/health

# Discover URLs
curl -X POST http://localhost:8004/discover \
  -H "Content-Type: application/json" \
  -d '{"query": "python tutorials", "max_results": 5}'

# Extract data
curl -X POST http://localhost:8001/extract \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "schema": {
      "title": "string",
      "price": "number"
    }
  }'
```

## Monitoring

### Service Tracker

Monitor all services in real-time:

```bash
# Check once
python3 scripts/service_tracker.py

# Continuous monitoring
python3 scripts/service_tracker.py --watch

# JSON output
python3 scripts/service_tracker.py --json
```

### Health Check Script

Quick health check:

```bash
bash scripts/health-check.sh
```

## Development

### Adding a New Service

1. Add service to `services.json`
2. Create service directory in `services/`
3. Add Dockerfile and application code
4. Update `coolify-manifest.yaml`
5. Update documentation

### Testing Locally

```bash
# Start all services
docker-compose -f docker-compose.local.yml up -d

# View logs
docker-compose -f docker-compose.local.yml logs -f [service-name]

# Stop services
docker-compose -f docker-compose.local.yml down
```

## Troubleshooting

See **[TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** for common issues and solutions.

## Project Structure

```
prompt2dataset/
├── services.json              # Service registry (source of truth)
├── coolify-manifest.yaml      # Coolify deployment manifest
├── docker-compose.local.yml   # Local development compose
├── .gitignore                 # Git ignore rules
│
├── config/
│   └── .env.example           # Environment template
│
├── services/
│   ├── html-parser/           # HTML parsing service
│   ├── extraction-agent/      # Data extraction agent
│   ├── vision-agent/          # Vision analysis agent
│   ├── orchestrator-agent/    # Workflow orchestrator
│   └── discovery-agent/       # URL discovery & monitoring
│
├── scripts/
│   ├── service_tracker.py     # Service monitoring tool
│   ├── service_client.py      # Python SDK
│   ├── setup.sh               # Setup script
│   └── health-check.sh        # Quick health check
│
└── docs/
    ├── DEPLOYMENT.md          # Deployment guide
    ├── SERVICES.md            # Service documentation
    ├── API_ENDPOINTS.md       # API reference
    └── TROUBLESHOOTING.md     # Troubleshooting guide
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test locally with `docker-compose.local.yml`
5. Submit a pull request

## License

See [LICENSE](LICENSE) for details.

## Support

- Issues: [GitHub Issues](https://github.com/yourusername/prompt2dataset/issues)
- Documentation: [docs/](docs/)
- Discussions: [GitHub Discussions](https://github.com/yourusername/prompt2dataset/discussions)

---

**Built for self-hosting. Deploy anywhere. Own your data.**
