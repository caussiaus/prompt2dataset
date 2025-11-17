# Services Documentation

Complete reference for all services in the prompt2dataset stack.

## Table of Contents

- [Agent Services](#agent-services)
- [Utility Services](#utility-services)
- [Infrastructure Services](#infrastructure-services)
- [Service Dependencies](#service-dependencies)

---

## Agent Services

### Agent Gateway

**Port**: 8000  
**Type**: Gateway  
**Repository**: `/agent-gateway`

Central API gateway that routes requests to specialized agents.

**Features**:
- Request routing
- Load balancing
- API versioning
- Authentication (optional)
- Request logging

**Health Check**:
```bash
curl http://localhost:8000/health
```

**Dependencies**:
- All agent services
- Services registry (services.json)

---

### Extraction Agent

**Port**: 8001  
**Type**: Agent  
**Repository**: `/services/extraction-agent`

Extracts structured data from web pages using LLM-powered analysis.

**Features**:
- HTML-to-structured-data conversion
- Schema-based extraction
- LLM-powered entity recognition
- Batch processing
- Database storage

**Key Endpoints**:
- `POST /extract` - Extract data from single URL
- `POST /batch-extract` - Process multiple URLs
- `GET /health` - Health check

**Dependencies**:
- PostgreSQL (data storage)
- HTML Parser (content parsing)
- Ollama (LLM inference)

**Example Usage**:
```python
import requests

response = requests.post('http://localhost:8001/extract', json={
    'url': 'https://example.com/product',
    'schema': {
        'title': 'string',
        'price': 'number',
        'description': 'string',
        'features': 'array'
    },
    'store': True
})

data = response.json()
```

---

### Vision Agent

**Port**: 8002  
**Type**: Agent  
**Repository**: `/services/vision-agent`

Analyzes images and visual content using vision models.

**Features**:
- Image description generation
- Object detection
- OCR (text extraction from images)
- Image classification
- Batch processing

**Key Endpoints**:
- `POST /analyze-image` - Analyze single image
- `POST /batch-analyze` - Process multiple images
- `GET /health` - Health check

**Dependencies**:
- PostgreSQL (analysis storage)
- Ollama with LLaVA model (vision inference)

**Example Usage**:
```python
import requests

response = requests.post('http://localhost:8002/analyze-image', json={
    'image_url': 'https://example.com/product.jpg',
    'prompt': 'Describe this product in detail, including colors, materials, and features',
    'store': True
})

analysis = response.json()
```

**Supported Models**:
- LLaVA (default)
- BakLLaVA
- Other vision-capable models via Ollama

---

### Orchestrator Agent

**Port**: 8003  
**Type**: Agent  
**Repository**: `/services/orchestrator-agent`

Coordinates complex multi-step workflows across different agents.

**Features**:
- Sequential workflow execution
- Parallel step execution
- Dependency management
- Error handling and retries
- Workflow templates
- Result aggregation

**Key Endpoints**:
- `POST /orchestrate` - Execute workflow
- `GET /workflows` - List stored workflows
- `GET /health` - Health check

**Dependencies**:
- PostgreSQL (workflow storage)
- Extraction Agent
- Vision Agent
- Discovery Agent

**Example Workflow**:
```python
import requests

workflow = {
    'workflow_name': 'Product Data Pipeline',
    'steps': [
        {
            'name': 'discover_products',
            'type': 'discover',
            'data': {
                'query': 'gaming laptops 2024',
                'max_results': 10
            }
        },
        {
            'name': 'extract_details',
            'type': 'extract',
            'data': {
                'schema': {
                    'name': 'string',
                    'price': 'number',
                    'specs': 'object'
                }
            },
            'depends_on': 'discover_products'
        },
        {
            'name': 'analyze_images',
            'type': 'analyze_image',
            'data': {
                'prompt': 'Describe product appearance'
            },
            'depends_on': 'extract_details'
        }
    ],
    'parallel': False,
    'store': True
}

response = requests.post('http://localhost:8003/orchestrate', json=workflow)
results = response.json()
```

---

### Discovery Agent

**Port**: 8004  
**Type**: Agent  
**Repository**: `/services/discovery-agent`

Discovers URLs and monitors service health.

**Features**:
- Web search via SearXNG
- URL discovery
- Service health monitoring
- Domain filtering
- Batch discovery

**Key Endpoints**:
- `POST /discover` - Discover URLs
- `GET /services` - List all services status
- `GET /service/<id>` - Get service details
- `POST /batch-discover` - Batch URL discovery
- `GET /health` - Health check

**Dependencies**:
- PostgreSQL (discovery storage)
- SearXNG (search engine)
- Services.json (service registry)

**Example Usage**:
```python
import requests

# Discover URLs
response = requests.post('http://localhost:8004/discover', json={
    'query': 'python tutorials 2024',
    'max_results': 20,
    'categories': ['general', 'it'],
    'filter_domains': ['python.org', 'realpython.com'],
    'store': True
})

urls = response.json()

# Check service health
health = requests.get('http://localhost:8004/services')
print(health.json())
```

---

## Utility Services

### HTML Parser

**Port**: 5000  
**Type**: Utility  
**Repository**: `/services/html-parser`

Parses HTML content and extracts structured data.

**Features**:
- HTML parsing (BeautifulSoup + lxml)
- Text extraction
- Link extraction
- Image extraction
- Metadata extraction
- Table extraction
- Database storage

**Key Endpoints**:
- `POST /parse` - Parse HTML
- `POST /extract-text` - Extract clean text
- `GET /health` - Health check

**Dependencies**:
- PostgreSQL (optional, for storage)

**Example Usage**:
```python
import requests

response = requests.post('http://localhost:5000/parse', json={
    'html': '<html><body><h1>Title</h1><p>Content</p></body></html>',
    'options': {
        'extract_links': True,
        'extract_images': True,
        'extract_tables': False
    }
})

parsed = response.json()
```

---

### Camoufox

**Port**: 3000  
**Type**: Browser Automation  
**Image**: `camoufox/camoufox:latest`

Headless browser for JavaScript-heavy sites.

**Features**:
- Headless browsing
- JavaScript execution
- Screenshot capture
- Cookie management
- Proxy support

**Use Cases**:
- Single-page applications (SPAs)
- Dynamic content loading
- Sites requiring JavaScript

---

## Infrastructure Services

### PostgreSQL + pgvector

**Port**: 5432  
**Type**: Database  
**Image**: `pgvector/pgvector:pg16`

Primary database with vector search capabilities.

**Features**:
- Relational data storage
- Vector embeddings (pgvector)
- JSONB support
- Full-text search
- Transactional integrity

**Managed Tables**:
- `parsed_html` - HTML Parser results
- `extractions` - Extraction Agent results
- `vision_analyses` - Vision Agent results
- `workflows` - Orchestrator workflows
- `discoveries` - Discovery Agent results

**Configuration**:
```sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Example vector search
SELECT * FROM embeddings
ORDER BY embedding <-> '[0.1, 0.2, 0.3]'::vector
LIMIT 10;
```

---

### Ollama

**Port**: 11434  
**Type**: LLM Server  
**Image**: `ollama/ollama:latest`

Local LLM inference server.

**Features**:
- Multiple model support
- GPU acceleration (optional)
- Model management
- Streaming responses
- Context management

**Required Models**:
- `mistral:latest` - Text generation
- `llava:latest` - Vision analysis
- `neural-chat:latest` - Conversational AI (optional)

**Model Management**:
```bash
# Download model
docker exec <ollama-container> ollama pull mistral:latest

# List models
docker exec <ollama-container> ollama list

# Remove model
docker exec <ollama-container> ollama rm mistral:latest
```

**API Usage**:
```bash
curl http://localhost:11434/api/generate -d '{
  "model": "mistral:latest",
  "prompt": "Explain web scraping",
  "stream": false
}'
```

---

### SearXNG

**Port**: 8888  
**Type**: Search Engine  
**Image**: `searxng/searxng:latest`

Privacy-focused metasearch engine.

**Features**:
- Multi-engine search aggregation
- No tracking
- JSON API
- Category filtering
- Result ranking

**API Usage**:
```bash
curl "http://localhost:8888/search?q=python&format=json"
```

---

### n8n

**Port**: 5678  
**Type**: Workflow Automation  
**Image**: `n8nio/n8n:latest`

Visual workflow automation platform.

**Features**:
- Visual workflow builder
- 300+ integrations
- Webhook support
- Scheduling
- Error workflows
- Version control

**Use Cases**:
- Automate data pipelines
- Scheduled scraping
- Data transformation
- API orchestration
- Alert notifications

**Example Workflow**:
1. Trigger: Webhook or schedule
2. Discovery Agent: Find URLs
3. Extraction Agent: Extract data
4. Transform: Clean data
5. Store: Save to database
6. Notify: Send completion email

---

## Service Dependencies

### Dependency Graph

```
PostgreSQL (foundational)
    ├── HTML Parser
    ├── Extraction Agent
    ├── Vision Agent
    ├── Orchestrator Agent
    └── Discovery Agent

Ollama (foundational)
    ├── Extraction Agent
    └── Vision Agent

SearXNG (foundational)
    └── Discovery Agent

HTML Parser
    └── Extraction Agent

All Agents
    └── Agent Gateway

Discovery Agent, Extraction Agent, Vision Agent
    └── Orchestrator Agent
```

### Deployment Order

1. **Foundation Layer**: PostgreSQL, Ollama
2. **Search Layer**: SearXNG
3. **Utility Layer**: Camoufox, HTML Parser
4. **Orchestration**: n8n
5. **Agent Layer**: Extraction, Vision, Discovery
6. **Coordination**: Orchestrator Agent
7. **Gateway**: Agent Gateway

---

## Resource Requirements

| Service | CPU | Memory | Storage |
|---------|-----|--------|---------|
| PostgreSQL | 1-2 cores | 2-4GB | 10GB+ |
| Ollama | 2-4 cores | 4-8GB | 30GB+ (models) |
| Extraction Agent | 1 core | 1GB | - |
| Vision Agent | 1-2 cores | 2GB | - |
| Orchestrator | 1 core | 1GB | - |
| Discovery Agent | 1 core | 512MB | - |
| HTML Parser | 1 core | 512MB | - |
| SearXNG | 1 core | 512MB | - |
| n8n | 1 core | 1GB | 1GB |
| Camoufox | 1 core | 1GB | - |
| Agent Gateway | 1 core | 512MB | - |

**Total Recommended**: 8 cores, 16GB RAM, 50GB storage

---

## Service Communication

All services communicate via HTTP/REST APIs over Docker network `mvp-network`.

**Internal URLs** (within Docker):
- `http://postgres:5432`
- `http://ollama:11434`
- `http://searxng:8888`
- `http://extraction-agent:8001`
- `http://vision-agent:8002`
- `http://orchestrator-agent:8003`
- `http://discovery-agent:8004`

**External Access** (via Coolify domains):
- `https://api.yourdomain.com` → Agent Gateway
- `https://n8n.yourdomain.com` → n8n
- `https://search.yourdomain.com` → SearXNG

---

## Monitoring Services

### Health Check URLs

All services expose `/health` endpoints:

```bash
# Check all services
for port in 5000 8000 8001 8002 8003 8004; do
    echo "Port $port:"
    curl -s "http://localhost:$port/health" | jq .
done
```

### Logging

Services log to stdout. View logs:

```bash
# Docker Compose
docker-compose -f docker-compose.local.yml logs -f [service-name]

# Coolify
# View logs in Coolify dashboard
```

### Metrics

Basic metrics available via health endpoints:
- Service status
- Dependencies status
- Response times
- Error counts

For production monitoring, consider:
- Prometheus + Grafana
- DataDog
- New Relic
- Custom monitoring via service_tracker.py

---

## Development

### Adding a New Service

1. Create service directory in `services/`
2. Add Dockerfile and app code
3. Update `services.json`
4. Update `coolify-manifest.yaml`
5. Update `docker-compose.local.yml`
6. Add documentation

### Service Template

```python
#!/usr/bin/env python3
from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'healthy',
        'service': 'your-service',
        'version': '1.0.0'
    }), 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
```

---

**For more information, see:**
- [API Endpoints](API_ENDPOINTS.md)
- [Deployment Guide](../DEPLOYMENT.md)
- [Troubleshooting](TROUBLESHOOTING.md)
